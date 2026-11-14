import copy
import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import rqalpha_backtests as rq
from app.compute_objects import canonical_bytes
from app.lab_strategies import LabDraftCreate, LabMultiSettings
from app.sandbox import RqalphaSandbox, RunnerCleanupFailure, RunnerFailure, RunnerUnavailable

SYMBOLS = ["600519.SS", "000001.SZ"]
SOURCE = "def init(context):\n    pass\n\ndef handle_bar(context, bar_dict):\n    pass\n"
DAYS = ["2025-01-02", "2025-01-03", "2025-01-06"]


@pytest.fixture
def frozen_dataset(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    root.mkdir()
    files = []
    for name in ("instruments.pk", "trading_dates.npy", "stocks.h5"):
        content = b"not imported or unpickled by host " + name.encode()
        (root / name).write_bytes(content)
        files.append({"path": name, "bytes": len(content),
                      "sha256": hashlib.sha256(content).hexdigest()})
    data = {"schema": "atlas.rqalpha.dataset/v1", "engine_version": rq.ENGINE_VERSION,
            "usage": "academic-noncommercial-local-research", "bundle_root": ".",
            "files": files, "sessions": DAYS,
            "instruments": {symbol: {"native_symbol": symbol[:6] + suffix,
                                     "start": DAYS[0], "end": DAYS[-1]}
                            for symbol, suffix in zip(SYMBOLS, (".XSHG", ".XSHE"), strict=True)}}
    manifest = tmp_path / "dataset.json"

    def save(value):
        value.pop("digest", None)
        value["digest"] = hashlib.sha256(canonical_bytes(value)).hexdigest()
        manifest.write_bytes(canonical_bytes(value))

    save(data)
    monkeypatch.setenv("ATLAS_RQALPHA_DATASET", str(manifest))
    monkeypatch.setenv("ATLAS_RQALPHA_BUNDLE_DIR", str(root))
    return data, root, manifest, save


def settings(**patch):
    return LabMultiSettings(engine_id="rqalpha", symbols=SYMBOLS, **patch)


def result_for(config, market):
    return {"engine_version": rq.ENGINE_VERSION, "matching_type": "current_bar",
            "equity": [{"time": rq._close(day), "equity": config.initial_capital,
                        "cash": config.initial_capital, "market_value": 0}
                       for day in market["sessions"]],
            "trades": [], "positions": [], "rejections": [], "corporate_actions": [],
            "native_metrics": {"sharpe": None, "total_returns": 0}}


def test_source_validation_does_not_execute_code(tmp_path):
    path = tmp_path / "must-not-exist"
    rq.validate_source(f"open({str(path)!r}, 'w').write('bad')\n" + SOURCE)
    assert not path.exists()


@pytest.mark.parametrize("source", ["", " ", "class Strategy: pass", "def init(: pass",
                                          "__config__ = {}\n" + SOURCE, "\ud800", "x" * 60001])
def test_rejects_wrong_source_protocol(source):
    with pytest.raises(RunnerFailure):
        rq.validate_source(source)


def test_rejects_atlas_package():
    with pytest.raises(RunnerFailure, match="策略包"):
        rq.validate_source(SOURCE, "ZXhhbXBsZQ==")


@pytest.mark.parametrize("patch", [{"interval": "15m"}, {"universe": "semiconductor"},
                                   {"symbols": ["600519.SS", "430047.BJ"]}])
def test_settings_reject_unsupported_rqalpha_modes(patch):
    with pytest.raises(ValidationError):
        LabMultiSettings.model_validate({"engine_id": "rqalpha", "symbols": SYMBOLS, **patch})


def test_settings_preserve_old_atlas_and_reject_rqalpha_packages():
    assert LabMultiSettings(symbols=SYMBOLS).engine_id == "atlas_portfolio"
    with pytest.raises(ValidationError, match="策略包"):
        LabDraftCreate.model_validate({"id": "a" * 32, "name": "RQ", "kind": "multi_python",
                                       "language": "python", "source": SOURCE,
                                       "package_b64": "QQ==",
                                       "settings": {"engine_id": "rqalpha", "symbols": SYMBOLS}})


def test_resolve_freezes_actual_trading_days_and_does_not_import_data(frozen_dataset):
    data, _, _, _ = frozen_dataset
    selected = rq.resolve(settings())
    assert selected["digest"] == data["digest"]
    assert selected["sessions"] == DAYS
    assert selected["window"] == {"start": DAYS[0], "end": DAYS[-1]}
    assert selected["rule_version"] == rq.RULE_VERSION


def test_resolve_uses_beijing_inclusive_end_and_refuses_missing_data(frozen_dataset):
    config = settings(start=datetime(2025, 1, 2, 7, tzinfo=UTC),
                      end=datetime(2025, 1, 3, 7, tzinfo=UTC))
    assert rq.resolve(config)["sessions"] == DAYS[:2]
    with pytest.raises(RunnerFailure, match="覆盖范围"):
        rq.resolve(settings(start=datetime(2024, 1, 1, tzinfo=UTC)))
    with pytest.raises(RunnerFailure, match="未被"):
        rq.resolve(LabMultiSettings(engine_id="rqalpha", symbols=["600519.SS", "600001.SS"]))
    with pytest.raises(RunnerFailure, match="不足两个"):
        rq.resolve(settings(start=datetime(2025, 1, 6, tzinfo=UTC)))


@pytest.mark.parametrize("change", [
    "digest", "calendar", "path", "symbol", "engine", "size", "extra_file",
])
def test_dataset_metadata_rejects_corruption(frozen_dataset, change):
    data, root, path, save = frozen_dataset
    if change == "digest":
        data["digest"] = "0" * 64
        path.write_bytes(canonical_bytes(data))
    else:
        if change == "calendar":
            data["sessions"] = list(reversed(DAYS))
        if change == "path":
            data["files"][0]["path"] = "../escape"
        if change == "symbol":
            data["instruments"][SYMBOLS[0]]["native_symbol"] = "000001.XSHE"
        if change == "engine":
            data["engine_version"] = "other"
        if change == "size":
            data["files"][0]["bytes"] += 1
        if change == "extra_file":
            (root / "unexpected.h5").write_bytes(b"not part of the frozen input")
        save(data)
    with pytest.raises(RunnerUnavailable):
        rq.resolve(settings())


def test_result_metadata_is_host_owned_and_empty_trades_are_valid(frozen_dataset):
    config = settings()
    market = rq.resolve(config)
    raw = result_for(config, market)
    raw.update(engine_id="forged", proof_status="verified", total_return=900)
    result = rq.validate_result(raw, config, market)
    assert result["engine_id"] == "rqalpha"
    assert result["proof_status"] == "unverified"
    assert result["total_return"] == 0
    assert result["final_equity"] == config.initial_capital
    assert result["trades"] == []


@pytest.mark.parametrize("change", ["nan", "cash", "missing_day", "forged_version", "positions",
                                   "outside_trade", "fee", "native_metric", "wrong_record"])
def test_result_rejects_untrusted_worker_values(frozen_dataset, change):
    config = settings()
    market = rq.resolve(config)
    raw = result_for(config, market)
    trade = {"symbol": SYMBOLS[0], "side": "buy", "time": market["start"], "quantity": 100,
             "price": 10, "fee": 5, "commission": 5, "tax": 0}
    if change == "nan":
        raw["equity"][0]["cash"] = float("nan")
    if change == "cash":
        raw["equity"][0]["cash"] -= 1
    if change == "missing_day":
        raw["equity"].pop()
    if change == "forged_version":
        raw["engine_version"] = "other"
    if change == "positions":
        raw["positions"] = [{"symbol": SYMBOLS[0], "quantity": 100, "mark_price": 10,
                             "market_value": 1000, "sellable": 200}]
    if change == "outside_trade":
        raw["trades"] = [{**trade, "symbol": "600001.SS"}]
    if change == "fee":
        raw["trades"] = [{**trade, "fee": 0}]
    if change == "native_metric":
        raw["native_metrics"] = {"sharpe": "not a number"}
    if change == "wrong_record":
        raw["trades"] = [True]
    with pytest.raises(RunnerFailure):
        rq.validate_result(raw, config, market)


def test_execution_rechecks_frozen_bytes_before_starting_runner(frozen_dataset, monkeypatch):
    _, root, _, _ = frozen_dataset
    config = settings()
    market = rq.resolve(config)
    current = root / "stocks.h5"
    body = current.read_bytes()
    current.write_bytes(b"z" + body[1:])
    monkeypatch.setattr(
        rq, "RqalphaSandbox", lambda *args, **kwargs: pytest.fail("must not launch"),
    )
    with pytest.raises(RunnerFailure, match="摘要"):
        rq.execute(SOURCE, config, market)


def test_execution_uses_fixed_data_and_validates_runner_result(frozen_dataset, monkeypatch):
    config = settings()
    market = rq.resolve(config)
    seen = {}

    class FakeRunner:
        def __init__(self, bundle, **kwargs):
            seen["bundle"] = Path(bundle)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, payload):
            seen["payload"] = copy.deepcopy(payload)
            return result_for(config, market)

    monkeypatch.setattr(rq, "RqalphaSandbox", FakeRunner)
    result = rq.execute(SOURCE, config, market)
    assert result["proof_status"] == "unverified"
    assert seen["bundle"] == frozen_dataset[1]
    assert seen["payload"]["window"] == market["window"]
    assert seen["payload"]["settings"]["engine_id"] == "rqalpha"


@pytest.mark.parametrize("removal,inspection,leftover,fails", [
    (0, 0, b"", False), (1, 0, b"", False),
    (1, 0, b"atlas-run-residual\n", True), (1, 1, b"", True),
])
def test_cleanup_distinguishes_absent_container_from_failure(
    monkeypatch, removal, inspection, leftover, fails,
):
    runner = RqalphaSandbox(Path("."))
    monkeypatch.setattr(runner, "_command", lambda *args: list(args))
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=removal if command[0] == "rm" else inspection,
                               stdout=b"" if command[0] == "rm" else leftover)

    monkeypatch.setattr("app.sandbox.subprocess.run", execute)
    if fails:
        with pytest.raises(RunnerCleanupFailure, match="清理"):
            runner._remove_container()
    else:
        runner._remove_container()
    assert calls[0] == ["rm", "--force", runner.name]
    assert len(calls) == (1 if removal == 0 else 2)


def test_cleanup_timeout_is_not_silently_ignored(monkeypatch):
    runner = RqalphaSandbox(Path("."))
    monkeypatch.setattr(runner, "_command", lambda *args: list(args))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("docker", 10)

    monkeypatch.setattr("app.sandbox.subprocess.run", timeout)
    with pytest.raises(RunnerCleanupFailure, match="清理失败"):
        runner._remove_container()


def add_benchmark(frozen_dataset, covered=None):
    data, root, _, save = frozen_dataset
    content = b"synthetic index bytes; never imported by the host"
    (root / "indexes.h5").write_bytes(content)
    data["files"].append({"path": "indexes.h5", "bytes": len(content),
                          "sha256": hashlib.sha256(content).hexdigest()})
    covered = covered or DAYS
    data["benchmarks"] = {"000300.SS": {"native_symbol": "000300.XSHG", "name": "沪深300",
                                           "start": covered[0], "end": covered[-1],
                                           "sessions": covered}}
    save(data)
    return data


def test_benchmark_requires_frozen_index_and_previous_session(frozen_dataset):
    config = settings(benchmark="000300.SS")
    with pytest.raises(RunnerFailure, match="未核验"):
        rq.resolve(config)
    add_benchmark(frozen_dataset)
    with pytest.raises(RunnerFailure, match="前一交易日"):
        rq.resolve(config)
    config.start = datetime(2025, 1, 3, tzinfo=UTC)
    selected = rq.resolve(config)
    assert selected["sessions"] == DAYS[1:]
    assert selected["benchmark"] == "000300.SS"
    assert rq.benchmark_options() == [{"symbol": "000300.SS", "name": "沪深300",
                                       "start": DAYS[0], "end": DAYS[-1]}]


def test_benchmark_cannot_skip_an_internal_trading_day(frozen_dataset):
    add_benchmark(frozen_dataset, [DAYS[0], DAYS[-1]])
    with pytest.raises(RunnerFailure, match="完整"):
        rq.resolve(settings(benchmark="000300.SS", start=datetime(2025, 1, 3, tzinfo=UTC)))


@pytest.mark.parametrize("change", ["name", "native_symbol", "sessions", "unknown"])
def test_benchmark_metadata_identity_is_validated(frozen_dataset, change):
    data = add_benchmark(frozen_dataset)
    if change == "unknown":
        data["benchmarks"]["510300.SS"] = data["benchmarks"].pop("000300.SS")
    else:
        data["benchmarks"]["000300.SS"][change] = "wrong"
    frozen_dataset[-1](data)
    with pytest.raises(RunnerUnavailable):
        rq.resolve(settings())


def test_benchmark_settings_are_rqalpha_only():
    with pytest.raises(ValidationError, match="仅用于"):
        LabMultiSettings(symbols=SYMBOLS, benchmark="000300.SS")
    with pytest.raises(ValidationError):
        settings(benchmark="510300.SS")
