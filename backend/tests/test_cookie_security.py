"""Cookie regression tests use disposable users and never trust forwarded headers."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.journal import router
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
