import copy
import hashlib
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import rqalpha_backtests as rq
from app import rqalpha_industries as industries
from app import rqalpha_minute_data as minutes
from app.compute_objects import canonical_bytes
from app.lab_strategies import LabMultiSettings
from app.sandbox import RqalphaSandbox, RunnerFailure, RunnerUnavailable

DAYS = ["2025-01-02", "2025-01-03", "2025-01-06"]
SYMBOLS = ["600584.SS", "603986.SS"]
SOURCE = "def init(context):\n    pass\n\ndef handle_bar(context, bar_dict):\n    pass\n"


def signed(value):
    value.pop("digest", None)
    value["digest"] = hashlib.sha256(canonical_bytes(value)).hexdigest()
    return value


@pytest.fixture
def frozen_minutes(tmp_path, monkeypatch):
    daily_root, root = tmp_path / "daily", tmp_path / "minutes"
    daily_root.mkdir()
    root.mkdir()
    files = []
    for name in ("instruments.pk", "trading_dates.npy", "stocks.h5"):
        body = b"synthetic opaque bytes; never deserialized by host " + name.encode()
        (daily_root / name).write_bytes(body)
        files.append({"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    daily = signed({"schema": "atlas.rqalpha.dataset/v1", "engine_version": "6.5.0",
                    "usage": "academic-noncommercial-local-research", "bundle_root": ".",
                    "files": files, "sessions": DAYS,
                    "instruments": {symbol: {"native_symbol": symbol[:6] + ".XSHG",
                                              "start": DAYS[0], "end": DAYS[-1]}
                                    for symbol in SYMBOLS}})
    daily_index = tmp_path / "daily.json"
    daily_index.write_bytes(canonical_bytes(daily))
    record = {"as_of": DAYS[0], "published": "2024-12-20", "effective": "2025-01-01",
              "source": "https://example.test/verified-membership", "symbols": SYMBOLS}
    membership = signed({"schema": "atlas.rqalpha.sectors/v1", "industries": {
        key: [copy.deepcopy(record)] for key in industries.INDUSTRIES
    }})
    member_path = tmp_path / "members.json"
    member_path.write_bytes(canonical_bytes(membership))
    manifest = {"schema": minutes.SCHEMA, "adapter_version": minutes.SCHEMA,
                "engine_version": "6.5.0", "usage": "academic-noncommercial-local-research",
                "bar_convention": minutes.BAR_CONVENTION,
                "extra_session_policy": minutes.EXTRA_SESSION_POLICY,
                "daily_digest": daily["digest"], "membership_sha256": membership["digest"],
                "start": DAYS[0], "end": DAYS[-1], "sessions": DAYS,
                "source": {"repo_id": minutes.REPO, "revision": minutes.REVISION,
                           "timezone": "Asia/Singapore", "price_adjustment": "none",
                           "volume_unit": "shares", "turnover_unit": "CNY",
                           "last_complete_day": minutes.LAST_COMPLETE_DAY,
                           "license_declared": "apache-2.0", "source_files": []},
                "files": [], "instruments": {}}
    for symbol in SYMBOLS:
        path = f"bars/{symbol}/2025-01.csv.gz"
        file = root / path
        file.parent.mkdir(parents=True)
        body = b"opaque metadata test input; runtime separately validates CSV " + symbol.encode()
        file.write_bytes(body)
        manifest["files"].append({"path": path, "symbol": symbol, "month": "2025-01",
                                  "bytes": len(body), "rows": 723,
                                  "sha256": hashlib.sha256(body).hexdigest()})
        manifest["instruments"][symbol] = {
            "native_symbol": symbol[:6] + ".XSHG", "start": DAYS[0], "end": DAYS[-1],
            "complete_sessions": DAYS.copy(), "no_trade_sessions": {}, "gaps": {},
            "months": {"2025-01": path}, "source_path": f"data/stock_1m/SH/{symbol[:6]}.parquet",
            "source_sha256": "a" * 64, "source_bytes": 1000,
            "source_first": "2010-01-04T09:30:00", "source_last": "2026-08-07T10:21:00",
        }
    index = root / "index.json"

    def save():
        index.write_bytes(canonical_bytes(signed(manifest)))

    save()
    monkeypatch.setenv("ATLAS_RQALPHA_DATASET", str(daily_index))
    monkeypatch.setenv("ATLAS_RQALPHA_BUNDLE_DIR", str(daily_root))
    monkeypatch.setenv("ATLAS_RQALPHA_MINUTE_DATASET", str(index))
    monkeypatch.setenv("ATLAS_RQALPHA_MINUTE_DIR", str(root))
    monkeypatch.setenv("ATLAS_RQALPHA_SECTOR_MEMBERSHIP", str(member_path))
    return SimpleNamespace(manifest=manifest, root=root, index=index, save=save, daily=daily,
                           membership=membership, member_path=member_path)


def settings(interval="5m", **patch):
    return LabMultiSettings(engine_id="rqalpha", interval=interval, symbols=SYMBOLS,
                            industry="semiconductor", **patch)


def raw_result(config, market):
    return {"engine_version": "6.5.0", "matching_type": "current_bar",
            "bar_interval": config.interval, "minute_digest": market["minute_digest"],
            "minute_adapter_version": minutes.SCHEMA,
            "equity": [{"time": rq._close(day), "equity": config.initial_capital,
                        "cash": config.initial_capital, "market_value": 0} for day in DAYS],
            "trades": [], "positions": [], "rejections": [], "corporate_actions": [],
            "native_metrics": {"total_returns": 0}}


@pytest.mark.parametrize("interval", minutes.INTERVALS)
def test_five_periods_bind_daily_minute_and_dated_membership(frozen_minutes, interval):
    manifest, root = minutes.load()
    market = rq.resolve(settings(interval))
    assert root == frozen_minutes.root
    assert market["digest"] == minutes.combined_digest(manifest)
    assert market["digest"] != frozen_minutes.daily["digest"]
    assert market["daily_digest"] == frozen_minutes.daily["digest"]
    assert market["minute_digest"] == manifest["digest"]
    assert market["sessions"] == DAYS
    assert market["count"] == len(DAYS) * 240 // int(interval[:-1])
    assert market["symbol_bars"] == market["count"] * len(SYMBOLS)
    assert market["industry"]["versions"][0]["symbols"] == SYMBOLS
    assert market["minute_source"]["last_complete_day"] == "2026-08-06"
    assert "不同来源" in market["minute_source"]["provenance_note"]
    assert rq.minute_status()[0]["digest"] == manifest["digest"]


def test_unconfigured_minutes_do_not_claim_availability(monkeypatch):
    monkeypatch.delenv("ATLAS_RQALPHA_MINUTE_DATASET", raising=False)
    monkeypatch.delenv("ATLAS_RQALPHA_MINUTE_DIR", raising=False)
    with pytest.raises(RunnerUnavailable, match="尚未配置"):
        minutes.load()
    assert rq.minute_status()[0] is None


@pytest.mark.parametrize("change", ["digest", "revision", "timezone", "volume_unit", "late_end",
                                     "duplicate_day", "classification", "mapping", "native", "path",
                                     "duplicate_file", "rows", "size", "daily_binding",
                                     "member_binding"])
def test_frozen_metadata_refuses_corruption_or_wrong_bindings(frozen_minutes, change):
    value = frozen_minutes.manifest
    if change == "digest":
        value["digest"] = "0" * 64
        frozen_minutes.index.write_bytes(canonical_bytes(value))
    else:
        if change in ("revision", "timezone", "volume_unit"):
            value["source"][change] = "wrong"
        elif change == "late_end":
            value["end"] = "2026-08-07"
        elif change == "duplicate_day":
            value["sessions"] = [DAYS[0], *DAYS]
        elif change == "classification":
            value["instruments"][SYMBOLS[0]]["no_trade_sessions"] = {DAYS[0]: "unresolved_no_bar"}
        elif change == "mapping":
            value["instruments"][SYMBOLS[0]]["months"] = {}
        elif change == "native":
            value["instruments"][SYMBOLS[0]]["native_symbol"] = "600584.XSHE"
        elif change == "path":
            value["files"][0]["path"] = "../escape.csv.gz"
        elif change == "duplicate_file":
            value["files"].append(value["files"][0].copy())
        elif change == "rows":
            value["files"][0]["rows"] = 8001
        elif change == "size":
            value["files"][0]["bytes"] += 1
        elif change == "daily_binding":
            value["daily_digest"] = "0" * 64
        elif change == "member_binding":
            value["membership_sha256"] = "0" * 64
        frozen_minutes.save()
    with pytest.raises((RunnerFailure, RunnerUnavailable)):
        rq.resolve(settings())


def test_missing_continuous_minutes_are_not_silently_skipped(frozen_minutes):
    item = frozen_minutes.manifest["instruments"][SYMBOLS[0]]
    item["complete_sessions"].remove(DAYS[1])
    item["gaps"][DAYS[1]] = "missing_continuous_minutes:13:01"
    frozen_minutes.save()
    with pytest.raises(RunnerFailure, match="2025-01-03.*不完整"):
        rq.resolve(settings())


@pytest.mark.parametrize("classification", ["confirmed_suspension", "zero_daily_no_trade"])
def test_explicit_no_trade_days_are_not_filled_or_counted_as_source_gaps(
    frozen_minutes, classification,
):
    item = frozen_minutes.manifest["instruments"][SYMBOLS[0]]
    item["complete_sessions"].remove(DAYS[1])
    item["no_trade_sessions"][DAYS[1]] = classification
    frozen_minutes.save()
    assert rq.resolve(settings())["sessions"] == DAYS


def test_duplicate_index_fields_are_rejected(frozen_minutes):
    body = frozen_minutes.index.read_text()
    frozen_minutes.index.write_text('{"schema":"ignored",' + body[1:])
    with pytest.raises(RunnerUnavailable):
        minutes.load()


def test_extra_files_and_symlinks_are_not_accepted(frozen_minutes):
    extra = frozen_minutes.root / "not-in-index.py"
    extra.write_bytes(b"never executed")
    with pytest.raises(RunnerUnavailable):
        minutes.load()
    extra.unlink()
    path = frozen_minutes.root / frozen_minutes.manifest["files"][0]["path"]
    body = path.read_bytes()
    outside = frozen_minutes.root.parent / "outside.csv.gz"
    outside.write_bytes(body)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(RunnerUnavailable):
        minutes.load()


def test_tampered_bytes_are_rechecked_before_runner_launch(frozen_minutes, monkeypatch):
    config = settings()
    market = rq.resolve(config)
    file = frozen_minutes.root / frozen_minutes.manifest["files"][0]["path"]
    body = file.read_bytes()
    file.write_bytes(b"x" + body[1:])
    monkeypatch.setattr(rq, "RqalphaSandbox",
                        lambda *args, **kwargs: pytest.fail("must not launch"))
    with pytest.raises(RunnerFailure, match="SHA-256"):
        rq.execute(SOURCE, config, market)


def test_changed_snapshot_and_cancellation_do_not_start_a_strategy(frozen_minutes, monkeypatch):
    config = settings()
    market = rq.resolve(config)
    monkeypatch.setattr(rq, "RqalphaSandbox",
                        lambda *args, **kwargs: pytest.fail("must not launch"))
    with pytest.raises(RunnerFailure, match="取消"):
        rq.execute(SOURCE, config, market, cancelled=lambda: True)
    frozen_minutes.manifest["source"]["provenance_note"] = "changed snapshot"
    frozen_minutes.save()
    with pytest.raises(RunnerFailure, match="已变更"):
        rq.execute(SOURCE, config, market)


def test_minute_execution_uses_two_readonly_inputs_and_fixed_identity(frozen_minutes, monkeypatch):
    config = settings("60m")
    market = rq.resolve(config)
    seen = {}

    class Runner:
        def __init__(self, bundle, **kwargs):
            seen.update(bundle=bundle, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, payload):
            seen["payload"] = payload
            return raw_result(config, market)

    monkeypatch.setattr(rq, "RqalphaSandbox", Runner)
    result = rq.execute(SOURCE, config, market)
    assert seen["minute_bundle"] == frozen_minutes.root
    assert seen["payload"]["expected_daily_digest"] == frozen_minutes.daily["digest"]
    assert seen["payload"]["minute_membership"] == market["industry"]["versions"]
    assert result["interval"] == "60m"
    assert result["minute_digest"] == market["minute_digest"]
    assert result["proof_status"] == "unverified"


@pytest.mark.parametrize("change", ["bar_interval", "minute_digest", "minute_adapter_version"])
def test_wrong_minute_execution_identity_is_rejected(frozen_minutes, change):
    config = settings()
    market = rq.resolve(config)
    raw = raw_result(config, market)
    raw[change] = "wrong"
    with pytest.raises(RunnerFailure, match="分钟周期"):
        rq.validate_result(raw, config, market)


@pytest.mark.parametrize("clock", ["09:30", "09:36", "11:31", "12:00", "13:00", "15:01"])
def test_trades_cannot_use_extra_unclosed_or_lunch_bars(frozen_minutes, clock):
    config = settings()
    market = rq.resolve(config)
    raw = raw_result(config, market)
    stamp = int(datetime.fromisoformat(f"2025-01-02T{clock}:00").replace(
        tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    raw["trades"] = [{"symbol": SYMBOLS[0], "side": "buy", "time": stamp,
                      "quantity": 100, "price": 10, "fee": 5, "commission": 5, "tax": 0}]
    with pytest.raises(RunnerFailure, match="已完成"):
        rq.validate_result(raw, config, market)


def test_explicit_intraday_bounds_are_not_silently_ignored(frozen_minutes):
    zone = ZoneInfo("Asia/Shanghai")
    for patch in ({"start": datetime(2025, 1, 2, 14, tzinfo=zone)},
                  {"end": datetime(2025, 1, 6, 13, tzinfo=zone)}):
        with pytest.raises(RunnerFailure, match="完整交易日"):
            rq.resolve(settings(**patch))


def test_minute_symbol_budget_is_enforced_without_shrinking_range(frozen_minutes, monkeypatch):
    monkeypatch.setattr(minutes, "MAX_SYMBOL_BARS", 1)
    with pytest.raises(RunnerFailure, match="预算"):
        rq.resolve(settings("1m"))


def test_catalog_uses_requested_membership_date_and_per_stock_quality(frozen_minutes):
    later = copy.deepcopy(frozen_minutes.membership["industries"]["semiconductor"][0])
    later.update(as_of="2025-02-03", published="2025-01-20", symbols=["600001.SS"])
    frozen_minutes.membership["industries"]["semiconductor"].append(later)
    frozen_minutes.member_path.write_bytes(canonical_bytes(signed(frozen_minutes.membership)))
    early = industries.catalog(as_of="2025-01-02", minute=frozen_minutes.manifest)[0]
    late = industries.catalog(as_of="2025-02-03", minute=frozen_minutes.manifest)[0]
    assert [item["symbol"] for item in early["symbols"]] == SYMBOLS
    assert early["minute_intervals"] == list(minutes.INTERVALS)
    assert early["symbols"][0]["minute_available"] is True
    assert early["symbols"][0]["missing_sessions"] == 0
    assert early["minute_source"]["revision"] == minutes.REVISION
    assert "不表示" in early["coverage_note"]
    assert late["symbols"][0]["minute_available"] is False
    assert late["minute_intervals"] == []


def test_minute_mount_does_not_change_gvisor_limits(frozen_minutes, monkeypatch):
    runner = RqalphaSandbox(frozen_minutes.root.parent / "daily", minute_bundle=frozen_minutes.root)
    monkeypatch.setattr(runner, "_check_runtime", lambda: None)
    monkeypatch.setattr(runner, "_command", lambda *args: list(args))
    seen = {}

    def popen(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace()

    monkeypatch.setattr("app.sandbox.subprocess.Popen", popen)
    runner._open_rqalpha()
    command = seen["command"]
    assert "--runtime=runsc" in command
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--memory=1g" in command
    assert "--cpus=1" in command
    assert f"type=bind,src={frozen_minutes.root},dst=/minutes,readonly" in command
