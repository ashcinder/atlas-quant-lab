"""Exercise real images, same-origin routing and persistence in a disposable project.

Requires a running Docker engine and network access for the image build.
Only the randomly named test project's containers/network/volume are removed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    project = f"atlas-smoke-{uuid4().hex[:12]}"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ,
        "ATLAS_HTTP_PORT": str(port),
        "QUANTJUDGE_SUPERVISOR_RPC_URL": "http://127.0.0.1:42515",
    }
    command = ["docker", "compose", "-f", str(REPO / "compose.yaml"), "-p", project]
    browser = build_opener(HTTPCookieProcessor(CookieJar()))

    def compose(*args: str, capture: bool = False, check: bool = True) -> str:
        result = subprocess.run(
            [*command, *args], cwd=REPO, env=environment,
            check=check, text=True, capture_output=capture, timeout=1200,
        )
        return result.stdout if capture else ""

    def request(path: str, payload: dict | None = None) -> tuple[bytes, str]:
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            f"http://127.0.0.1:{port}{path}", data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with browser.open(req, timeout=60) as response:
            return response.read(), response.headers.get("Content-Type", "")

    def api(path: str, payload: dict | None = None):
        body, content_type = request(path, payload)
        assert "application/json" in content_type, (path, content_type)
        return json.loads(body)

    config = json.loads(compose("config", "--format", "json", capture=True))
    assert "ports" not in config["services"]["api"]
    assert config["services"]["web"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert config["volumes"]["atlas-data"]["name"] == f"{project}_atlas-data"
    print(f"Building disposable project {project} on loopback port {port}", flush=True)
    try:
        compose("up", "--build", "--detach", "--wait", "--wait-timeout", "180")
        compose("exec", "-T", "web", "nginx", "-t")
        for service in ("api", "web"):
            assert compose("exec", "-T", service, "id", "-u", capture=True).strip() != "0"
        container = compose("ps", "-q", "api", capture=True).strip()
        inspection = json.loads(subprocess.check_output(
            ["docker", "inspect", container], text=True,
        ))[0]
        assert inspection["HostConfig"]["ReadonlyRootfs"] is True
        assert inspection["HostConfig"]["PortBindings"] in (None, {})
        runtime_command = inspection["Config"]["Cmd"]
        assert runtime_command[runtime_command.index("--workers") + 1] == "1"

        html, content_type = request("/")
        assert "text/html" in content_type
        asset = re.search(rb'<script[^>]+src="([^"]+)"', html)
        assert asset, "Built HTML must reference a JavaScript asset"
        assert request(asset[1].decode())[0], "Built JavaScript must be served"
        assert request("/strategy-lab")[0] == html, "SPA fallback must serve the app"
        assert request("/healthz")[0].strip() == b"ok"
        assert api("/api/v1/health")["status"] == "ok"
        assert "/api/v1/health" in api("/openapi.json")["paths"]
        assert b"/openapi.json" in request("/api/docs")[0]
        assert not api("/api/session")["authenticated"]
        api("/api/register", {"email": "container-fixture@example.test", "password": "disposable-fixture-password"})
        assert api("/api/session")["authenticated"]
        assert api("/api/ledger")["state"]["accounts"] == []
        try:
            request("/api/v1/this-route-does-not-exist")
            raise AssertionError("Unknown API routes must not return the SPA")
        except HTTPError as error:
            assert error.code == 404
            assert "application/json" in error.headers.get("Content-Type", "")

        profiles = api("/api/v1/quantjudge/zkp/profiles")
        assert profiles and all(profile["verifier_ready"] is False for profile in profiles)
        result = api("/api/v1/backtests", {
            "symbol": "BTC-USD", "asset_class": "crypto", "interval": "1d",
            "data_source": "demo", "strategy_id": "sma_cross",
            "params": {"fast": 12, "slow": 48}, "persist": True,
        })
        run_id = result["run_id"]
        assert api(f"/api/v1/runs/{run_id}")["run_id"] == run_id
        identity = api("/api/v1/quantjudge/overview")["attestation"]
        key_hash = compose("exec", "-T", "api", "python", "-c", (
            "import hashlib; from pathlib import Path; "
            "print(hashlib.sha256(Path('.data/quantjudge_package.key').read_bytes()).hexdigest())"
        ), capture=True)
        # Both containers are replaced, while their data volume is retained.
        compose("up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "180")
        assert api(f"/api/v1/runs/{run_id}")["run_id"] == run_id
        assert api("/api/v1/quantjudge/overview")["attestation"] == identity
        assert compose("exec", "-T", "api", "python", "-c", (
            "import hashlib; from pathlib import Path; "
            "print(hashlib.sha256(Path('.data/quantjudge_package.key').read_bytes()).hexdigest())"
        ), capture=True) == key_hash
        print("Container smoke passed: routes, nonroot, offline backtest, persistent DB and keys.")
    except BaseException:
        compose("ps", check=False)
        compose("logs", "--no-color", "--tail", "80", check=False)
        raise
    finally:
        # Config asserted this project's unique volume name before creating it.
        compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
