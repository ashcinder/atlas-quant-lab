from datetime import UTC, datetime

import httpx
import pandas as pd
import pytest

from app.backtest.metrics import periods_per_year
from app.catalog import find_asset, search_assets
from app.compute_objects import ComputeObjects
from app.data.import_cn_tech import publish_snapshot, validated_frame
from app.data.providers import ProviderError, SinaProvider
from app.data.service import MarketDataService
from app.market_publication import MarketPublication
from app.data.import_cn_daily_bundle import merge_checked
from app.data.publish_baostock_minutes import aggregate


def sample(start='2026-01-05 01:31',periods=45):
    return pd.DataFrame({'open':100.,'high':102.,'low':99.,'close':101.,'volume':12345.},index=pd.date_range(start,periods=periods,freq='min',tz='UTC'))


@pytest.mark.parametrize('topic',['半导体','机器人','航天'])
def test_research_pool_is_searchable_and_cny(topic):
    assets=search_assets(topic)
    assert len(assets)==5
    assert all(a.currency=='CNY' and a.timezone=='Asia/Shanghai' and a.exchange in {'SSE','SZSE'} for a in assets)


@pytest.mark.parametrize('interval,scale',[('1m',1),('5m',5)])
def test_sina_actual_minute_scale_and_shanghai_volume(monkeypatch,interval,scale):
    provider=SinaProvider()
    rows=[dict(day='2026-01-05 09:31:00' if interval=='1m' else '2026-01-05 09:35:00',open='100',high='102',low='99',close='101',volume='12345')]
    seen=[]
    def get(url,params):
        seen.append(params)
        return httpx.Response(200,json=rows)
    monkeypatch.setattr(provider,'_get',get)
    frame=provider.fetch_bars(find_asset('688981.SS'),interval,None,None,'raw')
    assert seen[0]['scale']==scale and seen[0]['datalen']==1970
    assert frame.index[0]==pd.Timestamp('2026-01-05 01:30Z')
    assert frame.volume.iloc[0]==12345  # Sina returns shares, not lots.
    with pytest.raises(ProviderError,match='不复权'):
        provider.fetch_bars(find_asset('688981.SS'),interval,None,None,'forward')
    with pytest.raises(ProviderError,match='沪深A股'):
        provider.fetch_bars(find_asset('AAPL'),interval,None,None,'auto')
    provider.client.close()


def test_reject_invalid_bars_without_filling_sessions():
    frame=sample()
    frame.iloc[0,frame.columns.get_loc('high')]=50
    frame.iloc[1,frame.columns.get_loc('volume')]=-1
    cleaned,rejected=validated_frame(frame,datetime(2026,1,6,tzinfo=UTC))
    assert rejected==2 and len(cleaned)==43
    assert cleaned.index[0]==frame.index[2]


def test_daily_bundle_refuses_conflicting_sources():
    first=pd.DataFrame(
        {'open':[10.], 'high':[11.], 'low':[9.], 'close':[10.5], 'volume':[1000.]},
        index=pd.DatetimeIndex(['2025-01-02'],tz='Asia/Shanghai'))
    second=first.copy();second['close']=10.6
    with pytest.raises(ValueError,match='不一致'):
        merge_checked(first,second)
    second['close']=10.5
    assert len(merge_checked(first,second))==1


def test_sina_import_does_not_overwrite_a_different_source(tmp_path):
    from app.data.service import DataBundle
    service=MarketDataService(tmp_path/'cache')
    publications=MarketPublication(tmp_path/'publications.db',ComputeObjects(tmp_path/'objects'))
    now=datetime(2026,1,6,tzinfo=UTC)
    asset=find_asset('688981.SS')
    query={'symbol':asset.symbol,'asset_class':'equity','interval':'5m','adjustment':'auto','data_source':'auto'}
    original=publications.publish(query,DataBundle(asset=asset,frame=sample(),source='another-provider'))
    with pytest.raises(ValueError,match='未覆盖'):
        publish_snapshot(asset.symbol,'5m',sample(),now,publications,service)
    assert publications.lookup(query)['dataset_id']==original['dataset_id']


def test_minute_aggregation_does_not_fill_missing_bars_or_cross_lunch():
    idx=pd.DatetimeIndex(['2025-01-02 09:30','2025-01-02 09:35','2025-01-02 09:40',
                          '2025-01-02 11:25','2025-01-02 13:00','2025-01-02 13:05'],tz='Asia/Shanghai').tz_convert('UTC')
    frame=pd.DataFrame({'open':[1,2,3,4,5,6],'high':[2,3,4,5,6,7],
                        'low':[1,2,3,4,5,6],'close':[2,3,4,5,6,7],
                        'volume':[10,10,10,10,10,10]},index=idx)
    result=aggregate(frame,15)
    assert len(result)==1 and result.iloc[0]['volume']==30
    assert result.index[0]==idx[0]


def test_publication_aliases_use_raw_snapshot_and_accumulate_only_actual_rows(tmp_path):
    service=MarketDataService(tmp_path/'cache')
    publications=MarketPublication(tmp_path/'publications.db',ComputeObjects(tmp_path/'objects'))
    now=datetime(2026,1,6,tzinfo=UTC)
    first=publish_snapshot('688981.SS','1m',sample(),now,publications,service)
    changed=sample(start='2026-01-05 02:01')
    changed['close']=100.5
    second=publish_snapshot('688981.SS','1m',changed,now,publications,service)
    assert first['count']==45 and second['count']==75
    assert first['dataset_id']!=second['dataset_id']
    for adjustment in ('auto','raw'):
        for source in ('auto','sina'):
            manifest=publications.lookup(dict(symbol='688981.SS',asset_class='equity',interval='1m',adjustment=adjustment,data_source=source))
            assert manifest['adjustment']=='raw'
            assert manifest['count']==75
            assert manifest['dataset_id']==second['dataset_id']
    assert publications.lookup(dict(symbol='688981.SS',asset_class='equity',interval='1m',adjustment='forward')) is None
    frame=publications.bundle(second['dataset_id']).frame
    assert frame.loc[changed.index[0],'close']==100.5
    assert frame.volume.iloc[0]==12345


def test_cn_session_annualization_preserves_crypto_and_us():
    assert periods_per_year('1m','equity','SSE')==252*240
    assert periods_per_year('5m','equity','SZSE')==252*48
    assert periods_per_year('15m','equity','SSE')==252*16
    assert periods_per_year('1h','equity','NASDAQ')==252*6.5
    assert periods_per_year('1m','crypto','CRYPTO')==365*1440
