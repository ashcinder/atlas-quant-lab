//! Isolated experiments only. No registered profile lookup or service writes.
use std::{cell::RefCell, collections::BTreeMap, env, fs, path::Path, rc::Rc, time::Instant};
use anyhow::{ensure, Context, Result};
use risc0_binfmt::ProgramBinary;
use risc0_zkvm::{get_prover_server, ExecutorEnv, ExecutorImpl, ProverOpts, Receipt, Segment, SessionEvents, TraceEvent, VerifierContext};
use serde_json::json;

const PROFILE: &str = "atlas_program_backtest_risc0_v3_experimental";
const OLD_IMAGE: &str = "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4";

struct Progress(Instant);
impl SessionEvents for Progress {
    fn on_post_prove_segment(&self, segment: &Segment) {
        eprintln!("segment_completed={} po2={} proving_elapsed_seconds={:.3}",
            segment.index, segment.po2(), self.0.elapsed().as_secs_f64());
    }
}

fn id_hex(id: risc0_zkvm::sha::Digest) -> String { hex::encode(id.as_bytes()) }

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    ensure!(args.len() >= 2, "expected pack, analyze, prove, or verify");
    ensure!(env::var("RISC0_DEV_MODE").unwrap_or_default() != "1", "development mode forbidden");
    if args[1] == "encode" {
        ensure!(args.len() == 4, "encode WITNESS_JSON RAW_OUTPUT");
        let witness: atlas_program_core::StrategyWitness = serde_json::from_slice(&fs::read(&args[2])?)?;
        let words = risc0_zkvm::serde::to_vec(&witness)?;
        let bytes: Vec<u8> = words.iter().flat_map(|word| word.to_le_bytes()).collect();
        fs::write(&args[3], &bytes)?;
        println!("{}", json!({"serialization_only":true,"execution_only":true,"input_bytes":bytes.len()}));
        return Ok(());
    }
    if args[1] == "pack" {
        ensure!(args.len() == 5, "pack USER_ELF REVIEWED_OLD_R0BF OUTPUT_R0BF");
        let user = fs::read(&args[2])?;
        let old = fs::read(&args[3])?;
        ensure!(id_hex(risc0_zkvm::compute_image_id(&old)?) == OLD_IMAGE, "reviewed kernel source ID mismatch");
        let old = ProgramBinary::decode(&old)?;
        let packaged = ProgramBinary::new(&user, old.kernel_elf).encode();
        let image = id_hex(risc0_zkvm::compute_image_id(&packaged)?);
        fs::write(&args[4], packaged)?;
        println!("{}", json!({"image_id":image,"experimental_only":true,"registered_profile":false}));
        return Ok(());
    }
    if args[1] == "verify" || args[1] == "tampercheck" {
        ensure!(args.len() == 4, "verify RECEIPT EXPECTED_IMAGE_ID");
        ensure!(args[3].len() == 64 && args[3] == args[3].to_lowercase(), "expected 32-byte lowercase image ID");
        let bytes = hex::decode(&args[3])?;
        let digest = risc0_zkvm::sha::Digest::from(<[u8; 32]>::try_from(bytes.as_slice())?);
        let receipt: Receipt = bincode::deserialize(&fs::read(&args[2])?)?;
        receipt.verify(digest)?;
        if args[1] == "tampercheck" {
            use risc0_zkvm::{FakeReceipt, InnerReceipt, ReceiptClaim};
            for mutation in 0..3 {
                let mut changed = receipt.clone();
                let InnerReceipt::Composite(ref mut composite) = changed.inner else { anyhow::bail!("expected composite"); };
                ensure!(composite.segments.len() >= 2, "need genuine multi-segment proof");
                match mutation {
                    0 => { composite.segments.remove(0); },
                    1 => composite.segments.swap(0, 1),
                    _ => { composite.segments[0] = composite.segments[1].clone(); },
                }
                ensure!(changed.verify(digest).is_err(), "segment mutation {mutation} accepted");
            }
            let fake = Receipt::new(InnerReceipt::Fake(FakeReceipt::new(ReceiptClaim::ok(digest, vec![]))), vec![]);
            ensure!(fake.verify(digest).is_err(), "fake receipt accepted");
            println!("{}", json!({"experimental_only":true,"missing_reordered_replaced_segments_rejected":true,"fake_rejected":true}));
            return Ok(());
        }
        let journal: atlas_program_core::ZkPublicStatement = receipt.journal.decode()?;
        println!("{}", json!({"valid":true,"experimental_only":true,"registered_profile":false,"image_id":args[3],"journal":journal}));
        return Ok(());
    }
    let proving = args[1] == "prove";
    let tracing = args[1] == "trace";
    let raw = args[1] == "analyze-raw";
    ensure!(proving || tracing || raw || args[1] == "analyze", "unknown command");
    ensure!(args.len() == if proving || raw { 8 } else { 7 },
        "analyze|prove GUEST_R0BF EXPECTED_IMAGE_ID WITNESS PO2 SEGMENT_DIR [RECEIPT]");
    let started = Instant::now();
    let elf = fs::read(&args[2])?;
    let image = risc0_zkvm::compute_image_id(&elf)?;
    ensure!(id_hex(image) == args[3], "candidate ID differs from pinned manifest");
    let witness: atlas_program_core::StrategyWitness = serde_json::from_slice(&fs::read(&args[4])?)?;
    let mut expected = serde_json::to_value(atlas_program_core::execute(witness.clone()))?;
    expected["proof_profile"] = json!(PROFILE);
    let po2: u32 = args[5].parse()?;
    ensure!((16..=20).contains(&po2), "segment po2 outside 16..20");
    ensure!(Path::new(&args[6]).is_dir(), "segment directory must exist");
    let mut builder = ExecutorEnv::builder();
    builder.segment_limit_po2(po2).segment_path(&args[6]);
    if raw {
        // Analysis only: exercise the actual SDK serializer's bytes and malformed inputs.
        builder.write_slice(&fs::read(&args[7])?);
    } else {
        builder.write(&witness)?;
    }
    let pcs = Rc::new(RefCell::new(BTreeMap::<u32, (u64, u64, u32)>::new()));
    let tail = Rc::new(RefCell::new(None::<(u64, u32)>));
    let paging = Rc::new(RefCell::new((0u64, 0u64)));
    if tracing {
        let counts = pcs.clone();
        let previous = tail.clone();
        let page_events = paging.clone();
        builder.trace_callback(move |event| {
            match event {
              TraceEvent::InstructionStart { cycle, pc, insn } => {
                let mut counts = counts.borrow_mut();
                if let Some((last_cycle, last_pc)) = *previous.borrow() {
                    counts.entry(last_pc).or_default().1 += cycle.checked_sub(last_cycle)
                        .context("instruction trace cycle rolled backwards")?;
                }
                let row = counts.entry(pc).or_default();
                row.0 += 1;
                row.2 = insn;
                *previous.borrow_mut() = Some((cycle, pc));
              }
              TraceEvent::PageIn { cycles } => page_events.borrow_mut().0 += cycles,
              TraceEvent::PageOut { cycles } => page_events.borrow_mut().1 += cycles,
              _ => (),
            }
            Ok(())
        });
    }
    let prepare_seconds = started.elapsed().as_secs_f64();
    let stage = Instant::now();
    let mut session = ExecutorImpl::from_elf(builder.build()?, &elf)?.run()?;
    let execution_seconds = stage.elapsed().as_secs_f64();
    let journal: atlas_program_core::ZkPublicStatement = session.journal.as_ref().context("missing journal")?.decode()?;
    ensure!(serde_json::to_value(&journal)? == expected, "full journal differs from unchanged registered algorithm");
    let stats = session.stats();
    let segments: Vec<_> = session.segments.iter().map(|s| Ok(json!({"po2":s.resolve()?.po2()}))).collect::<Result<_>>()?;
    let mut output = json!({"experimental_only":true,"registered_profile":false,
        "execution_only":!proving,"image_id":args[3],"journal":journal,"stats":stats,
        "segments":segments,"segment_limit_po2":po2,
        "timings":{"prepare_seconds":prepare_seconds,"execution_seconds":execution_seconds}});
    if tracing {
        if let Some((last_cycle, last_pc)) = *tail.borrow() {
            pcs.borrow_mut().entry(last_pc).or_default().1 += stats.user_cycles.checked_sub(last_cycle)
                .context("trace tail exceeds complete session user cycles")?;
        }
        ensure!(pcs.borrow().values().map(|row| row.1).sum::<u64>() == stats.user_cycles,
            "instruction cycle aggregate differs from full session");
        let rows: Vec<_> = pcs.borrow().iter().map(|(pc, (count, cycles, insn))|
            json!({"pc":pc,"instruction_count":count,"raw_cycle_delta":cycles,"insn":insn})).collect();
        fs::write(Path::new(&args[6]).join("pc-trace.json"), serde_json::to_vec(&json!({
            "execution_only":true,"raw_cycle_deltas_may_include_paging":false,
            "cycle_source":"SDK cumulative user cycles, final instruction flushed",
            "user_cycles":stats.user_cycles,"paging_cycles":stats.paging_cycles,
            "page_in_event_cycles":paging.borrow().0,"page_out_event_cycles":paging.borrow().1,
            "paging_events_may_omit_final_commit":true,"rows":rows}))?)?;
    }
    if proving {
        let stage = Instant::now();
        session.add_hook(Progress(stage));
        let info = get_prover_server(&ProverOpts::default())?.prove_session(&VerifierContext::default(), &session)?;
        output["timings"]["proving_seconds"] = json!(stage.elapsed().as_secs_f64());
        let stage = Instant::now();
        info.receipt.verify(image)?;
        let proven: atlas_program_core::ZkPublicStatement = info.receipt.journal.decode()?;
        ensure!(serde_json::to_value(proven)? == expected, "receipt journal mismatch");
        output["timings"]["verification_seconds"] = json!(stage.elapsed().as_secs_f64());
        let bytes = bincode::serialize(&info.receipt)?;
        ensure!(bytes.len() <= 16 * 1024 * 1024, "receipt exceeds existing 16MiB limit");
        fs::write(&args[7], &bytes)?;
        output["receipt_bytes"] = json!(bytes.len());
        output["valid"] = json!(true);
    }
    output["elapsed_seconds"] = json!(started.elapsed().as_secs_f64());
    println!("{}", output);
    Ok(())
}
