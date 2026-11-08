"""Import rejects archive structure before accessing application data."""
from contextlib import nullcontext
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

MEMBERS = {"manifest.json", "journal.json", "proof.r0", "market.json", "verify-proof-bundle.py", "README.txt"}
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/import-verified-proof.py"


@pytest.mark.parametrize("extra", ["../escape", "/absolute", "proof.r0", "nested/extra"])
def test_unsafe_or_duplicate_archive_member_is_rejected_without_data_writes(tmp_path, extra):
    archive = tmp_path / "invalid.zip"
    with ZipFile(archive, "w") as bundle:
        for name in MEMBERS:
            bundle.writestr(name, b"{}")
        with pytest.warns(UserWarning) if extra == "proof.r0" else nullcontext():
            bundle.writestr(extra, b"not imported")
    target = tmp_path / "app-data"
    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--bundle", str(archive), "--data-dir", str(target),
         "--expected-receipt-sha256", "00" * 32],
        capture_output=True, text=True,
    )
    assert process.returncode != 0
    assert "Unexpected bundle members" in process.stderr
    assert not target.exists()
    assert not (tmp_path / "escape").exists()


def test_compressed_oversize_archive_is_rejected_before_any_data_write(tmp_path):
    archive = tmp_path / "large.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for name in MEMBERS:
            bundle.writestr(name, bytes(25_000_001) if name == "proof.r0" else b"{}")
    assert archive.stat().st_size < 20_000_000
    target = tmp_path / "app-data"
    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--bundle", str(archive), "--data-dir", str(target),
         "--expected-receipt-sha256", "00" * 32],
        capture_output=True, text=True,
    )
    assert process.returncode != 0
    assert "Expanded bundle exceeds 25 MB" in process.stderr
    assert not target.exists()
