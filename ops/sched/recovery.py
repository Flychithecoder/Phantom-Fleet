"""Deterministic recovery state machine.

Replaces the "Recovery Agent" entirely.  Zero LLM calls.

Input : the last N action_results for every account whose status is
        'alive' or 'unknown'.
Output: zero or more status transitions on those accounts.

Rules (in priority order; first match wins per account):

  R1  3 consecutive 'login_required' outcomes within 24h
       -> transition to 'needs_reset' with reason='r1_login_required_3x'

  R2  any 'checkpoint' or 'account_disabled' outcome in the last 24h
       -> transition to 'dead' with reason='r2_checkpoint'

  R3  5 consecutive 'network_error' outcomes within 2h
       AND no proxy rotation has happened in that window
       -> emit a proxy rotate signal (handled in proxy.py) + stay alive

  R4  no successful action in the last 48h on an 'alive' account that
       received >= 10 scheduled actions
       -> transition to 'needs_reset' with reason='r4_silent_48h'

  R5  5 consecutive 'ok' outcomes after a 'needs_reset' status
       -> transition back to 'alive' with reason='r5_self_healed'

Everything is deterministic; "consecutive" is measured against the
chronological action_results tail.  No fuzzy matching, no judgment.
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


WINDOW_LOGIN_MS = 24 * 3600 * 1000
WINDOW_NETERR_MS = 2 * 3600 * 1000
WINDOW_SILENT_MS = 48 * 3600 * 1000


def _tail(con, account_id: int, since_ms: int) -> list[dict]:
    rows = con.execute(
        "SELECT outcome, ts_ms FROM action_results "
        "WHERE account_id = ? AND ts_ms >= ? "
        "ORDER BY ts_ms DESC LIMIT 50",
        (account_id, since_ms),
    ).fetchall()
    return [dict(r) for r in rows]


def _consecutive_prefix(tail: list[dict], outcome: str) -> int:
    count = 0
    for r in tail:
        if r["outcome"] == outcome:
            count += 1
        else:
            break
    return count


def evaluate_account(con, account: dict, now_ms: int) -> dict | None:
    """Return a transition dict or None."""
    aid = account["id"]
    status = account["status"]

    tail_24h = _tail(con, aid, now_ms - WINDOW_LOGIN_MS)
    tail_2h = _tail(con, aid, now_ms - WINDOW_NETERR_MS)

    # R2 beats everything else.
    for r in tail_24h:
        if r["outcome"] in ("checkpoint", "account_disabled"):
            return {"status": "dead", "reason": "r2_checkpoint"}

    # R1 only applies if currently alive.
    if status == "alive":
        if _consecutive_prefix(tail_24h, "login_required") >= 3:
            return {"status": "needs_reset", "reason": "r1_login_required_3x"}

    # R3 emits a proxy signal, not an account transition.
    if status == "alive":
        if _consecutive_prefix(tail_2h, "network_error") >= 5:
            return {"status": "alive", "reason": "r3_proxy_rotate_signal",
                    "proxy_signal": True}

    # R4 — silent-but-scheduled.
    if status == "alive":
        last_ok = con.execute(
            "SELECT MAX(ts_ms) FROM action_results "
            "WHERE account_id = ? AND outcome = 'ok'",
            (aid,),
        ).fetchone()[0]
        scheduled = con.execute(
            "SELECT COUNT(*) FROM action_queue "
            "WHERE account_id = ? AND created_ms >= ?",
            (aid, now_ms - WINDOW_SILENT_MS),
        ).fetchone()[0]
        if scheduled >= 10 and (last_ok is None or last_ok < now_ms - WINDOW_SILENT_MS):
            return {"status": "needs_reset", "reason": "r4_silent_48h"}

    # R5 — self-heal.
    if status == "needs_reset":
        if _consecutive_prefix(tail_24h, "ok") >= 5:
            return {"status": "alive", "reason": "r5_self_healed"}

    return None


def run(apply: bool, now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else _store.now_ms()
    _store.apply_migrations()
    transitions: list[dict] = []
    proxy_signals: list[dict] = []

    with instrument("recovery", apply=apply) as rec:
        rec["now_ms"] = now_ms
        with _store.connect() as con:
            if _replay is not None:
                rec["inputs"] = _replay.snapshot_inputs(con, "recovery")
            rows = con.execute(
                "SELECT id, username, status FROM accounts "
                "WHERE status IN ('alive', 'needs_reset', 'unknown') "
                "ORDER BY id"
            ).fetchall()
            for row in rows:
                acct = dict(row)
                decision = evaluate_account(con, acct, now_ms)
                if not decision:
                    continue
                if decision.get("proxy_signal"):
                    proxy_signals.append({"account_id": acct["id"],
                                          "reason": decision["reason"]})
                    continue
                if decision["status"] == acct["status"]:
                    continue
                transitions.append({
                    "account_id": acct["id"],
                    "username": acct["username"],
                    "from": acct["status"],
                    "to": decision["status"],
                    "reason": decision["reason"],
                })
                if apply:
                    _store.transition_status(
                        con, acct["id"], decision["status"], decision["reason"],
                    )
        rec["decisions"] = {"transitions": transitions,
                            "proxy_signals": proxy_signals}

    return {
        "now_ms": now_ms, "apply": apply,
        "transitions": transitions, "proxy_signals": proxy_signals,
        "tick_id": rec.get("tick_id"),
        "chain_head": rec.get("chain_head"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now-ms", type=int)
    args = ap.parse_args()

    out = run(apply=args.apply, now_ms=args.now_ms)
    print(f"recovery @ {out['now_ms']}  apply={out['apply']}")
    print(f"  transitions   : {len(out['transitions'])}")
    print(f"  proxy signals : {len(out['proxy_signals'])}")
    for t in out["transitions"][:20]:
        print(f"    acct#{t['account_id']:<4} {t['username'][:20]:<20} "
              f"{t['from']:<12} -> {t['to']:<12} {t['reason']}")
    for s in out["proxy_signals"][:20]:
        print(f"    PROXY acct#{s['account_id']} {s['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
