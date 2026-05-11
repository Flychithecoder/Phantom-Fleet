"""
DailyPlanRepository — persistence for the daily_plans table.

Schema (from 001_initial_schema.sql):
    daily_plans(id TEXT PK DEFAULT gen_random_uuid(), account_id,
                plan_date DATE, day_in_curve, curve_label,
                intensity_level, intensity_multiplier, weekly_multiplier,
                persona_aggressiveness, follows_target, likes_target,
                story_views_target, comments_target, dms_target,
                actions_executed, created_at)

The plan dict passed to save_plan() should mirror the DailyPlan dataclass
fields from phantom_fleet.core.warming_curve:
    day_in_curve, curve_label, intensity_level, intensity_multiplier,
    weekly_multiplier, persona_aggressiveness,
    follows, likes, story_views, comments, dms

*_target columns store the sampled ceiling values for the day.
actions_executed is updated by the WarmingAgent as actions complete.
"""
from __future__ import annotations

from typing import Any

import asyncpg


class DailyPlanRepository:
    """
    Async repository for the `daily_plans` table.

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

    async def save_plan(
        self,
        account_id: str,
        date_iso: str,
        plan: dict,
    ) -> None:
        """
        Persist a DailyPlan for one account on one date.

        plan dict keys (maps from DailyPlan dataclass):
            day_in_curve        → day_in_curve
            curve_label         → curve_label
            intensity_level     → intensity_level
            intensity_multiplier → intensity_multiplier
            weekly_multiplier   → weekly_multiplier
            persona_aggressiveness → persona_aggressiveness
            follows             → follows_target
            likes               → likes_target
            story_views         → story_views_target
            comments            → comments_target
            dms                 → dms_target

        Uses INSERT ... ON CONFLICT DO UPDATE so that re-planning the same
        day replaces the old plan (re-plan is idempotent; actions_executed
        is preserved if the plan is refreshed mid-day).
        """
        await self._execute(
            """
            INSERT INTO daily_plans (
                account_id, plan_date, day_in_curve, curve_label,
                intensity_level, intensity_multiplier, weekly_multiplier,
                persona_aggressiveness,
                follows_target, likes_target, story_views_target,
                comments_target, dms_target
            )
            VALUES (
                $1, $2::date, $3, $4,
                $5, $6, $7,
                $8,
                $9, $10, $11,
                $12, $13
            )
            ON CONFLICT (account_id, plan_date) DO UPDATE SET
                day_in_curve          = EXCLUDED.day_in_curve,
                curve_label           = EXCLUDED.curve_label,
                intensity_level       = EXCLUDED.intensity_level,
                intensity_multiplier  = EXCLUDED.intensity_multiplier,
                weekly_multiplier     = EXCLUDED.weekly_multiplier,
                persona_aggressiveness = EXCLUDED.persona_aggressiveness,
                follows_target        = EXCLUDED.follows_target,
                likes_target          = EXCLUDED.likes_target,
                story_views_target    = EXCLUDED.story_views_target,
                comments_target       = EXCLUDED.comments_target,
                dms_target            = EXCLUDED.dms_target
            """,
            account_id,
            date_iso,
            plan.get("day_in_curve", 0),
            plan.get("curve_label", ""),
            plan.get("intensity_level", "normal"),
            float(plan.get("intensity_multiplier", 1.0)),
            float(plan.get("weekly_multiplier", 1.0)),
            float(plan.get("persona_aggressiveness", 1.0)),
            int(plan.get("follows", plan.get("follows_target", 0))),
            int(plan.get("likes", plan.get("likes_target", 0))),
            int(plan.get("story_views", plan.get("story_views_target", 0))),
            int(plan.get("comments", plan.get("comments_target", 0))),
            int(plan.get("dms", plan.get("dms_target", 0))),
        )

    async def increment_executed(self, account_id: str, date_iso: str, count: int = 1) -> None:
        """Atomically increment actions_executed counter for one plan row."""
        await self._execute(
            """
            UPDATE daily_plans
            SET actions_executed = actions_executed + $1
            WHERE account_id = $2 AND plan_date = $3::date
            """,
            count,
            account_id,
            date_iso,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_plan(self, account_id: str, date_iso: str) -> dict | None:
        """Return the plan for one account on one date, or None if not found."""
        row = await self._fetchrow(
            """
            SELECT * FROM daily_plans
            WHERE account_id = $1 AND plan_date = $2::date
            """,
            account_id,
            date_iso,
        )
        return self._row(row)

    async def get_all_plans_for_date(
        self,
        date_iso: str,
        platform: str | None = None,
    ) -> list[dict]:
        """
        Return all plans for a given date, optionally filtered by platform.

        To filter by platform we join against the accounts table.
        When platform is None, no join is performed.
        """
        if platform is not None:
            rows = await self._fetch(
                """
                SELECT dp.*
                FROM daily_plans dp
                JOIN accounts a ON a.id = dp.account_id
                WHERE dp.plan_date = $1::date
                  AND a.platform = $2
                ORDER BY dp.account_id
                """,
                date_iso,
                platform,
            )
        else:
            rows = await self._fetch(
                """
                SELECT * FROM daily_plans
                WHERE plan_date = $1::date
                ORDER BY account_id
                """,
                date_iso,
            )
        return self._rows(rows)
