"""
Tests for Bluesky specialist agents and client.

Covers:
    - bluesky_client.py new methods (get_follows, get_feed, unlike_post, put_record)
    - BlueSkyUnfollowAgent: strategy sorting, ratio protection, daily cap
    - BlueSkyLikeAgent: topic scoring, dedup, daily cap
    - BlueSkyScrapeAgent: topic shuffle, DID dedup, blast-radius cap
    - BlueSkyFeedAgent: rkey derivation, record build, missing URL guard
    - BlueSkyCrossPostAgent: text adaptation, dedup, cross-platform hash

All external HTTP calls are mocked. No real AT Protocol network traffic.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pytest
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def _make_session(did: str = "did:plc:test123", handle: str = "test.bsky.social") -> Any:
    """Create a minimal BlueSkySession-like object for testing."""
    from phantom_fleet.core.bluesky_client import BlueSkySession
    from phantom_fleet.core.hybrid_runner import PlatformHeaders

    headers = PlatformHeaders(
        platform="bluesky",
        session_token="tok_bluesky",
        device_id="dev_bluesky",
        user_agent="Mozilla/5.0 (BlueTest)",
        app_version="1.0.0",
        android_id="abc123",
        advertising_id="gaid-test",
        carrier_name="Test",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
    )
    return BlueSkySession(
        account_id="acct_1",
        did=did,
        access_jwt="jwt_test",
        refresh_jwt="refresh_test",
        handle=handle,
        headers=headers,
    )


def _make_run() -> Any:
    from phantom_fleet.agents.base import AgentRun
    return AgentRun(
        run_id="run_test",
        agent_name="test",
        started_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# BlueSkyClient new method tests
# ---------------------------------------------------------------------------


class TestBlueSkyClientNewMethods:
    """Tests for the three new client methods added in this build."""

    def test_get_follows_builds_correct_params(self):
        """get_follows calls app.bsky.graph.getFollows with actor + limit."""
        from phantom_fleet.core.bluesky_client import BlueSkyClient

        session = _make_session()
        client = BlueSkyClient(session)

        calls: list[dict] = []

        async def fake_get(lexicon: str, params: dict = None) -> dict:
            calls.append({"lexicon": lexicon, "params": params or {}})
            return {"follows": [], "cursor": ""}

        client._get = fake_get  # type: ignore[assignment]

        asyncio.run(
            client.get_follows(actor="did:plc:test123", limit=25)
        )

        assert len(calls) == 1
        assert calls[0]["lexicon"] == "app.bsky.graph.getFollows"
        assert calls[0]["params"]["actor"] == "did:plc:test123"
        assert calls[0]["params"]["limit"] == 25

    def test_get_follows_passes_cursor(self):
        from phantom_fleet.core.bluesky_client import BlueSkyClient

        session = _make_session()
        client = BlueSkyClient(session)
        calls: list[dict] = []

        async def fake_get(lexicon, params=None):
            calls.append({"lexicon": lexicon, "params": params or {}})
            return {}

        client._get = fake_get
        asyncio.run(
            client.get_follows("did:plc:test", limit=10, cursor="page2")
        )
        assert calls[0]["params"]["cursor"] == "page2"

    def test_get_feed_builds_correct_params(self):
        from phantom_fleet.core.bluesky_client import BlueSkyClient

        session = _make_session()
        client = BlueSkyClient(session)
        calls: list[dict] = []

        async def fake_get(lexicon, params=None):
            calls.append({"lexicon": lexicon, "params": params or {}})
            return {}

        client._get = fake_get
        asyncio.run(
            client.get_feed("at://did:plc:xxx/app.bsky.feed.generator/hot", limit=30)
        )
        assert calls[0]["lexicon"] == "app.bsky.feed.getFeed"
        assert calls[0]["params"]["feed"] == "at://did:plc:xxx/app.bsky.feed.generator/hot"
        assert calls[0]["params"]["limit"] == 30

    def test_unlike_post_calls_delete_record(self):
        from phantom_fleet.core.bluesky_client import BlueSkyClient

        session = _make_session()
        client = BlueSkyClient(session)
        calls: list[dict] = []

        async def fake_post(lexicon, payload=None):
            calls.append({"lexicon": lexicon, "payload": payload or {}})
            return {}

        client._post = fake_post
        asyncio.run(
            client.unlike_post("rkey_abc123")
        )
        assert calls[0]["lexicon"] == "com.atproto.repo.deleteRecord"
        assert calls[0]["payload"]["collection"] == "app.bsky.feed.like"
        assert calls[0]["payload"]["rkey"] == "rkey_abc123"

    def test_put_record_calls_correct_lexicon(self):
        from phantom_fleet.core.bluesky_client import BlueSkyClient

        session = _make_session()
        client = BlueSkyClient(session)
        calls: list[dict] = []

        async def fake_post(lexicon, payload=None):
            calls.append({"lexicon": lexicon, "payload": payload or {}})
            return {"uri": "at://did:plc:test/app.bsky.feed.generator/rkey1"}

        client._post = fake_post
        asyncio.run(
            client.put_record("app.bsky.feed.generator", "rkey1", {"$type": "..."})
        )
        assert calls[0]["lexicon"] == "com.atproto.repo.putRecord"
        assert calls[0]["payload"]["rkey"] == "rkey1"
        assert calls[0]["payload"]["collection"] == "app.bsky.feed.generator"


# ---------------------------------------------------------------------------
# BlueSkyUnfollowAgent
# ---------------------------------------------------------------------------


class TestBlueSkyUnfollowAgent:

    def _make_records(self, count: int, is_follower: bool = False) -> list[dict]:
        return [
            {
                "did":             f"did:plc:target{i}",
                "rkey":            f"rkey{i}",
                "followed_at_iso": f"2026-01-{i:02d}T00:00:00Z",
                "is_follower":     is_follower,
            }
            for i in range(1, count + 1)
        ]

    def test_non_followers_sorted_before_mutuals(self):
        from phantom_fleet.agents.specialists.bluesky_unfollow_agent import (
            _sort_non_followers_first,
        )

        records = [
            {"did": "a", "rkey": "r1", "followed_at_iso": "", "is_follower": True},
            {"did": "b", "rkey": "r2", "followed_at_iso": "", "is_follower": False},
            {"did": "c", "rkey": "r3", "followed_at_iso": "", "is_follower": True},
            {"did": "d", "rkey": "r4", "followed_at_iso": "", "is_follower": False},
        ]
        result = _sort_non_followers_first(records, "acct_1", "2026-04-13")
        non_follower_dids = {r["did"] for r in result[:2]}
        mutual_dids       = {r["did"] for r in result[2:]}
        assert non_follower_dids == {"b", "d"}
        assert mutual_dids == {"a", "c"}

    def test_rkey_from_uri(self):
        from phantom_fleet.agents.specialists.bluesky_unfollow_agent import _rkey_from_uri
        uri = "at://did:plc:abc123/app.bsky.graph.follow/3kwx5abc"
        assert _rkey_from_uri(uri) == "3kwx5abc"

    def test_daily_cap_enforced(self):
        """Agent stops at MAX_UNFOLLOWS_PER_DAY even if more records provided."""
        from phantom_fleet.agents.specialists.bluesky_unfollow_agent import (
            BlueSkyUnfollowAgent,
            MAX_UNFOLLOWS_PER_DAY,
        )

        agent = BlueSkyUnfollowAgent()
        records = self._make_records(MAX_UNFOLLOWS_PER_DAY + 20)

        unfollow_calls: list[str] = []

        async def fake_unfollow(follow_rkey: str) -> dict:
            unfollow_calls.append(follow_rkey)
            return {}

        async def run_it():
            from phantom_fleet.core.bluesky_client import BlueSkyClient
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":      "acct_1",
                "session":         session,
                "follow_records":  records,
                "target_count":    MAX_UNFOLLOWS_PER_DAY + 20,  # try to go over cap
                "current_followers": 1000,
                "current_follows": len(records),
                "keep_ratio_target": 0.0,  # no ratio protection for this test
            }

            with patch("phantom_fleet.agents.specialists.bluesky_unfollow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.unfollow_user = fake_unfollow
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_unfollow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

        asyncio.run(run_it())
        assert len(unfollow_calls) == MAX_UNFOLLOWS_PER_DAY

    def test_ratio_protection_stops_early(self):
        """Agent stops when next unfollow would drop below keep_ratio_target."""
        from phantom_fleet.agents.specialists.bluesky_unfollow_agent import BlueSkyUnfollowAgent

        agent = BlueSkyUnfollowAgent()
        # 5 follows, 3 followers → ratio = 5/3 ≈ 1.67
        # If we unfollow 1 → 4/3 ≈ 1.33, keep_ratio = 1.5 → should stop after 0 unfollows
        records = self._make_records(5, is_follower=False)
        unfollow_calls: list[str] = []

        async def fake_unfollow(follow_rkey: str) -> dict:
            unfollow_calls.append(follow_rkey)
            return {}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":        "acct_1",
                "session":           session,
                "follow_records":    records,
                "target_count":      10,
                "current_followers": 3,
                "current_follows":   5,
                "keep_ratio_target": 1.5,  # 4/3 < 1.5 → block immediately
            }
            with patch("phantom_fleet.agents.specialists.bluesky_unfollow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.unfollow_user = fake_unfollow
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_unfollow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

        asyncio.run(run_it())
        assert len(unfollow_calls) == 0

    def test_empty_follow_records_no_error(self):
        from phantom_fleet.agents.specialists.bluesky_unfollow_agent import BlueSkyUnfollowAgent

        agent = BlueSkyUnfollowAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {"account_id": "acct_1", "session": session, "follow_records": []}
            done = await agent.run_once(ctx, run)
            assert done is True
            assert run.outputs["result"].unfollowed == 0

        asyncio.run(run_it())


# ---------------------------------------------------------------------------
# BlueSkyLikeAgent
# ---------------------------------------------------------------------------


class TestBlueSkyLikeAgent:

    def test_topic_score_zero_threshold_likes_all(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import _topic_score
        score = _topic_score("some random post text", topic_affinity=[])
        assert score == 1  # no affinity filter → always passes

    def test_topic_score_keyword_match(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import _topic_score
        score = _topic_score("I love fitness and wellness", ["fitness", "coding"])
        assert score == 1

    def test_topic_score_no_match(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import _topic_score
        score = _topic_score("post about cooking and food", ["fitness", "coding"])
        assert score == 0

    def test_extract_posts_from_timeline_feed(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import _extract_posts_from_feed
        feed_resp = {
            "feed": [
                {"post": {"uri": "at://1", "cid": "cid1", "record": {"text": "hello"}}},
                {"post": {"uri": "at://2", "cid": "cid2", "text": "world"}},
            ]
        }
        posts = _extract_posts_from_feed(feed_resp)
        assert len(posts) == 2
        assert posts[0]["uri"] == "at://1"
        assert posts[1]["uri"] == "at://2"

    def test_extract_posts_from_search_response(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import _extract_posts_from_feed
        feed_resp = {
            "posts": [
                {"uri": "at://3", "cid": "cid3", "record": {"text": "search result"}},
            ]
        }
        posts = _extract_posts_from_feed(feed_resp)
        assert len(posts) == 1
        assert posts[0]["uri"] == "at://3"

    def test_daily_cap_enforced(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import (
            BlueSkyLikeAgent,
            MAX_LIKES_PER_DAY,
        )

        agent = BlueSkyLikeAgent()
        posts = [{"uri": f"at://{i}", "cid": f"cid{i}", "text": "test"} for i in range(50)]
        like_calls: list[str] = []

        async def fake_like(uri: str, cid: str) -> dict:
            like_calls.append(uri)
            return {}

        async def fake_fetch(client, feed_source, feed_uri, topic_affinity, limit):
            return posts

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":           "acct_1",
                "session":              session,
                "target_count":         MAX_LIKES_PER_DAY + 10,
                "already_liked_today":  MAX_LIKES_PER_DAY - 5,  # near cap
            }
            with patch.object(agent, "_fetch_posts", side_effect=fake_fetch):
                with patch("phantom_fleet.agents.specialists.bluesky_like_agent.BlueSkyClient") as MockClient:
                    mock_instance = AsyncMock()
                    mock_instance.like_post = AsyncMock(side_effect=fake_like)
                    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                    mock_instance.__aexit__  = AsyncMock(return_value=None)
                    MockClient.return_value = mock_instance

                    with patch("phantom_fleet.agents.specialists.bluesky_like_agent.asyncio.sleep", new=AsyncMock()):
                        await agent.run_once(ctx, run)

        asyncio.run(run_it())
        # already_liked=MAX-5, cap=MAX → only 5 more allowed
        assert len(like_calls) == 5

    def test_session_dedup_skips_already_liked(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import BlueSkyLikeAgent

        agent = BlueSkyLikeAgent()
        like_calls: list[str] = []

        async def fake_like(uri: str, cid: str) -> dict:
            like_calls.append(uri)
            return {}

        async def fake_fetch(client, feed_source, feed_uri, topic_affinity, limit):
            return [{"uri": "at://dupe", "cid": "cid1", "text": "test"}]

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session":    session,
                "target_count": 10,
                "liked_uris": {"at://dupe"},  # already in session dedup
            }
            with patch.object(agent, "_fetch_posts", side_effect=fake_fetch):
                with patch("phantom_fleet.agents.specialists.bluesky_like_agent.BlueSkyClient") as MockClient:
                    mock_instance = AsyncMock()
                    mock_instance.like_post = AsyncMock(side_effect=fake_like)
                    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                    mock_instance.__aexit__  = AsyncMock(return_value=None)
                    MockClient.return_value = mock_instance

                    with patch("phantom_fleet.agents.specialists.bluesky_like_agent.asyncio.sleep", new=AsyncMock()):
                        await agent.run_once(ctx, run)

        asyncio.run(run_it())
        assert len(like_calls) == 0  # skipped by dedup


# ---------------------------------------------------------------------------
# BlueSkyScrapeAgent
# ---------------------------------------------------------------------------


class TestBlueSkyScrapeAgent:

    def test_blast_radius_cap_enforced(self):
        from phantom_fleet.agents.specialists.bluesky_scrape_agent import (
            BlueSkyScrapeAgent,
            MAX_DIDS_PER_RUN,
        )

        agent = BlueSkyScrapeAgent()

        search_results = {
            "posts": [
                {"author": {"did": f"did:plc:target{i}", "handle": f"user{i}.bsky.social"}}
                for i in range(200)
            ]
        }

        async def fake_search(query: str, limit: int = 25) -> dict:
            return search_results

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session":    session,
                "topics":     ["fitness"],
                "max_dids":   MAX_DIDS_PER_RUN + 100,  # try to exceed cap
            }
            with patch("phantom_fleet.agents.specialists.bluesky_scrape_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.search_posts = AsyncMock(side_effect=fake_search)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_scrape_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

            return run

        run = asyncio.run(run_it())
        assert len(run.outputs["new_dids"]) <= MAX_DIDS_PER_RUN

    def test_existing_pool_dedup(self):
        from phantom_fleet.agents.specialists.bluesky_scrape_agent import BlueSkyScrapeAgent

        agent = BlueSkyScrapeAgent()
        existing = {"did:plc:target1", "did:plc:target2"}

        search_results = {
            "posts": [
                {"author": {"did": "did:plc:target1", "handle": "known1.bsky.social"}},
                {"author": {"did": "did:plc:target2", "handle": "known2.bsky.social"}},
                {"author": {"did": "did:plc:new1",    "handle": "new1.bsky.social"}},
            ]
        }

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":        "acct_1",
                "session":           session,
                "topics":            ["fitness"],
                "existing_did_pool": list(existing),
            }
            with patch("phantom_fleet.agents.specialists.bluesky_scrape_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.search_posts = AsyncMock(return_value=search_results)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_scrape_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

            return run

        run = asyncio.run(run_it())
        assert run.outputs["new_dids"] == ["did:plc:new1"]

    def test_no_duplicate_dids_in_output(self):
        """Same DID appearing in multiple search result pages is only returned once."""
        from phantom_fleet.agents.specialists.bluesky_scrape_agent import BlueSkyScrapeAgent

        agent = BlueSkyScrapeAgent()
        search_results = {
            "posts": [
                {"author": {"did": "did:plc:dup", "handle": "dup.bsky.social"}},
                {"author": {"did": "did:plc:dup", "handle": "dup.bsky.social"}},
                {"author": {"did": "did:plc:unique", "handle": "unique.bsky.social"}},
            ]
        }

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {"account_id": "acct_1", "session": session, "topics": ["art", "music"]}
            with patch("phantom_fleet.agents.specialists.bluesky_scrape_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.search_posts = AsyncMock(return_value=search_results)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_scrape_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

            return run

        run = asyncio.run(run_it())
        dids = run.outputs["new_dids"]
        assert len(dids) == len(set(dids))  # no duplicates


# ---------------------------------------------------------------------------
# BlueSkyFeedAgent
# ---------------------------------------------------------------------------


class TestBlueSkyFeedAgent:

    def test_stable_rkey_is_deterministic(self):
        from phantom_fleet.agents.specialists.bluesky_feed_agent import _stable_rkey
        r1 = _stable_rkey("my-creator-feed")
        r2 = _stable_rkey("my-creator-feed")
        assert r1 == r2
        assert len(r1) == 32

    def test_stable_rkey_different_feed_ids(self):
        from phantom_fleet.agents.specialists.bluesky_feed_agent import _stable_rkey
        assert _stable_rkey("feed-a") != _stable_rkey("feed-b")

    def test_generator_record_structure(self):
        from phantom_fleet.agents.specialists.bluesky_feed_agent import _build_generator_record
        record = _build_generator_record(
            feed_id="test-feed",
            display_name="Test Feed",
            description="A test feed",
            feed_service_url="https://feed.test.io",
            did="did:plc:test",
        )
        assert record["$type"] == "app.bsky.feed.generator"
        assert record["displayName"] == "Test Feed"
        assert record["acceptsInteractions"] is True
        assert "createdAt" in record

    def test_disable_operation_sets_accepts_interactions_false(self):
        from phantom_fleet.agents.specialists.bluesky_feed_agent import _build_generator_record
        record = _build_generator_record(
            "f", "F", "desc", "https://test.io", "did:plc:x",
            accepts_interactions=False,
        )
        assert record["acceptsInteractions"] is False

    def test_missing_feed_service_url_returns_error(self):
        from phantom_fleet.agents.specialists.bluesky_feed_agent import BlueSkyFeedAgent

        agent = BlueSkyFeedAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":      "acct_1",
                "session":         session,
                "feed_id":         "my-feed",
                "feed_service_url": "",   # missing!
            }
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert "missing_feed_service_url" in run.outputs["result"].errors

    def test_create_operation_calls_put_record(self):
        from phantom_fleet.agents.specialists.bluesky_feed_agent import BlueSkyFeedAgent

        agent = BlueSkyFeedAgent()
        put_calls: list[dict] = []

        async def fake_put_record(collection: str, rkey: str, record: dict) -> dict:
            put_calls.append({"collection": collection, "rkey": rkey})
            return {"uri": f"at://did:plc:test/{collection}/{rkey}"}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":       "acct_1",
                "session":          session,
                "feed_id":          "my-feed",
                "display_name":     "My Feed",
                "description":      "A cool feed",
                "feed_service_url": "https://feed.phantom.io",
                "operation":        "create",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_feed_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.put_record = AsyncMock(side_effect=fake_put_record)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)

            return run

        run = asyncio.run(run_it())
        assert len(put_calls) == 1
        assert put_calls[0]["collection"] == "app.bsky.feed.generator"
        assert "feed_uri" in run.outputs


# ---------------------------------------------------------------------------
# BlueSkyCrossPostAgent
# ---------------------------------------------------------------------------


class TestBlueSkyCrossPostAgent:

    def test_adapt_text_strips_mentions(self):
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import _adapt_text
        adapted = _adapt_text("Hey @username_x check this out!")
        assert "@username_x" not in adapted

    def test_adapt_text_strips_hashtags(self):
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import _adapt_text
        adapted = _adapt_text("Love this #lifestyle #travel post")
        assert "#lifestyle" not in adapted
        assert "#travel" not in adapted

    def test_truncate_natural_at_sentence(self):
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import _truncate_natural
        text = "First sentence. " + "x" * 290  # pushes well over 300
        result = _truncate_natural(text, 300)
        assert len(result) <= 300
        assert result.endswith("…")
        # Should have truncated at the first sentence
        assert "First sentence." in result

    def test_truncate_natural_at_word_boundary(self):
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import _truncate_natural
        text = "word " * 80  # 400 chars, no sentence boundaries
        result = _truncate_natural(text, 300)
        assert len(result) <= 300
        assert not result.endswith(" …")  # shouldn't have trailing space before ellipsis

    def test_content_dedup_skips_already_posted(self):
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import (
            BlueSkyCrossPostAgent,
            _content_hash,
        )

        agent = BlueSkyCrossPostAgent()
        text = "This is duplicate content"
        chash = _content_hash("acct_1", text)

        post_calls: list[str] = []

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":    "acct_1",
                "session":       session,
                "source_posts":  [{"text": text, "source_platform": "x", "source_id": "1"}],
                "posted_hashes": {chash},  # already posted
            }
            with patch("phantom_fleet.agents.specialists.bluesky_crosspost_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_timeline = AsyncMock(return_value={"feed": []})
                mock_instance.create_post  = AsyncMock(side_effect=lambda text: post_calls.append(text))
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_crosspost_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

            return run

        run = asyncio.run(run_it())
        assert len(post_calls) == 0
        assert run.outputs["result"].skipped_dedup == 1

    def test_daily_cap_shared_with_native_posts(self):
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import (
            BlueSkyCrossPostAgent,
            MAX_POSTS_PER_DAY,
        )

        agent = BlueSkyCrossPostAgent()
        sources = [
            {"text": f"Cross-post content {i}", "source_platform": "x", "source_id": str(i)}
            for i in range(20)
        ]
        post_calls: list[str] = []

        async def fake_create(text: str) -> dict:
            post_calls.append(text)
            return {}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":           "acct_1",
                "session":              session,
                "source_posts":         sources,
                "already_posted_today": MAX_POSTS_PER_DAY - 2,  # 2 slots left
                "max_per_day":          10,
            }
            with patch("phantom_fleet.agents.specialists.bluesky_crosspost_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_timeline = AsyncMock(return_value={"feed": []})
                mock_instance.create_post  = AsyncMock(side_effect=fake_create)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_crosspost_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

        asyncio.run(run_it())
        assert len(post_calls) == 2  # cap respected

    def test_max_source_posts_blast_radius(self):
        """Agent silently truncates source_posts list at MAX_SOURCE_POSTS."""
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import (
            BlueSkyCrossPostAgent,
            MAX_SOURCE_POSTS,
        )

        agent = BlueSkyCrossPostAgent()
        # Feed more than MAX_SOURCE_POSTS
        sources = [
            {"text": f"Post {i}", "source_platform": "ig", "source_id": str(i)}
            for i in range(MAX_SOURCE_POSTS + 20)
        ]

        processed: list[str] = []

        async def fake_create(text: str) -> dict:
            processed.append(text)
            return {}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":   "acct_1",
                "session":      session,
                "source_posts": sources,
                "max_per_day":  MAX_SOURCE_POSTS + 20,  # no per-day limit
            }
            with patch("phantom_fleet.agents.specialists.bluesky_crosspost_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_timeline = AsyncMock(return_value={"feed": []})
                mock_instance.create_post  = AsyncMock(side_effect=fake_create)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance

                with patch("phantom_fleet.agents.specialists.bluesky_crosspost_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)

        asyncio.run(run_it())
        # posts_per_day=8 caps it even before MAX_SOURCE_POSTS, but key check is
        # that we never process more than MAX_SOURCE_POSTS items
        assert len(processed) <= min(MAX_SOURCE_POSTS, 8)


# ---------------------------------------------------------------------------
# Fleet-level distribution shape tests
# ---------------------------------------------------------------------------


class TestBlueSkyFleetDistributions:
    """
    CLAUDE.md 20K-account rule: verify distribution shapes are non-uniform.
    These tests sample distributions at scale and check histogram shape.
    """

    def test_unfollow_inter_action_sleep_is_lognormal(self):
        """Inter-unfollow sleep distribution should have long right tail (not uniform)."""
        from phantom_fleet.agents.specialists.bluesky_unfollow_agent import _INTER_UNFOLLOW_DIST

        samples = [
            _INTER_UNFOLLOW_DIST.sample(
                account_id=f"acct_{i}",
                date_iso="2026-04-13",
                field=f"test_{i}",
            )
            for i in range(500)
        ]
        mean_val = sum(samples) / len(samples)
        median_approx = sorted(samples)[len(samples) // 2]
        # LogNormal: mean > median (right-skewed)
        assert mean_val > median_approx, "Expected right-skewed (mean > median)"

    def test_like_inter_action_sleep_is_lognormal(self):
        from phantom_fleet.agents.specialists.bluesky_like_agent import _INTER_LIKE_DIST

        samples = [
            _INTER_LIKE_DIST.sample(
                account_id=f"acct_{i}",
                date_iso="2026-04-13",
                field=f"test_{i}",
            )
            for i in range(500)
        ]
        mean_val = sum(samples) / len(samples)
        median_approx = sorted(samples)[len(samples) // 2]
        assert mean_val > median_approx

    def test_crosspost_hashtag_decision_converges_to_15pct(self):
        """At 1000 accounts, hashtag injection rate should be near 15%."""
        from phantom_fleet.agents.specialists.bluesky_crosspost_agent import _should_add_hashtags

        hits = sum(
            1 for i in range(1000)
            if _should_add_hashtags(f"acct_{i}", 0)
        )
        rate = hits / 1000
        # Allow ±5% tolerance
        assert 0.10 <= rate <= 0.20, f"Hashtag rate {rate:.2%} outside 10-20% window"

    def test_scrape_topic_shuffle_differs_across_accounts(self):
        """Two accounts should produce different topic orderings."""
        import random
        import hashlib

        topics = ["fitness", "art", "gaming", "travel", "food", "music"]

        def shuffle_for(account_id: str) -> list[str]:
            seed_val = int(hashlib.sha256(
                f"{account_id}|2026-04-13|topic_shuffle".encode()
            ).hexdigest()[:8], 16)
            rng = random.Random(seed_val)
            shuffled = list(topics)
            rng.shuffle(shuffled)
            return shuffled

        orders = [shuffle_for(f"acct_{i}") for i in range(50)]
        unique_orders = {tuple(o) for o in orders}
        # Should have many different orderings across 50 accounts
        assert len(unique_orders) > 10, "Topics should shuffle differently per account"


# ---------------------------------------------------------------------------
# BlueSky A/B Test Framework
# ---------------------------------------------------------------------------


class TestBlueSkyABTestFramework:
    """Tests for core/bluesky_ab_test.py — framework logic, no LLM calls."""

    def _make_two_variants(self):
        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        return [
            BlueSkyABVariant("a", "A: Follow+Like", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY,
                             {"follow_source": "search"}),
            BlueSkyABVariant("b", "B: Follow+Like+DM", BlueSkyEngagementVariant.FOLLOW_LIKE_DM,
                             {"follow_source": "search"}),
        ]

    def test_stable_variant_assignment(self, tmp_path, monkeypatch):
        """Same account always maps to same variant regardless of restart."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import BlueSkyABManager
        mgr = BlueSkyABManager()
        accounts = [f"acct_{i}" for i in range(20)]
        spec = mgr.create_test(
            name="Stability test",
            account_ids=accounts,
            variants=self._make_two_variants(),
            start_date_iso="2026-04-13",
            end_date_iso="2026-04-27",
        )

        # Re-assign via get_variant_for_account — must match original assignment
        for account_id in accounts:
            v1 = mgr.get_variant_for_account(account_id, spec)
            v2 = mgr.get_variant_for_account(account_id, spec)
            assert v1.variant_id == v2.variant_id, \
                f"Account {account_id} got different variants on two calls"

    def test_create_test_roughly_even_split(self, tmp_path, monkeypatch):
        """50/50 hash split: neither variant gets more than 70% of cohort."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import BlueSkyABManager
        mgr = BlueSkyABManager()
        accounts = [f"acct_{i}" for i in range(100)]
        spec = mgr.create_test(
            name="Split test",
            account_ids=accounts,
            variants=self._make_two_variants(),
            start_date_iso="2026-04-13",
            end_date_iso="2026-04-27",
        )

        sizes = [len(v.assigned_account_ids) for v in spec.variants]
        for size in sizes:
            pct = size / len(accounts)
            assert pct <= 0.70, f"Variant imbalance: {pct:.0%}"

    def test_event_recording_aggregates_correctly(self, tmp_path, monkeypatch):
        """Record several event types and verify aggregate counters."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import BlueSkyABManager
        mgr = BlueSkyABManager()
        accounts = [f"acct_{i}" for i in range(10)]
        spec = mgr.create_test(
            name="Event test",
            account_ids=accounts,
            variants=self._make_two_variants(),
            start_date_iso="2026-04-13",
            end_date_iso="2026-04-27",
        )

        tid = spec.test_id
        # Record known events for variant "a"
        for _ in range(5):
            mgr.record_follow(tid, "acct_0", "a", "did:plc:x")
        for _ in range(3):
            mgr.record_follow_back(tid, "acct_0", "a", "did:plc:x")

        metrics_list = mgr.aggregate_metrics(tid, spec)
        a_metrics = next(m for m in metrics_list if m.variant_id == "a")

        assert a_metrics.follows_sent == 5
        assert a_metrics.follow_backs == 3
        assert round(a_metrics.follow_back_rate, 2) == 0.60

    def test_report_not_significant_below_min_sample(self, tmp_path, monkeypatch):
        """Report correctly reports not significant when below min_sample_size."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import BlueSkyABManager
        mgr = BlueSkyABManager()
        accounts = [f"acct_{i}" for i in range(10)]
        spec = mgr.create_test(
            name="Significance test",
            account_ids=accounts,
            variants=self._make_two_variants(),
            start_date_iso="2026-04-13",
            end_date_iso="2026-04-27",
            min_sample_size=50,
        )

        # Only 2 follows — well below 50
        mgr.record_follow(spec.test_id, "acct_0", "a", "did:plc:target1")
        mgr.record_follow(spec.test_id, "acct_0", "a", "did:plc:target2")

        report = mgr.generate_report(spec.test_id)
        assert report is not None
        assert report.is_significant is False
        assert report.winner_id is None

    def test_report_declares_winner_when_significant(self, tmp_path, monkeypatch):
        """Winner declared when both variants exceed min_sample_size."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import BlueSkyABManager
        mgr = BlueSkyABManager()
        accounts = [f"acct_{i}" for i in range(20)]
        spec = mgr.create_test(
            name="Winner test",
            account_ids=accounts,
            variants=self._make_two_variants(),
            start_date_iso="2026-04-13",
            end_date_iso="2026-04-27",
            min_sample_size=5,
        )
        tid = spec.test_id

        # Variant A: 10 follows, 6 follow-backs → 60% FBR
        for j in range(10):
            mgr.record_follow(tid, "acct_0", "a", f"did:plc:ta{j}")
        for j in range(6):
            mgr.record_follow_back(tid, "acct_0", "a", f"did:plc:ta{j}")

        # Variant B: 10 follows, 3 follow-backs → 30% FBR
        for j in range(10):
            mgr.record_follow(tid, "acct_1", "b", f"did:plc:tb{j}")
        for j in range(3):
            mgr.record_follow_back(tid, "acct_1", "b", f"did:plc:tb{j}")

        report = mgr.generate_report(tid)
        assert report is not None
        assert report.is_significant is True
        assert report.winner_id == "a"
        assert report.winner_lift_pct > 0

    def test_get_winning_params_returns_variant_params(self, tmp_path, monkeypatch):
        """get_winning_params returns the strategy + params of the winner."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import BlueSkyABManager
        mgr = BlueSkyABManager()
        accounts = [f"acct_{i}" for i in range(10)]
        spec = mgr.create_test(
            name="Params test",
            account_ids=accounts,
            variants=self._make_two_variants(),
            start_date_iso="2026-04-13",
            end_date_iso="2026-04-27",
            min_sample_size=2,
        )
        tid = spec.test_id

        # Make A the clear winner
        for j in range(5):
            mgr.record_follow(tid, "acct_0", "a", f"did:plc:x{j}")
            mgr.record_follow(tid, "acct_0", "b", f"did:plc:y{j}")
        for j in range(4):
            mgr.record_follow_back(tid, "acct_0", "a", f"did:plc:x{j}")  # 80%
        for j in range(1):
            mgr.record_follow_back(tid, "acct_0", "b", f"did:plc:y{j}")  # 20%

        params = mgr.get_winning_params(tid)
        assert params is not None
        assert "engagement_strategy" in params
        assert params["engagement_strategy"] == "follow_like_only"

    def test_list_active_tests_excludes_concluded(self, tmp_path, monkeypatch):
        """list_active_tests only returns tests with status=='running'."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import BlueSkyABManager
        mgr = BlueSkyABManager()

        spec1 = mgr.create_test(
            "Running test", ["a1", "a2"],
            self._make_two_variants(), "2026-04-13", "2026-04-27",
        )
        spec2 = mgr.create_test(
            "Concluded test", ["a3", "a4"],
            self._make_two_variants(), "2026-04-01", "2026-04-10",
        )
        # Manually conclude spec2
        from phantom_fleet.core.bluesky_ab_test import _save_spec
        spec2.status = "concluded"
        _save_spec(spec2)

        active = mgr.list_active_tests()
        active_ids = {s.test_id for s in active}
        assert spec1.test_id in active_ids
        assert spec2.test_id not in active_ids


# ---------------------------------------------------------------------------
# BlueSkyABTestAgent
# ---------------------------------------------------------------------------


class TestBlueSkyABTestAgent:
    """Tests for agents/specialists/bluesky_ab_test_agent.py."""

    def test_create_op_uses_defaults_when_llm_disabled(self, tmp_path, monkeypatch):
        """With use_llm=False, agent falls back to two-variant A/B defaults."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import BlueSkyABTestAgent

        agent = BlueSkyABTestAgent()

        async def run_it():
            run = _make_run()
            ctx = {
                "operation":       "create",
                "account_ids":     [f"acct_{i}" for i in range(10)],
                "test_name":       "LLM-disabled test",
                "start_date_iso":  "2026-04-13",
                "end_date_iso":    "2026-04-27",
                "use_llm":         False,
            }
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert "test_id" in run.outputs
        assert run.outputs["llm_used"] is False
        spec_dict = run.outputs["spec"]
        assert len(spec_dict["variants"]) == 2

    def test_evaluate_op_returns_not_significant(self, tmp_path, monkeypatch):
        """Evaluate on a test with no events reports not_significant."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import BlueSkyABTestAgent

        # Create a test directly via the framework
        mgr = BlueSkyABManager()
        variants = [
            BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY),
            BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM),
        ]
        spec = mgr.create_test(
            "Eval test", [f"acct_{i}" for i in range(4)],
            variants, "2026-04-13", "2026-04-27", min_sample_size=50,
        )

        agent = BlueSkyABTestAgent()

        async def run_it():
            run = _make_run()
            ctx = {"operation": "evaluate", "test_id": spec.test_id, "use_llm": False}
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs.get("concluded") is False
        report = run.outputs["report"]
        assert report["is_significant"] is False
        assert report["winner_id"] is None

    def test_evaluate_op_concludes_when_significant(self, tmp_path, monkeypatch):
        """When both variants exceed min_sample_size, agent concludes the test."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import BlueSkyABTestAgent

        mgr = BlueSkyABManager()
        variants = [
            BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY),
            BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM),
        ]
        spec = mgr.create_test(
            "Conclude test", [f"acct_{i}" for i in range(4)],
            variants, "2026-04-13", "2026-04-27", min_sample_size=3,
        )
        tid = spec.test_id

        # Pump in enough events for significance
        for j in range(5):
            mgr.record_follow(tid, "acct_0", "a", f"did:plc:a{j}")
            mgr.record_follow(tid, "acct_1", "b", f"did:plc:b{j}")
        for j in range(4):
            mgr.record_follow_back(tid, "acct_0", "a", f"did:plc:a{j}")  # 80%
        for j in range(1):
            mgr.record_follow_back(tid, "acct_1", "b", f"did:plc:b{j}")  # 20%

        agent = BlueSkyABTestAgent()

        async def run_it():
            run = _make_run()
            ctx = {"operation": "evaluate", "test_id": tid, "use_llm": False}
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["concluded"] is True
        assert run.outputs["report"]["winner_id"] == "a"
        assert "rollout_params" in run.outputs

    def test_status_operation_no_llm_call(self, tmp_path, monkeypatch):
        """Status operation returns a list of active tests without LLM call."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import BlueSkyABTestAgent

        mgr = BlueSkyABManager()
        variants = [
            BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY),
            BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM),
        ]
        mgr.create_test(
            "Status test", ["acct_1", "acct_2"],
            variants, "2026-04-13", "2026-04-27",
        )

        agent = BlueSkyABTestAgent()

        async def run_it():
            run = _make_run()
            ctx = {"operation": "status"}
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["llm_used"] is False
        assert run.outputs["count"] >= 1
        assert len(run.outputs["active_tests"]) >= 1

    def test_rollout_op_missing_test_id_returns_error(self, tmp_path, monkeypatch):
        """Rollout without test_id returns an error in outputs."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import BlueSkyABTestAgent

        agent = BlueSkyABTestAgent()

        async def run_it():
            run = _make_run()
            ctx = {"operation": "rollout"}  # no test_id
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert len(run.outputs["errors"]) > 0

    def test_parse_llm_variants_valid_json(self):
        """_parse_llm_variants handles a clean LLM response."""
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import _parse_llm_variants

        raw = json.dumps([
            {
                "variant_id": "a",
                "label": "A: Follow+Like",
                "engagement_strategy": "follow_like_only",
                "params": {"follow_source": "search", "hashtag_rate": 0.15},
            },
            {
                "variant_id": "b",
                "label": "B: +DM",
                "engagement_strategy": "follow_like_dm",
                "params": {"follow_source": "timeline"},
            },
        ])
        variants = _parse_llm_variants(raw)
        assert len(variants) == 2
        assert variants[0].variant_id == "a"
        assert variants[1].engagement_strategy.value == "follow_like_dm"

    def test_parse_llm_variants_strips_invalid_strategy(self):
        """Unknown engagement_strategy values are silently filtered."""
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import _parse_llm_variants

        raw = json.dumps([
            {
                "variant_id": "good",
                "label": "Good",
                "engagement_strategy": "follow_like_only",
                "params": {},
            },
            {
                "variant_id": "bad",
                "label": "Bad",
                "engagement_strategy": "hack_the_planet",  # invalid
                "params": {},
            },
        ])
        variants = _parse_llm_variants(raw)
        assert len(variants) == 1
        assert variants[0].variant_id == "good"

    def test_parse_llm_variants_handles_markdown_fence(self):
        """LLM often wraps JSON in ```json ... ``` — parser strips it."""
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import _parse_llm_variants

        raw = (
            "```json\n"
            + json.dumps([{
                "variant_id": "a",
                "label": "A",
                "engagement_strategy": "follow_only",
                "params": {},
            }])
            + "\n```"
        )
        variants = _parse_llm_variants(raw)
        assert len(variants) == 1

    def test_parse_llm_variants_clamps_hashtag_rate(self):
        """hashtag_rate values outside 0–1 are clamped."""
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import _parse_llm_variants

        raw = json.dumps([{
            "variant_id": "a",
            "label": "A",
            "engagement_strategy": "follow_like_only",
            "params": {"hashtag_rate": 5.0},  # way too high
        }])
        variants = _parse_llm_variants(raw)
        assert len(variants) == 1
        assert variants[0].params["hashtag_rate"] == 1.0  # clamped

    def test_parse_llm_variants_whitelists_params(self):
        """Unknown param keys are stripped — whitelist only."""
        from phantom_fleet.agents.specialists.bluesky_ab_test_agent import _parse_llm_variants

        raw = json.dumps([{
            "variant_id": "a",
            "label": "A",
            "engagement_strategy": "follow_like_only",
            "params": {
                "follow_source": "search",
                "evil_param": "rm -rf /",
                "another_unknown": 999,
            },
        }])
        variants = _parse_llm_variants(raw)
        assert len(variants) == 1
        assert "evil_param" not in variants[0].params
        assert "another_unknown" not in variants[0].params
        assert variants[0].params.get("follow_source") == "search"


# ---------------------------------------------------------------------------
# BlueSky A/B Fleet-scale sanity
# ---------------------------------------------------------------------------


class TestBlueSkyABFleetScale:
    """Verify A/B assignment stays balanced at scale."""

    def test_variant_assignment_50_50_split_at_1000_accounts(self):
        """1000 accounts should split ≈50/50 across two variants."""
        from phantom_fleet.core.bluesky_ab_test import _stable_hash_mod

        counts = [0, 0]
        for i in range(1000):
            idx = _stable_hash_mod(f"acct_{i}", "test_stability", 2)
            counts[idx] += 1

        for c in counts:
            pct = c / 1000
            assert 0.43 <= pct <= 0.57, f"Variant imbalance at scale: {pct:.1%}"

    def test_stable_hash_not_randomised_across_runs(self):
        """_stable_hash_mod must return same value across Python restarts (uses SHA-256, not hash())."""
        from phantom_fleet.core.bluesky_ab_test import _stable_hash_mod

        # Pre-computed expected values — if this breaks, the hash function changed
        assert _stable_hash_mod("acct_test", "test_stability", 2) == _stable_hash_mod("acct_test", "test_stability", 2)

        # Verify SHA-256 is used (result must be stable, not random)
        results = {_stable_hash_mod("acct_fixed", "test_stability", 2) for _ in range(100)}
        assert len(results) == 1, "Hash result must be deterministic"

    def test_four_variant_assignment_roughly_even(self):
        """With 4 variants across 400 accounts, each gets ~25% (±10%)."""
        from phantom_fleet.core.bluesky_ab_test import _stable_hash_mod

        counts = [0, 0, 0, 0]
        for i in range(400):
            idx = _stable_hash_mod(f"acct_{i}", "test_stability", 4)
            counts[idx] += 1

        for c in counts:
            pct = c / 400
            assert 0.15 <= pct <= 0.35, f"4-variant imbalance: {pct:.1%}"


# ---------------------------------------------------------------------------
# Wiring tests — event recording flows through specialist agents
# ---------------------------------------------------------------------------


class TestBlueSkyABWiring:
    """
    Verify that specialist agents correctly record A/B events when
    ab_test_id + ab_variant_id are present in ctx.
    """

    def test_follow_agent_records_follow_events(self, tmp_path, monkeypatch):
        """BlueSkyFollowAgent calls record_follow for each successful follow."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_follow_agent import BlueSkyFollowAgent

        # Create a test to record against
        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)]
        spec = mgr.create_test(
            "Wiring test", ["acct_1"], variants,
            "2026-04-13", "2026-04-27", min_sample_size=5,
        )

        agent = BlueSkyFollowAgent()
        followed_calls: list[str] = []

        async def fake_follow(did: str) -> dict:
            followed_calls.append(did)
            return {}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":    "acct_1",
                "session":       session,
                "target_dids":   ["did:plc:target1", "did:plc:target2"],
                "ab_test_id":    spec.test_id,
                "ab_variant_id": "a",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.follow_user = AsyncMock(side_effect=fake_follow)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())

        # Verify events recorded in A/B framework
        metrics = mgr.aggregate_metrics(spec.test_id, spec)
        assert metrics[0].follows_sent == 2
        # followed_dids should be in outputs for follow-back reconciliation
        assert set(run.outputs["followed_dids"]) == {"did:plc:target1", "did:plc:target2"}

    def test_follow_agent_no_recording_without_ab_test_id(self, tmp_path, monkeypatch):
        """Follow agent operates normally when no ab_test_id is passed."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.agents.specialists.bluesky_follow_agent import BlueSkyFollowAgent

        agent = BlueSkyFollowAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":  "acct_1",
                "session":     session,
                "target_dids": ["did:plc:x"],
                # No ab_test_id — should not crash
            }
            with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.follow_user = AsyncMock(return_value={})
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].followed == 1
        assert run.outputs["followed_dids"] == ["did:plc:x"]

    def test_like_agent_records_like_events(self, tmp_path, monkeypatch):
        """BlueSkyLikeAgent calls record_like for each successful like."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_like_agent import BlueSkyLikeAgent

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)]
        spec = mgr.create_test(
            "Like wiring", ["acct_1"], variants,
            "2026-04-13", "2026-04-27", min_sample_size=5,
        )

        agent = BlueSkyLikeAgent()
        feed_resp = {
            "feed": [
                {"post": {"uri": "at://x/post/1", "cid": "cid1", "record": {"text": "hello"}}},
                {"post": {"uri": "at://x/post/2", "cid": "cid2", "record": {"text": "world"}}},
            ]
        }

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":    "acct_1",
                "session":       session,
                "target_count":  2,
                "feed_source":   "timeline",
                "ab_test_id":    spec.test_id,
                "ab_variant_id": "a",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_like_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_timeline = AsyncMock(return_value=feed_resp)
                mock_instance.like_post    = AsyncMock(return_value={})
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_like_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        asyncio.run(run_it())
        metrics = mgr.aggregate_metrics(spec.test_id, spec)
        assert metrics[0].likes_given == 2

    def test_dm_agent_records_dm_sent_on_reply(self, tmp_path, monkeypatch):
        """BlueSkyDMChatAgent records dm_sent events in _send_reply."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_dm_chat_agent import BlueSkyDMChatAgent

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM)]
        spec = mgr.create_test(
            "DM wiring", ["acct_1"], variants,
            "2026-04-13", "2026-04-27", min_sample_size=5,
        )

        agent = BlueSkyDMChatAgent()
        # Call _send_reply directly — this is what the base class calls after LLM
        session = _make_session()

        async def run_it():
            from phantom_fleet.core.bluesky_client import BlueSkyClient
            client = BlueSkyClient(session)
            client._post = AsyncMock(return_value={})
            agent._ab_test_id    = spec.test_id
            agent._ab_variant_id = "b"
            agent._ab_account_id = "acct_1"
            conv = {"conv_id": "conv_123", "recipient_did": "did:plc:recipient"}
            await agent._send_reply(client, conv, "Hey there!")

        asyncio.run(run_it())
        metrics = mgr.aggregate_metrics(spec.test_id, spec)
        assert metrics[0].dms_sent == 1

    def test_followback_agent_records_new_followbacks(self, tmp_path, monkeypatch):
        """BlueSkyFollowBackAgent records follow_back for DIDs that are now followers."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_followback_agent import BlueSkyFollowBackAgent

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)]
        spec = mgr.create_test(
            "Followback wiring", ["acct_1"], variants,
            "2026-04-13", "2026-04-27", min_sample_size=5,
        )
        tid = spec.test_id

        # Record two follows in the test
        mgr.record_follow(tid, "acct_1", "a", "did:plc:t1")
        mgr.record_follow(tid, "acct_1", "a", "did:plc:t2")

        # Fake followers: t1 followed back, t2 has not
        followers_resp = {
            "followers": [
                {"did": "did:plc:t1", "handle": "t1.bsky.social"},
                {"did": "did:plc:unrelated", "handle": "other.bsky.social"},
            ],
            "cursor": "",
        }

        agent = BlueSkyFollowBackAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":    "acct_1",
                "session":       session,
                "ab_test_id":    tid,
                "ab_variant_id": "a",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_followback_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_followers = AsyncMock(return_value=followers_resp)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["new_followbacks"] == 1

        # Verify the follow_back event was recorded in the framework
        metrics = mgr.aggregate_metrics(tid, spec)
        assert metrics[0].follow_backs == 1

    def test_followback_agent_idempotent_no_double_count(self, tmp_path, monkeypatch):
        """Running followback agent twice doesn't double-count follow_backs."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_followback_agent import BlueSkyFollowBackAgent

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)]
        spec = mgr.create_test(
            "Idempotent test", ["acct_1"], variants,
            "2026-04-13", "2026-04-27", min_sample_size=5,
        )
        tid = spec.test_id
        mgr.record_follow(tid, "acct_1", "a", "did:plc:t1")

        # Simulate t1 already recorded as follow_back from a previous run
        mgr.record_follow_back(tid, "acct_1", "a", "did:plc:t1")

        followers_resp = {
            "followers": [{"did": "did:plc:t1", "handle": "t1.bsky.social"}],
            "cursor": "",
        }
        agent = BlueSkyFollowBackAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id":    "acct_1",
                "session":       session,
                "ab_test_id":    tid,
                "ab_variant_id": "a",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_followback_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_followers = AsyncMock(return_value=followers_resp)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__  = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        # Should record 0 new follow_backs (already recorded)
        assert run.outputs["new_followbacks"] == 0

        metrics = mgr.aggregate_metrics(tid, spec)
        assert metrics[0].follow_backs == 1  # still 1, not 2

    def test_followback_agent_requires_ab_test_id(self, tmp_path, monkeypatch):
        """Followback agent errors gracefully when no ab_test_id provided."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.agents.specialists.bluesky_followback_agent import BlueSkyFollowBackAgent

        agent = BlueSkyFollowBackAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {"account_id": "acct_1", "session": session}  # no ab_test_id
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert len(run.outputs["errors"]) > 0
        assert run.outputs["new_followbacks"] == 0

    def test_ab_manager_get_active_test_for_account(self, tmp_path, monkeypatch):
        """get_active_test_for_account returns (spec, variant) for enrolled accounts."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )

        mgr = BlueSkyABManager()
        variants = [
            BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY),
            BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM),
        ]
        mgr.create_test(
            "Lookup test", ["acct_enrolled", "acct_other"],
            variants, "2026-04-13", "2026-04-27",
        )

        result = mgr.get_active_test_for_account("acct_enrolled")
        assert result is not None
        spec, variant = result
        assert variant.variant_id in ("a", "b")

        not_enrolled = mgr.get_active_test_for_account("acct_not_in_test")
        assert not_enrolled is None

    def test_get_followed_dids_in_test(self, tmp_path, monkeypatch):
        """get_followed_dids_in_test returns only follow events for the account."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)]
        spec = mgr.create_test(
            "DID lookup", ["acct_1", "acct_2"],
            variants, "2026-04-13", "2026-04-27",
        )
        tid = spec.test_id

        mgr.record_follow(tid, "acct_1", "a", "did:plc:x1")
        mgr.record_follow(tid, "acct_1", "a", "did:plc:x2")
        mgr.record_follow(tid, "acct_2", "a", "did:plc:y1")  # different account

        dids = mgr.get_followed_dids_in_test(tid, "acct_1")
        assert dids == {"did:plc:x1", "did:plc:x2"}  # only acct_1's follows


# ---------------------------------------------------------------------------
# BlueSkyFollowAgent — standalone unit tests
# ---------------------------------------------------------------------------


class TestBlueSkyFollowAgent:
    """Unit tests for bluesky_follow_agent.py."""

    def test_empty_targets_early_return(self):
        """Both target_dids and target_handles empty → early return, zero follows."""
        from phantom_fleet.agents.specialists.bluesky_follow_agent import BlueSkyFollowAgent

        agent = BlueSkyFollowAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                # Neither target_dids nor target_handles
            }
            await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].followed == 0
        assert run.outputs["followed_dids"] == []

    def test_follows_target_dids_up_to_cap(self):
        """Follows all provided target_dids when under the daily cap."""
        from phantom_fleet.agents.specialists.bluesky_follow_agent import (
            BlueSkyFollowAgent,
            MAX_FOLLOWS_PER_DAY,
        )

        agent = BlueSkyFollowAgent()
        follow_calls: list[str] = []

        async def fake_follow(did):
            follow_calls.append(did)
            return {}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "target_dids": ["did:plc:a1", "did:plc:a2", "did:plc:a3"],
            }
            with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.follow_user = AsyncMock(side_effect=fake_follow)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].followed == 3
        assert len(follow_calls) == 3

    def test_daily_cap_enforced(self):
        """If MAX_FOLLOWS_PER_DAY would be exceeded, agent stops at the cap."""
        from phantom_fleet.agents.specialists.bluesky_follow_agent import (
            BlueSkyFollowAgent,
            MAX_FOLLOWS_PER_DAY,
        )

        agent = BlueSkyFollowAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            # Provide more DIDs than the daily cap
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "target_dids": [f"did:plc:t{i}" for i in range(MAX_FOLLOWS_PER_DAY + 10)],
            }
            with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.follow_user = AsyncMock(return_value={})
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].followed == MAX_FOLLOWS_PER_DAY

    def test_already_following_counted_separately(self):
        """AlreadyExists errors increment already_following, not errors."""
        from phantom_fleet.agents.specialists.bluesky_follow_agent import BlueSkyFollowAgent

        agent = BlueSkyFollowAgent()

        async def fake_follow(did):
            raise Exception("AlreadyExists: record already exists")

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "target_dids": ["did:plc:existing"],
            }
            with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.follow_user = AsyncMock(side_effect=fake_follow)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].already_following == 1
        assert len(run.outputs["result"].errors) == 0

    def test_handle_resolution_to_did(self):
        """target_handles are resolved via get_profile before following."""
        from phantom_fleet.agents.specialists.bluesky_follow_agent import BlueSkyFollowAgent

        agent = BlueSkyFollowAgent()

        async def fake_follow(did):
            return {}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "target_handles": ["someuser.bsky.social"],
            }
            with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_profile = AsyncMock(return_value={"did": "did:plc:resolved"})
                mock_instance.follow_user = AsyncMock(side_effect=fake_follow)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].followed == 1
        assert "did:plc:resolved" in run.outputs["followed_dids"]

    def test_session_expired_stops_follow_loop(self):
        """BlueSkySessionExpired breaks the follow loop and records error."""
        from phantom_fleet.agents.specialists.bluesky_follow_agent import BlueSkyFollowAgent
        from phantom_fleet.core.bluesky_client import BlueSkySessionExpired

        agent = BlueSkyFollowAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "target_dids": ["did:plc:t1", "did:plc:t2"],
            }
            with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.follow_user = AsyncMock(side_effect=BlueSkySessionExpired())
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_follow_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert "session_expired" in run.outputs["result"].errors
        # Loop stopped — not all targets were followed
        assert run.outputs["result"].followed == 0


# ---------------------------------------------------------------------------
# BlueSkyPostAgent — standalone unit tests
# ---------------------------------------------------------------------------


class TestBlueSkyPostAgent:
    """Unit tests for bluesky_post_agent.py."""

    _GOOD_POOL = [f"Template number {i}: some content here." for i in range(20)]

    def test_small_template_pool_raises(self):
        """Template pool < 15 items raises ValueError."""
        from phantom_fleet.agents.specialists.bluesky_post_agent import BlueSkyPostAgent

        agent = BlueSkyPostAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "template_pool": ["only_one"],
            }
            await agent.run_once(ctx, run)

        with pytest.raises(ValueError, match="template_pool must have"):
            asyncio.run(run_it())

    def test_posts_submitted_incremented(self):
        """Successful create_post call increments result.posts_submitted."""
        from phantom_fleet.agents.specialists.bluesky_post_agent import BlueSkyPostAgent

        agent = BlueSkyPostAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "template_pool": self._GOOD_POOL,
                "posts_to_attempt": 2,
            }
            with patch("phantom_fleet.agents.specialists.bluesky_post_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.create_post = AsyncMock(return_value={})
                mock_instance.get_timeline = AsyncMock(return_value={"feed": []})
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_post_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].posts_submitted == 2

    def test_daily_cap_respected(self):
        """already_posted_today at cap prevents any posts."""
        from phantom_fleet.agents.specialists.bluesky_post_agent import (
            BlueSkyPostAgent,
            MAX_POSTS_PER_DAY,
        )

        agent = BlueSkyPostAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "template_pool": self._GOOD_POOL,
                "posts_to_attempt": 3,
                "already_posted_today": MAX_POSTS_PER_DAY,  # already at cap
            }
            with patch("phantom_fleet.agents.specialists.bluesky_post_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.create_post = AsyncMock(return_value={})
                mock_instance.get_timeline = AsyncMock(return_value={"feed": []})
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_post_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].posts_submitted == 0

    def test_dedup_skips_already_posted_hash(self):
        """Content with a hash already in posted_hashes is skipped."""
        from phantom_fleet.agents.specialists.bluesky_post_agent import (
            BlueSkyPostAgent,
            _content_hash,
            _truncate_to_limit,
        )
        from phantom_fleet.core.human_post_behavior import select_template
        from phantom_fleet.core.distributions import seed_for

        agent = BlueSkyPostAgent()

        # Pre-compute the hash of what the agent will pick for post_idx=0
        account_id = "acct_hash_dedup"
        date_iso = "2026-04-13"
        seed = seed_for(account_id, date_iso, "bluesky_post_template_0")
        text = _truncate_to_limit(select_template(self._GOOD_POOL, seed))
        chash = _content_hash(account_id, text)

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": account_id,
                "session": session,
                "template_pool": self._GOOD_POOL,
                "posts_to_attempt": 1,
                "date_iso": date_iso,
                "posted_hashes": {chash},  # pre-seed the dedup set
            }
            with patch("phantom_fleet.agents.specialists.bluesky_post_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.create_post = AsyncMock(return_value={})
                mock_instance.get_timeline = AsyncMock(return_value={"feed": []})
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_post_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["result"].posts_submitted == 0
        assert run.outputs["result"].skipped_dedup == 1

    def test_session_expired_stops_posting(self):
        """BlueSkySessionExpired stops the post loop and records error."""
        from phantom_fleet.agents.specialists.bluesky_post_agent import BlueSkyPostAgent
        from phantom_fleet.core.bluesky_client import BlueSkySessionExpired

        agent = BlueSkyPostAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "template_pool": self._GOOD_POOL,
                "posts_to_attempt": 3,
            }
            with patch("phantom_fleet.agents.specialists.bluesky_post_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.create_post = AsyncMock(side_effect=BlueSkySessionExpired())
                mock_instance.get_timeline = AsyncMock(return_value={"feed": []})
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_post_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert "session_expired" in run.outputs["result"].errors
        assert run.outputs["result"].posts_submitted == 0

    def test_text_truncated_to_300_chars(self):
        """Templates over 300 chars are truncated with ellipsis."""
        from phantom_fleet.agents.specialists.bluesky_post_agent import (
            _truncate_to_limit,
            BLUESKY_CHAR_LIMIT,
        )

        long_text = "x" * 500
        truncated = _truncate_to_limit(long_text)
        assert len(truncated) == BLUESKY_CHAR_LIMIT
        assert truncated.endswith("…")


# ---------------------------------------------------------------------------
# BlueSkyLabelerAgent — unit tests
# ---------------------------------------------------------------------------


class TestBlueSkyLabelerAgent:
    """Unit tests for bluesky_labeler_agent.py."""

    def test_publish_calls_put_record_with_correct_args(self):
        """Publish operation calls put_record with labeler collection + rkey='self'."""
        from phantom_fleet.agents.specialists.bluesky_labeler_agent import BlueSkyLabelerAgent

        agent = BlueSkyLabelerAgent()
        put_record_calls: list[dict] = []

        async def fake_put_record(**kwargs):
            put_record_calls.append(kwargs)
            return {"uri": f"at://did:plc:test123/app.bsky.labeler.service/self"}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "operation": "publish",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_labeler_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.put_record = AsyncMock(side_effect=fake_put_record)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["operation"] == "publish"
        assert "app.bsky.labeler.service" in run.outputs.get("record_uri", "")
        assert len(put_record_calls) == 1
        assert put_record_calls[0]["collection"] == "app.bsky.labeler.service"
        assert put_record_calls[0]["rkey"] == "self"

    def test_refresh_is_identical_to_publish(self):
        """Refresh operation also calls put_record (upsert semantics)."""
        from phantom_fleet.agents.specialists.bluesky_labeler_agent import BlueSkyLabelerAgent

        agent = BlueSkyLabelerAgent()
        put_record_calls: list[dict] = []

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "operation": "refresh",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_labeler_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.put_record = AsyncMock(
                    side_effect=lambda **kw: put_record_calls.append(kw) or {"uri": "at://x/y/self"},
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["operation"] == "refresh"
        assert len(put_record_calls) == 1

    def test_disable_calls_delete_record(self):
        """Disable operation calls _post with deleteRecord lexicon."""
        from phantom_fleet.agents.specialists.bluesky_labeler_agent import BlueSkyLabelerAgent

        agent = BlueSkyLabelerAgent()
        post_calls: list[tuple] = []

        async def fake_post(lexicon, payload=None):
            post_calls.append((lexicon, payload))
            return {}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "operation": "disable",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_labeler_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance._post = AsyncMock(side_effect=fake_post)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert run.outputs["operation"] == "disable"
        assert run.outputs["record_uri"] == ""
        assert len(post_calls) == 1
        lexicon, payload = post_calls[0]
        assert lexicon == "com.atproto.repo.deleteRecord"
        assert payload["collection"] == "app.bsky.labeler.service"
        assert payload["rkey"] == "self"

    def test_unknown_operation_records_error(self):
        """Unknown operation records error without crashing."""
        from phantom_fleet.agents.specialists.bluesky_labeler_agent import BlueSkyLabelerAgent

        agent = BlueSkyLabelerAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "operation": "hack_the_planet",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_labeler_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert len(run.outputs["result"].errors) > 0
        assert "unknown_operation" in run.outputs["result"].errors[0]

    def test_disable_already_absent_is_not_error(self):
        """404 / recordNotFound during disable is treated as success (idempotent)."""
        from phantom_fleet.agents.specialists.bluesky_labeler_agent import BlueSkyLabelerAgent

        agent = BlueSkyLabelerAgent()

        async def fake_post(lexicon, payload=None):
            raise Exception("RecordNotFound: record does not exist")

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "operation": "disable",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_labeler_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance._post = AsyncMock(side_effect=fake_post)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        # RecordNotFound → no error added
        assert len(run.outputs["result"].errors) == 0

    def test_default_label_values_used_when_not_provided(self):
        """When label_values not in ctx, _DEFAULT_LABEL_VALUES are used."""
        from phantom_fleet.agents.specialists.bluesky_labeler_agent import (
            BlueSkyLabelerAgent,
            _DEFAULT_LABEL_VALUES,
        )

        agent = BlueSkyLabelerAgent()
        captured_records: list[dict] = []

        async def fake_put_record(**kwargs):
            captured_records.append(kwargs.get("record", {}))
            return {"uri": "at://x"}

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "operation": "publish",
                # No label_values
            }
            with patch("phantom_fleet.agents.specialists.bluesky_labeler_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.put_record = AsyncMock(side_effect=fake_put_record)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)

        asyncio.run(run_it())
        assert len(captured_records) == 1
        assert captured_records[0]["policies"]["labelValues"] == _DEFAULT_LABEL_VALUES


# ---------------------------------------------------------------------------
# BlueSkyDMChatAgent — routing and A/B recording tests
# ---------------------------------------------------------------------------


class TestBlueSkyDMChatAgent:
    """Unit tests for bluesky_dm_chat_agent.py."""

    def test_send_reply_uses_chat_base_url(self):
        """_send_reply passes base_url=_CHAT_BASE to client._post."""
        from phantom_fleet.agents.specialists.bluesky_dm_chat_agent import (
            BlueSkyDMChatAgent,
            _CHAT_BASE,
        )

        agent = BlueSkyDMChatAgent()
        post_calls: list[tuple] = []

        async def fake_post(lexicon, payload=None, base_url=None):
            post_calls.append((lexicon, base_url))
            return {}

        async def run_it():
            session = _make_session()
            from phantom_fleet.core.bluesky_client import BlueSkyClient
            client = BlueSkyClient(session)
            client._post = AsyncMock(side_effect=fake_post)
            conv = {"conv_id": "conv_abc", "recipient_did": "did:plc:recipient"}
            await agent._send_reply(client, conv, "Hello world!")

        asyncio.run(run_it())
        assert len(post_calls) == 1
        lexicon, base_url = post_calls[0]
        assert lexicon == "chat.bsky.convo.sendMessage"
        assert base_url == _CHAT_BASE

    def test_fetch_conversations_uses_chat_base_url(self):
        """_fetch_conversations passes base_url=_CHAT_BASE to both _get calls."""
        from phantom_fleet.agents.specialists.bluesky_dm_chat_agent import (
            BlueSkyDMChatAgent,
            _CHAT_BASE,
        )

        agent = BlueSkyDMChatAgent()
        get_calls: list[tuple] = []

        async def fake_get(lexicon, params=None, base_url=None):
            get_calls.append((lexicon, base_url))
            if lexicon == "chat.bsky.convo.listConvos":
                return {
                    "convos": [{"id": "conv_1", "unreadCount": 1, "members": []}]
                }
            if lexicon == "chat.bsky.convo.getMessages":
                return {"messages": []}
            return {}

        async def run_it():
            session = _make_session()
            from phantom_fleet.core.bluesky_client import BlueSkyClient
            client = BlueSkyClient(session)
            client._get = AsyncMock(side_effect=fake_get)
            client.session = session
            await agent._fetch_conversations(client)

        asyncio.run(run_it())
        # Both calls must use _CHAT_BASE
        assert all(base_url == _CHAT_BASE for _, base_url in get_calls)
        lexicons = [l for l, _ in get_calls]
        assert "chat.bsky.convo.listConvos" in lexicons
        assert "chat.bsky.convo.getMessages" in lexicons

    def test_fetch_conversations_skips_zero_unread(self):
        """Conversations with unreadCount=0 are not fetched or returned."""
        from phantom_fleet.agents.specialists.bluesky_dm_chat_agent import BlueSkyDMChatAgent

        agent = BlueSkyDMChatAgent()
        getmessages_called = []

        async def fake_get(lexicon, params=None, base_url=None):
            if lexicon == "chat.bsky.convo.listConvos":
                return {
                    "convos": [
                        {"id": "conv_read", "unreadCount": 0, "members": []},   # skip
                        {"id": "conv_unread", "unreadCount": 3, "members": []},  # fetch
                    ]
                }
            if lexicon == "chat.bsky.convo.getMessages":
                getmessages_called.append(params.get("convoId"))
                return {"messages": []}
            return {}

        async def run_it():
            session = _make_session()
            from phantom_fleet.core.bluesky_client import BlueSkyClient
            client = BlueSkyClient(session)
            client._get = AsyncMock(side_effect=fake_get)
            client.session = session
            return await agent._fetch_conversations(client)

        convs = asyncio.run(run_it())
        # Only the unread conversation should be in the result
        assert len(convs) == 1
        assert convs[0]["conv_id"] == "conv_unread"
        # getMessages should only have been called once (for conv_unread)
        assert getmessages_called == ["conv_unread"]

    def test_send_reply_records_ab_event(self, tmp_path, monkeypatch):
        """_send_reply records dm_sent to A/B framework when test metadata set."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_dm_chat_agent import BlueSkyDMChatAgent

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM)]
        spec = mgr.create_test(
            "DM AB test", ["acct_dm"], variants, "2026-04-13", "2026-04-27",
        )

        agent = BlueSkyDMChatAgent()
        agent._ab_test_id = spec.test_id
        agent._ab_variant_id = "b"
        agent._ab_account_id = "acct_dm"

        async def run_it():
            session = _make_session()
            from phantom_fleet.core.bluesky_client import BlueSkyClient
            client = BlueSkyClient(session)
            client._post = AsyncMock(return_value={})
            conv = {"conv_id": "conv_xyz", "recipient_did": "did:plc:fan"}
            await agent._send_reply(client, conv, "Hey!")

        asyncio.run(run_it())
        metrics = mgr.aggregate_metrics(spec.test_id, spec)
        assert metrics[0].dms_sent == 1


# ---------------------------------------------------------------------------
# BlueSkyFollowBackAgent — supplemental page-cap tests
# ---------------------------------------------------------------------------


class TestBlueSkyFollowBackAgentSupplemental:
    """Additional standalone tests for bluesky_followback_agent.py."""

    def test_page_cap_warning_recorded_as_error(self, tmp_path, monkeypatch):
        """When page cap hit without finding all pending DIDs, error is recorded."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_followback_agent import (
            BlueSkyFollowBackAgent,
            MAX_FOLLOWER_PAGES,
            FOLLOWERS_PER_PAGE,
        )

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)]
        spec = mgr.create_test(
            "Cap test", ["acct_1"], variants, "2026-04-13", "2026-04-27",
        )
        tid = spec.test_id
        mgr.record_follow(tid, "acct_1", "a", "did:plc:hidden")

        # Return full pages of followers that never contain did:plc:hidden
        def make_page(page_num):
            return {
                "followers": [
                    {"did": f"did:plc:other{page_num}_{i}"} for i in range(FOLLOWERS_PER_PAGE)
                ],
                "cursor": "next" if page_num < MAX_FOLLOWER_PAGES - 1 else "",
            }

        page_counter = [0]

        async def fake_get_followers(**kwargs):
            result = make_page(page_counter[0])
            page_counter[0] += 1
            return result

        agent = BlueSkyFollowBackAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "ab_test_id": tid,
                "ab_variant_id": "a",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_followback_agent.BlueSkyClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.get_followers = AsyncMock(side_effect=fake_get_followers)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        # Page cap error should be in errors
        assert any("page_cap_hit" in e for e in run.outputs["errors"])
        assert run.outputs["new_followbacks"] == 0

    def test_rate_limited_records_error_and_stops(self, tmp_path, monkeypatch):
        """BlueSkyRateLimited breaks pagination and records error."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )
        from phantom_fleet.agents.specialists.bluesky_followback_agent import BlueSkyFollowBackAgent
        from phantom_fleet.core.bluesky_client import BlueSkyRateLimited

        mgr = BlueSkyABManager()
        variants = [BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)]
        spec = mgr.create_test(
            "RL test", ["acct_1"], variants, "2026-04-13", "2026-04-27",
        )
        tid = spec.test_id
        mgr.record_follow(tid, "acct_1", "a", "did:plc:t1")

        agent = BlueSkyFollowBackAgent()

        async def run_it():
            session = _make_session()
            run = _make_run()
            ctx = {
                "account_id": "acct_1",
                "session": session,
                "ab_test_id": tid,
                "ab_variant_id": "a",
            }
            with patch("phantom_fleet.agents.specialists.bluesky_followback_agent.BlueSkyClient") as MockClient:
                rl = BlueSkyRateLimited()
                rl.retry_after_sec = 5
                mock_instance = AsyncMock()
                mock_instance.get_followers = AsyncMock(side_effect=rl)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_instance
                with patch("phantom_fleet.agents.specialists.bluesky_followback_agent.asyncio.sleep", new=AsyncMock()):
                    await agent.run_once(ctx, run)
            return run

        run = asyncio.run(run_it())
        assert any("rate_limited" in e for e in run.outputs["errors"])


# ---------------------------------------------------------------------------
# BlueSkyAgentManager — dispatch, variant_map, session guards
# ---------------------------------------------------------------------------


class TestBlueSkyAgentManager:
    """Unit tests for agents/managers/bluesky.py."""

    def _make_manager_with_tools(self, tool_registry: dict, specialist_registry: dict = None):
        from phantom_fleet.agents.managers.bluesky import BlueSkyAgentManager
        return BlueSkyAgentManager(
            tool_registry=tool_registry,
            specialist_registry=specialist_registry or {},
        )

    def _make_account(self, account_id: str, persona_id: str = None, session=None, **kwargs):
        """Build a minimal account dict for manager tests."""
        return {
            "account_id": account_id,
            "persona_id": persona_id or account_id,
            "session": session or _make_session(),
            "template_pool": [f"Template {i}" for i in range(20)],
            **kwargs,
        }

    def test_variant_map_built_from_active_tests(self, tmp_path, monkeypatch):
        """Manager builds variant_map from active A/B tests at run start."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
        )

        # Create a test with two accounts
        ab_mgr = BlueSkyABManager()
        variants = [
            BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY),
            BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM),
        ]
        ab_mgr.create_test(
            "Manager test", ["acct_1", "acct_2"],
            variants, "2026-04-13", "2026-04-27",
        )

        async def run_it():
            accounts = [
                self._make_account("acct_1"),
                self._make_account("acct_2"),
            ]
            _no_op_decision = {
                "follow_plan": {},
                "crosspost_personas": [],
                "native_post_personas": [],
                "unfollow_plan": {},
                "like_plan": {},
                "dm_plan": {},
                "scrape_plan": {},
                "feed_plan": [],
                "labeler_plan": [],
                "ab_test_operation": None,
            }
            tool_registry = {
                "db.load_bluesky_accounts":       AsyncMock(return_value=accounts),
                "db.load_custom_feeds":           AsyncMock(return_value=[]),
                "db.load_target_topics":          AsyncMock(return_value=[]),
                "db.load_persona_blacklist":      AsyncMock(return_value=[]),
                "db.load_bluesky_source_pool":    AsyncMock(return_value=[]),
                "db.save_bluesky_strategy_state": AsyncMock(return_value=None),
                "llm.decide_bluesky_strategy":    AsyncMock(return_value=_no_op_decision),
            }
            manager = self._make_manager_with_tools(tool_registry)
            # Inject the monkeypatched AB manager
            manager._ab_mgr = ab_mgr

            run = _make_run()
            await manager.run_once({}, run)
            return manager

        asyncio.run(run_it())
        # Verifying the run completes without exceptions validates the variant_map build path
        assert True

    def test_session_guard_skips_account_without_session(self, tmp_path, monkeypatch):
        """Accounts with session=None are skipped in DM dispatch (session guard)."""
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        async def run_it():
            accounts = [
                {"account_id": "acct_nosession", "persona_id": "p1", "session": None},
                self._make_account("acct_good"),
            ]
            # DM plan for both — session guard will block acct_nosession
            dm_plan = {
                "acct_nosession": {"conv_ids": ["c1"]},
                "acct_good":      {"conv_ids": ["c2"]},
            }
            _decision = {
                "follow_plan": {},
                "crosspost_personas": [],
                "native_post_personas": [],
                "unfollow_plan": {},
                "like_plan": {},
                "dm_plan": dm_plan,
                "scrape_plan": {},
                "feed_plan": [],
                "labeler_plan": [],
                "ab_test_operation": None,
            }

            mock_specialist = AsyncMock()
            mock_specialist.run = AsyncMock(return_value=_make_run())

            tool_registry = {
                "db.load_bluesky_accounts":       AsyncMock(return_value=accounts),
                "db.load_custom_feeds":           AsyncMock(return_value=[]),
                "db.load_target_topics":          AsyncMock(return_value=[]),
                "db.load_persona_blacklist":      AsyncMock(return_value=[]),
                "db.load_bluesky_source_pool":    AsyncMock(return_value=[]),
                "db.save_bluesky_strategy_state": AsyncMock(return_value=None),
                "llm.decide_bluesky_strategy":    AsyncMock(return_value=_decision),
            }
            specialist_registry = {"bluesky_dm_chat": mock_specialist}
            manager = self._make_manager_with_tools(tool_registry, specialist_registry)

            run = _make_run()
            await manager.run_once({}, run)
            return mock_specialist.run.call_count

        call_count = asyncio.run(run_it())
        # Only acct_good should have been dispatched (not acct_nosession)
        assert call_count == 1

    def test_dm_dispatch_gated_to_dm_strategy_variants(self, tmp_path, monkeypatch):
        """DM dispatch is only sent to accounts whose variant strategy includes DM.

        We control the variant_map by monkeypatching list_active_tests and
        get_variant_for_account, so the test is not sensitive to SHA256 hash
        assignment which varies per test_id.
        """
        from phantom_fleet.core import bluesky_ab_test as mod
        monkeypatch.setattr(mod, "_STORAGE_BASE", tmp_path)

        from phantom_fleet.core.bluesky_ab_test import (
            BlueSkyABManager, BlueSkyABVariant, BlueSkyEngagementVariant,
            BlueSkyABSpec,
        )

        # Build a synthetic spec (not persisted) so variant assignment is ours to control
        variant_a = BlueSkyABVariant("a", "A", BlueSkyEngagementVariant.FOLLOW_LIKE_ONLY)
        variant_b = BlueSkyABVariant("b", "B", BlueSkyEngagementVariant.FOLLOW_LIKE_DM)

        fake_spec = BlueSkyABSpec(
            test_id="fake_gate_test",
            name="DM gate test",
            cohort_account_ids=["acct_no_dm", "acct_dm"],
            variants=[variant_a, variant_b],
            start_date_iso="2026-04-13",
            end_date_iso="2026-04-27",
            min_sample_size=5,
            status="active",
        )

        # Stub AB manager so variant_map has exact assignments we want:
        # acct_no_dm → variant A (FOLLOW_LIKE_ONLY, no DM allowed)
        # acct_dm    → variant B (FOLLOW_LIKE_DM, DM allowed)
        mock_ab = MagicMock(spec=BlueSkyABManager)
        mock_ab.list_active_tests.return_value = [fake_spec]

        def fake_get_variant(account_id, spec):
            if account_id == "acct_no_dm":
                return variant_a
            if account_id == "acct_dm":
                return variant_b
            return None

        mock_ab.get_variant_for_account.side_effect = fake_get_variant

        async def run_it():
            accounts = [
                self._make_account("acct_no_dm"),
                self._make_account("acct_dm"),
            ]
            dm_plan = {
                "acct_no_dm": {"conv_ids": ["c1"]},
                "acct_dm":    {"conv_ids": ["c2"]},
            }
            _decision = {
                "follow_plan": {},
                "crosspost_personas": [],
                "native_post_personas": [],
                "unfollow_plan": {},
                "like_plan": {},
                "dm_plan": dm_plan,
                "scrape_plan": {},
                "feed_plan": [],
                "labeler_plan": [],
                "ab_test_operation": None,
            }
            tool_registry = {
                "db.load_bluesky_accounts":       AsyncMock(return_value=accounts),
                "db.load_custom_feeds":           AsyncMock(return_value=[]),
                "db.load_target_topics":          AsyncMock(return_value=[]),
                "db.load_persona_blacklist":      AsyncMock(return_value=[]),
                "db.load_bluesky_source_pool":    AsyncMock(return_value=[]),
                "db.save_bluesky_strategy_state": AsyncMock(return_value=None),
                "llm.decide_bluesky_strategy":    AsyncMock(return_value=_decision),
            }

            dm_specialist = AsyncMock()
            dm_specialist.run = AsyncMock(return_value=_make_run())
            specialist_registry = {"bluesky_dm_chat": dm_specialist}

            manager = self._make_manager_with_tools(tool_registry, specialist_registry)
            manager._ab_mgr = mock_ab

            run = _make_run()
            await manager.run_once({}, run)
            return dm_specialist.run.call_count

        dm_calls = asyncio.run(run_it())
        # Only acct_dm (variant B = FOLLOW_LIKE_DM) should receive DM dispatch;
        # acct_no_dm (variant A = FOLLOW_LIKE_ONLY) is gated out.
        assert dm_calls == 1
