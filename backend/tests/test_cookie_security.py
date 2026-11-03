"""Cookie regression tests use disposable users and never trust forwarded headers."""
import hashlib
import hmac
import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import auth, cloud_ai
from app.journal import router
from app.journal.store import JournalStore
from app.main import app


@pytest.mark.parametrize('force_secure,base_url,expected_secure', [
    (True, 'http://testserver', True),  # TLS terminates before the backend.
    (False, 'http://testserver', False),
    (False, 'https://testserver', True),
])
def test_session_cookie_lifecycle(monkeypatch, force_secure, base_url, expected_secure):
    monkeypatch.setattr(router, 'COOKIE_SECURE', force_secure)
    router._attempts.clear()
    client = TestClient(app, base_url=base_url)
    email, password = f'{uuid4()}@example.test', 'cookie-test-password'

    def cookie(response, status=200):
        assert response.status_code == status, response.text
        value = response.headers['set-cookie'].lower()
        assert ('secure' in value) is expected_secure
        assert 'httponly' in value and 'samesite=strict' in value
        return response

    cookie(client.post('/api/register', json={'email': email, 'password': password}), 201)
    if force_secure and base_url.startswith('http:'):
        # Browser/cookie jar refuses to send a Secure cookie via plaintext HTTP.
        assert client.get('/api/ledger').status_code == 401
        client.base_url = 'https://testserver'
    assert client.get('/api/session').json()['authenticated']
    cookie(client.post('/api/logout'))
    assert client.get('/api/ledger').status_code == 401
    cookie(client.post('/api/login', json={'email': email, 'password': password}))
    old_session = client.cookies.get('atlas_session')
    cookie(client.post('/api/change-password', json={
        'currentPassword': password, 'newPassword': password + '-new',
    }))
    assert client.get('/api/ledger').status_code == 200
    other_device = TestClient(app, base_url='https://testserver')
    other_device.cookies.set('atlas_session', old_session)
    assert other_device.get('/api/ledger').status_code == 401
    cookie(client.post('/api/logout'))
    assert client.post('/api/login', json={'email': email, 'password': password}).status_code == 401
    cookie(client.post('/api/login', json={'email': email, 'password': password + '-new'}))
    client.close()
    other_device.close()


def test_logout_revokes_only_current_session_and_clears_only_its_cloud_config():
    router._attempts.clear()
    cloud_ai._sessions.clear()
    first = TestClient(app)
    second = TestClient(app)
    email, password = f'{uuid4()}@example.test', 'two-device-password'
    assert first.post('/api/register', json={'email': email, 'password': password}).status_code == 201
    first_token = first.cookies.get('atlas_session')
    assert second.post('/api/login', json={'email': email, 'password': password}).status_code == 200
    second_token = second.cookies.get('atlas_session')
    assert first_token != second_token

    config = {
        'provider': 'deepseek', 'model': 'deepseek-chat',
        'api_key': 'test-secret-not-real', 'consent': True,
    }
    assert first.put('/api/v1/ai-settings', json=config).status_code == 200
    assert second.put('/api/v1/ai-settings', json=config).status_code == 200
    assert len(cloud_ai._sessions) == 2

    assert first.post('/api/logout').status_code == 200
    assert len(cloud_ai._sessions) == 1
    replay = TestClient(app)
    replay.cookies.set('atlas_session', first_token)
    assert replay.get('/api/ledger').status_code == 401

    JournalStore(router.store.path)
    assert replay.get('/api/ledger').status_code == 401
    assert second.get('/api/ledger').status_code == 200
    assert second.get('/api/v1/ai-settings').json()['configured'] is True

    second.post('/api/logout')
    first.close()
    second.close()
    replay.close()
    cloud_ai._sessions.clear()


def test_session_ids_are_hashed_and_legacy_tokens_without_sid_are_rejected():
    router._attempts.clear()
    client = TestClient(app)
    response = client.post('/api/register', json={
        'email': f'{uuid4()}@example.test', 'password': 'session-hash-password',
    })
    assert response.status_code == 201
    token = client.cookies.get('atlas_session')
    payload, _signature = token.split('.')
    session = json.loads(auth._unb64(payload))
    raw_session_id = session['sessionId']
    expected_hash = hashlib.sha256(raw_session_id.encode()).hexdigest()
    with sqlite3.connect(router.store.path) as connection:
        row = connection.execute(
            'SELECT sid_hash,expires_at FROM sessions WHERE sid_hash=?', (expected_hash,)
        ).fetchone()
    assert row is not None and row[0] == expected_hash
    assert row[0] != raw_session_id

    del session['sessionId']
    legacy_payload = auth._b64(json.dumps(session, separators=(',', ':')).encode())
    legacy_signature = auth._b64(
        hmac.new(auth.SESSION_SECRET.encode(), legacy_payload.encode(), hashlib.sha256).digest()
    )
    client.cookies.set('atlas_session', f'{legacy_payload}.{legacy_signature}')
    assert client.get('/api/ledger').status_code == 401
    client.close()


def test_forwarded_proto_cannot_override_explicit_cookie_security(monkeypatch):
    monkeypatch.setattr(router, 'COOKIE_SECURE', True)
    router._attempts.clear()
    client = TestClient(app)
    response = client.post('/api/register', headers={'X-Forwarded-Proto': 'http'}, json={
        'email': f'{uuid4()}@example.test', 'password': 'cookie-test-password',
    })
    assert response.status_code == 201
    assert 'Secure' in response.headers['set-cookie']
    client.close()
