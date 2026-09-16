from datetime import UTC, datetime, timedelta
import pandas as pd
import pytest
from app.zkp import ZkProofError
from app.zkp_dataset import closed_frame, validate_period

def test_interval_excludes_outside_and_unclosed_bars():
    start = datetime(2025, 8, 1, tzinfo=UTC)
    frame = pd.DataFrame({'close': range(8)}, index=pd.date_range(start, periods=8, freq='D'))
    selected = closed_frame(frame, '1d', start + timedelta(days=1), start + timedelta(days=6), now=start+timedelta(days=5,hours=12))
    assert list(selected['close']) == [1,2,3,4]
    assert len(closed_frame(frame, '1d', start, start+timedelta(days=3), now=start+timedelta(days=8))) == 3

def test_ambiguous_and_invalid_periods_fail_closed():
    with pytest.raises(ZkProofError, match='时区'):
        validate_period(datetime(2025, 8, 1), None)
    now=datetime.now(UTC)
    with pytest.raises(ZkProofError, match='早于'):
        validate_period(now, now)
    frame=pd.DataFrame({'close':[1,2]},index=pd.date_range(now-timedelta(days=3), periods=2, freq='D'))
    with pytest.raises(ZkProofError, match='3–20000'):
        closed_frame(frame,'1d',now=now)

def test_http_period_parameters_parse_and_select_closed_bars(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import main
    from app.zkp import ZkProofStore
    start=datetime(2025,8,1,tzinfo=UTC)
    frame=pd.DataFrame({'open':[100]*8,'high':[102]*8,'low':[99]*8,'close':[101]*8,'volume':[1000]*8},index=pd.date_range(start,periods=8,freq='D'))
    monkeypatch.setattr(main.data_service,'fetch',lambda *args:SimpleNamespace(source='test',asset=SimpleNamespace(symbol='TEST'),frame=frame,fetched_at=start))
    monkeypatch.setattr(main,'zk_proof_store',ZkProofStore(tmp_path/'db.sqlite',receipt_root=tmp_path/'proof',market_root=tmp_path/'market'))
    app=FastAPI();app.post('/dataset')(main.create_zkp_market_dataset)
    client=TestClient(app)
    response=client.post('/dataset',params={'start':'2025-08-02T00:00:00Z','end':'2025-08-06T00:00:00Z'})
    assert response.status_code==200,response.text
    assert len(response.json()['dataset']['bars'])==4
    assert client.post('/dataset',params={'start':'2025-08-02T00:00:00','end':'2025-08-06T00:00:00Z'}).status_code==422
