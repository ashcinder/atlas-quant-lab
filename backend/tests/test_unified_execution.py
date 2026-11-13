"""Different execution models must never be silently reported as equivalent."""
import json
from pathlib import Path
import subprocess

import pytest

from app.backtest.native import PYTHON, WORKER
from app.backtest.unified import ResearchLedger
from app.models import BacktestRequest


def test_request_preserves_execution_model():
    r = BacktestRequest(execution_model='unified')
    assert r.model_dump()['execution_model'] == 'unified'


def scenario():
    prices = [100+i for i in range(50)] + [150-i for i in range(50)]
    return [dict(time=1735781400+i*60,open=p+.5,high=p+2,low=p-2,close=p,
                 volume=0 if i in (10,11,51) else 100000) for i,p in enumerate(prices)]


def request():
    return BacktestRequest(execution_model='unified',backtest_engine='vnpy',symbol='300750.SZ',
        asset_class='equity',data_source='huggingface',adjustment='raw',interval='1m',
        start='2025-01-02',end='2025-01-03',params={'fast':3,'slow':10},max_participation_rate=1).model_dump(mode='json')


def test_unified_closed_signal_next_open_and_zero_volume():
    bars = scenario()
    ledger = ResearchLedger(request())
    for bar in bars:
        ledger.step(bar)
    assert ledger.fills and {t['side'] for t in ledger.fills} == {'buy','sell'}
    assert ledger.fills[0]['time'] == bars[12]['time']
    assert ledger.fills[0]['price'] == pytest.approx(bars[12]['open']*1.00075)
    assert all(t['cash_after'] >= -1e-8 for t in ledger.fills)


@pytest.mark.skipif(not PYTHON.exists(),reason='optional framework environment unavailable')
def test_vnpy_unified_runs_actual_framework_events_with_same_ledger():
    bars = scenario()
    expected = ResearchLedger(request())
    for b in bars:
        expected.step(b)
    process = subprocess.run([str(PYTHON),str(WORKER)],input=json.dumps(dict(engine='vnpy',request=request(),bars=bars)),
        text=True,capture_output=True,timeout=40)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result.get('execution_model') == 'unified'
    assert result['snapshots'] == expected.snapshots
    assert result['fills'] == expected.fills


def test_unified_does_not_read_future_prices():
    bars = scenario()
    changed = [dict(b) for b in bars]
    for b in changed[60:]:
        for field in ('open','high','low','close'): b[field] *= 2
    first, second = ResearchLedger(request()), ResearchLedger(request())
    for a,b in zip(bars,changed): first.step(a);second.step(b)
    assert first.snapshots[:60] == second.snapshots[:60]
    assert [t for t in first.fills if t['time']<bars[60]['time']] == [t for t in second.fills if t['time']<bars[60]['time']]


@pytest.mark.skipif(not PYTHON.exists(),reason='optional framework environment unavailable')
def test_unified_api_persists_contract_and_actual_engine():
    from uuid import uuid4
    import pandas as pd
    from fastapi.testclient import TestClient
    from app.main import app, market_publications
    from app.catalog import find_asset
    from app.data.service import DataBundle
    from app.journal.router import _attempts
    _attempts.clear()
    bars=scenario()
    frame=pd.DataFrame(bars).set_index('time')
    frame.index=pd.to_datetime(frame.index,unit='s',utc=True)
    query=dict(symbol='300750.SZ',asset_class='equity',interval='1m',data_source='huggingface',adjustment='raw')
    market_publications.publish(query,DataBundle(asset=find_asset('300750.SZ'),frame=frame,source='hf-ohlcv'))
    with TestClient(app) as client:
        registered=client.post('/api/register',json={'email':f'{uuid4()}@example.test','password':'test-password-123'})
        assert registered.status_code==201
        body={**request(),'start':frame.index[0].isoformat(),'end':frame.index[-1].isoformat(),'persist':True}
        response=client.post('/api/v1/backtests/native',json=body)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['execution_model']=='unified' and result['execution_contract']=='research-next-open/v1'
        assert result['backtest_engine']=='vnpy' and len(result['equity'])==len(bars)
        saved=client.get('/api/v1/runs/'+result['run_id']).json()
        assert saved['execution_model']=='unified' and saved['execution_contract']=='research-next-open/v1'
