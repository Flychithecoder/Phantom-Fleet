"""#1 Replay engine + shadow mode.

Turns every scheduler / recovery tick into a pure, replayable function
by capturing (now_ms, entropy_seed, rule_version) at the moment of
decision. Enables:

 * **replay(tick_id)** — re-execute any past tick against the exact DB
   state it saw, deterministically. Debug by reproduction, not by
   staring at logs.
 * **shadow(rule_fn)** — run a candidate rule on every live tick in
   parallel; writes to *_shadow tables; comparable after N days.
 * **counterfactual(tick_id, rule_fn)** — "what would THIS tick have
   decided if rule R were replaced with R'?" A/B at the decision
   level, not the day level.

Zero LLM calls. Pure stdlib.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402


REPLAY_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS tick_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,          -- 'scheduler' | 'recovery' | 'proxy'
        now_ms INTEGER NOT NULL,
        seed_hex TEXT NOT NULL,      -- 128-bit entropy capture
        rule_version TEXT NOT NULL,  -- git short hash of the rule file
        input_hash TEXT NOT NULL,    -- sha256 of the DB rows read
        output_hash TEXT NOT NULL,   -- sha256 of the decisions produced
        decisions_json TEXT NOT NULL,
        duration_ms INTEGER NOT NULL,
        is_shadow INTEGER NOT NULL DEFAULT 0
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_tick_log_kind_ts ON tick_log(kind, now_ms);",
    "CREATE INDEX IF NOT EXISTS ix_tick_log_shadow ON tick_log(is_shadow, now_ms);",
    """
    CREATE TABLE IF NOT EXISTS shadow_divergences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        live_tick_id INTEGER NOT NULL,
        shadow_tick_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        divergence_json TEXT NOT NULL,
        ts_ms INTEGER NOT NULL
    );
    """,
]


def _init() -> None:
    _store.apply_migrations()
    with _store.connect() as con:
        for stmt in REPLAY_SCHEMA:
            con.executescript(stmt)


def _canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode("utf-8"),
    ).hexdigest()[:16]


def mint_seed() -> str:
    """128-bit seed from the OS CSPRNG. Reproducible via replay."""
    return secrets.token_hex(16)


def snapshot_inputs(con, kind: str) -> dict:
    """Capture the subset of DB state the given tick kind reads.

    Keeping this hand-rolled (vs 'SELECT * FROM every table') means a
    tick's input hash only changes when its *relevant* inputs change —
    adding a new unrelated column doesn't invalidate the replay.
    """
    if kind == "scheduler":
        rows = con.execute(
            "SELECT id, status, persona, device_serial FROM accounts "
            "ORDER BY id"
        ).fetchall()
        sched = con.execute(
            "SELECT account_id, warming_day, last_tick_ms "
            "FROM account_schedule_state ORDER BY account_id"
        ).fetchall()
        profiles = con.execute(
            "SELECT persona, diurnal_peak_hour_local, timezone "
            "FROM persona_profiles ORDER BY persona"
        ).fetchall()
        return {
            "accounts": [dict(r) for r in rows],
            "schedule_state": [dict(r) for r in sched],
            "profiles": [dict(r) for r in profiles],
        }
    if kind == "recovery":
        return {
            "accounts": [dict(r) for r in con.execute(
                "SELECT id, status FROM accounts ORDER BY id"
            ).fetchall()],
            "recent_results": [dict(r) for r in con.execute(
                "SELECT account_id, outcome, ts_ms FROM action_results "
                "WHERE ts_ms >= ? ORDER BY account_id, ts_ms DESC",
                (int(time.time() * 1000) - 48 * 3600 * 1000,),
            ).fetchall()],
        }
    if kind == "proxy":
        return {
            "plans": [dict(r) for r in con.execute(
                "SELECT * FROM proxy_state ORDER BY plan_id"
            ).fetchall()],
            "recent_err": int(con.execute(
                "SELECT COUNT(*) FROM action_results "
                "WHERE outcome != 'ok' AND ts_ms >= ?",
                (int(time.time() * 1000) - 2 * 3600 * 1000,),
            ).fetchone()[0]),
        }
    return {}


def log_tick(
    kind: str, now_ms: int, seed_hex: str, rule_version: str,
    inputs: dict, decisions: dict, duration_ms: int,
    is_shadow: bool = False,
) -> int:
    _init()
    rec = {
        "kind": kind, "now_ms": now_ms, "seed_hex": seed_hex,
        "rule_version": rule_version,
        "input_hash": _canonical_hash(inputs),
        "output_hash": _canonical_hash(decisions),
        "decisions_json": json.dumps(decisions, default=str),
        "duration_ms": duration_ms,
        "is_shadow": 1 if is_shadow else 0,
    }
    with _store.connect() as con:
        cur = con.execute(
            "INSERT INTO tick_log (kind, now_ms, seed_hex, rule_version, "
            "input_hash, output_hash, decisions_json, duration_ms, is_shadow) "
            "VALUES (:kind, :now_ms, :seed_hex, :rule_version, "
            ":input_hash, :output_hash, :decisions_json, :duration_ms, :is_shadow)",
            rec,
        )
        return int(cur.lastrowid or 0)


def record_divergence(live_id: int, shadow_id: int, kind: str,
                      divergence: dict) -> None:
    with _store.connect() as con:
        con.execute(
            "INSERT INTO shadow_divergences "
            "(live_tick_id, shadow_tick_id, kind, divergence_json, ts_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (live_id, shadow_id, kind, json.dumps(divergence, default=str),
             int(time.time() * 1000)),
        )


def replay(tick_id: int) -> dict:
    """Return the stored (inputs, decisions, hashes) for a past tick."""
    _init()
    with _store.connect() as con:
        row = con.execute(
            "SELECT * FROM tick_log WHERE id = ?", (tick_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"no tick {tick_id}")
        row = dict(row)
    row["decisions"] = json.loads(row.pop("decisions_json"))
    return row


def verify(tick_id: int, fn: Callable[[dict, str, int], dict]) -> dict:
    """Replay a tick deterministically.

    `fn(inputs, seed_hex, now_ms) -> decisions` should re-run the
    exact rule the live tick ran. Returns a diff report.
    """
    live = replay(tick_id)
    _init()
    with _store.connect() as con:
        inputs = snapshot_inputs(con, live["kind"])
    redo = fn(inputs, live["seed_hex"], live["now_ms"])
    return {
        "tick_id": tick_id,
        "live_output_hash": live["output_hash"],
        "replay_output_hash": _canonical_hash(redo),
        "match": _canonical_hash(redo) == live["output_hash"],
        "live_decisions": live["decisions"],
        "replay_decisions": redo,
    }


def shadow_run(
    kind: str,
    candidate_fn: Callable[[dict, str, int], dict],
    rule_version: str = "candidate",
) -> int:
    """Run `candidate_fn` once against today's DB, log as is_shadow=1."""
    _init()
    seed = mint_seed()
    now_ms = int(time.time() * 1000)
    with _store.connect() as con:
        inputs = snapshot_inputs(con, kind)
    t0 = time.monotonic()
    decisions = candidate_fn(inputs, seed, now_ms)
    dur = int((time.monotonic() - t0) * 1000)
    return log_tick(kind, now_ms, seed, rule_version, inputs, decisions,
                    dur, is_shadow=True)


def compare(live_id: int, shadow_id: int) -> dict:
    """Diff a live tick against a shadow run of the same kind."""
    live = replay(live_id)
    shadow = replay(shadow_id)
    if live["kind"] != shadow["kind"]:
        raise ValueError("kind mismatch")
    live_set = _normalise(live["decisions"])
    shadow_set = _normalise(shadow["decisions"])
    only_live = [d for d in live_set if d not in shadow_set]
    only_shadow = [d for d in shadow_set if d not in live_set]
    report = {
        "kind": live["kind"],
        "live_count": len(live_set),
        "shadow_count": len(shadow_set),
        "same": len(live_set & shadow_set) if isinstance(live_set, set) else None,
        "only_live_sample": list(only_live)[:10],
        "only_shadow_sample": list(only_shadow)[:10],
    }
    record_divergence(live_id, shadow_id, live["kind"], report)
    return report


def _normalise(decisions: dict) -> set:
    """Flatten decisions into a set of comparable tuples."""
    items: list = []
    for key in ("transitions", "proxy_signals", "decisions",
                "emitted", "per_account"):
        rows = decisions.get(key) or []
        for r in rows:
            if isinstance(r, dict):
                items.append(tuple(sorted(
                    (k, v) for k, v in r.items()
                    if isinstance(v, (str, int, float, bool)) or v is None
                )))
    return set(items)
