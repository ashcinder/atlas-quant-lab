"""Archive unadjusted BaoStock minute data; no automatic cross-source merging.

Uses the separately installed optional `baostock` package. Each completed
year is saved independently; a failed query never replaces published data.
"""
from __future__ import annotations
import argparse
from datetime import datetime, UTC
import gzip
import json
from pathlib import Path
import socket

FIELDS='date,time,code,open,high,low,close,volume'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',default='sz.300750')
    parser.add_argument('--years',nargs='+',type=int,required=True)
    parser.add_argument('--frequency',choices=['5','15','30','60'],default='5')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    socket.setdefaulttimeout(25)
    import baostock as bs
    login=bs.login()
    if login.error_code!='0':raise RuntimeError('BaoStock 登录失败: '+login.error_msg)
    try:
        for year in args.years:
            q=bs.query_history_k_data_plus(args.symbol,FIELDS,f'{year}-01-01',f'{year}-12-31',frequency=args.frequency,adjustflag='3')
            rows=[]
            while q.error_code=='0' and q.next():rows.append(q.get_row_data())
            if q.error_code!='0':raise RuntimeError(f'{year} 获取失败: {q.error_msg}')
            output=args.output/f'{args.symbol}-{args.frequency}m-{year}.json.gz'
            temporary=output.with_name(output.name+'.tmp')
            with gzip.open(temporary,'wt',encoding='utf-8') as f:json.dump({'fields':FIELDS.split(','),'rows':rows,'source':'baostock','adjustment':'raw','retrieved_at':datetime.now(UTC).isoformat()},f,ensure_ascii=False)
            temporary.replace(output)
            print(json.dumps({'year':year,'rows':len(rows),'first':rows[0][1] if rows else None,'last':rows[-1][1] if rows else None,'file':str(output)},ensure_ascii=False),flush=True)
    finally:bs.logout()

if __name__=='__main__':main()
