"""Run INSIDE the Linux image. It exercises the real seccomp/UID worker, not NSM."""
from enclave import decide
book = {'symbol': 'BTCUSDT', 'bidPrice': '100', 'askPrice': '101', 'bidQty': '1', 'askQty': '1'}
assert decide('def decide(ctx): return "0.1" if ctx["step"] % 2 == 0 else "0"', 0, book) == '0.1'
assert decide('def decide(ctx): return "0.1" if ctx["step"] % 2 == 0 else "0"', 1, book) == '0'
for source in [
    'import socket\nsocket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)\ndef decide(ctx): return "0"',
    'import os\nos.fork()\ndef decide(ctx): return "0"',
    'print("SOURCE_MUST_NOT_ESCAPE")\ndef decide(ctx): return "0"',
    'def decide(ctx): raise Exception("SECRET")',
    'def decide(ctx): return "nan"',
    'def decide(ctx): return "2"',
    'print("x" * 10000)\ndef decide(ctx): return "0"',
]:
    try:
        decide(source, 0, book)
    except (ValueError, TimeoutError):
        pass
    else:
        raise AssertionError('Unsafe worker accepted')
print('PASS: actual Linux worker targets, network/fork denial and bounded output. TEE NOT tested.')
