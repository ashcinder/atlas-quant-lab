"""Manual spot trading. Credentials stay on the server; no strategy execution hooks."""

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

Venue = Literal["binance", "okx"]


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    venue: Venue
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,15}-USDT$")
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=12, allow_inf_nan=False)
    price: Decimal = Field(gt=0, max_digits=24, decimal_places=12, allow_inf_nan=False)


class ExchangeRejected(HTTPException):
    """A definitive exchange rejection, unlike a transport/processing timeout."""

    def __init__(self):
        super().__init__(422, "交易所明确拒绝请求，请核对权限、余额、最小数量和价格精度")


class Exchange:
    def __init__(self, venue: Venue):
        self.venue = venue
        prefix = "ATLAS_" + venue.upper() + "_"
        self.mode = os.getenv(prefix + "MODE", "demo")
        if self.mode not in {"demo", "live"}:
            raise HTTPException(503, "交易环境配置无效")
        self.key = os.getenv(prefix + "API_KEY", "")
        self.secret = os.getenv(prefix + "API_SECRET", "")
        self.passphrase = os.getenv(prefix + "PASSPHRASE", "")
        self.configured = bool(self.key and self.secret and (venue != "okx" or self.passphrase))
        self.enabled = os.getenv("ATLAS_TRADING_ENABLED") == "1"
        self.live_enabled = os.getenv("ATLAS_TRADING_LIVE_ENABLED") == "1"
        self.base = (
            ("https://testnet.binance.vision" if self.mode == "demo" else "https://api.binance.com")
            if venue == "binance"
            else "https://www.okx.com"
        )

    def fingerprint(self):
        return hashlib.sha256((self.venue + self.mode + self.key).encode()).hexdigest()

    def can_trade(self):
        return self.configured and self.enabled and (self.mode == "demo" or self.live_enabled)

    def call(self, method, path, params=None):
        if not self.configured:
            raise HTTPException(503, "尚未配置此交易所账户，请查看接入说明")
        params = dict(params or {})
        body = ""
        if self.venue == "binance":
            params.update(timestamp=int(time.time() * 1000), recvWindow=5000)
            query = urlencode(params)
            signature = hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            path += "?" + query + "&signature=" + signature
            headers = {"X-MBX-APIKEY": self.key}
        else:
            stamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            if method == "GET" and params:
                path += "?" + urlencode(params)
            elif params:
                body = json.dumps(params, separators=(",", ":"))
            signed = hmac.new(
                self.secret.encode(), (stamp + method + path + body).encode(), hashlib.sha256
            ).digest()
            headers = {
                "OK-ACCESS-KEY": self.key,
                "OK-ACCESS-SIGN": base64.b64encode(signed).decode(),
                "OK-ACCESS-TIMESTAMP": stamp,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }
            if self.mode == "demo":
                headers["x-simulated-trading"] = "1"
        try:
            # No automatic retries: a timeout can occur after an order was accepted.
            with httpx.Client(timeout=12, follow_redirects=False) as client:
                response = client.request(method, self.base + path, headers=headers, content=body)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, "交易所响应未确认，请查询订单状态；不要重复下单") from exc
        if (
            self.venue == "binance"
            and isinstance(data, dict)
            and 400 <= response.status_code < 500
            and isinstance(data.get("code"), int)
            and data["code"] < 0
            and data["code"] not in {-1000, -1001, -1006, -1007}
        ):
            raise ExchangeRejected()
        if not response.is_success or not isinstance(data, dict):
            raise HTTPException(502, "交易所请求失败，请核对权限、网络和订单状态")
        if self.venue == "okx":
            rows = data.get("data")
            code = str(data.get("code", ""))
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                code = str(rows[0].get("sCode", code))
            if code.startswith(("51", "501")) or code in {"50011", "50061"}:
                raise ExchangeRejected()
            if data.get("code") != "0":
                raise HTTPException(502, "欧易处理结果未确认，请查询订单状态")
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise HTTPException(502, "欧易响应不完整，请查询订单状态")
            if rows[0].get("sCode", "0") != "0":
                raise HTTPException(502, "欧易拒绝订单，请检查余额、最小数量和价格精度")
            return rows[0]
        return data

    def account(self):
        data = self.call(
            "GET", "/api/v3/account" if self.venue == "binance" else "/api/v5/account/balance"
        )
        rows = data.get("balances") if self.venue == "binance" else data.get("details")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(502, "账户响应不完整，请重新查询")
        return [
            {
                "asset": row.get("asset", row.get("ccy")),
                "available": row.get("free", row.get("availBal", "")),
                "locked": row.get("locked", row.get("frozenBal", "")),
            }
            for row in rows
        ]

    def place(self, order: OrderInput, client_id: str):
        if self.venue == "binance":
            data = self.call(
                "POST",
                "/api/v3/order",
                {
                    "symbol": order.symbol.replace("-", ""),
                    "side": order.side.upper(),
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "quantity": format(order.quantity, "f"),
                    "price": format(order.price, "f"),
                    "newClientOrderId": client_id,
                },
            )
        else:
            data = self.call(
                "POST",
                "/api/v5/trade/order",
                {
                    "instId": order.symbol,
                    "tdMode": "cash",
                    "side": order.side,
                    "ordType": "limit",
                    "sz": format(order.quantity, "f"),
                    "px": format(order.price, "f"),
                    "clOrdId": client_id,
                },
            )
        if not data.get("orderId", data.get("ordId")):
            raise HTTPException(502, "交易所未返回订单编号，请查询订单状态")
        return self.normalized(data)

    def lookup(self, symbol, client_id, cancel=False):
        if self.venue == "binance":
            data = self.call(
                "DELETE" if cancel else "GET",
                "/api/v3/order",
                {
                    "symbol": symbol.replace("-", ""),
                    "origClientOrderId": client_id,
                },
            )
        else:
            data = self.call(
                "POST" if cancel else "GET",
                "/api/v5/trade/cancel-order" if cancel else "/api/v5/trade/order",
                {"instId": symbol, "clOrdId": client_id},
            )
        return self.normalized(data)

    @staticmethod
    def normalized(data):
        # Never relay upstream error text, headers or signed URLs to the browser/log.
        return {
            "exchange_order_id": str(data.get("orderId", data.get("ordId", ""))),
            "exchange_status": data.get("status", data.get("state", "acknowledged")),
            "filled_quantity": data.get("executedQty", data.get("accFillSz", "")),
        }
