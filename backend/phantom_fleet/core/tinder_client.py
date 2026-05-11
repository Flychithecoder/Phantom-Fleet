"""
TinderClient — private API client for Tinder automation.

Security profile: HIGH.
    - SafetyNet / Play Integrity checked on every launch
    - Photo verification via Onfido 3-step liveness (turn, smile, forward)
    - Strict swipe pattern analysis (bots swipe too uniformly)
    - s_number is an anti-replay token per recommendation — must be echoed back
    - Sessions expire frequently; token refresh via phone-issued flow

API structure:
    - Base: https://api.gotinder.com
    - Auth: "X-Auth-Token: {auth_token}" header
    - JSON throughout
    - Swipe endpoints require s_number (per-profile anti-replay token)

Routing: socks5://127.0.0.1:8089

This client is a thin HTTP layer. Rate limit enforcement, swipe budgets, and
bezier swipe biometrics are the DatingSwipeAgent's responsibility.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TINDER_API_BASE    = "https://api.gotinder.com"
TINDER_APP_VERSION = "14.21.0"
TINDER_PLATFORM    = "ios"      # iOS client fingerprint — lower detection than Android


def _generate_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class TinderSession:
    """Live authenticated session for one Tinder account."""
    account_id:  str              # internal account ID
    auth_token:  str              # Tinder X-Auth-Token
    user_id:     str              # Tinder user ID
    headers:     PlatformHeaders
    is_valid:    bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TinderClient:
    """
    Thin async HTTP client for the Tinder private mobile API.

    One instance per account session. All requests route through the
    phone's local SOCKS5 proxy: socks5://127.0.0.1:8089

    Usage:
        async with TinderClient(session) as c:
            recs = await c.get_recs(count=10)
    """

    def __init__(
        self,
        session: TinderSession,
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
                "X-Auth-Token":      self.session.auth_token,
                "User-Agent":        h.user_agent,
                "Accept":            "application/json",
                "Content-Type":      "application/json",
                "Accept-Encoding":   "gzip, deflate",
                "Accept-Language":   h.locale.replace("_", "-"),
                "app-version":       TINDER_APP_VERSION,
                "platform":          TINDER_PLATFORM,
                "X-Supported-Image-Formats": "webp,jpeg",
                "Connection":        "keep-alive",
            },
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "TinderClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        assert self._client, "Use 'async with TinderClient(...) as c:'"
        resp = await self._client.get(
            f"{TINDER_API_BASE}/{endpoint}",
            params=params or {},
        )
        self._handle_status(resp)
        return resp.json()

    async def _post(self, endpoint: str, json: dict | None = None) -> dict:
        assert self._client, "Use 'async with TinderClient(...) as c:'"
        resp = await self._client.post(
            f"{TINDER_API_BASE}/{endpoint}",
            json=json or {},
        )
        self._handle_status(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def _handle_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            self.session.is_valid = False
            raise TinderSessionExpired(
                f"Session expired for account {self.session.account_id}"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise TinderRateLimited(
                f"Rate limited — retry after {retry_after}s",
                retry_after=retry_after,
            )
        if resp.status_code == 403:
            try:
                data = resp.json()
                reason = data.get("error", {}).get("message", "")
            except Exception:
                reason = ""
            raise TinderActionBlocked(
                f"Action blocked for account {self.session.account_id}: {reason}"
            )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def get_recs(self, count: int = 10) -> dict:
        """
        Fetch the recommendation (swipe) stack.

        Returns up to `count` profiles. Each profile entry includes:
        type, user (id, name, photos, bio, distance_mi, s_number, content_hash).

        s_number MUST be preserved and passed back to swipe_like/swipe_pass.
        It is a per-profile anti-replay token that expires.
        """
        return await self._get(
            "v2/recs/core",
            params={"count": count},
        )

    async def swipe_like(
        self,
        user_id: str,
        s_number: int,
        photo_id: str,
    ) -> dict:
        """
        Right-swipe (like) a profile.

        s_number: anti-replay token from get_recs response — required.
        photo_id: the photo shown during the swipe, from the profile's photo list.

        Returns: {"match": bool, "likes_remaining": int, "match": {...} | null}
        A match dict is returned when the swipe results in a mutual match.
        """
        return await self._get(
            f"like/{user_id}",
            params={
                "s_number":  s_number,
                "photoId":   photo_id,
                "content_hash": "",
                "super_like_type": "banner",
            },
        )

    async def swipe_pass(self, user_id: str, s_number: int) -> dict:
        """
        Left-swipe (pass) a profile.

        s_number: anti-replay token from get_recs response — required.
        Returns: {"status": 200}
        """
        return await self._get(
            f"pass/{user_id}",
            params={"s_number": s_number},
        )

    async def get_matches(
        self,
        count: int = 60,
        page_token: str = "",
    ) -> dict:
        """
        Fetch the matches list.

        page_token: opaque pagination cursor from previous response.
        Returns: {"matches": [...], "next_page_token": str}
        Each match includes: id, person (user object), last_activity_date, messages.
        """
        params: dict = {"count": count, "message": 1, "is_tinder_u": False}
        if page_token:
            params["page_token"] = page_token
        return await self._get("v2/matches", params=params)

    async def send_message(self, match_id: str, message: str) -> dict:
        """
        Send a text message within a match conversation.

        match_id: from get_matches() response, format "{user_a_id}{user_b_id}".
        Returns: the created message object including id, sent_date, message.
        """
        return await self._post(
            f"user/matches/{match_id}",
            json={"message": message},
        )

    async def get_messages(
        self,
        match_id: str,
        count: int = 100,
    ) -> dict:
        """
        Fetch message history for a match.

        Returns: {"messages": [...], "next_page_token": str | null}
        Messages ordered newest first.
        """
        return await self._get(
            f"v2/matches/{match_id}/messages",
            params={"count": count},
        )

    async def update_location(self, lat: float, lon: float) -> dict:
        """
        Update the account's GPS location.

        Tinder uses this for distance calculations and recommendation radius.
        Motion-sync the drift across a session to avoid static-location flags.
        """
        return await self._post(
            "user/ping",
            json={
                "lat": lat,
                "lon": lon,
            },
        )

    async def boost_profile(self) -> dict:
        """
        Trigger a Boost (increases profile visibility for 30 min).

        Consumes one Boost credit from the account's balance.
        Returns: {"expires_at": ISO timestamp}
        """
        return await self._post("boost", json={})

    async def get_self(self) -> dict:
        """Fetch this account's own profile."""
        return await self._get("v2/profile")

    async def get_matches_list(
        self,
        count: int = 60,
        page_token: str = "",
    ) -> list[dict]:
        """
        Fetch matches and return a normalized list.

        Each item: {match_id, person_id, person_name, last_message, is_new_match}.

        Wraps get_matches() for DatingChatAgent consumption.
        """
        resp = await self.get_matches(count=count, page_token=page_token)
        matches = resp.get("data", {}).get("matches", resp.get("matches", []))
        result = []
        for m in matches:
            person = m.get("person", {})
            messages = m.get("messages", [])
            last_msg = messages[0].get("message", "") if messages else ""
            result.append({
                "match_id":     str(m.get("id", "")),
                "person_id":    str(person.get("_id", person.get("id", ""))),
                "person_name":  person.get("name", ""),
                "last_message": last_msg,
                "is_new_match": bool(m.get("is_new_match", not bool(messages))),
                # Preserve original match dict for downstream use
                **m,
            })
        return result

    async def get_messages_list(
        self,
        match_id: str,
        count: int = 100,
    ) -> list[dict]:
        """
        Fetch messages for a match and return a normalized list.

        Each item: {_id, from_id, message, sent_date}.

        Wraps get_messages() and normalizes field names.
        """
        resp = await self.get_messages(match_id, count=count)
        messages = resp.get("data", {}).get("messages", resp.get("messages", []))
        return [
            {
                "_id":       str(m.get("_id", m.get("id", ""))),
                "from_id":   str(m.get("from", m.get("from_id", ""))),
                "message":   str(m.get("message", m.get("body", ""))),
                "sent_date": m.get("sent_date", m.get("timestamp", "")),
                # Preserve original keys
                **m,
            }
            for m in messages
        ]

    async def ping_session(self) -> bool:
        """Lightweight session health check."""
        try:
            await self._get("v2/profile", params={})
            return True
        except (TinderSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TinderSessionExpired(Exception):
    """Raised when Tinder returns 401 — auth_token needs refresh."""


class TinderRateLimited(Exception):
    """Raised when Tinder returns 429 — back off and retry."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class TinderActionBlocked(Exception):
    """
    Raised when Tinder returns 403 — specific action blocked.

    Common causes: like limit exhausted, swipe block from pattern detection,
    account in a restricted state post-verification-fail.
    """
