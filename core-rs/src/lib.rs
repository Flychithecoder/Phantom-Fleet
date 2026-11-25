//! Phantom Fleet deterministic control plane — Rust port.
//!
//! The Python modules under `ops/sched/` are the specification; this
//! crate is a mechanical translation that keeps bit-exact behaviour
//! and gains ~100x throughput + near-zero memory per device.
//!
//! Phase 0 ports:
//!   * `warming` — day-N bands + diurnal placement
//!
//! Phase 1 ports (planned, mirroring the Python):
//!   * `tick`
//!   * `recovery`
//!   * `replacement`
//!   * `proxy`
//!
//! All ports preserve: 22/day cap, 06-24h awake window, LogNormal-ish
//! band sampling, Normal-around-peak intraday placement.
pub mod warming;
