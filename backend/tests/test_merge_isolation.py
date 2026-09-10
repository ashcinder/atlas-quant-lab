"""Both product lines must retain account boundaries after the merge."""

import sqlite3

import pytest

from app import main
from app.journal.router import _attempts
from app.quantjudge import canonical_json, sha256_hex
from app.strategy_projects import StrategyProjectStore
from tests.test_integrated_api import registered
from tests.test_quantjudge import create_agent
from tests.test_strategy_projects import custom_strategy
from tests.test_strategy_studio import package_bytes


@pytest.fixture
def users():
    _attempts.clear()
    first, _, _ = registered()
    second, _, _ = registered()
    yield first, second
    first.close()
    second.close()


def project(client):
    response = client.post('/api/v1/strategy-projects', json={
        'name': 'Private research', 'thesis': 'A private causal momentum research hypothesis.',
        'asset_symbol': 'BTC-USD', 'asset_class': 'crypto',
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_projects_and_same_named_strategies_are_account_scoped(users):
    first, second = users
    a, b = project(first), project(second)
    assert [p['id'] for p in second.get('/api/v1/strategy-projects').json()] == [b['id']]
    root = '/api/v1/strategy-projects/' + a['id']
    assert second.get(root).status_code == 404
    assert second.patch(root, json={'expected_revision': 1, 'name': 'Stolen'}).status_code == 404
    assert second.post(root + '/freeze', json={'expected_revision': 1, 'version': '1.0.0'}).status_code == 404
    spec_a = custom_strategy()
    spec_b = spec_a.model_copy(update={'target_position': 0.2})
    for client, spec in [(first, spec_a), (second, spec_b)]:
        assert client.put('/api/v1/custom-strategies/' + spec.id, json=spec.model_dump(mode='json')).status_code == 200
    for client, p, spec in [(first, a, spec_a), (second, b, spec_b)]:
        linked = client.post('/api/v1/strategy-projects/' + p['id'] + '/artifacts', json={
            'expected_revision': 1, 'kind': 'strategy', 'artifact_id': spec.id,
        })
        assert linked.status_code == 200, linked.text
        assert linked.json()['strategy_hash'] == sha256_hex(canonical_json(spec.model_dump(mode='json')))
    foreign_spec = spec_a.model_copy(update={'id': 'only_first'})
    assert first.put('/api/v1/custom-strategies/only_first', json=foreign_spec.model_dump(mode='json')).status_code == 200
    assert second.post('/api/v1/strategy-projects/' + b['id'] + '/artifacts', json={
        'expected_revision': 2, 'kind': 'strategy', 'artifact_id': 'only_first',
    }).status_code == 422


def test_package_links_require_developer_credential_and_subscriptions_require_session_owner(users):
    first, second = users
    a = project(first)
    created = create_agent(main.quantjudge_store)
    agent_id, token = created['agent']['id'], created['developer_token']
    package = main.strategy_studio_store.upload_package(agent_id, 'test.qstrategy', package_bytes(), token)
    endpoint = '/api/v1/strategy-projects/' + a['id'] + '/artifacts'
    link = {'expected_revision': 1, 'kind': 'package', 'artifact_id': package['id']}
    assert first.post(endpoint, json=link).status_code == 401
    assert first.post(endpoint, json=link, headers={'X-Developer-Token': 'wrong'}).status_code == 401
    assert first.post(endpoint, json=link, headers={'X-Developer-Token': token}).status_code == 200
    subscription = first.post(f'/api/v1/quantjudge/agents/{agent_id}/subscriptions', json={
        'investor_alias': 'shared-alias', 'payment_reference': 'first-private-reference',
    })
    assert subscription.status_code == 201, subscription.text
    query = '/api/v1/quantjudge/subscriptions?investor_alias=shared-alias'
    assert second.get(query).json() == []
    own = second.post(f'/api/v1/quantjudge/agents/{agent_id}/subscriptions', json={'investor_alias': 'shared-alias'})
    assert own.status_code == 201, own.text
    assert [s['id'] for s in first.get(query).json()] == [subscription.json()['id']]
    assert [s['id'] for s in second.get(query).json()] == [own.json()['id']]


def test_project_owner_migration_preserves_unassigned_legacy_rows(tmp_path):
    from app.strategy_projects import StrategyProjectCreate
    path = tmp_path / 'legacy.db'
    store = StrategyProjectStore(path)
    p = store.create(StrategyProjectCreate(name='Legacy project', thesis='An existing local private hypothesis.', asset_symbol='BTC-USD', asset_class='crypto'))
    with sqlite3.connect(path) as db:
        db.execute('DROP INDEX idx_strategy_projects_owner_updated')
        db.execute('ALTER TABLE strategy_projects DROP COLUMN owner_id')
    migrated = StrategyProjectStore(path)
    assert migrated.get(p['id'])['id'] == p['id']
    assert migrated.list('new-user') == []
