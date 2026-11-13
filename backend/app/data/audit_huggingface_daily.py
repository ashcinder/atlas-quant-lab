"""Compare the pinned HF minute snapshot with locally published raw daily bars.

Outputs a local diagnostic, never alters the source data or claims either source
is correct. Run: python -m app.data.audit_huggingface_daily
"""
from __future__ import annotations
import json
from datetime import UTC, datetime
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
from app.config import DATA_DIR
from app.data.import_huggingface_cn_minutes import project_equities, REPO, REVISION
from app.market_publication import MarketPublication


def main():
    root = DATA_DIR / 'cn-tech' / 'huggingface'
    publication = MarketPublication()
    report = {'dataset': REPO, 'revision': REVISION, 'generated_at': datetime.now(UTC).isoformat(),
              'price_tolerance_yuan': 0.021, 'volume_tolerance_shares': 1,
              'method': 'Compare 241-record sessions with nonzero volume using local raw daily OHLCV; 2026-08-07 partial session excluded.',
              'symbols': {}}
    for symbol, name in project_equities().items():
        code, suffix = symbol.split('.')
        file = root / 'data' / 'stock_1m' / ('SH' if suffix == 'SS' else 'SZ') / (code + '.parquet')
        frame = pq.read_table(file, columns=['timestamp','open','high','low','close','volume']).to_pandas()
        frame['date'] = pd.to_datetime(frame.timestamp).dt.date
        group = frame.groupby('date', sort=True)
        daily = group.agg(open=('open','first'), high=('high','max'), low=('low','min'),
                          close=('close','last'), volume=('volume','sum'), count=('volume','size'))
        active = daily[(daily['count'] == 241) & (daily.volume > 0)]
        m = publication.lookup({'symbol': symbol, 'asset_class':'equity','interval':'1d','adjustment':'auto','data_source':'auto'})
        if not m:
            report['symbols'][symbol] = {'name': name, 'error': '本地未发布日线'}
            continue
        other = publication.bundle(m['dataset_id']).frame.copy()
        other.index = other.index.tz_convert('Asia/Shanghai').date
        joined = active.join(other[['open','high','low','close','volume']], how='inner', rsuffix='_daily')
        differences = {}
        for field in ('open','high','low','close','volume'):
            delta = (joined[field] - joined[field+'_daily']).abs()
            bad = delta > (1 if field == 'volume' else 0.021)
            differences[field] = {'days': int(bad.sum()), 'max_abs': float(delta.max()) if len(delta) else None,
                                  'examples': [{'date': str(date), 'minute': float(joined.loc[date, field]),
                                                'daily': float(joined.loc[date, field+'_daily'])}
                                               for date in joined.index[bad][:5]]}
        report['symbols'][symbol] = {'name': name, 'minute_rows': len(frame),
            'first': str(frame.timestamp.min()), 'last': str(frame.timestamp.max()),
            'complete_nonzero_sessions': len(active), 'zero_volume_sessions': int((daily.volume == 0).sum()),
            'partial_sessions': int((daily['count'] != 241).sum()), 'daily_source': m['source'],
            'daily_dataset_id': m['dataset_id'], 'overlap_sessions': len(joined), 'differences': differences}
        print(symbol, len(joined), differences['high']['days'], differences['low']['days'], flush=True)
    output = root / 'metadata' / 'daily-reconciliation.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('report:', output)

if __name__ == '__main__':
    main()
