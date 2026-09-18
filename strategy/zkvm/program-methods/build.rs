fn main() {
    println!("cargo:rerun-if-env-changed=TRINE_PREBUILT_GUESTS");
    if let Ok(root) = std::env::var("TRINE_PREBUILT_GUESTS") {
        // Cross-host packaging reuses the reviewed RISC-V guest; host proves
        // only when its embedded image matches the pinned profile.
        let input = std::path::Path::new(&root).join("program-methods").join("methods.rs");
        println!("cargo:rerun-if-changed={}", input.display());
        std::fs::copy(input, std::path::Path::new(&std::env::var("OUT_DIR").unwrap()).join("methods.rs")).unwrap();
    } else { risc0_build::embed_methods(); }
}
