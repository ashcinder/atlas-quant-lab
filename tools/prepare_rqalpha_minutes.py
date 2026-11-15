import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import re
import stat
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

REPO_ID = "neigezhu/china-a-share-1min-ohlcv"
REVISION = "ba589a11534825044fe5a6b84838f50ba8d8d188"
SCHEMA = "atlas.rqalpha.minutes/v1"
LAST_COMPLETE_DAY = "2026-08-06"
DEFAULT_START = "2025-01-02"
INDUSTRIES = {"semiconductor", "defense", "space", "robotics"}
OPTIONAL_INDUSTRIES = {"strait"}
SYMBOL = re.compile(r"(?:6[0-9]{5}\.SS|[03][0-9]{5}\.SZ)")
DIGEST = re.compile(r"[a-f0-9]{64}")
CANONICAL = re.compile(r"data/stock_1m/(?:SH/6[0-9]{5}|SZ/[03][0-9]{5})\.parquet")
METADATA_FILES = (
    "README.md",
    "LICENSE",
    "metadata/source_provenance.json",
    "metadata/coverage_by_instrument.csv",
    "metadata/market_calendar.csv",
    "metadata/missing_intervals.csv",
    "metadata/no_bar_day_classification.csv",
    "metadata/summary.json",
)
CSV_FIELDS = ("datetime", "open", "high", "low", "close", "volume", "total_turnover")
RAW_FIELDS = (
    "symbol",
    "exchange",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
)
MAX_FILE_BYTES = 96 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 2 * 1024**3
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_MEMBERSHIP_BYTES = 2 * 1024 * 1024
MAX_MONTH_BYTES = 2 * 1024 * 1024
MAX_MONTH_ROWS = 8_000
MAX_PARQUET_ROWS = 5_000_000
MAX_ROW_GROUP_BYTES = 128 * 1024 * 1024
MAX_ROW_GROUPS = 256
NO_TRADE = {"confirmed_suspension", "zero_daily_no_trade"}
CONTINUOUS_LABELS = frozenset(
    [9 * 60 + 30 + offset for offset in range(1, 121)]
    + [13 * 60 + offset for offset in range(1, 121)]
)
EXTRA_LABELS = {9 * 60 + 30, 13 * 60}


def canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def iso_day(value):
    if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError("日期必须是 YYYY-MM-DD")
    return value


def relative_path(value):
    if not isinstance(value, str) or not value or any(c in value for c in "\\:,\n\r\0"):
        raise ValueError("非法数据路径")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("非法数据路径")
    return path


def regular_file(root, relative):
    relative = relative_path(relative)
    file = root
    for part in relative.parts:
        file /= part
        if file.is_symlink():
            raise ValueError("数据路径不能含符号链接")
    if not file.resolve(strict=True).is_relative_to(root) or not stat.S_ISREG(file.stat().st_mode):
        raise ValueError("数据路径不是范围内的普通文件")
    return file


def existing_directory(value, *, empty=False):
    path = Path(value)
    if path.is_symlink():
        raise ValueError("数据目录不能是符号链接")
    path = path.resolve(strict=True)
    if not path.is_dir() or empty and any(path.iterdir()):
        raise ValueError("目标必须是新建的空目录" if empty else "数据目录无效")
    return path


def read_json(path, limit):
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("清单必须是普通文件")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError("清单超过体积限制")
    return json.loads(
        body, parse_constant=lambda _: invalid_json(), object_pairs_hook=unique_object
    )


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 清单含重复字段")
        result[key] = value
    return result


def invalid_json():
    raise ValueError("JSON 不允许非有限数值")


def source_url(name):
    relative_path(name)
    if name not in METADATA_FILES and not CANONICAL.fullmatch(name):
        raise ValueError("只允许固定主数据和元数据路径，不能使用浏览样本")
    return f"https://huggingface.co/datasets/{REPO_ID}/resolve/{REVISION}/{name}"


def source_path(symbol):
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        raise ValueError("只接受带 .SS/.SZ 后缀的沪深股票")
    return f"data/stock_1m/{'SH' if symbol.endswith('.SS') else 'SZ'}/{symbol[:6]}.parquet"


def evidence_url(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("海峡研究池证据来源必须是无凭据 HTTPS 地址")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("海峡研究池证据来源必须是无凭据 HTTPS 地址")


def validate_strait_record(record):
    as_of = iso_day(record.get("as_of"))
    published = iso_day(record.get("published"))
    effective = iso_day(record.get("effective"))
    selected_on = iso_day(record.get("selected_on"))
    note = record.get("membership_note")
    evidence = record.get("member_evidence")
    if (record.get("scope") != "historical-theme-research-sample"
            or record.get("partial") is not True
            or published >= as_of or effective > as_of or selected_on < as_of
            or not isinstance(note, str) or not note.strip() or len(note) > 1000
            or not isinstance(evidence, dict) or set(evidence) != set(record["symbols"])):
        raise ValueError("海峡研究池范围、日期或逐股证据无效")
    evidence_url(record.get("source"))
    for item in evidence.values():
        if not isinstance(item, dict):
            raise TypeError("海峡研究池逐股证据无效")
        name = item.get("name")
        if (not isinstance(name, str) or not name.strip() or len(name) > 80
                or item.get("basis") not in {
                    "historical-concept-news", "annual-report-business-proxy",
                } or iso_day(item.get("published")) > published):
            raise ValueError("海峡研究池证据类型、名称或公开日期无效")
        evidence_url(item.get("source"))


def load_membership(path, symbols=None):
    manifest = read_json(path, MAX_MEMBERSHIP_BYTES)
    if not isinstance(manifest, dict):
        raise TypeError("行业/题材成员清单无效")
    identity = {key: value for key, value in manifest.items() if key != "digest"}
    if (
        manifest.get("schema") != "atlas.rqalpha.sectors/v1"
        or manifest.get("digest") != hashlib.sha256(canonical_bytes(identity)).hexdigest()
        or not isinstance(manifest.get("industries"), dict)
        or not INDUSTRIES <= set(manifest["industries"]) <= INDUSTRIES | OPTIONAL_INDUSTRIES
    ):
        raise ValueError("行业/题材成员清单或摘要无效")
    members = set()
    for industry, records in manifest["industries"].items():
        if not isinstance(records, list) or not records or len(records) > 500:
            raise ValueError("行业/题材成员版本无效")
        for record in records:
            pool = record.get("symbols") if isinstance(record, dict) else None
            if (
                not isinstance(pool, list)
                or not 1 <= len(pool) <= 150
                or any(not isinstance(s, str) or not SYMBOL.fullmatch(s) for s in pool)
                or len(set(pool)) != len(pool)
            ):
                raise ValueError("行业成员代码无效")
            if industry == "strait":
                validate_strait_record(record)
            members.update(pool)
    selected = sorted(members) if symbols is None else list(symbols)
    if (
        not 1 <= len(selected) <= 150
        or len(set(selected)) != len(selected)
        or any(not isinstance(s, str) or not SYMBOL.fullmatch(s) for s in selected)
        or not set(selected) <= members
    ):
        raise ValueError("只允许选择已配置行业/题材历史成员中不重复的 1–150 只股票")
    return manifest, sorted(selected)


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def freeze_directories(root):
    for directory in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    root.chmod(0o555)


def download_file(root, name, remaining):
    url = source_url(name)
    target = root / relative_path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Atlas-Academic-Minutes/1.0"})
    digest, written = hashlib.sha256(), 0
    file_limit = (
        min(MAX_FILE_BYTES, MAX_METADATA_BYTES) if name in METADATA_FILES else MAX_FILE_BYTES
    )
    with (
        urllib.request.urlopen(request, timeout=90) as response,
        target.open("xb") as output,
    ):
        if not response.geturl().startswith("https://"):
            raise ValueError("数据下载不能降级到非 HTTPS")
        while chunk := response.read(1024 * 1024):
            written += len(chunk)
            if written > file_limit or written > remaining:
                raise ValueError("数据下载超过单文件或批次体积限制")
            digest.update(chunk)
            output.write(chunk)
    if written == 0:
        raise ValueError("下载文件为空")
    target.chmod(0o444)
    return {"path": name, "url": url, "bytes": written, "sha256": digest.hexdigest()}


def download(destination, receipt_path, membership_path, *, symbols=None):
    root = existing_directory(destination, empty=True)
    receipt_path = Path(receipt_path)
    if receipt_path.exists() or receipt_path.resolve().is_relative_to(root):
        raise ValueError("下载凭据必须使用原始数据目录之外的新文件")
    _, selected = load_membership(membership_path, symbols)
    files, total = [], 0
    for name in METADATA_FILES:
        row = download_file(root, name, MAX_DOWNLOAD_BYTES - total)
        files.append(row)
        total += row["bytes"]
    inventory = read_inventory(root)
    for symbol in selected:
        if symbol not in inventory:
            raise ValueError(f"发布清单中没有 {symbol} 的主数据")
        row = download_file(root, source_path(symbol), MAX_DOWNLOAD_BYTES - total)
        files.append(row)
        total += row["bytes"]
    receipt = {
        "schema": "atlas.rqalpha.minute-download/v1",
        "repo_id": REPO_ID,
        "revision": REVISION,
        "files": files,
    }
    body = canonical_bytes(receipt)
    if len(body) + 1 > MAX_MANIFEST_BYTES:
        raise ValueError("下载凭据超过体积限制")
    with receipt_path.open("xb") as stream:
        stream.write(body + b"\n")
    receipt_path.chmod(0o444)
    freeze_directories(root)
    return receipt


def verify_receipt(root, receipt_path, selected):
    receipt = read_json(receipt_path, MAX_MANIFEST_BYTES)
    if (
        not isinstance(receipt, dict)
        or receipt.get("repo_id") != REPO_ID
        or receipt.get("revision") != REVISION
        or receipt.get("schema") not in (None, "atlas.rqalpha.minute-download/v1")
    ):
        raise ValueError("需要固定版本的下载凭据，准备过程不能自行补造")
    rows = receipt.get("files")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("下载文件清单无效")
    seen, total = {}, 0
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("下载文件条目无效")
        name = relative_path(row.get("path")).as_posix()
        expected_url = source_url(name)
        if (
            name.casefold() in seen
            or row.get("url") != expected_url
            or type(row.get("bytes")) is not int
            or not 0 < row["bytes"] <= MAX_FILE_BYTES
            or name in METADATA_FILES
            and row["bytes"] > MAX_METADATA_BYTES
            or not isinstance(row.get("sha256"), str)
            or not DIGEST.fullmatch(row["sha256"])
        ):
            raise ValueError("下载文件路径、来源或摘要无效")
        file = regular_file(root, name)
        total += row["bytes"]
        if total > MAX_DOWNLOAD_BYTES:
            raise ValueError("原始数据超过批次体积限制")
        if file.stat().st_size != row["bytes"] or file_digest(file) != row["sha256"]:
            raise ValueError("原始数据 SHA-256 或文件大小与下载凭据不符")
        seen[name.casefold()] = row
    actual = set()
    for file in root.rglob("*"):
        if file.is_symlink() or not (file.is_file() or file.is_dir()):
            raise ValueError("原始目录包含链接或特殊文件")
        if file.is_file():
            name = file.relative_to(root).as_posix().casefold()
            if name in actual:
                raise ValueError("原始目录存在大小写冲突文件")
            actual.add(name)
    if actual != set(seen):
        raise ValueError("原始目录文件集合与下载凭据不符")
    required = {*METADATA_FILES, *(source_path(s) for s in selected)}
    if not {name.casefold() for name in required} <= set(seen):
        raise ValueError("下载凭据缺少必要的主数据或元数据")
    return {row["path"]: row for row in seen.values()}


def csv_rows(root, name, required):
    file = regular_file(root, name)
    if file.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError("来源元数据超过体积限制")
    with file.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if (
            reader.fieldnames is None
            or len(reader.fieldnames) != len(set(reader.fieldnames))
            or not set(required) <= set(reader.fieldnames)
        ):
            raise ValueError("来源元数据字段无效")
        for index, row in enumerate(reader):
            if index >= 200_000 or None in row or any(value is None for value in row.values()):
                raise ValueError("来源元数据行数或格式无效")
            yield row


def read_inventory(root):
    inventory = {}
    for row in csv_rows(
        root,
        "metadata/coverage_by_instrument.csv",
        (
            "symbol",
            "exchange",
            "file",
            "records",
            "first_timestamp",
            "last_timestamp",
            "listing_date",
            "delisting_date",
        ),
    ):
        if row["exchange"] not in ("SH", "SZ", "BJ") or not re.fullmatch(
            r"[0-9]{6}", row["symbol"]
        ):
            raise ValueError("证券覆盖清单代码无效")
        if row["exchange"] == "BJ":
            continue
        symbol = row["symbol"] + (".SS" if row["exchange"] == "SH" else ".SZ")
        if not SYMBOL.fullmatch(symbol):
            continue
        if symbol in inventory or row["file"] != source_path(symbol):
            raise ValueError("证券覆盖清单重复或主数据路径无效")
        for field in ("listing_date", "delisting_date"):
            if row[field]:
                iso_day(row[field])
        first, last = (
            parse_source_timestamp(row["first_timestamp"]),
            parse_source_timestamp(row["last_timestamp"]),
        )
        if (
            first > last
            or not row["records"].isdigit()
            or not 1 <= int(row["records"]) <= MAX_PARQUET_ROWS
        ):
            raise ValueError("证券覆盖清单范围或记录数无效")
        inventory[symbol] = row
    return inventory


def parse_source_timestamp(value):
    if not isinstance(value, str):
        raise TypeError("来源时间戳无效")
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise ValueError("来源时间必须为 UTC+8 无时区整分钟标签")
    return parsed


def source_metadata(root):
    value = read_json(regular_file(root, "metadata/source_provenance.json"), MAX_METADATA_BYTES)
    required = {
        "dataset_schema_version": 1,
        "frequency": "1m",
        "timezone": "Asia/Singapore",
        "timestamp_storage": "timezone-naive",
        "price_adjustment": "none",
        "volume_unit": "shares",
        "turnover_unit": "CNY",
    }
    if not isinstance(value, dict) or any(
        type(value.get(k)) is not type(v) or value.get(k) != v for k, v in required.items()
    ):
        raise ValueError("来源时区、模式、频率或单位不符合固定分钟契约")
    readme = regular_file(root, "README.md").read_text(encoding="utf-8")
    license_text = regular_file(root, "LICENSE").read_text(encoding="utf-8")
    if (
        not re.search(r"(?m)^license: apache-2\.0\s*$", readme)
        or "Apache License" not in license_text
        or "Version 2.0" not in license_text
    ):
        raise ValueError("来源许可声明与固定快照不符")
    return value


def read_calendar(root, start, end):
    sessions, previous = [], ""
    for row in csv_rows(root, "metadata/market_calendar.csv", ("date", "is_trading_day")):
        day = iso_day(row["date"])
        if day <= previous or row["is_trading_day"] not in ("True", "False"):
            raise ValueError("来源交易日历重复、无序或布尔值无效")
        previous = day
        if start <= day <= end and row["is_trading_day"] == "True":
            sessions.append(day)
    if not sessions:
        raise ValueError("准备区间没有来源交易日历覆盖")
    return sessions


def read_no_bar_classification(root, selected, start, end):
    selected = set(selected)
    statuses = {symbol: {} for symbol in selected}
    for row in csv_rows(
        root,
        "metadata/no_bar_day_classification.csv",
        (
            "symbol",
            "exchange",
            "date",
            "classification",
            "evidence",
        ),
    ):
        suffix = ".SS" if row["exchange"] == "SH" else ".SZ" if row["exchange"] == "SZ" else ".BJ"
        symbol = row["symbol"] + suffix
        if symbol not in selected or not start <= row["date"] <= end:
            continue
        day = iso_day(row["date"])
        if day in statuses[symbol] or not row["classification"]:
            raise ValueError("缺日分类重复或为空")
        statuses[symbol][day] = row["classification"]
    return statuses


def validate_row(row, symbol, previous=None):
    if (
        not isinstance(row, dict)
        or set(row) != set(RAW_FIELDS)
        or row["symbol"] != symbol[:6]
        or row["exchange"] != ("SH" if symbol.endswith(".SS") else "SZ")
    ):
        raise ValueError("分钟行证券身份或字段无效")
    stamp = row["timestamp"]
    if (
        not isinstance(stamp, dt.datetime)
        or stamp.tzinfo is not None
        or stamp.second
        or stamp.microsecond
        or previous is not None
        and stamp <= previous
    ):
        raise ValueError("分钟标签重复、无序、带时区或不是整分钟")
    label = stamp.hour * 60 + stamp.minute
    if label not in CONTINUOUS_LABELS | EXTRA_LABELS:
        raise ValueError("分钟标签超出交易时段")
    prices = [row[field] for field in ("open", "high", "low", "close")]
    if (
        any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in prices
        )
        or row["low"] > min(row["open"], row["close"])
        or row["high"] < max(row["open"], row["close"])
        or type(row["volume"]) is not int
        or not 0 <= row["volume"] <= 10**13
        or type(row["turnover"]) not in (int, float)
        or not math.isfinite(row["turnover"])
        or not 0 <= row["turnover"] <= 10**16
    ):
        raise ValueError("分钟 OHLCV 含非法数值、价格边界或非整数股数")
    return (
        int(stamp.strftime("%Y%m%d%H%M%S")),
        *prices,
        row["volume"],
        row["turnover"],
    )


def audit_day(rows):
    if not rows:
        return False, "no-bars"
    labels = [((row[0] // 10000) % 100) * 60 + ((row[0] // 100) % 100) for row in rows]
    if len(set(labels)) != len(labels):
        raise ValueError("分钟标签重复")
    missing = CONTINUOUS_LABELS - set(labels)
    return (True, None) if not missing else (False, f"missing-continuous-minutes:{len(missing)}")


def read_parquet_rows(path, symbol, start, end, inventory):
    import pyarrow as pa
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    expected = (
        pa.string(),
        pa.string(),
        pa.timestamp("us"),
        pa.float64(),
        pa.float64(),
        pa.float64(),
        pa.float64(),
        pa.int64(),
        pa.float64(),
    )
    if (
        tuple(schema.names) != RAW_FIELDS
        or tuple(field.type for field in schema) != expected
        or (schema.metadata or {}).get(b"dataset_schema_version") != b"1"
    ):
        raise ValueError("Parquet 字段、数值类型、时区或模式版本无效")
    metadata = parquet.metadata
    if (
        metadata.num_rows != int(inventory["records"])
        or metadata.num_rows > MAX_PARQUET_ROWS
        or not 1 <= metadata.num_row_groups <= MAX_ROW_GROUPS
    ):
        raise ValueError("Parquet 记录数或分块数与来源清单不符")
    lower = dt.datetime.combine(dt.date.fromisoformat(start), dt.time())
    upper = dt.datetime.combine(dt.date.fromisoformat(end), dt.time(23, 59))
    groups, prior_max, source_first, source_last = [], None, None, None
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        if group.total_byte_size > MAX_ROW_GROUP_BYTES:
            raise ValueError("Parquet 分块解码体积超过限制")
        stats = group.column(2).statistics
        if stats is None or not stats.has_min_max or stats.null_count:
            raise ValueError("Parquet 缺少可审计的时间分块统计")
        first, last = stats.min, stats.max
        if (
            not isinstance(first, dt.datetime)
            or not isinstance(last, dt.datetime)
            or first.tzinfo is not None
            or last.tzinfo is not None
            or first > last
            or prior_max is not None
            and first <= prior_max
        ):
            raise ValueError("Parquet 时间分块重复、交叉或无序")
        source_first = first if source_first is None else source_first
        source_last, prior_max = last, last
        if last >= lower and first <= upper:
            groups.append(index)
    if source_first != parse_source_timestamp(
        inventory["first_timestamp"]
    ) or source_last != parse_source_timestamp(inventory["last_timestamp"]):
        raise ValueError("Parquet 真实时间范围与来源覆盖清单不符")
    previous = None
    for batch in parquet.iter_batches(batch_size=8192, row_groups=groups, use_threads=False):
        for row in batch.to_pylist():
            stamp = row["timestamp"]
            if (
                not isinstance(stamp, dt.datetime)
                or stamp.tzinfo is not None
                or previous is not None
                and stamp <= previous
            ):
                raise ValueError("Parquet 时间标签重复或无序")
            previous = stamp
            if lower <= stamp <= upper:
                yield row


def write_month(root, symbol, month, rows):
    if not rows or len(rows) > MAX_MONTH_ROWS:
        raise ValueError("单月分钟行数超过限制")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    writer.writerows(rows)
    encoded = stream.getvalue().encode("utf-8")
    if len(encoded) > MAX_MONTH_BYTES:
        raise ValueError("单月分钟解压体积超过限制")
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as zipped:
        zipped.write(encoded)
    body = output.getvalue()
    path = f"bars/{symbol}/{month}.csv.gz"
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as file:
        file.write(body)
    target.chmod(0o444)
    return {
        "path": path,
        "symbol": symbol,
        "month": month,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "rows": len(rows),
    }


def prepare_instrument(root, raw, symbol, sessions, start, end, inventory, statuses, receipt):
    listing, delisting = inventory["listing_date"], inventory["delisting_date"]
    if listing and delisting and listing > delisting:
        raise ValueError("证券上市退市区间无效")
    eligible = {
        day
        for day in sessions
        if (not listing or day >= listing) and (not delisting or day <= delisting)
    }
    session_set, days, months, files = set(sessions), {}, {}, []
    current_month, month_rows, previous, current_day, day_rows = (
        None,
        [],
        None,
        None,
        [],
    )
    for row in read_parquet_rows(
        regular_file(raw, source_path(symbol)), symbol, start, end, inventory
    ):
        normalized = validate_row(row, symbol, previous)
        previous = row["timestamp"]
        day, month = previous.date().isoformat(), previous.strftime("%Y-%m")
        if day not in session_set:
            raise ValueError("分钟记录不在来源交易日历中")
        if day not in eligible:
            continue
        if current_day is not None and day != current_day:
            days[current_day] = audit_day(day_rows)
            day_rows = []
        current_day = day
        day_rows.append(normalized)
        if current_month is not None and month != current_month:
            file = write_month(root, symbol, current_month, month_rows)
            files.append(file)
            months[current_month] = file["path"]
            month_rows = []
        current_month = month
        month_rows.append(normalized)
        if len(month_rows) > MAX_MONTH_ROWS:
            raise ValueError("单月分钟行数超过限制")
    if day_rows:
        days[current_day] = audit_day(day_rows)
    if month_rows:
        file = write_month(root, symbol, current_month, month_rows)
        files.append(file)
        months[current_month] = file["path"]
    complete, no_trade, gaps = [], {}, {}
    for day in sorted(eligible):
        observed = days.get(day)
        classification = statuses.get(day)
        if observed is not None:
            if classification is not None:
                raise ValueError("已观察分钟记录与无记录分类冲突")
            valid, reason = observed
            if valid:
                complete.append(day)
            else:
                gaps[day] = reason
        elif classification in NO_TRADE:
            no_trade[day] = classification
        else:
            gaps[day] = f"no-bars:{classification or 'unclassified'}"
    item = {
        "native_symbol": symbol[:6] + (".XSHG" if symbol.endswith(".SS") else ".XSHE"),
        "start": complete[0] if complete else None,
        "end": complete[-1] if complete else None,
        "complete_sessions": complete,
        "no_trade_sessions": no_trade,
        "gaps": gaps,
        "months": months,
        "source_path": source_path(symbol),
        "source_sha256": receipt["sha256"],
        "source_bytes": receipt["bytes"],
        "source_first": inventory["first_timestamp"],
        "source_last": inventory["last_timestamp"],
        "listing_date": listing or None,
        "delisting_date": delisting or None,
    }
    return item, files


def prepare(
    raw_directory,
    receipt_path,
    destination,
    membership_path,
    daily_digest,
    *,
    symbols=None,
    start=DEFAULT_START,
    end=LAST_COMPLETE_DAY,
):
    raw, root = (
        existing_directory(raw_directory),
        existing_directory(destination, empty=True),
    )
    if raw == root or raw.is_relative_to(root) or root.is_relative_to(raw):
        raise ValueError("原始数据与发布数据目录必须互相独立")
    iso_day(start)
    iso_day(end)
    if start > end or end > LAST_COMPLETE_DAY:
        raise ValueError("准备区间必须结束于 2026-08-06 或更早的完整日期")
    if not isinstance(daily_digest, str) or not DIGEST.fullmatch(daily_digest):
        raise ValueError("需要已冻结原生日线数据集的 SHA-256")
    membership, selected = load_membership(membership_path, symbols)
    receipts = verify_receipt(raw, receipt_path, selected)
    provenance = source_metadata(raw)
    inventory = read_inventory(raw)
    if any(symbol not in inventory for symbol in selected):
        raise ValueError("来源覆盖清单缺少所选股票")
    sessions = read_calendar(raw, start, end)
    if len(sessions) < 2:
        raise ValueError("准备区间至少需要两个真实交易日")
    statuses = read_no_bar_classification(raw, selected, start, end)
    files, instruments = [], {}
    for symbol in selected:
        item, chunks = prepare_instrument(
            root,
            raw,
            symbol,
            sessions,
            start,
            end,
            inventory[symbol],
            statuses[symbol],
            receipts[source_path(symbol)],
        )
        instruments[symbol] = item
        files.extend(chunks)
    if not files or len(files) > 5_000:
        raise ValueError("需要 1–5,000 个真实分钟文件才能发布快照")
    if verify_receipt(raw, receipt_path, selected) != receipts:
        raise ValueError("准备期间原始下载凭据已改变")
    manifest = {
        "schema": SCHEMA,
        "adapter_version": SCHEMA,
        "engine_version": "6.5.0",
        "usage": "academic-noncommercial-local-research",
        "daily_digest": daily_digest,
        "membership_sha256": membership["digest"],
        "start": sessions[0],
        "end": sessions[-1],
        "requested_window": {"start": start, "end": end},
        "sessions": sessions,
        "bar_convention": "end-label-session-local/v1",
        "extra_session_policy": "retained-for-cumulative-snapshot;excluded-from-continuous-bars-and-orders",
        "validation_scope": "normalized-date-range;raw-file-digests-and-parquet-range-statistics",
        "source": {
            "repo_id": REPO_ID,
            "revision": REVISION,
            "license_declared": "apache-2.0",
            "timezone": "Asia/Singapore",
            "timestamp_storage": "timezone-naive",
            "price_adjustment": "none",
            "volume_unit": "shares",
            "turnover_unit": "CNY",
            "last_complete_day": LAST_COMPLETE_DAY,
            "generated_at": provenance.get("generated_at"),
            "source_files": [
                {key: receipts[name][key] for key in ("path", "bytes", "sha256")}
                for name in METADATA_FILES
            ],
            "excluded_partial_day": "2026-08-07",
            "integrity_note": "发布者声明 Apache-2.0；未披露上游提供方。SHA-256只固定内容，不是来源签名、zkTLS或ZKP。",
        },
        "instruments": instruments,
        "files": files,
    }
    manifest["digest"] = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    body = canonical_bytes(manifest)
    if len(body) + 1 > MAX_MANIFEST_BYTES:
        raise ValueError("分钟索引超过 4 MiB 限制")
    with (root / "index.json").open("xb") as stream:
        stream.write(body + b"\n")
    (root / "index.json").chmod(0o444)
    freeze_directories(root)
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="固定 HF 行业/题材主数据下载与只读分钟快照准备；不执行数据集代码"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("download")
    get.add_argument("destination", type=Path)
    get.add_argument("receipt", type=Path)
    get.add_argument("--membership", type=Path, required=True)
    get.add_argument("--symbols", nargs="+")
    build = commands.add_parser("prepare")
    build.add_argument("raw", type=Path)
    build.add_argument("receipt", type=Path)
    build.add_argument("destination", type=Path)
    build.add_argument("--membership", type=Path, required=True)
    build.add_argument("--daily-digest", required=True)
    build.add_argument("--symbols", nargs="+")
    build.add_argument("--start", default=DEFAULT_START)
    build.add_argument("--end", default=LAST_COMPLETE_DAY)
    args = parser.parse_args()
    if args.command == "download":
        result = download(args.destination, args.receipt, args.membership, symbols=args.symbols)
        print(
            json.dumps(
                {
                    "repo_id": result["repo_id"],
                    "revision": result["revision"],
                    "files": len(result["files"]),
                    "bytes": sum(r["bytes"] for r in result["files"]),
                }
            )
        )
    else:
        result = prepare(
            args.raw,
            args.receipt,
            args.destination,
            args.membership,
            args.daily_digest,
            symbols=args.symbols,
            start=args.start,
            end=args.end,
        )
        print(
            json.dumps(
                {
                    "digest": result["digest"],
                    "instruments": len(result["instruments"]),
                    "files": len(result["files"]),
                    "sessions": len(result["sessions"]),
                    "gaps": sum(len(row["gaps"]) for row in result["instruments"].values()),
                }
            )
        )


if __name__ == "__main__":
    main()
