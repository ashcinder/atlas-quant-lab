import json
import sys
from decimal import Decimal
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from app.private_compute import PrivateCompute


class Runtime:
    def __init__(self):
        self.allowed = True
        self.release = {"owner_id": "author", "name": "Published name", "source_kind": "builtin"}
        self.snapshot = {"params": {"fast": 3, "slow": 8}}

    def backtest_release(self, owner, identifier):
        if not self.allowed:
            raise HTTPException(403, "subscription revoked")
        return "sma_cross", self.snapshot

    def _connect(self):
        return nullcontext(None)

    def _release_for(self, db, identifier):
        return self.release


class Publications:
    def manifest(self, identifier):
        if identifier != "registered":
            raise KeyError(identifier)
        return {"asset": {"symbol": "BTC-USD", "name": "Bitcoin", "asset_class": "crypto",
                          "exchange": "CRYPTO", "currency": "USD"},
                "interval": "1d", "adjustment": "raw", "source": "fixture"}

    def bundle(self, identifier, start, end):
        frame = pd.DataFrame({"open": [100 + i for i in range(70)],
                              "high": [102 + i for i in range(70)],
                              "low": [99 + i for i in range(70)],
                              "close": [101 + i for i in range(70)], "volume": 10000},
                             index=pd.date_range("2025-01-01", periods=70, tz="UTC"))
        if start is not None:
            frame = frame.loc[frame.index >= start]
        if end is not None:
            frame = frame.loc[frame.index <= end]
        return SimpleNamespace(frame=frame)


@pytest.fixture
def service():
    return PrivateCompute(Runtime(), Publications())


def result():
    return {"run_id": "new", "created_at": datetime.now(UTC).isoformat(),
            "asset": Publications().manifest("registered")["asset"], "interval": "1d",
            "strategy": {"id": "secret_algorithm", "name": "SECRET", "category": "secret",
                         "description": "SECRET source", "suitable_for": "secret", "risk_level": "高",
                         "parameters": [{"key": "threshold", "label": "secret", "kind": "number", "default": 5}]},
            "data_source": "fixture", "source_note": "SECRET debug", "bars": [], "indicators": {},
            "trades": [{"reason": "SECRET rule"}], "equity": [], "metrics": {}, "regime_metrics": {},
            "warnings": ["SECRET warning"]}


@pytest.mark.parametrize("key", ["symbol", "asset_class", "interval", "adjustment", "params", "python_source",
                                 "python_program", "custom_strategy", "strategy_id", "execution_pipeline", "persist",
                                 "proof_status", "bars", "batch"])
def test_rejects_logic_data_and_proof_overrides(service, key):
    with pytest.raises(HTTPException) as error:
        service.backtest("subscriber", "release", "registered", {key: None})
    assert error.value.status_code == 422


def test_sanitizes_subscriber_and_marks_unverified(service, monkeypatch):
    monkeypatch.setattr(service, "_execute", lambda encoded: result())
    output = service.backtest("subscriber", "release", "registered", {})
    assert "SECRET" not in json.dumps(output)
    assert "secret_algorithm" not in json.dumps(output)
    assert output["strategy"]["parameters"] == []
    assert output["strategy"]["id"] == "release"
    assert output["compute"]["dataset_ids"] == ["registered"]
    assert output["proof_status"] == "unverified"


def test_input_uses_registered_identity_and_fixed_program(service, monkeypatch):
    service.runtime.snapshot = {"params": {}, "python_program": {"secret": "fixed"}}
    captured = {}

    def execute(encoded):
        captured.update(json.loads(encoded))
        return result()

    monkeypatch.setattr(service, "_execute", execute)
    service.backtest("subscriber", "release", "registered", {"initial_capital": 500})
    assert captured["request"]["symbol"] == "BTC-USD"
    assert captured["request"]["initial_capital"] == 500
    assert captured["request"]["persist"] is False
    assert captured["program"] == {"secret": "fixed"}


def test_rechecks_revoked_entitlement_and_releases_slot(service, monkeypatch):
    def execute(encoded):
        service.runtime.allowed = False
        return result()

    monkeypatch.setattr(service, "_execute", execute)
    with pytest.raises(HTTPException) as error:
        service.backtest("subscriber", "release", "registered", {})
    assert error.value.status_code == 403
    assert not service._owners
    assert not service._serial.locked()


def test_duplicate_owner_and_full_queue_fail_fast(service, monkeypatch):
    service._owners.add("subscriber")
    with pytest.raises(HTTPException) as error:
        service.backtest("subscriber", "release", "registered", {})
    assert error.value.status_code == 429
    for _ in range(5):
        assert service._capacity.acquire(False)
    with pytest.raises(HTTPException) as error:
        service.backtest("other", "release", "registered", {})
    assert error.value.status_code == 429


def test_registered_dataset_missing_releases_permit(service):
    with pytest.raises(HTTPException) as error:
        service.backtest("subscriber", "release", "missing", {})
    assert error.value.status_code == 404
    assert not service._owners
    assert not service._serial.locked()


@pytest.mark.skipif(sys.platform != "linux", reason="Darwin cannot enforce the mandatory address-space limit")
def test_real_resource_limited_subprocess(service):
    output = service.backtest("subscriber", "release", "registered", {})
    assert len(output["bars"]) == 70
    assert output["trades"]
    assert output["metrics"]["total_return"] > 0
    assert output["execution_location"] == "server_private"


def test_worker_environment_excludes_host_keys(service, monkeypatch):
    monkeypatch.setattr("app.private_compute.sys.platform", "linux")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "DO-NOT-PASS")
    monkeypatch.setenv("ATLAS_DATA_DIR", "/private/do-not-read")
    captured = {}

    class Process:
        returncode = 1

        def communicate(self, **kwargs):
            return None, None

    def popen(*args, **kwargs):
        captured.update(kwargs["env"])
        return Process()

    monkeypatch.setattr("app.private_compute.subprocess.Popen", popen)
    with pytest.raises(HTTPException):
        service._execute(b"{}")
    assert "DEEPSEEK_API_KEY" not in captured
    assert captured["ATLAS_DATA_DIR"] != "/private/do-not-read"
    assert captured["OPENBLAS_NUM_THREADS"] == "1"


def test_unsupported_os_fails_closed(service, monkeypatch):
    monkeypatch.setattr("app.private_compute.sys.platform", "darwin")
    with pytest.raises(HTTPException) as error:
        service._execute(b"{}")
    assert error.value.status_code == 503


def test_timeout_kills_reaps_and_hides_diagnostics(service, monkeypatch):
    import subprocess
    monkeypatch.setattr("app.private_compute.sys.platform", "linux")

    class Process:
        killed = False
        reaped = False

        def communicate(self, **kwargs):
            if "timeout" in kwargs:
                raise subprocess.TimeoutExpired("SECRET executable arguments", 60)
            self.reaped = True

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr("app.private_compute.subprocess.Popen", lambda *args, **kwargs: process)
    with pytest.raises(HTTPException) as error:
        service._execute(b"{}")
    assert error.value.status_code == 504
    assert "SECRET" not in error.value.detail
    assert process.killed and process.reaped


def test_targets_share_owner_capacity_and_restore_series_index(service, monkeypatch):
    bundle = Publications().bundle("registered", None, None)
    captured = {}

    def execute(encoded, result_kind="backtest"):
        captured.update(json.loads(encoded))
        assert result_kind == "targets"
        with pytest.raises(HTTPException) as error:
            service.backtest("subscriber", "release", "registered", {})
        assert error.value.status_code == 429
        return {"targets": [0.5] * len(bundle.frame), "reasons": ["internal secret"] * len(bundle.frame)}

    monkeypatch.setattr(service, "_execute", execute)
    values, reasons = service.targets("subscriber", "release", bundle, Decimal("10000"), [100])
    assert values.index.equals(bundle.frame.index)
    assert (values == 0.5).all()
    assert (reasons == "internal secret").all()
    assert captured["snapshot"] == service.runtime.snapshot
    assert captured["operation"] == "targets"
    assert captured["initial_cash"] == "10000"
    assert captured["schedule_history"] == [100]
    assert not service._owners and not service._serial.locked()


def test_runtime_targets_match_existing_scheduled_calendar(service):
    # Pure worker helper parity does not spawn/prove or require Linux resources.
    from app.private_compute_worker import targets
    from app.strategies.schedule import contribution_schedule
    frame = Publications().bundle("registered", None, None).frame
    history = [int(frame.index[4].timestamp()), int(frame.index[9].timestamp())]
    body = {"source_kind": "builtin", "strategy_id": "scheduled_dca", "schedule_history": history,
            "snapshot": {"params": {"every": 1, "unit": "weeks", "start_delay": 1}}}
    actual, reasons = targets(body, frame)
    dates = pd.to_datetime(history, unit="s", utc=True).union(frame.index[frame.index >= pd.Timestamp(min(history), unit="s", tz="UTC")]).sort_values()
    expected = pd.Series(contribution_schedule(dates, 1, "weeks", 1), index=dates, dtype=float).reindex(frame.index, fill_value=0.0)
    pd.testing.assert_series_equal(actual, expected)
    assert set(reasons) <= {"等待定投", "固定金额定投"}


@pytest.mark.skipif(sys.platform != "linux", reason="Darwin cannot enforce the mandatory address-space limit")
def test_real_resource_limited_runtime_targets(service):
    frame = Publications().bundle("registered", None, None).frame
    from app.strategies.signals import generate_target_exposure
    actual, reasons = service.targets("subscriber", "release", SimpleNamespace(frame=frame), Decimal("10000"))
    expected, expected_reasons = generate_target_exposure(frame, "sma_cross", service.runtime.snapshot["params"], 1.0)
    pd.testing.assert_series_equal(actual, expected, check_names=False)
    pd.testing.assert_series_equal(reasons, expected_reasons, check_names=False)
