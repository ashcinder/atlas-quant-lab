import json
from types import SimpleNamespace
import pytest
from app.zkp_bindings import init_public_programs, check_public_program
from app.zkp import ZkProofError
from test_zkp import setup

def test_public_code_binding_rejects_source_substitution(tmp_path):
    _, store, created, _ = setup(tmp_path)
    proof=store.register_receipt(created['agent']['id'],'atlas_sma_backtest_risc0_v1',b'receipt',created['developer_token'])
    init_public_programs(store)
    with store._connect() as conn:
        conn.execute('INSERT INTO qj_public_programs VALUES (?,?,?)',(proof['id'],'def target_bps(index, close, sma):\n    return 3000',json.dumps({'strategy':{'program':[{'const':1000}],'commission_bps':10,'slippage_bps':5}})))
    with pytest.raises(ZkProofError,match='源码'):
        check_public_program(store,proof['id'],{})

def test_public_program_reexecution_must_equal_verified_journal(tmp_path,monkeypatch):
    _, store, created, _ = setup(tmp_path)
    proof=store.register_receipt(created['agent']['id'],'atlas_sma_backtest_risc0_v1',b'receipt',created['developer_token'])
    init_public_programs(store)
    with store._connect() as conn:
        conn.execute('INSERT INTO qj_public_programs VALUES (?,?,?)',(proof['id'],'def target_bps(index, close, sma):\n    return 1000',json.dumps({'strategy':{'program':[{'const':1000}],'commission_bps':10,'slippage_bps':5}})))
    journal={'proof_profile':'test','return':42}
    monkeypatch.setattr('app.zkp_bindings.subprocess.run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(journal)))
    assert check_public_program(store,proof['id'],journal)['compiled_program_commitment_verified']
    with pytest.raises(ZkProofError,match='结果'):
        check_public_program(store,proof['id'],{**journal,'return':43})

def test_only_explicit_public_examples_are_downloadable(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.zkp_api import proof_inspection_router
    _, store, created, _ = setup(tmp_path)
    proof = store.register_receipt(created['agent']['id'], 'atlas_sma_backtest_risc0_v1', b'receipt', created['developer_token'])
    app = FastAPI(); app.include_router(proof_inspection_router(store))
    client = TestClient(app)
    url = f"/api/v1/quantjudge/zk-proofs/{proof['id']}/public-example"
    assert client.get(url).status_code == 404
    with store._connect() as conn:
        conn.execute('INSERT INTO qj_public_programs VALUES (?,?,?)', (proof['id'], 'public example', '{"public":true}'))
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()['witness'] == {'public': True}
