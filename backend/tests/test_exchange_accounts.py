from types import SimpleNamespace
import asyncio
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import exchange_accounts as accounts


@pytest.fixture
def client():
    accounts._sessions.clear()
    accounts._last_read.clear()
    app = FastAPI()
    @app.middleware('http')
    async def identify(request, call_next):
        request.state.user = SimpleNamespace(id='test-user')
        return await call_next(request)
    app.include_router(accounts.router)
    with TestClient(app) as c:
        c.cookies.set('atlas_session','one')
        yield c


def test_session_isolation_and_disconnect(client):
    r = client.put('/api/v1/exchange-account', json={'exchange':'binance','api_key':'test-key','secret':'test-secret','consent':True})
    assert r.status_code == 200 and r.json()['can_trade'] is False
    assert 'test-secret' not in client.get('/api/v1/exchange-account').text
    client.cookies.set('atlas_session','two')
    assert client.get('/api/v1/exchange-account').json()['configured'] is False
    client.cookies.set('atlas_session','one')
    client.delete('/api/v1/exchange-account')
    assert client.get('/api/v1/exchange-account').json()['configured'] is False


def test_okx_requires_passphrase():
    with pytest.raises(ValueError):
        accounts.Connection(exchange='okx',api_key='a',secret='b',consent=True)


def test_balance_filters_raw_data_and_closes_client(monkeypatch):
    closed = []
    class Exchange:
        async def fetch_balance(self, params):
            return {'info': {'apiKey':'never-return-this'}, 'total':{'BTC':1,'USD':0},'free':{'BTC':.5},'used':{'BTC':.5}}
        async def close(self): closed.append(True)
    monkeypatch.setattr(accounts,'create_client',lambda c:Exchange())
    result = asyncio.run(accounts.read_balance(accounts.Connection(exchange='binance',api_key='a',secret='b',consent=True)))
    assert result['assets'] == [{'currency':'BTC','total':'1','free':'0.5','used':'0.5'}]
    assert 'never-return' not in str(result) and closed


def test_failed_exchange_does_not_leak_secret(monkeypatch):
    class Exchange:
        async def fetch_balance(self, params): raise RuntimeError('signed-secret-url')
        async def close(self): pass
    monkeypatch.setattr(accounts,'create_client',lambda c:Exchange())
    with pytest.raises(HTTPException) as error:
        asyncio.run(accounts.read_balance(accounts.Connection(exchange='binance',api_key='a',secret='b',consent=True)))
    assert error.value.status_code == 502 and 'signed-secret' not in error.value.detail
