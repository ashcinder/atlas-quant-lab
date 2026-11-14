import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.compute_objects import canonical_bytes
from app.sandbox import RunnerFailure

INDUSTRIES = {
    "semiconductor": "半导体",
    "defense": "军工",
    "space": "商业航天",
    "robotics": "机器人",
    "strait": "海峡两岸（研究池）",
}
BASE_INDUSTRIES = frozenset(INDUSTRIES) - {"strait"}
RESEARCH_SCOPE = "historical-theme-research-sample"
EVIDENCE_BASES = {"historical-concept-news", "annual-report-business-proxy"}
MINUTE_INTERVALS = ("1m", "5m", "15m", "30m", "60m")
MINUTE_REQUIREMENT = (
    "已指定HF固定历史快照，优先2025年起、按各股实际完整日期开放；尚未准备通过验收的股票池1分钟数据"
)
MAX_MEMBERSHIP_BYTES = 2 * 1024 * 1024


def _https_source(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None)


def _validate_research_record(record):
    evidence = record.get("member_evidence")
    note = record.get("membership_note")
    for field in ("as_of", "published", "effective", "selected_on"):
        value = record.get(field)
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("Invalid research sample date")
    if (record.get("scope") != RESEARCH_SCOPE or record.get("partial") is not True
            or not isinstance(note, str) or not note.strip() or len(note) > 1000
            or not isinstance(evidence, dict) or set(evidence) != set(record["symbols"])
            or record["selected_on"] < record["as_of"]
            or record["published"] >= record["as_of"] or record["effective"] > record["as_of"]):
        raise ValueError("Invalid research sample identity")
    for item in evidence.values():
        if (not isinstance(item, dict) or item.get("basis") not in EVIDENCE_BASES
                or not isinstance(item.get("name"), str) or not item["name"].strip()
                or len(item["name"]) > 80 or not _https_source(item.get("source"))
                or not isinstance(item.get("published"), str)
                or date.fromisoformat(item["published"]).isoformat() != item["published"]
                or item["published"] > record["published"]):
            raise ValueError("Invalid research sample evidence")


def _research_metadata(record):
    return {"membership_scope": record["scope"], "membership_note": record["membership_note"],
            "membership_selected_on": record["selected_on"],
            "membership_evidence": record["member_evidence"]}


def load_membership():
    location = os.environ.get("ATLAS_RQALPHA_SECTOR_MEMBERSHIP", "")
    if not location:
        return None
    try:
        with Path(location).open("rb") as stream:
            body = stream.read(MAX_MEMBERSHIP_BYTES + 1)
        if len(body) > MAX_MEMBERSHIP_BYTES:
            raise ValueError("Membership manifest too large")
        manifest = json.loads(body)
        identity = {key: value for key, value in manifest.items() if key != "digest"}
        if (
            manifest.get("schema") != "atlas.rqalpha.sectors/v1"
            or manifest.get("digest") != hashlib.sha256(canonical_bytes(identity)).hexdigest()
            or not isinstance(manifest.get("industries"), dict)
            or not BASE_INDUSTRIES <= set(manifest["industries"]) <= set(INDUSTRIES)
        ):
            raise ValueError("Invalid sector identity")
        for industry, records in manifest["industries"].items():
            if not isinstance(records, list) or not 1 <= len(records) <= 500:
                raise ValueError("Invalid membership versions")
            prior = ""
            for record in records:
                published = date.fromisoformat(record["published"]).isoformat()
                effective = date.fromisoformat(record["effective"]).isoformat()
                as_of = date.fromisoformat(record["as_of"]).isoformat()
                if (
                    as_of < prior
                    or as_of < effective
                    or as_of < published
                    or not isinstance(record.get("source"), str)
                    or not record["source"].startswith("https://")
                    or not isinstance(record.get("symbols"), list)
                    or not 1 <= len(record["symbols"]) <= 150
                    or len(set(record["symbols"])) != len(record["symbols"])
                ):
                    raise ValueError("Invalid membership provenance")
                for symbol in record["symbols"]:
                    if not isinstance(symbol, str) or not re.fullmatch(
                        r"(?:6[0-9]{5}\.SS|[03][0-9]{5}\.SZ)", symbol,
                    ):
                        raise ValueError("Invalid member symbol")
                if industry == "strait":
                    if not _https_source(record["source"]):
                        raise ValueError("Invalid research sample source")
                    _validate_research_record(record)
                prior = as_of
        return manifest
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise RunnerFailure("股票池成员清单或来源摘要校验失败，请重新准备已核验的名单") from exc


def membership_at(manifest, industry, day):
    candidates = [
        record
        for record in manifest["industries"].get(industry, [])
        if record["published"] < day and record["effective"] <= day and record["as_of"] <= day
    ]
    if not candidates:
        raise RunnerFailure("所选日期之前没有已公开的行业成员名单")
    return candidates[-1]


def catalog(*, as_of=None, minute=None, minute_reason=None):
    manifest = load_membership()
    selected_day = as_of or (minute["start"] if minute else
                             datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    result = []
    for industry, name in INDUSTRIES.items():
        if industry == "strait" and (
            manifest is None or industry not in manifest["industries"] or minute is None
        ):
            continue
        members, record = [], None
        if manifest:
            try:
                record = membership_at(manifest, industry, selected_day)
                members = record["symbols"]
            except RunnerFailure:
                pass
        symbols, covered = [], []
        for symbol in members:
            evidence = record["member_evidence"].get(symbol) if industry == "strait" else None
            row = {"symbol": symbol, "name": evidence["name"] if evidence else None}
            if minute:
                item = minute["instruments"].get(symbol)
                ready = item is not None and len(item["complete_sessions"]) >= 2
                row.update(
                    minute_available=ready, start=item["start"] if item else None,
                    end=item["end"] if item else None,
                    missing_sessions=len(item["gaps"]) if item else None,
                    minute_reason=None if ready else "该股尚无至少两个完整交易日的冻结分钟行情",
                )
                if ready:
                    covered.append(item)
            symbols.append(row)
        if industry == "strait" and not covered:
            continue
        result.append(
            {
                "id": industry,
                "name": name,
                "symbols": symbols,
                "as_of": selected_day,
                "membership_sha256": manifest["digest"] if manifest else None,
                **(_research_metadata(record) if industry == "strait" and record else {}),
                **({"membership_note": (
                    "沿用已核验月度研究池（含ETF披露代理及历史指数名单），不代表完整行业成分；"
                    "按所选开始日期查看，分钟买入按当时已公开生效名单检查，退出持仓不受移出限制"
                )} if industry != "strait" else {}),
                "start": min(item["start"] for item in covered) if covered else None,
                "end": max(item["end"] for item in covered) if covered else None,
                "minute_intervals": list(MINUTE_INTERVALS) if covered else [],
                "minute_source": {
                    "repo_id": minute["source"]["repo_id"],
                    "revision": minute["source"]["revision"],
                    "last_complete_day": minute["source"]["last_complete_day"],
                } if minute else None,
                "coverage_note": (
                    "日期仅为成员可用范围的外边界，不表示各股逐日连续无缺口；以股票和区间预检为准。"
                    "HF快照不实时更新，2026-08-07为部分日，之后未覆盖。"
                ) if minute else None,
                "reason": (
                    None if covered else minute_reason or MINUTE_REQUIREMENT
                ) if members else "所选日期之前尚无可核验的行业成员名单；" + MINUTE_REQUIREMENT,
            }
        )
    return result


def validate_daily_selection(settings, sessions, *, manifest=None):
    if not settings.industry:
        return None
    manifest = manifest if manifest is not None else load_membership()
    if manifest is None:
        raise RunnerFailure("股票池成员清单尚未准备，请先检查数据覆盖")
    first = membership_at(manifest, settings.industry, sessions[0])
    if not set(settings.symbols) <= set(first["symbols"]):
        raise RunnerFailure(
            "股票池包含在回测开始时尚未公开纳入所选行业的证券，请核对名单与起始日期"
        )
    return {
        "industry": settings.industry,
        "membership_sha256": manifest["digest"],
        "as_of": first["as_of"],
        "published": first["published"],
        "effective": first["effective"],
        "selection_mode": "static-pool-from-start-of-run-membership",
        **(_research_metadata(first) if settings.industry == "strait" else {}),
    }
