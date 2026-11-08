"""Synthetic-only ASGI fixture; never packaged as a production entry point."""
import json
import math
import os
from pathlib import Path
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from dataclasses import replace

if os.environ.get('ATLAS_E2E_ISOLATED') != '1' or os.environ.get('ATLAS_DATA_DIR') != '/work/data':
    raise RuntimeError('Dedicated synthetic E2E data directory and explicit marker required')
if os.environ.get('ATLAS_COMPUTE_MODE') != 'browser' or os.environ.get('ATLAS_CLOUD_PROOF_GENERATION') != 'false':
    raise RuntimeError('Browser mode with paid proof generation disabled required')
sys.path.insert(0,'/app/backend')
import httpx
from provider_faults import binance_partial, bkc_fixture_mode, bkc_receipt_status, okx_fixture
# Every outbound HTTP request stays at the external transport boundary. Unknown
# destinations fail closed; no personal credentials are present in this process.
orders = {}
def transport(request):
    host,path=request.url.host,request.url.path
    okx = okx_fixture(request)
    if okx is not None: return okx
    if host=='api.frankfurter.dev':return httpx.Response(200,json={'base':'USD','quote':'CNY','rate':7.2,'date':'2026-11-08'})
    if host in {'api.deepseek.com','dashscope.aliyuncs.com'}:
        body=json.loads(request.content); messages=body.get('messages',[])
        if any('request_id' in m.get('content','') for m in messages):
            try:q=json.loads(messages[-1]['content']);content=json.dumps({'request_id':q['request_id'],'action':'approve','scale':1,'reason':'Synthetic isolated response'})
            except (KeyError,ValueError):content='{"ok":true}'
        else:content='{"ok":true}'
        return httpx.Response(200,json={'choices':[{'message':{'content':content}}]})
    if host=='testnet.binance.vision':
        q=dict(request.url.params)
        fault_response = binance_partial(request, q)
        if fault_response is not None:
            return fault_response
        if path.endswith('/account'):return httpx.Response(200,json={'balances':[{'asset':'USDT','free':'10000','locked':'0'},{'asset':'BTC','free':'1','locked':'0'}]})
        if path.endswith('/ticker/price'):
            row={'symbol':'BTCUSDT','price':'10000'};return httpx.Response(200,json=row if q.get('symbol') else [row])
        if path.endswith('/exchangeInfo'):return httpx.Response(200,json={'symbols':[{'symbol':'BTCUSDT','status':'TRADING','filters':[{'filterType':'PRICE_FILTER','tickSize':'0.01'},{'filterType':'LOT_SIZE','stepSize':'0.00001','minQty':'0.00001'},{'filterType':'MIN_NOTIONAL','minNotional':'1'}]}]})
        if path.endswith('/order'):
            cid=q.get('newClientOrderId',q.get('origClientOrderId',''))
            if request.method=='POST':orders[cid]={'orderId':len(orders)+1,'clientOrderId':cid,'symbol':q['symbol'],'status':'NEW','executedQty':'0','origQty':q['quantity'],'price':q['price']}
            row=orders.get(cid)
            if row is None:return httpx.Response(400,json={'code':-2013,'msg':'Order does not exist'})
            if request.method=='DELETE':row['status']='CANCELED'
            return httpx.Response(200,json=row)
        if path.endswith('/myTrades'):return httpx.Response(200,json=[])
    raise httpx.ConnectError('Synthetic environment blocks external provider',request=request)
_RealClient,_RealAsync=httpx.Client,httpx.AsyncClient
class FixtureClient(_RealClient):
    def __init__(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(transport);super().__init__(*args,**kwargs)
class FixtureAsync(_RealAsync):
    def __init__(self,*args,**kwargs):kwargs['transport']=httpx.MockTransport(transport);super().__init__(*args,**kwargs)
httpx.Client,httpx.AsyncClient=FixtureClient,FixtureAsync

import pandas as pd
from app.main import app, journal_store, market_publications, strategy_runtime_store, data_service
from app.catalog import ASSETS, find_asset
from app.data.service import DataBundle
from app.strategy_runtime import ReleaseCreate
from app import strategy_runtime
from app.data.providers import MarketDataProvider
from app.supervisor_client import SupervisorClient, SupervisorRPCError

# Yahoo's client uses its own HTTP stack, so isolate its remote-data adapter too.
# Keep the real FundamentalsService, normalization, cache and API authorization.
import app.fundamentals as fundamentals
class FixtureTicker:
    def __init__(self, symbol): self.symbol = symbol
    def get_info(self):
        if self.symbol != 'SPY': raise RuntimeError('Synthetic fixture blocks this Yahoo snapshot')
        return {'currency': 'USD', 'financialCurrency': 'USD', 'marketCap': 500000000000,
                'currentPrice': 600.25, 'totalAssets': 500000000000, 'trailingPE': 22.5,
                'yield': 0.012, 'annualReportExpenseRatio': 0.0009, 'fundFamily': 'Synthetic E2E Fund',
                'fiftyTwoWeekHigh': 620.5, 'fiftyTwoWeekLow': 480.25, 'averageVolume': 60000000}
    def get_fast_info(self): return {}
fundamentals.yf.Ticker = FixtureTicker

class FixtureProvider(MarketDataProvider):
    def fetch_bars(self,asset,interval,start,end,adjustment):
        frame=make_frame(asset.symbol,interval)
        if start:frame=frame.loc[frame.index>=start]
        if end:frame=frame.loc[frame.index<=end]
        return frame

def make_frame(symbol,interval):
    step={'15m':900,'1h':3600,'4h':14400,'1d':86400,'1wk':604800}[interval]
    end=int(datetime.now(UTC).timestamp())//step*step-step
    scale=1+(sum(symbol.encode())%17)/10
    rows=[]
    for i in range(1000):
        close=scale*(100+.035*i+12*math.sin(i/17)+5*math.sin(i/7))
        rows.append({'time':end-(999-i)*step,'open':close*.998,'high':close*1.01,'low':close*.99,'close':close,'volume':1000000.})
    frame=pd.DataFrame(rows);frame['time']=pd.to_datetime(frame['time'],unit='s',utc=True)
    return frame.set_index('time')
# Replace provider adapters, not market/compute routes or their authorization.
for name in data_service.providers:data_service.providers[name]=FixtureProvider()
# Supervisor remains an isolated RPC boundary, never a product auth shortcut.
chain_transactions={}
def rpc(self,method,params):
    genesis='0x'+'31'*32;block='0x'+'42'*32
    if method=='eth_chainId':return '0x41b'
    if method=='eth_blockNumber':return '0xa'
    if method=='eth_getBlockByNumber':return {'hash':genesis if params[0]=='0x0' else block,'number':params[0]}
    if method in {'eth_getTransactionCount','eth_gasPrice','eth_estimateGas','eth_getBalance'}:return {'eth_getTransactionCount':'0x0','eth_gasPrice':'0x1','eth_estimateGas':'0x100000','eth_getBalance':hex(10**24)}[method]
    if method=='eth_sendRawTransaction':
        import subprocess
        decoded=json.loads(subprocess.check_output(['node','/app/contracts/scripts/decode-transaction.mjs'],input=json.dumps({'raw_transaction':params[0]}),text=True))
        row={**decoded,'value':hex(int(decoded['value'])),'input':decoded['data'],'blockHash':block,'blockNumber':'0xa'}
        mode = bkc_fixture_mode(decoded)
        row['fixture_receipt_status'] = bkc_receipt_status(decoded, chain_transactions)
        chain_transactions[decoded['hash']] = row
        if mode == 'lost_reply':
            raise SupervisorRPCError('Synthetic transaction accepted but RPC reply lost')
        return decoded['hash']
    if method=='eth_getTransactionByHash':return chain_transactions.get(params[0])
    if method=='eth_getTransactionReceipt':
        row = chain_transactions.get(params[0])
        if row is None:
            return None
        return {'transactionHash': params[0], 'blockHash': block, 'blockNumber': '0xa',
                'status': row['fixture_receipt_status']}
    raise SupervisorRPCError('Unsupported synthetic RPC method')
SupervisorClient._call=rpc

work=Path('/work');meta=work/'fixture.json'
runtime_start_time = ContextVar('runtime_start_time', default=None)
real_runtime_now = strategy_runtime._now
set_runtime_status = strategy_runtime.StrategyRuntimeStore.set_status

def runtime_now():
    return runtime_start_time.get() or real_runtime_now()

def fixture_runtime_status(self, owner, identifier, action):
    # Advance the two scripted market snapshots without a 24-hour pause. Only
    # this test account's Start action uses the historical clock; all heartbeats,
    # computation, next-bar fills and other status changes retain real time.
    marker = work / 'role-market-start.txt'
    if action != 'start' or not marker.is_file():
        return set_runtime_status(self, owner, identifier, action)
    if owner != json.loads(meta.read_text())['accounts']['outsider']['id']:
        return set_runtime_status(self, owner, identifier, action)
    token = runtime_start_time.set(datetime.fromtimestamp(int(marker.read_text()), UTC))
    try:
        return set_runtime_status(self, owner, identifier, action)
    finally:
        runtime_start_time.reset(token)

strategy_runtime._now = runtime_now
strategy_runtime.StrategyRuntimeStore.set_status = fixture_runtime_status

if not meta.exists():
    names=['author','subscriber','expired','outsider']+[f'user{i:02d}' for i in range(100)]
    password=os.environ.get('ATLAS_E2E_PASSWORD','Only-E2E-Fixture-2026!')
    users={}
    for name in names:
        user=journal_store.create_user(f'{name}@e2e.example.test',password)
        if user is None:raise RuntimeError('Refusing partial or foreign fixture database')
        users[name]=user
    releases={}
    for name,visibility,kind in [('private','private','builtin'),('public','public','builtin'),('python','private','python')]:
        body={'name':'E2E '+name+' strategy','source_kind':kind,'strategy_id':'sma_cross','params':{'fast':5,'slow':20},'markets':['CRYPTO','US','CN'],'source_visibility':visibility}
        if kind=='python':body.update(strategy_id='python_bounded',params={},python_source='def target_bps(index, close, sma):\n return (5000 if close(0) > sma(20) else 0) if index >= 20 else 0')
        releases[name]=strategy_runtime_store.create_release(users['author'].id,ReleaseCreate(**body))['id']
    now=datetime.now(UTC).isoformat()
    with strategy_runtime_store._connect() as db:
        for name in ['subscriber','expired','user44','user45','user46','user47']:
            for key,rid in releases.items():
                db.execute("INSERT INTO strategy_subscriptions VALUES (?,?,?,?,?,?)",('sub_e2e_'+name+'_'+key,users[name].id,rid,'cancelled' if name=='expired' else 'active',now,now if name=='expired' else None))
    datasets={}
    # Fixed, explicitly synthetic public snapshots. Query identities stay distinct.
    for asset in ASSETS:
        intervals=['1d','15m','1h','4h','1wk'] if asset.asset_class=='crypto' else ['1d']
        for interval in intervals:
            frame=make_frame(asset.symbol,interval)
            for adjustment in ['auto','raw','forward','backward']:
                bundle=DataBundle(asset,frame,'synthetic-e2e','Deterministic synthetic E2E fixture; not market evidence',datetime.now(UTC))
                query=dict(symbol=asset.symbol,asset_class=asset.asset_class,interval=interval,adjustment=adjustment,data_source='auto')
                rates={'CNY':1.,'USD':7.2,'USDT':7.2,'JPY':.048,'HKD':.92}
                conversions={}
                for currency in ['CNY','USD','USDT']:
                    converted=frame.copy();converted[['open','high','low','close']]*=rates.get(asset.currency,7.2)/rates[currency]
                    b=replace(bundle,asset=asset.model_copy(update={'currency':currency}),frame=converted)
                    conversions[currency]=market_publications.publish({**query,'base_currency':currency},b)['dataset_id']
                manifest=market_publications.publish(query,bundle,conversions)
                from app.market_publication import query_key
                with market_publications.connect() as db:
                    for source in ['yahoo','binance']:
                        db.execute('INSERT OR REPLACE INTO market_publications VALUES (?,?,?)',(query_key({**query,'data_source':source}),manifest['dataset_id'],json.dumps(manifest)))
                market_publications.publish({**query,'data_source':'demo'},replace(bundle,source='demo',source_note='Explicit synthetic demonstration fixture'),conversions)
                if adjustment=='auto':datasets[asset.symbol+':'+interval]={'dataset_id':manifest['dataset_id'],'start':manifest['start'],'end':manifest['end'],'count':manifest['count']}
    for user in users.values():strategy_runtime_store.list_accounts(user.id)
    meta.write_text(json.dumps({'schema':'atlas.e2e-fixture/v1','synthetic_only':True,'accounts':{n:{'id':u.id,'email':u.email} for n,u in users.items()},'releases':releases,'datasets':datasets,'ready':True}))

# Import only the pinned historical public receipt; never generate a proof.
if Path('/sample-bundle.zip').is_file():
    import subprocess
    output=subprocess.check_output([sys.executable,'/app/scripts/import-verified-proof.py','--bundle','/sample-bundle.zip','--expected-receipt-sha256','6c85feec41f6ad8bd64f3520984a9886ff877df1eac5f41298993157d58bd2d3'],text=True)
    m=json.loads(meta.read_text());m['proof_id']=json.loads(output)['proof_id'];meta.write_text(json.dumps(m))

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8000,workers=1,access_log=False,proxy_headers=True,forwarded_allow_ips='*')
