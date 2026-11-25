# core-rs — Phantom Fleet deterministic control plane (Rust)

Direct 1:1 Rust port of `ops/sched/*.py`. The Python modules are the
spec; this crate inherits bit-for-bit behaviour and gains ~100×
throughput + near-zero memory per device.

## Scope (Phase 0)

- `warming.rs` — shipped. Parity with `ops/sched/warming.py`
  (DAY_BANDS, MAX_PER_DAY, awake window, Normal-around-peak intraday
  placement, OS CSPRNG via raw getrandom syscall / BCryptGenRandom).

## Scope (Phase 1, in progress)

- `endpoints.rs` / `outcome.rs` / `transport.rs` / `worker.rs` — shipped.
  Parity with `ops/dispatch/*.py`. EXACT APK field names preserved
  (clonePackage/username/mediaId/commentText/storyCount/watchCount),
  verified in CI by `tests/wire_test_stub.rs` against the same 8
  assertions as the Python wire test.
- `bin/dispatcher_rs.rs` — `cargo run --bin dispatcher-rs -- --once`
  drains up to N and exits. Mirrors `python -m ops.dispatch.worker`.
- `tick.rs` / `recovery.rs` / `replacement.rs` / `proxy.rs` — remaining
  state machines (future).

## Dependencies

- `warming.rs` stays stdlib-only. We go straight to `getrandom(2)` on
  Linux and `BCryptGenRandom` on Windows via extern C declarations.
  **Never** pull in `rand` here — distribution discipline forbids it
  on any code path that touches identity, fingerprint, scheduling, or
  inter-action delays.
- Dispatcher modules use `sqlx` (SQLite now; Postgres behind a feature
  flag), `reqwest` for HTTP, and `tokio` for the async runtime. These
  live strictly below the identity/schedule layer; the hot path never
  samples randomness from them.

## Build + test

```
cargo build --release
cargo test
```

## Parity contract

Any divergence between this crate and `ops/sched/warming.py` is a bug
in the Rust port (never the Python). Maintain the Python version first;
re-port if its semantics change.
