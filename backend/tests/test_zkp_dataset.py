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
    from app.data.service import MarketDataService
    service=MarketDataService(tmp_path/'cache')
    service.providers['binance']=SimpleNamespace(fetch_bars=lambda *args:frame)
    monkeypatch.setattr(main,'data_service',service)
    monkeypatch.setattr(main,'zk_proof_store',ZkProofStore(tmp_path/'db.sqlite',receipt_root=tmp_path/'proof',market_root=tmp_path/'market'))
    app=FastAPI();app.post('/dataset')(main.create_zkp_market_dataset)
    client=TestClient(app)
    response=client.post('/dataset',params={'start':'2025-08-02T00:00:00Z','end':'2025-08-06T00:00:00Z'})
    assert response.status_code==200,response.text
    assert len(response.json()['dataset']['bars'])==4
    assert client.post('/dataset',params={'start':'2025-08-02T00:00:00','end':'2025-08-06T00:00:00Z'}).status_code==422

@pytest.mark.parametrize('count', [3, 4, 257])
def test_short_proof_dataset_uses_real_service_without_relaxing_backtests(tmp_path, count):
    from app.data.service import MarketDataService
    from app.data.providers import ProviderError
    from types import SimpleNamespace
    start=datetime(2025,1,1,tzinfo=UTC)
    frame=pd.DataFrame({'open':[100]*count,'high':[102]*count,'low':[99]*count,'close':[101]*count,'volume':[1000]*count},index=pd.date_range(start,periods=count,freq='D'))
    service=MarketDataService(tmp_path/'cache')
    service.providers['binance']=SimpleNamespace(fetch_bars=lambda *args:frame)
    args=('BTC-USD','crypto','1d',start,start+timedelta(days=count))
    result=service.fetch(*args,source='binance',minimum_bars=3)
    assert len(closed_frame(result.frame,'1d',args[3],args[4]))==count
    # A short cached Proof dataset must not bypass the ordinary backtest floor.
    if count < 30:
        with pytest.raises(ProviderError,match='30'):
            service.fetch(*args,source='binance')

@pytest.mark.parametrize('count', [2, 20001])
def test_proof_dataset_rejects_out_of_range_count(count):
    start=datetime(1900,1,1,tzinfo=UTC)
    frame=pd.DataFrame({'close':[100]*count},index=pd.date_range(start,periods=count,freq='h'))
    with pytest.raises(ZkProofError,match='3–20000'):
        closed_frame(frame,'1h',now=datetime(2025,1,1,tzinfo=UTC))

def test_maximum_proof_window_is_accepted():
    start=datetime(1900,1,1,tzinfo=UTC)
    frame=pd.DataFrame({'close':[100]*20000},index=pd.date_range(start,periods=20000,freq='h'))
    assert len(closed_frame(frame,'1h',now=datetime(2025,1,1,tzinfo=UTC)))==20000
