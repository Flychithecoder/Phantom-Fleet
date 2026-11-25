"""Shared store access for the deterministic state-machine stack.

Thin layer on top of SQLite.  Every mutation is small, explicit, and
transactional.  No ORM; no magic.  The whole farm's control plane
ultimately reduces to SELECT -> compute -> INSERT.

Phase 0 persistence target:
    backend/.data/persona-store.sqlite

Phase 1 swaps in Postgres.  The function signatures here stay the same;
the backing DSN changes.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator

STORE = (
    Path(__file__).resolve().parent.parent.parent
    / "backend" / ".data" / "persona-store.sqlite"
)

# Additive migrations.  Every ALTER is guarded with IF-NOT-EXISTS-style
# idempotency so `apply_migrations()` is safe on first run, re-run, and
# against a store already populated by the Onimator migration.
MIGRATIONS = [
    # Base schema (also created by 03_onimator_migrate.py; duplicated
    # here so the sched stack can bring up a store on its own).
    """
    CREATE TABLE IF NOT EXISTS personas (
        name TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        settings_json TEXT,
        imported_at_ms INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS devices (
        serial TEXT PRIMARY KEY,
        model TEXT, region TEXT,
        source TEXT NOT NULL,
        imported_at_ms INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        persona TEXT,
        device_serial TEXT,
        status TEXT NOT NULL DEFAULT 'unknown',
        imported_at_ms INTEGER NOT NULL,
        FOREIGN KEY (persona) REFERENCES personas(name),
        FOREIGN KEY (device_serial) REFERENCES devices(serial)
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_accounts_persona ON accounts(persona);",
    "CREATE INDEX IF NOT EXISTS ix_accounts_device  ON accounts(device_serial);",
    """
    CREATE TABLE IF NOT EXISTS warming_curves (
        day INTEGER PRIMARY KEY,
        follows_lo REAL NOT NULL, follows_hi REAL NOT NULL,
        likes_lo   REAL NOT NULL, likes_hi   REAL NOT NULL,
        stories_lo REAL NOT NULL, stories_hi REAL NOT NULL,
        comments_lo REAL NOT NULL, comments_hi REAL NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS action_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        due_ms INTEGER NOT NULL,
        params_json TEXT,
        state TEXT NOT NULL DEFAULT 'due',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_ms INTEGER NOT NULL,
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_action_queue_due ON action_queue(state, due_ms);",
    "CREATE INDEX IF NOT EXISTS ix_action_queue_account ON action_queue(account_id, due_ms);",
    """
    CREATE TABLE IF NOT EXISTS action_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        outcome TEXT NOT NULL,
        latency_ms INTEGER,
        signal_json TEXT,
        ts_ms INTEGER NOT NULL,
        FOREIGN KEY (action_id) REFERENCES action_queue(id),
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_action_results_account ON action_results(account_id, ts_ms);",
    """
    CREATE TABLE IF NOT EXISTS proxy_state (
        plan_id TEXT PRIMARY KEY,
        in_use INTEGER NOT NULL DEFAULT 0,
        blocked_count INTEGER NOT NULL DEFAULT 0,
        last_rotate_ms INTEGER,
        last_block_ms INTEGER,
        notes TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS account_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        reason TEXT,
        ts_ms INTEGER NOT NULL,
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_status_history ON account_status_history(account_id, ts_ms);",
    """
    CREATE TABLE IF NOT EXISTS replacements_needed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        emitted_ms INTEGER NOT NULL,
        fulfilled_ms INTEGER,
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );
    """,
    # Persona diurnal peak + warming anchor day (so the scheduler is a
    # pure function of (now, account row, persona row)).
    """
    CREATE TABLE IF NOT EXISTS persona_profiles (
        persona TEXT PRIMARY KEY,
        diurnal_peak_hour_local INTEGER NOT NULL DEFAULT 14,
        timezone TEXT NOT NULL DEFAULT 'America/New_York',
        warming_anchor_day INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (persona) REFERENCES personas(name)
    );
    """,
    # Each account carries its OWN warming day pointer.  The scheduler
    # advances this atomically with the day's actions.
    """
    CREATE TABLE IF NOT EXISTS account_schedule_state (
        account_id INTEGER PRIMARY KEY,
        warming_day INTEGER NOT NULL DEFAULT 1,
        last_tick_ms INTEGER,
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );
    """,
    # Dispatcher-facing: which clone package drives this account, and
    # where the device answers HTTP. Both nullable so Onimator migration
    # can land accounts before the dispatcher knows how to reach them.
    """
    CREATE TABLE IF NOT EXISTS clone_assignments (
        account_id INTEGER PRIMARY KEY,
        clone_package TEXT NOT NULL,
        assigned_ms INTEGER NOT NULL,
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS device_endpoints (
        serial TEXT PRIMARY KEY,
        wifi_ip TEXT,
        port INTEGER NOT NULL DEFAULT 8080,
        last_seen_ms INTEGER,
        FOREIGN KEY (serial) REFERENCES devices(serial)
    );
    """,
]


def apply_migrations(store: Path | None = None) -> None:
    store = store or STORE
    store.parent.mkdir(parents=True, exist_ok=True)
    with connect(store) as con:
        for stmt in MIGRATIONS:
            con.executescript(stmt)


@contextlib.contextmanager
def connect(store: Path | None = None) -> Iterator[sqlite3.Connection]:
    store = store or STORE
    con = sqlite3.connect(store)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def now_ms() -> int:
    return int(time.time() * 1000)


def transition_status(
    con: sqlite3.Connection, account_id: int, status: str, reason: str,
) -> None:
    con.execute(
        "UPDATE accounts SET status = ? WHERE id = ?",
        (status, account_id),
    )
    con.execute(
        "INSERT INTO account_status_history (account_id, status, reason, ts_ms) "
        "VALUES (?, ?, ?, ?)",
        (account_id, status, reason, now_ms()),
    )


def enqueue(
    con: sqlite3.Connection, account_id: int, kind: str,
    due_ms: int, params: dict[str, Any] | None = None,
) -> int:
    cur = con.execute(
        "INSERT INTO action_queue (account_id, kind, due_ms, params_json, created_ms) "
        "VALUES (?, ?, ?, ?, ?)",
        (account_id, kind, due_ms, json.dumps(params or {}), now_ms()),
    )
    return int(cur.lastrowid or 0)


def record_result(
    con: sqlite3.Connection, action_id: int, account_id: int,
    outcome: str, latency_ms: int | None = None,
    signal: dict[str, Any] | None = None,
) -> None:
    con.execute(
        "INSERT INTO action_results "
        "(action_id, account_id, outcome, latency_ms, signal_json, ts_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (action_id, account_id, outcome, latency_ms,
         json.dumps(signal or {}), now_ms()),
    )
    new_state = "done" if outcome == "ok" else "failed"
    con.execute(
        "UPDATE action_queue SET state = ?, attempts = attempts + 1 "
        "WHERE id = ?",
        (new_state, action_id),
    )
