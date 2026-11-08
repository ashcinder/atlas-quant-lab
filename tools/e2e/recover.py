"""Observe closed browser sessions without renewing runtime demand."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from control import inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("load_directory", type=Path)
    parser.add_argument("--seconds", type=int, default=600)
    args = parser.parse_args()
    if args.seconds < 120:
        parser.error("At least 120 seconds of recovery observation is required")
    run = json.loads((args.run_directory / "run.json").read_text())
    load = json.loads((args.load_directory / "result.json").read_text())
    if (not run["synthetic_only"] or run["port"] == 18095 or not load["complete"]
            or load["run_id"] != run["run_id"] or load["images"] != run["images"]):
        raise RuntimeError("Recovery needs matching synthetic test evidence")
    protected = json.loads((args.run_directory / "protected-before.json").read_text())
    runtimes = load["runtime_before_close"]
    if not runtimes or len({item["id"] for item in runtimes}) != len(runtimes):
        raise RuntimeError("Runtime observations are missing or duplicated")

    clients = {}
    for item in runtimes:
        client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        body = json.dumps({
            "email": f"user{item['user']:02d}@e2e.example.test",
            "password": os.environ.get("ATLAS_E2E_PASSWORD", "Only-E2E-Fixture-2026!"),
        }).encode()
        with client.open(Request(run["origin"] + "/api/login", data=body, headers={
            "Content-Type": "application/json", "Origin": run["origin"],
        }), timeout=30):
            pass
        clients[item["id"]] = client

    started_at = time.time()
    started = time.monotonic()
    samples, errors = [], []
    expired = set()
    while True:
        elapsed = time.monotonic() - started
        for item in runtimes:
            identifier = item["id"]
            client = clients[identifier]
            url = run["origin"] + "/api/v1/trading/runs/" + identifier
            try:
                with client.open(url, timeout=15) as response:
                    current = json.load(response)
                snapshot = {
                    "fills": [fill["id"] for fill in current["fills"]],
                    "signals": [{key: signal[key] for key in ("id", "status")} for signal in current["signals"]],
                    "last_bar_time": current["last_bar_time"], "status": current["status"],
                }
                if any(snapshot[key] != item[key] for key in snapshot) or len(set(snapshot["fills"])) != len(snapshot["fills"]):
                    raise ValueError("Runtime advanced, changed state, or duplicated fills after page closure")
                if elapsed >= 50 and identifier not in expired:
                    try:
                        with client.open(Request(url + "/tick", data=b"{}", headers={
                            "Content-Type": "application/json", "Origin": run["origin"],
                        }), timeout=15):
                            raise ValueError("Expired demand accepted a tick")
                    except HTTPError as error:
                        if error.code != 409 or "租约已过期" not in error.read().decode():
                            raise
                    expired.add(identifier)
                samples.append({"elapsed_seconds": elapsed, "run_id": identifier, "unchanged": True})
            except (OSError, KeyError, TypeError, ValueError) as error:
                errors.append({"elapsed_seconds": elapsed, "run_id": identifier, "error": str(error)})
        if inventory() != protected:
            errors.append({"elapsed_seconds": elapsed, "error": "Protected five services changed"})
        (args.load_directory / "recovery-progress.json").write_text(json.dumps({
            "elapsed_seconds": elapsed, "errors": errors, "samples": len(samples),
        }, indent=2))
        if elapsed >= args.seconds:
            break
        time.sleep(min(10, max(0, args.seconds - (time.monotonic() - started))))

    elapsed = time.monotonic() - started
    result = {
        "schema": "atlas.e2e-recovery/v1", "run_id": run["run_id"], "images": run["images"],
        "source_fingerprint": load["source_fingerprint"], "started_at": started_at,
        "finished_at": time.time(), "elapsed_seconds": elapsed, "full_ten_minutes": elapsed >= 600,
        "closed_browser_runtime_unchanged": not errors, "expired_leases_rejected": len(expired) == len(clients),
        "runtime_instances": len(clients), "protected_services_unchanged": inventory() == protected,
        "errors": errors, "samples": samples,
    }
    result["diagnostic_pass"] = not errors and result["expired_leases_rejected"] and result["protected_services_unchanged"]
    result["passed"] = result["diagnostic_pass"] and result["full_ten_minutes"]
    (args.load_directory / "recovery-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}))
    raise SystemExit(0 if result["passed" if args.seconds >= 600 else "diagnostic_pass"] else 1)


if __name__ == "__main__":
    main()
