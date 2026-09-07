"""Golden results captured from the unchanged Clarity TypeScript test suite.

The production backend never invokes JavaScript. Fixtures keep cross-language
validation and automatic bookkeeping behavior reviewable and reproducible.
"""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from app.journal import domain

FIXTURES = Path(__file__).parent / "journal_fixtures"


@pytest.mark.parametrize("example", json.loads((FIXTURES / "validation.json").read_text()))
def test_clarity_validation_parity(example, monkeypatch):
    monkeypatch.setattr(domain, "_today", lambda *args: "2026-09-06")
    if example["valid"]:
        assert domain.validate_ledger(example["input"]) == example["input"]
    else:
        with pytest.raises(ValueError):
            domain.validate_ledger(example["input"])


@pytest.mark.parametrize("example", json.loads((FIXTURES / "auto.json").read_text()))
def test_clarity_automatic_bookkeeping_parity(example):
    before = deepcopy(example["input"])
    now = datetime.fromisoformat(example["now"].replace("Z", "+00:00"))
    result = domain.materialize_automatic(before, now)
    assert before == example["input"], "Materialization must not partially modify caller state"
    expected = deepcopy(example["result"])
    for value in (result, expected):
        for entry in value["state"]["entries"]:
            entry.pop("id", None)  # Each implementation generates fresh UUIDs.
    assert result == expected
