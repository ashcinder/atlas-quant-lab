"""Publish deterministic extended history inside a synthetic fixture only."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

if os.environ.get('ATLAS_E2E_ISOLATED') != '1' or os.environ.get('ATLAS_DATA_DIR') != '/work/data' or not Path('/work/fixture.json').is_file():
    raise RuntimeError('An initialized synthetic fixture volume is required')
sys.path.insert(0, '/app/backend')
import pandas as pd
from app.catalog import find_asset
from app.data.service import DataBundle
from app.market_publication import MarketPublication
from temporary_market import checkpoint, restore

publications = MarketPublication()
if sys.argv[1:] == ['restore']:
    print(json.dumps(restore(publications, 'history')))
    sys.exit(0)

count = int(sys.argv[1])
if count not in {1000, 2000}:
    raise ValueError('Two fixed history phases are supported')
end = int(datetime.now(UTC).timestamp()) // 86400 * 86400 - 86400
index = pd.date_range(end=pd.Timestamp(end, unit='s', tz='UTC'), periods=count, freq='D')
# Index by date so overlapping bars have exactly the same OHLCV bytes.
rows = []
for stamp in index:
    close = 100 + int(stamp.timestamp() // 86400) % 71
    rows.append({'open': close, 'high': close + 1, 'low': close - 1, 'close': close, 'volume': 1000000})
bundle = DataBundle(find_asset('BTC-USD', 'crypto'), pd.DataFrame(rows, index=index),
                    'binance:synthetic-e2e-history', 'Synthetic overlapping historical fixture, not real provider evidence', datetime.now(UTC))
checkpoint(publications, 'history', ['auto', 'binance'])
for source in ('auto', 'binance'):
    result = publications.publish({'symbol': 'BTC-USD', 'asset_class': 'crypto', 'interval': '1d',
                                   'adjustment': 'auto', 'data_source': source}, bundle)
print(json.dumps({'count': result['count'], 'start': result['start'], 'end': result['end']}))
