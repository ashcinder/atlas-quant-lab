"""Control-flow gates only; mocked Proofs never supply cryptographic evidence."""
import hashlib
import fcntl
import json
from types import SimpleNamespace

import pytest

import accept_experimental as acceptance
from run import witness


def setup_candidate(tmp_path, monkeypatch):
    experiment, source = tmp_path / "experiment", tmp_path / "initial"
    (experiment / "signed").mkdir(parents=True)
    (experiment / "candidate").mkdir()
    guest = experiment / "signed/guest.r0bf"
    guest.write_bytes(b"not-a-guest")
    driver = experiment / "candidate/atlas-experimental-proofbench"
    driver.write_bytes(b"not-a-driver")
    verifier = tmp_path / "verifier"
    verifier.write_bytes(b"not-a-verifier")
    (experiment / "guest-manifest.json").write_text(json.dumps({"signed": {
        "image_id": "ab" * 32, "guest_sha256": hashlib.sha256(guest.read_bytes()).hexdigest()}}))

    def fixture(folder, program, count, integrated=False):
        folder.mkdir(parents=True)
        (folder / "proof.r0").write_bytes(b"mock-only-not-a-proof")
        (folder / "witness.json").write_text(json.dumps(witness(count, program)))
        (folder / "result.json").write_text(json.dumps({"exit_code": 0, "stop_reason": None,
            "measurement_complete": True, "guest_image_id": "ab" * 32,
            "guest_sha256": hashlib.sha256(guest.read_bytes()).hexdigest(),
            "binary_sha256": hashlib.sha256(driver.read_bytes()).hexdigest(),
            "witness_sha256": hashlib.sha256((folder / "witness.json").read_bytes()).hexdigest(),
            "program": program, "bars": count, "po2": 18 if count <= 32 else 19,
            "execution_architecture": "native", "mode": "prove", "cpus": 3, "threads": 3,
            "memory": "6g" if integrated else "5g", "disk_segments": True,
            "ordinary_api_slo_passed": True if integrated else None,
            "image": "atlas-proofbench-api:20261104-arm64", "image_id": "sha256:test-runtime",
            "docker_host": {"architecture": "aarch64", "cpus": 10, "memory_bytes": 12526305280},
            "integrated": integrated, "elapsed_seconds": 10, "peak_bytes": 1000, "final_cgroup_peak_bytes": 1000}))
        (folder / "parameters.json").write_bytes((folder / "result.json").read_bytes())
        if integrated:
            rows = [{"user": i, "write": write, "status": 200, "valid": True,
                     "seconds": .02 if write else .01} for i in range(5) for write in (False, True)]
            metrics = {"requests": len(rows), "unexpected": 0, "status_429": 0,
                       "read_p95_seconds": .01, "write_p95_seconds": .02, "elapsed_seconds": 60}
            (folder / "baseline.json").write_text(json.dumps({"metrics": metrics, "requests": rows}))
            (folder / "competition.json").write_text(json.dumps({"metrics": metrics, "requests": rows,
                "limits_seconds": {"read": 1, "write": 2}, "shared_api_prover_cgroup": True, "slo_passed": True}))
            (folder / "api-verifier-preflight.json").write_text(json.dumps({
                "id": "atlas_program_backtest_risc0_v2",
                "image_id": "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4"}))

    for count in (16, 32, 100, 500):
        fixture(source / str(count), "sma", count)
    monkeypatch.setattr(acceptance, "docker", lambda *a, **k:
        "sha256:test-runtime" if a[0] == "image" else json.dumps({"architecture": "aarch64", "cpus": 10,
        "memory_bytes": 12526305280}) if a[0] == "info" else "")
    monkeypatch.setattr(acceptance, "health_gate", lambda: None)
    monkeypatch.setattr(acceptance, "validate", lambda b, i, p, f, s: {
        "valid": True, "bars": json.loads((f / "result.json").read_text())["bars"]})
    args = SimpleNamespace(experiment=experiment, initial_sma=source, output=tmp_path / "acceptance",
        variant="signed", verifier=verifier, explore_1000=True)
    return args, fixture


@pytest.mark.parametrize("field,value", [("stop_reason", "timeout"), ("guest_image_id", "wrong"),
    ("execution_architecture", "cross_architecture"), ("elapsed_seconds", 1801), ("image_id", "wrong"),
    ("docker_host", {"architecture": "aarch64", "cpus": 2, "memory_bytes": 12526305280}),
    ("elapsed_seconds", float("nan")), ("final_cgroup_peak_bytes", 0)])
def test_ineligible_initial_sample_cannot_start_a_new_proof(tmp_path, monkeypatch, field, value):
    args, _ = setup_candidate(tmp_path, monkeypatch)
    path = args.initial_sma / "500/result.json"
    value_map = json.loads(path.read_text())
    value_map[field] = value
    path.write_text(json.dumps(value_map))
    monkeypatch.setattr(acceptance, "run", lambda *a, **k: pytest.fail("new Proof must not start"))
    with pytest.raises((RuntimeError, ValueError)):
        acceptance.main(args)
    assert json.loads((args.output / "acceptance.json").read_text())["status"] == "stopped"


def test_verifier_parameters_cannot_select_a_different_image_than_measured(tmp_path, monkeypatch):
    args, _ = setup_candidate(tmp_path, monkeypatch)
    path = args.initial_sma / "500/parameters.json"
    parameters = json.loads(path.read_text()); parameters["guest_image_id"] = "different"
    path.write_text(json.dumps(parameters))
    monkeypatch.setattr(acceptance, "run", lambda *a, **k: pytest.fail("new Proof must not start"))
    with pytest.raises(ValueError, match="parameters differ"):
        acceptance.main(args)


def test_small_initial_sample_must_keep_the_fixed_segment_configuration(tmp_path, monkeypatch):
    args, _ = setup_candidate(tmp_path, monkeypatch)
    path = args.initial_sma / "16/result.json"
    result = json.loads(path.read_text()); result["po2"] = 17
    path.write_text(json.dumps(result))
    monkeypatch.setattr(acceptance, "run", lambda *a, **k: pytest.fail("new Proof must not start"))
    with pytest.raises(ValueError, match="identity/configuration"):
        acceptance.main(args)


@pytest.mark.parametrize("scenario", ["success", "state_500_fail", "missing_integrated_slo", "missing_competition"])
def test_repeats_and_1000_are_gated_and_failure_never_retried(tmp_path, monkeypatch, scenario):
    args, fixture = setup_candidate(tmp_path, monkeypatch)
    calls = []

    def run(settings, count, folder):
        calls.append((settings.program, count, settings.integrated))
        assert settings.cpus == settings.threads == 3
        assert settings.timeout == (3600 if count == 1000 else 1800)
        if count == 1000:
            state = json.loads((args.output / "acceptance.json").read_text())
            assert state["representative_500_repeats_passed"] is True
            assert len([s for s in state["samples"] if s["bars"] == 500]) == 6
        if scenario == "state_500_fail" and settings.program == "state" and count == 500:
            return False
        fixture(folder, settings.program, count, settings.integrated)
        if scenario == "missing_integrated_slo" and settings.integrated:
            path = folder / "result.json"
            data = json.loads(path.read_text())
            del data["ordinary_api_slo_passed"]
            path.write_text(json.dumps(data))
        if scenario == "missing_competition" and settings.integrated:
            (folder / "competition.json").unlink()
        return True

    monkeypatch.setattr(acceptance, "run", run)
    if scenario == "state_500_fail":
        with pytest.raises(RuntimeError, match="series stopped without retry"):
            acceptance.main(args)
        assert calls == [("state", n, False) for n in (16, 32, 100, 500)]
    elif scenario == "missing_integrated_slo":
        with pytest.raises(RuntimeError, match="failed or incomplete sample"):
            acceptance.main(args)
        assert calls[-1] == ("sma", 500, True)
        assert not any(count == 1000 for _, count, _ in calls)
    elif scenario == "missing_competition":
        with pytest.raises(FileNotFoundError):
            acceptance.main(args)
        assert calls[-1] == ("sma", 500, True)
        assert not any(count == 1000 for _, count, _ in calls)
    else:
        acceptance.main(args)
        state = json.loads((args.output / "acceptance.json").read_text())
        assert state["whole_machine_4cpu_8gib_verified"] is False
        assert state["status"] == "restricted_samples_complete_whole_machine_pending"
        assert calls.count(("sma", 500, True)) == 1
        assert calls[-2:] == [("sma", 1000, False), ("state", 1000, False)]


def test_concurrent_acceptance_is_refused_without_starting_a_proof(tmp_path, monkeypatch):
    args, _ = setup_candidate(tmp_path, monkeypatch)
    with (args.experiment / ".acceptance.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            acceptance.main(args)
    assert not args.output.exists()


def test_failed_manual_health_stops_before_proof(tmp_path, monkeypatch):
    args, _ = setup_candidate(tmp_path, monkeypatch)
    monkeypatch.setattr(acceptance, "health_gate", lambda: (_ for _ in ()).throw(RuntimeError("health failed")))
    monkeypatch.setattr(acceptance, "run", lambda *a, **k: pytest.fail("new Proof must not start"))
    with pytest.raises(RuntimeError, match="health failed"):
        acceptance.main(args)
    assert json.loads((args.output / "acceptance.json").read_text())["status"] == "stopped"


def paused_candidate(tmp_path, monkeypatch):
    args, fixture = setup_candidate(tmp_path, monkeypatch)
    state500_seen = 0

    def interrupted_run(settings, count, folder):
        nonlocal state500_seen
        fixture(folder, settings.program, count, settings.integrated)
        if settings.program == "state" and count == 500:
            state500_seen += 1
            if state500_seen == 2:
                path = folder / "result.json"
                raw = json.loads(path.read_text())
                raw.update(stop_reason="observer_interrupted", measurement_complete=False,
                           elapsed_seconds=705.35, final_cgroup_peak_bytes=0,
                           state_before_cleanup={"OOMKilled": False, "Running": True})
                raw.pop("exit_code")
                path.write_text(json.dumps(raw))
                (folder / "proof.r0").unlink()
                observations = [{"memory.events": "oom 0\noom_kill 0\n", "memory.current": "1000",
                                 "elapsed_seconds": t, "vm_used_fraction": .5, "health_errors": 0}
                                for t in (0, 10, 20)]
                (folder / "samples.json").write_text(json.dumps(observations))
                raise KeyboardInterrupt()
        return True

    monkeypatch.setattr(acceptance, "run", interrupted_run)
    with pytest.raises(KeyboardInterrupt):
        acceptance.main(args)
    assert len(json.loads((args.output / "acceptance.json").read_text())["samples"]) == 9
    pause = args.experiment / "user-pause.json"
    pause.write_text(json.dumps({"user_requested_pause": True, "status": "paused_by_user",
        "original_observer_reason": "observer_interrupted", "receipt_complete": False,
        "measurement_complete": False, "sample": "state-repeat-2/500", "elapsed_seconds": 705.35}))
    args.resume_user_pause, args.pause_record = args.output, pause
    args.output = tmp_path / "fresh-recovery"
    return args, fixture


def test_explicit_pause_recovery_reverifies_prefix_and_only_runs_missing_proofs(tmp_path, monkeypatch):
    args, fixture = paused_candidate(tmp_path, monkeypatch)
    calls = []
    before = (args.resume_user_pause / "acceptance.json").read_bytes()
    def tree(directory):
        return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.rglob("*") if p.is_file()}
    prior_tree, source_tree = tree(args.resume_user_pause), tree(args.initial_sma)

    def fresh_validate(binary, image, platform, folder, backend):
        assert folder.is_relative_to(args.output)
        (folder / "new-verification-marker").write_text("mock-only")
        return {"valid": True, "bars": json.loads((folder / "result.json").read_text())["bars"]}

    monkeypatch.setattr(acceptance, "validate", fresh_validate)

    def resumed_run(settings, count, folder):
        evidence = json.loads((args.output / "acceptance.json").read_text())
        assert evidence["resumed_user_pause"]["completed_prefix_reverified"] is True
        assert len(evidence["samples"]) >= 9
        assert folder.is_relative_to(args.output)
        if count == 1000:
            assert evidence["representative_500_repeats_passed"] is True
            assert len([s for s in evidence["samples"] if s["bars"] == 500]) == 6
        calls.append((settings.program, count, settings.integrated))
        fixture(folder, settings.program, count, settings.integrated)
        return True

    monkeypatch.setattr(acceptance, "run", resumed_run)
    acceptance.main(args)
    assert calls == [("state", 500, False), ("sma", 500, True), ("state", 500, False),
                     ("sma", 1000, False), ("state", 1000, False)]
    assert (args.resume_user_pause / "acceptance.json").read_bytes() == before
    assert tree(args.resume_user_pause) == prior_tree
    assert tree(args.initial_sma) == source_tree
    assert not (args.resume_user_pause / "state-repeat-2/500/proof.r0").exists()


@pytest.mark.parametrize("directory", ["previous", "source"])
def test_recovery_output_cannot_modify_a_preserved_tree(tmp_path, monkeypatch, directory):
    args, _ = paused_candidate(tmp_path, monkeypatch)
    args.output = (args.resume_user_pause if directory == "previous" else args.initial_sma) / "new-output"
    monkeypatch.setattr(acceptance, "run", lambda *a, **k: pytest.fail("new Proof must not start"))
    with pytest.raises(ValueError, match="outside preserved"):
        acceptance.main(args)
    assert not args.output.exists()


@pytest.mark.parametrize("mutation", ["timeout", "oom", "manual_health", "wrong_pause",
    "duplicate_prefix", "changed_environment", "completed_receipt", "failed_completed_prefix",
    "observed_oom", "observed_health", "observed_vm_pressure", "observed_memory_pressure",
    "different_input", "missing_observations", "process_failure", "process_timeout", "raw_exit",
    "not_running", "observed_group_oom", "backward_observations", "nonfinite_vm"])
def test_pause_cannot_override_failure_or_changed_evidence(tmp_path, monkeypatch, mutation):
    args, _ = paused_candidate(tmp_path, monkeypatch)
    interrupted = args.resume_user_pause / "state-repeat-2/500"
    if mutation in {"timeout", "oom", "manual_health"}:
        path = interrupted / "result.json"
        raw = json.loads(path.read_text()); raw["stop_reason"] = mutation
    elif mutation == "wrong_pause":
        path = args.pause_record; raw = json.loads(path.read_text()); raw["sample"] = "state/500"
    elif mutation in {"duplicate_prefix", "changed_environment"}:
        path = args.resume_user_pause / "acceptance.json"; raw = json.loads(path.read_text())
        if mutation == "duplicate_prefix": raw["samples"][-1] = raw["samples"][-2]
        else: raw["runtime_image_id"] = "different"
    elif mutation == "completed_receipt":
        (interrupted / "proof.r0").write_bytes(b"must not silently redo")
    elif mutation in {"process_failure", "process_timeout"}:
        (interrupted / "process.json").write_text(json.dumps({"exit_code": 1 if mutation == "process_failure" else 124,
            "timed_out": mutation == "process_timeout"}))
    elif mutation in {"raw_exit", "not_running"}:
        path = interrupted / "result.json"; raw = json.loads(path.read_text())
        if mutation == "raw_exit": raw["exit_code"] = 1
        else: raw["state_before_cleanup"]["Running"] = False
    elif mutation == "failed_completed_prefix":
        path = args.resume_user_pause / "state/500/result.json"
        raw = json.loads(path.read_text()); raw["stop_reason"] = "timeout"
    elif mutation.startswith("observed_") or mutation in {"backward_observations", "nonfinite_vm"}:
        path = interrupted / "samples.json"; raw = json.loads(path.read_text())
        for observation in raw:
            if mutation == "observed_oom": observation["memory.events"] = "oom 1\noom_kill 0\n"
            elif mutation == "observed_group_oom": observation["memory.events"] = "oom 0\noom_group_kill 1\n"
            elif mutation == "observed_health": observation["health_errors"] = 3
            elif mutation == "observed_vm_pressure": observation["vm_used_fraction"] = .9
            elif mutation == "nonfinite_vm": observation["vm_used_fraction"] = float("nan")
            elif mutation == "backward_observations": observation["elapsed_seconds"] = 0
            else: observation["memory.current"] = str(5 * 1024**3)
    elif mutation == "different_input":
        path = interrupted / "witness.json"; raw = json.loads(path.read_text()); raw["agent_id"] = "qja_other"
    else:
        (interrupted / "samples.json").unlink()
    if mutation not in {"completed_receipt", "missing_observations", "process_failure", "process_timeout"}:
        path.write_text(json.dumps(raw))
    monkeypatch.setattr(acceptance, "run", lambda *a, **k: pytest.fail("new Proof must not start"))
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        acceptance.main(args)
    assert json.loads((args.output / "acceptance.json").read_text())["status"] == "stopped"
