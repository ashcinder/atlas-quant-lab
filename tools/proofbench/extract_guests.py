#!/usr/bin/env python3
"""Recover reviewed RISC-V ELFs for a host-only rebuild, never new guests.

The rebuilt host MUST pass packaged_guests_match_the_immutable_registry before
use. The constants below are names only; IDs come from the trusted registry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def extract(binary, output, profiles, legacy_build_image_id=None):
    content = binary.read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    found = {}
    start = 0
    while True:
        offset = content.find(b"R0BF\x01\x00\x00\x00", start)
        if offset < 0:
            break
        start = offset + 8
        header_length = struct.unpack_from("<I", content, offset+8)[0]
        user_start = offset + 16 + header_length
        if header_length > 4096:
            continue
        user_length = struct.unpack_from("<I", content, user_start-4)[0]
        kernel_start = user_start + user_length
        if content[user_start:user_start+7] != b"\x7fELF\x01\x01\x01" or content[kernel_start:kernel_start+7] != b"\x7fELF\x01\x01\x01":
            raise ValueError("invalid reviewed ProgramBinary")
        # SDK 3.0.6 needs the R0BF header plus BOTH user and kernel ELF.
        header = struct.unpack_from("<16sHHIIIIIHHHHHH", content, kernel_start)
        if header[2] != 243:
            continue
        _, _, _, _, _, phoff, shoff, _, _, phsize, phnum, shsize, shnum, _ = header
        ends = [52, phoff + phsize*phnum, shoff + shsize*shnum]
        for i in range(shnum):
            section = struct.unpack_from("<IIIIIIIIII", content, kernel_start + shoff + i*shsize)
            if section[1] != 8:
                ends.append(section[4] + section[5])
        length = kernel_start - offset + max(ends)
        if length > 20_000_000 or offset + length > len(content):
            raise ValueError("invalid embedded ELF bounds")
        elf = content[offset:offset+length]
        if b"atlas_program_backtest_risc0_v2" in elf:
            kind, symbol, profile = "program-methods", "ATLAS_PROGRAM_GUEST", "atlas_program_backtest_risc0_v2"
        elif b"atlas_sma_backtest_risc0_v1" in elf:
            kind, symbol, profile = "methods", "ATLAS_BACKTEST_GUEST", "atlas_sma_backtest_risc0_v1"
        else:
            continue
        if kind in found:
            raise ValueError("ambiguous guest; refuse to choose")
        path = output / (kind + ".elf")
        path.write_bytes(elf)
        registered_id = profiles[profile]["image_id"]
        # Preserve a shipped legacy build even when it cannot prove the old
        # immutable profile. Host's existing fail-closed guard stays in force.
        built_id = legacy_build_image_id if kind == "methods" and legacy_build_image_id else registered_id
        digest = bytes.fromhex(built_id)
        if len(digest) != 32:
            raise ValueError("image ID must be 32 bytes")
        words = [int.from_bytes(digest[i:i+4], "little") for i in range(0, 32, 4)]
        directory = output / kind
        directory.mkdir()
        # Mount this directory at /prebuilt when rebuilding the host.
        (directory / "methods.rs").write_text(
            f'pub const {symbol}_ELF: &[u8] = include_bytes!("/prebuilt/{path.name}");\n'
            f'pub const {symbol}_ID: [u32; 8] = {words};\n')
        found[kind] = {"offset": offset, "bytes": length, "sha256": hashlib.sha256(elf).hexdigest(),
                       "expected_image_id": registered_id, "embedded_build_image_id": digest.hex()}
    if set(found) != {"methods", "program-methods"}:
        raise ValueError("both registered guests are required")
    manifest = {"source_binary_sha256": hashlib.sha256(content).hexdigest(), "guests": found,
                "validation": "unverified until SDK compute_image_id tests pass"}
    (output / "extraction.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--legacy-build-image-id", help="exact legacy profile output from the trusted released binary")
    p.add_argument("--registry", type=Path, default=Path(__file__).resolve().parents[2] / "strategy/zkvm/profiles.json")
    args = p.parse_args()
    print(json.dumps(extract(args.binary, args.output, json.loads(args.registry.read_text())["profiles"], args.legacy_build_image_id)))
