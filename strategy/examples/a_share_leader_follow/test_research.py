"""Causality checks; run with the engine venv's Python -m unittest discover."""
import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from research import Parameters, FEATURES, stock_features, walk_forward
from rq_backtest import performance, plan_peer_orders


class CausalityTests(unittest.TestCase):
    def test_future_price_changes_only_future_features_and_evaluation_labels(self):
        dates=pd.bdate_range('2021-01-01',periods=260)
        dtype=[('datetime','i8')]+[(name,'f8') for name in ['open','high','low','close','prev_close','limit_up','limit_down','volume','total_turnover']]
        raw=np.zeros(len(dates),dtype=dtype)
        close=10*np.exp(np.arange(len(dates))*.001)
        raw['datetime']=dates.strftime('%Y%m%d').astype('int64')*1_000_000
        for name in ['open','close']:raw[name]=close
        raw['prev_close']=close/1.001;raw['high']=close*1.01;raw['low']=close*.99
        raw['limit_up']=raw['prev_close']*1.1;raw['limit_down']=raw['prev_close']*.9
        raw['volume']=10_000_000;raw['total_turnover']=100_000_000
        changed=raw.copy();cutoff=dates[-3]
        changed['high'][-2:]=changed['limit_up'][-2:];changed['close'][-2:]=changed['limit_up'][-2:]
        changed['volume'][-2:]*=100;changed['total_turnover'][-2:]*=100
        original=stock_features(raw,[],'000001.XSHE','J66',dates,Parameters())
        mutated=stock_features(changed,[],'000001.XSHE','J66',dates,Parameters())
        columns=[key for key in FEATURES if key not in ['industry_momentum','industry_breadth']]+['adv20']
        pd.testing.assert_frame_equal(original.loc[original.date<=cutoff,columns],mutated.loc[mutated.date<=cutoff,columns])
        self.assertNotEqual(float(original.loc[original.date==cutoff,'target_touch'].iloc[0]),
                            float(mutated.loc[mutated.date==cutoff,'target_touch'].iloc[0]))

    def test_labels_crossing_month_boundary_are_not_used_to_train(self):
        rng=np.random.default_rng(5)
        dates=pd.bdate_range('2020-01-01','2023-02-28')
        frame=pd.DataFrame({'date':dates,'label_date':dates+pd.offsets.BDay(),
            'candidate':True,'target_touch':rng.binomial(1,.15,len(dates))})
        for key in FEATURES:frame[key]=rng.normal(size=len(frame))
        p=replace(Parameters(),test_start='2023-02-01',test_end='2023-02-28')
        _,audit,models=walk_forward(frame,p)
        altered=frame.copy()
        forbidden=altered.label_date>=pd.Timestamp('2023-02-01')
        altered.loc[forbidden,'target_touch']=1-altered.loc[forbidden,'target_touch']
        _,_,other=walk_forward(altered,p)
        self.assertEqual(models,other)
        self.assertLess(pd.Timestamp(audit[0]['last_training_label']),pd.Timestamp('2023-02-01'))

    def test_initial_loss_is_included_in_drawdown(self):
        nav=pd.Series([.9,.95,.8],index=pd.bdate_range('2023-01-01',periods=3))
        self.assertAlmostEqual(performance(nav)['max_drawdown'],-.2)

    def test_auction_plan_reserves_old_slots_and_worst_case_limit_cash(self):
        p=Parameters();codes=['000001.XSHE','000002.XSHE','688001.XSHG']
        meta={code:{'industry_code':'C1'} for code in codes}
        signal={'date':pd.Timestamp('2023-01-03'),'symbol':codes[0],'industry':'C1',
                'probability':.3,'followers':[{'symbol':code,'adv20':100_000_000} for code in codes[1:]]}
        references={code:(10.,11.) for code in codes}
        plans,_=plan_peer_orders([signal],{},1_000_000,meta,references,p,p.impact)
        self.assertEqual(len(plans),2)
        self.assertTrue(all(plan['order_limit']==10.3 for plan in plans))
        self.assertTrue(all(plan['quantity']*plan['order_limit']<=plan['budget_at_order'] for plan in plans))
        # Exiting holdings still reserve their pre-auction slots. A hypothetical
        # successful exit / observed open is not an input to this pure planner.
        reserved={f'60000{i}.XSHG':100_000 for i in range(6)}
        meta.update({code:{'industry_code':'C2'} for code in reserved})
        plans,_=plan_peer_orders([signal],reserved,400_000,meta,references,p,p.impact)
        self.assertEqual(plans,[])

if __name__=='__main__':unittest.main()
