# Frozen isolated guest hashforcelto

This snapshot is public interpreter/guest code, not a user strategy or witness.
It was measured before the security fixes; it has NOT been rebuilt or enabled.
SDK: RISC Zero 3.0.6. Official guest rustc 1.97.0-dev (e638c6cfe).
Official x86_64 compiler archive SHA256:
100b597d605b706bec94e1d32bfaaf5851df8d75173f986d4b56a3e90916be53

Reproduction requires the recorded SDK toolchain, Cargo.lock dependencies and
user-guest flags in manifest.json, plus the reviewed v2 R0BF kernel (Image ID
02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4).
Compile offline and locked for riscv32im-risc0-zkvm-elf using the included guest
Cargo.toml (release fat LTO, codegen-units=1). The repository's reviewed
build_guest_experiments.py and experimental driver's pack command document
compilation and SDK ProgramBinary packaging. Compute the resulting SDK Image ID
and R0BF SHA256; never replace a registered ID to match a different build.

The guest still lacks metadata string limits; trusted generation entrypoints
enforce 4096 UTF-8 bytes per field and a 16MiB witness limit. These are host
resource controls, not additional properties proven inside this guest.
