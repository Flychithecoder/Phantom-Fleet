"""Target hydrator — fills missing target params on due action_queue rows.

Cron job, between `scheduler_tick` and `dispatch`:

    1. SELECT action_queue rows WHERE state='due' AND due_ms<=now
       AND params lack targetUsername/mediaCode/text/usernames.
    2. Call picker.pick_for(account, kind).
    3. Merge params; UPDATE action_queue.
    4. INSERT target_history row ('picked').
    5. If picker returns None (pool exhausted):
         - record target_history outcome='pool_exhausted'
         - UPDATE action_queue state='missing_target' so dispatcher
           drops the row with a terminal result (not retried).

Pure function. No network. No LLM. Deterministic: given the same
(queue, pool, history) state it produces the same outcome.

Usage:
    python -m ops.targets.hydrator --apply
    python -m ops.targets.hydrator --apply --max 200
    python -m ops.targets.hydrator --dry-run
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402
from ops.targets import picker  # noqa: E402


REQUIRED_KEYS = {
    "follows":   ("targetUsername",),
    "follow":    ("targetUsername",),
    "unfollow":  ("targetUsername",),
    "likes":     ("mediaCode",),
    "like":      ("mediaCode",),
    "comments":  ("mediaCode", "text"),
    "comment":   ("mediaCode", "text"),
    "stories":   ("usernames",),
    "story":     ("usernames",),
    "view_stories": ("usernames",),
}


def _load_account(con: sqlite3.Connection, account_id: int) -> dict | None:
    row = con.execute(
        """
        SELECT a.id, a.username, a.persona, a.device_serial, a.status,
               df.farm_id
        FROM accounts a
        LEFT JOIN device_farm df ON df.serial = a.device_serial
        LEFT JOIN personas p ON p.name = a.persona
        WHERE a.id = ?
        """,
        (account_id,),
    ).fetchone()
    if not row:
        return None
    # Locale lives on the persona settings_json; pull it lazily.
    locale = None
    if row["persona"]:
        p = con.execute(
            "SELECT settings_json FROM personas WHERE name = ?",
            (row["persona"],),
        ).fetchone()
        if p and p["settings_json"]:
            try:
                locale = json.loads(p["settings_json"]).get("locale")
            except Exception:
                pass
    return {
        "id": row["id"],
        "username": row["username"],
        "persona": row["persona"],
        "device_serial": row["device_serial"],
        "farm_id": row["farm_id"],
        "locale": locale,
    }


def _needs_hydration(kind: str, params: dict) -> bool:
    req = REQUIRED_KEYS.get(kind)
    if not req:
        return False
    for k in req:
        v = params.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            return True
        if isinstance(v, list) and not v:
            return True
    return False


def _due_rows(con: sqlite3.Connection, now_ms: int, limit: int) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT id, account_id, kind, params_json
        FROM action_queue
        WHERE state = 'due' AND due_ms <= ?
        ORDER BY due_ms ASC, id ASC
        LIMIT ?
        """,
        (now_ms, limit),
    ).fetchall()


def run(apply: bool = False, max_rows: int = 500) -> dict:
    now_ms = int(time.time() * 1000)
    _store.apply_migrations()

    stats = {
        "scanned": 0, "already_hydrated": 0, "hydrated": 0,
        "exhausted": 0, "account_missing": 0,
    }

    with _store.connect() as con:
        rows = _due_rows(con, now_ms, max_rows)
        stats["scanned"] = len(rows)

        for r in rows:
            try:
                params = json.loads(r["params_json"] or "{}")
            except Exception:
                params = {}
            kind = r["kind"]
            if not _needs_hydration(kind, params):
                stats["already_hydrated"] += 1
                continue

            account = _load_account(con, r["account_id"])
            if account is None:
                stats["account_missing"] += 1
                continue

            picked = picker.pick_for(con, account, kind, now_ms)
            if picked is None:
                stats["exhausted"] += 1
                if apply:
                    con.execute(
                        "UPDATE action_queue SET state='missing_target' "
                        "WHERE id = ?", (r["id"],),
                    )
                continue

            # Extract target ids before merging into stored params.
            target_id = picked.pop("_target_id", None)
            target_ids = picked.pop("_target_ids", None) or (
                [target_id] if target_id else []
            )
            params.update(picked)
            stats["hydrated"] += 1

            if apply:
                con.execute(
                    "UPDATE action_queue SET params_json = ? WHERE id = ?",
                    (json.dumps(params, sort_keys=True), r["id"]),
                )
                for tid in target_ids:
                    picker.record_touch(
                        con, account["id"], tid, kind, now_ms, "picked",
                    )
        if apply:
            con.commit()

    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=500)
    args = ap.parse_args()

    stats = run(apply=args.apply, max_rows=args.max)
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
