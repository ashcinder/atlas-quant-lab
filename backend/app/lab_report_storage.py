from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.rqalpha_reports import validate_logs

TABLES = ("trades", "positions", "accounts", "logs")
CHUNK_ROWS = 1000
CHINA = ZoneInfo("Asia/Shanghai")
SORT_FIELDS = ("time", "symbol", "quantity", "price", "fee", "market_value", "pnl", "equity")
LOG_LEVELS = ("INFO", "WARN", "DEBUG", "ERROR")
COLUMNS = {
    "trades": (
        ("time", "成交时间"),
        ("symbol", "合约代码"),
        ("name", "合约名称"),
        ("side", "买/卖"),
        ("position_effect", "开/平"),
        ("quantity", "成交量"),
        ("price", "成交价"),
        ("fee", "费用"),
        ("commission", "佣金"),
        ("tax", "税费"),
        ("order_id", "订单标识"),
        ("exec_id", "成交标识"),
    ),
    "positions": (
        ("time", "时间"),
        ("symbol", "合约代码"),
        ("name", "合约名称"),
        ("last_price", "最新价"),
        ("direction", "多/空"),
        ("quantity", "数量"),
        ("avg_price", "开仓均价"),
        ("market_value", "市值"),
        ("pnl", "持仓浮盈亏"),
        ("fee", "当日费用"),
        ("sellable", "可卖数量"),
        ("dividend_receivable", "应收分红"),
    ),
    "accounts": (
        ("time", "日期"),
        ("account_type", "账户类别"),
        ("cash", "可用资金"),
        ("equity", "总权益"),
        ("market_value", "市值"),
        ("margin", "保证金"),
        ("fee", "当日费用"),
        ("daily_pnl", "每日盈亏"),
        ("frozen_cash", "冻结资金"),
        ("dividend_receivable", "应收分红"),
        ("cash_liabilities", "现金负债"),
        ("cash_liabilities_interest", "负债利息"),
        ("pending_cash_flow", "待到账申赎"),
    ),
    "annual": (
        ("year", "年度"),
        ("start", "开始日期"),
        ("end", "结束日期"),
        ("partial", "不完整年度"),
        ("strategy", "策略收益率"),
        ("benchmark", "基准收益率"),
    ),
}


def _put_table(objects, table, rows, recorded=True):
    chunks = []
    for offset in range(0, len(rows), CHUNK_ROWS):
        chunk = rows[offset : offset + CHUNK_ROWS]
        digest = objects.put(
            "private",
            {
                "schema": "atlas.lab-report-table/v1",
                "table": table,
                "offset": offset,
                "rows": chunk,
            },
        )
        chunks.append({"digest": digest, "offset": offset, "count": len(chunk)})
    time_ordered = all(row.get("time") is not None for row in rows) and all(
        left["time"] <= right["time"] for left, right in zip(rows, rows[1:], strict=False)
    )
    return {
        "count": len(rows),
        "recorded": bool(recorded),
        "chunks": chunks,
        "time_ordered": time_ordered,
    }


def store_result(objects, result):
    if "report_rows" not in result:
        return objects.put("private", result)
    rows = result["report_rows"]
    tables = result["report"]["tables"]
    stored = {key: value for key, value in result.items() if key != "report_rows"}
    references = {}
    for table in TABLES:
        records = rows[table]
        metadata = tables[table]
        if metadata["count"] != len(records):
            raise ValueError("报告明细数量与汇总不一致")
        references[table] = _put_table(objects, table, records, metadata["recorded"])
    stored["_report_tables"] = references
    stored["trades_complete"] = len(rows["trades"]) <= CHUNK_ROWS
    stored["trades"] = rows["trades"] if stored["trades_complete"] else []
    return objects.put("private", stored)


def public_result(result):
    return {key: value for key, value in result.items() if key != "_report_tables"}


def _read_chunks(objects, table, metadata, start=0, stop=None):
    offset = 0
    for reference in metadata["chunks"]:
        if reference["offset"] != offset or reference["count"] < 1:
            raise ValueError("报告分块索引不一致")
        next_offset = offset + reference["count"]
        if next_offset > start and (stop is None or offset < stop):
            value = objects.read("private", reference["digest"])
            rows = value["rows"]
            if (
                value.get("schema") != "atlas.lab-report-table/v1"
                or value.get("table") != table
                or value.get("offset") != offset
                or len(rows) != reference["count"]
            ):
                raise ValueError("报告分块完整性检查失败")
            yield from rows[
                max(0, start - offset) : None if stop is None else max(0, stop - offset)
            ]
        offset = next_offset
    if offset != metadata["count"]:
        raise ValueError("报告分块数量不一致")


def table_metadata(result, table):
    if table in result.get("_report_tables", {}):
        return result["_report_tables"][table]
    if table == "trades" and isinstance(result.get("trades"), list):
        return {"count": len(result["trades"]), "recorded": True}
    return {"count": 0, "recorded": False}


def table_rows(objects, result, table):
    metadata = table_metadata(result, table)
    if "chunks" in metadata:
        return _read_chunks(objects, table, metadata)
    return iter(result.get("trades", []) if table == "trades" else [])


def diagnostic_report(count, truncated):
    return {
        "schema_version": "atlas.rqalpha.report/v1",
        "benchmark": None,
        "conventions": {"status": "仅保留本次任务诊断，未生成经济结果"},
        "metrics": [],
        "series": [],
        "annual_returns": [],
        "drawdown": None,
        "tables": {
            table: {"count": count if table == "logs" else 0, "recorded": table == "logs"}
            for table in TABLES
        },
        "logs_truncated": truncated,
        "performance": {"enabled": False},
    }


def store_diagnostics(objects, logs, truncated=False):
    records = validate_logs(logs, truncated=truncated)
    return objects.put(
        "private",
        {
            "report": diagnostic_report(len(records), truncated),
            "_report_tables": {"logs": _put_table(objects, "logs", records)},
        },
    )


def _timestamp_boundary(value, upper=False):
    if value is None:
        return None
    parsed = date.fromisoformat(str(value))
    if upper:
        if parsed == date.max:
            return datetime.combine(parsed, time(), CHINA).timestamp() + 86400
        parsed += timedelta(days=1)
    return datetime.combine(parsed, time(), CHINA).timestamp()


def select_rows(objects, result, table, query):
    start = _timestamp_boundary(query.get("start"))
    end = _timestamp_boundary(query.get("end"), upper=True)
    symbol, side = query.get("symbol"), query.get("side")
    levels = set(query.get("levels", "").split(",")) - {""}
    filtered = []
    for row in table_rows(objects, result, table):
        stamp = row.get("time")
        if start is not None and (stamp is None or stamp < start):
            continue
        if end is not None and (stamp is None or stamp >= end):
            continue
        if symbol and row.get("symbol") != symbol:
            continue
        if side and row.get("side") != side:
            continue
        if levels and row.get("level") not in levels:
            continue
        filtered.append(row)
    sort = query.get("sort", "time")
    if sort not in SORT_FIELDS:
        raise HTTPException(422, "报告排序字段不支持")
    present, missing = [], []
    for index, row in enumerate(filtered):
        value = row.get(sort)
        (missing if value is None else present).append((index, row))
    if sort == "time":
        present.sort(
            key=lambda item: (item[1][sort], item[1].get("sequence", item[0])),
            reverse=bool(query.get("descending")),
        )
        missing.sort(
            key=lambda item: item[1].get("sequence", item[0]),
            reverse=bool(query.get("descending")),
        )
    else:
        present.sort(key=lambda item: item[1][sort], reverse=bool(query.get("descending")))
    return [row for _, row in present] + [row for _, row in missing]


def page_rows(objects, result, table, query):
    metadata = table_metadata(result, table)
    offset, limit = query.get("offset", 0), query.get("limit", 100)
    unfiltered = not any(query.get(key) for key in ("start", "end", "symbol", "side", "levels"))
    if (
        "chunks" in metadata
        and metadata.get("time_ordered")
        and unfiltered
        and query.get("sort", "time") == "time"
        and not query.get("descending")
    ):
        page = list(_read_chunks(objects, table, metadata, offset, offset + limit))
        total = metadata["count"]
    else:
        rows = select_rows(objects, result, table, query)
        page, total = rows[offset : offset + limit], len(rows)
    return {
        "rows": page,
        "total": total,
        "unfiltered_total": metadata["count"],
        "offset": offset,
        "limit": limit,
        "recorded": metadata["recorded"],
        "logs_truncated": bool(result.get("report", {}).get("logs_truncated", False)),
    }


def format_time(value, *, day=False):
    if value is None:
        return ""
    return datetime.fromtimestamp(value, CHINA).strftime("%Y-%m-%d" if day else "%Y-%m-%d %H:%M:%S")


def _csv_value(key, value):
    if value is None:
        return ""
    if key in ("time", "start", "end"):
        return format_time(value, day=key != "time")
    if isinstance(value, str):
        if key == "side":
            value = {"buy": "买入", "sell": "卖出"}.get(value.lower(), value)
        elif key == "account_type":
            value = {"stock": "股票"}.get(value.lower(), value)
        elif key == "position_effect":
            value = {
                "open": "开",
                "close": "平",
                "close_today": "平今",
                "close_yesterday": "平昨",
            }.get(value.lower(), value)
        elif key == "direction":
            value = {"long": "多", "short": "空"}.get(value.lower(), value)
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
        if key in ("symbol", "order_id", "exec_id") and value.isdecimal() and value.startswith("0"):
            return "'" + value
    return value


def bounded_chunks(parts):
    limit = 64 * 1024
    buffer = bytearray()
    for text in parts:
        for start in range(0, len(text), limit // 4):
            data = text[start : start + limit // 4].encode("utf-8")
            offset = 0
            while offset < len(data):
                end = min(offset + limit - len(buffer), len(data))
                buffer.extend(data[offset:end])
                offset = end
                if len(buffer) == limit:
                    yield bytes(buffer)
                    buffer.clear()
    if buffer:
        yield bytes(buffer)


def csv_export(table, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    columns = COLUMNS[table]
    writer.writerow([title for _, title in columns])
    yield chr(0xFEFF) + stream.getvalue()
    stream.seek(0)
    stream.truncate(0)
    for row in rows:
        writer.writerow([_csv_value(key, row.get(key)) for key, _ in columns])
        yield stream.getvalue()
        stream.seek(0)
        stream.truncate(0)


def logs_export(rows):
    for row in rows:
        stamp = format_time(row.get("time")) or "时间未记录"
        line = f" [策略行 {row['line']}]" if row.get("line") else ""
        yield f"{stamp} {row['level']} {row['source']}{line} {row['message']}\n"


def snapshot_export(objects, payload, result):
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    public = public_result(result)
    public.pop("trades", None)
    public.pop("trades_complete", None)
    job = {**payload, "result": None}
    job.pop("report", None)
    yield "{"
    for key, value in job.items():
        if key == "result":
            continue
        yield json.dumps(key) + ":"
        yield from encoder.iterencode(value)
        yield ","
    yield '"result":{'
    for key, value in public.items():
        yield json.dumps(key) + ":"
        yield from encoder.iterencode(value)
        yield ","
    yield '"trades_complete":true,"trades":['
    for index, row in enumerate(table_rows(objects, result, "trades")):
        if index:
            yield ","
        yield from encoder.iterencode(row)
    yield '],"report_rows":{'
    recorded_tables = [table for table in TABLES if table_metadata(result, table)["recorded"]]
    for table_index, table in enumerate(recorded_tables):
        if table_index:
            yield ","
        yield json.dumps(table) + ":["
        for index, row in enumerate(table_rows(objects, result, table)):
            if index:
                yield ","
            yield from encoder.iterencode(row)
        yield "]"
    yield "}}}\n"
