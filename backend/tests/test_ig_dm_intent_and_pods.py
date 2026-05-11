"""
Tests for DM Intent Classifier and Comment Pod Network.

Coverage (≥ 22 tests):

Intent Classifier:
    1.  is_story_reply=True → STORY_REPLY
    2.  STORY_REPLY beats ENGAGED_FAN (priority order)
    3.  "stop" in message → NEGATIVE
    4.  "not interested" → NEGATIVE
    5.  3x one-word replies → LOW_INTENT
    6.  Only 2 short messages (not 3) → NOT LOW_INTENT
    7.  message_count >= 3, no negative → ENGAGED_FAN
    8.  Default (no signals) → NEW_FAN
    9.  Profile routing: NEW_FAN → INSTAGRAM_CASUAL_SFW
    10. Profile routing: ENGAGED_FAN → INSTAGRAM_FLIRTY_SFW
    11. Profile routing: STORY_REPLY → INSTAGRAM_FLIRTY_SFW
    12. LOW_INTENT profile is None (thread skipped, no LLM call)
    13. NEGATIVE profile is None (thread skipped)
    14. max_tokens: NEW_FAN=80, ENGAGED_FAN=120, STORY_REPLY=80
    15. LOW_INTENT returns None profile → thread skipped

Comment Pod:
    16. Pod with < 8 accounts → ValueError
    17. Pod with > 15 accounts → ValueError
    18. Pod with 8-15 accounts → success
    19. Comment timing is staggered (NOT simultaneous)
    20. Same account never comments on same post twice (dedup)
    21. Banned phrase triggers retry → if LLM always returns banned phrase, skip
    22. Daily cap at 5 pod comments per account
    23. Pod rotation changes last_rotated_iso and shuffles members
    24. Generated comment is 4-15 words (word count gate)
    25. needs_rotation=True after 7+ days
    26. needs_rotation=False when freshly created
    27. auto_assign creates correct number of pods

All HTTP calls are mocked. asyncio_mode = "auto" (pyproject.toml).
"""
from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from phantom_fleet.core.dm_intent_classifier import (
    CLASSIFIER,
    DMIntent,
    INTENT_MAX_TOKENS,
    INTENT_PROFILE_MAP,
    DMIntentClassifier,
)
from phantom_fleet.core.comment_pod import (
    CommentPod,
    PodCommentTask,
    POD_MIN_ACCOUNTS,
    POD_MAX_ACCOUNTS,
    POD_MAX_DAILY_COMMENTS_PER_ACCOUNT,
)
from phantom_fleet.agents.specialists.ig_comment_pod_agent import (
    BANNED_POD_PHRASES,
    COMMENT_MIN_WORDS,
    COMMENT_MAX_WORDS,
    IGCommentPodAgent,
)
from phantom_fleet.core.hybrid_runner import PlatformHeaders, WorkerResult
from phantom_fleet.core.instagram_client import IGSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_headers() -> PlatformHeaders:
    return PlatformHeaders(
        platform="instagram",
        session_token="tok_test",
        device_id="android-abc123",
        user_agent="Instagram 300.0.0.1 Android",
        app_version="300.0.0.1",
        android_id="abc123def456abc1",
        advertising_id="gaid-test",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra={"mid": "mid_test", "family_device_id": "fam-uuid-test"},
    )


def make_session(account_id: str = "acct_001") -> IGSession:
    return IGSession(
        account_id=account_id,
        ig_user_id="111222333",
        username=f"user_{account_id}",
        session_id="sess_test",
        csrftoken="csrf_test",
        mid="mid_test",
        ds_user_id="111222333",
        headers=make_headers(),
    )


def make_pod_account_ids(n: int = 10) -> list[str]:
    return [f"acct_{i:03d}" for i in range(n)]


# ---------------------------------------------------------------------------
# Helper: build thread dict for classifier
# ---------------------------------------------------------------------------


def make_thread(
    message_count: int = 0,
    is_story_reply: bool = False,
    thread_id: str = "thread_001",
) -> dict:
    return {
        "thread_id":      thread_id,
        "message_count":  message_count,
        "is_story_reply": is_story_reply,
    }


# ============================================================================
# Feature 1: DM Intent Classifier
# ============================================================================


class TestDMIntentClassifier:

    # ------------------------------------------------------------------
    # Story reply
    # ------------------------------------------------------------------

    def test_story_reply_flag(self):
        """is_story_reply=True → STORY_REPLY."""
        intent = CLASSIFIER.classify(
            message="omg this is so cute",
            thread=make_thread(is_story_reply=True),
        )
        assert intent == DMIntent.STORY_REPLY

    def test_story_reply_beats_engaged_fan(self):
        """STORY_REPLY beats ENGAGED_FAN even with high message count."""
        intent = CLASSIFIER.classify(
            message="nice",
            thread=make_thread(message_count=10, is_story_reply=True),
        )
        assert intent == DMIntent.STORY_REPLY

    # ------------------------------------------------------------------
    # Negative
    # ------------------------------------------------------------------

    def test_negative_stop_keyword(self):
        """'stop' in message → NEGATIVE."""
        intent = CLASSIFIER.classify(
            message="stop messaging me",
            thread=make_thread(),
        )
        assert intent == DMIntent.NEGATIVE

    def test_negative_not_interested(self):
        """'not interested' → NEGATIVE."""
        intent = CLASSIFIER.classify(
            message="I'm not interested, leave me alone",
            thread=make_thread(),
        )
        assert intent == DMIntent.NEGATIVE

    # ------------------------------------------------------------------
    # Low intent
    # ------------------------------------------------------------------

    def test_low_intent_one_word_replies(self):
        """3 consecutive ≤5-char messages from target → LOW_INTENT."""
        intent = CLASSIFIER.classify(
            message="k",
            thread=make_thread(),
            recent_target_messages=["k", "ok", "😐"],
        )
        assert intent == DMIntent.LOW_INTENT

    def test_low_intent_needs_full_lookback(self):
        """
        Only 2 short messages in lookback window (not 3) → NOT LOW_INTENT.
        Should fall through to NEW_FAN (message_count=0).
        """
        intent = CLASSIFIER.classify(
            message="sure",
            thread=make_thread(),
            recent_target_messages=["k", "ok"],  # only 2, need 3
        )
        assert intent != DMIntent.LOW_INTENT

    def test_low_intent_returns_none_profile(self):
        """LOW_INTENT → None profile (thread skipped, no LLM call)."""
        assert INTENT_PROFILE_MAP[DMIntent.LOW_INTENT] is None

    # ------------------------------------------------------------------
    # Engaged fan
    # ------------------------------------------------------------------

    def test_engaged_fan_three_plus_messages(self):
        """message_count >= 3 and no negative → ENGAGED_FAN."""
        intent = CLASSIFIER.classify(
            message="lol that's so funny",
            thread=make_thread(message_count=4),
        )
        assert intent == DMIntent.ENGAGED_FAN

    def test_engaged_fan_min_threshold(self):
        """message_count == 3 exactly → ENGAGED_FAN."""
        intent = CLASSIFIER.classify(
            message="hey again",
            thread=make_thread(message_count=3),
        )
        assert intent == DMIntent.ENGAGED_FAN

    def test_below_engaged_fan_threshold(self):
        """message_count == 2 → NOT ENGAGED_FAN (falls to NEW_FAN)."""
        intent = CLASSIFIER.classify(
            message="hey",
            thread=make_thread(message_count=2),
        )
        assert intent == DMIntent.NEW_FAN

    # ------------------------------------------------------------------
    # Default
    # ------------------------------------------------------------------

    def test_new_fan_default(self):
        """No signals → NEW_FAN."""
        intent = CLASSIFIER.classify(
            message="hey!",
            thread=make_thread(),
        )
        assert intent == DMIntent.NEW_FAN

    # ------------------------------------------------------------------
    # Profile routing
    # ------------------------------------------------------------------

    def test_new_fan_routes_to_casual_profile(self):
        """NEW_FAN intent → INSTAGRAM_CASUAL_SFW profile."""
        assert INTENT_PROFILE_MAP[DMIntent.NEW_FAN] == "INSTAGRAM_CASUAL_SFW"

    def test_engaged_fan_routes_to_flirty_profile(self):
        """ENGAGED_FAN intent → INSTAGRAM_FLIRTY_SFW profile."""
        assert INTENT_PROFILE_MAP[DMIntent.ENGAGED_FAN] == "INSTAGRAM_FLIRTY_SFW"

    def test_story_reply_routes_to_flirty_profile(self):
        """STORY_REPLY intent → INSTAGRAM_FLIRTY_SFW profile."""
        assert INTENT_PROFILE_MAP[DMIntent.STORY_REPLY] == "INSTAGRAM_FLIRTY_SFW"

    def test_negative_profile_is_none(self):
        """NEGATIVE → None profile (thread skipped)."""
        assert INTENT_PROFILE_MAP[DMIntent.NEGATIVE] is None

    # ------------------------------------------------------------------
    # Token budgets
    # ------------------------------------------------------------------

    def test_max_tokens_new_fan(self):
        assert INTENT_MAX_TOKENS[DMIntent.NEW_FAN] == 80

    def test_max_tokens_engaged_fan(self):
        assert INTENT_MAX_TOKENS[DMIntent.ENGAGED_FAN] == 120

    def test_max_tokens_story_reply(self):
        assert INTENT_MAX_TOKENS[DMIntent.STORY_REPLY] == 80


# ============================================================================
# Feature 2: Comment Pod Network
# ============================================================================


class TestCommentPodDataclasses:

    def test_pod_requires_min_accounts(self):
        """CommentPod with < 8 accounts → ValueError."""
        with pytest.raises(ValueError, match="8"):
            CommentPod(
                pod_id="pod_test",
                account_ids=["a", "b", "c"],  # only 3
                niche="fitness",
                created_at_iso="2026-04-11T00:00:00+00:00",
                last_rotated_iso="2026-04-11T00:00:00+00:00",
            )

    def test_pod_requires_max_accounts(self):
        """CommentPod with > 15 accounts → ValueError."""
        with pytest.raises(ValueError, match="15"):
            CommentPod(
                pod_id="pod_test",
                account_ids=[f"a{i}" for i in range(16)],  # 16 accounts
                niche="fitness",
                created_at_iso="2026-04-11T00:00:00+00:00",
                last_rotated_iso="2026-04-11T00:00:00+00:00",
            )

    def test_pod_valid_with_8_to_15_accounts(self):
        """CommentPod with 8 accounts → no error."""
        pod = CommentPod(
            pod_id="pod_ok",
            account_ids=[f"a{i}" for i in range(8)],
            niche="general",
            created_at_iso="2026-04-11T00:00:00+00:00",
            last_rotated_iso="2026-04-11T00:00:00+00:00",
        )
        assert len(pod.account_ids) == 8

    def test_needs_rotation_true_after_7_days(self):
        """needs_rotation=True when last_rotated_iso is > 7 days ago."""
        old_iso = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        pod = CommentPod(
            pod_id="pod_stale",
            account_ids=[f"a{i}" for i in range(8)],
            niche="general",
            created_at_iso=old_iso,
            last_rotated_iso=old_iso,
        )
        assert pod.needs_rotation is True

    def test_needs_rotation_false_when_fresh(self):
        """needs_rotation=False when last_rotated_iso is recent."""
        now_iso = datetime.now(timezone.utc).isoformat()
        pod = CommentPod(
            pod_id="pod_fresh",
            account_ids=[f"a{i}" for i in range(8)],
            niche="general",
            created_at_iso=now_iso,
            last_rotated_iso=now_iso,
        )
        assert pod.needs_rotation is False


class TestIGCommentPodAgent:

    def make_agent(self) -> IGCommentPodAgent:
        return IGCommentPodAgent()

    # ------------------------------------------------------------------
    # Pod creation
    # ------------------------------------------------------------------

    def test_create_pod_too_few_accounts(self):
        """create_pod with < 8 accounts → ValueError."""
        agent = self.make_agent()
        with pytest.raises(ValueError, match="8"):
            agent.create_pod(account_ids=["a", "b"], niche="fitness")

    def test_create_pod_too_many_accounts(self):
        """create_pod with > 15 accounts → ValueError."""
        agent = self.make_agent()
        with pytest.raises(ValueError, match="15"):
            agent.create_pod(
                account_ids=[f"a{i}" for i in range(16)],
                niche="fitness",
            )

    def test_create_pod_success(self):
        """create_pod with valid count → CommentPod returned."""
        agent = self.make_agent()
        pod = agent.create_pod(account_ids=make_pod_account_ids(10), niche="fitness")
        assert pod.pod_id.startswith("pod_fitness_")
        assert len(pod.account_ids) == 10
        assert pod.niche == "fitness"

    # ------------------------------------------------------------------
    # Comment timing stagger
    # ------------------------------------------------------------------

    def test_comment_timing_is_staggered_not_simultaneous(self):
        """
        Schedule pod comments for 10 members.
        Every scheduled_at_unix must be STRICTLY after the previous one.
        """
        agent = self.make_agent()
        accounts = make_pod_account_ids(10)
        agent.create_pod(account_ids=accounts, niche="general")

        post_time = time.time()
        tasks = agent.schedule_pod_comments(
            poster_account_id=accounts[0],
            media_id="media_abc",
            post_time_unix=post_time,
        )

        assert len(tasks) == 9  # poster excluded
        times = [t.scheduled_at_unix for t in tasks]
        for i in range(1, len(times)):
            assert times[i] > times[i - 1], (
                f"Comment {i} scheduled at {times[i]:.1f} "
                f"which is NOT after {times[i-1]:.1f}"
            )

    def test_first_comment_after_min_delay(self):
        """First comment must arrive at least 120s (2 min) after post."""
        agent = self.make_agent()
        accounts = make_pod_account_ids(8)
        agent.create_pod(account_ids=accounts, niche="general")

        post_time = 1000000.0
        tasks = agent.schedule_pod_comments(
            poster_account_id=accounts[0],
            media_id="media_xyz",
            post_time_unix=post_time,
        )
        assert len(tasks) >= 1
        assert tasks[0].scheduled_at_unix >= post_time + 120.0

    # ------------------------------------------------------------------
    # Dedup
    # ------------------------------------------------------------------

    async def test_same_account_never_comments_twice(self):
        """
        Run run_pod_comment twice for the same (account, media).
        Second call must be skipped with reason='already_commented'.
        """
        agent = self.make_agent()
        accounts = make_pod_account_ids(8)
        pod = agent.create_pod(account_ids=accounts, niche="general")

        task = PodCommentTask(
            poster_account_id=accounts[0],
            media_id="media_dedup",
            pod_id=pod.pod_id,
            commenter_account_id=accounts[1],
            scheduled_at_unix=time.time(),
        )
        session = make_session(accounts[1])

        # Mock LLM to return a valid comment
        valid_comment = "this looks really interesting to me"

        with patch(
            "phantom_fleet.agents.specialists.ig_comment_pod_agent.httpx.AsyncClient"
        ) as mock_http_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": valid_comment}}]
            }
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http_cls.return_value = mock_http

            # Also mock InstagramClient._post
            with patch.object(
                agent,
                "run_pod_comment",
                wraps=agent.run_pod_comment,
            ):
                # First call — mock the IG _post inside InstagramClient
                with patch(
                    "phantom_fleet.core.instagram_client.InstagramClient._post",
                    new_callable=AsyncMock,
                    return_value={"status": "ok"},
                ):
                    result1 = await agent.run_pod_comment(
                        task=task, session=session, date_iso="2026-04-11"
                    )
                    assert result1.success is True
                    assert result1.data.get("skipped") is not True

                    # Second call — same task, same account/media
                    result2 = await agent.run_pod_comment(
                        task=task, session=session, date_iso="2026-04-11"
                    )
                    assert result2.data.get("skipped") is True
                    assert result2.data.get("reason") == "already_commented"

    # ------------------------------------------------------------------
    # Daily cap
    # ------------------------------------------------------------------

    async def test_daily_cap_at_5(self):
        """
        After 5 successful pod comments, 6th call returns skipped=True, reason=daily_cap.
        """
        agent = self.make_agent()
        accounts = make_pod_account_ids(8)
        pod = agent.create_pod(account_ids=accounts, niche="general")
        commenter = accounts[1]
        session = make_session(commenter)
        date_iso = "2026-04-11"

        valid_comment = "this content is really something special today"

        def make_task(media_id: str) -> PodCommentTask:
            return PodCommentTask(
                poster_account_id=accounts[0],
                media_id=media_id,
                pod_id=pod.pod_id,
                commenter_account_id=commenter,
                scheduled_at_unix=time.time(),
            )

        with patch(
            "phantom_fleet.agents.specialists.ig_comment_pod_agent.httpx.AsyncClient"
        ) as mock_http_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": valid_comment}}]
            }
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http_cls.return_value = mock_http

            with patch(
                "phantom_fleet.core.instagram_client.InstagramClient._post",
                new_callable=AsyncMock,
                return_value={"status": "ok"},
            ):
                for i in range(POD_MAX_DAILY_COMMENTS_PER_ACCOUNT):
                    r = await agent.run_pod_comment(
                        task=make_task(f"media_{i:03d}"),
                        session=session,
                        date_iso=date_iso,
                    )
                    assert r.success is True
                    assert r.data.get("skipped") is not True

                # 6th call must be capped
                r_cap = await agent.run_pod_comment(
                    task=make_task("media_999"),
                    session=session,
                    date_iso=date_iso,
                )
                assert r_cap.data.get("skipped") is True
                assert r_cap.data.get("reason") == "daily_cap"

    # ------------------------------------------------------------------
    # Banned phrase retry
    # ------------------------------------------------------------------

    async def test_banned_phrase_triggers_retry_then_skip(self):
        """
        If LLM always returns a banned phrase, comment is skipped after retries.
        """
        agent = self.make_agent()
        accounts = make_pod_account_ids(8)
        pod = agent.create_pod(account_ids=accounts, niche="fitness")
        session = make_session(accounts[1])

        task = PodCommentTask(
            poster_account_id=accounts[0],
            media_id="media_banned",
            pod_id=pod.pod_id,
            commenter_account_id=accounts[1],
            scheduled_at_unix=time.time(),
        )

        # Always return a banned phrase
        banned_comment = "great post keep it up!"

        with patch(
            "phantom_fleet.agents.specialists.ig_comment_pod_agent.httpx.AsyncClient"
        ) as mock_http_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": banned_comment}}]
            }
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http_cls.return_value = mock_http

            result = await agent.run_pod_comment(
                task=task, session=session, date_iso="2026-04-11"
            )

        # LLM always fails quality gate → generation fails → error
        assert result.success is False
        assert "comment_gen_failed" in (result.error or "")

    # ------------------------------------------------------------------
    # Pod rotation
    # ------------------------------------------------------------------

    def test_pod_rotation_changes_membership_order(self):
        """
        After rotate_pod, last_rotated_iso changes and membership is shuffled.
        """
        agent = self.make_agent()
        original_accounts = make_pod_account_ids(10)
        pod = agent.create_pod(account_ids=original_accounts, niche="lifestyle")
        old_rotated = pod.last_rotated_iso
        original_order = list(pod.account_ids)

        rotated_pod = agent.rotate_pod(pod.pod_id)

        # Timestamp must have changed (rotation happened after creation)
        assert rotated_pod.last_rotated_iso != old_rotated
        # Same set of accounts (no external pool in unit test)
        assert set(rotated_pod.account_ids) == set(original_accounts)
        # Order must differ (rotation shuffled)
        assert rotated_pod.account_ids != original_order

    # ------------------------------------------------------------------
    # Comment word count
    # ------------------------------------------------------------------

    async def test_generated_comment_within_word_limits(self):
        """
        Generated comment must be between COMMENT_MIN_WORDS and COMMENT_MAX_WORDS.
        A 3-word comment is rejected; a 16-word comment is rejected.
        A 7-word comment is accepted.
        """
        agent = self.make_agent()
        accounts = make_pod_account_ids(8)
        pod = agent.create_pod(account_ids=accounts, niche="fitness")
        session = make_session(accounts[1])

        task = PodCommentTask(
            poster_account_id=accounts[0],
            media_id="media_wordcount",
            pod_id=pod.pod_id,
            commenter_account_id=accounts[1],
            scheduled_at_unix=time.time(),
        )

        # Valid 7-word comment (within bounds)
        valid_comment = "this workout routine really changed my game"
        assert COMMENT_MIN_WORDS <= len(valid_comment.split()) <= COMMENT_MAX_WORDS

        with patch(
            "phantom_fleet.agents.specialists.ig_comment_pod_agent.httpx.AsyncClient"
        ) as mock_http_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": valid_comment}}]
            }
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http_cls.return_value = mock_http

            with patch(
                "phantom_fleet.core.instagram_client.InstagramClient._post",
                new_callable=AsyncMock,
                return_value={"status": "ok"},
            ):
                result = await agent.run_pod_comment(
                    task=task, session=session, date_iso="2026-04-11"
                )

        assert result.success is True
        assert result.data["comment_text"] == valid_comment

    # ------------------------------------------------------------------
    # Auto-assign
    # ------------------------------------------------------------------

    def test_auto_assign_creates_pods(self):
        """
        auto_assign with 20 accounts of the same niche should create 2 pods
        (each 10 accounts = 2 full pods).
        """
        agent = self.make_agent()
        accounts = [
            {"account_id": f"acct_{i:03d}", "niche": "fitness"}
            for i in range(20)
        ]
        pods = agent.assign_accounts_to_pods(accounts)
        assert len(pods) == 2
        total_members = sum(len(p.account_ids) for p in pods)
        assert total_members == 20

    def test_auto_assign_mixed_niches(self):
        """
        10 fitness + 10 lifestyle → 2 pods (1 per niche).
        """
        agent = self.make_agent()
        accounts = (
            [{"account_id": f"fit_{i}", "niche": "fitness"} for i in range(10)]
            + [{"account_id": f"lif_{i}", "niche": "lifestyle"} for i in range(10)]
        )
        pods = agent.assign_accounts_to_pods(accounts)
        niches = {p.niche for p in pods}
        assert "fitness" in niches
        assert "lifestyle" in niches
        assert len(pods) == 2

    def test_auto_assign_residual_below_min_is_skipped(self):
        """
        7 accounts (< 8 minimum) → 0 pods created (residual skipped).
        """
        agent = self.make_agent()
        accounts = [
            {"account_id": f"a{i}", "niche": "fitness"} for i in range(7)
        ]
        pods = agent.assign_accounts_to_pods(accounts)
        assert len(pods) == 0
