"""Regression coverage for the canonical HF feed and native minute adapters."""
import pandas as pd
import pytest

from app.data.import_huggingface_cn_minutes import aggregate_minutes, aggregate_days, aggregate_weeks, publish_frame
from app.models import BacktestRequest
from app.backtest.native import validate_native


def session():
    index = pd.date_range('2025-01-02 09:30', periods=121, freq='min', tz='Asia/Shanghai').append(
        pd.date_range('2025-01-02 13:01', periods=120, freq='min', tz='Asia/Shanghai'))
    return pd.DataFrame(dict(open=10., high=11., low=9., close=10.5, volume=100.), index=index.tz_convert('UTC'))


@pytest.mark.parametrize('period,count', [(1,240),(5,48),(15,16),(60,4)])
def test_complete_sessions_preserve_auction_volume_and_use_open_labels(period, count):
    frame = session()
    bars = aggregate_minutes(frame, period)
    assert len(bars) == count
    assert bars.index[0] == frame.index[0]
    assert bars.volume.sum() == frame.volume.sum()
    assert bars.index[-1].tz_convert('Asia/Shanghai').strftime('%H:%M') == {1:'14:59',5:'14:55',15:'14:45',60:'14:00'}[period]


def test_missing_minute_drops_only_its_bucket_without_crossing_lunch():
    frame = session().drop(pd.Timestamp('2025-01-02 10:02',tz='Asia/Shanghai'))
    bars = aggregate_minutes(frame, 5)
    assert len(bars) == 47
    assert pd.Timestamp('2025-01-02 10:00',tz='Asia/Shanghai') not in bars.index
    assert not any(t.hour == 12 for t in bars.index.tz_convert('Asia/Shanghai'))


@pytest.mark.parametrize('engine',['vnpy','rqalpha'])
@pytest.mark.parametrize('interval',['1m','5m','15m','1h','4h','1d','1wk'])
def test_native_accepts_explicit_hf_published_intervals(engine, interval):
    request = BacktestRequest(backtest_engine=engine, symbol='300750.SZ', asset_class='equity',
        data_source='huggingface', adjustment='raw', interval=interval,
        start='2025-01-02', end='2025-06-30', params={'fast':5,'slow':20})
    validate_native(request)


def test_daily_weekly_aggregation_excludes_partial_sessions_and_incomplete_weeks():
    first = session()
    second = first.copy()
    second.index += pd.Timedelta(days=1)
    partial = first.iloc[:52].copy()
    partial.index += pd.Timedelta(days=4)
    daily = aggregate_days(pd.concat([first, second, partial]))
    assert len(daily) == 2
    assert daily.volume.sum() == first.volume.sum() * 2
    weeks = aggregate_weeks(daily, {'2025-01-02', '2025-01-03'})
    assert len(weeks) == 1 and weeks.volume.iloc[0] == daily.volume.sum()
    with pytest.raises(ValueError, match='完整周线'):
        aggregate_weeks(daily, {'2025-01-01', '2025-01-02', '2025-01-03'})


def test_publication_coverage_and_ohlcv_are_immutable(tmp_path):
    import hashlib
    from datetime import UTC, datetime
    from app.compute_objects import ComputeObjects, canonical_bytes
    from app.market_publication import MarketPublication
    p = MarketPublication(tmp_path/'market.db', ComputeObjects(tmp_path/'objects'))
    frame = aggregate_minutes(session(), 5)
    manifest = publish_frame(p,'300750.SZ','5m',frame,datetime(2026,11,12,tzinfo=UTC),'first','last')
    with p.connect() as db:
        import json
        stored = json.loads(db.execute('SELECT manifest FROM market_versions WHERE dataset_id=?', (manifest['dataset_id'],)).fetchone()[0])
    identifier = stored.pop('dataset_id')
    assert hashlib.sha256(canonical_bytes(stored)).hexdigest() == identifier
    assert p.lookup(dict(symbol='300750.SZ',asset_class='equity',interval='5m',data_source='huggingface',adjustment='auto'))['dataset_id'] == identifier
    assert manifest['coverage']['start'] < manifest['start']
    assert manifest['coverage']['end'] > manifest['end']
    assert p.bundle(identifier,datetime(2025,1,1,16,tzinfo=UTC),datetime(2025,1,2,15,59,59,tzinfo=UTC)).frame.volume.sum() == frame.volume.sum()


def test_chart_api_reads_explicit_hf_manifest_and_hash_checked_public_chunks():
    from datetime import UTC, datetime
    import hashlib
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.main import app, market_publications
    from app.journal.router import _attempts
    _attempts.clear()
    frame = aggregate_minutes(session(), 1)
    manifest = publish_frame(market_publications,'300750.SZ','1m',frame,
        datetime(2026,11,12,tzinfo=UTC),'first','last')
    with TestClient(app) as client:
        assert client.get('/api/v1/market/manifest').status_code == 401
        response = client.post('/api/register',json={'email':f'{uuid4()}@example.test','password':'test-password-123'})
        assert response.status_code == 201, response.text
        response = client.get('/api/v1/market/manifest',params=dict(symbol='300750.SZ',asset_class='equity',
            interval='1m',adjustment='raw',data_source='huggingface'))
        assert response.status_code == 200, response.text
        published = response.json()
        assert published['dataset_id'] == manifest['dataset_id'] and published['count'] == 240
        client.cookies.clear()  # CDN chunks are intentionally read without session credentials.
        chunk = published['chunks'][0]
        response = client.get(chunk['url'])
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == chunk['sha256']
        assert len(response.json()['bars']) == chunk['count']
