#!/usr/bin/env python3
"""Validate a real sample through isolated API/store and offline bundle paths.

Run in the release API image with /source (read-only checkout), /candidate
(candidate Linux binary) and /sample (one benchmark sample) mounted.
No application volume, network access, order or payment is used.
"""
from datetime import UTC, datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

os.environ["ATLAS_DATA_DIR"] = "/sample/validation-config"
sys.path.insert(0, "/source/backend")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.quantjudge import QuantJudgeStore, ReceiptAttestor
from app.quantjudge_models import QuantAgentCreate
from app.zkp import Risc0ReceiptVerifier, ZkProofStore, ZkProofError, MAX_RECEIPT_BYTES
from app.zkp_api import proof_inspection_router


sample = Path("/sample")
work = sample / "validation"
work.mkdir(exist_ok=False)
binary = Path("/candidate/atlas-zkvm")
witness = json.loads((sample / "witness.json").read_text())
profiles_path = Path("/source/strategy/zkvm/profiles.json")
registry = json.loads(profiles_path.read_text())
parameters = json.loads((sample / "parameters.json").read_text())
experimental = parameters.get("experimental_only", False)
profile_id = "atlas_program_backtest_risc0_v2"
if experimental:
    # A private test registry only: do not overwrite the production v2 entry.
    profile_id = "atlas_program_backtest_risc0_v3_experimental"
    registry["profiles"][profile_id] = dict(registry["profiles"]["atlas_program_backtest_risc0_v2"],
        image_id=parameters["guest_image_id"], guest_version="isolated-experiment")
    profiles_path = work / "experimental-profiles.json"
    profiles_path.write_text(json.dumps(registry, indent=2))
image = registry["profiles"][profile_id]["image_id"]


def invoke(*args, success=True):
    result = subprocess.run([str(binary), *map(str, args)], capture_output=True, text=True, timeout=45,
                            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "RISC0_DEV_MODE": "0"})
    assert (result.returncode == 0) is success, result.stderr[-1000:]
    return json.loads(result.stdout) if success else None


started = time.monotonic()
actual = invoke("verify", "--receipt", sample / "proof.r0", "--expected-image-id", image)
verify_seconds = time.monotonic() - started
statement = actual["journal"]
assert actual["valid"] is True
expected = invoke("inspect", "--profile", "atlas_program_backtest_risc0_v2" if experimental else statement["proof_profile"], "--witness", sample / "witness.json")
if experimental:
    assert statement["proof_profile"] == profile_id
    expected["proof_profile"] = profile_id
assert statement == expected
assert statement["decision_count"] == statement["metrics"]["observation_count"] == len(witness["market"]["bars"])
receipt = (sample / "proof.r0").read_bytes()
assert len(receipt) <= MAX_RECEIPT_BYTES, "receipt exceeds current API upload limit"

# A new private database only; no copied users, orders, chain or wallets.
database = work / "isolated.sqlite3"
quant = QuantJudgeStore(database, seed_demo=False)
created = quant.create_agent(QuantAgentCreate(
    name="Unpaid synthetic full execution benchmark", developer_alias="Isolated benchmark",
    category="timing", asset_classes=["crypto"], description="Synthetic execution proof only",
    strategy_commitment=statement["strategy_commitment"]))
with quant._connect() as connection:
    connection.execute("UPDATE qj_agents SET id=? WHERE id=?", (statement["agent_id"], created["agent"]["id"]))
store = ZkProofStore(database, receipt_root=work / "receipts", market_root=work / "markets",
                     verifier=Risc0ReceiptVerifier(binary), profiles_path=profiles_path)
store.register_market_dataset(witness["market"], fetched_at=datetime.now(UTC))
proof = store.register_receipt(statement["agent_id"], statement["proof_profile"], receipt, created["developer_token"])
quant.bind_proof_store(store)
report = quant.publish_zk_report(statement["agent_id"], proof["id"], created["developer_token"])
assert quant.verify_report(report["id"], refresh_chain=False)["external_proof_verified"] is True
app = FastAPI()
app.include_router(proof_inspection_router(store))
client = TestClient(app)
url = f"/api/v1/quantjudge/zk-proofs/{proof['id']}"
response = client.post(url + "/verify")
assert response.status_code == 200, response.text
assert response.json()["valid"] is True
bundle = client.get(url + "/bundle")
assert bundle.status_code == 200, bundle.text
(work / "bundle.zip").write_bytes(bundle.content)
folder = work / "bundle"
with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
    archive.extractall(folder)

# Trusted checkout view for the stock offline script, with candidate verifier.
repository = work / "trusted-checkout"
(repository / "strategy/zkvm/target/release").mkdir(parents=True)
(repository / "backend").symlink_to("/source/backend")
(repository / "strategy/zkvm/profiles.json").symlink_to(profiles_path)
(repository / "strategy/zkvm/target/release/atlas-zkvm").symlink_to(binary)
spec = importlib.util.spec_from_file_location("offline_verifier", "/source/scripts/verify-proof-bundle.py")
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)
assert offline.verify_bundle(folder, repository, statement["agent_id"])["valid"] is True

rejected = []
wrong_profiles = [(statement["proof_profile"], "duplicate_real_receipt"),
                  ("atlas_sma_backtest_risc0_v1", "wrong_registered_profile")]
if experimental:
    wrong_profiles.append(("atlas_program_backtest_risc0_v2", "production_v2_rejects_experimental_receipt"))
for profile, label in wrong_profiles:
    try:
        store.register_receipt(statement["agent_id"], profile, receipt, created["developer_token"])
    except ZkProofError:
        rejected.append(label)
    else:
        raise AssertionError("accepted " + label)
corrupt = bytearray(receipt)
corrupt[len(corrupt) // 2] ^= 1
(work / "corrupt.r0").write_bytes(corrupt)
invoke("verify", "--receipt", work / "corrupt.r0", "--expected-image-id", image, success=False)
rejected.append("cryptographic_receipt_bit_flip")
invoke("verify", "--receipt", sample / "proof.r0", "--expected-image-id", "00" * 32, success=False)
rejected.append("cryptographic_wrong_image_id")

# Stored journal and dataset tampering must fail the real online route.
with store._connect() as connection:
    row = connection.execute("SELECT public_statement_json FROM qj_zk_proofs WHERE id=?", (proof["id"],)).fetchone()
    changed = json.loads(row[0]); changed["final_equity_micros"] += 1
    connection.execute("UPDATE qj_zk_proofs SET public_statement_json=? WHERE id=?", (json.dumps(changed), proof["id"]))
assert client.post(url + "/verify").status_code == 409
rejected.append("online_changed_result")
with store._connect() as connection:
    connection.execute("UPDATE qj_zk_proofs SET public_statement_json=? WHERE id=?", (row[0], proof["id"]))
_, dataset_path = store.market_dataset(statement["market_data_hash"])
original_market = dataset_path.read_bytes()
changed = json.loads(original_market); changed["dataset"]["bars"][0]["close_micros"] += 1
dataset_path.write_text(json.dumps(changed))
assert client.post(url + "/verify").status_code == 409
rejected.append("online_changed_market")
dataset_path.write_bytes(original_market)
with store._connect() as connection:
    original_curve = connection.execute("SELECT curve_json FROM qj_reports WHERE id=?", (report["id"],)).fetchone()[0]
    connection.execute("UPDATE qj_reports SET curve_json='[]' WHERE id=?", (report["id"],))
assert client.post(url + "/verify").status_code == 409
rejected.append("online_changed_published_curve")
with store._connect() as connection:
    connection.execute("UPDATE qj_reports SET curve_json=? WHERE id=?", (original_curve, report["id"]))

for name, field in [("journal.json", "metrics"), ("market.json", "dataset"), ("manifest.json", "image_id")]:
    path = folder / name
    original = path.read_bytes(); changed = json.loads(original)
    if field == "metrics": changed[field]["total_return_ppm"] += 1
    elif field == "dataset": changed[field]["bars"].reverse()
    else: changed[field] = "00" * 32
    path.write_text(json.dumps(changed))
    try:
        offline.verify_bundle(folder, repository)
    except ValueError:
        rejected.append("offline_" + field)
    else:
        raise AssertionError("offline accepted " + field)
    finally:
        path.write_bytes(original)

result = {"valid": True, "full_journal_equals_native_inspect": True,
          "bars": len(witness["market"]["bars"]), "receipt_bytes": len(receipt),
          "cryptographic_verify_seconds": verify_seconds,
          "isolated_api_verify_seconds": response.json()["verification_seconds"],
          "offline_valid": True, "tamper_rejected": rejected,
          "published_report_verified": True,
          "market_origin_verified": False, "payment_or_order_created": False}
result.update(experimental_only=experimental, registered_profile=not experimental,
              isolated_schema_migration=Path("/source/backend/experimental-schema.json").exists(),
              current_service_updated=False)
(work / "result.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
