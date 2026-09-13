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
from app.strategy_runtime import ReleaseCreate, RunCreate, StrategyRuntimeStore
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
    monkeypatch.setattr(Exchange, "spot_prices", lambda self: {})
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


def linked_suggestion(client, suffix="2", suggested_quantity="0.001", venue="binance"):
    user = client.get("/api/v1/trading/capabilities").json()["user_id"]
    store = StrategyRuntimeStore(None, trading_api.DB_PATH)
    account = next(
        item
        for item in store.list_accounts(user)
        if item["environment"] == "exchange_test" and item["name"].lower().startswith(venue)
    )
    release = store.create_release(
        user,
        ReleaseCreate(
            name="预留规则",
            source_kind="builtin",
            strategy_id="momentum",
            params={"lookback": 10, "smoothing": 2, "threshold": 0, "exit_threshold": -0.1},
            markets=["CRYPTO"],
        ),
    )
    run = store.create_run(
        user,
        RunCreate(
            release_id=release["id"],
            account_id=account["id"],
            market="CRYPTO",
            environment="exchange_test",
            symbol="BTC-USDT",
            initial_cash="10000",
        ),
    )
    signal_id = "sig_" + suffix * 18
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO strategy_signals
               (id,owner_id,run_id,bar_time,target,reason,status,created_at,side,quantity,reference_price)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal_id,
                user,
                run["id"],
                1,
                "0.5",
                "规则买入",
                "recommendation",
                "now",
                "buy",
                suggested_quantity,
                "10000",
            ),
        )
    store.set_status(user, run["id"], "start")
    return store, user, run, signal_id


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


def test_strategy_partial_fill_survives_cancellation_and_syncs_to_ledger(client, monkeypatch):
    user = client.get("/api/v1/trading/capabilities").json()["user_id"]
    store = StrategyRuntimeStore(None, trading_api.DB_PATH)
    account = next(
        item
        for item in store.list_accounts(user)
        if item["environment"] == "exchange_test" and item["name"].lower().startswith("binance")
    )
    release = store.create_release(
        user,
        ReleaseCreate(
            name="联调规则",
            source_kind="builtin",
            strategy_id="momentum",
            params={"lookback": 10, "smoothing": 2, "threshold": 0, "exit_threshold": -0.1},
            markets=["CRYPTO"],
        ),
    )
    run = store.create_run(
        user,
        RunCreate(
            release_id=release["id"],
            account_id=account["id"],
            market="CRYPTO",
            environment="exchange_test",
            symbol="BTC-USDT",
            initial_cash="10000",
        ),
    )
    signal_id = "sig_" + "1" * 18
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO strategy_signals
               (id,owner_id,run_id,bar_time,target,reason,status,created_at,side,quantity,reference_price)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal_id,
                user,
                run["id"],
                1,
                "0.5",
                "规则买入",
                "recommendation",
                "now",
                "buy",
                "0.001",
                "10000",
            ),
        )
    store.set_status(user, run["id"], "start")
    monkeypatch.setattr(
        Exchange, "account", lambda self: [{"asset": "USDT", "available": "100", "locked": "0"}]
    )
    monkeypatch.setattr(Exchange, "validate_order", lambda self, order: Decimal("10020"))
    linked = payload(strategy_run_id=run["id"], strategy_signal_id=signal_id)
    preview = client.post("/api/v1/trading/orders/preview", json=linked)
    assert preview.status_code == 200
    identifier = preview.json()["id"]
    monkeypatch.setattr(
        Exchange,
        "place",
        lambda *_args: {
            "exchange_order_id": "77",
            "exchange_status": "NEW",
            "filled_quantity": "0",
        },
    )
    monkeypatch.setattr(Exchange, "fills", lambda *_args: [])
    client.post(
        f"/api/v1/trading/orders/{identifier}/confirm",
        json={"confirmation": "确认模拟下单"},
    )
    monkeypatch.setattr(
        Exchange,
        "lookup",
        lambda *_args, **_kwargs: {
            "exchange_order_id": "77",
            "exchange_status": "CANCELED",
            "filled_quantity": "0.0005",
        },
    )
    monkeypatch.setattr(
        Exchange,
        "fills",
        lambda *_args: [
            {
                "trade_id": "trade-1",
                "price": "10000",
                "quantity": "0.0005",
                "fee": "0.005",
                "fee_currency": "USDT",
                "executed_at": "2026-09-10T00:00:00+00:00",
            }
        ],
    )
    refreshed = client.post(f"/api/v1/trading/orders/{identifier}/refresh", json={})
    assert refreshed.status_code == 200
    ledger = store.ledger(user, None, None, run["id"], None, None, None, None, 50, 0)
    assert ledger["fills"][0]["external_trade_id"] == "trade-1"
    assert ledger["fills"][0]["order_id"] == identifier

    with store._connect() as connection:
        signal = connection.execute(
            "SELECT status FROM strategy_signals WHERE id=?", (signal_id,)
        ).fetchone()
        reservation = connection.execute(
            "SELECT amount FROM strategy_order_reservations WHERE order_id=?", (identifier,)
        ).fetchone()
    assert signal["status"] == "partially_filled"
    assert reservation["amount"] == "0"


def test_strategy_preview_reserves_splits_atomically_and_rejects_stopped_run(client, monkeypatch):
    store, _user, run, signal_id = linked_suggestion(client)
    monkeypatch.setattr(
        Exchange, "account", lambda self: [{"asset": "USDT", "available": "100", "locked": "0"}]
    )
    monkeypatch.setattr(Exchange, "validate_order", lambda self, order: Decimal("10000"))
    link = {"strategy_run_id": run["id"], "strategy_signal_id": signal_id}
    first = client.post("/api/v1/trading/orders/preview", json=payload(quantity="0.0006", **link))
    assert first.status_code == 200
    over = client.post("/api/v1/trading/orders/preview", json=payload(quantity="0.0005", **link))
    assert over.status_code == 422
    with trading_api.database() as connection:
        connection.execute(
            "UPDATE manual_trade_orders SET expires=0 WHERE id=?", (first.json()["id"],)
        )
    replacement = client.post(
        "/api/v1/trading/orders/preview", json=payload(quantity="0.0005", **link)
    )
    assert replacement.status_code == 200
    store.set_status(_user, run["id"], "stop")
    stopped = client.post("/api/v1/trading/orders/preview", json=payload(quantity="0.0001", **link))
    assert stopped.status_code == 409
    with trading_api.database() as connection:
        expired = connection.execute(
            "SELECT state FROM manual_trade_orders WHERE id=?", (first.json()["id"],)
        ).fetchone()
    assert expired["state"] == "preview_expired"


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


def test_split_suggestion_can_finish_in_multiple_orders(client, monkeypatch):
    store, user, run, signal_id = linked_suggestion(client, suggested_quantity="0.002")
    monkeypatch.setattr(
        Exchange, "account", lambda self: [{"asset": "USDT", "available": "100", "locked": "0"}]
    )
    monkeypatch.setattr(Exchange, "validate_order", lambda self, order: Decimal("10000"))
    current_fill = []
    monkeypatch.setattr(Exchange, "fills", lambda *args: list(current_fill))
    monkeypatch.setattr(
        Exchange,
        "place",
        lambda *args: {
            "exchange_order_id": "77",
            "exchange_status": "FILLED",
            "filled_quantity": "0.001",
        },
    )
    for index in range(2):
        preview = client.post(
            "/api/v1/trading/orders/preview",
            json=payload(strategy_run_id=run["id"], strategy_signal_id=signal_id),
        )
        assert preview.status_code == 200, preview.text
        current_fill[:] = [
            {
                "trade_id": f"split-{index}",
                "quantity": "0.001",
                "price": "10000",
                "fee": "0",
                "fee_currency": "USDT",
                "executed_at": "2026-09-10T00:00:00Z",
            }
        ]
        confirmed = client.post(
            f"/api/v1/trading/orders/{preview.json()['id']}/confirm",
            json={"confirmation": "确认模拟下单"},
        )
        assert confirmed.status_code == 200
    result = store.get_run(user, run["id"], True)
    assert Decimal(result["quantity"]) == Decimal("0.002")
    assert result["signals"][0]["status"] == "filled"


def test_concurrent_previews_only_reserve_suggestion_once(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    _store, _user, run, signal_id = linked_suggestion(client)
    monkeypatch.setattr(
        Exchange, "account", lambda self: [{"asset": "USDT", "available": "100", "locked": "0"}]
    )

    def remote_check(self, order):
        # An unrelated writer must be able to acquire the database during remote validation.
        with trading_api.database() as connection:
            connection.execute("BEGIN IMMEDIATE")
        return Decimal("10000")

    monkeypatch.setattr(Exchange, "validate_order", remote_check)
    linked = payload(strategy_run_id=run["id"], strategy_signal_id=signal_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: client.post("/api/v1/trading/orders/preview", json=linked), range(2))
        )
    assert sorted(response.status_code for response in responses) == [200, 422]


def test_background_sync_retries_failed_fill_fetch_and_books_cancelled_partial(client, monkeypatch):
    store, user, run, signal_id = linked_suggestion(client)
    monkeypatch.setattr(
        Exchange, "account", lambda self: [{"asset": "USDT", "available": "100", "locked": "0"}]
    )
    monkeypatch.setattr(Exchange, "validate_order", lambda self, order: Decimal("10000"))
    preview = client.post(
        "/api/v1/trading/orders/preview",
        json=payload(strategy_run_id=run["id"], strategy_signal_id=signal_id),
    ).json()
    with trading_api.database() as connection:
        connection.execute(
            "UPDATE manual_trade_orders SET state='unknown' WHERE id=?", (preview["id"],)
        )
    monkeypatch.setattr(
        Exchange,
        "lookup",
        lambda *args, **kwargs: {
            "exchange_order_id": "77",
            "exchange_status": "CANCELED",
            "filled_quantity": "0.0005",
        },
    )

    def unavailable(*args):
        raise HTTPException(502, "temporary")

    monkeypatch.setattr(Exchange, "fills", unavailable)
    scheduler = trading_api.ManualTradeSyncScheduler()
    scheduler._run_once()
    with trading_api.database() as connection:
        row = trading_api.get_order(connection, preview["id"], user)
        assert not json.loads(row["result"]).get("strategy_sync_complete")
        assert (
            Decimal(
                connection.execute(
                    "SELECT amount FROM strategy_order_reservations WHERE order_id=?",
                    (preview["id"],),
                ).fetchone()[0]
            )
            > 0
        )
    monkeypatch.setattr(
        Exchange,
        "fills",
        lambda *args: [
            {
                "trade_id": "background-1",
                "quantity": "0.0005",
                "price": "10000",
                "fee": "0",
                "fee_currency": "USDT",
                "executed_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    scheduler._run_once()
    scheduler._run_once()
    assert Decimal(store.get_run(user, run["id"])["quantity"]) == Decimal("0.0005")
    with trading_api.database() as connection:
        row = trading_api.get_order(connection, preview["id"], user)
        assert json.loads(row["result"])["strategy_sync_complete"]
        assert connection.execute("SELECT COUNT(*) FROM strategy_external_fills").fetchone()[0] == 1


@pytest.mark.parametrize("venue,page_size", [("binance", 1000), ("okx", 100)])
def test_fill_sync_pages_the_whole_order(monkeypatch, venue, page_size):
    calls = []

    def fetch(_self, method, path, params, many=False):
        calls.append((path, dict(params)))
        assert method == "GET" and many
        count = page_size if len(calls) == 1 else 1
        if venue == "binance":
            start = params["fromId"]
            return [
                {
                    "id": start + i,
                    "price": "10",
                    "qty": "1",
                    "commission": "0.1",
                    "commissionAsset": "USDT",
                    "time": 1700000000000,
                }
                for i in range(count)
            ]
        start = int(params.get("after", "1000"))
        return [
            {
                "billId": str(start - i - 1),
                "tradeId": str(start - i - 1),
                "fillPx": "10",
                "fillSz": "1",
                "fee": "-0.1",
                "feeCcy": "USDT",
                "ts": "1700000000000",
            }
            for i in range(count)
        ]

    monkeypatch.setattr(Exchange, "call", fetch)
    fills = Exchange(venue).fills("BTC-USDT", "123")
    assert len(fills) == page_size + 1
    assert len({fill["trade_id"] for fill in fills}) == page_size + 1
    assert all(fill["fee"] == "0.1" for fill in fills)
    assert len(calls) == 2
    assert calls[1][1]["fromId" if venue == "binance" else "after"] == (
        1000 if venue == "binance" else "900"
    )


def test_legacy_order_cost_is_explicitly_incomplete():
    row = {
        "id": "legacy",
        "payload": json.dumps(payload()),
        "result": json.dumps({"filled_quantity": "1", "exchange_status": "FILLED"}),
        "mode": "live",
        "expires": 0,
        "state": "reconciled",
    }
    assert trading_api.view(row)["accounting_status"] == "cost_incomplete"
    assert "return_rate" not in trading_api.view(row)["result"]


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-1", "0"])
def test_invalid_fill_cannot_poison_strategy_balance(client, monkeypatch, invalid):
    store, user, run, signal_id = linked_suggestion(client)
    before = store.get_run(user, run["id"])
    monkeypatch.setattr(
        Exchange,
        "fills",
        lambda *args: [
            {
                "trade_id": "invalid",
                "quantity": invalid,
                "price": "10000",
                "fee": "0",
                "fee_currency": "USDT",
                "executed_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    with pytest.raises(HTTPException) as error:
        trading_api.sync_strategy_fills(
            user,
            OrderInput(**payload(strategy_run_id=run["id"], strategy_signal_id=signal_id)),
            {"exchange_order_id": "77"},
            Exchange("binance"),
            "unused",
        )
    assert error.value.status_code == 502
    after = store.get_run(user, run["id"], True)
    assert after["cash"] == before["cash"]
    assert after["quantity"] == before["quantity"]
    assert after["fills"] == []


def test_manual_platform_fill_enters_ledger_without_inventing_cost(client, monkeypatch):
    store, user, run, _ = linked_suggestion(client)
    monkeypatch.setattr(
        Exchange,
        "place",
        lambda *args: {
            "exchange_order_id": "manual-77",
            "exchange_status": "FILLED",
            "filled_quantity": "0.001",
        },
    )
    monkeypatch.setattr(
        Exchange,
        "lookup",
        lambda *args, **kwargs: {
            "exchange_order_id": "manual-77",
            "exchange_status": "FILLED",
            "filled_quantity": "0.001",
        },
    )
    monkeypatch.setattr(
        Exchange,
        "fills",
        lambda *args: [
            {
                "trade_id": "manual-fill",
                "quantity": "0.001",
                "price": "10000",
                "fee": "0.01",
                "fee_currency": "USDT",
                "executed_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    preview = client.post("/api/v1/trading/orders/preview", json=payload()).json()
    path = f"/api/v1/trading/orders/{preview['id']}"
    response = client.post(path + "/confirm", json={"confirmation": "确认模拟下单"})
    assert response.status_code == 200, response.text
    client.post(path + "/refresh", json={})
    ledger = store.ledger(user, None, None, None, None, None, None, None, 50, 0)
    assert len(ledger["fills"]) == 1
    fill = ledger["fills"][0]
    assert fill["run_id"] is None and fill["release_id"] is None
    assert fill["realized_pnl"] is None
    assert fill["order_id"] == preview["id"]
    assert fill["fee"] == "0.01"
    assert store.get_run(user, run["id"])["quantity"] == "0.00000000"
    assert store.ledger("other", None, None, None, None, None, None, None, 50, 0)["fills"] == []
    assert store.ledger(user, None, None, run["id"], None, None, None, None, 50, 0)["fills"] == []


@pytest.mark.parametrize("venue", ["binance", "okx"])
def test_demo_auto_executes_once_and_books_exchange_fills(client, monkeypatch, venue):
    from app.demo_execution import execute_demo_signal

    store, user, run, signal_id = linked_suggestion(client, venue=venue)
    with store._connect() as connection:
        connection.execute("UPDATE strategy_runs SET demo_auto='1' WHERE id=?", (run["id"],))
    monkeypatch.setattr(
        Exchange,
        "spot_rules",
        lambda *a: (Decimal(".01"), Decimal(".00001"), Decimal(".00001"), Decimal("1")),
    )
    monkeypatch.setattr(Exchange, "ticker", lambda *a: Decimal("10000"))
    monkeypatch.setattr(Exchange, "validate_order", lambda *a: Decimal("10000"))
    monkeypatch.setattr(
        Exchange, "account", lambda *a: [{"asset": "USDT", "available": "1000", "locked": "0"}]
    )
    submitted = []

    def place(self, order, client_id):
        submitted.append(client_id)
        return {
            "exchange_order_id": "demo77",
            "exchange_status": "FILLED",
            "filled_quantity": "0.001",
        }

    monkeypatch.setattr(Exchange, "place", place)
    monkeypatch.setattr(
        Exchange,
        "fills",
        lambda *a: [
            {
                "trade_id": "demo-fill",
                "quantity": ".001",
                "price": "10000",
                "fee": ".01",
                "fee_currency": "USDT",
                "executed_at": "2026-09-11T00:00:00Z",
            }
        ],
    )
    execute_demo_signal(store, user, run["id"])
    result = store.get_run(user, run["id"], True)
    assert result["status"] == "active", result["latest_error"]
    assert Decimal(result["quantity"]) == Decimal(".001")
    assert len(result["fills"]) == 1
    execute_demo_signal(StrategyRuntimeStore(None, trading_api.DB_PATH), user, run["id"])
    assert len(submitted) == 1
    assert len(store.ledger(user, None, None, None, None, None, None, None, 50, 0)["fills"]) == 1


def test_demo_auto_rejects_live_mode_without_sending(client, monkeypatch):
    from app.demo_execution import execute_demo_signal

    store, user, run, _ = linked_suggestion(client)
    with store._connect() as connection:
        connection.execute("UPDATE strategy_runs SET demo_auto='1' WHERE id=?", (run["id"],))
    monkeypatch.setenv("ATLAS_BINANCE_MODE", "live")
    monkeypatch.setattr(Exchange, "place", lambda *a: pytest.fail("live submission"))
    execute_demo_signal(store, user, run["id"])
    assert store.get_run(user, run["id"])["status"] == "error"


def test_auto_run_cannot_be_created_for_live():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RunCreate(
            release_id="test",
            market="CRYPTO",
            symbol="BTC-USDT",
            initial_cash="100",
            environment="live",
            demo_auto=True,
        )


def test_demo_unknown_submission_never_retries_after_resume(client, monkeypatch):
    from app.demo_execution import execute_demo_signal

    store, user, run, _ = linked_suggestion(client)
    with store._connect() as connection:
        connection.execute("UPDATE strategy_runs SET demo_auto='1' WHERE id=?", (run["id"],))
    monkeypatch.setattr(
        Exchange,
        "spot_rules",
        lambda *a: (Decimal(".01"), Decimal(".00001"), Decimal(".00001"), Decimal("1")),
    )
    monkeypatch.setattr(Exchange, "ticker", lambda *a: Decimal("10000"))
    monkeypatch.setattr(Exchange, "validate_order", lambda *a: Decimal("10000"))
    monkeypatch.setattr(
        Exchange, "account", lambda *a: [{"asset": "USDT", "available": "1000", "locked": "0"}]
    )
    attempts = []

    def timeout(*args):
        attempts.append(1)
        raise HTTPException(502, "unknown")

    monkeypatch.setattr(Exchange, "place", timeout)
    execute_demo_signal(store, user, run["id"])
    assert store.get_run(user, run["id"])["status"] == "error"
    store.set_status(user, run["id"], "resume")
    execute_demo_signal(store, user, run["id"])
    assert len(attempts) == 1


def test_page_demo_configuration_is_verified_encrypted_and_owner_scoped(
    client, monkeypatch, tmp_path
):
    from app import demo_credentials

    monkeypatch.setattr(demo_credentials, "DB_PATH", trading_api.DB_PATH)
    monkeypatch.setattr(demo_credentials, "KEY_PATH", tmp_path / ".account-key")
    monkeypatch.delenv("ATLAS_TRADING_OWNER_ID")
    monkeypatch.setenv("ATLAS_TRADING_ENABLED", "0")
    seen = []

    def verify(self):
        seen.append((self.mode, self.base))
        return []

    monkeypatch.setattr(Exchange, "account", verify)
    monkeypatch.setattr(Exchange, "place", lambda *a: pytest.fail("setup sent an order"))
    result = client.put(
        "/api/v1/trading/demo-accounts/binance",
        json={"api_key": "unique-demo-key", "secret": "unique-demo-secret", "consent": True},
    )
    assert result.status_code == 200, result.text
    assert result.json()["mode"] == "demo"
    assert all(mode == "demo" and host == "https://testnet.binance.vision" for mode, host in seen)
    assert "unique-demo" not in result.text
    user = client.get("/api/v1/trading/capabilities").json()["user_id"]
    assert Exchange("binance", owner=user).can_trade()
    assert not Exchange("binance", owner="other-user").configured
    with demo_credentials.database() as connection:
        blob = connection.execute("SELECT encrypted FROM demo_credentials").fetchone()[0]
    assert b"unique-demo" not in blob
    assert demo_credentials.KEY_PATH.stat().st_mode & 0o777 == 0o600
    assert demo_credentials.load(user, "binance")["secret"] == "unique-demo-secret"


def test_rejected_demo_configuration_does_not_save_or_echo_secrets(client, monkeypatch, tmp_path):
    from app import demo_credentials

    monkeypatch.setattr(demo_credentials, "DB_PATH", trading_api.DB_PATH)
    monkeypatch.setattr(demo_credentials, "KEY_PATH", tmp_path / ".account-key")

    def reject(*a):
        raise HTTPException(401, "upstream containing VERY-SECRET")

    monkeypatch.setattr(Exchange, "account", reject)
    response = client.put(
        "/api/v1/trading/demo-accounts/okx",
        json={
            "api_key": "VERY-SECRET-key",
            "secret": "VERY-SECRET",
            "passphrase": "phrase",
            "consent": True,
        },
    )
    assert response.status_code == 422
    assert "VERY-SECRET" not in response.text
    assert demo_credentials.owners() == []
    invalid = client.put(
        "/api/v1/trading/demo-accounts/binance",
        json={"api_key": "VERY-SECRET-key", "secret": "VERY-SECRET", "consent": False},
    )
    assert invalid.status_code == 422
    assert "VERY-SECRET" not in invalid.text
