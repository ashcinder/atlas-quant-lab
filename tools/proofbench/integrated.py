#!/usr/bin/env python3
"""In-container API/prover competition check, using five new private users.

Used by run.py --integrated in a disposable 6-GiB container. No chain orders,
payments, live market requests or existing application volume are involved.
"""
import concurrent.futures
import importlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

import httpx

sample = Path("/sample")
assert os.environ["ATLAS_DATA_DIR"] == "/sample/application"
sys.path.insert(0, "/workspace/backend")
importlib.invalidate_caches()
from app.main import journal_store


def percentile(values, fraction=.95):
    values = sorted(values)
    position = (len(values)-1)*fraction
    lower = int(position)
    return values[lower] + (values[min(lower+1, len(values)-1)]-values[lower])*(position-lower)


def phase(clients, projects, seconds=None, process=None):
    results, lock = [], threading.Lock()
    started = time.monotonic()

    def worker(index):
        client, project = clients[index], projects[index]
        turn = 0
        while (time.monotonic()-started < seconds) if seconds is not None else process.poll() is None:
            write = turn % 5 == 4
            endpoint = ["/api/v1/strategy-projects", "/api/v1/runs", "/api/v1/trading/accounts", "/api/ledger"][turn % 4]
            point = time.monotonic()
            try:
                if write:
                    response = client.patch("/api/v1/strategy-projects/"+project["id"], json={
                        "expected_revision": project["revision"], "name": f"Benchmark {index} turn {turn}"})
                    if response.status_code == 200:
                        project.update(response.json())
                else:
                    response = client.get(endpoint)
                status = response.status_code
                ok = status == 200
                if ok:
                    value = response.json()
                    ok = isinstance(value, dict if write or endpoint == "/api/ledger" else list)
            except (httpx.HTTPError, ValueError):
                status, ok = None, False
            elapsed = time.monotonic()-point
            with lock:
                results.append({"user": index, "write": write, "status": status,
                                "seconds": elapsed, "valid": ok})
            turn += 1
            time.sleep(max(0, 2-elapsed))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(worker, range(5)))
    metrics = {"requests": len(results), "unexpected": sum(not r["valid"] and r["status"] != 429 for r in results),
               "status_429": sum(r["status"] == 429 for r in results), "elapsed_seconds": time.monotonic()-started}
    for kind in ("read", "write"):
        values = [r["seconds"] for r in results if r["write"] == (kind == "write")]
        metrics[kind+"_p95_seconds"] = percentile(values) if values else None
    return metrics, results


def main(command):
    # Check the actual API host before starting users, HTTP traffic or Proof.
    verifier = "/workspace/strategy/zkvm/target/release/atlas-zkvm"
    profile = "atlas_program_backtest_risc0_v2"
    expected = json.loads(Path("/workspace/strategy/zkvm/profiles.json").read_text())["profiles"][profile]
    checked = subprocess.run([verifier, "profile", "--profile", profile],
                             capture_output=True, text=True, check=True, timeout=30)
    actual = json.loads(checked.stdout)
    if actual.get("id") != profile or actual.get("image_id") != expected["image_id"]:
        raise RuntimeError("ordinary API verifier does not match its unchanged registry")
    (sample / "api-verifier-preflight.json").write_text(json.dumps(actual, indent=2))
    # Credentials exist only in memory and in this new isolated application's DB.
    accounts = []
    for i in range(5):
        email, password = f"proofbench-{i}@example.invalid", secrets.token_urlsafe(24)
        assert journal_store.create_user(email, password)
        accounts.append((email, password))
    log = (sample / "api.log").open("w")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                               "--port", "8000", "--workers", "1", "--no-access-log"],
                              cwd="/workspace/backend", stdout=log, stderr=log)
    clients = []
    proof = None
    try:
        for attempt in range(120):
            try:
                response = httpx.get("http://127.0.0.1:8000/api/v1/health", timeout=2)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError("isolated API did not start")
        projects = []
        for i, (email, password) in enumerate(accounts):
            client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=10, trust_env=False)
            clients.append(client)
            assert client.post("/api/login", json={"email": email, "password": password}).status_code == 200
            response = client.post("/api/v1/strategy-projects", json={"name": f"Benchmark {i}",
                "thesis": "Synthetic resource competition benchmark only", "asset_symbol": "BTC-USD",
                "asset_class": "crypto", "interval": "1d"})
            assert response.status_code == 201, response.text
            projects.append(response.json())
        baseline, baseline_requests = phase(clients, projects, seconds=60)
        with (sample / "baseline.json").open("w") as output:
            json.dump({"metrics": baseline, "requests": baseline_requests}, output, indent=2)
        assert baseline["unexpected"] == baseline["status_429"] == 0
        started = time.monotonic()
        with (sample / "stdout.json").open("w") as out, (sample / "stderr.log").open("w") as err:
            proof = subprocess.Popen(command, stdout=out, stderr=err)
            (sample / "proof-started.json").write_text(json.dumps({"started": True}))
            completion, timed_out = {}, threading.Event()

            def await_proof():
                completion["exit_code"] = proof.wait()
                completion["elapsed_seconds"] = time.monotonic()-started

            def expire_proof():
                if proof.poll() is None:
                    timed_out.set()
                    proof.kill()

            waiter = threading.Thread(target=await_proof)
            waiter.start()
            timer = threading.Timer(int(os.environ.get("ATLAS_BENCH_PROOF_TIMEOUT", "1800")), expire_proof)
            timer.start()
            try:
                competition, requests = phase(clients, projects, process=proof)
                waiter.join()
            finally:
                timer.cancel()
        limits = {kind: max(baseline[kind+"_p95_seconds"]*2, default) for kind, default in [("read",1), ("write",2)]}
        slo = (competition["unexpected"] == competition["status_429"] == 0 and all(
            competition[kind+"_p95_seconds"] is not None and competition[kind+"_p95_seconds"] <= limits[kind]
            for kind in limits))
        (sample / "competition.json").write_text(json.dumps({"metrics": competition, "requests": requests,
            "limits_seconds": limits, "slo_passed": slo, "shared_api_prover_cgroup": True,
            "proof_initiation": "direct local host; no paid job", "work_lease_emulated": False}, indent=2))
        return {**completion, "timed_out": timed_out.is_set(),
                "competition_elapsed_seconds": time.monotonic()-started,
                "ordinary_api_slo_passed": slo}
    finally:
        if proof is not None and proof.poll() is None:
            proof.kill(); proof.wait()
        for client in clients:
            client.close()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill(); server.wait()
        log.close()
