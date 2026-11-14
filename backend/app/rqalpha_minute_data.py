import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

from app.compute_objects import canonical_bytes
from app.sandbox import RunnerFailure, RunnerUnavailable

SCHEMA = "atlas.rqalpha.minutes/v1"
REPO = "neigezhu/china-a-share-1min-ohlcv"
REVISION = "ba589a11534825044fe5a6b84838f50ba8d8d188"
LAST_COMPLETE_DAY = "2026-08-06"
BAR_CONVENTION = "end-label-session-local/v1"
EXTRA_SESSION_POLICY = "retained-for-cumulative-snapshot;excluded-from-continuous-bars-and-orders"
INTERVALS = ("1m", "5m", "15m", "30m", "60m")
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_CHUNK_BYTES = 2 * 1024 * 1024
MAX_SYMBOL_BARS = 5_000_000
DIGEST = re.compile(r"[0-9a-f]{64}")
SYMBOL = re.compile(r"(?:6[0-9]{5}\.SS|[03][0-9]{5}\.SZ)")
MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
MISSING = "HF 1分钟源已选定（优先2025年起），但尚未配置通过审计的冻结快照；不会回退日线或补造分钟"


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Invalid minute date")
    return value


def _days(values, allowed=None):
    if (not isinstance(values, list) or len(values) > 20_000
            or [_day(value) for value in values] != sorted(set(values))
            or allowed is not None and not set(values) <= allowed):
        raise ValueError("Invalid minute sessions")
    return set(values)


def _digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError("Invalid minute digest")
    return value


def _validate(value, root):
    if (not isinstance(value, dict) or value.get("schema") != SCHEMA
            or value.get("adapter_version") != SCHEMA or value.get("engine_version") != "6.5.0"
            or value.get("usage") != "academic-noncommercial-local-research"
            or value.get("bar_convention") != BAR_CONVENTION
            or value.get("extra_session_policy") != EXTRA_SESSION_POLICY):
        raise ValueError("Invalid minute identity")
    identity = {key: item for key, item in value.items() if key != "digest"}
    if _digest(value.get("digest")) != hashlib.sha256(canonical_bytes(identity)).hexdigest():
        raise ValueError("Minute manifest digest mismatch")
    _digest(value.get("daily_digest"))
    _digest(value.get("membership_sha256"))
    source = value["source"]
    expected = {"repo_id": REPO, "revision": REVISION, "timezone": "Asia/Singapore",
                "price_adjustment": "none", "volume_unit": "shares", "turnover_unit": "CNY",
                "last_complete_day": LAST_COMPLETE_DAY, "license_declared": "apache-2.0"}
    if (not isinstance(source, dict)
            or any(source.get(key) != item for key, item in expected.items())):
        raise ValueError("Unexpected minute source")
    sessions = _days(value["sessions"])
    if (len(sessions) < 2 or _day(value["start"]) > _day(value["end"])
            or value["end"] > LAST_COMPLETE_DAY
            or any(not value["start"] <= day <= value["end"] for day in sessions)):
        raise ValueError("Invalid minute preparation range")
    instruments, files = value["instruments"], value["files"]
    if (not isinstance(instruments, dict) or not 1 <= len(instruments) <= 150
            or not isinstance(files, list) or not 1 <= len(files) <= 5_000):
        raise ValueError("Invalid minute inventory")
    paths, rows_by_symbol = set(), {symbol: {} for symbol in instruments}
    for row in files:
        symbol, month, path = row["symbol"], row["month"], row["path"]
        if (symbol not in instruments or not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol)
                or not isinstance(month, str) or not MONTH.fullmatch(month)
                or path != f"bars/{symbol}/{month}.csv.gz" or path.casefold() in paths
                or type(row["bytes"]) is not int or not 1 <= row["bytes"] <= MAX_CHUNK_BYTES
                or type(row["rows"]) is not int or not 1 <= row["rows"] <= 8_000):
            raise ValueError("Invalid minute chunk")
        _digest(row["sha256"])
        paths.add(path.casefold())
        if month in rows_by_symbol[symbol]:
            raise ValueError("Duplicate minute month")
        rows_by_symbol[symbol][month] = path
        file = root / path
        if (file.is_symlink() or not file.resolve(strict=True).is_relative_to(root)
                or not file.is_file() or file.stat().st_size != row["bytes"]):
            raise ValueError("Minute file differs from manifest")
    for symbol, item in instruments.items():
        if (not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol)
                or not isinstance(item, dict)):
            raise ValueError("Invalid minute instrument")
        native = symbol[:6] + (".XSHG" if symbol.endswith(".SS") else ".XSHE")
        if item.get("native_symbol") != native or item.get("months") != rows_by_symbol[symbol]:
            raise ValueError("Invalid minute instrument mapping")
        covered = _days(item["complete_sessions"], sessions)
        no_trade, gaps = item["no_trade_sessions"], item["gaps"]
        if (not isinstance(no_trade, dict) or not isinstance(gaps, dict)
                or not set(no_trade) <= sessions or not set(gaps) <= sessions
                or any(kind not in ("confirmed_suspension", "zero_daily_no_trade")
                       for kind in no_trade.values())
                or any(not isinstance(reason, str) or not 1 <= len(reason) <= 500
                       for reason in gaps.values())
                or covered & set(no_trade) or covered & set(gaps) or set(no_trade) & set(gaps)):
            raise ValueError("Invalid minute quality classification")
        for day in (*no_trade, *gaps):
            _day(day)
        if covered:
            if (item["start"] != min(covered) or item["end"] != max(covered)
                    or any(day[:7] not in item["months"] for day in covered)):
                raise ValueError("Invalid complete minute range")
        elif item["start"] is not None or item["end"] is not None:
            raise ValueError("Minute range without complete sessions")
        _digest(item["source_sha256"])
        exchange = "SH" if symbol.endswith(".SS") else "SZ"
        if (item["source_path"] != f"data/stock_1m/{exchange}/{symbol[:6]}.parquet"
                or type(item["source_bytes"]) is not int or item["source_bytes"] <= 0):
            raise ValueError("Invalid raw minute provenance")
    actual = set()
    for file in root.rglob("*"):
        if file.is_symlink() or not (file.is_file() or file.is_dir()):
            raise ValueError("Unexpected minute filesystem entry")
        if file.is_file():
            relative = file.relative_to(root).as_posix().casefold()
            if relative in actual:
                raise ValueError("Case-colliding minute path")
            actual.add(relative)
    if actual != paths | {"index.json"}:
        raise ValueError("Minute file set differs from manifest")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate minute manifest field")
        result[key] = value
    return result


def load():
    location = os.environ.get("ATLAS_RQALPHA_MINUTE_DATASET", "")
    directory = os.environ.get("ATLAS_RQALPHA_MINUTE_DIR", "")
    if not location or not directory:
        raise RunnerUnavailable(MISSING)
    try:
        directory_path = Path(directory)
        root = directory_path.resolve(strict=True)
        index = root / "index.json"
        if (directory_path.is_symlink() or not root.is_dir()
                or index.is_symlink() or not index.is_file()
                or Path(location).is_symlink() or Path(location).resolve(strict=True) != index):
            raise ValueError("Invalid minute index location")
        with index.open("rb") as stream:
            body = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(body) > MAX_MANIFEST_BYTES:
            raise ValueError("Oversized minute index")
        value = json.loads(body, object_pairs_hook=_unique_object)
        _validate(value, root)
        return value, root
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        raise RunnerUnavailable("HF 分钟快照的版本、覆盖或文件完整性检查失败") from exc


def require_bindings(manifest, daily_digest, membership_digest):
    if manifest["daily_digest"] != daily_digest:
        raise RunnerFailure("分钟与原生日线规则快照不匹配，请重新准备配套数据")
    if manifest["membership_sha256"] != membership_digest:
        raise RunnerFailure("分钟与四行业成员版本不匹配，请重新检查数据覆盖")


def combined_digest(manifest):
    return hashlib.sha256(canonical_bytes({
        "schema": "atlas.rqalpha.minute-snapshot/v1",
        "daily_digest": manifest["daily_digest"], "minute_digest": manifest["digest"],
        "membership_sha256": manifest["membership_sha256"],
        "bar_convention": manifest["bar_convention"],
        "adapter_version": manifest["adapter_version"],
    })).hexdigest()


def verify_files(manifest, root, symbols, *, cancelled=None):
    selected = set(symbols)
    for row in manifest["files"]:
        if row["symbol"] not in selected:
            continue
        digest = hashlib.sha256()
        try:
            with (root / row["path"]).open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    if cancelled and cancelled():
                        raise RunnerFailure("RQAlpha 执行已取消")
                    digest.update(chunk)
        except OSError as exc:
            raise RunnerFailure("HF 冻结分钟文件无法读取") from exc
        if digest.hexdigest() != row["sha256"]:
            raise RunnerFailure("HF 冻结分钟文件 SHA-256 不符")
