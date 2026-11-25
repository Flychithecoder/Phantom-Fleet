"""Scheduler tick.

Pure function + CLI.  Reads account + persona state out of
persona-store.sqlite, computes the next 24h of (kind, due_ms) per
account, writes them to action_queue in one transaction.

This is the thing a cron job runs daily at ~04:30 local:
    python -m ops.sched.tick --apply

Everything is deterministic:
 - Skip accounts not in 'alive' status.
 - Skip accounts that already have due future actions beyond a
   lookahead horizon (default 24h) — no double-booking.
 - Advance warming_day by 1 for every account we scheduled for.
 - Record last_tick_ms.

No LLM calls.  No agents.  A tick that fails is retried by the next
cron fire; a tick that succeeds is idempotent across the day.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402
from ops.sched._telemetry import instrument  # noqa: E402
from ops.sched.warming import schedule_day, summarise  # noqa: E402

try:
    from ops.intel import replay as _replay  # noqa: E402
except ImportError:  # pragma: no cover
    _replay = None  # type: ignore


LOOKAHEAD_MS = 24 * 3600 * 1000


def accounts_due(con, now_ms: int, lookahead_ms: int = LOOKAHEAD_MS) -> list[dict]:
    """Return the accounts that need a fresh day's schedule.

    Criteria:
     - status = 'alive'
     - either no row in account_schedule_state, OR last_tick_ms older
       than lookahead_ms ago.
    """
    cutoff = now_ms - lookahead_ms
    rows = con.execute(
        """
        SELECT a.id, a.username, a.persona, a.device_serial,
               COALESCE(s.warming_day, 1) AS warming_day,
               s.last_tick_ms,
               COALESCE(p.diurnal_peak_hour_local, 14) AS peak_hour,
               COALESCE(p.timezone, 'America/New_York') AS tz
        FROM accounts a
        LEFT JOIN account_schedule_state s ON s.account_id = a.id
        LEFT JOIN persona_profiles p ON p.persona = a.persona
        WHERE a.status = 'alive'
          AND (s.last_tick_ms IS NULL OR s.last_tick_ms < ?)
        ORDER BY a.id
        """,
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def future_queued_count(con, account_id: int, now_ms: int) -> int:
    return int(con.execute(
        "SELECT COUNT(*) FROM action_queue "
        "WHERE account_id = ? AND state = 'due' AND due_ms > ?",
        (account_id, now_ms),
    ).fetchone()[0])


def tick(apply: bool, now_ms: int | None = None, limit: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else _store.now_ms()
    _store.apply_migrations()
    totals = {"accounts_considered": 0, "accounts_scheduled": 0,
              "actions_enqueued": 0, "skipped_already_queued": 0}
    per_account: list[dict] = []

    with instrument("scheduler", apply=apply) as rec:
        rec["now_ms"] = now_ms
        with _store.connect() as con:
            if _replay is not None:
                rec["inputs"] = _replay.snapshot_inputs(con, "scheduler")
            due = accounts_due(con, now_ms)
            if limit:
                due = due[:limit]
            for acct in due:
                totals["accounts_considered"] += 1
                if future_queued_count(con, acct["id"], now_ms) > 0:
                    totals["skipped_already_queued"] += 1
                    per_account.append({**acct, "skipped": "already_queued"})
                    continue
                actions = schedule_day(
                    warming_day=acct["warming_day"],
                    now_ms=now_ms,
                    persona_tz=acct["tz"],
                    peak_hour=acct["peak_hour"],
                )
                if apply:
                    for a in actions:
                        _store.enqueue(
                            con, acct["id"], a.kind, a.due_ms, a.params,
                        )
                    con.execute(
                        "INSERT INTO account_schedule_state "
                        "(account_id, warming_day, last_tick_ms) "
                        "VALUES (?, ?, ?) "
                        "ON CONFLICT(account_id) DO UPDATE SET "
                        "warming_day = excluded.warming_day, "
                        "last_tick_ms = excluded.last_tick_ms",
                        (acct["id"], acct["warming_day"] + 1, now_ms),
                    )
                totals["accounts_scheduled"] += 1
                totals["actions_enqueued"] += len(actions)
                per_account.append({**acct, **summarise(actions)})
        rec["decisions"] = {"totals": totals, "per_account": per_account}

    return {
        "now_ms": now_ms, "apply": apply,
        "totals": totals, "per_account": per_account,
        "tick_id": rec.get("tick_id"),
        "chain_head": rec.get("chain_head"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now-ms", type=int, help="override wall clock (testing)")
    ap.add_argument("--limit", type=int, help="first N accounts only")
    args = ap.parse_args()

    out = tick(apply=args.apply, now_ms=args.now_ms, limit=args.limit)
    t = out["totals"]
    print(f"scheduler tick @ {out['now_ms']}  apply={out['apply']}")
    print(f"  considered       : {t['accounts_considered']}")
    print(f"  scheduled        : {t['accounts_scheduled']}")
    print(f"  enqueued         : {t['actions_enqueued']}")
    print(f"  skipped (queued) : {t['skipped_already_queued']}")
    for row in out["per_account"][:10]:
        label = row.get("skipped") or (
            f"day={row['warming_day']} -> {row.get('total', 0)} actions "
            f"({row.get('by_kind', {})})"
        )
        print(f"    acct#{row['id']:<4} {row['username'][:20]:<20} {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
