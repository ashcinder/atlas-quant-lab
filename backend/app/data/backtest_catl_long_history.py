"""Long-window CATL tests using production Atlas TS, vn.py and RQAlpha.

Run from backend: .venv/bin/python -m app.data.backtest_catl_long_history [--resume]
No parameter search, fabricated bars, segmented account resets or user-history writes.
"""
import argparse
from datetime import UTC, datetime
import gzip
import hashlib
import json
import subprocess
import time
import traceback

import numpy as np
import pandas as pd

from app.backtest.native import run_native
from app.compute_objects import canonical_bytes
from app.config import DATA_DIR, ROOT_DIR
from app.data.import_huggingface_cn_minutes import REVISION, SCHEMA
from app.market_publication import MarketPublication
from app.models import BacktestRequest

INTERVALS = ('1m','5m','15m','1h','4h','1d','1wk')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    root=DATA_DIR/'cn-tech/huggingface/catl-long-history-20261112'
    root.mkdir(parents=True,exist_ok=True)
    output=root/'summary.json'
    settings=dict(symbol='300750.SZ',asset_class='equity',data_source='huggingface',adjustment='raw',
        strategy_id='sma_cross',params={'fast':5,'slow':20},initial_capital=100000,
        commission_rate=.001,slippage_rate=.0005,spread_rate=.0005,max_position=.95,
        max_participation_rate=.01,stop_loss=None,take_profit=None,persist=False)
    report=dict(created_at=datetime.now(UTC).isoformat(),revision=REVISION,schema=SCHEMA,settings=settings,
        atlas_runtime='Production TypeScript engine bundled for Node; not a browser UI test',
        cases=[],boundary_checks=[],failures=[])
    if args.resume and output.exists():
        report=json.loads(output.read_text());report.pop('completed_at',None)
    def checkpoint():
        temp=output.with_suffix('.tmp')
        temp.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False));temp.replace(output)
    frontend=ROOT_DIR.parent/'frontend'
    runner=root/'atlas.mjs'
    subprocess.run([str(frontend/'node_modules/.bin/rolldown'),'scripts/verify-hf-engine.ts',
        '--platform','node','--format','esm','--file',str(runner)],cwd=frontend,check=True,capture_output=True)
    p=MarketPublication()
    for interval in INTERVALS:
        m=p.lookup({**settings,'interval':interval})
        full=p.bundle(m['dataset_id']).frame
        all_bars=[dict(time=int(stamp.timestamp()),**{k:float(row[k]) for k in ('open','high','low','close','volume')}) for stamp,row in full.iterrows()]
        for engine in ('atlas','vnpy','rqalpha'):
            windows=['full'] if engine=='atlas' or len(all_bars)<=100000 else ['latest-100000']
            if engine=='atlas' and len(all_bars)>100000:windows.append('latest-100000')
            for window in windows:
                key=f'{interval}-{engine}-{window}'
                if any(c['key']==key for c in report['cases']):continue
                bars=all_bars if window=='full' else all_bars[-100000:]
                r=BacktestRequest(**settings,interval=interval,backtest_engine=engine,
                    start=datetime.fromtimestamp(bars[0]['time'],UTC),end=datetime.fromtimestamp(bars[-1]['time'],UTC))
                print(f'START {key} bars={len(bars)} {r.start.isoformat()} .. {r.end.isoformat()}',flush=True)
                started=time.perf_counter()
                try:
                    if engine=='atlas':
                        market=dict(asset=m['asset'],bars=bars,source=m['source'],source_note=m['source_note'],interval=interval,adjustment='raw')
                        process=subprocess.run(['node','--max-old-space-size=6144',str(runner)],input=json.dumps(dict(request=r.model_dump(mode='json'),market=market)),text=True,capture_output=True,timeout=600)
                        if process.returncode:raise RuntimeError(process.stderr[-4000:])
                        result=json.loads(process.stdout)
                    else:result=run_native(r,p).model_dump(mode='json')
                    elapsed=time.perf_counter()-started
                    assert result['bars']==bars,'Engine OHLCV differs from publication'
                    assert len(result['equity'])==len(bars),'Incomplete account replay'
                    assert all(np.isfinite(point['equity']) and point['equity']>0 for point in result['equity']),'Invalid equity'
                    by_time={b['time']:b for b in bars}
                    assert all(t['time'] in by_time and by_time[t['time']]['volume']>0 and t['cash_after']>=-1e-6 and t['position_after']>=-1e-6 for t in result['trades']),'Invalid trade or negative account'
                    result_path=root/f'{key}.json.gz'
                    with gzip.open(result_path,'wt',encoding='utf-8') as handle:json.dump(result,handle,ensure_ascii=False,allow_nan=False)
                    pd.DataFrame(result['trades']).to_csv(root/f'{key}-trades.csv.gz',index=False,compression='gzip')
                    pd.DataFrame(result['equity']).to_csv(root/f'{key}-equity.csv.gz',index=False,compression='gzip')
                    report['cases'].append(dict(key=key,interval=interval,engine=engine,window=window,
                        bars=len(bars),full_available=len(all_bars),start=r.start.isoformat(),end=r.end.isoformat(),
                        dataset_id=m['dataset_id'],input_sha256=hashlib.sha256(canonical_bytes(bars)).hexdigest(),
                        elapsed_seconds=elapsed,metrics=result['metrics'],final_equity=result['equity'][-1]['equity'],
                        warnings=result['warnings'],engine_version=result.get('engine_version') or 'browser-ts/v1',result_file=str(result_path)))
                    report['failures']=[f for f in report['failures'] if f['key']!=key]
                    print(f'PASS {key}: return={result["metrics"]["total_return"]:.6f} dd={result["metrics"]["max_drawdown"]:.6f} trades={len(result["trades"])} elapsed={elapsed:.2f}s',flush=True)
                except Exception as exc:
                    failure=dict(key=key,interval=interval,engine=engine,window=window,bars=len(bars),error=str(exc),elapsed_seconds=time.perf_counter()-started)
                    report['failures']=[f for f in report['failures'] if f['key']!=key]+[failure]
                    (root/f'{key}.error.txt').write_text(traceback.format_exc())
                    print(f'FAIL {key}: {exc}',flush=True)
                checkpoint()
        if len(all_bars)>100000 and not report['boundary_checks']:
            for engine in ('vnpy','rqalpha'):
                r=BacktestRequest(**settings,interval=interval,backtest_engine=engine,start=full.index[0],end=full.index[-1])
                try:run_native(r,p);boundary=dict(engine=engine,status='unexpectedly-accepted')
                except ValueError as exc:boundary=dict(engine=engine,status='rejected',message=str(exc),requested_bars=len(full))
                report['boundary_checks'].append(boundary);checkpoint()
    report['completed_at']=datetime.now(UTC).isoformat();checkpoint()
    print(json.dumps(dict(report=str(output),passed=len(report['cases']),failed=len(report['failures'])),ensure_ascii=False),flush=True)
    return 1 if report['failures'] else 0


if __name__=='__main__':raise SystemExit(main())
