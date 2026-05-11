"""
InstagramClient — private mobile API client for Instagram automation.

Uses the Instagram private API (same endpoints as the official Android app).
Every request carries the exact device headers extracted from the physical
phone's installed IG app via DeviceProfile, routed through the phone's
local SOCKS5 proxy (IPRoyal residential).

Actions implemented:
    follow          — follow a user by ID
    unfollow        — unfollow a user by ID
    like_post       — like a media item
    unlike_post     — unlike a media item
    story_view      — mark a story as seen
    send_dm         — send a direct message
    get_user_info   — fetch a user's public profile
    get_followers   — paginate a user's follower list
    get_feed        — fetch the account's home feed

Detection hardening per action:
    - All requests carry the full device header set from DeviceProfile
    - Requests route through phone's residential proxy (socks5://127.0.0.1:8089)
    - Inter-action timing is LogNormal sampled (not fixed delay)
    - Follow/unfollow ratio enforced by caller (WarmingAgent)
    - Session tokens refreshed automatically on 401

This client does NOT enforce rate limits or warming curves — that is the
WarmingAgent's responsibility. The client is a thin HTTP layer only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Any

import httpx

from .hybrid_runner import PlatformHeaders


# ---------------------------------------------------------------------------
# Instagram API constants
# ---------------------------------------------------------------------------

IG_API_BASE    = "https://i.instagram.com/api/v1"

# ---------------------------------------------------------------------------
# Valid story reaction emojis
#
# Instagram supports a wide range of story reaction emojis.  Listing the full
# supported set here so personality pools can reference any of these without
# hitting an API rejection.  Each EmojiPersonality in ig_story_react_agent
# draws from its own subset — the fleet's aggregate emoji distribution across
# all personalities therefore looks like a real diverse user population.
# ---------------------------------------------------------------------------

VALID_STORY_REACTIONS: list[str] = [
    "❤️", "🔥", "😂", "😍", "😮", "😢", "😡", "🥰", "💯", "👏",
    "🙌", "💕", "✨", "🌸", "💀", "😭", "😅", "🤣", "💪", "😤",
]

IG_SIG_KEY     = "9193488027538fd3450b83b7d05286d4ca9599572d" \
                 "10f60bb7f3fc2e5b5e0f7b"   # public sig key, static
IG_APP_ID      = "567067343352427"
IG_CAPABILITIES = "3brTvx0="
THREADS_UA_FALLBACK = "Instagram 276.0.0.29.117 Android"  # fallback for sessions without device headers
IG_CONNECTION_TYPE = "WIFI"


def _generate_uuid() -> str:
    return str(uuid.uuid4())


def _sign_payload(data: dict) -> str:
    """HMAC-SHA256 sign a request body — required by Instagram's API."""
    payload = json.dumps(data, separators=(",", ":"))
    sig = hmac.new(
        IG_SIG_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"ig_sig_key_version=4&signed_body={sig}.{payload}"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class IGSession:
    """Live authenticated session for one Instagram account."""
    account_id:    str        # our internal account ID
    ig_user_id:    str        # Instagram's numeric user ID
    username:      str
    session_id:    str        # sessionid cookie
    csrftoken:     str
    mid:           str        # machine ID cookie
    ds_user_id:    str        # same as ig_user_id usually
    headers:       Optional[PlatformHeaders] = None
    is_valid:      bool = True


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class InstagramClient:
    """
    Thin async HTTP client for the Instagram private mobile API.

    One instance per account session. Constructed by the account provisioner
    after session bootstrap, stored in the account's DB row as a serialized
    session object.

    All requests go through the phone's local SOCKS5 proxy:
        socks5://127.0.0.1:8089

    The proxy routes to IPRoyal residential — so Instagram's backend sees
    the phone's assigned residential IP, not the farm's real IP.
    """

    def __init__(self, session: IGSession, proxy_url: str = "socks5://127.0.0.1:8089"):
        self.session   = session
        self.proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    def _build_client(self) -> httpx.AsyncClient:
        h = self.session.headers  # may be None for ThreadsClient-only sessions
        return httpx.AsyncClient(
            proxy=self.proxy_url,
            headers={
                "User-Agent":                h.user_agent if h else THREADS_UA_FALLBACK,
                "X-IG-App-ID":               IG_APP_ID,
                "X-IG-Device-ID":            h.device_id if h else "",
                "X-IG-Android-ID":           h.android_id if h else "",
                "X-MID":                     h.extra.get("mid", "") if h else "",
                "X-IG-Family-Device-ID":     h.extra.get("family_device_id", _generate_uuid()) if h else _generate_uuid(),
                "X-IG-Capabilities":         IG_CAPABILITIES,
                "X-IG-Connection-Type":      IG_CONNECTION_TYPE,
                "X-IG-Timezone-Offset":      _tz_offset(h.timezone) if h else "0",
                "Accept-Language":           h.locale.replace("_", "-") if h else "en-US",
                "Accept-Encoding":           "gzip, deflate",
                "Connection":                "keep-alive",
                "Cookie": (
                    f"sessionid={self.session.session_id}; "
                    f"csrftoken={self.session.csrftoken}; "
                    f"ds_user_id={self.session.ds_user_id}; "
                    f"mid={self.session.mid}"
                ),
            },
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "InstagramClient":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helper
    # ------------------------------------------------------------------

    async def _post(self, endpoint: str, data: dict) -> dict:
        assert self._client, "Use 'async with InstagramClient(...) as c:'"
        signed = _sign_payload(data)
        resp = await self._client.post(
            f"{IG_API_BASE}/{endpoint}",
            content=signed.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code == 401:
            self.session.is_valid = False
            raise IGSessionExpired(f"Session expired for {self.session.username}")
        resp.raise_for_status()
        return resp.json()

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        assert self._client, "Use 'async with InstagramClient(...) as c:'"
        resp = await self._client.get(
            f"{IG_API_BASE}/{endpoint}",
            params=params or {},
        )
        if resp.status_code == 401:
            self.session.is_valid = False
            raise IGSessionExpired(f"Session expired for {self.session.username}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def follow(self, target_user_id: str) -> dict:
        """Follow a user. Returns API response."""
        return await self._post(
            f"friendships/create/{target_user_id}/",
            {
                "user_id":    target_user_id,
                "_uuid":      _generate_uuid(),
                "_uid":       self.session.ig_user_id,
                "_csrftoken": self.session.csrftoken,
                "radio_type": "wifi-none",
                "device_id":  self.session.headers.device_id if self.session.headers else "",
            },
        )

    async def unfollow(self, target_user_id: str) -> dict:
        """Unfollow a user."""
        return await self._post(
            f"friendships/destroy/{target_user_id}/",
            {
                "user_id":    target_user_id,
                "_uuid":      _generate_uuid(),
                "_uid":       self.session.ig_user_id,
                "_csrftoken": self.session.csrftoken,
            },
        )

    async def like_post(self, media_id: str) -> dict:
        """Like a post by media ID."""
        return await self._post(
            f"media/{media_id}/like/",
            {
                "media_id":   media_id,
                "_uuid":      _generate_uuid(),
                "_uid":       self.session.ig_user_id,
                "_csrftoken": self.session.csrftoken,
                "module_name": "feed_timeline",
                "d": "0",
            },
        )

    async def comment_post(self, media_id: str, comment_text: str) -> bool:
        """
        Post a comment on a media item.

        Uses POST /api/v1/media/{media_id}/comment/ — the same endpoint the
        Android app uses. comment_text must be < 2200 chars (IG hard limit).

        Returns True if the comment was accepted (status == "ok").

        Detection hardening:
            - comment_text comes from the niche pool in IGPodManager (200+
              entries) — never static strings.
            - Caller enforces 3 pod-comments/day cap before calling this method.
        """
        try:
            resp = await self._post(
                f"media/{media_id}/comment/",
                {
                    "comment_text": comment_text[:2200],
                    "media_id":     media_id,
                    "_uuid":        _generate_uuid(),
                    "_uid":         self.session.ig_user_id,
                    "_csrftoken":   self.session.csrftoken,
                    "user_breadcrumb": "",
                    "idempotence_token": _generate_uuid(),
                    "containermodule": "self_comments_v2",
                },
            )
            return resp.get("status") == "ok"
        except Exception:
            return False

    async def unlike_post(self, media_id: str) -> dict:
        """Unlike a post."""
        return await self._post(
            f"media/{media_id}/unlike/",
            {
                "media_id":   media_id,
                "_uuid":      _generate_uuid(),
                "_uid":       self.session.ig_user_id,
                "_csrftoken": self.session.csrftoken,
                "module_name": "feed_timeline",
            },
        )

    async def story_view(self, reel_id: str, media_ids: list[str]) -> dict:
        """Mark stories as seen. reel_id is the owner's user ID."""
        seen_payload = {
            mid: [f"{int(time.time())}_3"]
            for mid in media_ids
        }
        return await self._post(
            "media/seen/",
            {
                "reels":      json.dumps({reel_id: seen_payload}),
                "_uuid":      _generate_uuid(),
                "_uid":       self.session.ig_user_id,
                "_csrftoken": self.session.csrftoken,
                "container_module": "reel_feed_timeline",
                "reel_media_skipped": "{}",
                "live_vods_skipped": "{}",
                "nuxes_skipped": "{}",
                "nuxes": "{}",
            },
        )

    async def send_dm(self, recipient_user_id: str, text: str) -> dict:
        """Send a direct message text to a user."""
        thread_params = json.dumps({"user_ids": [recipient_user_id]})
        return await self._post(
            "direct_v2/threads/broadcast/text/",
            {
                "recipient_users": json.dumps([[recipient_user_id]]),
                "action":          "send_item",
                "is_shh_mode":     "0",
                "send_attribution": "message_button",
                "client_context":  _generate_uuid(),
                "text":            text,
                "device_id":       self.session.headers.device_id if self.session.headers else "",
                "_uuid":           _generate_uuid(),
                "_uid":            self.session.ig_user_id,
                "_csrftoken":      self.session.csrftoken,
            },
        )

    async def get_user_info(self, username: str) -> dict:
        """Fetch a user's public profile by username."""
        return await self._get(f"users/{username}/usernameinfo/")

    async def get_user_followers(
        self,
        user_id: str,
        max_id: str = "",
        count: int = 50,
    ) -> dict:
        """
        Paginate a user's follower list.
        Returns: {"users": [...], "next_max_id": "...", "big_list": bool}
        """
        params: dict[str, Any] = {
            "count": count,
            "search_surface": "follow_list_page",
            "order": "default",
            "enable_groups": "true",
        }
        if max_id:
            params["max_id"] = max_id
        return await self._get(f"friendships/{user_id}/followers/", params=params)

    async def get_following(
        self,
        user_id: str,
        max_id: str = "",
        count: int = 50,
    ) -> dict:
        """Paginate the accounts this user follows."""
        params: dict[str, Any] = {"count": count}
        if max_id:
            params["max_id"] = max_id
        return await self._get(f"friendships/{user_id}/following/", params=params)

    async def get_feed(self) -> dict:
        """Fetch the home timeline feed for this account."""
        return await self._get(
            "feed/timeline/",
            params={
                "is_pull_to_refresh": "0",
                "feed_view_info":     "[]",
                "seen_posts":         "",
                "phone_id":           self.session.headers.extra.get("phone_id", _generate_uuid()) if self.session.headers else _generate_uuid(),
                "battery_level":      "72",   # realistic static value fine here
                "timezone_offset":    _tz_offset(self.session.headers.timezone) if self.session.headers else "0",
            },
        )

    async def get_inbox(self, cursor: str = "") -> dict:
        """Fetch the DM inbox."""
        params: dict[str, Any] = {
            "visual_message_return_type": "unseen",
            "thread_message_limit":       "10",
            "persistentBadging":          "true",
            "limit":                      "20",
        }
        if cursor:
            params["cursor"] = cursor
        return await self._get("direct_v2/inbox/", params=params)

    async def ping_session(self) -> bool:
        """
        Lightweight session health check.
        Returns True if session is still valid.
        """
        try:
            resp = await self._get("accounts/current_user/", params={"edit": "true"})
            return "user" in resp
        except (IGSessionExpired, httpx.HTTPError):
            return False

    async def archive_post(self, media_id: str) -> bool:
        """
        Archive (hide from profile) a post with low ER.

        Uses POST /api/v1/media/{media_id}/only_me/
        Archived posts are hidden from the grid but not deleted.
        Returns True if the archive succeeded.
        """
        try:
            resp = await self._post(
                f"media/{media_id}/only_me/",
                {
                    "media_id":   media_id,
                    "_uuid":      _generate_uuid(),
                    "_uid":       self.session.ig_user_id,
                    "_csrftoken": self.session.csrftoken,
                },
            )
            return resp.get("status") == "ok"
        except Exception:
            return False

    async def check_hashtag_post_visibility(
        self,
        hashtag: str,
        our_media_id: str,
    ) -> bool:
        """
        Check if our post appears in a hashtag feed (shadowban check).

        Uses an unauthenticated request to the public hashtag endpoint —
        NO session cookies, NO X-IG-* auth headers.  This mirrors what a
        logged-out user would see and is the standard shadowban detection.

        Returns True if the post is visible (NOT shadowbanned).
        Returns False if the post is absent from the hashtag feed (shadowban
        likely) or if the check could not be completed.

        NOTE: This method intentionally creates its own unauthenticated
        httpx.AsyncClient, bypassing the authenticated self._client entirely.
        """
        url = (
            f"https://www.instagram.com/explore/tags/{hashtag.lstrip('#')}/"
            "?__a=1&__d=dis"
        )
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"
                    ),
                },
                # Explicitly NO Cookie header, NO X-IG-* headers
            ) as unauthed:
                resp = await unauthed.get(url)

            if resp.status_code != 200:
                return False
            return our_media_id in resp.text

        except httpx.HTTPError:
            return False

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    async def set_note(self, text: str) -> bool:
        """
        Set/update the account's Instagram Note.

        Notes appear at the top of every follower's DM list for 24 hours.
        Max 60 chars. audience=2 means visible to followers (not just
        Close Friends).

        Returns True on success.
        """
        if len(text) > 60:
            text = text[:57] + "..."
        resp = await self._post(
            "notes/create_note/",
            {
                "text":         text,
                "audience":     2,          # 2 = followers
                "_uuid":        _generate_uuid(),
                "_uid":         self.session.ig_user_id,
                "_csrftoken":   self.session.csrftoken,
            },
        )
        return resp.get("status") == "ok"

    async def delete_note(self) -> bool:
        """
        Delete the account's current Instagram Note.

        Called before setting a new note to avoid duplicate-note state on
        Instagram's server. Safe to call when no note exists — IG returns ok.

        Returns True on success.
        """
        resp = await self._post(
            "notes/delete_note/",
            {
                "_uuid":      _generate_uuid(),
                "_uid":       self.session.ig_user_id,
                "_csrftoken": self.session.csrftoken,
            },
        )
        return resp.get("status") == "ok"

    # ------------------------------------------------------------------
    # Broadcast Channels
    # ------------------------------------------------------------------

    async def create_broadcast_channel(
        self,
        title: str,
        description: str,
    ) -> dict:
        """
        Create a new Instagram Broadcast Channel.

        Returns the full API response dict (contains channel_id and metadata).
        Broadcast channels let creators send one-way messages to all subscribers.
        """
        return await self._post(
            "direct_v2/create_broadcast_channel/",
            {
                "title":        title,
                "description":  description,
                "_uuid":        _generate_uuid(),
                "_uid":         self.session.ig_user_id,
                "_csrftoken":   self.session.csrftoken,
            },
        )

    async def send_broadcast_message(
        self,
        channel_id: str,
        text: str,
    ) -> bool:
        """
        Send a text message to all subscribers of a broadcast channel.

        Returns True on success.
        """
        resp = await self._post(
            f"direct_v2/broadcast/{channel_id}/send/",
            {
                "text":         text,
                "item_type":    "text",
                "_uuid":        _generate_uuid(),
                "_uid":         self.session.ig_user_id,
                "_csrftoken":   self.session.csrftoken,
            },
        )
        return resp.get("status") == "ok"

    async def invite_to_broadcast(
        self,
        channel_id: str,
        user_ids: list[str],
    ) -> bool:
        """
        Invite users to join a broadcast channel.

        user_ids: list of Instagram numeric user ID strings.
        Returns True on success.
        """
        resp = await self._post(
            f"direct_v2/broadcast/{channel_id}/invite/",
            {
                "user_ids":     json.dumps(user_ids),
                "_uuid":        _generate_uuid(),
                "_uid":         self.session.ig_user_id,
                "_csrftoken":   self.session.csrftoken,
            },
        )
        return resp.get("status") == "ok"

    async def get_broadcast_subscribers(
        self,
        channel_id: str,
    ) -> list[dict]:
        """
        Get the list of subscribers for a broadcast channel.

        Returns a list of user dicts (ig_user_id, username, follower_count, etc.)
        """
        resp = await self._get(
            f"direct_v2/broadcast/{channel_id}/subscribers/",
        )
        return resp.get("subscribers", [])

    # ------------------------------------------------------------------
    # Optimization feature endpoints
    # ------------------------------------------------------------------

    async def get_post_insights(self, media_id: str) -> dict:
        """
        Get reach, impression, and save data for a post.

        Returns a dict with at least:
            {
                "reach":       int,
                "impressions": int,
                "saved":       int,
                "likes":       int,
                "comments":    int,
            }

        Used by IGHashtagTrackerAgent to estimate per-post reach for
        attribution and by IGPeakTimeAgent to compute engagement rate.
        """
        return await self._get(f"media/{media_id}/insights/")

    async def update_profile(
        self,
        biography: str | None = None,
        full_name: str | None = None,
    ) -> bool:
        """
        Update account bio and/or display name.

        Sends a POST to the edit_profile endpoint. Only fields that are not
        None are included in the payload — callers can update just the bio
        without touching the display name and vice versa.

        Returns True on success (status == "ok").

        Used by IGBioABAgent to apply winning variants to cohort accounts.
        """
        if biography is None and full_name is None:
            raise ValueError("update_profile: at least one of biography or full_name must be set")

        payload: dict = {
            "_uuid":      _generate_uuid(),
            "_uid":       self.session.ig_user_id,
            "_csrftoken": self.session.csrftoken,
        }
        if biography is not None:
            payload["biography"] = biography
        if full_name is not None:
            payload["full_name"] = full_name

        resp = await self._post("accounts/edit_profile/", payload)
        return resp.get("status") == "ok"

    # ------------------------------------------------------------------
    # Story mentions
    # ------------------------------------------------------------------

    async def get_story_mentions(self) -> list[dict]:
        """
        Fetch accounts that mentioned this account in their stories.

        Reads the news/activity inbox and filters for story_mention activity.
        Returns a list of dicts:
            [{
                "mentioner_user_id": str,
                "mentioner_username": str,
                "mentioner_follower_count": int,
                "story_pk": str,
                "media_url": str,
            }, ...]
        """
        resp = await self._get(
            "news/inbox/",
            params={"mark_as_seen": "false"},
        )
        stories = resp.get("new_stories", []) + resp.get("old_stories", [])
        mentions: list[dict] = []
        for item in stories:
            args = item.get("args", {})
            if item.get("type") != 202:          # 202 = story mention activity type
                # Also accept string-typed variants from IG's inconsistent responses
                inline_items = args.get("inline_follow_up_items", [])
                story_type_found = False
                for sub in inline_items:
                    if sub.get("type") == 202:
                        story_type_found = True
                        break
                if not story_type_found and item.get("type") not in (202, "story_mention"):
                    continue
            media = args.get("media", {})
            user = args.get("profile_user", [{}])
            user = user[0] if isinstance(user, list) and user else user
            media_url = (
                media.get("image_versions2", {})
                    .get("candidates", [{}])[0]
                    .get("url", "")
            )
            mentions.append({
                "mentioner_user_id":       str(user.get("id", "")),
                "mentioner_username":      user.get("username", ""),
                "mentioner_follower_count": int(user.get("follower_count", 0)),
                "story_pk":                str(media.get("pk", "")),
                "media_url":               media_url,
            })
        return mentions

    async def react_to_story(
        self,
        reel_id: str,
        media_id: str,
        reaction_emoji: str,
    ) -> bool:
        """
        Send an emoji reaction to a story. Appears as a DM to the creator.

        This is the highest-conversion touchpoint in the Follow+Story flow.
        A story reaction triggers a DM notification to the creator — more
        intimate than a silent view, less pushy than a cold DM.

        reel_id: the story owner's Instagram user ID
        media_id: the specific story item's media ID
        reaction_emoji: one of the approved emoji from REACTION_POOL
        """
        try:
            resp = await self._post(
                f"media/{media_id}/story_reaction/",
                {
                    "reaction_emoji":   reaction_emoji,
                    "reel_id":          reel_id,
                    "module_name":      "story_viewer",
                    "_uuid":            _generate_uuid(),
                    "_uid":             self.session.ig_user_id,
                    "_csrftoken":       self.session.csrftoken,
                    "container_module": "reel_viewer_default",
                },
            )
            return resp.get("status") == "ok"
        except (IGSessionExpired, IGRateLimited, IGActionBlocked):
            raise
        except Exception:
            return False

    async def repost_story_mention(
        self,
        story_pk: str,
        text_overlay: str | None = None,
    ) -> bool:
        """
        Repost a story that mentioned us as our own story.

        Optionally adds a text overlay (thank-you message) before posting.
        Routes through the private /media/share/ endpoint — the same path
        the native IG app uses for resharing a mention.

        Returns True on success.
        """
        payload: dict = {
            "story_pk":         story_pk,
            "recipient_users":  "[]",
            "thread_ids":       "[]",
            "story_type":       "reshare",
            "_uuid":            _generate_uuid(),
            "_uid":             self.session.ig_user_id,
            "_csrftoken":       self.session.csrftoken,
        }
        if text_overlay:
            payload["overlay_text"] = text_overlay
        resp = await self._post(
            f"media/{story_pk}/share_to_story/",
            payload,
        )
        return resp.get("status") == "ok"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IGSessionExpired(Exception):
    """Raised when Instagram returns 401 — session needs refresh."""


class IGRateLimited(Exception):
    """Raised when Instagram returns 429 — back off and retry."""


class IGActionBlocked(Exception):
    """Raised when Instagram blocks a specific action (follow block, DM block)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tz_offset(timezone: str) -> str:
    """Convert timezone string to UTC offset in seconds (approximate)."""
    # Common US timezone offsets — extend as needed
    offsets = {
        "America/New_York":    "-18000",
        "America/Chicago":     "-21600",
        "America/Denver":      "-25200",
        "America/Los_Angeles": "-28800",
        "America/Phoenix":     "-25200",
        "Europe/London":       "0",
        "Europe/Paris":        "3600",
    }
    return offsets.get(timezone, "-18000")   # default EST
