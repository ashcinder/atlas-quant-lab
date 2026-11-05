"""Safety guards with a simulated cgroup; never starts Docker or a proof."""
from contextlib import nullcontext
import json
import os
import subprocess
import sys
from types import SimpleNamespace
import urllib.error

import pytest

import run as runner


@pytest.mark.parametrize("verifier_kind", ["missing", "standard", "driver_copy"])
def test_experimental_api_cannot_use_the_experimental_cli_as_its_verifier(tmp_path, monkeypatch, verifier_kind):
    binary, guest, verifier = [tmp_path / name for name in ("driver", "guest", "verifier")]
    for path in (binary, guest, verifier):
        path.write_bytes(path.name.encode())
    if verifier_kind == "driver_copy":
        verifier.write_bytes(binary.read_bytes())
    captured = {}

    def docker(*args, **kwargs):
        if args[:2] == ("image", "inspect"):
            return "test-image"
        if args[0] == "info":
            return json.dumps({"architecture": "aarch64", "cpus": 10, "memory_bytes": 12526305280})
        assert args[0] == "run"
        captured["command"] = args
        raise RuntimeError("captured; no container started")

    monkeypatch.setattr(runner, "docker", docker)
    args = SimpleNamespace(binary=binary, mode="prove", program="sma", po2=18,
        disk_segments=True, integrated=True, cpus=3, threads=3, memory="6g",
        platform="linux/arm64", timeout=1, image="test", health="http://unused.invalid",
        experimental_guest=guest, experimental_image_id="ab" * 32,
        verifier_binary=None if verifier_kind == "missing" else verifier)
    if verifier_kind != "standard":
        with pytest.raises(ValueError, match="separate standard verifier|experimental driver cannot"):
            runner.run(args, 16, tmp_path / "sample")
        assert captured == {}
    else:
        with pytest.raises(RuntimeError, match="no container started"):
            runner.run(args, 16, tmp_path / "sample")
        command = captured["command"]
        assert f"type=bind,source={verifier},target=/candidate/verifier,readonly" in command
        assert ".symlink_to('/candidate/verifier')" in command[-1]
        assert "'/candidate/atlas-zkvm', 'prove', '/candidate/guest.r0bf'" in command[-1]
        metadata = json.loads((tmp_path / "sample/parameters.json").read_text())
        assert metadata["api_verifier_preflight_required"] is True
        assert metadata["ordinary_api_profile_source"] == "unchanged_canonical_registry"


@pytest.mark.parametrize("scenario,expected", [("slo", "ordinary_api_slo"), ("exit", "proof_exit"),
                                             ("slow_api", None), ("timeout_finalize", "timeout")])
def test_completion_classification_and_full_deadline_after_slow_api_start(tmp_path, monkeypatch, scenario, expected):
    binary = tmp_path / "candidate"
    binary.write_bytes(b"not-executed")
    folder, clock = tmp_path / "sample", SimpleNamespace(now=0)

    def docker(*args, **kwargs):
        if args[:2] == ("image", "inspect"):
            return "test-image"
        if args[0] == "info":
            return json.dumps({"architecture": "aarch64", "cpus": 10, "memory_bytes": 12526305280})
        if args[0] in {"run", "kill", "rm"}:
            return ""
        if args[0] == "inspect":
            return json.dumps([{"State": {"Running": True, "OOMKilled": False}}])
        assert args[0] == "exec"
        delayed = scenario in {"slow_api", "timeout_finalize"}
        if delayed and clock.now >= 120:
            (folder / "proof-started.json").write_text('{"started":true}')
        if not delayed or clock.now >= (136 if scenario == "timeout_finalize" else 130):
            (folder / "process.json").write_text(json.dumps({"exit_code": 17 if scenario == "exit" else 0,
                "elapsed_seconds": 12.001 if scenario == "timeout_finalize" else 10,
                "timed_out": scenario == "timeout_finalize", "ordinary_api_slo_passed": scenario != "slo"}))
        return json.dumps({"memory.current": "1000", "memory.peak": "1234", "memory.events": "oom_kill 0\n",
            "cpu.stat": "usage_usec 10\n", "temporary_bytes": 0,
            "meminfo": "MemTotal: 100000 kB\nMemAvailable: 90000 kB\n"})

    monkeypatch.setattr(runner, "docker", docker)
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: setattr(clock, "now", clock.now+seconds))
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *a, **k: nullcontext(SimpleNamespace(status=200)))
    args = SimpleNamespace(binary=binary, mode="prove", program="sma", po2=18,
        disk_segments=True, integrated=True, cpus=3, threads=3, memory="6g",
        platform="linux/arm64", timeout=12, image="test", health="http://unused.invalid")
    assert runner.run(args, 16, folder) is (expected is None)
    result = json.loads((folder / "result.json").read_text())
    assert result["stop_reason"] == expected
    if scenario == "slow_api":
        assert clock.now == 130
    if scenario == "timeout_finalize":
        assert clock.now == 136 and result["measurement_complete"] is True


@pytest.mark.parametrize("scenario,expected", [
    ("memory", "container_memory_pressure"),
    ("vm", "vm_pressure"),
    ("health", "manual_health"),
    ("oom", "oom"),
    ("timeout", "timeout"),
    ("interrupt", "observer_interrupted"),
])
def test_protection_stops_and_only_cleans_own_container(tmp_path, monkeypatch, scenario, expected):
    binary = tmp_path / "candidate"
    binary.write_bytes(b"not-executed")
    folder = tmp_path / "sample"
    clock = SimpleNamespace(now=0)
    created, cleaned = [], []
    polls = 0
    limit = 5 * 1024**3

    def docker(*args, **kwargs):
        nonlocal polls
        if args[:2] == ("image", "inspect"):
            return "sha256:test-image"
        if args[0] == "info":
            return json.dumps({"architecture": "aarch64", "cpus": 10, "memory_bytes": 12526305280})
        if args[0] == "run":
            created.append(args[args.index("--name") + 1])
            return created[0]
        if args[0] == "inspect":
            return json.dumps([{"State": {"Running": scenario != "oom", "OOMKilled": scenario == "oom"}}])
        if args[0] in {"kill", "rm"}:
            cleaned.append((args[0], args[1]))
            return ""
        assert args[0] == "exec"
        if scenario == "interrupt":
            raise KeyboardInterrupt
        polls += 1
        # A success marker on the third unhealthy poll cannot override protection.
        if scenario == "health" and polls == 3:
            (folder / "process.json").write_text(json.dumps({"exit_code": 0, "elapsed_seconds": 1}))
        return json.dumps({"memory.current": str(int(limit * .96) if scenario == "memory" else 1000),
            "memory.peak": "1234", "memory.events": "oom_kill 0\n", "cpu.stat": "usage_usec 10\n",
            "meminfo": "MemTotal: 100000 kB\nMemAvailable: " + ("10000" if scenario == "vm" else "90000") + " kB\n",
            "temporary_bytes": 0})

    def health(*args, **kwargs):
        if scenario == "health":
            raise urllib.error.URLError("simulated")
        return nullcontext(SimpleNamespace(status=200))

    monkeypatch.setattr(runner, "docker", docker)
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds))
    monkeypatch.setattr(runner.urllib.request, "urlopen", health)
    args = SimpleNamespace(binary=binary, mode="prove", program="zero", po2=18,
        disk_segments=False, integrated=False, cpus=3, threads=3, memory="5g",
        platform="linux/arm64", timeout=12, image="test", health="http://unused.invalid")
    if scenario == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            runner.run(args, 16, folder)
    else:
        assert runner.run(args, 16, folder) is False
    result = json.loads((folder / "result.json").read_text())
    assert result["stop_reason"] == expected
    assert result["container"] == created[0]
    assert result["execution_architecture"] == "native"
    assert cleaned[-1] == ("rm", created[0])
    assert all(name == created[0] for _, name in cleaned)
    assert result["elapsed_seconds"] <= (29 if scenario == "timeout" else 14)
    assert result["measurement_complete"] is (scenario == "health")
    if scenario in {"memory", "vm"}:
        assert result["elapsed_seconds"] >= 10


@pytest.mark.parametrize("experimental", [False, True])
def test_internal_deadline_kills_child_without_an_observer(tmp_path, monkeypatch, experimental):
    binary = tmp_path / "candidate"
    binary.write_bytes(b"not-executed")
    captured = {}

    def docker(*args, **kwargs):
        if args[:2] == ("image", "inspect"):
            return "test-image"
        if args[0] == "info":
            return json.dumps({"architecture": "aarch64", "cpus": 10, "memory_bytes": 12526305280})
        assert args[0] == "run"
        captured["launcher"] = args[-1]
        raise RuntimeError("capture only; no Docker started")

    monkeypatch.setattr(runner, "docker", docker)
    args = SimpleNamespace(binary=binary, mode="prove", program="zero", po2=18,
        disk_segments=False, integrated=False, cpus=3, threads=3, memory="5g",
        platform="linux/arm64", timeout=1, image="test", health="http://unused.invalid")
    if experimental:
        guest = tmp_path / "guest.r0bf"
        guest.write_bytes(b"not-executed")
        args.experimental_guest = guest
        args.experimental_image_id = "ab" * 32
        args.disk_segments = True
    with pytest.raises(RuntimeError, match="capture only"):
        runner.run(args, 16, tmp_path / "captured")
    # Execute the exact container launcher against a harmless sleeping child.
    # No external monitor is present to kill that child.
    child = "import os,time;from pathlib import Path;Path('child.pid').write_text(str(os.getpid()));time.sleep(60)"
    launcher = captured["launcher"].replace("'/sample'", repr(str(tmp_path)))
    before, remainder = launcher.split("code=subprocess.run(", 1)
    _, after = remainder.split(",stdout=out", 1)
    launcher = before + "code=subprocess.run(" + repr([sys.executable, "-c", child]) + ",stdout=out" + after
    launcher = launcher.replace("time.sleep(30)", "pass")
    subprocess.run([sys.executable, "-c", launcher], cwd=tmp_path, timeout=5, check=True)
    result = json.loads((tmp_path / "process.json").read_text())
    assert result["exit_code"] == 124 and result["timed_out"] is True
    assert 1 <= result["elapsed_seconds"] < 4
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "child.pid").read_text()), 0)


@pytest.mark.parametrize("tail_oom", [False, True])
def test_final_spike_and_oom_cannot_hide_between_poll_and_child_exit(tmp_path, monkeypatch, tail_oom):
    binary = tmp_path / "candidate"
    binary.write_bytes(b"not-executed")
    folder = tmp_path / "sample"
    polls = 0

    def docker(*args, **kwargs):
        nonlocal polls
        if args[:2] == ("image", "inspect"):
            return "test-image"
        if args[0] == "info":
            return json.dumps({"architecture": "aarch64", "cpus": 10, "memory_bytes": 12526305280})
        if args[0] in {"run", "kill", "rm"}:
            return ""
        if args[0] == "inspect":
            return json.dumps([{"State": {"Running": True, "OOMKilled": False}}])
        assert args[0] == "exec"
        polls += 1
        if polls == 1:
            # Completion arrives after the sampled peak; the final kernel
            # state must override this otherwise successful process marker.
            (folder / "process.json").write_text(json.dumps({"exit_code": 0, "elapsed_seconds": 1}))
        return json.dumps({"memory.current": "1000", "memory.peak": "8192" if polls > 1 else "1234",
            "memory.events": "oom_kill " + ("1" if tail_oom and polls > 1 else "0") + "\n",
            "cpu.stat": "usage_usec 10\n", "meminfo": "MemTotal: 100000 kB\nMemAvailable: 90000 kB\n",
            "temporary_bytes": 0})

    monkeypatch.setattr(runner, "docker", docker)
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *a, **k: nullcontext(SimpleNamespace(status=200)))
    args = SimpleNamespace(binary=binary, mode="prove", program="zero", po2=18,
        disk_segments=False, integrated=False, cpus=3, threads=3, memory="5g",
        platform="linux/arm64", timeout=12, image="test", health="http://unused.invalid")
    assert runner.run(args, 16, folder) is (not tail_oom)
    result = json.loads((folder / "result.json").read_text())
    assert result["peak_bytes"] == result["final_cgroup_peak_bytes"] == 8192
    assert result["stop_reason"] == ("oom" if tail_oom else None)
