"""Runs ONLY inside the sandbox image. All output is an untrusted proposal."""

from collections import deque
import contextlib
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import MappingProxyType

from atlas_strategy_sdk import Bar, PortfolioSnapshot, StrategyContext

PORTFOLIO_PROTOCOL = "atlas.portfolio/v1"
HISTORY_BARS = 128
MAX_PROPOSALS = 300


def _time(value):
    return datetime.fromtimestamp(value, UTC)


def _bars(symbol, rows):
    for row in rows:
        yield Bar(
            symbol, _time(row["time"]), row["open"], row["high"], row["low"], row["close"], row["volume"],
            open_time=_time(row["open_time"]) if row.get("open_time") is not None else None,
            limit_up=row.get("limit_up"), limit_down=row.get("limit_down"),
            reference=row.get("reference"), split_ratio=row.get("split_ratio", 1.0),
            cash_dividend=row.get("cash_dividend", 0.0), research_close=row.get("research_close"),
            daily=MappingProxyType(row["daily"]) if row.get("daily") is not None else None,
            touch_evidence=row.get("touch_evidence", False),
        )


def _load(entrypoint):
    filename, class_name = entrypoint.split(":")
    root = Path("/strategy")
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("entrypoint")
    # Packaged strategies may place their entry file alongside sibling modules.
    sys.path.insert(0, str(root))
    if path.parent != root:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("uploaded_strategy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return getattr(module, class_name)


class PortfolioProtocol:
    def __init__(self, factory, parameters, checkpoint):
        self.factory, self.parameters = factory, parameters
        self.history = {}
        self.strategy = self._new_strategy()
        self.stateful = callable(getattr(self.strategy, "export_state", None))
        if self.stateful != callable(getattr(self.strategy, "import_state", None)):
            raise ValueError("state contract")
        self.orders = callable(getattr(self.strategy, "generate_orders", None))
        if self.orders == callable(getattr(self.strategy, "generate_targets", None)):
            raise ValueError("exactly one proposal mode required")
        if checkpoint is not None:
            if not self.stateful:
                raise ValueError("stateless checkpoint")
            self.strategy.import_state(checkpoint)

    def _new_strategy(self):
        instance = self.factory()
        initialize = getattr(instance, "initialize", None)
        if initialize is not None:
            initialize(self.parameters)
        return instance

    def seed(self, bars):
        for symbol, rows in bars.items():
            self.history.setdefault(symbol, deque(maxlen=HISTORY_BARS)).extend(_bars(symbol, rows))

    def step(self, message):
        now = _time(message["time"])
        self.seed({symbol: [bar] for symbol, bar in message["bars"].items()})
        portfolio = PortfolioSnapshot(
            now, message["equity"], message["cash"], MappingProxyType(message["positions"]),
            MappingProxyType(message["weights"]), drawdown=message["drawdown"],
            sellable=MappingProxyType(message["sellable"]),
        )
        context = StrategyContext(
            now, MappingProxyType({symbol: tuple(rows) for symbol, rows in self.history.items()}),
            portfolio, self.parameters, message["run_id"], 0, symbols=tuple(message["symbols"]),
            suspended=tuple(message["suspended"]), session_date=message["session_date"],
            fills=tuple(MappingProxyType(fill) for fill in message["fills"]),
            daily=MappingProxyType({symbol: MappingProxyType(bar) for symbol, bar in message.get("daily", {}).items()}),
        )
        strategy = self.strategy if self.stateful else self._new_strategy()
        key = "orders" if self.orders else "targets"
        proposals = strategy.generate_orders(context) if self.orders else strategy.generate_targets(context)
        rows = []
        for proposal in proposals:
            if len(rows) >= MAX_PROPOSALS:
                raise ValueError("too many proposals")
            if self.orders:
                if proposal.order_type != "market" or proposal.limit_price is not None:
                    raise ValueError("only market intents supported")
                row = {"side": proposal.side, "quantity": proposal.quantity}
            else:
                row = {"target_weight": proposal.target_weight}
            rows.append({"symbol": proposal.symbol, "reason_code": proposal.reason_code, **row})
        response = {key: rows}
        if self.stateful and message.get("save_state"):
            response["checkpoint"] = strategy.export_state()
        return response


def main():
    strategy = portfolio_protocol = None
    parameters = {}
    wire = sys.stdout
    for line in sys.stdin:
        message = json.loads(line)
        result = {"request_id": message["request_id"]}
        try:
            with contextlib.redirect_stdout(sys.stderr):
                kind = message["kind"]
                if kind == "init":
                    factory = _load(message["entrypoint"])
                    parameters = MappingProxyType(message["parameters"])
                    if message.get("protocol") == PORTFOLIO_PROTOCOL:
                        portfolio_protocol = PortfolioProtocol(factory, parameters, message.get("checkpoint"))
                        result.update(protocol=PORTFOLIO_PROTOCOL, stateful=portfolio_protocol.stateful)
                    else:
                        strategy = factory()
                        strategy.initialize(parameters)
                elif kind == "portfolio_history" and portfolio_protocol:
                    portfolio_protocol.seed(message["bars"])
                elif kind == "portfolio_step" and portfolio_protocol:
                    result.update(portfolio_protocol.step(message))
                elif kind == "step" and strategy is not None:
                    now, symbol = _time(message["time"]), message["symbol"]
                    portfolio = PortfolioSnapshot(
                        now, message["equity"], message["cash"],
                        MappingProxyType({symbol: message["quantity"]}),
                        MappingProxyType({symbol: message["weight"]}), drawdown=message["drawdown"],
                    )
                    context = StrategyContext(
                        now, MappingProxyType({symbol: tuple(_bars(symbol, message["bars"]))}),
                        portfolio, parameters, message["run_id"], 0,
                    )
                    result["targets"] = [
                        {"symbol": target.symbol, "target_weight": target.target_weight}
                        for target in strategy.generate_targets(context)
                    ]
                else:
                    raise ValueError("unknown operation")
            encoded = json.dumps({**result, "ok": True}, allow_nan=False)
        except BaseException:
            # Code, prompts, parameters and tracebacks are deliberately not exported.
            encoded = json.dumps({"request_id": message["request_id"], "ok": False})
        wire.write(encoded + "\n")
        wire.flush()


if __name__ == "__main__":
    main()
