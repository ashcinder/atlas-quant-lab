import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.zkp_models import ZkMetricSet

SDK = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/prove-private-program.py'))


def test_local_prover_does_not_inherit_remote_credentials_or_dev_mode(monkeypatch):
    for name in ['BONSAI_API_KEY', 'BONSAI_API_URL', 'RISC0_DEV_MODE', 'RISC0_PROVER',
                 'RISC0_PROVER_SERVER', 'RUSTC_WRAPPER', 'LD_PRELOAD',
                 'DYLD_INSERT_LIBRARIES', 'AWS_SECRET_ACCESS_KEY']:
        monkeypatch.setenv(name, 'untrusted-setting')
    monkeypatch.setenv('ATLAS_PROOF_THREADS', '3')
    env = SDK['prover_environment']()
    assert env['RISC0_PROVER'] == 'local'
    assert env['RISC0_DEV_MODE'] == '0'
    assert env['RAYON_NUM_THREADS'] == '3'
    assert not any(key.startswith('BONSAI') for key in env)
    assert set(env) == {'PATH', 'RISC0_PROVER', 'RISC0_DEV_MODE', 'RAYON_NUM_THREADS'}


def test_unconfigured_proof_settings_preserve_the_old_command(monkeypatch, tmp_path):
    for name in ['ATLAS_PROOF_THREADS', 'ATLAS_PROOF_SEGMENT_PO2',
                 'ATLAS_PROOF_DISK_SEGMENTS']:
        monkeypatch.delenv(name, raising=False)
    assert SDK['prover_environment']()['RAYON_NUM_THREADS'] == '1'
    assert SDK['prove_arguments'](tmp_path / 'witness.json', tmp_path / 'proof.r0') == [
        'prove', '--profile', SDK['PROFILE'], '--witness', str(tmp_path / 'witness.json'),
        '--receipt', str(tmp_path / 'proof.r0')]


def test_explicit_segment_setting_is_only_added_to_prove(monkeypatch, tmp_path):
    monkeypatch.setenv('ATLAS_PROOF_SEGMENT_PO2', '18')
    commands = []

    def completed(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'ok': True}))

    monkeypatch.setattr(SDK['subprocess'], 'run', completed)
    SDK['invoke'](['verify', '--receipt', 'old.r0', '--expected-image-id', 'ab' * 32])
    SDK['invoke'](['inspect', '--profile', SDK['PROFILE'], '--witness', 'witness.json'])
    SDK['invoke'](['profile', '--profile', SDK['PROFILE']])
    SDK['invoke_prove'](tmp_path / 'witness.json', tmp_path / 'proof.r0', tmp_path)
    assert all('--segment-limit-po2' not in command for command, _ in commands[:3])
    assert commands[3][0][-2:] == ['--segment-limit-po2', '18']
    assert all(set(kwargs['env']) == {'PATH', 'RISC0_PROVER', 'RISC0_DEV_MODE',
                                      'RAYON_NUM_THREADS'} for _, kwargs in commands)


def test_prover_failure_does_not_echo_private_diagnostics(monkeypatch):
    private_value = 'private-witness-and-credential'
    monkeypatch.setattr(
        SDK['subprocess'], 'run',
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout='', stderr=private_value))
    with pytest.raises(RuntimeError) as error:
        SDK['invoke'](['prove'])
    assert private_value not in str(error.value)


@pytest.mark.parametrize(('name', 'value'), [
    ('ATLAS_PROOF_THREADS', '0'), ('ATLAS_PROOF_THREADS', '4'),
    ('ATLAS_PROOF_THREADS', 'credential-value'),
    ('ATLAS_PROOF_SEGMENT_PO2', '15'), ('ATLAS_PROOF_SEGMENT_PO2', '21'),
    ('ATLAS_PROOF_SEGMENT_PO2', 'credential-value'),
    ('ATLAS_PROOF_DISK_SEGMENTS', 'credential-value'),
])
def test_invalid_proof_settings_are_rejected_without_echoing_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    function = (SDK['prover_environment'] if name == 'ATLAS_PROOF_THREADS'
                else SDK['proof_segment_limit_po2'] if name == 'ATLAS_PROOF_SEGMENT_PO2'
                else SDK['proof_disk_segments_enabled'])
    with pytest.raises(ValueError) as error:
        function()
    assert value not in str(error.value)


@pytest.mark.parametrize('fail', [False, True])
def test_disk_segment_directory_is_private_and_always_cleaned(monkeypatch, tmp_path, fail):
    monkeypatch.setenv('ATLAS_PROOF_DISK_SEGMENTS', '1')
    observed = {}

    def fake_invoke(arguments, timeout=3600, pass_fds=()):
        segment_path = Path(arguments[arguments.index('--segment-path') + 1])
        observed['path'] = segment_path
        assert segment_path.parent == tmp_path
        assert segment_path.is_dir()
        assert segment_path.stat().st_mode & 0o777 == 0o700
        if fail:
            raise RuntimeError('controlled prover failure')
        return {'stats': {'segments': 2}}

    monkeypatch.setitem(SDK['invoke_prove'].__globals__, 'invoke', fake_invoke)
    if fail:
        with pytest.raises(RuntimeError, match='controlled prover failure'):
            SDK['invoke_prove'](tmp_path / 'witness.json', tmp_path / 'proof.r0', tmp_path)
    else:
        assert SDK['invoke_prove'](tmp_path / 'witness.json', tmp_path / 'proof.r0', tmp_path) == {
            'stats': {'segments': 2}}
    assert not observed['path'].exists()
    assert list(tmp_path.glob('.proof-segments-*')) == []


def test_public_prover_performance_excludes_journal_and_private_values():
    public = SDK['public_prover_performance']({
        'stats': {'segments': 3}, 'segment_limit_po2': 18, 'elapsed_seconds': 1.25,
        'timings': {'proving_seconds': 1.0}, 'journal': {'private': 'no'},
        'witness': {'strategy': 'no'}, 'unexpected': 'no'})
    assert public == {'stats': {'segments': 3}, 'segment_limit_po2': 18,
                      'elapsed_seconds': 1.25}


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


def test_incomplete_json_is_never_published_as_an_atomic_file(tmp_path):
    path=tmp_path/'verification.public.json'
    with pytest.raises(ValueError):SDK['write_private'](path, {'metric':float('nan')})
    assert not path.exists()
    assert list(tmp_path.iterdir())==[]
