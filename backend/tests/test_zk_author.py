import pytest
from app.zk_author import prepare_witness
from app.zkp import market_commitment, ZkProofError
from app.zk_python import UnsupportedStrategy

def dataset():
    return {'source': 'test-fixture', 'symbol': 'TEST', 'interval': '1d', 'adjustment': 'raw', 'bars': [{'time': 1700000000+i*86400, 'open_micros': 100, 'close_micros': 101, 'high_micros': 102, 'low_micros': 99, 'volume_micros': 1000} for i in range(3)]}

def test_author_compiles_locally_and_randomizes_openings():
    market = dataset()
    args = ({'dataset': market, 'market_data_hash': market_commitment(market)}, 'def target_bps(index, close, sma):\n    return (index % 2) * 1000', 'qja_test', 100000000, 10, 5)
    first, second = prepare_witness(*args), prepare_witness(*args)
    assert first['strategy']['program'] == ['index', {'const': 2}, 'mod', {'const': 1000}, 'mul']
    assert first['strategy_salt'] != second['strategy_salt']
    assert first['nullifier_nonce'] != second['nullifier_nonce']
    assert 'source' not in first

def test_author_rejects_bad_hash_and_unsupported_python():
    with pytest.raises(ZkProofError):
        prepare_witness({'dataset': dataset(), 'market_data_hash': '00'*32}, '', 'qja_test', 100, 10, 5)
    with pytest.raises(UnsupportedStrategy):
        prepare_witness(dataset(), 'import os', 'qja_test', 100, 10, 5)
