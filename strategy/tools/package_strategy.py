#!/usr/bin/env python3
"""Build a deterministic .qstrategy archive from a strategy source directory."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ALLOWED = {".py", ".json", ".md", ".txt", ".toml", ".lock", ".csv"}


def build(source: Path, output: Path) -> None:
    manifest_path = source / "strategy.json"
    if not manifest_path.is_file():
        raise SystemExit("strategy.json is required at the package root")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("id", "name", "version", "language", "description"):
        if key not in manifest:
            raise SystemExit(f"strategy.json is missing {key}")
    files = sorted(path for path in source.rglob("*") if path.is_file() and ".git" not in path.parts)
    unsupported = [path for path in files if path.suffix.lower() not in ALLOWED]
    if unsupported:
        raise SystemExit(f"unsupported package files: {', '.join(str(path) for path in unsupported)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(f"built {output} ({len(files)} files)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args()
    destination = args.output or Path(".artifacts") / "strategies" / f"{args.source.name}.qstrategy"
    build(args.source.resolve(), destination.resolve())


if __name__ == "__main__":
    main()
