"""Run thesis prerequisites with public frozen data and the exact API image.
No running application volumes, credentials, network or model calls are used.
"""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE = 'sha256:1a22da2adf85b43b41c58afa507d75c0c8c56f7274a52619ddba246d12fbaa27'
raw = (ROOT / 'market-binance.json').read_bytes()
data = json.loads(raw)
PROGRAM = r'''
import hashlib,json
from datetime import datetime,timezone
from threading import Event
import pandas as pd
from app.catalog import find_asset
from app.data.service import DataBundle
from app.backtest import run_backtest
from app.models import BacktestRequest,ResearchRequest,ResearchExperiment,WalkForwardConfig
from app.research import run_research
from app.strategies.catalog import default_params

index=pd.to_datetime([b[0] for b in DATA['bars']],unit='ms',utc=True)
frame=pd.DataFrame([[float(b[i]) for i in range(1,6)] for b in DATA['bars']],columns=['open','high','low','close','volume'],index=index)
assert len(frame)==600 and frame.index.is_monotonic_increasing and not frame.index.duplicated().any()
assert (frame['volume']>0).all()
asset=find_asset('BTC-USD','crypto')
bundle=DataBundle(asset=asset,frame=frame,source='binance',source_note='Frozen public Binance BTCUSDT daily klines; no credentials')
params={'fast':10,'slow':40}
common=dict(symbol='BTC-USD',asset_class='crypto',interval='1d',data_source='binance',strategy_id='sma_cross',params=params,initial_capital=100000,spread_rate=0.0005,persist=False)
runs=[]
for commission,slippage in [(0.001,0.0005),(0.003,0.002)]:
 request=BacktestRequest(**common,commission_rate=commission,slippage_rate=slippage)
 result=run_backtest(request,bundle)
 assert result.metrics['trade_count']==len(result.trades)>0
 assert result.evaluation.version=='evaluation_v1'
 runs.append({'request':request.model_dump(mode='json'),'result':result.model_dump(mode='json',exclude={'bars','indicators','equity'})})
assert runs[0]['result']['metrics']['total_return'] != runs[1]['result']['metrics']['total_return']
research_request=ResearchRequest(symbol='BTC-USD',asset_class='crypto',interval='1d',data_source='binance',initial_capital=100000,commission_rate=0.001,slippage_rate=0.0005,spread_rate=0.0005,experiments=[ResearchExperiment(strategy_id='sma_cross',base_params=params)],holdout_ratio=0.2,walk_forward=WalkForwardConfig(enabled=True,train_bars=240,test_bars=120,step_bars=120,max_windows=3))
research=run_research('thesis-docker-prerequisite-20261030',research_request,bundle,Event(),lambda *_:None)
candidate=next(c for c in research.candidates if c.test_metrics)
assert candidate.params=={**default_params("sma_cross"),**params},candidate.params
split=int(len(frame)*0.8)
checks=[]
for name,part,expected in [('train',frame.iloc[:split],candidate.train_metrics),('test',frame.iloc[split:],candidate.test_metrics)]:
 check=run_backtest(BacktestRequest(**common,commission_rate=0.001,slippage_rate=0.0005),DataBundle(asset=asset,frame=part.copy(),source='binance'))
 for key in ['total_return','sharpe','max_drawdown','trade_count']:
  assert check.metrics[key]==expected[key],(name,key,check.metrics[key],expected[key])
 checks.append({'part':name,'bars':len(part),'start':part.index[0].isoformat(),'end':part.index[-1].isoformat(),'metrics':check.metrics})
assert len(research.walk_forward)==3
assert all(w.train_end<w.test_start for w in research.walk_forward)
print(json.dumps({'verified_at':datetime.now(timezone.utc).isoformat(),'image':IMAGE,'market_sha256':MARKET_SHA,'public_source_url':DATA['url'],'market':{'symbol':'BTCUSDT','bars':len(frame),'start':index[0].isoformat(),'end':index[-1].isoformat()},'isolation':{'network':'none','readonly_root':True,'application_volumes':False},'backtests':runs,'research_request':research_request.model_dump(mode='json'),'research':research.model_dump(mode='json'),'independent_split_checks':checks,'scope':'Calculation/tool compatibility verified; not an authenticated UI, diagnosis Agent or real model test'},ensure_ascii=False,allow_nan=False))
'''
payload = 'DATA='+repr(data)+'\nIMAGE='+repr(IMAGE)+'\nMARKET_SHA='+repr(hashlib.sha256(raw).hexdigest())+'\n'+PROGRAM
cmd=['docker','run','--rm','-i','--platform','linux/amd64','--network','none','--read-only','--tmpfs','/tmp:rw,size=128m','--memory','1g','--cpus','1','--workdir','/app/backend','-e','ATLAS_DATA_DIR=/tmp/thesis-probe','--entrypoint','python',IMAGE,'-']
proc=subprocess.run(cmd,input=payload,text=True,capture_output=True,timeout=150)
if proc.returncode:
 raise RuntimeError(proc.stderr[-4000:])
result=json.loads(proc.stdout)
(ROOT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'market':result['market'],'cost_comparison':[{'commission_rate':x['request']['commission_rate'],'slippage_rate':x['request']['slippage_rate'],'trade_count':x['result']['metrics']['trade_count'],'total_return':x['result']['metrics']['total_return']} for x in result['backtests']],'split_checks':[{'part':x['part'],'bars':x['bars'],'trade_count':x['metrics']['trade_count']} for x in result['independent_split_checks']],'walk_forward_windows':len(result['research']['walk_forward']),'research_warnings':result['research']['warnings'],'evaluation':[{'id':d['id'],'status':d['status']} for d in result['backtests'][0]['result']['evaluation']['dimensions']]},ensure_ascii=False,indent=2))
