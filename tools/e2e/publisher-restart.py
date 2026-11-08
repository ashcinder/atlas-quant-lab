"""Observe a real publisher restart against a dedicated synthetic application volume."""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

from control import ROOT, call, inventory, paths

CONFIG = ROOT / "tools/e2e/online-market.json"


def inspect(target):
    return json.loads(call("docker", "inspect", target))[0]


def wait_cycle(container, started, symbols):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        events = []
        for line in call("docker", "logs", "--since", started, container).splitlines():
            if line.startswith("{"):
                events.append(json.loads(line))
        published = {row["symbol"]: row for row in events if row["status"] == "published"}
        if published.keys() == symbols:
            return published
        if not inspect(container)["State"]["Running"]:
            break
        time.sleep(2)
    raise RuntimeError(f"Publisher did not complete a successful cycle for {sorted(symbols)}")


def main(run_id):
    out, project = paths(run_id)
    run = json.loads((out / "run.json").read_text())
    api = inspect(project + "-api-1")
    volume = project + "_e2e-data"
    if (not run["synthetic_only"] or run["project"] != project or run["volume"] != volume
            or run["port"] == 18095 or "hour" in project
            or api["Config"]["Labels"].get("com.docker.compose.project") != project
            or "ATLAS_E2E_ISOLATED=1" not in api["Config"]["Env"]
            or api["Image"] != run["images"]["api"]
            or not any(m.get("Name") == volume and m["Destination"] == "/work" for m in api["Mounts"])):
        raise RuntimeError("A non-performance synthetic test project is required")
    name = project + "-publisher-restart"
    before = inventory()
    origin = run["origin"]
    queries = json.loads(CONFIG.read_text())
    symbols = {query["symbol"] for query in queries}
    client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    auth = json.dumps({"email": "author@e2e.example.test", "password": "Only-E2E-Fixture-2026!"}).encode()
    with client.open(Request(origin + "/api/login", data=auth, headers={
        "Content-Type": "application/json", "Origin": origin,
    }), timeout=8) as response:
        if response.status != 200:
            raise RuntimeError("Test account login failed")

    def snapshot():
        result = {}
        for row in queries:
            query = {key: value for key, value in row.items() if key != "base_currencies"}
            with client.open(origin + "/api/v1/market/manifest?" + urlencode(query), timeout=8) as response:
                manifest = json.load(response)
            with client.open(origin + manifest["chunks"][0]["url"], timeout=8) as response:
                chunk = hashlib.sha256(response.read()).hexdigest()
            if chunk != manifest["chunks"][0]["sha256"]:
                raise RuntimeError("Published market chunk hash differs from its manifest")
            if manifest["is_stale"] or manifest["source"].startswith(("synthetic", "demo")):
                raise RuntimeError("Publisher did not serve a fresh public source")
            result[row["symbol"]] = {"dataset_id": manifest["dataset_id"], "chunk_sha256": chunk,
                                     "source": manifest["source"], "count": manifest["count"]}
        return result

    # Use the isolated volume and exact pinned API image. Bridge egress is for
    # public providers; the publisher exposes no ports and joins no project network.
    created = call("docker", "run", "-d", "--name", name, "--platform", "linux/amd64",
                   "--read-only", "--init", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--cpus", "0.5", "--memory", "512m", "--memory-swap", "512m",
                   "--tmpfs", "/tmp:size=128m,mode=1777,nosuid",
                   "-e", "ATLAS_DATA_DIR=/work/data", "-e", "ATLAS_OBJECT_ROOT=/work/data/objects",
                   "-e", "OMP_NUM_THREADS=1", "-e", "OPENBLAS_NUM_THREADS=1",
                   "-v", volume + ":/work", "-v", str(CONFIG) + ":/publisher.json:ro",
                   "--entrypoint", "python", run["images"]["api"], "-m", "app.data.publish_market",
                   "--config", "/publisher.json", "--interval", "300").strip()
    try:
        first = inspect(created)["State"]["StartedAt"]
        published = wait_cycle(created, first, symbols)
        active = snapshot()
        if any(active[symbol]["dataset_id"] != published[symbol]["dataset_id"] for symbol in symbols):
            raise RuntimeError("API does not serve the version emitted by the publisher")
        if inspect(created)["State"]["OOMKilled"]:
            raise RuntimeError("Publisher was killed under its separate resource limit")
        call("docker", "stop", "--timeout", "2", created)
        if inspect(created)["State"]["Running"] or snapshot() != active:
            raise RuntimeError("Market data unavailable or changed while publisher was stopped")
        call("docker", "start", created)
        second = inspect(created)["State"]["StartedAt"]
        if first == second:
            raise RuntimeError("Publisher did not restart")
        republished = wait_cycle(created, second, symbols)
        recovered = snapshot()
        if any(recovered[symbol]["dataset_id"] != republished[symbol]["dataset_id"] for symbol in symbols):
            raise RuntimeError("API does not serve the restarted publisher's version")
        result = {"passed": True, "started_at": [first, second], "before": active, "after": recovered}
    finally:
        (out / "publisher-restart.log").write_text(call("docker", "logs", created))
        call("docker", "rm", "-f", created)
    if inventory() != before:
        raise RuntimeError("Protected service state changed")
    (out / "publisher-restart.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1])
