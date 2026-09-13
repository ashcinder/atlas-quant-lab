import runpy
from pathlib import Path

import pytest
from app.zkp_models import ZkMetricSet

SDK = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/prove-private-program.py'))


def test_local_prover_does_not_inherit_remote_credentials_or_dev_mode(monkeypatch):
    for name in ['BONSAI_API_KEY', 'BONSAI_API_URL', 'RISC0_DEV_MODE', 'RISC0_PROVER']:
        monkeypatch.setenv(name, 'untrusted-setting')
    env = SDK['prover_environment']()
    assert env['RISC0_PROVER'] == 'local'
    assert env['RISC0_DEV_MODE'] == '0'
    assert not any(key.startswith('BONSAI') for key in env)
    assert set(env) == {'PATH', 'RISC0_PROVER', 'RISC0_DEV_MODE', 'RAYON_NUM_THREADS'}


def test_author_material_is_private_and_never_overwritten(tmp_path):
    path = tmp_path / 'private.json'
    SDK['write_private'](path, {'private': 'material'})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        SDK['write_private'](path, {'private': 'replacement'})
    assert 'material' in path.read_text()


def test_short_period_sharpe_matches_guest_i64_contract():
    metrics = dict(total_return_ppm=-4724, annualized_return_ppm=-46246,
                   annualized_volatility_ppm=3663, benchmark_return_ppm=-197,
                   max_drawdown_ppm=-4723, observation_count=32,
                   sharpe_milli=-471734, win_rate_ppm=0)
    assert ZkMetricSet(**metrics).sharpe_milli == -471734
    for invalid in [-(2**63) - 1, 2**63]:
        with pytest.raises(ValueError):
            ZkMetricSet(**{**metrics, 'sharpe_milli': invalid})
