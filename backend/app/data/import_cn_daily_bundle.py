"""Publish verified unadjusted local bundle daily bars and derived session/week bars.

Input CSVs are exported from the trusted RQAlpha stocks.h5 by the separate
engine Python environment. Never fabricate missing or suspended sessions.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import httpx
import pandas as pd

from app.catalog import ASSETS
from app.data.providers import SinaProvider, _records_frame
from app.data.service import DataBundle
from app.market_publication import MarketPublication, query_key


def by_session(frame):
    frame=frame.copy()
    frame.index=frame.index.tz_convert('Asia/Shanghai').normalize()
    if frame.index.has_duplicates:raise ValueError('同一交易日存在重复K线')
    return frame.sort_index()[['open','high','low','close','volume']]


def merge_checked(base, incoming):
    if incoming is None or incoming.empty:return base
    shared=base.index.intersection(incoming.index)
    if len(shared)==0:raise ValueError('数据源无重叠交易日，无法校验后拼接')
    a,b=base.loc[shared],incoming.loc[shared]
    for col in ['open','high','low','close','volume']:
        if ((a[col]-b[col]).abs()>(1 if col=='volume' else .02)).any():
            raise ValueError(f'数据源重叠交易日 {col} 不一致，保留原数据')
    return pd.concat([base,incoming]).loc[lambda f:~f.index.duplicated(keep='last')].sort_index()


def fetch_recent(asset,now):
    symbol=('sh' if asset.symbol.endswith('.SS') else 'sz')+asset.symbol.split('.')[0]
    try:
        with httpx.Client(timeout=20,follow_redirects=True,headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'}) as c:
            resp=c.get(SinaProvider.CN_KLINE_URL,params={'symbol':symbol,'scale':240,'ma':'no','datalen':1970});resp.raise_for_status()
            payload=resp.json()
        if not isinstance(payload,list) or not payload:raise ValueError('新浪未返回日线')
        frame=by_session(_records_frame(payload,{'day':'date'},'Asia/Shanghai'))
        if now.tz_convert('Asia/Shanghai').hour<15:
            frame=frame.loc[frame.index.date<now.tz_convert('Asia/Shanghai').date()]
        return frame,None
    except Exception as exc:return None,str(exc)[:160]


def publish(publications,asset,interval,frame,note,now,coverage_end):
    query=dict(symbol=asset.symbol,asset_class='equity',interval=interval,adjustment='raw',data_source='auto',
        start=frame.index[0].isoformat(),end=min(now,coverage_end).isoformat())
    result=publications.publish(query,DataBundle(asset=asset,frame=frame,source='rqalpha-sina',source_note=note,fetched_at=now.to_pydatetime()))
    encoded=json.dumps(result,ensure_ascii=False,allow_nan=False)
    with publications.connect() as db:
        for source in ('auto','rqalpha-sina'):
            for adjustment in ('auto','raw'):
                db.execute('INSERT OR REPLACE INTO market_publications VALUES (?,?,?)',
                           (query_key({**query,'adjustment':adjustment,'data_source':source}),result['dataset_id'],encoded))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--rq-csv-dir',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();now=pd.Timestamp.now(tz='UTC');p=MarketPublication()
    assets=[a for a in ASSETS if a.asset_class=='equity' and a.exchange in ('SSE','SZSE') and a.symbol.endswith(('.SS','.SZ'))]
    with ThreadPoolExecutor(max_workers=3) as pool: recent=list(pool.map(lambda a:fetch_recent(a,now),assets))
    report=[]
    for asset,(latest,fetch_error) in zip(assets,recent):
        row={'symbol':asset.symbol,'name':asset.name,'recent_fetch_error':fetch_error}
        try:
            path=args.rq_csv_dir/(asset.symbol+'.csv')
            if not path.exists():raise ValueError('本机 RQAlpha bundle 没有该标的')
            base=by_session(pd.read_csv(path,index_col='time',parse_dates=True))
            old=p.lookup(dict(symbol=asset.symbol,asset_class='equity',interval='1d'))
            if old:base=merge_checked(base,by_session(p.bundle(old['dataset_id']).frame))
            base=merge_checked(base,latest)
            # Daily/weekly labels match native daily bars at Shanghai 15:00.
            daily=base.copy();daily.index=(daily.index+pd.Timedelta(hours=15)).tz_convert('UTC')
            note='RQAlpha原始日线与新浪不复权日线重叠区间OHLCV核对一致后合并；成交量为股；未补造停牌与缺失交易日。'
            coverage_end=(base.index[-1]+pd.Timedelta(days=1)).tz_convert('UTC')
            day=publish(p,asset,'1d',daily,note,now,coverage_end)
            # Four trading hours span both A-share sessions, excluding lunch.
            session=base.copy();session.index=(session.index+pd.Timedelta(hours=9,minutes=30)).tz_convert('UTC')
            four=publish(p,asset,'4h',session,note+' 4小时为当日完整四小时交易时段汇总（午休不计），直接使用日线OHLCV。',now,coverage_end)
            period=base.index.tz_localize(None).to_period('W-FRI')
            week=base.groupby(period).agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
            # W-FRI periods begin Saturday; label the trading week Monday.
            week.index=pd.DatetimeIndex([(x.start_time+pd.Timedelta(days=2)).tz_localize('Asia/Shanghai') for x in week.index]).tz_convert('UTC')
            weekly=publish(p,asset,'1wk',week,note+' 周线按周一至周五交易日聚合；末周可能尚未结束。',now,coverage_end)
            row.update(status='published',daily=day['count'],first_daily=str(base.index[0].date()),last_daily=str(base.index[-1].date()),four_hours=four['count'],weekly=weekly['count'])
        except Exception as exc:row.update(status='failed',error=str(exc)[:250])
        report.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'published':sum(r['status']=='published' for r in report),'failed':sum(r['status']=='failed' for r in report)},ensure_ascii=False))

if __name__=='__main__':main()
