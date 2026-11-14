import copy
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import stat
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

SPEC = spec_from_file_location(
    "prepare_rqalpha_minutes",
    Path(__file__).resolve().parents[2] / "tools/prepare_rqalpha_minutes.py",
)
prep = module_from_spec(SPEC)
SPEC.loader.exec_module(prep)
SYMBOLS = ["600584.SS", "603986.SS"]
DAYS = ["2025-01-02", "2025-01-03"]
DAILY_DIGEST = "d" * 64


def csv_bytes(fields, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(fields)
    writer.writerows(rows)
    return output.getvalue().encode()


def bars(symbol, day, *, extras=(570,)):
    value = 41.10000228881836
    date = dt.date.fromisoformat(day)
    return [
        {
            "symbol": symbol[:6],
            "exchange": "SH" if symbol.endswith(".SS") else "SZ",
            "timestamp": dt.datetime.combine(date, dt.time(label // 60, label % 60)),
            "open": value,
            "high": value + 0.1,
            "low": value - 0.1,
            "close": value,
            "volume": 123400,
            "turnover": 5_071_740.2824401855,
        }
        for label in sorted(prep.CONTINUOUS_LABELS | set(extras))
    ]


def membership_file(root, symbols=SYMBOLS):
    value = {
        "schema": "atlas.rqalpha.sectors/v1",
        "industries": {
            sector: [
                {
                    "symbols": symbols,
                    "as_of": DAYS[0],
                    "published": "2024-12-01",
                    "effective": "2024-12-01",
                    "source": "https://example.test/members",
                }
            ]
            for sector in sorted(prep.INDUSTRIES)
        },
    }
    value["digest"] = hashlib.sha256(prep.canonical_bytes(value)).hexdigest()
    file = root / "membership.json"
    file.write_bytes(prep.canonical_bytes(value))
    return file, value


def save_membership(file, value):
    value.pop("digest", None)
    value["digest"] = hashlib.sha256(prep.canonical_bytes(value)).hexdigest()
    file.write_bytes(prep.canonical_bytes(value))


def strait_record(symbols=("000592.SZ", "300300.SZ", "603122.SS")):
    return {
        "symbols": list(symbols),
        "as_of": "2025-01-02",
        "published": "2024-10-29",
        "effective": "2024-10-30",
        "source": "https://example.test/historical-concept-report",
        "scope": "historical-theme-research-sample",
        "partial": True,
        "selected_on": "2026-11-15",
        "membership_note": "本次整理的部分研究观察池，不是官方完整成分或无偏训练样本。",
        "member_evidence": {
            symbol: {
                "name": f"合成研究样本 {index}",
                "basis": "annual-report-business-proxy"
                if symbol == "603122.SS" else "historical-concept-news",
                "source": "https://example.test/annual-report"
                if symbol == "603122.SS" else "https://example.test/historical-concept-report",
                "published": "2023-03-22" if symbol == "603122.SS" else "2024-10-29",
            }
            for index, symbol in enumerate(symbols)
        },
    }


def test_original_four_pools_remain_valid_and_optional_strait_extends_members(tmp_path):
    file, value = membership_file(tmp_path)
    original = copy.deepcopy(value["industries"])
    assert set(value["industries"]) == prep.INDUSTRIES
    assert prep.load_membership(file)[1] == SYMBOLS
    value["industries"]["strait"] = [strait_record()]
    save_membership(file, value)
    loaded, symbols = prep.load_membership(file)
    assert loaded["industries"]["strait"][0]["member_evidence"]["603122.SS"]["basis"] == (
        "annual-report-business-proxy"
    )
    assert symbols == sorted([*SYMBOLS, "000592.SZ", "300300.SZ", "603122.SS"])
    assert {key: loaded["industries"][key] for key in prep.INDUSTRIES} == original
    assert prep.load_membership(file, ["300300.SZ"])[1] == ["300300.SZ"]


def test_strait_evidence_accepts_exact_text_size_limits(tmp_path):
    file, value = membership_file(tmp_path)
    record = strait_record()
    record["membership_note"] = "x" * 1000
    record["member_evidence"]["603122.SS"]["name"] = "x" * 80
    value["industries"]["strait"] = [record]
    save_membership(file, value)
    assert "603122.SS" in prep.load_membership(file)[1]


@pytest.mark.parametrize("removed", sorted(prep.INDUSTRIES))
def test_optional_strait_does_not_replace_a_required_original_pool(tmp_path, removed):
    file, value = membership_file(tmp_path)
    value["industries"]["strait"] = [strait_record()]
    del value["industries"][removed]
    save_membership(file, value)
    with pytest.raises(ValueError, match="清单"):
        prep.load_membership(file)


@pytest.mark.parametrize("include_strait", [False, True])
def test_preparation_rejects_unknown_sector_in_four_or_five_pool_manifest(tmp_path, include_strait):
    file, value = membership_file(tmp_path)
    if include_strait:
        value["industries"]["strait"] = [strait_record()]
    value["industries"]["unapproved-theme"] = copy.deepcopy(value["industries"]["space"])
    save_membership(file, value)
    with pytest.raises(ValueError, match="清单"):
        prep.load_membership(file)


@pytest.mark.parametrize("mutation", [
    "scope", "partial", "selected_before_as_of", "selected_invalid", "published_on_as_of",
    "effective_after_as_of", "as_of_invalid", "note_empty", "note_oversized", "evidence_missing",
    "evidence_extra", "evidence_not_object", "item_not_object", "name_empty", "name_oversized",
    "basis", "evidence_after_record", "evidence_date_invalid", "source_http", "source_credentials",
    "source_missing_host", "source_whitespace", "source_control", "source_oversized",
    "source_not_string",
    "record_source_http", "record_source_credentials",
])
def test_strait_evidence_must_be_complete_visible_and_safe(tmp_path, mutation):
    file, value = membership_file(tmp_path)
    record = strait_record()
    item = record["member_evidence"]["603122.SS"]
    if mutation == "scope":
        record["scope"] = "official-complete-industry"
    elif mutation == "partial":
        record["partial"] = 1
    elif mutation == "selected_before_as_of":
        record["selected_on"] = "2024-12-31"
    elif mutation == "selected_invalid":
        record["selected_on"] = "not-a-date"
    elif mutation == "published_on_as_of":
        record["published"] = record["as_of"]
    elif mutation == "effective_after_as_of":
        record["effective"] = "2025-01-03"
    elif mutation == "as_of_invalid":
        record["as_of"] = None
    elif mutation == "note_empty":
        record["membership_note"] = "  "
    elif mutation == "note_oversized":
        record["membership_note"] = "x" * 1001
    elif mutation == "evidence_missing":
        del record["member_evidence"]["000592.SZ"]
    elif mutation == "evidence_extra":
        record["member_evidence"]["600519.SS"] = item.copy()
    elif mutation == "evidence_not_object":
        record["member_evidence"] = []
    elif mutation == "item_not_object":
        record["member_evidence"]["603122.SS"] = "not evidence"
    elif mutation == "name_empty":
        item["name"] = "\t"
    elif mutation == "name_oversized":
        item["name"] = "x" * 81
    elif mutation == "basis":
        item["basis"] = "future-leader"
    elif mutation == "evidence_after_record":
        item["published"] = "2024-10-30"
    elif mutation == "evidence_date_invalid":
        item["published"] = "2024/10/29"
    elif mutation == "record_source_http":
        record["source"] = "http://example.test/report"
    elif mutation == "record_source_credentials":
        record["source"] = "https://user:secret@example.test/report"
    else:
        item["source"] = {
            "source_http": "http://example.test/report",
            "source_credentials": "https://user:secret@example.test/report",
            "source_missing_host": "https:///report",
            "source_whitespace": "https://example.test/\nreport",
            "source_control": "https://example.test/" + chr(127) + "report",
            "source_oversized": "https://example.test/" + "x" * 2048,
            "source_not_string": None,
        }[mutation]
    value["industries"]["strait"] = [record]
    save_membership(file, value)
    with pytest.raises((TypeError, ValueError)):
        prep.load_membership(file)


def test_strait_preparation_keeps_original_csv_contract_and_raw_bytes(source_fixture):
    fixture = source_fixture
    fixture.members["industries"]["strait"] = [strait_record(SYMBOLS)]
    save_membership(fixture.membership, fixture.members)
    before = {
        file.relative_to(fixture.raw).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in fixture.raw.rglob("*") if file.is_file()
    }
    result = prepare(fixture, symbols=SYMBOLS)
    assert result["membership_sha256"] == fixture.members["digest"]
    assert set(result["instruments"]) == set(SYMBOLS)
    assert result["source"]["revision"] == prep.REVISION
    for chunk in result["files"]:
        with gzip.open(fixture.published / chunk["path"], "rt", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            assert tuple(reader.fieldnames) == prep.CSV_FIELDS
        assert len(rows) == 482
        assert rows[1]["datetime"] == "20250102093100"
        assert float(rows[1]["close"]) == 41.10000228881836
    assert before == {
        file.relative_to(fixture.raw).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in fixture.raw.rglob("*") if file.is_file()
    }


def fixture_metadata():
    provenance = {
        "dataset_schema_version": 1,
        "frequency": "1m",
        "timezone": "Asia/Singapore",
        "timestamp_storage": "timezone-naive",
        "price_adjustment": "none",
        "volume_unit": "shares",
        "turnover_unit": "CNY",
        "generated_at": "2026-08-21",
    }
    fields = [
        "symbol",
        "exchange",
        "file",
        "records",
        "first_timestamp",
        "last_timestamp",
        "listing_date",
        "delisting_date",
    ]
    inventory = [
        [
            symbol[:6],
            "SH",
            prep.source_path(symbol),
            482,
            f"{DAYS[0]} 09:30:00",
            f"{DAYS[-1]} 15:00:00",
            "2010-01-01",
            "",
        ]
        for symbol in SYMBOLS
    ]
    return {
        "README.md": b"---\nlicense: apache-2.0\n---\n",
        "LICENSE": b"Apache License\nVersion 2.0\n",
        "metadata/source_provenance.json": prep.canonical_bytes(provenance),
        "metadata/coverage_by_instrument.csv": csv_bytes(fields, inventory),
        "metadata/market_calendar.csv": csv_bytes(
            ["date", "is_trading_day"],
            [
                ["2025-01-01", "False"],
                [DAYS[0], "True"],
                [DAYS[1], "True"],
                ["2025-01-04", "False"],
                ["2025-02-05", "True"],
            ],
        ),
        "metadata/no_bar_day_classification.csv": csv_bytes(
            ["symbol", "exchange", "date", "classification", "evidence"],
            [],
        ),
        "metadata/missing_intervals.csv": b"symbol,exchange,start,end\n",
        "metadata/summary.json": b"{}",
    }


def receipt_for(raw, file):
    rows = []
    for path in sorted(p for p in raw.rglob("*") if p.is_file()):
        name = path.relative_to(raw).as_posix()
        rows.append(
            {
                "path": name,
                "url": prep.source_url(name),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    value = {"repo_id": prep.REPO_ID, "revision": prep.REVISION, "files": rows}
    file.write_bytes(prep.canonical_bytes(value))
    return value


@pytest.fixture
def source_fixture(tmp_path, monkeypatch):
    raw, published = tmp_path / "raw", tmp_path / "published"
    raw.mkdir()
    published.mkdir()
    metadata = fixture_metadata()
    for name, body in metadata.items():
        file = raw / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(body)
    for symbol in SYMBOLS:
        file = raw / prep.source_path(symbol)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"parquet is not imported in pure preparation tests")
    receipt = tmp_path / "receipt.json"
    receipt_for(raw, receipt)
    membership, members = membership_file(tmp_path)
    values = {symbol: [row for day in DAYS for row in bars(symbol, day)] for symbol in SYMBOLS}

    def read_rows(path, symbol, start, end, inventory):
        yield from (
            row for row in values[symbol] if start <= row["timestamp"].date().isoformat() <= end
        )

    monkeypatch.setattr(prep, "read_parquet_rows", read_rows)
    return SimpleNamespace(
        raw=raw,
        published=published,
        receipt=receipt,
        membership=membership,
        members=members,
        values=values,
        root=tmp_path,
        reader=read_rows,
    )


def prepare(fixture, **kwargs):
    return prep.prepare(
        fixture.raw,
        fixture.receipt,
        fixture.published,
        fixture.membership,
        DAILY_DIGEST,
        start=DAYS[0],
        end=DAYS[-1],
        **kwargs,
    )


def update_metadata(fixture, name, body):
    (fixture.raw / name).write_bytes(body)
    receipt_for(fixture.raw, fixture.receipt)


def test_prepares_bound_read_only_months_and_keeps_float_precision(source_fixture):
    fixture = source_fixture
    result = prepare(fixture)
    index = fixture.published / "index.json"
    assert json.loads(index.read_bytes()) == result
    identity = {k: v for k, v in result.items() if k != "digest"}
    assert result["digest"] == hashlib.sha256(prep.canonical_bytes(identity)).hexdigest()
    assert result["daily_digest"] == DAILY_DIGEST
    assert result["membership_sha256"] == fixture.members["digest"]
    assert result["source"]["repo_id"] == prep.REPO_ID
    assert result["source"]["revision"] == prep.REVISION
    assert result["source"]["excluded_partial_day"] == "2026-08-07"
    assert result["start"] == DAYS[0] and result["end"] == DAYS[-1]
    assert result["requested_window"] == {"start": DAYS[0], "end": DAYS[-1]}
    assert result["sessions"] == DAYS
    assert (
        result["extra_session_policy"]
        == "retained-for-cumulative-snapshot;excluded-from-continuous-bars-and-orders"
    )
    item = result["instruments"][SYMBOLS[0]]
    assert item["complete_sessions"] == DAYS
    assert item["gaps"] == {} and item["no_trade_sessions"] == {}
    assert item["source_bytes"] == (fixture.raw / prep.source_path(SYMBOLS[0])).stat().st_size
    assert item["start"] == DAYS[0] and item["end"] == DAYS[-1]
    chunk = result["files"][0]
    content = gzip.decompress((fixture.published / chunk["path"]).read_bytes()).decode()
    rows = list(csv.DictReader(io.StringIO(content)))
    assert len(rows) == 482
    assert rows[0]["datetime"] == "20250102093000"
    assert rows[1]["datetime"] == "20250102093100"
    assert rows[-1]["datetime"] == "20250103150000"
    assert float(rows[0]["open"]) == 41.10000228881836
    assert rows[0]["volume"] == "123400"
    assert (
        hashlib.sha256((fixture.published / chunk["path"]).read_bytes()).hexdigest()
        == chunk["sha256"]
    )
    assert set(
        p.relative_to(fixture.published).as_posix()
        for p in fixture.published.rglob("*")
        if p.is_file()
    ) == {
        "index.json",
        *(row["path"] for row in result["files"]),
    }
    for path in [fixture.published, index, *(p for p in fixture.published.rglob("*"))]:
        assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


@pytest.mark.parametrize(
    "start,end",
    [("2025-01-01", "2025-01-03"), ("2025-01-02", "2025-01-04"),
     ("2025-01-01", "2025-01-04")],
)
def test_holiday_and_weekend_bounds_publish_trade_day_range_accepted_by_consumers(
    source_fixture, monkeypatch, start, end,
):
    from app import rqalpha_minute_data

    fixture = source_fixture
    observed = []

    def rows(path, symbol, lower, upper, inventory):
        observed.append((lower, upper))
        yield from fixture.reader(path, symbol, lower, upper, inventory)

    monkeypatch.setattr(prep, "read_parquet_rows", rows)
    result = prep.prepare(
        fixture.raw, fixture.receipt, fixture.published, fixture.membership,
        DAILY_DIGEST, start=start, end=end,
    )
    assert result["requested_window"] == {"start": start, "end": end}
    assert result["start"] == result["sessions"][0] == DAYS[0]
    assert result["end"] == result["sessions"][-1] == DAYS[-1]
    assert observed == [(start, end)] * len(SYMBOLS)
    rqalpha_minute_data._validate(result, fixture.published)

    spec = spec_from_file_location(
        "prepared_minutes_calendar_test",
        Path(__file__).resolve().parents[2] / "strategy/runner/rqalpha_minutes.py",
    )
    minutes = module_from_spec(spec)
    spec.loader.exec_module(minutes)
    store = minutes.MinuteStore(
        result["digest"], DAILY_DIGEST,
        {"symbols": SYMBOLS, "interval": "1m", "industry": "semiconductor"},
        {"start": DAYS[0], "end": DAYS[-1]}, root=fixture.published,
    )
    assert store.request_sessions == tuple(dt.date.fromisoformat(day) for day in DAYS)


def test_preparation_is_deterministic_and_does_not_modify_raw_history(source_fixture):
    fixture = source_fixture
    before = {p: p.read_bytes() for p in fixture.raw.rglob("*") if p.is_file()}
    first = prepare(fixture)
    another = fixture.root / "another"
    another.mkdir()
    second = prep.prepare(
        fixture.raw,
        fixture.receipt,
        another,
        fixture.membership,
        DAILY_DIGEST,
        start=DAYS[0],
        end=DAYS[-1],
    )
    assert first == second
    assert (fixture.published / "index.json").read_bytes() == (another / "index.json").read_bytes()
    assert all(
        (fixture.published / row["path"]).read_bytes() == (another / row["path"]).read_bytes()
        for row in first["files"]
    )
    assert all(p.read_bytes() == body for p, body in before.items())


def test_missing_minute_is_gap_not_filled_or_marked_complete(source_fixture):
    fixture = source_fixture
    del fixture.values[SYMBOLS[0]][1]
    result = prepare(fixture)
    item = result["instruments"][SYMBOLS[0]]
    assert item["complete_sessions"] == DAYS[1:]
    assert item["start"] == DAYS[1] and item["end"] == DAYS[1]
    assert item["gaps"] == {DAYS[0]: "missing-continuous-minutes:1"}
    chunk = next(row for row in result["files"] if row["symbol"] == SYMBOLS[0])
    assert chunk["rows"] == 481


def test_start_end_are_null_if_only_partial_sessions(source_fixture):
    fixture = source_fixture
    fixture.values[SYMBOLS[0]] = fixture.values[SYMBOLS[0]][:5]
    item = prepare(fixture)["instruments"][SYMBOLS[0]]
    assert item["start"] is None and item["end"] is None
    assert item["complete_sessions"] == []
    assert set(item["gaps"]) == set(DAYS)


@pytest.mark.parametrize(
    "classification,recognized",
    [
        ("confirmed_suspension", True),
        ("zero_daily_no_trade", True),
        ("unresolved_no_bar", False),
        ("verified_missing_minutes", False),
    ],
)
def test_no_bar_classification_does_not_invent_bars(source_fixture, classification, recognized):
    fixture = source_fixture
    fixture.values[SYMBOLS[0]] = [
        row for row in fixture.values[SYMBOLS[0]] if row["timestamp"].date().isoformat() != DAYS[0]
    ]
    update_metadata(
        fixture,
        "metadata/no_bar_day_classification.csv",
        csv_bytes(
            ["symbol", "exchange", "date", "classification", "evidence"],
            [[SYMBOLS[0][:6], "SH", DAYS[0], classification, "source-evidence"]],
        ),
    )
    item = prepare(fixture)["instruments"][SYMBOLS[0]]
    assert item["no_trade_sessions"] == ({DAYS[0]: classification} if recognized else {})
    assert item["gaps"] == ({} if recognized else {DAYS[0]: f"no-bars:{classification}"})
    assert item["complete_sessions"] == DAYS[1:]


def test_conflicting_no_bar_status_rejects_publication(source_fixture):
    fixture = source_fixture
    update_metadata(
        fixture,
        "metadata/no_bar_day_classification.csv",
        csv_bytes(
            ["symbol", "exchange", "date", "classification", "evidence"],
            [[SYMBOLS[0][:6], "SH", DAYS[0], "confirmed_suspension", "event"]],
        ),
    )
    with pytest.raises(ValueError, match="冲突"):
        prepare(fixture)
    assert not (fixture.published / "index.json").exists()


def test_listing_range_excludes_pre_listing_days_without_fabrication(source_fixture):
    fixture = source_fixture
    data = list(
        csv.DictReader(
            io.StringIO((fixture.raw / "metadata/coverage_by_instrument.csv").read_text())
        )
    )
    data[0]["listing_date"] = DAYS[1]
    update_metadata(
        fixture,
        "metadata/coverage_by_instrument.csv",
        csv_bytes(data[0].keys(), [r.values() for r in data]),
    )
    item = prepare(fixture)["instruments"][SYMBOLS[0]]
    assert item["complete_sessions"] == DAYS[1:]
    assert item["gaps"] == {} and item["no_trade_sessions"] == {}


def test_multiple_months_are_separate_bounded_chunks(source_fixture):
    fixture = source_fixture
    for symbol in SYMBOLS:
        fixture.values[symbol].extend(bars(symbol, "2025-02-05"))
    result = prep.prepare(
        fixture.raw,
        fixture.receipt,
        fixture.published,
        fixture.membership,
        DAILY_DIGEST,
        start=DAYS[0],
        end="2025-02-05",
    )
    assert len(result["files"]) == 4
    assert set(result["instruments"][SYMBOLS[0]]["months"]) == {"2025-01", "2025-02"}
    assert all(row["rows"] <= prep.MAX_MONTH_ROWS for row in result["files"])


@pytest.mark.parametrize("extras", [(), (570,), (780,), (570, 780)])
def test_day_grid_retains_optional_session_extras_but_never_requires_them(extras):
    source = bars(SYMBOLS[0], DAYS[0], extras=extras)
    normalized = [prep.validate_row(row, SYMBOLS[0]) for row in source]
    assert prep.audit_day(normalized) == (True, None)
    assert len(normalized) == 240 + len(extras)


def test_audit_day_requires_every_continuous_minute_even_with_extra_rows():
    rows = [
        prep.validate_row(row, SYMBOLS[0]) for row in bars(SYMBOLS[0], DAYS[0], extras=(570, 780))
    ]
    assert prep.audit_day(rows[:2])[0] is False
    with pytest.raises(ValueError, match="重复"):
        prep.audit_day([*rows, rows[0]])


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "600519"),
        ("exchange", "SZ"),
        ("open", float("nan")),
        ("close", float("inf")),
        ("low", 100),
        ("high", 0.01),
        ("open", True),
        ("close", 0),
        ("volume", 1.5),
        ("volume", -1),
        ("volume", True),
        ("turnover", -1),
        ("turnover", float("nan")),
        ("turnover", True),
        ("timestamp", dt.datetime(2025, 1, 2, 12)),
        ("timestamp", dt.datetime(2025, 1, 2, 9, 31, 1)),
        ("timestamp", dt.datetime(2025, 1, 2, 9, 31, microsecond=1)),
        ("timestamp", dt.datetime(2025, 1, 2, 9, 31, tzinfo=dt.UTC)),
    ],
)
def test_row_validator_rejects_bad_identity_values_or_timestamps(field, value):
    row = bars(SYMBOLS[0], DAYS[0])[1]
    row[field] = value
    with pytest.raises(ValueError):
        prep.validate_row(row, SYMBOLS[0])


@pytest.mark.parametrize("mutation", ["duplicate", "reverse", "unknown_field", "weekend"])
def test_corrupt_rows_never_publish_index(source_fixture, mutation):
    fixture = source_fixture
    values = fixture.values[SYMBOLS[0]]
    if mutation == "duplicate":
        values.insert(1, copy.deepcopy(values[0]))
    elif mutation == "reverse":
        values[0], values[1] = values[1], values[0]
    elif mutation == "unknown_field":
        values[0]["payload"] = "must not execute"
    else:
        values.append({**values[-1], "timestamp": dt.datetime(2025, 1, 4, 9, 31)})
        monkey_end = "2025-01-04"
        with pytest.raises(ValueError, match="交易日历"):
            prep.prepare(
                fixture.raw,
                fixture.receipt,
                fixture.published,
                fixture.membership,
                DAILY_DIGEST,
                start=DAYS[0],
                end=monkey_end,
            )
        assert not (fixture.published / "index.json").exists()
        return
    with pytest.raises(ValueError):
        prepare(fixture)
    assert not (fixture.published / "index.json").exists()


@pytest.mark.parametrize(
    "mutation", ["revision", "repo", "digest", "size", "duplicate", "url", "missing_metadata"]
)
def test_receipt_pin_and_original_hashes_are_required(source_fixture, mutation):
    fixture = source_fixture
    receipt = json.loads(fixture.receipt.read_bytes())
    if mutation == "revision":
        receipt["revision"] = "main"
    elif mutation == "repo":
        receipt["repo_id"] = "someone/other"
    elif mutation == "digest":
        receipt["files"][0]["sha256"] = "0" * 64
    elif mutation == "size":
        receipt["files"][0]["bytes"] += 1
    elif mutation == "duplicate":
        receipt["files"].append(receipt["files"][0])
    elif mutation == "url":
        receipt["files"][0]["url"] += "?token=never"
    else:
        receipt["files"] = [row for row in receipt["files"] if row["path"] != "LICENSE"]
    fixture.receipt.write_bytes(prep.canonical_bytes(receipt))
    with pytest.raises(ValueError):
        prepare(fixture)
    assert not list(fixture.published.iterdir())


def test_receipt_cannot_be_invented_by_preparation(source_fixture):
    fixture = source_fixture
    fixture.receipt.unlink()
    with pytest.raises(OSError):
        prepare(fixture)
    assert not list(fixture.published.iterdir())


@pytest.mark.parametrize(
    "path", ["../escape", "/tmp/escape", "data\\evil", "a//b", "a/./b", "a,b", "a:b", ""]
)
def test_rejects_unsafe_relative_paths(path):
    with pytest.raises(ValueError):
        prep.relative_path(path)


@pytest.mark.parametrize(
    "path", ["viewer/bars_sample.parquet", "data/stock_1m/BJ/833874.parquet", "script.py"]
)
def test_source_download_never_uses_viewer_or_unapproved_files(path):
    with pytest.raises(ValueError):
        prep.source_url(path)


def test_unexpected_raw_code_file_rejects_without_execution(source_fixture):
    fixture = source_fixture
    (fixture.raw / "json.py").write_text("raise RuntimeError('never execute')")
    with pytest.raises(ValueError, match="文件集合"):
        prepare(fixture)
    assert not (fixture.published / "index.json").exists()


def test_symlink_raw_file_and_symlink_directory_are_rejected(source_fixture):
    fixture = source_fixture
    file = fixture.raw / "README.md"
    external = fixture.root / "outside-readme"
    file.rename(external)
    file.symlink_to(external)
    with pytest.raises(ValueError, match="符号链接"):
        prepare(fixture)
    linked = fixture.root / "raw-link"
    linked.symlink_to(fixture.raw, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        prep.existing_directory(linked)


def test_nonempty_destination_is_preserved(source_fixture):
    fixture = source_fixture
    keep = fixture.published / "keep"
    keep.write_text("existing work")
    with pytest.raises(ValueError, match="空目录"):
        prepare(fixture)
    assert keep.read_text() == "existing work"


def test_destinations_must_not_overlap_raw(source_fixture):
    fixture = source_fixture
    nested = fixture.raw / "published"
    nested.mkdir()
    with pytest.raises(ValueError, match="互相独立"):
        prep.prepare(fixture.raw, fixture.receipt, nested, fixture.membership, DAILY_DIGEST)


@pytest.mark.parametrize(
    "patch",
    ["corrupt_digest", "other_industry", "outside_symbol", "duplicate_symbol", "many_symbols"],
)
def test_membership_limits_are_enforced_before_reading_parquet(source_fixture, patch):
    fixture = source_fixture
    if patch in ("corrupt_digest", "other_industry"):
        manifest = json.loads(fixture.membership.read_bytes())
        if patch == "corrupt_digest":
            manifest["digest"] = "0" * 64
        else:
            manifest["industries"]["other"] = manifest["industries"].pop("space")
            manifest.pop("digest")
            manifest["digest"] = hashlib.sha256(prep.canonical_bytes(manifest)).hexdigest()
        fixture.membership.write_bytes(prep.canonical_bytes(manifest))
        selected = None
    else:
        selected = (
            ["600519.SS"]
            if patch == "outside_symbol"
            else [SYMBOLS[0]] * (151 if patch == "many_symbols" else 2)
        )
    with pytest.raises(ValueError):
        prepare(fixture, symbols=selected)
    assert not list(fixture.published.iterdir())


@pytest.mark.parametrize(
    "field,value",
    [
        ("timezone", "UTC"),
        ("timestamp_storage", "timezone-aware"),
        ("volume_unit", "lots"),
        ("turnover_unit", "USD"),
        ("price_adjustment", "pre"),
        ("frequency", "15m"),
        ("dataset_schema_version", True),
    ],
)
def test_wrong_source_schema_or_units_reject_publication(source_fixture, field, value):
    fixture = source_fixture
    provenance = json.loads((fixture.raw / "metadata/source_provenance.json").read_bytes())
    provenance[field] = value
    update_metadata(fixture, "metadata/source_provenance.json", prep.canonical_bytes(provenance))
    with pytest.raises(ValueError, match="契约"):
        prepare(fixture)
    assert not list(fixture.published.iterdir())


def test_no_false_full_coverage_after_partial_snapshot_cutoff(source_fixture):
    fixture = source_fixture
    with pytest.raises(ValueError, match="完整日期"):
        prep.prepare(
            fixture.raw,
            fixture.receipt,
            fixture.published,
            fixture.membership,
            DAILY_DIGEST,
            end="2026-08-07",
        )
    assert not list(fixture.published.iterdir())


@pytest.mark.parametrize(
    "option,limit",
    [
        ("MAX_MONTH_ROWS", 5),
        ("MAX_MONTH_BYTES", 50),
        ("MAX_MANIFEST_BYTES", 128),
        ("MAX_DOWNLOAD_BYTES", 10),
        ("MAX_METADATA_BYTES", 5),
    ],
)
def test_preparation_budgets_fail_without_index(source_fixture, monkeypatch, option, limit):
    fixture = source_fixture
    monkeypatch.setattr(prep, option, limit)
    with pytest.raises(ValueError):
        prepare(fixture)
    assert not (fixture.published / "index.json").exists()


def test_invalid_json_constants_duplicate_fields_and_size_fail_closed(tmp_path):
    file = tmp_path / "bad.json"
    for body in (b'{"a":NaN}', b'{"a":1,"a":2}'):
        file.write_bytes(body)
        with pytest.raises(ValueError):
            prep.read_json(file, 100)
    file.write_bytes(b"x" * 101)
    with pytest.raises(ValueError, match="体积"):
        prep.read_json(file, 100)


def test_download_pins_canonical_files_and_writes_external_read_only_receipt(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    membership, _ = membership_file(tmp_path)
    payloads = fixture_metadata()
    payloads.update({prep.source_path(symbol): b"canonical-parquet-bytes" for symbol in SYMBOLS})
    requests = []

    class Response(io.BytesIO):
        def __init__(self, body, url):
            super().__init__(body)
            self.url = url

        def geturl(self):
            return self.url

    def open_url(request, timeout):
        assert timeout == 90
        requests.append(request.full_url)
        name = request.full_url.split(f"/{prep.REVISION}/", 1)[1]
        return Response(payloads[name], request.full_url)

    monkeypatch.setattr(prep.urllib.request, "urlopen", open_url)
    receipt = tmp_path / "receipt.json"
    result = prep.download(raw, receipt, membership)
    assert len(requests) == len(prep.METADATA_FILES) + 2
    assert all(f"/resolve/{prep.REVISION}/" in url and "viewer" not in url for url in requests)
    assert result["schema"] == "atlas.rqalpha.minute-download/v1"
    assert json.loads(receipt.read_bytes()) == result
    assert prep.verify_receipt(raw, receipt, SYMBOLS)
    assert not receipt.stat().st_mode & stat.S_IWUSR
    assert not raw.stat().st_mode & stat.S_IWUSR


@pytest.mark.parametrize("option,limit", [("MAX_FILE_BYTES", 10), ("MAX_DOWNLOAD_BYTES", 10)])
def test_download_budget_failure_never_forges_receipt(tmp_path, monkeypatch, option, limit):
    raw = tmp_path / "raw"
    raw.mkdir()
    membership, _ = membership_file(tmp_path)
    monkeypatch.setattr(prep, option, limit)

    class Response(io.BytesIO):
        def geturl(self):
            return "https://huggingface.co/fixed"

    monkeypatch.setattr(prep.urllib.request, "urlopen", lambda *a, **k: Response(b"x" * 20))
    receipt = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="体积"):
        prep.download(raw, receipt, membership)
    assert not receipt.exists()


def test_download_network_failure_and_existing_receipt_preserve_existing_files(
    tmp_path, monkeypatch
):
    raw = tmp_path / "raw"
    raw.mkdir()
    membership, _ = membership_file(tmp_path)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("keep receipt")
    with pytest.raises(ValueError, match="新文件"):
        prep.download(raw, receipt, membership)
    assert receipt.read_text() == "keep receipt"
    receipt.unlink()
    monkeypatch.setattr(
        prep.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(URLError("offline"))
    )
    with pytest.raises(URLError):
        prep.download(raw, receipt, membership)
    assert not receipt.exists()


def test_real_parquet_reader_schema_range_order_and_roundtrip(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    values = [row for day in DAYS for row in bars(SYMBOLS[0], day)]
    schema = pa.schema(
        [
            (name, kind)
            for name, kind in zip(
                prep.RAW_FIELDS,
                (
                    pa.string(),
                    pa.string(),
                    pa.timestamp("us"),
                    pa.float64(),
                    pa.float64(),
                    pa.float64(),
                    pa.float64(),
                    pa.int64(),
                    pa.float64(),
                ),
                strict=True,
            )
        ],
        metadata={b"dataset_schema_version": b"1"},
    )
    file = tmp_path / "stock.parquet"
    table = pa.Table.from_pylist(values, schema=schema)
    pq.write_table(table, file, row_group_size=256)
    inventory = {
        "records": str(len(values)),
        "first_timestamp": f"{DAYS[0]} 09:30:00",
        "last_timestamp": f"{DAYS[-1]} 15:00:00",
    }
    actual = list(prep.read_parquet_rows(file, SYMBOLS[0], *DAYS, inventory))
    assert actual == values
    assert len(list(prep.read_parquet_rows(file, SYMBOLS[0], DAYS[1], DAYS[1], inventory))) == 241
    wrong = dict(inventory, records="1")
    with pytest.raises(ValueError, match="记录数"):
        list(prep.read_parquet_rows(file, SYMBOLS[0], *DAYS, wrong))
    invalid = table.set_column(
        2,
        "timestamp",
        pa.array(
            [row["timestamp"].replace(tzinfo=dt.UTC) for row in values],
            type=pa.timestamp("us", "UTC"),
        ),
    )
    pq.write_table(invalid, file)
    with pytest.raises(ValueError, match="字段"):
        list(prep.read_parquet_rows(file, SYMBOLS[0], *DAYS, inventory))
