"""Existing receipt compatibility, in a disposable offline Linux test container."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys

ROOT = Path("/app")
sys.path.insert(0, str(ROOT / "backend"))
from fastapi.testclient import TestClient

raw = Path("/bundle/proof.r0").read_bytes()
before = hashlib.sha256(raw).hexdigest()
capture = io.StringIO()
sys.argv = ["import-verified-proof.py", "--bundle", "/bundle.zip", "--expected-receipt-sha256", before]
with contextlib.redirect_stdout(capture):
    runpy.run_path(str(ROOT / "scripts/import-verified-proof.py"), run_name="__main__")
from app.main import app, zk_proof_store
from app.zkp_bundle import export_bundle

proof = next(record for record in zk_proof_store.list_imported() if record["proof_hash"] == before)
client = TestClient(app)
response = client.post("/api/register", json={"email": "compat@isolated.example.test", "password": "isolated-compat-password"})
assert response.status_code == 201
response = client.post(f"/api/v1/quantjudge/zk-proofs/{proof['id']}/verify", json={})
assert response.status_code == 200, response.text
result = response.json()
assert result["valid"] is True
bundle_response = client.get(f"/api/v1/quantjudge/zk-proofs/{proof['id']}/bundle")
assert bundle_response.status_code == 200
Path("/output/compat-bundle.zip").write_bytes(bundle_response.content)

sys.path.insert(0, str(ROOT / "scripts"))
spec = runpy.run_path(str(ROOT / "scripts/verify-proof-bundle.py"))
offline = spec["verify_bundle"](Path("/bundle"), ROOT)
assert offline["valid"] is True
from zipfile import ZipFile
from pathlib import PurePosixPath
extracted = Path("/tmp/downloaded-bundle")
with ZipFile(io.BytesIO(bundle_response.content)) as archive:
    for member in archive.infolist():
        relative = PurePosixPath(member.filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unexpected archive path")
        destination = extracted / member.filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not member.is_dir():
            destination.write_bytes(archive.read(member))
assert spec["verify_bundle"](extracted, ROOT)["valid"] is True
from app.zkp import ZkProofError
path = zk_proof_store.receipt_path(proof["id"])
corrupt = bytearray(path.read_bytes()); corrupt[len(corrupt) // 2] ^= 1; path.write_bytes(corrupt)
refused = client.post(f"/api/v1/quantjudge/zk-proofs/{proof['id']}/verify", json={})
assert refused.status_code in {409, 422}
assert hashlib.sha256(Path("/bundle/proof.r0").read_bytes()).hexdigest() == before
summary = {"existing_v2_receipt_sha256": before, "online_verified": True, "offline_verified": True,
           "bundle_downloaded": True, "tamper_rejected": True, "source_sample_unchanged": True,
           "generated_proofs": 0}
Path("/output/compatibility.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary))
