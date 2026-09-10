import base64
import hashlib
import hmac
import json
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import trading_api
from app.main import app
from app.trading import Exchange, OrderInput


@pytest.fixture(scope="module")
def logged_client():
    with TestClient(app) as client:
        result = client.post(
            "/api/register", json={"email": f"{uuid4()}@example.test", "password": "password-12345"}
        )
        assert result.status_code == 201
        yield client


@pytest.fixture
def client(logged_client, monkeypatch, tmp_path):
    monkeypatch.setattr(trading_api, "DB_PATH", tmp_path / "trades.db")
    user = logged_client.get("/api/v1/trading/capabilities").json()["user_id"]
    monkeypatch.setenv("ATLAS_TRADING_OWNER_ID", user)
    monkeypatch.setenv("ATLAS_TRADING_ENABLED", "1")
    monkeypatch.setenv("ATLAS_TRADING_LIVE_ENABLED", "0")
    monkeypatch.setenv("ATLAS_TRADING_MAX_ORDER_USDT", "100")
    for venue in ["BINANCE", "OKX"]:
        monkeypatch.setenv(f"ATLAS_{venue}_MODE", "demo")
        monkeypatch.setenv(f"ATLAS_{venue}_API_KEY", "test-key")
        monkeypatch.setenv(f"ATLAS_{venue}_API_SECRET", "test-secret")
    monkeypatch.setenv("ATLAS_OKX_PASSPHRASE", "test-passphrase")
    return logged_client


def payload(**changes):
    return {
        "venue": "binance",
        "symbol": "BTC-USDT",
        "side": "buy",
        "quantity": "0.001",
        "price": "10000",
        **changes,
    }


def test_owner_and_origin_are_enforced(client, monkeypatch):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/trading/orders").status_code == 401
    assert (
        client.post(
            "/api/v1/trading/orders/preview",
            json=payload(),
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    monkeypatch.setenv("ATLAS_TRADING_OWNER_ID", "another-user")
    for path in ["/orders", "/binance/account"]:
        assert client.get("/api/v1/trading" + path).status_code == 403
    assert client.post("/api/v1/trading/orders/preview", json=payload()).status_code == 403
    assert not client.get("/api/v1/trading/capabilities").json()["authorized"]


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": "-1"},
        {"price": "NaN"},
        {"symbol": "BTC-USDT-SWAP"},
        {"quantity": "Infinity"},
        {"price": "0"},
        {"quantity": "1"},
    ],
)
def test_input_and_notional_limits(client, change):
    assert client.post("/api/v1/trading/orders/preview", json=payload(**change)).status_code == 422


def test_demo_preview_confirm_replay_and_refresh(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        Exchange,
        "place",
        lambda self, order, identifier: calls.append(identifier) or {"exchange_status": "NEW"},
    )
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    assert not calls
    identifier = preview["id"]
    path = "/api/v1/trading/orders/" + identifier
    assert client.post(path + "/confirm", json={"confirmation": "yes"}).status_code == 422
    for _ in range(2):
        response = client.post(path + "/confirm", json={"confirmation": "确认模拟下单"})
        assert response.json()["state"] == "submitted"
    assert calls == [identifier]
    monkeypatch.setattr(
        Exchange,
        "lookup",
        lambda *args, **kwargs: {"exchange_status": "FILLED", "filled_quantity": "0.001"},
    )
    assert client.post(path + "/refresh", json={}).json()["result"]["exchange_status"] == "FILLED"


def test_unknown_submission_never_retries(client, monkeypatch):
    calls = []

    def fail(*args):
        calls.append(1)
        raise HTTPException(502, "sensitive upstream error")

    monkeypatch.setattr(Exchange, "place", fail)
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    for _ in range(2):
        result = client.post(
            f"/api/v1/trading/orders/{preview['id']}/confirm", json={"confirmation": "确认模拟下单"}
        )
        assert result.json()["state"] == "unknown"
        assert "sensitive" not in result.text
    assert len(calls) == 1


def test_live_switch_expiration_and_account_change(client, monkeypatch):
    monkeypatch.setenv("ATLAS_BINANCE_MODE", "live")
    assert client.post("/api/v1/trading/orders/preview", json=payload()).status_code == 403
    monkeypatch.setenv("ATLAS_TRADING_LIVE_ENABLED", "1")
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    path = f"/api/v1/trading/orders/{preview['id']}/confirm"
    assert client.post(path, json={"confirmation": "确认模拟下单"}).status_code == 422
    monkeypatch.setenv("ATLAS_BINANCE_API_KEY", "changed")
    assert client.post(path, json={"confirmation": "确认实盘下单"}).status_code == 409
    monkeypatch.setenv("ATLAS_BINANCE_API_KEY", "test-key")
    with trading_api.database() as db:
        db.execute("UPDATE manual_trade_orders SET expires=0")
    assert client.post(path, json={"confirmation": "确认实盘下单"}).status_code == 409


def test_order_ownership(client, monkeypatch):
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    with trading_api.database() as db:
        db.execute("UPDATE manual_trade_orders SET owner='other'")
    assert client.get("/api/v1/trading/orders").json() == []
    assert (
        client.post(
            f"/api/v1/trading/orders/{preview['id']}/confirm", json={"confirmation": "确认模拟下单"}
        ).status_code
        == 404
    )


def test_binance_signature_and_no_secret_leak(monkeypatch):
    monkeypatch.setenv("ATLAS_BINANCE_API_KEY", "key")
    monkeypatch.setenv("ATLAS_BINANCE_API_SECRET", "secret")
    monkeypatch.setenv("ATLAS_BINANCE_MODE", "demo")
    original = httpx.Client

    def handler(request):
        assert request.url.host == "testnet.binance.vision"
        query, signature = request.url.query.decode().rsplit("&signature=", 1)
        assert signature == hmac.new(b"secret", query.encode(), hashlib.sha256).hexdigest()
        assert request.headers["X-MBX-APIKEY"] == "key"
        assert "newClientOrderId=aq123" in query
        return httpx.Response(200, json={"orderId": 1, "status": "NEW", "secret": "hidden"})

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    result = Exchange("binance").place(OrderInput(**payload()), "aq123")
    assert result["exchange_order_id"] == "1"
    assert "secret" not in result


def test_okx_signature_and_business_rejection(monkeypatch):
    monkeypatch.setenv("ATLAS_OKX_API_KEY", "key")
    monkeypatch.setenv("ATLAS_OKX_API_SECRET", "secret")
    monkeypatch.setenv("ATLAS_OKX_PASSPHRASE", "pass")
    monkeypatch.setenv("ATLAS_OKX_MODE", "demo")
    original = httpx.Client

    def handler(request):
        assert request.headers["x-simulated-trading"] == "1"
        text = request.headers["OK-ACCESS-TIMESTAMP"] + request.method
        text += request.url.raw_path.decode() + request.content.decode()
        expected = base64.b64encode(hmac.new(b"secret", text.encode(), hashlib.sha256).digest())
        assert request.headers["OK-ACCESS-SIGN"] == expected.decode()
        data = json.loads(request.content)
        assert data["tdMode"] == "cash" and data["ordType"] == "limit"
        return httpx.Response(
            200, json={"code": "0", "data": [{"sCode": "51008", "sMsg": "secret"}]}
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    with pytest.raises(HTTPException) as result:
        Exchange("okx").place(OrderInput(**payload(venue="okx")), "aq123")
    assert "secret" not in str(result.value.detail)


def test_decimal_precision():
    order = OrderInput(**payload(quantity="0.00000001", price="1.00000001"))
    assert order.quantity * order.price == Decimal("0.0000000100000001")


def test_late_submit_does_not_overwrite_cancellation(client, monkeypatch):
    def place(self, order, identifier):
        with trading_api.database() as db:
            db.execute(
                "UPDATE manual_trade_orders SET state='cancel_requested',result=? WHERE id=?",
                (json.dumps({"exchange_status": "CANCELED"}), identifier),
            )
        return {"exchange_status": "NEW"}

    monkeypatch.setattr(Exchange, "place", place)
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    result = client.post(
        f"/api/v1/trading/orders/{preview['id']}/confirm", json={"confirmation": "确认模拟下单"}
    ).json()
    assert result["state"] == "cancel_requested"
    assert result["result"]["exchange_status"] == "CANCELED"


def test_definitive_rejection_is_not_unknown(client, monkeypatch):
    from app.trading import ExchangeRejected

    def reject(*args):
        raise ExchangeRejected()

    monkeypatch.setattr(Exchange, "place", reject)
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    path = f"/api/v1/trading/orders/{preview['id']}"
    assert (
        client.post(path + "/confirm", json={"confirmation": "确认模拟下单"}).json()["state"]
        == "rejected"
    )
    assert client.post(path + "/refresh", json={}).json()["state"] == "rejected"


def test_cancel_intent_persisted_and_available_with_new_orders_disabled(client, monkeypatch):
    monkeypatch.setattr(Exchange, "place", lambda *args: {"exchange_status": "NEW"})
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    path = f"/api/v1/trading/orders/{preview['id']}"
    client.post(path + "/confirm", json={"confirmation": "确认模拟下单"})
    monkeypatch.setenv("ATLAS_TRADING_ENABLED", "0")

    def timeout(self, symbol, identifier, cancel=False):
        with trading_api.database() as db:
            row = db.execute(
                "SELECT state FROM manual_trade_orders WHERE id=?", (identifier,)
            ).fetchone()
            assert row["state"] == "cancel_submitting"
        assert cancel
        raise HTTPException(502, "timeout")

    monkeypatch.setattr(Exchange, "lookup", timeout)
    result = client.post(path + "/cancel", json={"confirmation": "确认撤单"}).json()
    assert result["state"] == "cancel_unknown"
    assert client.get("/api/v1/trading/orders").json()[0]["state"] == "cancel_unknown"


def test_concurrent_confirmation_sends_once(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    calls = []

    def slow(self, order, identifier):
        calls.append(identifier)
        entered.set()
        assert release.wait(5)
        return {"exchange_status": "NEW"}

    monkeypatch.setattr(Exchange, "place", slow)
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    path = f"/api/v1/trading/orders/{preview['id']}/confirm"
    with ThreadPoolExecutor() as pool:
        first = pool.submit(client.post, path, json={"confirmation": "确认模拟下单"})
        assert entered.wait(5)
        try:
            replay = client.post(path, json={"confirmation": "确认模拟下单"})
            assert replay.json()["state"] == "submitting"
            cancel = client.post(
                path.removesuffix("/confirm") + "/cancel", json={"confirmation": "确认撤单"}
            )
            assert cancel.status_code == 409
        finally:
            release.set()
        assert first.result().json()["state"] == "submitted"
    assert len(calls) == 1


def test_terminal_orders_cannot_cancel_and_partial_fills_survive_cancel_timeout(
    client, monkeypatch
):
    monkeypatch.setattr(Exchange, "place", lambda *args: {"exchange_status": "NEW"})
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    path = f"/api/v1/trading/orders/{preview['id']}"
    client.post(path + "/confirm", json={"confirmation": "确认模拟下单"})
    with trading_api.database() as db:
        db.execute(
            "UPDATE manual_trade_orders SET result=?",
            (json.dumps({"exchange_status": "FILLED", "filled_quantity": "0.001"}),),
        )
    assert client.post(path + "/cancel", json={"confirmation": "确认撤单"}).status_code == 409
    with trading_api.database() as db:
        db.execute(
            "UPDATE manual_trade_orders SET result=?",
            (json.dumps({"exchange_status": "PARTIALLY_FILLED", "filled_quantity": "0.0005"}),),
        )

    def timeout(*args, **kwargs):
        raise HTTPException(502, "timeout")

    monkeypatch.setattr(Exchange, "lookup", timeout)
    result = client.post(path + "/cancel", json={"confirmation": "确认撤单"}).json()
    assert result["state"] == "cancel_unknown"
    assert result["result"]["filled_quantity"] == "0.0005"
    assert result["result"]["exchange_status"] == "PARTIALLY_FILLED"


@pytest.mark.parametrize(
    "status,code,rejected", [(400, -1021, True), (400, -1007, False), (500, -2010, False)]
)
def test_binance_definitive_and_uncertain_errors(monkeypatch, status, code, rejected):
    from app.trading import ExchangeRejected

    monkeypatch.setenv("ATLAS_BINANCE_API_KEY", "key")
    monkeypatch.setenv("ATLAS_BINANCE_API_SECRET", "secret")
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda req: httpx.Response(status, json={"code": code})),
            **kwargs,
        ),
    )
    with pytest.raises(HTTPException) as error:
        Exchange("binance").place(OrderInput(**payload()), "aq123")
    assert isinstance(error.value, ExchangeRejected) == rejected


def test_refresh_waits_for_active_cancel_but_recovers_expired_lease(client, monkeypatch):
    monkeypatch.setattr(Exchange, "place", lambda *args: {"exchange_status": "NEW"})
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    path = f"/api/v1/trading/orders/{preview['id']}"
    client.post(path + "/confirm", json={"confirmation": "确认模拟下单"})
    import time

    with trading_api.database() as db:
        db.execute(
            "UPDATE manual_trade_orders SET state='cancel_submitting',expires=?",
            (time.time() + 60,),
        )
    calls = []
    monkeypatch.setattr(
        Exchange,
        "lookup",
        lambda *args, **kwargs: calls.append(1) or {"exchange_status": "CANCELED"},
    )
    assert client.post(path + "/refresh", json={}).json()["state"] == "cancel_submitting"
    assert not calls
    with trading_api.database() as db:
        db.execute("UPDATE manual_trade_orders SET expires=0")
    result = client.post(path + "/refresh", json={}).json()
    assert result["state"] == "reconciled"
    assert result["result"]["exchange_status"] == "CANCELED"
    assert len(calls) == 1
