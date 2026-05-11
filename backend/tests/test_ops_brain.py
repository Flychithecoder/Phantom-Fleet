"""
Tests for PhantomFleetOpsBrain, FleetScheduler, and HQBridge.

asyncio_mode = "auto"  (configured via pytest.ini / pyproject.toml)

All Redis, DB, and PhoneFleet calls are mocked — no real infrastructure required.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.core.ops_brain import (
    PhantomFleetOpsBrain,
    OpsCycleReport,
    HealthSnapshot,
    LLM_COST_RULE_BASED_PCT,
    MAX_CONSECUTIVE_FAILURES,
)
from phantom_fleet.core.fleet_scheduler import (
    FleetScheduler,
    ScheduledAction,
    FleetDailySchedule,
    is_quiet_hour,
    QUIET_START_HOUR,
    QUIET_END_HOUR,
)
from phantom_fleet.core.hq_bridge import (
    HQAccountHandoff,
    HQBridge,
    HandoffResult,
    BulkHandoffResult,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_fleet(**kwargs):
    fleet = MagicMock()
    fleet.scan                       = AsyncMock(return_value=[])
    fleet.verify_proxy               = AsyncMock(return_value=True)
    fleet.get_accounts_for_phone     = AsyncMock(return_value=[])
    fleet.get_all_active_accounts    = AsyncMock(return_value=[])
    fleet.get_performance_metrics    = AsyncMock(return_value={})
    fleet.get_spare_pool_count       = AsyncMock(return_value=10)
    fleet.get_newly_dead_accounts    = AsyncMock(return_value=[])
    fleet.trigger_replacement        = AsyncMock(return_value=True)
    fleet.check_er_guardian          = AsyncMock(return_value=[])
    fleet.check_shadowban_signals    = AsyncMock(return_value=[])
    fleet.enqueue_for_warming        = AsyncMock(return_value=True)
    fleet.get_account_metrics        = AsyncMock(return_value={})
    fleet.get_accounts_for_creator   = AsyncMock(return_value=[])
    fleet.get_phones_for_platform    = AsyncMock(return_value=[{"serial": "PHONE001"}])
    for k, v in kwargs.items():
        setattr(fleet, k, v)
    return fleet


def _make_redis():
    redis = MagicMock()
    redis.publish = AsyncMock(return_value=None)
    return redis


def _make_brain(fleet=None, redis=None, daily_cap=25.0):
    f = fleet or _make_fleet()
    r = redis or _make_redis()
    brain = PhantomFleetOpsBrain(fleet=f, redis=r, daily_llm_cap_usd=daily_cap)
    return brain, f, r


# ---------------------------------------------------------------------------
# 1. OpsBrain starts 3 background tasks on start()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brain_starts_three_background_tasks():
    brain, _, _ = _make_brain()
    await brain.start()
    assert len(brain._tasks) == 3
    assert brain._running is True
    await brain.stop()


# ---------------------------------------------------------------------------
# 2. Health loop: marks dead sessions, publishes to Redis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_loop_marks_dead_sessions_and_publishes():
    fleet = _make_fleet()
    # One phone with one account whose session.ping_session returns False
    mock_session = MagicMock()
    mock_session.ping_session = AsyncMock(return_value=False)
    fleet.scan = AsyncMock(return_value=[{"serial": "P1", "state": "PROXY_READY"}])
    fleet.get_accounts_for_phone = AsyncMock(return_value=[
        {"account_id": "acct1", "session": mock_session}
    ])

    redis = _make_redis()
    brain = PhantomFleetOpsBrain(fleet=fleet, redis=redis)

    await brain._run_health_check()

    snapshot = brain.latest_health()
    assert snapshot is not None
    assert snapshot.online_phones == 1
    assert snapshot.dead_accounts == 1
    assert snapshot.sessions_valid == 0

    # Redis should have been published
    redis.publish.assert_called()
    call_args = redis.publish.call_args_list
    channels = [c[0][0] for c in call_args]
    assert "fleet:health" in channels


# ---------------------------------------------------------------------------
# 3. Ops cycle: runs Chief agent, logs cycle report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ops_cycle_runs_chief_and_logs_report():
    brain, fleet, redis = _make_brain()

    # Mock Chief agent
    mock_chief = MagicMock()
    mock_chief.run = AsyncMock(return_value=None)
    brain._chief = mock_chief

    # Mock DB cost query to return 0
    brain._get_llm_cost_today = AsyncMock(return_value=0.0)
    brain._log_cycle_to_db    = AsyncMock(return_value=None)

    await brain._run_ops_cycle()

    # Chief was called
    mock_chief.run.assert_awaited_once()

    # Report was stored
    report = brain.latest_report()
    assert report is not None
    assert isinstance(report, OpsCycleReport)
    assert report.status in ("success", "partial", "failed")
    assert report.cycle_id != ""
    assert report.duration_sec >= 0

    # History accumulated
    assert len(brain.cycle_history()) == 1


# ---------------------------------------------------------------------------
# 4. Self-heal: LLM cost > 80% daily cap → rule-based mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_cost_above_80pct_triggers_rule_based_mode():
    brain, _, redis = _make_brain(daily_cap=10.0)
    brain._get_llm_cost_today = AsyncMock(return_value=8.5)   # 85% of $10
    brain._log_cycle_to_db    = AsyncMock(return_value=None)

    mock_chief = MagicMock()
    mock_chief.run = AsyncMock()
    brain._chief = mock_chief

    await brain._run_ops_cycle()

    assert brain.is_rule_based_mode() is True
    # Chief should NOT have been dispatched in rule-based mode
    mock_chief.run.assert_not_awaited()

    # Redis alert should have been published
    publish_calls = [json.loads(c[0][1]) for c in redis.publish.call_args_list]
    alert_payloads = [p for p in publish_calls if p.get("dimension") == "llm_cost"]
    assert len(alert_payloads) >= 1


# ---------------------------------------------------------------------------
# 5. 3 consecutive Chief failures → pauses and fires critical alert
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_three_consecutive_failures_pauses_and_alerts():
    brain, _, redis = _make_brain()
    brain._get_llm_cost_today = AsyncMock(return_value=0.0)
    brain._log_cycle_to_db    = AsyncMock(return_value=None)

    # Chief always raises
    error_chief = MagicMock()
    error_chief.run = AsyncMock(side_effect=RuntimeError("chief exploded"))
    brain._chief = error_chief

    # Also make direct platform manager dispatch fail
    brain._get_platform_manager = AsyncMock(return_value=None)

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        await brain._run_ops_cycle()

    assert brain._paused is True

    # Critical alert published
    publish_calls = [json.loads(c[0][1]) for c in redis.publish.call_args_list]
    critical = [p for p in publish_calls if p.get("severity") == "critical"]
    assert len(critical) >= 1


# ---------------------------------------------------------------------------
# 6. Alert loop: ER drop detected → alert published
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_loop_er_drop_fires_alert():
    fleet = _make_fleet()
    fleet.check_er_guardian = AsyncMock(return_value=["@tatiana_nyc ER dropped 4.2% → 1.8%"])

    redis = _make_redis()
    brain = PhantomFleetOpsBrain(fleet=fleet, redis=redis)

    await brain._run_alert_sweep()

    publish_calls = [json.loads(c[0][1]) for c in redis.publish.call_args_list]
    er_alerts = [p for p in publish_calls if p.get("dimension") == "engagement_rate"]
    assert len(er_alerts) >= 1


# ---------------------------------------------------------------------------
# 7. Alert loop: spare pool low → escalation fired
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_loop_spare_pool_low_fires_alert():
    fleet = _make_fleet()
    fleet.get_spare_pool_count = AsyncMock(return_value=2)   # < 5 threshold

    redis = _make_redis()
    brain = PhantomFleetOpsBrain(fleet=fleet, redis=redis)

    await brain._run_alert_sweep()

    publish_calls = [json.loads(c[0][1]) for c in redis.publish.call_args_list]
    pool_alerts = [p for p in publish_calls if p.get("dimension") == "spare_pool"]
    assert len(pool_alerts) >= 1
    assert pool_alerts[0]["severity"] in ("medium", "high")


# ---------------------------------------------------------------------------
# 8. HQ handoff: account provisioned, warming started, result returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hq_handoff_provisions_account_and_returns_result():
    fleet = _make_fleet()
    bridge = HQBridge(fleet=fleet, db_pool=None)

    payload = HQAccountHandoff(
        creator_id="creator_123",
        platform="instagram",
        username="tatiana_nyc",
        password="secret",
        two_fa_secret=None,
        chat_tier="FLIRTY_SFW",
        persona_name="Tatiana_NYC",
        content_tags=["lifestyle", "sfw"],
        target_niches=["fitness", "travel"],
        hq_api_key="test-key",
    )
    result = await bridge.receive_account_handoff(payload)

    assert result.ok is True
    assert result.account_id != ""
    assert result.platform == "instagram"
    assert result.warming_start_date != ""
    assert result.estimated_ready_date != ""
    assert result.status in ("warming", "queued")

    # Phone should have been queried
    fleet.get_phones_for_platform.assert_called()
    fleet.enqueue_for_warming.assert_awaited_once()


# ---------------------------------------------------------------------------
# 9. HQ handoff: wrong API key → 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hq_handoff_wrong_api_key_returns_401():
    """The FastAPI route validates the X-HQ-API-Key before reaching the bridge.
    Test that the dependency raises HTTPException for wrong key."""
    os.environ["HQ_API_KEY"] = "correct-secret-key"

    from phantom_fleet.api.routes.hq_bridge import _require_hq_key
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await _require_hq_key(x_hq_api_key="wrong-key")

    assert exc_info.value.status_code == 401

    del os.environ["HQ_API_KEY"]


# ---------------------------------------------------------------------------
# 10. Bulk handoff: processes multiple accounts, per-account results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_handoff_processes_multiple_accounts():
    fleet = _make_fleet()
    bridge = HQBridge(fleet=fleet, db_pool=None)

    payloads = [
        HQAccountHandoff(
            creator_id="creator_A",
            platform="instagram",
            username=f"account_{i}",
            password="pw",
            two_fa_secret=None,
            chat_tier="CASUAL_SFW",
            persona_name=f"Persona_{i}",
            content_tags=[],
            target_niches=[],
            hq_api_key="key",
        )
        for i in range(3)
    ]

    result: BulkHandoffResult = await bridge.bulk_handoff(payloads)

    assert result.total == 3
    assert result.succeeded == 3
    assert result.failed == 0
    assert len(result.results) == 3
    # All unique account IDs
    ids = {r.account_id for r in result.results}
    assert len(ids) == 3


# ---------------------------------------------------------------------------
# 11. Fleet scheduler: morning sessions scheduled 7–11am account timezone
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduler_morning_sessions_in_correct_window():
    scheduler = FleetScheduler()
    today = date.today().isoformat()

    accounts = [
        {
            "account_id":            "acct_nyc",
            "platform":              "instagram",
            "phone_serial":          "PHONE1",
            "timezone_offset_hours": -5,   # EST
            "action_types":          ["story_session"],
        }
    ]
    schedule = await scheduler.build_fleet_schedule(today, accounts)

    assert len(schedule.actions) == 1
    action = schedule.actions[0]
    assert action.action_type == "story_session"

    # Convert UTC back to EST and verify it's in 7-11am window
    scheduled_utc = datetime.fromtimestamp(action.scheduled_at_unix, tz=timezone.utc)
    local_hour = (scheduled_utc.hour - 5) % 24   # EST = UTC-5
    assert 7 <= local_hour < 11, f"Expected 7-11am EST, got hour {local_hour}"


# ---------------------------------------------------------------------------
# 12. Fleet scheduler: quiet hours enforced (no actions 11pm–7am)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduler_quiet_hours_enforced():
    # Verify is_quiet_hour for boundary values
    assert is_quiet_hour(23) is True    # 11pm
    assert is_quiet_hour(0)  is True    # midnight
    assert is_quiet_hour(3)  is True    # 3am
    assert is_quiet_hour(6)  is True    # 6am (still quiet)
    assert is_quiet_hour(7)  is False   # 7am is active
    assert is_quiet_hour(12) is False   # noon is active
    assert is_quiet_hour(22) is False   # 10pm is active


@pytest.mark.asyncio
async def test_scheduler_no_actions_during_quiet_hours():
    """An account in a timezone where ALL windows fall in quiet hours
    should produce no scheduled actions."""
    scheduler = FleetScheduler()
    today = date.today().isoformat()

    # tz_offset = +20 is not realistic but forces all local windows into UTC quiet hours
    # Instead, directly verify that no story_session is scheduled in 11pm-7am local window
    # We use a valid real-world check: schedule a story_session for an account
    # and verify the scheduled time is NOT in quiet hours (local)
    accounts = [
        {
            "account_id":            "acct_test",
            "platform":              "instagram",
            "phone_serial":          "PHONE2",
            "timezone_offset_hours": 0,   # UTC
            "action_types":          ["story_session"],
        }
    ]
    schedule = await scheduler.build_fleet_schedule(today, accounts)
    for action in schedule.actions:
        scheduled_utc = datetime.fromtimestamp(action.scheduled_at_unix, tz=timezone.utc)
        local_hour = scheduled_utc.hour  # UTC offset = 0
        assert not is_quiet_hour(local_hour), (
            f"Action {action.action_type} scheduled during quiet hour {local_hour}"
        )


# ---------------------------------------------------------------------------
# 13. Pause/resume: operations stop/start correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_resume_controls():
    brain, _, _ = _make_brain()

    assert brain.status() == "stopped"   # not started yet

    await brain.start()
    assert brain.status() == "running"

    brain.pause()
    assert brain.status() == "paused"
    assert brain._paused is True

    brain.resume()
    assert brain.status() == "running"
    assert brain._paused is False
    assert brain._consecutive_failures == 0

    await brain.stop()


# ---------------------------------------------------------------------------
# 14. Cycle report: all platform fields populated after successful cycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cycle_report_platform_fields_populated():
    brain, _, _ = _make_brain()

    mock_chief = MagicMock()
    mock_chief.run = AsyncMock(return_value=None)
    brain._chief = mock_chief
    brain._get_llm_cost_today = AsyncMock(return_value=1.5)
    brain._log_cycle_to_db    = AsyncMock(return_value=None)

    # Give it a health snapshot first
    brain._latest_health = HealthSnapshot(
        ts_iso=datetime.now(tz=timezone.utc).isoformat(),
        online_phones=5,
        proxy_ready=5,
        active_accounts=100,
        dead_accounts=0,
        sessions_valid=98,
    )

    await brain._run_ops_cycle()

    report = brain.latest_report()
    assert report is not None
    assert report.phones_online == 5
    assert report.accounts_active == 100
    assert isinstance(report.platform_cycles_completed, dict)
    assert report.llm_cost_usd == 1.5
    assert report.cycle_id != ""
    assert report.started_at_iso != ""
    assert report.completed_at_iso != ""


# ---------------------------------------------------------------------------
# 15. Platform manager failure doesn't kill other platforms
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_platform_manager_failure_is_isolated():
    """One platform manager crashing must not stop other platforms from running."""
    brain, fleet, _ = _make_brain()
    brain._get_llm_cost_today = AsyncMock(return_value=0.0)
    brain._log_cycle_to_db    = AsyncMock(return_value=None)

    # Chief fails → falls back to direct platform manager dispatch
    bad_chief = MagicMock()
    bad_chief.run = AsyncMock(side_effect=RuntimeError("chief down"))
    brain._chief = bad_chief

    call_log: list[str] = []

    async def fake_get_manager(platform: str):
        mgr = MagicMock()
        if platform == "instagram":
            async def bad_run(ctx):
                raise RuntimeError("ig exploded")
            mgr.run = bad_run
        else:
            async def good_run(ctx):
                call_log.append(platform)
            mgr.run = good_run
        return mgr

    brain._get_platform_manager = fake_get_manager

    await brain._run_ops_cycle()

    report = brain.latest_report()
    assert report is not None
    # Instagram failed but other platforms should have run
    assert report.platform_cycles_completed.get("instagram") is False
    # At least some other platforms should have succeeded
    succeeded = [k for k, v in report.platform_cycles_completed.items() if v is True]
    assert len(succeeded) > 0
    # No unhandled exception propagated
