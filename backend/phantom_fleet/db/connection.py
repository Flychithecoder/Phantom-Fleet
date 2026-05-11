"""
AsyncPG connection pool setup for Phantom Fleet.

Usage:
    from phantom_fleet.db.connection import get_pool, get_conn, ping_db, run_migrations

    # At application startup:
    pool = await get_pool()

    # In a route / agent:
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT 1")

    # Health check:
    ok = await ping_db()
"""
from __future__ import annotations

import os
import pathlib
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


# ---------------------------------------------------------------------------
# Module-level singleton pool
# ---------------------------------------------------------------------------

_pool: asyncpg.Pool | None = None

# Path to the migrations directory (one level above this package, at backend/)
_MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent.parent / "migrations"


# ---------------------------------------------------------------------------
# Pool lifecycle
# ---------------------------------------------------------------------------


async def get_pool() -> asyncpg.Pool:
    """
    Return the shared connection pool, creating it on first call.

    Reads DATABASE_URL from the environment. Expected format:
        postgresql://user:password@host:port/dbname

    The pool is intentionally a module-level singleton — call this freely
    from any coroutine; the pool is only created once.
    """
    global _pool
    if _pool is None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Set it to a valid asyncpg DSN before calling get_pool()."
            )
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
            # Decode JSONB columns as Python dicts automatically
            init=_init_connection,
        )
    return _pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Configure each new connection in the pool."""
    await conn.set_type_codec(
        "jsonb",
        encoder=_jsonb_encoder,
        decoder=_jsonb_decoder,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=_jsonb_encoder,
        decoder=_jsonb_decoder,
        schema="pg_catalog",
    )


def _jsonb_encoder(value: dict | list | None) -> str:
    import json
    return json.dumps(value)


def _jsonb_decoder(value: str) -> dict | list | None:
    import json
    return json.loads(value)


async def close_pool() -> None:
    """Gracefully close the pool. Call at application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# Connection context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """
    Async context manager that yields a connection from the pool.

    Usage:
        async with get_conn() as conn:
            row = await conn.fetchrow("SELECT $1::int", 42)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


async def run_migrations() -> list[str]:
    """
    Apply all SQL migration files from the migrations/ directory in sorted order.

    Files must follow the naming convention: NNN_description.sql
    (e.g. 001_initial_schema.sql, 002_add_conversions.sql).

    Each file is applied as a single transaction. Files that have already been
    applied are tracked in a lightweight _schema_migrations table so re-running
    is idempotent.

    Returns:
        List of migration filenames that were applied (empty if nothing new).
    """
    async with get_conn() as conn:
        # Bootstrap the migrations tracking table if it doesn't exist yet
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        applied_rows = await conn.fetch("SELECT filename FROM _schema_migrations")
        applied: set[str] = {row["filename"] for row in applied_rows}

    if not _MIGRATIONS_DIR.exists():
        return []

    sql_files = sorted(
        f for f in _MIGRATIONS_DIR.iterdir()
        if f.suffix == ".sql" and re.match(r"^\d+_", f.name)
    )

    newly_applied: list[str] = []

    for sql_file in sql_files:
        if sql_file.name in applied:
            continue

        sql_content = sql_file.read_text(encoding="utf-8")

        async with get_conn() as conn:
            async with conn.transaction():
                await conn.execute(sql_content)
                await conn.execute(
                    "INSERT INTO _schema_migrations (filename) VALUES ($1)",
                    sql_file.name,
                )

        newly_applied.append(sql_file.name)

    return newly_applied


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


async def ping_db() -> bool:
    """
    Lightweight DB health check.

    Returns True if the database is reachable, False on any error.
    Safe to call from a /health endpoint without raising.
    """
    try:
        async with get_conn() as conn:
            val = await conn.fetchval("SELECT 1")
            return val == 1
    except Exception:
        return False
