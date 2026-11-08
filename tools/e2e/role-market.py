"""Publish two deterministic snapshots for the author/subscriber journey."""
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

if os.environ.get("ATLAS_E2E_ISOLATED") != "1" or os.environ.get("ATLAS_DATA_DIR") != "/work/data":
    raise RuntimeError("An isolated E2E volume is required")
if not Path("/work/fixture.json").is_file():
    raise RuntimeError("Synthetic fixture has not been initialized")

sys.path.insert(0, "/app/backend")
import pandas as pd

from app.catalog import find_asset
from app.data.service import DataBundle
from app.market_publication import MarketPublication
from temporary_market import checkpoint, restore


def price(index):
    step = (index + 6) % 20
    return 100 + 2 * min(step, 20 - step)


def main():
    publications = MarketPublication()
    if sys.argv[1:] == ['restore']:
        result = restore(publications, 'role')
        Path('/work/role-market-start.txt').unlink(missing_ok=True)
        print(json.dumps(result))
        return
    end, extra = map(int, sys.argv[1:])
    if extra not in (0, 1) or end % 86400 or end + 2 * 86400 >= datetime.now(UTC).timestamp():
        raise ValueError("Expected a closed UTC day and one of the two fixture phases")
    rows = []
    for index in range(1000 + extra):
        opened, closed = price(index - 1), price(index)
        rows.append({"open": opened, "high": max(opened, closed) + .2,
                     "low": min(opened, closed) - .2, "close": closed, "volume": 1_000_000})
    times = pd.date_range(end=pd.Timestamp(end + extra * 86400, unit="s", tz="UTC"),
                          periods=len(rows), freq="D")
    asset = find_asset("BTC-USD", "crypto")
    bundle = DataBundle(asset, pd.DataFrame(rows, index=times), "synthetic-e2e-journey",
                        "Synthetic triangle pattern with a known next-bar opening price", datetime.now(UTC))
    checkpoint(publications, 'role', ['auto'])
    manifest = publications.publish({"symbol": asset.symbol, "asset_class": "crypto",
                                             "interval": "1d"}, bundle)
    clock = Path("/work/role-market-start.txt")
    if extra:
        clock.unlink(missing_ok=True)
    else:
        # Record a start after the initial bar and before the next bar's open.
        clock.write_text(str(end + 43200))
    print(json.dumps({key: manifest[key] for key in ("dataset_id", "end", "count")}))


if __name__ == "__main__":
    main()
