import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

SOURCE = "https://bundle.assets.ricequant.com/bundles_v4/rqbundle_202611.tar.bz2"
MAX_FILES = 10_000
MAX_FILE_BYTES = 4 * 1024**3
MAX_TOTAL_BYTES = 8 * 1024**3


def prepare_bundle(
    archive_path, destination, manifest_path, *, expected_sha256=None, source_url=SOURCE,
):
    archive_path, destination, manifest_path = map(Path, (archive_path, destination, manifest_path))
    destination = destination.resolve(strict=True)
    if not destination.is_dir() or any(destination.iterdir()):
        raise ValueError("解包目标必须是新建的空目录")
    if manifest_path.exists() or manifest_path.resolve().is_relative_to(destination):
        raise ValueError("清单必须使用数据目录之外的新文件")
    source_pattern = (
        r"https://bundle\.assets\.ricequant\.com/bundles_v4/rqbundle_[0-9]{6}\.tar\.bz2"
    )
    if not re.fullmatch(source_pattern, source_url):
        raise ValueError("请指定官方 HTTPS 日线数据包地址")
    with archive_path.open("rb") as stream:
        archive_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected_sha256 is not None and (
        not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or expected_sha256 != archive_digest
    ):
        raise ValueError("归档 SHA-256 与指定摘要不符")
    seen, files, total = set(), [], 0
    with tarfile.open(archive_path, mode="r|bz2") as archive:
        for index, member in enumerate(archive):
            if index >= MAX_FILES:
                raise ValueError("归档条目过多")
            name = PurePosixPath(member.name)
            if not name.parts and member.isdir():
                continue
            if (not name.parts or name.is_absolute() or ".." in name.parts
                    or "\\" in member.name or ":" in member.name
                    or not (member.isdir() or member.isfile())):
                raise ValueError("归档含非法路径、链接或特殊文件")
            folded = name.as_posix().casefold()
            if folded in seen:
                raise ValueError("归档含重复或大小写冲突路径")
            seen.add(folded)
            target = destination.joinpath(*name.parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError("归档文件超出数据目录")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.size < 0 or member.size > MAX_FILE_BYTES:
                raise ValueError("归档单文件超过体积限制")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("归档解压体积超过限制")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("归档文件内容缺失")
            digest, written = hashlib.sha256(), 0
            with source, target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    written += len(chunk)
                    if written > member.size:
                        raise ValueError("归档文件超出声明体积")
                    digest.update(chunk)
                    output.write(chunk)
            if written != member.size:
                raise ValueError("归档文件被截断")
            target.chmod(0o444)
            files.append({"path": name.as_posix(), "bytes": written, "sha256": digest.hexdigest()})
    roots = list(destination.rglob("instruments.pk"))
    if len(roots) != 1 or not (roots[0].parent / "trading_dates.npy").is_file():
        raise ValueError("原生日线数据根目录缺失或不唯一")
    manifest = {
        "schema": "atlas.rqalpha.bundle-preparation/v1",
        "source_url": source_url,
        "source_kind": "official-free-daily-bundle",
        "usage": "academic-noncommercial-local-research",
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": archive_digest,
        "integrity_note": "本地摘要仅固定下载内容，未验证来源签名或 zkTLS 证明。",
        "bundle_root": roots[0].parent.relative_to(destination).as_posix(),
        "files": sorted(files, key=lambda row: row["path"]),
        "extracted_bytes": total,
    }
    for directory in sorted((p for p in destination.rglob("*") if p.is_dir()),
                            key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o555)
    destination.chmod(0o555)
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="安全准备官方公开日线包；不下载、不执行包内代码或读取 pickle",
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--source-url", default=SOURCE)
    args = parser.parse_args()
    manifest = prepare_bundle(args.archive, args.destination, args.manifest,
                              expected_sha256=args.expected_sha256, source_url=args.source_url)
    print(json.dumps({"files": len(manifest["files"]), "bytes": manifest["extracted_bytes"],
                      "archive_sha256": manifest["archive_sha256"]}))


if __name__ == "__main__":
    main()
