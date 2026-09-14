"""Bounded integer Python strategy execution, without eval/exec or a ZKP claim.

Only instructions emitted by zk_python.compile_strategy are accepted. Prices
use micros and targets use bps, matching the existing author-side language.
"""

from decimal import Decimal

import pandas as pd

from app.zk_python import LIMIT, UnsupportedStrategy, compile_strategy


def compile_program(source: str) -> list:
    program = compile_strategy(source)
    # Check stack/instruction constraints before storing an immutable release.
    _evaluate(program, [1], [0, 1], 1)
    return program


def _evaluate(program, prices, totals, end):
    if not 0 < len(program) <= 256:
        raise UnsupportedStrategy("指令数量必须在1至256之间")
    stack = []
    for instruction in program:
        if isinstance(instruction, dict):
            if len(instruction) != 1:
                raise UnsupportedStrategy("无效指令")
            operation, value = next(iter(instruction.items()))
            if type(value) is not int:
                raise UnsupportedStrategy("指令参数必须是整数")
            if operation == "const":
                result = value
            elif operation == "close" and 0 <= value <= 500:
                result = prices[end - value - 1] if end > value else 0
            elif operation == "sma" and 1 <= value <= 500:
                result = (totals[end] - totals[end - value]) // value if end >= value else 0
            else:
                raise UnsupportedStrategy("不支持的行情指令")
        elif instruction == "index":
            result = end
        elif instruction == "not" and stack:
            result = int(not stack.pop())
        elif instruction == "select" and len(stack) >= 3:
            no, yes, condition = stack.pop(), stack.pop(), stack.pop()
            result = yes if condition else no
        elif len(stack) >= 2:
            b, a = stack.pop(), stack.pop()
            if instruction == "add":
                result = a + b
            elif instruction == "sub":
                result = a - b
            elif instruction == "mul":
                result = a * b
            elif instruction in {"div", "mod"} and a >= 0 and b > 0:
                result = a // b if instruction == "div" else a % b
            elif instruction == "gt":
                result = int(a > b)
            elif instruction == "lt":
                result = int(a < b)
            elif instruction == "eq":
                result = int(a == b)
            else:
                raise UnsupportedStrategy("不支持的算术指令")
        else:
            raise UnsupportedStrategy("指令栈不完整")
        if abs(result) > LIMIT or len(stack) >= 64:
            raise UnsupportedStrategy("指令超出数值或栈限制")
        stack.append(result)
    if len(stack) != 1 or not 0 <= stack[0] <= 9500:
        raise UnsupportedStrategy("目标仓位必须在0至9500bps之间")
    return stack[0]


def generate_python_targets(frame: pd.DataFrame, program: list, max_position=1.0):
    if not 1 <= len(frame) <= 20_000:
        raise UnsupportedStrategy("受限Python仅支持1至20000根K线")
    prices, totals = [], [0]
    for value in frame["close"]:
        price = Decimal(str(value)) * 1_000_000
        if not price.is_finite() or not 0 < price <= LIMIT:
            raise UnsupportedStrategy("行情价格无效或超过整数边界")
        prices.append(int(price))
        totals.append(totals[-1] + prices[-1])
    weights = [
        min(_evaluate(program, prices, totals, i) / 10_000, max_position)
        for i in range(1, len(prices) + 1)
    ]
    return (
        pd.Series(weights, index=frame.index, dtype=float),
        pd.Series("受限Python · 收盘信号", index=frame.index, dtype=object),
    )
