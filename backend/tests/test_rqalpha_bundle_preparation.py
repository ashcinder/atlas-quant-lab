import hashlib
import json
import stat
import tarfile
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path

import pytest

SPEC = spec_from_file_location(
    "prepare_rqalpha_bundle",
    Path(__file__).resolve().parents[2] / "tools/prepare_rqalpha_bundle.py",
)
preparation = module_from_spec(SPEC)
SPEC.loader.exec_module(preparation)


def make_archive(root, entries):
    archive_path = root / "download.tar.bz2"
    with tarfile.open(archive_path, "w:bz2") as archive:
        for name, body, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = "../../escape"
            else:
                member.size = len(body)
            archive.addfile(member, BytesIO(body) if kind == tarfile.REGTYPE else None)
    destination, manifest = root / "data", root / "manifest.json"
    destination.mkdir()
    return archive_path, destination, manifest


def normal_files():
    return [("bundle/instruments.pk", b"opaque-data-not-loaded", tarfile.REGTYPE),
            ("bundle/trading_dates.npy", b"opaque-data-not-loaded", tarfile.REGTYPE)]


def test_prepares_read_only_native_files_without_deserialization(tmp_path):
    archive, destination, manifest_path = make_archive(tmp_path, normal_files())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = preparation.prepare_bundle(
        archive, destination, manifest_path, expected_sha256=checksum,
    )
    assert json.loads(manifest_path.read_text()) == manifest
    assert manifest["archive_sha256"] == checksum
    assert manifest["bundle_root"] == "bundle"
    assert manifest["extracted_bytes"] == 2 * len(b"opaque-data-not-loaded")
    assert len(manifest["files"]) == 2
    for item in manifest["files"]:
        file = destination / item["path"]
        assert hashlib.sha256(file.read_bytes()).hexdigest() == item["sha256"]
        assert not file.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    assert not destination.stat().st_mode & stat.S_IWUSR


@pytest.mark.parametrize("name,kind", [
    ("../../escape", tarfile.REGTYPE), ("/tmp/escape", tarfile.REGTYPE),
    ("bundle/../../escape", tarfile.REGTYPE), ("bundle\\escape", tarfile.REGTYPE),
    ("bundle/link", tarfile.SYMTYPE), ("bundle/hardlink", tarfile.LNKTYPE),
    ("bundle/fifo", tarfile.FIFOTYPE),
])
def test_rejects_unsafe_archive_members(tmp_path, name, kind):
    archive, destination, manifest = make_archive(tmp_path, [(name, b"x", kind)])
    with pytest.raises(ValueError, match="非法路径"):
        preparation.prepare_bundle(archive, destination, manifest)
    assert not manifest.exists()
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.parametrize("duplicate", ["bundle/instruments.pk", "BUNDLE/instruments.pk"])
def test_rejects_duplicate_paths_and_case_collisions(tmp_path, duplicate):
    entries = normal_files() + [(duplicate, b"x", tarfile.REGTYPE)]
    archive, destination, manifest = make_archive(tmp_path, entries)
    with pytest.raises(ValueError, match="冲突路径"):
        preparation.prepare_bundle(archive, destination, manifest)
    assert not manifest.exists()


def test_checksum_mismatch_does_not_extract(tmp_path):
    archive, destination, manifest = make_archive(tmp_path, normal_files())
    with pytest.raises(ValueError, match="SHA-256"):
        preparation.prepare_bundle(archive, destination, manifest, expected_sha256="0" * 64)
    assert not list(destination.iterdir())
    assert not manifest.exists()


def test_refuses_nonempty_destination_and_existing_manifest(tmp_path):
    archive, destination, manifest = make_archive(tmp_path, normal_files())
    existing = destination / "keep"
    existing.write_text("do not erase")
    with pytest.raises(ValueError, match="空目录"):
        preparation.prepare_bundle(archive, destination, manifest)
    assert existing.read_text() == "do not erase"
    existing.unlink()
    manifest.write_text("do not overwrite")
    with pytest.raises(ValueError, match="新文件"):
        preparation.prepare_bundle(archive, destination, manifest)
    assert manifest.read_text() == "do not overwrite"


def test_refuses_manifest_inside_native_bundle(tmp_path):
    archive, destination, _ = make_archive(tmp_path, normal_files())
    with pytest.raises(ValueError, match="数据目录之外"):
        preparation.prepare_bundle(archive, destination, destination / "manifest.json")


@pytest.mark.parametrize("option,limit,error", [
    ("MAX_FILES", 1, "条目过多"), ("MAX_FILE_BYTES", 1, "单文件"),
    ("MAX_TOTAL_BYTES", len(b"opaque-data-not-loaded"), "解压体积"),
])
def test_enforces_archive_budgets(tmp_path, monkeypatch, option, limit, error):
    archive, destination, manifest = make_archive(tmp_path, normal_files())
    monkeypatch.setattr(preparation, option, limit)
    with pytest.raises(ValueError, match=error):
        preparation.prepare_bundle(archive, destination, manifest)
    assert not manifest.exists()


def test_rejects_wrong_source_and_missing_bundle_root(tmp_path):
    archive, destination, manifest = make_archive(
        tmp_path, [("payload.txt", b"x", tarfile.REGTYPE)],
    )
    with pytest.raises(ValueError, match="HTTPS"):
        preparation.prepare_bundle(archive, destination, manifest, source_url="http://example.test/bundle")
    with pytest.raises(ValueError, match="根目录"):
        preparation.prepare_bundle(archive, destination, manifest)
    assert not manifest.exists()
