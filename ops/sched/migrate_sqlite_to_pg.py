"""One-shot migrator: SQLite persona-store -> Postgres 16.

Reads the live Phase-0 store at ``backend/.data/persona-store.sqlite``
(read-only — never writes to it), opens a Postgres connection using
the usual PF_PG_DSN / PG* env vars, runs the pg DDL, and copies every
row from every table in a single transaction.

Idempotent: every table is upserted on its primary key, so running the
migrator twice converges to the same state. ``ON CONFLICT DO NOTHING``
is the right call for rows that have no business mutating under us
(target_pool admissions, action_results history). For tables where the
SQLite side is the source of truth (accounts, action_queue, etc.) we
``ON CONFLICT DO UPDATE`` the non-key columns.

Usage::

    PF_PG_DSN=postgresql://.../phantom_fleet \\
        python -m ops.sched.migrate_sqlite_to_pg

    # or point at an alternate sqlite file:
    python -m ops.sched.migrate_sqlite_to_pg --sqlite /path/to/other.sqlite

After a successful copy the migrator re-synchronises the identity
sequences on every autoincrement table so the next INSERT doesn't
collide with a copied id.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from ops.sched import _store_pg

# Each entry: (table, primary-key tuple, columns-in-both,
#              conflict-strategy). "replace" = DO UPDATE SET <non-pk>;
# "ignore" = DO NOTHING.
_TABLES: list[tuple[str, tuple[str, ...], tuple[str, ...], str]] = [
    ("personas",
     ("name",),
     ("name", "mode", "settings_json", "imported_at_ms"),
     "replace"),
    ("devices",
     ("serial",),
     ("serial", "model", "region", "source", "imported_at_ms"),
     "replace"),
    ("accounts",
     ("id",),
     ("id", "username", "persona", "device_serial", "status",
      "imported_at_ms"),
     "replace"),
    ("warming_curves",
     ("day",),
     ("day", "follows_lo", "follows_hi", "likes_lo", "likes_hi",
      "stories_lo", "stories_hi", "comments_lo", "comments_hi"),
     "replace"),
    ("action_queue",
     ("id",),
     ("id", "account_id", "kind", "due_ms", "params_json", "state",
      "attempts", "created_ms", "claimed_ms"),
     "replace"),
    ("action_results",
     ("id",),
     ("id", "action_id", "account_id", "outcome", "latency_ms",
      "signal_json", "ts_ms"),
     "ignore"),
    ("proxy_state",
     ("plan_id",),
     ("plan_id", "in_use", "blocked_count", "last_rotate_ms",
      "last_block_ms", "notes"),
     "replace"),
    ("account_status_history",
     ("id",),
     ("id", "account_id", "status", "reason", "ts_ms"),
     "ignore"),
    ("replacements_needed",
     ("id",),
     ("id", "account_id", "reason", "emitted_ms", "fulfilled_ms"),
     "replace"),
    ("persona_profiles",
     ("persona",),
     ("persona", "diurnal_peak_hour_local", "timezone",
      "warming_anchor_day"),
     "replace"),
    ("account_schedule_state",
     ("account_id",),
     ("account_id", "warming_day", "last_tick_ms"),
     "replace"),
    ("clone_assignments",
     ("account_id",),
     ("account_id", "clone_package", "assigned_ms"),
     "replace"),
    ("device_endpoints",
     ("serial",),
     ("serial", "wifi_ip", "port", "last_seen_ms"),
     "replace"),
    ("target_pool",
     ("id",),
     ("id", "farm_id", "kind", "handle", "media_code", "tags_json",
      "locale", "status", "source", "imported_ms", "approved_by",
      "approved_ms", "rejected_reason"),
     "replace"),
    ("target_history",
     ("id",),
     ("id", "account_id", "target_id", "kind", "ts_ms", "outcome"),
     "ignore"),
    ("persona_tags",
     ("persona", "tag"),
     ("persona", "tag"),
     "ignore"),
    ("comment_pool",
     ("id",),
     ("id", "text", "niche", "status", "source", "imported_ms",
      "approved_by", "approved_ms", "last_picked_ms"),
     "replace"),
    ("device_farm",
     ("serial",),
     ("serial", "farm_id"),
     "replace"),
]

# Tables that use an auto-generated id; we resync pg sequences on
# these so autoincrement keeps climbing from the migrated max.
_IDENTITY_TABLES = [
    "accounts", "action_queue", "action_results",
    "account_status_history", "replacements_needed",
    "target_pool", "target_history", "comment_pool",
]


def _open_sqlite(path: Path) -> sqlite3.Connection:
    # URI + mode=ro keeps our promise that we never write the live file.
    uri = f"file:{path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _sqlite_has_column(sc: sqlite3.Connection, table: str, col: str) -> bool:
    for r in sc.execute(f"PRAGMA table_info({table})"):
        if r["name"] == col:
            return True
    return False


def _sqlite_has_table(sc: sqlite3.Connection, table: str) -> bool:
    row = sc.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _build_upsert(
    table: str, pk: Sequence[str], cols: Sequence[str], strategy: str,
) -> str:
    placeholders = ",".join(["%s"] * len(cols))
    col_list = ",".join(cols)
    pk_list = ",".join(pk)
    if strategy == "ignore" or len(cols) == len(pk):
        suffix = f"ON CONFLICT ({pk_list}) DO NOTHING"
    else:
        updates = ",".join(
            f"{c}=EXCLUDED.{c}" for c in cols if c not in pk
        )
        suffix = f"ON CONFLICT ({pk_list}) DO UPDATE SET {updates}"
    return f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) {suffix}"


def _copy_table(
    sc: sqlite3.Connection,
    pg_cur: Any,
    table: str,
    pk: Sequence[str],
    cols: Sequence[str],
    strategy: str,
) -> int:
    if not _sqlite_has_table(sc, table):
        return 0
    # Narrow to columns that actually exist in the sqlite side — tables
    # that pre-date the additive columns (claimed_ms, last_picked_ms)
    # don't have them yet, and we must still migrate the rest.
    present = tuple(c for c in cols if _sqlite_has_column(sc, table, c))
    if not present:
        return 0
    rows = sc.execute(
        f"SELECT {','.join(present)} FROM {table}"
    ).fetchall()
    if not rows:
        return 0
    stmt = _build_upsert(table, pk, present, strategy)
    pg_cur.executemany(stmt, [tuple(r) for r in rows])
    return len(rows)


def _resync_sequences(pg_cur: Any) -> None:
    for table in _IDENTITY_TABLES:
        pg_cur.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE((SELECT MAX(id) FROM {table}), 1),
                (SELECT MAX(id) IS NOT NULL FROM {table})
            )
            """
        )


def migrate(sqlite_path: Path, pg_dsn: str | None = None) -> dict[str, int]:
    """Copy every table under one Postgres transaction.

    Returns a count-per-table dict. Rollback-on-failure is guaranteed:
    psycopg's context manager commits on clean exit and rolls back on
    exception.
    """
    import psycopg  # local import so SQLite-only envs don't need it

    counts: dict[str, int] = {}
    _store_pg.apply_migrations(pg_dsn)
    sc = _open_sqlite(sqlite_path)
    try:
        with psycopg.connect(pg_dsn or _store_pg.STORE) as pc:
            with pc.cursor() as cur:
                for table, pk, cols, strat in _TABLES:
                    n = _copy_table(sc, cur, table, pk, cols, strat)
                    counts[table] = n
                _resync_sequences(cur)
            pc.commit()
    finally:
        sc.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--sqlite",
        default=None,
        help="Path to the SQLite persona-store "
             "(default: backend/.data/persona-store.sqlite)",
    )
    ap.add_argument(
        "--pg-dsn",
        default=None,
        help="Postgres DSN (default: PF_PG_DSN or PG* env vars)",
    )
    args = ap.parse_args(argv)

    sqlite_path = Path(args.sqlite) if args.sqlite else (
        Path(__file__).resolve().parent.parent.parent
        / "backend" / ".data" / "persona-store.sqlite"
    )
    if not sqlite_path.exists():
        print(f"SQLite store not found at {sqlite_path}", file=sys.stderr)
        return 2
    print(f"source : {sqlite_path}")
    print(f"target : {args.pg_dsn or _store_pg.STORE}")
    counts = migrate(sqlite_path, args.pg_dsn)
    total = sum(counts.values())
    print(f"copied : {total} rows")
    for t in sorted(counts):
        print(f"  {t:28s} {counts[t]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
