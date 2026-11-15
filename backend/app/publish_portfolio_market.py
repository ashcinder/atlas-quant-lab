"""Publish one trusted A-share market manifest and its event JSONL.

Run as the operator, independently of the HTTP API. The producer is responsible
for exchange calendar, source, timestamp semantics and dated security rules.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import time


def publish_file(market, manifest_path, events_path, *, require_digest=False):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("行情清单须为 JSON 对象")
    expected = manifest.get("events_sha256")
    if require_digest and (not isinstance(expected, str) or len(expected) != 64):
        raise ValueError("连续发布清单须包含 events_sha256")
    with events_path.open("rb") as stream:
        if expected is not None:
            actual = sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                actual.update(block)
            if actual.hexdigest() != expected:
                raise ValueError("事件文件与清单摘要不一致")
            stream.seek(0)
        return market.publish(manifest, (json.loads(line) for line in stream if line.strip()))


def watch(market, directory, interval):
    """Consume completed, immutable producer batches. Keep prior snapshots on errors."""
    processed = set()
    while True:
        for path in sorted(directory.glob("*.manifest.json")):
            if path.name in processed:
                continue
            try:
                events = path.with_name(path.name.removesuffix(".manifest.json") + ".events.jsonl")
                identifier = publish_file(market, path, events, require_digest=True)
            except (ValueError, OSError) as exc:
                print(json.dumps({"status": "failed", "batch": path.name, "error": str(exc)},
                                 ensure_ascii=False), flush=True)
                continue
            processed.add(path.name)
            print(json.dumps({"status": "published", "batch": path.name, "dataset_sha256": identifier},
                             ensure_ascii=False), flush=True)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("events", type=Path, nargs="?")
    parser.add_argument("--watch", type=Path, help="持续发布经行情供应方写完的独立批次目录")
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    if not os.environ.get("ATLAS_DATA_DIR"):
        parser.error("请显式配置 ATLAS_DATA_DIR")
    if args.watch:
        if args.manifest or args.events or not args.watch.is_dir() or args.interval < 5:
            parser.error("--watch 需要已有目录和至少 5 秒的间隔，不能同时指定单次文件")
    elif not args.manifest or not args.events:
        parser.error("请指定单次发布的清单和事件文件，或使用 --watch")
    from app.compute_objects import ComputeObjects
    from app.lab_portfolio import LabPortfolioStore
    from app.lab_strategies import LabStrategyStore
    from types import SimpleNamespace

    store = LabPortfolioStore(LabStrategyStore(), None, SimpleNamespace(objects=ComputeObjects()))
    if args.watch:
        try:
            watch(store.market, args.watch, args.interval)
        except KeyboardInterrupt:
            return 130
    else:
        print(publish_file(store.market, args.manifest, args.events))


if __name__ == "__main__":
    raise SystemExit(main())
