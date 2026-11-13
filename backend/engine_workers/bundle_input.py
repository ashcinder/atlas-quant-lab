"""Read the installed RQAlpha bundle without loading any strategy source."""
def load_bars(payload):
    import pandas as pd
    from datetime import datetime
    from rqalpha.data.base_data_source import BaseDataSource
    from rqalpha.utils import RqAttrDict
    from rqalpha.utils.datetime_func import convert_int_to_datetime
    r=payload['request']
    source=BaseDataSource(RqAttrDict({'data_bundle_path':payload['bundle_path']}))
    code=r['symbol'].replace('.SS','.XSHG').replace('.SZ','.XSHE')
    instrument=next(source.get_instruments([code]))
    start=pd.Timestamp(r['start']).tz_convert('Asia/Shanghai').date()
    end=pd.Timestamp(r['end']).tz_convert('Asia/Shanghai').date()
    rows=source.history_bars(instrument,1000000,'1d',None,datetime.combine(end,datetime.max.time()),
        skip_suspended=False,include_now=True,adjust_type='none')
    bars=[]
    for row in rows:
        day=convert_int_to_datetime(int(row['datetime'])).date()
        if start<=day<=end:
            stamp=pd.Timestamp(day).tz_localize('Asia/Shanghai')+pd.Timedelta(hours=9,minutes=30)
            bars.append(dict(time=int(stamp.timestamp()),**{k:float(row[k]) for k in ('open','high','low','close','volume')}))
    return {'bars':bars}
