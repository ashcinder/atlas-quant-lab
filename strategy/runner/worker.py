"""Runs ONLY inside the sandbox image. All output is an untrusted proposal.

The parent owns data access, accounting, AI policy and final risk limits.
"""
import contextlib
from datetime import datetime, UTC
import importlib.util
import json
from pathlib import Path
import sys
from types import MappingProxyType

from atlas_strategy_sdk import Bar, PortfolioSnapshot, StrategyContext


def main():
    strategy = None
    parameters = {}
    wire = sys.stdout
    for line in sys.stdin:
        message = json.loads(line)
        result = {"request_id": message["request_id"], "ok": False}
        try:
            with contextlib.redirect_stdout(sys.stderr):
                if message["kind"] == "init":
                    filename, class_name = message["entrypoint"].split(":")
                    path = (Path("/strategy") / filename).resolve()
                    if not path.is_relative_to("/strategy"):
                        raise ValueError("entrypoint")
                    sys.path.insert(0, "/strategy")
                    spec = importlib.util.spec_from_file_location("uploaded_strategy", path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = module
                    spec.loader.exec_module(module)
                    parameters = MappingProxyType(message["parameters"])
                    strategy = getattr(module, class_name)()
                    strategy.initialize(parameters)
                else:
                    now = datetime.fromtimestamp(message["time"], UTC)
                    symbol = message["symbol"]
                    bars = tuple(Bar(symbol, datetime.fromtimestamp(b["time"], UTC),
                                     b["open"], b["high"], b["low"], b["close"], b["volume"])
                                 for b in message["bars"])
                    portfolio = PortfolioSnapshot(now, message["equity"], message["cash"],
                        MappingProxyType({symbol: message["quantity"]}),
                        MappingProxyType({symbol: message["weight"]}),
                        drawdown=message["drawdown"])
                    context = StrategyContext(now, MappingProxyType({symbol: bars}), portfolio,
                                              parameters, message["run_id"], 0)
                    result["targets"] = [{"symbol": t.symbol, "target_weight": t.target_weight}
                                         for t in strategy.generate_targets(context)]
            result["ok"] = True
        except BaseException:
            # Code, prompts, parameters and tracebacks are deliberately not exported.
            result = {"request_id": message["request_id"], "ok": False}
        wire.write(json.dumps(result, allow_nan=False) + "\n")
        wire.flush()


if __name__ == "__main__":
    main()
