"""Versioned rule strategies, subscriptions and durable paper-trading runs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import DB_PATH
from app.data.providers import ProviderError
from app.models import CustomStrategySpec
from app.private_runner import PrivateDecision, PrivateRunnerStore
from app.strategies import generate_target_exposure, get_strategy
from app.strategies.catalog import validate_params
from app.strategies.custom import generate_custom_target
from app.strategies.schedule import contribution_schedule
from app.strategy_anchor import AnchorConfirm, AnchorPrepare, StrategyAnchorStore
from app.trade_facts import ensure_manual_fills

Market = Literal["CRYPTO", "US", "CN"]
Environment = Literal["platform_sim", "exchange_test", "live"]
RunStatus = Literal["draft", "active", "paused", "stopped", "error"]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso() -> str:
    return _now().isoformat()


def _decimal(value: Any, label: str = "数值") -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise HTTPException(422, f"{label}格式无效") from exc
    if not result.is_finite():
        raise HTTPException(422, f"{label}格式无效")
    return result


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.00000001")), "f")


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    source_kind: Literal["builtin", "custom", "private_runner"]
    strategy_id: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    custom_strategy: CustomStrategySpec | None = None
    markets: list[Market] = Field(min_length=1, max_length=3)
    description: str = Field(default="", max_length=300)
    published: bool = True
    execution_mode: Literal["candles", "quote_probe", "private_runner"] = "candles"
    runner_public_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    code_commitment: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_source(self):
        if self.source_kind == "private_runner":
            if (
                self.execution_mode != "private_runner"
                or not self.runner_public_key
                or not self.code_commitment
                or self.custom_strategy
                or self.params
                or self.markets != ["CRYPTO"]
            ):
                raise ValueError("私有执行仅登记公钥与代码承诺，不接收规则或参数；市场为CRYPTO")
        elif (
            self.execution_mode == "private_runner"
            or self.runner_public_key
            or self.code_commitment
        ):
            raise ValueError("私有执行元数据只能用于private_runner")
        if (self.source_kind == "custom") != (self.custom_strategy is not None):
            raise ValueError("自定义发布必须包含且只能包含一份规则快照")
        if self.custom_strategy and self.custom_strategy.id != self.strategy_id:
            raise ValueError("策略 ID 与规则快照不一致")
        self.markets = list(dict.fromkeys(self.markets))
        return self


class SubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str


class AccountLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_account_id: str | None = None


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str
    subscription_id: str | None = None
    demo_auto: bool = False
    account_id: str | None = None
    market: Market
    environment: Environment = "platform_sim"
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9.=_/-]+$")
    interval: Literal["15m", "1h", "4h", "1d", "1wk"] = "1d"
    initial_cash: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    commission_rate: Decimal = Field(default=Decimal("0.001"), ge=0, le=Decimal("0.1"))
    slippage_rate: Decimal = Field(default=Decimal("0.0005"), ge=0, le=Decimal("0.1"))
    max_position: Decimal = Field(default=Decimal("0.95"), gt=0, le=1)
    max_participation: Decimal = Field(default=Decimal("0.01"), gt=0, le=1)
    stop_loss: Decimal = Field(default=Decimal("0"), ge=0, lt=1)
    take_profit: Decimal = Field(default=Decimal("0"), ge=0, le=10)

    @model_validator(mode="after")
    def supported_market_rules(self):
        if self.demo_auto and self.environment != "exchange_test":
            raise ValueError("自动执行仅支持交易所测试账户")
        if self.market == "CN" and self.interval not in {"1d", "1wk"}:
            raise ValueError("A 股模拟第一版仅支持日线或周线，以保证 T+1 可卖规则")
        return self


class StrategyRuntimeStore:
    def __init__(self, data_service, path: Path = DB_PATH):
        self.data_service = data_service
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=20000")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS strategy_releases (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, strategy_key TEXT NOT NULL,
                    name TEXT NOT NULL, version INTEGER NOT NULL, source_kind TEXT NOT NULL,
                    strategy_id TEXT NOT NULL, snapshot TEXT NOT NULL, markets TEXT NOT NULL,
                    description TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(owner_id, strategy_key, version)
                );
                CREATE TABLE IF NOT EXISTS strategy_subscriptions (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, release_id TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, cancelled_at TEXT,
                    UNIQUE(owner_id, release_id),
                    FOREIGN KEY(release_id) REFERENCES strategy_releases(id)
                );
                CREATE TABLE IF NOT EXISTS strategy_accounts (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
                    market TEXT NOT NULL, environment TEXT NOT NULL, currency TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(owner_id, market, environment, name)
                );
                CREATE TABLE IF NOT EXISTS strategy_account_links (
                    account_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    manual_account_id TEXT NOT NULL, UNIQUE(owner_id,manual_account_id)
                );
                CREATE TABLE IF NOT EXISTS strategy_account_snapshots (
                    account_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    balances TEXT NOT NULL, status TEXT NOT NULL, message TEXT,
                    synced_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strategy_account_bindings (
                    account_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strategy_runs (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, release_id TEXT NOT NULL,
                    subscription_id TEXT, account_id TEXT NOT NULL, market TEXT NOT NULL,
                    environment TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
                    initial_cash TEXT NOT NULL, cash TEXT NOT NULL, quantity TEXT NOT NULL,
                    average_cost TEXT NOT NULL, realized_pnl TEXT NOT NULL,
                    commission_rate TEXT NOT NULL, slippage_rate TEXT NOT NULL,
                    max_position TEXT NOT NULL DEFAULT '0.95',
                    max_participation TEXT NOT NULL DEFAULT '0.01',
                    stop_loss TEXT NOT NULL DEFAULT '0', take_profit TEXT NOT NULL DEFAULT '0',
                    exit_pending TEXT NOT NULL DEFAULT '0',
                    status TEXT NOT NULL, last_bar_time INTEGER, pending_target TEXT NOT NULL,
                    latest_signal TEXT, latest_error TEXT, lease_until REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(release_id) REFERENCES strategy_releases(id),
                    FOREIGN KEY(subscription_id) REFERENCES strategy_subscriptions(id),
                    FOREIGN KEY(account_id) REFERENCES strategy_accounts(id)
                );
                CREATE TABLE IF NOT EXISTS strategy_signals (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    bar_time INTEGER NOT NULL, target TEXT NOT NULL, reason TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, side TEXT,
                    quantity TEXT, reference_price TEXT,
                    UNIQUE(run_id, bar_time), FOREIGN KEY(run_id) REFERENCES strategy_runs(id)
                );
                CREATE TABLE IF NOT EXISTS strategy_fills (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    signal_id TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL,
                    price TEXT NOT NULL, fee TEXT NOT NULL, fee_currency TEXT NOT NULL,
                    realized_pnl TEXT NOT NULL, environment TEXT NOT NULL,
                    executed_at TEXT NOT NULL, external_trade_id TEXT,
                    UNIQUE(run_id, signal_id), FOREIGN KEY(run_id) REFERENCES strategy_runs(id)
                );
                CREATE TABLE IF NOT EXISTS strategy_external_fills (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    signal_id TEXT NOT NULL, order_id TEXT NOT NULL, account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, side TEXT NOT NULL, quantity TEXT NOT NULL,
                    price TEXT NOT NULL, fee TEXT NOT NULL, fee_currency TEXT NOT NULL,
                    realized_pnl TEXT NOT NULL, environment TEXT NOT NULL,
                    executed_at TEXT NOT NULL, external_trade_id TEXT NOT NULL,
                    UNIQUE(owner_id,account_id,environment,symbol,external_trade_id),
                    FOREIGN KEY(run_id) REFERENCES strategy_runs(id)
                );
                CREATE TABLE IF NOT EXISTS strategy_orders (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    signal_id TEXT NOT NULL UNIQUE, environment TEXT NOT NULL,
                    side TEXT NOT NULL, requested_quantity TEXT NOT NULL,
                    filled_quantity TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES strategy_runs(id)
                );
                CREATE TABLE IF NOT EXISTS strategy_fund_events (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    account_id TEXT NOT NULL, environment TEXT NOT NULL,
                    event_type TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(run_id,event_type)
                );
                CREATE TABLE IF NOT EXISTS strategy_equity (
                    run_id TEXT NOT NULL, owner_id TEXT NOT NULL, bar_time INTEGER NOT NULL,
                    equity TEXT NOT NULL, cash TEXT NOT NULL, position_value TEXT NOT NULL,
                    mark_price TEXT NOT NULL, return_rate TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, bar_time), FOREIGN KEY(run_id) REFERENCES strategy_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_runs_owner
                    ON strategy_runs(owner_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_strategy_fills_owner
                    ON strategy_fills(owner_id, executed_at);
                CREATE INDEX IF NOT EXISTS idx_strategy_external_fills_owner
                    ON strategy_external_fills(owner_id, executed_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_active_external_symbol
                    ON strategy_runs(owner_id, account_id, symbol)
                    WHERE environment<>'platform_sim' AND status IN ('active','paused');
            """)
            ensure_manual_fills(connection)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(strategy_runs)")}
            for name, default in (
                ("max_position", "0.95"),
                ("max_participation", "0.01"),
                ("stop_loss", "0"),
                ("take_profit", "0"),
                ("exit_pending", "0"),
                ("needs_reanchor", "0"),
                ("demo_auto", "0"),
                ("execution_not_before", "0"),
            ):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE strategy_runs ADD COLUMN {name} TEXT NOT NULL "
                        f"DEFAULT '{default}'"
                    )
            release_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(strategy_releases)")
            }
            if "published" not in release_columns:
                connection.execute(
                    "ALTER TABLE strategy_releases ADD COLUMN published INTEGER NOT NULL DEFAULT 1"
                )
            signal_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(strategy_signals)")
            }
            for name in ("side", "quantity", "reference_price"):
                if name not in signal_columns:
                    connection.execute(f"ALTER TABLE strategy_signals ADD COLUMN {name} TEXT")

    @staticmethod
    def _release(row):
        payload = dict(row)
        payload["markets"] = json.loads(payload["markets"])
        snapshot = json.loads(payload.pop("snapshot"))
        payload["execution_mode"] = snapshot.get("execution_mode", "candles")
        payload["params"] = snapshot.get("params", {})
        payload["custom_strategy"] = snapshot.get("custom_strategy")
        if snapshot.get("execution_mode") == "private_runner":
            payload["runner_public_key"] = snapshot["runner_public_key"]
            payload["code_commitment"] = snapshot["code_commitment"]
        payload["owned"] = False
        return payload

    def create_release(self, owner: str, request: ReleaseCreate):
        if request.source_kind == "builtin":
            try:
                strategy = get_strategy(request.strategy_id)
                params = validate_params(request.strategy_id, request.params)
            except (KeyError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
            if strategy.mode != "single":
                raise HTTPException(422, "第一版仅支持单资产策略")
            custom = None
        elif request.source_kind == "custom":
            params = {}
            custom = request.custom_strategy.model_dump(mode="json")
        else:
            params, custom = {}, None
        snapshot = {
            "params": params,
            "custom_strategy": custom,
            "execution_mode": request.execution_mode,
        }
        if request.source_kind == "private_runner":
            snapshot = {
                "execution_mode": "private_runner",
                "runner_public_key": request.runner_public_key,
                "code_commitment": request.code_commitment,
            }
        canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        key = f"{request.source_kind}:{request.strategy_id}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM strategy_releases "
                "WHERE owner_id=? AND strategy_key=?",
                (owner, key),
            ).fetchone()[0]
            identifier = f"rel_{uuid4().hex[:18]}"
            connection.execute(
                "INSERT INTO strategy_releases "
                "(id,owner_id,strategy_key,name,version,source_kind,strategy_id,snapshot,markets,"
                "description,content_hash,created_at,published) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    owner,
                    key,
                    request.name,
                    version,
                    request.source_kind,
                    request.strategy_id,
                    canonical,
                    json.dumps(request.markets),
                    request.description,
                    digest,
                    _iso(),
                    int(request.published),
                ),
            )
            row = connection.execute(
                "SELECT * FROM strategy_releases WHERE id=?", (identifier,)
            ).fetchone()
        result = self._release(row)
        result["owned"] = True
        result.pop("owner_id", None)
        result.pop("strategy_key", None)
        return result

    def publish_release(self, owner: str, identifier: str):
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE strategy_releases SET published=1 WHERE id=? AND owner_id=?",
                (identifier, owner),
            ).rowcount
            if not changed:
                raise HTTPException(404, "策略版本不存在")
        return {"id": identifier, "published": True}

    def list_releases(self, owner: str, mine: bool | None = None):
        sql = "SELECT * FROM strategy_releases WHERE (owner_id=? OR published=1)"
        args: tuple[Any, ...] = (owner,)
        if mine is True:
            sql += " AND owner_id=?"
            args = (owner, owner)
        elif mine is False:
            sql += " AND owner_id<>?"
            args = (owner, owner)
        sql += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, args).fetchall()
        output = []
        for row in rows:
            item = self._release(row)
            item["owned"] = row["owner_id"] == owner
            if not item["owned"]:
                item.pop("params", None)
                item.pop("custom_strategy", None)
            item.pop("owner_id", None)
            item.pop("strategy_key", None)
            output.append(item)
        return output

    def _release_for(self, connection, identifier: str):
        row = connection.execute(
            "SELECT * FROM strategy_releases WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "策略版本不存在")
        return row

    def subscribe(self, owner: str, release_id: str):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            release = self._release_for(connection, release_id)
            if not release["published"] and release["owner_id"] != owner:
                raise HTTPException(404, "策略版本尚未公开")
            existing = connection.execute(
                "SELECT * FROM strategy_subscriptions WHERE owner_id=? AND release_id=?",
                (owner, release_id),
            ).fetchone()
            if existing:
                if existing["status"] != "active":
                    connection.execute(
                        "UPDATE strategy_subscriptions SET status='active', "
                        "cancelled_at=NULL WHERE id=?",
                        (existing["id"],),
                    )
                identifier = existing["id"]
            else:
                identifier = f"sub_{uuid4().hex[:18]}"
                connection.execute(
                    "INSERT INTO strategy_subscriptions VALUES (?,?,?,'active',?,NULL)",
                    (identifier, owner, release_id, _iso()),
                )
        return self.get_subscription(owner, identifier)

    def get_subscription(self, owner: str, identifier: str):
        with self._connect() as connection:
            row = connection.execute(
                """SELECT s.*, r.name, r.version, r.markets, r.content_hash,
                          r.owner_id AS release_owner,r.strategy_key FROM strategy_subscriptions s
                   JOIN strategy_releases r ON r.id=s.release_id
                   WHERE s.id=? AND s.owner_id=?""",
                (identifier, owner),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "订阅不存在")
        result = dict(row)
        result["markets"] = json.loads(result["markets"])
        result["owned_release"] = result.pop("release_owner") == owner
        with self._connect() as connection:
            newer = connection.execute(
                "SELECT id,version FROM strategy_releases WHERE owner_id=? AND strategy_key=? "
                "AND version>? AND published=1 ORDER BY version DESC LIMIT 1",
                (row["release_owner"], result["strategy_key"], result["version"]),
            ).fetchone()
        result["upgrade_release_id"] = newer["id"] if newer else None
        result["upgrade_version"] = newer["version"] if newer else None
        result.pop("strategy_key", None)
        result.pop("owner_id", None)
        return result

    def list_subscriptions(self, owner: str):
        with self._connect() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM strategy_subscriptions WHERE owner_id=? "
                    "ORDER BY created_at DESC",
                    (owner,),
                )
            ]
        return [self.get_subscription(owner, identifier) for identifier in ids]

    def cancel_subscription(self, owner: str, identifier: str):
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE strategy_subscriptions SET status='cancelled',cancelled_at=? "
                "WHERE id=? AND owner_id=?",
                (_iso(), identifier, owner),
            )
            if not cursor.rowcount:
                raise HTTPException(404, "订阅不存在")
            connection.execute(
                "UPDATE strategy_runs SET status='stopped',updated_at=? "
                "WHERE subscription_id=? AND owner_id=? "
                "AND status IN ('draft','active','paused','error')",
                (_iso(), identifier, owner),
            )
        return self.get_subscription(owner, identifier)

    def _ensure_accounts(self, owner: str):
        defaults = [("CRYPTO", "USDT"), ("CRYPTO", "USD"), ("US", "USD"), ("CN", "CNY")]
        with self._connect() as connection:
            for market, currency in defaults:
                account_seed = owner + market
                if market == "CRYPTO" and currency == "USD":
                    account_seed += currency
                connection.execute(
                    "INSERT OR IGNORE INTO strategy_accounts VALUES (?,?,?,?,?,?,?)",
                    (
                        f"sim_{hashlib.sha256(account_seed.encode()).hexdigest()[:18]}",
                        owner,
                        f"{market} USD 模拟账户"
                        if market == "CRYPTO" and currency == "USD"
                        else f"{market} 模拟账户",
                        market,
                        "platform_sim",
                        currency,
                        _iso(),
                    ),
                )
            from app.trading import Exchange

            for venue in ("BINANCE", "OKX"):
                exchange = Exchange(venue.lower(), owner=owner)
                if not exchange.configured:
                    continue
                mode = exchange.mode
                environment = "live" if mode == "live" else "exchange_test"
                fingerprint = exchange.fingerprint()
                account_id = hashlib.sha256(
                    f"{owner}:{venue}:{mode}:{fingerprint}".encode()
                ).hexdigest()[:18]
                connection.execute(
                    "INSERT OR IGNORE INTO strategy_accounts VALUES (?,?,?,?,?,?,?)",
                    (
                        f"exchange_{account_id}",
                        owner,
                        f"{venue.title()} {'实盘' if mode == 'live' else '测试'}账户 "
                        f"· {account_id[:6]}",
                        "CRYPTO",
                        environment,
                        "USDT",
                        _iso(),
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO strategy_account_bindings VALUES (?,?)",
                    (f"exchange_{account_id}", fingerprint),
                )

    def manual_accounts(self, owner: str):
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledgers'"
            ).fetchone()
            if not exists:
                return []
            row = connection.execute(
                "SELECT data FROM ledgers WHERE owner_id=?", (owner,)
            ).fetchone()
        if row is None:
            return []
        return [
            {"id": item["id"], "name": item["name"], "currency": item["currency"]}
            for item in json.loads(row["data"]).get("accounts", [])
        ]

    def link_account(self, owner: str, identifier: str, manual_account_id: str | None):
        if manual_account_id and not any(
            item["id"] == manual_account_id for item in self.manual_accounts(owner)
        ):
            raise HTTPException(404, "手工账户不存在或不属于当前用户")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            account = connection.execute(
                "SELECT environment FROM strategy_accounts WHERE id=? AND owner_id=?",
                (identifier, owner),
            ).fetchone()
            if account is None or account["environment"] != "live":
                raise HTTPException(422, "仅实盘账户可关联手工账本，模拟资产不能关联真实资产")
            if manual_account_id is None:
                connection.execute(
                    "DELETE FROM strategy_account_links WHERE account_id=?", (identifier,)
                )
            else:
                try:
                    connection.execute(
                        "INSERT INTO strategy_account_links VALUES (?,?,?) "
                        "ON CONFLICT(account_id) DO UPDATE "
                        "SET manual_account_id=excluded.manual_account_id",
                        (identifier, owner, manual_account_id),
                    )
                except sqlite3.IntegrityError as exc:
                    raise HTTPException(409, "该手工账户已关联其他交易账户") from exc
        return {"account_id": identifier, "manual_account_id": manual_account_id}

    def sync_account(self, owner: str, identifier: str):
        from app.trading import Exchange

        with self._connect() as connection:
            account = connection.execute(
                "SELECT a.*,b.fingerprint FROM strategy_accounts a "
                "LEFT JOIN strategy_account_bindings b ON b.account_id=a.id "
                "WHERE a.id=? AND a.owner_id=?",
                (identifier, owner),
            ).fetchone()
        if account is None:
            raise HTTPException(404, "账户不存在")
        if account["environment"] == "platform_sim":
            raise HTTPException(422, "平台模拟账户无需交易所同步")
        venue = "okx" if account["name"].lower().startswith("okx") else "binance"
        exchange = Exchange(venue, owner=owner)
        if account["fingerprint"] != exchange.fingerprint():
            raise HTTPException(409, "账户凭据已变化，请切回原账户")
        balances = exchange.account()
        prices = {"USDT": Decimal("1")}
        if any(
            item["asset"] != "USDT"
            and _decimal(item["available"]) + _decimal(item["locked"] or "0") != 0
            for item in balances
        ):
            try:
                prices.update(exchange.spot_prices())
            except HTTPException:
                pass  # Preserve quantities; incomplete valuations never become zero.
        # Save raw units and a timestamped valuation, never infer deposits or PnL.
        clean = []
        for item in balances:
            available = _decimal(item["available"])
            locked = _decimal(item["locked"] or "0")
            clean.append(
                {
                    "asset": item["asset"],
                    "available": format(available, "f"),
                    "locked": format(locked, "f"),
                    "total": format(available + locked, "f"),
                    "value_usdt": format((available + locked) * prices[item["asset"]], "f")
                    if item["asset"] in prices
                    else "0"
                    if available + locked == 0
                    else None,
                }
            )
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO strategy_account_snapshots VALUES (?,?,?,?,?,?)",
                (identifier, owner, json.dumps(clean), "synced", None, _iso()),
            )
            # Mark all attributed strategy holdings using the same venue snapshot
            # as the account total, rather than treating fill prices as current prices.
            for run in connection.execute(
                "SELECT id,symbol,cash,quantity,initial_cash FROM strategy_runs "
                "WHERE owner_id=? AND account_id=?",
                (owner, identifier),
            ).fetchall():
                mark = prices.get(run["symbol"].split("-")[0])
                if mark is None:
                    continue
                cash = _decimal(run["cash"])
                position = _decimal(run["quantity"]) * mark
                initial = _decimal(run["initial_cash"])
                connection.execute(
                    "INSERT OR REPLACE INTO strategy_equity VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        run["id"],
                        owner,
                        int(_now().timestamp()),
                        _text(cash + position),
                        _text(cash),
                        _text(position),
                        _text(mark),
                        _text((cash + position - initial) / initial),
                        _iso(),
                    ),
                )
        return self.account_assets(owner, identifier)

    def account_assets(self, owner: str, identifier: str):
        with self._connect() as connection:
            account = connection.execute(
                "SELECT * FROM strategy_accounts WHERE id=? AND owner_id=?", (identifier, owner)
            ).fetchone()
            if account is None:
                raise HTTPException(404, "账户不存在")
            snapshot = connection.execute(
                "SELECT * FROM strategy_account_snapshots WHERE account_id=? AND owner_id=?",
                (identifier, owner),
            ).fetchone()
            linked = connection.execute(
                "SELECT manual_account_id FROM strategy_account_links "
                "WHERE account_id=? AND owner_id=?",
                (identifier, owner),
            ).fetchone()
            runs = connection.execute(
                "SELECT symbol,quantity FROM strategy_runs WHERE account_id=? AND owner_id=?",
                (identifier, owner),
            ).fetchall()
        attributed: dict[str, Decimal] = {}
        for run in runs:
            asset = run["symbol"].split("-")[0]
            attributed[asset] = attributed.get(asset, Decimal("0")) + _decimal(run["quantity"])
        rows = json.loads(snapshot["balances"]) if snapshot else []
        for asset in attributed:
            if not any(item["asset"] == asset for item in rows) and snapshot:
                rows.append({"asset": asset, "available": "0", "locked": "0", "total": "0"})
        mismatch = False
        for item in rows:
            quantity = attributed.get(item["asset"], Decimal("0"))
            difference = _decimal(item["total"]) - quantity
            item["attributed_quantity"] = format(quantity, "f")
            item["unattributed_quantity"] = format(max(difference, Decimal("0")), "f")
            item["reconciliation_shortfall"] = format(min(difference, Decimal("0")), "f")
            mismatch |= difference < 0
        complete = bool(snapshot) and all(item.get("value_usdt") is not None for item in rows)
        known_value = sum(
            (_decimal(item["value_usdt"]) for item in rows if item.get("value_usdt") is not None),
            Decimal("0"),
        )
        stale = (
            not snapshot
            or (_now() - datetime.fromisoformat(snapshot["synced_at"])).total_seconds() > 300
        )
        return {
            "account_id": identifier,
            "valuation_complete": complete and not stale,
            "valuation_stale": stale,
            "known_value_usdt": format(known_value, "f") if snapshot else None,
            "total_value_usdt": format(known_value, "f") if complete and not stale else None,
            "manual_account_id": linked["manual_account_id"] if linked else None,
            "name": account["name"],
            "environment": account["environment"],
            "balances": rows,
            "status": "reconciliation_required"
            if mismatch
            else "synced"
            if snapshot
            else "not_synced",
            "synced_at": snapshot["synced_at"] if snapshot else None,
            "message": "余额不足以覆盖策略归属持仓，差异待核实"
            if mismatch
            else "非平台资产保留为未归属；账户收益因历史成本不完整暂不可计算",
        }

    def list_accounts(self, owner: str):
        self._ensure_accounts(owner)
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id,name,market,environment,currency,created_at "
                    "FROM strategy_accounts WHERE owner_id=? ORDER BY market",
                    (owner,),
                )
            ]

    def create_run(self, owner: str, request: RunCreate):
        self._ensure_accounts(owner)
        with self._connect() as connection:
            release = self._release_for(connection, request.release_id)
            if json.loads(release["snapshot"]).get("execution_mode") in {
                "quote_probe",
                "private_runner",
            } and (
                request.environment != "platform_sim"
                or request.market != "CRYPTO"
                or request.symbol.upper() != "BTC-USDT"
            ):
                raise HTTPException(422, "报价联调与私有执行当前仅支持 BTC-USDT 平台模拟账户")
            if request.market not in json.loads(release["markets"]):
                raise HTTPException(422, "此策略版本不支持所选市场")
            if release["owner_id"] != owner:
                sub = connection.execute(
                    "SELECT * FROM strategy_subscriptions WHERE id=? AND owner_id=? "
                    "AND release_id=? AND status='active'",
                    (request.subscription_id, owner, request.release_id),
                ).fetchone()
                if sub is None:
                    raise HTTPException(403, "需要有效订阅才能运行此策略版本")
            currency = (
                request.symbol.upper().rsplit("-", 1)[-1]
                if request.market == "CRYPTO"
                else ("CNY" if request.market == "CN" else "USD")
            )
            if request.market == "CRYPTO" and currency not in {"USD", "USDT"}:
                raise HTTPException(422, "加密货币第一版仅支持 USD 或 USDT 计价现货")
            account_id = request.account_id
            if account_id is None and request.environment == "platform_sim":
                account_id = connection.execute(
                    "SELECT id FROM strategy_accounts WHERE owner_id=? AND market=? "
                    "AND environment='platform_sim' AND currency=?",
                    (owner, request.market, currency),
                ).fetchone()[0]
            account = connection.execute(
                "SELECT * FROM strategy_accounts WHERE id=? AND owner_id=?", (account_id, owner)
            ).fetchone()
            if (
                account is None
                or account["market"] != request.market
                or account["environment"] != request.environment
                or account["currency"] != currency
            ):
                raise HTTPException(422, "账户与市场或环境不匹配")
            if request.environment != "platform_sim":
                conflict = connection.execute(
                    "SELECT 1 FROM strategy_runs WHERE owner_id=? AND account_id=? "
                    "AND symbol=? AND status IN ('active','paused')",
                    (owner, account_id, request.symbol.upper()),
                ).fetchone()
                if conflict:
                    raise HTTPException(409, "同一真实账户和标的已有活动策略")
            identifier = f"run_{uuid4().hex[:18]}"
            now = _iso()
            cash = _text(request.initial_cash)
            connection.execute(
                """INSERT INTO strategy_runs (
                   id,owner_id,release_id,subscription_id,account_id,market,environment,
                   symbol,interval,initial_cash,cash,quantity,average_cost,realized_pnl,
                   commission_rate,slippage_rate,max_position,max_participation,stop_loss,
                   take_profit,status,last_bar_time,pending_target,
                   latest_signal,latest_error,lease_until,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',NULL,'0',
                             NULL,NULL,0,?,?)""",
                (
                    identifier,
                    owner,
                    request.release_id,
                    request.subscription_id,
                    account_id,
                    request.market,
                    request.environment,
                    request.symbol.upper(),
                    request.interval,
                    cash,
                    cash,
                    "0.00000000",
                    "0.00000000",
                    "0.00000000",
                    _text(request.commission_rate),
                    _text(request.slippage_rate),
                    _text(request.max_position),
                    _text(request.max_participation),
                    _text(request.stop_loss),
                    _text(request.take_profit),
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO strategy_fund_events VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"capital_{identifier}",
                    owner,
                    identifier,
                    account_id,
                    request.environment,
                    "initial_allocation",
                    cash,
                    currency,
                    now,
                ),
            )
            connection.execute(
                "UPDATE strategy_runs SET demo_auto=? WHERE id=?",
                ("1" if request.demo_auto else "0", identifier),
            )
        return self.get_run(owner, identifier)

    def _run_view(self, connection, row):
        last = connection.execute(
            "SELECT * FROM strategy_equity WHERE run_id=? ORDER BY bar_time DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        release = connection.execute(
            "SELECT name,version,content_hash,snapshot FROM strategy_releases WHERE id=?",
            (row["release_id"],),
        ).fetchone()
        account = connection.execute(
            "SELECT name,currency FROM strategy_accounts WHERE id=?", (row["account_id"],)
        ).fetchone()
        recommendation = connection.execute(
            "SELECT id,side,quantity,reference_price,reason FROM strategy_signals "
            "WHERE run_id=? AND status IN ('recommendation','partially_filled') "
            "ORDER BY bar_time DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        result = dict(row)
        result.update(
            strategy_name=release["name"],
            strategy_version=release["version"],
            strategy_hash=release["content_hash"],
            execution_mode=json.loads(release["snapshot"]).get("execution_mode", "candles"),
            account_name=account["name"] if account else "",
            currency=account["currency"] if account else None,
            recommendation=dict(recommendation)
            if recommendation and row["status"] == "active"
            else None,
        )
        for key in ("lease_until", "owner_id"):
            result.pop(key, None)
        result["equity"] = last["equity"] if last else result["initial_cash"]
        result["return_rate"] = last["return_rate"] if last else "0.00000000"
        result["mark_price"] = last["mark_price"] if last else None
        result["position_value"] = last["position_value"] if last else "0.00000000"
        incomplete_fee = connection.execute(
            "SELECT 1 FROM strategy_external_fills WHERE run_id=? AND fee<>'0' "
            "AND fee_currency NOT IN ('USDT',?) LIMIT 1",
            (row["id"], row["symbol"].split("-")[0]),
        ).fetchone()
        result["valuation_complete"] = not bool(incomplete_fee)
        if incomplete_fee:
            result["latest_error"] = "存在尚未折算的第三币种手续费，净收益和收益率暂不可完整计算"
        return result

    def get_run(self, owner: str, identifier: str, detail: bool = False):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_runs WHERE id=? AND owner_id=?", (identifier, owner)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "运行实例不存在")
            result = self._run_view(connection, row)
            if result["execution_mode"] == "private_runner":
                result["execution_evidence"] = {
                    "level": "developer_signature",
                    "source_uploaded": False,
                    "strategy_execution_proven": False,
                    "exchange_fills_verified": False,
                    "performance_source": "platform_quote_simulation",
                }
            if detail:
                result["orders"] = [
                    dict(item)
                    for item in connection.execute(
                        "SELECT * FROM strategy_orders WHERE run_id=? "
                        "ORDER BY created_at DESC LIMIT 100",
                        (identifier,),
                    )
                ]
                result["fund_events"] = [
                    dict(item)
                    for item in connection.execute(
                        "SELECT * FROM strategy_fund_events WHERE run_id=? ORDER BY created_at",
                        (identifier,),
                    )
                ]
                result["signals"] = [
                    dict(x)
                    for x in connection.execute(
                        "SELECT * FROM strategy_signals WHERE run_id=? "
                        "ORDER BY bar_time DESC LIMIT 100",
                        (identifier,),
                    )
                ]
                simulated_fills = [
                    dict(x)
                    for x in connection.execute(
                        "SELECT * FROM strategy_fills WHERE run_id=? "
                        "ORDER BY executed_at DESC LIMIT 100",
                        (identifier,),
                    )
                ]
                external_fills = [
                    dict(x)
                    for x in connection.execute(
                        "SELECT * FROM strategy_external_fills WHERE run_id=? "
                        "ORDER BY executed_at DESC LIMIT 100",
                        (identifier,),
                    )
                ]
                result["fills"] = sorted(
                    [*simulated_fills, *external_fills],
                    key=lambda item: item["executed_at"],
                    reverse=True,
                )[:100]
                result["curve"] = [
                    dict(x)
                    for x in connection.execute(
                        "SELECT bar_time,equity,cash,position_value,mark_price,return_rate "
                        "FROM strategy_equity WHERE run_id=? ORDER BY bar_time",
                        (identifier,),
                    )
                ]
            return result

    def list_runs(self, owner: str, market: str | None = None, environment: str | None = None):
        sql = "SELECT * FROM strategy_runs WHERE owner_id=?"
        args: list[Any] = [owner]
        if market:
            sql += " AND market=?"
            args.append(market)
        if environment:
            sql += " AND environment=?"
            args.append(environment)
        sql += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            return [self._run_view(connection, row) for row in connection.execute(sql, args)]

    def set_status(self, owner: str, identifier: str, action: str):
        allowed = {
            "start": ("active", ("draft", "paused", "error")),
            "resume": ("active", ("paused", "error")),
            "pause": ("paused", ("active",)),
            "stop": ("stopped", ("draft", "active", "paused", "error")),
        }
        if action not in allowed:
            raise HTTPException(404, "未知运行操作")
        target, sources = allowed[action]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,account_id,symbol,environment,subscription_id FROM strategy_runs "
                "WHERE id=? AND owner_id=?",
                (identifier, owner),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "运行实例不存在")
            if row["status"] not in sources:
                raise HTTPException(409, "当前状态不能执行此操作")
            if target == "active" and row["subscription_id"]:
                subscription = connection.execute(
                    "SELECT status FROM strategy_subscriptions WHERE id=? AND owner_id=?",
                    (row["subscription_id"], owner),
                ).fetchone()
                if subscription is None or subscription["status"] != "active":
                    raise HTTPException(409, "订阅已失效，无法恢复运行")
            if target == "active" and row["environment"] != "platform_sim":
                conflict = connection.execute(
                    "SELECT 1 FROM strategy_runs WHERE owner_id=? AND account_id=? "
                    "AND symbol=? AND id<>? AND status IN ('active','paused')",
                    (owner, row["account_id"], row["symbol"], identifier),
                ).fetchone()
                if conflict:
                    raise HTTPException(409, "同一真实账户和标的已有活动策略")
            try:
                connection.execute(
                    "UPDATE strategy_runs SET status=?,latest_error=NULL,updated_at=?,"
                    "needs_reanchor=? WHERE id=?",
                    (target, _iso(), "1" if target == "active" else "0", identifier),
                )
                if target == "active":
                    connection.execute(
                        "UPDATE strategy_runs SET execution_not_before=? WHERE id=?",
                        (str(_now().timestamp()), identifier),
                    )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "同一真实账户和标的已有活动策略") from exc
        return self.get_run(owner, identifier)

    def _targets(self, release, frame, initial_cash: Decimal, schedule_history=None):
        snapshot = json.loads(release["snapshot"])
        if release["source_kind"] == "custom":
            spec = CustomStrategySpec.model_validate(snapshot["custom_strategy"])
            return generate_custom_target(frame, spec, spec.target_position)
        if release["strategy_id"] == "scheduled_dca":
            params = snapshot["params"]
            # Persisted signal dates anchor the calendar across restarts and rolling
            # provider windows. Warm-up bars never count as contributions or delay.
            history = schedule_history or [int(frame.index[-1].timestamp())]
            anchor = pd.Timestamp(min(history), unit="s", tz="UTC")
            dates = (
                pd.to_datetime(history, unit="s", utc=True)
                .union(frame.index[frame.index >= anchor])
                .sort_values()
            )
            schedule = contribution_schedule(
                dates,
                int(params["every"]),
                str(params["unit"]),
                int(params.get("start_delay", 0)),
            )
            target = pd.Series(schedule, index=dates, dtype=float).reindex(
                frame.index, fill_value=0.0
            )
            reasons = pd.Series("等待定投", index=frame.index, dtype=object)
            reasons.loc[target > 0] = "固定金额定投"
            return target, reasons
        return generate_target_exposure(frame, release["strategy_id"], snapshot["params"], 1.0)

    @staticmethod
    def _completed_frame(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
        duration = {
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "1d": timedelta(days=1),
            "1wk": timedelta(days=7),
        }[interval]
        return frame[frame.index <= pd.Timestamp.now(tz="UTC") - duration]

    def tick(self, owner: str, identifier: str):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM strategy_runs WHERE id=? AND owner_id=?", (identifier, owner)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "运行实例不存在")
            if row["status"] != "active":
                raise HTTPException(409, "仅活动策略可以运行")
            if row["lease_until"] > _now().timestamp():
                raise HTTPException(409, "策略正在运行")
            connection.execute(
                "UPDATE strategy_runs SET lease_until=? WHERE id=?",
                (_now().timestamp() + 45, identifier),
            )
        try:
            return self._tick_locked(owner, identifier)
        except (ProviderError, ValueError, HTTPException) as exc:
            message = exc.detail if isinstance(exc, HTTPException) else str(exc)
            with self._connect() as connection:
                connection.execute(
                    "UPDATE strategy_runs SET status='error',latest_error=?,"
                    "lease_until=0,updated_at=? WHERE id=? AND owner_id=?",
                    (message, _iso(), identifier, owner),
                )
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(422, message) from exc

    def _tick_locked(self, owner: str, identifier: str):
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM strategy_runs WHERE id=? AND owner_id=?", (identifier, owner)
            ).fetchone()
            release = self._release_for(connection, run["release_id"])
            if json.loads(release["snapshot"]).get("execution_mode") == "private_runner":
                connection.execute(
                    "UPDATE strategy_runs SET lease_until=0 WHERE id=?", (identifier,)
                )
                return self.get_run(owner, identifier, True)
            schedule_history = (
                [
                    row[0]
                    for row in connection.execute(
                        "SELECT bar_time FROM strategy_signals WHERE run_id=? ORDER BY bar_time",
                        (identifier,),
                    )
                ]
                if release["strategy_id"] == "scheduled_dca"
                else None
            )
        if json.loads(release["snapshot"]).get("execution_mode") == "quote_probe":
            from app.quote_probe import tick_probe

            return tick_probe(self, owner, identifier, release, run)
        asset_class = "crypto" if run["market"] == "CRYPTO" else "equity"
        bundle = self.data_service.fetch(
            run["symbol"], asset_class, run["interval"], None, None, "auto", "auto", True
        )
        if bundle.source == "demo" or bundle.source.startswith("demo:"):
            raise HTTPException(422, "演示行情不能产生正式模拟成交")
        if bundle.is_stale:
            raise HTTPException(422, "行情已过期，已暂停新的模拟成交")
        frame = self._completed_frame(bundle.frame.sort_index(), run["interval"])
        if len(frame) < 40:
            raise HTTPException(422, "至少需要40根已完成K线才能运行")
        targets, reasons = self._targets(
            release, frame, _decimal(run["initial_cash"]), schedule_history
        )
        times = [int(index.timestamp()) for index in frame.index]
        if run["last_bar_time"] is None or run["needs_reanchor"] == "1":
            index = len(frame) - 1
            mark = _decimal(frame.iloc[index]["close"])
            when = times[index]
            signal_id = f"sig_{uuid4().hex[:18]}"
            target = min(
                max(_decimal(targets.iloc[index]), Decimal("0")),
                _decimal(run["max_position"]),
            )
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                latest_run = connection.execute(
                    "SELECT status,last_bar_time,needs_reanchor FROM strategy_runs WHERE id=?",
                    (identifier,),
                ).fetchone()
                if latest_run["status"] != "active" or (
                    latest_run["last_bar_time"] != run["last_bar_time"]
                    or latest_run["needs_reanchor"] != run["needs_reanchor"]
                ):
                    return self.get_run(owner, identifier, True)
                connection.execute(
                    "UPDATE strategy_signals SET status='superseded' WHERE run_id=? "
                    "AND bar_time<>? AND status IN ('queued','recommendation','partially_filled')",
                    (identifier, when),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO strategy_signals "
                    "(id,owner_id,run_id,bar_time,target,reason,status,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        signal_id,
                        owner,
                        identifier,
                        when,
                        _text(target),
                        str(reasons.iloc[index]),
                        "queued",
                        _iso(),
                    ),
                )
                initial = _decimal(run["initial_cash"])
                cash = _decimal(run["cash"])
                position = _decimal(run["quantity"]) * mark
                connection.execute(
                    "INSERT OR IGNORE INTO strategy_equity VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        owner,
                        when,
                        _text(cash + position),
                        _text(cash),
                        _text(position),
                        _text(mark),
                        _text((cash + position - initial) / initial),
                        _iso(),
                    ),
                )
                connection.execute(
                    "UPDATE strategy_runs SET last_bar_time=?,pending_target=?,"
                    "latest_signal=?,lease_until=0,needs_reanchor='0',updated_at=? "
                    "WHERE id=? AND owner_id=?",
                    (when, _text(target), str(reasons.iloc[index]), _iso(), identifier, owner),
                )
            return self.get_run(owner, identifier, True)
        new_indexes = [i for i, stamp in enumerate(times) if stamp > run["last_bar_time"]]
        for index in new_indexes:
            self._process_bar(owner, identifier, release, frame, targets, reasons, times, index)
        with self._connect() as connection:
            connection.execute(
                "UPDATE strategy_runs SET lease_until=0,updated_at=? WHERE id=? AND owner_id=?",
                (_iso(), identifier, owner),
            )
        return self.get_run(owner, identifier, True)

    def mark_position(self, owner: str, identifier: str):
        """Track existing positions after pause/stop, without creating signals or trades."""
        run = self.get_run(owner, identifier)
        bundle = self.data_service.fetch(
            run["symbol"],
            "crypto" if run["market"] == "CRYPTO" else "equity",
            run["interval"],
            None,
            None,
            "auto",
            "auto",
            True,
        )
        if bundle.is_stale or bundle.source.startswith("demo"):
            raise HTTPException(422, "持仓估值行情不可用，保留上次估值")
        frame = self._completed_frame(bundle.frame.sort_index(), run["interval"])
        if frame.empty:
            return
        price = _decimal(frame.iloc[-1]["close"])
        if price <= 0:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM strategy_runs WHERE id=? AND owner_id=?", (identifier, owner)
            ).fetchone()
            if row["status"] not in {"paused", "stopped", "error"}:
                return
            cash = _decimal(row["cash"])
            position = _decimal(row["quantity"]) * price
            initial = _decimal(row["initial_cash"])
            stamp = int(frame.index[-1].timestamp())
            connection.execute(
                "INSERT OR REPLACE INTO strategy_equity VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    owner,
                    stamp,
                    _text(cash + position),
                    _text(cash),
                    _text(position),
                    _text(price),
                    _text((cash + position - initial) / initial),
                    _iso(),
                ),
            )

    def _process_bar(
        self,
        owner,
        identifier,
        release,
        frame,
        targets,
        reasons,
        times,
        index,
        *,
        quoted=False,
        decision_target=None,
        execution_epoch=None,
    ):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM strategy_runs WHERE id=? AND owner_id=?", (identifier, owner)
            ).fetchone()
            if (
                run["status"] != "active"
                or times[index] <= (run["last_bar_time"] or 0)
                or (execution_epoch is not None and run["execution_not_before"] != execution_epoch)
            ):
                return False
            cash = _decimal(run["cash"])
            quantity = _decimal(run["quantity"])
            average = _decimal(run["average_cost"])
            realized = _decimal(run["realized_pnl"])
            initial = _decimal(run["initial_cash"])
            open_price = _decimal(frame.iloc[index]["open"])
            mark = _decimal(frame.iloc[index]["close"])
            target = min(
                max(
                    _decimal(run["pending_target"] if decision_target is None else decision_target),
                    Decimal("0"),
                ),
                _decimal(run["max_position"]),
            )
            commission = _decimal(run["commission_rate"])
            slippage = _decimal(run["slippage_rate"])
            risk_reason = None
            force_exit = run["exit_pending"] == "1"
            if force_exit:
                target = Decimal("0")
                risk_reason = "风控退出继续执行"
            if quantity > 0 and average > 0:
                stop_loss = _decimal(run["stop_loss"])
                take_profit = _decimal(run["take_profit"])
                if stop_loss and open_price <= average * (Decimal("1") - stop_loss):
                    target = Decimal("0")
                    risk_reason = "止损触发"
                    force_exit = True
                elif take_profit and open_price >= average * (Decimal("1") + take_profit):
                    target = Decimal("0")
                    risk_reason = "止盈触发"
                    force_exit = True
            equity_open = cash + quantity * open_price
            desired = target * equity_open / open_price if open_price else quantity
            if (
                release["source_kind"] == "builtin"
                and release["strategy_id"] == "scheduled_dca"
                and not force_exit
            ):
                # A due contribution spends a fixed gross amount; price changes and
                # non-due bars must not rebalance or sell the accumulated holding.
                amount = _decimal(json.loads(release["snapshot"])["params"]["amount"])
                headroom = max(
                    Decimal("0"),
                    _decimal(run["max_position"]) * equity_open - quantity * open_price,
                )
                budget = min(amount, cash, headroom) if target > 0 else Decimal("0")
                desired = quantity + budget / (
                    open_price * (Decimal("1") + slippage) * (Decimal("1") + commission)
                )
            if run["market"] == "CN":
                desired = (desired / 100).to_integral_value(rounding=ROUND_DOWN) * 100
            delta = desired - quantity
            if run["environment"] == "platform_sim" and times[index] < float(
                run["execution_not_before"]
            ):
                # A bar already open when the user starts/resumes cannot be
                # filled retrospectively at that bar's opening price.
                delta = Decimal("0")
            if decision_target is not None:
                connection.execute(
                    "INSERT INTO strategy_signals "
                    "(id,owner_id,run_id,bar_time,target,reason,status,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        f"sig_{uuid4().hex[:18]}",
                        owner,
                        identifier,
                        times[index],
                        str(decision_target),
                        str(reasons.iloc[index]),
                        "received",
                        _iso(),
                    ),
                )
            previous = connection.execute(
                "SELECT id FROM strategy_signals WHERE run_id=? AND bar_time=?",
                (identifier, times[index] if decision_target is not None else run["last_bar_time"]),
            ).fetchone()
            signal_id = previous["id"] if previous else f"sig_{uuid4().hex[:18]}"
            if run["environment"] != "platform_sim":
                connection.execute(
                    "UPDATE strategy_signals SET status='superseded' WHERE run_id=? "
                    "AND id<>? AND status IN ('recommendation','partially_filled')",
                    (identifier, signal_id),
                )
            if risk_reason and previous:
                connection.execute(
                    "UPDATE strategy_signals SET reason=? WHERE id=?", (risk_reason, signal_id)
                )
            if run["environment"] == "platform_sim" and abs(delta) > Decimal("0.00000001"):
                side = "buy" if delta > 0 else "sell"
                qty = abs(delta)
                volume_limit = _decimal(frame.iloc[index]["volume"]) * _decimal(
                    run["max_participation"]
                )
                if quoted:
                    # Probe fills use fresh top-of-book liquidity, not candle volume.
                    volume_limit = min(
                        _decimal(frame.iloc[index]["volume"]), Decimal("100") / open_price
                    )
                if run["market"] == "CN":
                    volume_limit = (volume_limit / 100).to_integral_value(rounding=ROUND_DOWN) * 100
                qty = min(qty, volume_limit)
                price = open_price * (
                    Decimal("1") + slippage if side == "buy" else Decimal("1") - slippage
                )
                if side == "buy":
                    qty = min(qty, cash / (price * (Decimal("1") + commission)))
                    if run["market"] == "CN":
                        qty = (qty / 100).to_integral_value(rounding=ROUND_DOWN) * 100
                    qty = qty.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    cost = qty * price
                    fee = cost * commission
                    new_qty = quantity + qty
                    average = (
                        (quantity * average + cost + fee) / new_qty if new_qty else Decimal("0")
                    )
                    cash -= cost + fee
                    quantity = new_qty
                    pnl = Decimal("0")
                else:
                    qty = min(qty, quantity)
                    proceeds = qty * price
                    fee = proceeds * commission
                    pnl = (price - average) * qty - fee
                    cash += proceeds - fee
                    quantity -= qty
                    realized += pnl
                    if quantity <= Decimal("0.00000001"):
                        quantity = Decimal("0")
                        average = Decimal("0")
                connection.execute(
                    "INSERT OR IGNORE INTO strategy_orders VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"sim_order_{signal_id}",
                        owner,
                        identifier,
                        signal_id,
                        run["environment"],
                        side,
                        _text(abs(delta)),
                        _text(qty),
                        "filled"
                        if qty >= abs(delta)
                        else "partial_expired"
                        if qty > 0
                        else "expired",
                        datetime.fromtimestamp(times[index], UTC).isoformat(),
                    ),
                )
                if qty > Decimal("0.00000001"):
                    connection.execute(
                        "INSERT OR IGNORE INTO strategy_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            f"fill_{uuid4().hex[:18]}",
                            owner,
                            identifier,
                            signal_id,
                            side,
                            _text(qty),
                            _text(price),
                            _text(fee),
                            run["symbol"].rsplit("-", 1)[-1]
                            if run["market"] == "CRYPTO"
                            else ("CNY" if run["market"] == "CN" else "USD"),
                            _text(pnl),
                            run["environment"],
                            datetime.fromtimestamp(times[index], UTC).isoformat(),
                            None,
                        ),
                    )
                    connection.execute(
                        "UPDATE strategy_signals SET status='filled',side=?,quantity=?,"
                        "reference_price=? WHERE id=?",
                        (side, _text(qty), _text(price), signal_id),
                    )
            elif run["environment"] != "platform_sim" and abs(delta) > Decimal("0.00000001"):
                side = "buy" if delta > 0 else "sell"
                qty = abs(delta)
                connection.execute(
                    "UPDATE strategy_signals SET status='recommendation',side=?,quantity=?,"
                    "reference_price=? WHERE id=?",
                    (side, _text(qty), _text(open_price), signal_id),
                )
            next_target = min(
                max(_decimal(targets.iloc[index]), Decimal("0")),
                _decimal(run["max_position"]),
            )
            if force_exit and quantity > Decimal("0.00000001"):
                next_target = Decimal("0")
            elif quantity <= Decimal("0.00000001"):
                force_exit = False
            reason = str(reasons.iloc[index])
            next_signal = f"sig_{uuid4().hex[:18]}"
            connection.execute(
                "INSERT OR IGNORE INTO strategy_signals "
                "(id,owner_id,run_id,bar_time,target,reason,status,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    next_signal,
                    owner,
                    identifier,
                    times[index],
                    _text(next_target),
                    reason,
                    "queued",
                    _iso(),
                ),
            )
            position = quantity * mark
            equity = cash + position
            return_rate = (equity - initial) / initial
            connection.execute(
                "INSERT OR IGNORE INTO strategy_equity VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    owner,
                    times[index],
                    _text(equity),
                    _text(cash),
                    _text(position),
                    _text(mark),
                    _text(return_rate),
                    _iso(),
                ),
            )
            connection.execute(
                "UPDATE strategy_runs SET cash=?,quantity=?,average_cost=?,realized_pnl=?,"
                "last_bar_time=?,pending_target=?,latest_signal=?,latest_error=NULL,"
                "exit_pending=?,updated_at=? WHERE id=?",
                (
                    _text(cash),
                    _text(quantity),
                    _text(average),
                    _text(realized),
                    times[index],
                    _text(next_target),
                    reason,
                    "1" if force_exit else "0",
                    _iso(),
                    identifier,
                ),
            )
            return True

    def ledger(
        self,
        owner: str,
        market: str | None,
        environment: str | None,
        run_id: str | None,
        account_id: str | None,
        release_id: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        offset: int,
    ):
        sql = """SELECT * FROM (
                 SELECT f.id,f.owner_id,f.run_id,f.signal_id,f.side,f.quantity,f.price,
                        f.fee,f.fee_currency,f.realized_pnl,f.environment,f.executed_at,
                        f.external_trade_id,r.symbol,r.market,r.account_id,r.release_id,
                        s.name AS strategy_name,s.version AS strategy_version,
                        'sim_order_'||f.signal_id AS order_id
                 FROM strategy_fills f JOIN strategy_runs r ON r.id=f.run_id
                 JOIN strategy_releases s ON s.id=r.release_id
                 UNION ALL
                 SELECT f.id,f.owner_id,f.run_id,f.signal_id,f.side,f.quantity,f.price,
                        f.fee,f.fee_currency,f.realized_pnl,f.environment,f.executed_at,
                        f.external_trade_id,f.symbol,r.market,f.account_id,r.release_id,
                        s.name AS strategy_name,s.version AS strategy_version,f.order_id
                 FROM strategy_external_fills f JOIN strategy_runs r ON r.id=f.run_id
                 JOIN strategy_releases s ON s.id=r.release_id
                 UNION ALL
                 SELECT f.id,f.owner_id,NULL,NULL,f.side,f.quantity,f.price,
                        f.fee,f.fee_currency,NULL,f.environment,f.executed_at,
                        f.external_trade_id,f.symbol,'CRYPTO',f.account_id,NULL,
                        '人工订单',NULL,f.order_id
                 FROM platform_manual_fills f
                 ) AS records WHERE owner_id=?"""
        args: list[Any] = [owner]
        for clause, value in (
            ("market", market),
            ("environment", environment),
            ("run_id", run_id),
            ("account_id", account_id),
            ("release_id", release_id),
        ):
            if value:
                sql += f" AND {clause}=?"
                args.append(value)
        if date_from:
            sql += " AND executed_at>=?"
            args.append(date_from)
        if date_to:
            sql += " AND executed_at<=?"
            args.append(date_to + "T23:59:59.999999+00:00" if len(date_to) == 10 else date_to)
        sql += " ORDER BY executed_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self._connect() as connection:
            fills = [dict(row) for row in connection.execute(sql, args)]
            accounts = self.list_accounts(owner)
            runs = self.list_runs(owner, market, environment)
        for fill in fills:
            fill["pnl_currency"] = (
                fill["symbol"].rsplit("-", 1)[-1]
                if fill["market"] == "CRYPTO" and "-" in fill["symbol"]
                else ("CNY" if fill["market"] == "CN" else "USD")
            )
        if run_id:
            runs = [run for run in runs if run["id"] == run_id]
        if account_id:
            runs = [run for run in runs if run["account_id"] == account_id]
        if release_id:
            runs = [run for run in runs if run["release_id"] == release_id]
        totals: dict[str, dict[str, Any]] = {}
        for run in runs:
            currency = run["currency"]
            total_key = f"{run['environment']}:{currency}"
            bucket = totals.setdefault(
                total_key,
                {
                    "environment": run["environment"],
                    "currency": currency,
                    "equity": Decimal("0"),
                    "cash": Decimal("0"),
                    "profit": Decimal("0"),
                    "valuation_complete": True,
                },
            )
            bucket["valuation_complete"] &= run["valuation_complete"]
            bucket["equity"] += _decimal(run["equity"])
            bucket["cash"] += _decimal(run["cash"])
            bucket["profit"] += _decimal(run["equity"]) - _decimal(run["initial_cash"])
        return {
            "accounts": accounts,
            "manual_accounts": self.manual_accounts(owner),
            "account_assets": [
                self.account_assets(owner, item["id"])
                for item in accounts
                if item["environment"] != "platform_sim"
                and (not environment or item["environment"] == environment)
                and (not account_id or item["id"] == account_id)
            ],
            "runs": runs,
            "totals": {
                key: {
                    name: _text(value) if isinstance(value, Decimal) else value
                    for name, value in values.items()
                }
                for key, values in totals.items()
            },
            "fills": fills,
            "positions": [
                {
                    "run_id": run["id"],
                    "account_id": run["account_id"],
                    "strategy_name": run["strategy_name"],
                    "strategy_version": run["strategy_version"],
                    "market": run["market"],
                    "environment": run["environment"],
                    "symbol": run["symbol"],
                    "quantity": run["quantity"],
                    "average_cost": run["average_cost"],
                    "mark_price": run["mark_price"],
                    "market_value": run["position_value"],
                    "unrealized_pnl": _text(
                        (_decimal(run["mark_price"]) - _decimal(run["average_cost"]))
                        * _decimal(run["quantity"])
                    )
                    if run["mark_price"] is not None
                    else None,
                }
                for run in runs
                if _decimal(run["quantity"]) > 0
            ],
            "limit": limit,
            "offset": offset,
        }


def runtime_router(store: StrategyRuntimeStore):
    router = APIRouter(tags=["strategy-runtime"])
    anchors = StrategyAnchorStore(store)
    private_runner = PrivateRunnerStore(store)

    @router.post("/api/v1/private-runner/signals")
    def private_signal(body: PrivateDecision):
        return private_runner.submit(body)

    def owner(request: Request):
        return request.state.user.id

    @router.get("/api/v1/strategy-releases/{identifier}/anchor")
    def anchor_status(identifier: str, request: Request):
        return anchors.status(owner(request), identifier)

    @router.post("/api/v1/strategy-releases/{identifier}/anchor/prepare")
    def anchor_prepare(identifier: str, body: AnchorPrepare, request: Request):
        return anchors.prepare(owner(request), identifier, body.address)

    @router.post("/api/v1/strategy-releases/{identifier}/anchor/confirm")
    def anchor_confirm(identifier: str, body: AnchorConfirm, request: Request):
        return anchors.confirm(owner(request), identifier, body.transaction_hash)

    @router.get("/api/v1/strategy-releases")
    def releases(request: Request, mine: bool | None = None):
        return store.list_releases(owner(request), mine)

    @router.post("/api/v1/strategy-releases/demo-example", status_code=201)
    def create_demo_example(request: Request):
        example = (
            Path(__file__).resolve().parents[2] / "strategy/examples/exchange-demo/release.json"
        )
        body = ReleaseCreate.model_validate_json(example.read_text())
        return store.create_release(owner(request), body)

    @router.post("/api/v1/strategy-releases/quote-probe", status_code=201)
    def create_quote_probe(request: Request):
        example = Path(__file__).resolve().parents[2] / "strategy/examples/quote-probe/release.json"
        return store.create_release(
            owner(request), ReleaseCreate.model_validate_json(example.read_text())
        )

    @router.post("/api/v1/strategy-releases", status_code=201)
    def create_release(body: ReleaseCreate, request: Request):
        return store.create_release(owner(request), body)

    @router.post("/api/v1/strategy-releases/{identifier}/publish")
    def publish_release(identifier: str, request: Request):
        return store.publish_release(owner(request), identifier)

    @router.put("/api/v1/trading/accounts/{identifier}/manual-link")
    def link_account(identifier: str, body: AccountLink, request: Request):
        return store.link_account(owner(request), identifier, body.manual_account_id)

    @router.post("/api/v1/trading/accounts/{identifier}/sync")
    def sync_account(identifier: str, request: Request):
        return store.sync_account(owner(request), identifier)

    @router.get("/api/v1/trading/accounts/{identifier}/assets")
    def account_assets(identifier: str, request: Request):
        return store.account_assets(owner(request), identifier)

    @router.get("/api/v1/strategy-subscriptions")
    def subscriptions(request: Request):
        return store.list_subscriptions(owner(request))

    @router.post("/api/v1/strategy-subscriptions", status_code=201)
    def subscribe(body: SubscriptionCreate, request: Request):
        return store.subscribe(owner(request), body.release_id)

    @router.delete("/api/v1/strategy-subscriptions/{identifier}")
    def unsubscribe(identifier: str, request: Request):
        return store.cancel_subscription(owner(request), identifier)

    @router.get("/api/v1/trading/accounts")
    def accounts(request: Request):
        return store.list_accounts(owner(request))

    @router.get("/api/v1/trading/runs")
    def runs(request: Request, market: str | None = None, environment: str | None = None):
        return store.list_runs(owner(request), market, environment)

    @router.post("/api/v1/trading/runs", status_code=201)
    def create_run(body: RunCreate, request: Request):
        return store.create_run(owner(request), body)

    @router.get("/api/v1/trading/runs/{identifier}")
    def run(identifier: str, request: Request):
        return store.get_run(owner(request), identifier, True)

    @router.post("/api/v1/trading/runs/{identifier}/{action}")
    def run_action(identifier: str, action: str, request: Request):
        if action == "tick":
            store.tick(owner(request), identifier)
            from app.demo_execution import execute_demo_signal

            execute_demo_signal(store, owner(request), identifier)
            return store.get_run(owner(request), identifier, True)
        return store.set_status(owner(request), identifier, action)

    @router.get("/api/v1/ledger/trades")
    def ledger(
        request: Request,
        market: str | None = None,
        environment: str | None = None,
        run_id: str | None = None,
        account_id: str | None = None,
        release_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        return store.ledger(
            owner(request),
            market,
            environment,
            run_id,
            account_id,
            release_id,
            date_from,
            date_to,
            limit,
            offset,
        )

    return router


class StrategyRuntimeScheduler:
    def __init__(self, store: StrategyRuntimeStore, interval_seconds: int = 10):
        self.store = store
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _run_once(self):
        from app.demo_credentials import owners

        account_owners = set(owners())
        if os.getenv("ATLAS_TRADING_OWNER_ID"):
            account_owners.add(os.environ["ATLAS_TRADING_OWNER_ID"])
        for owner in account_owners:
            try:
                accounts = self.store.list_accounts(owner)
            except Exception:
                continue
            for account in accounts:
                if account["environment"] != "platform_sim":
                    try:
                        self.store.sync_account(owner, account["id"])
                    except Exception:
                        continue
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT owner_id,id,status FROM strategy_runs WHERE status='active' "
                "OR (status IN ('paused','stopped','error') AND CAST(quantity AS REAL)>0)"
            ).fetchall()
        for row in rows:
            try:
                if row["status"] == "active":
                    self.store.tick(row["owner_id"], row["id"])
                    from app.demo_execution import execute_demo_signal

                    execute_demo_signal(self.store, row["owner_id"], row["id"])
                else:
                    self.store.mark_position(row["owner_id"], row["id"])
            except Exception:
                continue

    def _loop(self):
        while not self.stop_event.wait(self.interval_seconds):
            self._run_once()

    def start(self):
        # Resume from current data, without manufacturing fills while offline.
        # Existing exchange orders are reconciled independently.
        with self.store._connect() as connection:
            connection.execute("UPDATE strategy_runs SET needs_reanchor='1' WHERE status='active'")
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="strategy-runtime", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
