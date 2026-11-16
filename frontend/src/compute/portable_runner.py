"""This file runs ONLY inside the browser's isolated WebAssembly Python worker."""
import json
import math
from array import array
from collections.abc import Sequence


class CandleHistory(Sequence):
    fields = ('time', 'open', 'high', 'low', 'close', 'volume')

    def __init__(self, values, closes=False):
        self.__values = values
        self.__closes = closes
        self._length = 0

    def __len__(self):
        return self._length

    def __getitem__(self, item):
        if isinstance(item, slice):
            return [self[i] for i in range(*item.indices(self._length))]
        if item < 0:
            item += self._length
        if not 0 <= item < self._length:
            raise IndexError(item)
        offset = item * 6
        if self.__closes:
            return self.__values[offset + 4]
        return {**dict(zip(self.fields, self.__values[offset:offset + 6])), 'time': int(self.__values[offset])}


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
    return run_namespace(namespace, bars_json, parameters_json)


def run_packed_strategy(source, packed, parameters_json):
    namespace = {'__name__': 'strategy'}
    exec(compile(source, 'strategy.py', 'exec'), namespace)
    return run_packed_namespace(namespace, packed, parameters_json)


def run_packed_namespace(namespace, packed, parameters_json):
    values = packed.to_py().cast('d')
    context = StrategyContext(json.loads(parameters_json))
    context.history = CandleHistory(values)
    context.close = CandleHistory(values, closes=True)
    targets = array('d', evaluate(namespace, context, range(len(values) // 6), packed=True))
    return targets.tobytes()


def run_namespace(namespace, bars_json, parameters_json='{}'):
    context = StrategyContext(json.loads(parameters_json))
    return json.dumps(list(evaluate(namespace, context, json.loads(bars_json))), allow_nan=False)


def evaluate(namespace, context, bars, packed=False):
    target = namespace.get('target')
    if not callable(target):
        raise ValueError('请定义 target(context)，返回0至1的目标仓位')
    initialize = namespace.get('initialize')
    if callable(initialize):
        initialize(context)
    for index, bar in enumerate(bars):
        context.index = index
        if packed:
            context.history._length = context.close._length = index + 1
            context.bar = context.history[index]
        else:
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
        yield result
