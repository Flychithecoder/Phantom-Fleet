"""Tests for TikTokController — all Companion APK HTTP calls are mocked."""
from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from phantom_fleet.core.tiktok_controller import (
    TikTokController,
    TikTokSession,
    TikTokAction,
    TikTokResult,
    CompanionAPKUnreachable,
    _TIKTOK_ACTION_URL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_session(
    account_id: str = "acc_tk_001",
    username: str   = "test_user",
    phone_serial: str = "192.168.1.10:5555",
    clone_package: str = "com.zhiliaoapp.musically.clone_01",
) -> TikTokSession:
    return TikTokSession(
        account_id=account_id,
        username=username,
        phone_serial=phone_serial,
        clone_package=clone_package,
    )


def apk_ok(data: dict | None = None) -> MagicMock:
    """Simulate a successful 200 response from the Companion APK."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"success": True, "data": data or {}}
    return resp


def apk_fail(error: str = "element_not_found") -> MagicMock:
    """Simulate an APK-level failure (HTTP 200, success=False)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"success": False, "error": error}
    return resp


def apk_http_error(status_code: int = 500) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {}
    return resp


# ---------------------------------------------------------------------------
# scroll_feed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scroll_feed_sends_correct_params():
    session = make_session()
    ctrl = TikTokController(session)
    mock_post = AsyncMock(return_value=apk_ok())

    async with ctrl:
        with patch.object(ctrl._http, "post", new=mock_post):
            result = await ctrl.scroll_feed(duration_sec=8.5, swipe_count=4)

    assert result.success is True
    assert result.action_type == "scroll_feed"

    _, kwargs = mock_post.call_args
    payload = kwargs.get("json")

    # Inspect the actual call
    call_args = mock_post.call_args
    sent_json = call_args.kwargs.get("json") or call_args[1].get("json") if len(call_args) > 1 else None
    if sent_json is None and call_args[0]:
        sent_json = call_args[0][1] if len(call_args[0]) > 1 else None

    # Re-do with a simpler capture
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl2:
        with patch.object(ctrl2._http, "post", new=AsyncMock(side_effect=capture_post)):
            await ctrl2.scroll_feed(duration_sec=8.5, swipe_count=4)

    assert captured["action_type"] == "scroll_feed"
    assert captured["params"]["duration_sec"] == 8.5
    assert captured["params"]["swipe_count"] == 4
    assert captured["clone_package"] == session.clone_package
    assert captured["account_id"] == session.account_id


@pytest.mark.asyncio
async def test_scroll_feed_posts_to_correct_url():
    session = make_session()
    urls_called = []

    async def capture_post(url, **kwargs):
        urls_called.append(url)
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            await ctrl.scroll_feed(duration_sec=5.0, swipe_count=3)

    assert len(urls_called) == 1
    assert urls_called[0] == _TIKTOK_ACTION_URL


# ---------------------------------------------------------------------------
# like_video
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_like_video_sends_correct_action():
    session = make_session()
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            result = await ctrl.like_video(pause_ms=1200)

    assert result.success is True
    assert result.action_type == "like_video"
    assert captured["action_type"] == "like_video"
    assert captured["params"]["pause_ms"] == 1200


@pytest.mark.asyncio
async def test_like_video_uses_range_when_pause_ms_not_set():
    session = make_session()
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            await ctrl.like_video(pause_ms_range=(900, 2000))

    assert "pause_ms_range" in captured["params"]
    assert captured["params"]["pause_ms_range"] == [900, 2000]
    assert "pause_ms" not in captured["params"]


# ---------------------------------------------------------------------------
# follow_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_follow_user_sends_username():
    session = make_session()
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            result = await ctrl.follow_user("fitness_queen99")

    assert result.success is True
    assert result.action_type == "follow_user"
    assert captured["action_type"] == "follow_user"
    assert captured["params"]["username"] == "fitness_queen99"


@pytest.mark.asyncio
async def test_unfollow_user_sends_correct_action_type():
    session = make_session()
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            result = await ctrl.unfollow_user("old_follow_xyz")

    assert result.success is True
    assert captured["action_type"] == "unfollow_user"
    assert captured["params"]["username"] == "old_follow_xyz"


# ---------------------------------------------------------------------------
# view_profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_view_profile_sends_username_and_dwell():
    session = make_session()
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            result = await ctrl.view_profile("target_user", dwell_sec=7.3)

    assert result.success is True
    assert captured["params"]["username"] == "target_user"
    assert captured["params"]["dwell_sec"] == 7.3


# ---------------------------------------------------------------------------
# post_comment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_comment_sends_text():
    session = make_session()
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            result = await ctrl.post_comment("This is exactly what I needed today 🔥")

    assert result.success is True
    assert captured["action_type"] == "post_comment"
    assert captured["params"]["text"] == "This is exactly what I needed today 🔥"


# ---------------------------------------------------------------------------
# open_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_search_sends_query():
    session = make_session()
    captured = {}

    async def capture_post(url, **kwargs):
        captured.update(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=capture_post)):
            result = await ctrl.open_search("#fitness")

    assert result.success is True
    assert captured["action_type"] == "open_search"
    assert captured["params"]["query"] == "#fitness"


# ---------------------------------------------------------------------------
# Failure handling — APK unreachable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_actions_fail_gracefully_when_apk_unreachable():
    """
    When the Companion APK is unreachable (ConnectError), every action
    must return TikTokResult(success=False, error="apk_unreachable")
    without raising an exception — the caller handles graceful fallback.
    """
    session = make_session()

    async def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    actions_to_test = [
        ("scroll_feed",    lambda c: c.scroll_feed(5.0, 3)),
        ("like_video",     lambda c: c.like_video()),
        ("follow_user",    lambda c: c.follow_user("someone")),
        ("unfollow_user",  lambda c: c.unfollow_user("someone")),
        ("view_profile",   lambda c: c.view_profile("someone", 5.0)),
        ("post_comment",   lambda c: c.post_comment("Great content!")),
        ("open_search",    lambda c: c.open_search("fitness")),
    ]

    for action_name, action_fn in actions_to_test:
        async with TikTokController(session) as ctrl:
            with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=raise_connect_error)):
                result = await action_fn(ctrl)

        assert result.success is False, f"{action_name} should return success=False on connect error"
        assert result.error == "apk_unreachable", (
            f"{action_name} error should be 'apk_unreachable', got {result.error!r}"
        )


@pytest.mark.asyncio
async def test_action_fails_gracefully_on_timeout():
    session = make_session()

    async def raise_timeout(url, **kwargs):
        raise httpx.TimeoutException("Timeout", request=None)

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(side_effect=raise_timeout)):
            result = await ctrl.scroll_feed(5.0, 3)

    assert result.success is False
    assert result.error == "action_timeout"


@pytest.mark.asyncio
async def test_action_fails_gracefully_on_http_500():
    session = make_session()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(return_value=apk_http_error(500))):
            result = await ctrl.follow_user("someone")

    assert result.success is False
    assert result.error == "http_500"


@pytest.mark.asyncio
async def test_apk_level_failure_returns_error_reason():
    """APK returns HTTP 200 but success=False — controller surfaces the error reason."""
    session = make_session()

    async with TikTokController(session) as ctrl:
        with patch.object(ctrl._http, "post", new=AsyncMock(return_value=apk_fail("element_not_found"))):
            result = await ctrl.like_video()

    assert result.success is False
    assert result.error == "element_not_found"


# ---------------------------------------------------------------------------
# Context manager safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raises_when_called_outside_context_manager():
    """
    Calling a controller action without 'async with' should raise RuntimeError,
    not silently fail.
    """
    session = make_session()
    ctrl = TikTokController(session)  # NOT used as context manager

    with pytest.raises(RuntimeError, match="async with"):
        await ctrl.scroll_feed(5.0, 3)


# ---------------------------------------------------------------------------
# Payload contains phone + clone metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_actions_include_account_and_phone_in_payload():
    """Every dispatched action must carry account_id and phone_serial."""
    session = make_session(
        account_id="acc_verify_001",
        phone_serial="10.0.0.5:5555",
        clone_package="com.zhiliaoapp.musically.clone_03",
    )
    captured_payloads: list[dict] = []

    async def capture_post(url, **kwargs):
        captured_payloads.append(kwargs.get("json", {}))
        return apk_ok()

    async with TikTokController(session) as ctrl:
        mock = AsyncMock(side_effect=capture_post)
        with patch.object(ctrl._http, "post", new=mock):
            await ctrl.scroll_feed(5.0, 2)
            await ctrl.like_video()
            await ctrl.follow_user("x")
            await ctrl.open_search("fitness")

    assert len(captured_payloads) == 4
    for payload in captured_payloads:
        assert payload["account_id"]   == "acc_verify_001"
        assert payload["phone_serial"] == "10.0.0.5:5555"
        assert payload["clone_package"] == "com.zhiliaoapp.musically.clone_03"
