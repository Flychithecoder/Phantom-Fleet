//! Phantom Fleet deterministic control plane — Rust port.
//!
//! The Python modules under `ops/sched/` and `ops/dispatch/` are the
//! specification; this crate is a mechanical translation that keeps
//! bit-exact behaviour and gains ~100x throughput + near-zero memory
//! per device.
//!
//! Phase 0 ports:
//!   * `warming`   — day-N bands + diurnal placement (ops/sched/warming.py)
//!   * `endpoints` — scheduler kind -> APK endpoint spec (ops/dispatch/_endpoints.py)
//!   * `outcome`   — HTTP response -> recovery outcome (ops/dispatch/_outcome.py)
//!   * `transport` — resolve/claim/release/sweep/do_request (ops/dispatch/_transport.py)
//!   * `store`     — SQLite schema bring-up matching ops/sched/_store.py
//!   * `worker`    — dispatcher main loop (ops/dispatch/worker.py)
//!
//! All ports preserve: 22/day cap, 06-24h awake window, LogNormal-ish
//! band sampling, Normal-around-peak intraday placement, EXACT APK
//! field names (clonePackage/username/mediaId/commentText).
pub mod warming;

pub mod endpoints;
pub mod outcome;
pub mod store;
pub mod transport;
pub mod worker;
