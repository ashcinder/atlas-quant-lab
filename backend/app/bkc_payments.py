"""Native BKC transfers and public report anchors. No ZK/proof implementation."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
from pathlib import Path
from decimal import Decimal
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app.supervisor_client import SupervisorClient, SupervisorRPCError

CHAIN_ID = 1051

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

class OfferInput(BaseModel):
    recipient: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    amount_bkc: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,18})?$")

class PrepareInput(BaseModel):
    address: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")

class ConfirmInput(BaseModel):
    transaction_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")

class BroadcastInput(BaseModel):
    raw_transaction: str = Field(pattern=r"^0x[0-9a-fA-F]+$", max_length=140000)

class BkcStore:
    def __init__(self, runtime, runs, client=None):
        self.runtime, self.runs = runtime, runs
        self.client = client or SupervisorClient()
        with runtime._connect() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS bkc_offers (
                release_id TEXT PRIMARY KEY, recipient TEXT NOT NULL, amount_wei TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bkc_orders (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, kind TEXT NOT NULL,
                resource_id TEXT NOT NULL, signer TEXT NOT NULL, recipient TEXT NOT NULL,
                amount_wei TEXT NOT NULL, data TEXT NOT NULL, genesis TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', transaction_hash TEXT UNIQUE,
                block_number INTEGER, block_hash TEXT,
                UNIQUE(owner_id,kind,resource_id));
            ''')

            columns={r[1] for r in conn.execute('PRAGMA table_info(bkc_orders)')}
            if 'signed_raw' not in columns:conn.execute('ALTER TABLE bkc_orders ADD COLUMN signed_raw TEXT')

    def network(self):
        status = self.client.status()
        if not status.connected or status.chain_id != CHAIN_ID:
            raise HTTPException(503, 'Supervisor 未连接或链 ID 不匹配')
        try:
            genesis = self.client._call('eth_getBlockByNumber', ['0x0', False])
            if not genesis or not genesis.get('hash'):
                raise SupervisorRPCError('缺少创世区块')
        except SupervisorRPCError as exc:
            raise HTTPException(503, '无法确认 Supervisor 网络身份') from exc
        return status, genesis['hash'].lower()

    def config(self):
        status, genesis = self.network()
        return {'chain_id': CHAIN_ID, 'chain_name': os.getenv('TRINE_SUPERVISOR_NETWORK_LABEL','Trine Supervisor'), 'currency': 'BKC',
                'rpc_url': os.getenv('ATLAS_WALLET_RPC_URL', self.client.rpc_url),
                'genesis_hash': genesis, 'block_number': status.block_number}

    def release(self, owner, release_id, write=False):
        with self.runtime._connect() as conn:
            release = self.runtime._release_for(conn, release_id)
        if release['owner_id'] != owner and (write or not release['published']):
            raise HTTPException(404, '策略版本不存在')
        return release

    def offer(self, owner, release_id):
        self.release(owner, release_id)
        with self.runtime._connect() as conn:
            row = conn.execute('SELECT * FROM bkc_offers WHERE release_id=?', (release_id,)).fetchone()
        if not row:
            return None
        return {**dict(row), 'amount_bkc': format(Decimal(row['amount_wei']) / Decimal(10**18), 'f'), 'terms': '一次支付，授权当前版本；新版本另行订阅'}

    def set_offer(self, owner, release_id, value):
        self.release(owner, release_id, True)
        amount = int(Decimal(value.amount_bkc) * Decimal(10**18))
        if amount <= 0 or int(value.recipient, 16) == 0:
            raise HTTPException(422, '价格必须大于零，收款地址不能是零地址')
        with self.runtime._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT * FROM bkc_offers WHERE release_id=?', (release_id,)).fetchone()
            if existing:
                raise HTTPException(409, '此版本的价格已固定；更改价格请发布新版本')
            conn.execute('INSERT INTO bkc_offers VALUES (?,?,?)', (release_id, value.recipient.lower(), str(amount)))
        return self.offer(owner, release_id)

    def prepare(self, owner, kind, resource_id, address):
        address = address.lower()
        if kind == 'subscription':
            offer = self.offer(owner, resource_id)
            if not offer:
                raise HTTPException(409, '作者尚未设置 BKC 订阅价格')
            recipient, amount = offer['recipient'], offer['amount_wei']
            release = self.release(owner, resource_id)
            payload = {'domain': 'atlas.bkc-subscription/v1', 'release_id': resource_id,
                       'content_hash': release['content_hash'], 'terms': 'version-access'}
        elif kind == 'proof_anchor':
            from app.zkp import ZkProofStore
            with self.runtime._connect() as conn:
                job = conn.execute("SELECT release_id FROM cloud_proof_jobs WHERE proof_id=? AND status='verified'", (resource_id,)).fetchone()
            if not job:
                raise HTTPException(404, '没有可存证的已验证 Proof')
            release = self.release(owner, job['release_id'])
            proofs = ZkProofStore()
            proofs.reverify(resource_id)
            proof = proofs.get(resource_id)
            payload = {'domain': 'trine.verified-proof-anchor/v1', 'release_id': job['release_id'],
                       'content_hash': release['content_hash'], 'proof_id': resource_id,
                       'proof_hash': proof['proof_hash'], 'image_id': proof['image_id'],
                       'public_inputs_hash': proof['public_inputs_hash'],
                       'public_statement': proof['public_statement'],
                       'claim': 'server-verified-proof-and-public-results-anchored-not-contract-verified'}
            recipient, amount = address, '0'
        elif kind == 'release':
            release = self.release(owner, resource_id, True)
            payload = {'domain': 'trine.strategy-release/v1', 'release_id': resource_id,
                       'content_hash': release['content_hash'], 'claim': 'version-anchored-only'}
            recipient, amount = address, '0'
        else:
            with self.runs._connect() as conn:
                row = conn.execute('SELECT * FROM backtest_runs WHERE id=? AND owner_id=?', (resource_id, owner)).fetchone()
            if not row:
                raise HTTPException(404, '回测记录不存在，请先保存回测')
            result, request = json.loads(row['result_json']), json.loads(row['request_json'])
            safe_keys = ['symbol', 'asset_class', 'interval', 'start', 'end', 'data_source', 'initial_capital', 'commission_rate', 'slippage_rate', 'spread_rate', 'max_position', 'max_participation_rate', 'stop_loss', 'take_profit', 'adjustment', 'base_currency']
            payload = {'domain': 'atlas.backtest-report/v1', 'run_id': resource_id,
                       'strategy_id': row['strategy_id'], 'request_hash': digest(request),
                       'report_hash': digest(result), 'config': {k: request[k] for k in safe_keys if k in request},
                       'metrics': result['metrics'], 'source': result.get('data_source'),
                       'created_at': row['created_at'], 'claim': 'report-anchored-only'}
            recipient, amount = address, '0'
        _, genesis = self.network()
        with self.runtime._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM bkc_orders WHERE owner_id=? AND kind=? AND resource_id=?', (owner, kind, resource_id)).fetchone()
            if row:
                return self.order_result(dict(row))
            identifier = 'bkc_' + uuid4().hex
            payload.update(order_id=identifier, chain_id=CHAIN_ID, genesis_hash=genesis)
            data = '0x' + canonical(payload).encode().hex()
            conn.execute('INSERT INTO bkc_orders (id,owner_id,kind,resource_id,signer,recipient,amount_wei,data,genesis) VALUES (?,?,?,?,?,?,?,?,?)', (identifier, owner, kind, resource_id, address, recipient, amount, data, genesis))
        return self.get(owner, identifier)

    def signing(self, owner, identifier):
        order = self.get(owner, identifier)
        _, genesis = self.network()
        if genesis != order['genesis']:
            raise HTTPException(409, '网络身份发生变化')
        if order['transaction_hash']:
            raise HTTPException(409, '订单已广播，请核验原交易')
        tx = order['transaction']
        try:
            nonce = self.client._call('eth_getTransactionCount', [order['signer'], 'pending'])
            price = self.client._call('eth_gasPrice', [])
            gas = self.client._call('eth_estimateGas', [{k:v for k,v in tx.items() if k != 'chainId'}])
            balance = self.client._call('eth_getBalance', [order['signer'], 'latest'])
            # Supervisor's legacy estimator can omit calldata. Respect its
            # pre-Istanbul intrinsic cost (68/nonzero byte) as a lower bound.
            calldata = bytes.fromhex(tx['data'][2:])
            intrinsic = 21000 + sum(4 if byte == 0 else 68 for byte in calldata)
            limit = (max(int(gas,16), intrinsic)*12+9)//10
            if int(balance,16) < int(order['amount_wei'])+limit*int(price,16):
                raise HTTPException(402, 'BKC 余额不足（含交易手续费）')
            return {'transaction': {**tx,'nonce':nonce,'gasPrice':price,'gasLimit':hex(limit)}, 'balance_wei':str(int(balance,16))}
        except (SupervisorRPCError,ValueError) as exc:
            raise HTTPException(503, '无法从 Supervisor 获取余额或交易费用') from exc

    def broadcast(self, owner, identifier, raw):
        order = self.get(owner, identifier)
        _, genesis = self.network()
        if genesis != order['genesis']:
            raise HTTPException(409, '网络身份发生变化')
        script = Path(__file__).resolve().parents[2]/'contracts/scripts/decode-transaction.mjs'
        try:
            result = subprocess.run(['node',str(script)], input=json.dumps({'raw_transaction':raw}), capture_output=True,text=True,timeout=10)
            if result.returncode: raise ValueError()
            tx = json.loads(result.stdout)
            if not (tx['from'].lower()==order['signer'] and (tx['to'] or '').lower()==order['recipient']
                    and tx['value']==order['amount_wei'] and tx['data'].lower()==order['data']
                    and tx['chainId']==str(CHAIN_ID) and tx['type']==0): raise ValueError()
        except (ValueError,KeyError,OSError,subprocess.TimeoutExpired) as exc:
            raise HTTPException(422, '签名交易与订单不匹配') from exc
        # Persist the exact signed transaction identity before touching the network.
        # A lost HTTP response cannot cause a second payment with a new nonce.
        with self.runtime._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            latest=conn.execute('SELECT transaction_hash FROM bkc_orders WHERE id=?',(identifier,)).fetchone()
            if latest['transaction_hash'] and latest['transaction_hash']!=tx['hash']:
                raise HTTPException(409,'订单已有交易，请恢复核验')
            conn.execute("UPDATE bkc_orders SET transaction_hash=?,signed_raw=?,status='submitted' WHERE id=?",(tx['hash'],raw,identifier))
        try:
            if not self.client.transaction(tx['hash']):
                returned=self.client.submit_signed_transaction(raw)
                if returned.lower()!=tx['hash'].lower(): raise SupervisorRPCError('交易哈希不一致')
        except SupervisorRPCError:
            # Return the persisted hash even on an uncertain broadcast; never clear it.
            return {'transaction_hash':tx['hash'],'status':'submitted','message':'广播结果待核验，请保留原交易哈希'}
        return {'transaction_hash':tx['hash'],'status':'submitted'}

    @staticmethod
    def order_result(row):
        public = {k: v for k, v in row.items() if k not in {'owner_id','signed_raw'}}
        public['transaction'] = {'from': row['signer'], 'to': row['recipient'], 'value': hex(int(row['amount_wei'])), 'data': row['data'], 'chainId': hex(CHAIN_ID)}
        public['payload'] = json.loads(bytes.fromhex(row['data'][2:]))
        return public

    def get(self, owner, identifier):
        with self.runtime._connect() as conn:
            row = conn.execute('SELECT * FROM bkc_orders WHERE id=? AND owner_id=?', (identifier, owner)).fetchone()
        if not row:
            raise HTTPException(404, '订单不存在')
        return self.order_result(dict(row))

    def confirm(self, owner, identifier, tx_hash):
        order = self.get(owner, identifier)
        tx_hash = tx_hash.lower()
        if order['transaction_hash'] not in (None, tx_hash):
            raise HTTPException(409, '请核验原交易，避免重复付款')
        try:
            status, genesis = self.network()
            if genesis != order['genesis']:
                raise HTTPException(409, 'Supervisor 网络已变化，不能核验原订单')
            tx, receipt = self.client.transaction(tx_hash), self.client.transaction_receipt(tx_hash)
            state, block, block_hash = 'submitted', None, None
            if tx:
                if not (str(tx.get('hash', '')).lower() == tx_hash and str(tx.get('from', '')).lower() == order['signer']
                        and str(tx.get('to', '')).lower() == order['recipient']
                        and str(tx.get('input', '')).lower() == order['data']
                        and int(tx.get('value', '-1'), 16) == int(order['amount_wei'])):
                    raise HTTPException(422, '交易的钱包、收款人、金额或订单内容不匹配')
            if receipt:
                if not tx or str(receipt.get('transactionHash', '')).lower() != tx_hash:
                    raise HTTPException(422, '回执缺少匹配交易')
                if receipt.get('status') == '0x0':
                    state = 'failed'
                elif receipt.get('status') == '0x1':
                    block, block_hash = int(receipt['blockNumber'], 16), receipt['blockHash']
                    canonical_block = self.client._call('eth_getBlockByNumber', [hex(block), False])
                    if (not canonical_block or canonical_block.get('hash') != block_hash or tx.get('blockHash') != block_hash
                            or int(tx.get('blockNumber', '-1'), 16) != block or status.block_number < block):
                        raise HTTPException(409, '交易尚未被当前规范链确认')
                    state = 'confirmed'
        except (SupervisorRPCError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, '链上核验暂不可用，请保留交易哈希后重试') from exc
        with self.runtime._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            latest = conn.execute('SELECT transaction_hash FROM bkc_orders WHERE id=?', (identifier,)).fetchone()
            if latest['transaction_hash'] not in (None, tx_hash):
                raise HTTPException(409, '订单已关联另一笔交易')
            duplicate = conn.execute('SELECT id FROM bkc_orders WHERE transaction_hash=? AND id<>?', (tx_hash, identifier)).fetchone()
            if duplicate:
                raise HTTPException(409, '交易已用于其他订单')
            conn.execute('UPDATE bkc_orders SET transaction_hash=?,status=?,block_number=?,block_hash=? WHERE id=?', (tx_hash, state, block, block_hash, identifier))
        result = self.get(owner, identifier)
        if state == 'confirmed' and order['kind'] == 'subscription':
            result['subscription'] = self.runtime.subscribe(owner, order['resource_id'])
        return result


def bkc_router(runtime, runs):
    store = BkcStore(runtime, runs)
    router = APIRouter(prefix='/api/v1')

    @router.get('/wallet/network')
    def network():
        return store.config()

    @router.get('/wallet/balance')
    def balance(address: str):
        import re
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}',address): raise HTTPException(422,'账户地址无效')
        store.network()
        try:
            amount=int(store.client._call('eth_getBalance',[address,'latest']),16)
            return {'address':address,'balance_wei':str(amount),'balance_bkc':format(Decimal(amount)/Decimal(10**18),'f'),'currency':'BKC','network_label':os.getenv('TRINE_SUPERVISOR_NETWORK_LABEL','Supervisor')}
        except (SupervisorRPCError,ValueError) as exc:
            raise HTTPException(503,'余额查询失败') from exc

    @router.get('/bkc-orders/{identifier}/signing')
    def signing(identifier: str, request: Request):
        return store.signing(request.state.user.id,identifier)

    @router.post('/bkc-orders/{identifier}/broadcast')
    def broadcast(identifier: str, value: BroadcastInput, request: Request):
        return store.broadcast(request.state.user.id,identifier,value.raw_transaction)

    @router.post('/bkc-orders/{identifier}/rebroadcast')
    def rebroadcast(identifier: str, request: Request):
        store.get(request.state.user.id,identifier)
        with runtime._connect() as c: row=c.execute('SELECT signed_raw FROM bkc_orders WHERE id=?',(identifier,)).fetchone()
        if not row['signed_raw']:raise HTTPException(409,'没有可恢复的签名交易')
        return store.broadcast(request.state.user.id,identifier,row['signed_raw'])

    @router.get('/strategy-releases/{release_id}/bkc-offer')
    def offer(release_id: str, request: Request):
        return store.offer(request.state.user.id, release_id)

    @router.put('/strategy-releases/{release_id}/bkc-offer')
    def set_offer(release_id: str, value: OfferInput, request: Request):
        return store.set_offer(request.state.user.id, release_id, value)

    @router.post('/strategy-releases/{release_id}/bkc-order')
    def prepare_subscription(release_id: str, value: PrepareInput, request: Request):
        return store.prepare(request.state.user.id, 'subscription', release_id, value.address)

    @router.post('/strategy-releases/{release_id}/anchor-order')
    def prepare_release(release_id: str, value: PrepareInput, request: Request):
        return store.prepare(request.state.user.id, 'release', release_id, value.address)

    @router.post('/strategy-releases/{release_id}/proof-anchor-order')
    def prepare_proof_anchor(release_id: str, value: PrepareInput, request: Request):
        store.release(request.state.user.id, release_id)
        with runtime._connect() as conn:
            job = conn.execute("SELECT proof_id FROM cloud_proof_jobs WHERE release_id=? AND status='verified' ORDER BY created_at DESC LIMIT 1", (release_id,)).fetchone()
        if not job:
            raise HTTPException(409, '请先完成 Proof 生成与验证')
        return store.prepare(request.state.user.id, 'proof_anchor', job['proof_id'], value.address)

    @router.get('/strategy-releases/{release_id}/anchors')
    def release_anchors(release_id: str, request: Request):
        store.release(request.state.user.id, release_id)
        with runtime._connect() as conn:
            rows = conn.execute("SELECT * FROM bkc_orders WHERE status='confirmed' AND (kind='release' AND resource_id=? OR kind='proof_anchor' AND resource_id IN (SELECT proof_id FROM cloud_proof_jobs WHERE release_id=? AND status='verified'))", (release_id, release_id)).fetchall()
        return [{'kind': row['kind'], 'transaction_hash': row['transaction_hash'],
                 'block_number': row['block_number'], 'block_hash': row['block_hash'],
                 'genesis': row['genesis'], 'chain_id': CHAIN_ID,
                 'payload': json.loads(bytes.fromhex(row['data'][2:]).decode())} for row in rows]

    @router.post('/runs/{run_id}/anchor-order')
    def prepare_report(run_id: str, value: PrepareInput, request: Request):
        return store.prepare(request.state.user.id, 'report', run_id, value.address)

    @router.get('/bkc-orders/{identifier}')
    def get(identifier: str, request: Request):
        return store.get(request.state.user.id, identifier)

    @router.post('/bkc-orders/{identifier}/confirm')
    def confirm(identifier: str, value: ConfirmInput, request: Request):
        return store.confirm(request.state.user.id, identifier, value.transaction_hash)

    return router
