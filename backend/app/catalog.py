from app.models import Asset

ASSETS = [
    Asset(
        symbol="BTC-USD",
        name="比特币",
        asset_class="crypto",
        exchange="CRYPTO",
        currency="USD",
        tags=["btc", "bitcoin", "加密货币"],
    ),
    Asset(
        symbol="ETH-USD",
        name="以太坊",
        asset_class="crypto",
        exchange="CRYPTO",
        currency="USD",
        tags=["eth", "ethereum", "加密货币"],
    ),
    Asset(
        symbol="SOL-USD",
        name="Solana",
        asset_class="crypto",
        exchange="CRYPTO",
        currency="USD",
        tags=["sol", "加密货币"],
    ),
    Asset(
        symbol="AAPL",
        name="Apple",
        asset_class="equity",
        exchange="NASDAQ",
        currency="USD",
        tags=["苹果", "美股"],
    ),
    Asset(
        symbol="MSFT",
        name="Microsoft",
        asset_class="equity",
        exchange="NASDAQ",
        currency="USD",
        tags=["微软", "美股"],
    ),
    Asset(
        symbol="NVDA",
        name="NVIDIA",
        asset_class="equity",
        exchange="NASDAQ",
        currency="USD",
        tags=["英伟达", "美股"],
    ),
    Asset(
        symbol="SPY",
        name="SPDR S&P 500 ETF",
        asset_class="etf",
        exchange="NYSE Arca",
        currency="USD",
        tags=["标普500", "ETF"],
    ),
    Asset(
        symbol="QQQ",
        name="Invesco QQQ",
        asset_class="etf",
        exchange="NASDAQ",
        currency="USD",
        tags=["纳斯达克", "ETF"],
    ),
    Asset(
        symbol="TLT",
        name="iShares 20+ Year Treasury",
        asset_class="etf",
        exchange="NASDAQ",
        currency="USD",
        tags=["美国长期国债", "ETF"],
    ),
    Asset(
        symbol="IEF",
        name="iShares 7-10 Year Treasury",
        asset_class="etf",
        exchange="NASDAQ",
        currency="USD",
        tags=["美国中期国债", "ETF"],
    ),
    Asset(
        symbol="GLD",
        name="SPDR Gold Shares",
        asset_class="etf",
        exchange="NYSE Arca",
        currency="USD",
        tags=["黄金ETF"],
    ),
    Asset(
        symbol="GC=F",
        name="黄金连续期货",
        asset_class="commodity",
        exchange="COMEX",
        currency="USD",
        tags=["gold", "黄金"],
    ),
    Asset(
        symbol="SI=F",
        name="白银连续期货",
        asset_class="commodity",
        exchange="COMEX",
        currency="USD",
        tags=["silver", "白银"],
    ),
    Asset(
        symbol="CL=F",
        name="WTI原油连续期货",
        asset_class="commodity",
        exchange="NYMEX",
        currency="USD",
        tags=["oil", "原油"],
    ),
    Asset(
        symbol="EURUSD=X",
        name="欧元/美元",
        asset_class="forex",
        exchange="FX",
        currency="USD",
        tags=["外汇", "eurusd"],
    ),
    Asset(
        symbol="USDJPY=X",
        name="美元/日元",
        asset_class="forex",
        exchange="FX",
        currency="JPY",
        tags=["外汇", "usdjpy"],
    ),
    Asset(
        symbol="000001.SS",
        name="上证指数",
        asset_class="index",
        exchange="SSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        tags=["A股", "指数"],
    ),
    Asset(
        symbol="510300.SS",
        name="沪深300ETF",
        asset_class="etf",
        exchange="SSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        tags=["A股", "ETF"],
    ),
    Asset(
        symbol="600519.SS",
        name="贵州茅台",
        asset_class="equity",
        exchange="SSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        tags=["A股"],
    ),
    Asset(
        symbol="300750.SZ",
        name="宁德时代",
        asset_class="equity",
        exchange="SZSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        tags=["A股", "创业板"],
    ),
    Asset(
        symbol="0700.HK",
        name="腾讯控股",
        asset_class="equity",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        tags=["港股"],
    ),
    Asset(
        symbol="^HSI",
        name="恒生指数",
        asset_class="index",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        tags=["港股", "指数"],
    ),
]


def find_asset(symbol: str, asset_class: str | None = None) -> Asset:
    normalized = symbol.strip().upper()
    for asset in ASSETS:
        if asset.symbol.upper() == normalized:
            return asset
    return Asset(
        symbol=normalized,
        name=normalized,
        asset_class=asset_class or "unknown",
        exchange="UNKNOWN",
        currency="USD",
        tags=["动态标的"],
    )


def search_assets(query: str, limit: int = 30) -> list[Asset]:
    needle = query.strip().lower()
    if not needle:
        return ASSETS[:limit]
    scored: list[tuple[int, Asset]] = []
    for asset in ASSETS:
        haystack = " ".join([asset.symbol, asset.name, asset.exchange, *asset.tags]).lower()
        if needle in haystack:
            score = 0 if asset.symbol.lower().startswith(needle) else 1
            scored.append((score, asset))
    matches = [
        asset for _, asset in sorted(scored, key=lambda item: (item[0], item[1].symbol))[:limit]
    ]
    # The static list is a useful watchlist, not a hard whitelist.  A ticker-
    # shaped query can be sent directly to the broad provider.
    ticker_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-=^")
    normalized = query.strip().upper()
    is_ticker = 1 < len(normalized) <= 24 and set(normalized) <= ticker_chars
    if is_ticker and not any(asset.symbol == normalized for asset in matches):
        asset_class = "unknown"
        exchange = "GLOBAL"
        currency = "USD"
        if normalized.endswith("=F"):
            asset_class, exchange = "commodity", "FUTURES"
        elif normalized.endswith("=X"):
            asset_class, exchange = "forex", "FX"
        elif normalized.endswith((".SS", ".SZ")):
            asset_class, exchange, currency = "equity", "CN", "CNY"
        elif normalized.endswith(".HK"):
            asset_class, exchange, currency = "equity", "HKEX", "HKD"
        elif normalized.endswith(("-USD", "-USDT")):
            asset_class, exchange = "crypto", "CRYPTO"
        matches.append(
            Asset(
                symbol=normalized,
                name=f"自定义标的 {normalized}",
                asset_class=asset_class,
                exchange=exchange,
                currency=currency,
                tags=["动态标的"],
            )
        )
    return matches[:limit]
