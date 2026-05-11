"""
HingeClient — private API client for Hinge automation.

Security profile: STRICTEST of the four dating platforms.
    - Lowest retry allowance (2 photo-verification attempts before 24h block)
    - Hardware-backed Play Integrity attestation
    - Like system (not swipe): like a specific content item (photo/prompt)
      with optional comment — more expressive than Tinder swipe
    - Roses = premium super-likes; do not use unless account has credits
    - HingeVerificationRequired raised for any action attempted while
      account is in verification-pending state — do not retry blindly

API structure:
    - Base: https://prod-api.hingeaws.net
    - Auth: "Authorization: Bearer {auth_token}" header
    - JSON throughout
    - Like endpoint requires: subject_id (target user), content_id (which
      photo or prompt was liked), optional comment string

Routing: socks5://127.0.0.1:8089

This client is a thin HTTP layer. Rate limit enforcement and like budgets
are the DatingSwipeAgent's responsibility.
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

HINGE_API_BASE    = "https://prod-api.hingeaws.net"
HINGE_APP_VERSION = "9.62.0"
HINGE_PLATFORM    = "ios"      # iOS fingerprint — lower detection surface than Android


def _generate_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class HingeSession:
    """Live authenticated session for one Hinge account."""
    account_id:  str              # internal account ID
    auth_token:  str              # Hinge Bearer token (JWT)
    user_id:     str              # Hinge user ID
    headers:     PlatformHeaders
    is_valid:    bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class HingeClient:
    """
    Thin async HTTP client for the Hinge private mobile API.

    One instance per account session. All requests route through the
    phone's local SOCKS5 proxy: socks5://127.0.0.1:8089

    CAUTION — Hinge has the STRICTEST trust-score system:
        - 2 failed photo verifications = 24h verification block
        - Swipe-like pattern analysis flags accounts with static like rates
        - Rapid-fire likes without comment are distinguished from human use

    Usage:
        async with HingeClient(session) as c:
            stack = await c.get_discover()
    """

    def __init__(
        self,
        session: HingeSession,
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
                "Authorization":     f"Bearer {self.session.auth_token}",
                "User-Agent":        h.user_agent,
                "Accept":            "application/json",
                "Content-Type":      "application/json",
                "Accept-Encoding":   "gzip, deflate",
                "Accept-Language":   h.locale.replace("_", "-"),
                "X-App-Version":     HINGE_APP_VERSION,
                "X-Device-Platform": HINGE_PLATFORM,
                "X-Device-Id":       h.device_id,
                "X-Idfa":            h.advertising_id,
                "Connection":        "keep-alive",
            },
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "HingeClient":
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
        assert self._client, "Use 'async with HingeClient(...) as c:'"
        resp = await self._client.get(
            f"{HINGE_API_BASE}/{endpoint}",
            params=params or {},
        )
        self._handle_status(resp)
        return resp.json()

    async def _post(self, endpoint: str, json: dict | None = None) -> dict:
        assert self._client, "Use 'async with HingeClient(...) as c:'"
        resp = await self._client.post(
            f"{HINGE_API_BASE}/{endpoint}",
            json=json or {},
        )
        self._handle_status(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    async def _delete(self, endpoint: str) -> dict:
        assert self._client, "Use 'async with HingeClient(...) as c:'"
        resp = await self._client.delete(f"{HINGE_API_BASE}/{endpoint}")
        self._handle_status(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def _handle_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            self.session.is_valid = False
            raise HingeSessionExpired(
                f"Session expired for account {self.session.account_id}"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise HingeRateLimited(
                f"Rate limited — retry after {retry_after}s",
                retry_after=retry_after,
            )
        if resp.status_code == 403:
            try:
                data = resp.json()
                error_code = data.get("error_code", "")
                message = data.get("message", "")
            except Exception:
                error_code = ""
                message = ""
            # Hinge uses specific error codes for verification state
            if "verification" in message.lower() or error_code in (
                "PHOTO_VERIFICATION_REQUIRED",
                "IDENTITY_VERIFICATION_REQUIRED",
            ):
                raise HingeVerificationRequired(
                    f"Verification required for account {self.session.account_id}: "
                    f"{error_code} — {message}"
                )
            raise HingeActionBlocked(
                f"Action blocked for account {self.session.account_id}: {message}"
            )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def get_discover(self) -> dict:
        """
        Fetch the discovery stack (Hinge's equivalent of swipe recommendations).

        Returns a list of profile objects. Each profile includes:
        subject_id, display_name, age, distance_mi, content items.

        Content items are the individual photos and prompt answers that can
        be individually liked. Each has a content_id used in like_content().

        Note: Hinge does not expose a simple "count" param — it returns a
        server-determined batch size (typically 10-15 profiles).
        """
        return await self._get("discover")

    async def like_content(
        self,
        subject_id: str,
        content_id: str,
        comment: Optional[str] = None,
    ) -> dict:
        """
        Like a specific content item on a profile (photo or prompt answer).

        subject_id: the target user's Hinge user ID.
        content_id: the specific photo or prompt content ID being liked.
        comment: optional string to attach to the like (max ~150 chars).

        Hinge's core mechanic requires liking a SPECIFIC content item rather
        than swiping on the whole profile. Including a comment significantly
        increases match rate — use with 30% probability per DatingSwipeAgent.

        Returns: {"like_id": str, "is_match": bool, "match": {...} | null}
        """
        body: dict = {
            "subject_id": subject_id,
            "content_id": content_id,
            "liked_content_id": content_id,
        }
        if comment:
            body["comment"] = comment[:150]  # hard cap to API limit

        return await self._post("like", json=body)

    async def pass_profile(self, subject_id: str) -> dict:
        """
        Pass (skip) a profile in the discovery stack.

        Returns: {} (204 No Content on success)
        """
        return await self._post(
            "pass",
            json={"subject_id": subject_id},
        )

    async def get_matches(self) -> dict:
        """
        Fetch the list of mutual matches.

        Returns: {"matches": [...]}
        Each match includes: match_id, subject (profile), conversation (messages).
        """
        return await self._get("match")

    async def send_message(self, match_id: str, body: str) -> dict:
        """
        Send a text message within a match conversation.

        Returns: the created message object.
        """
        return await self._post(
            f"match/{match_id}/message",
            json={
                "body":       body,
                "message_id": _generate_uuid(),
            },
        )

    async def get_conversation(self, match_id: str) -> dict:
        """
        Fetch full conversation history for a match.

        Returns: {"messages": [...], "match": {...}}
        Messages ordered oldest first.
        """
        return await self._get(f"match/{match_id}/message")

    async def update_location(self, lat: float, lon: float) -> dict:
        """
        Update the account's GPS location.

        Hinge uses location for distance display and discovery radius.
        """
        return await self._post(
            "location",
            json={
                "lat": lat,
                "lon": lon,
            },
        )

    async def get_match_messages(self, match_id: str) -> list[dict]:
        """
        Fetch full ordered message list for a match conversation.

        Returns messages sorted oldest-first (same as get_conversation).
        This is the DatingChatAgent-facing interface name — delegates to
        get_conversation() which returns {"messages": [...], "match": {...}}.
        """
        resp = await self.get_conversation(match_id)
        return resp.get("messages", [])

    async def get_self(self) -> dict:
        """Fetch this account's own profile."""
        return await self._get("me")

    async def ping_session(self) -> bool:
        """Lightweight session health check."""
        try:
            await self._get("me")
            return True
        except (HingeSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HingeSessionExpired(Exception):
    """Raised when Hinge returns 401 — auth_token needs refresh."""


class HingeRateLimited(Exception):
    """Raised when Hinge returns 429 — back off and retry."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class HingeVerificationRequired(Exception):
    """
    Raised when Hinge requires photo verification before continuing.

    Hinge allows only 2 verification attempts before a 24h cooldown.
    Caller MUST check this and route to PhotoVerificationOrchestrator
    before retrying any action.
    """


class HingeActionBlocked(Exception):
    """
    Raised when Hinge returns 403 for a non-verification reason.

    May indicate: like limit exhausted, account in review, account banned.
    """
