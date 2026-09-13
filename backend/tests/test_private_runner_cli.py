import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


def test_continuous_runner_retries_only_quotes_and_stops_on_rejected_signal(tmp_path, monkeypatch):
    sdk = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/private-strategy-runner.py'))
    source = tmp_path / 'strategy.py'
    source.write_text('def decide(context):\n    return "0.1" if context["step"] % 2 == 0 else "0"\n')
    directory = tmp_path / 'private'
    sdk['initialize'](SimpleNamespace(strategy=source, directory=directory, name='test'))
    metadata = json.loads((directory / 'release.public.json').read_text())
    snapshot = {key: metadata[key] for key in ('execution_mode', 'runner_public_key', 'code_commitment')}
    config = tmp_path / 'run.json'
    config.write_text(json.dumps({'api_url': 'http://127.0.0.1:8000', 'run_id': 'test-run', 'release_id': 'test-release', 'content_hash': sdk['hashlib'].sha256(sdk['canonical'](snapshot)).hexdigest()}))
    calls = {'get': 0, 'post': []}
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            calls['get'] += 1
            if calls['get'] == 1:
                raise httpx.ConnectTimeout('temporary quote failure')
            return httpx.Response(200, json={'bidPrice': '99', 'askPrice': '100'}, request=httpx.Request('GET', url))
        def post(self, url, json):
            calls['post'].append(json)
            return httpx.Response(200 if len(calls['post']) == 1 else 409, json={'accepted': True}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: Client())
    sleeps = []
    monkeypatch.setattr(sdk['time'], 'sleep', sleeps.append)
    with pytest.raises(RuntimeError, match='不重试成交'):
        sdk['run'](SimpleNamespace(directory=directory, config=config, steps=1, continuous=True, interval=12))
    assert calls['get'] == 3
    assert [body['target'] for body in calls['post']] == ['0.1', '0']
    assert sleeps == [30, 12]
