"""Real quote driven paper-execution probe; never calls private exchange APIs."""

import time
from decimal import Decimal
from email.utils import parsedate_to_datetime
from uuid import uuid4

import httpx
import pandas as pd
from fastapi import HTTPException


def _fetch_quote():
    started = time.monotonic()
    try:
        response = httpx.get(
            "https://api.binance.com/api/v3/ticker/bookTicker",
            params={"symbol": "BTCUSDT"},
            timeout=5,
            headers={"Cache-Control": "no-cache"},
        )
        response.raise_for_status()
        server_time = parsedate_to_datetime(response.headers["date"]).timestamp()
        if abs(time.time() - server_time) > 30:
            raise ValueError("stale server response")
        data = response.json()
        result = {key: Decimal(data[key]) for key in ("bidPrice", "askPrice", "bidQty", "askQty")}
        if (
            time.monotonic() - started > 5
            or any(not value.is_finite() or value <= 0 for value in result.values())
            or result["bidPrice"] > result["askPrice"]
        ):
            raise ValueError("invalid or slow quote")
        return result
    except Exception:
        raise HTTPException(422, "实时买卖报价不可用，已暂停联调；不使用缓存补单") from None


def quote():
    # Read-only quote refresh can retry; order processing happens only afterwards.
    try:
        return _fetch_quote()
    except HTTPException:
        return _fetch_quote()


def tick_probe(store, owner, identifier, release, run):
    from app.strategy_runtime import _iso, _now, _text

    if run["environment"] != "platform_sim" or run["symbol"] != "BTC-USDT":
        raise HTTPException(422, "报价联调仅允许BTC-USDT平台模拟")
    stamp = int(_now().timestamp())
    try:
        if run["last_bar_time"] and stamp - run["last_bar_time"] < 10:
            return store.get_run(owner, identifier, True)
        book = quote()
        stamp = int(_now().timestamp())  # Receipt time, never a past candle's open.
        with store._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS strategy_quote_samples (run_id TEXT, "
                "observed_at INTEGER, bid TEXT, ask TEXT, bid_qty TEXT, ask_qty TEXT, "
                "PRIMARY KEY(run_id,observed_at))"
            )
            connection.execute(
                "INSERT OR IGNORE INTO strategy_quote_samples VALUES (?,?,?,?,?,?)",
                (
                    identifier,
                    stamp,
                    str(book["bidPrice"]),
                    str(book["askPrice"]),
                    str(book["bidQty"]),
                    str(book["askQty"]),
                ),
            )
        reason = "10秒联调 · 币安真实买卖报价 · 平台模拟撮合"
        if run["last_bar_time"] is None or run["needs_reanchor"] == "1":
            cash, quantity = Decimal(run["cash"]), Decimal(run["quantity"])
            mark = book["bidPrice"]
            equity = cash + quantity * mark
            with store._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT status FROM strategy_runs WHERE id=?", (identifier,)
                ).fetchone()
                if not current or current["status"] != "active":
                    return store.get_run(owner, identifier, True)
                connection.execute(
                    "INSERT INTO strategy_signals "
                    "(id,owner_id,run_id,bar_time,target,reason,status,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        f"sig_{uuid4().hex[:18]}",
                        owner,
                        identifier,
                        stamp,
                        "0.1",
                        reason,
                        "queued",
                        _iso(),
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO strategy_equity VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        owner,
                        stamp,
                        _text(equity),
                        _text(cash),
                        _text(quantity * mark),
                        _text(mark),
                        _text(equity / Decimal(run["initial_cash"]) - 1),
                        _iso(),
                    ),
                )
                connection.execute(
                    "UPDATE strategy_runs SET last_bar_time=?,pending_target='0.1',"
                    "needs_reanchor='0',latest_signal=? WHERE id=? AND status='active'",
                    (stamp, reason, identifier),
                )
            return store.get_run(owner, identifier, True)
        buying = Decimal(run["pending_target"]) > 0
        price = book["askPrice"] if buying else book["bidPrice"]
        # _process_bar accepts an execution sample: open is the observed executable
        # quote; close is the current bid valuation. These are not historical OHLCV.
        sample = pd.DataFrame(
            [
                {
                    "open": price,
                    "close": book["bidPrice"],
                    "volume": book["askQty"] if buying else book["bidQty"],
                }
            ]
        )
        next_target = 0 if buying else 0.1
        store._process_bar(
            owner,
            identifier,
            release,
            sample,
            pd.Series([next_target]),
            pd.Series([reason]),
            [stamp],
            0,
            quoted=True,
        )
        with store._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM strategy_orders WHERE run_id=? AND created_at>=?",
                (
                    identifier,
                    pd.Timestamp(
                        float(run["execution_not_before"]), unit="s", tz="UTC"
                    ).isoformat(),
                ),
            ).fetchone()[0]
            if count >= 12:
                connection.execute(
                    "UPDATE strategy_runs SET status='paused',latest_signal=? "
                    "WHERE id=? AND status='active'",
                    (
                        "本轮12次报价联调完成，已暂停；可查看成交与曲线，恢复后开始新一轮",
                        identifier,
                    ),
                )
        return store.get_run(owner, identifier, True)
    finally:
        with store._connect() as connection:
            connection.execute("UPDATE strategy_runs SET lease_until=0 WHERE id=?", (identifier,))
