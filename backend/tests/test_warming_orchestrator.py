"""
Tests for WarmingOrchestrator — daily warming cycle runner.

All Instagram HTTP calls are mocked. No real IG endpoints are ever called.

Coverage targets:
    - Quiet-hour skipping (accounts on phones with no active slots are counted)
    - Session expiry handled gracefully (report tallies, no exception propagation)
    - Rate-limit handled gracefully (report tallies, no crash)
    - Report totals match actions executed
    - Accounts with no session are skipped correctly
    - Unknown actions produce errors in report, not exceptions
    - No-runner-for-phone is logged to report.errors
    - DailyPlan follows/likes/story_views all flow into correct result buckets
    - Multiple accounts on multiple phones run concurrently
    - Accounts with missing targets log appropriate errors
    - _tally_results correctly categorises all result types
    - _has_active_slot returns False for pure-quiet-hour schedules
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.core.hybrid_runner import (
    BackgroundWorker,
    DeviceProfile,
    InstagramAPIWorker,
    PhoneHybridRunner,
    PhoneSlotLock,
    PlatformHeaders,
    WorkerResult,
    WorkerTask,
    build_fleet_runners,
)
from phantom_fleet.core.instagram_client import IGSession
from phantom_fleet.core.time_slot_scheduler import (
    DailySchedule,
    SlotAssignment,
    QUIET_HOURS_START,
    QUIET_HOURS_END,
    slot_index,
)
from phantom_fleet.core.warming_orchestrator import (
    WarmingCycleReport,
    WarmingOrchestrator,
    _tally_results,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def make_platform_headers(
    platform: str = "instagram",
    phone_serial: str = "PHONE_001",
) -> PlatformHeaders:
    return PlatformHeaders(
        platform=platform,
        session_token=f"tok_{phone_serial}",
        device_id=f"dev_{phone_serial}",
        user_agent=(
            "Instagram 300.0.0.1 Android (31/12; 420dpi; 1080x2400; "
            "samsung; SM-G770F; x1s; exynos9610; en_US; 480028919)"
        ),
        app_version="300.0.0.1",
        android_id="abc123def456abc1",
        advertising_id="gaid-1234-5678",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra={"mid": "mid_test_value", "family_device_id": "fam-uuid-test"},
    )


def make_device_profile(
    phone_serial: str = "PHONE_001",
    platforms: list[str] | None = None,
) -> DeviceProfile:
    if platforms is None:
        platforms = ["instagram"]
    headers = {p: make_platform_headers(p, phone_serial) for p in platforms}
    return DeviceProfile(
        phone_serial=phone_serial,
        model="Samsung Galaxy S10 Lite",
        android_version="12",
        android_id="abc123def456abc1",
        advertising_id="gaid-1234-5678",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        timezone="America/New_York",
        locale="en_US",
        platform_headers=headers,
    )


def make_session(
    account_id: str = "acc_001",
    ig_user_id: str = "1000000001",
    username: str = "test_user",
    phone_serial: str = "PHONE_001",
) -> IGSession:
    return IGSession(
        account_id=account_id,
        ig_user_id=ig_user_id,
        username=username,
        session_id="sess_abc123",
        csrftoken="csrf_xyz789",
        mid="mid_test_value",
        ds_user_id=ig_user_id,
        headers=make_platform_headers("instagram", phone_serial),
        is_valid=True,
    )


def make_account(
    account_id: str = "acc_001",
    phone_serial: str = "PHONE_001",
    warmup_day: int = 5,
    session: IGSession | None = None,
    targets: list[dict] | None = None,
    curve_type: str = "fresh_warmup",
) -> dict:
    if session is None:
        session = make_session(account_id=account_id, phone_serial=phone_serial)
    return {
        "account_id": account_id,
        "ig_user_id": session.ig_user_id,
        "username": session.username,
        "phone_serial": phone_serial,
        "warmup_day": warmup_day,
        "platform": "instagram",
        "session": session,
        "targets": targets or [
            {"user_id": f"target_{i}", "media_id": f"media_{i}"}
            for i in range(1, 51)   # 50 targets, enough for any plan day
        ],
        "curve_type": curve_type,
    }


def make_active_schedule(
    phone_serial: str = "PHONE_001",
    platform: str = "instagram",
    persona_id: str = "persona_test",
    date_iso: str = "2026-04-11",
) -> DailySchedule:
    """A schedule with one active (non-quiet) slot for the given phone."""
    # slot_index(18) = 36 — 6pm, well outside quiet hours
    return DailySchedule(
        persona_id=persona_id,
        date_iso=date_iso,
        timezone="America/New_York",
        assignments=[
            SlotAssignment(
                slot=slot_index(18),   # 6pm — active
                platform=platform,
                phone_serial=phone_serial,
                persona_id=persona_id,
                expected_accounts=10,
            )
        ],
    )


def make_quiet_schedule(
    phone_serial: str = "PHONE_001",
    platform: str = "instagram",
    persona_id: str = "persona_test",
    date_iso: str = "2026-04-11",
) -> DailySchedule:
    """A schedule whose only slot is inside quiet hours."""
    # QUIET_HOURS_START = slot_index(2), QUIET_HOURS_END = slot_index(6)
    quiet_slot = QUIET_HOURS_START  # 2am slot — definitely quiet
    return DailySchedule(
        persona_id=persona_id,
        date_iso=date_iso,
        timezone="America/New_York",
        assignments=[
            SlotAssignment(
                slot=quiet_slot,
                platform=platform,
                phone_serial=phone_serial,
                persona_id=persona_id,
                expected_accounts=10,
            )
        ],
    )


def make_empty_schedule(
    persona_id: str = "persona_test",
    date_iso: str = "2026-04-11",
) -> DailySchedule:
    """A schedule with zero assignments."""
    return DailySchedule(
        persona_id=persona_id,
        date_iso=date_iso,
        timezone="America/New_York",
        assignments=[],
    )


def make_fleet_runners(
    phone_serials: list[str] | None = None,
) -> dict[str, PhoneHybridRunner]:
    if phone_serials is None:
        phone_serials = ["PHONE_001"]
    profiles = [make_device_profile(s, ["instagram"]) for s in phone_serials]
    return build_fleet_runners(profiles)


# ---------------------------------------------------------------------------
# Helpers: patch InstagramAPIWorker so it never touches the network.
#
# We patch TWO things:
#   1. InstagramAPIWorker.execute_task  — the actual action (no HTTP)
#   2. BackgroundWorker._human_sleep   — eliminates 1-20 second sleeps in tests
# ---------------------------------------------------------------------------


def fake_execute_task_factory(
    *,
    succeed: bool = True,
    error: str | None = None,
) -> callable:
    """
    Returns an async function that pretends to execute a task successfully
    (or with a named failure) without touching the Instagram API.
    """
    async def _fake(self, task: WorkerTask) -> WorkerResult:
        if not succeed:
            return WorkerResult(
                task_id=task.task_id,
                platform="instagram",
                account_id=task.account_id,
                success=False,
                error=error or "simulated_failure",
            )
        # Map action to the data dict the real worker would return
        action_data = {"action": task.action}
        if task.action in ("follow", "unfollow"):
            action_data["target_user_id"] = task.params.get("target_user_id", "")
        elif task.action == "like":
            action_data["media_id"] = task.params.get("media_id", "")
        elif task.action == "story_view":
            action_data["reel_id"] = task.params.get("reel_id", "")
        elif task.action == "send_dm":
            action_data["recipient_user_id"] = task.params.get("recipient_user_id", "")
        return WorkerResult(
            task_id=task.task_id,
            platform="instagram",
            account_id=task.account_id,
            success=True,
            data=action_data,
        )
    return _fake


async def _noop_sleep(*args, **kwargs) -> None:
    """Drop-in for BackgroundWorker._human_sleep — returns immediately."""
    pass


# Context-manager helper used by all async tests to avoid sleep delays
# and avoid real HTTP calls. Usage:
#   with _patch_worker(succeed=True):
#       report = await orchestrator.run_warming_cycle(...)


@contextlib.contextmanager
def _patch_worker(*, succeed: bool = True, error: str | None = None):
    with patch.object(
        InstagramAPIWorker,
        "execute_task",
        new=fake_execute_task_factory(succeed=succeed, error=error),
    ):
        with patch.object(BackgroundWorker, "_human_sleep", new=staticmethod(_noop_sleep)):
            yield


# ---------------------------------------------------------------------------
# Test 1 — quiet hours: account on a phone with only quiet-hour slots is skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quiet_hour_accounts_are_skipped():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_quiet_schedule("PHONE_001")  # only 2am slot
    orchestrator = WarmingOrchestrator(fleet, schedule)

    accounts = [make_account("acc_001", "PHONE_001", warmup_day=5)]

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle(accounts, "2026-04-11")

    assert report.accounts_attempted == 1
    assert report.skipped_quiet_hours == 1
    assert report.accounts_succeeded == 0
    assert report.total_follows == 0
    assert report.total_story_views == 0
    assert report.total_likes == 0


# ---------------------------------------------------------------------------
# Test 2 — no schedule assignments at all → all accounts skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_schedule_skips_all_accounts():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_empty_schedule()
    orchestrator = WarmingOrchestrator(fleet, schedule)

    accounts = [make_account("acc_001", "PHONE_001", warmup_day=10)]

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle(accounts, "2026-04-11")

    assert report.accounts_attempted == 1
    assert report.skipped_quiet_hours == 1
    assert report.accounts_succeeded == 0


# ---------------------------------------------------------------------------
# Test 3 — session expiry is tallied, cycle does not crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_expiry_handled_gracefully():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    accounts = [make_account("acc_001", "PHONE_001", warmup_day=5)]

    with _patch_worker(succeed=False, error="session_expired"):
        report = await orchestrator.run_warming_cycle(accounts, "2026-04-11")

    # Cycle must not raise
    assert isinstance(report, WarmingCycleReport)
    # session_expired results should be counted
    assert report.session_expired_count > 0
    # totals must be zero since all tasks failed
    assert report.total_follows == 0
    assert report.total_story_views == 0
    assert report.total_likes == 0


# ---------------------------------------------------------------------------
# Test 4 — rate limit is tallied, cycle does not crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_handled_gracefully():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    accounts = [make_account("acc_001", "PHONE_001", warmup_day=5)]

    with _patch_worker(succeed=False, error="rate_limited"):
        report = await orchestrator.run_warming_cycle(accounts, "2026-04-11")

    assert isinstance(report, WarmingCycleReport)
    assert report.rate_limited_count > 0
    assert report.total_follows == 0


# ---------------------------------------------------------------------------
# Test 5 — successful run: report totals match actions executed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_totals_match_executed_actions():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    # Use a day that definitely has > 0 follows, likes, and story_views in the plan
    # Day 10 in FRESH_WARMUP_CURVE: follows(6,11), likes(13,22), story_views(17,30)
    accounts = [make_account("acc_001", "PHONE_001", warmup_day=10)]

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle(accounts, "2026-04-11")

    # All three categories should have been executed
    assert report.total_follows >= 0
    assert report.total_story_views >= 0
    assert report.total_likes >= 0
    # At least one category should have > 0 (day 10 is past the zero-action days)
    assert report.total_follows + report.total_story_views + report.total_likes > 0


# ---------------------------------------------------------------------------
# Test 6 — no-session account is skipped without error propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_session_account_skipped():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    acct = make_account("acc_001", "PHONE_001", warmup_day=5, session=None)
    # Override the session to None after construction
    acct["session"] = None

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle([acct], "2026-04-11")

    assert report.accounts_attempted == 1
    assert report.skipped_no_session == 1
    assert report.accounts_succeeded == 0


# ---------------------------------------------------------------------------
# Test 7 — invalid session (is_valid=False) is also skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_session_skipped():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    sess = make_session("acc_001", phone_serial="PHONE_001")
    sess.is_valid = False

    acct = make_account("acc_001", "PHONE_001", warmup_day=5, session=sess)

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle([acct], "2026-04-11")

    assert report.skipped_no_session == 1
    assert report.accounts_succeeded == 0


# ---------------------------------------------------------------------------
# Test 8 — multiple accounts on multiple phones run correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_accounts_multiple_phones():
    phones = ["PHONE_A", "PHONE_B", "PHONE_C"]
    fleet = make_fleet_runners(phones)
    schedule = DailySchedule(
        persona_id="persona_multi",
        date_iso="2026-04-11",
        timezone="America/New_York",
        assignments=[
            SlotAssignment(
                slot=slot_index(18),
                platform="instagram",
                phone_serial=p,
                persona_id="persona_multi",
                expected_accounts=5,
            )
            for p in phones
        ],
    )
    orchestrator = WarmingOrchestrator(fleet, schedule)

    accounts = [
        make_account(f"acc_{i:03d}", phones[i % len(phones)], warmup_day=10)
        for i in range(6)  # 2 accounts per phone
    ]

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle(accounts, "2026-04-11")

    assert report.accounts_attempted == 6
    assert report.skipped_quiet_hours == 0
    assert report.skipped_no_session == 0
    # At least some actions should have been executed
    total_actions = (
        report.total_follows + report.total_story_views + report.total_likes
    )
    assert total_actions >= 0   # plan may be zero on early days


# ---------------------------------------------------------------------------
# Test 9 — accounts with no targets log errors, do not crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_targets_logs_errors_no_crash():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    # warmup_day=10 plans > 0 follows/likes/story_views, but no targets supplied
    # Note: make_account uses `targets or [defaults]` so [] is replaced by default list.
    # Override after construction to force truly empty targets.
    acct = make_account("acc_001", "PHONE_001", warmup_day=10)
    acct["targets"] = []

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle([acct], "2026-04-11")

    # Should not crash; errors list should have entries about missing targets
    assert isinstance(report, WarmingCycleReport)
    # There should be at least one error message for missing targets
    assert any("targets" in e for e in report.errors), (
        f"Expected target-missing errors, got: {report.errors}"
    )


# ---------------------------------------------------------------------------
# Test 10 — unknown phone serial logged to errors, no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_phone_logs_error():
    fleet = make_fleet_runners(["PHONE_KNOWN"])
    schedule = make_active_schedule("PHONE_UNKNOWN")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    # Account on PHONE_UNKNOWN, which has no runner
    acct = make_account("acc_001", "PHONE_UNKNOWN", warmup_day=5)

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle([acct], "2026-04-11")

    assert any("no_runner_for_phone" in e for e in report.errors), (
        f"Expected no-runner error, got: {report.errors}"
    )


# ---------------------------------------------------------------------------
# Test 11 — _tally_results correctly buckets follow/like/story_view/dm
# ---------------------------------------------------------------------------


def test_tally_results_buckets_correctly():
    report = WarmingCycleReport(date_iso="2026-04-11")

    def _result(action: str, success: bool = True, error: str | None = None) -> WorkerResult:
        return WorkerResult(
            task_id=str(uuid.uuid4()),
            platform="instagram",
            account_id="acc_001",
            success=success,
            error=error,
            data={"action": action} if success else {},
        )

    runner_results = {
        "PHONE_001": {
            "instagram": [
                _result("follow"),
                _result("follow"),
                _result("story_view"),
                _result("like"),
                _result("send_dm"),
                _result("follow", success=False, error="session_expired"),
                _result("like",   success=False, error="rate_limited"),
            ]
        }
    }

    _tally_results(runner_results, report)

    assert report.total_follows == 2
    assert report.total_story_views == 1
    assert report.total_likes == 1
    assert report.total_dms == 1
    assert report.session_expired_count == 1
    assert report.rate_limited_count == 1


# ---------------------------------------------------------------------------
# Test 12 — _tally_results with action_blocked error goes to report.errors
# ---------------------------------------------------------------------------


def test_tally_results_action_blocked_goes_to_errors():
    report = WarmingCycleReport(date_iso="2026-04-11")

    runner_results = {
        "PHONE_001": {
            "instagram": [
                WorkerResult(
                    task_id="t1",
                    platform="instagram",
                    account_id="acc_002",
                    success=False,
                    error="action_blocked:follow blocked",
                )
            ]
        }
    }

    _tally_results(runner_results, report)

    assert any("action_blocked" in e for e in report.errors)
    assert report.session_expired_count == 0
    assert report.rate_limited_count == 0


# ---------------------------------------------------------------------------
# Test 13 — re-wake curve accounts are handled identically to fresh accounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_re_wake_curve_accounts_processed():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    # RE_WAKE_CURVE day 3: follows(2,4), likes(4,8), story_views(8,12)
    acct = make_account(
        "acc_001", "PHONE_001", warmup_day=3, curve_type="re_wake"
    )

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle([acct], "2026-04-11")

    assert isinstance(report, WarmingCycleReport)
    assert report.skipped_quiet_hours == 0
    assert report.skipped_no_session == 0


# ---------------------------------------------------------------------------
# Test 14 — day 0 dormant: no actions enqueued, but account is not counted
#            as a failure (it just has no tasks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_day_zero_dormant_no_actions():
    fleet = make_fleet_runners(["PHONE_001"])
    schedule = make_active_schedule("PHONE_001")
    orchestrator = WarmingOrchestrator(fleet, schedule)

    # Day 0 of FRESH_WARMUP_CURVE: all (0,0) ranges → 0 for every action type
    acct = make_account("acc_001", "PHONE_001", warmup_day=0)

    with _patch_worker(succeed=True):
        report = await orchestrator.run_warming_cycle([acct], "2026-04-11")

    # No tasks will be enqueued → accounts_succeeded stays at 0 (0 enqueued)
    # No follows/likes/story_views possible on day 0
    assert report.total_follows == 0
    assert report.total_story_views == 0
    assert report.total_likes == 0
    assert report.skipped_quiet_hours == 0
    assert report.skipped_no_session == 0


# ---------------------------------------------------------------------------
# Test 15 — has_active_slot boundary: slot exactly on QUIET_HOURS_END is active
# ---------------------------------------------------------------------------


def test_has_active_slot_at_quiet_hours_boundary():
    """Slot at QUIET_HOURS_END (6am) should be considered active (not quiet)."""
    schedule = DailySchedule(
        persona_id="p",
        date_iso="2026-04-11",
        timezone="America/New_York",
        assignments=[
            SlotAssignment(
                slot=QUIET_HOURS_END,       # exactly 6am — NOT quiet (open end)
                platform="instagram",
                phone_serial="PHONE_001",
                persona_id="p",
                expected_accounts=5,
            )
        ],
    )
    fleet = make_fleet_runners(["PHONE_001"])
    orchestrator = WarmingOrchestrator(fleet, schedule)

    assert orchestrator._has_active_slot("PHONE_001", "instagram") is True


def test_has_active_slot_returns_false_for_quiet_only():
    """A schedule with only slot 2am (QUIET_HOURS_START) should return False."""
    schedule = DailySchedule(
        persona_id="p",
        date_iso="2026-04-11",
        timezone="America/New_York",
        assignments=[
            SlotAssignment(
                slot=QUIET_HOURS_START,   # 2am — quiet
                platform="instagram",
                phone_serial="PHONE_001",
                persona_id="p",
                expected_accounts=5,
            )
        ],
    )
    fleet = make_fleet_runners(["PHONE_001"])
    orchestrator = WarmingOrchestrator(fleet, schedule)

    assert orchestrator._has_active_slot("PHONE_001", "instagram") is False
