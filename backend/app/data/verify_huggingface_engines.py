"""Audit all project HF publications and replay actual engines on the same bars.

Run after import: python -m app.data.verify_huggingface_engines
Writes a local report, never saves backtests into a user's history.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import pandas as pd

from app.backtest.native import run_native
from app.compute_objects import canonical_bytes
from app.config import DATA_DIR, ROOT_DIR
from app.data.import_huggingface_cn_minutes import project_equities, REVISION, SOURCE, SCHEMA
from app.market_publication import MarketPublication
from app.models import BacktestRequest

INTERVALS = ('1m','5m','15m','1h','4h','1d','1wk')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', nargs='+')
    parser.add_argument('--intervals', nargs='+', choices=INTERVALS, default=list(INTERVALS))
    parser.add_argument('--resume', action='store_true', help='Retry failed or unfinished cases in the existing report')
    parser.add_argument('--full-integrity', action='store_true', help='Read and hash every published chunk')
    args = parser.parse_args()
    publication = MarketPublication()
    frontend = ROOT_DIR.parent / 'frontend'
    output = DATA_DIR / 'cn-tech/huggingface/metadata/three-engine-acceptance.json'
    report = {'revision':REVISION,'schema':SCHEMA,'created_at':datetime.now(UTC).isoformat(),
              'scope':'Last 128 actual bars of every selected stock/interval; research SMA 5/20; no fabricated bars',
              'integrity':[], 'runs':[], 'failures':[]}

    if args.resume and output.exists():
        previous=json.loads(output.read_text())
        if previous.get('revision') != REVISION or previous.get('schema') != SCHEMA:
            raise ValueError('旧报告不属于当前固定版本')
        report=previous
        report.pop('completed_at',None)
    def checkpoint():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
        temporary.replace(output)

    with tempfile.TemporaryDirectory(prefix='atlas-hf-acceptance-') as directory:
        runner = Path(directory) / 'atlas.mjs'
        subprocess.run([str(frontend/'node_modules/.bin/rolldown'), 'scripts/verify-hf-engine.ts',
            '--platform','node','--format','esm','--file',str(runner)],cwd=frontend,check=True,capture_output=True)

        def verify(symbol, interval):
            query = dict(symbol=symbol,asset_class='equity',interval=interval,adjustment='raw',data_source='huggingface')
            manifest = publication.lookup(query)
            if not manifest or manifest['source']!=SOURCE or SCHEMA not in manifest['source_note']:
                raise ValueError(f'{symbol}/{interval}: normalized publication missing')
            parts = manifest['chunks'] if args.full_integrity else manifest['chunks'][-1:]
            previous = None
            for part in parts:
                bars = publication.objects.read('public',part['sha256'])['bars']
                assert len(bars)==part['count'] and bars[0]['time']==part['start'] and bars[-1]['time']==part['end']
                for b in bars:
                    assert previous is None or previous < b['time']
                    assert np.isfinite(list(b.values())).all() and b['low']>0 and b['volume']>=0
                    assert b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']
                    previous = b['time']
            tail = publication.objects.read('public',manifest['chunks'][-1]['sha256'])['bars']
            if len(tail)<128 and len(manifest['chunks'])>1:
                tail = publication.objects.read('public',manifest['chunks'][-2]['sha256'])['bars']+tail
            tail = tail[-128:]
            request = BacktestRequest(**query,start=datetime.fromtimestamp(tail[0]['time'],UTC),
                end=datetime.fromtimestamp(tail[-1]['time'],UTC),params={'fast':5,'slow':20},persist=False)
            fingerprint = hashlib.sha256(canonical_bytes(tail)).hexdigest()
            runs = []
            for engine in ('atlas','vnpy','rqalpha'):
                if engine=='atlas':
                    market = dict(asset=manifest['asset'],bars=tail,source=SOURCE,source_note=manifest['source_note'],interval=interval,adjustment='raw')
                    process=subprocess.run(['node',str(runner)],input=json.dumps(dict(request=request.model_dump(mode='json'),market=market)),text=True,capture_output=True,timeout=120)
                    if process.returncode:
                        raise ValueError(f'Atlas failed: {process.stderr[-500:]}')
                    result=json.loads(process.stdout)
                else:
                    result=run_native(request.model_copy(update={'backtest_engine':engine}),publication).model_dump(mode='json')
                assert result['bars']==tail, f'{engine}: OHLCV changed'
                assert len(result['equity'])==len(tail), f'{engine}: account snapshot count mismatch'
                assert all(np.isfinite(point['equity']) and point['equity']>0 for point in result['equity']), f'{engine}: invalid or nonpositive equity'
                by_time={b['time']:b for b in tail}
                assert all(t['time'] in by_time and by_time[t['time']]['volume']>0 and t['cash_after']>=-1e-6 and t['position_after']>=-1e-6 for t in result['trades']), f'{engine}: trade outside input bars, zero-volume execution, or negative account balance'
                runs.append(dict(symbol=symbol,interval=interval,engine=engine,dataset_id=manifest['dataset_id'],
                    input_sha256=fingerprint,bars=len(tail),trades=len(result['trades']),
                    total_return=result['metrics']['total_return'],engine_version=result.get('engine_version') or 'browser-ts/v1'))
            return dict(symbol=symbol,interval=interval,count=manifest['count'],chunks_checked=len(parts)),runs

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures={pool.submit(verify,symbol,interval):(symbol,interval)
                for symbol in (args.symbols or project_equities()) for interval in args.intervals
                if not any(row['symbol']==symbol and row['interval']==interval for row in report['integrity'])}
            for future in as_completed(futures):
                symbol,interval=futures[future]
                report['failures']=[row for row in report['failures'] if (row['symbol'],row['interval'])!=(symbol,interval)]
                try:
                    integrity,runs=future.result()
                    report['integrity'].append(integrity);report['runs'].extend(runs)
                    print(f'PASS {symbol} {interval}: atlas/vnpy/rqalpha',flush=True)
                except Exception as exc:
                    report['failures'].append(dict(symbol=symbol,interval=interval,error=str(exc)))
                    print(f'FAIL {symbol} {interval}: {exc}',flush=True)
                checkpoint()
    report['completed_at']=datetime.now(UTC).isoformat();checkpoint()
    print(json.dumps({'report':str(output),'runs':len(report['runs']),'failures':len(report['failures'])}),flush=True)
    return 1 if report['failures'] else 0


if __name__=='__main__':
    raise SystemExit(main())
