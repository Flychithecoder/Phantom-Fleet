//! `cargo run --bin dispatcher-rs -- --once --apply --max 25`
//!
//! Mirrors `python -m ops.dispatch.worker`. The Python version stays
//! the reference implementation until this port passes CI parity.

use anyhow::Result;
use clap::Parser;
use pf_core::{store, worker};
use std::path::PathBuf;
use std::time::Duration;

#[derive(Parser, Debug)]
#[command(name = "dispatcher-rs", about = "Phantom Fleet Rust dispatcher")]
struct Args {
    /// Drain up to --max actions then exit.
    #[arg(long)]
    once: bool,
    /// Actually POST to devices. Mutually exclusive with --dry-run.
    #[arg(long, conflicts_with = "dry_run")]
    apply: bool,
    /// Classify what it WOULD dispatch, no HTTP calls.
    #[arg(long = "dry-run")]
    dry_run: bool,
    /// Max rows per pass.
    #[arg(long, default_value_t = 25)]
    max: i64,
    /// Limit to one device serial.
    #[arg(long)]
    only: Option<String>,
    /// SQLite path (defaults to `backend/.data/persona-store.sqlite`
    /// relative to CWD).
    #[arg(long)]
    db: Option<PathBuf>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    if !args.apply && !args.dry_run {
        eprintln!("one of --apply / --dry-run is required");
        std::process::exit(2);
    }

    let db_path = args
        .db
        .unwrap_or_else(|| PathBuf::from("backend/.data/persona-store.sqlite"));
    let pool = store::connect(&db_path).await?;
    store::apply_migrations(&pool).await?;

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()?;
    let report = worker::run(
        &pool,
        &client,
        args.apply,
        args.max,
        args.only.as_deref(),
        None,
    )
    .await?;

    let t = &report.totals;
    println!("dispatch @ {}  apply={}", report.now_ms, report.apply);
    println!("  claimed   : {}", t.claimed);
    println!("  dispatched: {}", t.dispatched);
    println!("  ok        : {}", t.ok);
    println!("  err       : {}", t.err);
    println!("  skipped   : {} (per-device cooldown)", t.skipped_cooldown);
    for r in report.results.iter().take(15) {
        let ser: String = r.device_serial.chars().take(12).collect();
        println!(
            "    #{:<5} {:<8} serial={:<12} -> {:<22} ({}ms)",
            r.action_id, r.kind, ser, r.outcome, r.latency_ms
        );
    }
    Ok(())
}
