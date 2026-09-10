"""Owner-bound, durable preview/confirm flow for manual orders."""

import json
import os
import secrets
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.config import DB_PATH
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
    connection.execute("""CREATE TABLE IF NOT EXISTS manual_trade_orders (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, venue TEXT NOT NULL,
        fingerprint TEXT NOT NULL, payload TEXT NOT NULL, mode TEXT NOT NULL,
        expires REAL NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}')""")
    return connection


def get_order(connection, identifier, user):
    row = connection.execute(
        "SELECT * FROM manual_trade_orders WHERE id=? AND owner=?", (identifier, user)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "订单不存在")
    return row


def view(row):
    return {
        "id": row["id"],
        "order": json.loads(row["payload"]),
        "mode": row["mode"],
        "expires": row["expires"],
        "state": row["state"],
        "result": json.loads(row["result"]),
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
    identifier = "aq" + secrets.token_hex(15)
    with database() as connection:
        connection.execute(
            "INSERT INTO manual_trade_orders "
            "(id,owner,venue,fingerprint,payload,mode,expires,state) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                identifier,
                user,
                order.venue,
                exchange.fingerprint(),
                order.model_dump_json(),
                exchange.mode,
                time.time() + 120,
                "preview",
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
        return view(get_order(connection, identifier, user))


@router.get("/orders")
def orders(user: Owner):
    with database() as connection:
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
    if row["state"] in {"preview", "rejected"}:
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
        return view(get_order(connection, identifier, user))


@router.post("/orders/{identifier}/cancel")
def cancel(identifier: str, body: Confirmation, user: Owner):
    with database() as connection:
        row = get_order(connection, identifier, user)
    if body.confirmation != "确认撤单":
        raise HTTPException(422, "需要确认撤单")
    if row["state"] in {"preview", "rejected"}:
        raise HTTPException(409, "此订单没有可撤销的委托")
    if row["state"] == "submitting":
        raise HTTPException(409, "下单仍在处理中，请先查询并确认交易所已收到订单，再撤单")
    previous = json.loads(row["result"])
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
    exchange = bound_exchange(row)
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
        return view(get_order(connection, identifier, user))
