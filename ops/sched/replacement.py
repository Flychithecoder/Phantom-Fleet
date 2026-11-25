"""Deterministic replacement emitter.

Reads the accounts table for rows in 'dead' status that do not yet have
an open row in replacements_needed.  Emits one.  That's it.

The actual replacement (buy aged account, install into clone, run
account-setup) is out of scope here — a human operator or a content
job picks these up from the replacements_needed queue.

Zero LLM calls.  Pure SELECT -> INSERT.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402


def run(apply: bool, now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else _store.now_ms()
    _store.apply_migrations()
    emitted: list[dict] = []
    with _store.connect() as con:
        rows = con.execute(
            """
            SELECT a.id, a.username,
                   (SELECT reason FROM account_status_history h
                    WHERE h.account_id = a.id AND h.status = 'dead'
                    ORDER BY ts_ms DESC LIMIT 1) AS reason
            FROM accounts a
            WHERE a.status = 'dead'
              AND NOT EXISTS (
                  SELECT 1 FROM replacements_needed r
                  WHERE r.account_id = a.id AND r.fulfilled_ms IS NULL
              )
            ORDER BY a.id
            """
        ).fetchall()
        for row in rows:
            emitted.append({
                "account_id": row["id"],
                "username": row["username"],
                "reason": row["reason"] or "dead",
            })
            if apply:
                con.execute(
                    "INSERT INTO replacements_needed "
                    "(account_id, reason, emitted_ms) VALUES (?, ?, ?)",
                    (row["id"], row["reason"] or "dead", now_ms),
                )
    return {"now_ms": now_ms, "apply": apply, "emitted": emitted}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now-ms", type=int)
    args = ap.parse_args()

    out = run(apply=args.apply, now_ms=args.now_ms)
    print(f"replacement @ {out['now_ms']}  apply={out['apply']}")
    print(f"  emitted : {len(out['emitted'])}")
    for e in out["emitted"][:20]:
        print(f"    acct#{e['account_id']:<4} {e['username'][:20]:<20} {e['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
