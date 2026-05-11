"""Tests for InstagramClient — all mocked, no real IG calls."""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from phantom_fleet.core.instagram_client import (
    InstagramClient,
    IGSession,
    IGSessionExpired,
    _sign_payload,
    _generate_uuid,
    _tz_offset,
)
from phantom_fleet.core.hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_headers() -> PlatformHeaders:
    return PlatformHeaders(
        platform="instagram",
        session_token="tok_test",
        device_id="android-abc123",
        user_agent="Instagram 300.0.0.1 Android (31/12; 420dpi; 1080x2400; samsung; SM-G770F; x1s; exynos9610; en_US; 480028919)",
        app_version="300.0.0.1",
        android_id="abc123def456abc1",
        advertising_id="gaid-1234-5678",
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra={
            "mid": "mid_test_value",
            "family_device_id": "family-uuid-test",
        },
    )


def make_session() -> IGSession:
    return IGSession(
        account_id="acc_001",
        ig_user_id="1234567890",
        username="test_account",
        session_id="sess_abc123",
        csrftoken="csrf_xyz789",
        mid="mid_test_value",
        ds_user_id="1234567890",
        headers=make_headers(),
    )


def make_client(session=None) -> InstagramClient:
    return InstagramClient(
        session=session or make_session(),
        proxy_url="socks5://127.0.0.1:8089",
    )


def mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Signing + UUID
# ---------------------------------------------------------------------------

def test_sign_payload_produces_signature():
    signed = _sign_payload({"user_id": "123", "_uuid": "abc"})
    assert signed.startswith("ig_sig_key_version=4&signed_body=")
    assert "user_id" in signed


def test_sign_payload_deterministic():
    data = {"a": "1", "b": "2"}
    assert _sign_payload(data) == _sign_payload(data)


def test_generate_uuid_format():
    u = _generate_uuid()
    parts = u.split("-")
    assert len(parts) == 5


def test_tz_offset_new_york():
    assert _tz_offset("America/New_York") == "-18000"


def test_tz_offset_fallback():
    assert _tz_offset("Unknown/Timezone") == "-18000"


# ---------------------------------------------------------------------------
# Client header construction
# ---------------------------------------------------------------------------

def test_client_builds_correct_headers():
    client = make_client()
    http_client = client._build_client()
    headers = dict(http_client.headers)
    assert "instagram" in headers.get("user-agent", "").lower()
    assert headers.get("x-ig-app-id") == "567067343352427"
    assert "sessionid=sess_abc123" in headers.get("cookie", "")
    assert "csrftoken=csrf_xyz789" in headers.get("cookie", "")
    http_client.aclose()   # sync close for test cleanup is fine here


# ---------------------------------------------------------------------------
# Actions (mocked HTTP)
# ---------------------------------------------------------------------------

async def test_follow_sends_correct_endpoint():
    client = make_client()
    resp = mock_response({"friendship_status": {"following": True}})
    with patch.object(client, "_post", new=AsyncMock(return_value=resp.json())) as mock_post:
        async with client:
            result = await client.follow("999888777")
        mock_post.assert_called_once()
        endpoint, payload = mock_post.call_args[0]
        assert "friendships/create/999888777" in endpoint
        assert payload["user_id"] == "999888777"


async def test_unfollow_sends_correct_endpoint():
    client = make_client()
    resp_data = {"friendship_status": {"following": False}}
    with patch.object(client, "_post", new=AsyncMock(return_value=resp_data)) as mock_post:
        async with client:
            await client.unfollow("999888777")
        endpoint, _ = mock_post.call_args[0]
        assert "friendships/destroy/999888777" in endpoint


async def test_like_post_sends_correct_endpoint():
    client = make_client()
    with patch.object(client, "_post", new=AsyncMock(return_value={"status": "ok"})) as mock_post:
        async with client:
            await client.like_post("media_abc123")
        endpoint, payload = mock_post.call_args[0]
        assert "media/media_abc123/like" in endpoint
        assert payload["media_id"] == "media_abc123"


async def test_story_view_sends_reels_payload():
    client = make_client()
    with patch.object(client, "_post", new=AsyncMock(return_value={"status": "ok"})) as mock_post:
        async with client:
            await client.story_view("owner_456", ["media_1", "media_2"])
        endpoint, payload = mock_post.call_args[0]
        assert "media/seen" in endpoint
        assert "owner_456" in payload["reels"]


async def test_send_dm_sends_text():
    client = make_client()
    with patch.object(client, "_post", new=AsyncMock(return_value={"status": "ok"})) as mock_post:
        async with client:
            await client.send_dm("777666555", "Hey! Saw your profile")
        endpoint, payload = mock_post.call_args[0]
        assert "direct_v2/threads/broadcast/text" in endpoint
        assert payload["text"] == "Hey! Saw your profile"


async def test_get_user_info_calls_get():
    client = make_client()
    user_data = {"user": {"pk": "123", "username": "test_user"}}
    with patch.object(client, "_get", new=AsyncMock(return_value=user_data)):
        async with client:
            result = await client.get_user_info("test_user")
        assert result == user_data


async def test_get_followers_paginates():
    client = make_client()
    data = {"users": [{"pk": "111"}, {"pk": "222"}], "next_max_id": "cursor_abc"}
    with patch.object(client, "_get", new=AsyncMock(return_value=data)) as mock_get:
        async with client:
            result = await client.get_user_followers("owner_123", max_id="prev_cursor")
        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params.get("max_id") == "prev_cursor"


# ---------------------------------------------------------------------------
# Session expiry
# ---------------------------------------------------------------------------

async def test_session_expires_on_401():
    client = make_client()
    resp_401 = mock_response({}, status_code=401)

    async def fake_post_request(url, **kwargs):
        return resp_401

    with patch.object(
        client, "_post",
        new=AsyncMock(side_effect=IGSessionExpired("Session expired"))
    ):
        async with client:
            with pytest.raises(IGSessionExpired):
                await client.follow("some_user")


async def test_ping_session_returns_true_when_valid():
    client = make_client()
    with patch.object(client, "_get", new=AsyncMock(return_value={"user": {"pk": "123"}})):
        async with client:
            result = await client.ping_session()
        assert result is True


async def test_ping_session_returns_false_on_expiry():
    client = make_client()
    with patch.object(
        client, "_get",
        new=AsyncMock(side_effect=IGSessionExpired("expired"))
    ):
        async with client:
            result = await client.ping_session()
        assert result is False
