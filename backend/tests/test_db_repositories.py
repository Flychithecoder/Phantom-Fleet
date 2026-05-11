"""
Tests for phantom_fleet.db.repositories.*

All tests mock the asyncpg pool to avoid requiring a live database.
The mock pool's acquire() is an async context manager that yields a fake
connection.  Since we pass a MagicMock (not asyncpg.Connection), the
repositories take the pool branch and call pool.acquire().__aenter__(),
which correctly returns the fake inner connection.

Run with:
    pytest tests/test_db_repositories.py -v

Coverage (22 tests):
    - PhoneRepository:     upsert, get_by_serial, update_state, update_proxy_status,
                           get_ready_phones, delete, get_all
    - AccountRepository:   create, get_by_id, update_status, get_warming_accounts,
                           bulk_create, increment_warmup_day, get_by_phone
    - ActionLogRepository: log_action, get_recent, get_daily_totals, get_by_phone
    - DailyPlanRepository: save_plan, get_plan, get_all_plans_for_date
    - AgentRunRepository:  log_run, get_recent_runs, get_total_cost_today,
                           get_all_agent_summary
    - AlertRepository:     create_alert, get_unread, mark_read, mark_all_read
    - All repositories handle missing records gracefully (return None, not raise)
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from phantom_fleet.db.repositories.phones import PhoneRepository
from phantom_fleet.db.repositories.accounts import AccountRepository
from phantom_fleet.db.repositories.action_log import ActionLogRepository
from phantom_fleet.db.repositories.daily_plans import DailyPlanRepository
from phantom_fleet.db.repositories.agent_runs import AgentRunRepository
from phantom_fleet.db.repositories.alerts import AlertRepository


# ---------------------------------------------------------------------------
# Helpers — fake asyncpg Record and Pool
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """dict that quacks like an asyncpg Record."""
    pass


def make_pool(
    *,
    fetchrow_return: FakeRecord | None = None,
    fetch_return: list[FakeRecord] | None = None,
    fetchval_return: Any = None,
) -> MagicMock:
    """
    Build a mock asyncpg Pool whose acquire() yields a fake inner connection.

    All async methods on the inner connection (fetchrow, fetch, fetchval,
    execute) are AsyncMocks with preconfigured return values.

    We pass a MagicMock as the pool (not asyncpg.Pool or asyncpg.Connection)
    so the isinstance(pool, asyncpg.Connection) check inside repositories
    evaluates to False and the pool.acquire() branch executes.
    """
    # Inner connection
    inner = MagicMock()
    inner.fetchrow = AsyncMock(return_value=fetchrow_return)
    inner.fetch = AsyncMock(return_value=fetch_return or [])
    inner.fetchval = AsyncMock(return_value=fetchval_return)
    inner.execute = AsyncMock(return_value=None)

    # Transaction context manager (used by bulk_create)
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    inner.transaction = MagicMock(return_value=tx)

    # Pool-level acquire() async context manager
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=inner)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)

    # Expose inner so tests can assert on it
    pool._inner = inner
    return pool


# ---------------------------------------------------------------------------
# PhoneRepository
# ---------------------------------------------------------------------------


class TestPhoneRepository:
    """Tests for PhoneRepository."""

    def _make_phone_row(self, serial: str = "192.168.1.10:5555") -> FakeRecord:
        return FakeRecord({
            "id": str(uuid.uuid4()),
            "farm_id": "farm-001",
            "serial": serial,
            "model": "Samsung Galaxy S10 Lite",
            "android_version": "12",
            "locale": "en-US",
            "timezone": "America/New_York",
            "state": "proxy_ready",
            "assigned_persona_id": None,
            "wifi_ip": "192.168.1.10",
            "last_seen_at": datetime.now(tz=timezone.utc),
            "metadata": {"proxy_verified": True, "android_id": "abc123"},
        })

    @pytest.mark.asyncio
    async def test_get_by_serial_returns_dict(self) -> None:
        """get_by_serial should return a plain dict when the row exists."""
        row = self._make_phone_row()
        pool = make_pool(fetchrow_return=row)

        repo = PhoneRepository(pool)
        result = await repo.get_by_serial("192.168.1.10:5555")

        assert isinstance(result, dict)
        assert result["serial"] == "192.168.1.10:5555"
        assert result["state"] == "proxy_ready"

    @pytest.mark.asyncio
    async def test_get_by_serial_returns_none_when_missing(self) -> None:
        """get_by_serial should return None when no row found — not raise."""
        pool = make_pool(fetchrow_return=None)

        repo = PhoneRepository(pool)
        result = await repo.get_by_serial("does-not-exist")

        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_returns_dict(self) -> None:
        """upsert should INSERT/UPDATE and return the resulting row as a dict."""
        row = self._make_phone_row()
        pool = make_pool(fetchrow_return=row)

        repo = PhoneRepository(pool)
        result = await repo.upsert(
            "192.168.1.10:5555",
            farm_id="farm-001",
            model="Samsung Galaxy S10 Lite",
            android_version="12",
            android_id="abc123",
            state="proxy_ready",
        )

        assert isinstance(result, dict)
        assert result["serial"] == "192.168.1.10:5555"

        # Verify parameterised query: serial must NOT appear inline in the SQL
        query = pool._inner.fetchrow.call_args[0][0]
        assert "INSERT INTO phones" in query
        assert "$1" in query
        assert "192.168.1.10" not in query

    @pytest.mark.asyncio
    async def test_update_state_uses_parameterised_query(self) -> None:
        """update_state should execute an UPDATE with parameterised args."""
        pool = make_pool()

        repo = PhoneRepository(pool)
        await repo.update_state("192.168.1.10:5555", "busy")

        query, state, serial = pool._inner.execute.call_args[0]
        assert "UPDATE phones" in query
        assert state == "busy"
        assert serial == "192.168.1.10:5555"
        assert "busy" not in query      # must be a parameter, not inlined

    @pytest.mark.asyncio
    async def test_update_proxy_status_writes_metadata(self) -> None:
        """update_proxy_status should update metadata JSONB via parameterised UPDATE."""
        pool = make_pool()

        repo = PhoneRepository(pool)
        await repo.update_proxy_status("192.168.1.10:5555", verified=True)

        pool._inner.execute.assert_awaited_once()
        query = pool._inner.execute.call_args[0][0]
        assert "proxy_verified" in query
        assert "metadata" in query

    @pytest.mark.asyncio
    async def test_get_ready_phones_filters_by_state(self) -> None:
        """get_ready_phones should query only state = 'proxy_ready'."""
        rows = [
            self._make_phone_row("192.168.1.10:5555"),
            self._make_phone_row("192.168.1.11:5555"),
        ]
        pool = make_pool(fetch_return=rows)

        repo = PhoneRepository(pool)
        result = await repo.get_ready_phones()

        assert len(result) == 2
        assert all(isinstance(r, dict) for r in result)
        query = pool._inner.fetch.call_args[0][0]
        assert "proxy_ready" in query

    @pytest.mark.asyncio
    async def test_delete_uses_parameterised_serial(self) -> None:
        """delete should execute DELETE with serial as a parameter."""
        pool = make_pool()

        repo = PhoneRepository(pool)
        await repo.delete("192.168.1.10:5555")

        query, serial = pool._inner.execute.call_args[0]
        assert "DELETE FROM phones" in query
        assert serial == "192.168.1.10:5555"
        assert "192.168.1.10" not in query

    @pytest.mark.asyncio
    async def test_get_all_returns_list(self) -> None:
        """get_all should return a list of dicts."""
        rows = [self._make_phone_row("A"), self._make_phone_row("B")]
        pool = make_pool(fetch_return=rows)

        repo = PhoneRepository(pool)
        result = await repo.get_all()

        assert isinstance(result, list)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# AccountRepository
# ---------------------------------------------------------------------------


class TestAccountRepository:
    """Tests for AccountRepository."""

    def _make_account_row(self, account_id: str | None = None) -> FakeRecord:
        return FakeRecord({
            "id": account_id or str(uuid.uuid4()),
            "persona_id": str(uuid.uuid4()),
            "platform": "instagram",
            "phone_id": str(uuid.uuid4()),
            "clone_package": "com.instagram.android.clone1",
            "username": "test_user_123",
            "status": "warming",
            "curve_type": "fresh_warmup",
            "day_in_curve": 3,
            "weekly_multiplier": 1.0,
            "home_state": "California",
            "home_city": "Los Angeles",
            "credentials_ref": {"sessionid": "abc123"},
            "aggressiveness": 1.0,
            "created_at": datetime.now(tz=timezone.utc),
            "imported_at": datetime.now(tz=timezone.utc),
            "last_action_at": None,
            "dead_reason": None,
        })

    @pytest.mark.asyncio
    async def test_create_returns_dict(self) -> None:
        """create should INSERT and return the new account row as a dict."""
        aid = str(uuid.uuid4())
        pool = make_pool(fetchrow_return=self._make_account_row(aid))

        repo = AccountRepository(pool)
        result = await repo.create(
            aid,
            "instagram",
            "test_user_123",
            persona_id=str(uuid.uuid4()),
            session_data={"sessionid": "abc123"},
            warmup_day=3,
        )

        assert isinstance(result, dict)
        assert result["id"] == aid
        assert result["status"] == "warming"

        # session_data must not be inlined in SQL
        query = pool._inner.fetchrow.call_args[0][0]
        assert "abc123" not in query

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_when_missing(self) -> None:
        """get_by_id should return None gracefully when no account found."""
        pool = make_pool(fetchrow_return=None)

        repo = AccountRepository(pool)
        result = await repo.get_by_id("nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_status_parameterised(self) -> None:
        """update_status must pass status as a query parameter, not inlined."""
        pool = make_pool()

        repo = AccountRepository(pool)
        await repo.update_status("acct-001", "active")

        query, status, acct_id = pool._inner.execute.call_args[0]
        assert "UPDATE accounts" in query
        assert status == "active"
        assert acct_id == "acct-001"
        assert "active" not in query

    @pytest.mark.asyncio
    async def test_get_warming_accounts_filters_correctly(self) -> None:
        """get_warming_accounts should filter by status='warming' and platform."""
        rows = [self._make_account_row(), self._make_account_row()]
        pool = make_pool(fetch_return=rows)

        repo = AccountRepository(pool)
        result = await repo.get_warming_accounts(platform="instagram")

        assert len(result) == 2
        assert all(isinstance(r, dict) for r in result)
        query = pool._inner.fetch.call_args[0][0]
        assert "warming" in query

    @pytest.mark.asyncio
    async def test_increment_warmup_day_atomic(self) -> None:
        """increment_warmup_day should use atomic SQL addition (not read-then-write)."""
        pool = make_pool()

        repo = AccountRepository(pool)
        await repo.increment_warmup_day("acct-001")

        query, acct_id = pool._inner.execute.call_args[0]
        assert "day_in_curve + 1" in query
        assert acct_id == "acct-001"

    @pytest.mark.asyncio
    async def test_get_by_phone_returns_list(self) -> None:
        """get_by_phone should return a list of dicts for the given phone."""
        rows = [self._make_account_row()]
        pool = make_pool(fetch_return=rows)

        repo = AccountRepository(pool)
        result = await repo.get_by_phone("phone-uuid-001", platform="instagram")

        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_bulk_create_empty_list(self) -> None:
        """bulk_create with empty list should return [] without errors."""
        pool = make_pool()

        repo = AccountRepository(pool)
        result = await repo.bulk_create([])

        assert result == []


# ---------------------------------------------------------------------------
# ActionLogRepository
# ---------------------------------------------------------------------------


class TestActionLogRepository:
    """Tests for ActionLogRepository."""

    def _make_log_row(self, action_type: str = "follow") -> FakeRecord:
        return FakeRecord({
            "id": 1001,
            "account_id": "acct-001",
            "agent_name": "WarmingAgent",
            "action_type": action_type,
            "target_username": "target_user",
            "phone_serial": "192.168.1.10:5555",
            "proxy_ip": "1.2.3.4",
            "queued_at": datetime.now(tz=timezone.utc),
            "executed_at": datetime.now(tz=timezone.utc),
            "status": "success",
            "error": None,
            "metadata": {"platform": "instagram"},
        })

    @pytest.mark.asyncio
    async def test_log_action_success(self) -> None:
        """log_action should execute a parameterised INSERT."""
        pool = make_pool()

        repo = ActionLogRepository(pool)
        await repo.log_action(
            "acct-001",
            "instagram",
            "follow",
            "target_user",
            success=True,
            data={"response": "ok"},
        )

        pool._inner.execute.assert_awaited_once()
        query = pool._inner.execute.call_args[0][0]
        assert "INSERT INTO action_log" in query
        assert "acct-001" not in query     # must be parameterised

    @pytest.mark.asyncio
    async def test_log_action_failed_sets_failed_status(self) -> None:
        """log_action with success=False should pass 'failed' as the status arg."""
        pool = make_pool()

        repo = ActionLogRepository(pool)
        await repo.log_action(
            "acct-001",
            "instagram",
            "follow",
            "target_user",
            success=False,
            error="rate_limited",
        )

        call_positional = pool._inner.execute.call_args[0]
        assert "failed" in call_positional

    @pytest.mark.asyncio
    async def test_get_recent_uses_limit(self) -> None:
        """get_recent should pass the limit value as a query parameter."""
        rows = [self._make_log_row() for _ in range(3)]
        pool = make_pool(fetch_return=rows)

        repo = ActionLogRepository(pool)
        result = await repo.get_recent("acct-001", limit=10)

        assert len(result) == 3
        call_args = pool._inner.fetch.call_args[0]
        assert 10 in call_args

    @pytest.mark.asyncio
    async def test_get_daily_totals_returns_all_action_types(self) -> None:
        """get_daily_totals should return all standard action types with 0 for missing."""
        count_rows = [
            FakeRecord({"action_type": "follow", "cnt": 12}),
            FakeRecord({"action_type": "like",   "cnt": 34}),
        ]
        pool = make_pool(fetch_return=count_rows)

        repo = ActionLogRepository(pool)
        result = await repo.get_daily_totals("acct-001", "2026-04-11")

        assert result["follow"] == 12
        assert result["like"] == 34
        assert result["unfollow"] == 0
        assert result["story_view"] == 0
        assert result["dm"] == 0
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_by_phone_passes_serial_as_param(self) -> None:
        """get_by_phone should pass phone_serial as a query parameter, not inline."""
        rows = [self._make_log_row()]
        pool = make_pool(fetch_return=rows)

        repo = ActionLogRepository(pool)
        result = await repo.get_by_phone("192.168.1.10:5555", "2026-04-11")

        assert len(result) == 1
        call_args = pool._inner.fetch.call_args[0]
        query = call_args[0]
        assert "192.168.1.10:5555" not in query   # parameterised
        assert "192.168.1.10:5555" in call_args   # passed as arg


# ---------------------------------------------------------------------------
# DailyPlanRepository
# ---------------------------------------------------------------------------


class TestDailyPlanRepository:
    """Tests for DailyPlanRepository."""

    def _make_plan_row(self, account_id: str = "acct-001") -> FakeRecord:
        return FakeRecord({
            "id": str(uuid.uuid4()),
            "account_id": account_id,
            "plan_date": "2026-04-11",
            "day_in_curve": 5,
            "curve_label": "day 5",
            "intensity_level": "normal",
            "intensity_multiplier": 1.0,
            "weekly_multiplier": 1.0,
            "persona_aggressiveness": 1.0,
            "follows_target": 5,
            "likes_target": 10,
            "story_views_target": 15,
            "comments_target": 1,
            "dms_target": 0,
            "actions_executed": 0,
            "created_at": datetime.now(tz=timezone.utc),
        })

    @pytest.mark.asyncio
    async def test_save_plan_upserts(self) -> None:
        """save_plan should execute an INSERT ... ON CONFLICT DO UPDATE."""
        pool = make_pool()
        plan = {
            "day_in_curve": 5,
            "curve_label": "day 5",
            "intensity_level": "normal",
            "intensity_multiplier": 1.0,
            "weekly_multiplier": 1.0,
            "persona_aggressiveness": 1.0,
            "follows": 5,
            "likes": 10,
            "story_views": 15,
            "comments": 1,
            "dms": 0,
        }

        repo = DailyPlanRepository(pool)
        await repo.save_plan("acct-001", "2026-04-11", plan)

        pool._inner.execute.assert_awaited_once()
        query = pool._inner.execute.call_args[0][0]
        assert "INSERT INTO daily_plans" in query
        assert "ON CONFLICT" in query

    @pytest.mark.asyncio
    async def test_get_plan_returns_dict(self) -> None:
        """get_plan should return a dict when the plan exists."""
        row = self._make_plan_row()
        pool = make_pool(fetchrow_return=row)

        repo = DailyPlanRepository(pool)
        result = await repo.get_plan("acct-001", "2026-04-11")

        assert isinstance(result, dict)
        assert result["account_id"] == "acct-001"
        assert result["follows_target"] == 5

    @pytest.mark.asyncio
    async def test_get_plan_returns_none_when_missing(self) -> None:
        """get_plan should return None gracefully when no plan found."""
        pool = make_pool(fetchrow_return=None)

        repo = DailyPlanRepository(pool)
        result = await repo.get_plan("acct-999", "2026-04-11")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_plans_for_date_no_join_without_platform(self) -> None:
        """Without platform filter, get_all_plans_for_date should not JOIN accounts."""
        rows = [self._make_plan_row("acct-001"), self._make_plan_row("acct-002")]
        pool = make_pool(fetch_return=rows)

        repo = DailyPlanRepository(pool)
        result = await repo.get_all_plans_for_date("2026-04-11")

        assert len(result) == 2
        query = pool._inner.fetch.call_args[0][0]
        assert "daily_plans" in query
        assert "JOIN accounts" not in query


# ---------------------------------------------------------------------------
# AgentRunRepository
# ---------------------------------------------------------------------------


class TestAgentRunRepository:
    """Tests for AgentRunRepository."""

    def _make_run_row(self, agent_name: str = "WarmingAgent") -> FakeRecord:
        return FakeRecord({
            "run_id": str(uuid.uuid4()),
            "agent_name": agent_name,
            "started_at": datetime.now(tz=timezone.utc),
            "ended_at": datetime.now(tz=timezone.utc),
            "status": "success",
            "iterations": 5,
            "cost_usd": 0.0042,
            "inputs": {},
            "outputs": {"accounts_processed": 12},
            "error": None,
        })

    @pytest.mark.asyncio
    async def test_log_run_returns_string_id(self) -> None:
        """log_run should return a non-empty string run_id."""
        pool = make_pool()

        repo = AgentRunRepository(pool)
        run_id = await repo.log_run(
            "WarmingAgent",
            started_at=datetime.now(tz=timezone.utc),
            ended_at=datetime.now(tz=timezone.utc),
            cost_usd=0.0042,
            success=True,
            result={"accounts_processed": 12},
        )

        assert isinstance(run_id, str)
        assert len(run_id) > 0
        pool._inner.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_recent_runs_returns_list(self) -> None:
        """get_recent_runs should return a list of dicts."""
        rows = [self._make_run_row() for _ in range(5)]
        pool = make_pool(fetch_return=rows)

        repo = AgentRunRepository(pool)
        result = await repo.get_recent_runs("WarmingAgent", limit=10)

        assert isinstance(result, list)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_get_total_cost_today_returns_float(self) -> None:
        """get_total_cost_today should return a float."""
        pool = make_pool(fetchval_return=0.25)

        repo = AgentRunRepository(pool)
        cost = await repo.get_total_cost_today()

        assert isinstance(cost, float)
        assert cost == 0.25

    @pytest.mark.asyncio
    async def test_get_total_cost_today_zero_when_null(self) -> None:
        """get_total_cost_today should return 0.0 when DB returns NULL."""
        pool = make_pool(fetchval_return=None)

        repo = AgentRunRepository(pool)
        cost = await repo.get_total_cost_today(agent_name="WarmingAgent")

        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_get_all_agent_summary_returns_list(self) -> None:
        """get_all_agent_summary should return one dict per agent."""
        rows = [
            FakeRecord({
                "agent_name": "WarmingAgent",
                "last_run": datetime.now(tz=timezone.utc),
                "total_cost_today": 0.15,
                "total_runs_today": 3,
                "success_rate": 1.0,
            }),
        ]
        pool = make_pool(fetch_return=rows)

        repo = AgentRunRepository(pool)
        result = await repo.get_all_agent_summary()

        assert isinstance(result, list)
        assert result[0]["agent_name"] == "WarmingAgent"
        assert result[0]["success_rate"] == 1.0


# ---------------------------------------------------------------------------
# AlertRepository
# ---------------------------------------------------------------------------


class TestAlertRepository:
    """Tests for AlertRepository."""

    def _make_alert_row(self, severity: str = "high") -> FakeRecord:
        return FakeRecord({
            "id": str(uuid.uuid4()),
            "severity": severity,
            "dimension": "ua_monoculture",
            "description": "All accounts report identical UA string.",
            "affected_count": 220,
            "action": "pause_cohort",
            "raised_at": datetime.now(tz=timezone.utc),
            "resolved_at": None,
            "metadata": {},
        })

    @pytest.mark.asyncio
    async def test_create_alert_returns_string_id(self) -> None:
        """create_alert should return the newly generated alert id."""
        alert_id = str(uuid.uuid4())
        pool = make_pool(fetchrow_return=FakeRecord({"id": alert_id}))

        repo = AlertRepository(pool)
        result = await repo.create_alert(
            "high",
            "ua_monoculture",
            "All accounts report identical UA string.",
            action="pause_cohort",
            affected_count=220,
        )

        assert result == alert_id
        query = pool._inner.fetchrow.call_args[0][0]
        assert "INSERT INTO alerts" in query

    @pytest.mark.asyncio
    async def test_create_alert_stores_context_in_metadata(self) -> None:
        """account_id and phone_serial must appear in the metadata JSON arg."""
        alert_id = str(uuid.uuid4())
        pool = make_pool(fetchrow_return=FakeRecord({"id": alert_id}))

        repo = AlertRepository(pool)
        await repo.create_alert(
            "medium",
            "proxy_gap",
            "Phone offline.",
            account_id="acct-001",
            phone_serial="192.168.1.10:5555",
        )

        call_args = pool._inner.fetchrow.call_args[0]
        # metadata JSON is the last positional arg
        metadata_json: str = call_args[-1]
        metadata = json.loads(metadata_json)
        assert metadata["account_id"] == "acct-001"
        assert metadata["phone_serial"] == "192.168.1.10:5555"

    @pytest.mark.asyncio
    async def test_get_unread_filters_by_null_resolved(self) -> None:
        """get_unread should filter alerts where resolved_at IS NULL."""
        rows = [self._make_alert_row()]
        pool = make_pool(fetch_return=rows)

        repo = AlertRepository(pool)
        result = await repo.get_unread(limit=50)

        assert len(result) == 1
        query = pool._inner.fetch.call_args[0][0]
        assert "resolved_at IS NULL" in query

    @pytest.mark.asyncio
    async def test_mark_read_updates_single_alert(self) -> None:
        """mark_read should set resolved_at = now() for one alert by id."""
        pool = make_pool()

        repo = AlertRepository(pool)
        await repo.mark_read("alert-001")

        pool._inner.execute.assert_awaited_once()
        query, alert_id = pool._inner.execute.call_args[0]
        assert "resolved_at = now()" in query
        assert alert_id == "alert-001"

    @pytest.mark.asyncio
    async def test_mark_all_read_no_per_alert_params(self) -> None:
        """mark_all_read should UPDATE all unresolved rows with no per-row args."""
        pool = make_pool()

        repo = AlertRepository(pool)
        await repo.mark_all_read()

        pool._inner.execute.assert_awaited_once()
        call_args = pool._inner.execute.call_args[0]
        # Only the query string — no parameters
        assert len(call_args) == 1
        assert "resolved_at IS NULL" in call_args[0]
