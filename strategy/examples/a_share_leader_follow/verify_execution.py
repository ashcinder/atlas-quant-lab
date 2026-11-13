"""Independently verify exported real-bundle fills, lagging and charged costs."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import h5py
import numpy as np
import pandas as pd
from research import ROOT, metadata


def verify(bundle,output):
    meta=metadata(bundle)
    calendar=np.load(bundle/'trading_dates.npy').astype('int64')
    forecasts=pd.read_csv(output/'forecasts.csv.gz')
    signals={(row['date'],row['symbol']):row for row in forecasts.to_dict('records')}
    totals={}
    for name in ['leader_peer','momentum_peer_control','double_impact']:
        fills=pd.read_csv(output/name/'fills.csv');entries={};checks=0
        with h5py.File(bundle/'stocks.h5') as stocks:
            raw={code:stocks[code][:] for code in fills.symbol.unique()}
            for row in fills.to_dict('records'):
                if row['reason']=='engine_corporate_action':continue
                code=row['symbol'];number=int(row['date'].replace('-',''))
                array=raw[code];dates=array['datetime']//1_000_000
                index=np.searchsorted(dates,number);bar=array[index]
                assert dates[index]==number
                assert abs(row['price']-bar['open'])<1e-6,(name,code,row['date'],'not native open')
                assert row['execution_phase']=='OPEN_AUCTION'
                assert abs(row['cost']-row['commission']-row['tax']-row['impact_and_transfer'])<1e-7
                notional=row['quantity']*row['price']
                assert abs(row['commission']-max(5,notional*.0003))<1e-6
                impact=.002 if name=='double_impact' else .001
                assert abs(row['impact_and_transfer']-notional*(impact+.00001))<1e-6
                expected_tax=0 if row['side']=='BUY' else notional*(.001 if number<20230828 else .0005)
                assert abs(row['tax']-expected_tax)<1e-6
                if row['side']=='BUY':
                    signal_row=signals[(row['signal_date'],row['leader'])]
                    if name!='momentum_peer_control':assert signal_row['selected']
                    followers=json.loads(signal_row['followers'])
                    assert any(peer['symbol']==code and abs(peer['adv20']-row['lagged_adv20'])<1e-4 for peer in followers)
                    assert abs(row['probability']-signal_row['probability'])<1e-10
                    signal=int(row['signal_date'].replace('-',''))
                    assert calendar[np.searchsorted(calendar,signal)+1]==number,'Not T+1 entry'
                    assert code!=row['leader']
                    assert meta[code]['industry_code']==meta[row['leader']]['industry_code']
                    assert row['price']<bar['limit_up']-.005
                    assert row['price']/bar['prev_close']-1<=.03+1e-8
                    assert row['quantity']*row['price']<=row['lagged_adv20']*.005+1e-6
                    assert row['quantity']*row['price']<=row['budget_at_order']+1e-6
                    assert row['price']<=row['order_limit']+1e-8
                    assert row['quantity']*row['order_limit']<=row['budget_at_order']+1e-6
                    if code.startswith('688'):assert row['quantity']>=200
                    else:assert row['quantity']%100==0
                    assert code not in entries,'Unintended pyramid buy'
                    entries[code]=number
                else:
                    assert code in entries and entries.pop(code)<number,'T+1 violation'
                    assert row['price']>bar['limit_down']+.005
                    assert row['price']>=row['order_limit']-1e-8
                checks+=1
        audit=pd.read_csv(output/name/'execution_audit.csv')
        assert audit.positions.max()<=6
        totals[name]={'verified_auction_fills':checks,'max_positions':int(audit.positions.max()),
            'open_positions_at_end':len(entries)}
    walk=json.loads((output/'walk_forward.json').read_text())
    for month in walk:
        if 'skipped' not in month:
            assert pd.Timestamp(month['last_training_label'])<pd.Timestamp(month['month']+'-01')
    totals['verified_monthly_train_cutoffs']=len(walk)
    (output/'verification.json').write_text(json.dumps(totals,indent=2))
    print(json.dumps(totals,indent=2))

if __name__=='__main__':
    verify(ROOT/'backend/.data/rqalpha/bundle',Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'.artifacts/a-share-leader-follow')
