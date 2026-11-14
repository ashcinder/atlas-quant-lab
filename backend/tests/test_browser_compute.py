"""Browser architecture boundaries; synthetic data and disposable SQLite only."""
from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pandas as pd
import pytest

from app import main
from app.backtest.engine import run_backtest
from app.browser_runtime import authorized_run, demand_check, heartbeat
from app.cloud_proofs import CloudProofService
from app.compute_mode import browser_compute_enabled, cloud_generation_enabled
from app.compute_objects import ComputeObjects
from app.data.service import DataBundle
from app.lab_strategies import LabStrategyStore
from app.market_publication import MarketPublication
from app.models import Asset, BacktestRequest
from app.storage import RunStore
from app.strategy_runtime import ReleaseCreate, RunCreate, StrategyRuntimeStore
from app.workspace import WorkspaceStore


def register():
    from app.journal.router import _attempts
    _attempts.clear()
    client = TestClient(main.app)
    response = client.post('/api/register', json={'email': f'{uuid4()}@example.test', 'password': 'browser-test-password'})
    assert response.status_code == 201, response.text
    return client


@pytest.fixture
def architecture(tmp_path, monkeypatch):
    monkeypatch.setenv('ATLAS_COMPUTE_MODE', 'browser')
    monkeypatch.setenv('ATLAS_CLOUD_PROOF_GENERATION', 'false')
    monkeypatch.setenv('ATLAS_OBJECT_ROOT', str(tmp_path / 'objects'))
    monkeypatch.delenv('ATLAS_PUBLIC_S3_URI', raising=False)
    monkeypatch.delenv('ATLAS_PUBLIC_DATA_URL', raising=False)
    path = tmp_path / 'state.sqlite'
    runtime = StrategyRuntimeStore(main.data_service, path)
    runs = RunStore(path)
    cloud = CloudProofService(runtime, runs, None)
    workspace = WorkspaceStore(path)
    objects = ComputeObjects(tmp_path / 'objects')
    publications = MarketPublication(path, objects)
    LabStrategyStore(path)
    for singleton in (main.strategy_runtime_store, main.run_store, main.workspace_store, main.market_publications, main.lab_strategy_store):
        monkeypatch.setattr(singleton, 'path', path)
    monkeypatch.setattr(main.market_publications, 'objects', objects)
    monkeypatch.setattr(main.data_service, 'fetch', lambda *args, **kwargs: pytest.fail('HTTP consumer must never fetch upstream market data'))
    client = register()
    other = register()
    yield SimpleNamespace(client=client, other=other, runtime=runtime, runs=runs, cloud=cloud, workspace=workspace,
                          publications=publications, objects=objects, path=path)
    client.close()
    other.close()


@pytest.fixture
def published(architecture):
    frame = pd.DataFrame({'open': [100 + i for i in range(60)], 'high': [102 + i for i in range(60)],
                          'low': [99 + i for i in range(60)], 'close': [101 + i for i in range(60)], 'volume': 10000.},
                         index=pd.date_range('2025-01-01', periods=60, tz='UTC'))
    asset = Asset(symbol='BTC-USD', name='Synthetic fixture', asset_class='crypto', exchange='CRYPTO', currency='USD')
    bundle = DataBundle(asset, frame, 'synthetic-fixture', fetched_at=datetime(2025, 4, 1, tzinfo=UTC))
    manifest = architecture.publications.publish({'symbol': 'BTC-USD', 'asset_class': 'crypto', 'interval': '1d', 'adjustment': 'auto', 'data_source': 'auto'}, bundle)
    request = BacktestRequest(symbol='BTC-USD', asset_class='crypto', strategy_id='dca', persist=False)
    result = run_backtest(request, bundle).model_dump(mode='json')
    return SimpleNamespace(manifest=manifest, bundle=bundle, request=request.model_dump(mode='json'), result=result)


def upload(published, **updates):
    return {'mode': 'single', 'request': published.request, 'result': published.result,
            'dataset_ids': [published.manifest['dataset_id']], 'engine_version': 'browser-ts/v1', **updates}


def test_code_lab_keeps_private_drafts_and_separate_run_snapshots(architecture, published):
    client, other = architecture.client, architecture.other
    root = "/api/v1/lab-strategies"
    initial = "def target_bps(index, close, sma):\n    return 5000\n"
    draft = {"id": uuid4().hex, "name": "私有测试策略", "language": "python", "source": initial,
             "settings": {"symbol": "BTC-USD", "asset_class": "crypto", "initial_capital": 6000}}
    assert TestClient(main.app).get(root).status_code == 401
    client_owner = owner(client)
    client.headers["X-Atlas-Lab-Owner"] = client_owner
    other.headers["X-Atlas-Lab-Owner"] = owner(other)
    assert other.post(root, json=draft, headers={"X-Atlas-Lab-Owner": client_owner}).status_code == 403
    assert other.post("/api/v1/compute/compile", json={"source": initial},
                      headers={"X-Atlas-Lab-Owner": client_owner}).status_code == 403
    assert other.get(root).json() == []
    created = client.post(root, json=draft)
    assert created.status_code == 201, created.text
    item = created.json()
    assert client.post(root, json=draft).json() == item
    url = f"{root}/{item['id']}"
    assert item["revision"] == 1
    assert client.get(url).json()["source"] == initial
    summary = client.get(root)
    assert summary.headers["cache-control"] == "no-store"
    assert set(summary.json()[0]) == {"id", "name", "language", "kind", "revision", "updated_at"}
    assert summary.json()[0]["kind"] == "single_bounded"
    assert other.get(root).json() == []
    assert other.get(url).status_code == 404
    assert other.get(f"{url}/runs").status_code == 404
    changed = {**{key: value for key, value in draft.items() if key != "id"}, "expected_revision": 1, "name": "改名"}
    assert other.patch(url, json=changed).status_code == 404
    updated = client.patch(url, json=changed)
    assert updated.json()["revision"] == 2
    assert client.patch(url, json=changed).status_code == 409
    assert client.patch(url, json={**changed, "source": "\0", "expected_revision": 2}).status_code == 422

    expected = {}
    for target, capital in ((3000, 8000), (9500, 9000)):
        source = initial.replace("5000", str(target))
        request = BacktestRequest(symbol="BTC-USD", asset_class="crypto", strategy_id="python_bounded",
                                  python_source=source, initial_capital=capital)
        result = run_backtest(request, published.bundle).model_dump(mode="json")
        body = upload(published, request=request.model_dump(mode="json"), result=result, lab_strategy_id=item["id"])
        assert other.post("/api/v1/compute/runs", json=body).status_code == 404
        run = client.post("/api/v1/compute/runs", json=body)
        assert run.status_code == 201, run.text
        assert run.json()["compute"]["proof_status"] == "unverified"
        expected[run.json()["run_id"]] = (hashlib.sha256(source.encode()).hexdigest(), capital)
    assert client.post("/api/v1/compute/runs", json=upload(published, lab_strategy_id=item["id"])).status_code == 422
    history = client.get(f"{url}/runs").json()
    assert len(history) == 2
    for row in history:
        assert (row["source_sha256"], row["settings"]["initial_capital"]) == expected[row["id"]]
        assert "python_source" not in row
        assert client.get(f"/api/v1/runs/{row['id']}").status_code == 200
        assert other.get(f"/api/v1/runs/{row['id']}").status_code == 404
    assert client.get(url).json()["settings"]["initial_capital"] == 6000
    assert client.get(url).json()["source"] == initial


def owner(client):
    response = client.get('/api/v1/compute/identity')
    assert response.status_code == 200, response.text
    identity = response.json()
    assert identity['owner_id'] and identity['session_scope']
    return identity['owner_id']


def release(runtime, owner_id, visibility='private', python=False):
    fields = dict(name='Immutable strategy', source_kind='builtin', strategy_id='sma_cross', params={'fast': 3, 'slow': 8}, markets=['CRYPTO'], source_visibility=visibility)
    if python:
        fields.update(source_kind='python', strategy_id='python_bounded', params={}, python_source='def target_bps(index, close, sma):\n return 2000 if close(1) > 0 else 0')
    return runtime.create_release(owner_id, ReleaseCreate(**fields))


def subscription(runtime, owner_id, release_id):
    identifier = f'sub_{uuid4().hex}'
    with runtime._connect() as db:
        db.execute("INSERT INTO strategy_subscriptions VALUES (?,?,?,'active',?,NULL)", (identifier, owner_id, release_id, datetime.now(UTC).isoformat()))
    return identifier


def test_browser_is_default_and_cloud_generation_requires_explicit_legacy(monkeypatch):
    monkeypatch.delenv('ATLAS_COMPUTE_MODE', raising=False)
    monkeypatch.delenv('ATLAS_CLOUD_PROOF_GENERATION', raising=False)
    assert browser_compute_enabled()
    assert not cloud_generation_enabled()
    monkeypatch.setenv('ATLAS_CLOUD_PROOF_GENERATION', 'true')
    assert not cloud_generation_enabled()


def test_manifest_preparing_without_provider_fetch_and_authentication(architecture):
    anonymous = TestClient(main.app)
    assert anonymous.get('/api/v1/market/manifest').status_code == 401
    anonymous.close()
    response = architecture.client.get('/api/v1/market/manifest', params={'symbol': 'NOT-PUBLISHED'})
    assert response.status_code == 202
    assert response.json()['status'] == 'preparing'
    assert response.headers['cache-control'] == 'no-store'


def test_public_objects_are_immutable_authenticated_manifests_and_exact_sha(architecture, published):
    response = architecture.client.get('/api/v1/market/manifest', params={'symbol': 'BTC-USD', 'asset_class': 'crypto'})
    assert response.status_code == 200
    assert response.json()['dataset_id'] == published.manifest['dataset_id']
    chunk = response.json()['chunks'][0]
    anonymous = TestClient(main.app)
    try:
        response = anonymous.get(chunk['url'])
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == chunk['sha256']
        assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
        assert response.headers['access-control-allow-origin'] == '*'
        assert response.headers['etag'] == f'"{chunk["sha256"]}"'
        assert anonymous.get('/api/v1/market/datasets/' + published.manifest['dataset_id']).status_code == 401
    finally:
        anonymous.close()


def test_legacy_compute_routes_fail_closed_without_provider_calls(architecture):
    client = architecture.client
    assert client.get('/api/v1/market/bars').status_code == 410
    assert client.post('/api/v1/backtests', json={'symbol': 'BTC-USD', 'asset_class': 'crypto'}).status_code == 410
    assert client.post('/api/v1/portfolio/backtests', json={'assets': [{'symbol': 'SPY'}, {'symbol': 'TLT'}]}).status_code == 410
    assert client.post('/api/v1/research/jobs', json={'symbol': 'BTC-USD', 'asset_class': 'crypto', 'experiments': [{'strategy_id': 'sma_cross'}]}).status_code == 410
    assert client.post('/api/v1/alerts/evaluate').status_code == 410


def test_capabilities_reveal_owner_program_but_no_subscriber_secrets(architecture):
    author = owner(architecture.client)
    subscriber = owner(architecture.other)
    created = release(architecture.runtime, author, python=True)
    identifier = created['id']
    denied = architecture.other.get('/api/v1/compute/capabilities', params={'release_id': identifier})
    assert denied.status_code == 403
    subscription(architecture.runtime, subscriber, identifier)
    own = architecture.client.get('/api/v1/compute/capabilities', params={'release_id': identifier})
    assert own.status_code == 200
    assert own.json()['execution_location'] == 'browser'
    assert own.json()['strategy']['python_program']
    subscribed = architecture.other.get('/api/v1/compute/capabilities', params={'release_id': identifier})
    assert subscribed.status_code == 200
    assert subscribed.json()['execution_location'] == 'server_private'
    assert 'strategy' not in subscribed.json()
    encoded = subscribed.text
    assert 'python_program' not in encoded and 'target_bps' not in encoded and 'params' not in encoded


def test_save_assigns_identity_time_and_object_references(architecture, published):
    payload = upload(published)
    payload['result'] = {**payload['result'], 'run_id': 'client-invented-id', 'created_at': '2000-01-01T00:00:00Z'}
    response = architecture.client.post('/api/v1/compute/runs', json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['run_id'] != 'client-invented-id'
    assert result['created_at'].startswith(str(datetime.now(UTC).year))
    assert result['bars'] == []
    expected_compute = {'execution_location': 'browser', 'proof_status': 'unverified', 'engine_version': 'browser-ts/v1', 'dataset_ids': [published.manifest['dataset_id']], 'strategy_version': None}
    assert {key: result['compute'][key] for key in expected_compute} == expected_compute
    assert result['compute']['period_start'] == published.result['equity'][0]['time']
    assert result['compute']['period_end'] == published.result['equity'][-1]['time']
    saved_owner = owner(architecture.client)
    with architecture.runs._connect() as db:
        row = db.execute('SELECT owner_id,result_json FROM backtest_runs WHERE id=?', (result['run_id'],)).fetchone()
    assert row['owner_id'] == saved_owner
    index = json.loads(row['result_json'])
    assert '_object_sha256' in index and 'bars' not in index and 'equity' not in index
    assert architecture.objects.read('private', index['_object_sha256'])['bars'] == []
    history = architecture.client.get('/api/v1/runs/' + result['run_id'])
    assert history.status_code == 200 and history.json() == result
    assert history.headers['cache-control'] == 'no-store'
    assert architecture.other.get('/api/v1/runs/' + result['run_id']).status_code == 404
    listed = architecture.client.get('/api/v1/runs').json()
    assert listed[0]['compute']['execution_location'] == 'browser'
    assert architecture.other.get('/api/v1/runs').json() == []


@pytest.mark.parametrize('field,value', [('proof_status', 'verified'), ('verified', True), ('owner_id', 'someone-else'), ('execution_location', 'server_private'), ('zk_proof_id', 'fake'), ('receipt', {})])
def test_save_cannot_promote_uploaded_claims(architecture, published, field, value):
    payload = upload(published)
    payload['result'] = {**payload['result'], field: value}
    assert architecture.client.post('/api/v1/compute/runs', json=payload).status_code == 422


def test_save_rejects_unregistered_datasets_and_corrupt_public_objects(architecture, published):
    response = architecture.client.post('/api/v1/compute/runs', json=upload(published, dataset_ids=['a' * 64]))
    assert response.status_code == 422
    part = published.manifest['chunks'][0]
    architecture.objects.path('public', part['sha256']).write_text('{"bars":[]}')
    response = architecture.client.get(part['url'])
    assert response.status_code == 404
    with pytest.raises(ValueError, match='完整性'):
        architecture.publications.bundle(published.manifest['dataset_id'])


def active_run(architecture, subscriber=False):
    author = owner(architecture.client)
    run_owner = owner(architecture.other) if subscriber else author
    created = release(architecture.runtime, author)
    sub = subscription(architecture.runtime, run_owner, created['id']) if subscriber else None
    result = architecture.runtime.create_run(run_owner, RunCreate(release_id=created['id'], subscription_id=sub, market='CRYPTO', symbol='BTC-USD', initial_cash='10000'))
    architecture.runtime.set_status(run_owner, result['id'], 'start')
    return run_owner, result['id'], sub


def test_browser_demand_lease_is_independent_of_execution_mutex(architecture, monkeypatch):
    run_owner, identifier, _ = active_run(architecture)
    monkeypatch.setattr('app.browser_runtime.time.time', lambda: 1000.)
    with architecture.runtime._connect() as db:
        db.execute('UPDATE strategy_runs SET lease_until=999999,demand_until=0 WHERE id=?', (identifier,))
    response = heartbeat(architecture.runtime, run_owner, identifier)
    assert response == {'lease_expires_at': 1045., 'heartbeat_seconds': 15}
    run, _ = authorized_run(architecture.runtime, run_owner, identifier)
    assert run['lease_until'] == 999999
    assert run['demand_until'] == 1045
    assert run['needs_reanchor'] == '1'
    monkeypatch.setattr('app.browser_runtime.time.time', lambda: 1046.)
    monkeypatch.setattr(architecture.runtime, '_tick_locked', lambda *a, **kw: pytest.fail('expired demand must not tick'))
    with pytest.raises(HTTPException) as error:
        architecture.runtime.tick(run_owner, identifier, {'dataset_id': 'a' * 64, 'bar_time': 1, 'target': 1})
    assert error.value.status_code == 409
    run, _ = authorized_run(architecture.runtime, run_owner, identifier)
    assert run['status'] == 'active'


def test_runtime_rechecks_subscription_and_rejects_browser_signal_for_private(architecture):
    run_owner, identifier, sub = active_run(architecture, subscriber=True)
    heartbeat(architecture.runtime, run_owner, identifier)
    with pytest.raises(HTTPException) as error:
        demand_check(architecture.runtime, run_owner, identifier, {'target': 1})
    assert error.value.status_code == 403
    with architecture.runtime._connect() as db:
        db.execute("UPDATE strategy_subscriptions SET status='cancelled' WHERE id=?", (sub,))
    with pytest.raises(HTTPException) as error:
        heartbeat(architecture.runtime, run_owner, identifier)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        architecture.runtime.tick(run_owner, identifier)
    assert error.value.status_code == 403


def test_cloud_proof_creation_disabled_without_profiles_or_prover(architecture, monkeypatch):
    monkeypatch.setattr('app.cloud_proofs.load_profiles', lambda *a, **kw: pytest.fail('disabled cloud must not inspect profiles'))
    monkeypatch.setattr('app.cloud_proofs.run_proof', lambda *a, **kw: pytest.fail('disabled cloud must not start prover'))
    response = architecture.client.post('/api/v1/strategy-releases/not-real/proof-jobs', json={'market_data_hash': 'a' * 64, 'address': '0x' + '1' * 40})
    assert response.status_code == 410
    assert architecture.cloud.config()['location'] == 'author_local'
    architecture.cloud.tick()
    architecture.cloud.start()
    assert architecture.cloud.thread is None


def test_paid_unfinished_jobs_block_retirement_without_rewriting_history(architecture):
    with architecture.runtime._connect() as db:
        db.execute("INSERT INTO bkc_orders (id,owner_id,kind,resource_id,signer,recipient,amount_wei,data,genesis,status,transaction_hash) VALUES ('old-order','old-owner','proof','old-job','signer','recipient','1','0x','genesis','confirmed','old-tx')")
        db.execute("INSERT INTO cloud_proof_jobs VALUES ('old-job','old-owner','old-release','market','{}','old-order','proving',NULL,NULL,1,1)")
    assert architecture.cloud.pending_paid_jobs() == [{'id': 'old-job', 'status': 'proving'}]
    with pytest.raises(RuntimeError, match='阻止停用'):
        architecture.cloud.start()
    with architecture.runtime._connect() as db:
        assert db.execute("SELECT status,updated_at FROM cloud_proof_jobs WHERE id='old-job'").fetchone()[:] == ('proving', 1.)
        assert db.execute("SELECT status,transaction_hash FROM bkc_orders WHERE id='old-order'").fetchone()[:] == ('confirmed', 'old-tx')


def test_private_results_owner_isolation_and_browser_upload_denial(architecture, published, monkeypatch):
    author = owner(architecture.client)
    subscriber = owner(architecture.other)
    created = release(architecture.runtime, author)
    subscription(architecture.runtime, subscriber, created['id'])
    raw_result = json.loads(json.dumps(published.result))
    raw_result['strategy']['description'] = 'SECRET internal parameter'
    raw_result['source_note'] = 'SECRET internal debugging'
    for trade in raw_result['trades']:
        trade['reason'] = 'SECRET internal decision'
    monkeypatch.setattr(main.private_compute, '_execute', lambda encoded: json.loads(json.dumps(raw_result)))
    response = architecture.other.post('/api/v1/compute/private-backtests', json={'release_id': created['id'], 'dataset_id': published.manifest['dataset_id']})
    assert response.status_code == 200, response.text
    result = response.json()
    assert 'SECRET' not in response.text
    assert result['compute']['execution_location'] == 'server_private'
    assert result['proof_status'] == 'unverified'
    assert result['strategy']['parameters'] == []
    assert architecture.client.get('/api/v1/runs/' + result['run_id']).status_code == 404
    saved = architecture.other.get('/api/v1/runs/' + result['run_id'])
    assert saved.status_code == 200
    assert saved.headers['cache-control'] == 'no-store'
    assert saved.json()['bars'] == []
    assert saved.json()['compute']['dataset_ids'] == [published.manifest['dataset_id']]
    forged = upload(published, request={**published.request, 'release_id': created['id']}, strategy_version=created['content_hash'])
    assert architecture.other.post('/api/v1/compute/runs', json=forged).status_code == 403
    assert architecture.client.post('/api/v1/compute/private-backtests', json={'release_id': created['id'], 'dataset_id': published.manifest['dataset_id']}).status_code == 409


def test_alert_observations_recheck_owner_enabled_and_cooldown(architecture):
    response = architecture.client.post('/api/v1/alerts', json={'name': 'Browser price', 'symbol': 'BTC-USD', 'asset_class': 'crypto', 'kind': 'price_above', 'threshold': 100})
    assert response.status_code == 201, response.text
    identifier = response.json()['id']
    endpoint = '/api/v1/compute/alerts/' + identifier + '/observations'
    assert architecture.other.post(endpoint, json={'value': 110, 'triggered': True}).status_code == 404
    first = architecture.client.post(endpoint, json={'value': 110, 'triggered': True})
    assert first.status_code == 200 and first.json()['notification']
    assert '浏览器计算，未证明' in first.json()['notification']['message']
    second = architecture.client.post(endpoint, json={'value': 120, 'triggered': True})
    assert second.json()['notification'] is None
    assert architecture.client.get('/api/v1/alerts').json()[0]['last_value'] == 120
    alert = response.json()
    body = {key: alert[key] for key in ('name', 'symbol', 'asset_class', 'interval', 'data_source', 'kind', 'threshold', 'cooldown_minutes', 'enabled')}
    architecture.client.put('/api/v1/alerts/' + identifier, json={**body, 'enabled': False})
    assert architecture.client.post(endpoint, json={'value': 130, 'triggered': True}).status_code == 409


def test_runtime_requires_current_registered_dataset_and_never_recomputes_browser_strategy(architecture, published, monkeypatch):
    from dataclasses import replace
    run_owner, identifier, _ = active_run(architecture)
    architecture.runtime.publications = architecture.publications
    monkeypatch.setattr(architecture.runtime, '_targets', lambda *a, **kw: pytest.fail('browser signal must not run strategy on server'))
    heartbeat(architecture.runtime, run_owner, identifier)
    old_id = published.manifest['dataset_id']
    replacement = architecture.publications.publish({'symbol': 'BTC-USD', 'asset_class': 'crypto', 'interval': '1d', 'adjustment': 'auto', 'data_source': 'auto'}, replace(published.bundle, fetched_at=datetime(2025, 4, 2, tzinfo=UTC)))
    assert replacement['dataset_id'] != old_id
    assert architecture.publications.manifest(old_id)['dataset_id'] == old_id
    signal = {'dataset_id': old_id, 'bar_time': published.result['equity'][-1]['time'], 'target': 1., 'reason': 'untrusted source'}
    with pytest.raises(HTTPException) as error:
        architecture.runtime.tick(run_owner, identifier, signal)
    assert error.value.status_code == 409
    assert '当前服务端登记' in error.value.detail
    assert architecture.runtime.get_run(run_owner, identifier)['status'] == 'active'
    heartbeat(architecture.runtime, run_owner, identifier)
    response = architecture.runtime.tick(run_owner, identifier, {**signal, 'dataset_id': replacement['dataset_id']})
    assert response['last_bar_time'] == signal['bar_time']
    # Reopening against historical data anchors the run; it never fabricates fills.
    assert response.get('fills', []) == []


@pytest.mark.parametrize('mode', ['', 'typo', 'Browser'])
def test_unknown_compute_mode_does_not_enable_legacy(monkeypatch, mode):
    monkeypatch.setenv('ATLAS_COMPUTE_MODE', mode)
    with pytest.raises(ValueError, match='ATLAS_COMPUTE_MODE'):
        browser_compute_enabled()


def test_private_execution_mutex_outlasts_queue_and_demand_lease(architecture, monkeypatch):
    run_owner, identifier, _ = active_run(architecture, subscriber=True)
    heartbeat(architecture.runtime, run_owner, identifier)
    def inspect_mutex(*args):
        run, _ = authorized_run(architecture.runtime, run_owner, identifier)
        remaining = run['lease_until'] - datetime.now(UTC).timestamp()
        assert 120 < remaining <= 135
        raise HTTPException(429, 'busy')
    monkeypatch.setattr(architecture.runtime, '_tick_locked', inspect_mutex)
    with pytest.raises(HTTPException) as error:
        architecture.runtime.tick(run_owner, identifier)
    assert error.value.status_code == 429
    run, _ = authorized_run(architecture.runtime, run_owner, identifier)
    assert run['status'] == 'active' and run['lease_until'] == 0


def test_retry_public_distribution_uses_internal_agent_binding(architecture, tmp_path, monkeypatch):
    from tests.test_quantjudge import create_agent, make_report, make_store
    from app.public_artifacts import PublicArtifacts
    reports = make_store(tmp_path)
    agent = create_agent(reports)
    report = reports.publish_report(agent['agent']['id'], make_report(), agent['developer_token'])
    assert 'agent_id' not in reports.get_report(report['id'])
    exports = PublicArtifacts(reports, None, architecture.objects)
    monkeypatch.setattr(main, 'quantjudge_store', reports)
    monkeypatch.setattr(main.public_artifacts, 'path', exports.path)
    monkeypatch.setattr(main.public_artifacts, 'root', exports.root)
    monkeypatch.setattr(main.public_artifacts, 'reports', reports)
    url = f"/api/v1/quantjudge/reports/{report['id']}/distribution"
    assert architecture.client.post(url, json={}).status_code == 403
    response = architecture.client.post(url, headers={'X-Developer-Token': agent['developer_token']}, json={})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'ready'
    public_file = architecture.client.get(response.json()['report_url'])
    assert public_file.status_code == 200
    assert 'immutable' in public_file.headers['cache-control']


def test_published_query_coverage_includes_closed_market_days(architecture):
    frame = pd.DataFrame({'open':[100,101,102],'high':[102,103,104],'low':[99,100,101],'close':[101,102,103],'volume':[100,100,100]},
                         index=pd.to_datetime(['2025-03-03T04:00Z','2025-03-04T04:00Z','2025-03-07T04:00Z']))
    bundle = DataBundle(Asset(symbol='TEST',name='test',asset_class='equity',exchange='NYSE',currency='USD'),frame,'synthetic',fetched_at=datetime(2025,3,10,tzinfo=UTC))
    query = {'symbol':'TEST','asset_class':'equity','interval':'1d','start':datetime(2025,3,1,tzinfo=UTC),'end':datetime(2025,3,9,tzinfo=UTC)}
    manifest = architecture.publications.publish(query,bundle)
    selected = architecture.publications.bundle(manifest['dataset_id'], query['start'], query['end'])
    assert len(selected.frame)==3
    assert manifest['coverage']['start'] < manifest['start'] and manifest['coverage']['end'] > manifest['end']
    with pytest.raises(ValueError,match='开始日期'):
        architecture.publications.bundle(manifest['dataset_id'],datetime(2025,2,28,tzinfo=UTC),query['end'])


def test_code_lab_schema_upgrade_preserves_existing_run_and_project(tmp_path):
    import sqlite3

    path = tmp_path / "old-copy.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE backtest_runs (
                id TEXT PRIMARY KEY, mode TEXT NOT NULL, strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL,
                created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'completed', owner_id TEXT NOT NULL
            );
            INSERT INTO backtest_runs VALUES (
                'old-run','single','sma_cross','BTC-USD','{}','{"metrics":{"total_return":0.2}}',
                '2025-01-01T00:00:00Z','completed','old-owner'
            );
            CREATE TABLE strategy_projects (id TEXT PRIMARY KEY);
            INSERT INTO strategy_projects VALUES ('old-project');
        """)
    store = RunStore(path)
    LabStrategyStore(path)
    assert store.list("old-owner")[0].total_return == 0.2
    assert store.get("old-owner", "old-run") == {"metrics": {"total_return": 0.2}}
    assert store.list_lab("old-owner", "new-draft") == []
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id FROM strategy_projects").fetchone() == ("old-project",)
        assert db.execute("SELECT lab_strategy_id FROM backtest_runs").fetchone() == (None,)
