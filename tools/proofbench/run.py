#!/usr/bin/env python3
"""Bounded, unpaid full-guest experiments. Never mounts application data.

Runs one disposable, network-disabled container per sample. Stops the series
on any failed sample, timeout, sustained VM pressure, or failed manual health.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid


PROFILE = "atlas_program_backtest_risc0_v2"
ROOT = Path(__file__).resolve().parent.parent.parent
FINALIZE_GRACE_SECONDS = 15  # Inner subprocess/Timer still enforces the exact Proof deadline.


def docker(*args, timeout=20):
    return subprocess.run(["docker", *map(str, args)], capture_output=True,
                          text=True, timeout=timeout, check=True).stdout.strip()


def witness(count, program):
    workflow = b"ATLASWORKFLOW2:closed_market>private_program>long_only_cap_9500bps>affordable_next_open>audit>output"
    source = {"agent_id": "qja_synthetic", "workflow_commitment": hashlib.sha256(workflow).hexdigest(),
              "previous_receipt_hash": None, "strategy_salt": [0]*32, "nullifier_nonce": [0]*32,
              "initial_equity_micros": 10_000_000_000,
              "strategy": {"program": [{"const": 0}], "commission_bps": 10, "slippage_bps": 5},
              "market": {"source": "synthetic", "symbol": "TEST", "interval": "1d", "adjustment": "none", "bars": []}}
    bar = {"time": 1_700_000_000, "volume_micros": 1_000_000}
    for i in range(count):
        price = 100_000_000 + (i % 37 - 18) * 100_000 + i * 1_000
        source["market"]["bars"].append(dict(bar, time=bar["time"] + i * 86400,
            open_micros=price, close_micros=price + 10_000,
            high_micros=price + 1_000_000, low_micros=price - 1_000_000))
    if program == "sma":
        source["strategy"]["program"] = [
            "index", {"const": 20}, "lt", {"const": 0},
            {"sma": 5}, {"sma": 20}, "gt", {"const": 5000}, {"const": 0}, "select", "select"]
    elif program == "state":
        source["strategy"]["program"] = [
            {"load": 0}, {"const": 1}, "add", {"store": 0},
            {"load": 0}, {"const": 7}, "mod", {"const": 3}, "lt",
            {"const": 5000}, {"const": 0}, "select"]
    return source


def run(args, count, folder, witness_data=None):
    folder.mkdir(parents=True, exist_ok=False)
    data = witness(count, args.program) if witness_data is None else witness_data
    if len(data["market"]["bars"]) != count:
        raise ValueError("witness must contain the complete requested bar count")
    (folder / "witness.json").write_text(json.dumps(data))
    name = "atlas-proofbench-" + uuid.uuid4().hex[:12]
    command = ["/candidate/atlas-zkvm", args.mode, "--profile", PROFILE,
               "--witness", "/sample/witness.json", "--segment-limit-po2", str(args.po2)]
    if args.mode == "prove":
        command += ["--receipt", "/sample/proof.r0"]
    if args.disk_segments:
        (folder / "segments").mkdir(mode=0o700)
        command += ["--segment-path", "/sample/segments"]
    experimental_guest = getattr(args, "experimental_guest", None)
    verifier_binary = getattr(args, "verifier_binary", None)
    experimental_mounts = []
    if experimental_guest:
        if not args.disk_segments:
            raise ValueError("experimental guest requires disk segments")
        if args.integrated and (verifier_binary is None or not verifier_binary.is_file()):
            raise ValueError("experimental integration requires a separate standard verifier")
        if args.integrated and hashlib.sha256(verifier_binary.read_bytes()).digest() == hashlib.sha256(args.binary.read_bytes()).digest():
            raise ValueError("experimental driver cannot be the ordinary API verifier")
        command = ["/candidate/atlas-zkvm", args.mode, "/candidate/guest.r0bf",
                   args.experimental_image_id, "/sample/witness.json", str(args.po2), "/sample/segments"]
        if args.mode == "prove":
            command += ["/sample/proof.r0"]
        experimental_mounts = ["--mount", f"type=bind,source={experimental_guest},target=/candidate/guest.r0bf,readonly"]
        if args.integrated:
            experimental_mounts += ["--mount", f"type=bind,source={verifier_binary},target=/candidate/verifier,readonly"]
    # Keep the cgroup alive until peak memory and process output are collected.
    launcher = """import subprocess,json,time,pathlib,os
p=pathlib.Path('/sample'); start=time.monotonic()
with (p/'stdout.json').open('w') as out,(p/'stderr.log').open('w') as err:
 try:
  code=subprocess.run(COMMAND,stdout=out,stderr=err,timeout=TIMEOUT).returncode
 except subprocess.TimeoutExpired:
  code=124
(p/'process.json.tmp').write_text(json.dumps({'exit_code':code,'elapsed_seconds':time.monotonic()-start,'timed_out':code==124}))
os.replace(p/'process.json.tmp',p/'process.json')
time.sleep(30)
""".replace("COMMAND", repr(command)).replace("TIMEOUT", repr(args.timeout))
    if args.integrated:
        launcher = """import json,time,pathlib,shutil,sys,os
shutil.copytree('/source/backend/app','/workspace/backend/app')
shutil.copytree('/source/scripts','/workspace/scripts')
p=pathlib.Path('/workspace/strategy/zkvm/target/release');p.mkdir(parents=True)
(p/'atlas-zkvm').symlink_to(VERIFIER)
shutil.copy('/source/strategy/zkvm/profiles.json','/workspace/strategy/zkvm/profiles.json')
sys.path.insert(0,'/tools');from integrated import main
result=main(COMMAND)
pathlib.Path('/sample/process.json.tmp').write_text(json.dumps(result))
os.replace('/sample/process.json.tmp','/sample/process.json');time.sleep(30)
""".replace("COMMAND", repr(command)).replace("VERIFIER", repr(
            "/candidate/verifier" if experimental_guest else "/candidate/atlas-zkvm"))
    started = time.monotonic()
    samples, reason, pressure_since, memory_since, health_errors = [], None, None, None, 0
    created, proof_observed_at = False, None
    metadata = dict(bars=count, program=args.program, mode=args.mode, po2=args.po2,
                    cpus=args.cpus, threads=args.threads, memory=args.memory, platform=args.platform,
                    disk_segments=args.disk_segments,
                    integrated=args.integrated,
                    binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                    witness_sha256=hashlib.sha256((folder / "witness.json").read_bytes()).hexdigest(),
                    input_source="fixed_synthetic" if witness_data is None else "provided_fixture",
                    container=name, timeout=args.timeout, image=args.image)
    metadata["image_id"] = docker("image", "inspect", args.image, "--format", "{{.Id}}")
    if experimental_guest:
        metadata.update(experimental_only=True, registered_profile=False,
                        guest_sha256=hashlib.sha256(experimental_guest.read_bytes()).hexdigest(),
                        guest_image_id=args.experimental_image_id)
        if args.integrated:
            metadata.update(api_verifier_sha256=hashlib.sha256(verifier_binary.read_bytes()).hexdigest(),
                            api_verifier_preflight_required=True,
                            ordinary_api_profile_source="unchanged_canonical_registry")
    metadata["docker_host"] = json.loads(docker("info", "--format",
        '{"architecture":{{json .Architecture}},"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}'))
    architecture = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}.get(
        metadata["docker_host"]["architecture"])
    metadata["execution_architecture"] = ("native" if args.platform == "linux/" + architecture
        else "cross_architecture") if architecture else "unknown"
    (folder / "parameters.json").write_text(json.dumps(metadata, indent=2))
    profiling = ["-e", "RISC0_PPROF_OUT=/sample/profile.pb"] if args.mode == "analyze" else []
    if getattr(args, "profile_inline", False):
        if args.mode != "analyze":
            raise ValueError("inline profiling is execution analysis only")
        profiling += ["-e", "RISC0_PPROF_ENABLE_INLINE_FUNCTIONS=1"]
    integration_mounts = []
    if args.integrated:
        integration_mounts = ["--mount", f"type=bind,source={ROOT / 'backend/app'},target=/source/backend/app,readonly",
            "--mount", f"type=bind,source={ROOT / 'scripts'},target=/source/scripts,readonly",
            "--mount", f"type=bind,source={ROOT / 'strategy/zkvm/profiles.json'},target=/source/strategy/zkvm/profiles.json,readonly",
            "--mount", f"type=bind,source={Path(__file__).resolve().parent},target=/tools,readonly",
            "-e", "ATLAS_DATA_DIR=/sample/application", "-e", "PYTHONPATH=/workspace/backend",
            "-e", f"ATLAS_BENCH_PROOF_TIMEOUT={args.timeout}",
            "-e", "ATLAS_ALLOW_REGISTRATION=false"]
    try:
        docker("run", "-d", "--pull", "never", "--name", name, "--platform", args.platform,
               "--network", "none", "--cpus", args.cpus, "--memory", args.memory,
               "--memory-swap", args.memory, "--pids-limit", "128",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
               "--tmpfs", "/tmp:size=128m,mode=1777,noexec,nosuid",
               "--mount", f"type=bind,source={args.binary},target=/candidate/atlas-zkvm,readonly",
               "--mount", f"type=bind,source={folder},target=/sample",
               "-e", "RISC0_DEV_MODE=0", "-e", "RISC0_PROVER=local",
               "-e", f"RAYON_NUM_THREADS={args.threads}",
               *profiling,
               *experimental_mounts,
               *integration_mounts,
               "--entrypoint", "python", args.image, "-c", launcher)
        created = True
        while True:
            state = json.loads(docker("inspect", name))[0]["State"]
            if not state["Running"]:
                reason = "oom" if state["OOMKilled"] else "container_exit"
                break
            try:
                data = json.loads(docker("exec", name, "python", "-c",
                    "import json,pathlib; p=pathlib.Path('/sys/fs/cgroup'); "
                    "print(json.dumps({k:(p/k).read_text() for k in "
                    "['memory.current','memory.peak','memory.events','cpu.stat']} | "
                    "{'meminfo':pathlib.Path('/proc/meminfo').read_text(), "
                    "'temporary_bytes':sum(f.stat().st_size for d in ['/tmp','/sample/segments'] "
                    "for f in pathlib.Path(d).rglob('*') if f.is_file())}))"))
            except subprocess.CalledProcessError:
                reason = "container_lost"
                break
            mem = {line.split(':')[0]:int(line.split()[1])*1024
                   for line in data.pop("meminfo").splitlines() if line.split()[1].isdigit()}
            data["vm_used_fraction"] = 1 - mem["MemAvailable"] / mem["MemTotal"]
            data["elapsed_seconds"] = time.monotonic() - started
            try:
                with urllib.request.urlopen(args.health, timeout=4) as response:
                    if response.status != 200:
                        raise RuntimeError("health status")
                health_errors = 0
            except Exception:
                health_errors += 1
            data["health_errors"] = health_errors
            samples.append(data)
            (folder / "samples.json").write_text(json.dumps(samples, indent=2))
            now = time.monotonic()
            pressure_since = (pressure_since or now) if data["vm_used_fraction"] > .85 else None
            limit = int(args.memory[:-1]) * 1024**3
            memory_since = (memory_since or now) if int(data["memory.current"]) > limit * .95 else None
            events = dict(line.split() for line in data["memory.events"].splitlines())
            if state["OOMKilled"] or int(events.get("oom_kill", 0)) > 0:
                reason = "oom"
                break
            if pressure_since and now - pressure_since >= 10:
                reason = "vm_pressure"
                break
            if memory_since and now - memory_since >= 10:
                reason = "container_memory_pressure"
                break
            if health_errors >= 3:
                reason = "manual_health"
                break
            if (folder / "process.json").exists():
                process = json.loads((folder / "process.json").read_text())
                if process.get("timed_out") or process["elapsed_seconds"] > args.timeout:
                    reason = "timeout"
                break
            if args.integrated:
                if (folder / "proof-started.json").exists() and proof_observed_at is None:
                    proof_observed_at = time.monotonic()
                deadline_exceeded = ((time.monotonic() - proof_observed_at > args.timeout + FINALIZE_GRACE_SECONDS)
                    if proof_observed_at is not None else time.monotonic() - started > 180)
            else:
                deadline_exceeded = time.monotonic() - started > args.timeout + FINALIZE_GRACE_SECONDS
            if deadline_exceeded:
                reason = "timeout"
                break
            time.sleep(2)
    except BaseException:
        reason = "observer_interrupted"
        raise
    finally:
        if not created:
            (folder / "result.json").write_text(json.dumps({**metadata, "stop_reason": "container_not_created"}, indent=2))
        else:
            state = json.loads(docker("inspect", name))[0]["State"]
            final_peak = 0
            if state["Running"] and (folder / "process.json").exists():
                try:
                    # The child has exited; read the kernel peak once more so
                    # its final spike cannot fall between sampling and exit.
                    final = json.loads(docker("exec", name, "python", "-c",
                        "import json,pathlib; p=pathlib.Path('/sys/fs/cgroup'); "
                        "print(json.dumps({k:(p/k).read_text() for k in ['memory.peak','memory.events']}))"))
                    final_peak = int(final["memory.peak"])
                    events = dict(line.split() for line in final["memory.events"].splitlines())
                    if int(events.get("oom_kill", 0)) > 0:
                        reason = "oom"
                except (subprocess.SubprocessError, ValueError, KeyError):
                    reason = reason or "final_cgroup_unavailable"
            # Only stop/remove the unique container created by this invocation.
            if state["Running"]:
                docker("kill", name)
            metadata.update(stop_reason=reason, state_before_cleanup=state,
                            measurement_complete=reason not in {"observer_interrupted", "final_cgroup_unavailable"}
                                and (folder / "process.json").exists(),
                            elapsed_seconds=time.monotonic()-started,
                            peak_bytes=max(final_peak, max((int(s["memory.peak"]) for s in samples), default=0)),
                            final_cgroup_peak_bytes=final_peak)
            metadata["peak_measurement"] = "final_kernel_peak" if final_peak else "sampled_lower_bound"
            metadata["peak_temporary_bytes"] = max((s["temporary_bytes"] for s in samples), default=0)
            metadata["cpu_usage_usec"] = max((int(s["cpu.stat"].split("usage_usec ")[1].split()[0]) for s in samples), default=0)
            if (folder / "process.json").exists():
                metadata.update(json.loads((folder / "process.json").read_text()))
                if reason is None and metadata.get("exit_code") != 0:
                    reason = "proof_exit"
                if reason is None and metadata.get("ordinary_api_slo_passed") is False:
                    reason = "ordinary_api_slo"
                metadata["stop_reason"] = reason
            (folder / "result.json").write_text(json.dumps(metadata, indent=2))
            docker("rm", name)
    print(json.dumps(metadata), flush=True)
    return reason is None and metadata.get("exit_code") == 0 and metadata.get("ordinary_api_slo_passed", True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--bars", type=int, nargs="+", default=[16, 32, 100, 500, 1000])
    p.add_argument("--program", choices=["zero", "sma", "state"], default="zero")
    p.add_argument("--mode", choices=["analyze", "trace", "prove"], default="prove")
    p.add_argument("--po2", type=int, choices=range(16, 21), default=18)
    p.add_argument("--cpus", type=int, choices=range(1, 4), default=3)
    p.add_argument("--threads", type=int, choices=range(1, 4), default=1)
    p.add_argument("--disk-segments", action="store_true")
    p.add_argument("--experimental-guest", type=Path)
    p.add_argument("--experimental-image-id")
    p.add_argument("--verifier-binary", type=Path, help="standard verifier required for experimental API competition")
    p.add_argument("--profile-inline", action="store_true")
    p.add_argument("--integrated", action="store_true", help="API and prover share the same 6-GiB cgroup")
    p.add_argument("--memory", choices=["2g", "3g", "4g", "5g", "6g"], default="5g")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--image", default="atlas-quant-api:20261103-release-v1-amd64")
    p.add_argument("--platform", choices=["linux/amd64", "linux/arm64"], default="linux/amd64")
    p.add_argument("--health", default="http://127.0.0.1:18095/api/v1/health")
    a = p.parse_args()
    a.binary = a.binary.resolve()
    a.output = a.output.resolve()
    if a.mode == "trace" and not a.experimental_guest:
        p.error("trace mode requires the isolated experimental driver and guest")
    if a.profile_inline and a.mode != "analyze":
        p.error("--profile-inline requires --mode analyze")
    if a.experimental_guest:
        a.experimental_guest = a.experimental_guest.resolve()
        if not a.experimental_guest.is_file() or not a.experimental_image_id or len(a.experimental_image_id) != 64:
            p.error("experimental guest needs an existing R0BF and pinned 64-character image ID")
        if not a.disk_segments:
            p.error("experimental guest requires --disk-segments")
        if a.integrated:
            if a.verifier_binary is None or not a.verifier_binary.is_file():
                p.error("experimental integration requires --verifier-binary for the unchanged ordinary API")
            a.verifier_binary = a.verifier_binary.resolve()
    if a.integrated and (a.memory != "6g" or a.mode != "prove"):
        p.error("integrated runs require --memory 6g --mode prove")
    if not a.binary.is_file() or any(n < 3 or n > 1000 for n in a.bars) or a.timeout < 1:
        p.error("existing candidate binary, 3..1000 bars and positive timeout required")
    for n in a.bars:
        if not run(a, n, a.output / str(n)):
            raise SystemExit("series stopped; inspect result.json before another sample")
