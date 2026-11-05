#!/usr/bin/env python3
"""Compile prepared guests offline with a SHA-verified official Linux toolchain.

The compiler may run under amd64 emulation; execution/proof benchmarks must
still record their own architecture. No application mounts or service changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
import uuid


def registry_versions(lock):
    return {(p["name"], p["version"], p.get("checksum"))
            for p in tomllib.loads(lock.read_text())["package"] if p.get("source")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--image", default="atlas-cn-host:local-20261016")
    parser.add_argument("--variants", nargs="+", choices=["baseline", "sha", "optimized", "narrow", "buffered", "signed", "hashbatch", "hashfull", "hashwords", "hashlto", "hashinline", "hashinlinelto", "hashforceinline", "hashforcelto", "hashstack"],
                        default=["baseline", "sha", "optimized"])
    args = parser.parse_args()
    root = args.experiment.resolve()
    verified = json.loads((root / "toolchain/verified.json").read_text())
    archive = root / "toolchain/rust-toolchain-x86_64-unknown-linux-gnu.tar.gz"
    if verified["sha256"] != "100b597d605b706bec94e1d32bfaaf5851df8d75173f986d4b56a3e90916be53":
        raise ValueError("official toolchain digest differs")
    if archive.stat().st_size != 528796425 or verified["bytes"] != 528796425:
        raise ValueError("official toolchain archive is incomplete")
    with archive.open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != verified["sha256"]:
            raise ValueError("official toolchain archive digest mismatch")
    # SDK 3.0.6 encode_rust_flags for a user guest, without metadata overrides.
    flags = "\x1f".join(["-C", "passes=lower-atomic", "-C", "link-arg=-Ttext=0x00200800",
        "-C", "link-arg=--fatal-warnings", "-C", "panic=abort", "--cfg", 'getrandom_backend="custom"'])
    for variant in args.variants:
        name = "atlas-speed-guest-build-" + uuid.uuid4().hex[:12]
        lock = root / "source" / variant / "program-methods/guest/Cargo.lock"
        before = registry_versions(lock)
        command = ["docker", "run", "--rm", "--pull", "never",
            "--name", name, "--platform", "linux/amd64",
            "--cpus", "2", "--memory", "3g", "--memory-swap", "3g", "--network", "none",
            "--entrypoint", "sh", "--mount", f"type=bind,src={root},dst=/experiment",
            "--mount", f"type=bind,src={root}/toolchain/install,dst=/toolchain,readonly"]
        for value in ["RUSTC=/toolchain/bin/rustc", "CARGO_BUILD_JOBS=1",
                "CARGO_TARGET_DIR=/experiment/guest-target", "RISC0_FEATURE_bigint2=",
                "CC=/no_risc0_cpp_toolchain_installed_run_rzup_install_cpp",
                "CFLAGS_riscv32im_risc0_zkvm_elf=-march=rv32im -nostdlib",
                "CARGO_ENCODED_RUSTFLAGS=" + flags]:
            command += ["-e", value]
        command += [args.image, "-c", "/toolchain/bin/rustc -vV > /experiment/guest-rustc.txt && "
            "cargo build --offline " + ("--locked " if variant in {"buffered", "signed", "hashbatch", "hashfull", "hashwords", "hashlto", "hashinline", "hashinlinelto", "hashforceinline", "hashforcelto", "hashstack"} else "") +
            "--release --target riscv32im-risc0-zkvm-elf "
            f"--manifest-path /experiment/source/{variant}/program-methods/guest/Cargo.toml"]
        try:
            with (root / (variant + "-guest-build.log")).open("w") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
        finally:
            # Limit cleanup to this script's uniquely named disposable container.
            subprocess.run(["docker", "rm", "-f", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        if registry_versions(lock) != before:
            raise ValueError("registry dependency versions changed")
        (root / variant).mkdir(exist_ok=True)
        shutil.copyfile(root / "guest-target/riscv32im-risc0-zkvm-elf/release/atlas-program-guest",
                        root / variant / "user.elf")
        print(variant, "built with unchanged registry versions", flush=True)


if __name__ == "__main__":
    main()
