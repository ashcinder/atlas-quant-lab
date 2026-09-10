"""Read-only account handshake. No order, transfer or withdrawal routes.

Session memory only: deliberately not suitable for unattended deployment.
Credentials and exchange raw responses never enter the public ledger or logs.
"""
import asyncio
import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator
from app.auth import COOKIE_NAME


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange: Literal["binance", "okx"]
    api_key: SecretStr
    secret: SecretStr
    passphrase: SecretStr = SecretStr("")
    consent: Literal[True]

    @model_validator(mode="after")
    def credentials_valid(self):
        required = [self.api_key, self.secret] + ([self.passphrase] if self.exchange == "okx" else [])
        if any(not 1 <= len(v.get_secret_value()) <= 512 or any(c.isspace() for c in v.get_secret_value()) for v in required):
            raise ValueError("密钥字段为空或格式无效；OKX 还需要 API Passphrase")
        return self


_sessions: dict[str, tuple[float, Connection]] = {}
_last_read: dict[str, float] = {}
_lock = Lock()
router = APIRouter(prefix="/api/v1/exchange-account", tags=["exchange-account"])


def owner(request: Request) -> str:
    user = getattr(request.state, "user", None)
    cookie = request.cookies.get(COOKIE_NAME)
    if user is None or not cookie:
        raise HTTPException(401, "请先登录")
    return hashlib.sha256(f"{user.id}:{cookie}".encode()).hexdigest()


def get_config(key: str):
    with _lock:
        for expired in [k for k, (deadline, _) in _sessions.items() if deadline <= monotonic()]:
            _sessions.pop(expired, None)
            _last_read.pop(expired, None)
        entry = _sessions.get(key)
    return entry[1] if entry else None


def create_client(config: Connection):
    import ccxt.async_support as ccxt
    cls = {"binance": ccxt.binance, "okx": ccxt.okx}[config.exchange]
    return cls({"apiKey": config.api_key.get_secret_value(), "secret": config.secret.get_secret_value(),
                "password": config.passphrase.get_secret_value(), "timeout": 12000, "enableRateLimit": True,
                "options": {"defaultType": "spot", "fetchCurrencies": False}, "verbose": False})


def decimal_text(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("invalid balance")
    return format(number, "f")


async def read_balance(config: Connection):
    client = create_client(config)
    try:
        async with asyncio.timeout(25):
            balance = await client.fetch_balance({"type": "spot"})
        totals = balance.get("total")
        if not isinstance(totals, dict):
            raise ValueError("invalid balance schema")
        assets = []
        for currency, total in sorted(totals.items()):
            if total is None or Decimal(str(total)) == 0:
                continue
            assets.append({"currency": currency, "total": decimal_text(total),
                "free": decimal_text(balance.get("free", {}).get(currency)) if balance.get("free", {}).get(currency) is not None else None,
                "used": decimal_text(balance.get("used", {}).get(currency)) if balance.get("used", {}).get(currency) is not None else None})
        return {"exchange": config.exchange, "scope": "spot_or_unified_trading_account", "assets": assets,
                "observed_at": datetime.now(UTC).isoformat(), "can_trade": False}
    except (Exception, InvalidOperation):
        # No raw exception: vendor errors can embed signed URLs or credentials.
        raise HTTPException(502, "账户读取失败，请核对只读权限、IP 白名单、API 密钥、OKX Passphrase 和网络；未下单") from None
    finally:
        try:
            await client.close()
        except Exception:
            pass


@router.get("")
def status(request: Request):
    config = get_config(owner(request))
    return {"configured": config is not None, "exchange": config.exchange if config else None,
            "storage": "session_memory_8h", "can_trade": False}


@router.put("")
def configure(config: Connection, request: Request):
    key = owner(request)
    get_config(key)
    with _lock:
        if key not in _sessions and len(_sessions) >= 500:
            raise HTTPException(503, "连接配置容量已满")
        _sessions[key] = (monotonic() + 8 * 3600, config)
    return {"saved": True, "verified": False, "can_trade": False}


@router.delete("")
def disconnect(request: Request):
    key = owner(request)
    with _lock:
        _sessions.pop(key, None)
        _last_read.pop(key, None)
    return {"cleared": True}


@router.post("/balance")
async def balance(request: Request):
    key = owner(request)
    config = get_config(key)
    if config is None:
        raise HTTPException(409, "请先配置账户连接")
    with _lock:
        if monotonic() - _last_read.get(key, -1000) < 30:
            raise HTTPException(429, "请间隔至少 30 秒再读取账户")
        _last_read[key] = monotonic()
    return await read_balance(config)
