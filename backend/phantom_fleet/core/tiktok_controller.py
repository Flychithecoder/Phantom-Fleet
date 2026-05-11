"""
TikTokController — accessibility-based TikTok automation via the Companion APK.

TikTok is FOREGROUND_UI only. It rotates its request-signing stack
(X-Ladon / Gorgon / Khronos) on every app update, making background
API calls unreliable within days of any APK release. The only stable
automation surface is the accessibility service exposed by the Companion
APK while the TikTok clone runs in the foreground.

Architecture:
    - Companion APK runs an HTTP server on 127.0.0.1:8090
    - All TikTok actions POST to /tiktok/action with a JSON body
    - The APK's AccessibilityService translates the action into real
      touch/swipe/type events on the TikTok clone identified by clone_package
    - Timing parameters are passed to the APK; the APK executes them
      directly on the display so durations are real-world milliseconds

Proxy note:
    Traffic flows from TikTok app → Companion APK local proxy (port 8089)
    → residential 4G proxy. The controller itself only talks to the
    Companion APK on loopback — no proxy needed for this HTTP call.

Detection hardening built into every call:
    - All pause/dwell values use LogNormal sampling (caller must pass
      sampled values; the controller does not sample internally)
    - Character-by-character typing with per-keystroke delays for
      comment and search inputs
    - Returns TikTokResult with success/error so callers can handle
      graceful fallback without crashing the session
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Companion APK endpoint
# ---------------------------------------------------------------------------

COMPANION_HOST    = "127.0.0.1"
COMPANION_PORT    = 8090
COMPANION_TIMEOUT = 15.0   # seconds; TikTok UI actions can be slow

_TIKTOK_ACTION_URL = f"http://{COMPANION_HOST}:{COMPANION_PORT}/tiktok/action"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TikTokSession:
    """
    Live TikTok session bound to one physical phone + clone package.

    One TikTokSession per account currently active in the foreground
    slot. The session is created by the TikTokAgentManager when it
    acquires the foreground slot for this phone, and released when the
    slot is returned.
    """
    account_id:    str          # Phantom Fleet internal account ID
    username:      str          # TikTok @username
    phone_serial:  str          # ADB serial of the physical phone
    clone_package: str          # e.g. com.zhiliaoapp.musically.clone_01
    device_profile: dict = field(default_factory=dict)  # DeviceProfile extras


@dataclass
class TikTokAction:
    """
    One action dispatched to the Companion APK's accessibility service.

    The APK routes on action_type and executes the corresponding
    accessibility gesture on the clone_package.
    """
    action_type:  str           # e.g. "scroll_feed", "like_video", "follow_user"
    params:       dict          # action-specific params (see per-action docs)
    account_id:   str
    phone_serial: str


@dataclass
class TikTokResult:
    """
    Result returned by TikTokController for every dispatched action.

    On success:  success=True,  data contains any response payload
    On failure:  success=False, error contains a machine-readable reason
                 ("apk_unreachable", "action_timeout", "element_not_found", ...)
    """
    success:     bool
    action_type: str
    data:        dict = field(default_factory=dict)
    error:       Optional[str] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CompanionAPKUnreachable(RuntimeError):
    """Raised when the Companion APK HTTP endpoint does not respond."""


class TikTokActionFailed(RuntimeError):
    """Raised when the APK reports a failure executing an accessibility action."""


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class TikTokController:
    """
    Async controller for one TikTok account on one phone.

    One instance per (account, phone) pair. The caller — typically
    TikTokFollowAgent or TikTokScrollAgent — constructs the controller
    from a TikTokSession, calls the action methods, and reads back
    TikTokResult objects.

    All actions are dispatched via HTTP POST to the Companion APK's
    /tiktok/action endpoint. The APK's AccessibilityService executes
    the action on the correct clone package and returns a JSON result.

    Timing contract:
        All dwell/pause values MUST be pre-sampled by the caller using
        LogNormal distributions from core.distributions. The controller
        passes them verbatim to the APK — it never generates its own
        random values.
    """

    def __init__(self, session: TikTokSession):
        self.session = session
        self._http: Optional[httpx.AsyncClient] = None

    def _build_http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(COMPANION_TIMEOUT))

    async def __aenter__(self) -> "TikTokController":
        self._http = self._build_http()
        return self

    async def __aexit__(self, *_) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Core dispatcher
    # ------------------------------------------------------------------

    async def _dispatch(self, action: TikTokAction) -> TikTokResult:
        """
        POST an action to the Companion APK and return its result.

        Handles:
            - Connection errors  → CompanionAPKUnreachable
            - Non-200 HTTP       → TikTokActionFailed
            - APK-level failure  → TikTokResult(success=False, error=...)
        """
        if self._http is None:
            raise RuntimeError(
                "Use 'async with TikTokController(...) as ctrl:' before calling actions."
            )

        payload = {
            "action_type":   action.action_type,
            "params":        action.params,
            "account_id":    action.account_id,
            "phone_serial":  action.phone_serial,
            "clone_package": self.session.clone_package,
        }

        try:
            resp = await self._http.post(_TIKTOK_ACTION_URL, json=payload)
        except httpx.ConnectError as exc:
            log.warning(
                "Companion APK unreachable for account=%s phone=%s: %s",
                action.account_id, action.phone_serial, exc,
            )
            return TikTokResult(
                success=False,
                action_type=action.action_type,
                error="apk_unreachable",
            )
        except httpx.TimeoutException as exc:
            log.warning(
                "Companion APK timed out for action=%s account=%s: %s",
                action.action_type, action.account_id, exc,
            )
            return TikTokResult(
                success=False,
                action_type=action.action_type,
                error="action_timeout",
            )

        if resp.status_code != 200:
            return TikTokResult(
                success=False,
                action_type=action.action_type,
                error=f"http_{resp.status_code}",
            )

        try:
            body = resp.json()
        except Exception:
            return TikTokResult(
                success=False,
                action_type=action.action_type,
                error="invalid_json_response",
            )

        if not body.get("success", False):
            return TikTokResult(
                success=False,
                action_type=action.action_type,
                error=body.get("error", "unknown_apk_error"),
                data=body,
            )

        return TikTokResult(
            success=True,
            action_type=action.action_type,
            data=body.get("data", {}),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def scroll_feed(
        self,
        duration_sec: float,
        swipe_count: int,
    ) -> TikTokResult:
        """
        Scroll the TikTok For You Page feed.

        The APK issues `swipe_count` upward swipes spaced evenly across
        `duration_sec`. Each swipe includes a realistic dwell pause so
        TikTok's engagement model sees partial video views.

        Args:
            duration_sec: total wall-clock seconds for the scroll session
                          (pre-sampled by caller from LogNormal)
            swipe_count:  number of upward swipes (pre-sampled by caller)
        """
        return await self._dispatch(TikTokAction(
            action_type="scroll_feed",
            params={
                "duration_sec": duration_sec,
                "swipe_count": swipe_count,
            },
            account_id=self.session.account_id,
            phone_serial=self.session.phone_serial,
        ))

    async def like_video(
        self,
        pause_ms_range: tuple[int, int] = (800, 2500),
        pause_ms: Optional[int] = None,
    ) -> TikTokResult:
        """
        Double-tap the current video to like it.

        Args:
            pause_ms_range: fallback (low, high) ms range if pause_ms is None.
                            The caller should pass a pre-sampled pause_ms
                            whenever possible so distribution shape is correct.
            pause_ms:       pre-sampled pause before the like tap (ms).
                            If None, the APK samples from pause_ms_range —
                            this is acceptable for one-off calls but not
                            fleet-scale sessions (use pre-sampled values there).
        """
        params: dict[str, Any] = {"pause_ms_range": list(pause_ms_range)}
        if pause_ms is not None:
            params["pause_ms"] = pause_ms
        return await self._dispatch(TikTokAction(
            action_type="like_video",
            params=params,
            account_id=self.session.account_id,
            phone_serial=self.session.phone_serial,
        ))

    async def follow_user(self, username: str) -> TikTokResult:
        """
        Navigate to a user's profile and tap the Follow button.

        The APK:
            1. Opens the search tab
            2. Types the username
            3. Taps the first matching profile result
            4. Taps the Follow button on the profile page
            5. Returns to the previous screen

        Args:
            username: TikTok @username (without the @)
        """
        return await self._dispatch(TikTokAction(
            action_type="follow_user",
            params={"username": username},
            account_id=self.session.account_id,
            phone_serial=self.session.phone_serial,
        ))

    async def unfollow_user(self, username: str) -> TikTokResult:
        """
        Navigate to a user's profile and tap Unfollow.

        Args:
            username: TikTok @username (without the @)
        """
        return await self._dispatch(TikTokAction(
            action_type="unfollow_user",
            params={"username": username},
            account_id=self.session.account_id,
            phone_serial=self.session.phone_serial,
        ))

    async def view_profile(
        self,
        username: str,
        dwell_sec: float,
    ) -> TikTokResult:
        """
        Navigate to a user's profile and dwell for a sampled duration.

        Contributes to the account's profile-view signal. The dwell_sec
        MUST be pre-sampled by the caller from LogNormal(low=3, high=15)
        so the fleet-wide distribution is shaped correctly.

        Args:
            username:  TikTok @username (without the @)
            dwell_sec: seconds to spend on the profile page (pre-sampled)
        """
        return await self._dispatch(TikTokAction(
            action_type="view_profile",
            params={
                "username": username,
                "dwell_sec": dwell_sec,
            },
            account_id=self.session.account_id,
            phone_serial=self.session.phone_serial,
        ))

    async def post_comment(self, text: str) -> TikTokResult:
        """
        Post a comment on the currently visible video.

        The APK:
            1. Taps the comment icon to open the comment sheet
            2. Taps the text input field
            3. Types the comment character by character with realistic
               inter-keystroke delays (the APK handles timing at the
               accessibility layer)
            4. Taps the Send/Post button
            5. Waits for the comment to appear in the stream

        Args:
            text: comment text (already selected from template pool by caller)
        """
        return await self._dispatch(TikTokAction(
            action_type="post_comment",
            params={"text": text},
            account_id=self.session.account_id,
            phone_serial=self.session.phone_serial,
        ))

    async def open_search(self, query: str) -> TikTokResult:
        """
        Navigate to the Search tab and enter a query.

        Used by TikTokScrollAgent to discover content in a niche, and by
        TikTokFollowAgent to find users in a target niche.

        Args:
            query: search term (hashtag, username prefix, or keyword)
        """
        return await self._dispatch(TikTokAction(
            action_type="open_search",
            params={"query": query},
            account_id=self.session.account_id,
            phone_serial=self.session.phone_serial,
        ))
