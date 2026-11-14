import copy
import hashlib
import json

import pytest

from app import rqalpha_industries as industries
from app.compute_objects import canonical_bytes
from app.lab_strategies import LabMultiSettings
from app.sandbox import RunnerFailure


@pytest.fixture
def membership(tmp_path, monkeypatch):
    base = {
        "as_of": "2025-01-02",
        "published": "2024-12-20",
        "effective": "2025-01-01",
        "source": "https://example.test/public-membership",
        "symbols": ["600001.SS"],
    }
    value = {
        "schema": "atlas.rqalpha.sectors/v1",
        "industries": {key: [copy.deepcopy(base)] for key in industries.BASE_INDUSTRIES},
    }
    location = tmp_path / "members.json"

    def save(data):
        data.pop("digest", None)
        data["digest"] = hashlib.sha256(canonical_bytes(data)).hexdigest()
        location.write_bytes(canonical_bytes(data))

    save(value)
    monkeypatch.setenv("ATLAS_RQALPHA_SECTOR_MEMBERSHIP", str(location))
    return value, location, save


def test_missing_membership_has_explicit_four_industry_data_blocker(monkeypatch):
    monkeypatch.delenv("ATLAS_RQALPHA_SECTOR_MEMBERSHIP", raising=False)
    rows = industries.catalog()
    assert len(rows) == 4
    assert all(row["symbols"] == [] and row["minute_intervals"] == [] for row in rows)
    assert all(row["membership_sha256"] is None and "2025" in row["reason"] for row in rows)


def test_frozen_membership_catalog_is_not_a_minute_coverage_claim(membership):
    value, _, _ = membership
    rows = industries.catalog()
    assert [row["id"] for row in rows] == [key for key in industries.INDUSTRIES if key != "strait"]
    assert all(row["symbols"] == [{"symbol": "600001.SS", "name": None}] for row in rows)
    assert all(row["membership_sha256"] == value["digest"] for row in rows)
    assert all(row["start"] is None and row["end"] is None for row in rows)
    assert all(
        row["minute_intervals"] == [] and "不代表完整行业" in row["membership_note"] for row in rows
    )


def test_selection_uses_publication_and_as_of_dates_without_future_members(membership):
    value, _, save = membership
    value["industries"]["semiconductor"].append(
        {
            "as_of": "2025-02-03",
            "published": "2025-01-20",
            "effective": "2024-12-31",
            "source": "https://example.test/later-pool",
            "symbols": ["600002.SS"],
        }
    )
    save(value)
    loaded = industries.load_membership()
    assert industries.membership_at(loaded, "semiconductor", "2025-01-21")["symbols"] == [
        "600001.SS"
    ]
    assert industries.membership_at(loaded, "semiconductor", "2025-02-03")["symbols"] == [
        "600002.SS"
    ]
    settings = LabMultiSettings(
        engine_id="rqalpha", symbols=["600001.SS"], industry="semiconductor"
    )
    frozen = industries.validate_daily_selection(settings, ["2025-01-02", "2025-01-03"])
    assert frozen["membership_sha256"] == value["digest"]
    assert frozen["selection_mode"] == "static-pool-from-start-of-run-membership"
    settings.symbols = ["600002.SS"]
    with pytest.raises(RunnerFailure, match="尚未公开纳入"):
        industries.validate_daily_selection(settings, ["2025-01-02"])


def test_announcement_before_effective_date_is_valid_when_used_after_both(membership):
    value, _, save = membership
    for rows in value["industries"].values():
        rows[0].update(published="2024-03-27", effective="2024-03-28", as_of="2025-01-02")
    save(value)
    assert industries.load_membership()["digest"] == value["digest"]


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "schema",
        "industry",
        "empty_versions",
        "future",
        "duplicate",
        "symbol",
        "source",
        "order",
    ],
)
def test_corrupt_or_noncausal_membership_is_not_silently_accepted(membership, change):
    value, location, save = membership
    row = value["industries"]["semiconductor"][0]
    if change == "digest":
        value["digest"] = "0" * 64
        location.write_bytes(canonical_bytes(value))
    else:
        if change == "schema":
            value["schema"] = "other"
        elif change == "industry":
            value["industries"]["other"] = value["industries"].pop("space")
        elif change == "empty_versions":
            value["industries"]["space"] = []
        elif change == "future":
            row["published"] = "2025-01-03"
        elif change == "duplicate":
            row["symbols"].append("600001.SS")
        elif change == "symbol":
            row["symbols"] = ["000001.SS"]
        elif change == "source":
            row["source"] = "file:///private"
        elif change == "order":
            value["industries"]["semiconductor"].append({**row, "as_of": "2024-12-31"})
        save(value)
    with pytest.raises(RunnerFailure, match="成员清单"):
        industries.load_membership()


def test_invalid_json_and_oversized_manifest_fail_closed(membership, monkeypatch):
    _, location, _ = membership
    location.write_text("{bad")
    with pytest.raises(RunnerFailure):
        industries.catalog()
    monkeypatch.setattr(industries, "MAX_MEMBERSHIP_BYTES", 2)
    location.write_bytes(json.dumps({"unexpected": 1}).encode())
    with pytest.raises(RunnerFailure):
        industries.catalog()


def test_daily_without_industry_does_not_require_a_sector_manifest(monkeypatch):
    monkeypatch.delenv("ATLAS_RQALPHA_SECTOR_MEMBERSHIP", raising=False)
    assert (
        industries.validate_daily_selection(LabMultiSettings(engine_id="rqalpha"), ["2025-01-02"])
        is None
    )


def strait_record():
    return {
        "as_of": "2025-01-02", "published": "2024-10-29", "effective": "2024-10-30",
        "source": "https://example.test/historical-concept-news", "symbols": ["603122.SS"],
        "scope": "historical-theme-research-sample", "partial": True,
        "selected_on": "2026-11-15", "membership_note": "部分研究观察池，不代表完整成分或龙头",
        "member_evidence": {"603122.SS": {
            "name": "合富中国", "basis": "annual-report-business-proxy",
            "source": "https://example.test/annual-report", "published": "2023-03-22",
        }},
    }


def test_strait_is_optional_and_activated_only_with_prepared_minutes(membership):
    value, _, save = membership
    assert industries.load_membership()["digest"] == value["digest"]
    assert len(industries.catalog()) == 4
    value["industries"]["strait"] = [strait_record()]
    save(value)
    assert len(industries.catalog()) == 4
    minute = {"start": "2025-01-02", "instruments": {
        "603122.SS": {"start": "2025-01-02", "end": "2026-08-06",
                      "complete_sessions": ["2025-01-02", "2025-01-03"], "gaps": {}},
    }, "source": {"repo_id": "neigezhu/china-a-share-1min-ohlcv",
                   "revision": "a" * 40, "last_complete_day": "2026-08-06"}}
    rows = industries.catalog(as_of="2025-01-02", minute=minute)
    assert len(rows) == 5
    row = rows[-1]
    assert row["id"] == "strait" and row["name"] == "海峡两岸（研究池）"
    assert row["symbols"][0]["name"] == "合富中国"
    assert row["minute_intervals"] == list(industries.MINUTE_INTERVALS)
    assert row["membership_selected_on"] == "2026-11-15"
    assert row["membership_evidence"]["603122.SS"]["published"] == "2023-03-22"
    assert "部分" in row["membership_note"]
    without_strait_data = {**minute, "instruments": {}}
    assert len(industries.catalog(as_of="2025-01-02", minute=without_strait_data)) == 4


def test_strait_selection_freezes_evidence_without_relabeling_business_as_market_concept(
    membership,
):
    value, _, save = membership
    value["industries"]["strait"] = [strait_record()]
    save(value)
    config = LabMultiSettings(engine_id="rqalpha", interval="1m", industry="strait",
                              symbols=["603122.SS"])
    selected = industries.validate_daily_selection(config, ["2025-01-02", "2025-01-03"])
    assert selected["membership_scope"] == "historical-theme-research-sample"
    assert selected["membership_evidence"]["603122.SS"]["basis"] == "annual-report-business-proxy"
    assert selected["membership_sha256"] == value["digest"]
    value["industries"]["strait"][0]["member_evidence"]["603122.SS"]["name"] = "后来更名"
    save(value)
    assert selected["membership_evidence"]["603122.SS"]["name"] == "合富中国"
    assert selected["membership_sha256"] != value["digest"]
    with pytest.raises(RunnerFailure, match="所选日期之前"):
        industries.validate_daily_selection(config, ["2024-10-29", "2024-10-30"])


@pytest.mark.parametrize("change", [
    "missing_evidence", "extra_evidence", "basis", "future_evidence", "source_scheme",
    "source_credentials", "source_whitespace", "source_del", "name_empty", "name_long",
    "note_empty", "note_long", "scope", "partial", "selected_on", "compact_date",
    "record_source_credentials", "same_day_publication", "future_effective",
])
def test_strait_evidence_rejects_unsupported_or_noncausal_claims(membership, change):
    value, _, save = membership
    record = strait_record()
    value["industries"]["strait"] = [record]
    item = record["member_evidence"]["603122.SS"]
    if change == "missing_evidence":
        record["member_evidence"] = {}
    elif change == "extra_evidence":
        record["member_evidence"]["600001.SS"] = item.copy()
    elif change == "basis":
        item["basis"] = "future-known-leader"
    elif change == "future_evidence":
        item["published"] = "2025-10-28"
    elif change == "source_scheme":
        item["source"] = "javascript:alert(1)"
    elif change == "source_credentials":
        item["source"] = "https://private@example.test/report"
    elif change == "source_whitespace":
        item["source"] = "https://example.test/unsafe path"
    elif change == "source_del":
        item["source"] = "https://example.test/unsafe\x7fpath"
    elif change == "name_empty":
        item["name"] = " "
    elif change == "name_long":
        item["name"] = "a" * 81
    elif change == "note_empty":
        record["membership_note"] = " "
    elif change == "note_long":
        record["membership_note"] = "a" * 1001
    elif change == "scope":
        record["scope"] = "official-complete-industry"
    elif change == "partial":
        record["partial"] = False
    elif change == "selected_on":
        record["selected_on"] = "2024-12-31"
    elif change == "compact_date":
        item["published"] = "20230322"
    elif change == "record_source_credentials":
        record["source"] = "https://private@example.test/source"
    elif change == "same_day_publication":
        record["published"] = "2025-01-02"
    elif change == "future_effective":
        record["effective"] = "2025-01-03"
    save(value)
    with pytest.raises(RunnerFailure, match="成员清单"):
        industries.load_membership()


def test_adding_strait_does_not_allow_missing_original_industries(membership):
    value, _, save = membership
    value["industries"]["strait"] = [strait_record()]
    value["industries"].pop("robotics")
    save(value)
    with pytest.raises(RunnerFailure, match="成员清单"):
        industries.load_membership()
