"""User-supplied disclosure extracts compared with same-scope source records."""

import csv
import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import DATA_DIR
from app.style_review import canonical, rows, user

router = APIRouter(prefix="/api/v1/disclosure-review", tags=["disclosure-review"])
DB = DATA_DIR / "disclosure_review.db"


class DisclosureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    fund_code: str = Field(min_length=1, max_length=40)
    fund_name: str = Field(min_length=1, max_length=100)
    disclosure_date: date
    records_date: date
    disclosure_source: str = Field(min_length=1, max_length=1000)
    records_source: str = Field(min_length=1, max_length=1000)
    scope: str = Field(min_length=1, max_length=1000)
    currency: str = Field(pattern="^[A-Z]{3}$")
    same_basis: bool
    complete_scope: bool
    demo: bool = False
    quantity_tolerance: Decimal = Field(ge=0, le=1000000, decimal_places=6)
    value_tolerance: Decimal = Field(ge=0, le=1000000, decimal_places=6)
    disclosure_csv: str = Field(min_length=1, max_length=500000)
    records_csv: str = Field(min_length=1, max_length=500000)


def calculate(data):
    tables = []
    for text in (data.disclosure_csv, data.records_csv):
        entries = rows(text, ["code", "name", "quantity", "value"])
        if not entries:
            raise ValueError("双方至少各提供一条记录")
        for entry in entries:
            for key in ("quantity", "value"):
                try:
                    number = Decimal(entry[key])
                except InvalidOperation as exc:
                    raise ValueError("数量与市值必须为有效数字") from exc
                if not number.is_finite() or not 0 <= number <= Decimal("1e16"):
                    raise ValueError("数量与市值须为0至1e16的有限数字")
                if number.as_tuple().exponent < -6:
                    raise ValueError("数量与市值最多保留6位小数")
                entry[key] = number
        tables.append({entry["code"]: entry for entry in entries})
    disclosed, records = tables
    comparable = data.disclosure_date == data.records_date and data.same_basis
    details = []
    for code in sorted(disclosed.keys() | records.keys()):
        left, right = disclosed.get(code), records.get(code)
        issues = []
        dq = dv = None
        if not comparable:
            issues.append("口径或时点未对齐，暂不判断差异")
        elif left is None:
            issues.append("仅底层记录存在" if data.complete_scope else "披露范围未确认，待核对")
        elif right is None:
            issues.append("仅披露数据存在")
        else:
            dq, dv = left["quantity"] - right["quantity"], left["value"] - right["value"]
            if abs(dq) > data.quantity_tolerance:
                issues.append("数量差异")
            if abs(dv) > data.value_tolerance:
                issues.append("市值差异")
            if left["name"] != right["name"]:
                issues.append("名称差异")
        details.append(
            {
                "code": code,
                "disclosure": {k: str(v) for k, v in left.items()} if left else None,
                "records": {k: str(v) for k, v in right.items()} if right else None,
                "quantity_delta": str(dq) if dq is not None else None,
                "value_delta": str(dv) if dv is not None else None,
                "issues": issues,
            }
        )
    count = sum(bool(row["issues"]) for row in details)
    return {
        "engine": "disclosure-review-v1",
        "comparable": comparable,
        "status": "口径待对齐"
        if not comparable
        else "存在待核对项"
        if count
        else "所提供记录在容差内一致",
        "issue_count": count,
        "row_count": len(details),
        "rows": details,
        "notice": (
            "仅核验人工提取的结构化记录，不自动解析原文，不证明来源真实或披露完整，"
            "不作违规认定。差额为披露减底层；缺项不按零处理。"
        ),
    }


def connect():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, owner TEXT, body TEXT)")
    return con


@router.post("/reports")
def create_report(data: DisclosureInput, request: Request):
    owner = user(request)
    try:
        result = calculate(data)
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    report = {
        "id": uuid4().hex,
        "received_at": datetime.now(UTC).isoformat(),
        "input": data.model_dump(mode="json"),
        "result": result,
    }
    con = connect()
    try:
        with con:
            con.execute(
                "INSERT INTO reports VALUES(?,?,?)", (report["id"], owner, canonical(report))
            )
    finally:
        con.close()
    return report


@router.get("/reports")
def list_reports(request: Request):
    owner = user(request)
    con = connect()
    try:
        reports = [
            json.loads(r[0])
            for r in con.execute(
                "SELECT body FROM reports WHERE owner=? ORDER BY rowid DESC LIMIT 200", (owner,)
            )
        ]
    finally:
        con.close()
    return [
        {
            "id": r["id"],
            "received_at": r["received_at"],
            "fund_name": r["input"]["fund_name"],
            "as_of": r["input"]["disclosure_date"],
            "status": r["result"]["status"],
        }
        for r in reports
    ]


@router.get("/reports/{report_id}")
def read_report(report_id: str, request: Request):
    owner = user(request)
    con = connect()
    try:
        record = con.execute(
            "SELECT body FROM reports WHERE id=? AND owner=?", (report_id, owner)
        ).fetchone()
    finally:
        con.close()
    if record is None:
        raise HTTPException(404, "报告不存在")
    return json.loads(record[0])
