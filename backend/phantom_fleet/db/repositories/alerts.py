"""
AlertRepository — raised-by-FingerprintMonitorAgent alerts.

Schema (from 001_initial_schema.sql):
    alerts(id TEXT PK DEFAULT gen_random_uuid(),
           severity TEXT,       -- low/medium/high/critical
           dimension TEXT,      -- which detection dimension triggered (e.g. 'ua_monoculture')
           description TEXT,    -- human-readable explanation
           affected_count INT,
           action TEXT,         -- monitor/pause_cohort/pause_all
           raised_at TIMESTAMPTZ,
           resolved_at TIMESTAMPTZ,
           metadata JSONB)

Spec mapping:
    title   → dimension  (short dimension label)
    message → description (full description)
    account_id / phone_serial → stored in metadata JSONB
    unread  ↔ resolved_at IS NULL

Unresolved = resolved_at IS NULL.
get_unread() returns all rows where resolved_at IS NULL.
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg


class AlertRepository:
    """
    Async repository for the `alerts` table.

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
    def _row(record: asyncpg.Record | None) -> dict | None:
        return dict(record) if record is not None else None

    @staticmethod
    def _rows(records: list[asyncpg.Record]) -> list[dict]:
        return [dict(r) for r in records]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create_alert(
        self,
        severity: str,
        title: str,
        message: str,
        account_id: str | None = None,
        phone_serial: str | None = None,
        *,
        action: str = "monitor",
        affected_count: int = 0,
        extra_metadata: dict | None = None,
    ) -> str:
        """
        Raise a new alert.

        Args:
            severity:      low / medium / high / critical
            title:         Short dimension label (maps to schema.dimension)
            message:       Full human-readable description (maps to schema.description)
            account_id:    Optional linked account (stored in metadata)
            phone_serial:  Optional linked phone (stored in metadata)
            action:        Recommended action: monitor / pause_cohort / pause_all
            affected_count: Number of accounts/phones affected
            extra_metadata: Any additional metadata to store

        Returns:
            The alert id (UUID string).
        """
        metadata: dict[str, Any] = {}
        if account_id is not None:
            metadata["account_id"] = account_id
        if phone_serial is not None:
            metadata["phone_serial"] = phone_serial
        if extra_metadata:
            metadata.update(extra_metadata)

        row = await self._fetchrow(
            """
            INSERT INTO alerts (
                severity, dimension, description,
                affected_count, action, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            severity,
            title,         # dimension column
            message,       # description column
            affected_count,
            action,
            json.dumps(metadata),
        )
        return row["id"]  # type: ignore[index]

    async def mark_read(self, alert_id: str) -> None:
        """
        Resolve a single alert by setting resolved_at = now().

        'Read' == 'resolved' in the Phantom Fleet schema.
        """
        await self._execute(
            """
            UPDATE alerts
            SET resolved_at = now()
            WHERE id = $1 AND resolved_at IS NULL
            """,
            alert_id,
        )

    async def mark_all_read(self) -> None:
        """Resolve all currently unresolved alerts."""
        await self._execute(
            """
            UPDATE alerts
            SET resolved_at = now()
            WHERE resolved_at IS NULL
            """
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_unread(self, limit: int = 50) -> list[dict]:
        """
        Return unresolved alerts (resolved_at IS NULL), newest first.

        'Unread' == unresolved in the Phantom Fleet schema.
        """
        rows = await self._fetch(
            """
            SELECT * FROM alerts
            WHERE resolved_at IS NULL
            ORDER BY raised_at DESC
            LIMIT $1
            """,
            limit,
        )
        return self._rows(rows)

    async def get_all(
        self,
        severity: str | None = None,
        include_resolved: bool = True,
        limit: int = 200,
    ) -> list[dict]:
        """
        Return alerts optionally filtered by severity and resolved status.

        Useful for the monitoring dashboard and historical analysis.
        """
        conditions: list[str] = []
        args: list[Any] = []
        idx = 1

        if severity is not None:
            conditions.append(f"severity = ${idx}")
            args.append(severity)
            idx += 1
        if not include_resolved:
            conditions.append("resolved_at IS NULL")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        args.append(limit)

        rows = await self._fetch(
            f"""
            SELECT * FROM alerts
            {where}
            ORDER BY raised_at DESC
            LIMIT ${idx}
            """,
            *args,
        )
        return self._rows(rows)

    async def get_by_id(self, alert_id: str) -> dict | None:
        """Return a single alert by id, or None."""
        row = await self._fetchrow(
            "SELECT * FROM alerts WHERE id = $1",
            alert_id,
        )
        return self._row(row)
