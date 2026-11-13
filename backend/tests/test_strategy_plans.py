import hashlib
import pandas as pd
import pytest

from app.models import BacktestRequest
from app.backtest.native import validate_native, normalize
from app.backtest.strategy_plan import prepare_plan, definition
from app.backtest.unified import ResearchLedger


def bars():
    prices=[100+i for i in range(50)]+[150-i for i in range(50)]
    return [dict(time=1735781400+i*60,open=p,high=p+1,low=p-1,close=p,volume=100000) for i,p in enumerate(prices)]


@pytest.mark.parametrize('strategy,params',[('ema_cross',{'fast':3,'slow':10}),('rsi_reversal',{}),('macd',{}),('scheduled_dca',{}),('sma_cross',{'fast':5,'slow':20,'confirm_bars':2})])
@pytest.mark.parametrize('engine',['vnpy','rqalpha'])
def test_other_strategies_are_accepted_and_prepare_finite_targets(strategy,params,engine):
    r=BacktestRequest(backtest_engine=engine,execution_model='unified',symbol='300750.SZ',asset_class='equity',
        data_source='huggingface',adjustment='raw',interval='1m',start='2025-01-02',end='2025-01-03',strategy_id=strategy,params=params)
    validate_native(r)
    plan=prepare_plan(r,bars(),'a'*64)
    assert len(plan['targets'])==100
    ledger=ResearchLedger(r.model_dump(mode='json'),plan)
    for b in bars():ledger.step(b)
    assert len(ledger.snapshots)==100
    assert definition(r).id==strategy


def test_portable_plan_is_bound_to_dataset_range_and_code_hash():
    source='def target(context):\n    return 0.5\n'
    plan=dict(dataset_id='a'*64,source_sha256=hashlib.sha256(source.encode()).hexdigest(),start=bars()[0]['time'],end=bars()[-1]['time'],targets=[.5]*100,name='自己的Python')
    r=BacktestRequest(strategy_id='python_portable',portable_python=source,portable_plan=plan)
    assert prepare_plan(r,bars(),'a'*64)['targets']==[.5]*100
    with pytest.raises(ValueError,match='行情'):
        prepare_plan(r,bars(),'b'*64)
    with pytest.raises(ValueError,match='哈希'):
        prepare_plan(r.model_copy(update={'portable_python':source+'# altered'}),bars(),'a'*64)


def test_python_parameters_are_not_interpreted_as_sma_settings():
    r=BacktestRequest(params={'fast':'custom-mode','slow':{'window':12}})
    ledger=ResearchLedger(r.model_dump(mode='json'),{'targets':[.5]*100,'reason':'自己的参数'})
    for b in bars():ledger.step(b)
    assert len(ledger.snapshots)==100
    assert ledger.fills
