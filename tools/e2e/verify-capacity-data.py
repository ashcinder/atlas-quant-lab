"""Reconcile acknowledged results and ledger revisions on the isolated volume."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def inside():
    if os.environ.get("ATLAS_E2E_ISOLATED") != "1" or os.environ.get("ATLAS_DATA_DIR") != "/work/data":
        raise RuntimeError("Refusing a non-synthetic volume")
    sys.path.insert(0, "/app/backend")
    from app.compute_objects import ComputeObjects
    from app.config import DB_PATH

    expected = json.load(sys.stdin)
    objects = ComputeObjects()
    totals = Counter()
    with closing(sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        for user in expected:
            owner = user["owner"]
            artifacts = user["artifacts"]
            if artifacts:
                stored_ids = {row[0] for row in db.execute("SELECT id FROM backtest_runs WHERE owner_id=?", (owner,))}
                expected_ids = {artifact["run_id"] for artifact in artifacts}
                if stored_ids != expected_ids or len(expected_ids) != len(artifacts):
                    raise ValueError("Persisted run set differs from acknowledged runs")
            for artifact in artifacts:
                run_id = artifact["run_id"]
                mode, payload = db.execute(
                    "SELECT mode,result_json FROM backtest_runs WHERE id=? AND owner_id=? AND status='completed'",
                    (run_id, owner),
                ).fetchone()
                result = objects.read("private", json.loads(payload)["_object_sha256"])
                if result.get("run_id") != run_id or mode != user["group"]:
                    raise ValueError("Saved result ID or mode differs from acknowledgment")
                if mode == "research":
                    job_id = artifact["job_id"]
                    row = db.execute(
                        "SELECT result_json FROM research_jobs WHERE id=? AND owner_id=? AND status='completed'",
                        (job_id, owner),
                    ).fetchone()
                    if not row or json.loads(row[0])["_object_sha256"] != json.loads(payload)["_object_sha256"]:
                        raise ValueError("Research history binding differs from saved run")
                    if result.get("job_id") != job_id or result.get("tested_combinations") != 6:
                        raise ValueError("Research object differs from acknowledgment")
                totals[mode] += 1
            if (ledger := user["ledger"]) is not None:
                stored, revision = db.execute("SELECT data,revision FROM ledgers WHERE owner_id=?", (owner,)).fetchone()
                notes = [note for note in json.loads(stored)["journals"] if note["title"] == "Load bounded note"]
                if revision != ledger["revision"] or len(notes) != 1 or notes[0]["id"] != ledger["note_id"]:
                    raise ValueError("Final ledger revision or note identity differs from acknowledgment")
                if notes[0]["body"] != f"Synthetic bounded stability sample {ledger['sequence']}":
                    raise ValueError("Final ledger content differs from acknowledgment")
                totals["ledger"] += 1
    print(json.dumps({"passed": True, "verified": dict(totals)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("load_directory", type=Path)
    args = parser.parse_args()
    from control import call, paths

    run = json.loads((args.run_directory / "run.json").read_text())
    result = json.loads((args.load_directory / "result.json").read_text())
    fixture = json.loads((args.run_directory / "fixture.json").read_text())
    out, project = paths(run["run_id"])
    target = project + "-api-1"
    container = json.loads(call("docker", "inspect", target))[0]
    if (out.resolve() != args.run_directory.resolve() or not run["synthetic_only"] or not fixture["synthetic_only"]
            or run["project"] != project or not result["complete"] or result["run_id"] != run["run_id"]
            or run["images"] != result["images"] or container["Image"] != run["images"]["api"]
            or run["volume"] != project + "_e2e-data"
            or container["Config"]["Labels"].get("com.docker.compose.project") != project
            or not any(item.get("Name") == run["volume"] and item["Destination"] == "/work"
                       for item in container["Mounts"])):
        raise RuntimeError("Run evidence and synthetic volume do not match")
    users = [{
        "owner": fixture["accounts"][f"user{row['user']:02d}"]["id"], "group": row["group"],
        "artifacts": [], "ledger": None,
    } for row in result["groups"]]
    for operation in result["operations"]:
        if not operation["ok"]:
            continue
        group = operation["group"]
        user = users[operation["user"]]
        if group in {"single", "portfolio", "research"}:
            user["artifacts"].append(operation["persisted"])
        elif group == "ledger":
            user["ledger"] = operation["persisted"]
    evidence = {"run_id": run["run_id"], "images": run["images"], "source_fingerprint": result["source_fingerprint"]}
    process = subprocess.run(
        ["docker", "exec", "-i", target, "python", "/e2e/verify-capacity-data.py", "--inside"],
        input=json.dumps(users), capture_output=True, text=True,
    )
    if process.returncode:
        evidence.update(passed=False, reason=process.stderr.strip().splitlines()[-1] if process.stderr.strip() else "Audit exited")
    else:
        evidence.update(json.loads(process.stdout))
    (args.load_directory / "persistence-result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))
    raise SystemExit(0 if evidence["passed"] else 1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        inside()
    else:
        main()
