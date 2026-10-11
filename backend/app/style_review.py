"""Snapshot-based style review. Uploaded data is not authenticated market evidence."""

import csv
import hashlib
import io
import json
import sqlite3
import struct
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import DATA_DIR

router = APIRouter(prefix="/api/v1/style-review", tags=["style-review"])
DB = DATA_DIR / "style_review.db"
ENGINE = "style-review-v1"
HASH_SCHEME = "typed-json-ieee754-v1"


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    fund_code: str = Field(min_length=1, max_length=40)
    fund_name: str = Field(min_length=1, max_length=100)
    theme: str = Field(min_length=1, max_length=100)
    rule_version: str = Field(min_length=1, max_length=60)
    rule_basis: str = Field(min_length=1, max_length=4000)
    denominator_basis: str = Field(min_length=1, max_length=1000)
    as_of: date
    effective_on: date
    previous_effective_on: date
    library_version: str = Field(min_length=1, max_length=60)
    previous_version: str = Field(min_length=1, max_length=60)
    change_reason: str = Field(min_length=1, max_length=2000)
    threshold: Decimal = Field(ge=0, le=100, max_digits=8, decimal_places=4)
    denominator: Decimal = Field(gt=0, le=Decimal("1e16"), max_digits=23, decimal_places=6)
    complete: bool
    demo: bool = False
    source: str = Field(min_length=1, max_length=2000)
    holdings_csv: str = Field(min_length=1, max_length=500000)
    library_csv: str = Field(min_length=1, max_length=500000)
    previous_library_csv: str = Field(min_length=1, max_length=500000)

    @model_validator(mode="after")
    def dates(self):
        if not self.previous_effective_on <= self.effective_on <= self.as_of:
            raise ValueError("需满足旧版生效日 ≤ 新版生效日 ≤ 持仓日期")
        return self


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=4000)
    outcome: str = Field(pattern="^(待补材料|已记录说明|建议调整|复核完成)$")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    # Browser JSON round-trips turn 85.0 into 85. Hash numeric values, not spelling.
    # Type tags prevent user strings/objects from aliasing the numeric encoding.
    def typed(item):
        if item is None:
            return ["null"]
        if isinstance(item, bool):
            return ["boolean", item]
        if isinstance(item, (int, float)):
            return ["number", struct.pack(">d", float(item) if item else 0.0).hex()]
        if isinstance(item, str):
            return ["string", item]
        if isinstance(item, list):
            return ["array", [typed(v) for v in item]]
        if isinstance(item, dict):
            return ["object", [[k, typed(v)] for k, v in sorted(item.items())]]
        raise ValueError("不支持的摘要数据类型")

    return hashlib.sha256(canonical(typed(value)).encode()).hexdigest()


def rows(text, columns):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    if reader.fieldnames != columns:
        raise ValueError("CSV表头必须为：" + ",".join(columns))
    result = []
    seen = set()
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("CSV列数不一致")
        row = {k: v.strip() for k, v in row.items()}
        if not row["code"] or row["code"] in seen:
            raise ValueError("证券代码为空或重复，请按证券代码汇总")
        if any(len(v) > 4000 for v in row.values()):
            raise ValueError("单元格过长")
        seen.add(row["code"])
        result.append(row)
        if len(result) > 5000:
            raise ValueError("每份数据最多5000行")
    return sorted(result, key=lambda row: row["code"])


def calculate(data):
    current = rows(data.library_csv, ["code", "name", "basis"])
    previous = rows(data.previous_library_csv, ["code", "name", "basis"])
    holdings = rows(data.holdings_csv, ["code", "name", "value"])
    if not holdings:
        raise ValueError("至少提供一条持仓")
    old = {r["code"]: r for r in previous}
    new = {r["code"]: r for r in current}
    details = []
    total = old_total = new_total = Decimal(0)
    for row in holdings:
        try:
            amount = Decimal(row["value"])
        except InvalidOperation as exc:
            raise ValueError("市值必须为有限非负数") from exc
        if not amount.is_finite() or amount < 0 or amount > Decimal("1e16"):
            raise ValueError("市值必须为有限非负数且不超过1e16")
        if amount.as_tuple().exponent < -6:
            raise ValueError("市值最多6位小数")
        code = row["code"]
        total += amount
        old_total += amount if code in old else 0
        new_total += amount if code in new else 0
        details.append(
            {
                **row,
                "in_old": code in old,
                "in_new": code in new,
                "basis": new.get(code, {}).get("basis", ""),
                "contribution_pp": float(
                    amount / data.denominator * 100 * (int(code in new) - int(code in old))
                ),
            }
        )
    if total > data.denominator:
        raise ValueError("持仓市值超过所填非现金资产，请检查分母、币种及重复数据")
    if data.complete and total != data.denominator:
        raise ValueError("完整数据要求持仓市值合计等于非现金资产；其他非现金资产也须列入")
    lower = new_total / data.denominator * 100
    upper = (new_total + data.denominator - total) / data.denominator * 100
    status = (
        "比例偏离"
        if upper < data.threshold
        else "本项比例达标"
        if lower >= data.threshold
        else "证据不足"
    )
    return {
        "engine": ENGINE,
        "status": status,
        "current_pct": float(lower),
        "upper_pct": float(upper),
        "previous_pct": float(old_total / data.denominator * 100),
        "library_effect_pp": float((new_total - old_total) / data.denominator * 100),
        "coverage_pct": float(total / data.denominator * 100),
        "rows": details,
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "missing_basis": [r["code"] for r in current if not r["basis"]],
        "basis_changed": [
            k for k in sorted(new.keys() & old.keys()) if new[k]["basis"] != old[k]["basis"]
        ],
        "limitations": [
            "按用户提交名单计算，不代表入库资格或监管合规已确认",
            "来源未独立验证；完整性声明不等于真实性证明",
            "仅量化固定持仓下的名单影响，不推断交易、市场影响或主观意图",
            "无机构签名、TEE、ZKP或链上存证；不自动对外报送",
        ],
    }


@contextmanager
def connect():
    con = sqlite3.connect(DB, timeout=15)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions (
            owner TEXT, fund TEXT, kind TEXT, version TEXT, fingerprint TEXT,
            PRIMARY KEY(owner, fund, kind, version));
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, report TEXT REFERENCES reports(id),
            body TEXT NOT NULL);
    """)
    try:
        with con:
            yield con
    finally:
        con.close()


def user(request):
    actor = getattr(request.state, "user", None)
    if actor is None:
        raise HTTPException(401, "需要登录")
    return actor.id


def get_report(con, owner, report_id):
    row = con.execute(
        "SELECT body FROM reports WHERE id=? AND owner=?", (report_id, owner)
    ).fetchone()
    if not row:
        raise HTTPException(404, "报告不存在")
    return json.loads(row[0])


@router.post("/reports")
def create_report(data: ReviewInput, request: Request):
    owner = user(request)
    try:
        result = calculate(data)
        versions = [
            (
                "rule",
                data.rule_version,
                {
                    "theme": data.theme,
                    "basis": data.rule_basis,
                    "denominator_basis": data.denominator_basis,
                    "threshold": str(data.threshold),
                },
            ),
            (
                "library",
                data.library_version,
                {
                    "effective": str(data.effective_on),
                    "rows": rows(data.library_csv, ["code", "name", "basis"]),
                },
            ),
            (
                "library",
                data.previous_version,
                {
                    "effective": str(data.previous_effective_on),
                    "rows": rows(data.previous_library_csv, ["code", "name", "basis"]),
                },
            ),
        ]
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    payload = {
        "id": uuid4().hex,
        "received_at": datetime.now(UTC).isoformat(),
        "input": data.model_dump(mode="json"),
        "result": result,
    }
    report = {"payload": payload, "sha256": digest(payload), "hash_scheme": HASH_SCHEME}
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        for kind, version, content in versions:
            fingerprint = digest(content)
            key = (owner, data.fund_code, kind, version)
            existing = con.execute(
                "SELECT fingerprint FROM versions "
                "WHERE owner=? AND fund=? AND kind=? AND version=?",
                key,
            ).fetchone()
            if existing and existing[0] != fingerprint:
                raise HTTPException(409, f"{kind}版本 {version} 已有不同内容，请创建新版本")
            con.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?,?)", (*key, fingerprint))
        con.execute("INSERT INTO reports VALUES(?,?,?)", (payload["id"], owner, canonical(report)))
    return report


@router.get("/reports")
def list_reports(request: Request):
    with connect() as con:
        records = con.execute(
            "SELECT body FROM reports WHERE owner=? ORDER BY rowid DESC LIMIT 200", (user(request),)
        ).fetchall()
    return [
        {
            "id": r["payload"]["id"],
            "received_at": r["payload"]["received_at"],
            "fund_name": r["payload"]["input"]["fund_name"],
            "fund_code": r["payload"]["input"]["fund_code"],
            "as_of": r["payload"]["input"]["as_of"],
            "version": r["payload"]["input"]["library_version"],
            "status": r["payload"]["result"]["status"],
            "demo": r["payload"]["input"]["demo"],
        }
        for r in (json.loads(row[0]) for row in records)
    ]


@router.get("/reports/{report_id}")
def read_report(report_id: str, request: Request):
    with connect() as con:
        report = get_report(con, user(request), report_id)
        notes = [
            json.loads(row[0])
            for row in con.execute(
                "SELECT body FROM notes WHERE report=? ORDER BY id", (report_id,)
            )
        ]
    return {**report, "notes": notes}


@router.post("/reports/{report_id}/notes")
def append_note(report_id: str, note: Note, request: Request):
    owner = user(request)
    record = {**note.model_dump(), "actor": owner, "at": datetime.now(UTC).isoformat()}
    with connect() as con:
        get_report(con, owner, report_id)
        con.execute("INSERT INTO notes(report,body) VALUES(?,?)", (report_id, canonical(record)))
    return record


@router.post("/verify")
def verify_bundle(bundle: dict, request: Request):
    user(request)
    try:
        payload = bundle["payload"]
        data = ReviewInput.model_validate(payload["input"])
        expected = calculate(data)
        return {
            "hash_matches": bundle.get("hash_scheme") == HASH_SCHEME
            and digest(payload) == bundle.get("sha256"),
            "calculation_matches": expected == payload["result"],
            "engine_matches": payload["result"]["engine"] == ENGINE,
            "notice": "自包含复算不认证来源或签发者；可同时改内容与摘要。复核备注不在摘要范围内。",
        }
    except (KeyError, TypeError, ValueError, OverflowError, csv.Error) as exc:
        raise HTTPException(422, "复核包格式无效或输入未通过校验") from exc
