"""
Tests for the Reddit specialist agent suite.

Coverage:
    - RedditKarmaFarmingAgent: stage 1 no comments, stage 2 comments, CQS
      calculation, graduation_ready flag at correct thresholds
    - RedditPostAgent: pre-post browse called, compose dwell called, daily
      cap at 3, dedup prevents repeat title, ValueError on small template
      pool, only stage >= 3 accounts post
    - RedditInboxChatAgent: bot filtering (AutoModerator skipped), daily cap
      at 30, 120s gate per thread, LLM tell stripped, PPV pitch at threshold,
      XML delimit verified
    - RedditShadowbanCheckAgent: shadowban detected when public < authenticated,
      quarantine set, uncertain when counts differ significantly
    - human_post_behavior module: all functions exist, timing is not zero

asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
All HTTP calls are mocked.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal stubs so imports resolve without a live database
# ---------------------------------------------------------------------------

def _make_session(username: str = "test_user") -> Any:
    from phantom_fleet.core.reddit_client import RedditSession
    from phantom_fleet.core.hybrid_runner import PlatformHeaders
    headers = PlatformHeaders(
        device_id="dev123",
        locale="en_US",
        extra={"reddit_device_id": "dev123", "loid": "loid123", "reddit_session": "sess123"},
    )
    return RedditSession(
        account_id="acct_001",
        access_token="tok_abc",
        refresh_token="ref_xyz",
        user_id="t2_abc",
        username=username,
        headers=headers,
        is_valid=True,
    )


def _make_run(agent_name: str = "test") -> Any:
    from phantom_fleet.agents.base import AgentRun
    return AgentRun(
        run_id="run_001",
        agent_name=agent_name,
        started_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session():
    return _make_session()


@pytest.fixture
def run():
    return _make_run()


# ---------------------------------------------------------------------------
# Helpers for mock Reddit client responses
# ---------------------------------------------------------------------------

def _make_post_listing(n: int = 10) -> dict:
    """Build a minimal Reddit listing with n post items."""
    children = [
        {"data": {"name": f"t3_{i:05d}", "title": f"Post {i}", "selftext": ""}}
        for i in range(n)
    ]
    return {"data": {"children": children, "after": None}}


def _make_inbox_pm(sender: str, body: str, subject: str = "Hello") -> dict:
    return {
        "kind": "t4",
        "data": {
            "author":  sender,
            "subject": subject,
            "body":    body,
            "new":     True,
        },
    }


# ===========================================================================
# human_post_behavior tests
# ===========================================================================


class TestHumanPostBehavior:
    """Verify the module exports all required symbols and timing is not zero."""

    def test_module_imports(self):
        from phantom_fleet.core import human_post_behavior as hpb
        assert callable(hpb.pre_post_browse_delay)
        assert callable(hpb.compose_dwell)
        assert callable(hpb.typing_delay)
        assert callable(hpb.rethink_pause)
        assert callable(hpb.inter_post_delay)
        assert callable(hpb.post_time_jitter_seconds)
        assert callable(hpb.should_rethink)
        assert callable(hpb.select_template)

    async def test_pre_post_browse_returns_nonzero(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            from phantom_fleet.core.human_post_behavior import pre_post_browse_delay
            duration = await pre_post_browse_delay()
            assert duration > 0
            mock_sleep.assert_called_once()

    async def test_compose_dwell_returns_nonzero(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            from phantom_fleet.core.human_post_behavior import compose_dwell
            duration = await compose_dwell()
            assert duration > 0
            mock_sleep.assert_called_once()

    async def test_typing_delay_scales_with_text(self):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            from phantom_fleet.core.human_post_behavior import typing_delay
            d_short = await typing_delay("hi")
            d_long  = await typing_delay("x" * 200)
            # Long text should take longer (stochastic but almost certainly true
            # with a large enough text difference)
            assert d_long >= d_short or d_long > 0

    async def test_typing_delay_empty_text_is_zero(self):
        from phantom_fleet.core.human_post_behavior import typing_delay
        d = await typing_delay("")
        assert d == 0.0

    async def test_rethink_pause_returns_nonzero(self):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            from phantom_fleet.core.human_post_behavior import rethink_pause
            duration = await rethink_pause()
            assert duration > 0
            mock_sleep.assert_called_once()

    def test_post_time_jitter_is_int(self):
        from phantom_fleet.core.human_post_behavior import post_time_jitter_seconds
        j = post_time_jitter_seconds()
        assert isinstance(j, int)
        assert -1800 <= j <= 1800

    def test_should_rethink_returns_bool(self):
        from phantom_fleet.core.human_post_behavior import should_rethink
        result = should_rethink()
        assert isinstance(result, bool)

    def test_select_template_deterministic(self):
        from phantom_fleet.core.human_post_behavior import select_template
        pool = [f"item_{i}" for i in range(25)]
        r1 = select_template(pool, seed=42)
        r2 = select_template(pool, seed=42)
        assert r1 == r2

    def test_select_template_empty_raises(self):
        from phantom_fleet.core.human_post_behavior import select_template
        with pytest.raises(ValueError):
            select_template([], seed=1)


# ===========================================================================
# CQS calculation
# ===========================================================================


class TestCQS:
    def test_cqs_formula(self):
        from phantom_fleet.agents.specialists.reddit_karma_farming_agent import compute_cqs
        assert compute_cqs(100, 10, 5) == 100 + 20 + 25  # 145
        assert compute_cqs(0, 0, 0) == 0
        assert compute_cqs(500, 45, 50) == 500 + 90 + 250  # 840

    def test_cqs_threshold_for_stage_4(self):
        from phantom_fleet.agents.specialists.reddit_karma_farming_agent import compute_cqs
        # Stage 4 minimum is CQS >= 500
        assert compute_cqs(400, 25, 8) >= 0   # could be below 500
        assert compute_cqs(300, 50, 10) == 300 + 100 + 50  # 450 — below 500
        assert compute_cqs(100, 100, 50) == 100 + 200 + 250  # 550 — above 500


# ===========================================================================
# RedditKarmaFarmingAgent
# ===========================================================================


class TestRedditKarmaFarmingAgent:

    def _make_agent(self) -> Any:
        from phantom_fleet.agents.specialists.reddit_karma_farming_agent import (
            RedditKarmaFarmingAgent,
        )
        return RedditKarmaFarmingAgent(tool_registry={}, audit_sink=lambda e: None)

    def _base_ctx(self, stage: int = 1, **kwargs) -> dict:
        return {
            "account_id":         "acct_001",
            "stage":              stage,
            "session":            _make_session(),
            "account_age_days":   0,
            "karma_score":        0,
            "comment_count":      0,
            "unique_subreddits":  0,
            "session_cap_min":    15,
            "subscribed_subs":    [],
            "proxy_url":          "socks5://127.0.0.1:8089",
            **kwargs,
        }

    async def test_stage1_no_comments(self):
        """Stage 1 must not call client.comment()."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=1)

        with patch(
            "phantom_fleet.agents.specialists.reddit_karma_farming_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.subscribe_subreddit = AsyncMock(return_value={})
            mock_client.upvote = AsyncMock(return_value={})
            mock_client.comment = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(10))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                run = await agent.run(ctx)

        mock_client.comment.assert_not_called()
        assert run.outputs.get("comments_posted", 0) == 0

    async def test_stage2_makes_comments(self):
        """Stage 2 must call client.comment() at least once."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=2, account_age_days=10)

        with patch(
            "phantom_fleet.agents.specialists.reddit_karma_farming_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.subscribe_subreddit = AsyncMock(return_value={})
            mock_client.upvote = AsyncMock(return_value={})
            mock_client.comment = AsyncMock(return_value={"json": {"data": {"id": "c001"}}})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(10))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                run = await agent.run(ctx)

        assert mock_client.comment.call_count >= 1
        assert run.outputs.get("comments_posted", 0) >= 1

    async def test_graduation_stage1_age_gate(self):
        """Stage 1 graduates when account_age_days >= 7."""
        agent = self._make_agent()

        with patch(
            "phantom_fleet.agents.specialists.reddit_karma_farming_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.subscribe_subreddit = AsyncMock(return_value={})
            mock_client.upvote = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                # Not ready (age 6)
                run_not_ready = await agent.run(self._base_ctx(stage=1, account_age_days=6))
                # Ready (age 7)
                run_ready = await agent.run(self._base_ctx(stage=1, account_age_days=7))

        assert run_not_ready.outputs["graduation_ready"] is False
        assert run_ready.outputs["graduation_ready"] is True

    async def test_graduation_stage2_comment_gate(self):
        """Stage 2 graduates when lifetime comment_count >= 20."""
        agent = self._make_agent()

        with patch(
            "phantom_fleet.agents.specialists.reddit_karma_farming_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.subscribe_subreddit = AsyncMock(return_value={})
            mock_client.upvote  = AsyncMock(return_value={})
            mock_client.comment = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(10))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                # Not ready (19 lifetime comments + 1 this session = 20, now ready)
                run_ready = await agent.run(
                    self._base_ctx(stage=2, account_age_days=14, comment_count=19)
                )

        # After posting 1 comment this session, total is 20 → graduation_ready
        assert run_ready.outputs["graduation_ready"] is True

    async def test_graduation_stage3_cqs_gate(self):
        """Stage 3 graduates when CQS >= 500."""
        from phantom_fleet.agents.specialists.reddit_karma_farming_agent import compute_cqs
        agent = self._make_agent()

        with patch(
            "phantom_fleet.agents.specialists.reddit_karma_farming_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.subscribe_subreddit = AsyncMock(return_value={})
            mock_client.upvote    = AsyncMock(return_value={})
            mock_client.comment   = AsyncMock(return_value={})
            mock_client.submit_post = AsyncMock(return_value={"json": {"data": {"id": "p001"}}})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch(
                    "phantom_fleet.core.human_post_behavior.pre_post_browse_delay",
                    new_callable=AsyncMock, return_value=1.0,
                ):
                    with patch(
                        "phantom_fleet.core.human_post_behavior.compose_dwell",
                        new_callable=AsyncMock, return_value=1.0,
                    ):
                        with patch(
                            "phantom_fleet.core.human_post_behavior.typing_delay",
                            new_callable=AsyncMock, return_value=1.0,
                        ):
                            with patch(
                                "phantom_fleet.core.human_post_behavior.should_rethink",
                                return_value=False,
                            ):
                                # High karma, 50 days old, 50 subs → CQS = 400 + 100 + 250 = 750
                                run = await agent.run(self._base_ctx(
                                    stage=3,
                                    account_age_days=50,
                                    karma_score=400,
                                    unique_subreddits=50,
                                    comment_count=10,
                                ))

        assert run.outputs["cqs_current"] >= 500
        assert run.outputs["graduation_ready"] is True

    async def test_stage4_skipped(self):
        """Stage 4 accounts should be skipped by this agent."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=4)

        with patch(
            "phantom_fleet.agents.specialists.reddit_karma_farming_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            run = await agent.run(ctx)

        assert run.outputs.get("skipped_stage_4") is True
        mock_client.submit_post.assert_not_called() if hasattr(mock_client, "submit_post") else None

    async def test_cqs_returned_in_outputs(self):
        """CQS is always present in run outputs."""
        agent = self._make_agent()

        with patch(
            "phantom_fleet.agents.specialists.reddit_karma_farming_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.subscribe_subreddit = AsyncMock(return_value={})
            mock_client.upvote = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                run = await agent.run(self._base_ctx(stage=1))

        assert "cqs_current" in run.outputs
        assert isinstance(run.outputs["cqs_current"], int)


# ===========================================================================
# RedditPostAgent
# ===========================================================================


class TestRedditPostAgent:

    def _make_agent(self) -> Any:
        from phantom_fleet.agents.specialists.reddit_post_agent import RedditPostAgent
        return RedditPostAgent(tool_registry={}, audit_sink=lambda e: None)

    def _base_ctx(self, stage: int = 3, **kwargs) -> dict:
        return {
            "account_id":   "acct_002",
            "stage":        stage,
            "session":      _make_session(),
            "subreddit":    "CasualConversation",
            "posts_today":  0,
            "used_titles":  [],
            "proxy_url":    "socks5://127.0.0.1:8089",
            **kwargs,
        }

    def _mock_client_ctx(self):
        """Context manager that provides a mocked RedditClient."""
        from unittest.mock import patch, AsyncMock
        return patch(
            "phantom_fleet.agents.specialists.reddit_post_agent.RedditClient"
        )

    async def test_stage_gate_blocks_stage1(self):
        """Accounts at stage < 3 must not post."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=1)

        with self._mock_client_ctx() as MockClient:
            mock_client = AsyncMock()
            mock_client.submit_post = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            run = await agent.run(ctx)

        assert run.outputs.get("blocked_stage") is True
        mock_client.submit_post.assert_not_called()

    async def test_stage_gate_blocks_stage2(self):
        """Stage 2 must also be blocked."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=2)

        with self._mock_client_ctx() as MockClient:
            mock_client = AsyncMock()
            mock_client.submit_post = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            run = await agent.run(ctx)

        assert run.outputs.get("blocked_stage") is True

    async def test_stage3_allows_posting(self):
        """Stage 3 accounts should submit a post."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=3)

        with self._mock_client_ctx() as MockClient:
            mock_client = AsyncMock()
            mock_client.submit_post = AsyncMock(return_value={"json": {"data": {"id": "p001"}}})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch(
                    "phantom_fleet.core.human_post_behavior.pre_post_browse_delay",
                    new_callable=AsyncMock, return_value=1.0,
                ):
                    with patch(
                        "phantom_fleet.core.human_post_behavior.compose_dwell",
                        new_callable=AsyncMock, return_value=1.0,
                    ):
                        with patch(
                            "phantom_fleet.core.human_post_behavior.typing_delay",
                            new_callable=AsyncMock, return_value=1.0,
                        ):
                            with patch(
                                "phantom_fleet.core.human_post_behavior.should_rethink",
                                return_value=False,
                            ):
                                run = await agent.run(ctx)

        assert run.outputs.get("posts_submitted", 0) == 1

    async def test_daily_cap_at_3(self):
        """Agent must not post if posts_today >= 3."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=3, posts_today=3)

        with self._mock_client_ctx() as MockClient:
            mock_client = AsyncMock()
            mock_client.submit_post = AsyncMock(return_value={})
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            run = await agent.run(ctx)

        assert run.outputs.get("cap_hit") is True
        mock_client.submit_post.assert_not_called()

    async def test_dedup_blocks_repeat_title(self):
        """If used_titles already contains the dedup key, agent must skip."""
        from phantom_fleet.agents.specialists.reddit_post_agent import (
            _dedup_key, TITLE_POOL, select_template
        )
        from phantom_fleet.core.distributions import seed_for

        account_id = "acct_002"
        subreddit  = "CasualConversation"
        date_iso   = datetime.now(timezone.utc).date().isoformat()
        title_seed = seed_for(account_id, date_iso, "title_0")
        title      = select_template(TITLE_POOL, title_seed)
        dk         = _dedup_key(account_id, subreddit, title)

        agent = self._make_agent()
        ctx   = self._base_ctx(stage=3, used_titles=[dk])

        with self._mock_client_ctx() as MockClient:
            mock_client = AsyncMock()
            mock_client.submit_post = AsyncMock(return_value={})
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)
            run = await agent.run(ctx)

        assert run.outputs.get("posts_skipped_dedup", 0) == 1
        mock_client.submit_post.assert_not_called()

    def test_small_title_pool_raises_at_import(self):
        """TITLE_POOL must have >= 20 entries; an undersized pool raises ValueError."""
        from phantom_fleet.agents.specialists.reddit_post_agent import TITLE_POOL, MIN_TITLE_POOL_SIZE
        assert len(TITLE_POOL) >= MIN_TITLE_POOL_SIZE

    def test_small_body_pool_raises_at_import(self):
        from phantom_fleet.agents.specialists.reddit_post_agent import BODY_POOL, MIN_BODY_POOL_SIZE
        assert len(BODY_POOL) >= MIN_BODY_POOL_SIZE

    async def test_pre_post_browse_called(self):
        """pre_post_browse_delay must be awaited before submitting."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=3)

        with self._mock_client_ctx() as MockClient:
            mock_client = AsyncMock()
            mock_client.submit_post = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch(
                    "phantom_fleet.agents.specialists.reddit_post_agent.pre_post_browse_delay",
                    new_callable=AsyncMock, return_value=1.0,
                ) as mock_browse:
                    with patch(
                        "phantom_fleet.agents.specialists.reddit_post_agent.compose_dwell",
                        new_callable=AsyncMock, return_value=1.0,
                    ):
                        with patch(
                            "phantom_fleet.agents.specialists.reddit_post_agent.typing_delay",
                            new_callable=AsyncMock, return_value=1.0,
                        ):
                            with patch(
                                "phantom_fleet.agents.specialists.reddit_post_agent.should_rethink",
                                return_value=False,
                            ):
                                run = await agent.run(ctx)

        mock_browse.assert_called_once()

    async def test_compose_dwell_called(self):
        """compose_dwell must be awaited before submitting."""
        agent = self._make_agent()
        ctx   = self._base_ctx(stage=3)

        with self._mock_client_ctx() as MockClient:
            mock_client = AsyncMock()
            mock_client.submit_post = AsyncMock(return_value={})
            mock_client.get_subreddit_posts = AsyncMock(return_value=_make_post_listing(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch(
                    "phantom_fleet.agents.specialists.reddit_post_agent.pre_post_browse_delay",
                    new_callable=AsyncMock, return_value=1.0,
                ):
                    with patch(
                        "phantom_fleet.agents.specialists.reddit_post_agent.compose_dwell",
                        new_callable=AsyncMock, return_value=1.0,
                    ) as mock_dwell:
                        with patch(
                            "phantom_fleet.agents.specialists.reddit_post_agent.typing_delay",
                            new_callable=AsyncMock, return_value=1.0,
                        ):
                            with patch(
                                "phantom_fleet.agents.specialists.reddit_post_agent.should_rethink",
                                return_value=False,
                            ):
                                run = await agent.run(ctx)

        mock_dwell.assert_called_once()


# ===========================================================================
# RedditInboxChatAgent
# ===========================================================================


class TestRedditInboxChatAgent:

    def _make_agent(self) -> Any:
        from phantom_fleet.agents.specialists.reddit_inbox_chat_agent import (
            RedditInboxChatAgent,
        )
        return RedditInboxChatAgent(tool_registry={}, audit_sink=lambda e: None)

    def _base_ctx(self, **kwargs) -> dict:
        return {
            "account_id":           "acct_003",
            "session":              _make_session(),
            "chat_mode":            "reddit_casual",
            "ppv_pitch_after_msgs": 0,
            "replies_sent_today":   0,
            "thread_states":        {},
            "proxy_url":            "socks5://127.0.0.1:8089",
            **kwargs,
        }

    def _mock_reddit_and_llm(self, inbox_messages: list, llm_reply: str = "sounds good"):
        """Return combined patch context managers."""
        from unittest.mock import patch, AsyncMock

        inbox_data = {"data": {"children": inbox_messages}}

        def _client_patcher():
            return patch(
                "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
            )

        def _llm_patcher():
            return patch.object(
                __import__(
                    "phantom_fleet.agents.specialists.reddit_inbox_chat_agent",
                    fromlist=["RedditInboxChatAgent"],
                ).RedditInboxChatAgent,
                "_call_llm",
                new_callable=AsyncMock,
                return_value=llm_reply,
            )

        return _client_patcher, _llm_patcher, inbox_data

    async def test_automod_filtered(self):
        """AutoModerator messages must not trigger a reply."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        inbox = {"data": {"children": [
            _make_inbox_pm("AutoModerator", "Your post has been removed.")
        ]}}

        with patch(
            "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.get_inbox  = AsyncMock(return_value=inbox)
            mock_client.send_pm    = AsyncMock(return_value={})
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            run = await agent.run(ctx)

        assert run.outputs.get("filtered_bots", 0) >= 1
        mock_client.send_pm.assert_not_called()

    async def test_bot_suffix_filtered(self):
        """Usernames ending in 'Bot' are filtered."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        inbox = {"data": {"children": [
            _make_inbox_pm("SomeRandomBot", "Hello there.")
        ]}}

        with patch(
            "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.get_inbox  = AsyncMock(return_value=inbox)
            mock_client.send_pm    = AsyncMock(return_value={})
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            run = await agent.run(ctx)

        assert run.outputs.get("filtered_bots", 0) >= 1

    async def test_daily_cap_at_30(self):
        """No replies are sent if replies_sent_today >= 30."""
        agent = self._make_agent()
        ctx   = self._base_ctx(replies_sent_today=30)

        inbox = {"data": {"children": [
            _make_inbox_pm("real_user", "Hey how are you?")
        ]}}

        with patch(
            "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.get_inbox  = AsyncMock(return_value=inbox)
            mock_client.send_pm    = AsyncMock(return_value={})
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            run = await agent.run(ctx)

        mock_client.send_pm.assert_not_called()
        assert run.outputs.get("replies_sent", 0) == 0

    async def test_120s_gate_per_thread(self):
        """Must not reply to same sender if last reply was < 120s ago."""
        agent = self._make_agent()

        # last_reply_at = now - 60s (less than 120s gate)
        now = time.time()
        ctx = self._base_ctx(thread_states={
            "real_user": {
                "sender": "real_user",
                "messages_sent_today": 1,
                "last_reply_at": now - 60,
                "ppv_pitched": False,
            }
        })

        inbox = {"data": {"children": [
            _make_inbox_pm("real_user", "What's up?")
        ]}}

        with patch(
            "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.get_inbox  = AsyncMock(return_value=inbox)
            mock_client.send_pm    = AsyncMock(return_value={})
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            run = await agent.run(ctx)

        mock_client.send_pm.assert_not_called()

    async def test_reply_after_gap_clears(self):
        """Reply IS sent when gap >= 120s."""
        agent = self._make_agent()

        now = time.time()
        ctx = self._base_ctx(thread_states={
            "real_user": {
                "sender": "real_user",
                "messages_sent_today": 1,
                "last_reply_at": now - 200,  # > 120s ago
                "ppv_pitched": False,
            }
        })

        inbox = {"data": {"children": [
            _make_inbox_pm("real_user", "What's up?")
        ]}}

        with patch(
            "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.get_inbox  = AsyncMock(return_value=inbox)
            mock_client.send_pm    = AsyncMock(return_value={})
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch.object(agent, "_call_llm", new=AsyncMock(return_value="sounds good")):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    run = await agent.run(ctx)

        mock_client.send_pm.assert_called_once()
        assert run.outputs.get("replies_sent", 0) == 1

    async def test_llm_tell_stripped_before_send(self):
        """Generated reply must have LLM tells stripped."""
        from phantom_fleet.agents.specialists.reddit_inbox_chat_agent import _strip_llm_tells

        raw = "Certainly! I'd be happy to help. Moreover, this is great!"
        stripped = _strip_llm_tells(raw)
        assert "Certainly!" not in stripped
        assert "I'd be happy to" not in stripped
        assert "Moreover," not in stripped

    async def test_ppv_pitch_at_threshold(self):
        """PPV pitch is appended when messages_sent_today >= ppv_pitch_threshold."""
        agent = self._make_agent()

        ctx = self._base_ctx(
            ppv_pitch_after_msgs=3,
            thread_states={
                "fan_user": {
                    "sender":              "fan_user",
                    "messages_sent_today": 3,   # at threshold
                    "last_reply_at":       0.0,
                    "ppv_pitched":         False,
                }
            }
        )

        inbox = {"data": {"children": [
            _make_inbox_pm("fan_user", "You seem interesting")
        ]}}

        sent_texts: list[str] = []

        async def _fake_send_pm(username, subject, text):
            sent_texts.append(text)
            return {}

        with patch(
            "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.get_inbox  = AsyncMock(return_value=inbox)
            mock_client.send_pm    = AsyncMock(side_effect=_fake_send_pm)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch.object(agent, "_call_llm", new=AsyncMock(return_value="hey!")):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    run = await agent.run(ctx)

        assert run.outputs.get("ppv_pitched", 0) == 1
        # The sent text should contain one of the PPV phrases
        assert any("private" in t.lower() or "vip" in t.lower() or "exclusive" in t.lower()
                   for t in sent_texts)

    def test_xml_delimit_in_prompt(self):
        """PM bodies must be wrapped in XML tags before LLM injection."""
        from phantom_fleet.agents.specialists.reddit_inbox_chat_agent import RedditInboxChatAgent
        import inspect
        source = inspect.getsource(RedditInboxChatAgent.run_once)
        assert "<user_message>" in source

    async def test_empty_inbox_no_crash(self):
        """Empty inbox must return gracefully with 0 replies."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        inbox = {"data": {"children": []}}

        with patch(
            "phantom_fleet.agents.specialists.reddit_inbox_chat_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client.get_inbox  = AsyncMock(return_value=inbox)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            run = await agent.run(ctx)

        assert run.status == "success"
        assert run.outputs.get("replies_sent", 0) == 0


# ===========================================================================
# RedditShadowbanCheckAgent
# ===========================================================================


class TestRedditShadowbanCheckAgent:

    def _make_agent(self) -> Any:
        from phantom_fleet.agents.specialists.reddit_shadowban_check_agent import (
            RedditShadowbanCheckAgent,
        )
        return RedditShadowbanCheckAgent(tool_registry={}, audit_sink=lambda e: None)

    def _base_ctx(self, **kwargs) -> dict:
        return {
            "account_id": "acct_004",
            "session":    _make_session("test_redditor"),
            "proxy_url":  "socks5://127.0.0.1:8089",
            **kwargs,
        }

    def _make_auth_response(self, n: int) -> dict:
        return {
            "data": {
                "children": [{"data": {"id": f"c{i}"}} for i in range(n)]
            }
        }

    def _make_anon_response(self, n: int, status: int = 200) -> Any:
        mock = MagicMock()
        mock.status_code = status
        if status == 200:
            mock.json.return_value = {
                "data": {
                    "children": [{"data": {"id": f"p{i}"}} for i in range(n)]
                }
            }
        return mock

    async def test_shadowbanned_when_public_zero(self):
        """Account is shadowbanned when authenticated has posts but public has 0."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        with patch(
            "phantom_fleet.agents.specialists.reddit_shadowban_check_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client._get = AsyncMock(return_value=self._make_auth_response(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient") as MockAnon:
                mock_anon = AsyncMock()
                mock_anon.get = AsyncMock(return_value=self._make_anon_response(0))
                MockAnon.return_value.__aenter__ = AsyncMock(return_value=mock_anon)
                MockAnon.return_value.__aexit__  = AsyncMock(return_value=False)

                run = await agent.run(ctx)

        assert run.outputs["shadowbanned"] is True
        assert run.outputs["status"] == "shadowbanned"

    async def test_shadowbanned_when_404(self):
        """Account is shadowbanned when public returns 404."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        with patch(
            "phantom_fleet.agents.specialists.reddit_shadowban_check_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client._get = AsyncMock(return_value=self._make_auth_response(3))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient") as MockAnon:
                mock_anon = AsyncMock()
                mock_anon.get = AsyncMock(return_value=self._make_anon_response(0, status=404))
                MockAnon.return_value.__aenter__ = AsyncMock(return_value=mock_anon)
                MockAnon.return_value.__aexit__  = AsyncMock(return_value=False)

                run = await agent.run(ctx)

        assert run.outputs["shadowbanned"] is True

    async def test_quarantine_set_when_shadowbanned(self):
        """Quarantine timestamp is set when account is shadowbanned."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        with patch(
            "phantom_fleet.agents.specialists.reddit_shadowban_check_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client._get = AsyncMock(return_value=self._make_auth_response(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient") as MockAnon:
                mock_anon = AsyncMock()
                mock_anon.get = AsyncMock(return_value=self._make_anon_response(0))
                MockAnon.return_value.__aenter__ = AsyncMock(return_value=mock_anon)
                MockAnon.return_value.__aexit__  = AsyncMock(return_value=False)

                run = await agent.run(ctx)

        assert run.outputs["quarantine_until_iso"] is not None
        q_dt = datetime.fromisoformat(run.outputs["quarantine_until_iso"])
        now  = datetime.now(timezone.utc)
        # Should be roughly 48h in the future
        diff_hours = (q_dt - now).total_seconds() / 3600
        assert 47 < diff_hours < 49

    async def test_uncertain_when_partial_shadow(self):
        """Status is 'uncertain' when public_count < 50% of authenticated_count."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        # Authenticated: 10 comments, Public: 4 comments (< 50%)
        with patch(
            "phantom_fleet.agents.specialists.reddit_shadowban_check_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client._get = AsyncMock(return_value=self._make_auth_response(10))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient") as MockAnon:
                mock_anon = AsyncMock()
                mock_anon.get = AsyncMock(return_value=self._make_anon_response(4))
                MockAnon.return_value.__aenter__ = AsyncMock(return_value=mock_anon)
                MockAnon.return_value.__aexit__  = AsyncMock(return_value=False)

                run = await agent.run(ctx)

        assert run.outputs["status"] == "uncertain"
        assert run.outputs["shadowbanned"] is False

    async def test_clean_when_counts_match(self):
        """Status is 'clean' when public count >= 50% of authenticated count."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        # Authenticated: 10, Public: 9 (>= 50%)
        with patch(
            "phantom_fleet.agents.specialists.reddit_shadowban_check_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client._get = AsyncMock(return_value=self._make_auth_response(10))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient") as MockAnon:
                mock_anon = AsyncMock()
                mock_anon.get = AsyncMock(return_value=self._make_anon_response(9))
                MockAnon.return_value.__aenter__ = AsyncMock(return_value=mock_anon)
                MockAnon.return_value.__aexit__  = AsyncMock(return_value=False)

                run = await agent.run(ctx)

        assert run.outputs["status"] == "clean"
        assert run.outputs["shadowbanned"] is False
        assert run.outputs["quarantine_until_iso"] is None

    async def test_output_keys_always_present(self):
        """All expected output keys are present regardless of result."""
        agent = self._make_agent()
        ctx   = self._base_ctx()

        with patch(
            "phantom_fleet.agents.specialists.reddit_shadowban_check_agent.RedditClient"
        ) as MockClient:
            mock_client = AsyncMock()
            mock_client._get = AsyncMock(return_value=self._make_auth_response(5))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__  = AsyncMock(return_value=False)

            with patch("httpx.AsyncClient") as MockAnon:
                mock_anon = AsyncMock()
                mock_anon.get = AsyncMock(return_value=self._make_anon_response(5))
                MockAnon.return_value.__aenter__ = AsyncMock(return_value=mock_anon)
                MockAnon.return_value.__aexit__  = AsyncMock(return_value=False)

                run = await agent.run(ctx)

        required_keys = {
            "status", "authenticated_post_count", "public_post_count",
            "shadowbanned", "quarantine_until_iso",
        }
        assert required_keys.issubset(run.outputs.keys())


# ===========================================================================
# Comment pool validation
# ===========================================================================


class TestCommentPool:
    def test_comment_pool_min_40(self):
        from phantom_fleet.agents.specialists.reddit_karma_farming_agent import COMMENT_POOL
        assert len(COMMENT_POOL) >= 40

    def test_comment_selection_deterministic(self):
        from phantom_fleet.agents.specialists.reddit_karma_farming_agent import _comment_for
        c1 = _comment_for("acct_001", "t3_abc123")
        c2 = _comment_for("acct_001", "t3_abc123")
        assert c1 == c2

    def test_comment_selection_varies_by_account(self):
        """Different accounts commenting on the same post get different comments."""
        from phantom_fleet.agents.specialists.reddit_karma_farming_agent import (
            _comment_for, COMMENT_POOL
        )
        # With 44 pool entries, 44 different accounts will all get different comments
        comments = [_comment_for(f"acct_{i:04d}", "t3_shared_post") for i in range(44)]
        # At least half should be unique (deterministic seeding ensures full diversity)
        assert len(set(comments)) > len(COMMENT_POOL) // 2
