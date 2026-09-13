"""Strict author-side Python subset -> existing private v2 integer program.

Never exec/eval author code. The receipt proves the compiled program, not this
compiler, CPython, an LLM or the provenance of an external input.
"""
import ast
from dataclasses import dataclass

LIMIT = 10**18


class UnsupportedStrategy(ValueError):
    pass


@dataclass
class Expression:
    code: list
    low: int
    high: int


def compile_strategy(source: str) -> list:
    if len(source.encode()) > 16_384:
        raise UnsupportedStrategy('策略超过16KiB')
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError) as exc:
        raise UnsupportedStrategy('无法解析策略') from exc
    if sum(1 for _ in ast.walk(tree)) > 512:
        raise UnsupportedStrategy('策略AST超过512节点')
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise UnsupportedStrategy('仅支持单个 target_bps(index, close, sma) 函数')
    fn = tree.body[0]
    args = fn.args
    if (fn.name != 'target_bps' or fn.decorator_list or fn.returns or
            args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or
            args.defaults or [a.arg for a in args.args] != ['index', 'close', 'sma'] or
            any(a.annotation for a in args.args)):
        raise UnsupportedStrategy('函数签名必须是 target_bps(index, close, sma)')
    names = {'index': Expression(['index'], 1, 20_000)}

    def bounded(code, low, high):
        if low < -LIMIT or high > LIMIT or len(code) > 256:
            raise UnsupportedStrategy('无法保证指令或数值处于固定guest边界')
        return Expression(code, low, high)

    def expr(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return bounded([{'const': node.value}], node.value, node.value)
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if (name in {'close', 'sma'} and not node.keywords and len(node.args) == 1
                    and isinstance(node.args[0], ast.Constant) and type(node.args[0].value) is int):
                value = node.args[0].value
                if (0 if name == 'close' else 1) <= value <= 500:
                    return Expression([{name: value}], 0, LIMIT)
        if isinstance(node, ast.BinOp):
            a, b = expr(node.left), expr(node.right)
            code = a.code + b.code
            if isinstance(node.op, ast.Add):
                return bounded(code + ['add'], a.low + b.low, a.high + b.high)
            if isinstance(node.op, ast.Sub):
                return bounded(code + ['sub'], a.low - b.high, a.high - b.low)
            if isinstance(node.op, ast.Mult):
                values = [x*y for x in (a.low, a.high) for y in (b.low, b.high)]
                return bounded(code + ['mul'], min(values), max(values))
            if isinstance(node.op, (ast.FloorDiv, ast.Mod)):
                # Python floor/mod differ from Rust for negative values.
                if a.low < 0 or b.low <= 0 or b.low != b.high:
                    raise UnsupportedStrategy('//和%要求非负被除数与正整数字面常量除数')
                if isinstance(node.op, ast.FloorDiv):
                    return bounded(code + ['div'], a.low // b.low, a.high // b.low)
                return bounded(code + ['mod'], 0, b.high - 1)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = expr(node.left), expr(node.comparators[0])
            operation = {ast.Gt: ['gt'], ast.Lt: ['lt'], ast.Eq: ['eq'],
                         ast.NotEq: ['eq', 'not'], ast.GtE: ['lt', 'not'],
                         ast.LtE: ['gt', 'not']}.get(type(node.ops[0]))
            if operation:
                return bounded(a.code + b.code + operation, 0, 1)
        if isinstance(node, ast.IfExp):
            condition, yes, no = expr(node.test), expr(node.body), expr(node.orelse)
            # Every allowed expression is total: eagerly evaluating either
            # branch cannot introduce Python side effects or division by zero.
            return bounded(condition.code + yes.code + no.code + ['select'],
                           min(yes.low, no.low), max(yes.high, no.high))
        raise UnsupportedStrategy(f'不支持的Python语法：{type(node).__name__}')

    if not fn.body or not isinstance(fn.body[-1], ast.Return):
        raise UnsupportedStrategy('函数最后必须返回目标仓位bps')
    for statement in fn.body[:-1]:
        if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)):
            raise UnsupportedStrategy('仅支持局部变量赋值和最终return')
        name = statement.targets[0].id
        if name in {'index', 'close', 'sma'}:
            raise UnsupportedStrategy('不能覆盖输入参数')
        names[name] = expr(statement.value)
    result = expr(fn.body[-1].value)
    if result.low < 0 or result.high > 9500:
        raise UnsupportedStrategy('无法保证目标仓位在0至9500bps内')
    return result.code
