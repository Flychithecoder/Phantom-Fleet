"""
ThreadsRepository — durable store for the Threads platform.

Writes four streams:
    * threads_funnel_events      (append on every FunnelEvent)
    * threads_health_snapshots   (append on every health scan)
    * threads_recovery_records   (upsert per enrolled account)
    * threads_ig_events          (append on every IG bus publish)

The repository is DESIGNED to be optional. Every call takes pool=None as
a valid state and silently no-ops. The in-memory tracker / monitor / agent
calls `await repo.*` in fire-and-forget asyncio tasks, so a DB that is
down (or doesn't exist) never blocks a hot path. The one time we DO want
to wait on the DB is startup, where `restore_*` reads prior state back
into memory before the agents start.

This gives us the shape the user asked for — Postgres persistence —
without wedging the app when Postgres is cold (which is the current
dev environment).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import asyncpg                                # type: ignore
except Exception:
    asyncpg = None                                # type: ignore[assignment]

log = logging.getLogger("phantom_fleet.db.threads_persistence")


class ThreadsRepository:
    """
    Durable backing store for Threads state. `pool=None` makes every
    method a no-op; the app is expected to run in that mode until the
    user brings Postgres up.
    """

    def __init__(self, pool: Any | None) -> None:
        self._pool = pool

    @property
    def enabled(self) -> bool:
        return self._pool is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _exec(self, query: str, *args: Any) -> None:
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(query, *args)
        except Exception:
            log.exception("ThreadsRepository exec failed: %s", query[:80])

    async def _fetch(self, query: str, *args: Any) -> list[dict]:
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]
        except Exception:
            log.exception("ThreadsRepository fetch failed: %s", query[:80])
            return []

    @staticmethod
    def _to_ts(iso_or_dt: str | datetime | None) -> Optional[datetime]:
        if iso_or_dt is None or iso_or_dt == "":
            return None
        if isinstance(iso_or_dt, datetime):
            return iso_or_dt
        try:
            return datetime.fromisoformat(iso_or_dt.replace("Z", "+00:00"))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Funnel events
    # ------------------------------------------------------------------

    async def record_funnel_event(self, ev: dict) -> None:
        await self._exec(
            """
            INSERT INTO threads_funnel_events
                (kind, threads_account_id, ig_account_id, action_id,
                 target, meta, ts)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            ev.get("kind"), ev.get("threads_account_id"),
            ev.get("ig_account_id"), ev.get("action_id"),
            ev.get("target", ""), ev.get("meta", {}),
            self._to_ts(ev.get("ts")) or datetime.now(timezone.utc),
        )

    async def restore_funnel_counters(self) -> dict[str, dict[str, int]]:
        """
        Reload per-account counters by grouping events by kind. Returns
        {account_id: {reply_posted: N, profile_view: N, ...}}.
        """
        rows = await self._fetch(
            """
            SELECT threads_account_id, kind, COUNT(*) AS n
            FROM threads_funnel_events
            GROUP BY threads_account_id, kind
            """
        )
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["threads_account_id"], {})[r["kind"]] = int(r["n"])
        return out

    async def recent_funnel_events(self, limit: int = 100) -> list[dict]:
        return await self._fetch(
            """
            SELECT kind, threads_account_id, ig_account_id, action_id,
                   target, ts
            FROM threads_funnel_events
            ORDER BY ts DESC
            LIMIT $1
            """,
            limit,
        )

    # ------------------------------------------------------------------
    # Health snapshots
    # ------------------------------------------------------------------

    async def record_health_snapshot(self, h: dict) -> None:
        await self._exec(
            """
            INSERT INTO threads_health_snapshots
                (account_id, status, score, flags, signals, computed_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            h["account_id"], h["status"], int(h["score"]),
            list(h.get("flags", [])), dict(h.get("signals", {})),
            self._to_ts(h.get("computed_at")) or datetime.now(timezone.utc),
        )

    async def recent_health_for(self, account_id: str,
                                 limit: int = 50) -> list[dict]:
        return await self._fetch(
            """
            SELECT status, score, flags, signals, computed_at
            FROM threads_health_snapshots
            WHERE account_id = $1
            ORDER BY computed_at DESC
            LIMIT $2
            """,
            account_id, limit,
        )

    # ------------------------------------------------------------------
    # Recovery records
    # ------------------------------------------------------------------

    async def upsert_recovery_record(self, r: dict) -> None:
        await self._exec(
            """
            INSERT INTO threads_recovery_records
                (account_id, phase, strikes, entered_at, cool_down_until,
                 original_warmup_day, rewarm_baseline_replies,
                 rewarm_actions_observed, graduated_at, retired_at, notes,
                 updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
            ON CONFLICT (account_id) DO UPDATE SET
                phase                   = EXCLUDED.phase,
                strikes                 = EXCLUDED.strikes,
                cool_down_until         = EXCLUDED.cool_down_until,
                rewarm_baseline_replies = EXCLUDED.rewarm_baseline_replies,
                rewarm_actions_observed = EXCLUDED.rewarm_actions_observed,
                graduated_at            = EXCLUDED.graduated_at,
                retired_at              = EXCLUDED.retired_at,
                notes                   = EXCLUDED.notes,
                updated_at              = now()
            """,
            r["account_id"], r["phase"], int(r["strikes"]),
            self._to_ts(r.get("entered_at")) or datetime.now(timezone.utc),
            self._to_ts(r.get("cool_down_until")),
            int(r.get("original_warmup_day", 1)),
            int(r.get("rewarm_baseline_replies", 0)),
            int(r.get("rewarm_actions_observed", 0)),
            self._to_ts(r.get("graduated_at")),
            self._to_ts(r.get("retired_at")),
            list(r.get("notes", [])),
        )

    async def restore_recovery_records(self) -> list[dict]:
        rows = await self._fetch(
            """
            SELECT account_id, phase, strikes, entered_at, cool_down_until,
                   original_warmup_day, rewarm_baseline_replies,
                   rewarm_actions_observed, graduated_at, retired_at, notes
            FROM threads_recovery_records
            """
        )
        # Normalize datetimes to ISO so the in-memory dataclasses can
        # rehydrate with the same shape they were serialized from.
        out: list[dict] = []
        for r in rows:
            out.append({
                "account_id":              r["account_id"],
                "phase":                   r["phase"],
                "strikes":                 int(r["strikes"]),
                "entered_at":              r["entered_at"].isoformat() if r.get("entered_at") else "",
                "cool_down_until":         r["cool_down_until"].isoformat() if r.get("cool_down_until") else "",
                "original_warmup_day":     int(r["original_warmup_day"]),
                "rewarm_baseline_replies": int(r["rewarm_baseline_replies"]),
                "rewarm_actions_observed": int(r["rewarm_actions_observed"]),
                "graduated_at":            r["graduated_at"].isoformat() if r.get("graduated_at") else None,
                "retired_at":              r["retired_at"].isoformat() if r.get("retired_at") else None,
                "notes":                   list(r.get("notes") or []),
            })
        return out

    # ------------------------------------------------------------------
    # IG bus events
    # ------------------------------------------------------------------

    async def record_ig_event(self, ev: dict) -> None:
        await self._exec(
            """
            INSERT INTO threads_ig_events
                (ig_account_id, post_id, caption, source, ts)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (ig_account_id, post_id) DO NOTHING
            """,
            ev["ig_account_id"], ev["post_id"], ev.get("caption", ""),
            ev.get("source", "manual"),
            self._to_ts(ev.get("ts")) or datetime.now(timezone.utc),
        )

    async def recent_ig_events(self, limit: int = 100) -> list[dict]:
        return await self._fetch(
            """
            SELECT ig_account_id, post_id, caption, source, ts
            FROM threads_ig_events
            ORDER BY ts DESC
            LIMIT $1
            """,
            limit,
        )

    # ------------------------------------------------------------------
    # Snapshot summary (for /status + drill page)
    # ------------------------------------------------------------------

    async def summary(self) -> dict:
        """Row counts across every Threads table — one DB round-trip."""
        if self._pool is None:
            return {"enabled": False, "funnel_events": 0, "health_snapshots": 0,
                    "recovery_records": 0, "ig_events": 0}
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM threads_funnel_events)    AS f,
                        (SELECT COUNT(*) FROM threads_health_snapshots) AS h,
                        (SELECT COUNT(*) FROM threads_recovery_records) AS r,
                        (SELECT COUNT(*) FROM threads_ig_events)        AS i
                    """
                )
            return {
                "enabled":          True,
                "funnel_events":    int(row["f"] if row else 0),
                "health_snapshots": int(row["h"] if row else 0),
                "recovery_records": int(row["r"] if row else 0),
                "ig_events":        int(row["i"] if row else 0),
            }
        except Exception:
            log.exception("ThreadsRepository summary failed")
            return {"enabled": True, "error": True, "funnel_events": 0,
                    "health_snapshots": 0, "recovery_records": 0,
                    "ig_events": 0}
