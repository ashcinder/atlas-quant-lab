"""Boundary validation plus real engine smoke tests when optional engines exist."""
import json
import subprocess
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.backtest.native import BUNDLE, PYTHON, WORKER, run_native, validate_native
from app.market_publication import MarketPublication
from app.models import BacktestRequest


@pytest.mark.parametrize('updates', [
    {'backtest_engine':'rqalpha'},
    {'backtest_engine':'vnpy','strategy_id':'buy_hold'},
    {'backtest_engine':'vnpy','release_id':'private-release'},
    {'backtest_engine':'vnpy','adjustment':'forward'},
    {'backtest_engine':'vnpy','symbol':'ETH-USD'},
])
def test_native_rejects_incompatible_requests(updates):
    request=BacktestRequest(start='2025-01-01',end='2025-06-01',**updates)
    with pytest.raises(ValueError): validate_native(request)


def test_native_worker_writes_complete_report_to_a_pipe_with_partial_writes(monkeypatch, capfd):
    from engine_workers import native as worker

    output = bytearray()

    def partial_write(fd, remaining):
        assert fd == sys.stdout.fileno()
        portion = remaining[:65_536]
        output.extend(portion)
        return len(portion)

    monkeypatch.setattr(worker, "os", SimpleNamespace(write=partial_write))
    result = {"snapshots": [{"time": i, "equity": 10000.0} for i in range(3000)]}
    worker.write_result(result)

    assert len(output) > 65_536
    assert json.loads(output) == result
    assert output.endswith(b"\n")


@pytest.mark.skipif(not PYTHON.exists(),reason='optional native environment not installed')
def test_real_vnpy_matching_and_cash_account():
    # Rising then falling prices force both entry and exit; a long warmup
    # proves no fill occurs before a closed-bar signal exists.
    prices=[100+i for i in range(50)]+[150-i for i in range(50)]
    bars=[dict(time=1735689600+i*60,open=p,high=p+1,low=p-1,close=p,volume=10000) for i,p in enumerate(prices)]
    request=BacktestRequest(backtest_engine='vnpy',interval='1m',start='2025-01-01',end='2025-01-02',params={'fast':3,'slow':10},max_participation_rate=1)
    result=subprocess.run([str(PYTHON),str(WORKER)],input=json.dumps({'engine':'vnpy','request':request.model_dump(mode='json'),'bars':bars}),capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stderr
    data=json.loads(result.stdout)
    assert len(data['snapshots'])==len(bars)
    assert {t['side'] for t in data['fills']}=={'buy','sell'}
    assert data['fills'][0]['time']>=bars[10]['time']
    assert all(t['cash_after']>=-1e-8 and t['position_after']>=-1e-8 for t in data['fills'])
    last=data['fills'][-1]
    assert data['snapshots'][-1]['equity']==pytest.approx(last['cash_after']+last['position_after']*prices[-1])


@pytest.mark.skipif(not PYTHON.exists() or not (BUNDLE/'stocks.h5').exists(),reason='optional RQAlpha bundle unavailable')
def test_real_rqalpha_native_stock_account():
    request=BacktestRequest(backtest_engine='rqalpha',symbol='300750.SZ',asset_class='equity',interval='1d',
        start='2025-01-01',end='2025-06-30',params={'fast':5,'slow':20},persist=False)
    result=run_native(request,MarketPublication())
    assert result.backtest_engine=='rqalpha'
    assert result.data_source=='rqalpha-bundle'
    assert len(result.bars)==len(result.equity)>40
    assert result.trades
    assert all(t.quantity%100==0 for t in result.trades if t.side=='buy')
    assert result.engine_version


@pytest.mark.skipif(not PYTHON.exists() or not (BUNDLE/'stocks.h5').exists(), reason='optional RQAlpha bundle unavailable')
def test_rqalpha_published_report_keeps_only_symbol_sessions():
    request = BacktestRequest(backtest_engine='rqalpha', symbol='600036.SS', asset_class='equity',
        interval='1d', start='2005-01-04', end='2005-08-01', persist=False)
    payload = {'engine': 'rqalpha', 'request': request.model_dump(mode='json'), 'bundle_path': str(BUNDLE)}
    loaded = subprocess.run([str(PYTHON), str(WORKER)], input=json.dumps({**payload, 'operation': 'load_bundle'}),
        capture_output=True, text=True, timeout=40, check=True)
    suspended = datetime(2005, 5, 17, 1, 30, tzinfo=UTC).timestamp()
    bars = [bar for bar in json.loads(loaded.stdout)['bars'] if bar['time'] != suspended]
    result = subprocess.run([str(PYTHON), str(WORKER)], input=json.dumps({**payload, 'bars': bars}),
        capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
    raw = json.loads(result.stdout)
    assert raw['bars'] == bars
    assert [snapshot['time'] for snapshot in raw['snapshots']] == [bar['time'] for bar in bars]
    assert raw['fills']

    actions = subprocess.run([str(PYTHON), str(WORKER)], input=json.dumps({
        **payload, 'operation': 'daily_actions', 'request': {
            'symbol': request.symbol, 'from': bars[0]['time'], 'to': bars[-1]['time'],
        },
    }), capture_output=True, text=True, timeout=40, check=True)
    metadata = json.loads(actions.stdout)
    vnpy = subprocess.run([str(PYTHON), str(WORKER)], input=json.dumps({
        **payload, 'engine': 'vnpy', 'request': {
            **payload['request'], 'backtest_engine': 'vnpy', 'daily_action_version': metadata['version'],
        }, 'bars': bars, 'prepared_strategy': {'targets': [.8] * len(bars)},
    }), capture_output=True, text=True, timeout=40, check=True)
    report = json.loads(vnpy.stdout)
    ex_time = int(datetime(2005, 6, 20, 1, 30, tzinfo=UTC).timestamp())
    ex_index = next(i for i, bar in enumerate(bars) if bar['time'] == ex_time)
    assert bars[ex_index]['close'] / bars[ex_index - 1]['close'] < .75
    assert report['research_closes'][ex_index] / report['research_closes'][ex_index - 1] > 1
    assert report['snapshots'][ex_index]['equity'] / report['snapshots'][ex_index - 1]['equity'] > 1


@pytest.mark.skipif(not PYTHON.exists(), reason='optional native environment not installed')
def test_vnpy_a_share_daily_replays_published_bars():
    from app.backtest.native import normalize
    from app.catalog import find_asset
    import pandas as pd
    request=BacktestRequest(backtest_engine='vnpy',symbol='300750.SZ',asset_class='equity',interval='1d',
        start='2025-01-01',end='2025-06-30',params={'fast':5,'slow':20},persist=False)
    validate_native(request)
    prices=[100+i for i in range(50)]+[150-i for i in range(50)]
    bars=[dict(time=int(t.timestamp()),open=p,high=p+1,low=p-1,close=p,volume=100000)
          for t,p in zip(pd.bdate_range('2025-01-01',periods=100,tz='UTC'),prices)]
    result=subprocess.run([str(PYTHON),str(WORKER)],input=json.dumps({'engine':'vnpy','request':request.model_dump(mode='json'),'bars':bars}),capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stderr
    raw=json.loads(result.stdout)
    assert raw['bars']==bars and len(raw['snapshots'])==len(bars)
    assert {t['side'] for t in raw['fills']}=={'buy','sell'}
    normalized=normalize(request,raw,'rqalpha-bundle','test')
    assert normalized.valuation_currency=='CNY'
    assert any('尚不模拟 T+1' in warning for warning in normalized.warnings)


@pytest.mark.skipif(not PYTHON.exists(),reason='optional native environment not installed')
def test_native_api_requires_auth_and_persists_engine(monkeypatch):
    from uuid import uuid4
    import pandas as pd
    from fastapi.testclient import TestClient
    from app.main import app, market_publications
    from app.catalog import find_asset
    from app.data.service import DataBundle
    from app.journal.router import _attempts
    _attempts.clear()
    with TestClient(app) as client:
        assert client.post('/api/v1/backtests/native',json={}).status_code==401
        registered=client.post('/api/register',json={'email':f'{uuid4()}@example.test','password':'test-password-123'})
        assert registered.status_code==201,registered.text
        prices=[100+i for i in range(50)]+[150-i for i in range(50)]
        frame=pd.DataFrame([dict(open=p,high=p+1,low=p-1,close=p,volume=10000) for p in prices],index=pd.date_range('2025-01-01',periods=100,freq='min',tz='UTC'))
        market_publications.publish({'symbol':'BTC-USD','asset_class':'crypto','interval':'1m','start':'2025-01-01','end':'2025-01-02'},
            DataBundle(asset=find_asset('BTC-USD','crypto'),frame=frame,source='binance'))
        payload=dict(backtest_engine='vnpy',interval='1m',params={'fast':3,'slow':10})
        response=client.post('/api/v1/backtests/native',json=payload)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['backtest_engine']=='vnpy' and result['engine_version']
        assert result['bar_count'] == len(frame)
        assert result['equity'][0]['time'] == int(frame.index[0].timestamp())
        assert result['equity'][-1]['time'] == int(frame.index[-1].timestamp())
        saved=client.get('/api/v1/runs/'+result['run_id'])
        assert saved.status_code==200
        assert saved.json()['backtest_engine']=='vnpy'

        from app.backtest import native
        monkeypatch.setattr(native, 'LONG_REPORT_THRESHOLD', 90)
        monkeypatch.setattr(native, 'REPORT_POINTS', 40)
        replay = client.post('/api/v1/backtests/native', json={**payload, 'persist': False})
        assert replay.status_code == 200, replay.text
        replayed = replay.json()
        assert replayed['bar_count'] == len(frame)
        assert replayed['metrics'] == result['metrics']
        assert replayed['trades'] == result['trades']
        assert replayed['equity'][0] == result['equity'][0]
        assert replayed['equity'][-1] == result['equity'][-1]
