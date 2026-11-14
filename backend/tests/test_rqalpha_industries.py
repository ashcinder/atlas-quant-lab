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
        "industries": {key: [copy.deepcopy(base)] for key in industries.INDUSTRIES},
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
    assert [row["id"] for row in rows] == list(industries.INDUSTRIES)
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
