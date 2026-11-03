import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/release'))
spec = importlib.util.spec_from_file_location('chain_snapshot_test', ROOT / 'deploy/release/chain-snapshot.py')
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def resources(monkeypatch, tmp_path, missing=False, wrong=False):
    secret = tmp_path / 'secrets'
    secret.mkdir(mode=0o700)
    values = {'COMPOSE_PROJECT_NAME': 'audit-test', 'ATLAS_CHAIN_SECRETS_DIR': str(secret)}
    import preflight
    monkeypatch.setattr(preflight, 'validate_chain', lambda _: None)
    calls = []
    def output(args, **kwargs):
        calls.append(args)
        if args[:3] == ['docker', 'volume', 'inspect']:
            if missing:raise subprocess.CalledProcessError(1, args)
            volume = args[-1].removeprefix('audit-test_')
            return json.dumps([{'Labels': {'com.docker.compose.project': 'other' if wrong else 'audit-test', 'com.docker.compose.volume': volume}}])
        if 'ps' in args:return args[-1]
        service = args[-1]
        volume, destination = next((v, d) for v, (s, d) in snapshot.VOLUMES.items() if s == service)
        return json.dumps([{'Image': 'sha256:test', 'Config': {'Labels': {'com.docker.compose.project': 'audit-test', 'com.docker.compose.service': service}}, 'State': {'Running': True}, 'Mounts': [{'Type': 'volume', 'Name': 'audit-test_' + volume, 'Destination': destination}, {'Source': str(secret / 'mysql-password'), 'Destination': '/run/secrets/supervisor-db-password'}, {'Source': str(secret / 'mysql-root-password'), 'Destination': '/run/secrets/supervisor-db-root-password'}]}])
    monkeypatch.setattr(snapshot.subprocess, 'check_output', output)
    return values, calls


@pytest.mark.parametrize('missing,wrong', [(True, False), (False, True)])
def test_missing_or_foreign_volumes_fail_before_any_service_or_volume_mutation(monkeypatch, tmp_path, missing, wrong):
    values, calls = resources(monkeypatch, tmp_path, missing, wrong)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        snapshot.checked_resources(values, ['compose'])
    assert not any('stop' in c or 'run' in c or 'create' in c for c in calls)


def test_valid_resources_are_bound_to_the_expected_project_mounts(monkeypatch, tmp_path):
    values, calls = resources(monkeypatch, tmp_path)
    assert set(snapshot.checked_resources(values, ['compose'])) == {'api', 'supervisor', 'supervisor-db'}
    assert sum(c[:3] == ['docker', 'volume', 'inspect'] for c in calls) == 3


def test_database_secret_sources_must_match_the_selected_directory(monkeypatch, tmp_path):
    values, calls = resources(monkeypatch, tmp_path)
    original = snapshot.subprocess.check_output
    def output(args, **kwargs):
        result = original(args, **kwargs)
        if args[:2] == ['docker', 'inspect'] and args[-1] == 'supervisor-db':
            data=json.loads(result)
            data[0]['Mounts'][-1]['Source']='/different/mysql-root-password'
            return json.dumps(data)
        return result
    monkeypatch.setattr(snapshot.subprocess,'check_output',output)
    with pytest.raises(ValueError,match='MySQL'):snapshot.checked_resources(values,['compose'])


def test_backup_failure_restarts_stopped_services_and_publishes_nothing(monkeypatch, tmp_path):
    values = {'COMPOSE_PROJECT_NAME': 'audit-test', 'ATLAS_CHAIN_SECRETS_DIR': str(tmp_path), 'ATLAS_API_IMAGE': 'reviewed:test'}
    monkeypatch.setattr(snapshot, 'read_env', lambda _: values)
    monkeypatch.setattr(snapshot, 'checked_resources', lambda *_: {s: {'Image': 'sha256:test'} for s in ('api','supervisor','supervisor-db')})
    monkeypatch.setattr(snapshot, 'mysql_digest', lambda _: 'digest')
    rpc = iter(['0x41b', '0x5', {'hash': '0x' + '1'*64}])
    monkeypatch.setattr(snapshot.subprocess, 'check_output', lambda *a, **k: json.dumps({'result': next(rpc)}))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ['docker', 'run']:
            (tmp_path / 'backup.tar.gz.partial').write_bytes(b'partial')
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(snapshot, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):snapshot.backup(tmp_path / 'env', tmp_path / 'backup.tar.gz')
    assert not list(tmp_path.glob('backup*'))
    assert [c[-1] for c in calls if 'start' in c] == ['supervisor-db', 'supervisor', 'api']


def test_archive_rejects_duplicate_and_unsafe_members(tmp_path):
    import io
    import tarfile
    for name in ['../secret', '/secret', 'secrets/unexpected']:
        path = tmp_path / 'invalid.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            entry = tarfile.TarInfo(name);entry.size=1
            archive.addfile(entry, io.BytesIO(b'x'))
        with pytest.raises(ValueError):snapshot.verify_archive(path)
