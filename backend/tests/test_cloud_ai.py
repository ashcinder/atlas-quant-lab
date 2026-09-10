from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cloud_ai

@pytest.fixture
def client():
    cloud_ai._sessions.clear()
    app = FastAPI()
    @app.middleware("http")
    async def user(request, call_next):
        request.state.user = SimpleNamespace(id="user-a")
        return await call_next(request)
    app.include_router(cloud_ai.router)
    with TestClient(app) as client:
        client.cookies.set("atlas_session", "session-one")
        yield client
    cloud_ai._sessions.clear()

def save(client):
    return client.put('/api/v1/ai-settings', json={"provider":"deepseek", "model":"deepseek-chat", "api_key":"test-secret-not-real", "consent":True})

def test_secret_never_returned_and_sessions_isolated(client):
    assert save(client).status_code == 200
    response = client.get('/api/v1/ai-settings')
    assert response.json()['configured'] is True
    assert 'test-secret' not in response.text
    client.cookies.set('atlas_session', 'session-two')
    assert client.get('/api/v1/ai-settings').json()['configured'] is False

def test_requires_session_consent_and_allowlisted_provider(client):
    client.cookies.clear()
    assert save(client).status_code == 401
    client.cookies.set('atlas_session','session-one')
    assert client.put('/api/v1/ai-settings', json={"provider":"arbitrary-url", "model":"x", "api_key":"test-secret", "consent":True}).status_code == 422
    assert client.put('/api/v1/ai-settings', json={"provider":"deepseek", "model":"x", "api_key":"test-secret", "consent":False}).status_code == 422

def test_clear_and_expiry(client, monkeypatch):
    assert save(client).status_code == 200
    assert client.delete('/api/v1/ai-settings').status_code == 200
    assert client.get('/api/v1/ai-settings').json()['configured'] is False
    assert save(client).status_code == 200
    future = cloud_ai.monotonic() + 8 * 3600 + 1
    monkeypatch.setattr(cloud_ai, 'monotonic', lambda: future)
    assert client.get('/api/v1/ai-settings').json()['configured'] is False

def test_connection_validates_json(client, monkeypatch):
    save(client)
    monkeypatch.setattr(cloud_ai, 'complete', lambda *args, **kwargs: '{"ok":true}')
    assert client.post('/api/v1/ai-settings/test').json()['connected'] is True
    monkeypatch.setattr(cloud_ai, 'complete', lambda *args, **kwargs: 'broken')
    assert client.post('/api/v1/ai-settings/test').status_code == 502

def test_cloud_guard_is_bounded_and_fail_closed(monkeypatch):
    import json
    config = cloud_ai.CloudConfig(provider='deepseek', model='deepseek-chat', api_key='fake-key-for-tests', consent=True)
    def response(config, messages, **kwargs):
        incoming = json.loads(messages[-1]['content'])
        return json.dumps({'request_id':incoming['request_id'], 'action':'reduce', 'scale':0.5})
    monkeypatch.setattr(cloud_ai, 'complete', response)
    guard = cloud_ai.CloudGuard(config)
    weight, receipt = guard.review({}, .8, 'reduce_only')
    assert weight == .4
    assert receipt['status'] == 'inference_completed'
    assert guard.review({}, .8, 'advisory')[0] == .8
    monkeypatch.setattr(cloud_ai, 'complete', lambda *a, **k: '{"action":"approve","scale":8}')
    assert guard.review({}, .8, 'reduce_only')[1]['status'] == 'failed_closed'

def test_cloud_transport_uses_fixed_endpoint_and_redacts_failures(monkeypatch):
    import httpx
    config = cloud_ai.CloudConfig(provider='deepseek', model='deepseek-chat', api_key='fake-key-for-tests', consent=True)
    original = httpx.Client
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(401, text='sensitive provider response')
    monkeypatch.setattr(cloud_ai.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(cloud_ai.HTTPException) as failure:
        cloud_ai.complete(config, [])
    assert seen == ['https://api.deepseek.com/chat/completions']
    assert 'sensitive' not in failure.value.detail
    assert 'fake-key' not in failure.value.detail
