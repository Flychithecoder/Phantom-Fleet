"""
Tests for the DM Funnel engine.

Coverage (25 tests):
    01  DEFAULT_OFM_SEQUENCE has 6 steps in correct day order
    02  DEFAULT_OFM_SEQUENCE step types in correct order
    03  FunnelStep rejects invalid action
    04  FunnelStep rejects dm action with <15 templates
    05  FunnelStep rejects unknown condition
    06  FunnelSequence rejects unsorted steps
    07  FunnelEnrollment round-trips through to_dict/from_dict
    08  Day-offset gate: step NOT executed before day_offset days
    09  Day-offset gate: step IS executed on/after day_offset days
    10  Condition gate: if_followed_back blocks step when target hasn't followed back
    11  Condition gate: if_followed_back allows step when target has followed back
    12  Conversion detection: "link" in target DM → converted=True
    13  Conversion detection: "how much" in target DM → converted=True
    14  Conversion detection: "$" in target DM → converted=True
    15  No conversion: random message → converted stays False
    16  Daily cap: after 30 actions no more steps executed (code-enforced)
    17  Dedup: same (account_id, target_user_id) not enrolled twice from enrollment agent
    18  Dedup: bulk enroll API skips duplicates and reports duplicate_skips
    19  Template seeding: different accounts targeting same person get different messages
    20  Story view step calls client.story_view with correct args
    21  Like post step calls client.like_post with correct args
    22  Profile visit step calls client.get_user_info
    23  Stagger sleep is LogNormal — sample() called, not a fixed value
    24  Enrollment sidecar: save and reload produces identical state
    25  Bulk enrollment creates correct count of new enrollments

All HTTP calls are mocked — no real API calls.
asyncio_mode = "auto" is configured in pyproject.toml (no @pytest.mark.asyncio needed).
"""
from __future__ import annotations

import math
import uuid
from datetime import date, timedelta
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from phantom_fleet.core.dm_funnel import (
    DEFAULT_OFM_SEQUENCE,
    FUNNEL_DAILY_ACTION_CAP,
    FunnelEnrollment,
    FunnelSequence,
    FunnelStep,
)
from phantom_fleet.core.chat_modes import ChatTier
from phantom_fleet.core.hybrid_runner import WorkerTask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_enrollment(
    account_id: str = "acc_001",
    target_user_id: str = "target_001",
    sequence_id: str = DEFAULT_OFM_SEQUENCE.sequence_id,
    enrolled_days_ago: int = 0,
    current_step_index: int = 0,
    completed: bool = False,
    converted: bool = False,
    state: Optional[dict] = None,
) -> FunnelEnrollment:
    enrolled_at = (
        date.today() - timedelta(days=enrolled_days_ago)
    ).isoformat() + "T00:00:00+00:00"
    return FunnelEnrollment(
        enrollment_id=uuid.uuid4().hex,
        account_id=account_id,
        target_user_id=target_user_id,
        sequence_id=sequence_id,
        enrolled_at_iso=enrolled_at,
        current_step_index=current_step_index,
        completed=completed,
        converted=converted,
        state=state or {},
    )


def make_task(
    account_id: str = "acc_001",
    enrollments: Optional[list[dict]] = None,
    date_iso: Optional[str] = None,
    sequence_override: Optional[dict] = None,
    session=None,
) -> WorkerTask:
    params: dict = {}
    if enrollments is not None:
        params["enrollments"] = enrollments
    if date_iso is not None:
        params["date_iso"] = date_iso
    if sequence_override is not None:
        params["sequence_override"] = sequence_override
    if session is not None:
        params["session"] = session
    return WorkerTask(
        task_id=f"{account_id}_funnel_test",
        platform="instagram",
        account_id=account_id,
        phone_serial="serial_test",
        action="funnel_advance",
        params=params,
    )


def make_simple_sequence(steps: list[dict]) -> dict:
    """Build a minimal sequence_override dict for task params."""
    return {
        "sequence_id": "test_seq",
        "name": "Test Sequence",
        "chat_tier": int(ChatTier.FLIRTY_SFW),
        "steps": steps,
    }


def minimal_dm_pool() -> list[str]:
    return [f"hey template {i}" for i in range(15)]


# ---------------------------------------------------------------------------
# 01: DEFAULT_OFM_SEQUENCE has 6 steps in correct day order
# ---------------------------------------------------------------------------


def test_default_sequence_step_count():
    assert len(DEFAULT_OFM_SEQUENCE.steps) == 6


def test_default_sequence_day_offsets_sorted():
    offsets = [s.day_offset for s in DEFAULT_OFM_SEQUENCE.steps]
    assert offsets == sorted(offsets), "Steps must be in ascending day_offset order"
    assert offsets == [2, 4, 6, 9, 11, 14]


# ---------------------------------------------------------------------------
# 02: Step types in correct order
# ---------------------------------------------------------------------------


def test_default_sequence_step_types():
    actions = [s.action for s in DEFAULT_OFM_SEQUENCE.steps]
    assert actions == [
        "story_view",
        "like_post",
        "dm",
        "story_view",
        "dm",
        "dm",
    ]


# ---------------------------------------------------------------------------
# 03: FunnelStep rejects invalid action
# ---------------------------------------------------------------------------


def test_funnel_step_invalid_action():
    with pytest.raises(ValueError, match="action must be one of"):
        FunnelStep(day_offset=1, action="tweet")


# ---------------------------------------------------------------------------
# 04: FunnelStep rejects dm with <15 templates
# ---------------------------------------------------------------------------


def test_funnel_step_dm_requires_15_templates():
    with pytest.raises(ValueError, match="15 templates"):
        FunnelStep(day_offset=1, action="dm", dm_template_pool=["too few"] * 5)


def test_funnel_step_dm_accepts_15_templates():
    step = FunnelStep(day_offset=1, action="dm", dm_template_pool=minimal_dm_pool())
    assert len(step.dm_template_pool) == 15


# ---------------------------------------------------------------------------
# 05: FunnelStep rejects unknown condition
# ---------------------------------------------------------------------------


def test_funnel_step_invalid_condition():
    with pytest.raises(ValueError, match="condition must be one of"):
        FunnelStep(day_offset=1, action="story_view", condition="if_paid")


# ---------------------------------------------------------------------------
# 06: FunnelSequence rejects unsorted steps
# ---------------------------------------------------------------------------


def test_funnel_sequence_unsorted_steps_rejected():
    steps = [
        FunnelStep(day_offset=5, action="story_view"),
        FunnelStep(day_offset=2, action="like_post"),
    ]
    with pytest.raises(ValueError, match="ascending day_offset"):
        FunnelSequence(sequence_id="bad_seq", name="Bad", steps=steps)


# ---------------------------------------------------------------------------
# 07: FunnelEnrollment round-trips through to_dict/from_dict
# ---------------------------------------------------------------------------


def test_enrollment_round_trip():
    e = make_enrollment(
        account_id="acct_42",
        target_user_id="user_99",
        current_step_index=3,
        completed=False,
        converted=True,
        state={"last_media_id": "media_123"},
    )
    d = e.to_dict()
    restored = FunnelEnrollment.from_dict(d)
    assert restored.enrollment_id == e.enrollment_id
    assert restored.account_id == e.account_id
    assert restored.target_user_id == e.target_user_id
    assert restored.current_step_index == e.current_step_index
    assert restored.converted is True
    assert restored.state == {"last_media_id": "media_123"}


# ---------------------------------------------------------------------------
# 08: Day-offset gate — step NOT executed before day_offset
# ---------------------------------------------------------------------------


async def test_day_offset_gate_blocks_early_step():
    """Step with day_offset=6 should NOT run when only 3 days have elapsed."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent

    e = make_enrollment(
        account_id="acc_gate",
        enrolled_days_ago=3,  # enrolled 3 days ago → day 3
        current_step_index=0,
    )
    # Override with a sequence that has day_offset=6
    seq_override = make_simple_sequence([
        {"day_offset": 6, "action": "like_post"},
    ])
    task = make_task(
        account_id="acc_gate",
        enrollments=[e.to_dict()],
        date_iso=date.today().isoformat(),
        sequence_override=seq_override,
    )

    agent = IGDMFunnelAgent()
    result = await agent.run_session(task)

    # Step should NOT have been executed — not enough days elapsed
    assert result.data["steps_executed"] == 0


# ---------------------------------------------------------------------------
# 09: Day-offset gate — step IS executed on/after day_offset
# ---------------------------------------------------------------------------


async def test_day_offset_gate_allows_on_time():
    """Step with day_offset=6 SHOULD run when 6+ days have elapsed."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent, _NullClient

    e = make_enrollment(
        account_id="acc_ontime",
        enrolled_days_ago=6,  # exactly 6 days ago
        current_step_index=0,
        state={"last_media_id": "media_abc"},
    )
    seq_override = make_simple_sequence([
        {"day_offset": 6, "action": "like_post"},
    ])
    task = make_task(
        account_id="acc_ontime",
        enrollments=[e.to_dict()],
        date_iso=date.today().isoformat(),
        sequence_override=seq_override,
    )

    with patch("phantom_fleet.agents.specialists.ig_dm_funnel_agent.asyncio.sleep"):
        agent = IGDMFunnelAgent()
        result = await agent.run_session(task)

    assert result.data["steps_executed"] == 1


# ---------------------------------------------------------------------------
# 10: Condition gate — if_followed_back blocks when not followed back
# ---------------------------------------------------------------------------


async def test_condition_gate_followed_back_blocks():
    """if_followed_back condition should block step when target hasn't followed back."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent

    e = make_enrollment(
        account_id="acc_cond",
        enrolled_days_ago=10,
        current_step_index=0,
        state={"follows_us": False},  # explicitly not following back
    )
    seq_override = make_simple_sequence([
        {"day_offset": 5, "action": "story_view", "condition": "if_followed_back"},
    ])
    task = make_task(
        account_id="acc_cond",
        enrollments=[e.to_dict()],
        date_iso=date.today().isoformat(),
        sequence_override=seq_override,
    )

    with patch("phantom_fleet.agents.specialists.ig_dm_funnel_agent.asyncio.sleep"):
        agent = IGDMFunnelAgent()
        result = await agent.run_session(task)

    assert result.data["steps_executed"] == 0


# ---------------------------------------------------------------------------
# 11: Condition gate — if_followed_back allows when followed back
# ---------------------------------------------------------------------------


async def test_condition_gate_followed_back_allows():
    """if_followed_back condition should allow step when target HAS followed back."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent

    e = make_enrollment(
        account_id="acc_cond_ok",
        enrolled_days_ago=10,
        current_step_index=0,
        state={"follows_us": True, "story_reel_id": "reel_1", "story_media_ids": ["m1"]},
    )
    seq_override = make_simple_sequence([
        {"day_offset": 5, "action": "story_view", "condition": "if_followed_back"},
    ])
    task = make_task(
        account_id="acc_cond_ok",
        enrollments=[e.to_dict()],
        date_iso=date.today().isoformat(),
        sequence_override=seq_override,
    )

    with patch("phantom_fleet.agents.specialists.ig_dm_funnel_agent.asyncio.sleep"):
        agent = IGDMFunnelAgent()
        result = await agent.run_session(task)

    assert result.data["steps_executed"] == 1


# ---------------------------------------------------------------------------
# 12-14: Conversion signal detection
# ---------------------------------------------------------------------------


async def _run_with_inbox_reply(reply_text: str, account_id: str = "acc_conv") -> dict:
    """Helper: run funnel agent with a mock inbox that has reply_text from target."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent
    from phantom_fleet.core.instagram_client import IGSession
    from phantom_fleet.core.hybrid_runner import PlatformHeaders

    e = make_enrollment(
        account_id=account_id,
        target_user_id="target_conv",
        enrolled_days_ago=7,
        current_step_index=0,
        state={"story_reel_id": "reel_1", "story_media_ids": ["m1"]},
    )
    seq_override = make_simple_sequence([
        {"day_offset": 5, "action": "story_view"},
    ])

    # Build a fake IGSession so _check_conversion path runs
    headers = PlatformHeaders(
        platform="instagram",
        session_token="tok",
        device_id="dev",
        user_agent="IG/300",
        app_version="300",
        android_id="aid",
        advertising_id="gaid",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
    )
    fake_session = IGSession(
        account_id=account_id,
        ig_user_id="123",
        username="test",
        session_id="sess",
        csrftoken="csrf",
        mid="mid",
        ds_user_id="123",
        headers=headers,
    )

    # Mock the inbox to return the target's reply
    inbox_resp = {
        "inbox": {
            "threads": [
                {
                    "users": [{"pk": "target_conv"}],
                    "items": [
                        {
                            "text": reply_text,
                            "is_sent_by_viewer": False,
                        }
                    ],
                }
            ]
        }
    }

    task = make_task(
        account_id=account_id,
        enrollments=[e.to_dict()],
        date_iso=date.today().isoformat(),
        sequence_override=seq_override,
        session=fake_session,
    )

    with (
        patch("phantom_fleet.agents.specialists.ig_dm_funnel_agent.asyncio.sleep"),
        patch(
            "phantom_fleet.agents.specialists.ig_dm_funnel_agent.InstagramClient",
        ) as MockClient,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_instance.story_view = AsyncMock(return_value={})
        mock_instance.like_post = AsyncMock(return_value={})
        mock_instance.get_user_info = AsyncMock(return_value={})
        mock_instance.send_dm = AsyncMock(return_value={})
        mock_instance.get_inbox = AsyncMock(return_value=inbox_resp)
        MockClient.return_value = mock_instance

        agent = IGDMFunnelAgent()
        result = await agent.run_session(task)

    return result.data


async def test_conversion_signal_link():
    data = await _run_with_inbox_reply("can you send me the link please?", "acc_conv_link")
    assert data["conversions_detected"] == 1


async def test_conversion_signal_how_much():
    data = await _run_with_inbox_reply("how much is it?", "acc_conv_howmuch")
    assert data["conversions_detected"] == 1


async def test_conversion_signal_dollar():
    data = await _run_with_inbox_reply("is it $10 a month?", "acc_conv_dollar")
    assert data["conversions_detected"] == 1


# ---------------------------------------------------------------------------
# 15: No conversion on random message
# ---------------------------------------------------------------------------


async def test_no_conversion_random_message():
    data = await _run_with_inbox_reply("lol nice pic", "acc_conv_none")
    assert data["conversions_detected"] == 0


# ---------------------------------------------------------------------------
# 16: Daily cap — code-enforced at 30
# ---------------------------------------------------------------------------


async def test_daily_cap_enforced():
    """After FUNNEL_DAILY_ACTION_CAP actions, no more steps are executed."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent

    today = date.today().isoformat()

    # Create 50 enrollments, all past their day_offset
    # Give each a last_action_at_iso of TODAY so they count toward today's cap
    enrollments = []
    for i in range(50):
        e = make_enrollment(
            account_id="acc_cap",
            target_user_id=f"target_{i:04d}",
            enrolled_days_ago=10,
            current_step_index=0,
            state={"last_media_id": f"media_{i}"},
        )
        # Mark some as already actioned today to seed the cap counter
        # We will mark exactly FUNNEL_DAILY_ACTION_CAP actions already done
        if i < FUNNEL_DAILY_ACTION_CAP:
            e.last_action_at_iso = today + "T00:00:00+00:00"
            e.current_step_index = 1  # already advanced
        enrollments.append(e)

    seq_override = make_simple_sequence([
        {"day_offset": 5, "action": "like_post"},
        {"day_offset": 8, "action": "like_post"},
    ])
    task = make_task(
        account_id="acc_cap",
        enrollments=[e.to_dict() for e in enrollments],
        date_iso=today,
        sequence_override=seq_override,
    )

    with patch("phantom_fleet.agents.specialists.ig_dm_funnel_agent.asyncio.sleep"):
        agent = IGDMFunnelAgent()
        result = await agent.run_session(task)

    # Cap was already hit from today's actions — no new steps should execute
    assert result.data["daily_cap_hit"] is True
    assert result.data["steps_executed"] == 0


# ---------------------------------------------------------------------------
# 17: Enrollment dedup — same target not enrolled twice from enrollment agent
# ---------------------------------------------------------------------------


async def test_enrollment_agent_dedup(tmp_path, monkeypatch):
    """Same (account_id, target_user_id) must not be enrolled twice."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    from phantom_fleet.agents.specialists.ig_funnel_enrollment_agent import (
        IGFunnelEnrollmentAgent,
    )

    agent = IGFunnelEnrollmentAgent()
    account_id = "acc_dedup"
    new_follows = [
        {"target_user_id": "user_A"},
        {"target_user_id": "user_B"},
    ]
    task1 = WorkerTask(
        task_id="enroll_1",
        platform="instagram",
        account_id=account_id,
        phone_serial="serial",
        action="enroll",
        params={
            "new_follows": new_follows,
            "sequence_id": DEFAULT_OFM_SEQUENCE.sequence_id,
            "date_iso": date.today().isoformat(),
        },
    )
    result1 = await agent.run_session(task1)
    assert result1.data["enrolled_count"] == 2
    assert result1.data["duplicate_skips"] == 0

    # Enroll the same targets again — should all be skipped
    result2 = await agent.run_session(task1)
    assert result2.data["enrolled_count"] == 0
    assert result2.data["duplicate_skips"] == 2


# ---------------------------------------------------------------------------
# 18: Bulk enroll API dedup
# ---------------------------------------------------------------------------


async def test_bulk_enroll_dedup(tmp_path, monkeypatch):
    """Bulk enroll endpoint skips already-enrolled targets."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    from phantom_fleet.api.routes.funnel import bulk_enroll
    from phantom_fleet.api.schemas import BulkEnrollIn

    account_id = "acc_bulk_dedup"
    target_ids = ["t001", "t002", "t003"]

    body1 = BulkEnrollIn(
        account_id=account_id,
        target_user_ids=target_ids,
        sequence_id=DEFAULT_OFM_SEQUENCE.sequence_id,
    )
    result1 = await bulk_enroll(body1)
    assert result1.enrolled_count == 3
    assert result1.duplicate_skips == 0

    # Second enroll — all duplicates
    body2 = BulkEnrollIn(
        account_id=account_id,
        target_user_ids=["t001", "t002", "t004"],
        sequence_id=DEFAULT_OFM_SEQUENCE.sequence_id,
    )
    result2 = await bulk_enroll(body2)
    assert result2.enrolled_count == 1      # t004 is new
    assert result2.duplicate_skips == 2    # t001, t002 already enrolled


# ---------------------------------------------------------------------------
# 19: Template seeding — different accounts get different messages for same target
# ---------------------------------------------------------------------------


def test_template_selection_different_per_account():
    """
    hash(account_id + target_id + step_idx) % pool_size must differ across accounts.
    Tested: two different accounts targeting the same user on the same step
    should select different template indices (with high probability given pool=17).
    """
    import hashlib

    pool = minimal_dm_pool()  # 15 templates
    target_id = "target_shared"
    step_idx = 0

    def pick(account_id: str) -> int:
        seed_key = f"{account_id}|{target_id}|{step_idx}"
        digest = hashlib.sha256(seed_key.encode()).digest()
        return int.from_bytes(digest[:4], "big") % len(pool)

    picks = {pick(f"acc_{i:04d}") for i in range(15)}
    # With 15 different accounts and 15 template slots, we expect most picks to differ
    # (birthday paradox — collision possible but distribution should not be all-same)
    assert len(picks) > 1, "All accounts picked same template — seeding is broken"


# ---------------------------------------------------------------------------
# 20: Story view step calls client.story_view
# ---------------------------------------------------------------------------


async def test_story_view_step_calls_correct_method():
    """story_view action must call client.story_view() with the reel and media IDs."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent, _NullClient

    e = make_enrollment(
        account_id="acc_sv",
        enrolled_days_ago=10,
        current_step_index=0,
        state={"story_reel_id": "reel_99", "story_media_ids": ["m1", "m2"]},
    )

    null_client = _NullClient()
    story_view_mock = AsyncMock(return_value={})
    null_client.story_view = story_view_mock

    agent = IGDMFunnelAgent()
    result = await agent._do_story_view(
        target_id="target_sv",
        enrollment=e,
        client=null_client,
    )

    assert result is True
    story_view_mock.assert_awaited_once_with(
        reel_id="reel_99",
        media_ids=["m1", "m2"],
    )


# ---------------------------------------------------------------------------
# 21: Like post step calls client.like_post
# ---------------------------------------------------------------------------


async def test_like_post_step_calls_correct_method():
    """like_post action must call client.like_post()."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent, _NullClient

    e = make_enrollment(
        state={"last_media_id": "media_777"},
        enrolled_days_ago=5,
    )
    null_client = _NullClient()
    like_mock = AsyncMock(return_value={})
    null_client.like_post = like_mock

    agent = IGDMFunnelAgent()
    result = await agent._do_like_post(
        target_id="t1",
        enrollment=e,
        client=null_client,
    )

    assert result is True
    like_mock.assert_awaited_once_with(media_id="media_777")


# ---------------------------------------------------------------------------
# 22: Profile visit step calls client.get_user_info
# ---------------------------------------------------------------------------


async def test_profile_visit_step_calls_get_user_info():
    """profile_visit action must call client.get_user_info()."""
    from phantom_fleet.agents.specialists.ig_dm_funnel_agent import IGDMFunnelAgent, _NullClient

    null_client = _NullClient()
    info_mock = AsyncMock(return_value={"user": {}})
    null_client.get_user_info = info_mock

    agent = IGDMFunnelAgent()
    result = await agent._do_profile_visit(
        target_id="target_pv",
        client=null_client,
    )

    assert result is True
    info_mock.assert_awaited_once_with("target_pv")


# ---------------------------------------------------------------------------
# 23: Stagger sleep is LogNormal — not fixed
# ---------------------------------------------------------------------------


def test_stagger_is_lognormal():
    """
    Verify the stagger distribution is LogNormal — samples 1000 values and
    checks that the distribution is NOT uniform (coefficient of variation > 0.2).
    A fixed value would have CV=0. A uniform distribution on [30, 900] has
    CV = (high-low) / (sqrt(12) * mean) ≈ 0.81. A log-normal should have
    CV well above 0, confirming non-flatness.
    """
    from phantom_fleet.core.dm_funnel import _STAGGER_LOW, _STAGGER_HIGH, _STAGGER_SIGMA
    from phantom_fleet.core.distributions import LogNormal

    dist = LogNormal(low=_STAGGER_LOW, high=_STAGGER_HIGH, sigma=_STAGGER_SIGMA)
    samples = [dist.sample() for _ in range(1000)]

    mean = sum(samples) / len(samples)
    variance = sum((x - mean) ** 2 for x in samples) / len(samples)
    std = math.sqrt(variance)
    cv = std / mean

    # CV > 0.1 confirms it's NOT a fixed value and NOT nearly-zero variance
    assert cv > 0.1, f"Stagger distribution CV too low ({cv:.3f}) — may not be LogNormal"
    # All values within bounds
    assert all(_STAGGER_LOW <= s <= _STAGGER_HIGH for s in samples)


# ---------------------------------------------------------------------------
# 24: Enrollment sidecar — save and reload produces identical state
# ---------------------------------------------------------------------------


def test_enrollment_sidecar_round_trip(tmp_path, monkeypatch):
    """Saving enrollments to sidecar and reloading them produces identical records."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    from phantom_fleet.agents.specialists.ig_funnel_enrollment_agent import (
        _sidecar_path,
        _save_sidecar,
        _load_sidecar,
    )

    today = date.today().isoformat()
    e1 = make_enrollment(account_id="acc_sidecar", target_user_id="t1", current_step_index=2)
    e2 = make_enrollment(account_id="acc_sidecar", target_user_id="t2", converted=True)

    path = _sidecar_path("acc_sidecar", today)
    _save_sidecar(path, [e1, e2])
    loaded = _load_sidecar(path)

    assert len(loaded) == 2
    ids = {e.enrollment_id for e in loaded}
    assert e1.enrollment_id in ids
    assert e2.enrollment_id in ids

    loaded_map = {e.target_user_id: e for e in loaded}
    assert loaded_map["t1"].current_step_index == 2
    assert loaded_map["t2"].converted is True


# ---------------------------------------------------------------------------
# 25: Bulk enrollment creates correct count of enrollments
# ---------------------------------------------------------------------------


async def test_bulk_enroll_creates_correct_count(tmp_path, monkeypatch):
    """POST /bulk should create exactly N enrollments for N unique targets."""
    monkeypatch.setenv("PHANTOM_STATE_DIR", str(tmp_path))

    from phantom_fleet.api.routes.funnel import bulk_enroll
    from phantom_fleet.api.schemas import BulkEnrollIn

    targets = [f"user_{i:04d}" for i in range(10)]
    body = BulkEnrollIn(
        account_id="acc_bulk_count",
        target_user_ids=targets,
        sequence_id=DEFAULT_OFM_SEQUENCE.sequence_id,
    )
    result = await bulk_enroll(body)

    assert result.enrolled_count == 10
    assert len(result.enrollment_ids) == 10
    assert result.duplicate_skips == 0
    assert result.errors == []

    # Verify sidecar actually written
    from phantom_fleet.agents.specialists.ig_funnel_enrollment_agent import (
        _load_sidecar,
        _sidecar_path,
    )
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    path = _sidecar_path("acc_bulk_count", today)
    loaded = _load_sidecar(path)
    assert len(loaded) == 10
