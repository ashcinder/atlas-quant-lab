import pytest

from app.zk_python import UnsupportedStrategy, compile_strategy


def compile_return(expression):
    return compile_strategy('def target_bps(index, close, sma):\n    return ' + expression)


def test_python_alternating_program_matches_existing_guest_instructions():
    assert compile_return('(index % 2) * 1000') == ['index', {'const': 2}, 'mod', {'const': 1000}, 'mul']


def test_conditionals_and_local_values_compile_without_execution():
    result = compile_strategy('def target_bps(index, close, sma):\n    signal = sma(3) > sma(8)\n    return 1000 if signal else 0')
    assert result == [{'sma': 3}, {'sma': 8}, 'gt', {'const': 1000}, {'const': 0}, 'select']


@pytest.mark.parametrize('expression', [
    '__import__("os").system("false")', 'open("private.key").read()',
    'index / 2', '10000', '-1', '(0 - index) // 2', '(0 - index) % 2',
    '1000 if index else (1 // 0)', 'index and 1000', 'close(0) + 1000',
    'sma(501)', 'True', '[1][0]', 'close(index)', '1 << 5',
])
def test_unsupported_or_semantically_unsafe_code_is_rejected(expression):
    with pytest.raises(UnsupportedStrategy):
        compile_return(expression)


@pytest.mark.parametrize('source', [
    'import os\ndef target_bps(index, close, sma):\n    return 0',
    '@decorator\ndef target_bps(index, close, sma):\n    return 0',
    'def target_bps(index, close, sma):\n    while True: pass\n    return 0',
    'def target_bps(index, close, sma):\n    index = 1\n    return 0',
    'def target_bps(index=1, close=2, sma=3):\n    return 0',
])
def test_only_fixed_function_contract_is_accepted(source):
    with pytest.raises(UnsupportedStrategy):
        compile_strategy(source)
