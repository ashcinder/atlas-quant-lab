import io
import zipfile
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.zkp_api import proof_inspection_router
from test_zkp import setup

def test_bundle_contains_public_files_and_rejects_corrupted_receipt(tmp_path):
    _, store, created, _ = setup(tmp_path)
    proof=store.register_receipt(created['agent']['id'],'atlas_sma_backtest_risc0_v1',b'receipt',created['developer_token'])
    app=FastAPI();app.include_router(proof_inspection_router(store));client=TestClient(app)
    url=f"/api/v1/quantjudge/zk-proofs/{proof['id']}/bundle"
    response=client.get(url)
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist())=={'manifest.json','journal.json','market.json','proof.r0','verify-proof-bundle.py','README.txt'}
        assert archive.read('proof.r0')==b'receipt'
    store.receipt_path(proof['id']).write_bytes(b'corrupt')
    assert client.get(url).status_code==409
