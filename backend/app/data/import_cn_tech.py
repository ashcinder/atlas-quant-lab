"""Collect and publish a bounded, auditable Chinese technology equity snapshot.

Run: cd backend && .venv/bin/python -m app.data.import_cn_tech
No paid data, synthetic bars or claimed all-history coverage.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd

from app.catalog import ASSETS, find_asset
from app.cn_universe import CN_TECH_UNIVERSE
from app.config import DATA_DIR
from app.data.providers import SinaProvider, cn_bar_open_times
from app.data.service import DataBundle, MarketDataService
from app.market_publication import MarketPublication

INTERVALS = ('1m', '5m', '15m', '1h', '1d')


def validated_frame(frame: pd.DataFrame, now: datetime):
    columns=['open','high','low','close','volume']
    valid=(np.isfinite(frame[columns]).all(axis=1)
        & (frame[['open','high','low','close']]>0).all(axis=1)
        & (frame.high>=frame[['open','close']].max(axis=1))
        & (frame.low<=frame[['open','close']].min(axis=1)) & (frame.volume>=0)
        & (frame.index<=pd.Timestamp(now)))
    clean=frame.loc[valid].copy()
    if clean.index.has_duplicates or not clean.index.is_monotonic_increasing or len(clean)<40:
        raise ValueError('有效行情不足40根或时间乱序，保留原发布版本')
    return clean, int((~valid).sum())


def publish_snapshot(symbol, interval, frame, fetched, publications, service, rejected=0):
    asset=find_asset(symbol,'equity')
    note=(f'新浪公开沪深行情；{interval}；不复权；成交量单位股；Asia/Shanghai转UTC。'
          f'仅为接口实际返回的最近窗口（上限1970根），不是上市以来全历史。'
          f'剔除无效或未收盘时间记录{rejected}根，未补造停牌、午休及休市K线。')
    if interval!='1d':
        note+='原始分钟标签为收盘时刻，已转换为开盘时刻。当前通用引擎未完整实现A股T+1、整手和涨跌停规则。'
    if interval=='1m':
        note+='该源部分交易日在收盘集合竞价附近缺少单独的14:57和14:58分钟记录；末条原始标签为15:00，按通常1分钟标签转为14:59，实际覆盖时段待核验；请勿将时间范围视为逐分钟完整性证明。'
    bundle=DataBundle(asset=asset,frame=frame,source='sina',source_note=note,fetched_at=fetched)
    # Raw price history can accumulate over repeated imports without rebasing.
    cache_key=service._cache_path('sina',symbol,interval,None,None,'raw').name
    # Versioned key prevents mixing legacy close-labelled bars with open times.
    key=cache_key+':bar-open-v1'
    cached=service.store.read(key)
    previous=publications.lookup(dict(symbol=symbol,asset_class='equity',interval=interval,adjustment='auto',data_source='auto'))
    if previous is not None and previous['source']!='sina':
        raise ValueError('已有其他来源的数据，未覆盖；需先核验后合并')
    if cached is None and previous is not None:
        if interval!='1d' and '开盘时刻' not in (previous.get('source_note') or ''):
            raise ValueError('已有其他来源或时间口径的数据，未覆盖；需先核验后合并')
        cached=publications.bundle(previous['dataset_id']).frame
    if cached is not None:
        frame=pd.concat([cached,frame]).loc[lambda f:~f.index.duplicated(keep='last')].sort_index()
        frame,_=validated_frame(frame,fetched)
        bundle.frame=frame
    service.store.write(key,frame,fetched)
    service.store.write(cache_key,frame,fetched)
    # Coverage begins at the first actual candle. The last known close also
    # covers the remainder of that calendar day if the market is already closed.
    local_last=frame.index[-1].to_pydatetime().astimezone(ZoneInfo('Asia/Shanghai'))
    end=min(fetched,local_last.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1))
    raw_query=dict(symbol=symbol,asset_class='equity',interval=interval,adjustment='raw',data_source='auto',
                   start=frame.index[0].isoformat(),end=end.isoformat())
    manifest=publications.publish(raw_query,bundle)
    # auto explicitly resolves to the same raw snapshot, without creating a
    # misleading adjusted-price manifest or duplicating immutable chunks.
    encoded=json.dumps({k:v for k,v in manifest.items() if k!='status'},ensure_ascii=False,allow_nan=False)
    from app.market_publication import query_key
    with publications.connect() as db:
        for source in ('auto','sina'):
            for adjustment in ('auto','raw'):
                db.execute('INSERT OR REPLACE INTO market_publications VALUES (?,?,?)',
                    (query_key({**raw_query,'adjustment':adjustment,'data_source':source}),manifest['dataset_id'],encoded))
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intervals',nargs='+',choices=INTERVALS,default=['1m','5m','15m','1h'])
    parser.add_argument('--symbols',nargs='+',help='Subset of the curated research universe')
    args=parser.parse_args(argv)
    universe={a.symbol:('沪深A股',a.name) for a in ASSETS if a.asset_class=='equity' and a.exchange in ('SSE','SZSE') and a.symbol.endswith(('.SS','.SZ'))}
    universe.update({s:(topic,name) for topic,members in CN_TECH_UNIVERSE.items() for s,name in members})
    selected=args.symbols or list(universe)
    if any(s not in universe for s in selected): parser.error('标的不在项目沪深股票目录中')
    root=DATA_DIR/'cn-tech'/datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    root.mkdir(parents=True,exist_ok=True)
    service,publications=MarketDataService(),MarketPublication()
    provider=SinaProvider()
    provider.client.close()
    provider.client=httpx.Client(trust_env=True,timeout=25,follow_redirects=True,
        headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'})
    report=[]
    try:
        for symbol in selected:
            topic,name=universe[symbol]
            for interval in args.intervals:
                entry=dict(symbol=symbol,name=name,topic=topic,interval=interval)
                try:
                    for attempt in range(3):
                        try:
                            scale={'1m':1,'5m':5,'15m':15,'1h':60,'1d':240}[interval]
                            response=provider._get(provider.CN_KLINE_URL,dict(symbol=provider._cn_symbol(find_asset(symbol)),scale=scale,ma='no',datalen=1970))
                            payload=response.json()
                            if not isinstance(payload,list) or not payload: raise ValueError('数据源未返回K线')
                            break
                        except (httpx.HTTPError,RuntimeError,ValueError):
                            if attempt==2: raise
                            time.sleep(attempt+1)
                    directory=root/symbol
                    directory.mkdir(exist_ok=True)
                    archive=directory/f'{interval}.source.json'
                    archive.write_bytes(response.content)
                    from app.data.providers import _records_frame
                    frame=_records_frame(payload,{'day':'date'},'Asia/Shanghai')
                    fetched=datetime.now(UTC)
                    local_now=fetched.astimezone(ZoneInfo('Asia/Shanghai'))
                    if interval=='1d' and local_now.hour<15:
                        frame=frame.loc[frame.index.tz_convert('Asia/Shanghai').date<local_now.date()]
                    frame,rejected=validated_frame(frame,fetched)
                    rejected=len(payload)-len(frame)
                    frame=cn_bar_open_times(frame,interval)
                    frame.to_csv(directory/f'{interval}.csv.gz',compression='gzip')
                    manifest=publish_snapshot(symbol,interval,frame,fetched,publications,service,rejected)
                    entry.update(status='published',count=manifest['count'],dataset_id=manifest['dataset_id'],
                        first_shanghai=datetime.fromtimestamp(manifest['start'],UTC).astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
                        last_shanghai=datetime.fromtimestamp(manifest['end'],UTC).astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
                        source_sha256=hashlib.sha256(response.content).hexdigest(),rejected=rejected)
                except Exception as exc:
                    entry.update(status='failed',error=str(exc)[:300])
                report.append(entry)
                (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
                print(json.dumps(entry,ensure_ascii=False),flush=True)
                time.sleep(0.25)
    finally: provider.client.close()
    summary={'report':str(root/'report.json'),'published':sum(e['status']=='published' for e in report),'failed':sum(e['status']=='failed' for e in report),'bars':sum(e.get('count',0) for e in report)}
    (DATA_DIR/'cn-tech'/'latest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return bool(summary['failed'])


if __name__=='__main__': raise SystemExit(main())
