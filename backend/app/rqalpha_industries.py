import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.compute_objects import canonical_bytes
from app.sandbox import RunnerFailure

INDUSTRIES = {
    "semiconductor": "半导体",
    "defense": "军工",
    "space": "商业航天",
    "robotics": "机器人",
}
MINUTE_INTERVALS = ("1m", "5m", "15m", "30m", "60m")
MINUTE_REQUIREMENT = (
    "已指定HF固定历史快照，优先2025年起、按各股实际完整日期开放；当前尚未准备通过验收的四行业1分钟数据"
)
MAX_MEMBERSHIP_BYTES = 2 * 1024 * 1024


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
            or set(manifest.get("industries", {})) != set(INDUSTRIES)
        ):
            raise ValueError("Invalid sector identity")
        for records in manifest["industries"].values():
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
                prior = as_of
        return manifest
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise RunnerFailure("四行业成员清单或来源摘要校验失败，请重新准备已核验的名单") from exc


def membership_at(manifest, industry, day):
    candidates = [
        record
        for record in manifest["industries"][industry]
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
        members, record = [], None
        if manifest:
            try:
                record = membership_at(manifest, industry, selected_day)
                members = record["symbols"]
            except RunnerFailure:
                pass
        symbols, covered = [], []
        for symbol in members:
            row = {"symbol": symbol, "name": None}
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
        result.append(
            {
                "id": industry,
                "name": name,
                "symbols": symbols,
                "as_of": selected_day,
                "membership_sha256": manifest["digest"] if manifest else None,
                "membership_note": (
                    "沿用已核验月度研究池（含ETF披露代理及历史指数名单），不代表完整行业成分；"
                    "按所选开始日期查看，分钟买入按当时已公开生效名单检查，退出持仓不受移出限制"
                ),
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
        raise RunnerFailure("四行业成员清单尚未准备，请先检查行业数据覆盖")
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
    }
