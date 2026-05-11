"""
ActionLogRepository — write-only event log for all executed agent actions.

Schema (from 001_initial_schema.sql):
    action_log(id BIGSERIAL PK, account_id, agent_name, action_type,
               target_username, phone_serial, proxy_ip, queued_at,
               executed_at, status TEXT, error, metadata JSONB)

Per the global agent-audit rule, every action is written to this table
BEFORE execution (status='queued') and updated AFTER execution
(status='success'|'failed').  log_action() is a convenience wrapper that
writes a fully-resolved row in a single INSERT for callers that record
outcomes synchronously.

get_daily_totals() computes action counts grouped by action_type for one
account on one day — used by the WarmingAgent to enforce daily limits.
"""
from __future__ import annotations

import json
from datetime import date, timezone
from typing import Any

import asyncpg


class ActionLogRepository:
    """
    Async repository for the `action_log` table.

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

    async def _execute(self, query: str, *args: Any) -> None:
        if isinstance(self._pool, asyncpg.Connection):
            await self._pool.execute(query, *args)
        else:
            async with self._pool.acquire() as conn:
                await conn.execute(query, *args)

    @staticmethod
    def _rows(records: list[asyncpg.Record]) -> list[dict]:
        return [dict(r) for r in records]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def log_action(
        self,
        account_id: str,
        platform: str,
        action_type: str,
        target_id: str | None,
        success: bool,
        error: str | None = None,
        data: dict | None = None,
        *,
        agent_name: str = "unknown",
        phone_serial: str | None = None,
        proxy_ip: str | None = None,
    ) -> None:
        """
        Write a completed action to the log.

        Args:
            account_id:   The account that performed the action.
            platform:     Platform name — stored in metadata['platform'].
            action_type:  e.g. 'follow', 'like', 'story_view', 'dm', 'unfollow'.
            target_id:    Target username or media_id (stored as target_username).
            success:      True → status='success', False → status='failed'.
            error:        Error message string when success=False.
            data:         Arbitrary extra data merged into metadata JSONB.
            agent_name:   Name of the agent that executed the action.
            phone_serial: ADB serial of the phone that executed the action.
            proxy_ip:     Residential proxy IP used for the request.
        """
        status = "success" if success else "failed"
        metadata: dict[str, Any] = {"platform": platform}
        if data:
            metadata.update(data)

        await self._execute(
            """
            INSERT INTO action_log (
                account_id, agent_name, action_type, target_username,
                phone_serial, proxy_ip, executed_at, status, error, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, now(), $7, $8, $9)
            """,
            account_id,
            agent_name,
            action_type,
            target_id,
            phone_serial,
            proxy_ip,
            status,
            error,
            json.dumps(metadata),
        )

    async def log_queued(
        self,
        account_id: str,
        action_type: str,
        target_id: str | None = None,
        *,
        agent_name: str = "unknown",
        phone_serial: str | None = None,
        proxy_ip: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        """
        Write a 'queued' entry before execution starts.

        Returns the BIGSERIAL id so the caller can update to success/failed.

        Per the agent-audit rule: every action is written BEFORE execution.
        """
        row = await self._fetchrow(
            """
            INSERT INTO action_log (
                account_id, agent_name, action_type, target_username,
                phone_serial, proxy_ip, status, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'queued', $7)
            RETURNING id
            """,
            account_id,
            agent_name,
            action_type,
            target_id,
            phone_serial,
            proxy_ip,
            json.dumps(metadata or {}),
        )
        return row["id"]  # type: ignore[index]

    async def resolve_queued(
        self,
        log_id: int,
        success: bool,
        error: str | None = None,
        data: dict | None = None,
    ) -> None:
        """
        Update a queued log entry with the outcome after execution completes.
        """
        status = "success" if success else "failed"
        extra = json.dumps(data or {})
        await self._execute(
            """
            UPDATE action_log
            SET status      = $1,
                error       = $2,
                executed_at = now(),
                metadata    = metadata || $3::jsonb
            WHERE id = $4
            """,
            status,
            error,
            extra,
            log_id,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_recent(self, account_id: str, limit: int = 50) -> list[dict]:
        """Return the most recent N action log entries for an account."""
        rows = await self._fetch(
            """
            SELECT * FROM action_log
            WHERE account_id = $1
            ORDER BY queued_at DESC
            LIMIT $2
            """,
            account_id,
            limit,
        )
        return self._rows(rows)

    async def get_by_phone(
        self,
        phone_serial: str,
        date_iso: str,
        limit: int = 200,
    ) -> list[dict]:
        """
        Return action log entries for a specific phone on a specific date.

        date_iso: 'YYYY-MM-DD' in local time (stored as UTC in queued_at;
        comparison uses DATE(queued_at) which truncates to day in DB timezone).
        """
        rows = await self._fetch(
            """
            SELECT * FROM action_log
            WHERE phone_serial = $1
              AND DATE(queued_at AT TIME ZONE 'UTC') = $2::date
            ORDER BY queued_at DESC
            LIMIT $3
            """,
            phone_serial,
            date_iso,
            limit,
        )
        return self._rows(rows)

    async def get_daily_totals(self, account_id: str, date_iso: str) -> dict:
        """
        Return action counts by action_type for one account on one day.

        Returns a dict like:
            {"follow": 12, "unfollow": 2, "like": 34, "story_view": 18, "dm": 3}

        Only counts rows with status='success'.  Missing action types get 0.
        """
        rows = await self._fetch(
            """
            SELECT action_type, COUNT(*) AS cnt
            FROM action_log
            WHERE account_id = $1
              AND DATE(queued_at AT TIME ZONE 'UTC') = $2::date
              AND status = 'success'
            GROUP BY action_type
            """,
            account_id,
            date_iso,
        )

        # Build dict with all standard action types initialised to 0
        totals: dict[str, int] = {
            "follow":      0,
            "unfollow":    0,
            "like":        0,
            "story_view":  0,
            "dm":          0,
            "comment":     0,
        }
        for row in rows:
            totals[row["action_type"]] = int(row["cnt"])

        return totals
