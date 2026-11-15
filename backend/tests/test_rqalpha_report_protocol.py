import copy
import datetime as dt
import json
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from test_rqalpha_worker import CallbackBus, native_result, request, worker

from app import sandbox
from app.sandbox import RqalphaSandbox, RunnerCleanupFailure, RunnerFailure, RunnerUnavailable

PROGRAM = """
import json, sys, time
request = json.loads(sys.stdin.buffer.readline())
spec = json.loads(sys.argv[1])
assert request.get('stream') is True if request['op'] == 'run' else 'stream' not in request
for frame in spec['frames']:
    if '__raw__' in frame:
        encoded = frame['__raw__'].encode()
    else:
        frame.setdefault('protocol', request['protocol'])
        frame.setdefault('request_id', request['request_id'])
        encoded = (json.dumps(frame, ensure_ascii=False) + '\\n').encode()
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
if spec.get('linger'):
    time.sleep(10)
sys.exit(spec.get('exit_code', 0))
"""


@pytest.fixture
def launch():
    processes = []

    def start(frames, **options):
        runner = RqalphaSandbox(Path("."))
        runner.deadline = time.monotonic() + 5
        runner.process = subprocess.Popen(
            [sys.executable, "-I", "-c", PROGRAM,
             json.dumps({"frames": frames, **options}, ensure_ascii=False)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )
        processes.append(runner.process)
        return runner

    yield start
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()


def log_row(sequence=0, **patch):
    return {"sequence": sequence, "time": 1735801200, "level": "INFO",
            "source": "strategy", "message": "checked user message", **patch}


def frames():
    result = worker.convert_result(native_result(), 10_000, {}, [])
    report = result["report_data"]
    messages = [{"event": "log", "row": log_row()}]
    for table in worker.REPORT_TABLES:
        if report[table]:
            messages.append({"event": "rows", "table": table, "offset": 0,
                             "rows": report[table]})
    metadata = {key: value for key, value in report.items()
                if key not in (*worker.REPORT_TABLES, "logs")}
    metadata["counts"]["logs"] = 1
    messages.append({"ok": True, "result": {**result, "report_data": metadata}})
    return messages


def test_native_report_keeps_every_day_and_native_values():
    captured = {("2025-01-03", "600519.XSHG"): {
        "quantity": 100, "market_value": 1100, "pnl": 100, "fee": 0,
        "dividend_receivable": 0,
    }}
    daily = {"2025-01-03": {key: {
        "equity": 10100, "cash": 9000, "market_value": 1100, "daily_pnl": 101,
        "frozen_cash": 0, "dividend_receivable": 0, "cash_liabilities": 0,
        "cash_liabilities_interest": 0, "pending_cash_flow": 0,
    } for key in ("portfolio", "stock")}}
    available = {("2025-01-03", "600519.XSHG"): {
        "day": "2025-01-03", "quantity": 100, "market_value": 1100, "sellable": 70,
    }}
    native = native_result()
    native["benchmark_portfolio"] = pd.DataFrame(
        {"unit_net_value": [.98, 1.03]}, index=native["portfolio"].index,
    )
    result = worker.convert_result(native, 10_000, {}, [], snapshots=captured,
                                   daily_snapshots=daily, sellable_snapshots=available,
                                   risk_free_rate=.02, trading_days=252)
    report = result["report_data"]
    assert report["schema_version"] == worker.REPORT_SCHEMA
    assert len(report["positions"]) == len(report["accounts"]) == 2
    assert report["positions"][0]["pnl"] is None
    assert report["positions"][1] == {
        "time": 1735887600, "symbol": "600519.SS", "name": "贵州茅台", "last_price": 11,
        "direction": "long", "quantity": 100, "avg_price": 10, "market_value": 1100,
        "pnl": 100, "fee": 0, "dividend_receivable": 0, "sellable": 70,
    }
    assert report["position_snapshot_time"] == "post_settlement_before_account_reset"
    assert report["sellable_snapshot_time"] == "after_trading_before_settlement"
    assert report["accounts"][1]["daily_pnl"] == 101
    assert report["accounts"][1]["margin"] is None
    assert report["accounts"][0]["fee"] == 5
    assert report["benchmark"][0]["net_value"] == .98
    assert report["risk_free_rate"] == .02
    assert result["equity"][1]["daily_pnl"] == 101
    assert result["equity"][1]["net_value"] == 1.01
    assert result["equity"][1]["units"] == 10000
    assert result["trades"][0]["name"] == "贵州茅台"
    assert result["trades"][0]["position_effect"] == "open"


@pytest.mark.parametrize("patch", [{"quantity": 90}, {"market_value": 1000}])
def test_snapshot_value_mismatch_does_not_invent_profit_or_available_quantity(patch):
    captured = {("2025-01-03", "600519.XSHG"): {
        "quantity": 100, "market_value": 1100, "pnl": 100, "fee": 5, "sellable": 100, **patch,
    }}
    result = worker.convert_result(native_result(), 10_000, {}, [], snapshots=captured)
    position = result["report_data"]["positions"][1]
    assert all(position[key] is None for key in ("pnl", "fee", "sellable"))


def test_unit_net_value_is_not_replaced_by_equity_over_initial_cash():
    native = native_result()
    native["portfolio"].loc[
        native["portfolio"].index[-1], ["units", "total_value"],
    ] = [20000, 20200]
    result = worker.convert_result(native, 10000, {}, [])
    assert result["equity"][-1]["net_value"] == 1.01
    assert result["equity"][-1]["equity"] / 10000 == 2.02
    assert result["equity"][-1]["daily_pnl"] is None
    native["portfolio"] = native["portfolio"].drop(columns="unit_net_value")
    with pytest.raises(KeyError):
        worker.convert_result(native, 10000, {}, [])


@pytest.mark.parametrize("benchmark,native", [
    ("000300.SS", "000300.XSHG"), ("000905.SS", "000905.XSHG"),
    ("000001.SS", "000001.XSHG"), (None, None),
])
def test_benchmarks_are_configured_separately_from_stock_trading(benchmark, native):
    settings = {"symbols": ["600519.SS", "000001.SZ"], "interval": "1d",
                "initial_capital": 10000, "commission_rate": .001, "slippage_rate": 0,
                "max_position": 1, "max_participation_rate": .01, "benchmark": benchmark}
    config = worker.run_config(settings, {"start": "2025-01-02", "end": "2025-01-03"})
    assert config["mod"]["sys_analyser"]["benchmark"] == native
    assert config["base"]["rqdatac_uri"] == "disabled"
    if benchmark:
        with pytest.raises(worker.WorkerError):
            worker.native_symbol(benchmark)
    settings["benchmark"] = {"000300.SS": 1}
    with pytest.raises(worker.WorkerError, match="基准"):
        worker.run_config(settings, {"start": "2025-01-02", "end": "2025-01-03"})


def test_index_inspection_filters_invalid_prices_without_pickle(monkeypatch):
    dates = np.array([20250101000000, 20250102000000, 20250103000000,
                      20250106000000, 20250107000000, 20250108000000])

    class Dataset:
        dtype = SimpleNamespace(names=("datetime", "close"))

        def __len__(self):
            return len(dates)

        def __getitem__(self, key):
            if key == "datetime":
                return dates
            if key == "close":
                return np.array([10, np.nan, 0, np.inf, -1, 11])
            return {"datetime": dates[key]}

    class Store(dict):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(np, "load", lambda path, *, allow_pickle:
                        dates if not allow_pickle else None)
    monkeypatch.setitem(sys.modules, "hdf5plugin", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "h5py", SimpleNamespace(
        Dataset=Dataset, File=lambda path, mode: Store({
            "600519.XSHG" if path.name == "stocks.h5" else "000300.XSHG": Dataset(),
        }),
    ))
    result = worker.inspect_bundle()
    assert result["benchmarks"] == {"000300.SS": {
        "native_symbol": "000300.XSHG", "name": "沪深300", "start": "2025-01-01",
        "end": "2025-01-08", "sessions": ["2025-01-01", "2025-01-08"],
    }}
    assert list(result["instruments"]) == ["600519.SS"]


def test_user_logs_are_bounded_and_paths_and_controls_are_redacted(monkeypatch):
    capture = worker.ReportCapture()
    capture.clock = lambda: dt.datetime(2025, 1, 2, 15)
    capture.append("unsafe /Users/person/key.env and C:\\secret\\file\x00\x1b[31mtext")
    assert capture.logs[0]["time"] == 1735801200
    assert "/Users" not in capture.logs[0]["message"]
    assert "C:\\secret" not in capture.logs[0]["message"]
    assert "\x00" not in capture.logs[0]["message"]
    capture.append("x" * 5000)
    assert len(capture.logs[-1]["message"]) == 4096
    assert capture.truncated
    for _ in range(2100):
        capture.append("continued")
    assert len(capture.logs) == 2000
    assert capture.bytes <= 1024 * 1024
    assert [row["sequence"] for row in capture.logs] == list(range(2000))
    monkeypatch.setattr(worker, "LOG_BYTES", 100)
    small = worker.ReportCapture()
    small.append("a" * 500)
    assert small.logs == [] and small.truncated


def test_handler_only_captures_user_channels_and_normalizes_levels(monkeypatch):
    class Handler:
        def __init__(self, **kwargs):
            assert kwargs == {"level": 10, "bubble": False}

    monkeypatch.setitem(sys.modules, "logbook", SimpleNamespace(Handler=Handler, DEBUG=10))
    capture = worker.ReportCapture()
    handler = capture.handler()
    for channel, level in (("system_log", "DEBUG"), ("user_log", "INFO"),
                           ("user_system_log", "WARNING")):
        handler.emit(SimpleNamespace(channel=channel, level_name=level, message="safe"))
    assert [(row["source"], row["level"]) for row in capture.logs] == [
        ("strategy", "INFO"), ("engine", "WARN"),
    ]


def test_safe_strategy_exception_keeps_only_strategy_line_and_message():
    capture = worker.ReportCapture()
    try:
        source = "raise ValueError('bad /Users/person/private.env')"
        exec(compile(source, "strategy.py", "exec"), {})
    except ValueError as exc:
        capture.exception(exc)
    assert capture.logs[0]["line"] == 1
    assert "ValueError: bad" in capture.logs[0]["message"]
    assert "/Users" not in capture.logs[0]["message"]
    try:
        raise RuntimeError("internal /home/runner/env")
    except RuntimeError as exc:
        capture.exception(exc)
    assert len(capture.logs) == 1


def test_worker_stream_emits_live_logs_then_rows_and_terminal_metadata(monkeypatch):
    def dispatch(value):
        capture = value["_report_capture"]
        capture.user_print("first")
        assert output.getvalue().count(b"\n") == 1
        return worker.convert_result(native_result(), 10000, {}, [], capture=capture)

    monkeypatch.setattr(worker, "dispatch", dispatch)
    value = request(op="run", stream=True)
    output = BytesIO()
    worker.serve(BytesIO(json.dumps(value).encode()), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert responses[0]["event"] == "log"
    assert responses[1]["event"] == "rows" and responses[1]["offset"] == 0
    report = responses[-1]["result"]["report_data"]
    assert report["counts"] == {"positions": 2, "accounts": 2, "benchmark": 0, "logs": 1}
    assert all(table not in report for table in (*worker.REPORT_TABLES, "logs"))
    assert all(row["request_id"] == value["request_id"] for row in responses)


def test_worker_batches_at_1000_rows_and_keeps_nonstream_size_limit():
    output = BytesIO()
    writer = worker.StreamWriter(output, "a" * 32)
    result = worker.convert_result(native_result(), 10000, {}, [])
    result["report_data"]["positions"] = [{}] * 2001
    writer.result(result)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    batches = [row for row in messages if row.get("table") == "positions"]
    assert [row["offset"] for row in batches] == [0, 1000, 2000]
    assert [len(row["rows"]) for row in batches] == [1000, 1000, 1]
    assert messages[-1]["result"]["report_data"]["counts"]["positions"] == 2001
    with pytest.raises(worker.WorkerError, match="输出体积"):
        worker.encoded_response({"value": "large"}, limit=10)


@pytest.mark.parametrize("streaming", [False, True])
def test_failure_keeps_collected_logs_without_internal_exception_text(monkeypatch, streaming):
    def fail(value):
        value["_report_capture"].append("already collected")
        raise RuntimeError("internal /Users/person/env must not escape")

    monkeypatch.setattr(worker, "dispatch", fail)
    output = BytesIO()
    worker.serve(BytesIO(json.dumps(request(op="run", stream=streaming)).encode()), output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[-1]["ok"] is False
    assert "must not escape" not in output.getvalue().decode()
    if streaming:
        assert rows[0]["row"]["message"] == "already collected"
        assert rows[-1]["report_data"]["counts"]["logs"] == 1
    else:
        assert rows[-1]["report_data"]["logs"][0]["message"] == "already collected"


def test_host_reconstructs_stream_and_exposes_live_logs(launch):
    runner = launch(frames())
    result = runner.run({"op": "run"})
    report = result["report_data"]
    assert len(report["positions"]) == len(report["accounts"]) == 2
    assert report["logs"] == runner.report_logs == [log_row()]
    assert not runner.logs_truncated


def test_inspection_protocol_remains_one_json_response(launch):
    runner = launch([{"ok": True, "result": {"benchmarks": {}}}])
    assert runner.run({"op": "inspect"}) == {"benchmarks": {}}


@pytest.mark.parametrize("change", [
    "request_id", "unknown_event", "missing_batch", "duplicate_batch", "offset", "table",
    "log_sequence", "duplicate_log", "late_log", "post_terminal", "missing_terminal",
    "counts", "bool_counts", "inline_rows", "direction", "account_type", "schema",
])
def test_host_rejects_corrupt_missing_duplicate_and_out_of_order_frames(launch, change):
    messages = frames()
    if change == "request_id":
        messages[0]["request_id"] = "b" * 32
    elif change == "unknown_event":
        messages[0]["event"] = "shell"
    elif change == "missing_batch":
        messages.pop(1)
    elif change == "duplicate_batch":
        messages.insert(2, copy.deepcopy(messages[1]))
    elif change == "offset":
        messages[1]["offset"] = 10
    elif change == "table":
        messages[1]["table"] = ["positions"]
    elif change == "log_sequence":
        messages[0]["row"]["sequence"] = 1
    elif change == "duplicate_log":
        messages.insert(1, copy.deepcopy(messages[0]))
    elif change == "late_log":
        messages.insert(2, messages.pop(0))
    elif change == "post_terminal":
        messages.append(copy.deepcopy(messages[-1]))
    elif change == "missing_terminal":
        messages.pop()
    elif change == "counts":
        messages[-1]["result"]["report_data"]["counts"]["accounts"] = 3
    elif change == "bool_counts":
        messages[-1]["result"]["report_data"]["counts"]["logs"] = True
    elif change == "inline_rows":
        messages[-1]["result"]["report_data"]["positions"] = []
    elif change == "direction":
        messages[1]["rows"][0]["direction"] = "short"
    elif change == "account_type":
        messages[2]["rows"][0]["account_type"] = "future"
    elif change == "schema":
        messages[-1]["result"]["report_data"]["schema_version"] = "other"
    runner = launch(messages)
    with pytest.raises(RunnerFailure) as raised:
        runner.run({"op": "run"})
    assert hasattr(raised.value, "report_logs")
    assert hasattr(raised.value, "logs_truncated")


@pytest.mark.parametrize("patch", [
    {"sequence": True}, {"time": float("nan")}, {"level": "FATAL"}, {"source": "internal"},
    {"message": "x" * 4097}, {"line": 0}, {"line": True},
])
def test_host_rejects_invalid_log_metadata(launch, patch):
    messages = frames()
    messages[0]["row"].update(patch)
    with pytest.raises(RunnerFailure):
        launch(messages).run({"op": "run"})


def test_host_preserves_logs_and_truncation_on_worker_failure(launch):
    messages = [{"event": "log", "row": log_row()}]
    messages.append({"ok": False, "error": {"message": "safe error"}, "report_data": {
        "schema_version": worker.REPORT_SCHEMA, "logs_truncated": True,
        "counts": {"positions": 0, "accounts": 0, "benchmark": 0, "logs": 1},
    }})
    with pytest.raises(RunnerFailure) as raised:
        launch(messages).run({"op": "run"})
    assert raised.value.report_logs == [log_row()]
    assert raised.value.logs_truncated is True


@pytest.mark.parametrize("mode", ["cancel", "deadline"])
def test_host_keeps_logs_received_before_cancellation_or_timeout(launch, mode):
    runner = launch([{"event": "log", "row": log_row()}], linger=True)

    def cancelled():
        if runner.report_logs and mode == "deadline":
            runner.deadline = time.monotonic() - 1
        return bool(runner.report_logs) and mode == "cancel"

    runner._should_cancel = cancelled
    with pytest.raises(RunnerFailure, match="取消|时限") as raised:
        runner.run({"op": "run"})
    assert raised.value.report_logs == [log_row()]


def test_cleanup_errors_keep_already_collected_logs(launch, monkeypatch):
    runner = launch(frames())
    runner.run({"op": "run"})

    def failed_cleanup():
        raise RunnerCleanupFailure("synthetic cleanup error")

    monkeypatch.setattr(runner, "_remove_container", failed_cleanup)
    with pytest.raises(RunnerCleanupFailure) as raised:
        runner.__exit__(None, None, None)
    assert raised.value.report_logs == [log_row()]
    runner = RqalphaSandbox(Path("."))
    with pytest.raises(RunnerUnavailable) as unavailable:
        runner.run({"op": "run"})
    assert unavailable.value.report_logs == []


@pytest.mark.parametrize("limit", ["frame", "channel", "records", "logs"])
def test_host_enforces_frame_channel_economic_record_and_log_budgets(launch, monkeypatch, limit):
    messages = frames()
    runner = launch(messages)
    if limit == "frame":
        runner.output_limit = 100
    elif limit == "channel":
        runner.channel_limit = 300
    elif limit == "records":
        monkeypatch.setattr(sandbox, "RQALPHA_MAX_RECORDS", 7)
    else:
        monkeypatch.setattr(sandbox, "RQALPHA_LOG_BYTES", 10)
    with pytest.raises(RunnerFailure, match="限制"):
        runner.run({"op": "run"})


def test_worker_counts_history_and_final_positions_in_economic_budget(monkeypatch):
    monkeypatch.setattr(worker, "MAX_RECORDS", 7)
    with pytest.raises(worker.WorkerError, match="记录过多"):
        worker.convert_result(native_result(), 10000, {}, [])


def test_callback_adapter_collects_settlement_values_before_account_reset(monkeypatch):
    position = SimpleNamespace(order_book_id="600519.XSHG", quantity=100,
                               market_value=999, closable=0, pnl=-1, transaction_cost=7)
    stock = SimpleNamespace(cash=9000, total_value=9999, market_value=999, daily_pnl=-1,
                            frozen_cash=0, cash_liabilities=0, cash_liabilities_interest=0,
                            _pending_deposit_withdraw=[], get_positions=lambda: [position])
    portfolio = SimpleNamespace(
        cash=9000, total_value=9999, market_value=999, daily_pnl=-1, accounts={"STOCK": stock},
        get_positions=lambda: [position],
    )
    context = SimpleNamespace(now=dt.datetime(2025, 1, 3, 15), portfolio=portfolio)
    dates = []
    start, end = dt.date(2025, 1, 2), dt.date(2025, 1, 3)

    def risk_free(first, last):
        dates.append((first, last))
        return .018

    bus = CallbackBus()
    environment = SimpleNamespace(
        calendar_dt=context.now, global_vars=SimpleNamespace(), trading_days_a_year=252,
        data_proxy=SimpleNamespace(get_risk_free_rate=risk_free), portfolio=portfolio,
        config=SimpleNamespace(base=SimpleNamespace(start_date=start, end_date=end)),
        add_frontend_validator=lambda _: None, event_bus=bus,
    )

    def analyser(_):
        assert portfolio.daily_pnl == stock.daily_pnl == 101

    def account_reset(_):
        portfolio.daily_pnl = stock.daily_pnl = position.pnl = position.transaction_cost = 0

    def run_func(**callbacks):
        bus.add_listener(3, analyser)
        bus.add_listener(3, account_reset)
        callbacks["init"](context)
        callbacks["handle_bar"](context, {})
        callbacks["after_trading"](context)
        portfolio.total_value = stock.total_value = 10100
        portfolio.market_value = stock.market_value = position.market_value = 1100
        portfolio.daily_pnl = stock.daily_pnl = 101
        position.pnl, position.transaction_cost = 100, 3
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
    monkeypatch.setattr(worker.ReportCapture, "handler", lambda _: SimpleNamespace(
        applicationbound=worker.contextlib.nullcontext,
    ))
    settings = {"symbols": ["600519.SS", "000001.SZ"], "interval": "1d",
                "initial_capital": 10000, "commission_rate": .001, "slippage_rate": 0,
                "max_position": 1, "max_participation_rate": .01}
    value = {"source": "def init(c): print('boot')\ndef handle_bar(c,b): pass",
             "settings": settings, "window": {"start": start.isoformat(), "end": end.isoformat()}}
    result = worker.run_backtest(value)
    report = result["report_data"]
    assert dates == [(start, end)]
    assert report["risk_free_rate"] == .018
    assert report["trading_days_a_year"] == 252
    assert report["positions"][1]["pnl"] == 100
    assert report["positions"][1]["fee"] == 3
    assert report["positions"][1]["sellable"] is None
    assert bus.prepended == [(3, "collect_settlement")]
    assert bus.dispatched[:3] == [(3, "collect_settlement"), (3, "analyser"),
                                  (3, "account_reset")]
    assert stock.daily_pnl == 0
    assert report["accounts"][1]["daily_pnl"] == result["equity"][1]["daily_pnl"] == 101
    assert report["logs"][0]["time"] == 1735887600
    assert report["logs"][0]["message"] == "boot\n"

    def dispatch(request_value):
        return worker.run_backtest({**value, "_report_capture": request_value["_report_capture"],
                                   "source": "def init(c): print('boot')\n"
                                   "def handle_bar(c,b):\n"
                                   " raise ValueError('bad /home/secret/file')"})

    monkeypatch.setattr(worker, "dispatch", dispatch)
    output = BytesIO()
    worker.serve(BytesIO(json.dumps(request(op="run", stream=True)).encode()), output)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert messages[-1]["ok"] is False
    assert messages[-1]["error"]["line"] == 3
    assert messages[-2]["row"]["line"] == 3
    assert "ValueError: bad" in messages[-2]["row"]["message"]
    assert b"/home/secret" not in output.getvalue()


@pytest.mark.parametrize("include_payout", [False, True])
def test_settlement_captures_zero_quantity_receivables_and_explicit_cash_components(
    monkeypatch, include_payout,
):
    index = pd.to_datetime(["2025-01-02", "2025-01-03"] if include_payout else ["2025-01-02"])
    state = {"positions": []}
    stock = SimpleNamespace(cash=100, total_value=113, market_value=0, daily_pnl=0,
                            frozen_cash=12, cash_liabilities=5, cash_liabilities_interest=1,
                            _pending_deposit_withdraw=[(dt.date(2025, 1, 8), 9),
                                                       (dt.date(2025, 1, 9), -2)],
                            get_positions=lambda: state["positions"])
    portfolio = SimpleNamespace(cash=100, total_value=113, market_value=0, daily_pnl=0,
                                accounts={"STOCK": stock}, get_positions=lambda: state["positions"])
    context = SimpleNamespace(now=index[0].to_pydatetime().replace(hour=15), portfolio=portfolio)
    bus = CallbackBus()
    env = SimpleNamespace(calendar_dt=context.now, portfolio=portfolio,
                          global_vars=SimpleNamespace(), trading_days_a_year=252, event_bus=bus,
                          add_frontend_validator=lambda _: None,
                          data_proxy=SimpleNamespace(get_risk_free_rate=lambda *_: .02),
                          config=SimpleNamespace(base=SimpleNamespace(
                              start_date=dt.date(2025, 1, 2), end_date=dt.date(2025, 1, 3),
                          )))
    native = {
        "portfolio": pd.DataFrame({
            "cash": [100, 124][:len(index)], "total_value": [137] * len(index),
            "market_value": [0] * len(index), "unit_net_value": [137 / 113] * len(index),
            "units": [113] * len(index), "static_unit_net_value": [1, 137 / 113][:len(index)],
        }, index=index),
        "stock_account": pd.DataFrame({
            "cash": [100, 124][:len(index)], "total_value": [137] * len(index),
            "market_value": [0] * len(index), "transaction_cost": [3, 0][:len(index)],
        }, index=index),
        "stock_positions": pd.DataFrame({
            "order_book_id": ["600519.XSHG"], "symbol": ["贵州茅台"], "quantity": [0],
            "last_price": [10], "avg_price": [10], "market_value": [0],
        }, index=index[:1]),
        "trades": pd.DataFrame(), "summary": {"total_returns": 137 / 113 - 1},
    }

    def reset(_):
        stock.daily_pnl = portfolio.daily_pnl = 0
        for position in state["positions"]:
            position.transaction_cost = 0

    def run_func(**callbacks):
        bus.add_listener(3, reset)
        callbacks["init"](context)
        for offset, current in enumerate(index):
            context.now = env.calendar_dt = current.to_pydatetime().replace(hour=15)
            callbacks["handle_bar"](context, {})
            callbacks["after_trading"](context)
            stock.total_value = portfolio.total_value = 137
            stock.cash = portfolio.cash = 100 if offset == 0 else 124
            stock.daily_pnl = portfolio.daily_pnl = 24 if offset == 0 else 0
            state["positions"] = [SimpleNamespace(
                order_book_id="600519.XSHG", quantity=0, market_value=0, pnl=0,
                transaction_cost=3, dividend_receivable=24,
            )] if offset == 0 else []
            bus.dispatch(3)
        return {"sys_analyser": native}

    monkeypatch.setitem(sys.modules, "rqalpha", SimpleNamespace(run_func=run_func))
    monkeypatch.setitem(sys.modules, "rqalpha.core.events", SimpleNamespace(EVENT=SimpleNamespace(
        ORDER_CREATION_REJECT=1, ORDER_UNSOLICITED_UPDATE=2, POST_SETTLEMENT=3,
    )))
    monkeypatch.setitem(sys.modules, "rqalpha.environment", SimpleNamespace(
        Environment=SimpleNamespace(get_instance=lambda: env),
    ))
    monkeypatch.setitem(sys.modules, "rqalpha.main", SimpleNamespace(
        create_base_scope=lambda: {}, get_strategy_apis=lambda: {},
    ))
    monkeypatch.setattr(worker.ReportCapture, "handler", lambda _: SimpleNamespace(
        applicationbound=worker.contextlib.nullcontext,
    ))
    settings = {"symbols": ["600519.SS", "000001.SZ"], "interval": "1d",
                "initial_capital": 113, "commission_rate": .001, "slippage_rate": 0,
                "max_position": 1, "max_participation_rate": .01}
    result = worker.run_backtest({"settings": settings,
                                  "source": "def init(c): pass\ndef handle_bar(c,b): pass",
                                  "window": {"start": "2025-01-02", "end": "2025-01-03"}})
    report = result["report_data"]
    holding = report["positions"][0]
    assert holding["quantity"] == holding["market_value"] == 0
    assert holding["dividend_receivable"] == 24
    assert holding["fee"] == 3 and holding["pnl"] == 0
    assert holding["sellable"] is None
    for row in (result["equity"][0], report["accounts"][0]):
        assert row["frozen_cash"] == 12
        assert row["dividend_receivable"] == 24
        assert row["cash_liabilities"] == 5
        assert row["cash_liabilities_interest"] == 1
        assert row["pending_cash_flow"] == 7
        assert row["daily_pnl"] == 24
    assert bus.prepended == [(3, "collect_settlement")]
    if include_payout:
        assert result["positions"] == []
        for row in (result["equity"][1], report["accounts"][1]):
            assert row["cash"] == 124
            assert row["dividend_receivable"] == 0
            assert row["equity"] == 137
            assert row["daily_pnl"] == 0
    else:
        assert len(result["positions"]) == 1
        assert result["positions"][0]["quantity"] == 0
        assert result["positions"][0]["dividend_receivable"] == 24


def test_logs_do_not_copy_native_error_traceback_locals(monkeypatch):
    class Handler:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setitem(sys.modules, "logbook", SimpleNamespace(Handler=Handler, DEBUG=10))
    capture = worker.ReportCapture()
    handler = capture.handler()
    handler.emit(SimpleNamespace(channel="user_system_log", level_name="ERROR", msg="error",
                                 message="Traceback (most recent call last):\n  File /private/x\n"
                                 " --> token = confidential"))
    assert capture.logs[0]["message"] == "策略执行异常，内部堆栈已隐藏"
    native_error = SimpleNamespace(exc_val=RuntimeError("internal"))
    handler.emit(SimpleNamespace(channel="user_system_log", level_name="ERROR", msg=native_error,
                                 message="must not include repr of locals"))
    assert len(capture.logs) == 1


def test_large_user_print_and_invalid_unicode_stay_safe_and_bounded():
    capture = worker.ReportCapture()
    capture.user_print("x" * 100000, "tail", end="y" * 100000)
    assert len(capture.logs[0]["message"]) == 4096
    assert capture.truncated
    capture.append("bad \ud800")
    assert capture.logs[-1]["message"] == "bad ?"


def test_host_rejects_invalid_unicode_without_leaking_a_raw_exception(launch):
    messages = frames()
    messages[0] = {"__raw__": "{\"protocol\":\"atlas.rqalpha/v1\",\"request_id\":\"wrong\"}\n"}
    with pytest.raises(RunnerFailure):
        launch(messages).run({"op": "run"})
    runner = RqalphaSandbox(Path("."))
    with pytest.raises(RunnerFailure, match="编码"):
        runner._accept_log(log_row(message="\ud800"))


def test_startup_failures_attach_logs_without_touching_runtime(monkeypatch):
    runner = RqalphaSandbox(Path("."))
    runner.report_logs = [log_row()]

    def fail():
        raise OSError("internal launcher state")

    monkeypatch.setattr(runner, "_open_rqalpha", fail)
    with pytest.raises(RunnerUnavailable) as raised:
        runner.__enter__()
    assert raised.value.report_logs == [log_row()]
    assert "internal launcher" not in str(raised.value)


def test_syntax_error_reports_only_the_user_source_line(monkeypatch):
    monkeypatch.setattr(worker, "dispatch", lambda _: worker.check_source(
        "def init(c): pass\ndef handle_bar(:",
    ))
    output = BytesIO()
    worker.serve(BytesIO(json.dumps(request(op="run", stream=True)).encode()), output)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[0]["event"] == "log"
    assert rows[0]["row"]["line"] == rows[-1]["error"]["line"] == 2
    assert rows[-1]["ok"] is False
    assert "File " not in rows[0]["row"]["message"]


def test_worker_stream_channel_is_bounded(monkeypatch):
    monkeypatch.setattr(worker, "STREAM_BYTES", 8300)
    writer = worker.StreamWriter(BytesIO(), "a" * 32)
    with pytest.raises(worker.WorkerError, match="通道限制"):
        writer.write({"event": "log", "row": log_row(message="x" * 200)})
