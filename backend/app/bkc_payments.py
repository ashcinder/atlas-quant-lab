"""Native BKC transfers and public report anchors. No ZK/proof implementation."""
from __future__ import annotations
import hashlib
import json
import os
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
        return {'chain_id': CHAIN_ID, 'chain_name': 'Atlas Supervisor', 'currency': 'BKC',
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
                raise HTTPException(409, '此版本为免费订阅')
            recipient, amount = offer['recipient'], offer['amount_wei']
            release = self.release(owner, resource_id)
            payload = {'domain': 'atlas.bkc-subscription/v1', 'release_id': resource_id,
                       'content_hash': release['content_hash'], 'terms': 'version-access'}
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

    @staticmethod
    def order_result(row):
        public = {k: v for k, v in row.items() if k != 'owner_id'}
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

    @router.get('/strategy-releases/{release_id}/bkc-offer')
    def offer(release_id: str, request: Request):
        return store.offer(request.state.user.id, release_id)

    @router.put('/strategy-releases/{release_id}/bkc-offer')
    def set_offer(release_id: str, value: OfferInput, request: Request):
        return store.set_offer(request.state.user.id, release_id, value)

    @router.post('/strategy-releases/{release_id}/bkc-order')
    def prepare_subscription(release_id: str, value: PrepareInput, request: Request):
        return store.prepare(request.state.user.id, 'subscription', release_id, value.address)

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
