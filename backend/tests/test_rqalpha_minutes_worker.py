import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import sys
from collections import OrderedDict
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = spec_from_file_location("rqalpha_minutes_test", ROOT / "strategy/runner/rqalpha_minutes.py")
minutes = module_from_spec(SPEC)
SPEC.loader.exec_module(minutes)
WORKER_SPEC = spec_from_file_location(
    "rqalpha_minutes_worker_test", ROOT / "strategy/runner/rqalpha_worker.py"
)
worker = module_from_spec(WORKER_SPEC)
WORKER_SPEC.loader.exec_module(worker)
SYMBOL = "600584.SS"
NATIVE = "600584.XSHG"
DAYS = (dt.date(2025, 1, 2), dt.date(2025, 1, 3))
DAILY_DIGEST = "a" * 64
MEMBERSHIP = [
    {
        "as_of": "2024-12-01",
        "published": "2024-12-20",
        "effective": "2025-01-01",
        "symbols": [SYMBOL, "600519.SS"],
    }
]


def rows_for(day):
    result = [
        (
            minutes.encoded(dt.datetime.combine(day, dt.time(9, 30))),
            9.5,
            10.1,
            9.4,
            9.8,
            9000,
            90000,
        )
    ]
    for i, code in enumerate(minutes.continuous_codes(day)):
        opening = 10 + i / 100
        result.append(
            (
                int(code),
                opening,
                opening + 0.02,
                opening - 0.01,
                opening + 0.01,
                100 + i,
                (100 + i) * opening,
            )
        )
    return result


def freeze(root, index, rows=None):
    path = root / "bars" / SYMBOL / "2025-01.csv.gz"
    if rows is not None:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(minutes.COLUMNS)
        writer.writerows(rows)
        path.write_bytes(gzip.compress(buffer.getvalue().encode(), mtime=0))
        index["files"][0].update(
            bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            rows=len(rows),
        )
    index.pop("digest", None)
    index["digest"] = hashlib.sha256(minutes.canonical(index)).hexdigest()
    (root / "index.json").write_bytes(minutes.canonical(index))
    return index["digest"]


@pytest.fixture
def frozen(tmp_path):
    root = tmp_path / "minutes"
    (root / "bars" / SYMBOL).mkdir(parents=True)
    index = {
        "schema": minutes.SCHEMA,
        "adapter_version": minutes.SCHEMA,
        "engine_version": "6.5.0",
        "usage": "academic-noncommercial-local-research",
        "daily_digest": DAILY_DIGEST,
        "membership_sha256": "b" * 64,
        "start": "2025-01-02",
        "end": "2025-01-03",
        "sessions": [day.isoformat() for day in DAYS],
        "bar_convention": "end-label-session-local/v1",
        "extra_session_policy": (
            "retained-for-cumulative-snapshot;excluded-from-continuous-bars-and-orders"
        ),
        "source": {
            "repo_id": "neigezhu/china-a-share-1min-ohlcv",
            "revision": "ba589a11534825044fe5a6b84838f50ba8d8d188",
            "timezone": "Asia/Singapore",
            "price_adjustment": "none",
            "volume_unit": "shares",
            "turnover_unit": "CNY",
            "last_complete_day": "2026-08-06",
            "license_declared": "apache-2.0",
            "source_files": [{"path": "metadata/source_provenance.json", "sha256": "c" * 64}],
        },
        "files": [{"path": f"bars/{SYMBOL}/2025-01.csv.gz", "symbol": SYMBOL, "month": "2025-01"}],
        "instruments": {
            SYMBOL: {
                "native_symbol": NATIVE,
                "start": "2025-01-02",
                "end": "2025-01-03",
                "complete_sessions": [day.isoformat() for day in DAYS],
                "no_trade_sessions": {},
                "gaps": {},
                "months": {"2025-01": f"bars/{SYMBOL}/2025-01.csv.gz"},
                "source_path": "data/stock_1m/SH/600584.parquet",
                "source_sha256": "d" * 64,
                "source_bytes": 1000,
                "source_first": "2010-01-04T09:30:00",
                "source_last": "2026-08-07T10:21:00",
            }
        },
    }
    digest = freeze(root, index, rows_for(DAYS[0]) + rows_for(DAYS[1]))
    settings = {"symbols": [SYMBOL], "interval": "1m", "industry": "semiconductor"}
    window = {"start": "2025-01-02", "end": "2025-01-03"}
    return root, index, digest, settings, window


def store_for(frozen, **patch):
    root, _, digest, settings, window = frozen
    return minutes.MinuteStore(digest, DAILY_DIGEST, {**settings, **patch}, window, root=root)


def test_frozen_index_and_selected_chunks_are_verified_before_execution(frozen):
    store = store_for(frozen)
    assert store.digest == frozen[2]
    assert store.request_sessions == DAYS
    assert store.cache == OrderedDict()
    assert len(store.month(SYMBOL, "2025-01")["raw"]) == 482


@pytest.mark.parametrize("industry", ["semiconductor", "strait"])
@pytest.mark.parametrize(
    "interval,per_day", [("1m", 240), ("5m", 48), ("15m", 16), ("30m", 8), ("60m", 4)]
)
def test_five_periods_aggregate_exact_continuous_minutes_without_lunch_or_extra_opening(
    frozen, interval, per_day, industry,
):
    store = store_for(frozen, interval=interval, industry=industry)
    size = minutes.INTERVALS[interval]
    bars = store.bars(SYMBOL, "2025-01", size)
    raw = store.bars(SYMBOL, "2025-01", 1)
    assert len(bars) == 2 * per_day
    assert bars["datetime"][0] == minutes.continuous_codes(DAYS[0])[size - 1]
    assert bars["datetime"][per_day // 2 - 1] == 20250102113000
    assert bars["datetime"][per_day // 2] == minutes.continuous_codes(DAYS[0])[120 + size - 1]
    assert bars["datetime"][per_day - 1] == 20250102150000
    assert bars["open"][0] == raw["open"][0]
    assert bars["close"][0] == raw["close"][size - 1]
    assert bars["volume"][0] == raw["volume"][:size].sum()
    assert bars["total_turnover"][0] == raw["total_turnover"][:size].sum()
    assert bars["high"][0] == raw["high"][:size].max()
    assert bars["low"][0] == raw["low"][:size].min()
    assert not np.isin(bars["datetime"] % 1_000_000, [93000, 130000]).any()


@pytest.mark.parametrize("industry", [None, "", "unapproved-theme", "strait-extra"])
def test_native_minute_store_rejects_unconfigured_industries(frozen, industry):
    with pytest.raises(minutes.MinuteError, match="行业/题材"):
        store_for(frozen, industry=industry)


def test_raw_one_minute_stays_one_minute_and_n_bar_never_reads_its_future_close(frozen):
    store = store_for(frozen, interval="60m")
    moment = dt.datetime(2025, 1, 2, 9, 31)
    assert store.get_bar(SYMBOL, moment, 60) is None
    one = store.get_bar(SYMBOL, moment, 1)
    assert one["datetime"] == 20250102093100
    assert one["volume"] == 100
    assert store.get_bar(SYMBOL, dt.datetime(2025, 1, 2, 9, 30), 1) is None
    assert len(store.history(SYMBOL, dt.datetime(2025, 1, 2, 13, 59), 10, 60)) == 2
    assert len(store.history(SYMBOL, dt.datetime(2025, 1, 2, 14), 10, 60)) == 3
    assert store.history(SYMBOL, dt.datetime(2025, 1, 3, 8, 30), 1)[0]["datetime"] == 20250102150000


def historical_store(frozen, *, partial=True, older=True, no_trade=None):
    root, index, _, settings, _ = frozen
    later = (dt.date(2025, 1, 6), dt.date(2025, 1, 7))
    index["end"] = later[-1].isoformat()
    index["sessions"] = [day.isoformat() for day in (*DAYS, *later)]
    complete = ([DAYS[0]] if older else []) + list(later)
    info = index["instruments"][SYMBOL]
    info["start"], info["end"] = complete[0].isoformat(), complete[-1].isoformat()
    info["complete_sessions"] = [day.isoformat() for day in complete]
    if no_trade is None:
        info["gaps"] = {DAYS[1].isoformat(): "incomplete minutes" if partial else "no bars"}
    else:
        info["no_trade_sessions"] = {DAYS[1].isoformat(): no_trade}
    rows = rows_for(DAYS[0]) if older else []
    if partial and no_trade is None:
        rows.extend(rows_for(DAYS[1])[0:100] + rows_for(DAYS[1])[101:])
    for day in later:
        rows.extend(rows_for(day))
    digest = freeze(root, index, rows)
    return minutes.MinuteStore(
        digest,
        DAILY_DIGEST,
        settings,
        {"start": later[0].isoformat(), "end": later[-1].isoformat()},
        root=root,
    )


@pytest.mark.parametrize("interval", [1, 5, 15, 30, 60])
@pytest.mark.parametrize("partial", [True, False])
def test_history_fails_when_crossing_gap_before_run_but_count_one_stays_local(
    frozen,
    interval,
    partial,
):
    store = historical_store(frozen, partial=partial)
    query = dt.datetime(2025, 1, 6, 9, 30) + dt.timedelta(minutes=interval)
    assert store.start == dt.date(2025, 1, 6)
    assert store.history(SYMBOL, query, 1, interval)[0]["datetime"] == minutes.encoded(query)
    with pytest.raises(minutes.MinuteError, match="已知数据缺口"):
        store.history(SYMBOL, query, 2, interval)
    before_gap = dt.datetime(2025, 1, 2, 15)
    assert len(store.history(SYMBOL, before_gap, 100_000, interval)) == 240 // interval


@pytest.mark.parametrize("interval", [1, 5, 15, 30, 60])
@pytest.mark.parametrize("partial", [True, False])
def test_insufficient_history_cannot_silently_traverse_gap_without_older_complete_bars(
    frozen,
    interval,
    partial,
):
    store = historical_store(frozen, partial=partial, older=False)
    query = dt.datetime(2025, 1, 6, 9, 30) + dt.timedelta(minutes=interval)
    assert len(store.history(SYMBOL, query, 1, interval)) == 1
    with pytest.raises(minutes.MinuteError, match="已知数据缺口"):
        store.history(SYMBOL, query, 2, interval)
    with pytest.raises(minutes.MinuteError, match="已知数据缺口"):
        store.history(SYMBOL, dt.datetime(2025, 1, 6, 8, 30), 1, interval)


@pytest.mark.parametrize("interval", [1, 5, 15, 30, 60])
@pytest.mark.parametrize("classification", ["confirmed_suspension", "zero_daily_no_trade"])
def test_history_can_cross_confirmed_no_trade_day(frozen, interval, classification):
    store = historical_store(frozen, no_trade=classification)
    query = dt.datetime(2025, 1, 6, 9, 30) + dt.timedelta(minutes=interval)
    values = store.history(SYMBOL, query, 2, interval)
    assert list(values["datetime"]) == [20250102150000, minutes.encoded(query)]


def test_visible_cumulative_snapshot_retains_only_visible_extra_observations(frozen):
    store = store_for(frozen)
    assert minutes.cumulative(store.visible(SYMBOL, dt.datetime(2025, 1, 2, 9, 29))) is None
    extra = minutes.cumulative(store.visible(SYMBOL, dt.datetime(2025, 1, 2, 9, 30)))
    assert extra["datetime"] == 20250102093000
    assert extra["open"] == 9.5
    assert extra["high"] == 10.1
    assert extra["low"] == 9.4
    assert extra["volume"] == 9000
    first = minutes.cumulative(store.visible(SYMBOL, dt.datetime(2025, 1, 2, 9, 31)))
    assert first["volume"] == 9100
    assert first["close"] == 10.01
    assert first["high"] == 10.1
    assert minutes.cumulative(store.visible(SYMBOL, dt.datetime(2025, 1, 3, 9, 29))) is None


@pytest.mark.parametrize(
    "change", ["digest", "source", "daily", "extra_file", "missing_file", "symlink", "rows"]
)
def test_index_file_set_and_content_tampering_fail_closed(frozen, change):
    root, index, digest, settings, window = frozen
    path = root / index["files"][0]["path"]
    if change == "digest":
        index["usage"] = "commercial"
        (root / "index.json").write_text(json.dumps(index))
    elif change == "source":
        index["source"]["revision"] = "main"
        digest = freeze(root, index)
    elif change == "daily":
        index["daily_digest"] = "c" * 64
        digest = freeze(root, index)
    elif change == "extra_file":
        (root / "json.py").write_text("raise RuntimeError('untrusted data is not code')")
    elif change == "missing_file":
        path.unlink()
    elif change == "symlink":
        copied = root.parent / "copy.csv.gz"
        copied.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copied)
    elif change == "rows":
        index["files"][0]["rows"] = minutes.MONTH_ROWS + 1
        digest = freeze(root, index)
    with pytest.raises(minutes.MinuteError):
        minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)


def test_selected_months_are_rehashed_on_demand(frozen):
    store = store_for(frozen)
    path = frozen[0] / frozen[1]["files"][0]["path"]
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(minutes.MinuteError, match="摘要"):
        store.month(SYMBOL, "2025-01")


@pytest.mark.parametrize(
    "change",
    [
        "missing_minute",
        "duplicate",
        "order",
        "invalid_price",
        "nan",
        "fractional_volume",
        "wrong_month",
    ],
)
def test_reader_defends_complete_day_and_raw_price_time_rules(frozen, change):
    root, index, _, settings, window = frozen
    rows = rows_for(DAYS[0]) + rows_for(DAYS[1])
    if change == "missing_minute":
        rows.pop(2)
    elif change == "duplicate":
        rows.insert(2, rows[1])
    elif change == "order":
        rows[1], rows[2] = rows[2], rows[1]
    elif change in {"invalid_price", "nan", "fractional_volume"}:
        value = list(rows[1])
        value[2 if change != "fractional_volume" else 5] = (
            -1 if change == "invalid_price" else float("nan") if change == "nan" else 1.5
        )
        rows[1] = tuple(value)
    else:
        rows = rows_for(dt.date(2025, 2, 3))
    digest = freeze(root, index, rows)
    store = minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)
    with pytest.raises(minutes.MinuteError):
        store.month(SYMBOL, "2025-01")


def test_gzip_expansion_bomb_is_bounded(frozen):
    root, index, _, settings, window = frozen
    path = root / index["files"][0]["path"]
    path.write_bytes(gzip.compress(b"x" * (minutes.MONTH_BYTES + 1), mtime=0))
    index["files"][0].update(
        bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()
    )
    digest = freeze(root, index)
    store = minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)
    with pytest.raises(minutes.MinuteError, match="解压"):
        store.month(SYMBOL, "2025-01")


def test_cache_is_month_bounded_instead_of_preloading_history(frozen):
    store = store_for(frozen)
    for i in range(64):
        store.cache[("old", str(i))] = {}
    store.month(SYMBOL, "2025-01")
    assert len(store.cache) == 64
    assert ("old", "0") not in store.cache


@pytest.mark.parametrize(
    "classification,allowed",
    [
        ("confirmed_suspension", True),
        ("zero_daily_no_trade", True),
        ("unresolved_no_bar", False),
        ("confirmed_no_trade", False),
    ],
)
def test_only_actual_confirmed_no_trade_classes_can_cover_a_missing_day(
    frozen, classification, allowed
):
    root, index, _, settings, window = frozen
    info = index["instruments"][SYMBOL]
    info["complete_sessions"] = [DAYS[0].isoformat()]
    info["end"] = DAYS[0].isoformat()
    info["no_trade_sessions"] = {DAYS[1].isoformat(): classification}
    digest = freeze(root, index, rows_for(DAYS[0]))
    if allowed:
        store = minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)
        assert store.get_bar(SYMBOL, dt.datetime(2025, 1, 3, 9, 31)) is None
    else:
        with pytest.raises(minutes.MinuteError):
            minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)


def test_unresolved_day_or_unfrozen_window_is_rejected(frozen):
    root, index, digest, settings, window = frozen
    with pytest.raises(minutes.MinuteError):
        minutes.MinuteStore(
            digest, DAILY_DIGEST, settings, {**window, "end": "2025-01-04"}, root=root
        )
    info = index["instruments"][SYMBOL]
    info["complete_sessions"] = [DAYS[0].isoformat()]
    info["end"] = DAYS[0].isoformat()
    info["gaps"] = {DAYS[1].isoformat(): "missing continuous minute"}
    digest = freeze(root, index)
    with pytest.raises(minutes.MinuteError, match="缺口"):
        minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)


def test_dated_membership_does_not_backfill_future_entries_and_allows_exit():
    records = minutes.validate_membership(
        [
            *MEMBERSHIP,
            {
                "as_of": "2025-01-01",
                "published": "2025-01-02",
                "effective": "2025-01-03",
                "symbols": ["600519.SS"],
            },
        ]
    )
    env = SimpleNamespace(trading_dt=dt.datetime(2025, 1, 2, 10))

    def phase():
        return SimpleNamespace(name="ON_BAR")

    validator = minutes.EligibilityValidator(env, records, phase)
    buy = SimpleNamespace(side=SimpleNamespace(name="BUY"), order_book_id=NATIVE)
    assert validator.validate_submission(buy) is None
    env.trading_dt = dt.datetime(2025, 1, 3, 10)
    assert "名单" in validator.validate_submission(buy)
    assert (
        validator.validate_submission(
            SimpleNamespace(side=SimpleNamespace(name="SELL"), order_book_id=NATIVE)
        )
        is None
    )
    same_day = minutes.EligibilityValidator(
        env,
        minutes.validate_membership(
            [
                {
                    "as_of": "2025-01-01",
                    "published": "2025-01-03",
                    "effective": "2025-01-03",
                    "symbols": [SYMBOL],
                },
            ]
        ),
        phase,
    )
    assert same_day.validate_submission(buy) is not None
    auction = minutes.EligibilityValidator(
        env, records, lambda: SimpleNamespace(name="OPEN_AUCTION")
    )
    assert "集合竞价" in auction.validate_submission(buy)


@pytest.mark.parametrize(
    "records",
    [
        None,
        [],
        [{"as_of": "bad", "symbols": [SYMBOL]}],
        [{**MEMBERSHIP[0], "symbols": ["BTC"]}],
        [MEMBERSHIP[0], MEMBERSHIP[0]],
    ],
)
def test_invalid_membership_is_rejected(records):
    with pytest.raises(minutes.MinuteError):
        minutes.validate_membership(records)


@pytest.mark.parametrize("industry", ["semiconductor", "strait"])
@pytest.mark.parametrize("interval", minutes.INTERVALS)
def test_worker_uses_one_minute_native_clock_and_trusted_sibling_module(industry, interval):
    base = {
        "symbols": [SYMBOL],
        "interval": interval,
        "industry": industry,
        "initial_capital": 100000,
        "commission_rate": 0.001,
        "slippage_rate": 0,
        "max_position": 1,
        "max_participation_rate": 0.01,
    }
    config = worker.run_config(base, {"start": "2025-01-02", "end": "2025-01-03"})
    assert config["base"]["frequency"] == "1m"
    assert config["mod"]["sys_simulation"]["matching_type"] == "current_bar"
    assert config["mod"]["sys_transaction_cost"]["pit_tax"] is True
    extension = worker.load_minute_extension()
    assert Path(extension.__file__).resolve() == ROOT / "strategy/runner/rqalpha_minutes.py"
    assert worker.INPUT_BYTES == 128 * 1024
    assert not any(name == "rqalpha" for name in sys.modules)


def fake_runtime(monkeypatch, store):
    listeners = {}
    phase = SimpleNamespace(name="ON_BAR")
    daily_rows = np.asarray(
        [(minutes.encoded(day), 99, 199, 89, 149, 999999, 9999999, 200, 80) for day in DAYS],
        dtype=minutes.BAR_DTYPE,
    )
    adjustments = []

    class Base:
        def __init__(self, config):
            pass

        def get_bar(self, instrument, moment, frequency):
            day = moment.date() if isinstance(moment, dt.datetime) else moment
            matches = daily_rows[daily_rows["datetime"] == minutes.encoded(day)]
            return matches[0] if len(matches) else None

        def history_bars(
            self,
            instrument,
            count,
            frequency,
            fields,
            moment,
            skip_suspended=True,
            include_now=False,
            adjust_type="pre",
            adjust_orig=None,
        ):
            bars = daily_rows[daily_rows["datetime"] <= minutes.encoded(moment)]
            bars = bars if count is None else bars[-count:] if count else bars[:0]
            return bars if fields is None else bars[fields]

        def get_ex_cum_factor(self, instrument):
            return "native-factors"

        @staticmethod
        def _are_fields_valid(fields, valid):
            return (
                fields is None or fields in valid
                if isinstance(fields, str)
                else fields is None or set(fields) <= set(valid)
            )

    class BarMap:
        def __init__(self, proxy, frequency):
            self.proxy, self.frequency = proxy, frequency

        def update_dt(self, moment):
            self.moment = moment

    class DefaultMatcher:
        def __init__(self, env, config):
            self._env = env

    class PriceBoard:
        def __init__(self):
            self._env = env

        def get_last_price(self, symbol):
            return self._get_bar(symbol).close

    def adjust(bars, factors, fields, adjustment, origin):
        adjustments.append((factors, adjustment, origin, bars.copy()))
        return bars

    def install(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)

    for name in (
        "rqalpha",
        "rqalpha.core",
        "rqalpha.data",
        "rqalpha.model",
        "rqalpha.mod",
        "rqalpha.mod.rqalpha_mod_sys_simulation",
    ):
        install(name)
    kinds = SimpleNamespace(CS="CS")
    event_types = SimpleNamespace(
        BAR="BAR",
        BEFORE_TRADING="BEFORE_TRADING",
        OPEN_AUCTION="OPEN_AUCTION",
        AFTER_TRADING="AFTER_TRADING",
    )
    install(
        "rqalpha.const",
        INSTRUMENT_TYPE=kinds,
        EXECUTION_PHASE=SimpleNamespace(OPEN_AUCTION=SimpleNamespace(name="OPEN_AUCTION")),
    )
    install(
        "rqalpha.core.events",
        EVENT=event_types,
        Event=lambda event_type, **kw: SimpleNamespace(event_type=event_type, **kw),
    )
    install("rqalpha.core.execution_context", ExecutionContext=SimpleNamespace(phase=lambda: phase))
    install("rqalpha.data.bar_dict_price_board", BarDictPriceBoard=PriceBoard)
    install("rqalpha.data.base_data_source", BaseDataSource=Base)
    install("rqalpha.data.base_data_source.adjust", adjust_bars=adjust)
    install("rqalpha.interface", AbstractEventSource=object, AbstractMod=object)
    install("rqalpha.model.bar", BarMap=BarMap)
    install("rqalpha.model.order", ALGO_ORDER_STYLES=())
    install("rqalpha.model.tick", TickObject=lambda instrument, value: SimpleNamespace(**value))
    install("rqalpha.mod.rqalpha_mod_sys_simulation.matcher", DefaultBarMatcher=DefaultMatcher)
    env = SimpleNamespace(
        config=SimpleNamespace(
            base=SimpleNamespace(
                start_date=DAYS[0],
                end_date=DAYS[1],
                trading_calendar=[dt.datetime.combine(day, dt.time()) for day in DAYS],
            ),
            mod=SimpleNamespace(sys_simulation=SimpleNamespace()),
        ),
        calendar_dt=dt.datetime(2025, 1, 2, 9, 35),
    )
    env.set_data_source = lambda value: setattr(env, "data_source", value)
    env.set_event_source = lambda value: setattr(env, "event_source", value)
    env.set_price_board = lambda value: setattr(env, "price_board", value)
    env.broker = SimpleNamespace(
        register_matcher=lambda kind, value: setattr(env, "matcher", value)
    )
    env.add_frontend_validator = lambda value: setattr(env, "eligibility", value)
    env.event_bus = SimpleNamespace(
        prepend_listener=lambda kind, fn: listeners.setdefault(kind, []).insert(0, fn)
    )
    minutes.configure(store, MEMBERSHIP)
    mod = minutes.load_mod()
    mod.start_up(env, None)
    instrument = type("Instrument", (), {"order_book_id": NATIVE})()

    def get_bar(symbol, moment, frequency):
        row = env.data_source.get_bar(instrument, moment, frequency)
        return (
            SimpleNamespace(**{field: row[field] for field in row.dtype.names})
            if row is not None
            else SimpleNamespace(close=np.nan, volume=np.nan)
        )

    env.data_proxy = SimpleNamespace(
        get_bar=get_bar,
        get_prev_close=lambda symbol, moment: 9,
        get_previous_trading_date=lambda day: dt.datetime.combine(
            day - dt.timedelta(days=1), dt.time()
        ),
    )
    return env, instrument, listeners, adjustments


def test_selected_views_share_native_matcher_price_and_volume(frozen, monkeypatch):
    store = store_for(frozen, interval="5m")
    env, instrument, listeners, _ = fake_runtime(monkeypatch, store)
    minutes.activate(env)
    native = env.data_source.get_bar(instrument, env.calendar_dt, "1m")
    selected = env.data_source.get_bar(instrument, env.calendar_dt, "5m")
    assert native["volume"] == 104
    assert selected["volume"] == 510
    assert env.price_board.get_last_price(NATIVE) == selected["close"]
    assert env.matcher._current_bar_close_decider(NATIVE, None) == selected["close"]
    assert env.matcher._get_bar_volume(SimpleNamespace(style=None, order_book_id=NATIVE)) == 510
    event = SimpleNamespace(calendar_dt=env.calendar_dt, bar_dict="original-one-minute")
    listeners["BAR"][0](event)
    assert event.bar_dict.frequency == "5m"
    assert event.bar_dict.moment == env.calendar_dt
    with pytest.raises(minutes.MinuteError):
        env.matcher._get_bar_volume(
            SimpleNamespace(style=None, order_book_id=NATIVE), open_auction=True
        )


def test_source_daily_partial_snapshot_and_native_adjustment_never_read_future_daily_ohlcv(
    frozen, monkeypatch
):
    store = store_for(frozen, interval="60m")
    env, instrument, _, adjustments = fake_runtime(monkeypatch, store)
    minutes.activate(env)
    env.calendar_dt = dt.datetime(2025, 1, 3, 9, 31)
    current = env.data_source.get_bar(instrument, env.calendar_dt, "1d")
    assert current["open"] == 9.5
    assert current["close"] == 10.01
    assert current["volume"] == 9100
    assert current["high"] == 10.1
    snapshot = env.data_source.current_snapshot(instrument, "1m", env.calendar_dt)
    assert snapshot.last == 10.01
    assert snapshot.volume == 9100
    assert snapshot.prev_close == 9
    assert snapshot.datetime == 20250103093100
    history = env.data_source.history_bars(
        instrument,
        2,
        "1d",
        ["datetime", "close"],
        dt=env.calendar_dt,
        include_now=True,
        adjust_orig=env.calendar_dt,
    )
    assert list(history["close"]) == [149, 10.01]
    assert adjustments[-1][0:3] == ("native-factors", "pre", env.calendar_dt)
    minute_history = env.data_source.history_bars(
        instrument, 1, "1m", "close", env.calendar_dt, adjust_type="none"
    )
    assert list(minute_history) == [10.01]
    env.calendar_dt = dt.datetime(2025, 1, 3, 9, 29)
    assert env.data_source.get_bar(instrument, env.calendar_dt, "1d") is None
    with pytest.raises(minutes.MinuteError, match="已完成"):
        env.data_source.current_snapshot(instrument, "1m", env.calendar_dt)
    with pytest.raises(minutes.MinuteError, match="集合竞价"):
        env.data_source.get_open_auction_bar(instrument, env.calendar_dt)


def test_native_events_have_fixed_session_clocks_for_all_periods_and_no_synthetic_auction_data(
    frozen, monkeypatch
):
    store = store_for(frozen, interval="60m")
    env, _, _, _ = fake_runtime(monkeypatch, store)
    events = list(env.event_source.events(DAYS[0], DAYS[1], "1m"))
    first = events[:7]
    assert [(event.event_type, event.calendar_dt.strftime("%H:%M")) for event in first] == [
        ("BEFORE_TRADING", "08:30"),
        ("OPEN_AUCTION", "09:28"),
        ("BAR", "10:30"),
        ("BAR", "11:30"),
        ("BAR", "14:00"),
        ("BAR", "15:00"),
        ("AFTER_TRADING", "15:30"),
    ]
    assert len(events) == 14
    assert env.data_source.available_data_range("1m") == DAYS
    env.config.base.start_date = dt.date(2025, 1, 3)
    with pytest.raises(minutes.MinuteError, match="静默缩短"):
        minutes.activate(env)


def test_no_trade_metadata_cannot_hide_positive_raw_volume(frozen):
    root, index, _, settings, window = frozen
    info = index["instruments"][SYMBOL]
    info["complete_sessions"] = [DAYS[0].isoformat()]
    info["end"] = DAYS[0].isoformat()
    info["no_trade_sessions"] = {DAYS[1].isoformat(): "confirmed_suspension"}
    digest = freeze(root, index)
    store = minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)
    with pytest.raises(minutes.MinuteError, match="含有成交量"):
        store.month(SYMBOL, "2025-01")


@pytest.mark.parametrize("raw", [b'{"digest":"x","digest":"y"}', b"x" * (minutes.INDEX_BYTES + 1)])
def test_index_duplicate_keys_and_oversize_are_rejected(frozen, raw):
    root, _, digest, settings, window = frozen
    (root / "index.json").write_bytes(raw)
    with pytest.raises(minutes.MinuteError):
        minutes.MinuteStore(digest, DAILY_DIGEST, settings, window, root=root)


@pytest.mark.parametrize("digest", [None, "bad", 1])
def test_daily_binding_is_mandatory_for_minute_requests(frozen, digest):
    root, _, minute_digest, settings, window = frozen
    with pytest.raises(minutes.MinuteError, match="摘要"):
        minutes.MinuteStore(minute_digest, digest, settings, window, root=root)
