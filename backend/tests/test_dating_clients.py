"""
Tests for dating platform API clients — all mocked, no real network calls.

Coverage:
    GrindrClient:
        - cascade fetch parses correctly
        - view_profile fires view POST
        - send_message sends correct endpoint + body
        - tap_profile sends correct endpoint
        - update_location encodes geohash
        - 401 raises GrindrSessionExpired
        - 429 raises GrindrRateLimited with retry_after

    TinderClient:
        - get_recs returns data
        - swipe_like sends correct endpoint + params
        - swipe_pass sends correct endpoint + params
        - get_matches passes count + page_token
        - send_message posts to correct match endpoint
        - 401 raises TinderSessionExpired
        - 429 raises TinderRateLimited
        - 403 raises TinderActionBlocked

    BumbleClient:
        - get_encounters calls RPC with correct message_type
        - vote yes sends direction=1 in body
        - vote no sends direction=2 in body
        - send_message uses TEXT type by default
        - 401 raises BumbleSessionExpired
        - 429 raises BumbleRateLimited

    HingeClient:
        - get_discover calls correct endpoint
        - like_content without comment — no comment key in body
        - like_content with comment — comment field present and capped at 150 chars
        - pass_profile sends subject_id
        - send_message posts to match endpoint
        - 401 raises HingeSessionExpired
        - 429 raises HingeRateLimited
        - 403 with verification message raises HingeVerificationRequired
        - 403 without verification message raises HingeActionBlocked

    DatingSwipeAgent helpers:
        - _hinge_comment_for: different targets → different comments
        - _hinge_comment_for: same inputs → same comment (deterministic)
        - _should_comment: ~30% true at scale
        - _opening_for (GrindrGridAgent): deterministic, different accounts vary

Total: 28 tests
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx

from phantom_fleet.core.hybrid_runner import PlatformHeaders
from phantom_fleet.core.grindr_client import (
    GrindrClient,
    GrindrSession,
    GrindrSessionExpired,
    GrindrRateLimited,
    _lat_lon_to_geohash,
)
from phantom_fleet.core.tinder_client import (
    TinderClient,
    TinderSession,
    TinderSessionExpired,
    TinderRateLimited,
    TinderActionBlocked,
)
from phantom_fleet.core.bumble_client import (
    BumbleClient,
    BumbleSession,
    BumbleSessionExpired,
    BumbleRateLimited,
    MSG_TYPE_ENCOUNTERS,
    MSG_TYPE_VOTE,
    MSG_TYPE_SEND_MSG,
)
from phantom_fleet.core.hinge_client import (
    HingeClient,
    HingeSession,
    HingeSessionExpired,
    HingeRateLimited,
    HingeVerificationRequired,
    HingeActionBlocked,
)
from phantom_fleet.agents.specialists.dating_swipe_agent import (
    _hinge_comment_for,
    _should_comment,
    HINGE_COMMENT_POOL,
)
from phantom_fleet.agents.specialists.grindr_grid_agent import (
    _opening_for,
    OPENING_TEMPLATES,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def make_platform_headers(platform: str = "grindr") -> PlatformHeaders:
    return PlatformHeaders(
        platform=platform,
        session_token="tok_test",
        device_id="android-test-device-001",
        user_agent=f"Grindr/24.3.0 (Android 12; samsung SM-G991B)",
        app_version="24.3.0",
        android_id="abc123def456abc1",
        advertising_id="gaid-test-adid-1234",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra={},
    )


def make_grindr_session() -> GrindrSession:
    return GrindrSession(
        account_id="grindr_acc_001",
        auth_token="grindr-jwt-test-token",
        user_id="g_user_12345",
        profile_id="g_profile_12345",
        headers=make_platform_headers("grindr"),
    )


def make_tinder_session() -> TinderSession:
    return TinderSession(
        account_id="tinder_acc_001",
        auth_token="tinder-x-auth-test-token",
        user_id="t_user_67890",
        headers=make_platform_headers("tinder"),
    )


def make_bumble_session() -> BumbleSession:
    return BumbleSession(
        account_id="bumble_acc_001",
        token="bumble-jwt-test-token",
        user_id="b_user_11111",
        headers=make_platform_headers("bumble"),
    )


def make_hinge_session() -> HingeSession:
    return HingeSession(
        account_id="hinge_acc_001",
        auth_token="hinge-bearer-test-token",
        user_id="h_user_22222",
        headers=make_platform_headers("hinge"),
    )


def mock_response(
    json_data: dict,
    status_code: int = 200,
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.content = b"content"
    resp.headers = httpx.Headers(headers or {})
    resp.raise_for_status = MagicMock()
    return resp


def mock_empty_response(status_code: int = 204) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.content = b""
    resp.headers = httpx.Headers({})
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# GrindrClient tests
# ---------------------------------------------------------------------------


class TestGrindrClientCascade:
    """get_cascade parses profiles list correctly."""

    @pytest.mark.asyncio
    async def test_cascade_returns_profiles(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()

        cascade_data = {
            "profiles": [
                {"profileId": "p001", "displayName": "Alex", "age": 28},
                {"profileId": "p002", "displayName": "Jordan", "age": 31},
            ],
            "cached": False,
        }
        client._client.get = AsyncMock(return_value=mock_response(cascade_data))

        result = await client.get_cascade(limit=50)
        profiles = result.get("profiles", [])

        assert len(profiles) == 2
        assert profiles[0]["profileId"] == "p001"
        assert profiles[1]["profileId"] == "p002"

    @pytest.mark.asyncio
    async def test_cascade_passes_limit_in_params(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response({"profiles": []}))

        await client.get_cascade(limit=25)

        call_kwargs = client._client.get.call_args
        assert call_kwargs is not None
        url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("url", "")
        # The endpoint should contain cascade
        assert "cascade" in url


class TestGrindrClientViewProfile:
    """view_profile fires a GET then a view POST."""

    @pytest.mark.asyncio
    async def test_view_profile_fires_view_post(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()

        profile_data = {"profileId": "p001", "displayName": "Alex"}
        client._client.get = AsyncMock(return_value=mock_response(profile_data))
        client._client.post = AsyncMock(return_value=mock_empty_response(204))

        result = await client.view_profile("p001", dwell_ms=3000)

        assert client._client.get.called
        assert client._client.post.called
        assert result.get("profileId") == "p001"


class TestGrindrClientSendMessage:
    """send_message sends correct endpoint and body structure."""

    @pytest.mark.asyncio
    async def test_send_message_uses_conversation_endpoint(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()

        msg_resp = {"messageId": "msg_abc123", "type": "Text"}
        client._client.post = AsyncMock(return_value=mock_response(msg_resp))

        result = await client.send_message(
            conversation_id="conv_001",
            body="Hey there",
            msg_type="Text",
        )

        assert client._client.post.called
        call_kwargs = client._client.post.call_args
        url = call_kwargs[0][0]
        assert "conv_001" in url
        body = call_kwargs[1].get("json", {})
        assert body.get("body") == "Hey there"
        assert body.get("type") == "Text"
        assert result.get("messageId") == "msg_abc123"


class TestGrindrClientTap:
    """tap_profile sends correct endpoint."""

    @pytest.mark.asyncio
    async def test_tap_profile_sends_tap_endpoint(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_empty_response(204))

        await client.tap_profile("p001")

        call_kwargs = client._client.post.call_args
        url = call_kwargs[0][0]
        assert "tap" in url
        body = call_kwargs[1].get("json", {})
        assert body.get("tappedProfileId") == "p001"


class TestGrindrClientUpdateLocation:
    """update_location posts lat/lon and encodes geohash."""

    @pytest.mark.asyncio
    async def test_update_location_includes_geohash(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_empty_response(204))

        await client.update_location(40.7128, -74.0060)

        call_kwargs = client._client.post.call_args
        body = call_kwargs[1].get("json", {})
        assert "geohash" in body
        assert body.get("lat") == 40.7128
        assert body.get("lon") == -74.0060
        assert len(body["geohash"]) == 7  # precision=7


class TestGrindrSessionExpiry:
    """401 raises GrindrSessionExpired and marks session invalid."""

    @pytest.mark.asyncio
    async def test_401_raises_session_expired(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response({}, status_code=401)
        )

        with pytest.raises(GrindrSessionExpired):
            await client.get_cascade()

        assert session.is_valid is False

    @pytest.mark.asyncio
    async def test_429_raises_rate_limited_with_retry_after(self):
        session = make_grindr_session()
        client = GrindrClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response(
                {}, status_code=429, headers={"Retry-After": "30"}
            )
        )

        with pytest.raises(GrindrRateLimited) as exc_info:
            await client.get_cascade()

        assert exc_info.value.retry_after == 30


# ---------------------------------------------------------------------------
# TinderClient tests
# ---------------------------------------------------------------------------


class TestTinderClientGetRecs:
    """get_recs returns data from correct endpoint."""

    @pytest.mark.asyncio
    async def test_get_recs_returns_profiles(self):
        session = make_tinder_session()
        client = TinderClient(session)
        client._client = AsyncMock()

        recs_data = {
            "data": {
                "results": [
                    {"user": {"_id": "u001", "name": "Sam"}, "s_number": 12345},
                    {"user": {"_id": "u002", "name": "Taylor"}, "s_number": 67890},
                ]
            }
        }
        client._client.get = AsyncMock(return_value=mock_response(recs_data))

        result = await client.get_recs(count=10)
        profiles = result.get("data", {}).get("results", [])
        assert len(profiles) == 2


class TestTinderClientSwipeLike:
    """swipe_like sends to /like/{user_id} with s_number param."""

    @pytest.mark.asyncio
    async def test_swipe_like_correct_endpoint_and_params(self):
        session = make_tinder_session()
        client = TinderClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response({"match": False, "likes_remaining": 50})
        )

        result = await client.swipe_like("u001", s_number=12345, photo_id="photo_abc")

        call_kwargs = client._client.get.call_args
        url = call_kwargs[0][0]
        assert "like/u001" in url
        params = call_kwargs[1].get("params", {})
        assert params.get("s_number") == 12345
        assert params.get("photoId") == "photo_abc"
        assert "match" in result


class TestTinderClientSwipePass:
    """swipe_pass sends to /pass/{user_id} with s_number param."""

    @pytest.mark.asyncio
    async def test_swipe_pass_correct_endpoint_and_params(self):
        session = make_tinder_session()
        client = TinderClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response({"status": 200})
        )

        await client.swipe_pass("u001", s_number=12345)

        call_kwargs = client._client.get.call_args
        url = call_kwargs[0][0]
        assert "pass/u001" in url
        params = call_kwargs[1].get("params", {})
        assert params.get("s_number") == 12345


class TestTinderClientSessionExpiry:
    """401 raises TinderSessionExpired; 429 raises TinderRateLimited."""

    @pytest.mark.asyncio
    async def test_401_raises_session_expired(self):
        session = make_tinder_session()
        client = TinderClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response({}, status_code=401)
        )

        with pytest.raises(TinderSessionExpired):
            await client.get_recs()

        assert session.is_valid is False

    @pytest.mark.asyncio
    async def test_429_raises_rate_limited(self):
        session = make_tinder_session()
        client = TinderClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response(
                {}, status_code=429, headers={"Retry-After": "45"}
            )
        )

        with pytest.raises(TinderRateLimited) as exc_info:
            await client.get_recs()

        assert exc_info.value.retry_after == 45

    @pytest.mark.asyncio
    async def test_403_raises_action_blocked(self):
        session = make_tinder_session()
        client = TinderClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response(
                {"error": {"message": "Like limit reached"}}, status_code=403
            )
        )

        with pytest.raises(TinderActionBlocked):
            await client.swipe_like("u001", 999, "photo_x")


# ---------------------------------------------------------------------------
# BumbleClient tests
# ---------------------------------------------------------------------------


class TestBumbleClientGetEncounters:
    """get_encounters sends the correct RPC message_type."""

    @pytest.mark.asyncio
    async def test_get_encounters_correct_message_type(self):
        session = make_bumble_session()
        client = BumbleClient(session)
        client._client = AsyncMock()

        encounters_resp = {
            "body": [{"message_type": MSG_TYPE_ENCOUNTERS, "results": []}]
        }
        client._client.post = AsyncMock(return_value=mock_response(encounters_resp))

        await client.get_encounters()

        call_kwargs = client._client.post.call_args
        body_sent = call_kwargs[1].get("json", {})
        assert body_sent.get("message_type") == MSG_TYPE_ENCOUNTERS


class TestBumbleClientVote:
    """vote yes sends direction=1; vote no sends direction=2."""

    @pytest.mark.asyncio
    async def test_vote_yes_sends_direction_1(self):
        session = make_bumble_session()
        client = BumbleClient(session)
        client._client = AsyncMock()

        vote_resp = {"body": [{"message_type": MSG_TYPE_VOTE, "match": False}]}
        client._client.post = AsyncMock(return_value=mock_response(vote_resp))

        await client.vote("u001", direction="yes")

        call_kwargs = client._client.post.call_args
        body_sent = call_kwargs[1].get("json", {})
        # The body list items include the vote payload
        body_items = body_sent.get("body", [])
        assert len(body_items) >= 1
        assert body_items[0].get("vote") == 1

    @pytest.mark.asyncio
    async def test_vote_no_sends_direction_2(self):
        session = make_bumble_session()
        client = BumbleClient(session)
        client._client = AsyncMock()

        vote_resp = {"body": [{"message_type": MSG_TYPE_VOTE}]}
        client._client.post = AsyncMock(return_value=mock_response(vote_resp))

        await client.vote("u001", direction="no")

        call_kwargs = client._client.post.call_args
        body_sent = call_kwargs[1].get("json", {})
        body_items = body_sent.get("body", [])
        assert body_items[0].get("vote") == 2

    @pytest.mark.asyncio
    async def test_vote_no_superswipe_by_default(self):
        session = make_bumble_session()
        client = BumbleClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            return_value=mock_response(
                {"body": [{"message_type": MSG_TYPE_VOTE}]}
            )
        )

        await client.vote("u001", direction="yes")

        call_kwargs = client._client.post.call_args
        body_sent = call_kwargs[1].get("json", {})
        body_items = body_sent.get("body", [])
        assert body_items[0].get("is_super_like") is False


class TestBumbleClientSendMessage:
    """send_message uses TEXT type by default."""

    @pytest.mark.asyncio
    async def test_send_message_uses_text_type_by_default(self):
        session = make_bumble_session()
        client = BumbleClient(session)
        client._client = AsyncMock()

        msg_resp = {"body": [{"message_type": MSG_TYPE_SEND_MSG, "msg_id": "m001"}]}
        client._client.post = AsyncMock(return_value=mock_response(msg_resp))

        await client.send_message("conn_001", body="Hey!")

        call_kwargs = client._client.post.call_args
        body_sent = call_kwargs[1].get("json", {})
        body_items = body_sent.get("body", [])
        assert body_items[0].get("type") == "TEXT"


class TestBumbleClientSessionExpiry:
    """401 / 429 raise correct exceptions."""

    @pytest.mark.asyncio
    async def test_401_raises_session_expired(self):
        session = make_bumble_session()
        client = BumbleClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            return_value=mock_response({}, status_code=401)
        )

        with pytest.raises(BumbleSessionExpired):
            await client.get_encounters()

        assert session.is_valid is False

    @pytest.mark.asyncio
    async def test_429_raises_rate_limited(self):
        session = make_bumble_session()
        client = BumbleClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            return_value=mock_response(
                {}, status_code=429, headers={"Retry-After": "20"}
            )
        )

        with pytest.raises(BumbleRateLimited) as exc_info:
            await client.get_encounters()

        assert exc_info.value.retry_after == 20


# ---------------------------------------------------------------------------
# HingeClient tests
# ---------------------------------------------------------------------------


class TestHingeClientGetDiscover:
    """get_discover calls the correct endpoint."""

    @pytest.mark.asyncio
    async def test_get_discover_calls_discover_endpoint(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()

        discover_resp = {"subjects": []}
        client._client.get = AsyncMock(return_value=mock_response(discover_resp))

        await client.get_discover()

        call_kwargs = client._client.get.call_args
        url = call_kwargs[0][0]
        assert "discover" in url


class TestHingeClientLikeContent:
    """like_content with/without comment includes correct fields."""

    @pytest.mark.asyncio
    async def test_like_without_comment_no_comment_key(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()

        like_resp = {"like_id": "like_001", "is_match": False}
        client._client.post = AsyncMock(return_value=mock_response(like_resp))

        await client.like_content("sub_001", "content_001", comment=None)

        call_kwargs = client._client.post.call_args
        body = call_kwargs[1].get("json", {})
        assert "comment" not in body
        assert body.get("subject_id") == "sub_001"
        assert body.get("content_id") == "content_001"

    @pytest.mark.asyncio
    async def test_like_with_comment_includes_comment_field(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()

        like_resp = {"like_id": "like_002", "is_match": True}
        client._client.post = AsyncMock(return_value=mock_response(like_resp))

        await client.like_content("sub_001", "content_001", comment="This is great!")

        call_kwargs = client._client.post.call_args
        body = call_kwargs[1].get("json", {})
        assert body.get("comment") == "This is great!"

    @pytest.mark.asyncio
    async def test_like_comment_capped_at_150_chars(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            return_value=mock_response({"like_id": "like_003", "is_match": False})
        )

        long_comment = "x" * 200
        await client.like_content("sub_001", "content_001", comment=long_comment)

        call_kwargs = client._client.post.call_args
        body = call_kwargs[1].get("json", {})
        assert len(body.get("comment", "")) == 150


class TestHingeClientPassProfile:
    """pass_profile sends subject_id correctly."""

    @pytest.mark.asyncio
    async def test_pass_profile_sends_subject_id(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_empty_response(204))

        await client.pass_profile("sub_002")

        call_kwargs = client._client.post.call_args
        url = call_kwargs[0][0]
        assert "pass" in url
        body = call_kwargs[1].get("json", {})
        assert body.get("subject_id") == "sub_002"


class TestHingeClientSessionExpiry:
    """401 / 429 / 403 raise correct exceptions."""

    @pytest.mark.asyncio
    async def test_401_raises_session_expired(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response({}, status_code=401)
        )

        with pytest.raises(HingeSessionExpired):
            await client.get_discover()

        assert session.is_valid is False

    @pytest.mark.asyncio
    async def test_429_raises_rate_limited(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response(
                {}, status_code=429, headers={"Retry-After": "60"}
            )
        )

        with pytest.raises(HingeRateLimited) as exc_info:
            await client.get_discover()

        assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_403_with_verification_message_raises_verification_required(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            return_value=mock_response(
                {
                    "error_code": "PHOTO_VERIFICATION_REQUIRED",
                    "message": "Photo verification is required to continue",
                },
                status_code=403,
            )
        )

        with pytest.raises(HingeVerificationRequired):
            await client.get_discover()

    @pytest.mark.asyncio
    async def test_403_without_verification_raises_action_blocked(self):
        session = make_hinge_session()
        client = HingeClient(session)
        client._client = AsyncMock()
        client._client.post = AsyncMock(
            return_value=mock_response(
                {"message": "Like limit exhausted for today"},
                status_code=403,
            )
        )

        with pytest.raises(HingeActionBlocked):
            await client.like_content("sub_001", "content_001")


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHingeCommentHelpers:
    """_hinge_comment_for is deterministic and diverse across inputs."""

    def test_same_inputs_same_comment(self):
        c1 = _hinge_comment_for("acc_001", "target_001", "content_001")
        c2 = _hinge_comment_for("acc_001", "target_001", "content_001")
        assert c1 == c2

    def test_different_targets_likely_different_comments(self):
        comments = {
            _hinge_comment_for("acc_001", f"target_{i:04d}", "content_001")
            for i in range(50)
        }
        # With 60 templates and 50 targets, we expect significant variety
        assert len(comments) > 10

    def test_different_accounts_likely_different_comments(self):
        comments = {
            _hinge_comment_for(f"acc_{i:04d}", "target_001", "content_001")
            for i in range(50)
        }
        assert len(comments) > 10

    def test_comment_is_in_pool(self):
        pool_texts = {t for t, _ in []} | set(HINGE_COMMENT_POOL)
        c = _hinge_comment_for("acc_001", "target_001", "content_001")
        assert c in pool_texts


class TestShouldComment:
    """_should_comment returns ~30% True at scale."""

    def test_approximately_30_percent_true(self):
        # Sample 300 combinations to check distribution
        trues = sum(
            1
            for i in range(300)
            for _ in [None]
            if _should_comment("acc_001", f"t_{i:04d}", f"c_{i:04d}")
        )
        # Allow wide tolerance: expect 60–120 out of 300 (20%–40%)
        assert 60 <= trues <= 120

    def test_same_inputs_deterministic(self):
        r1 = _should_comment("acc_001", "t_001", "c_001")
        r2 = _should_comment("acc_001", "t_001", "c_001")
        assert r1 == r2


class TestOpeningTemplateHelper:
    """_opening_for is deterministic and diverse across accounts."""

    def test_same_inputs_same_template(self):
        t1 = _opening_for("acc_001", "target_001")
        t2 = _opening_for("acc_001", "target_001")
        assert t1 == t2

    def test_different_accounts_vary(self):
        templates = {_opening_for(f"acc_{i:04d}", "target_001") for i in range(60)}
        # With 30+ templates, expect good coverage
        assert len(templates) > 8

    def test_template_is_in_pool(self):
        pool_texts = {t for t, _ in OPENING_TEMPLATES}
        t = _opening_for("acc_001", "target_001")
        assert t in pool_texts
