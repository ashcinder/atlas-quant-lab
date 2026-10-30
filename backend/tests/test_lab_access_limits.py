from threading import Event
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.journal import router as journal
from app.work_limits import WorkLimits, expensive_request


@pytest.fixture(autouse=True)
def isolated_work_budget(monkeypatch):
    # Other integration tests may still be completing background research.
    # Keep this test's admission budget independent without clearing live leases.
    import app.main as main
    import app.work_limits as module
    budget = WorkLimits()
    monkeypatch.setattr(module, 'work_limits', budget)
    monkeypatch.setattr(main, 'work_limits', budget)


def test_same_nat_other_account_can_login_and_headers_do_not_reset_limit():
    journal._attempts.clear()
    app = FastAPI()
    app.include_router(journal.router)
    client = TestClient(app)
    first, second = f'{uuid4()}@example.test', f'{uuid4()}@example.test'
    for email in (first, second):
        assert client.post('/api/register', json={'email': email, 'password': 'lab-test-password'}).status_code == 201
    for _ in range(5):
        assert client.post('/api/login', json={'email': first, 'password': 'incorrect-password'}).status_code == 401
    assert client.post('/api/login', headers={'X-Forwarded-For': '192.0.2.99'}, json={
        'email': first.upper(), 'password': 'lab-test-password',
    }).status_code == 429
    assert client.post('/api/login', json={'email': second, 'password': 'lab-test-password'}).status_code == 200
    journal._attempts.clear()


def test_shared_budget_rejects_duplicate_and_third_owner_then_releases():
    limits = WorkLimits()
    limits.acquire('first')
    with pytest.raises(HTTPException) as duplicate:
        limits.acquire('first')
    assert duplicate.value.status_code == 429
    limits.acquire('second')
    with pytest.raises(HTTPException) as full:
        limits.acquire('third')
    assert full.value.status_code == 429
    limits.release('first')
    limits.acquire('third')
    limits.release('second')
    limits.release('third')


def test_asgi_trusts_forwarded_identity_only_from_allowlisted_proxy():
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    async def identify(scope, receive, send):
        request = Request(scope)
        response = JSONResponse({'host': request.client.host, 'scheme': request.url.scheme})
        await response(scope, receive, send)

    app = ProxyHeadersMiddleware(identify, trusted_hosts=['172.30.120.3'])
    headers = {'X-Forwarded-For': '192.0.2.15', 'X-Forwarded-Proto': 'https'}
    trusted = TestClient(app, client=('172.30.120.3', 1234))
    untrusted = TestClient(app, client=('172.30.120.5', 1234))
    assert trusted.get('/', headers=headers).json() == {'host': '192.0.2.15', 'scheme': 'https'}
    assert untrusted.get('/', headers=headers).json() == {'host': '172.30.120.5', 'scheme': 'http'}
    trusted.close()
    untrusted.close()


def test_background_research_keeps_lease_until_failure(tmp_path):
    from app.research import ResearchService
    from app.models import ResearchRequest, ResearchExperiment
    from app.work_limits import work_limits

    entered, release = Event(), Event()

    class FailingData:
        def fetch(self, *args):
            entered.set()
            assert release.wait(5)
            raise ValueError('isolated failure')

    service = ResearchService(FailingData(), tmp_path / 'jobs.sqlite3')
    request = ResearchRequest(symbol='BTC-USD', asset_class='crypto', experiments=[ResearchExperiment(strategy_id='sma_cross')])
    owner = uuid4().hex
    try:
        job = service.submit(owner, request)
        assert entered.wait(5)
        with pytest.raises(HTTPException) as busy:
            work_limits.acquire(owner)
        assert busy.value.status_code == 429
    finally:
        release.set()
        service.executor.shutdown(wait=True)
    assert service.get(owner, job.id).status == 'failed'
    work_limits.acquire(owner)
    work_limits.release(owner)


def test_api_budget_is_shared_across_accounts_and_freed_after_exception(monkeypatch):
    from app.main import app, data_service
    from app.work_limits import work_limits
    from threading import Lock

    clients = [TestClient(app) for _ in range(3)]
    users = []
    for client in clients:
        email = f'{uuid4()}@example.test'
        users.append(journal.store.create_user(email, 'lab-test-password'))
        assert client.post('/api/login', json={'email': email, 'password': 'lab-test-password'}).status_code == 200
    entered, release = Event(), Event()
    lock, count = Lock(), [0]

    def blocked_fetch(*args, **kwargs):
        with lock:
            count[0] += 1
            if count[0] == 2:
                entered.set()
        assert release.wait(5)
        raise ValueError('disposable test error')

    monkeypatch.setattr(data_service, 'fetch', blocked_fetch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(client.post, '/api/v1/backtests', json={}) for client in clients[:2]]
        try:
            assert entered.wait(5)
            assert clients[2].post('/api/v1/backtests', json={}).status_code == 429
            assert clients[0].post('/api/v1/ai-settings/test').status_code == 429
            assert clients[2].get('/api/v1/health').status_code == 200
        finally:
            release.set()
        assert [future.result().status_code for future in futures] == [422, 422]
    for user, client in zip(users, clients):
        work_limits.acquire(user.id)
        work_limits.release(user.id)
        client.close()


@pytest.mark.parametrize('method,path', [
    ('POST', '/api/v1/backtests'), ('POST', '/api/v1/strategy-code/assist'),
    ('GET', '/api/v1/quantjudge/zk-proofs/id/bundle'),
    ('POST', '/api/v1/quantjudge/zk-proofs/id/verify'),
])
def test_expensive_routes_share_budget(method, path):
    assert expensive_request(method, path)
    assert not expensive_request('GET', '/api/v1/health')
