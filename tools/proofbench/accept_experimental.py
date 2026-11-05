#!/usr/bin/env python3
"""Bounded representative acceptance for an isolated, already reviewed guest.

Reuses genuine initial SMA samples; never retries a failed Proof. Ordinary API
competition is the third SMA repeat. Whole-machine acceptance remains pending.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
import urllib.request

from run import docker, run, witness
from sweep import validate


def health_gate():
    for attempt in range(3):
        try:
            with urllib.request.urlopen("http://127.0.0.1:18095/api/v1/health", timeout=4) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        if attempt < 2:
            time.sleep(1)
    raise RuntimeError("manual service failed three validation health checks")


def api_evidence(folder, proof_seconds):
    names = ("baseline.json", "competition.json", "api-verifier-preflight.json")
    baseline, competition, preflight = [json.loads((folder / name).read_text()) for name in names]
    if (preflight.get("id") != "atlas_program_backtest_risc0_v2"
            or preflight.get("image_id") != "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4"):
        raise ValueError("ordinary API preflight does not match the original fixed profile")
    if competition.get("slo_passed") is not True or competition.get("shared_api_prover_cgroup") is not True:
        raise ValueError("shared API competition did not pass")
    for phase in (baseline, competition):
        rows, metrics = phase["requests"], phase["metrics"]
        if (not rows or metrics["requests"] != len(rows) or {r["user"] for r in rows} != set(range(5))
                or metrics["unexpected"] != 0 or metrics["status_429"] != 0
                or not math.isfinite(metrics["elapsed_seconds"])
                or any(r["valid"] is not True or r["status"] != 200 for r in rows)):
            raise ValueError("ordinary API request evidence is missing or failed")
        for kind in ("read", "write"):
            values = sorted(r["seconds"] for r in rows if r["write"] == (kind == "write"))
            if not values or any(not math.isfinite(v) or v < 0 for v in values):
                raise ValueError("ordinary API latency evidence is invalid")
            position = (len(values)-1)*.95
            lower = int(position)
            p95 = values[lower] + (values[min(lower+1, len(values)-1)]-values[lower])*(position-lower)
            if not math.isclose(p95, metrics[kind+"_p95_seconds"], abs_tol=1e-9):
                raise ValueError("API P95 summary differs from raw requests")
    if baseline["metrics"]["elapsed_seconds"] < 60 or competition["metrics"]["elapsed_seconds"] < proof_seconds-1:
        raise ValueError("ordinary API competition did not cover the Proof duration")
    for kind, default in (("read", 1), ("write", 2)):
        limit = max(baseline["metrics"][kind+"_p95_seconds"]*2, default)
        if competition["limits_seconds"][kind] != limit or competition["metrics"][kind+"_p95_seconds"] > limit:
            raise ValueError("ordinary API latency threshold failed")
    return {"baseline": baseline["metrics"], "competition": competition["metrics"],
            "evidence_sha256": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in names}}


def accept(args):
    experiment = args.experiment.resolve()
    source = args.initial_sma.resolve()
    output = args.output.resolve()
    manifest = json.loads((experiment / "guest-manifest.json").read_text())[args.variant]
    guest = experiment / args.variant / "guest.r0bf"
    driver = experiment / "candidate/atlas-experimental-proofbench"
    verifier = args.verifier.resolve()
    backend = experiment / "validation-source/backend"
    image = "atlas-proofbench-api:20261104-arm64"
    image_id = docker("image", "inspect", image, "--format", "{{.Id}}")
    host = json.loads(docker("info", "--format",
        '{"architecture":{{json .Architecture}},"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}'))
    if host["cpus"] < 3:
        raise ValueError("host has fewer than three available CPUs")
    if hashlib.sha256(guest.read_bytes()).hexdigest() != manifest["guest_sha256"]:
        raise ValueError("guest differs from the frozen candidate")
    driver_hash = hashlib.sha256(driver.read_bytes()).hexdigest()
    if any(name.startswith("atlas-proofbench-") for name in docker("ps", "--format", "{{.Names}}").splitlines()):
        raise RuntimeError("another benchmark container remains active")
    previous_arg = getattr(args, "resume_user_pause", None)
    if output.is_relative_to(source) or (previous_arg and output.is_relative_to(previous_arg.resolve())):
        raise ValueError("new output must be outside preserved sample directories")
    output.mkdir(parents=True, exist_ok=False)
    evidence = {"experimental_only": True, "image_id": manifest["image_id"], "variant": args.variant,
        "whole_machine_4cpu_8gib_verified": False, "explore_1000_requested": args.explore_1000,
        "standard_verifier_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
        "runtime_image_id": image_id, "docker_host": host,
        "samples": [], "status": "running"}

    plan = [("state", "state", count, False) for count in (16, 32, 100, 500)] + [
        ("sma-repeat-2", "sma", 500, False), ("state-repeat-2", "state", 500, False),
        ("sma-repeat-3-integrated", "sma", 500, True), ("state-repeat-3", "state", 500, False)]

    def save():
        (output / "acceptance.json").write_text(json.dumps(evidence, indent=2))

    def check_identity(result, program, count, integrated):
        if (result["guest_image_id"] != manifest["image_id"] or result["guest_sha256"] != manifest["guest_sha256"]
                or result["binary_sha256"] != driver_hash
                or result["program"] != program or result["bars"] != count
                or result["execution_architecture"] != "native" or result["mode"] != "prove"
                or result["cpus"] != 3 or result["threads"] != 3
                or result["memory"] != ("6g" if integrated else "5g")
                or result["integrated"] != integrated or not result["disk_segments"]
                or result["image"] != image or result["image_id"] != image_id or result["docker_host"] != host
                or result["po2"] != (18 if count <= 32 else 19)):
            raise ValueError("sample identity/configuration differs from the acceptance candidate")

    def verify_sample(folder, program, count, reused=False, integrated=False):
        result = json.loads((folder / "result.json").read_text())
        if (result.get("exit_code") != 0 or result.get("stop_reason") is not None
                or result.get("measurement_complete") is not True
                or result.get("final_cgroup_peak_bytes", 0) <= 0
                or not math.isfinite(result["elapsed_seconds"])
                or result.get("ordinary_api_slo_passed") is False
                or (integrated and result.get("ordinary_api_slo_passed") is not True)
                or result["elapsed_seconds"] > (3600 if count == 1000 else 1800)):
            raise RuntimeError("failed or incomplete sample; no automatic Proof retry")
        check_identity(result, program, count, integrated)
        if json.loads((folder / "witness.json").read_text()) != witness(count, program):
            raise ValueError("sample is not the complete fixed representative input")
        parameters = json.loads((folder / "parameters.json").read_text())
        for key in ("guest_image_id", "guest_sha256", "binary_sha256", "witness_sha256",
                    "program", "bars", "po2", "cpus", "threads", "memory", "integrated",
                    "image", "image_id", "docker_host", "execution_architecture"):
            if parameters.get(key) != result.get(key):
                raise ValueError("verification parameters differ from measured sample identity")
        if parameters["witness_sha256"] != hashlib.sha256((folder / "witness.json").read_bytes()).hexdigest():
            raise ValueError("measured witness bytes changed")
        ordinary_api = api_evidence(folder, result["elapsed_seconds"]) if integrated else None
        validation_folder = folder
        source_hashes = {}
        if reused:
            validation_folder = output / "reverified" / str(len(evidence["samples"]))
            validation_folder.mkdir(parents=True, exist_ok=False)
            for name in ("proof.r0", "witness.json", "parameters.json", "result.json"):
                source_hashes[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
                shutil.copyfile(folder / name, validation_folder / name)
                if hashlib.sha256((validation_folder / name).read_bytes()).hexdigest() != source_hashes[name]:
                    raise ValueError("sample changed during reverification copy")
        health_gate()
        validated = validate(verifier, image, "linux/arm64", validation_folder, backend)
        health_gate()
        if validated.get("valid") is not True or validated.get("bars") != count:
            raise RuntimeError("full validation failed")
        if any(hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest
               for name, digest in source_hashes.items()):
            raise ValueError("original sample changed during reverification")
        evidence["samples"].append({"folder": str(folder), "program": program, "bars": count,
            "reused": reused, "integrated": result["integrated"],
            "ordinary_api": ordinary_api,
            "validation_folder": str(validation_folder), "source_sha256": source_hashes,
            "elapsed_seconds": result["elapsed_seconds"], "peak_bytes": result["peak_bytes"]})
        save()

    def sample(label, program, count, integrated=False):
        folder = output / label / str(count)
        settings = SimpleNamespace(binary=driver, experimental_guest=guest,
            experimental_image_id=manifest["image_id"], verifier_binary=verifier,
            mode="prove", program=program, po2=18 if count <= 32 else 19,
            disk_segments=True, integrated=integrated, cpus=3, threads=3,
            memory="6g" if integrated else "5g", platform="linux/arm64", image=image,
            timeout=3600 if count == 1000 else 1800, health="http://127.0.0.1:18095/api/v1/health")
        print("START", label, count, flush=True)
        if not run(settings, count, folder):
            raise RuntimeError("sample failed/protected; series stopped without retry")
        verify_sample(folder, program, count, integrated=integrated)
        print("VALIDATED", label, count, flush=True)

    save()
    try:
        recovered = {}
        pause_arg = getattr(args, "pause_record", None)
        if bool(previous_arg) != bool(pause_arg):
            raise ValueError("user-pause recovery requires both prior directory and pause record")
        if previous_arg:
            previous = previous_arg.resolve()
            pause_path = pause_arg.resolve()
            old = json.loads((previous / "acceptance.json").read_text())
            pause = json.loads(pause_path.read_text())
            if (previous == output or old.get("status") != "stopped"
                    or old.get("error_type") != "KeyboardInterrupt"
                    or pause.get("user_requested_pause") is not True
                    or pause.get("status") != "paused_by_user"
                    or pause.get("original_observer_reason") != "observer_interrupted"
                    or pause.get("receipt_complete") is not False
                    or pause.get("measurement_complete") is not False):
                raise ValueError("prior run was not an explicitly recorded user pause")
            for key in ("image_id", "variant", "standard_verifier_sha256", "runtime_image_id", "docker_host"):
                if old.get(key) != evidence[key]:
                    raise ValueError("paused acceptance identity/environment changed")
            completed = old.get("samples", [])
            # Only an ordered, completed prefix can be reused; no skipped/duplicate cases.
            if not 4 <= len(completed) < 4 + len(plan):
                raise ValueError("paused acceptance lacks a recoverable completed prefix")
            for index, record in enumerate(completed):
                if index < 4:
                    count = (16, 32, 100, 500)[index]
                    folder, program, integrated = source / str(count), "sma", False
                else:
                    label, program, count, integrated = plan[index - 4]
                    folder = previous / label / str(count)
                    recovered[(label, count)] = folder
                if (Path(record["folder"]).resolve() != folder or record["program"] != program
                        or record["bars"] != count or record["integrated"] != integrated):
                    raise ValueError("paused acceptance prefix is out of order or duplicated")
            label, program, count, integrated = plan[len(completed) - 4]
            interrupted = previous / label / str(count)
            raw = json.loads((interrupted / "result.json").read_text())
            check_identity(raw, program, count, integrated)
            if (pause.get("sample") != f"{label}/{count}"
                    or raw.get("stop_reason") != "observer_interrupted"
                    or raw.get("measurement_complete") is not False
                    or raw.get("timed_out") is True
                    or raw.get("exit_code") is not None
                    or (interrupted / "process.json").exists()
                    or raw.get("state_before_cleanup", {}).get("Running") is not True
                    or raw.get("state_before_cleanup", {}).get("OOMKilled") is True
                    or raw.get("ordinary_api_slo_passed") is False
                    or not math.isfinite(raw["elapsed_seconds"])
                    or raw["elapsed_seconds"] >= 1800
                    or not math.isclose(raw["elapsed_seconds"], pause["elapsed_seconds"], abs_tol=.001)
                    or (interrupted / "proof.r0").exists()):
                raise ValueError("interrupted sample was not an incomplete user pause")
            if json.loads((interrupted / "witness.json").read_text()) != witness(count, program):
                raise ValueError("interrupted sample input differs from fixed representative input")
            samples = json.loads((interrupted / "samples.json").read_text())
            if not samples:
                raise ValueError("interrupted sample lacks resource observation")
            vm_since = memory_since = previous_observation = None
            for observation in samples:
                events = dict(line.split() for line in observation["memory.events"].splitlines())
                now = observation["elapsed_seconds"]
                if (not math.isfinite(now) or not math.isfinite(observation["vm_used_fraction"])
                        or (previous_observation is not None and now <= previous_observation)):
                    raise ValueError("interrupted resource observation is invalid")
                previous_observation = now
                vm_since = (now if vm_since is None else vm_since) if observation["vm_used_fraction"] > .85 else None
                memory_since = (now if memory_since is None else memory_since) if int(observation["memory.current"]) > int(raw["memory"][:-1]) * 1024**3 * .95 else None
                if (int(events.get("oom", 0)) > 0 or int(events.get("oom_kill", 0)) > 0
                        or int(events.get("oom_group_kill", 0)) > 0
                        or observation["health_errors"] >= 3
                        or (vm_since is not None and now - vm_since >= 10)
                        or (memory_since is not None and now - memory_since >= 10)):
                    raise ValueError("resource/health protection cannot be retried as a user pause")
            evidence["resumed_user_pause"] = {
                "previous_directory": str(previous), "interrupted_sample": str(interrupted),
                "pause_record_sha256": hashlib.sha256(pause_path.read_bytes()).hexdigest(),
                "previous_acceptance_sha256": hashlib.sha256((previous / "acceptance.json").read_bytes()).hexdigest(),
                "completed_prefix_reverified": False}
            save()
        for count in (16, 32, 100, 500):
            verify_sample(source / str(count), "sma", count, reused=True)
        for (label, count), folder in recovered.items():
            program = "state" if label == "state" or label.startswith("state-") else "sma"
            verify_sample(folder, program, count, reused=True, integrated="integrated" in label)
        if previous_arg:
            evidence["resumed_user_pause"]["completed_prefix_reverified"] = True
            save()
        for label, program, count, integrated in plan:
            if (label, count) not in recovered:
                sample(label, program, count, integrated=integrated)
        for program in ("sma", "state"):
            completed = [s for s in evidence["samples"] if s["program"] == program and s["bars"] == 500]
            if len(completed) != 3 or any(s["elapsed_seconds"] > 1800 for s in completed):
                raise RuntimeError("three complete 500-bar repetitions did not pass")
        evidence["representative_500_repeats_passed"] = True
        evidence["status"] = "restricted_500_samples_passed_whole_machine_pending"
        save()
        if args.explore_1000:
            for program in ("sma", "state"):
                sample(program + "-1000", program, 1000)
        evidence["status"] = "restricted_samples_complete_whole_machine_pending"
        save()
    except BaseException as error:
        evidence["status"] = "stopped"
        evidence["error_type"] = type(error).__name__
        save()
        raise


def main(args):
    lock_path = args.experiment.resolve() / ".acceptance.lock"
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        return accept(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--variant", choices=["buffered", "signed", "hashbatch", "hashfull", "hashwords", "hashlto", "hashinline", "hashinlinelto", "hashforceinline", "hashforcelto", "hashstack"], default="signed")
    parser.add_argument("--initial-sma", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--explore-1000", action="store_true", help="only after all six 500-bar repetitions and SLO pass")
    parser.add_argument("--resume-user-pause", type=Path, help="prior stopped acceptance; requires an explicit user-pause audit and a fresh output directory")
    parser.add_argument("--pause-record", type=Path, help="record of the user-requested interruption, never a timeout/resource-failure override")
    main(parser.parse_args())
