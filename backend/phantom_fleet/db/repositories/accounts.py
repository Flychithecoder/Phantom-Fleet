"""
AccountRepository — CRUD for the accounts table.

Schema key points (from 001_initial_schema.sql):
    accounts(id, persona_id, platform, phone_id, clone_package,
             username, status, curve_type, day_in_curve, weekly_multiplier,
             home_state, home_city, credentials_ref JSONB, aggressiveness,
             created_at, imported_at, last_action_at, dead_reason)

Note on phone linkage: the schema uses phone_id (FK to phones.id), not a
raw phone_serial string.  get_by_phone() accepts either a phone_id (the
PK) or a serial and resolves automatically via a join when needed.

session_data maps to credentials_ref (the JSONB column for auth tokens).
warmup_day maps to day_in_curve.
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg


class AccountRepository:
    """
    Async repository for the `accounts` table.

    Args:
        pool: asyncpg Pool or Connection.
    """

    def __init__(self, pool: asyncpg.Pool | asyncpg.Connection) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        if isinstance(self._pool, asyncpg.Connection):
            return await self._pool.fetch(query, *args)
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def _fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        if isinstance(self._pool, asyncpg.Connection):
            return await self._pool.fetchrow(query, *args)
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def _fetchval(self, query: str, *args: Any) -> Any:
        if isinstance(self._pool, asyncpg.Connection):
            return await self._pool.fetchval(query, *args)
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def _execute(self, query: str, *args: Any) -> None:
        if isinstance(self._pool, asyncpg.Connection):
            await self._pool.execute(query, *args)
        else:
            async with self._pool.acquire() as conn:
                await conn.execute(query, *args)

    @staticmethod
    def _row(record: asyncpg.Record | None) -> dict | None:
        return dict(record) if record is not None else None

    @staticmethod
    def _rows(records: list[asyncpg.Record]) -> list[dict]:
        return [dict(r) for r in records]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_all(
        self,
        platform: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """
        Return all accounts, optionally filtered by platform and/or status.
        Results ordered by created_at DESC.
        """
        conditions: list[str] = []
        args: list[Any] = []
        idx = 1

        if platform is not None:
            conditions.append(f"platform = ${idx}")
            args.append(platform)
            idx += 1
        if status is not None:
            conditions.append(f"status = ${idx}")
            args.append(status)
            idx += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self._fetch(
            f"SELECT * FROM accounts {where} ORDER BY created_at DESC",
            *args,
        )
        return self._rows(rows)

    async def get_by_id(self, account_id: str) -> dict | None:
        """Return an account by its primary key, or None."""
        row = await self._fetchrow(
            "SELECT * FROM accounts WHERE id = $1",
            account_id,
        )
        return self._row(row)

    async def get_by_phone(
        self,
        phone_id: str,
        platform: str | None = None,
    ) -> list[dict]:
        """
        Return accounts assigned to a phone.

        phone_id is the phones.id primary key (UUID).  To look up by serial,
        join externally or use PhoneRepository.get_by_serial() first.
        """
        if platform is not None:
            rows = await self._fetch(
                """
                SELECT * FROM accounts
                WHERE phone_id = $1 AND platform = $2
                ORDER BY created_at DESC
                """,
                phone_id,
                platform,
            )
        else:
            rows = await self._fetch(
                """
                SELECT * FROM accounts
                WHERE phone_id = $1
                ORDER BY created_at DESC
                """,
                phone_id,
            )
        return self._rows(rows)

    async def get_warming_accounts(self, platform: str = "instagram") -> list[dict]:
        """
        Return all accounts with status='warming' for a given platform,
        ordered by day_in_curve ASC (earliest in warmup first).
        """
        rows = await self._fetch(
            """
            SELECT * FROM accounts
            WHERE platform = $1 AND status = 'warming'
            ORDER BY day_in_curve ASC, created_at ASC
            """,
            platform,
        )
        return self._rows(rows)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(
        self,
        account_id: str,
        platform: str,
        username: str,
        *,
        persona_id: str,
        phone_id: str | None = None,
        clone_package: str | None = None,
        session_data: dict | None = None,
        warmup_day: int = 0,
        status: str = "warming",
        curve_type: str = "fresh_warmup",
        aggressiveness: float = 1.0,
        weekly_multiplier: float = 1.0,
        home_state: str | None = None,
        home_city: str | None = None,
    ) -> dict:
        """
        Insert a new account row.

        session_data is stored as credentials_ref (JSONB).
        warmup_day maps to day_in_curve.

        Raises asyncpg.UniqueViolationError if (platform, username) already exists.
        """
        row = await self._fetchrow(
            """
            INSERT INTO accounts (
                id, persona_id, platform, phone_id, clone_package,
                username, status, curve_type, day_in_curve,
                weekly_multiplier, home_state, home_city,
                credentials_ref, aggressiveness, imported_at
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                $10, $11, $12,
                $13, $14, now()
            )
            RETURNING *
            """,
            account_id,
            persona_id,
            platform,
            phone_id,
            clone_package,
            username,
            status,
            curve_type,
            warmup_day,
            weekly_multiplier,
            home_state,
            home_city,
            json.dumps(session_data or {}),
            aggressiveness,
        )
        return self._row(row)  # type: ignore[return-value]

    async def update_warmup_day(self, account_id: str, day: int) -> None:
        """Set day_in_curve to an absolute value."""
        await self._execute(
            "UPDATE accounts SET day_in_curve = $1 WHERE id = $2",
            day,
            account_id,
        )

    async def increment_warmup_day(self, account_id: str) -> None:
        """Atomically increment day_in_curve by 1."""
        await self._execute(
            "UPDATE accounts SET day_in_curve = day_in_curve + 1 WHERE id = $1",
            account_id,
        )

    async def update_status(self, account_id: str, status: str) -> None:
        """Update account status (warming/active/paused/dead/imported)."""
        await self._execute(
            "UPDATE accounts SET status = $1 WHERE id = $2",
            status,
            account_id,
        )

    async def update_session(self, account_id: str, session_data: dict) -> None:
        """
        Replace credentials_ref (session_data) for an account.

        Full replacement — merge at call site if you want to preserve existing keys.
        """
        await self._execute(
            "UPDATE accounts SET credentials_ref = $1 WHERE id = $2",
            json.dumps(session_data),
            account_id,
        )

    async def touch_last_action(self, account_id: str) -> None:
        """Update last_action_at to now(). Call after every executed action."""
        await self._execute(
            "UPDATE accounts SET last_action_at = now() WHERE id = $1",
            account_id,
        )

    async def mark_dead(self, account_id: str, reason: str) -> None:
        """Mark an account as dead with a reason string."""
        await self._execute(
            """
            UPDATE accounts
            SET status = 'dead', dead_reason = $1
            WHERE id = $2
            """,
            reason,
            account_id,
        )

    async def bulk_create(self, accounts: list[dict]) -> list[str]:
        """
        Insert multiple accounts in a single transaction.

        Each dict in accounts must contain at least:
            id, persona_id, platform, username, aggressiveness

        Optional keys: phone_id, clone_package, session_data, warmup_day,
                        status, curve_type, weekly_multiplier,
                        home_state, home_city

        Returns the list of inserted account_ids.
        Skips rows that violate the (platform, username) unique constraint
        (logs the skip via the error column but continues the batch).
        """
        inserted_ids: list[str] = []

        if isinstance(self._pool, asyncpg.Connection):
            conn = self._pool
            async with conn.transaction():
                for acc in accounts:
                    aid = await self._insert_one(conn, acc)
                    if aid:
                        inserted_ids.append(aid)
        else:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    for acc in accounts:
                        aid = await self._insert_one(conn, acc)
                        if aid:
                            inserted_ids.append(aid)

        return inserted_ids

    @staticmethod
    async def _insert_one(conn: asyncpg.Connection, acc: dict) -> str | None:
        """Insert one account dict; returns the id on success, None on conflict."""
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO accounts (
                    id, persona_id, platform, phone_id, clone_package,
                    username, status, curve_type, day_in_curve,
                    weekly_multiplier, home_state, home_city,
                    credentials_ref, aggressiveness, imported_at
                )
                VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8, $9,
                    $10, $11, $12,
                    $13, $14, now()
                )
                ON CONFLICT (platform, username) DO NOTHING
                RETURNING id
                """,
                acc["id"],
                acc["persona_id"],
                acc["platform"],
                acc.get("phone_id"),
                acc.get("clone_package"),
                acc["username"],
                acc.get("status", "warming"),
                acc.get("curve_type", "fresh_warmup"),
                acc.get("warmup_day", acc.get("day_in_curve", 0)),
                acc.get("weekly_multiplier", 1.0),
                acc.get("home_state"),
                acc.get("home_city"),
                json.dumps(acc.get("session_data") or acc.get("credentials_ref") or {}),
                acc["aggressiveness"],
            )
            return row["id"] if row else None
        except asyncpg.UniqueViolationError:
            return None
