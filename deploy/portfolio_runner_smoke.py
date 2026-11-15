"""Real gVisor portfolio smoke using only synthetic data and self-authored code."""
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.lab_portfolio_engine import PortfolioEngine, run_portfolio_backtest  # noqa: E402
from app.lab_portfolio_market import session_windows  # noqa: E402
from app.sandbox import PortfolioSandbox, RunnerFailure, portfolio_runner_status  # noqa: E402

SYMBOLS = ["600001.SS", "600002.SS"]
SETTINGS = {"symbols": SYMBOLS, "interval": "1d", "initial_capital": 10_000}
SCRIPT = """
from atlas_strategy_sdk import TargetPosition
import numpy as np
import pandas as pd
import scipy
import sklearn
import os
import socket

class Strategy:
    def initialize(self, params):
        self.steps = 0

    def import_state(self, state):
        self.steps = state["steps"]

    def export_state(self):
        return {"steps": self.steps}

    def generate_targets(self, ctx):
        assert len(ctx.symbols) == 2
        assert all(bar.timestamp <= ctx.now for rows in ctx.bars.values() for bar in rows)
        assert not os.path.exists("/var/run/docker.sock")
        assert not os.path.exists(__CANARY__)
        assert not os.environ.get("ATLAS_SESSION_SECRET")
        try:
            open("/strategy/strategy.py", "w")
        except OSError:
            pass
        else:
            raise AssertionError("strategy mount writable")
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=0.2)
        except OSError:
            pass
        else:
            raise AssertionError("network not isolated")
        self.steps += 1
        score = pd.Series(np.asarray([rows[-1].close for rows in ctx.bars.values()]))
        strongest = tuple(ctx.bars)[int(score.idxmax())]
        return [TargetPosition(strongest, 0.5, 1, "smoke")]
"""


def package(source):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("strategy.py", source)
        archive.writestr("strategy.json", json.dumps({
            "id": "portfolio_smoke", "name": "Portfolio smoke", "version": "1.0.0",
            "language": "python", "entrypoint": "strategy.py:Strategy",
            "description": "Synthetic data sandbox smoke test",
            "asset_classes": ["cn_stock"], "intervals": ["1d"],
        }))
    return buffer.getvalue()


def event(day):
    opening, closing = session_windows(date.fromisoformat(day), "1d")[0]
    return {"time": closing, "bars": {
        symbol: {"open_time": opening, "open": price, "close": price, "high": price,
                 "low": price, "volume": 100_000, "lot_size": 100,
                 "limit_up": price * 1.1, "limit_down": price * 0.9}
        for symbol, price in zip(SYMBOLS, [10, 20], strict=True)
    }}


def main():
    ready, reason = portfolio_runner_status()
    if not ready:
        raise SystemExit(f"Portfolio gVisor unavailable: {reason}")
    events = [event(day) for day in ("2025-01-02", "2025-01-03", "2025-01-06")]
    with TemporaryDirectory(prefix="atlas-portfolio-host-canary-") as directory:
        canary = Path(directory) / "private"
        canary.write_text("must not be visible in guest")
        archive = package(SCRIPT.replace("__CANARY__", repr(str(canary))))
        result = run_portfolio_backtest(archive, events, SETTINGS)
        assert result["trades"] and result["proof_status"] == "unverified"

        engine = PortfolioEngine(SETTINGS)
        with PortfolioSandbox(archive, {}) as runner:
            engine.step(events[0], runner.exchange)
            assert runner.checkpoint() == {"steps": 1}
        engine = PortfolioEngine(SETTINGS, json.loads(json.dumps(engine.snapshot())))
        with PortfolioSandbox(archive, {}, checkpoint=engine.strategy_state) as runner:
            runner.seed_history(engine.history())
            next_point = engine.step(events[1], runner.exchange)
            assert next_point["trades"] and runner.checkpoint() == {"steps": 2}
    for name, body in (
        ("timeout", "while True: pass"),
        ("memory", "self.buffer = bytearray(2_000_000_000)"),
        ("output", "import os; os.write(1, b'x' * 5_000_000)"),
    ):
        attack = package(f"class Strategy:\n    def generate_orders(self, context):\n        {body}\n        return []\n")
        try:
            run_portfolio_backtest(attack, events, SETTINGS)
        except RunnerFailure:
            print(f"Rejected actual portfolio sandbox {name} attack", flush=True)
        else:
            raise AssertionError(f"{name} attack was not rejected")
    print("Real portfolio gVisor, locked libraries, multi-stock causal data, isolation and restart passed.")


if __name__ == "__main__":
    main()
