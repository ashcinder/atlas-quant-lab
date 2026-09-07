from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.journal.domain import (
    clear_ledger,
    empty_ledger,
    materialize_automatic,
    validate_ledger,
)


def ledger_with_account() -> dict:
    state = empty_ledger()
    state["accounts"] = [
        {
            "id": "wallet",
            "name": "Wallet",
            "platform": "Test",
            "category": "crypto",
            "currency": "USD",
            "archived": False,
            "note": "",
        }
    ]
    state["fxRates"][0]["date"] = "2026-09-01"
    return state


def entry(identifier: str, kind: str = "deposit", amount: float = 100, **extra) -> dict:
    return {
        "id": identifier,
        "accountId": "wallet",
        "kind": kind,
        "amount": amount,
        "date": "2026-09-01",
        "fx": 7.0,
        "note": "test",
        "createdAt": "2026-09-01T00:00:00.000Z",
        **extra,
    }


def plan(**extra) -> dict:
    return {
        "id": "daily",
        "accountId": "wallet",
        "name": "Daily",
        "amount": 10,
        "frequency": "daily",
        "market": "CRYPTO",
        "time": "09:00",
        "day": 1,
        "startDate": "2026-09-01",
        "paused": False,
        "mode": "auto",
        **extra,
    }


def test_empty_ledger_is_valid_and_clear_keeps_only_accounts():
    state = ledger_with_account()
    state["entries"] = [entry("opening")]
    state["journals"] = [
        {"id": "j", "date": "2026-09-01", "title": "note", "body": "body", "tag": "tag"}
    ]
    validate_ledger(state)
    cleared = clear_ledger(state, True)
    assert len(cleared["accounts"]) == 1
    assert not cleared["entries"] and not cleared["plans"] and not cleared["journals"]
    assert clear_ledger(state, False)["accounts"] == []


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda state: state["accounts"][0].update(id="bad:id"), "账户编号重复"),
        (lambda state: state.update(entries=[entry("x", amount=-1)]), "金额和汇率"),
        (lambda state: state.update(entries=[entry("x", date="2026-02-30")]), "记账日期"),
        (
            lambda state: state.update(entries=[entry("x", planKey="p"), entry("y", planKey="p")]),
            "定投不可重复",
        ),
    ],
)
def test_validation_rejects_invalid_backup(mutate, message):
    state = ledger_with_account()
    mutate(state)
    with pytest.raises(ValueError, match=message):
        validate_ledger(state)


def test_validation_rejects_unbalanced_transfers_and_negative_balance():
    state = ledger_with_account()
    state["entries"] = [entry("a", "withdraw", 10, transferId="transfer")]
    with pytest.raises(ValueError, match="转账必须"):
        validate_ledger(state)
    state["entries"] = [entry("a", "withdraw", 10)]
    with pytest.raises(ValueError, match="超过该日可用余额"):
        validate_ledger(state)


def test_validation_checks_holding_plan_allocation_and_market():
    state = ledger_with_account()
    state["holdings"] = [
        {
            "id": "btc",
            "accountId": "wallet",
            "symbol": "BTC",
            "name": "Bitcoin",
            "archived": False,
            "trackingMode": "quantity",
        }
    ]
    state["plans"] = [
        plan(
            allocationMode="ratios",
            allocations=[{"holdingId": "btc", "ratio": 90}],
        )
    ]
    with pytest.raises(ValueError, match="占比合计"):
        validate_ledger(state)
    state["plans"] = [plan(market="US")]
    with pytest.raises(ValueError, match="市场必须"):
        validate_ledger(state)


def test_monthly_holiday_defers_when_calendar_year_known():
    state = ledger_with_account()
    state["accounts"][0].update(category="fund", currency="CNY")
    state["plans"] = [
        plan(
            frequency="monthly",
            market="CN",
            day=25,
            startDate="2026-09-01",
            time="09:00",
        )
    ]
    validate_ledger(state)
    result = materialize_automatic(state, datetime(2026, 9, 28, 2, tzinfo=UTC))
    assert result["added"] == 1
    assert result["state"]["entries"][0]["date"] == "2026-09-28"


def test_unknown_calendar_year_does_not_materialize_stock_plan():
    state = ledger_with_account()
    state["accounts"][0].update(category="stock")
    state["plans"] = [plan(frequency="monthly", market="US", day=1, startDate="2029-01-01")]
    validate_ledger(state)
    result = materialize_automatic(state, datetime(2029, 1, 10, tzinfo=UTC))
    assert result["added"] == 0


def test_automatic_plan_is_idempotent_skippable_and_does_not_mutate_input():
    state = ledger_with_account()
    state["plans"] = [plan(startDate="2026-09-01")]
    original = deepcopy(state)
    now = datetime(2026, 9, 3, 2, tzinfo=UTC)
    first = materialize_automatic(state, now)
    assert state == original
    assert first["added"] == 3
    assert len({item["planKey"] for item in first["state"]["entries"]}) == 3
    assert materialize_automatic(first["state"], now)["added"] == 0
    skipped = ledger_with_account()
    skipped["plans"] = [plan(startDate="2026-09-01")]
    skipped["skipped"] = ["daily:2026-09-02"]
    result = materialize_automatic(skipped, now)
    assert {item["date"] for item in result["state"]["entries"]} == {"2026-09-01", "2026-09-03"}


def test_cross_currency_and_legacy_single_holding_automatic_allocation():
    state = ledger_with_account()
    state["accounts"][0].update(category="fund", currency="CNY")
    state["holdings"] = [
        {"id": "fund-a", "accountId": "wallet", "symbol": "F", "name": "Fund", "archived": False}
    ]
    state["plans"] = [
        plan(
            amount=10,
            currency="USD",
            holdingId="fund-a",
            startDate="2026-09-01",
            market="CN",
        )
    ]
    result = materialize_automatic(state, datetime(2026, 9, 1, 2, tzinfo=UTC))
    saved = result["state"]["entries"][0]
    assert saved["holdingId"] == "fund-a"
    assert saved["amount"] == 10 * state["fxRates"][0]["rate"]


def test_quantity_holding_automatic_plan_uses_latest_manual_price():
    state = ledger_with_account()
    state["holdings"] = [
        {
            "id": "btc",
            "accountId": "wallet",
            "symbol": "BTC",
            "name": "Bitcoin",
            "archived": False,
            "trackingMode": "quantity",
        }
    ]
    state["entries"] = [
        entry(
            "manual",
            holdingId="btc",
            kind="valuation",
            amount=200,
            quantitySet=2,
            unitPrice=100,
            unitCost=90,
        )
    ]
    state["plans"] = [plan(holdingId="btc", amount=10, startDate="2026-09-02")]
    result = materialize_automatic(state, datetime(2026, 9, 2, 2, tzinfo=UTC))
    automatic = result["state"]["entries"][-1]
    assert automatic["quantityDelta"] == 0.1
    assert automatic["unitPrice"] == 100
