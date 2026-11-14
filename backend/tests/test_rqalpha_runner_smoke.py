import copy
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SPEC = spec_from_file_location(
    "rqalpha_runner_smoke",
    Path(__file__).resolve().parents[2] / "deploy/rqalpha_runner_smoke.py",
)
smoke = module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_economic_comparison_keeps_fills_but_not_generated_identifiers():
    first = {"equity": [{"time": 1, "equity": 100, "cash": 10, "market_value": 90}],
             "trades": [{"time": 1, "symbol": "000001.SZ", "side": "buy", "quantity": 100,
                         "price": 1, "fee": 5, "commission": 5, "tax": 0,
                         "order_id": "first", "exec_id": "first"}],
             "positions": [], "corporate_actions": [], "rejections": []}
    second = copy.deepcopy(first)
    second["trades"][0].update(order_id="second", exec_id="second")
    assert smoke.economic_result(first) == smoke.economic_result(second)
    second["trades"][0]["price"] = 2
    assert smoke.economic_result(first) != smoke.economic_result(second)


def test_runner_smoke_requires_explicit_data_directory(monkeypatch):
    monkeypatch.delenv("ATLAS_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "argv", ["rqalpha_runner_smoke.py", "--symbols", "600519.SS",
                                    "000001.SZ", "--start", "2025-01-02", "--end", "2025-12-31"])
    with pytest.raises(SystemExit, match="独立 ATLAS_DATA_DIR"):
        smoke.main()
