"""
BumbleClient — private API client for Bumble automation.

Security profile: HIGH.
    - Photo verification via iProov / FaceMatch liveness (blink, nod, smile)
    - Play Integrity checked on Android
    - Women-first UX: female accounts can message first, male accounts must wait
    - Binary-ish RPC over HTTP POST — all requests go to a single PHTML endpoint
      with action/version/body structure rather than distinct REST paths

API structure:
    - Base: https://bumble.com/mwebapi.phtml
    - All requests: POST to the same URL with different "body" action IDs
    - Auth: token in the "token" field of the request body (not a header)
    - Also requires "session_id" per-request token (CSRF-like)
    - Response: {"body": [{...}], "message_type": int, "payload": {...}}

Routing: socks5://127.0.0.1:8089

This client is a thin HTTP layer. Rate limit enforcement and swipe budgets
are the DatingSwipeAgent's responsibility.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUMBLE_API_BASE    = "https://bumble.com/mwebapi.phtml"
BUMBLE_APP_VERSION = "6.7.0"
BUMBLE_PLATFORM    = "android"

# Bumble RPC server message types (action IDs)
# These correspond to the numeric IDs used in the binary RPC layer
MSG_TYPE_ENCOUNTERS  = 81   # get swipe stack
MSG_TYPE_VOTE        = 80   # like / pass
MSG_TYPE_CONNECTIONS = 245  # get matches
MSG_TYPE_SEND_MSG    = 102  # send chat message
MSG_TYPE_CHAT        = 101  # get chat history
MSG_TYPE_LOCATION    = 51   # update location
MSG_TYPE_USER        = 244  # get own profile


def _generate_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class BumbleSession:
    """Live authenticated session for one Bumble account."""
    account_id:  str              # internal account ID
    token:       str              # Bumble auth token (long-lived JWT)
    user_id:     str              # Bumble user ID
    headers:     PlatformHeaders
    is_valid:    bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class BumbleClient:
    """
    Thin async HTTP client for the Bumble private mobile API.

    Bumble uses a custom binary-ish RPC protocol over HTTP POST. All requests
    hit the same URL (mwebapi.phtml) with a body containing:
        - server_message_type: int (which action to perform)
        - body: list of action-specific payload dicts
        - token: auth token
        - version: API version string

    One instance per account session. All requests route through the
    phone's local SOCKS5 proxy: socks5://127.0.0.1:8089

    Usage:
        async with BumbleClient(session) as c:
            encounters = await c.get_encounters()
    """

    def __init__(
        self,
        session: BumbleSession,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ):
        self.session    = session
        self.proxy_url  = proxy_url
        self._client: Optional[httpx.AsyncClient] = None
        self._request_id: int = 0   # monotonically increments per request

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers
        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "User-Agent":      h.user_agent,
                "Accept":          "application/json",
                "Content-Type":    "application/json;charset=utf-8",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": h.locale.replace("_", "-"),
                "X-App-Version":   BUMBLE_APP_VERSION,
                "X-Platform":      BUMBLE_PLATFORM,
                "Connection":      "keep-alive",
            },
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "BumbleClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core RPC helper
    # ------------------------------------------------------------------

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _rpc(
        self,
        server_message_type: int,
        body: list[dict],
    ) -> dict:
        """
        Send a Bumble RPC call.

        All Bumble API actions are POST requests to the same endpoint
        with a server_message_type discriminator and a body list.
        """
        assert self._client, "Use 'async with BumbleClient(...) as c:'"

        payload = {
            "body":                [
                {**b, "message_type": server_message_type}
                for b in body
            ],
            "message_type":        server_message_type,
            "version":             1,
            "is_background":       False,
            "token":               self.session.token,
            "request_id":         _generate_uuid(),
            "device_info": {
                "platform_id":   3,          # 3 = Android
                "app_version":   BUMBLE_APP_VERSION,
                "device_id":     self.session.headers.device_id,
            },
        }

        resp = await self._client.post(BUMBLE_API_BASE, json=payload)
        self._handle_status(resp)

        data = resp.json()
        # Unwrap the standard Bumble response envelope
        return self._unwrap(data, server_message_type)

    def _unwrap(self, data: dict, expected_type: int) -> dict:
        """
        Unwrap Bumble's response envelope.

        Bumble wraps responses as:
          {"body": [{"message_type": N, ...payload...}]}
        We return the first body item's payload dict.
        """
        bodies = data.get("body", [])
        if not bodies:
            return data
        first = bodies[0]
        # Remove the message_type discriminator key before returning
        return {k: v for k, v in first.items() if k != "message_type"}

    def _handle_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            self.session.is_valid = False
            raise BumbleSessionExpired(
                f"Session expired for account {self.session.account_id}"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise BumbleRateLimited(
                f"Rate limited — retry after {retry_after}s",
                retry_after=retry_after,
            )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def get_encounters(self) -> dict:
        """
        Fetch the swipe stack (Bumble calls them "encounters").

        Returns a list of user objects, each including:
        user_id, name, age, distance, profile_photo, interests.
        """
        return await self._rpc(
            MSG_TYPE_ENCOUNTERS,
            body=[{
                "is_swipe_mode": True,
                "context":       "PEOPLE",
                "count":         10,
            }],
        )

    async def vote(
        self,
        user_id: str,
        direction: Literal["yes", "no"],
        is_superswipe: bool = False,
    ) -> dict:
        """
        Vote on a profile — "yes" = like, "no" = pass.

        is_superswipe: True to use a SuperSwipe (premium feature, consumes credits).

        Returns: {"match": bool, "match_id": str | null}
        When direction=="yes" and the target already liked back, match=True.
        """
        vote_map = {"yes": 1, "no": 2}
        return await self._rpc(
            MSG_TYPE_VOTE,
            body=[{
                "person_id":     user_id,
                "vote":          vote_map[direction],
                "is_super_like": is_superswipe,
            }],
        )

    async def get_connections(self) -> dict:
        """
        Fetch the connections (matches) list.

        Returns: {"connections": [...]}
        Each connection includes: connection_id, user (profile), unread_count,
        last_message.
        """
        return await self._rpc(
            MSG_TYPE_CONNECTIONS,
            body=[{
                "offset":       0,
                "count":        30,
                "connection_type": 0,  # 0 = all connections
            }],
        )

    async def send_message(
        self,
        connection_id: str,
        message_type: str = "TEXT",
        body: str = "",
    ) -> dict:
        """
        Send a message within a connection (match) conversation.

        message_type options: "TEXT", "PHOTO", "GIF", "QUESTION"
        Returns: the created message object.
        """
        return await self._rpc(
            MSG_TYPE_SEND_MSG,
            body=[{
                "uid":          connection_id,
                "type":         message_type,
                "body":         body,
                "client_msg_id": _generate_uuid(),
            }],
        )

    async def get_chat(self, connection_id: str) -> dict:
        """
        Fetch message history for a connection.

        Returns: {"messages": [...], "has_more": bool}
        """
        return await self._rpc(
            MSG_TYPE_CHAT,
            body=[{
                "uid":      connection_id,
                "offset":   0,
                "count":    50,
            }],
        )

    async def update_location(self, lat: float, lon: float) -> dict:
        """
        Update the account's GPS location.

        Bumble uses location for swipe radius and distance display.
        """
        return await self._rpc(
            MSG_TYPE_LOCATION,
            body=[{
                "location": {
                    "lat": lat,
                    "lon": lon,
                    "alt": 0.0,
                },
                "accuracy": 15.0,  # realistic GPS accuracy in meters
            }],
        )

    async def get_conversations(self) -> list[dict]:
        """
        Fetch the list of active conversations (alias for get_connections).

        Returns a list of connection objects, each with:
        connection_id, person_name, last_message_text, has_unread.

        This is the DatingChatAgent-facing interface — use get_connections()
        for the raw RPC response.
        """
        resp = await self.get_connections()
        connections = resp.get("connections", [])
        return [
            {
                "conversation_id": str(c.get("connection_id", c.get("uid", ""))),
                "person_name":     c.get("user", {}).get("name", ""),
                "last_message_text": (
                    c.get("last_message", {}).get("body", "")
                    if isinstance(c.get("last_message"), dict)
                    else str(c.get("last_message", ""))
                ),
                "has_unread": bool(c.get("unread_count", 0)),
                # Preserve original fields for downstream use
                **c,
            }
            for c in connections
        ]

    async def get_messages(self, conversation_id: str) -> list[dict]:
        """
        Fetch message history for a connection conversation.

        Returns a list of message objects ordered from oldest to newest.
        Wraps get_chat() and unwraps the 'messages' list.
        """
        resp = await self.get_chat(conversation_id)
        return resp.get("messages", [])

    async def get_self(self) -> dict:
        """Fetch this account's own profile."""
        return await self._rpc(
            MSG_TYPE_USER,
            body=[{}],
        )

    async def ping_session(self) -> bool:
        """Lightweight session health check."""
        try:
            await self.get_self()
            return True
        except (BumbleSessionExpired, httpx.HTTPError):
            return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BumbleSessionExpired(Exception):
    """Raised when Bumble returns 401 — token needs refresh."""


class BumbleRateLimited(Exception):
    """Raised when Bumble returns 429 — back off and retry."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after
