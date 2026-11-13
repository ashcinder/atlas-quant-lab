"""Real framework event adapters feeding an explicitly shared research ledger.

No native-stock matching is claimed in this mode. Native mode stays separate.
"""
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backtest.unified import ResearchLedger, CONTRACT, NOTICE


def vnpy_replay(payload):
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData
    from vnpy_ctastrategy import CtaTemplate
    from vnpy_ctastrategy.backtesting import BacktestingEngine
    r, bars = payload['request'], payload['bars']
    ledger = ResearchLedger(r,payload.get('prepared_strategy'))
    replayed = []

    class Strategy(CtaTemplate):
        def on_init(self): pass
        def on_start(self): pass
        def on_stop(self): pass
        def on_bar(self, bar):
            actual = dict(time=int(bar.datetime.timestamp()),open=bar.open_price,high=bar.high_price,
                low=bar.low_price,close=bar.close_price,volume=bar.volume)
            replayed.append(actual)
            ledger.step(actual)

    class Engine(BacktestingEngine):
        def output(self, message): pass

    symbol=r['symbol'].replace('.','_')
    engine = Engine()
    engine.set_parameters(vt_symbol=symbol+'.LOCAL',interval=Interval.MINUTE,
        start=datetime.fromtimestamp(bars[0]['time'],timezone.utc),
        end=datetime.fromtimestamp(bars[-1]['time'],timezone.utc),rate=0,slippage=0,
        size=1,pricetick=.01,capital=r['initial_capital'])
    engine.add_strategy(Strategy,{})
    engine.history_data = [BarData(symbol=symbol,exchange=Exchange.LOCAL,
        datetime=datetime.fromtimestamp(b['time'],timezone.utc),interval=Interval.MINUTE,
        open_price=b['open'],high_price=b['high'],low_price=b['low'],close_price=b['close'],
        volume=b['volume'],gateway_name='PUBLISHED') for b in bars]
    engine.run_backtesting()
    return output(ledger,replayed,'vnpy '+version('vnpy')+' / CTA '+version('vnpy_ctastrategy'))


def rqalpha_replay(payload):
    import pandas as pd
    from rqalpha import run_func
    from rqalpha.api import subscribe
    from rqalpha.environment import Environment
    import hf_rqalpha
    hf_rqalpha.PAYLOAD = payload
    r, bars = payload['request'], payload['bars']
    ledger, replayed, labels = ResearchLedger(r,payload.get('prepared_strategy')), [], {}
    code = r['symbol'].replace('.SS','.XSHG').replace('.SZ','.XSHE')

    def init(context):
        subscribe(code)
        labels.update({dt:b['time'] for dt,b in Environment.get_instance().data_source.events if b is not None})

    def handle_bar(context, data):
        if context.now not in labels: return
        b = data[code]
        actual = dict(time=labels[context.now],open=float(b.open),high=float(b.high),
            low=float(b.low),close=float(b.close),volume=float(b.volume))
        replayed.append(actual)
        ledger.step(actual)

    first = pd.Timestamp(bars[0]['time'],unit='s',tz='UTC').tz_convert('Asia/Shanghai')
    last = pd.Timestamp(bars[-1]['time'],unit='s',tz='UTC').tz_convert('Asia/Shanghai')
    end = last+pd.Timedelta(days=6) if r['interval']=='1wk' else last
    run_func(config={'base':{'start_date':str(first.date()),'end_date':str(end.date()),'frequency':'1m',
        'accounts':{'stock':r['initial_capital']},'data_bundle_path':payload['bundle_path']},
        'extra':{'log_level':'error'},
        'mod':{'atlas_published':{'enabled':True,'lib':'hf_rqalpha','priority':10000},
               'sys_analyser':{'enabled':False},'sys_progress':{'enabled':False}}},init=init,handle_bar=handle_bar)
    return output(ledger,replayed,'rqalpha '+version('rqalpha'))


def output(ledger, replayed, engine_version):
    if ledger.count != len(replayed): raise ValueError('框架回放不完整')
    return dict(version=engine_version,execution_model='unified',execution_contract=CONTRACT,
        bars=replayed,fills=ledger.fills,snapshots=ledger.snapshots,warnings=[NOTICE])
