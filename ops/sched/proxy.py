"""Deterministic proxy block-signal state machine.

Replaces the "Proxy Orchestrator Agent".  Zero LLM calls.

Model:
  proxy_state(plan_id, in_use, blocked_count, last_rotate_ms,
              last_block_ms, notes)

Transitions:
  B1  action_results in the last 2h contain >= 5 'network_error' OR
      >= 3 'ig_rate_limited' outcomes on accounts assigned to this
      plan  AND  last_rotate_ms is NULL or older than COOLDOWN_MS
      -> emit rotate (increments blocked_count, updates last_rotate_ms)

  B2  no error signal in the last 24h AND blocked_count > 0
      -> decrement blocked_count (healthy decay)

Rotation is the state transition; actually swapping the upstream proxy
endpoint happens in whatever layer controls traffic (TrumpProxies plan
rotation API, an IPRoyal endpoint, a modem reboot script).  This module
writes the decision; a downstream deterministic step dispatches it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402
from ops.sched._telemetry import instrument  # noqa: E402

try:
    from ops.intel import replay as _replay  # noqa: E402
except ImportError:  # pragma: no cover
    _replay = None  # type: ignore


WINDOW_ERR_MS = 2 * 3600 * 1000
WINDOW_HEAL_MS = 24 * 3600 * 1000
COOLDOWN_MS = 30 * 60 * 1000  # min 30min between rotations per plan

NETERR_THRESHOLD = 5
RATELIMIT_THRESHOLD = 3


def _plans(con) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT plan_id, in_use, blocked_count, last_rotate_ms, last_block_ms "
        "FROM proxy_state"
    ).fetchall()]


def _ensure_plan(con, plan_id: str) -> None:
    con.execute(
        "INSERT OR IGNORE INTO proxy_state (plan_id) VALUES (?)",
        (plan_id,),
    )


def _signal_counts(con, plan_id: str, now_ms: int) -> dict[str, int]:
    """Count recent error outcomes across all accounts.

    Phase 0 has a single TrumpProxies plan so every account is on it.
    When multiple plans exist, this query gets extended with a join on
    an accounts.proxy_plan_id column.
    """
    since = now_ms - WINDOW_ERR_MS
    neterr = con.execute(
        "SELECT COUNT(*) FROM action_results "
        "WHERE outcome = 'network_error' AND ts_ms >= ?",
        (since,),
    ).fetchone()[0]
    ratel = con.execute(
        "SELECT COUNT(*) FROM action_results "
        "WHERE outcome = 'ig_rate_limited' AND ts_ms >= ?",
        (since,),
    ).fetchone()[0]
    recent = con.execute(
        "SELECT COUNT(*) FROM action_results "
        "WHERE outcome NOT IN ('ok') AND ts_ms >= ?",
        (now_ms - WINDOW_HEAL_MS,),
    ).fetchone()[0]
    return {"neterr": int(neterr), "ratel": int(ratel), "any_err_24h": int(recent)}


def evaluate_plan(con, plan: dict, now_ms: int) -> dict | None:
    counts = _signal_counts(con, plan["plan_id"], now_ms)
    last_rotate = plan.get("last_rotate_ms") or 0
    cooldown_ok = (now_ms - last_rotate) >= COOLDOWN_MS

    if cooldown_ok and (
        counts["neterr"] >= NETERR_THRESHOLD
        or counts["ratel"] >= RATELIMIT_THRESHOLD
    ):
        return {
            "plan_id": plan["plan_id"],
            "decision": "rotate",
            "reason": f"neterr={counts['neterr']} ratel={counts['ratel']}",
        }
    if counts["any_err_24h"] == 0 and (plan.get("blocked_count") or 0) > 0:
        return {
            "plan_id": plan["plan_id"],
            "decision": "heal",
            "reason": "no_err_24h",
        }
    return None


def run(apply: bool, now_ms: int | None = None,
        plan_ids: list[str] | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else _store.now_ms()
    _store.apply_migrations()
    decisions: list[dict] = []
    with instrument("proxy", apply=apply) as rec:
        rec["now_ms"] = now_ms
        with _store.connect() as con:
            for pid in plan_ids or []:
                _ensure_plan(con, pid)
            if _replay is not None:
                rec["inputs"] = _replay.snapshot_inputs(con, "proxy")
            for plan in _plans(con):
                d = evaluate_plan(con, plan, now_ms)
                if not d:
                    continue
                decisions.append(d)
                if not apply:
                    continue
                if d["decision"] == "rotate":
                    con.execute(
                        "UPDATE proxy_state SET "
                        "blocked_count = blocked_count + 1, "
                        "last_rotate_ms = ?, last_block_ms = ?, "
                        "notes = ? WHERE plan_id = ?",
                        (now_ms, now_ms, d["reason"], d["plan_id"]),
                    )
                elif d["decision"] == "heal":
                    con.execute(
                        "UPDATE proxy_state SET "
                        "blocked_count = MAX(0, blocked_count - 1) "
                        "WHERE plan_id = ?",
                        (d["plan_id"],),
                    )
        rec["decisions"] = {"decisions": decisions}
    return {"now_ms": now_ms, "apply": apply, "decisions": decisions,
            "tick_id": rec.get("tick_id"),
            "chain_head": rec.get("chain_head")}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now-ms", type=int)
    ap.add_argument("--register", action="append", default=[],
                    help="plan_id to register (idempotent)")
    args = ap.parse_args()

    out = run(apply=args.apply, now_ms=args.now_ms, plan_ids=args.register)
    print(f"proxy @ {out['now_ms']}  apply={out['apply']}")
    print(f"  decisions : {len(out['decisions'])}")
    for d in out["decisions"][:20]:
        print(f"    {d['plan_id']:<20} {d['decision']:<8} {d['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
