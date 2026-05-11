"""
PhoneRepository — CRUD for the phones table.

Schema key points (from 001_initial_schema.sql):
    phones(id, farm_id, serial, model, android_version, locale, timezone,
           state, assigned_persona_id, wifi_ip, last_seen_at, metadata JSONB)

Device-specific identifiers (android_id, advertising_id, carrier_name,
carrier_mcc_mnc, proxy_verified) are stored in the metadata JSONB column
because they are device-level details extracted after provisioning and are
not part of the core identity columns.

All queries are parameterised — no string interpolation.
All methods return plain dicts (asyncpg Record objects are dict-compatible
but we convert explicitly for type clarity).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg


class PhoneRepository:
    """
    Async repository for the `phones` table.

    Args:
        pool: An asyncpg Pool or a single Connection.  Passing a Connection
              is useful inside an explicit transaction.  Passing a Pool
              lets the repository acquire/release connections automatically.
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
        """Convert an asyncpg Record to a plain dict, or return None."""
        if record is None:
            return None
        return dict(record)

    @staticmethod
    def _rows(records: list[asyncpg.Record]) -> list[dict]:
        return [dict(r) for r in records]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_all(self) -> list[dict]:
        """Return all phones ordered by serial."""
        rows = await self._fetch(
            "SELECT * FROM phones ORDER BY serial"
        )
        return self._rows(rows)

    async def get_by_serial(self, serial: str) -> dict | None:
        """Return a phone by its ADB serial, or None if not found."""
        row = await self._fetchrow(
            "SELECT * FROM phones WHERE serial = $1",
            serial,
        )
        return self._row(row)

    async def get_by_id(self, phone_id: str) -> dict | None:
        """Return a phone by its primary-key id, or None if not found."""
        row = await self._fetchrow(
            "SELECT * FROM phones WHERE id = $1",
            phone_id,
        )
        return self._row(row)

    async def get_ready_phones(self) -> list[dict]:
        """
        Return phones where state = 'proxy_ready'.

        These are the only phones that should have actions dispatched to them.
        The proxy safety gate in PhoneController enforces this at runtime;
        this query provides the fleet-level view for the scheduler.
        """
        rows = await self._fetch(
            "SELECT * FROM phones WHERE state = 'proxy_ready' ORDER BY serial"
        )
        return self._rows(rows)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def upsert(
        self,
        serial: str,
        *,
        farm_id: str,
        model: str | None = None,
        android_version: str | None = None,
        android_id: str | None = None,
        advertising_id: str | None = None,
        carrier_name: str | None = None,
        carrier_mcc_mnc: str | None = None,
        timezone: str = "America/New_York",
        locale: str = "en-US",
        state: str = "idle",
        wifi_ip: str | None = None,
        proxy_verified: bool = False,
        extra_metadata: dict | None = None,
    ) -> dict:
        """
        Insert or update a phone row.

        Device-level identifiers (android_id, advertising_id, carrier_*)
        are stored in the metadata JSONB column.  The caller can pass
        additional key-value pairs via extra_metadata to store alongside them.

        Returns the resulting row as a dict.
        """
        # Build metadata JSONB from device identifiers + caller extras
        metadata: dict[str, Any] = {}
        if android_id is not None:
            metadata["android_id"] = android_id
        if advertising_id is not None:
            metadata["advertising_id"] = advertising_id
        if carrier_name is not None:
            metadata["carrier_name"] = carrier_name
        if carrier_mcc_mnc is not None:
            metadata["carrier_mcc_mnc"] = carrier_mcc_mnc
        metadata["proxy_verified"] = proxy_verified
        if extra_metadata:
            metadata.update(extra_metadata)

        phone_id = str(uuid.uuid4())

        row = await self._fetchrow(
            """
            INSERT INTO phones (
                id, farm_id, serial, model, android_version,
                locale, timezone, state, wifi_ip, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (serial) DO UPDATE SET
                model            = EXCLUDED.model,
                android_version  = EXCLUDED.android_version,
                locale           = EXCLUDED.locale,
                timezone         = EXCLUDED.timezone,
                state            = EXCLUDED.state,
                wifi_ip          = EXCLUDED.wifi_ip,
                metadata         = phones.metadata || EXCLUDED.metadata,
                last_seen_at     = now()
            RETURNING *
            """,
            phone_id,
            farm_id,
            serial,
            model,
            android_version,
            locale,
            timezone,
            state,
            wifi_ip,
            json.dumps(metadata),
        )
        return self._row(row)  # type: ignore[return-value]

    async def update_state(self, serial: str, state: str) -> None:
        """Update a phone's state column and last_seen_at."""
        await self._execute(
            """
            UPDATE phones
            SET state = $1, last_seen_at = now()
            WHERE serial = $2
            """,
            state,
            serial,
        )

    async def update_proxy_status(self, serial: str, verified: bool) -> None:
        """
        Set the proxy_verified flag inside the metadata JSONB.

        Uses Postgres's jsonb merge operator (||) so that other metadata
        keys are preserved.
        """
        await self._execute(
            """
            UPDATE phones
            SET metadata = metadata || jsonb_build_object('proxy_verified', $1::boolean),
                last_seen_at = now()
            WHERE serial = $2
            """,
            verified,
            serial,
        )

    async def delete(self, serial: str) -> None:
        """Delete a phone record by serial. Cascades are handled by the DB."""
        await self._execute(
            "DELETE FROM phones WHERE serial = $1",
            serial,
        )
