"""Author-side witness preparation; this module is not exposed as an HTTP API."""
import hashlib
import secrets
from app.zk_python import compile_strategy
from app.zkp import market_commitment, ZkProofError

PROFILE = 'atlas_program_backtest_risc0_v2'
WORKFLOW = hashlib.sha256(b'ATLASWORKFLOW2:closed_market>private_program>long_only_cap_9500bps>affordable_next_open>audit>output').hexdigest()

def prepare_witness(dataset, source, agent_id, capital_micros, commission_bps, slippage_bps):
    import re
    if not re.fullmatch(r'qja_[a-zA-Z0-9_]{2,64}', agent_id):
        raise ZkProofError('策略身份格式无效')
    if type(capital_micros) is not int or not 0 < capital_micros <= 10**15:
        raise ZkProofError('初始资金必须是有效的整数 micros')
    if any(type(v) is not int or not 0 <= v <= 1000 for v in (commission_bps, slippage_bps)):
        raise ZkProofError('费用必须是 0–1000 的整数 bps')
    market = dataset.get('dataset', dataset)
    expected = dataset.get('market_data_hash')
    if expected and expected != market_commitment(market):
        raise ZkProofError('下载数据与声明哈希不一致')
    bars = market.get('bars', [])
    if not 3 <= len(bars) <= 20000:
        raise ZkProofError('数据需要 3–20000 根 K 线')
    prior = 0
    for bar in bars:
        keys = ['time', 'open_micros', 'high_micros', 'low_micros', 'close_micros', 'volume_micros']
        if any(type(bar.get(key)) is not int for key in keys):
            raise ZkProofError('数据必须使用整数定点格式')
        if (bar['time'] <= prior or min(bar[k] for k in keys[1:5]) <= 0 or bar['volume_micros'] < 0
                or bar['low_micros'] > min(bar['open_micros'], bar['close_micros'])
                or bar['high_micros'] < max(bar['open_micros'], bar['close_micros'])):
            raise ZkProofError('K线价格或时间序列无效')
        prior = bar['time']
    return {'agent_id': agent_id, 'workflow_commitment': WORKFLOW,
            'previous_receipt_hash': None, 'strategy_salt': list(secrets.token_bytes(32)),
            'nullifier_nonce': list(secrets.token_bytes(32)), 'initial_equity_micros': capital_micros,
            'strategy': {'program': compile_strategy(source), 'commission_bps': commission_bps, 'slippage_bps': slippage_bps},
            'market': market}
