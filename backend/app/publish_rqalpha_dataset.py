import argparse
import hashlib
import json
from pathlib import Path

from app.compute_objects import canonical_bytes
from app.rqalpha_backtests import ENGINE_VERSION, MAX_MANIFEST_BYTES, _relative, runner_files
from app.sandbox import RqalphaSandbox


def publish(preparation_path, bundle_directory, output_path):
    root = Path(bundle_directory).resolve(strict=True)
    output = Path(output_path)
    if output.exists() or output.resolve().is_relative_to(root):
        raise ValueError("行情清单必须保存到数据目录之外的新文件")
    with Path(preparation_path).open("rb") as stream:
        body = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(body) > MAX_MANIFEST_BYTES:
        raise ValueError("数据准备清单超过大小限制")
    preparation = json.loads(body)
    if (preparation.get("schema") != "atlas.rqalpha.bundle-preparation/v1"
            or preparation.get("usage") != "academic-noncommercial-local-research"):
        raise ValueError("需要通过安全准备工具生成的学术日线清单")
    files = preparation["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 10_000:
        raise ValueError("数据文件清单无效")
    for row in files:
        relative = _relative(row["path"])
        file = root / relative
        if (file.is_symlink() or not file.resolve(strict=True).is_relative_to(root)
                or file.stat().st_size != row["bytes"]):
            raise ValueError("数据文件路径或大小与准备清单不符")
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != row["sha256"]:
            raise ValueError("数据文件摘要与准备清单不符")
    bundle = (root / _relative(preparation["bundle_root"])).resolve(strict=True)
    if not bundle.is_dir() or not bundle.is_relative_to(root):
        raise ValueError("数据根目录超出范围")
    with RqalphaSandbox(bundle) as runner:
        coverage = runner.run({
            "op": "inspect", "bundle_files": runner_files(preparation, root, bundle),
        })
    if (coverage.get("engine_version") != ENGINE_VERSION
            or not isinstance(coverage.get("sessions"), list)
            or not isinstance(coverage.get("instruments"), dict)):
        raise ValueError("RQAlpha 返回的日线覆盖无效")
    manifest = {key: preparation[key] for key in (
        "source_url", "source_kind", "usage", "archive_bytes", "archive_sha256",
        "integrity_note", "bundle_root", "files", "extracted_bytes",
    )} | {"schema": "atlas.rqalpha.dataset/v1", "engine_version": ENGINE_VERSION,
         "sessions": coverage["sessions"], "instruments": coverage["instruments"],
         "benchmarks": coverage.get("benchmarks", {})}
    digest = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    manifest["digest"] = digest
    encoded = canonical_bytes(manifest)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("行情覆盖清单超过 4 MiB")
    with output.open("xb") as stream:
        stream.write(encoded)
        stream.write(b"\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="在固定 gVisor 内检查原生包并发布私有日线清单")
    parser.add_argument("preparation", type=Path)
    parser.add_argument("bundle_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = publish(args.preparation, args.bundle_directory, args.output)
    print(json.dumps({"digest": manifest["digest"], "sessions": len(manifest["sessions"]),
                      "instruments": len(manifest["instruments"])}))


if __name__ == "__main__":
    main()
