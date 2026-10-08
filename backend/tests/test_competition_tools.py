import importlib.util
import json
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]

def load(relative):
    spec=importlib.util.spec_from_file_location('competition_tool', ROOT/relative)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_author_write_failure_never_leaves_a_partial_credential(tmp_path, monkeypatch):
    importer=load('scripts/import-verified-proof.py')
    def fail(_): raise OSError('injected fsync failure')
    monkeypatch.setattr(importer.os,'fsync',fail)
    target=tmp_path/'secrets/author.json'
    with pytest.raises(OSError):importer.persist_author_credential(target,'agent','test-token')
    assert not target.exists()

def test_author_is_private_exclusive_and_cannot_overwrite(tmp_path):
    importer=load('scripts/import-verified-proof.py');target=tmp_path/'secrets/author.json'
    importer.persist_author_credential(target,'agent','test-token')
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):importer.persist_author_credential(target,'agent','another')
    assert json.loads(target.read_text())['developer_token']=='test-token'

def test_import_rejects_repository_author_path_before_reading_bundle(monkeypatch,tmp_path):
    importer=load('scripts/import-verified-proof.py')
    monkeypatch.setattr(importer.sys,'argv',['import','--bundle',str(tmp_path/'missing.zip'),'--expected-receipt-sha256','0'*64,'--data-dir',str(tmp_path/'atlas-data'),'--author-file',str(ROOT/'docs/competition/evidence/author.private.json')])
    with pytest.raises(SystemExit):importer.main()
    assert not (ROOT/'docs/competition/evidence/author.private.json').exists()

def test_stop_rejects_unrelated_process_even_with_same_port(monkeypatch,tmp_path):
    demo=load('docs/competition/demo.py');(tmp_path/'api.pid').write_text('12345')
    monkeypatch.setattr(demo.subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a,0,stdout='python -m uvicorn app.main:app --port 8018',stderr=''))
    with pytest.raises(RuntimeError,match='ownership mismatch'):demo.own_pid(tmp_path,'api.pid')
