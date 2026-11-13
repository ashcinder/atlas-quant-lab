"""Boundary validation plus real engine smoke tests when optional engines exist."""
import json
import subprocess

import pytest

from app.backtest.native import BUNDLE, PYTHON, WORKER, run_native, validate_native
from app.market_publication import MarketPublication
from app.models import BacktestRequest


@pytest.mark.parametrize('updates', [
    {'backtest_engine':'rqalpha'},
    {'backtest_engine':'vnpy','strategy_id':'buy_hold'},
    {'backtest_engine':'vnpy','release_id':'private-release'},
    {'backtest_engine':'vnpy','start':None},
    {'backtest_engine':'vnpy','adjustment':'forward'},
    {'backtest_engine':'vnpy','symbol':'ETH-USD'},
])
def test_native_rejects_incompatible_requests(updates):
    request=BacktestRequest(start='2025-01-01',end='2025-06-01',**{k:v for k,v in updates.items() if k not in {'start','end'}})
    if 'start' in updates: request=request.model_copy(update={'start':updates['start']})
    with pytest.raises(ValueError): validate_native(request)


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
def test_native_api_requires_auth_and_persists_engine():
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
        payload=dict(backtest_engine='vnpy',interval='1m',start='2025-01-01',end='2025-01-02',params={'fast':3,'slow':10})
        response=client.post('/api/v1/backtests/native',json=payload)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['backtest_engine']=='vnpy' and result['engine_version']
        saved=client.get('/api/v1/runs/'+result['run_id'])
        assert saved.status_code==200
        assert saved.json()['backtest_engine']=='vnpy'
