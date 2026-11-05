#!/usr/bin/env python3
"""Pack isolated guests and compare full executions; never generates Proofs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import uuid

import run as runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--old-guest", type=Path, required=True)
    parser.add_argument("--image", default="atlas-proofbench-api:20261104-arm64")
    parser.add_argument("--variants", nargs="+", choices=["baseline", "sha", "optimized", "narrow", "buffered", "signed", "hashbatch", "hashfull", "hashwords", "hashlto", "hashinline", "hashinlinelto", "hashforceinline", "hashforcelto", "hashstack"],
                        default=["baseline", "sha", "optimized"])
    args = parser.parse_args()
    root = args.experiment.resolve()
    driver = args.driver.resolve()
    old_guest = args.old_guest.resolve()
    manifest_path = root / "guest-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for variant in args.variants:
        folder = root / variant
        if (folder / "guest.r0bf").exists():
            raise FileExistsError("do not overwrite a packaged candidate")
        name = "atlas-speed-pack-" + uuid.uuid4().hex[:12]
        command = ["docker", "run", "--rm", "--pull", "never", "--name", name,
            "--network", "none", "--cpus", "1", "--memory", "512m", "--memory-swap", "512m",
            "--mount", f"type=bind,src={driver},dst=/driver,readonly",
            "--mount", f"type=bind,src={old_guest},dst=/old.r0bf,readonly",
            "--mount", f"type=bind,src={folder},dst=/variant",
            "--entrypoint", "/driver", args.image,
            "pack", "/variant/user.elf", "/old.r0bf", "/variant/guest.r0bf"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            (folder / "pack.stderr.log").write_text(result.stderr)
            result.check_returncode()
            manifest[variant] = json.loads(result.stdout)
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
        manifest[variant]["guest_sha256"] = hashlib.sha256((folder / "guest.r0bf").read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    comparison = root / "comparison.json"
    results = json.loads(comparison.read_text()) if comparison.exists() else []
    for variant in args.variants:
        for program in ("zero", "sma", "state"):
            for count in (500, 1000):
                folder = root / "analyze" / variant / program / str(count)
                sample = SimpleNamespace(binary=driver, mode="analyze", program=program, po2=18,
                    disk_segments=True, integrated=False, cpus=3, threads=3, memory="5g",
                    platform="linux/arm64", timeout=120, image=args.image,
                    health="http://127.0.0.1:18095/api/v1/health",
                    experimental_guest=root / variant / "guest.r0bf",
                    experimental_image_id=manifest[variant]["image_id"])
                if not runner.run(sample, count, folder):
                    raise SystemExit("execution comparison stopped; inspect sample evidence")
                output = json.loads((folder / "stdout.json").read_text())
                measurement = json.loads((folder / "result.json").read_text())
                if output["execution_only"] is not True or "valid" in output:
                    raise ValueError("execution analysis must not mark a valid Proof")
                results.append(dict(variant=variant, program=program, bars=count,
                    image_id=output["image_id"], stats=output["stats"],
                    segments=len(output["segments"]), peak_bytes=measurement["peak_bytes"],
                    timings=output["timings"], execution_only=True))
                (root / "comparison.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
