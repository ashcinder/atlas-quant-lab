"""Native RQAlpha daily auction execution for the leader/peer experiment.

No broker connection. Decisions receive only T features and opening-public T+1
prices. In particular, today's final volume is NEVER an auction size budget.
"""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

import h5py
import numpy as np
import pandas as pd


def performance(nav, capital=1.0):
    nav=pd.Series(nav,dtype=float)/capital
    returns=nav.div(nav.shift(1).fillna(1))-1
    peak=np.maximum.accumulate(np.r_[1,nav.to_numpy()])[1:]
    years=len(nav)/252
    std=float(returns.std(ddof=1))
    return {'total_return':float(nav.iloc[-1]-1),
            'annual_return':float(nav.iloc[-1]**(1/years)-1),
            'max_drawdown':float((nav.to_numpy()/peak-1).min()),
            'sharpe_zero_rf':float(returns.mean()/std*np.sqrt(252)) if std else 0.,
            'sessions':len(nav),
            'yearly_returns':{str(k):float(v) for k,v in returns.groupby(returns.index.year).apply(lambda x:(1+x).prod()-1).items()}}


def block_confidence(returns, benchmark=None, repeats=1000, block=20):
    """Paired moving-block bootstrap; conditional on this historical sample."""
    rng=np.random.default_rng(20261112)
    data=np.asarray(returns,dtype=float);n=len(data)
    if n<block:return {}
    annual=[];excess=[]
    for _ in range(repeats):
        starts=rng.integers(0,n-block+1,size=math.ceil(n/block))
        ids=np.concatenate([np.arange(s,s+block) for s in starts])[:n]
        growth=np.exp(np.log1p(data[ids]).mean()*252)-1
        annual.append(growth)
        if benchmark is not None:
            excess.append(np.log1p(data[ids]).mean()*252-np.log1p(np.asarray(benchmark)[ids]).mean()*252)
    result={'annual_return_95':np.quantile(annual,[.025,.975]).tolist(), 'method':'20-session moving-block bootstrap, 1000 draws'}
    if excess:result['annual_log_excess_95']=np.quantile(excess,[.025,.975]).tolist()
    return result


def plan_peer_orders(signals,held_values,cash,meta,references,p,impact):
    """Freeze auction orders WITHOUT a final open price or any fill outcomes.

    references maps symbol -> (ex-rights reference, published upper limit).
    Existing positions, including planned exits, reserve their slots and gross
    exposure. Same-auction sell proceeds cannot finance conditional new orders.
    """
    reserved=dict(held_values);nav=cash+sum(reserved.values());plans=[];skips=Counter()
    for signal in signals:
        for follower in signal['followers']:
            code=str(follower['symbol'])
            if code==signal['symbol'] or meta[code]['industry_code']!=signal['industry']:
                raise AssertionError('Peer must differ from leader and share its industry')
            if code in reserved:continue
            if len(reserved)>=p.max_positions:skips['max_positions']+=1;continue
            if code not in references:skips['entry_suspended_or_no_reference']+=1;continue
            reference,upper=references[code]
            # Pre-auction buy limit rejects >3% gaps and the upper limit without
            # observing the realized auction price first. Round down to one cent.
            limit=math.floor((min(reference*(1+p.max_open_gap),upper-.01)+1e-9)*100)/100
            if not np.isfinite(limit) or limit<=0:skips['invalid_order_limit']+=1;continue
            sector=sum(value for key,value in reserved.items() if meta[key]['industry_code']==signal['industry'])
            if sum(meta[key]['industry_code']==signal['industry'] for key in reserved)>=p.followers_per_industry:
                skips['industry_position_cap']+=1;continue
            budget=min(p.stock_weight*nav,p.industry_weight*nav-sector,
                p.max_gross*nav-sum(reserved.values()),cash*.98,float(follower['adv20'])*p.max_adv_fraction)
            budget=max(0,budget-p.min_commission)/(1+p.commission+impact+p.transfer)
            quantity=int(budget/limit)
            if code.startswith('688'):quantity=quantity if quantity>=200 else 0
            else:quantity=quantity//100*100
            if quantity<=0:skips['below_lot_or_budget']+=1;continue
            notional=quantity*limit
            reserved[code]=notional
            cash-=notional+max(p.min_commission,notional*p.commission)+notional*(impact+p.transfer)
            plans.append({'symbol':code,'quantity':quantity,'order_limit':limit,
                'reason':'peer_entry','signal_date':str(signal['date'].date()),
                'leader':str(signal['symbol']),'industry':str(signal['industry']),
                'probability':float(signal['probability']),'lagged_adv20':float(follower['adv20']),
                'open_reference':reference,'open_limit_up':upper,'budget_at_order':budget,'nav_at_order':nav})
    return plans,skips


def run_one(bundle, output, p, predictions, meta, name, filtered=True, impact=None):
    from rqalpha import run_func
    from rqalpha.api import update_universe, order_shares, cancel_order
    from rqalpha.model.order import LimitOrder
    from rqalpha.environment import Environment
    from rqalpha.const import INSTRUMENT_TYPE, SIDE
    from rqalpha.core.events import EVENT
    from rqalpha.interface import TransactionCost, AbstractTransactionCostDecider

    impact=p.impact if impact is None else impact
    # Strip evaluation-only labels before anything enters trading callbacks.
    allowed=['date','symbol','industry','followers','probability','ret20']
    trade_signals=predictions.loc[predictions.selected if filtered else np.ones(len(predictions),dtype=bool),allowed].copy()
    rank='probability' if filtered else 'ret20'
    by_date={date.date():group.sort_values([rank,'industry'],ascending=[False,True]).to_dict('records')
             for date,group in trade_signals.groupby('date')}
    fills=[];skips=Counter();daily_audit=[];end_positions=[]
    raw_cache={}
    stocks=h5py.File(bundle/'stocks.h5','r')

    def opening_reference(code,date):
        # This reference is public BEFORE the opening auction, not high/low/close,
        # full-day turnover or full-day volume. prev_close handles ex-rights.
        if code not in raw_cache:
            raw=stocks[code][:]
            raw_cache[code]=(raw['datetime']//1_000_000, raw['prev_close'])
        dates,values=raw_cache[code];number=int(date.strftime('%Y%m%d'))
        index=np.searchsorted(dates,number)
        return float(values[index]) if index<len(dates) and dates[index]==number else float('nan')

    class CostWithImpact(AbstractTransactionCostDecider):
        def __init__(self,base): self.base=base
        def calc(self,args):
            cost=self.base.calc(args)
            return TransactionCost(cost.commission,cost.tax,cost.other_fees+args.quantity*args.price*(impact+p.transfer))
        def batch_estimate(self,delta_quantities,prices):
            return self.base.batch_estimate(delta_quantities,prices)+delta_quantities.abs()*prices*(impact+p.transfer)

    def on_trade(context,event):
        trade=event.trade;code=trade.order_book_id
        info=dict(context.order_info)
        if info.get('symbol')!=code:info={'reason':'engine_corporate_action','symbol':code}
        fills.append({'date':str(trade.trading_datetime.date()),'native_daily_time':str(trade.trading_datetime.time()),
            'execution_phase':'OPEN_AUCTION' if info.get('reason')!='engine_corporate_action' else 'ENGINE',
            'symbol':code,'side':trade.side.name,'quantity':int(trade.last_quantity),
            'price':float(trade.last_price),'cost':float(trade.transaction_cost),
            'commission':float(trade.commission),'tax':float(trade.tax),
            'impact_and_transfer':float(trade.transaction_cost-trade.commission-trade.tax),**info})
        if trade.side==SIDE.BUY:
            context.entries.setdefault(code,context.session)
            context.entry_info[code]=info

    def init(context):
        update_universe(sorted(meta))
        context.session=-1;context.pending=[];context.entries={};context.entry_info={}
        context.exit_reason={};context.last_close={};context.order_info={}
        env=Environment.get_instance()
        base=env.get_transaction_cost_decider(INSTRUMENT_TYPE.CS)
        env.set_transaction_cost_decider(INSTRUMENT_TYPE.CS,CostWithImpact(base))
        env.event_bus.add_listener(EVENT.TRADE,lambda event:on_trade(context,event))

    def positions(context):
        return {code:pos for code,pos in context.portfolio.positions.items() if pos.quantity>0}

    def open_auction(context,bars):
        context.session+=1
        today=context.now.date();env=Environment.get_instance()
        # Plan ALL buys before submitting anything. No final opening prices,
        # auction fill outcomes, or hypothetical sale proceeds enter the plan.
        held=positions(context)
        values={code:pos.quantity*opening_reference(code,today) for code,pos in held.items()}
        values={code:value if np.isfinite(value) and value>0 else held[code].quantity*context.last_close.get(code,0.) for code,value in values.items()}
        references={}
        for signal in context.pending:
            assert signal['date'].date()<today
            for follower in signal['followers']:
                code=str(follower['symbol']);reference=opening_reference(code,today)
                if not env.data_proxy.is_suspended(code,today) and np.isfinite(reference) and reference>0:
                    references[code]=(reference,float(bars[code].limit_up))
        plans,rejected=plan_peer_orders(context.pending,values,float(context.portfolio.cash),meta,references,p,impact)
        skips.update(rejected)

        def submit_auction_only(code,quantity,limit,info):
            context.order_info=info
            order=order_shares(code,quantity,LimitOrder(limit))
            # RQAlpha fills immediately in OPEN_AUCTION. Prevent an unmatched
            # auction limit from later filling at the close of this daily bar.
            if order is not None and not order.is_final():
                cancel_order(order);skips['unfilled_auction_'+('buy' if quantity>0 else 'sell')]+=1

        for code,pos in held.items():
            age=context.session-context.entries.get(code,context.session)
            if age<p.holding_sessions and code not in context.exit_reason:continue
            if env.data_proxy.is_suspended(code,today):skips['exit_suspended']+=1;continue
            if pos.sellable<=0:skips['exit_t_plus_one']+=1;continue
            limit=round(float(bars[code].limit_down)+.01,2)
            info={**context.entry_info.get(code,{}),'symbol':code,
                'reason':context.exit_reason.get(code,'holding_3_sessions'),
                'held_sessions':age,'sell_avg_cost':float(pos.avg_price),'order_limit':limit}
            submit_auction_only(code,-int(pos.sellable),limit,info)
            if code not in positions(context):
                context.entries.pop(code,None);context.entry_info.pop(code,None);context.exit_reason.pop(code,None)
        for plan in plans:
            info={key:value for key,value in plan.items() if key!='quantity'}
            submit_auction_only(plan['symbol'],plan['quantity'],plan['order_limit'],info)
        context.pending=[]

    def handle_bar(context,bars):
        for code,pos in positions(context).items():
            close=float(bars[code].close)
            if np.isfinite(close) and close>0:
                context.last_close[code]=close
                pnl=close/pos.avg_price-1 if pos.avg_price else 0
                if pnl<=-p.stop_loss:context.exit_reason[code]='close_confirmed_stop'
                elif pnl>=p.take_profit:context.exit_reason[code]='close_confirmed_take_profit'
        context.pending=by_date.get(context.now.date(),[])
        held=positions(context)
        daily_audit.append({'date':str(context.now.date()),'positions':len(held),
            'exposure':sum(pos.market_value for pos in held.values())/context.portfolio.total_value,
            'overdue_positions':sum(context.session-context.entries.get(code,context.session)>p.holding_sessions for code in held)})
        end_positions[:]=[{'symbol':code,'quantity':float(pos.quantity),'avg_price':float(pos.avg_price),
            'held_sessions':context.session-context.entries.get(code,context.session)} for code,pos in held.items()]

    config={'base':{'start_date':p.test_start,'end_date':p.test_end,'frequency':'1d',
                   'accounts':{'stock':p.capital},'capital_gain_tax_rate':0,'data_bundle_path':str(bundle)},
            'extra':{'log_level':'error'},
            'mod':{'sys_accounts':{'dividend_tax_enabled':True},
                   'sys_simulation':{'enabled':True,'matching_type':'current_bar',
                     'price_limit':True,'volume_limit':False,'inactive_limit':False,'slippage':0},
                   'sys_transaction_cost':{'enabled':True,'stock_commission_multiplier':p.commission/.0008,
                        'stock_min_commission':p.min_commission,'pit_tax':True},
                   'sys_analyser':{'enabled':True,'benchmark':'000300.XSHG','plot':False},
                   'sys_progress':{'enabled':False}}}
    folder=output/name;folder.mkdir(parents=True,exist_ok=True)
    try:
        with (folder/'engine.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
            result=run_func(config=config,init=init,open_auction=open_auction,handle_bar=handle_bar)
    finally:stocks.close()
    if not result or 'sys_analyser' not in result:
        raise RuntimeError(f'RQAlpha failed; inspect {folder}/engine.log')
    analysed=result['sys_analyser'];portfolio=analysed['portfolio'];benchmark=analysed['benchmark_portfolio']
    portfolio.to_csv(folder/'equity.csv');benchmark.to_csv(folder/'benchmark.csv')
    trades=pd.DataFrame(fills);trades.to_csv(folder/'fills.csv',index=False)
    pd.DataFrame(daily_audit).to_csv(folder/'execution_audit.csv',index=False)
    buys=trades.loc[trades.side=='BUY'] if len(trades) else trades
    sells=trades.loc[trades.side=='SELL'] if len(trades) else trades
    stats=performance(portfolio.total_value,p.capital)
    stats.update({'experiment':name,'buy_fills':len(buys),'sell_fills':len(sells),
        'fees_and_impact':float(trades.cost.sum()) if len(trades) else 0.,
        'average_exposure':float(pd.DataFrame(daily_audit).exposure.mean()),
        'impact_per_side':impact,'skipped':dict(skips),'end_positions':end_positions,
        'overdue_position_days':sum(row['overdue_positions'] for row in daily_audit)})
    daily=portfolio.total_value.div(portfolio.total_value.shift(1).fillna(p.capital))-1
    bm=benchmark.unit_net_value.div(benchmark.unit_net_value.shift(1).fillna(1))-1
    stats['confidence']=block_confidence(daily,bm)
    if len(buys):
        used=buys[['signal_date','leader']].drop_duplicates().rename(columns={'signal_date':'date','leader':'symbol'})
        used['date']=pd.to_datetime(used.date)
        assessed=used.merge(predictions[['date','symbol','target_touch','target_sealed']],on=['date','symbol']).dropna(subset=['target_touch'])
        stats['executed_leader_days']=len(assessed)
        stats['executed_leader_touch_precision']=float(assessed.target_touch.mean())
        stats['executed_leader_sealed_precision']=float(assessed.target_sealed.mean())
    (folder/'metrics.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
    return stats,portfolio,benchmark


def run_experiments(bundle,output,p,predictions,meta):
    results={};curves={};benchmark=None
    for name,filtered,impact in [('leader_peer',True,p.impact),('momentum_peer_control',False,p.impact),('double_impact',True,p.impact*2)]:
        print('Backtesting '+name,flush=True)
        stats,portfolio,benchmark=run_one(bundle,output,p,predictions,meta,name,filtered,impact)
        results[name]=stats;curves[name]=portfolio.total_value/p.capital
        print(json.dumps(stats,ensure_ascii=False),flush=True)
    results['hs300']=performance(benchmark.unit_net_value)
    (output/'backtest_metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    # Machine-readable provenance, including source and installed data snapshot.
    provenance={'parameters':asdict(p),'universe':len(meta),'industries':len({r['industry_code'] for r in meta.values()}),
        'industry_classification':'bundle snapshot, NOT historical point-in-time',
        'bundle':str(bundle),'files':{name:{'bytes':(bundle/name).stat().st_size,'mtime_ns':(bundle/name).stat().st_mtime_ns}
            for name in ['stocks.h5','instruments.pk','st_stock_days.h5','trading_dates.npy']},
        'source_sha256':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(__file__).parent.glob('*.py')}}
    (output/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2))
    from reporting import write_report
    write_report(output,p,results,curves,benchmark,provenance)
