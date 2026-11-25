# core-rs — Phantom Fleet deterministic control plane (Rust)

Direct 1:1 Rust port of `ops/sched/*.py`. The Python modules are the
spec; this crate inherits bit-for-bit behaviour and gains ~100×
throughput + near-zero memory per device.

## Scope (Phase 0)

- `warming.rs` — shipped. Parity with `ops/sched/warming.py`
  (DAY_BANDS, MAX_PER_DAY, awake window, Normal-around-peak intraday
  placement, OS CSPRNG via raw getrandom syscall / BCryptGenRandom).

## Scope (Phase 1, planned)

- `tick.rs` / `recovery.rs` / `replacement.rs` / `proxy.rs` — remaining
  state machines
- SQLite via `rusqlite` (only external dep we accept)
- Optional async HTTP dispatcher reading `action_queue`

## Dependencies

**Zero** (stdlib only). We go straight to `getrandom(2)` on Linux and
`BCryptGenRandom` on Windows via extern C declarations. If you ever
see this crate pull in `rand` or `tokio`, push back.

## Build + test

```
cargo build --release
cargo test
```

## Parity contract

Any divergence between this crate and `ops/sched/warming.py` is a bug
in the Rust port (never the Python). Maintain the Python version first;
re-port if its semantics change.
