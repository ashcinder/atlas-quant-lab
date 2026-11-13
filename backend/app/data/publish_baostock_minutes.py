"""Validate archived unadjusted BaoStock 5m bars against daily history.

On success publish 5m and fully populated derived 15m/1h bars as a separate
BaoStock source; preserve Sina's immutable snapshots. Never fill missing bars.
"""
from __future__ import annotations
import argparse
from datetime import UTC, datetime
import gzip
import json
from pathlib import Path
import numpy as np
import pandas as pd
from app.catalog import find_asset
from app.data.import_cn_daily_bundle import by_session
from app.data.service import DataBundle
from app.market_publication import MarketPublication, query_key


def aggregate(frame,mins):
    local=frame.tz_convert('Asia/Shanghai').copy()
    index=local.index
    begin=index.normalize()+pd.to_timedelta(np.where(index.hour<12,570,780),unit='m')
    offsets=(index-begin)//pd.Timedelta(minutes=mins)
    local['_bucket']=begin+offsets*pd.Timedelta(minutes=mins)
    groups=local.groupby('_bucket')
    count=groups.close.count()
    result=groups.agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    # No missing constituent bars are silently interpolated.
    result=result.loc[count==mins//5]
    result.index=result.index.tz_convert('UTC')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--input',type=Path,required=True)
    ap.add_argument('--start-year',type=int,required=True);ap.add_argument('--end-year',type=int,required=True)
    ap.add_argument('--chart-only-disputed',action='store_true',help='仅发布为独立的待核验图表源，绝不覆盖默认数据')
    args=ap.parse_args();rows=[]
    for year in range(args.start_year,args.end_year+1):
        path=args.input/f'sz.300750-5m-{year}.json.gz'
        if not path.exists():raise ValueError(f'历史文件缺失，未发布: {path}')
        with gzip.open(path,'rt',encoding='utf-8') as f:doc=json.load(f)
        if not doc['rows']:raise ValueError(f'{year} 无行情，未发布')
        rows.extend(doc['rows'])
    frame=pd.DataFrame(rows,columns=['date','time','code','open','high','low','close','volume'])
    frame.index=(pd.DatetimeIndex(pd.to_datetime(frame.time.str[:14],format='%Y%m%d%H%M%S')).tz_localize('Asia/Shanghai')-pd.Timedelta(minutes=5)).tz_convert('UTC')
    for col in ['open','high','low','close','volume']:frame[col]=pd.to_numeric(frame[col],errors='raise')
    frame=frame[['open','high','low','close','volume']].sort_index()
    if (frame.index.has_duplicates or not np.isfinite(frame.to_numpy()).all()
        or (frame[['open','high','low','close']]<=0).any().any() or (frame.volume<0).any()
        or (frame.high<frame[['open','close']].max(axis=1)).any()
        or (frame.low>frame[['open','close']].min(axis=1)).any()):
        raise ValueError('分钟行情存在重复或无效值，未发布')
    p=MarketPublication();asset=find_asset('300750.SZ','equity')
    manifest=p.lookup(dict(symbol=asset.symbol,asset_class='equity',interval='1d'))
    if not manifest:raise ValueError('缺少独立日线用于核验，未发布')
    daily=by_session(p.bundle(manifest['dataset_id']).frame)
    local=frame.tz_convert('Asia/Shanghai')
    clock=local.index.hour*60+local.index.minute
    if ((clock%5!=0)|~(((clock>=570)&(clock<690))|((clock>=780)&(clock<900)))).any():
        raise ValueError('分钟线时间不在标准交易时段或未按5分钟对齐，未发布')
    sessions=local.groupby(local.index.normalize()).agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    first,last=sessions.index[0],sessions.index[-1]
    existing=p.lookup(dict(symbol=asset.symbol,asset_class='equity',interval='5m'))
    if existing and last.date()<pd.Timestamp(existing['end'],unit='s',tz='UTC').tz_convert('Asia/Shanghai').date():
        raise ValueError('新数据截止日期早于现有版本，未发布')
    reference=daily.loc[(daily.index>=first)&(daily.index<=last)]
    missing=reference.index.difference(sessions.index)
    if len(missing):raise ValueError(f'分钟行情缺少 {len(missing)} 个有成交的交易日，未发布')
    comparison=reference.join(sessions,lsuffix='_day',rsuffix='_min',how='inner')
    differences={col:int(((comparison[col+'_day']-comparison[col+'_min']).abs()>(1 if col=='volume' else .021)).sum()) for col in ['open','high','low','close','volume']}
    if any(differences.values()) and not args.chart_only_disputed:
        raise ValueError(f'分钟数据汇总与日线不一致 {differences}，未发布')
    now=datetime.now(UTC)
    note=('BaoStock 不复权5分钟原始行情；与本地日线对账存在差异，仅供查看，不可回测。'
          +f'逐日最高价不符 {differences["high"]} 日、成交量不符 {differences["volume"]} 日。'
          +'各交易日内分时切分口径与新浪可能不同；不覆盖原有新浪版本。缺失分时不得插值；不代表上市以来全部历史。') if args.chart_only_disputed else (
          'BaoStock 不复权5分钟原始行情；逐日汇总已与本地日线OHLCV核验。缺失分时不得插值；不代表上市以来全部历史。')
    results={}
    for iv,data in [('5m',frame),('15m',aggregate(frame,15)),('1h',aggregate(frame,60))]:
        if data.empty:raise ValueError(f'{iv} 没有可发布K线')
        coverage_end=min(pd.Timestamp(now),(last+pd.Timedelta(days=1)).tz_convert('UTC'))
        query=dict(symbol=asset.symbol,asset_class='equity',interval=iv,adjustment='raw',data_source='baostock' if args.chart_only_disputed else 'auto',
                   start=data.index[0].isoformat(),end=coverage_end.isoformat())
        extra='' if iv=='5m' else f' {iv} 仅由完整5分钟K线聚合；午休不跨段，缺失的聚合周期不补造。'
        result=p.publish(query,DataBundle(asset=asset,frame=data,source='baostock-disputed' if args.chart_only_disputed else 'baostock',source_note=note+extra,fetched_at=now))
        encoded=json.dumps(result,ensure_ascii=False,allow_nan=False)
        aliases=('baostock','baostock-disputed') if args.chart_only_disputed else ('auto','baostock')
        with p.connect() as db:
            for source in aliases:
                for adjustment in ('auto','raw'):
                    db.execute('INSERT OR REPLACE INTO market_publications VALUES (?,?,?)',
                        (query_key({**query,'adjustment':adjustment,'data_source':source}),result['dataset_id'],encoded))
        results[iv]={'bars':len(data),'first':str(data.index[0]),'last':str(data.index[-1]),'dataset_id':result['dataset_id']}
    print(json.dumps({'compared_sessions':len(comparison),'daily_differences':differences,'results':results},ensure_ascii=False))

if __name__=='__main__':main()
