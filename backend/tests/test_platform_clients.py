"""
Tests for the five platform API clients.

All HTTP calls are mocked — no real API requests are made.
Pattern: patch._post / ._get / ._graphql_post etc. with AsyncMock,
matching the same approach as test_instagram_client.py.

Coverage goal: 20+ tests across Telegram, Reddit, Discord, BlueSky, X.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from phantom_fleet.core.hybrid_runner import PlatformHeaders

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_headers(platform: str, **extra) -> PlatformHeaders:
    base_extra = {
        "username":       f"{platform}_user",
        "user_id":        "100000001",
        "refresh_token":  "refresh_tok_abc",
        "did":            "did:plc:testdid123",
        "handle":         f"{platform}.bsky.social",
        "auth_key":       "a" * 64,
        "dc_id":          "2",
        "phone":          "+12025551234",
        "auth_token":     "auth_tok_abc",
        "ct0":            "csrf_tok_xyz",
        "client_uuid":    "client-uuid-test-1234",
        "super_properties": "eyJ0ZXN0IjoidmFsdWUifQ==",  # base64('{"test":"value"}')
        "refresh_jwt":    "refresh_jwt_abc",
        "reddit_device_id": "reddit-dev-id-abc",
        "loid":           "loid_abc123",
    }
    base_extra.update(extra)
    return PlatformHeaders(
        platform=platform,
        session_token="session_tok_test",
        device_id=f"{platform}-device-abc123",
        user_agent=f"Phantom/1.0 {platform.capitalize()} Android",
        app_version="10.0.0",
        android_id="abc123def456abc1",
        advertising_id="gaid-1234-5678",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra=base_extra,
    )


def mock_resp(json_data: dict | list, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    resp.headers = {}
    return resp


# ===========================================================================
# TELEGRAM
# ===========================================================================

from phantom_fleet.core.telegram_client import (
    TelegramClient, TelegramSession,
    TelegramSessionExpired, TelegramFloodWait, TelegramAPIError,
)


def make_tg_session() -> TelegramSession:
    h = make_headers("telegram")
    return TelegramSession(
        account_id="acc_tg_001",
        auth_key="a" * 64,
        dc_id=2,
        user_id="100000001",
        username="tg_test_user",
        phone="+12025551234",
        token="123456:ABC-DEF-bot-token",
        headers=h,
    )


class TestTelegramClient:

    def test_build_client_sets_user_agent(self):
        client = TelegramClient(make_tg_session())
        http_client = client._build_client()
        assert "Phantom" in dict(http_client.headers).get("user-agent", "")

    def test_base_url_includes_token(self):
        client = TelegramClient(make_tg_session())
        assert "123456:ABC-DEF-bot-token" in client._base_url

    async def test_send_dm_calls_sendMessage(self):
        client = TelegramClient(make_tg_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={"message_id": 42})
        ) as mock_post:
            async with client:
                await client.send_dm("999001", "Hello from phantom!")
            method, payload = mock_post.call_args[0]
            assert method == "sendMessage"
            assert payload["chat_id"] == "999001"
            assert "Hello from phantom!" in payload["text"]

    async def test_send_channel_post_calls_sendMessage(self):
        client = TelegramClient(make_tg_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={"message_id": 77})
        ) as mock_post:
            async with client:
                await client.send_channel_post("@mychannel", "Promo text")
            method, payload = mock_post.call_args[0]
            assert method == "sendMessage"
            assert payload["chat_id"] == "@mychannel"

    async def test_forward_message_calls_forwardMessage(self):
        client = TelegramClient(make_tg_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={"message_id": 100})
        ) as mock_post:
            async with client:
                await client.forward_message("@source", "@dest", 55)
            method, payload = mock_post.call_args[0]
            assert method == "forwardMessage"
            assert payload["message_id"] == 55
            assert payload["from_chat_id"] == "@source"

    async def test_join_group_calls_joinChat(self):
        client = TelegramClient(make_tg_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={})
        ) as mock_post:
            async with client:
                await client.join_group("https://t.me/+testInvite")
            method, _ = mock_post.call_args[0]
            assert method == "joinChat"

    async def test_flood_wait_raised_on_429_body(self):
        client = TelegramClient(make_tg_session())
        flood_body = {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests",
            "parameters": {"retry_after": 30},
        }
        resp = mock_resp(flood_body, status_code=200)
        # Patch the raw httpx client to return this response
        async with client:
            with patch.object(client._client, "post", new=AsyncMock(return_value=resp)):
                with pytest.raises(TelegramFloodWait) as exc_info:
                    await client.send_dm("111", "test")
                assert exc_info.value.retry_after_sec == 30

    async def test_session_expired_raised_on_401(self):
        client = TelegramClient(make_tg_session())
        resp = mock_resp({}, status_code=401)
        async with client:
            with patch.object(client._client, "post", new=AsyncMock(return_value=resp)):
                with pytest.raises(TelegramSessionExpired):
                    await client.send_dm("111", "test")

    async def test_ping_session_true_when_valid(self):
        client = TelegramClient(make_tg_session())
        with patch.object(
            client, "_get", new=AsyncMock(return_value={"id": 123456, "is_bot": True})
        ):
            async with client:
                assert await client.ping_session() is True

    async def test_ping_session_false_on_expiry(self):
        client = TelegramClient(make_tg_session())
        with patch.object(
            client, "_get", new=AsyncMock(side_effect=TelegramSessionExpired("expired"))
        ):
            async with client:
                assert await client.ping_session() is False


# ===========================================================================
# REDDIT
# ===========================================================================

from phantom_fleet.core.reddit_client import (
    RedditClient, RedditSession,
    RedditSessionExpired, RedditRateLimited, RedditForbidden,
)


def make_reddit_session() -> RedditSession:
    h = make_headers("reddit")
    return RedditSession(
        account_id="acc_reddit_001",
        access_token="bearer_tok_abc",
        refresh_token="refresh_tok_abc",
        user_id="t2_abc123",
        username="phantom_redditor",
        headers=h,
    )


class TestRedditClient:

    def test_build_client_user_agent_format(self):
        # Phone-backed session: uses the UA extracted from the installed app
        client = RedditClient(make_reddit_session())
        http_client = client._build_client()
        ua = dict(http_client.headers).get("user-agent", "")
        assert ua == "Phantom/1.0 Reddit Android"

    def test_build_client_user_agent_fallback_format(self):
        # No phone UA: falls back to the script-style Reddit UA
        session = make_reddit_session()
        session.headers.user_agent = ""
        client = RedditClient(session)
        http_client = client._build_client()
        ua = dict(http_client.headers).get("user-agent", "")
        assert ua == "phantom_fleet:v1.0 (by /u/phantom_redditor)"

    def test_build_client_authorization_header(self):
        client = RedditClient(make_reddit_session())
        http_client = client._build_client()
        auth = dict(http_client.headers).get("authorization", "")
        assert auth == "Bearer bearer_tok_abc"

    async def test_upvote_posts_to_vote_endpoint(self):
        client = RedditClient(make_reddit_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={})
        ) as mock_post:
            async with client:
                await client.upvote("t3_abc123")
            endpoint, payload = mock_post.call_args[0]
            assert endpoint == "api/vote"
            assert payload["id"] == "t3_abc123"
            assert payload["dir"] == "1"

    async def test_comment_calls_api_comment(self):
        client = RedditClient(make_reddit_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={"json": {"data": {}}})
        ) as mock_post:
            async with client:
                await client.comment("t3_post001", "Nice post!")
            endpoint, payload = mock_post.call_args[0]
            assert endpoint == "api/comment"
            assert payload["text"] == "Nice post!"
            assert payload["thing_id"] == "t3_post001"

    async def test_submit_post_self_type(self):
        client = RedditClient(make_reddit_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={"json": {"data": {}}})
        ) as mock_post:
            async with client:
                await client.submit_post(
                    subreddit="test",
                    title="My post",
                    text="Content here",
                )
            endpoint, payload = mock_post.call_args[0]
            assert endpoint == "api/submit"
            assert payload["sr"] == "test"
            assert payload["kind"] == "self"
            assert payload["text"] == "Content here"

    async def test_get_subreddit_posts_calls_hot(self):
        client = RedditClient(make_reddit_session())
        listing = {"data": {"children": [], "after": None}}
        with patch.object(
            client, "_get", new=AsyncMock(return_value=listing)
        ) as mock_get:
            async with client:
                await client.get_subreddit_posts("funny", limit=10)
            endpoint, = mock_get.call_args[0]
            assert "r/funny/hot" in endpoint

    async def test_send_pm_calls_compose(self):
        client = RedditClient(make_reddit_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={})
        ) as mock_post:
            async with client:
                await client.send_pm("target_user", "Hello", "Hi there!")
            endpoint, payload = mock_post.call_args[0]
            assert endpoint == "api/compose"
            assert payload["to"] == "target_user"
            assert payload["subject"] == "Hello"

    async def test_session_expired_on_401(self):
        client = RedditClient(make_reddit_session())
        with patch.object(
            client, "_get", new=AsyncMock(side_effect=RedditSessionExpired("expired"))
        ):
            async with client:
                with pytest.raises(RedditSessionExpired):
                    await client.get_me()

    async def test_rate_limited_on_429(self):
        client = RedditClient(make_reddit_session())
        with patch.object(
            client, "_get", new=AsyncMock(side_effect=RedditRateLimited(retry_after_sec=45))
        ):
            async with client:
                with pytest.raises(RedditRateLimited) as exc_info:
                    await client.get_me()
                assert exc_info.value.retry_after_sec == 45

    async def test_ping_session_true_when_valid(self):
        client = RedditClient(make_reddit_session())
        with patch.object(
            client, "_get", new=AsyncMock(return_value={"name": "phantom_redditor"})
        ):
            async with client:
                assert await client.ping_session() is True


# ===========================================================================
# DISCORD
# ===========================================================================

from phantom_fleet.core.discord_client import (
    DiscordClient, DiscordSession,
    DiscordSessionExpired, DiscordRateLimited,
)


def make_discord_session() -> DiscordSession:
    h = make_headers("discord")
    return DiscordSession(
        account_id="acc_discord_001",
        token="MTE0NTYwMDAx.Ga1234.test_discord_token",
        user_id="114500000000001",
        username="phantom_discord",
        discriminator="0",
        headers=h,
    )


class TestDiscordClient:

    def test_build_client_authorization_no_bot_prefix(self):
        client = DiscordClient(make_discord_session())
        http_client = client._build_client()
        auth = dict(http_client.headers).get("authorization", "")
        # User token — must NOT start with "Bot "
        assert not auth.startswith("Bot ")
        assert "MTE0" in auth

    def test_build_client_sets_super_properties(self):
        client = DiscordClient(make_discord_session())
        http_client = client._build_client()
        sp = dict(http_client.headers).get("x-super-properties", "")
        assert sp == "eyJ0ZXN0IjoidmFsdWUifQ=="

    async def test_send_message_calls_channels_endpoint(self):
        client = DiscordClient(make_discord_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={"id": "msg001"})
        ) as mock_post:
            async with client:
                await client.send_message("channel_abc", "Hello Discord!")
            endpoint, payload = mock_post.call_args[0]
            assert "channels/channel_abc/messages" in endpoint
            assert payload["content"] == "Hello Discord!"

    async def test_join_server_strips_url_prefix(self):
        client = DiscordClient(make_discord_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={})
        ) as mock_post:
            async with client:
                await client.join_server("https://discord.gg/abcd1234")
            endpoint, _ = mock_post.call_args[0]
            assert "invites/abcd1234" in endpoint

    async def test_send_dm_opens_channel_then_sends(self):
        client = DiscordClient(make_discord_session())
        channel_resp = {"id": "dm_channel_001"}
        message_resp = {"id": "msg_dm_001"}
        call_results = [channel_resp, message_resp]
        with patch.object(
            client, "_post", new=AsyncMock(side_effect=call_results)
        ) as mock_post:
            async with client:
                await client.send_dm("target_user_id", "Hey!")
            assert mock_post.call_count == 2
            # First call: create DM channel
            first_endpoint, first_payload = mock_post.call_args_list[0][0]
            assert "users/@me/channels" in first_endpoint
            assert first_payload["recipient_id"] == "target_user_id"

    async def test_react_to_message_calls_put(self):
        client = DiscordClient(make_discord_session())
        with patch.object(
            client, "_put", new=AsyncMock(return_value={})
        ) as mock_put:
            async with client:
                await client.react_to_message("ch001", "msg001", "%F0%9F%91%8D")
            endpoint = mock_put.call_args[0][0]
            assert "reactions/%F0%9F%91%8D/@me" in endpoint

    async def test_session_expired_raised_on_401(self):
        client = DiscordClient(make_discord_session())
        with patch.object(
            client, "_get", new=AsyncMock(side_effect=DiscordSessionExpired("expired"))
        ):
            async with client:
                with pytest.raises(DiscordSessionExpired):
                    await client.get_me()

    async def test_rate_limited_raised(self):
        client = DiscordClient(make_discord_session())
        with patch.object(
            client, "_post", new=AsyncMock(
                side_effect=DiscordRateLimited(retry_after_sec=2)
            )
        ):
            async with client:
                with pytest.raises(DiscordRateLimited) as exc_info:
                    await client.send_message("ch", "x")
                assert exc_info.value.retry_after_sec == 2

    async def test_ping_session_true_when_valid(self):
        client = DiscordClient(make_discord_session())
        with patch.object(
            client, "_get", new=AsyncMock(return_value={"id": "114500000000001"})
        ):
            async with client:
                assert await client.ping_session() is True


# ===========================================================================
# BLUESKY
# ===========================================================================

from phantom_fleet.core.bluesky_client import (
    BlueSkyClient, BlueSkySession,
    BlueSkySessionExpired, BlueSkyRateLimited,
)


def make_bsky_session() -> BlueSkySession:
    h = make_headers("bluesky")
    return BlueSkySession(
        account_id="acc_bsky_001",
        did="did:plc:testdid123",
        access_jwt="access_jwt_test",
        refresh_jwt="refresh_jwt_test",
        handle="phantom.bsky.social",
        headers=h,
    )


class TestBlueSkyClient:

    def test_build_client_bearer_token(self):
        client = BlueSkyClient(make_bsky_session())
        http_client = client._build_client()
        auth = dict(http_client.headers).get("authorization", "")
        assert auth == "Bearer access_jwt_test"

    async def test_create_post_calls_createRecord(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_post", new=AsyncMock(
                return_value={"uri": "at://did:plc:test/app.bsky.feed.post/rkey1", "cid": "cid1"}
            )
        ) as mock_post:
            async with client:
                result = await client.create_post("Hello Bluesky!")
            lexicon, payload = mock_post.call_args[0]
            assert lexicon == "com.atproto.repo.createRecord"
            assert payload["collection"] == "app.bsky.feed.post"
            assert payload["record"]["text"] == "Hello Bluesky!"
            assert result["cid"] == "cid1"

    async def test_follow_user_calls_createRecord_follow(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_post", new=AsyncMock(
                return_value={"uri": "at://did:plc:test/app.bsky.graph.follow/rkey2", "cid": "cid2"}
            )
        ) as mock_post:
            async with client:
                await client.follow_user("did:plc:target123")
            lexicon, payload = mock_post.call_args[0]
            assert lexicon == "com.atproto.repo.createRecord"
            assert payload["collection"] == "app.bsky.graph.follow"
            assert payload["record"]["subject"] == "did:plc:target123"

    async def test_unfollow_user_calls_deleteRecord(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={})
        ) as mock_post:
            async with client:
                await client.unfollow_user("rkey_follow_abc")
            lexicon, payload = mock_post.call_args[0]
            assert lexicon == "com.atproto.repo.deleteRecord"
            assert payload["collection"] == "app.bsky.graph.follow"
            assert payload["rkey"] == "rkey_follow_abc"

    async def test_like_post_calls_createRecord_like(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_post", new=AsyncMock(return_value={"uri": "at://like", "cid": "cid_like"})
        ) as mock_post:
            async with client:
                await client.like_post("at://post_uri", "cid_of_post")
            lexicon, payload = mock_post.call_args[0]
            assert payload["collection"] == "app.bsky.feed.like"
            assert payload["record"]["subject"]["uri"] == "at://post_uri"
            assert payload["record"]["subject"]["cid"] == "cid_of_post"

    async def test_get_timeline_calls_getTimeline(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_get", new=AsyncMock(return_value={"feed": [], "cursor": "cur1"})
        ) as mock_get:
            async with client:
                result = await client.get_timeline(limit=10, cursor="prev_cursor")
            # _get(lexicon, params=...) — lexicon is positional arg 0
            call_args = mock_get.call_args
            lexicon = call_args[0][0]
            assert lexicon == "app.bsky.feed.getTimeline"
            # params is passed as a keyword argument
            params = call_args.kwargs.get("params") or (call_args[1].get("params") if call_args[1] else {})
            assert params is not None
            assert params.get("cursor") == "prev_cursor"

    async def test_search_posts_calls_searchPosts(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_get", new=AsyncMock(return_value={"posts": []})
        ) as mock_get:
            async with client:
                await client.search_posts("phantom fleet", limit=5)
            lexicon = mock_get.call_args[0][0]
            assert lexicon == "app.bsky.feed.searchPosts"

    async def test_session_expired_on_401(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_get", new=AsyncMock(side_effect=BlueSkySessionExpired("expired"))
        ):
            async with client:
                with pytest.raises(BlueSkySessionExpired):
                    await client.get_profile("phantom.bsky.social")

    async def test_ping_session_false_on_expiry(self):
        client = BlueSkyClient(make_bsky_session())
        with patch.object(
            client, "_get", new=AsyncMock(side_effect=BlueSkySessionExpired("expired"))
        ):
            async with client:
                assert await client.ping_session() is False


# ===========================================================================
# X (TWITTER)
# ===========================================================================

from phantom_fleet.core.x_client import (
    XClient, XSession,
    XSessionExpired, XRateLimited,
    X_APP_BEARER,
)


def make_x_session() -> XSession:
    h = make_headers("x")
    return XSession(
        account_id="acc_x_001",
        auth_token="auth_tok_abc",
        ct0_csrf="csrf_tok_xyz",
        user_id="1234567890",
        username="phantom_x_user",
        headers=h,
    )


class TestXClient:

    def test_build_client_bearer_token(self):
        client = XClient(make_x_session())
        http_client = client._build_client()
        auth = dict(http_client.headers).get("authorization", "")
        assert auth == f"Bearer {X_APP_BEARER}"

    def test_build_client_csrf_header(self):
        client = XClient(make_x_session())
        http_client = client._build_client()
        csrf = dict(http_client.headers).get("x-csrf-token", "")
        assert csrf == "csrf_tok_xyz"

    def test_build_client_auth_cookie(self):
        client = XClient(make_x_session())
        http_client = client._build_client()
        cookie = dict(http_client.headers).get("cookie", "")
        assert "auth_token=auth_tok_abc" in cookie
        assert "ct0=csrf_tok_xyz" in cookie

    def test_build_client_active_user_header(self):
        client = XClient(make_x_session())
        http_client = client._build_client()
        active = dict(http_client.headers).get("x-twitter-active-user", "")
        assert active == "yes"

    async def test_follow_user_calls_graphql_post(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_graphql_post", new=AsyncMock(return_value={"data": {}})
        ) as mock_gql:
            async with client:
                await client.follow_user("987654321")
            query_id_path = mock_gql.call_args.args[0]
            variables = mock_gql.call_args.kwargs["variables"]
            assert "FollowUser" in query_id_path
            assert variables["userId"] == "987654321"

    async def test_like_tweet_calls_FavoriteTweet(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_graphql_post", new=AsyncMock(return_value={"data": {}})
        ) as mock_gql:
            async with client:
                await client.like_tweet("tweet_id_abc")
            query_id_path = mock_gql.call_args.args[0]
            variables = mock_gql.call_args.kwargs["variables"]
            assert "FavoriteTweet" in query_id_path
            assert variables["tweet_id"] == "tweet_id_abc"

    async def test_retweet_calls_CreateRetweet(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_graphql_post", new=AsyncMock(return_value={"data": {}})
        ) as mock_gql:
            async with client:
                await client.retweet("tweet_rt_001")
            query_id_path = mock_gql.call_args.args[0]
            variables = mock_gql.call_args.kwargs["variables"]
            assert "CreateRetweet" in query_id_path
            assert variables["tweet_id"] == "tweet_rt_001"

    async def test_send_dm_calls_graphql_post(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_graphql_post", new=AsyncMock(return_value={"data": {}})
        ) as mock_gql:
            async with client:
                await client.send_dm("555444333", "Hey, check this out!")
            query_id_path = mock_gql.call_args.args[0]
            variables = mock_gql.call_args.kwargs["variables"]
            assert "SendDM" in query_id_path
            assert variables["message"]["message_data"]["text"] == "Hey, check this out!"

    async def test_search_recent_calls_v2_get(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_v2_get", new=AsyncMock(
                return_value={"data": [], "meta": {"result_count": 0}}
            )
        ) as mock_v2:
            async with client:
                await client.search_recent("phantom fleet", count=10)
            endpoint, = mock_v2.call_args[0]
            assert endpoint == "tweets/search/recent"

    async def test_session_expired_on_401(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_graphql_post", new=AsyncMock(
                side_effect=XSessionExpired("expired")
            )
        ):
            async with client:
                with pytest.raises(XSessionExpired):
                    await client.follow_user("123")

    async def test_rate_limited_on_429(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_graphql_post", new=AsyncMock(
                side_effect=XRateLimited(retry_after_sec=900)
            )
        ):
            async with client:
                with pytest.raises(XRateLimited) as exc_info:
                    await client.like_tweet("tweet123")
                assert exc_info.value.retry_after_sec == 900

    async def test_ping_session_true_when_valid(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_v2_get", new=AsyncMock(
                return_value={"data": {"id": "1234567890", "name": "Phantom", "username": "phantom_x_user"}}
            )
        ):
            async with client:
                assert await client.ping_session() is True

    async def test_ping_session_false_on_expiry(self):
        client = XClient(make_x_session())
        with patch.object(
            client, "_v2_get", new=AsyncMock(side_effect=XSessionExpired("expired"))
        ):
            async with client:
                assert await client.ping_session() is False


# ===========================================================================
# Worker execute_task() integration tests (mocked clients)
# ===========================================================================

from phantom_fleet.core.hybrid_runner import (
    XAPIWorker, RedditAPIWorker, TelegramMTProtoWorker,
    DiscordAPIWorker, BlueSkyATProtoWorker,
    WorkerTask, DeviceProfile, PhoneSlotLock,
)


def make_device_profile(platform: str) -> DeviceProfile:
    h = make_headers(platform)
    return DeviceProfile(
        phone_serial="SERIAL_001",
        model="Samsung Galaxy S10 Lite",
        android_version="12",
        android_id="abc123def456abc1",
        advertising_id="gaid-test",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        timezone="America/New_York",
        locale="en_US",
        platform_headers={platform: h},
    )


def make_task(platform: str, action: str, params: dict) -> WorkerTask:
    return WorkerTask(
        task_id="task_test_001",
        platform=platform,
        account_id="acc_001",
        phone_serial="SERIAL_001",
        action=action,
        params=params,
    )


class TestWorkerExecuteTask:

    async def test_reddit_worker_upvote_returns_success(self):
        profile = make_device_profile("reddit")
        lock = PhoneSlotLock("SERIAL_001")
        worker = RedditAPIWorker("SERIAL_001", profile, lock)

        with patch(
            "phantom_fleet.core.reddit_client.RedditClient._post",
            new=AsyncMock(return_value={}),
        ):
            task = make_task("reddit", "upvote", {"post_id": "t3_abc"})
            result = await worker._safe_execute(task)
        assert result.success is True
        assert result.task_id == "task_test_001"

    async def test_reddit_worker_session_expired_returns_failure(self):
        profile = make_device_profile("reddit")
        lock = PhoneSlotLock("SERIAL_001")
        worker = RedditAPIWorker("SERIAL_001", profile, lock)

        with patch(
            "phantom_fleet.core.reddit_client.RedditClient._post",
            new=AsyncMock(side_effect=RedditSessionExpired("expired")),
        ):
            task = make_task("reddit", "upvote", {"post_id": "t3_abc"})
            result = await worker._safe_execute(task)
        assert result.success is False
        assert "session_expired" in result.error

    async def test_x_worker_unknown_action_returns_failure(self):
        profile = make_device_profile("x")
        lock = PhoneSlotLock("SERIAL_001")
        worker = XAPIWorker("SERIAL_001", profile, lock)

        task = make_task("x", "nonexistent_action", {})
        result = await worker._safe_execute(task)
        assert result.success is False
        assert "unknown_action" in result.error

    async def test_bluesky_worker_post_returns_success(self):
        profile = make_device_profile("bluesky")
        lock = PhoneSlotLock("SERIAL_001")
        worker = BlueSkyATProtoWorker("SERIAL_001", profile, lock)

        with patch(
            "phantom_fleet.core.bluesky_client.BlueSkyClient._post",
            new=AsyncMock(return_value={"uri": "at://test", "cid": "cid1"}),
        ):
            task = make_task("bluesky", "post", {"text": "Hello from worker!"})
            result = await worker._safe_execute(task)
        assert result.success is True
        assert result.data.get("uri") == "at://test"

    async def test_telegram_worker_rate_limited_returns_failure(self):
        profile = make_device_profile("telegram")
        lock = PhoneSlotLock("SERIAL_001")
        worker = TelegramMTProtoWorker("SERIAL_001", profile, lock)

        with patch(
            "phantom_fleet.core.telegram_client.TelegramClient._post",
            new=AsyncMock(side_effect=TelegramFloodWait(retry_after_sec=60)),
        ):
            task = make_task("telegram", "dm_send", {"user_id": "999", "text": "hi"})
            result = await worker._safe_execute(task)
        assert result.success is False
        assert "flood_wait" in result.error

    async def test_discord_worker_send_message_success(self):
        profile = make_device_profile("discord")
        lock = PhoneSlotLock("SERIAL_001")
        worker = DiscordAPIWorker("SERIAL_001", profile, lock)

        with patch(
            "phantom_fleet.core.discord_client.DiscordClient._post",
            new=AsyncMock(return_value={"id": "msg_001"}),
        ):
            task = make_task(
                "discord", "send_message",
                {"channel_id": "ch001", "content": "Hello!"}
            )
            result = await worker._safe_execute(task)
        assert result.success is True
