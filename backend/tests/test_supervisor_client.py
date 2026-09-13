import httpx
from app.supervisor_client import SupervisorClient


def test_loopback_rpc_bypasses_environment_proxy(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['trust_env'])
        return httpx.Response(200, json={'result': '0x41b'}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', post)
    assert SupervisorClient().status().connected
    SupervisorClient('https://example.com').status()
    assert calls == [False, False, True, True]
