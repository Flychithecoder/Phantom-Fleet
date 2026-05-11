"""
GrindrClient — private API client for Grindr automation.

Security profile: LOWEST of all dating platforms.
    - No hardware attestation (no SafetyNet / Play Integrity)
    - Email signup accepted — real SIM optional
    - Static selfie verification only (no liveness SDK)
    - Location spoofing works reliably (no motion-check enforcement)
    - Highest account density per phone: 5-10 accounts (see DatingAgentManager)

API structure:
    - Base: https://grindr.mobi/v3 (most endpoints)
    - Base v4: https://grindr.mobi/v4 (newer endpoints — media, preferences)
    - Auth: "Grindr3 {auth_token}" in Authorization header
    - JSON request/response throughout

Routing: socks5://127.0.0.1:8089 (same as all other clients)

This client is a thin HTTP layer. Rate limit enforcement and action
budgets are the GrindrGridAgent's responsibility.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional, Any

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRINDR_V3 = "https://grindr.mobi/v3"
GRINDR_V4 = "https://grindr.mobi/v4"

# App-level constants matching real Grindr Android APK (v24.x)
GRINDR_APP_VERSION    = "24.3.0"
GRINDR_BUILD_NUMBER   = "243001"
GRINDR_REQUIRE_MENU   = "0.1"
GRINDR_NET_TYPE       = "wifi"


def _generate_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class GrindrSession:
    """Live authenticated session for one Grindr account."""
    account_id:   str              # internal account ID
    auth_token:   str              # JWT returned by Grindr auth endpoint
    user_id:      str              # Grindr numeric user ID
    profile_id:   str              # Grindr profile ID (usually same as user_id)
    headers:      PlatformHeaders
    is_valid:     bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GrindrClient:
    """
    Thin async HTTP client for the Grindr private mobile API.

    One instance per account session. All requests route through the
    phone's local SOCKS5 proxy: socks5://127.0.0.1:8089

    Usage:
        async with GrindrClient(session) as c:
            cascade = await c.get_cascade(limit=50)
    """

    def __init__(
        self,
        session: GrindrSession,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ):
        self.session   = session
        self.proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers
        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "Authorization":       f"Grindr3 {self.session.auth_token}",
                "User-Agent":          h.user_agent,
                "Accept":              "application/json",
                "Accept-Encoding":     "gzip, deflate",
                "Accept-Language":     h.locale.replace("_", "-"),
                "Content-Type":        "application/json",
                "L-Device-Info":       _build_device_info(h),
                "L-Locale":            h.locale,
                "L-Time-Zone":         h.timezone,
                "L-App-Version":       GRINDR_APP_VERSION,
                "L-App-Build":         GRINDR_BUILD_NUMBER,
                "L-Net-Type":          GRINDR_NET_TYPE,
                "L-Require-Menu":      GRINDR_REQUIRE_MENU,
                "Connection":          "keep-alive",
            },
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "GrindrClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _get(
        self,
        endpoint: str,
        params: dict | None = None,
        v4: bool = False,
    ) -> dict:
        assert self._client, "Use 'async with GrindrClient(...) as c:'"
        base = GRINDR_V4 if v4 else GRINDR_V3
        resp = await self._client.get(
            f"{base}/{endpoint}",
            params=params or {},
        )
        self._handle_status(resp)
        return resp.json()

    async def _post(
        self,
        endpoint: str,
        json: dict | None = None,
        v4: bool = False,
    ) -> dict:
        assert self._client, "Use 'async with GrindrClient(...) as c:'"
        base = GRINDR_V4 if v4 else GRINDR_V3
        resp = await self._client.post(
            f"{base}/{endpoint}",
            json=json or {},
        )
        self._handle_status(resp)
        # Some endpoints return empty bodies (204 No Content)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    async def _delete(self, endpoint: str, v4: bool = False) -> dict:
        assert self._client, "Use 'async with GrindrClient(...) as c:'"
        base = GRINDR_V4 if v4 else GRINDR_V3
        resp = await self._client.delete(f"{base}/{endpoint}")
        self._handle_status(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def _handle_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            self.session.is_valid = False
            raise GrindrSessionExpired(
                f"Session expired for account {self.session.account_id}"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise GrindrRateLimited(
                f"Rate limited — retry after {retry_after}s",
                retry_after=retry_after,
            )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def get_cascade(self, limit: int = 50) -> dict:
        """
        Fetch the nearby profile grid (the core Grindr UI experience).

        Returns up to `limit` profiles sorted by distance.
        Response shape: {"profiles": [...], "cached": bool}
        Each profile entry includes: profileId, displayName, age, distance,
        tribes, photoHash, lastSeen, isFavorite, isTapped.
        """
        return await self._get(
            "cascade",
            params={
                "nearbyGeoHash": "",  # empty = use server-side location
                "pageNumber":    0,
                "showUnread":    "true",
                "onlineOnly":    "false",
                "photoOnly":     "false",
                "faceOnly":      "false",
                "notRecentlyChatted": "false",
                "fresh":         "true",
            },
        )

    async def view_profile(
        self,
        profile_id: str,
        dwell_ms: int = 3000,
    ) -> dict:
        """
        Fetch and record a profile view with realistic dwell time.

        Grindr tracks profile views — calling this signals to the target
        that this account visited their profile (optional notification setting).
        dwell_ms is informational for the caller to sleep after; the API call
        itself fires immediately.
        """
        result = await self._get(f"profile/{profile_id}")
        # Record the view server-side
        await self._post(
            "view",
            json={"vieweeId": profile_id, "source": "cascade"},
        )
        return result

    async def send_message(
        self,
        conversation_id: str,
        body: str,
        msg_type: str = "Text",
    ) -> dict:
        """
        Send a message to an existing conversation.

        msg_type options: "Text", "Image", "Album", "Giphy", "Video"
        Returns the sent message object.
        """
        return await self._post(
            f"chat/conversation/{conversation_id}/message",
            json={
                "type":   msg_type,
                "body":   body,
                "chatId": conversation_id,
                "guid":   _generate_uuid(),
            },
        )

    async def get_inbox(self, page: int = 1) -> dict:
        """
        Fetch the message inbox.

        Returns paginated conversation list with lastMessage and unreadCount.
        page is 1-indexed.
        """
        return await self._get(
            "chat/inbox",
            params={"page": page, "pageSize": 30},
        )

    async def get_conversation(self, conversation_id: str) -> dict:
        """
        Fetch full message history for a conversation.

        Returns: {"messages": [...], "totalCount": int}
        """
        return await self._get(
            f"chat/conversation/{conversation_id}",
            params={"pageSize": 50, "before": ""},
        )

    async def tap_profile(self, profile_id: str) -> dict:
        """
        Send a "Tap" (Grindr's like/ping mechanic).

        Taps notify the target and appear in their tap list. Lower commitment
        signal than an opening message. Used as a warm-up before messaging.
        """
        return await self._post(
            "tap",
            json={"tappedProfileId": profile_id},
        )

    async def block_profile(self, profile_id: str) -> dict:
        """
        Block a profile — removes them from cascade and prevents contact.

        Used for: targets who reply negatively, spam accounts, safety.
        """
        return await self._post(
            f"profile/{profile_id}/block",
            json={},
        )

    async def update_location(self, lat: float, lon: float) -> dict:
        """
        Spoof GPS location for the Grindr cascade radius.

        Grindr has no motion-check enforcement — a single coordinate update
        is sufficient. Call at session start and optionally drift slowly
        during long sessions to avoid static-location fingerprinting.
        """
        return await self._post(
            "location",
            json={
                "geohash": _lat_lon_to_geohash(lat, lon),
                "lat":     lat,
                "lon":     lon,
            },
        )

    async def get_profile(self, profile_id: str) -> dict:
        """
        Fetch a specific profile by ID.

        Returns full profile including bio, age, stats, photos, tribes.
        """
        return await self._get(f"profile/{profile_id}")

    async def get_inbox_list(self) -> list[dict]:
        """
        Fetch the message inbox and return a normalized list.

        Each item: {profile_id, display_name, last_message, unread_count}.

        Wraps get_inbox() for DatingChatAgent consumption. The raw response
        from get_inbox() is unwrapped here so callers get a plain list.
        """
        resp = await self.get_inbox()
        conversations = resp.get("conversations", resp.get("data", []))
        return [
            {
                "profile_id":    str(c.get("profileId", c.get("conversationId", ""))),
                "display_name":  c.get("displayName", c.get("name", "")),
                "last_message":  c.get("lastMessage", {}).get("body", "")
                                 if isinstance(c.get("lastMessage"), dict)
                                 else str(c.get("lastMessage", "")),
                "unread_count":  int(c.get("unreadCount", c.get("unread_count", 0))),
                # Preserve original keys for downstream use
                **c,
            }
            for c in conversations
        ]

    async def get_conversation_messages(self, conversation_id: str) -> list[dict]:
        """
        Fetch messages for a conversation and return a normalized list.

        Each item: {message_id, sender_id, body, timestamp}.

        Wraps get_conversation() for DatingChatAgent consumption.
        """
        resp = await self.get_conversation(conversation_id)
        messages = resp.get("messages", [])
        return [
            {
                "message_id": str(m.get("messageId", m.get("id", ""))),
                "sender_id":  str(m.get("senderId", m.get("sender_id", ""))),
                "body":       str(m.get("body", m.get("text", ""))),
                "timestamp":  m.get("timestamp", m.get("ts", "")),
                # Preserve original keys
                **m,
            }
            for m in messages
        ]

    async def ping_session(self) -> bool:
        """Lightweight session health check."""
        try:
            await self._get("chat/inbox", params={"page": 1, "pageSize": 1})
            return True
        except (GrindrSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GrindrSessionExpired(Exception):
    """Raised when Grindr returns 401 — auth_token needs refresh."""


class GrindrRateLimited(Exception):
    """Raised when Grindr returns 429 — back off and retry."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_device_info(h: PlatformHeaders) -> str:
    """
    Build the L-Device-Info header value.

    Format: "{androidId};{advertisingId};{appVersion}"
    Matches the format emitted by the real Grindr Android app.
    """
    return f"{h.android_id};{h.advertising_id};{GRINDR_APP_VERSION}"


def _lat_lon_to_geohash(lat: float, lon: float, precision: int = 7) -> str:
    """
    Encode a lat/lon pair to a geohash string (precision 7 ≈ 150m accuracy).

    Grindr uses geohash internally for its grid clustering. We encode client-
    side to match the app's behavior.
    """
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]

    bits = 0
    num_bits = 0
    even = True
    result = ""

    while len(result) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon >= mid:
                bits = (bits << 1) | 1
                lon_range[0] = mid
            else:
                bits = bits << 1
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                bits = (bits << 1) | 1
                lat_range[0] = mid
            else:
                bits = bits << 1
                lat_range[1] = mid

        even = not even
        num_bits += 1

        if num_bits == 5:
            result += base32[bits]
            bits = 0
            num_bits = 0

    return result
