"""Trusted target-plan adapters. No user Python is evaluated in this process."""
import contextlib
import json
import sys
from datetime import datetime, timezone


def vnpy_run(payload):
    from importlib.metadata import version
    from vnpy.trader.constant import Direction, Exchange, Interval
    from vnpy.trader.object import BarData
    from vnpy_ctastrategy import CtaTemplate
    from vnpy_ctastrategy.backtesting import BacktestingEngine

    r, bars = payload['request'], payload['bars']
    plan = payload.get('prepared_strategy')
    fast, slow = (int(r['params'].get('fast',20)),int(r['params'].get('slow',60))) if plan is None else (20,60)
    impact = r['slippage_rate'] + r['spread_rate'] / 2
    costs = r['commission_rate'] + impact
    fills, snapshots, replayed = [], [], []

    class TargetStrategy(CtaTemplate):
        def __init__(self, *args):
            super().__init__(*args)
            self.closes = []
            self.cash = r['initial_capital']
            self.average = 0
        def on_init(self): pass
        def on_start(self): pass
        def on_stop(self): pass
        def on_order(self, order): pass
        def on_trade(self, trade):
            buy = trade.direction == Direction.LONG
            q, price = trade.volume, trade.price
            fee = q * price * r['commission_rate']
            friction = q * price * impact
            old = self.pos - (q if buy else -q)
            pnl = None
            if buy:
                self.average = (old * self.average + q * price + fee + friction) / self.pos
                self.cash -= q * price + fee + friction
            else:
                pnl = q * (price - self.average) - fee - friction
                self.cash += q * price - fee - friction
            fills.append(dict(time=int(trade.datetime.timestamp()), side='buy' if buy else 'sell',
                price=price, quantity=q, fee=fee, slippage_cost=friction,
                position_after=self.pos, cash_after=self.cash, realized_pnl=pnl))
        def on_bar(self, bar):
            self.cancel_all()
            self.closes.append(bar.close_price)
            if plan is None and len(self.closes) < slow: return
            target = plan['targets'][len(self.closes)-1] if plan else (r['max_position'] if sum(self.closes[-fast:])/fast > sum(self.closes[-slow:])/slow else 0)
            if plan and 'amount' in plan:
                if not plan['due'][len(self.closes)-1]: return
                equity=self.cash+self.pos*bar.close_price
                addition=min(plan['amount'],self.cash)/(bar.close_price*(1+costs))
                target=min(r['max_position'],(self.pos+addition)*bar.close_price/equity)
            if self.pos and ((r.get('stop_loss') and bar.close_price <= self.average*(1-r['stop_loss'])) or
                             (r.get('take_profit') and bar.close_price >= self.average*(1+r['take_profit']))):
                target = 0
            equity = self.cash + self.pos * bar.close_price
            desired = target * equity / (bar.close_price * (1+costs))
            delta = desired - self.pos
            if abs(delta * bar.close_price) < max(equity*0.001, 1): return
            if delta > 0: self.buy(bar.close_price*100, delta)
            else: self.sell(bar.close_price/100, min(-delta, self.pos))

    class RecordingEngine(BacktestingEngine):
        def output(self, msg): pass
        def cross_limit_order(self):
            # Keep vn.py's matching and events; constrain submitted orders before matching.
            for key, order in list(self.active_limit_orders.items()):
                price = self.bar.open_price
                limit = self.bar.volume * r['max_participation_rate']
                if order.direction == Direction.LONG:
                    equity = self.strategy.cash + self.strategy.pos * price
                    limit = min(limit, max(0, self.strategy.cash)/(price*(1+costs)),
                                max(0, r['max_position']*equity/price-self.strategy.pos))
                else: limit = min(limit, self.strategy.pos)
                order.volume = min(order.volume, limit)
                if order.volume <= 1e-10: self.active_limit_orders.pop(key)
            super().cross_limit_order()
        def new_bar(self, bar):
            replayed.append(dict(time=int(bar.datetime.timestamp()),open=bar.open_price,high=bar.high_price,
                low=bar.low_price,close=bar.close_price,volume=bar.volume))
            super().new_bar(bar)
            snapshots.append(dict(time=int(bar.datetime.timestamp()),
                equity=self.strategy.cash+self.strategy.pos*bar.close_price,
                exposure=(self.strategy.pos*bar.close_price)/(self.strategy.cash+self.strategy.pos*bar.close_price)))

    engine = RecordingEngine()
    symbol = 'BTCUSDT' if r['asset_class']=='crypto' else r['symbol'].replace('.','_')
    engine.set_parameters(vt_symbol=symbol+'.LOCAL', interval=Interval.DAILY if r['interval']=='1d' else Interval.MINUTE,
        start=datetime.fromtimestamp(bars[0]['time'], timezone.utc), end=datetime.fromtimestamp(bars[-1]['time'], timezone.utc),
        rate=costs, slippage=0, size=1, pricetick=1e-8, capital=r['initial_capital'])
    engine.add_strategy(TargetStrategy, {})
    engine.history_data = [BarData(symbol=symbol, exchange=Exchange.LOCAL,
        datetime=datetime.fromtimestamp(b['time'],timezone.utc), interval=engine.interval, volume=b['volume'],
        open_price=b['open'], high_price=b['high'], low_price=b['low'], close_price=b['close'], gateway_name='ATLAS_CACHE') for b in bars]
    engine.run_backtesting()
    if len(snapshots) != len(bars): raise ValueError('vn.py 未完成历史回放')
    return dict(version=version('vnpy')+' / CTA '+version('vnpy_ctastrategy'), bars=replayed, fills=fills, snapshots=snapshots,
        warnings=['vn.py CTA 原生限价撮合；收盘提交激进限价单，最早下一根开盘成交。滑点与半价差按成交额计入成本，不改变原生撮合价。',
                  '适配器使用无杠杆、仅做多现金账户约束；这不是 vn.py 默认的期货保证金模型。',
                  *(['A股通用研究适配尚不模拟 T+1、整手、涨跌停及印花税，不能视为可执行的 A 股交易回测。'] if r['asset_class']=='equity' else [])])


def rqalpha_published_run(payload):
    """Replay the same published OHLCV via the real RQAlpha broker/account."""
    from importlib.metadata import version
    import pandas as pd
    from rqalpha import run_func
    from rqalpha.api import order_target_percent, subscribe
    from rqalpha.environment import Environment
    from rqalpha.core.events import EVENT
    import hf_rqalpha

    hf_rqalpha.PAYLOAD = payload
    r, bars = payload['request'], payload['bars']
    code = r['symbol'].replace('.SS','.XSHG').replace('.SZ','.XSHE')
    plan=payload.get('prepared_strategy')
    fast, slow = (int(r['params'].get('fast',20)),int(r['params'].get('slow',60))) if plan is None else (20,60)
    closes, snapshots, fills, replayed = [], [], [], []
    event_labels = {}

    def init(context):
        subscribe(code)
        env = Environment.get_instance()
        if env.data_source.missing_limits:
            raise ValueError('RQAlpha bundle缺少所选交易日的涨跌停参考字段，不能完整模拟')
        event_labels.update({dt: b['time'] for dt,b in env.data_source.events if b is not None})
        def snapshot(event):
            if env.calendar_dt not in event_labels:
                return
            portfolio = env.portfolio
            snapshots.append(dict(time=event_labels[env.calendar_dt], equity=float(portfolio.total_value),
                exposure=float(portfolio.market_value / portfolio.total_value)))
        env.event_bus.add_listener(EVENT.POST_BAR, snapshot)
        def record_trade(event):
            from rqalpha.const import SIDE
            trade = event.trade
            if trade.order_book_id != code:
                return
            position = env.portfolio.positions[code]
            buy = trade.side == SIDE.BUY
            quantity, price, fee = float(trade.last_quantity),float(trade.last_price),float(trade.transaction_cost)
            fills.append(dict(time=event_labels[trade.trading_datetime],side='buy' if buy else 'sell',
                price=price,quantity=quantity,fee=fee,slippage_cost=0,
                position_after=float(position.quantity),cash_after=float(env.portfolio.cash),
                realized_pnl=None if buy else quantity*(price-position.avg_price)-fee))
        env.event_bus.add_listener(EVENT.TRADE, record_trade)

    def handle_bar(context, data):
        if context.now not in event_labels:
            return
        b = data[code]
        replayed.append(dict(time=event_labels[context.now],open=float(b.open),high=float(b.high),
            low=float(b.low),close=float(b.close),volume=float(b.volume)))
        closes.append(float(b.close))
        if plan is None and len(closes) < slow:
            return
        target = plan['targets'][len(closes)-1] if plan else (r['max_position'] if sum(closes[-fast:])/fast > sum(closes[-slow:])/slow else 0)
        if plan and 'amount' in plan:
            if not plan['due'][len(closes)-1]:return
            target=min(r['max_position'],(context.portfolio.positions[code].quantity*b.close+min(plan['amount'],context.portfolio.cash))/context.portfolio.total_value)
        position = context.portfolio.positions[code]
        if position.quantity and ((r.get('stop_loss') and b.close<=position.avg_price*(1-r['stop_loss'])) or
                (r.get('take_profit') and b.close>=position.avg_price*(1+r['take_profit']))):
            target = 0
        # Zero-volume observations remain in the tape, but cannot execute.
        if b.volume > 0:
            order_target_percent(code, target)

    first = pd.Timestamp(bars[0]['time'],unit='s',tz='UTC').tz_convert('Asia/Shanghai')
    last = pd.Timestamp(bars[-1]['time'],unit='s',tz='UTC').tz_convert('Asia/Shanghai')
    end = last + pd.Timedelta(days=6) if r['interval']=='1wk' else last
    result = run_func(config={
        'base':{'start_date':str(first.date()),'end_date':str(end.date()),'frequency':'1m',
                'accounts':{'stock':r['initial_capital']},'data_bundle_path':payload['bundle_path']},
        'extra':{'log_level':'error'},
        'mod':{'atlas_published':{'enabled':True,'lib':'hf_rqalpha','priority':10000},
               'sys_analyser':{'enabled':True,'plot':False,'record':True},
               'sys_simulation':{'matching_type':'current_bar','volume_limit':True,
                    'inactive_limit':True,'volume_percent':r['max_participation_rate'],
                    'slippage':r['slippage_rate']+r['spread_rate']/2},
               'sys_transaction_cost':{'stock_commission_multiplier':r['commission_rate']/0.0008}}},
        init=init,handle_bar=handle_bar)
    if not result or 'sys_analyser' not in result or len(snapshots)!=len(bars):
        raise ValueError('RQAlpha 未完成已发布K线与账户逐根回放')
    return dict(version=version('rqalpha'),bars=replayed,fills=fills,snapshots=snapshots,
        warnings=['RQAlpha 原生账户与撮合；输入OHLCV与图表、Atlas、vn.py使用同一不可变行情版本。',
            '按已完成的输入周期触发回放（不是将5分钟数据伪造成1分钟）；策略信号来自区间内已关闭K线。',
            '当根收盘撮合，含原生T+1、整手、最低佣金及印花税。与下一根开盘撮合的框架收益可能不同。',
            '股票资料、交易日历、公司行动、涨跌停价来自本地RQAlpha bundle；HF自身不含这些字段。未提供可独立核验的逐笔成交。'])


def rqalpha_run(payload):
    if 'bars' in payload:
        return rqalpha_published_run(payload)
    from importlib.metadata import version
    from rqalpha import run_func
    from rqalpha.api import history_bars, order_target_percent
    import pandas as pd
    r = payload['request']
    code = r['symbol'].replace('.SS','.XSHG').replace('.SZ','.XSHE')
    fast, slow = int(r['params'].get('fast',20)), int(r['params'].get('slow',60))
    bars = []
    def init(context): context.code = code
    def handle_bar(context, data):
        b = data[code]
        ts = int(pd.Timestamp(context.now).tz_localize('Asia/Shanghai').timestamp())
        bars.append(dict(time=ts, open=float(b.open),high=float(b.high),low=float(b.low),close=float(b.close),volume=float(b.volume)))
        hist = history_bars(code, slow, '1d', 'close', include_now=True)
        if len(hist)<slow: return
        target = r['max_position'] if hist[-fast:].mean()>hist.mean() else 0
        position = context.portfolio.positions[code]
        if position.quantity and ((r.get('stop_loss') and b.close<=position.avg_price*(1-r['stop_loss'])) or
                                  (r.get('take_profit') and b.close>=position.avg_price*(1+r['take_profit']))): target=0
        order_target_percent(code,target)
    start_date = str(pd.Timestamp(r['start']).tz_convert('Asia/Shanghai').date())
    end_date = str(pd.Timestamp(r['end']).tz_convert('Asia/Shanghai').date())
    result=run_func(config={'base':{'start_date':start_date, 'end_date':end_date, 'frequency':'1d',
        'accounts':{'stock':r['initial_capital']}, 'data_bundle_path':payload['bundle_path']},
        'extra':{'log_level':'error'},
        'mod':{'sys_analyser':{'enabled':True,'plot':False,'record':True},
               'sys_simulation':{'matching_type':'current_bar','volume_limit':True,'volume_percent':r['max_participation_rate'],
                    'slippage':r['slippage_rate']+r['spread_rate']/2},
               'sys_transaction_cost':{'stock_commission_multiplier':r['commission_rate']/0.0008}}},
        init=init,handle_bar=handle_bar)
    if not result or 'sys_analyser' not in result: raise ValueError('RQAlpha 没有返回分析结果')
    report=result['sys_analyser']
    # RQAlpha supplies native portfolio values and transaction costs, including tax.
    portfolio=report['portfolio']
    if len(portfolio) != len(bars): raise ValueError('RQAlpha 行情与账户日期不一致')
    snapshots=[]
    for b, (_,row) in zip(bars,portfolio.iterrows()):
        snapshots.append(dict(time=b['time'],equity=float(row['total_value']),exposure=float(row['market_value']/row['total_value'])))
    fills=[]
    cash=r['initial_capital']; quantity=0; average=0
    for _, row in report['trades'].iterrows():
        buy=str(row['side']).upper()=='BUY'
        q=float(row['last_quantity']); price=float(row['last_price']); fee=float(row['transaction_cost'])
        pnl=None
        if buy:
            average=(quantity*average+q*price+fee)/(quantity+q)
            quantity+=q;cash-=q*price+fee
        else:
            quantity-=q;cash+=q*price-fee;pnl=q*(price-average)-fee
        fills.append(dict(time=int(pd.Timestamp(row['trading_datetime']).tz_localize('Asia/Shanghai').timestamp()),
            side='buy' if buy else 'sell',price=price,quantity=q,fee=fee,slippage_cost=0,
            position_after=quantity,cash_after=cash,realized_pnl=pnl))
    if len(bars)!=len(snapshots): raise ValueError('RQAlpha K线与账户记录数量不一致')
    return dict(version=version('rqalpha'),bars=bars,fills=fills,snapshots=snapshots,
        warnings=['RQAlpha 使用自己的中国股票日线 bundle、交易日历、T+1、整手、最低佣金和印花税规则；并非 Binance 数据。',
                  '日线使用原生 current_bar 收盘撮合及 PriceRatioSlippage，与当前引擎的下一根开盘成交口径不同；原生成交价已包含滑点，报告不重复计费。',
                  '均线预热读取区间开始前的 bundle 历史；执行价格使用原生未复权行情，历史均线采用 RQAlpha 默认前复权口径。日期按上海时区的完整交易日处理。'])


if __name__ == '__main__':
    payload=json.load(sys.stdin)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if payload.get('operation') == 'load_bundle':
                from bundle_input import load_bars
                result = load_bars(payload)
            elif payload['request'].get('execution_model') == 'unified':
                from unified_runner import vnpy_replay, rqalpha_replay
                result = vnpy_replay(payload) if payload['engine']=='vnpy' else rqalpha_replay(payload)
            else:
                result=vnpy_run(payload) if payload['engine']=='vnpy' else rqalpha_run(payload)
        print(json.dumps(result,allow_nan=False))
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({'error':str(exc)}))
        sys.exit(1)
