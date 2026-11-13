"""Compile strategy definitions into closed-bar targets; never execute user Python."""
import hashlib
import math

import pandas as pd

from app.models import StrategyDefinition
from app.strategies import get_strategy, generate_target_exposure
from app.strategies.catalog import validate_params
from app.strategies.custom import generate_custom_target
from app.strategies.schedule import contribution_schedule
from app.python_strategy import compile_program, generate_python_targets


def definition(r):
    if r.strategy_id == 'python_portable':
        return StrategyDefinition(id='python_portable',name=r.portable_plan.name if r.portable_plan else 'Python策略',
            category='代码',description='浏览器隔离Python产生目标仓位，框架执行回测',suitable_for='自定义研究',risk_level='高',parameters=[])
    if r.python_source is not None:
        return StrategyDefinition(id='python_bounded',name='受限Python策略',category='代码',description='整数Python指令',suitable_for='自定义研究',risk_level='高',parameters=[])
    if r.custom_strategy:
        c=r.custom_strategy
        return StrategyDefinition(id=c.id,name=c.name,category='自定义',description=c.description,suitable_for='条件策略',risk_level='高',parameters=[])
    result=get_strategy(r.strategy_id)
    if result.mode!='single': raise ValueError('单标的框架不能执行组合策略，请使用组合回测')
    return result


def validate_strategy(r):
    if r.release_id: raise ValueError('订阅策略需先解析拥有权限的策略版本，不能作为任意本地代码执行')
    if r.execution_pipeline and any(s.enabled for s in r.execution_pipeline.ai_stages):
        raise ValueError('外部框架尚不提供逐步AI审核，请关闭AI审核后回测')
    definition(r)
    if r.strategy_id=='python_portable':
        if not r.portable_plan or not r.portable_python: raise ValueError('通用Python需要浏览器运行生成仓位计划')
        if hashlib.sha256(r.portable_python.encode()).hexdigest()!=r.portable_plan.source_sha256:
            raise ValueError('Python源码与仓位计划哈希不一致')
        if r.custom_strategy or r.python_source: raise ValueError('Python策略不能混用其他信号定义')
    elif r.python_source is not None:
        compile_program(r.python_source)
    elif not r.custom_strategy:
        p=validate_params(r.strategy_id,r.params)
        if r.strategy_id in ('sma_cross','ema_cross','macd') and p.get('fast',0)>=p.get('slow',1):
            raise ValueError('快速周期必须小于慢速周期')


def prepare_plan(r,bars,dataset_id=None):
    validate_strategy(r)
    frame=pd.DataFrame(bars).set_index('time')
    frame.index=pd.to_datetime(frame.index,unit='s',utc=True)
    if r.strategy_id=='python_portable':
        p=r.portable_plan
        if (p.dataset_id!=dataset_id or p.start!=bars[0]['time'] or p.end!=bars[-1]['time'] or len(p.targets)!=len(bars)):
            raise ValueError('Python仓位计划与所选不可变行情或日期区间不一致')
        target=[min(v,r.max_position) for v in p.targets]
        reasons=[f'{p.name} · Python收盘信号']*len(bars)
        due=None
    elif r.python_source is not None:
        target,reasons=generate_python_targets(frame,compile_program(r.python_source),r.max_position)
        due=None
    elif r.custom_strategy:
        target,reasons=generate_custom_target(frame,r.custom_strategy,r.max_position);due=None
    elif r.strategy_id=='scheduled_dca':
        params=validate_params(r.strategy_id,r.params)
        due=contribution_schedule(frame.index,int(params['every']),str(params['unit']),int(params['start_delay']))
        return dict(targets=[0.0]*len(bars),reason='固定金额定投',due=[bool(v) for v in due],amount=float(params['amount']))
    else:
        # Preserve the existing online plain-SMA path's exact addition order.
        p=validate_params(r.strategy_id,r.params)
        if r.strategy_id=='sma_cross' and p['confirm_bars']==1 and p['min_gap']==0 and p['trend_filter']==0:
            return None
        target,reasons=generate_target_exposure(frame,r.strategy_id,r.params,r.max_position);due=None
    targets=[float(v) for v in target]
    if any(not math.isfinite(v) or not 0<=v<=r.max_position for v in targets):raise ValueError('策略产生了无效仓位')
    return dict(targets=targets,reasons=[str(v) for v in reasons],due=due)
