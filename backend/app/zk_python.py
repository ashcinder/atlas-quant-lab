"""Strict author-side Python subset -> existing private v2 integer program.

Never exec/eval author code. The receipt proves the compiled program, not this
compiler, CPython, an LLM or the provenance of an external input.
"""
import ast
from dataclasses import dataclass

LIMIT = 10**18


class UnsupportedStrategy(ValueError):
    def __init__(self, message, node=None, *, kind='unsupported'):
        self.kind = kind
        self.line = getattr(node, 'lineno', None)
        column = getattr(node, 'col_offset', None)
        self.offset = column + 1 if column is not None else None
        super().__init__(message)

    def diagnostic(self, source=None):
        offset = self.offset
        if source is not None and self.line is not None and offset is not None:
            prefix = source.splitlines()[self.line - 1].encode('utf-8')[:offset - 1].decode('utf-8')
            offset = len(prefix.encode('utf-16-le')) // 2 + 1
        return {'message': str(self), 'line': self.line, 'offset': offset, 'kind': self.kind}


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
        raise UnsupportedStrategy('无法解析策略', kind='syntax') from exc
    if sum(1 for _ in ast.walk(tree)) > 512:
        raise UnsupportedStrategy('策略AST超过512节点')
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise UnsupportedStrategy('仅支持单个 target_bps(index, close, sma) 函数', tree.body[0] if tree.body else None)
    fn = tree.body[0]
    args = fn.args
    if (fn.name != 'target_bps' or fn.decorator_list or fn.returns or
            args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or
            args.defaults or [a.arg for a in args.args] != ['index', 'close', 'sma'] or
            any(a.annotation for a in args.args)):
        raise UnsupportedStrategy('函数签名必须是 target_bps(index, close, sma)', fn)
    names = {'index': Expression(['index'], 1, 20_000)}

    def bounded(code, low, high, node):
        if len(code) > 256:
            raise UnsupportedStrategy(f'表达式展开为{len(code)}条指令，超过256条限制；请减少重复条件或规则。', node, kind='instructions')
        if low < -LIMIT or high > LIMIT:
            expression = (ast.get_source_segment(source, node) or '表达式')[:100]
            raise UnsupportedStrategy(f'表达式「{expression}」的推导范围[{low}, {high}]超出允许范围[-{LIMIT}, {LIMIT}]；请避免放大价格或均线，改用直接比较。', node, kind='numeric_bounds')
        return Expression(code, low, high)

    def expr(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return bounded([{'const': node.value}], node.value, node.value, node)
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
                return bounded(code + ['add'], a.low + b.low, a.high + b.high, node)
            if isinstance(node.op, ast.Sub):
                return bounded(code + ['sub'], a.low - b.high, a.high - b.low, node)
            if isinstance(node.op, ast.Mult):
                values = [x*y for x in (a.low, a.high) for y in (b.low, b.high)]
                return bounded(code + ['mul'], min(values), max(values), node)
            if isinstance(node.op, (ast.FloorDiv, ast.Mod)):
                # Python floor/mod differ from Rust for negative values.
                if a.low < 0 or b.low <= 0 or b.low != b.high:
                    raise UnsupportedStrategy('//和%要求非负被除数与正整数字面常量除数', node, kind='division')
                if isinstance(node.op, ast.FloorDiv):
                    return bounded(code + ['div'], a.low // b.low, a.high // b.low, node)
                return bounded(code + ['mod'], 0, b.high - 1, node)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = expr(node.left), expr(node.comparators[0])
            operation = {ast.Gt: ['gt'], ast.Lt: ['lt'], ast.Eq: ['eq'],
                         ast.NotEq: ['eq', 'not'], ast.GtE: ['lt', 'not'],
                         ast.LtE: ['gt', 'not']}.get(type(node.ops[0]))
            if operation:
                return bounded(a.code + b.code + operation, 0, 1, node)
        if isinstance(node, ast.IfExp):
            condition, yes, no = expr(node.test), expr(node.body), expr(node.orelse)
            # Every allowed expression is total: eagerly evaluating either
            # branch cannot introduce Python side effects or division by zero.
            return bounded(condition.code + yes.code + no.code + ['select'],
                           min(yes.low, no.low), max(yes.high, no.high), node)
        raise UnsupportedStrategy(f'不支持的Python语法：{type(node).__name__}', node, kind='syntax_subset')

    if not fn.body or not isinstance(fn.body[-1], ast.Return):
        raise UnsupportedStrategy('函数最后必须返回目标仓位bps', fn)
    for statement in fn.body[:-1]:
        if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)):
            raise UnsupportedStrategy('仅支持局部变量赋值和最终return；请将if语句写成条件表达式。', statement, kind='syntax_subset')
        name = statement.targets[0].id
        if name in {'index', 'close', 'sma'}:
            raise UnsupportedStrategy('不能覆盖输入参数', statement)
        names[name] = expr(statement.value)
    result = expr(fn.body[-1].value)
    if result.low < 0 or result.high > 9500:
        raise UnsupportedStrategy(f'目标仓位推导范围[{result.low}, {result.high}]超出0至9500bps限制', fn.body[-1], kind='target_bounds')
    return result.code
