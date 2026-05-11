"""
Threads private API client — shares IGSession, uses Threads App ID header.

Architecture:
    Threads is Meta's Instagram-adjacent app. It shares the same auth infrastructure
    as Instagram: same sessionid cookie, same csrftoken, same device fingerprint.
    The only differences at the API layer are:
        - X-IG-App-ID: 238260118697367  (Threads app, not IG app 567067343352427)
        - User-Agent: Barcelona 320.0.0.0.30 Android  (Threads UA)
        - Some Threads-specific endpoints

    This means every Threads account IS an Instagram account — you provision IG,
    Threads comes free. We just need to onboard (accept ToS, set profile link).

Key endpoints:
    POST /api/v1/media/configure_text_post_app_feed/   — text post
    POST /api/v1/friendships/create/{user_id}/         — follow
    POST /api/v1/friendships/destroy/{user_id}/        — unfollow
    POST /api/v1/media/{media_id}/like/                — like
    GET  /api/v1/feed/user/{user_id}/                  — user timeline
    GET  /api/v1/feed/timeline/                        — home timeline
    POST /api/v1/accounts/edit/                        — update profile (bio/link)
    POST /barista_graphql/                             — onboarding/registration check
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

from .instagram_client import IGSession, IGSessionExpired, IGRateLimited, IGActionBlocked

log = logging.getLogger("phantom_fleet.threads_client")

THREADS_APP_ID  = "238260118697367"
THREADS_UA      = "Barcelona 320.0.0.0.30 Android"
THREADS_BASE    = "https://i.instagram.com/api/v1/"


class ThreadsSessionExpired(Exception): ...
class ThreadsRateLimited(Exception):
    def __init__(self, retry_after_sec: int = 300):
        self.retry_after_sec = retry_after_sec
class ThreadsActionBlocked(Exception): ...


@dataclass
class ThreadsProfile:
    """Profile fields for a Threads account."""
    bio:         str = ""
    external_url: str = ""  # Telegram channel URL — never OnlyFans direct (flagged by Meta)
    display_name: str = ""


class ThreadsClient:
    """
    Threads private API client.

    Uses the same IGSession as InstagramClient — same cookies, same device fingerprint.
    Only the App ID header and User-Agent differ.

    Usage:
        async with ThreadsClient(session=ig_session, proxy_url=proxy_url) as client:
            await client.onboard(bio="...", funnel_url="https://...")
            await client.post_text("Hello from Threads!")
    """

    def __init__(self, session: IGSession, proxy_url: Optional[str] = None):
        self._session  = session
        self._proxy    = proxy_url
        self._http: Optional[httpx.AsyncClient] = None

    def _build_headers(self) -> dict:
        s = self._session
        h = s.headers
        return {
            "User-Agent":               THREADS_UA,
            "X-IG-App-ID":              THREADS_APP_ID,
            "X-CSRFToken":              s.csrftoken,
            "X-MID":                    s.mid,
            "X-IG-Device-ID":           h.device_id if h else "",
            "X-IG-Android-ID":          h.android_id if h else "",
            "X-IG-Connection-Type":     "WIFI",
            "X-IG-Capabilities":        "3brTvwE=",
            "Accept-Language":          h.locale.replace("_", "-") if h else "en-US",
            "Content-Type":             "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept":                   "*/*",
            "Cookie": (
                f"sessionid={s.session_id}; "
                f"csrftoken={s.csrftoken}; "
                f"mid={s.mid}; "
                f"ds_user_id={s.ds_user_id}"
            ),
        }

    async def __aenter__(self) -> "ThreadsClient":
        transport = httpx.AsyncHTTPTransport(retries=1)
        self._http = httpx.AsyncClient(
            headers=self._build_headers(),
            proxy=self._proxy if self._proxy else None,
            transport=transport,
            timeout=httpx.Timeout(connect=10, read=30, write=15, pool=5),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def _post(self, endpoint: str, data: dict) -> dict:
        assert self._http is not None, "Use 'async with ThreadsClient(...) as client'"
        resp = await self._http.post(THREADS_BASE + endpoint, data=data)
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", "300"))
            raise ThreadsRateLimited(retry_after_sec=retry)
        if resp.status_code in (401, 403):
            raise ThreadsSessionExpired()
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") == "fail":
            msg = body.get("message", "")
            if "challenge" in msg.lower() or "checkpoint" in msg.lower():
                raise ThreadsSessionExpired()
            if "feedback_required" in msg.lower() or body.get("feedback_required"):
                raise ThreadsActionBlocked()
        return body

    async def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        assert self._http is not None
        resp = await self._http.get(THREADS_BASE + endpoint, params=params)
        if resp.status_code == 429:
            raise ThreadsRateLimited()
        if resp.status_code in (401, 403):
            raise ThreadsSessionExpired()
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Onboarding — run once per account when first connecting to Threads
    # ------------------------------------------------------------------

    async def onboard(self, bio: str = "", funnel_url: str = "") -> bool:
        """
        Complete Threads onboarding for a freshly provisioned IG account.

        Steps:
            1. Verify the account is accessible on Threads (profile fetch)
            2. Set profile bio + external URL (funnel link)

        Returns True on success, False if account needs manual intervention.
        """
        try:
            # 1. Check accessibility — fetches own profile on Threads
            await self._get(
                f"users/{self._session.ig_user_id}/info/",
                params={"is_prefetch": "false"},
            )

            # 2. Set profile bio and funnel link
            if bio or funnel_url:
                await self.update_profile(bio=bio, external_url=funnel_url)

            log.info("[%s/threads] Onboarded successfully", self._session.account_id)
            return True

        except (ThreadsSessionExpired, ThreadsActionBlocked) as exc:
            log.warning("[%s/threads] Onboard failed: %s", self._session.account_id, exc)
            return False

    async def update_profile(
        self,
        bio: str = "",
        external_url: str = "",
        display_name: str = "",
    ) -> dict:
        """Update the Threads profile bio, external URL, and/or display name."""
        data: dict = {}
        if bio:
            data["biography"] = bio
        if external_url:
            data["external_url"] = external_url
        if display_name:
            data["first_name"] = display_name
        if not data:
            return {}
        return await self._post("accounts/edit/", data)

    # ------------------------------------------------------------------
    # Content actions
    # ------------------------------------------------------------------

    async def post_text(
        self,
        text: str,
        reply_to_id: Optional[str] = None,
    ) -> dict:
        """
        Publish a Threads text post.

        Args:
            text:         Post body (max ~500 chars)
            reply_to_id:  If set, post as a reply to this media ID
        """
        data: dict = {
            "publish_mode":   "text_post",
            "text_post_app_info": '{"reply_control":0}',
            "caption":        text,
            "media_type":     "1",
            "upload_id":      str(int(uuid.uuid4().int % 10**13)),
        }
        if reply_to_id:
            data["reply_to_id"] = reply_to_id
        return await self._post("media/configure_text_post_app_feed/", data)

    async def follow(self, target_user_id: str) -> dict:
        """Follow a user on Threads."""
        return await self._post(f"friendships/create/{target_user_id}/", {
            "user_id":  target_user_id,
            "_uuid":    str(uuid.uuid4()),
            "_uid":     self._session.ig_user_id,
            "_csrftoken": self._session.csrftoken,
        })

    async def unfollow(self, target_user_id: str) -> dict:
        """Unfollow a user on Threads."""
        return await self._post(f"friendships/destroy/{target_user_id}/", {
            "user_id":  target_user_id,
            "_uuid":    str(uuid.uuid4()),
            "_uid":     self._session.ig_user_id,
            "_csrftoken": self._session.csrftoken,
        })

    async def like(self, media_id: str) -> dict:
        """Like a Threads post."""
        return await self._post(f"media/{media_id}/like/", {
            "media_id":   media_id,
            "_uuid":      str(uuid.uuid4()),
            "_uid":       self._session.ig_user_id,
            "_csrftoken": self._session.csrftoken,
        })

    async def unlike(self, media_id: str) -> dict:
        """Unlike a Threads post."""
        return await self._post(f"media/{media_id}/unlike/", {
            "media_id":   media_id,
            "_uuid":      str(uuid.uuid4()),
            "_uid":       self._session.ig_user_id,
            "_csrftoken": self._session.csrftoken,
        })

    async def repost(self, media_id: str) -> dict:
        """Repost (re-thread) a post."""
        return await self._post(f"media/{media_id}/repost/", {
            "media_id":   media_id,
            "_uuid":      str(uuid.uuid4()),
            "_uid":       self._session.ig_user_id,
            "_csrftoken": self._session.csrftoken,
        })

    async def get_timeline(self, max_id: str = "") -> dict:
        """Fetch the home Threads timeline."""
        params = {"is_prefetch": "false"}
        if max_id:
            params["max_id"] = max_id
        return await self._get("feed/timeline/", params=params)

    async def get_user_feed(self, user_id: str, max_id: str = "") -> dict:
        """Fetch a specific user's Threads posts."""
        params: dict = {}
        if max_id:
            params["max_id"] = max_id
        return await self._get(f"feed/user/{user_id}/", params=params)

    async def ping_session(self) -> bool:
        """Lightweight session validity check."""
        try:
            await self._get(
                f"users/{self._session.ig_user_id}/info/",
                params={"is_prefetch": "true"},
            )
            return True
        except (ThreadsSessionExpired, ThreadsActionBlocked):
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Discovery / intelligence methods
    # ------------------------------------------------------------------

    async def search_hashtag(self, tag: str, limit: int = 20) -> list[dict]:
        """Search Threads posts by hashtag. Returns list of post dicts."""
        try:
            resp = await self._get(
                "tags/search/",
                params={"q": tag, "count": str(min(limit, 50))},
            )
            items = resp.get("items", []) or resp.get("media", {}).get("sections", [])
            posts = []
            for item in items:
                media = item.get("media") or item.get("media_or_ad") or item
                if not media:
                    continue
                cap = media.get("caption") or {}
                text = cap.get("text", "") if isinstance(cap, dict) else (cap or "")
                user = media.get("user") or {}
                posts.append({
                    "pk":       media.get("pk") or media.get("id", ""),
                    "media_id": media.get("pk") or media.get("id", ""),
                    "text":     text[:280],
                    "likes":    media.get("like_count", 0),
                    "reposts":  media.get("reshare_count", 0),
                    "replies":  media.get("text_post_app_replies_count", 0),
                    "username": user.get("username", ""),
                    "user_id":  str(user.get("pk", "") or user.get("id", "")),
                })
            return posts[:limit]
        except Exception:
            return []

    async def get_media_likers(self, media_id: str) -> list[dict]:
        """Return list of users who liked a post."""
        try:
            resp = await self._get(f"media/{media_id}/likers/")
            users = resp.get("users", [])
            return [
                {
                    "user_id":  str(u.get("pk") or u.get("id", "")),
                    "username": u.get("username", ""),
                    "follower_count": u.get("follower_count", 0),
                    "is_private": u.get("is_private", False),
                }
                for u in users
            ]
        except Exception:
            return []

    async def get_media_commenters(self, media_id: str) -> list[dict]:
        """Return list of users who commented on a post (de-duped)."""
        try:
            resp = await self._get(f"media/{media_id}/comments/")
            comments = resp.get("comments", [])
            seen: set[str] = set()
            result = []
            for c in comments:
                user = c.get("user") or {}
                uid = str(user.get("pk") or user.get("id", ""))
                if uid and uid not in seen:
                    seen.add(uid)
                    result.append({
                        "user_id":  uid,
                        "username": user.get("username", ""),
                        "follower_count": user.get("follower_count", 0),
                        "is_private": user.get("is_private", False),
                    })
            return result
        except Exception:
            return []

    async def get_friendship_status(self, target_user_id: str) -> dict:
        """Return friendship status with target user (following/followed_by/etc)."""
        try:
            resp = await self._get(f"friendships/show/{target_user_id}/")
            return {
                "following":          resp.get("following", False),
                "followed_by":        resp.get("followed_by", False),
                "blocking":           resp.get("blocking", False),
                "is_private":         resp.get("is_private", False),
                "outgoing_request":   resp.get("outgoing_request", False),
            }
        except Exception:
            return {"following": False, "followed_by": False}

    async def update_profile_photo(self, image_bytes: bytes) -> dict:
        """Upload a new profile photo. image_bytes is raw JPEG data."""
        assert self._http is not None, "Use 'async with ThreadsClient(...) as client'"
        import io
        files = {"profile_pic": ("photo.jpg", io.BytesIO(image_bytes), "image/jpeg")}
        # Profile photo upload uses multipart form, not URL-encoded
        old_ct = self._http.headers.get("Content-Type", "")
        headers = dict(self._http.headers)
        headers.pop("Content-Type", None)  # let httpx set multipart boundary
        resp = await self._http.post(
            THREADS_BASE + "accounts/change_profile_picture/",
            files=files,
            headers=headers,
        )
        if resp.status_code == 429:
            raise ThreadsRateLimited()
        if resp.status_code in (401, 403):
            raise ThreadsSessionExpired()
        resp.raise_for_status()
        return resp.json()

    async def pin_post(self, media_id: str) -> dict:
        """Pin a post to the top of the account's Threads profile."""
        return await self._post(f"media/{media_id}/pin_timeline_media/", {
            "media_id":   media_id,
            "_uuid":      str(uuid.uuid4()),
            "_uid":       self._session.ig_user_id,
            "_csrftoken": self._session.csrftoken,
        })
