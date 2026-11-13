"""Versioned research cash ledger, numerically paired with Atlas TypeScript.

Framework adapters feed actual bar callbacks here. This is deliberately a
shared execution model, NOT the frameworks' native stock accounts/matchers.
Fractional long-only shares; no T+1, corporate actions, tax or price limits.
"""
import math

CONTRACT = 'research-next-open/v1'
NOTICE = ('统一研究口径 research-next-open/v1：框架负责事件回放，共用信号与成交账本；'
          '收盘信号、下一根开盘成交，滑点与半价差进入成交价，按成交额收费；'
          '允许零股，不模拟T+1、涨跌停、印花税或分红送转。不是原生A股账户。')


def validate_unified(request):
    if request.get('release_id'):
        raise ValueError('统一研究口径需要已解析的策略定义')
    if request.get('execution_pipeline') and any(s.get('enabled') for s in request['execution_pipeline'].get('ai_stages',[])):
        raise ValueError('统一研究口径不执行逐步AI审核')


class ResearchLedger:
    def __init__(self, request, plan=None):
        validate_unified(request)
        self.r = request
        self.plan = plan
        self.pending_due = False
        self.fast = int(request.get('params', {}).get('fast', 20)) if plan is None else 20
        self.slow = int(request.get('params', {}).get('slow', 60)) if plan is None else 60
        self.cash = request['initial_capital']
        self.quantity = self.average = 0.0
        self.pending = self.last_signal = self.active = 0.0
        self.reason = '初始状态'
        self.rebalancing = False
        self.previous_close = None
        self.closes = []
        self.fills, self.snapshots = [], []
        self.count = 0

    def step(self, bar):
        r = self.r
        opened, closed = bar['open'], bar['close']
        equity = self.cash + self.quantity * opened
        if self.count:
            if abs(self.pending-self.last_signal) > 1e-9 + 1e-5*abs(self.last_signal):
                self.last_signal = self.pending
                self.active = self.pending
                self.rebalancing = True
            fraction = self.quantity*opened/equity if equity > 0 else 0
            desired = self.active*equity/opened
            scheduled = bool(self.plan and 'amount' in self.plan)
            if scheduled:
                self.rebalancing = self.pending_due
                impact = 1+r['slippage_rate']+r['spread_rate']/2
                budget = min(self.plan['amount'],max(0,self.cash))
                allowed = max(0,r['max_position']*equity-self.quantity*opened)
                addition = min(budget/(opened*impact*(1+r['commission_rate'])),allowed/(opened*impact)) if self.rebalancing else 0
                desired = self.quantity+addition
                self.active = desired*opened/equity if equity>0 else 0
                self.reason = '固定金额定投（下一根开盘）'
            if self.quantity > 0 and self.average > 0:
                if r.get('stop_loss') and self.previous_close <= self.average*(1-r['stop_loss']):
                    self.active = desired = 0
                    self.rebalancing = True
                    self.reason = '收盘确认止损'
                elif r.get('take_profit') and self.previous_close >= self.average*(1+r['take_profit']):
                    self.active = desired = 0
                    self.rebalancing = True
                    self.reason = '收盘确认止盈'
            delta = desired-self.quantity
            if self.rebalancing and abs(delta*opened) >= (.01 if scheduled else max(equity*.001, 1)) and (scheduled or abs(fraction-self.active) >= .001):
                buy = delta > 0
                impact = r['slippage_rate'] + r['spread_rate']/2
                price = opened*(1+impact if buy else 1-impact)
                maximum = bar['volume']*opened*r['max_participation_rate']
                amount = min(abs(delta), maximum/price)
                if buy:
                    amount = min(amount, self.cash/(price*(1+r['commission_rate'])))
                notional = amount*price
                fee = notional*r['commission_rate']
                friction = amount*abs(price-opened)
                pnl = None
                if amount > 0:
                    if buy:
                        old_cost = self.average*self.quantity
                        self.cash -= notional+fee
                        self.quantity += amount
                        self.average = (old_cost+notional+fee)/self.quantity
                    else:
                        amount = min(amount, self.quantity)
                        notional = amount*price
                        fee = notional*r['commission_rate']
                        self.cash += notional-fee
                        pnl = (price-self.average)*amount-fee
                        self.quantity -= amount
                        if self.quantity <= 1e-12:
                            self.quantity = self.average = 0
                    self.fills.append(dict(time=bar['time'],side='buy' if buy else 'sell',reason=self.reason,
                        price=price,quantity=amount,fee=fee,slippage_cost=friction,
                        position_after=self.quantity,cash_after=self.cash,realized_pnl=pnl))
            post = self.cash+self.quantity*opened
            fraction = self.quantity*opened/post if post > 0 else 0
            remaining = abs(self.active*post-self.quantity*opened)
            if abs(fraction-self.active) < .002 or remaining < max(post*.001, 1):
                self.rebalancing = False
        equity = self.cash+self.quantity*closed
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError('统一账户出现无效净值')
        self.snapshots.append(dict(time=bar['time'],equity=equity,exposure=self.quantity*closed/equity))
        if self.plan is not None:
            self.pending = self.plan['targets'][self.count]
            self.reason = self.plan['reasons'][self.count] if self.plan.get('reasons') else self.plan.get('reason','策略收盘信号')
            self.pending_due = bool(self.plan.get('due') and self.plan['due'][self.count])
            self.previous_close = closed
            self.count += 1
            return
        self.closes.append(closed)
        if len(self.closes) > self.slow:
            del self.closes[0]
        # Explicit left-to-right addition matches JS reduce, including at ties.
        fast_sum = slow_sum = 0.0
        for value in self.closes[-self.fast:]:
            fast_sum += value
        for value in self.closes:
            slow_sum += value
        above = len(self.closes) >= self.slow and fast_sum/self.fast > slow_sum/self.slow
        self.pending = r['max_position'] if above else 0
        self.reason = '快速均线位于慢速均线上方' if above else '均线差距、确认期或趋势过滤未满足'
        self.previous_close = closed
        self.count += 1
