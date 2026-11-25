"""Telemetry wrapper: every sched tick auto-logs to replay + chain.

One helper, called from the top of every tick's `run()`:

    with instrument("recovery", apply=True) as rec:
        with _store.connect() as con:
            rec["inputs"] = replay.snapshot_inputs(con, "recovery")
            # ... do the work ...
            rec["decisions"] = {"transitions": [...], "proxy_signals": [...]}
            rec["now_ms"] = now_ms

On exit the helper:
 - writes a tick_log row (is_shadow=1 if dry-run, else live)
 - on `apply=True`, appends {kind, tick_id, output_hash} to the Merkle
   chain

Behavior of the tick is unchanged — this is pure instrumentation. If
the intel modules are unavailable (edge case: cold install) the
wrapper no-ops silently so the tick never fails for a telemetry
reason.

Zero LLM calls.
"""
from __future__ import annotations

import contextlib
import time
from typing import Any


SCHEMA_VERSION = "sched@v0"


@contextlib.contextmanager
def instrument(kind: str, apply: bool):
    # Importing inside the function keeps the sched modules independent
    # of ops/intel at module load time — a fresh install without the
    # intel tree still runs the sched layer.
    try:
        from ops.intel import replay, chain
    except ImportError:  # pragma: no cover
        replay = chain = None  # type: ignore

    seed = replay.mint_seed() if replay else "00" * 16
    bag: dict[str, Any] = {
        "seed": seed, "now_ms": None,
        "inputs": None, "decisions": None,
        "tick_id": None, "chain_head": None,
    }
    t0 = time.monotonic()
    try:
        yield bag
    finally:
        dur_ms = int((time.monotonic() - t0) * 1000)
        if replay is None or bag["inputs"] is None or bag["decisions"] is None:
            return
        try:
            tid = replay.log_tick(
                kind=kind,
                now_ms=int(bag["now_ms"] or 0),
                seed_hex=seed, rule_version=SCHEMA_VERSION,
                inputs=bag["inputs"], decisions=bag["decisions"],
                duration_ms=dur_ms, is_shadow=not apply,
            )
            bag["tick_id"] = tid
            if apply and chain is not None:
                res = chain.append(kind, {
                    "tick_id": tid,
                    "now_ms": bag["now_ms"],
                    "inputs_hash": replay._canonical_hash(bag["inputs"]),
                    "outputs_hash": replay._canonical_hash(bag["decisions"]),
                    "rule_version": SCHEMA_VERSION,
                })
                bag["chain_head"] = res["head"]
        except Exception:
            # Instrumentation failure must never break the tick.
            return
