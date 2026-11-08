import sys,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
import pandas as pd
from app.models import Asset,BacktestRequest
from app.data.service import DataBundle
from app.backtest.engine import run_backtest
from app.strategies.catalog import list_strategies
from app.python_strategy import compile_program
out=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'.artifacts/browser-compute-fixtures/single.json'
out.parent.mkdir(parents=True,exist_ok=True)
bars=[]
for i in range(430):
 c=100+0.025*i+18*math.sin(i*.10)+6*math.sin(i*.37)
 o=c*(1+0.002*math.sin(i*.74));bars.append(dict(time=1706659200+i*86400,open=o,high=max(c,o)+2,low=min(c,o)-2,close=c,volume=0 if i%29==0 else (5 if i%7==0 else 1000)))
asset=Asset(symbol='TEST',name='Test',asset_class='crypto',exchange='fixture',currency='USD')
frame=pd.DataFrame(bars);frame.index=pd.to_datetime(frame.pop('time'),unit='s',utc=True)
bundle=DataBundle(asset=asset,frame=frame,source='fixture')
cases=[]
base=dict(initial_capital=100000,commission_rate=.001,slippage_rate=.0005,spread_rate=.0005,max_position=.95,max_participation_rate=.01)
for s in list_strategies('single'):
 r=dict(base,strategy_id=s.id,params={})
 if s.id=='scheduled_dca':r['params']=dict(unit='months',every=1,amount=2000)
 cases.append((s.id,r,None))
cases.extend([
 ('stops',dict(base,strategy_id='arithmetic_grid',params={},stop_loss=.04,take_profit=.07),None),
 ('pipeline',dict(base,strategy_id='ema_cross',params={},execution_pipeline=dict(max_position=.4,commission_rate=.003,slippage_rate=.002,max_participation_rate=.02)),None),
 ('custom',dict(base,strategy_id='custom',custom_strategy=dict(id='fixture_custom',name='Fixture',description='test',entry=dict(kind='condition',left=dict(field='rsi',period=14),operator='lt',right_value=35),exit=dict(kind='condition',left=dict(field='rsi',period=14),operator='gt',right_value=58),target_position=.7)),None),
 ('python',dict(base,strategy_id='python_bounded',python_source='def strategy(ctx):\n    return 9000 if ctx.close(0) > ctx.sma(15) else 0\n'),None),
])
# Compile actual bounded subset; use a known accepted source from compiler examples.
cases[-1]=('python',dict(base,strategy_id='python_bounded'),[{'close':0},{'sma':15},'gt',{'const':9000},{'const':0},'select'])
outputs=[]
for name,request,program in cases:
 req=BacktestRequest(**request)
 result=run_backtest(req,bundle,supplied_program=program).model_dump(mode='json')
 if program:request['python_program']=program
 outputs.append(dict(name=name,request=request,result=result))
out.write_text(json.dumps(dict(market=dict(asset=asset.model_dump(mode='json'),bars=bars,source='fixture'),cases=outputs),ensure_ascii=False,allow_nan=False))
print(f'{len(outputs)} fixtures -> {out}')
# A compact checked-in oracle reuses common bars/indicators across all cases.
import gzip
compact=dict(market=dict(asset=asset.model_dump(mode='json'),bars=bars,source='fixture'),indicators=outputs[0]['result']['indicators'],cases=[])
for case in outputs:
 compact['cases'].append(dict(case,result={k:v for k,v in case['result'].items() if k not in {'bars','indicators'}}))
packed=out.parent/'single-engine-python-v1.json.gz';packed.parent.mkdir(parents=True,exist_ok=True)
packed.write_bytes(gzip.compress(json.dumps(compact,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),mtime=0))
print(f'Compact oracle -> {packed}')
