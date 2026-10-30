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
    from app.work_limits import WorkLimits
    monkeypatch.setattr(module,'work_limits',WorkLimits())
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


def test_proof_worker_waits_for_shared_budget_and_releases_on_failure(setup, monkeypatch):
    import app.cloud_proofs as module
    runtime, service, release = setup
    job = service.create('author', release['id'], ProofJobInput(
        market_data_hash=HASH, address=ADDRESS, consent_cloud_source=True))
    with runtime._connect() as c:
        c.execute("UPDATE bkc_orders SET status='confirmed' WHERE id=?", (job['order_id'],))
        c.execute("UPDATE cloud_proof_jobs SET status='queued' WHERE id=?", (job['id'],))
    module.work_limits.acquire('author')
    service.tick()
    assert service.get('author', job['id'])['status'] == 'queued'
    module.work_limits.release('author')
    def fail_prover(*args, **kwargs):
        with pytest.raises(HTTPException) as failure:
            module.work_limits.acquire('author')
        assert failure.value.status_code == 429
        raise RuntimeError('test prover failure')
    monkeypatch.setattr(module, 'run_proof', fail_prover)
    service.tick()
    assert service.get('author', job['id'])['status'] == 'failed'
    module.work_limits.acquire('author')
    module.work_limits.release('author')


def test_config_refuses_payment_when_container_memory_is_too_low(setup, monkeypatch):
    import app.cloud_proofs as module
    _, service, _ = setup
    monkeypatch.setenv('TRINE_PROOF_PRICE_BKC','1')
    monkeypatch.setenv('TRINE_PROOF_RECIPIENT',ADDRESS)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps({'image_id':module.load_profiles()[module.PROFILE]['image_id']})))
    monkeypatch.setattr(module,'prover_memory_ready',lambda:False)
    result=CloudProofService.config(service)
    assert result['configured'] is False
    assert '6 GiB' in result['unavailable_reason']


def test_failed_job_reuses_original_paid_order(setup):
    runtime,service,release=setup
    body=ProofJobInput(market_data_hash=HASH,address=ADDRESS,consent_cloud_source=True)
    job=service.create('author',release['id'],body)
    with runtime._connect() as c:c.execute("UPDATE cloud_proof_jobs SET status='failed' WHERE id=?",(job['id'],))
    again=service.create('author',release['id'],body)
    assert again['id']==job['id'] and again['order_id']==job['order_id']


def test_early_partial_result_recovers_without_new_payment(setup,monkeypatch):
    import app.cloud_proofs as module
    runtime,service,release=setup
    body=ProofJobInput(market_data_hash=HASH,address=ADDRESS,consent_cloud_source=True)
    job=service.create('author',release['id'],body)
    with runtime._connect() as c:
        c.execute("UPDATE bkc_orders SET status='confirmed' WHERE id=?",(job['order_id'],))
        c.execute("UPDATE cloud_proof_jobs SET status='queued' WHERE id=?",(job['id'],))
    directory=service.root/job['id']/'result';directory.mkdir(parents=True)
    (directory/'verification.public.json').write_text('{broken')
    seen=[]
    def launch(command,**kwargs):
        seen.append(command)
        assert '--resume' not in command
        assert not directory.exists()
        raise RuntimeError('stop before expensive proof')
    monkeypatch.setattr(module,'run_proof',launch)
    service.tick()
    assert len(seen)==1
    assert list(directory.parent.glob('incomplete-*'))
    assert service.create('author',release['id'],body)['order_id']==job['order_id']


def test_timeout_terminates_prover_process_group(tmp_path):
    import os,subprocess,sys,time
    from app.cloud_proofs import run_proof
    pidfile=tmp_path/'child.pid'
    code="import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)"
    with pytest.raises(subprocess.TimeoutExpired):run_proof([sys.executable,'-c',code,str(pidfile)],timeout=.5)
    pid=int(pidfile.read_text())
    for _ in range(20):
        result=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True)
        if result.returncode or result.stdout.strip().startswith('Z'):break
        time.sleep(.05)
    else:
        os.kill(pid,9)
        pytest.fail('prover child survived task timeout')


def test_completed_proof_must_bind_paid_inputs_and_original_witness(tmp_path,monkeypatch):
    import app.cloud_proofs as module
    saved={'strategy':{'program':[1],'commission_bps':10,'slippage_bps':5},'market':{'bars':[1,2,3]},
           'initial_equity_micros':100,'strategy_salt':[1]*32,'nullifier_nonce':[2]*32,'workflow_commitment':'workflow'}
    original=tmp_path/'original.json';original.write_text(json.dumps(saved))
    result=tmp_path/'result';result.mkdir();(result/'witness.private.json').write_text(json.dumps(saved))
    inputs={'program':[1],'commission_bps':10,'slippage_bps':5,'initial_equity_micros':100}
    calls=[]
    def reverify(pid):
        calls.append(pid)
        return SimpleNamespace(journal={'market_data_hash':HASH,'agent_id':pid})
    proofs=SimpleNamespace(reverify=reverify)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps({'market_data_hash':HASH,'agent_id':'expected'})))
    module.check_paid_proof(proofs,'expected',result,original,inputs,HASH)
    with pytest.raises(RuntimeError,match='bind paid job'):
        module.check_paid_proof(proofs,'other-proof',result,original,inputs,HASH)
    with pytest.raises(RuntimeError,match='input mismatch'):
        module.check_paid_proof(proofs,'expected',result,original,{**inputs,'program':[2]},HASH)
    assert calls==['expected','other-proof','expected']


@pytest.mark.parametrize('has_saved_result',[False,True])
def test_partial_outer_witness_is_recovered_atomically(tmp_path,has_saved_result):
    from app.cloud_proofs import ensure_job_witness
    proposed={'agent_id':'qja_draft','strategy':{'program':[1]},'market':{'bars':[1,2,3]},
              'initial_equity_micros':100,'workflow_commitment':'workflow','nullifier_nonce':[1]*32}
    path=tmp_path/'witness.private.json';path.write_text('{incomplete')
    result=tmp_path/'result';result.mkdir()
    existing={**proposed,'agent_id':'qja_saved','nullifier_nonce':[2]*32}
    if has_saved_result:(result/'witness.private.json').write_text(json.dumps(existing))
    ensure_job_witness(path,proposed,result)
    assert json.loads(path.read_text())==(existing if has_saved_result else proposed)
    assert path.stat().st_mode & 0o777==0o600
    assert len(list(tmp_path.glob('incomplete-witness-*')))==1
    assert not list(tmp_path.glob('.witness-*'))
    ensure_job_witness(path,proposed,result)
    assert json.loads(path.read_text())==(existing if has_saved_result else proposed)
