import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.cloud_proofs import CloudProofService, ProofJobInput
from app.strategy_runtime import StrategyRuntimeStore,ReleaseCreate
from app.storage import RunStore
from app.bkc_payments import BkcStore

ADDRESS='0x'+'a'*40
HASH='b'*64
@pytest.fixture
def setup(tmp_path,monkeypatch):
    import app.cloud_proofs as module
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    runtime=StrategyRuntimeStore(SimpleNamespace(),tmp_path/'db.sqlite')
    runs=RunStore(tmp_path/'db.sqlite')
    dataset=tmp_path/'market.json';dataset.write_text(json.dumps({'dataset':{'bars':[{}]*32}}))
    service=CloudProofService(runtime,runs,SimpleNamespace(market_dataset=lambda h:({},dataset)))
    service.config=lambda:{'configured':True,'price_bkc':'1.25','recipient':ADDRESS}
    service.payments.network=lambda:(None,'0x'+'c'*64)
    release=runtime.create_release('author',ReleaseCreate(name='proof test',source_kind='python',strategy_id='python_bounded',python_source='def target_bps(index, close, sma):\n return 5000',markets=['CRYPTO']))
    return runtime,service,release

def test_cloud_job_requires_owner_consent_and_payment(setup):
    runtime,service,release=setup
    body=ProofJobInput(market_data_hash=HASH,address=ADDRESS,consent_cloud_source=True)
    with pytest.raises(HTTPException):service.create('other',release['id'],body)
    with pytest.raises(HTTPException):service.create('author',release['id'],body.model_copy(update={'consent_cloud_source':False}))
    job=service.create('author',release['id'],body)
    assert job['status']=='awaiting_payment'
    assert service.create('author',release['id'],body)['id']==job['id']
    order=service.payments.get('author',job['order_id'])
    assert order['amount_wei']=='1250000000000000000'
    assert order['payload']['release_id']==release['id']
    with pytest.raises(HTTPException):service.enqueue('author',job['id'])
    service.tick()
    assert service.get('author',job['id'])['status']=='awaiting_payment'
    with pytest.raises(HTTPException):service.get('other',job['id'])

def test_only_confirmed_payment_enqueues_and_status_visible(setup):
    runtime,service,release=setup
    job=service.create('author',release['id'],ProofJobInput(market_data_hash=HASH,address=ADDRESS,consent_cloud_source=True))
    with runtime._connect() as c:c.execute('UPDATE bkc_orders SET transaction_hash=? WHERE id=?',('0x'+'d'*64,job['order_id']))
    service.payments.confirm=lambda *a:{'status':'submitted'}
    with pytest.raises(HTTPException):service.enqueue('author',job['id'])
    service.payments.confirm=lambda *a:{'status':'confirmed'}
    assert service.enqueue('author',job['id'])['status']=='queued'
    assert runtime.list_releases('author')[0]['proof_status']=='queued'

def test_backtest_release_entitlement_and_program_snapshot(setup):
    runtime,service,release=setup
    strategy,snapshot=runtime.backtest_release('author',release['id'])
    assert strategy=='python_bounded' and snapshot['python_program']
    with pytest.raises(HTTPException):runtime.backtest_release('other',release['id'])
    with pytest.raises(HTTPException):runtime.subscribe('other',release['id'])
    runtime.subscribe('author',release['id'])
    public=runtime.list_releases('other')[0]
    assert 'python_source' not in public and 'python_program' not in public


def test_config_refuses_unmatched_native_program(setup, monkeypatch):
    _, service, _ = setup
    import app.cloud_proofs as module
    monkeypatch.setenv('TRINE_PROOF_PRICE_BKC', '1.25')
    monkeypatch.setenv('TRINE_PROOF_RECIPIENT', ADDRESS)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=json.dumps({'image_id': '0'*64})))
    config = CloudProofService.config(service)
    assert config['configured'] is False
    assert config['price_bkc'] == '1.25'
    assert '不匹配' in config['unavailable_reason']


def test_work_pricing_scales_with_bars_and_program_and_rounds_up():
    from app.cloud_proofs import proof_quote
    small = proof_quote([1], 32, '1')
    assert small['amount_wei'] == '1000000000000000000'
    assert proof_quote([1], 64, '1')['amount_bkc'] == '2.000000'
    assert int(proof_quote([1] * 128, 64, '1')['amount_wei']) > 2 * 10**18
    assert proof_quote([1], 33, '0.000001')['amount_bkc'] == '0.000002'


def test_pending_order_keeps_original_quote_after_tariff_change(setup):
    runtime, service, release = setup
    body = ProofJobInput(market_data_hash=HASH, address=ADDRESS, consent_cloud_source=True)
    job = service.create('author', release['id'], body)
    service.config = lambda: {'configured':True, 'price_bkc':'200', 'recipient':ADDRESS}
    again = service.create('author', release['id'], body)
    assert again['id'] == job['id']
    assert again['quote'] == job['quote']
    assert again['quote']['amount_bkc'] == '1.250000'
