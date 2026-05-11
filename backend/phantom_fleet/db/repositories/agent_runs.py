"""
AgentRunRepository — audit log for every agent execution.

Schema (from 001_initial_schema.sql):
    agent_runs(run_id TEXT PK, agent_name, started_at TIMESTAMPTZ,
               ended_at TIMESTAMPTZ, status, iterations INT,
               cost_usd REAL, inputs JSONB, outputs JSONB, error)

Per the global agent-audit rule (CLAUDE.md §AI agent audit depth, item 23):
    "Every agent action should write an audit log entry BEFORE executing,
     with the input, the plan, the reasoning, and the tool call.
     After execution, log the result."

Usage pattern:
    # Before execution:
    run_id = await repo.log_run(agent_name, started_at=now, ...)

    # After execution:
    await repo.complete_run(run_id, ended_at=now, success=True, result={...})

Or as a single write when outcome is already known:
    run_id = await repo.log_run(agent_name, started_at, ended_at, cost_usd, success, result)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg


class AgentRunRepository:
    """
    Async repository for the `agent_runs` table.

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
    # Write
    # ------------------------------------------------------------------

    async def log_run(
        self,
        agent_name: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        cost_usd: float = 0.0,
        success: bool = True,
        result: dict | None = None,
        *,
        iterations: int = 0,
        inputs: dict | None = None,
        error: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """
        Insert a complete agent run record.

        Args:
            agent_name:  Name of the agent (e.g. 'WarmingAgent', 'FingerprintMonitor').
            started_at:  When the run started.
            ended_at:    When the run finished (None = still running).
            cost_usd:    Total LLM cost in USD for this run.
            success:     True → status='success', False → status='failed'.
            result:      Stored as outputs JSONB.
            iterations:  Number of agent loop iterations executed.
            inputs:      Input parameters stored as inputs JSONB.
            error:       Error message if success=False.
            run_id:      Override the auto-generated UUID (for resuming a run).

        Returns:
            The run_id (UUID string) for the inserted row.
        """
        rid = run_id or str(uuid.uuid4())
        status = "success" if success else "failed"

        await self._execute(
            """
            INSERT INTO agent_runs (
                run_id, agent_name, started_at, ended_at,
                status, iterations, cost_usd,
                inputs, outputs, error
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            rid,
            agent_name,
            started_at,
            ended_at,
            status,
            iterations,
            cost_usd,
            json.dumps(inputs or {}),
            json.dumps(result or {}),
            error,
        )
        return rid

    async def start_run(
        self,
        agent_name: str,
        inputs: dict | None = None,
    ) -> str:
        """
        Write a 'running' entry before the agent starts executing.

        Returns the run_id.  Call complete_run() when done.
        This implements the "write BEFORE execution" requirement from
        the agent-audit rule.
        """
        rid = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)
        await self._execute(
            """
            INSERT INTO agent_runs (
                run_id, agent_name, started_at, status,
                iterations, cost_usd, inputs, outputs
            )
            VALUES ($1, $2, $3, 'running', 0, 0.0, $4, '{}')
            """,
            rid,
            agent_name,
            now,
            json.dumps(inputs or {}),
        )
        return rid

    async def complete_run(
        self,
        run_id: str,
        success: bool,
        cost_usd: float = 0.0,
        result: dict | None = None,
        error: str | None = None,
        iterations: int = 0,
    ) -> None:
        """Update a running run entry with its final outcome."""
        status = "success" if success else "failed"
        await self._execute(
            """
            UPDATE agent_runs
            SET ended_at    = now(),
                status      = $1,
                cost_usd    = $2,
                outputs     = $3::jsonb,
                error       = $4,
                iterations  = $5
            WHERE run_id = $6
            """,
            status,
            cost_usd,
            json.dumps(result or {}),
            error,
            iterations,
            run_id,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_recent_runs(
        self,
        agent_name: str,
        limit: int = 20,
    ) -> list[dict]:
        """Return the most recent N completed runs for one agent."""
        rows = await self._fetch(
            """
            SELECT * FROM agent_runs
            WHERE agent_name = $1
            ORDER BY started_at DESC
            LIMIT $2
            """,
            agent_name,
            limit,
        )
        return self._rows(rows)

    async def get_total_cost_today(self, agent_name: str | None = None) -> float:
        """
        Return total LLM cost_usd for today (UTC).

        If agent_name is None, returns cost across ALL agents.
        If agent_name is provided, returns cost only for that agent.
        """
        if agent_name is not None:
            val = await self._fetchval(
                """
                SELECT COALESCE(SUM(cost_usd), 0.0)
                FROM agent_runs
                WHERE agent_name = $1
                  AND DATE(started_at AT TIME ZONE 'UTC') = CURRENT_DATE
                """,
                agent_name,
            )
        else:
            val = await self._fetchval(
                """
                SELECT COALESCE(SUM(cost_usd), 0.0)
                FROM agent_runs
                WHERE DATE(started_at AT TIME ZONE 'UTC') = CURRENT_DATE
                """
            )
        return float(val) if val is not None else 0.0

    async def get_all_agent_summary(self) -> list[dict]:
        """
        Return one summary row per agent with:
            agent_name, last_run (timestamp), total_cost_today (float),
            success_rate (float 0.0-1.0), total_runs_today (int)

        Used by the Chief agent's dashboard and cost attribution.
        """
        rows = await self._fetch(
            """
            SELECT
                agent_name,
                MAX(started_at)                                              AS last_run,
                COALESCE(SUM(CASE
                    WHEN DATE(started_at AT TIME ZONE 'UTC') = CURRENT_DATE
                    THEN cost_usd ELSE 0 END), 0.0)                         AS total_cost_today,
                COUNT(*) FILTER (
                    WHERE DATE(started_at AT TIME ZONE 'UTC') = CURRENT_DATE
                )                                                            AS total_runs_today,
                ROUND(
                    COUNT(*) FILTER (WHERE status = 'success')::numeric
                    / NULLIF(COUNT(*), 0), 4
                )::float                                                     AS success_rate
            FROM agent_runs
            GROUP BY agent_name
            ORDER BY last_run DESC NULLS LAST
            """
        )
        return self._rows(rows)
