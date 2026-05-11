"""
Tests for IGForegroundPostAgent, IGContentScheduler, and PhoneController
ADB push/shell methods.

Coverage (15+ tests):
    IGForegroundPostAgent:
        - ADB push called with correct remote path format
        - MediaScanner POST called with correct path
        - APK post endpoint called with correct payload
        - Staging file deleted after successful post (try/finally)
        - Staging file deleted after failed post (try/finally)
        - Foreground lock acquired before posting
        - Foreground lock released after posting
        - Daily cap enforced at 3 grid posts (code-level, not prompt)
        - pre_post_browse_delay called before posting
        - rethink pause fires at ~15% (checked over many iterations)
        - WorkerResult fields correct on success
        - WorkerResult failure on APK error response
        - Validation fails on mismatched media_files / captions length

    IGContentScheduler:
        - No two accounts post at exact same second (fleet spread)
        - Jitter applied per account (scheduled_at_unix != base time)
        - Timezone peak hours respected (posting in 9-21h local window)
        - DailyPostSchedule has correct total count

    PhoneController.adb_push:
        - Formats ADB push command correctly
        - Raises ADBCommandFailed on non-zero exit code

asyncio_mode = "auto" is configured in pyproject.toml — no decorator needed.
All ADB subprocess calls and HTTP calls are mocked.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest

from phantom_fleet.agents.specialists.ig_foreground_post_agent import (
    IGForegroundPostAgent,
    IGPostTask,
    _make_remote_path,
    _validate_task,
)
from phantom_fleet.agents.specialists.ig_content_scheduler import (
    AccountConfig,
    ContentVaultItem,
    IGContentScheduler,
    _stable_hash_mod,
)
from phantom_fleet.core.hybrid_runner import PhoneSlotLock, WorkerResult
from phantom_fleet.core.phone_controller import (
    ADBCommandFailed,
    PhoneController,
    PhoneState,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def make_task(
    post_type: str = "grid",
    media_files: Optional[list[str]] = None,
    captions:    Optional[list[str]] = None,
    daily_counts: Optional[dict] = None,
) -> IGPostTask:
    if media_files is None:
        media_files = ["/tmp/phantom/test_image.jpg"]
    if captions is None:
        captions = ["Test caption #phantom"] * len(media_files)
    return IGPostTask(
        account_id    = "acc_001",
        phone_serial  = "192.168.1.42:5555",
        clone_package = "com.instagram.android.clone1",
        phone_ip      = "192.168.1.42",
        post_type     = post_type,
        media_files   = media_files,
        captions      = captions,
        apk_port      = 8090,
        daily_counts  = daily_counts or {},
    )


def make_phone_controller(state: PhoneState = PhoneState.PROXY_READY) -> PhoneController:
    ctrl = PhoneController(serial="192.168.1.42:5555", state=state)
    return ctrl


def make_slot_lock() -> PhoneSlotLock:
    return PhoneSlotLock("192.168.1.42:5555")


def make_mock_http_client(
    post_success: bool = True,
    apk_error: str = "test_error",
) -> MagicMock:
    """Build a mock httpx.AsyncClient that behaves as a context manager."""
    client = AsyncMock(spec=httpx.AsyncClient)

    # /media/scan response
    scan_resp = MagicMock()
    scan_resp.raise_for_status = MagicMock()

    # /instagram/post response
    post_resp = MagicMock()
    post_resp.raise_for_status = MagicMock()
    post_resp.json.return_value = (
        {"success": True} if post_success else {"success": False, "error": apk_error}
    )

    async def mock_post(url, **kwargs):
        if "/media/scan" in url:
            return scan_resp
        if "/instagram/post" in url:
            return post_resp
        raise ValueError(f"Unexpected URL: {url}")

    client.post = AsyncMock(side_effect=mock_post)

    # Context manager protocol
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    return client


# ---------------------------------------------------------------------------
# IGForegroundPostAgent tests
# ---------------------------------------------------------------------------

async def test_adb_push_called_with_correct_remote_path():
    """ADB push must target /sdcard/DCIM/PhantomFleet/<uuid>.<ext>."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success is True
    # Verify push was called once
    assert ctrl.adb_push.call_count == 1
    _, remote_path = ctrl.adb_push.call_args[0]
    # Must be in the staging dir with .jpg extension
    assert remote_path.startswith("/sdcard/DCIM/PhantomFleet/")
    assert remote_path.endswith(".jpg")
    # UUID portion: 32 hex chars between dir/ and .jpg
    filename = os.path.basename(remote_path)
    hex_part = filename[:-4]   # strip .jpg
    assert len(hex_part) == 32
    assert all(c in "0123456789abcdef" for c in hex_part)


async def test_media_scanner_post_called_with_correct_path():
    """The /media/scan endpoint must receive the same remote path as ADB push."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    pushed_paths: list[str] = []

    async def capture_push(local_path, remote_path):
        pushed_paths.append(remote_path)

    ctrl.adb_push  = AsyncMock(side_effect=capture_push)
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    # Find the /media/scan call
    scan_calls = [c for c in client.post.call_args_list if "/media/scan" in c[0][0]]
    assert len(scan_calls) == 1
    assert scan_calls[0][1]["json"]["path"] == pushed_paths[0]


async def test_apk_post_endpoint_called_with_correct_payload():
    """The /instagram/post call must include mediaPath, caption, accountId, postType."""
    task   = make_task(post_type="grid", captions=["Hello Instagram!"])
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    post_calls = [c for c in client.post.call_args_list if "/instagram/post" in c[0][0]]
    assert len(post_calls) == 1
    payload = post_calls[0][1]["json"]
    assert payload["caption"] == "Hello Instagram!"
    assert payload["accountId"] == "acc_001"
    assert payload["clonePackage"] == "com.instagram.android.clone1"
    assert payload["postType"] == "GRID"
    assert payload["mediaPath"].startswith("/sdcard/DCIM/PhantomFleet/")


async def test_staging_file_deleted_after_successful_post():
    """Staging file must be deleted via adb_shell rm after a successful post."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(post_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    assert ctrl.adb_shell.call_count == 1
    rm_cmd = ctrl.adb_shell.call_args[0][0]
    assert rm_cmd.startswith("rm -f /sdcard/DCIM/PhantomFleet/")


async def test_staging_file_deleted_after_failed_post():
    """Staging file must be deleted even when the APK reports an error."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(post_success=False, apk_error="node_not_found:new_post_button")

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    # Post failed but cleanup still ran
    assert result.success is False
    assert ctrl.adb_shell.call_count == 1
    rm_cmd = ctrl.adb_shell.call_args[0][0]
    assert rm_cmd.startswith("rm -f /sdcard/DCIM/PhantomFleet/")


async def test_foreground_lock_acquired_before_posting():
    """Foreground lock must be acquired before any Instagram UI action."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    acquire_order: list[str] = []

    original_acquire = lock.acquire_foreground
    async def tracking_acquire(platform):
        acquire_order.append("acquire")
        return await original_acquire(platform)

    original_push = ctrl.adb_push
    async def tracking_push(*args):
        acquire_order.append("push")
        return await original_push(*args)

    lock.acquire_foreground = tracking_acquire
    ctrl.adb_push = AsyncMock(side_effect=tracking_push)

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    assert acquire_order[0] == "acquire"
    assert "push" in acquire_order
    assert acquire_order.index("acquire") < acquire_order.index("push")


async def test_foreground_lock_released_after_posting():
    """Foreground lock must be released after posting (in finally block)."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    # After the session the foreground lock must be free
    assert not lock._foreground_lock.locked()


async def test_daily_cap_enforced_at_3_grid_posts():
    """Agent must refuse to post when the daily grid cap (3) is already reached."""
    # already_posted = 3 → remaining = 0 → should return failure immediately
    task = make_task(
        post_type="grid",
        media_files=["/tmp/photo.jpg"],
        daily_counts={"grid": 3},
    )
    ctrl = make_phone_controller()
    lock = make_slot_lock()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    agent = IGForegroundPostAgent()
    result = await agent.run_session(task, ctrl, lock)

    assert result.success is False
    assert "daily_cap_reached" in (result.error or "")
    # ADB push must NOT have been called — cap check runs before any phone action
    ctrl.adb_push.assert_not_called()


async def test_pre_post_browse_delay_called():
    """pre_post_browse_delay must be called once per session (before posting)."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

        mock_hpb.pre_post_browse_delay.assert_called_once()


async def test_rethink_pause_fires_at_approximately_15_percent():
    """
    should_rethink returns True ~15% of the time.

    Run 400 iterations; expect rethink_pause to fire between 5% and 30%
    (wide band to avoid flakiness, verifying it is neither 0% nor 100%).
    """
    fire_count = 0
    total = 400

    for i in range(total):
        task   = make_task()
        ctrl   = make_phone_controller()
        lock   = make_slot_lock()
        client = make_mock_http_client()

        ctrl.adb_push  = AsyncMock()
        ctrl.adb_shell = AsyncMock()

        rethink_mock = AsyncMock()
        with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
            mock_hpb.pre_post_browse_delay = AsyncMock()
            mock_hpb.compose_dwell         = AsyncMock()
            mock_hpb.rethink_pause         = rethink_mock
            # Use real should_rethink from human_post_behavior
            import phantom_fleet.core.human_post_behavior as real_hpb
            mock_hpb.should_rethink = real_hpb.should_rethink
            mock_hpb.inter_post_delay = AsyncMock()

            agent = IGForegroundPostAgent(http_client=client)
            await agent.run_session(task, ctrl, lock)

        fire_count += rethink_mock.call_count

    rate = fire_count / total
    assert 0.05 <= rate <= 0.30, (
        f"rethink_pause fired {fire_count}/{total} times ({rate:.1%}), "
        f"expected 5–30%"
    )


async def test_worker_result_fields_correct_on_success():
    """WorkerResult must carry correct metadata on a successful post."""
    task   = make_task(post_type="story")
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(post_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success is True
    assert result.platform == "instagram"
    assert result.account_id == "acc_001"
    assert result.data["posts_submitted"] == 1
    assert result.data["posts_failed"]    == 0
    assert result.data["post_type"]       == "story"
    assert result.data["errors"]          == []


async def test_worker_result_failure_on_apk_error_response():
    """WorkerResult must reflect failure when APK returns success=false."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(post_success=False, apk_error="share_timeout")

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_foreground_post_agent.human_post_behavior") as mock_hpb:
        mock_hpb.pre_post_browse_delay = AsyncMock()
        mock_hpb.compose_dwell         = AsyncMock()
        mock_hpb.rethink_pause         = AsyncMock()
        mock_hpb.should_rethink        = MagicMock(return_value=False)
        mock_hpb.inter_post_delay      = AsyncMock()

        agent = IGForegroundPostAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success is False
    assert result.data["posts_submitted"] == 0
    assert result.data["posts_failed"]    == 1
    assert any("share_timeout" in e for e in result.data["errors"])


async def test_validation_fails_on_mismatched_media_captions():
    """Validation must fail if media_files and captions have different lengths."""
    task = make_task(
        media_files=["/tmp/a.jpg", "/tmp/b.jpg"],
        captions=["Only one caption"],   # mismatch: 2 files, 1 caption
    )
    ctrl = make_phone_controller()
    lock = make_slot_lock()

    agent = IGForegroundPostAgent()
    result = await agent.run_session(task, ctrl, lock)

    assert result.success is False
    assert result.data["posts_submitted"] == 0
    assert any("length mismatch" in e for e in result.data["errors"])


# ---------------------------------------------------------------------------
# IGContentScheduler tests
# ---------------------------------------------------------------------------

def make_accounts(n: int) -> list[AccountConfig]:
    return [
        AccountConfig(
            account_id    = f"acc_{i:03d}",
            phone_serial  = f"192.168.1.{i}:5555",
            clone_package = f"com.instagram.android.clone{i}",
            active_timezone = "America/New_York",
            post_quota    = {"grid": 2, "story": 1},
        )
        for i in range(n)
    ]


def make_vault_items(n: int, post_type: str = "grid") -> list[ContentVaultItem]:
    return [
        ContentVaultItem(
            item_id    = f"item_{i:04d}",
            local_path = f"/vault/{post_type}/media_{i:04d}.jpg",
            caption    = f"Caption for item {i}",
            post_type  = post_type,
        )
        for i in range(n)
    ]


def test_scheduler_no_two_accounts_post_at_exact_same_second():
    """
    No two accounts must be scheduled at exactly the same Unix second.

    Fleet-scale test: 50 accounts × grid quota 1 = 50 posts.
    Per-account deterministic offset must prevent any two timestamps from
    colliding at second precision.
    """
    accounts = make_accounts(50)
    vault    = make_vault_items(200, "grid")

    # Override quota so each account posts exactly 1 grid per day
    for acc in accounts:
        acc.post_quota = {"grid": 1}

    scheduler = IGContentScheduler()
    schedule  = scheduler.build_daily_schedule(accounts, vault, "2026-04-11")

    times = [int(p.scheduled_at_unix) for p in schedule.posts]
    unique_times = set(times)

    # Every scheduled second must be unique
    assert len(times) == len(unique_times), (
        f"Found duplicate scheduled seconds among {len(times)} posts: "
        f"{len(times) - len(unique_times)} collisions"
    )


def test_scheduler_jitter_applied_per_account():
    """scheduled_at_unix must differ from the un-jittered base by the jitter amount."""
    accounts = make_accounts(3)
    vault    = make_vault_items(20, "grid")

    scheduler = IGContentScheduler()
    schedule  = scheduler.build_daily_schedule(accounts, vault, "2026-04-11")

    # Verify that jitter_applied_sec is stored and is not always 0
    jitters = [abs(p.jitter_applied_sec) for p in schedule.posts]
    # At least some jitter must be non-zero (probability of all-zero is negligible)
    assert any(j != 0 for j in jitters), "All posts have zero jitter — jitter not applied"


def test_scheduler_timezone_peak_hours_respected():
    """
    Posts should be scheduled within 9:00–21:00 local time.

    Use UTC timezone so local time == UTC time for simple verification.
    Check every post falls inside the union of the two peak windows
    (9:00-12:00 and 18:00-21:00) plus jitter (up to ±30 min).
    """
    accounts = [
        AccountConfig(
            account_id    = "acc_tz_test",
            phone_serial  = "192.168.1.99:5555",
            clone_package = "com.instagram.android.clone1",
            active_timezone = "UTC",
            post_quota    = {"grid": 1},
        )
    ]
    vault = make_vault_items(10, "grid")

    scheduler = IGContentScheduler()
    schedule  = scheduler.build_daily_schedule(accounts, vault, "2026-04-11")

    for post in schedule.posts:
        # Convert to UTC hour (same as local for UTC timezone)
        hour = datetime.fromtimestamp(post.scheduled_at_unix, tz=timezone.utc).hour
        # Allow ±1 hour window around peak windows to account for jitter (max ±30 min)
        in_morning_window = 8 <= hour <= 13
        in_evening_window = 17 <= hour <= 21
        assert in_morning_window or in_evening_window, (
            f"Post scheduled at local hour {hour} — outside peak windows "
            f"(expected 8-13 or 17-21, accounting for ±30 min jitter)"
        )


def test_scheduler_daily_schedule_has_correct_count():
    """
    DailyPostSchedule.total_posts must equal sum of all account quotas
    (subject to vault availability).
    """
    n_accounts = 5
    accounts   = make_accounts(n_accounts)
    # Each account: grid=2, story=1 → 3 posts/account × 5 = 15 total
    vault_grid  = make_vault_items(50, "grid")
    vault_story = make_vault_items(50, "story")

    scheduler = IGContentScheduler()
    schedule  = scheduler.build_daily_schedule(
        accounts,
        vault_grid + vault_story,
        "2026-04-11",
    )

    expected = n_accounts * (2 + 1)   # grid=2, story=1 per account
    assert schedule.total_posts == expected, (
        f"Expected {expected} posts, got {schedule.total_posts}"
    )


# ---------------------------------------------------------------------------
# PhoneController.adb_push tests
# ---------------------------------------------------------------------------

async def test_adb_push_formats_command_correctly():
    """adb_push must issue `adb -s <serial> push <local> <remote>`."""
    ctrl = make_phone_controller()

    with patch(
        "phantom_fleet.core.phone_controller._run_adb",
        new_callable=AsyncMock,
    ) as mock_run_adb:
        mock_run_adb.return_value = ""
        await ctrl.adb_push("/tmp/photo.jpg", "/sdcard/DCIM/PhantomFleet/abc.jpg")

    mock_run_adb.assert_called_once_with(
        "-s", "192.168.1.42:5555",
        "push",
        "/tmp/photo.jpg",
        "/sdcard/DCIM/PhantomFleet/abc.jpg",
        timeout=60,
    )


async def test_adb_push_raises_on_nonzero_exit():
    """adb_push must propagate ADBCommandFailed from _run_adb."""
    ctrl = make_phone_controller()

    with patch(
        "phantom_fleet.core.phone_controller._run_adb",
        new_callable=AsyncMock,
        side_effect=ADBCommandFailed("adb push failed: error: device unauthorized"),
    ):
        with pytest.raises(ADBCommandFailed, match="device unauthorized"):
            await ctrl.adb_push("/tmp/photo.jpg", "/sdcard/DCIM/PhantomFleet/abc.jpg")
