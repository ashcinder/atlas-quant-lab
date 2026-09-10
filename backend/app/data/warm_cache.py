"""Preload the catalog's daily research history without starting a web server.

Run from backend: .venv/bin/python -m app.data.warm_cache
No demo fallback, secrets or trading operations.
"""
import json
from app.catalog import ASSETS
from app.data.service import MarketDataService


def main():
    service = MarketDataService()
    failed = 0
    for asset in ASSETS:
        try:
            data = service.fetch(asset.symbol, asset.asset_class, "1d", None, None)
            print(json.dumps({"symbol": asset.symbol, "rows": len(data.frame), "source": data.source,
                "first": data.frame.index.min().isoformat(), "last": data.frame.index.max().isoformat(),
                "stale": data.is_stale}, ensure_ascii=False), flush=True)
            failed += int(data.is_stale)
        except Exception:
            failed += 1
            print(json.dumps({"symbol": asset.symbol, "status": "failed"}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
