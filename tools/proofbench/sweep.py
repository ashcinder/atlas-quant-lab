#!/usr/bin/env python3
"""Serial, bounded tuning and full-strategy scale checks after an initial proof.

Stops on environmental protection or any failed scale. Does not purchase,
deploy, pay, restart existing services, or automatically raise resource limits.
"""
import argparse
import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

from run import ROOT, docker, run


def validate(binary, image, platform, folder, backend_source=None):
    previous = folder / "validation"
    if previous.exists():
        previous.rename(folder / ("validation-previous-" + uuid.uuid4().hex[:8]))
    backend_mount = ROOT / "backend/app"
    backend_target = "/source/backend/app"
    if backend_source is not None:
        backend_mount = backend_source.resolve()
        assert json.loads((backend_mount / "experimental-schema.json").read_text())["experimental_only"] is True
        backend_target = "/source/backend"
    name = "atlas-proofbench-validate-" + uuid.uuid4().hex[:12]
    command = ("run", "--rm", "--pull", "never", "--name", name, "--platform", platform, "--network", "none", "--cpus", "1",
        "--memory", "1g", "--memory-swap", "1g", "--pids-limit", "128",
        "--mount", f"type=bind,source={backend_mount},target={backend_target},readonly",
        "--mount", f"type=bind,source={ROOT / 'scripts'},target=/source/scripts,readonly",
        "--mount", f"type=bind,source={ROOT / 'strategy/zkvm/profiles.json'},target=/source/strategy/zkvm/profiles.json,readonly",
        "--mount", f"type=bind,source={ROOT / 'strategy/zkvm/source-snapshots'},target=/source/strategy/zkvm/source-snapshots,readonly",
        "--mount", f"type=bind,source={ROOT / 'tools/proofbench'},target=/tools,readonly",
        "--mount", f"type=bind,source={binary},target=/candidate/atlas-zkvm,readonly",
        "--mount", f"type=bind,source={folder},target=/sample",
        "--entrypoint", "python", image, "/tools/validate.py")
    try:
        output = docker(*command, timeout=180)
    except subprocess.CalledProcessError as error:
        (folder / "validation-error.log").write_text(error.stderr)
        raise
    finally:
        # Never touch any application or other benchmark container.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
    print(output, flush=True)
    return json.loads((folder / "validation/result.json").read_text())


def main(a):
    a.binary, a.output = a.binary.resolve(), a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=a.resume)
    common = dict(binary=a.binary, image=a.image, platform=a.platform, health=a.health,
                  mode="prove", cpus=3, memory="5g", integrated=False, disk_segments=False)
    observations = json.loads((a.output / "observations.json").read_text()) if a.resume else []

    def sample(name, bars, program, po2, threads, timeout=1800, integrated=False):
        folder = a.output / name / str(bars)
        args = SimpleNamespace(**{**common, "memory": "6g" if integrated else "5g",
                                  "integrated": integrated}, program=program, po2=po2,
                               threads=threads, timeout=timeout)
        if a.resume and (folder / "result.json").exists():
            result = json.loads((folder / "result.json").read_text())
            if result.get("exit_code") != 0 or result.get("stop_reason") is not None:
                raise RuntimeError("refuse to repeat a failed sample on resume")
            ok = result.get("ordinary_api_slo_passed", True)
        else:
            ok = run(args, bars, folder)
            result = json.loads((folder / "result.json").read_text())
            observations.append({"name": name, **result})
        (a.output / "observations.json").write_text(json.dumps(observations, indent=2))
        if result.get("stop_reason") in {"vm_pressure", "manual_health", "container_lost"}:
            raise RuntimeError("environment protection; no further experiments")
        if ok:
            validate(a.binary, a.image, a.platform, folder)
            assert json.loads((folder / "stdout.json").read_text())["valid"] is True
        return ok, result

    candidates = []
    for po2, threads in [(18, 2), (18, 3), (19, 3)]:
        name = f"tune-p{po2}-t{threads}"
        ok, result = sample(name, 16, "zero", po2, threads, timeout=600)
        if ok and result.get("measurement_complete", True):
            candidates.append((result["elapsed_seconds"], po2, threads))
    if not candidates:
        raise RuntimeError("no candidate completed within the bounded tuning budget")
    _, po2, threads = min(candidates)
    selected = {"po2": po2, "threads": threads, "memory": "5g", "cpus": 3,
                "basis": "fastest validated 16-bar tuning sample; not a larger-scale guarantee"}
    (a.output / "selected.json").write_text(json.dumps(selected, indent=2))
    for program in ("sma", "state"):
        for bars in (16, 32, 100, 500):
            ok, _ = sample(program+"-scale", bars, program, po2, threads)
            if not ok:
                raise RuntimeError(f"{program} {bars} failed; scale series stopped")
        for repeat in (2, 3):
            ok, _ = sample(f"{program}-500-repeat-{repeat}", 500, program, po2, threads)
            if not ok:
                raise RuntimeError("500-bar repetition failed; stop acceptance")
    # Measure API competition only after representative standalone scale passes.
    ok, _ = sample("integrated-sma-500", 500, "sma", po2, threads, integrated=True)
    if not ok:
        raise RuntimeError("ordinary API SLO or proof failed")
    for program in ("sma", "state"):
        ok, _ = sample(program+"-1000", 1000, program, po2, threads, timeout=3600)
        if not ok:
            raise RuntimeError("1000-bar exploration stopped; keep lower-scale evidence")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="reverify completed samples; never repeat a failed proof")
    parser.add_argument("--image", default="atlas-proofbench-api:20261104-arm64")
    parser.add_argument("--platform", default="linux/arm64", choices=["linux/arm64", "linux/amd64"])
    parser.add_argument("--health", default="http://127.0.0.1:18095/api/v1/health")
    main(parser.parse_args())
