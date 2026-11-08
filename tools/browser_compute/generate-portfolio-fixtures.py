"""Run against unchanged backend source; output public synthetic numeric fixtures only."""
from datetime import UTC, datetime
import json
import math
from pathlib import Path
from threading import Event
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"backend"))

import numpy as np
import pandas as pd
from app.backtest.portfolio import run_portfolio_backtest, _risk_parity_weights
from app.catalog import find_asset
from app.data.service import DataBundle
from app.models import PortfolioBacktestRequest, ResearchRequest
from app.research import run_research

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)


def market(bundle):
    return {'asset': bundle.asset.model_dump(mode='json'), 'bars': [dict(time=int(ts.timestamp()), **{str(key): float(value) for key, value in row.items()}) for ts, row in bundle.frame.iterrows()], 'source':bundle.source, 'source_note':bundle.source_note}


def bundle(symbol, count=540, kind=0, hour_shift=0):
    index = pd.date_range('2022-01-03', periods=count, freq='D', tz='UTC') + pd.Timedelta(hours=hour_shift)
    step = np.arange(count)
    paths = [100*np.exp(.001*step+.05*np.sin(step/13)), 100*np.exp(-.0001*step+.08*np.sin(step/29+1)), 100*np.exp(.0002*step+.025*np.sin(step/41+2)), 100*np.exp(.0004*step+.10*np.sin(step/17+3)),100*np.exp(.00005*step+.14*np.sin(step/23+4))]
    close = paths[kind]
    open_ = close*(1+.002*np.sin(step/7+len(symbol)))
    frame = pd.DataFrame(dict(open=open_, high=np.maximum(open_,close)*1.01, low=np.minimum(open_,close)*.99, close=close, volume=np.repeat(10000000., count)),index=index)
    return DataBundle(asset=find_asset(symbol,'etf'),frame=frame,source='synthetic-fixture')

bundles=[bundle(symbol,kind=i) for i,symbol in enumerate(['SPY','TLT','IEF','GLD','DBC'])]
asset_inputs=[dict(symbol=b.asset.symbol,asset_class='etf') for b in bundles]
cases=[]
for strategy, params, extra in [('all_weather', {}, {}),('sixty_forty', {'equity_target':.7,'rebalance_band':.02,'min_trade_rate':0}, {'cash_buffer':.1,'max_asset_weight':.7}),('risk_parity', {'lookback':126,'covariance_shrinkage':.1},{}),('risk_parity', {'lookback':40,'covariance_shrinkage':1,'min_trade_rate':0}, {'volatility_target':.035,'cash_buffer':.1,'max_asset_weight':.4})]:
    request=PortfolioBacktestRequest(assets=asset_inputs,strategy_id=strategy, params=params, rebalance='monthly',base_currency='USD', persist=False,**extra)
    cases.append({'name':strategy+'-'+str(len(cases)), 'request':request.model_dump(mode='json'),'result':run_portfolio_backtest(request,bundles).model_dump(mode='json')})
(out/'portfolio-parity.json').write_text(json.dumps(dict(markets=[market(b) for b in bundles], cases=cases),allow_nan=False))

shifted=[bundle('SPY',count=90,kind=0,hour_shift=4),bundle('TLT',count=90,kind=1,hour_shift=-8)]
request=PortfolioBacktestRequest(assets=[dict(symbol='SPY',weight=.6),dict(symbol='TLT',weight=.4)],strategy_id='sixty_forty',base_currency='USD',persist=False)
(out/'portfolio-session-parity.json').write_text(json.dumps(dict(markets=[market(b) for b in shifted],request=request.model_dump(mode='json'),result=run_portfolio_backtest(request,shifted).model_dump(mode='json')),allow_nan=False))

source=bundle('SPY',count=360)
research_cases=[]
for enabled in [False,True]:
    request=ResearchRequest(symbol='SPY',asset_class='etf',experiments=[dict(strategy_id='sma_cross',parameter_grid={'fast':[8,12],'slow':[30,45]}),dict(strategy_id='momentum',parameter_grid={'lookback':[12,24]},base_params={'threshold':.003})],walk_forward=dict(enabled=enabled,train_bars=160,test_bars=40,step_bars=40,max_windows=2))
    result=run_research('fixture-job',request,source,Event(),lambda *_:None)
    research_cases.append(dict(name='walk-forward' if enabled else 'holdout',request=request.model_dump(mode='json'),result=result.model_dump(mode='json')))
(out/'research-parity.json').write_text(json.dumps(dict(market=market(source),cases=research_cases),allow_nan=False))

risk=[]
for scale in [.01,.04,.1]:
    returns=np.array([[scale*(math.sin(i/3+j)+.35*math.cos(i/7-j))*(j+1) for j in range(4)] for i in range(100)])
    frame=pd.DataFrame(returns,columns=['A','B','C','D'])
    for shrinkage in [0.,.1,1.]:
        risk.append(dict(rows=returns.tolist(),symbols=list(frame.columns),shrinkage=shrinkage,expected=_risk_parity_weights(frame,shrinkage)))
(out/'risk-parity-optimizer.json').write_text(json.dumps(risk,allow_nan=False))
print(json.dumps({'fixtures':sorted(p.name for p in out.iterdir())}))
