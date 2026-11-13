"""Replay independent strategies through production Atlas, vn.py and RQAlpha."""
import argparse
from datetime import UTC, datetime
import json
import subprocess
import time

import numpy as np

from app.config import DATA_DIR, ROOT_DIR
from app.market_publication import MarketPublication
from app.models import BacktestRequest
from app.backtest.native import run_native
from app.backtest.engine import serialize_bars
from app.python_strategy import compile_program


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval',default='1d')
    parser.add_argument('--portable-only',action='store_true')
    parser.add_argument('--native',action='store_true')
    args=parser.parse_args()
    root=DATA_DIR/'cn-tech/portable-strategy-audit';root.mkdir(parents=True,exist_ok=True)
    front=ROOT_DIR.parent/'frontend';runner=root/'atlas.mjs'
    subprocess.run([str(front/'node_modules/.bin/rolldown'),'scripts/verify-hf-engine.ts','--platform','node','--format','esm','--file',str(runner)],cwd=front,check=True,capture_output=True)
    query=dict(symbol='300750.SZ',asset_class='equity',interval=args.interval,data_source='huggingface',adjustment='raw')
    publications=MarketPublication();manifest=publications.lookup(query)
    frame=publications.bundle(manifest['dataset_id']).frame
    bars=[b.model_dump() for b in serialize_bars(frame)]
    input_path=root/f'catl-{args.interval}.json'
    input_path.write_text(json.dumps(dict(dataset_id=manifest['dataset_id'],bars=bars)))
    cases=[]
    if not args.portable_only:
        from app.strategies.catalog import STRATEGIES
        cases=[(s.id,dict(strategy_id=s.id)) for s in STRATEGIES if s.mode=='single']
        cases.append(('filtered_sma',dict(strategy_id='sma_cross',params={'fast':5,'slow':20,'confirm_bars':2,'min_gap':.01,'trend_filter':100})))
        cases.append(('bounded_python',dict(strategy_id='python_bounded',python_source='def target_bps(index, close, sma):\n    return (6000 if sma(5) > sma(20) else 0) if index >= 20 else 0\n')))
        cases.append(('visual_custom',dict(strategy_id='my_visual',custom_strategy=dict(id='my_visual',name='自定义均线',description='独立条件',
            entry=dict(kind='condition',left=dict(field='close'),operator='crosses_above',right_indicator=dict(field='sma',period=20)),
            exit=dict(kind='condition',left=dict(field='close'),operator='crosses_below',right_indicator=dict(field='sma',period=20)),target_position=.8))))
    for filename,name in [('stateful_rsi.py','有状态RSI'),('pandas_momentum.py','Pandas动量')]:
        if args.interval!='1d' and filename=='pandas_momentum.py':continue
        source_path=ROOT_DIR.parent/'strategy/examples/portable_python'/filename
        p=subprocess.run(['node','scripts/test-portable-python.mjs',str(input_path),str(source_path),name],cwd=front,text=True,capture_output=True,timeout=600)
        if p.returncode:raise RuntimeError(p.stderr[-2000:])
        print('WASM',name,p.stdout.strip(),flush=True)
        cases.append((filename[:-3],dict(strategy_id='python_portable',portable_python=source_path.read_text(),portable_plan=json.loads(input_path.with_suffix('.json.plan.json').read_text()))))
    report=dict(created_at=datetime.now(UTC).isoformat(),interval=args.interval,bars=len(bars),start=frame.index[0].isoformat(),end=frame.index[-1].isoformat(),dataset_id=manifest['dataset_id'],execution_model='native' if args.native else 'unified',cases=[],failures=[])
    for name,extra in cases:
        results={}
        for engine in ('atlas','vnpy','rqalpha'):
            if args.native and engine=='atlas':continue
            print('START',name,engine,flush=True);started=time.perf_counter()
            try:
                request=BacktestRequest(**query,backtest_engine=engine,execution_model=report['execution_model'],start=frame.index[0],end=frame.index[-1],persist=False,**extra)
                if engine=='atlas':
                    payload=request.model_dump(mode='json')
                    if request.python_source:payload['python_program']=compile_program(request.python_source)
                    market=dict(asset=manifest['asset'],bars=bars,source=manifest['source'],source_note=manifest['source_note'],interval=args.interval,adjustment='raw')
                    process=subprocess.run(['node','--max-old-space-size=4096',str(runner)],input=json.dumps(dict(request=payload,market=market)),text=True,capture_output=True,timeout=600)
                    if process.returncode:raise RuntimeError(process.stderr[-2000:])
                    result=json.loads(process.stdout)
                else:result=run_native(request,publications).model_dump(mode='json')
                assert len(result['equity'])==len(result['bars'])==len(bars)
                assert result['strategy']['id']==extra.get('custom_strategy',{}).get('id',extra['strategy_id'])
                results[engine]=result
                report['cases'].append(dict(strategy=name,engine=engine,bars=len(bars),trades=len(result['trades']),metrics=result['metrics'],elapsed_seconds=time.perf_counter()-started))
                print('PASS',name,engine,'return',result['metrics']['total_return'],'trades',len(result['trades']),flush=True)
            except Exception as exc:
                report['failures'].append(dict(strategy=name,engine=engine,error=str(exc)));print('FAIL',name,engine,exc,flush=True)
        if not args.native and len(results)==3:
            try:
                base=results['atlas']
                for engine in ('vnpy','rqalpha'):
                    other=results[engine]
                    np.testing.assert_allclose([[p['equity'],p['exposure']] for p in base['equity']],[[p['equity'],p['exposure']] for p in other['equity']],rtol=1e-10,atol=1e-6)
                    assert len(base['trades'])==len(other['trades'])
                    assert [(t['time'],t['side']) for t in base['trades']]==[(t['time'],t['side']) for t in other['trades']]
                    for field in ('price','quantity','fee','slippage_cost','cash_after','position_after','realized_pnl'):
                        np.testing.assert_allclose([t[field] if t[field] is not None else np.nan for t in base['trades']],[t[field] if t[field] is not None else np.nan for t in other['trades']],rtol=1e-10,atol=1e-6,equal_nan=True)
                print('MATCH',name,'all equity and fills',flush=True)
            except Exception as exc:report['failures'].append(dict(strategy=name,engine='comparison',error=str(exc)));print('MISMATCH',name,exc,flush=True)
        path=root/f"audit-{args.interval}-{report['execution_model']}.json"
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    print('REPORT',path,'cases',len(report['cases']),'failures',len(report['failures']),flush=True)
    return int(bool(report['failures']))


if __name__=='__main__':raise SystemExit(main())
