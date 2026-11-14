import contextlib
import datetime as dt
import hashlib
import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

SPEC = spec_from_file_location(
    "rqalpha_worker", Path(__file__).resolve().parents[2] / "strategy/runner/rqalpha_worker.py",
)
worker = module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


@pytest.fixture
def settings():
    return {"symbols": ["600519.SS", "000001.SZ"], "interval": "1d",
            "initial_capital": 1_000_000, "commission_rate": .001,
            "slippage_rate": .0005, "max_position": .95,
            "max_participation_rate": .01, "parameters": {}}


def request(**patch):
    return {"protocol": worker.PROTOCOL, "request_id": uuid4().hex, "op": "inspect", **patch}


def test_request_protocol_and_uuid():
    value = request()
    assert worker.parse_request(json.dumps(value).encode()) == value
    assert worker.parse_request(json.dumps(request(request_id=str(uuid4()))).encode())


@pytest.mark.parametrize("patch", [
    {"protocol": "other"}, {"request_id": "not-a-uuid"}, {"request_id": 1}, {"op": "shell"},
])
def test_rejects_invalid_request(patch):
    with pytest.raises(worker.WorkerError):
        worker.parse_request(json.dumps(request(**patch)).encode())


@pytest.mark.parametrize("raw", [b"[1,2]", b"{bad", b"\xff", b"{\"value\":NaN}",
                                  b"x" * (worker.INPUT_BYTES + 1)])
def test_rejects_invalid_json_and_oversized_requests(raw):
    with pytest.raises(worker.WorkerError):
        worker.parse_request(raw)


def test_dates_and_market_close_are_converted_to_utc():
    assert worker.day(20250102000000) == dt.date(2025, 1, 2)
    assert worker.day(b"20250102") == dt.date(2025, 1, 2)
    expected = int(dt.datetime(2025, 1, 2, 7, tzinfo=dt.UTC).timestamp())
    assert worker.timestamp("2025-01-02", close=True) == expected
    assert worker.timestamp("2025-01-02 15:00:00") == expected
    assert worker.timestamp("2025-01-02T07:00:00+00:00") == expected
    with pytest.raises(worker.WorkerError):
        worker.day("not-a-date")


@pytest.mark.parametrize("symbol,native", [("600519.SS", "600519.XSHG"),
                                           ("000001.SZ", "000001.XSHE"),
                                           ("300001.SZ", "300001.XSHE")])
def test_symbol_round_trip(symbol, native):
    assert worker.native_symbol(symbol) == native
    assert worker.platform_symbol(native) == symbol


@pytest.mark.parametrize("symbol", [
    "510300.SS", "600519.SZ", "000001.SS", "920001.BJ", "BTC", None,
])
def test_rejects_unsupported_stock_symbol(symbol):
    with pytest.raises(worker.WorkerError):
        worker.native_symbol(symbol)


def test_source_is_compiled_but_never_executed_during_check(tmp_path):
    target = tmp_path / "not-executed"
    source = (f"open({str(target)!r}, 'w').write('bad')\n"
              "def init(c): pass\ndef handle_bar(c,b): pass")
    assert worker.check_source(source)
    assert not target.exists()


@pytest.mark.parametrize("source", ["", "x" * 60_001, "def init(:", "def init(c): pass",
                                   "__config__={}\ndef init(c): pass\ndef handle_bar(c,b): pass",
                                   "def init(c):\n global __config__\n __config__={}\n"
                                   "def handle_bar(c,b): pass"])
def test_rejects_unsupported_source_without_execution(source):
    with pytest.raises(worker.WorkerError):
        worker.check_source(source)


def test_configuration_matches_native_cost_and_simulation_semantics(settings):
    config = worker.run_config(settings, {"start": "2025-01-02", "end": "2025-12-31"})
    assert config["base"]["rqdatac_uri"] == "disabled"
    assert config["base"]["auto_update_bundle"] is False
    assert config["base"]["data_bundle_path"] == "/bundle"
    assert config["base"]["capital_gain_tax_rate"] == 0
    assert config["mod"]["sys_transaction_cost"]["stock_commission_multiplier"] == 1.25
    assert config["mod"]["sys_transaction_cost"]["stock_min_commission"] == 5
    assert config["mod"]["sys_transaction_cost"]["pit_tax"] is True
    assert config["mod"]["sys_simulation"]["matching_type"] == "current_bar"
    assert config["mod"]["sys_simulation"]["volume_percent"] == .01
    assert config["mod"]["sys_analyser"]["output_file"] is None


@pytest.mark.parametrize("patch", [{"interval": "15m"}, {"universe": "semiconductor"},
                                    {"max_position": 0}, {"commission_rate": -1},
                                    {"max_participation_rate": float("inf")}, {"symbols": []}])
def test_invalid_configuration_fails_closed(settings, patch):
    with pytest.raises(worker.WorkerError):
        worker.run_config({**settings, **patch}, {"start": "2025-01-02", "end": "2025-12-31"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "not-number", None])
def test_nonfinite_required_numbers_are_rejected(value):
    with pytest.raises(worker.WorkerError):
        worker.finite(value)
    assert worker.optional_number(value) is None


def order(symbol="600519.XSHG", quantity=100, price=10, side="BUY", identifier=2):
    return SimpleNamespace(order_book_id=symbol, side=SimpleNamespace(name=side),
                           order_id=identifier, unfilled_quantity=quantity, frozen_price=price)


def test_pool_and_position_risk_are_validators_not_another_matching_engine():
    position = SimpleNamespace(order_book_id="600519.XSHG", quantity=400,
                               direction=SimpleNamespace(name="LONG"))
    pending = order(quantity=200, identifier=1)
    env = SimpleNamespace(portfolio=SimpleNamespace(total_value=10_000,
                          get_positions=lambda: [position]), get_last_price=lambda _: 10,
                          get_open_orders=lambda _: [pending])
    validator = worker.PoolRiskValidator(env, ["600519.XSHG"], .7)
    assert validator.validate_submission(order(quantity=100)) is None
    assert "仓位" in validator.validate_submission(order(quantity=200))
    assert "股票池" in validator.validate_submission(order(symbol="000001.XSHE"))
    assert validator.validate_submission(order(quantity=9999, side="SELL")) is None
    assert validator.validate_cancellation(order()) is None


def native_result(trades=True):
    index = pd.to_datetime(["2025-01-02", "2025-01-03"])
    portfolio = pd.DataFrame({"cash": [9_000, 9_000], "total_value": [9_999, 10_100],
                              "market_value": [999, 1100], "unit_net_value": [.9999, 1.01],
                              "units": [10_000, 10_000],
                              "static_unit_net_value": [1, .9999]}, index=index)
    positions = pd.DataFrame({"order_book_id": ["600519.XSHG", "600519.XSHG"],
                              "symbol": ["贵州茅台", "贵州茅台"], "avg_price": [10, 10],
                              "quantity": [100, 100], "last_price": [9.99, 11],
                              "market_value": [999, 1100]}, index=index)
    fills = pd.DataFrame([{"datetime": "2025-01-02 15:00:00", "order_book_id": "600519.XSHG",
                           "symbol": "贵州茅台", "position_effect": "OPEN",
                           "side": "BUY", "last_quantity": 100, "last_price": 10,
                           "transaction_cost": 5, "commission": 5, "tax": 0,
                           "order_id": 1, "exec_id": 2}] if trades else [])
    accounts = pd.DataFrame({"cash": [9000, 9000], "total_value": [9999, 10100],
                             "market_value": [999, 1100], "transaction_cost": [5, 0]}, index=index)
    return {"portfolio": portfolio, "stock_positions": positions, "trades": fills,
            "stock_account": accounts,
            "summary": {"sharpe": float("nan"), "returns": .01, "name": "native"}}


def test_result_uses_native_values_and_only_real_sellable_snapshot():
    native = native_result()
    result = worker.convert_result(native, 10_000, {
        "600519.XSHG": {"day": "2025-01-03", "quantity": 100,
                         "market_value": 1100, "sellable": 70},
    }, [])
    assert result["positions"][0]["sellable"] == 70
    assert result["trades"][0]["fee"] == 5
    assert result["trades"][0]["order_id"] == "1"
    assert result["equity"][0]["equity"] == 9999
    assert result["final_equity"] == 10100
    assert result["total_return"] == pytest.approx(.01)
    assert result["max_drawdown"] == pytest.approx(.0001)
    assert result["native_metrics"] == {"sharpe": None, "returns": .01}
    assert result["corporate_actions"] == []


def test_empty_trades_are_success_and_missing_sellable_is_not_invented():
    result = worker.convert_result(native_result(trades=False), 10_000, {}, [])
    assert result["trades"] == []
    assert result["positions"][0]["sellable"] is None
    assert result["rejections"] == []


def test_actual_native_corporate_events_are_preserved():
    native = native_result()
    native["portfolio_event"] = pd.DataFrame([{
        "datetime": "2025-01-03 09:00:00", "order_book_id": "600519.XSHG",
        "event_category": "cash_dividend", "delta_amount": 10, "delta_quantity": 0,
        "remark": "native event",
    }])
    result = worker.convert_result(native, 10_000, {}, [])
    assert result["corporate_actions"][0]["amount"] == 10
    assert result["corporate_actions"][0]["type"] == "cash_dividend"
    assert result["corporate_actions"][0]["symbol"] == "600519.SS"


def test_json_limits_and_forbidden_nonfinite_values():
    with pytest.raises(worker.WorkerError):
        worker.encoded_response({"bad": float("nan")})
    with pytest.raises(worker.WorkerError):
        worker.encoded_response({"message": "x" * 100}, limit=100)
    assert worker.encoded_response({"value": None}).endswith(b"\n")


def test_serve_writes_one_protocol_line_and_redacts_internal_errors(monkeypatch, capsys):
    value = request()

    def execute(_):
        print("user print")
        return {"answer": 1}

    monkeypatch.setattr(worker, "dispatch", execute)
    output = BytesIO()
    worker.serve(BytesIO(json.dumps(value).encode() + b"\n"), output)
    response = json.loads(output.getvalue())
    assert response["request_id"] == value["request_id"]
    assert response["ok"] is True
    assert output.getvalue().count(b"\n") == 1
    assert "user print" in capsys.readouterr().err

    def failure(_):
        raise RuntimeError("private token path must not be exposed")

    monkeypatch.setattr(worker, "dispatch", failure)
    output = BytesIO()
    worker.serve(BytesIO(json.dumps(value).encode()), output)
    assert json.loads(output.getvalue())["ok"] is False
    assert b"private token" not in output.getvalue()


def test_serve_protocol_error_is_bounded_and_does_not_require_sdk():
    output = BytesIO()
    worker.serve(BytesIO(b"not-json"), output)
    response = json.loads(output.getvalue())
    assert response["protocol"] == worker.PROTOCOL
    assert response["ok"] is False
    assert len(response["error"]["message"]) < 400


def test_inspection_reads_only_dataset_endpoints_and_disables_numpy_pickle(monkeypatch):
    import numpy as np

    reads = []

    class Dataset:
        dtype = SimpleNamespace(names=("datetime", "close"))

        def __len__(self):
            return 2

        def __getitem__(self, index):
            reads.append(index)
            return {"datetime": 20250102000000 if index == 0 else 20251231000000}

    class Store(dict):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def load(path, *, allow_pickle):
        assert allow_pickle is False
        assert path == Path("/bundle/trading_dates.npy")
        return np.array([20250102, 20250103])

    monkeypatch.setattr(np, "load", load)
    monkeypatch.setitem(sys.modules, "hdf5plugin", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "h5py", SimpleNamespace(
        Dataset=Dataset,
        File=lambda path, mode: Store({"600519.XSHG": Dataset(), "510300.XSHG": Dataset()}),
    ))
    result = worker.inspect_bundle()
    assert reads == [0, -1]
    assert result["sessions"] == ["2025-01-02", "2025-01-03"]
    assert result["instruments"] == {
        "600519.SS": {"native_symbol": "600519.XSHG", "start": "2025-01-02", "end": "2025-12-31"},
    }
    monkeypatch.setattr(worker, "MAX_SESSIONS", 1)
    with pytest.raises(worker.WorkerError, match="交易日历"):
        worker.inspect_bundle()


class CallbackBus:
    def __init__(self):
        self.listeners, self.prepended, self.dispatched = {}, [], []

    def add_listener(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def prepend_listener(self, event, callback):
        self.prepended.append((event, callback.__name__))
        self.listeners.setdefault(event, []).insert(0, callback)

    def dispatch(self, event):
        for callback in self.listeners.get(event, ()):
            self.dispatched.append((event, callback.__name__))
            callback(SimpleNamespace(event_type=event))


def test_native_callback_wrapper_executes_strategy_top_level_once(monkeypatch, settings):
    monkeypatch.setattr(worker.ReportCapture, "handler", lambda _: SimpleNamespace(
        applicationbound=contextlib.nullcontext,
    ))
    bus = CallbackBus()
    position = SimpleNamespace(order_book_id="600519.XSHG", quantity=100, closable=0,
                               market_value=1100, pnl=100, transaction_cost=0)
    stock = SimpleNamespace(cash=9000, total_value=10100, market_value=1100, daily_pnl=101,
                            frozen_cash=0, cash_liabilities=0, cash_liabilities_interest=0,
                            _pending_deposit_withdraw=[], get_positions=lambda: [position])
    portfolio = SimpleNamespace(cash=9000, total_value=10100, market_value=1100, daily_pnl=101,
                                get_positions=lambda: [position], accounts={"STOCK": stock})
    environment = SimpleNamespace(
        global_vars=SimpleNamespace(top_level_calls=0), portfolio=portfolio,
        calendar_dt=dt.datetime(2025, 1, 3, 15),
        add_frontend_validator=lambda _: None, event_bus=bus,
    )
    context = SimpleNamespace(now=environment.calendar_dt, portfolio=portfolio)

    def run_func(**callbacks):
        config = callbacks["config"]
        assert config["base"]["rqdatac_uri"] == "disabled"
        callbacks["init"](context)
        callbacks["before_trading"](context)
        callbacks["handle_bar"](context, {})
        callbacks["after_trading"](context)
        bus.dispatch(3)
        return {"sys_analyser": native_result()}

    monkeypatch.setitem(sys.modules, "rqalpha", SimpleNamespace(run_func=run_func))
    monkeypatch.setitem(sys.modules, "rqalpha.core.events", SimpleNamespace(EVENT=SimpleNamespace(
        ORDER_CREATION_REJECT=1, ORDER_UNSOLICITED_UPDATE=2, POST_SETTLEMENT=3,
    )))
    monkeypatch.setitem(sys.modules, "rqalpha.environment", SimpleNamespace(
        Environment=SimpleNamespace(get_instance=lambda: environment),
    ))
    monkeypatch.setitem(sys.modules, "rqalpha.main", SimpleNamespace(
        create_base_scope=lambda: {}, get_strategy_apis=lambda: {},
    ))
    source = """g.top_level_calls += 1

def init(context):
    assert context.parameters['lookback'] == 5
    assert context.symbols == ('600519.XSHG', '000001.XSHE')

def handle_bar(context, bars):
    context.handled = True
"""
    result = worker.run_backtest({"source": source, "settings": settings,
                                  "parameters": {"lookback": 5},
                                  "window": {"start": "2025-01-02", "end": "2025-01-03"}})
    assert environment.global_vars.top_level_calls == 1
    assert context.handled is True
    assert result["positions"][0]["sellable"] == 0
    assert bus.prepended == [(3, "collect_settlement")]
    assert result["equity"][1]["daily_pnl"] == 101
    assert result["equity"][1]["dividend_receivable"] == 0


def test_rejected_nonstock_order_keeps_observed_symbol_without_turning_into_trade():
    assert worker.rejected_symbol("510300.XSHG") == "510300.SS"
    assert worker.rejected_symbol("IF2501") == "IF2501"
    with pytest.raises(worker.WorkerError):
        worker.platform_symbol("510300.XSHG")


def test_record_limit_is_enforced_without_output(monkeypatch):
    monkeypatch.setattr(worker, "MAX_RECORDS", 1)
    with pytest.raises(worker.WorkerError, match="记录过多"):
        worker.convert_result(native_result(), 10_000, {}, [])
    with pytest.raises(worker.WorkerError, match="记录过多"):
        worker._append_record([{}], {})


def test_bundle_hashes_are_checked_inside_the_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "BUNDLE", tmp_path)
    content = b"only the expected immutable data"
    file = tmp_path / "stocks.h5"
    file.write_bytes(content)
    files = [{"path": file.name, "bytes": len(content),
              "sha256": hashlib.sha256(content).hexdigest()}]
    worker.verify_bundle(files)
    file.write_bytes(b"x" + content[1:])
    with pytest.raises(worker.WorkerError, match="摘要不符"):
        worker.verify_bundle(files)
    file.write_bytes(content)
    (tmp_path / "untracked.h5").write_bytes(b"unexpected")
    with pytest.raises(worker.WorkerError, match="集合不一致"):
        worker.verify_bundle(files)


@pytest.mark.parametrize("files", [
    None, [], [{"path": "../secret", "bytes": 1, "sha256": "0" * 64}],
    [{"path": "stocks.h5", "bytes": True, "sha256": "0" * 64}],
])
def test_bundle_manifest_is_required_and_paths_are_confined(tmp_path, monkeypatch, files):
    monkeypatch.setattr(worker, "BUNDLE", tmp_path)
    with pytest.raises(worker.WorkerError):
        worker.verify_bundle(files)
