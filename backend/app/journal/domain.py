"""Pure domain rules for the imported Clarity investment ledger.

The API layer owns persistence and revisions.  This module deliberately works
only on JSON-compatible dictionaries so exported Clarity backups remain valid.
"""

from __future__ import annotations

import base64
import math
import re
from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

Ledger = dict[str, Any]
SHANGHAI = ZoneInfo("Asia/Shanghai")
CATEGORIES = {"crypto", "stock", "grid", "fund"}
KINDS = {"deposit", "withdraw", "valuation", "income", "fee"}
MARKETS = {"CRYPTO", "CN", "US"}


def _today(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SHANGHAI).date().isoformat()


def _round(value: float) -> float:
    return math.floor((value + 2.220446049250313e-16) * 100000000 + 0.5) / 100000000


def _add_days(value: str, days: int) -> str:
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def _range(start: str, end: str) -> list[str]:
    if end < start:
        return []
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if (last - first).days >= 36600:
        raise ValueError("日期范围过大")
    return [(first + timedelta(days=index)).isoformat() for index in range((last - first).days + 1)]


def _default_calendar() -> dict[str, dict[str, list[str]]]:
    return {
        "CN": {
            "2026": _range("2026-01-01", "2026-01-03")
            + _range("2026-02-15", "2026-02-23")
            + _range("2026-04-04", "2026-04-06")
            + _range("2026-05-01", "2026-05-05")
            + _range("2026-06-19", "2026-06-21")
            + _range("2026-09-25", "2026-09-27")
            + _range("2026-10-01", "2026-10-07")
        },
        "US": {
            "2026": [
                "2026-01-01",
                "2026-01-19",
                "2026-02-16",
                "2026-04-03",
                "2026-05-25",
                "2026-06-19",
                "2026-07-03",
                "2026-09-07",
                "2026-11-26",
                "2026-12-25",
            ],
            "2027": [
                "2027-01-01",
                "2027-01-18",
                "2027-02-15",
                "2027-03-26",
                "2027-05-31",
                "2027-06-18",
                "2027-07-05",
                "2027-09-06",
                "2027-11-25",
                "2027-12-24",
            ],
            "2028": [
                "2028-01-17",
                "2028-02-21",
                "2028-04-14",
                "2028-05-29",
                "2028-06-19",
                "2028-07-04",
                "2028-09-04",
                "2028-11-23",
                "2028-12-25",
            ],
        },
    }


def empty_ledger() -> Ledger:
    """Return a valid, intentionally empty import/export-compatible ledger."""
    return {
        "version": 1,
        "accounts": [],
        "holdings": [],
        "entries": [],
        "plans": [],
        "journals": [],
        "fxRates": [
            {"date": "2026-09-04", "rate": 6.7157, "source": "内置历史参考值 · 请更新汇率"}
        ],
        "calendar": _default_calendar(),
        "skipped": [],
        "settings": {"name": "我的投资空间", "monthlyBudget": 0, "autoFx": True},
    }


def clear_ledger(state: Ledger, keep_accounts: bool) -> Ledger:
    result = deepcopy(state)
    result["accounts"] = deepcopy(state.get("accounts", [])) if keep_accounts else []
    result.update({"holdings": [], "entries": [], "plans": [], "journals": [], "skipped": []})
    return result


def _is_date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _number(value: Any, minimum: float = 0, maximum: float = 1e12) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _text(value: Any, maximum: int = 200) -> bool:
    return isinstance(value, str) and len(value) <= maximum


def _image_ok(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 12000:
        return False
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", value)
    if not match or len(match.group(2)) % 4:
        return False
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError:
        return False
    return (
        (match.group(1) == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n"))
        or (match.group(1) == "jpeg" and raw.startswith(b"\xff\xd8\xff"))
        or (match.group(1) == "webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
    )


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _entry_sort_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return entry["date"], entry["createdAt"], entry["id"]


def _apply_entry(buckets: dict[str, float], entry: dict[str, Any]) -> None:
    key = f"{entry['accountId']}:{entry.get('holdingId', '')}"
    if entry["kind"] == "valuation" and not entry.get("holdingId"):
        positions = sum(
            value
            for other, value in buckets.items()
            if other.startswith(f"{entry['accountId']}:") and other != key
        )
        buckets[key] = _round(entry["amount"] - positions)
    elif entry["kind"] == "valuation":
        buckets[key] = _round(entry["amount"])
    else:
        sign = -1 if entry["kind"] in {"withdraw", "fee"} else 1
        buckets[key] = _round(buckets.get(key, 0) + sign * entry["amount"])


def _plan_holding_ids(plan: dict[str, Any]) -> list[str]:
    return (
        [item["holdingId"] for item in plan.get("allocations", [])]
        if plan.get("allocations") is not None
        else ([plan["holdingId"]] if plan.get("holdingId") else [])
    )


def _market_for(category: str) -> str:
    return "CN" if category == "fund" else "US" if category == "stock" else "CRYPTO"


def _fx_at(state: Ledger, on: str) -> dict[str, Any]:
    rates = sorted(state["fxRates"], key=lambda item: item["date"])
    return next((item for item in reversed(rates) if item["date"] <= on), rates[0])


def _convert(amount: float, source: str, destination: str, fx: float) -> float:
    return amount if source == destination else amount * fx if source == "USD" else amount / fx


def _trading_day(on: str, market: str, calendar: dict[str, Any]) -> tuple[bool, bool]:
    if market == "CRYPTO":
        return True, True
    holidays = calendar[market].get(on[:4])
    if holidays is None:
        return False, False
    day = date.fromisoformat(on)
    return (False, True) if day.weekday() >= 5 or on in holidays else (True, True)


def _scheduled_dates(
    plan: dict[str, Any], start: str, end: str, calendar: dict[str, Any]
) -> list[str]:
    if plan["paused"] or end < plan["startDate"]:
        return []
    start = max(start, plan["startDate"])
    scan = max(_add_days(start, -32), plan["startDate"])
    result: set[str] = set()
    for current in _range(scan, end):
        current_day = date.fromisoformat(current)
        month_end = (current_day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
            days=1
        )
        weekday = (current_day.weekday() + 1) % 7  # JS Sunday is zero.
        matches = (
            plan["frequency"] == "daily"
            or (plan["frequency"] == "weekdays" and 0 < weekday < 6)
            or (plan["frequency"] == "weekly" and weekday == plan["day"] % 7)
            or (
                plan["frequency"] == "monthly"
                and current_day.day == min(plan["day"], month_end.day)
            )
        )
        if not matches:
            continue
        due = current
        open_, known = _trading_day(due, plan["market"], calendar)
        if plan["frequency"] in {"daily", "weekdays"}:
            if not open_:
                continue
        else:
            for _ in range(16):
                if not known or open_:
                    break
                due = _add_days(due, 1)
                open_, known = _trading_day(due, plan["market"], calendar)
            if not known or not open_:
                continue
        if start <= due <= end:
            result.add(due)
    return sorted(result)


def _plan_active(state: Ledger, plan: dict[str, Any]) -> bool:
    accounts = {item["id"]: item for item in state["accounts"]}
    holdings = {item["id"]: item for item in state.get("holdings", [])}
    return bool(
        accounts.get(plan["accountId"])
        and not accounts[plan["accountId"]]["archived"]
        and not plan["paused"]
        and all(
            identifier in holdings and not holdings[identifier]["archived"]
            for identifier in _plan_holding_ids(plan)
        )
    )


def _plan_keys(plan: dict[str, Any], on: str) -> list[str]:
    root = f"{plan['id']}:{on}"
    return (
        [f"{root}:{index}" for index, _ in enumerate(plan["allocations"])]
        if plan.get("allocations") is not None
        else [root]
    )


def _plan_allocations(state: Ledger, plan: dict[str, Any], on: str) -> list[dict[str, Any]]:
    account = next(item for item in state["accounts"] if item["id"] == plan["accountId"])
    raw = plan.get("allocations")
    if raw is None:
        raw = [{"holdingId": plan["holdingId"]}] if plan.get("holdingId") else [{}]
        amounts = [plan["amount"]]
    elif plan["allocationMode"] == "amounts":
        amounts = [item["amount"] for item in raw]
    else:
        amounts, allocated = [], 0.0
        for index, item in enumerate(raw):
            value = (
                _round(plan["amount"] - allocated)
                if index == len(raw) - 1
                else _round(plan["amount"] * item["ratio"] / 100)
            )
            allocated = _round(allocated + value)
            amounts.append(value)
    fx = _fx_at(state, on)["rate"]
    converted = [
        _round(_convert(value, plan.get("currency", account["currency"]), account["currency"], fx))
        for value in amounts
    ]
    # Preserve exact total after currency rounding, as the TypeScript implementation does.
    total = _round(
        _convert(plan["amount"], plan.get("currency", account["currency"]), account["currency"], fx)
    )
    if converted:
        converted[-1] = _round(total - sum(converted[:-1]))
    return [
        {
            **({"holdingId": item["holdingId"]} if item.get("holdingId") else {}),
            "amount": converted[index],
            "plannedAmount": amounts[index],
        }
        for index, item in enumerate(raw)
    ]


def _position_price(state: Ledger, holding: dict[str, Any], on: str) -> float | None:
    """Match the legacy TS position tracker: the most recently recorded price wins."""
    unit_price: float | None = None
    for entry in sorted(
        (
            item
            for item in state["entries"]
            if item.get("holdingId") == holding["id"] and item["date"] <= on
        ),
        key=_entry_sort_key,
    ):
        if "unitPrice" in entry:
            unit_price = entry["unitPrice"]
    return unit_price


def _validate_ledger(input_state: Any, now: str) -> Ledger:
    """Validate a Clarity v1 backup; return it unchanged for JSON round trips."""
    _assert(isinstance(input_state, dict), "账本格式无效")
    state: Ledger = input_state
    _assert(type(state.get("version")) is int and state["version"] == 1, "不支持此账本版本")
    for key, limit, message in (
        ("accounts", 100, "账户最多 100 个"),
        ("entries", 10000, "流水最多 10,000 条"),
        ("plans", 100, "计划最多 100 个"),
        ("journals", 5000, "手记格式无效"),
    ):
        _assert(isinstance(state.get(key), list) and len(state[key]) <= limit, message)
    accounts: dict[str, dict[str, Any]] = {}
    for account in state["accounts"]:
        _assert(
            isinstance(account, dict)
            and _text(account.get("id"), 100)
            and account["id"]
            and ":" not in account["id"]
            and account["id"] not in accounts,
            "账户编号重复",
        )
        _assert(
            "image" not in account or _image_ok(account["image"]),
            "账户图片无效，请重新上传 PNG、JPG 或 WebP 缩略图",
        )
        _assert(
            _text(account.get("name"), 80)
            and account["name"].strip()
            and _text(account.get("platform"), 80)
            and _text(account.get("note"), 2000),
            "账户信息无效",
        )
        _assert(
            account.get("category") in CATEGORIES
            and account.get("currency") in {"USD", "CNY"}
            and isinstance(account.get("archived"), bool),
            "账户类型无效",
        )
        _assert(
            account["currency"] == ("CNY" if account["category"] == "fund" else "USD"),
            "Crypto、美股使用 USD；基金使用 CNY",
        )
        accounts[account["id"]] = account
    holdings_value = state.get("holdings", [])
    _assert(
        "holdings" not in state
        or (isinstance(holdings_value, list) and len(holdings_value) <= 500),
        "标的最多 500 个",
    )
    holdings: dict[str, dict[str, Any]] = {}
    for holding in holdings_value:
        _assert(
            isinstance(holding, dict)
            and _text(holding.get("id"), 100)
            and holding["id"]
            and ":" not in holding["id"]
            and holding["id"] not in holdings
            and holding.get("accountId") in accounts
            and _text(holding.get("symbol"), 30)
            and holding["symbol"].strip()
            and _text(holding.get("name"), 80)
            and holding["name"].strip()
            and isinstance(holding.get("archived"), bool),
            "标的信息无效",
        )
        _assert("assetType" not in holding or holding["assetType"] in CATEGORIES, "资产类型无效")
        _assert(
            "trackingMode" not in holding or holding["trackingMode"] in {"amount", "quantity"},
            "资产记录方式无效",
        )
        _assert(
            "side" not in holding or holding["side"] in {"long", "short", "neutral"}, "仓位方向无效"
        )
        _assert("leverage" not in holding or _number(holding["leverage"], 1, 1000), "杠杆倍数无效")
        holdings[holding["id"]] = holding
    entry_ids: set[str] = set()
    plan_keys: set[str] = set()
    for entry in state["entries"]:
        _assert(
            isinstance(entry, dict)
            and _text(entry.get("id"), 100)
            and entry["id"]
            and entry["id"] not in entry_ids,
            "流水编号重复",
        )
        entry_ids.add(entry["id"])
        _assert(
            entry.get("accountId") in accounts and entry.get("kind") in KINDS, "流水账户或类型无效"
        )
        _assert(
            _number(entry.get("amount"))
            and (entry["kind"] == "valuation" or entry["amount"] > 0)
            and _number(entry.get("fx"), 0.01, 1000),
            "金额和汇率必须为有效正数",
        )
        _assert(
            _is_date(entry.get("date")) and "2000-01-01" <= entry["date"] <= now,
            "记账日期必须在 2000 年至今天之间",
        )
        _assert(
            _text(entry.get("note"), 2000)
            and _text(entry.get("createdAt"), 40)
            and re.match(r"\d{4}-\d{2}-\d{2}T", entry["createdAt"]) is not None,
            "流水信息无效",
        )
        try:
            datetime.fromisoformat(entry["createdAt"].replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("流水信息无效") from None
        if entry.get("holdingId"):
            _assert(
                entry["holdingId"] in holdings
                and holdings[entry["holdingId"]]["accountId"] == entry["accountId"],
                "标的必须属于所选账户",
            )
        for key in ("quantitySet", "quantityDelta", "unitPrice", "unitCost"):
            _assert(
                key not in entry or (_number(entry[key]) and bool(entry.get("holdingId"))),
                "资产数量与价格必须是非负数且归属资产",
            )
        _assert(
            "principalAdjustment" not in entry
            or (
                _number(entry["principalAdjustment"], -1e12, 1e12)
                and entry["kind"] == "valuation"
                and bool(entry.get("holdingId"))
            ),
            "本金更正格式无效",
        )
        _assert(
            "reportedRoi" not in entry
            or (_number(entry["reportedRoi"], -100, 100000) and entry["kind"] == "valuation"),
            "手动收益率格式无效",
        )
        _assert(
            "automatic" not in entry
            or (isinstance(entry["automatic"], bool) and bool(entry.get("planKey"))),
            "自动流水格式无效",
        )
        if entry.get("planKey"):
            _assert(
                _text(entry["planKey"], 150)
                and entry["planKey"] not in plan_keys
                and entry["kind"] == "deposit",
                "定投不可重复确认",
            )
            plan_keys.add(entry["planKey"])
        _assert(
            "transferId" not in entry
            or (_text(entry["transferId"], 100) and entry["kind"] in {"deposit", "withdraw"}),
            "转账格式错误",
        )
    for transfer_id in {
        item.get("transferId") for item in state["entries"] if item.get("transferId")
    }:
        legs = [item for item in state["entries"] if item.get("transferId") == transfer_id]
        _assert(
            len(legs) == 2
            and legs[0]["kind"] != legs[1]["kind"]
            and (legs[0]["accountId"], legs[0].get("holdingId"))
            != (legs[1]["accountId"], legs[1].get("holdingId"))
            and legs[0]["amount"] == legs[1]["amount"]
            and legs[0]["date"] == legs[1]["date"]
            and legs[0]["fx"] == legs[1]["fx"]
            and accounts[legs[0]["accountId"]]["currency"]
            == accounts[legs[1]["accountId"]]["currency"],
            "转账必须包含同币种、同金额、同日期的两笔流水",
        )
    buckets: dict[str, float] = {}
    for entry in sorted(state["entries"], key=_entry_sort_key):
        _apply_entry(buckets, entry)
        _assert(
            buckets.get(f"{entry['accountId']}:{entry.get('holdingId', '')}", 0) >= -1e-6,
            "取出、分配或费用超过该日可用余额；账户整体估值不能低于标的估值合计",
        )
    _validate_plans(state, accounts, holdings)
    journals: set[str] = set()
    for journal in state["journals"]:
        _assert(
            isinstance(journal, dict)
            and _text(journal.get("id"), 100)
            and journal["id"] not in journals
            and _is_date(journal.get("date"))
            and journal["date"] <= now
            and _text(journal.get("title"), 120)
            and journal["title"].strip()
            and _text(journal.get("body"), 10000)
            and _text(journal.get("tag"), 30),
            "手记格式无效",
        )
        journals.add(journal["id"])
    _validate_remainder(state, now)
    return state


def validate_ledger(input_state: Any) -> Ledger:
    """Validate a Clarity v1 backup against today's Shanghai date."""
    try:
        return _validate_ledger(input_state, _today())
    except (TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise ValueError("账本字段格式无效") from exc


def _validate_plans(
    state: Ledger, accounts: dict[str, dict[str, Any]], holdings: dict[str, dict[str, Any]]
) -> None:
    plan_ids: set[str] = set()
    for plan in state["plans"]:
        _assert(
            isinstance(plan, dict)
            and _text(plan.get("id"), 100)
            and plan["id"]
            and plan["id"] not in plan_ids,
            "计划编号重复",
        )
        plan_ids.add(plan["id"])
        _assert(
            plan.get("accountId") in accounts
            and _text(plan.get("name"), 80)
            and plan["name"].strip()
            and _number(plan.get("amount"), 0.01)
            and plan.get("frequency") in {"daily", "weekdays", "weekly", "monthly"}
            and plan.get("market") in MARKETS
            and isinstance(plan.get("paused"), bool),
            "定投信息无效",
        )
        _assert(
            "currency" not in plan or plan["currency"] in {"USD", "CNY"},
            "定投币种必须为 USD 或 CNY",
        )
        _assert("mode" not in plan or plan["mode"] in {"auto", "manual"}, "记账方式无效")
        _assert("autoFrom" not in plan or _is_date(plan["autoFrom"]), "自动开始日期无效")
        allocations = plan.get("allocations")
        _assert("allocations" not in plan or isinstance(allocations, list), "定投资产分配无效")
        if allocations is not None:
            _assert(
                plan.get("allocationMode") in {"amounts", "ratios"}
                and isinstance(allocations, list)
                and 0 < len(allocations) <= 100,
                "定投资产分配无效",
            )
            allocation_ids: set[str] = set()
            for allocation in allocations:
                _assert(
                    isinstance(allocation, dict)
                    and _text(allocation.get("holdingId"), 100)
                    and allocation["holdingId"] not in allocation_ids
                    and allocation["holdingId"] in holdings
                    and holdings[allocation["holdingId"]]["accountId"] == plan["accountId"],
                    "定投资产必须唯一且属于所选账户",
                )
                allocation_ids.add(allocation["holdingId"])
                if plan["allocationMode"] == "amounts":
                    _assert(
                        _number(allocation.get("amount"), 0.01) and "ratio" not in allocation,
                        "每项定投金额必须大于 0",
                    )
                else:
                    _assert(
                        _number(allocation.get("ratio"), 0.0001, 100)
                        and "amount" not in allocation,
                        "定投占比必须大于 0 且不超过 100%",
                    )
            total = sum(
                item["amount"] if plan["allocationMode"] == "amounts" else item["ratio"]
                for item in allocations
            )
            _assert(
                _round(total) == _round(plan["amount"])
                if plan["allocationMode"] == "amounts"
                else abs(total - 100) < 0.0001,
                "各资产定投金额之和必须等于计划总额"
                if plan["allocationMode"] == "amounts"
                else "各资产定投占比合计必须为 100%",
            )
            _assert("holdingId" not in plan, "组合定投不能同时设置旧版单一标的")
        else:
            _assert("allocationMode" not in plan, "定投资产分配无效")
        if plan.get("holdingId"):
            _assert(
                plan["holdingId"] in holdings
                and holdings[plan["holdingId"]]["accountId"] == plan["accountId"],
                "定投标的必须属于所选账户",
            )
        asset_types = [
            holdings[identifier].get("assetType", accounts[plan["accountId"]]["category"])
            for identifier in _plan_holding_ids(plan)
        ] or [accounts[plan["accountId"]]["category"]]
        _assert(
            len({_market_for(item) for item in asset_types}) == 1,
            "同一定投计划中的资产必须使用相同市场日历",
        )
        _assert(plan["market"] == _market_for(asset_types[0]), "市场必须与账户资产类型一致")
        _assert(
            isinstance(plan.get("day"), int)
            and not isinstance(plan["day"], bool)
            and 1 <= plan["day"] <= (7 if plan["frequency"] == "weekly" else 31)
            and _is_date(plan.get("startDate"))
            and plan["startDate"] >= "2000-01-01"
            and isinstance(plan.get("time"), str)
            and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", plan["time"]) is not None,
            "定投日期或时间无效",
        )


def _validate_remainder(state: Ledger, now: str) -> None:
    rates = state.get("fxRates")
    _assert(isinstance(rates, list) and 0 < len(rates) <= 10000, "至少保留一个有效汇率")
    seen: set[str] = set()
    for rate in rates:
        _assert(
            isinstance(rate, dict)
            and _is_date(rate.get("date"))
            and rate["date"] <= now
            and _number(rate.get("rate"), 0.01, 1000)
            and _text(rate.get("source"), 100)
            and rate["date"] not in seen,
            "汇率记录无效或日期重复",
        )
        seen.add(rate["date"])
    calendar = state.get("calendar")
    _assert(isinstance(calendar, dict), "缺少交易日历")
    for market in ("CN", "US"):
        value = calendar.get(market)
        _assert(isinstance(value, dict), "交易日历无效")
        for year, dates in value.items():
            _assert(
                isinstance(year, str)
                and re.fullmatch(r"20\d{2}", year) is not None
                and isinstance(dates, list)
                and len(dates) <= 366
                and all(_is_date(item) and item.startswith(year) for item in dates),
                "休市日期必须与年份相符",
            )
    _assert(
        isinstance(state.get("skipped"), list)
        and len(state["skipped"]) <= 10000
        and all(_text(item, 150) for item in state["skipped"]),
        "跳过记录无效",
    )
    settings = state.get("settings")
    _assert(
        isinstance(settings, dict)
        and _text(settings.get("name"), 80)
        and settings["name"].strip()
        and _number(settings.get("monthlyBudget"), 0)
        and isinstance(settings.get("autoFx"), bool),
        "设置无效",
    )


def materialize_automatic(input_state: Ledger, now: datetime | None = None) -> dict[str, Any]:
    """Return a deep-copied ledger with due automatic plan deposits materialized."""
    state = deepcopy(input_state)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    local = current.astimezone(SHANGHAI)
    today = local.date().isoformat()
    _validate_ledger(state, today)
    state.setdefault("holdings", [])
    for plan in state["plans"]:
        if not plan.get("mode"):
            plan.update(mode="auto", autoFrom=today)
    added = 0
    for plan in state["plans"]:
        if plan.get("mode") != "auto" or plan["paused"] or not _plan_active(state, plan):
            continue
        start = max(plan["startDate"], plan.get("autoFrom", plan["startDate"]))
        for due in _scheduled_dates(plan, start, today, state["calendar"]):
            plan_time = time.fromisoformat(plan["time"])
            due_at = datetime.combine(date.fromisoformat(due), plan_time, SHANGHAI)
            if due_at > local:
                continue
            keys = _plan_keys(plan, due)
            pending = [
                (allocation, key)
                for allocation, key in zip(_plan_allocations(state, plan, due), keys, strict=True)
                if not any(entry.get("planKey") == key for entry in state["entries"])
            ]
            if f"{plan['id']}:{due}" in state["skipped"]:
                continue
            if len(state["entries"]) + len(pending) > 10000:
                raise ValueError("流水已达上限，请先备份并整理历史记录后再自动记账")
            account = next(item for item in state["accounts"] if item["id"] == plan["accountId"])
            for allocation, key in pending:
                holding = next(
                    (
                        item
                        for item in state.get("holdings", [])
                        if item["id"] == allocation.get("holdingId")
                    ),
                    None,
                )
                price = _position_price(state, holding, due) if holding else None
                quantity = (
                    allocation["amount"] / price
                    if holding
                    and holding.get("trackingMode") != "amount"
                    and holding.get("assetType", account["category"]) != "grid"
                    and price is not None
                    and price > 0
                    else None
                )
                currency = plan.get("currency", account["currency"])
                planned_money = (
                    "$" if currency == "USD" else "¥"
                ) + f"{allocation['plannedAmount']:,.2f}"
                note = (
                    f"按计划自动记账：{plan['name']} · {planned_money}（北京时间；不代表实际成交）"
                )
                note += (
                    "；已累计投入金额，可在资产中更新收益率"
                    if holding and holding.get("trackingMode") == "amount"
                    else "；数量按最近手动价格估算"
                    if quantity is not None
                    else "；数量待实际成交后更新"
                )
                state["entries"].append(
                    {
                        "id": str(uuid4()),
                        "accountId": plan["accountId"],
                        **(
                            {"holdingId": allocation["holdingId"]}
                            if allocation.get("holdingId")
                            else {}
                        ),
                        "kind": "deposit",
                        "amount": allocation["amount"],
                        **(
                            {"quantityDelta": quantity, "unitPrice": price}
                            if quantity is not None
                            else {}
                        ),
                        "date": due,
                        "fx": _fx_at(state, due)["rate"],
                        "note": note,
                        "createdAt": due_at.astimezone(UTC)
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z"),
                        "planKey": key,
                        "automatic": True,
                    }
                )
                added += 1
    _validate_ledger(state, today)
    return {"state": state, "added": added}
