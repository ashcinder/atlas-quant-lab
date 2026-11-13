"""Full-history, bar-by-bar cross-language/framework execution audit.

Runs real Atlas TS, vn.py callbacks and RQAlpha callbacks. Unified mode shares
an explicit research ledger, NOT native stock matching/accounting.
"""
import argparse
from datetime import UTC, datetime
import hashlib
import json
import subprocess
import time

import numpy as np
import pandas as pd

from app.backtest.native import run_native
from app.compute_objects import canonical_bytes
from app.config import DATA_DIR, ROOT_DIR
from app.market_publication import MarketPublication
from app.models import BacktestRequest

PERIODS = ('1m','5m','15m','1h','4h','1d','1wk')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intervals',nargs='+',choices=PERIODS,default=list(PERIODS))
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--native-full-baseline',action='store_true',help='Also replay original native accounts over all 1m bars')
    args=parser.parse_args()
    root=DATA_DIR/'cn-tech/huggingface/catl-unified-20261113'
    root.mkdir(parents=True,exist_ok=True)
    path=root/'audit.json'
    report={'created_at':datetime.now(UTC).isoformat(),'scope':'Full available history, no window truncation or account resets',
        'execution_model':'unified','contract':'research-next-open/v1','cases':[],'comparisons':[],'failures':[]}
    if args.resume and path.exists():report=json.loads(path.read_text())
    def checkpoint():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False));tmp.replace(path)
    frontend=ROOT_DIR.parent/'frontend';runner=root/'atlas.mjs'
    subprocess.run([str(frontend/'node_modules/.bin/rolldown'),'scripts/verify-hf-engine.ts','--platform','node','--format','esm','--file',str(runner)],cwd=frontend,check=True,capture_output=True)
    publication=MarketPublication()
    for interval in args.intervals:
        query=dict(symbol='300750.SZ',asset_class='equity',interval=interval,data_source='huggingface',adjustment='raw')
        manifest=publication.lookup(query);frame=publication.bundle(manifest['dataset_id']).frame
        seconds=frame.index.as_unit('ns').asi8//1_000_000_000
        bars=[dict(time=int(t),open=float(o),high=float(h),low=float(l),close=float(c),volume=float(v))
            for t,(o,h,l,c,v) in zip(seconds,frame[['open','high','low','close','volume']].to_numpy(),strict=True)]
        digest=hashlib.sha256(canonical_bytes(bars)).hexdigest()
        request=BacktestRequest(**query,start=frame.index[0],end=frame.index[-1],params={'fast':5,'slow':20},execution_model='unified',persist=False)
        for engine in ('atlas','vnpy','rqalpha'):
            key=f'{interval}-{engine}'
            if any(c['key']==key for c in report['cases']):continue
            print('START',key,len(bars),flush=True)
            started=time.perf_counter()
            try:
                if engine=='atlas':
                    market=dict(asset=manifest['asset'],bars=bars,source=manifest['source'],source_note=manifest['source_note'],interval=interval,adjustment='raw')
                    process=subprocess.run(['node','--max-old-space-size=4096',str(runner)],input=json.dumps(dict(request=request.model_dump(mode='json'),market=market)),text=True,capture_output=True,timeout=600)
                    if process.returncode:raise ValueError(process.stderr[-2000:])
                    result=json.loads(process.stdout)
                else:
                    result=run_native(request.model_copy(update={'backtest_engine':engine}),publication).model_dump(mode='json')
                elapsed=time.perf_counter()-started
                assert result['execution_model']=='unified' and result['execution_contract']=='research-next-open/v1'
                assert result['bars']==bars and len(result['equity'])==len(bars)
                assert len(next(iter(result['indicators'].values())))<=3000
                assert all(np.isfinite(p['equity']) and p['equity']>0 for p in result['equity'])
                pd.DataFrame(result['equity']).to_csv(root/f'{key}-equity.csv.gz',index=False,compression='gzip')
                pd.DataFrame(result['trades']).to_csv(root/f'{key}-trades.csv.gz',index=False,compression='gzip')
                report['cases'].append(dict(key=key,interval=interval,engine=engine,bars=len(bars),start=frame.index[0].isoformat(),end=frame.index[-1].isoformat(),
                    dataset_id=manifest['dataset_id'],input_sha256=digest,metrics=result['metrics'],elapsed_seconds=elapsed,
                    final_equity=result['equity'][-1]['equity'],warnings=result['warnings'],version=result.get('engine_version') or 'browser-ts/v1'))
                report['failures']=[f for f in report['failures'] if f['key']!=key]
                print('PASS',key,'return',result['metrics']['total_return'],'trades',len(result['trades']),'seconds',round(elapsed,2),flush=True)
                del result
            except Exception as exc:
                report['failures']=[f for f in report['failures'] if f['key']!=key]+[dict(key=key,error=str(exc))]
                print('FAIL',key,exc,flush=True)
            checkpoint()
        if all(any(c['key']==f'{interval}-{engine}' for c in report['cases']) for engine in ('atlas','vnpy','rqalpha')):
            base=pd.read_csv(root/f'{interval}-atlas-equity.csv.gz')
            trades=pd.read_csv(root/f'{interval}-atlas-trades.csv.gz')
            for engine in ('vnpy','rqalpha'):
                actual=pd.read_csv(root/f'{interval}-{engine}-equity.csv.gz');fills=pd.read_csv(root/f'{interval}-{engine}-trades.csv.gz')
                diff=float(np.max(np.abs(base.equity-actual.equity)))
                np.testing.assert_array_equal(base.time,actual.time)
                np.testing.assert_allclose(base[['equity','exposure']],actual[['equity','exposure']],rtol=1e-10,atol=1e-6)
                assert len(trades)==len(fills)
                assert trades[['time','side','reason']].equals(fills[['time','side','reason']])
                for field in ('price','quantity','fee','slippage_cost','cash_after','position_after','realized_pnl'):
                    np.testing.assert_allclose(trades[field],fills[field],rtol=1e-10,atol=1e-6,equal_nan=True)
                comparison=dict(interval=interval,engine=engine,bars=len(base),trades=len(trades),maximum_equity_difference_cny=diff,status='pass')
                report['comparisons']=[c for c in report['comparisons'] if (c['interval'],c['engine'])!=(interval,engine)]+[comparison]
                print('MATCH',interval,engine,'all bars and fills; max equity difference',diff,flush=True)
            checkpoint()
    if args.native_full_baseline:
        query=dict(symbol='300750.SZ',asset_class='equity',interval='1m',data_source='huggingface',adjustment='raw')
        manifest=publication.lookup(query);frame=publication.bundle(manifest['dataset_id']).frame
        for engine in ('vnpy','rqalpha'):
            if any(c['engine']==engine for c in report.get('native_full_baseline',[])):continue
            request=BacktestRequest(**query,backtest_engine=engine,execution_model='native',start=frame.index[0],end=frame.index[-1],params={'fast':5,'slow':20},persist=False)
            print('START native-full',engine,len(frame),flush=True);started=time.perf_counter()
            result=run_native(request,publication).model_dump(mode='json')
            assert len(result['bars'])==len(frame)==len(result['equity'])
            pd.DataFrame(result['equity']).to_csv(root/f'1m-{engine}-native-equity.csv.gz',index=False,compression='gzip')
            pd.DataFrame(result['trades']).to_csv(root/f'1m-{engine}-native-trades.csv.gz',index=False,compression='gzip')
            report.setdefault('native_full_baseline',[]).append(dict(engine=engine,bars=len(frame),execution_model='native',metrics=result['metrics'],final_equity=result['equity'][-1]['equity'],elapsed_seconds=time.perf_counter()-started))
            print('PASS native-full',engine,result['metrics']['total_return'],flush=True);checkpoint();del result
    report['completed_at']=datetime.now(UTC).isoformat();checkpoint()
    print('REPORT',path,'cases',len(report['cases']),'comparisons',len(report['comparisons']),'failures',len(report['failures']),flush=True)
    return int(bool(report['failures']))


if __name__=='__main__':raise SystemExit(main())
