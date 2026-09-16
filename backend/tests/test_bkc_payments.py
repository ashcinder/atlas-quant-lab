from types import SimpleNamespace
import pytest
from fastapi import HTTPException
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
