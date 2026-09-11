"""Manual spot trading and read-only reconciliation. Strategies require user confirmation."""

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
    strategy_run_id: str | None = Field(default=None, pattern=r"^run_[a-f0-9]+$")
    strategy_signal_id: str | None = Field(default=None, pattern=r"^sig_[a-f0-9]+$")


class ExchangeRejected(HTTPException):
    """A definitive exchange rejection, unlike a transport/processing timeout."""

    def __init__(self):
        super().__init__(422, "交易所明确拒绝请求，请核对权限、余额、最小数量和价格精度")


class Exchange:
    def __init__(self, venue: Venue, owner: str | None = None, demo_credentials=None):
        self.venue = venue
        prefix = "ATLAS_" + venue.upper() + "_"
        self.mode = os.getenv(prefix + "MODE", "demo")
        if self.mode not in {"demo", "live"}:
            raise HTTPException(503, "交易环境配置无效")
        self.key = os.getenv(prefix + "API_KEY", "")
        self.secret = os.getenv(prefix + "API_SECRET", "")
        self.passphrase = os.getenv(prefix + "PASSPHRASE", "")
        if owner is not None and demo_credentials is None:
            from app.demo_credentials import load

            demo_credentials = load(owner, venue)
        if demo_credentials is not None:
            self.mode = "demo"
            self.key = demo_credentials["api_key"]
            self.secret = demo_credentials["secret"]
            self.passphrase = demo_credentials.get("passphrase", "")
        elif owner is not None and owner != os.getenv("ATLAS_TRADING_OWNER_ID"):
            self.key = self.secret = self.passphrase = ""
        self.ui_configured = demo_credentials is not None
        self.configured = bool(self.key and self.secret and (venue != "okx" or self.passphrase))
        self.enabled = self.ui_configured or os.getenv("ATLAS_TRADING_ENABLED") == "1"
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

    def call(self, method, path, params=None, many=False, public=False):
        if not self.configured:
            raise HTTPException(503, "尚未配置此交易所账户，请查看接入说明")
        params = dict(params or {})
        body = ""
        if public:
            path += "?" + urlencode(params) if params else ""
            headers = {}
        elif self.venue == "binance":
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
        if not response.is_success or (
            not isinstance(data, dict) and not (many and isinstance(data, list))
        ):
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
            if many and rows == []:
                return []
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise HTTPException(502, "欧易响应不完整，请查询订单状态")
            if rows[0].get("sCode", "0") != "0":
                raise HTTPException(502, "欧易拒绝订单，请检查余额、最小数量和价格精度")
            return rows if many else rows[0]
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

    def spot_prices(self):
        """One public venue snapshot; unavailable direct USDT pairs stay unknown."""
        rows = self.call(
            "GET",
            "/api/v3/ticker/price" if self.venue == "binance" else "/api/v5/market/tickers",
            {} if self.venue == "binance" else {"instType": "SPOT"},
            many=True,
            public=True,
        )
        prices = {"USDT": Decimal("1")}
        for row in rows:
            symbol = row.get("symbol", row.get("instId", ""))
            suffix = "USDT" if self.venue == "binance" else "-USDT"
            if not symbol.endswith(suffix):
                continue
            try:
                price = Decimal(str(row.get("price", row.get("last"))))
                if price.is_finite() and price > 0:
                    prices[symbol[: -len(suffix)]] = price
            except Exception:
                continue
        return prices

    def ticker(self, symbol):
        if self.venue == "binance":
            data = self.call(
                "GET", "/api/v3/ticker/price", {"symbol": symbol.replace("-", "")}, public=True
            )
            value = data.get("price")
        else:
            data = self.call("GET", "/api/v5/market/ticker", {"instId": symbol}, public=True)
            value = data.get("last")
        try:
            price = Decimal(str(value))
        except Exception as exc:
            raise HTTPException(502, "交易所最新行情响应不完整") from exc
        if not price.is_finite() or price <= 0:
            raise HTTPException(502, "交易所最新行情响应不完整")
        return price

    def validate_order(self, order: OrderInput):
        """Validate a linked suggestion against the latest venue price and spot filters."""
        market_price = self.ticker(order.symbol)
        try:
            maximum_deviation = Decimal(os.getenv("ATLAS_TRADING_MAX_PRICE_DEVIATION", "0.10"))
        except Exception as exc:
            raise HTTPException(503, "限价偏离配置无效") from exc
        if not maximum_deviation.is_finite() or not Decimal("0") <= maximum_deviation <= 1:
            raise HTTPException(503, "限价偏离配置无效")
        if abs(order.price - market_price) / market_price > maximum_deviation:
            raise HTTPException(422, "策略订单限价偏离交易所最新价超过允许范围")

        price_step, quantity_step, minimum_quantity, minimum_notional = self.spot_rules(
            order.symbol
        )
        if order.price % price_step or order.quantity % quantity_step:
            raise HTTPException(422, "订单价格或数量不符合交易所精度规则")
        if order.quantity < minimum_quantity or order.quantity * order.price < minimum_notional:
            raise HTTPException(422, "订单低于交易所最小数量或最小金额")
        return market_price

    def spot_rules(self, symbol):
        if self.venue == "binance":
            data = self.call(
                "GET",
                "/api/v3/exchangeInfo",
                {"symbol": symbol.replace("-", "")},
                public=True,
            )
            symbols = data.get("symbols", [])
            if not symbols or not isinstance(symbols[0], dict):
                raise HTTPException(502, "交易所交易规则响应不完整")
            filters = {
                item.get("filterType"): item
                for item in symbols[0].get("filters", [])
                if isinstance(item, dict)
            }
            price_step = Decimal(str(filters.get("PRICE_FILTER", {}).get("tickSize", "0")))
            lot = filters.get("LOT_SIZE", {})
            quantity_step = Decimal(str(lot.get("stepSize", "0")))
            minimum_quantity = Decimal(str(lot.get("minQty", "0")))
            notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
            minimum_notional = Decimal(str(notional.get("minNotional", "0")))
        else:
            instrument = self.call(
                "GET",
                "/api/v5/public/instruments",
                {"instType": "SPOT", "instId": symbol},
                public=True,
            )
            price_step = Decimal(str(instrument.get("tickSz", "0")))
            quantity_step = Decimal(str(instrument.get("lotSz", "0")))
            minimum_quantity = Decimal(str(instrument.get("minSz", "0")))
            minimum_notional = Decimal("0")
        if price_step <= 0 or quantity_step <= 0:
            raise HTTPException(502, "交易所交易规则响应不完整")
        return price_step, quantity_step, minimum_quantity, minimum_notional

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

    def fills(self, symbol, exchange_order_id):
        if not exchange_order_id:
            return []
        if self.venue == "binance":
            rows = []
            cursor = 0
            for _ in range(100):
                page = self.call(
                    "GET",
                    "/api/v3/myTrades",
                    {
                        "symbol": symbol.replace("-", ""),
                        "orderId": exchange_order_id,
                        "fromId": cursor,
                        "limit": 1000,
                    },
                    many=True,
                )
                rows.extend(page)
                if len(page) < 1000:
                    break
                next_cursor = max(int(row["id"]) for row in page) + 1
                if next_cursor <= cursor:
                    raise HTTPException(502, "成交分页未前进，请稍后重新同步")
                cursor = next_cursor
            else:
                raise HTTPException(502, "成交分页超过单次同步范围，保留待对账状态")
            return [
                {
                    "trade_id": str(row.get("id", "")),
                    "price": str(row.get("price", "")),
                    "quantity": str(row.get("qty", "")),
                    "fee": str(row.get("commission", "0")),
                    "fee_currency": str(row.get("commissionAsset", "")),
                    "executed_at": datetime.fromtimestamp(
                        int(row.get("time", 0)) / 1000, UTC
                    ).isoformat(),
                }
                for row in rows
                if isinstance(row, dict)
            ]
        rows = []
        cursor = None
        for _ in range(100):
            params = {
                "instType": "SPOT",
                "instId": symbol,
                "ordId": exchange_order_id,
                "limit": "100",
            }
            if cursor:
                params["after"] = cursor
            page = self.call("GET", "/api/v5/trade/fills-history", params, many=True)
            rows.extend(page)
            if len(page) < 100:
                break
            next_cursor = str(page[-1].get("billId", ""))
            if not next_cursor or next_cursor == cursor:
                raise HTTPException(502, "成交分页未前进，请稍后重新同步")
            cursor = next_cursor
        else:
            raise HTTPException(502, "成交分页超过单次同步范围，保留待对账状态")
        return [
            {
                "trade_id": str(row.get("tradeId", "")),
                "price": str(row.get("fillPx", "")),
                "quantity": str(row.get("fillSz", "")),
                "fee": str(-Decimal(str(row.get("fee", "0")))),
                "fee_currency": str(row.get("feeCcy", "")),
                "executed_at": datetime.fromtimestamp(
                    int(row.get("fillTime") or row.get("ts", 0)) / 1000, UTC
                ).isoformat(),
            }
            for row in rows
            if isinstance(row, dict)
        ]

    @staticmethod
    def normalized(data):
        # Never relay upstream error text, headers or signed URLs to the browser/log.
        return {
            "exchange_order_id": str(data.get("orderId", data.get("ordId", ""))),
            "exchange_status": data.get("status", data.get("state", "acknowledged")),
            "filled_quantity": data.get("executedQty", data.get("accFillSz", "")),
        }
