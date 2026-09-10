"""Owner-bound, durable preview/confirm flow for manual orders."""

import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.config import DB_PATH
from app.trade_facts import ensure_manual_fills
from app.trading import Exchange, ExchangeRejected, OrderInput, Venue


def owner(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "需要登录")
    if not os.getenv("ATLAS_TRADING_OWNER_ID") or user.id != os.getenv("ATLAS_TRADING_OWNER_ID"):
        raise HTTPException(403, "交易账户未绑定当前用户，请配置 ATLAS_TRADING_OWNER_ID")
    return user.id


Owner = Annotated[str, Depends(owner)]

router = APIRouter(prefix="/api/v1/trading", tags=["manual-trading"])


def database():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    ensure_manual_fills(connection)
    connection.execute("""CREATE TABLE IF NOT EXISTS manual_trade_orders (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, venue TEXT NOT NULL,
        fingerprint TEXT NOT NULL, payload TEXT NOT NULL, mode TEXT NOT NULL,
        expires REAL NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}')""")
    connection.execute("""CREATE TABLE IF NOT EXISTS strategy_order_reservations (
        order_id TEXT PRIMARY KEY, owner TEXT NOT NULL, account_key TEXT NOT NULL,
        asset TEXT NOT NULL, amount TEXT NOT NULL, run_id TEXT NOT NULL,
        signal_id TEXT, quantity TEXT NOT NULL DEFAULT '0', created_at TEXT NOT NULL)""")
    reservation_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(strategy_order_reservations)")
    }
    if "signal_id" not in reservation_columns:
        connection.execute("ALTER TABLE strategy_order_reservations ADD COLUMN signal_id TEXT")
    if "quantity" not in reservation_columns:
        connection.execute(
            "ALTER TABLE strategy_order_reservations ADD COLUMN quantity TEXT NOT NULL DEFAULT '0'"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_reservation_account "
        "ON strategy_order_reservations(owner,account_key,asset)"
    )
    return connection


def get_order(connection, identifier, user):
    row = connection.execute(
        "SELECT * FROM manual_trade_orders WHERE id=? AND owner=?", (identifier, user)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "订单不存在")
    return row


def view(row):
    order = json.loads(row["payload"])
    result = json.loads(row["result"])
    accounting = (
        "not_applicable"
        if row["state"] in {"preview", "preview_expired", "rejected"}
        else "complete"
        if result.get("strategy_sync_complete")
        else "pending_sync"
        if order.get("strategy_run_id")
        else "cost_incomplete"
    )
    return {
        "id": row["id"],
        "order": order,
        "accounting_status": accounting,
        "mode": row["mode"],
        "expires": row["expires"],
        "state": row["state"],
        "result": result,
    }


def bound_exchange(row):
    exchange = Exchange(row["venue"])
    if exchange.fingerprint() != row["fingerprint"]:
        raise HTTPException(409, "交易账户或环境已改变，请切回原账户查询；新订单需重新预览")
    return exchange


def trade_gate(exchange):
    if not exchange.can_trade():
        raise HTTPException(403, "交易提交未启用，请先配置账户与交易开关")


def amount_gate(order):
    try:
        maximum = Decimal(os.getenv("ATLAS_TRADING_MAX_ORDER_USDT", "100"))
        if not maximum.is_finite() or maximum <= 0:
            raise InvalidOperation
    except InvalidOperation as exc:
        raise HTTPException(503, "单笔限额配置无效") from exc
    if order.quantity * order.price > maximum:
        raise HTTPException(422, "订单金额超过服务端单笔 USDT 限额")


def _expire_previews(connection):
    expired = [
        row["id"]
        for row in connection.execute(
            "SELECT id FROM manual_trade_orders WHERE state='preview' AND expires<=?",
            (time.time(),),
        )
    ]
    if expired:
        connection.executemany(
            "UPDATE manual_trade_orders SET state='preview_expired' WHERE id=?",
            ((item,) for item in expired),
        )
        connection.executemany(
            "UPDATE strategy_order_reservations SET amount='0',quantity='0' WHERE order_id=?",
            ((item,) for item in expired),
        )


def _reservation(order, exchange):
    asset = "USDT" if order.side == "buy" else order.symbol.split("-")[0]
    amount = order.quantity * order.price if order.side == "buy" else order.quantity
    return exchange.fingerprint(), asset, amount


def _update_reservation(connection, identifier, order, result, state):
    status = str(result.get("exchange_status", "")).lower()
    terminal = status in {
        "filled",
        "canceled",
        "cancelled",
        "expired",
        "expired_in_match",
        "rejected",
        "mmp_canceled",
    } or state in {"rejected", "preview_expired"}
    reported = Decimal(str(result.get("filled_quantity") or "0"))
    filled = reported
    if order.strategy_run_id and state != "rejected":
        filled = sum(
            (
                Decimal(item[0])
                for item in connection.execute(
                    "SELECT quantity FROM strategy_external_fills WHERE order_id=?", (identifier,)
                )
            ),
            Decimal("0"),
        )
        terminal = (
            terminal and result.get("filled_quantity") not in (None, "") and filled >= reported
        )
    remaining = max(Decimal("0"), order.quantity - filled)
    amount = (
        Decimal("0")
        if terminal
        else (remaining * order.price if order.side == "buy" else remaining)
    )
    connection.execute(
        "UPDATE strategy_order_reservations SET amount=?,quantity=? WHERE order_id=?",
        (format(amount, "f"), format(Decimal("0") if terminal else remaining, "f"), identifier),
    )


def strategy_gate(connection, user, order, exchange, verified=None):
    if bool(order.strategy_run_id) != bool(order.strategy_signal_id):
        raise HTTPException(422, "策略运行和信号标识必须同时提供")
    if not order.strategy_run_id:
        return None
    row = connection.execute(
        """SELECT r.symbol,r.environment,r.cash,r.quantity AS held_quantity,
                  r.status AS run_status,r.subscription_id,a.name,b.fingerprint,
                  s.status AS signal_status,s.side,s.quantity,
                  sub.status AS subscription_status
           FROM strategy_runs r JOIN strategy_accounts a ON a.id=r.account_id
           JOIN strategy_signals s ON s.run_id=r.id
           LEFT JOIN strategy_account_bindings b ON b.account_id=a.id
           LEFT JOIN strategy_subscriptions sub ON sub.id=r.subscription_id
           WHERE r.id=? AND r.owner_id=? AND s.id=?""",
        (order.strategy_run_id, user, order.strategy_signal_id),
    ).fetchone()
    if row is None or row["signal_status"] not in {"recommendation", "partially_filled"}:
        raise HTTPException(409, "策略建议不存在、已处理或不属于当前用户")
    if row["run_status"] != "active" or (
        row["subscription_id"] and row["subscription_status"] != "active"
    ):
        raise HTTPException(409, "策略实例已停止或订阅已取消，不能创建新订单")
    latest = connection.execute(
        "SELECT id FROM strategy_signals WHERE run_id=? "
        "AND status IN ('recommendation','partially_filled') "
        "ORDER BY bar_time DESC LIMIT 1",
        (order.strategy_run_id,),
    ).fetchone()
    if latest is None or latest["id"] != order.strategy_signal_id:
        raise HTTPException(409, "该建议已被更新，请使用最新策略建议")
    if row["fingerprint"] != exchange.fingerprint():
        raise HTTPException(409, "策略绑定的交易凭据已变化，请使用对应账户的新实例")
    expected_environment = "live" if exchange.mode == "live" else "exchange_test"
    if row["environment"] != expected_environment or exchange.venue not in row["name"].lower():
        raise HTTPException(409, "策略建议绑定的账户或环境与当前交易所不一致")
    if row["symbol"] != order.symbol or row["side"] != order.side:
        raise HTTPException(409, "订单方向或标的与策略建议不一致")
    if order.quantity > Decimal(row["quantity"]):
        raise HTTPException(422, "确认数量不能超过策略建议数量")
    signal_reserved = sum(
        (
            Decimal(item["quantity"])
            for item in connection.execute(
                "SELECT quantity FROM strategy_order_reservations WHERE owner=? AND signal_id=?",
                (user, order.strategy_signal_id),
            )
        ),
        Decimal("0"),
    )
    signal_filled = sum(
        (
            Decimal(item[0])
            for item in connection.execute(
                "SELECT quantity FROM strategy_external_fills WHERE owner_id=? AND signal_id=?",
                (user, order.strategy_signal_id),
            )
        ),
        Decimal("0"),
    )
    if signal_filled + signal_reserved + order.quantity > Decimal(row["quantity"]):
        raise HTTPException(422, "拆分订单总量不能超过策略建议数量")
    account_key, required_asset, required = _reservation(order, exchange)
    run_reserved = sum(
        (
            Decimal(item["amount"])
            for item in connection.execute(
                "SELECT amount FROM strategy_order_reservations "
                "WHERE owner=? AND run_id=? AND asset=?",
                (user, order.strategy_run_id, required_asset),
            )
        ),
        Decimal("0"),
    )
    if order.side == "buy" and required > Decimal(row["cash"]) - run_reserved:
        raise HTTPException(422, "策略实例的可用预算不足")
    if order.side == "sell" and required > Decimal(row["held_quantity"]) - run_reserved:
        raise HTTPException(422, "策略实例的可归属持仓不足")
    balances, market_price = verified
    available = next(
        (Decimal(str(item["available"])) for item in balances if item["asset"] == required_asset),
        Decimal("0"),
    )
    account_reserved = sum(
        (
            Decimal(item["amount"])
            for item in connection.execute(
                "SELECT r.amount FROM strategy_order_reservations r "
                "JOIN manual_trade_orders m ON m.id=r.order_id "
                "WHERE r.owner=? AND r.account_key=? AND r.asset=? "
                "AND m.state IN ('preview','submitting','unknown')",
                (user, account_key, required_asset),
            )
        ),
        Decimal("0"),
    )
    if available - account_reserved < required:
        raise HTTPException(422, f"{required_asset} 可用余额不足，策略建议未创建预览")
    return market_price, account_key, required_asset, required


def validated_fills(rows):
    try:
        for fill in rows:
            quantity, price, fee = (Decimal(fill[key]) for key in ("quantity", "price", "fee"))
            if (
                not all(value.is_finite() for value in (quantity, price, fee))
                or quantity <= 0
                or price <= 0
                or not fill["trade_id"]
                or not fill["fee_currency"]
            ):
                raise ValueError("incomplete fill")
            datetime.fromisoformat(fill["executed_at"].replace("Z", "+00:00"))
        rows = sorted(rows, key=lambda fill: fill["executed_at"])
    except (ValueError, KeyError, ArithmeticError, TypeError) as exc:
        raise HTTPException(502, "成交资料不完整，保留待同步状态") from exc
    return rows


def sync_manual_fills(row, result, exchange):
    order = OrderInput.model_validate_json(row["payload"])
    with database() as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_account_bindings'"
        ).fetchone():
            return
        account = connection.execute(
            "SELECT a.id,a.environment FROM strategy_accounts a "
            "JOIN strategy_account_bindings b ON b.account_id=a.id "
            "WHERE a.owner_id=? AND b.fingerprint=?",
            (row["owner"], row["fingerprint"]),
        ).fetchone()
    if account is None:
        return
    fills = validated_fills(exchange.fills(order.symbol, result.get("exchange_order_id")))
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for fill in fills:
            connection.execute(
                "INSERT OR IGNORE INTO platform_manual_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"mf_{secrets.token_hex(12)}",
                    row["owner"],
                    row["id"],
                    account["id"],
                    order.symbol,
                    order.side,
                    fill["quantity"],
                    fill["price"],
                    fill["fee"],
                    fill["fee_currency"],
                    account["environment"],
                    fill["executed_at"],
                    fill["trade_id"],
                ),
            )
        current = get_order(connection, row["id"], row["owner"])
        current_result = json.loads(current["result"])
        recorded = sum(
            (
                Decimal(item[0])
                for item in connection.execute(
                    "SELECT quantity FROM platform_manual_fills WHERE order_id=?", (row["id"],)
                )
            ),
            Decimal("0"),
        )
        terminal = str(current_result.get("exchange_status", "")).lower() in {
            "filled",
            "canceled",
            "cancelled",
            "expired",
            "expired_in_match",
            "rejected",
        }
        expected = current_result.get("filled_quantity")
        if terminal and expected not in (None, "") and recorded == Decimal(str(expected)):
            current_result["platform_sync_complete"] = True
            connection.execute(
                "UPDATE manual_trade_orders SET result=? WHERE id=?",
                (json.dumps(current_result), row["id"]),
            )


def sync_strategy_fills(user, order, result, exchange, manual_order_id):
    if not order.strategy_run_id or not order.strategy_signal_id:
        return
    exchange_order_id = str(result.get("exchange_order_id", ""))
    rows = exchange.fills(order.symbol, exchange_order_id)
    rows = validated_fills(rows)
    base_asset = order.symbol.split("-")[0]
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = connection.execute(
            "SELECT * FROM strategy_runs WHERE id=? AND owner_id=?",
            (order.strategy_run_id, user),
        ).fetchone()
        if run is None:
            raise HTTPException(409, "策略实例已不存在，成交保留在人工订单中待对账")
        cash = Decimal(run["cash"])
        held = Decimal(run["quantity"])
        average = Decimal(run["average_cost"])
        realized = Decimal(run["realized_pnl"])
        incomplete_fee = False
        changed = False
        last_price = Decimal("0")
        for fill in rows:
            quantity = Decimal(fill["quantity"])
            price = Decimal(fill["price"])
            fee = Decimal(fill["fee"])
            fee_currency = fill["fee_currency"]
            quote_fee = fee if fee_currency == "USDT" else Decimal("0")
            base_fee = fee if fee_currency == base_asset else Decimal("0")
            if fee and fee_currency not in {"USDT", base_asset}:
                incomplete_fee = True
            if order.side == "buy":
                net_quantity = quantity - base_fee
                next_held = held + net_quantity
                cost = quantity * price + quote_fee
                next_average = (held * average + cost) / next_held if next_held else Decimal("0")
                next_cash = cash - cost
                fill_realized = Decimal("0")
            else:
                reduction = quantity + base_fee
                next_held = max(Decimal("0"), held - reduction)
                proceeds = quantity * price - quote_fee
                fill_realized = proceeds - average * reduction
                next_average = average if next_held else Decimal("0")
                next_cash = cash + proceeds
            inserted = connection.execute(
                """INSERT OR IGNORE INTO strategy_external_fills
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    f"xf_{secrets.token_hex(12)}",
                    user,
                    order.strategy_run_id,
                    order.strategy_signal_id,
                    manual_order_id,
                    run["account_id"],
                    order.symbol,
                    order.side,
                    format(quantity, "f"),
                    format(price, "f"),
                    format(fee, "f"),
                    fee_currency,
                    format(fill_realized, "f"),
                    run["environment"],
                    fill["executed_at"],
                    fill["trade_id"],
                ),
            ).rowcount
            if not inserted:
                continue
            changed = True
            last_price = price
            cash, held, average = next_cash, next_held, next_average
            realized += fill_realized
        connection.execute(
            "UPDATE strategy_runs SET cash=?,quantity=?,average_cost=?,realized_pnl=?,"
            "latest_error=?,exit_pending=?,updated_at=? WHERE id=? AND owner_id=?",
            (
                format(cash, "f"),
                format(held, "f"),
                format(average, "f"),
                format(realized, "f"),
                "手续费使用第三种币种，策略收益暂不含该费用" if incomplete_fee else None,
                "0" if held <= Decimal("0.00000001") else run["exit_pending"],
                datetime.now(UTC).isoformat(),
                order.strategy_run_id,
                user,
            ),
        )
        status = str(result.get("exchange_status", "")).lower()
        if changed or status == "filled":
            signal = connection.execute(
                "SELECT quantity FROM strategy_signals WHERE id=?", (order.strategy_signal_id,)
            ).fetchone()
            total_filled = sum(
                (
                    Decimal(item[0])
                    for item in connection.execute(
                        "SELECT quantity FROM strategy_external_fills WHERE signal_id=?",
                        (order.strategy_signal_id,),
                    )
                ),
                Decimal("0"),
            )
            signal_status = (
                "filled" if total_filled >= Decimal(signal["quantity"]) else "partially_filled"
            )
            connection.execute(
                "UPDATE strategy_signals SET status=? WHERE id=? AND run_id=? "
                "AND status<>'superseded'",
                (signal_status, order.strategy_signal_id, order.strategy_run_id),
            )
        if changed:
            equity = cash + held * last_price
            initial = Decimal(run["initial_cash"])
            stamp = int(time.time())
            connection.execute(
                "INSERT OR REPLACE INTO strategy_equity VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    order.strategy_run_id,
                    user,
                    stamp,
                    format(equity, "f"),
                    format(cash, "f"),
                    format(held * last_price, "f"),
                    format(last_price, "f"),
                    format((equity - initial) / initial, "f"),
                    datetime.now(UTC).isoformat(),
                ),
            )


def reconcile_strategy_order(row, result, exchange):
    order = OrderInput.model_validate_json(row["payload"])
    if not order.strategy_run_id:
        sync_manual_fills(row, result, exchange)
        return
    sync_strategy_fills(row["owner"], order, result, exchange, row["id"])
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = get_order(connection, row["id"], row["owner"])
        current_result = json.loads(current["result"])
        _update_reservation(connection, row["id"], order, current_result, current["state"])
        status = str(current_result.get("exchange_status", "")).lower()
        terminal = status in {
            "filled",
            "canceled",
            "cancelled",
            "expired",
            "expired_in_match",
            "rejected",
            "mmp_canceled",
        }
        recorded = sum(
            (
                Decimal(item[0])
                for item in connection.execute(
                    "SELECT quantity FROM strategy_external_fills WHERE order_id=?", (row["id"],)
                )
            ),
            Decimal("0"),
        )
        expected = current_result.get("filled_quantity")
        if terminal and expected not in (None, "") and recorded == Decimal(str(expected)):
            current_result["strategy_sync_complete"] = True
            connection.execute(
                "UPDATE manual_trade_orders SET result=? WHERE id=?",
                (json.dumps(current_result), row["id"]),
            )


@router.get("/capabilities")
def capabilities(request: Request):
    user = request.state.user
    authorized = bool(os.getenv("ATLAS_TRADING_OWNER_ID")) and (
        user.id == os.getenv("ATLAS_TRADING_OWNER_ID")
    )
    venues = []
    for venue in ("binance", "okx"):
        exchange = Exchange(venue)
        venues.append(
            {
                "venue": venue,
                "mode": exchange.mode,
                "configured": authorized and exchange.configured,
                "can_trade": authorized and exchange.can_trade(),
            }
        )
    return {
        "authorized": authorized,
        "user_id": user.id,
        "venues": venues,
        "a_share": {"available": False, "reason": "待提供券商名称及官方 QMT/miniQMT 接口权限"},
    }


@router.get("/{venue}/account")
def account(venue: Venue, user: Owner):
    exchange = Exchange(venue)
    return {"venue": venue, "mode": exchange.mode, "balances": exchange.account()}


@router.post("/orders/preview")
def preview(order: OrderInput, user: Owner):
    exchange = Exchange(order.venue)
    trade_gate(exchange)
    amount_gate(order)
    verified = (
        (exchange.account(), exchange.validate_order(order)) if order.strategy_run_id else None
    )
    identifier = "aq" + secrets.token_hex(15)
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _expire_previews(connection)
        strategy_check = strategy_gate(connection, user, order, exchange, verified)
        market_price = strategy_check[0] if strategy_check else None
        connection.execute(
            "INSERT INTO manual_trade_orders "
            "(id,owner,venue,fingerprint,payload,mode,expires,state,result) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                user,
                order.venue,
                exchange.fingerprint(),
                order.model_dump_json(),
                exchange.mode,
                time.time() + 120,
                "preview",
                json.dumps(
                    {"checked_market_price": format(market_price, "f")}
                    if market_price is not None
                    else {}
                ),
            ),
        )
        if strategy_check:
            _, account_key, asset, reserved = strategy_check
            connection.execute(
                """INSERT INTO strategy_order_reservations
                   (order_id,owner,account_key,asset,amount,run_id,signal_id,quantity,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    identifier,
                    user,
                    account_key,
                    asset,
                    format(reserved, "f"),
                    order.strategy_run_id,
                    order.strategy_signal_id,
                    format(order.quantity, "f"),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return view(get_order(connection, identifier, user))


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str


@router.post("/orders/{identifier}/confirm")
def confirm(identifier: str, body: Confirmation, user: Owner):
    with database() as connection:
        row = get_order(connection, identifier, user)
        exchange = bound_exchange(row)
        trade_gate(exchange)
        if body.confirmation != ("确认实盘下单" if row["mode"] == "live" else "确认模拟下单"):
            raise HTTPException(422, "确认文字与当前交易环境不匹配")
        if row["state"] != "preview":
            return view(row)  # Replay never sends another order, including after restart.
        order = OrderInput.model_validate_json(row["payload"])
        if order.strategy_run_id:
            active = connection.execute(
                "SELECT r.status,s.status AS signal_status FROM strategy_runs r "
                "JOIN strategy_signals s ON s.run_id=r.id WHERE r.id=? AND s.id=?",
                (order.strategy_run_id, order.strategy_signal_id),
            ).fetchone()
            if (
                active is None
                or active["status"] != "active"
                or active["signal_status"] not in {"recommendation", "partially_filled"}
            ):
                raise HTTPException(409, "策略已暂停、停止或建议已更新，请重新查看策略")
        amount_gate(order)
        changed = connection.execute(
            "UPDATE manual_trade_orders SET state='submitting' WHERE id=? "
            "AND state='preview' AND expires>?",
            (identifier, time.time()),
        ).rowcount
        if changed != 1:
            raise HTTPException(409, "预览已过期或已提交，请查询状态或重新预览")
    # Commit intent before making the external call; crash/timeout requires reconciliation.
    try:
        result = exchange.place(order, identifier)
        state = "submitted"
    except ExchangeRejected as exc:
        result = {"message": exc.detail}
        state = "rejected"
    except HTTPException:
        result = {"message": "提交结果未确认，请查询状态或在交易所核实；不要重复下单"}
        state = "unknown"
    with database() as connection:
        connection.execute(
            "UPDATE manual_trade_orders SET state=?,result=? WHERE id=? AND state='submitting'",
            (state, json.dumps(result), identifier),
        )
        if state == "rejected":
            _update_reservation(connection, identifier, order, result, state)
        updated_row = get_order(connection, identifier, user)
    if state != "rejected":
        try:
            reconcile_strategy_order(updated_row, result, exchange)
        except HTTPException:
            pass  # Durable submitted state is retained; the scheduler retries reconciliation.
    return view(updated_row)


@router.get("/orders")
def orders(user: Owner):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _expire_previews(connection)
        return [
            view(row)
            for row in connection.execute(
                "SELECT * FROM manual_trade_orders WHERE owner=? ORDER BY rowid DESC LIMIT 100",
                (user,),
            )
        ]


@router.post("/orders/{identifier}/refresh")
def refresh(identifier: str, user: Owner):
    with database() as connection:
        row = get_order(connection, identifier, user)
    if row["state"] in {"preview", "preview_expired", "rejected"}:
        return view(row)
    # During a cancel request, a pre-cancel query must not supersede its eventual reply.
    # expires is the preview expiry initially, then a bounded operation lease for cancellation.
    if row["state"] == "cancel_submitting" and row["expires"] > time.time():
        return view(row)
    result = bound_exchange(row).lookup(json.loads(row["payload"])["symbol"], identifier)
    with database() as connection:
        connection.execute(
            "UPDATE manual_trade_orders SET state='reconciled',result=? WHERE id=? "
            "AND state=? AND result=?",
            (json.dumps(result), identifier, row["state"], row["result"]),
        )
        updated = view(get_order(connection, identifier, user))
    reconcile_strategy_order(row, result, bound_exchange(row))
    return updated


@router.post("/orders/{identifier}/cancel")
def cancel(identifier: str, body: Confirmation, user: Owner):
    with database() as connection:
        row = get_order(connection, identifier, user)
    if body.confirmation != "确认撤单":
        raise HTTPException(422, "需要确认撤单")
    if row["state"] in {"preview", "preview_expired", "rejected"}:
        raise HTTPException(409, "此订单没有可撤销的委托")
    if row["state"] == "submitting":
        raise HTTPException(409, "下单仍在处理中，请先查询并确认交易所已收到订单，再撤单")
    previous = json.loads(row["result"])
    exchange = bound_exchange(row)
    reconcile_strategy_order(row, previous, exchange)
    if str(previous.get("exchange_status", "")).lower() in {
        "filled",
        "canceled",
        "cancelled",
        "expired",
        "expired_in_match",
        "rejected",
        "mmp_canceled",
    }:
        raise HTTPException(409, "订单已成交、已撤销或已结束，无需撤单")
    # Persist cancel intent before network I/O; new-order kill switch does not block cancellation.
    with database() as connection:
        changed = connection.execute(
            "UPDATE manual_trade_orders SET state='cancel_submitting',expires=? WHERE id=? "
            "AND state=? AND result=? AND state!='cancel_submitting'",
            (time.time() + 60, identifier, row["state"], row["result"]),
        ).rowcount
        if changed != 1:
            raise HTTPException(409, "订单状态已变化或撤单正在处理，请查询状态")
    try:
        received = exchange.lookup(json.loads(row["payload"])["symbol"], identifier, cancel=True)
        result = {
            **previous,
            **{key: value for key, value in received.items() if value and value != "acknowledged"},
        }
        state = "cancel_requested"
    except ExchangeRejected:
        result = {**previous, "message": "交易所拒绝撤单，请查询订单最新状态"}
        state = "cancel_rejected"
    except HTTPException:
        result = {**previous, "message": "撤单结果未确认，请查询状态或到交易所核实"}
        state = "cancel_unknown"
    with database() as connection:
        connection.execute(
            "UPDATE manual_trade_orders SET state=?,result=? WHERE id=? "
            "AND state='cancel_submitting'",
            (state, json.dumps(result), identifier),
        )
        updated_row = get_order(connection, identifier, user)
    reconcile_strategy_order(updated_row, result, exchange)
    return view(updated_row)


class ManualTradeSyncScheduler:
    """Continuously reconcile linked platform orders while the service is running."""

    def __init__(self, interval_seconds: int = 60):
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _run_once(self):
        with database() as connection:
            rows = connection.execute(
                "SELECT * FROM manual_trade_orders "
                "WHERE state NOT IN ('preview','preview_expired','rejected') "
                "AND COALESCE(json_extract(result,'$.strategy_sync_complete'),0)=0 "
                "AND COALESCE(json_extract(result,'$.platform_sync_complete'),0)=0 "
                "ORDER BY rowid ASC"
            ).fetchall()
        for row in rows:
            previous = json.loads(row["result"])
            if previous.get("strategy_sync_complete"):
                continue
            try:
                refresh(row["id"], row["owner"])
            except Exception:
                continue

    def _loop(self):
        while not self.stop_event.wait(self.interval_seconds):
            self._run_once()

    def start(self):
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="trade-sync", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
