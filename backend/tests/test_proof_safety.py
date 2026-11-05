import json
import os
from pathlib import Path
import signal
import subprocess
import shutil
import sys
import time
from types import SimpleNamespace

import pytest

from test_cloud_proofs import setup


@pytest.mark.parametrize(('name', 'value'), [
    ('ATLAS_PROOF_THREADS', '4'), ('ATLAS_PROOF_SEGMENT_PO2', '21'),
    ('ATLAS_PROOF_DISK_SEGMENTS', 'invalid'),
])
def test_invalid_settings_block_orders_even_with_cached_readiness(setup, monkeypatch, name, value):
    import app.cloud_proofs as module
    runtime, service, release = setup
    monkeypatch.setenv('TRINE_PROOF_PRICE_BKC', '1')
    monkeypatch.setenv('TRINE_PROOF_RECIPIENT', '0x' + 'a' * 40)
    monkeypatch.setenv(name, value)
    service._readiness_cache = (time.monotonic(), True)
    monkeypatch.setattr(module, 'prover_memory_ready', lambda: True)
    result = module.CloudProofService.config(service)
    assert result['configured'] is False
    assert value not in result['unavailable_reason']
    service.config = lambda: result
    with pytest.raises(module.HTTPException) as exc:
        service.create('author', release['id'], module.ProofJobInput(
            market_data_hash='b' * 64, address='0x' + 'a' * 40, consent_cloud_source=True))
    assert exc.value.status_code == 503
    with runtime._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM bkc_orders').fetchone()[0] == 0


def market(count=3):
    return {'source': 'synthetic', 'symbol': 'TEST', 'interval': '1d',
            'adjustment': 'none', 'bars': [{}] * count}


def test_metadata_limits_count_utf8_bytes_and_keep_maximum_bars():
    from app.proof_runtime import validate_market_input
    for field in ('source', 'symbol', 'interval', 'adjustment'):
        data = market(20_000)
        data[field] = '行' * 1365 + 'x'
        validate_market_input(data)
        data[field] += 'x'
        with pytest.raises(ValueError, match=field):
            validate_market_input(data)
        for value in (42, None, ['text']):
            data[field] = value
            with pytest.raises(ValueError, match=field):
                validate_market_input(data)


def test_json_read_is_bounded_before_parsing(tmp_path):
    from app.proof_runtime import read_proof_json, MAX_PROOF_INPUT_BYTES
    path = tmp_path / 'input.json'
    path.write_bytes(b'{}' + b' ' * (MAX_PROOF_INPUT_BYTES - 2))
    assert read_proof_json(path) == {}
    with path.open('ab') as f:
        f.write(b' ')
    with pytest.raises(ValueError, match='16MiB'):
        read_proof_json(path)


def test_oversized_market_is_rejected_before_creating_order(setup):
    from app.cloud_proofs import ProofJobInput, HTTPException
    runtime, service, release = setup
    dataset = service.proofs.market_dataset('b' * 64)[1]
    data = market(32)
    data['source'] = 'x' * 4097
    dataset.write_text(json.dumps({'dataset': data}))
    with pytest.raises(HTTPException) as exc:
        service.create('author', release['id'], ProofJobInput(
            market_data_hash='b' * 64, address='0x' + 'a' * 40, consent_cloud_source=True))
    assert exc.value.status_code == 422
    with runtime._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM bkc_orders').fetchone()[0] == 0


def test_final_witness_budget_is_checked_before_order(setup, monkeypatch):
    from app.cloud_proofs import ProofJobInput, HTTPException
    import app.proof_runtime as limits
    runtime, service, release = setup
    dataset = service.proofs.market_dataset('b' * 64)[1]
    assert dataset.stat().st_size < 600
    monkeypatch.setattr(limits, 'MAX_PROOF_INPUT_BYTES', 600)
    with pytest.raises(HTTPException) as exc:
        service.create('author', release['id'], ProofJobInput(
            market_data_hash='b' * 64, address='0x' + 'a' * 40, consent_cloud_source=True))
    assert exc.value.status_code == 422 and '完整' in exc.value.detail
    with runtime._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM bkc_orders').fetchone()[0] == 0


def test_configuration_change_after_payment_preserves_order_and_witness(setup, monkeypatch):
    import app.cloud_proofs as module
    runtime, service, release = setup
    job = service.create('author', release['id'], module.ProofJobInput(
        market_data_hash='b' * 64, address='0x' + 'a' * 40, consent_cloud_source=True))
    directory = service.root / job['id']
    directory.mkdir(mode=0o700)
    witness = directory / 'witness.private.json'
    witness.write_bytes(b'original paid identity and input; do not replace')
    with runtime._connect() as c:
        c.execute("UPDATE bkc_orders SET status='confirmed' WHERE id=?", (job['order_id'],))
        c.execute("UPDATE cloud_proof_jobs SET status='queued' WHERE id=?", (job['id'],))
    monkeypatch.setenv('ATLAS_PROOF_THREADS', '4')
    monkeypatch.setattr(module, 'run_proof', lambda *a, **k: pytest.fail('must not start prover'))
    service.tick()
    assert service.get('author', job['id'])['status'] == 'failed'
    assert service.get('author', job['id'])['order_id'] == job['order_id']
    assert witness.read_bytes() == b'original paid identity and input; do not replace'
    with runtime._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM bkc_orders').fetchone()[0] == 1
    module.work_limits.acquire('author')
    module.work_limits.release('author')


def test_segment_cleanup_refuses_foreign_dirs_and_symlinks(tmp_path):
    from app.proof_segments import segment_workspace, cleanup_segments
    output = tmp_path / 'task'
    output.mkdir(mode=0o700)
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'keep').write_text('preserve')
    foreign = output / '.proof-segments-foreign'
    foreign.mkdir(mode=0o700)
    (foreign / 'keep').write_text('preserve')
    (output / '.proof-segments-symlink').symlink_to(other, target_is_directory=True)
    with segment_workspace(output) as (path, fd):
        assert path.stat().st_mode & 0o777 == 0o700
        assert cleanup_segments(output) is False
        (path / 'segment').write_text('synthetic')
    assert not path.exists()
    assert cleanup_segments(output) is True
    assert (other / 'keep').is_file() and (foreign / 'keep').is_file()
    linked = tmp_path / 'linked'
    linked.symlink_to(output, target_is_directory=True)
    with pytest.raises(OSError):
        cleanup_segments(linked)


def test_worker_startup_reclaims_only_known_job_roots(setup):
    from app.cloud_proofs import ProofJobInput
    runtime, service, release = setup
    job = service.create('author', release['id'], ProofJobInput(
        market_data_hash='b' * 64, address='0x' + 'a' * 40, consent_cloud_source=True))
    output = service.root / job['id'] / 'result'
    output.mkdir(mode=0o700, parents=True)
    unknown = service.root / ('cpj_' + 'f' * 32) / 'result'
    unknown.mkdir(mode=0o700, parents=True)
    code = '''
import os,sys
from pathlib import Path
from app.proof_segments import segment_workspace
with segment_workspace(Path(sys.argv[1])) as (path,fd):
    (path/'synthetic.segment').write_text('synthetic')
    os._exit(0)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    for path in (output, unknown):
        subprocess.run([sys.executable, '-c', code, str(path)], env=env, timeout=5, check=True)
        assert list(path.glob('.proof-segments-*'))
    service.reclaim_segments()
    assert not list(output.glob('.proof-segments-*/synthetic.segment'))
    assert list(unknown.glob('.proof-segments-*/synthetic.segment'))


def test_copied_owner_marker_and_nested_symlink_cannot_delete_other_task(tmp_path):
    from app.proof_segments import segment_workspace, cleanup_segments
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir(mode=0o700); second.mkdir(mode=0o700)
    protected = tmp_path / 'keep'
    protected.mkdir(); (protected / 'data').write_text('preserve')
    with segment_workspace(first) as (path, _):
        copied = second / path.name
        shutil.copytree(path, copied)
        assert cleanup_segments(second)
        assert copied.is_dir()  # Marker is bound to the original task inode.
        (path / 'linked-data').symlink_to(protected, target_is_directory=True)
    assert not path.exists()
    assert (protected / 'data').read_text() == 'preserve'
    assert copied.is_dir()


def test_marker_failure_removes_only_new_empty_directory(tmp_path, monkeypatch):
    from app.proof_segments import segment_workspace
    import app.proof_segments as module
    with monkeypatch.context() as patch:
        patch.setattr(module.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('synthetic failure')))
        with pytest.raises(OSError, match='synthetic failure'):
            with segment_workspace(tmp_path):
                pytest.fail('must not start a prover without a durable owner marker')
    assert not list(tmp_path.glob('.proof-segments-*/'))


def test_saved_oversized_witness_is_not_replaced(tmp_path, monkeypatch):
    from app.cloud_proofs import ensure_job_witness
    import app.proof_runtime as limits
    monkeypatch.setattr(limits, 'MAX_PROOF_INPUT_BYTES', 10)
    saved = tmp_path / 'witness.private.json'
    content = b'{' + b' ' * 100 + b'}'
    saved.write_bytes(content)
    with pytest.raises(ValueError, match='16MiB'):
        ensure_job_witness(saved, {}, tmp_path / 'result')
    assert saved.read_bytes() == content
    assert not list(tmp_path.glob('incomplete-*'))


def test_sigkill_residue_recovered_only_after_inherited_lock_released(tmp_path):
    from app.proof_segments import cleanup_segments
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'task'
    output.mkdir(mode=0o700)
    code = '''
from pathlib import Path
import subprocess,sys,time
from app.proof_segments import segment_workspace
output=Path(sys.argv[1])
with segment_workspace(output) as (path,fd):
    (path/'synthetic.segment').write_text('no private data')
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],pass_fds=(fd,))
    (output/'child.pid').write_text(str(child.pid))
    (output/'ready').write_text(str(path))
    time.sleep(20)
'''
    env = dict(os.environ, PYTHONPATH=str(root))
    parent = subprocess.Popen([sys.executable, '-c', code, str(output)], env=env,
                              start_new_session=True)
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not (output / 'ready').exists() and time.monotonic() < deadline:
            assert parent.poll() is None
            time.sleep(.02)
        assert (output / 'ready').exists()
        child_pid = int((output / 'child.pid').read_text())
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=5)
        assert cleanup_segments(output) is False
        os.kill(child_pid, signal.SIGKILL)
        for _ in range(100):
            if cleanup_segments(output):
                break
            time.sleep(.02)
        else:
            pytest.fail('inherited task lock never released')
        assert not list(output.glob('.proof-segments-*/synthetic.segment'))
    finally:
        try:
            os.killpg(parent.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.wait(timeout=5)


def test_public_metrics_do_not_forward_nested_private_details():
    import runpy
    script = Path(__file__).resolve().parents[2] / 'scripts/prove-private-program.py'
    sdk = runpy.run_path(str(script))
    assert sdk['public_prover_performance']({
        'elapsed_seconds': 1.2, 'segment_limit_po2': 19,
        'stats': {'segments': 7, 'user_cycles': 12345},
        'timings': {'prepare': {'input_bytes': 999}, 'execution_seconds': .5},
    }) == {'elapsed_seconds': 1.2, 'segment_limit_po2': 19, 'stats': {'segments': 7}}


@pytest.mark.parametrize('disk_segments', ['0', '1'])
def test_global_worker_lock_survives_middle_process_sigkill(tmp_path, disk_segments):
    import fcntl
    from app.proof_segments import cleanup_segments
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / 'job' / 'result'
    output.mkdir(mode=0o700, parents=True)
    worker = (tmp_path / 'worker.lock').open('a')
    fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
    code = '''
from pathlib import Path
import runpy,sys
root=Path(sys.argv[1]);out=Path(sys.argv[2]);fd=int(sys.argv[3])
sys.path.insert(0,str(root/'backend'))
sdk=runpy.run_path(str(root/'scripts/prove-private-program.py'))
g=sdk['invoke_prove'].__globals__
g['BINARY']=Path(sys.executable)
stub="import os,time;from pathlib import Path;Path("+repr(str(out/'leaf.pid'))+").write_text(str(os.getpid()));time.sleep(20)"
g['prove_arguments']=lambda *a:['-c',stub]
sdk['invoke_prove'](out/'witness',out/'proof.r0',out,fd)
'''
    env = dict(os.environ, ATLAS_PROOF_DISK_SEGMENTS=disk_segments)
    middle = subprocess.Popen([sys.executable, '-c', code, str(root), str(output),
                               str(worker.fileno())], pass_fds=(worker.fileno(),),
                              env=env, start_new_session=True)
    worker.close()  # Simulate disappearance of the outer API worker.
    leaf = None
    probe = (tmp_path / 'worker.lock').open('a')
    try:
        deadline = time.monotonic() + 5
        while not (output / 'leaf.pid').exists() and time.monotonic() < deadline:
            assert middle.poll() is None
            time.sleep(.02)
        leaf = int((output / 'leaf.pid').read_text())
        os.kill(middle.pid, signal.SIGKILL)
        middle.wait(timeout=5)
        with pytest.raises(BlockingIOError):
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cleanup_segments(output) is (disk_segments == '0')
        os.kill(leaf, signal.SIGKILL)
        for _ in range(100):
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(.02)
        else:
            pytest.fail('global worker lock did not release')
        assert cleanup_segments(output)
    finally:
        probe.close()
        try:
            os.killpg(middle.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        middle.wait(timeout=5)
