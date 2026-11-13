"""This file runs ONLY inside the browser's isolated WebAssembly Python worker."""
import json
import math


class StrategyContext:
    def __init__(self, parameters):
        self.params = parameters
        self.state = {}
        self.history = []
        self.close = []
        self.index = -1
        self.bar = None
        self.last_target = 0.0

    def sma(self, period):
        if not isinstance(period, int) or period <= 0:
            raise ValueError('均线周期必须是正整数')
        if len(self.close) < period:
            return None
        return sum(self.close[-period:]) / period


def run_strategy(source, bars_json, parameters_json='{}'):
    namespace = {'__name__': 'strategy'}
    exec(compile(source, 'strategy.py', 'exec'), namespace)
    target = namespace.get('target')
    if not callable(target):
        raise ValueError('请定义 target(context)，返回0至1的目标仓位')
    context = StrategyContext(json.loads(parameters_json))
    initialize = namespace.get('initialize')
    if callable(initialize):
        initialize(context)
    targets = []
    for index, bar in enumerate(json.loads(bars_json)):
        context.index = index
        context.bar = bar
        context.history.append(bar)
        context.close.append(bar['close'])
        try:
            result = target(context)
            if result is None:
                result = context.last_target
            if isinstance(result, dict):
                result = result['target']
            result = float(result)
            if not math.isfinite(result) or not 0 <= result <= 1:
                raise ValueError('目标仓位必须是0至1之间的有限数值')
        except Exception as error:
            raise ValueError(f'第{index+1}根K线：{error}') from error
        context.last_target = result
        targets.append(result)
    return json.dumps(targets, allow_nan=False)
