from types import SimpleNamespace
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.bkc_payments import BkcStore, OfferInput
from app.storage import RunStore
from app.strategy_runtime import StrategyRuntimeStore, ReleaseCreate

ALICE = '0x' + 'a' * 40
BOB = '0x' + 'b' * 40
HASH = '0x' + '1' * 64
BLOCK = '0x' + '2' * 64
GENESIS = '0x' + '3' * 64

class Chain:
    rpc_url = 'http://127.0.0.1:42515'
    tx = None
    receipt = None
    genesis = GENESIS
    def status(self): return SimpleNamespace(connected=True, chain_id=1051, block_number=10)
    def _call(self, method, params): return {'hash': self.genesis if params[0] == '0x0' else BLOCK}
    def transaction(self, _): return self.tx
    def transaction_receipt(self, _): return self.receipt
    def mine(self, order):
        self.tx = {**order['transaction'], 'hash': HASH, 'input': order['transaction']['data'], 'blockHash': BLOCK, 'blockNumber': '0xa'}
        self.receipt = {'transactionHash': HASH, 'status': '0x1', 'blockNumber': '0xa', 'blockHash': BLOCK}

@pytest.fixture
def setup(tmp_path):
    runtime = StrategyRuntimeStore(SimpleNamespace(), tmp_path / 'runtime.db')
    runs = RunStore(tmp_path / 'runs.db')
    chain = Chain()
    store = BkcStore(runtime, runs, chain)
    release = runtime.create_release('alice', ReleaseCreate(name='SMA', source_kind='builtin', strategy_id='sma_cross', params={'fast': 5, 'slow': 20}, markets=['CRYPTO'], published=True))
    store.set_offer('alice', release['id'], OfferInput(recipient=ALICE, amount_bkc='0.010000000000000001'))
    return runtime, runs, chain, store, release['id']

def test_paid_release_cannot_use_free_subscription_endpoint(setup):
    runtime, _, _, store, release = setup
    with pytest.raises(HTTPException) as error: runtime.subscribe('bob', release)
    assert error.value.status_code == 402
    assert store.offer('bob', release)['amount_wei'] == '10000000000000001'
    with pytest.raises(HTTPException): store.set_offer('bob', release, OfferInput(recipient=BOB, amount_bkc='1'))
    with pytest.raises(HTTPException): store.set_offer('alice', release, OfferInput(recipient=ALICE, amount_bkc='2'))

def test_confirmed_exact_payment_activates_once_and_prepare_recovers(setup):
    runtime, _, chain, store, release = setup
    order = store.prepare('bob', 'subscription', release, BOB)
    assert store.prepare('bob', 'subscription', release, BOB)['id'] == order['id']
    chain.mine(order)
    result = store.confirm('bob', order['id'], HASH)
    assert result['status'] == 'confirmed'
    assert result['subscription']['status'] == 'active'
    again = store.confirm('bob', order['id'], HASH)
    assert again['subscription']['id'] == result['subscription']['id']
    assert len(runtime.list_subscriptions('bob')) == 1
    with pytest.raises(HTTPException): store.confirm('charlie', order['id'], HASH)

@pytest.mark.parametrize('field,value', [('value','0x1'),('to',BOB),('from',ALICE),('input','0x1234'),('hash','0x'+'9'*64)])
def test_tampered_payment_never_grants_access(setup, field, value):
    runtime, _, chain, store, release = setup
    order = store.prepare('bob', 'subscription', release, BOB)
    chain.mine(order); chain.tx[field] = value
    with pytest.raises(HTTPException): store.confirm('bob', order['id'], HASH)
    assert runtime.list_subscriptions('bob') == []

def test_pending_failed_and_wrong_chain_do_not_grant_access(setup):
    runtime, _, chain, store, release = setup
    order = store.prepare('bob', 'subscription', release, BOB)
    assert store.confirm('bob', order['id'], HASH)['status'] == 'submitted'
    assert runtime.list_subscriptions('bob') == []
    chain.mine(order); chain.receipt['status'] = '0x0'
    assert store.confirm('bob', order['id'], HASH)['status'] == 'failed'
    assert runtime.list_subscriptions('bob') == []
    chain.genesis = '0x'+'8'*64
    with pytest.raises(HTTPException): store.confirm('bob', order['id'], HASH)

def test_noncanonical_block_is_rejected(setup):
    runtime, _, chain, store, release = setup
    order = store.prepare('bob', 'subscription', release, BOB)
    chain.mine(order); chain.tx['blockHash'] = GENESIS
    with pytest.raises(HTTPException): store.confirm('bob', order['id'], HASH)
    assert runtime.list_subscriptions('bob') == []

def test_report_anchor_discloses_metrics_but_not_strategy_source(setup):
    _, runs, chain, store, _ = setup
    runs.save('bob', 'single', {'symbol':'BTC-USD', 'strategy_id':'python_bounded', 'python_source':'SECRET', 'params':{'secret':123}, 'initial_capital':100}, {'run_id':'r1', 'created_at':'2026-01-01', 'metrics':{'total_return':0.25}, 'equity':[], 'data_source':'fixture'})
    order = store.prepare('bob', 'report', 'r1', BOB)
    assert order['payload']['metrics']['total_return'] == 0.25
    assert order['payload']['claim'] == 'report-anchored-only'
    assert 'SECRET' not in str(order) and 'secret' not in str(order)
    assert order['transaction']['value'] == '0x0'
    chain.mine(order)
    assert store.confirm('bob', order['id'], HASH)['status'] == 'confirmed'
    with pytest.raises(HTTPException): store.prepare('alice', 'report', 'r1', ALICE)

def test_signed_transaction_relay_checks_exact_order_and_is_idempotent(setup):
    import json,subprocess
    from pathlib import Path
    runtime,_,chain,store,release=setup
    root=Path(__file__).resolve().parents[2]
    # Disposable key only for this test, never read a configured user's account.
    address=subprocess.run(['node','--input-type=module','-e',"import{Wallet}from'ethers';console.log(new Wallet('0x'+'11'.repeat(32)).address)"],cwd=root/'contracts',capture_output=True,text=True,check=True).stdout.strip()
    order=store.prepare('buyer','subscription',release,address)
    tx={**order['transaction'],'nonce':0,'gasLimit':'0x30d40','gasPrice':'0x1','type':0}
    script="import{Wallet}from'ethers';let s='';for await(const c of process.stdin)s+=c;console.log(await new Wallet('0x'+'11'.repeat(32)).signTransaction(JSON.parse(s)))"
    def sign(transaction):return subprocess.run(['node','--input-type=module','-e',script],cwd=root/'contracts',input=json.dumps(transaction),capture_output=True,text=True,check=True).stdout.strip()
    with pytest.raises(HTTPException):store.broadcast('buyer',order['id'],sign({**tx,'value':'0x1'}))
    with pytest.raises(HTTPException):store.broadcast('intruder',order['id'],sign(tx))
    submitted=[]
    def send(raw):
        decoder=subprocess.run(['node',str(root/'contracts/scripts/decode-transaction.mjs')],input=json.dumps({'raw_transaction':raw}),capture_output=True,text=True,check=True)
        value=json.loads(decoder.stdout);submitted.append(value['hash']);chain.tx={'hash':value['hash']};return value['hash']
    chain.submit_signed_transaction=send
    raw=sign(tx);result=store.broadcast('buyer',order['id'],raw)
    assert result['transaction_hash']==submitted[0]
    store.broadcast('buyer',order['id'],raw)
    assert len(submitted)==1
    assert 'signed_raw' not in store.get('buyer',order['id'])
    with pytest.raises(HTTPException):store.broadcast('buyer',order['id'],sign({**tx,'nonce':1}))
    assert runtime.list_subscriptions('buyer')==[]
    with runtime._connect() as c:
        c.execute("UPDATE bkc_orders SET status='confirmed' WHERE id=?",(order['id'],))
    assert store.broadcast('buyer',order['id'],raw)['status']=='confirmed'
    assert store.get('buyer',order['id'])['status']=='confirmed'
    assert len(submitted)==1


def test_release_anchor_is_owner_bound_zero_value_and_no_subscription(setup):
    runtime, _, chain, store, release = setup
    with pytest.raises(HTTPException):
        store.prepare('bob', 'release', release, BOB)
    order = store.prepare('alice', 'release', release, ALICE)
    assert order['amount_wei'] == '0'
    assert order['payload']['release_id'] == release
    assert order['payload']['claim'] == 'version-anchored-only'
    chain.mine(order)
    assert store.confirm('alice', order['id'], HASH)['status'] == 'confirmed'
    assert runtime.list_subscriptions('alice') == []

def test_proof_anchor_binds_verified_statement_and_rejects_invalid_receipt(setup, monkeypatch):
    from app.zkp import ZkProofStore
    runtime, _, chain, store, release = setup
    with runtime._connect() as c:
        c.execute('CREATE TABLE cloud_proof_jobs (release_id TEXT, proof_id TEXT, status TEXT)')
        c.execute('INSERT INTO cloud_proof_jobs VALUES (?,?,?)',(release,'proof-one','verified'))
    statement={'metrics':{'total_return':0.12},'market_data_hash':'market','strategy_commitment':'program'}
    monkeypatch.setattr(ZkProofStore,'reverify',lambda self,p: True)
    monkeypatch.setattr(ZkProofStore,'get',lambda self,p: {'proof_hash':'receipt','image_id':'image','public_inputs_hash':'inputs','public_statement':statement})
    order=store.prepare('bob','proof_anchor','proof-one',BOB)
    assert order['payload']['public_statement']==statement
    assert order['payload']['content_hash']==store.release('bob',release)['content_hash']
    assert order['transaction']['value']=='0x0'
    chain.mine(order)
    assert store.confirm('bob',order['id'],HASH)['status']=='confirmed'
    def reject(self,p): raise ValueError('invalid receipt')
    monkeypatch.setattr(ZkProofStore,'reverify',reject)
    with pytest.raises(ValueError,match='invalid receipt'):
        store.prepare('alice','proof_anchor','proof-one',ALICE)

def test_proof_anchor_api_identifies_actor_and_only_current_users_record(setup, monkeypatch):
    import app.bkc_payments as payments
    from app.zkp import ZkProofStore
    runtime, runs, chain, store, release = setup
    with runtime._connect() as c:
        c.execute('''CREATE TABLE cloud_proof_jobs (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, release_id TEXT NOT NULL,
            proof_id TEXT, status TEXT NOT NULL, created_at REAL NOT NULL)''')
        c.executemany('INSERT INTO cloud_proof_jobs VALUES (?,?,?,?,?,?)', [
            ('job-a', 'alice', release, 'proof-old', 'verified', 1.0),
            ('job-z', 'alice', release, 'proof-current', 'verified', 1.0),
        ])
    monkeypatch.setattr(ZkProofStore, 'reverify', lambda self, proof_id: True)
    monkeypatch.setattr(ZkProofStore, 'get', lambda self, proof_id: {
        'proof_hash': f'receipt-{proof_id}', 'image_id': 'image',
        'public_inputs_hash': 'inputs', 'public_statement': {'proof_id': proof_id},
    })
    author_order = store.prepare('alice', 'proof_anchor', 'proof-old', ALICE)

    monkeypatch.setattr(payments, 'SupervisorClient', lambda: chain)
    app = FastAPI()
    @app.middleware('http')
    async def identify(request, call_next):
        request.state.user = SimpleNamespace(id=request.headers.get('x-user', 'bob'))
        return await call_next(request)
    app.include_router(payments.bkc_router(runtime, runs))
    with TestClient(app) as client:
        prepared = client.post(
            f'/api/v1/strategy-releases/{release}/proof-anchor-order',
            headers={'x-user': 'bob'}, json={'address': BOB},
        )
        assert prepared.status_code == 200
        assert prepared.json()['payload']['proof_id'] == 'proof-current'
        duplicate = client.post(
            f'/api/v1/strategy-releases/{release}/proof-anchor-order',
            headers={'x-user': 'bob'}, json={'address': BOB},
        )
        assert duplicate.json()['id'] == prepared.json()['id']
        assert runtime.list_subscriptions('bob') == []

        with runtime._connect() as c:
            c.execute("UPDATE bkc_orders SET status='confirmed', transaction_hash=?, block_number=9, block_hash=? WHERE id=?", ('0x' + '4' * 64, BLOCK, author_order['id']))
            c.execute("UPDATE bkc_orders SET status='confirmed', transaction_hash=?, block_number=10, block_hash=? WHERE id=?", ('0x' + '5' * 64, BLOCK, prepared.json()['id']))

        response = client.get(
            f'/api/v1/strategy-releases/{release}/anchors',
            headers={'x-user': 'bob'},
        )
        assert response.status_code == 200
        anchors = {item['payload']['proof_id']: item for item in response.json()}
        current = anchors['proof-current']
        assert {key: current[key] for key in ('signer', 'actor_role', 'is_mine', 'is_current_proof')} == {
            'signer': BOB, 'actor_role': 'third_party',
            'is_mine': True, 'is_current_proof': True,
        }
        old = anchors['proof-old']
        assert {key: old[key] for key in ('signer', 'actor_role', 'is_mine', 'is_current_proof')} == {
            'signer': ALICE, 'actor_role': 'author',
            'is_mine': False, 'is_current_proof': False,
        }

def test_signing_never_underfunds_calldata_when_node_estimate_omits_it(setup, monkeypatch):
    _, _, chain, store, release = setup
    order=store.prepare('bob','subscription',release,BOB)
    import json
    raw=json.dumps({'statement':'a'*10000}).encode()
    with store.runtime._connect() as c:
        c.execute('UPDATE bkc_orders SET data=? WHERE id=?',('0x'+raw.hex(),order['id']))
    original=chain._call
    def rpc(method, params):
        return {'eth_getTransactionCount':'0x1','eth_gasPrice':'0x1','eth_estimateGas':hex(21000),'eth_getBalance':hex(10**20)}.get(method) or original(method,params)
    monkeypatch.setattr(chain,'_call',rpc)
    tx=store.signing('bob',order['id'])['transaction']
    assert int(tx['gasLimit'],16)>=21000+68*len(raw)


def test_retry_only_replaces_canonical_reverted_payment_and_preserves_history(setup):
    runtime, runs, chain, store, release = setup
    original = store.prepare('bob', 'subscription', release, BOB)
    chain.mine(original)
    chain.receipt['status'] = '0x0'
    failed = store.confirm('bob', original['id'], HASH)
    assert failed['status'] == 'failed'
    assert failed['block_hash'] == BLOCK
    replacement = store.retry('bob', original['id'], HASH)
    assert replacement['id'] != original['id']
    assert replacement['status'] == 'pending'
    assert replacement['transaction_hash'] is None
    assert replacement['previous_order_id'] == original['id']
    assert replacement['previous_transaction_hash'] == HASH
    assert replacement['payload']['order_id'] == replacement['id']
    for key in ('signer', 'recipient', 'amount_wei', 'genesis', 'resource_id'):
        assert replacement[key] == original[key]
    assert store.get('bob', original['id'])['transaction_hash'] == HASH
    assert store.get('bob', original['id'])['status'] == 'failed'
    assert store.confirm('bob', original['id'], HASH)['status'] == 'failed'
    assert store.retry('bob', original['id'], HASH)['id'] == replacement['id']
    assert store.prepare('bob', 'subscription', release, BOB)['id'] == replacement['id']
    assert runtime.list_subscriptions('bob') == []
    with pytest.raises(HTTPException) as forbidden:
        store.retry('charlie', original['id'], HASH)
    assert forbidden.value.status_code == 404
    # Legacy current rows and archived attempts remain readable after reopening.
    reopened = BkcStore(runtime, runs, chain)
    assert reopened.get('bob', original['id'])['current_order_id'] == replacement['id']
    assert reopened.get('bob', replacement['id']) == replacement
    chain.mine(replacement)
    second_hash = '0x' + '6' * 64
    chain.tx['hash'] = second_hash
    chain.receipt['transactionHash'] = second_hash
    confirmed = reopened.confirm('bob', replacement['id'], second_hash)
    assert confirmed['status'] == 'confirmed'
    assert reopened.confirm('bob', replacement['id'], second_hash)['subscription']['id'] == confirmed['subscription']['id']
    assert len(runtime.list_subscriptions('bob')) == 1
    assert reopened.confirm('bob', original['id'], HASH)['status'] == 'failed'


@pytest.mark.parametrize('state', ['pending', 'missing_receipt', 'confirmed', 'noncanonical', 'wrong_network'])
def test_retry_refuses_uncertain_successful_or_noncanonical_original_transaction(setup, state):
    runtime, _, chain, store, release = setup
    order = store.prepare('bob', 'subscription', release, BOB)
    if state != 'pending':
        chain.mine(order)
        chain.receipt['status'] = '0x0'
        assert store.confirm('bob', order['id'], HASH)['status'] == 'failed'
    if state == 'missing_receipt':
        chain.receipt = None
    elif state == 'confirmed':
        chain.receipt['status'] = '0x1'
    elif state == 'noncanonical':
        chain.tx['blockHash'] = GENESIS
    elif state == 'wrong_network':
        chain.genesis = '0x' + '9' * 64
    with pytest.raises(HTTPException):
        store.retry('bob', order['id'], HASH)
    assert store.get('bob', order['id'])['id'] == order['id']
    with runtime._connect() as db:
        assert db.execute('SELECT count(*) FROM bkc_order_attempts').fetchone()[0] == 0


def test_concurrent_retry_returns_one_replacement(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    runtime, _, chain, store, release = setup
    original = store.prepare('bob', 'subscription', release, BOB)
    chain.mine(original)
    chain.receipt['status'] = '0x0'
    store.confirm('bob', original['id'], HASH)
    barrier = Barrier(2)
    receipt = chain.transaction_receipt
    def simultaneous_receipt(value):
        barrier.wait(timeout=5)
        return receipt(value)
    monkeypatch.setattr(chain, 'transaction_receipt', simultaneous_receipt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replacements = list(pool.map(lambda _: store.retry('bob', original['id'], HASH), range(2)))
    assert replacements[0]['id'] == replacements[1]['id']
    assert runtime.list_subscriptions('bob') == []
    with runtime._connect() as db:
        assert db.execute('SELECT count(*) FROM bkc_order_attempts').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM bkc_orders').fetchone()[0] == 1


def test_two_reverted_attempts_preserve_the_full_chain_and_resolve_current_order(setup):
    _, _, chain, store, release = setup
    first = store.prepare('bob', 'subscription', release, BOB)
    chain.mine(first)
    chain.receipt['status'] = '0x0'
    store.confirm('bob', first['id'], HASH)
    second = store.retry('bob', first['id'], HASH)
    chain.mine(second)
    second_hash = '0x' + '7' * 64
    chain.tx['hash'] = second_hash
    chain.receipt.update(transactionHash=second_hash, status='0x0')
    store.confirm('bob', second['id'], second_hash)
    third = store.retry('bob', second['id'], second_hash)
    assert len({first['id'], second['id'], third['id']}) == 3
    assert store.get('bob', first['id'])['current_order_id'] == third['id']
    assert store.get('bob', second['id'])['current_order_id'] == third['id']
    assert store.get('bob', first['id'])['transaction_hash'] == HASH
    assert store.get('bob', second['id'])['transaction_hash'] == second_hash
    assert third['previous_order_id'] == second['id']
    assert third['transaction_hash'] is None
