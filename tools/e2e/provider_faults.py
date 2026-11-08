"""Durable synthetic Binance scenarios used only by the isolated QA entry point."""
from contextlib import closing
import json
import sqlite3
import time

import httpx


def binance_partial(request, query):
    """Accept one order, lose its acknowledgement, and persist its partial fill."""
    if not request.headers.get("X-MBX-APIKEY", "").startswith("synthetic-partial-"):
        return None
    if not request.url.path.endswith(("/order", "/myTrades")):
        return None
    with closing(sqlite3.connect("/work/synthetic-binance.sqlite", timeout=10)) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                status TEXT NOT NULL,
                quantity TEXT NOT NULL,
                price TEXT NOT NULL,
                accepted_ms INTEGER NOT NULL,
                submit_calls INTEGER NOT NULL
            )"""
        )
        db.row_factory = sqlite3.Row
        if request.url.path.endswith("/myTrades"):
            row = db.execute(
                "SELECT * FROM orders WHERE sequence=?", (query.get("orderId"),)
            ).fetchone()
            fills = [] if row is None else [{
                "id": row["sequence"],
                "price": row["price"],
                "qty": "0.0004",
                "commission": "0.004",
                "commissionAsset": "USDT",
                "time": row["accepted_ms"],
            }]
            return httpx.Response(200, json=fills)

        client_id = query.get("newClientOrderId", query.get("origClientOrderId"))
        if request.method == "POST":
            db.execute(
                """INSERT INTO orders
                   (client_id, symbol, status, quantity, price, accepted_ms, submit_calls)
                   VALUES (?, ?, 'PARTIALLY_FILLED', ?, ?, ?, 1)
                   ON CONFLICT(client_id) DO UPDATE SET submit_calls=submit_calls+1""",
                (client_id, query["symbol"], query["quantity"], query["price"], int(time.time()*1000)),
            )
            db.commit()
            raise httpx.ReadTimeout("Synthetic order acknowledgement lost", request=request)

        if request.method == "DELETE":
            db.execute("UPDATE orders SET status='CANCELED' WHERE client_id=?", (client_id,))
            db.commit()
        row = db.execute("SELECT * FROM orders WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            return httpx.Response(400, json={"code": -2013, "msg": "Synthetic order absent"})
        return httpx.Response(200, json={
            "orderId": row["sequence"],
            "clientOrderId": row["client_id"],
            "symbol": row["symbol"],
            "status": row["status"],
            "origQty": row["quantity"],
            "price": row["price"],
            "executedQty": "0.0004",
        })


def bkc_fixture_mode(raw_decoded):
    """Choose a fault using public synthetic destinations, without reading any key."""
    if raw_decoded.get("to", "").lower() == "0x" + "51" * 20:
        return "lost_reply"
    if raw_decoded.get("to", "").lower() == "0x" + "52" * 20:
        return "reverted"
    return "success"


okx_orders = {}


def okx_fixture(request):
    """Synthetic public data and authenticated demo order transport for OKX."""
    if request.url.host != 'www.okx.com':
        return None
    path = request.url.path
    params = json.loads(request.content) if request.content else dict(request.url.params)
    if path.startswith('/api/v5/account/') or path.startswith('/api/v5/trade/'):
        if request.headers.get('x-simulated-trading') != '1' or not request.headers.get('OK-ACCESS-KEY', '').startswith('synthetic-'):
            raise httpx.ConnectError('Only synthetic OKX demo requests are permitted', request=request)
    if path.endswith('/account/balance'):
        rows = [{'details': [{'ccy': 'USDT', 'availBal': '10000', 'frozenBal': '0'}, {'ccy': 'BTC', 'availBal': '1', 'frozenBal': '0'}]}]
    elif path.endswith(('/market/ticker', '/market/tickers')):
        rows = [{'instId': 'BTC-USDT', 'last': '10000'}]
    elif path.endswith('/public/instruments'):
        rows = [{'instId': 'BTC-USDT', 'tickSz': '0.01', 'lotSz': '0.00001', 'minSz': '0.00001'}]
    elif path.endswith('/fills-history'):
        rows = []
    elif path.endswith(('/trade/order', '/trade/cancel-order')):
        identifier = params.get('clOrdId')
        if path.endswith('/trade/order') and request.method == 'POST':
            okx_orders.setdefault(identifier, {'ordId': str(len(okx_orders) + 1), 'clOrdId': identifier,
                                              'state': 'live', 'accFillSz': '0', 'sCode': '0'})
        row = okx_orders.get(identifier)
        if row is None:
            return httpx.Response(200, json={'code': '51603', 'data': []})
        if path.endswith('/cancel-order'):
            row['state'] = 'canceled'
        rows = [dict(row)]
    else:
        raise httpx.ConnectError('Unrecognized synthetic OKX request', request=request)
    return httpx.Response(200, json={'code': '0', 'data': rows})


def bkc_receipt_status(decoded, transactions):
    if bkc_fixture_mode(decoded) != 'reverted':
        return '0x1'
    resource = json.loads(bytes.fromhex(decoded['data'][2:])).get('release_id')
    for tx in transactions.values():
        if tx.get('fixture_receipt_status') == '0x0' and json.loads(bytes.fromhex(tx['input'][2:])).get('release_id') == resource:
            return '0x1'
    return '0x0'
