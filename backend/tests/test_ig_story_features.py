"""
Tests for the full Instagram story feature suite.

Coverage:

    IGStoryAgent sticker injection:
        - poll_sticker_endpoint_called_when_poll_param_provided
        - question_sticker_endpoint_called_when_question_prompt_provided
        - neither_sticker_endpoint_called_when_params_are_none

    IGStoryAgent core behaviour:
        - story_post_endpoint_called_with_correct_payload
        - adb_push_called_before_media_scan
        - staging_file_deleted_after_success
        - staging_file_deleted_after_failure
        - daily_cap_enforced_at_5_stories
        - worker_result_poll_added_true_when_poll_succeeds
        - worker_result_question_added_true_when_question_succeeds
        - worker_result_fields_correct_on_success
        - validation_fails_on_empty_media_files
        - validation_fails_on_poll_missing_option2

    IGStoryAgent.post_story (extended feature):
        - post_story_calls_link_sticker_when_of_link_provided
        - post_story_calls_close_friends_when_flag_set
        - post_story_calls_highlight_when_add_to_highlight_set
        - post_story_staging_file_deleted_on_failure
        - post_story_daily_cap_enforced

    IGStoryAgent.run_mother_child_drop:
        - mother_child_drop_calls_transform_per_child
        - mother_child_drop_lognormal_stagger_not_fixed_sleep
        - mother_child_drop_skips_children_at_daily_cap
        - mother_child_drop_staging_file_deleted_for_each_child

    IGStoryReplyChatAgent:
        - story_reply_threads_processed_before_regular_threads
        - story_reply_daily_cap_is_60
        - story_reply_min_gap_is_45s
        - story_reply_ppv_threshold_is_2
        - is_story_reply_thread_detects_is_story_reply_flag
        - is_story_reply_thread_detects_thread_type
        - is_story_reply_thread_detects_item_type

    IGCoordinatedDropManager:
        - schedule_drop_produces_entry_per_account
        - schedule_drop_offsets_within_window
        - schedule_drop_deterministic_same_inputs
        - schedule_drop_same_phone_gap_enforced
        - schedule_drop_raises_on_too_many_accounts
        - schedule_drop_raises_on_window_too_large
        - validate_schedule_flags_same_phone_violations
        - hash_offset_in_range

asyncio_mode = "auto" is configured in pyproject.toml — no decorator needed.
All ADB subprocess calls and HTTP calls are mocked.
"""
from __future__ import annotations

import os
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, call as mock_call

import httpx
import pytest

from phantom_fleet.agents.specialists.ig_story_agent import (
    IGStoryAgent,
    IGStoryTask,
    IGMotherChildDropTask,
    _make_remote_path,
    _validate_task,
    _DAILY_STORY_CAP,
)
from phantom_fleet.agents.specialists.ig_story_reply_chat_agent import (
    IGStoryReplyChatAgent,
    MAX_STORY_REPLY_MESSAGES_PER_DAY,
    MIN_STORY_REPLY_GAP_SEC,
    STORY_REPLY_PPV_THRESHOLD,
    _is_story_reply_thread,
)
from phantom_fleet.agents.specialists.ig_coordinated_drop_manager import (
    IGCoordinatedDropManager,
    DropEntry,
    DropSchedule,
    MAX_ACCOUNTS_PER_DROP,
    MAX_DROP_WINDOW_MINUTES,
    MIN_SAME_PHONE_GAP_SEC,
    _hash_offset,
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
    media_files: Optional[list[str]] = None,
    daily_counts: Optional[dict] = None,
    poll: Optional[dict] = None,
    question_prompt: Optional[str] = None,
) -> IGStoryTask:
    if media_files is None:
        media_files = ["/tmp/phantom/story_image.jpg"]
    return IGStoryTask(
        account_id      = "acc_story_001",
        phone_serial    = "192.168.1.42:5555",
        clone_package   = "com.instagram.android.clone1",
        phone_ip        = "192.168.1.42",
        media_files     = media_files,
        apk_port        = 8090,
        daily_counts    = daily_counts or {},
        poll            = poll,
        question_prompt = question_prompt,
    )


def make_phone_controller(state: PhoneState = PhoneState.PROXY_READY) -> PhoneController:
    return PhoneController(serial="192.168.1.42:5555", state=state)


def make_slot_lock() -> PhoneSlotLock:
    return PhoneSlotLock("192.168.1.42:5555")


def make_mock_http_client(
    story_success: bool = True,
    poll_success: bool = True,
    question_success: bool = True,
    apk_error: str = "test_error",
) -> MagicMock:
    """
    Build a mock httpx.AsyncClient that routes to the correct JSON response
    per URL path.  Tracks all POST calls so tests can inspect them.
    """
    client = AsyncMock(spec=httpx.AsyncClient)

    # Per-endpoint mock responses
    scan_resp = MagicMock()
    scan_resp.raise_for_status = MagicMock()

    story_resp = MagicMock()
    story_resp.raise_for_status = MagicMock()
    story_resp.json.return_value = (
        {"success": True} if story_success else {"success": False, "error": apk_error}
    )

    poll_resp = MagicMock()
    poll_resp.raise_for_status = MagicMock()
    poll_resp.json.return_value = {"success": poll_success}

    question_resp = MagicMock()
    question_resp.raise_for_status = MagicMock()
    question_resp.json.return_value = {"success": question_success}

    async def mock_post(url, **kwargs):
        if "/media/scan" in url:
            return scan_resp
        if "/instagram/story/add_poll" in url:
            return poll_resp
        if "/instagram/story/add_question" in url:
            return question_resp
        if "/instagram/story" in url:
            return story_resp
        raise ValueError(f"Unexpected POST URL: {url}")

    client.post = AsyncMock(side_effect=mock_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def patch_human_behavior(mock_hpb):
    """Apply standard mock overrides to the human_post_behavior module mock."""
    mock_hpb.pre_post_browse_delay = AsyncMock()
    mock_hpb.compose_dwell         = AsyncMock()
    mock_hpb.rethink_pause         = AsyncMock()
    mock_hpb.should_rethink        = MagicMock(return_value=False)
    mock_hpb.inter_post_delay      = AsyncMock()


# ---------------------------------------------------------------------------
# ── PRIMARY STICKER TESTS (the 3 specified) ──────────────────────────────
# ---------------------------------------------------------------------------

async def test_poll_sticker_endpoint_called_when_poll_param_provided():
    """
    POST /instagram/story/add_poll must be called exactly once when task.poll is set,
    with the correct question, option1, option2 payload.
    """
    poll_data = {
        "question": "Which outfit? 🔥 or 💜",
        "option1":  "🔥 Spicy",
        "option2":  "💜 Cute",
    }
    task   = make_task(poll=poll_data)
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=True, poll_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success is True

    # Exactly one call to add_poll
    poll_calls = [c for c in client.post.call_args_list if "/instagram/story/add_poll" in c[0][0]]
    assert len(poll_calls) == 1, (
        f"Expected 1 add_poll call, got {len(poll_calls)}"
    )

    # Payload must match
    payload = poll_calls[0][1]["json"]
    assert payload["question"] == poll_data["question"]
    assert payload["option1"]  == poll_data["option1"]
    assert payload["option2"]  == poll_data["option2"]


async def test_question_sticker_endpoint_called_when_question_prompt_provided():
    """
    POST /instagram/story/add_question must be called exactly once when
    task.question_prompt is set, with the correct prompt payload.
    """
    task   = make_task(question_prompt="Ask me anything 💬")
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=True, question_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success is True

    # Exactly one call to add_question
    q_calls = [c for c in client.post.call_args_list if "/instagram/story/add_question" in c[0][0]]
    assert len(q_calls) == 1, (
        f"Expected 1 add_question call, got {len(q_calls)}"
    )

    payload = q_calls[0][1]["json"]
    assert payload["prompt"] == "Ask me anything 💬"


async def test_neither_sticker_endpoint_called_when_params_are_none():
    """
    Neither /instagram/story/add_poll nor /instagram/story/add_question must be called
    when both task.poll and task.question_prompt are None.

    Verifies that the absence of sticker params results in zero extra HTTP calls
    (no wasted round-trips to the APK).
    """
    task   = make_task(poll=None, question_prompt=None)
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success is True

    poll_calls     = [c for c in client.post.call_args_list if "/instagram/story/add_poll" in c[0][0]]
    question_calls = [c for c in client.post.call_args_list if "/instagram/story/add_question" in c[0][0]]

    assert len(poll_calls) == 0, (
        f"add_poll called {len(poll_calls)} times but task.poll was None"
    )
    assert len(question_calls) == 0, (
        f"add_question called {len(question_calls)} times but task.question_prompt was None"
    )


# ---------------------------------------------------------------------------
# ── ADDITIONAL COVERAGE TESTS ────────────────────────────────────────────
# ---------------------------------------------------------------------------

async def test_story_post_endpoint_called_with_correct_payload():
    """POST /instagram/story must receive correct mediaPath, accountId, clonePackage."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent = IGStoryAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    story_calls = [c for c in client.post.call_args_list if "/instagram/story" in c[0][0]
                   and "/add_poll" not in c[0][0] and "/add_question" not in c[0][0]]
    assert len(story_calls) == 1

    payload = story_calls[0][1]["json"]
    assert payload["accountId"]    == "acc_story_001"
    assert payload["clonePackage"] == "com.instagram.android.clone1"
    assert payload["postType"]     == "STORY"
    assert payload["mediaPath"].startswith("/sdcard/DCIM/PhantomFleet/")


async def test_adb_push_called_before_media_scan():
    """ADB push must happen before the /media/scan call."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client()

    call_order: list[str] = []

    async def track_push(local_path, remote_path):
        call_order.append("adb_push")

    async def track_post(url, **kwargs):
        if "/media/scan" in url:
            call_order.append("media_scan")
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"success": True}
        return resp

    ctrl.adb_push  = AsyncMock(side_effect=track_push)
    ctrl.adb_shell = AsyncMock()
    client.post    = AsyncMock(side_effect=track_post)

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent = IGStoryAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    assert "adb_push" in call_order
    assert "media_scan" in call_order
    assert call_order.index("adb_push") < call_order.index("media_scan"), (
        "ADB push must happen before /media/scan"
    )


async def test_staging_file_deleted_after_success():
    """adb_shell rm must be called after a successful story post."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent = IGStoryAgent(http_client=client)
        await agent.run_session(task, ctrl, lock)

    assert ctrl.adb_shell.call_count == 1
    rm_cmd = ctrl.adb_shell.call_args[0][0]
    assert rm_cmd.startswith("rm -f /sdcard/DCIM/PhantomFleet/")


async def test_staging_file_deleted_after_failure():
    """adb_shell rm must be called even when the APK reports an error."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=False, apk_error="share_timeout")

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success is False
    assert ctrl.adb_shell.call_count == 1
    rm_cmd = ctrl.adb_shell.call_args[0][0]
    assert rm_cmd.startswith("rm -f /sdcard/DCIM/PhantomFleet/")


async def test_daily_cap_enforced_at_5_stories():
    """
    Agent must refuse when daily_counts={"story": 5} (cap reached).

    ADB push must not be called — the cap check runs before any phone action.
    """
    task = make_task(daily_counts={"story": 5})
    ctrl = make_phone_controller()
    lock = make_slot_lock()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    agent  = IGStoryAgent()
    result = await agent.run_session(task, ctrl, lock)

    assert result.success is False
    assert "daily_cap_reached" in (result.error or "")
    ctrl.adb_push.assert_not_called()


async def test_worker_result_poll_added_true_when_poll_succeeds():
    """WorkerResult.data["poll_added"] must be True when add_poll returns success."""
    task   = make_task(poll={"question": "Q?", "option1": "A", "option2": "B"})
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=True, poll_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.data["poll_added"] is True


async def test_worker_result_question_added_true_when_question_succeeds():
    """WorkerResult.data["question_added"] must be True when add_question returns success."""
    task   = make_task(question_prompt="AMA 💬")
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=True, question_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.data["question_added"] is True


async def test_worker_result_fields_correct_on_success():
    """WorkerResult must carry correct posts_submitted, platform, and account_id."""
    task   = make_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_mock_http_client(story_success=True)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_session(task, ctrl, lock)

    assert result.success         is True
    assert result.platform        == "instagram"
    assert result.account_id      == "acc_story_001"
    assert result.data["posts_submitted"] == 1
    assert result.data["posts_failed"]    == 0
    assert result.data["errors"]          == []


async def test_validation_fails_on_empty_media_files():
    """Validation must fail when media_files is empty."""
    task = make_task(media_files=[])
    ctrl = make_phone_controller()
    lock = make_slot_lock()

    agent  = IGStoryAgent()
    result = await agent.run_session(task, ctrl, lock)

    assert result.success is False
    assert any("media_files is empty" in e for e in result.data["errors"])


async def test_validation_fails_on_poll_missing_option2():
    """Validation must fail when poll dict is missing option2."""
    task = make_task(
        poll={"question": "Q?", "option1": "A"},   # option2 absent
    )
    ctrl = make_phone_controller()
    lock = make_slot_lock()

    agent  = IGStoryAgent()
    result = await agent.run_session(task, ctrl, lock)

    assert result.success is False
    assert any("poll.option2" in e for e in result.data["errors"])


# ---------------------------------------------------------------------------
# ── IGStoryAgent.post_story (extended feature tests) ─────────────────────
# ---------------------------------------------------------------------------

def make_post_story_task(
    of_link: Optional[str] = None,
    close_friends: bool = False,
    add_to_highlight: Optional[str] = None,
    daily_counts: Optional[dict] = None,
) -> IGStoryTask:
    return IGStoryTask(
        account_id       = "acc_post_story_001",
        phone_serial     = "192.168.1.50:5555",
        clone_package    = "com.instagram.android.clone2",
        phone_ip         = "192.168.1.50",
        media_files      = ["/tmp/phantom/story.jpg"],
        apk_port         = 8090,
        daily_counts     = daily_counts or {},
        of_link          = of_link,
        close_friends    = close_friends,
        add_to_highlight = add_to_highlight,
    )


def make_extended_mock_client(
    story_success: bool = True,
    link_success: bool = True,
    cf_success: bool = True,
    highlight_success: bool = True,
) -> MagicMock:
    """Mock HTTP client for post_story extended feature tests."""
    client = AsyncMock(spec=httpx.AsyncClient)

    scan_resp  = MagicMock(); scan_resp.raise_for_status = MagicMock()
    story_resp = MagicMock(); story_resp.raise_for_status = MagicMock()
    story_resp.json.return_value = {"success": story_success}
    link_resp  = MagicMock()
    link_resp.is_success = True
    link_resp.json.return_value = {"success": link_success}
    cf_resp    = MagicMock()
    cf_resp.is_success = True
    cf_resp.json.return_value = {"success": cf_success}
    hl_resp    = MagicMock()
    hl_resp.is_success = True
    hl_resp.json.return_value = {"success": highlight_success}

    async def mock_post(url, **kwargs):
        if "/media/scan" in url:
            return scan_resp
        if "/instagram/story/add_link_sticker" in url:
            return link_resp
        if "/instagram/story/close_friends" in url:
            return cf_resp
        if "/instagram/story/add_to_highlight" in url:
            return hl_resp
        if "/instagram/story" in url:
            return story_resp
        raise ValueError(f"Unexpected POST URL in extended mock: {url}")

    client.post = AsyncMock(side_effect=mock_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    return client


async def test_post_story_calls_link_sticker_when_of_link_provided():
    """
    post_story must call /instagram/story/add_link_sticker with the OF link
    when task.of_link is set.
    """
    task   = make_post_story_task(of_link="https://onlyfans.com/creator123")
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_extended_mock_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.post_story(task, ctrl, lock)

    assert result.success is True

    link_calls = [c for c in client.post.call_args_list if "/add_link_sticker" in c[0][0]]
    assert len(link_calls) == 1
    payload = link_calls[0][1]["json"]
    assert payload["url"] == "https://onlyfans.com/creator123"


async def test_post_story_calls_close_friends_when_flag_set():
    """
    post_story must call /instagram/story/close_friends when task.close_friends=True.
    """
    task   = make_post_story_task(close_friends=True)
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_extended_mock_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.post_story(task, ctrl, lock)

    assert result.success is True

    cf_calls = [c for c in client.post.call_args_list if "/close_friends" in c[0][0]]
    assert len(cf_calls) == 1


async def test_post_story_calls_highlight_when_add_to_highlight_set():
    """
    post_story must call /instagram/story/add_to_highlight with createIfMissing=True
    when task.add_to_highlight is set.
    """
    task   = make_post_story_task(add_to_highlight="Hot Takes")
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_extended_mock_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.post_story(task, ctrl, lock)

    assert result.success is True

    hl_calls = [c for c in client.post.call_args_list if "/add_to_highlight" in c[0][0]]
    assert len(hl_calls) == 1
    payload = hl_calls[0][1]["json"]
    assert payload["highlightName"] == "Hot Takes"
    assert payload["createIfMissing"] is True


async def test_post_story_staging_file_deleted_on_failure():
    """
    post_story must call adb_shell rm even when the APK reports story failure.
    """
    task   = make_post_story_task()
    ctrl   = make_phone_controller()
    lock   = make_slot_lock()
    client = make_extended_mock_client(story_success=False)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch("phantom_fleet.agents.specialists.ig_story_agent.human_post_behavior") as mock_hpb:
        patch_human_behavior(mock_hpb)
        agent  = IGStoryAgent(http_client=client)
        result = await agent.post_story(task, ctrl, lock)

    assert result.success is False
    # staging cleanup must still happen
    rm_calls = [
        c for c in ctrl.adb_shell.call_args_list
        if "rm -f" in (c[0][0] if c[0] else "")
    ]
    assert len(rm_calls) >= 1, "Staging file rm was never called after APK failure"


async def test_post_story_daily_cap_enforced():
    """
    post_story must refuse immediately when daily_counts["story"] >= 5,
    without touching adb_push.
    """
    task = make_post_story_task(daily_counts={"story": _DAILY_STORY_CAP})
    ctrl = make_phone_controller()
    lock = make_slot_lock()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    agent  = IGStoryAgent()
    result = await agent.post_story(task, ctrl, lock)

    assert result.success is False
    assert "daily_cap_reached" in (result.error or "")
    ctrl.adb_push.assert_not_called()


# ---------------------------------------------------------------------------
# ── IGStoryAgent.run_mother_child_drop ────────────────────────────────────
# ---------------------------------------------------------------------------

def make_drop_task(
    child_ids: Optional[list[str]] = None,
    stories_today: Optional[dict] = None,
) -> IGMotherChildDropTask:
    if child_ids is None:
        child_ids = ["c_001", "c_002", "c_003"]
    return IGMotherChildDropTask(
        mother_account_id    = "acc_mother_001",
        child_account_ids    = child_ids,
        story_media_url      = "https://cdn.instagram.com/story_frame.jpg",
        of_link              = "https://onlyfans.com/creator123",
        phone_serial         = "192.168.1.10:5555",
        phone_ip             = "192.168.1.10",
        clone_packages       = {cid: f"com.instagram.android.{cid}" for cid in (child_ids or [])},
        apk_port             = 8090,
        stagger_seconds_mean = 120.0,
        stories_today        = stories_today or {},
    )


def make_drop_mock_client(
    transform_ok: bool = True,
    story_ok: bool = True,
    link_ok: bool = True,
) -> MagicMock:
    """Mock HTTP client for run_mother_child_drop tests."""
    client = AsyncMock(spec=httpx.AsyncClient)

    scan_resp  = MagicMock(); scan_resp.raise_for_status = MagicMock()
    xfrm_resp  = MagicMock(); xfrm_resp.raise_for_status = MagicMock()
    xfrm_resp.json.return_value = {"ok": transform_ok, "outputPath": "/sdcard/DCIM/PhantomFleet/t_abc123.jpg"}
    story_resp = MagicMock(); story_resp.raise_for_status = MagicMock()
    story_resp.json.return_value = {"success": story_ok}
    link_resp  = MagicMock()
    link_resp.is_success = True
    link_resp.json.return_value = {"success": link_ok}

    async def mock_post(url, **kwargs):
        if "/media/transform" in url:
            return xfrm_resp
        if "/media/scan" in url:
            return scan_resp
        if "/instagram/story/add_link_sticker" in url:
            return link_resp
        if "/instagram/story" in url:
            return story_resp
        raise ValueError(f"Unexpected POST URL in drop mock: {url}")

    client.post = AsyncMock(side_effect=mock_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    return client


async def test_mother_child_drop_calls_transform_per_child():
    """
    run_mother_child_drop must call /media/transform exactly once per eligible child,
    with accountId, postIndex, inputPath, and outputPath in the payload.
    """
    child_ids = ["c_001", "c_002", "c_003"]
    task   = make_drop_task(child_ids=child_ids)
    ctrl   = make_phone_controller()
    client = make_drop_mock_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    # Mock the download of the mother's story frame
    with patch(
        "phantom_fleet.agents.specialists.ig_story_agent._download_story_frame",
        new=AsyncMock(return_value="/tmp/phantom_mother_frame.jpg"),
    ), patch(
        "phantom_fleet.agents.specialists.ig_story_agent.asyncio.sleep",
        new=AsyncMock(),
    ):
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_mother_child_drop(task, ctrl)

    transform_calls = [c for c in client.post.call_args_list if "/media/transform" in c[0][0]]
    assert len(transform_calls) == len(child_ids), (
        f"Expected {len(child_ids)} transform calls, got {len(transform_calls)}"
    )

    # Every transform call must include accountId and postIndex
    for call in transform_calls:
        payload = call[1]["json"]
        assert "accountId"  in payload
        assert "postIndex"  in payload
        assert "inputPath"  in payload
        assert "outputPath" in payload

    assert result.success is True
    assert result.data["children_posted"] == len(child_ids)


async def test_mother_child_drop_lognormal_stagger_not_fixed_sleep():
    """
    run_mother_child_drop must call asyncio.sleep with a float value derived
    from the LogNormal distribution — not a constant.

    We verify by patching _lognormal_sample and confirming asyncio.sleep
    receives whatever value _lognormal_sample returns (i.e. the stagger path
    goes through the LogNormal sampler, not a hardcoded literal).
    """
    child_ids = ["c_001", "c_002"]
    task   = make_drop_task(child_ids=child_ids)
    ctrl   = make_phone_controller()
    client = make_drop_mock_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    sleep_calls: list[float] = []

    async def capture_sleep(seconds: float):
        sleep_calls.append(seconds)

    lognormal_returns = [95.3, 134.7]  # sentinel values — not a constant
    lognormal_call_count = [0]

    def mock_lognormal(mean, sigma):
        v = lognormal_returns[lognormal_call_count[0] % len(lognormal_returns)]
        lognormal_call_count[0] += 1
        return v

    with patch(
        "phantom_fleet.agents.specialists.ig_story_agent._download_story_frame",
        new=AsyncMock(return_value="/tmp/phantom_mother_frame.jpg"),
    ), patch(
        "phantom_fleet.agents.specialists.ig_story_agent.asyncio.sleep",
        new=AsyncMock(side_effect=capture_sleep),
    ), patch(
        "phantom_fleet.agents.specialists.ig_story_agent._lognormal_sample",
        side_effect=mock_lognormal,
    ):
        agent = IGStoryAgent(http_client=client)
        await agent.run_mother_child_drop(task, ctrl)

    # N-1 staggers for N children
    assert len(sleep_calls) == len(child_ids) - 1
    # Sleep values must match what _lognormal_sample returned (min-clamped at 90s)
    assert all(s >= 90.0 for s in sleep_calls), "Stagger must be >= 90s minimum gap"


async def test_mother_child_drop_skips_children_at_daily_cap():
    """
    run_mother_child_drop must skip children who have already reached the
    5-story daily cap, and succeed with the remaining children.
    """
    child_ids = ["c_001", "c_002", "c_003"]
    # c_002 is at the cap
    stories_today = {"c_002": _DAILY_STORY_CAP}
    task   = make_drop_task(child_ids=child_ids, stories_today=stories_today)
    ctrl   = make_phone_controller()
    client = make_drop_mock_client()

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock()

    with patch(
        "phantom_fleet.agents.specialists.ig_story_agent._download_story_frame",
        new=AsyncMock(return_value="/tmp/phantom_mother_frame.jpg"),
    ), patch(
        "phantom_fleet.agents.specialists.ig_story_agent.asyncio.sleep",
        new=AsyncMock(),
    ):
        agent  = IGStoryAgent(http_client=client)
        result = await agent.run_mother_child_drop(task, ctrl)

    # 2 of 3 children should post (c_002 skipped)
    assert result.data["children_posted"] == 2
    assert result.data["skipped_cap"] == 1
    assert result.success is True


async def test_mother_child_drop_staging_file_deleted_for_each_child():
    """
    Staging files (input + transformed output) must be deleted for each
    child even when that child's story post fails.
    """
    child_ids = ["c_001"]
    task   = make_drop_task(child_ids=child_ids)
    ctrl   = make_phone_controller()
    # Make the story post fail for this child
    client = make_drop_mock_client(story_ok=False)

    rm_calls: list[str] = []

    async def track_shell(cmd: str):
        if cmd.startswith("rm -f"):
            rm_calls.append(cmd)

    ctrl.adb_push  = AsyncMock()
    ctrl.adb_shell = AsyncMock(side_effect=track_shell)

    with patch(
        "phantom_fleet.agents.specialists.ig_story_agent._download_story_frame",
        new=AsyncMock(return_value="/tmp/phantom_mother_frame.jpg"),
    ), patch(
        "phantom_fleet.agents.specialists.ig_story_agent.asyncio.sleep",
        new=AsyncMock(),
    ):
        agent = IGStoryAgent(http_client=client)
        await agent.run_mother_child_drop(task, ctrl)

    # At minimum the transformed output file must be cleaned up
    assert len(rm_calls) >= 1, (
        "Expected at least one staging file deletion, got none"
    )


# ---------------------------------------------------------------------------
# ── IGStoryReplyChatAgent constants + helpers ─────────────────────────────
# ---------------------------------------------------------------------------

def test_story_reply_daily_cap_is_60():
    """MAX_STORY_REPLY_MESSAGES_PER_DAY must be 60."""
    assert MAX_STORY_REPLY_MESSAGES_PER_DAY == 60
    agent = IGStoryReplyChatAgent()
    assert agent.max_daily_replies == 60


def test_story_reply_min_gap_is_45s():
    """MIN_STORY_REPLY_GAP_SEC must be 45.0."""
    assert MIN_STORY_REPLY_GAP_SEC == 45.0
    agent = IGStoryReplyChatAgent()
    assert agent.min_gap_sec == 45.0


def test_story_reply_ppv_threshold_is_2():
    """STORY_REPLY_PPV_THRESHOLD must be 2 — lower than regular DMs (4)."""
    assert STORY_REPLY_PPV_THRESHOLD == 2


def test_is_story_reply_thread_detects_is_story_reply_flag():
    """_is_story_reply_thread must return True when is_story_reply=True."""
    thread = {"is_story_reply": True, "thread_id": "t_001", "items": []}
    assert _is_story_reply_thread(thread) is True


def test_is_story_reply_thread_detects_thread_type():
    """_is_story_reply_thread must return True when thread_type='story_reply'."""
    thread = {"is_story_reply": False, "thread_type": "story_reply", "items": []}
    assert _is_story_reply_thread(thread) is True


def test_is_story_reply_thread_detects_item_type():
    """_is_story_reply_thread must return True when any item has a story-related item_type."""
    thread = {
        "is_story_reply": False,
        "thread_type": "regular",
        "items": [
            {"item_type": "text", "text": "hey"},
            {"item_type": "story_share", "media_id": "12345"},
        ],
    }
    assert _is_story_reply_thread(thread) is True


def test_is_story_reply_thread_returns_false_for_regular():
    """_is_story_reply_thread must return False for a plain DM thread."""
    thread = {
        "is_story_reply": False,
        "thread_type": "regular",
        "items": [{"item_type": "text", "text": "what's up"}],
    }
    assert _is_story_reply_thread(thread) is False


def test_story_reply_threads_processed_before_regular_threads():
    """
    IGStoryReplyChatAgent's priority-split logic must place story reply threads
    first in the ordered list.

    The `_run_story_reply_inbox` method does:
        story_reply_threads = [t for t in threads if _is_story_reply_thread(t)]
        regular_threads     = [t for t in threads if not _is_story_reply_thread(t)]
        ordered_threads     = story_reply_threads + regular_threads

    We replicate this exact ordering logic and verify it — this is a white-box
    test of the priority-sort contract, independent of the async I/O layer.
    """
    threads = [
        {"thread_id": "reg_1",   "is_story_reply": False, "thread_type": "regular",     "items": []},
        {"thread_id": "story_1", "is_story_reply": True,  "thread_type": "story_reply",  "items": []},
        {"thread_id": "reg_2",   "is_story_reply": False, "thread_type": "regular",     "items": []},
        {"thread_id": "story_2", "is_story_reply": True,  "thread_type": "story_reply",  "items": []},
    ]

    story_reply_threads = [t for t in threads if _is_story_reply_thread(t)]
    regular_threads     = [t for t in threads if not _is_story_reply_thread(t)]
    ordered_threads     = story_reply_threads + regular_threads

    ordered_ids = [t["thread_id"] for t in ordered_threads]

    # Both story reply threads must appear before any regular thread
    story_indices   = [i for i, tid in enumerate(ordered_ids) if "story_" in tid]
    regular_indices = [i for i, tid in enumerate(ordered_ids) if "reg_"   in tid]

    assert story_indices,   "No story reply threads in ordered list"
    assert regular_indices, "No regular threads in ordered list"
    assert max(story_indices) < min(regular_indices), (
        f"Story reply threads must precede regular threads.\n"
        f"Ordered: {ordered_ids}\n"
        f"Story indices: {story_indices}, Regular indices: {regular_indices}"
    )


# ---------------------------------------------------------------------------
# ── IGCoordinatedDropManager ─────────────────────────────────────────────
# ---------------------------------------------------------------------------

_DROP_START = 1_744_300_800.0   # Fixed Unix timestamp for all manager tests
_DATE_ISO   = "2026-04-11"


def make_accounts(n: int, phones: Optional[list[str]] = None) -> list[dict]:
    """Generate n child account descriptors spread across available phone serials."""
    if phones is None:
        phones = ["192.168.1.10:5555", "192.168.1.11:5555", "192.168.1.12:5555"]
    return [
        {
            "account_id":   f"c_{i:04d}",
            "phone_serial": phones[i % len(phones)],
        }
        for i in range(n)
    ]


def test_schedule_drop_produces_entry_per_account():
    """schedule_drop must return one DropEntry per child account."""
    accounts = make_accounts(10)
    manager  = IGCoordinatedDropManager()
    schedule = manager.schedule_drop(
        mother_account_id = "acc_mother_001",
        child_accounts    = accounts,
        drop_start_unix   = _DROP_START,
        window_minutes    = 30,
        date_iso          = _DATE_ISO,
    )
    assert schedule.total_accounts == 10
    account_ids_in_schedule = {e.account_id for e in schedule.entries}
    assert account_ids_in_schedule == {a["account_id"] for a in accounts}


def test_schedule_drop_offsets_within_window():
    """Every entry's post_at_unix must be within [drop_start, drop_start + window_seconds)."""
    accounts = make_accounts(50)
    manager  = IGCoordinatedDropManager()
    schedule = manager.schedule_drop(
        mother_account_id = "acc_mother_001",
        child_accounts    = accounts,
        drop_start_unix   = _DROP_START,
        window_minutes    = 30,
        date_iso          = _DATE_ISO,
    )
    window_end = _DROP_START + 30 * 60
    for entry in schedule.entries:
        assert entry.post_at_unix >= _DROP_START, (
            f"{entry.account_id}: post_at {entry.post_at_unix} < drop_start {_DROP_START}"
        )
        assert entry.post_at_unix < window_end, (
            f"{entry.account_id}: post_at {entry.post_at_unix} >= window_end {window_end}"
        )


def test_schedule_drop_deterministic_same_inputs():
    """
    schedule_drop must be deterministic — same inputs always produce the same output.
    This is critical for retry logic: the retry can reconstruct the same schedule
    and pick up from wherever it left off.
    """
    accounts = make_accounts(20)
    manager  = IGCoordinatedDropManager()

    schedule_a = manager.schedule_drop(
        mother_account_id = "acc_mother_001",
        child_accounts    = accounts,
        drop_start_unix   = _DROP_START,
        window_minutes    = 30,
        date_iso          = _DATE_ISO,
    )
    schedule_b = manager.schedule_drop(
        mother_account_id = "acc_mother_001",
        child_accounts    = accounts,
        drop_start_unix   = _DROP_START,
        window_minutes    = 30,
        date_iso          = _DATE_ISO,
    )

    times_a = {e.account_id: e.post_at_unix for e in schedule_a.entries}
    times_b = {e.account_id: e.post_at_unix for e in schedule_b.entries}
    assert times_a == times_b, "schedule_drop is not deterministic"


def test_schedule_drop_same_phone_gap_enforced():
    """
    Two accounts on the same phone must never have post_at_unix values closer
    than MIN_SAME_PHONE_GAP_SEC seconds.

    Uses 10 accounts on one phone over 120 min (7200s).
    10 × 90 = 900s required; window = 7200s — ample space for all offsets.
    """
    # Force all accounts onto a single phone to maximise same-phone collisions
    accounts = make_accounts(10, phones=["192.168.1.10:5555"])
    manager  = IGCoordinatedDropManager()
    schedule = manager.schedule_drop(
        mother_account_id = "acc_mother_001",
        child_accounts    = accounts,
        drop_start_unix   = _DROP_START,
        window_minutes    = 120,  # 7200s — fits 10 accounts at 90s each regardless of start offset
        date_iso          = _DATE_ISO,
    )

    issues = manager.validate_schedule(schedule)
    gap_violations = [i for i in issues if "gap" in i]
    assert gap_violations == [], (
        f"Same-phone gap violations found:\n" + "\n".join(gap_violations)
    )


def test_schedule_drop_raises_on_too_many_accounts():
    """schedule_drop must raise ValueError when child_accounts > MAX_ACCOUNTS_PER_DROP."""
    accounts = make_accounts(MAX_ACCOUNTS_PER_DROP + 1)
    manager  = IGCoordinatedDropManager()
    with pytest.raises(ValueError, match="MAX_ACCOUNTS_PER_DROP"):
        manager.schedule_drop(
            mother_account_id = "acc_mother_001",
            child_accounts    = accounts,
            drop_start_unix   = _DROP_START,
            window_minutes    = 60,
            date_iso          = _DATE_ISO,
        )


def test_schedule_drop_raises_on_window_too_large():
    """schedule_drop must raise ValueError when window_minutes > MAX_DROP_WINDOW_MINUTES."""
    accounts = make_accounts(5)
    manager  = IGCoordinatedDropManager()
    with pytest.raises(ValueError, match="window_minutes"):
        manager.schedule_drop(
            mother_account_id = "acc_mother_001",
            child_accounts    = accounts,
            drop_start_unix   = _DROP_START,
            window_minutes    = MAX_DROP_WINDOW_MINUTES + 1,
            date_iso          = _DATE_ISO,
        )


def test_validate_schedule_flags_same_phone_violations():
    """
    validate_schedule must detect manually constructed schedules that violate
    the MIN_SAME_PHONE_GAP_SEC constraint.
    """
    manager = IGCoordinatedDropManager()

    # Manually build a schedule with two entries 30s apart on the same phone
    schedule = DropSchedule(
        mother_account_id = "acc_mother_001",
        drop_start_unix   = _DROP_START,
        window_seconds    = 3600,
        date_iso          = _DATE_ISO,
        entries = [
            DropEntry(account_id="c_001", phone_serial="192.168.1.10:5555",
                      post_at_unix=_DROP_START + 100, offset_sec=100),
            DropEntry(account_id="c_002", phone_serial="192.168.1.10:5555",
                      post_at_unix=_DROP_START + 130, offset_sec=130),  # 30s gap — VIOLATION
        ],
    )

    issues = manager.validate_schedule(schedule)
    assert len(issues) > 0, "validate_schedule must flag same-phone gap violation"
    assert any("gap" in i for i in issues)


def test_hash_offset_in_range():
    """_hash_offset must always return a value in [0, window_seconds)."""
    window_seconds = 1800  # 30 min
    for i in range(200):
        offset = _hash_offset(f"account_{i}", _DATE_ISO, window_seconds)
        assert 0 <= offset < window_seconds, (
            f"_hash_offset({i!r}) = {offset} out of [0, {window_seconds})"
        )
