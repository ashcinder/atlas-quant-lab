"""Opt-in exchange-test execution. Reuses durable order and fill reconciliation.

One attempt per signal survives restart and concurrent ticks. Uncertain orders
block subsequent orders; there is no automatic retry or live-mode fallback.
"""

import os
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from fastapi import HTTPException

from app import trading_api
from app.trading import Exchange, OrderInput


def execute_demo_signal(store, owner, identifier):
    run = store.get_run(owner, identifier, True)
    signal = run.get("recommendation")
    if run.get("demo_auto") != "1" or run["status"] != "active" or not signal:
        return
    try:
        if run["environment"] != "exchange_test":
            raise HTTPException(403, "模拟自动执行的账户授权已失效")
        venue = "okx" if run["account_name"].lower().startswith("okx") else "binance"
        exchange = Exchange(venue, owner=owner)
        if exchange.mode != "demo" or not exchange.can_trade():
            raise HTTPException(403, "模拟自动执行要求已启用的测试账户；禁止切换到实盘")
        # Initialize manual tables before checking unresolved orders.
        with trading_api.database() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS demo_signal_attempts (
                signal_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                order_id TEXT, state TEXT NOT NULL)""")
            connection.execute("BEGIN IMMEDIATE")
            pending = connection.execute(
                """SELECT 1 FROM strategy_order_reservations r
                   JOIN manual_trade_orders o ON o.id=r.order_id
                   WHERE r.run_id=? AND (CAST(r.amount AS REAL)>0 OR
                     (o.state NOT IN ('preview_expired','rejected') AND
                      COALESCE(json_extract(o.result,'$.strategy_sync_complete'),0)<>1))""",
                (identifier,),
            ).fetchone()
            if pending:
                return
            inserted = connection.execute(
                "INSERT OR IGNORE INTO demo_signal_attempts VALUES (?,?,?,NULL,'claimed')",
                (signal["id"], identifier, owner),
            ).rowcount
            if not inserted:
                return
        price_step, quantity_step, minimum_quantity, minimum_notional = exchange.spot_rules(
            run["symbol"]
        )
        mark = exchange.ticker(run["symbol"])
        side = signal["side"]
        # Marketable limit with a bounded 0.2% price allowance; GTC orders may
        # remain open and must be reconciled/cancelled before another submission.
        price = mark * (Decimal("1.002") if side == "buy" else Decimal("0.998"))
        price = (price / price_step).to_integral_value(
            rounding=ROUND_UP if side == "buy" else ROUND_DOWN
        ) * price_step
        quantity = Decimal(signal["quantity"])
        maximum = Decimal(os.getenv("ATLAS_TRADING_MAX_ORDER_USDT", "100"))
        if not maximum.is_finite() or maximum <= 0:
            raise HTTPException(503, "单笔限额配置无效")
        quantity = min(quantity, maximum / price)
        if side == "buy":
            quantity = min(quantity, Decimal(run["cash"]) * Decimal("0.99") / price)
        else:
            quantity = min(quantity, Decimal(run["quantity"]))
        quantity = (quantity / quantity_step).to_integral_value(rounding=ROUND_DOWN) * quantity_step
        if quantity <= 0 or quantity < minimum_quantity or quantity * price < minimum_notional:
            with trading_api.database() as connection:
                connection.execute(
                    "UPDATE demo_signal_attempts SET state='below_minimum' WHERE signal_id=?",
                    (signal["id"],),
                )
            return  # Wait for a later signal; never invent a dust fill or exceed its budget.
        order = OrderInput(
            venue=venue,
            symbol=run["symbol"],
            side=side,
            quantity=quantity,
            price=price,
            strategy_run_id=identifier,
            strategy_signal_id=signal["id"],
        )
        preview = trading_api.preview(order, owner)
        if preview["mode"] != "demo":
            raise HTTPException(403, "拒绝自动提交非模拟订单")
        with trading_api.database() as connection:
            connection.execute(
                "UPDATE demo_signal_attempts SET order_id=?,state='prepared' WHERE signal_id=?",
                (preview["id"], signal["id"]),
            )
        result = trading_api.confirm(
            preview["id"], trading_api.Confirmation(confirmation="确认模拟下单"), owner
        )
        with trading_api.database() as connection:
            connection.execute(
                "UPDATE demo_signal_attempts SET state=? WHERE signal_id=?",
                (result["state"], signal["id"]),
            )
        if result["state"] in {"rejected", "unknown", "submitting"}:
            raise HTTPException(409, "测试订单被拒绝或结果待核实，请查看交易所订单；不会自动重试")
        store.sync_account(owner, run["account_id"])
    except Exception as exc:
        message = (
            exc.detail
            if isinstance(exc, HTTPException)
            else "模拟执行失败，请核对账户、订单与配置；不会自动重试"
        )
        with store._connect() as connection:
            connection.execute(
                "UPDATE strategy_runs SET status='error',latest_error=? WHERE id=? AND owner_id=?",
                (str(message), identifier, owner),
            )
