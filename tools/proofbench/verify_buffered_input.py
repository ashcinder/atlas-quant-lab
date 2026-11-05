#!/usr/bin/env python3
"""Analyze real SDK-serialized bytes; never produces a receipt or Proof marker."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import uuid

from run import witness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", default=["narrow", "buffered"])
    args = parser.parse_args()
    root, driver, output = args.experiment.resolve(), args.driver.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((root / "guest-manifest.json").read_text())
    results = []

    def execute(label, command, accepted=True):
        with urllib.request.urlopen("http://127.0.0.1:18095/api/v1/health", timeout=3) as response:
            if response.status != 200:
                raise RuntimeError("manual service health failed")
        folder = output / label
        folder.mkdir()
        (folder / "segments").mkdir()
        name = "atlas-input-check-" + uuid.uuid4().hex[:12]
        docker = ["docker", "run", "--pull", "never", "--name", name, "--network", "none",
                  "--cpus", "1", "--memory", "512m", "--memory-swap", "512m", "--pids-limit", "64",
                  "--mount", f"type=bind,src={driver},dst=/driver,readonly",
                  "--mount", f"type=bind,src={root},dst=/experiment,readonly",
                  "--mount", f"type=bind,src={output},dst=/checks", "--entrypoint", "/driver",
                  "atlas-proofbench-api:20261104-arm64", *command]
        try:
            process = subprocess.run(docker, capture_output=True, text=True, timeout=30)
            (folder / "stdout.json").write_text(process.stdout)
            (folder / "stderr.log").write_text(process.stderr)
            state = json.loads(subprocess.run(["docker", "inspect", "--format", "{{json .State}}", name],
                               capture_output=True, text=True, check=True, timeout=10).stdout)
            if state["OOMKilled"] or process.returncode == 137:
                raise RuntimeError("resource failure is not an input rejection")
            if accepted:
                process.check_returncode()
                value = json.loads(process.stdout)
                if value.get("execution_only") is not True or "valid" in value:
                    raise RuntimeError("analysis output must not mark a valid Proof")
            else:
                if process.returncode == 0 or process.stdout.strip() or "UnexpectedEnd" not in process.stderr:
                    raise RuntimeError("truncated input must fail deserialization, with no journal or Proof marker")
                value = None
            results.append({"case": label, "accepted": accepted, "exit_code": process.returncode})
            return value
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)

    for count in (3, 16, 32, 100, 500, 1000):
        path = output / f"witness-{count}.json"
        path.write_text(json.dumps(witness(count, "sma")))
        execute(f"encode-{count}", ["encode", f"/checks/{path.name}", f"/checks/input-{count}.bin"])
    for variant in args.variants:
        if variant not in manifest:
            raise ValueError("variant absent from pinned manifest: " + variant)
        guest = root / variant / ("guest-final.r0bf" if variant == "narrow" else "guest.r0bf")
        if hashlib.sha256(guest.read_bytes()).hexdigest() != (
                "3b8537429c2c584d6d1878224fc7b5912a736190489831bca3be4a0552bc2475"
                if variant == "narrow" else manifest[variant]["guest_sha256"]):
            raise RuntimeError("pinned guest bytes changed")
        image = manifest[variant]["image_id"]

        def analyze(label, raw, count=1000, accepted=True):
            return execute(label, ["analyze-raw", "/experiment/" + str(guest.relative_to(root)), image,
                f"/checks/witness-{count}.json", "18", f"/checks/{label}/segments", "/checks/" + raw], accepted)

        for count in (3, 16, 32, 100, 500, 1000):
            analyze(f"{variant}-full-{count}", f"input-{count}.bin", count)
        payload = (output / "input-1000.bin").read_bytes()
        for length in [len(payload)-i for i in (1, 2, 3, 4)] + [8191, 8192, 8193, 16383, 16384, 16385]:
            raw = f"truncated-{length}.bin"
            (output / raw).write_bytes(payload[:length])
            analyze(f"{variant}-truncated-{length}", raw, accepted=False)
        for length in (1, 3, 4):
            name = f"trailing-{length}.bin"
            (output / name).write_bytes(payload + b"\0" * length)
            analyze(f"{variant}-trailing-{length}", name)
    (output / "summary.json").write_text(json.dumps({"execution_only": True,
        "driver_sha256": hashlib.sha256(driver.read_bytes()).hexdigest(),
        "trailing_bytes_ignored_by_both_versions": True, "variants": args.variants,
        "cases": results}, indent=2))
    print(f"{len(results)} protocol checks passed; execution only", flush=True)


if __name__ == "__main__":
    main()
