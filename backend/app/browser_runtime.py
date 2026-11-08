"""Browser demand leases are independent of the existing execution mutex."""
import json
import math
import time

from fastapi import HTTPException


def authorized_run(store, owner: str, identifier: str):
    with store._connect() as db:
        run = db.execute("SELECT * FROM strategy_runs WHERE id=? AND owner_id=?", (identifier, owner)).fetchone()
        if run is None:
            raise HTTPException(404, "运行实例不存在")
        release = store._release_for(db, run["release_id"])
        if release["owner_id"] != owner:
            subscribed = db.execute("SELECT 1 FROM strategy_subscriptions WHERE owner_id=? AND release_id=? AND status='active'", (owner, run["release_id"])).fetchone()
            if not subscribed:
                raise HTTPException(403, "策略订阅授权已失效")
        return run, release


def location(release, owner: str) -> str:
    snapshot = json.loads(release["snapshot"])
    if snapshot.get("execution_mode", "candles") != "candles":
        return "server_private"
    return "browser" if release["owner_id"] == owner or snapshot.get("source_visibility") == "public" else "server_private"


def heartbeat(store, owner: str, identifier: str):
    run, _ = authorized_run(store, owner, identifier)
    if run["status"] != "active":
        raise HTTPException(409, "只有活动实例可以续期")
    now = time.time()
    with store._connect() as db:
        # A gap invalidates queued recommendations. Resume from current data and
        # never manufacture fills for the period without browser demand.
        db.execute("UPDATE strategy_runs SET demand_until=?, needs_reanchor=CASE WHEN demand_until<=? THEN '1' ELSE needs_reanchor END WHERE id=? AND owner_id=?", (now + 45, now, identifier, owner))
        if float(run["demand_until"]) <= now:
            db.execute("UPDATE strategy_signals SET status='superseded' WHERE run_id=? AND status IN ('queued','recommendation','partially_filled')", (identifier,))
    return {"lease_expires_at": now + 45, "heartbeat_seconds": 15}


def demand_check(store, owner: str, identifier: str, browser_signal=None):
    run, release = authorized_run(store, owner, identifier)
    if float(run["demand_until"]) <= time.time():
        with store._connect() as db:
            db.execute("UPDATE strategy_runs SET needs_reanchor='1' WHERE id=?", (identifier,))
        raise HTTPException(409, "浏览器在线租约已过期，请重新打开网页并续期")
    if location(release, owner) == "browser" and browser_signal is None:
        raise HTTPException(409, "此策略由浏览器生成信号，不在服务器回退计算")
    if browser_signal is not None and location(release, owner) != "browser":
        raise HTTPException(403, "保密策略不接受客户端替换信号")
    return run, release


def signal_series(store, release, frame, body, schedule_history):
    import pandas as pd
    if body["bar_time"] != int(frame.index[-1].timestamp()):
        raise HTTPException(409, "浏览器信号不是当前已闭合行情版本")
    value = body["target"]
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise HTTPException(422, "目标仓位必须在0到1之间")
    targets = pd.Series(value, index=frame.index, dtype=float)
    reasons = pd.Series("浏览器策略信号（未证明）", index=frame.index)
    if release["strategy_id"] == "scheduled_dca":
        # Calendar validation is part of the authoritative contribution ledger;
        # indicator/strategy research remains on the browser.
        targets, _ = store._targets(release, frame, None, schedule_history)
    return targets, reasons


def sanitize_run(result: dict) -> dict:
    for key in ("latest_signal", "latest_error"):
        if result.get(key):
            result[key] = "保密策略信号" if key == "latest_signal" else "策略执行未完成，请稍后重试"
    for field in ("recommendation",):
        if isinstance(result.get(field), dict) and "reason" in result[field]:
            result[field]["reason"] = "保密策略信号"
    for field in ("signals", "orders", "fills", "fund_events"):
        for row in result.get(field, []):
            for key in ("reason", "error", "latest_error"):
                if row.get(key):
                    row[key] = "保密策略执行记录"
    return result
