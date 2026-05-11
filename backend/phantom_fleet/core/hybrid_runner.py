"""
HybridRunner — foreground UI automation + parallel background API workers per phone.

The insight:
    A phone is a DEVICE FINGERPRINT ANCHOR, not a display.

    When Instagram's backend receives a request, it doesn't check whether the
    IG app is on screen. It checks device headers: X-IG-Device-ID, X-IG-Android-ID,
    User-Agent, TLS JA3 fingerprint, advertising ID, carrier info. Every one of
    those values is bound to the PHYSICAL PHONE, not to the foreground state.

    Once we extract those headers + a valid session token from the installed app,
    we can fire authenticated API calls from a background process on the same phone
    WHILE its screen is running TikTok automation. Instagram's backend sees
    "real Galaxy S10 Lite doing normal API calls" — because it IS.

Competitor position:
    - Onimator: pure foreground UI automation → 1 platform × 20 accts = 20 active/phone
    - API bot farms on VPS: synthetic device IDs → caught because no real install trail
    - Phantom Fleet hybrid: real-device anchor + parallel API workers
      → 6 platforms × avg 15 accts = 90+ active/phone

Supported background-API platforms (as of 2026-04-11):
    instagram   — instagrapi-compatible private API, X-IG-* headers
    threads     — shares IG session, same headers
    x           — private GraphQL API (same as Twitter app)
    reddit      — official OAuth API + app headers
    telegram    — MTProto, official TDLib / telethon
    linkedin    — Voyager private API (LinkedIn mobile app endpoints)
    discord     — REST + Gateway (ToS risk — agent manager decides)
    bluesky     — AT Protocol, fully public

UI-only platforms (need foreground accessibility):
    tiktok      — request signing (X-Ladon/Gorgon/Khronos) rotates, API brittle
    tinder / bumble / hinge / grindr — app-integrity signing, use UI agent

Concurrency model:
    Each physical phone holds:
        - 1 foreground slot   (exclusive, one platform at a time per TimeSlotScheduler)
        - N API worker slots  (one per API-capable platform on that phone, concurrent)
        - 1 mutex per (phone, platform, account) — never overlap same account in both modes

    Within a background API worker, actions are rate-limited by LogNormal sampling
    matching the platform's human-usage distributions.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .telegram_client import TelegramClient, TelegramSession
    from .reddit_client import RedditClient, RedditSession
    from .discord_client import DiscordClient, DiscordSession
    from .bluesky_client import BlueSkyClient, BlueSkySession
    from .x_client import XClient, XSession
    from ..proxy import ISPProxyPool


# ---------------------------------------------------------------------------
# Mode classification
# ---------------------------------------------------------------------------


class ExecutionMode(str, Enum):
    FOREGROUND_UI  = "foreground_ui"   # accessibility service, screen required
    BACKGROUND_API = "background_api"  # HTTP/MTProto, no screen required


# Platforms that support clean background API execution
BACKGROUND_API_PLATFORMS: frozenset[str] = frozenset({
    "instagram",
    "threads",
    "x",
    "reddit",
    "telegram",
    "discord",
    "bluesky",
    # LinkedIn excluded from OFM build — general brand only
})

# Platforms that require foreground UI (accessibility or no reliable API)
FOREGROUND_ONLY_PLATFORMS: frozenset[str] = frozenset({
    "tiktok",
    "tinder",
    "bumble",
    "hinge",
    "grindr",
})


def execution_mode(platform: str) -> ExecutionMode:
    if platform in BACKGROUND_API_PLATFORMS:
        return ExecutionMode.BACKGROUND_API
    return ExecutionMode.FOREGROUND_UI


# ---------------------------------------------------------------------------
# Device profile — extracted once at clone provisioning
# ---------------------------------------------------------------------------


@dataclass
class PlatformHeaders:
    """Extracted device+app headers for one platform on one physical phone.

    All string fields default to "" so that test stubs can omit fields that
    aren't relevant to the test. Production code (Companion APK extraction)
    always fills every field. Empty strings in production indicate an
    extraction failure and should surface as a PhoneController error.
    """
    platform:        str = ""
    session_token:   str = ""    # authenticated session / bearer token
    device_id:       str = ""    # platform-specific device identifier
    user_agent:      str = ""    # exact UA string from the installed app
    app_version:     str = ""
    android_id:      str = ""    # Android hardware ID (same across platforms)
    advertising_id:  str = ""    # GAID / IDFA (same for all apps on device)
    carrier_name:    str = ""
    carrier_mcc_mnc: str = ""
    locale:          str = ""    # e.g. "en_US"
    timezone:        str = ""    # e.g. "America/New_York"
    extra:           dict = field(default_factory=dict)
    # Platform-specific extras:
    #   instagram: {"mid": "...", "family_device_id": "...", "ig_sig_key": "..."}
    #   x: {"ct0": "...", "auth_token": "..."}
    #   reddit: {"loid": "...", "modhash": "..."}
    #   telegram: {"dc_id": 2, "auth_key": "..."}
    #   linkedin: {"li_at": "...", "jsessionid": "..."}


@dataclass
class DeviceProfile:
    """
    Full fingerprint anchor for one physical phone.
    Extracted once at clone provisioning by Companion APK.
    Stored encrypted in Postgres phones table.
    """
    phone_serial:    str
    model:           str          # e.g. "Samsung Galaxy S10 Lite"
    android_version: str          # e.g. "12"
    android_id:      str          # 16-char hex, hardware-bound
    advertising_id:  str          # GAID
    carrier_name:    str
    carrier_mcc_mnc: str
    timezone:        str
    locale:          str
    # Per-platform extracted headers
    platform_headers: dict[str, PlatformHeaders] = field(default_factory=dict)

    def headers_for(self, platform: str) -> Optional[PlatformHeaders]:
        return self.platform_headers.get(platform)

    def supported_api_platforms(self) -> list[str]:
        """Platforms on this phone that have valid extracted headers."""
        return [
            p for p in self.platform_headers
            if p in BACKGROUND_API_PLATFORMS
        ]


# ---------------------------------------------------------------------------
# Phone-level slot locks (prevent same (phone, platform, account) running in both modes)
# ---------------------------------------------------------------------------


class PhoneSlotLock:
    """
    Mutex registry for one physical phone.

    Rules:
        1. Foreground slot: exclusive — only one platform can use the display.
        2. Background API slots: concurrent — multiple platforms can run in parallel.
        3. Per-account lock: an account can NEVER be in both foreground AND API at the same time.
           If IG foreground session is open, background API worker must not touch the same
           IG account until the foreground session releases.
    """

    def __init__(self, phone_serial: str):
        self.phone_serial = phone_serial
        self._foreground_lock: asyncio.Lock = asyncio.Lock()
        self._foreground_platform: Optional[str] = None
        self._account_locks: dict[str, asyncio.Lock] = {}

    def _account_lock(self, account_id: str) -> asyncio.Lock:
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    async def acquire_foreground(self, platform: str) -> bool:
        """Acquire the foreground slot for a platform. Returns True on success."""
        acquired = await asyncio.wait_for(
            self._foreground_lock.acquire(), timeout=5.0
        )
        if acquired:
            self._foreground_platform = platform
        return acquired

    def release_foreground(self) -> None:
        self._foreground_platform = None
        if self._foreground_lock.locked():
            self._foreground_lock.release()

    async def acquire_account(self, account_id: str) -> bool:
        """Acquire a per-account lock for background API work."""
        lock = self._account_lock(account_id)
        try:
            return await asyncio.wait_for(lock.acquire(), timeout=2.0)
        except asyncio.TimeoutError:
            return False

    def release_account(self, account_id: str) -> None:
        lock = self._account_locks.get(account_id)
        if lock and lock.locked():
            lock.release()

    @property
    def foreground_platform(self) -> Optional[str]:
        return self._foreground_platform


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------


@dataclass
class WorkerTask:
    """
    A unit of work dispatched to a background API worker.
    Produced by platform managers; consumed by BackgroundWorker.
    """
    task_id:      str
    platform:     str
    account_id:   str
    phone_serial: str
    action:       str           # e.g. "follow", "comment", "dm_send", "like"
    params:       dict = field(default_factory=dict)
    priority:     int = 5       # 1=highest, 10=lowest


@dataclass
class WorkerResult:
    task_id:   str
    platform:  str
    account_id: str
    success:   bool
    error:     Optional[str] = None
    data:      dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Background worker base
# ---------------------------------------------------------------------------


class BackgroundWorker:
    """
    Base class for a platform's background API worker.
    One instance per platform per phone, running concurrently.

    Subclasses implement `execute_task()` using the platform's private API.
    The base class handles:
        - account-level locking (via PhoneSlotLock)
        - result reporting
        - error + retry accounting
        - action timing (LogNormal sleep between actions)

    Companion APK routes all HTTP from this worker through its local SOCKS
    proxy at 127.0.0.1:8089, which upstream-connects to IPRoyal residential.
    This means all API calls carry the phone's real residential IP — same IP
    the native app uses.
    """

    PLATFORM: str = ""   # set by subclass

    def __init__(
        self,
        phone_serial: str,
        device_profile: DeviceProfile,
        slot_lock: PhoneSlotLock,
        proxy_url: str = "socks5://127.0.0.1:8089",
        proxy_pool: "Optional[ISPProxyPool]" = None,
    ):
        self.phone_serial   = phone_serial
        self.device_profile = device_profile
        self.slot_lock      = slot_lock
        self.proxy_url      = proxy_url
        self._proxy_pool    = proxy_pool
        self._task_queue: asyncio.Queue[WorkerTask] = asyncio.Queue()
        self._result_queue: asyncio.Queue[WorkerResult] = asyncio.Queue()
        self._running = False
        self._error_count = 0
        self._headers: Optional[PlatformHeaders] = device_profile.headers_for(self.PLATFORM)

    def enqueue(self, task: WorkerTask) -> None:
        self._task_queue.put_nowait(task)

    async def drain_results(self) -> list[WorkerResult]:
        results = []
        while not self._result_queue.empty():
            results.append(self._result_queue.get_nowait())
        return results

    async def run(self, max_tasks: int = 200) -> None:
        """Main worker loop — runs until queue empty or max_tasks hit."""
        self._running = True
        processed = 0
        while self._running and processed < max_tasks:
            try:
                task = self._task_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            result = await self._safe_execute(task)
            self._result_queue.put_nowait(result)
            processed += 1
            # LogNormal inter-action sleep: mean 4s, sigma 1.5s, clipped 1-20s
            await self._human_sleep(mean_sec=4.0, sigma=1.5, lo=1.0, hi=20.0)
        self._running = False

    def _proxy_for_task(self, task: WorkerTask) -> str:
        """
        Return the proxy URL for this specific account.

        When a Smartproxy/ISPProxyPool is wired in, accounts on the same phone
        are split into groups — each group gets its own IP, capping exposure
        to accounts_per_ip accounts per IP rather than all 12 sharing one.

        Falls back to the ADB tunnel URL when no pool is configured.
        """
        if self._proxy_pool is not None:
            return self._proxy_pool.get_for_account(self.phone_serial, task.account_id)
        return self.proxy_url

    async def _safe_execute(self, task: WorkerTask) -> WorkerResult:
        if self._headers is None:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error="no_device_headers_extracted",
            )

        acquired = await self.slot_lock.acquire_account(task.account_id)
        if not acquired:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error="account_locked_by_foreground",
            )
        try:
            result = await self.execute_task(task)
            self._error_count = 0
        except Exception as exc:
            self._error_count += 1
            result = WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=str(exc),
            )
        finally:
            self.slot_lock.release_account(task.account_id)

        # Broadcast to live dashboard (non-blocking, import deferred to avoid circular)
        try:
            from ..api.routes.fleet import publish_fleet_event
            import datetime as _dt
            await publish_fleet_event({
                "type":       "action",
                "action":     task.action,
                "account_id": task.account_id,
                "phone":      self.phone_serial,
                "platform":   self.PLATFORM,
                "success":    result.success,
                "ts_iso":     _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        except Exception:
            pass  # dashboard broadcast must never break execution

        return result

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        """Override in platform subclass to implement the actual API call."""
        raise NotImplementedError

    @staticmethod
    async def _human_sleep(mean_sec: float, sigma: float, lo: float, hi: float) -> None:
        """LogNormal sleep — matches real human inter-action timing distribution."""
        import math
        import random
        # LogNormal: mu/sigma in log-space
        mu_ln = math.log(mean_sec) - 0.5 * sigma ** 2
        raw = random.lognormvariate(mu_ln, sigma)
        sleep_sec = max(lo, min(hi, raw))
        await asyncio.sleep(sleep_sec)


# ---------------------------------------------------------------------------
# Per-platform worker stubs
# (full implementations wire to instagrapi / tweepy / praw / telethon / etc.)
# ---------------------------------------------------------------------------


class InstagramAPIWorker(BackgroundWorker):
    """
    Background IG worker using the Instagram private mobile API.
    Headers: X-IG-Device-ID, X-IG-Android-ID, X-MID, family_device_id, sig_key.
    Proxy: 127.0.0.1:8089 (Companion APK local SOCKS → IPRoyal residential).
    Session refresh: falls back to foreground slot if 401 — HeaderRefreshAgent handles it.
    """
    PLATFORM = "instagram"

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        """
        Dispatch a WorkerTask to the Instagram private API.

        Supported actions:
            follow          — follow a user (params: target_user_id)
            unfollow        — unfollow a user (params: target_user_id)
            like            — like a post (params: media_id)
            story_view      — mark stories seen (params: reel_id, media_ids: list[str])
            send_dm         — send a DM text (params: recipient_user_id, text)
            get_followers   — paginate follower list (params: user_id, max_id?, count?)

        Returns WorkerResult with:
            success=True  + data={...api response...}  on success
            success=False + error="session_expired"    on IGSessionExpired
            success=False + error="rate_limited"       on IGRateLimited
            success=False + error="action_blocked"     on IGActionBlocked
        """
        # Local import to avoid circular dependency
        # (instagram_client imports PlatformHeaders from this module)
        from .instagram_client import (
            InstagramClient,
            IGSession,
            IGSessionExpired,
            IGRateLimited,
            IGActionBlocked,
        )

        session: Optional[IGSession] = task.params.get("session")
        if session is None:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error="no_session_in_task_params",
            )

        client = InstagramClient(session=session, proxy_url=self._proxy_for_task(task))
        action = task.action
        params = task.params

        try:
            async with client:
                if action == "follow":
                    target = params["target_user_id"]
                    resp = await client.follow(target)
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=True,
                        data={"action": "follow", "target_user_id": target, "response": resp},
                    )

                elif action == "unfollow":
                    target = params["target_user_id"]
                    resp = await client.unfollow(target)
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=True,
                        data={"action": "unfollow", "target_user_id": target, "response": resp},
                    )

                elif action == "like":
                    media_id = params["media_id"]
                    resp = await client.like_post(media_id)
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=True,
                        data={"action": "like", "media_id": media_id, "response": resp},
                    )

                elif action == "story_view":
                    reel_id = params["reel_id"]
                    media_ids = params.get("media_ids", [reel_id])
                    resp = await client.story_view(reel_id, media_ids)
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=True,
                        data={"action": "story_view", "reel_id": reel_id, "response": resp},
                    )

                elif action == "send_dm":
                    recipient = params["recipient_user_id"]
                    text = params.get("text", "")
                    resp = await client.send_dm(recipient, text)
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=True,
                        data={"action": "send_dm", "recipient_user_id": recipient, "response": resp},
                    )

                elif action == "get_followers":
                    user_id = params["user_id"]
                    max_id = params.get("max_id", "")
                    count = params.get("count", 50)
                    resp = await client.get_user_followers(user_id, max_id=max_id, count=count)
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=True,
                        data={"action": "get_followers", "user_id": user_id, "response": resp},
                    )

                else:
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=False,
                        error=f"unknown_action:{action}",
                    )

        except IGSessionExpired:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error="session_expired",
            )
        except IGRateLimited:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error="rate_limited",
            )
        except IGActionBlocked as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"action_blocked:{exc}",
            )


class ThreadsAPIWorker(BackgroundWorker):
    """
    Threads background worker — shares IG session, uses Threads App ID header.
    Supported actions: threads_post, follow, unfollow, like, repost, get_timeline.
    Session is passed in task.params["session"] (same IGSession as IG worker).
    """
    PLATFORM = "threads"

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        from .threads_client import (
            ThreadsClient,
            ThreadsSessionExpired,
            ThreadsRateLimited,
            ThreadsActionBlocked,
        )
        from .instagram_client import IGSession

        session: Optional[IGSession] = task.params.get("session")
        if session is None:
            return WorkerResult(
                task_id=task.task_id, platform=self.PLATFORM,
                account_id=task.account_id, success=False,
                error="no_session_in_task_params",
            )

        action = task.action
        p = task.params

        try:
            async with ThreadsClient(session=session, proxy_url=self._proxy_for_task(task)) as client:
                if action == "threads_post":
                    data = await client.post_text(
                        text=p["text"],
                        reply_to_id=p.get("reply_to_id"),
                    )
                elif action == "follow":
                    data = await client.follow(p["target_user_id"])
                elif action == "unfollow":
                    data = await client.unfollow(p["target_user_id"])
                elif action == "like":
                    data = await client.like(p["media_id"])
                elif action == "unlike":
                    data = await client.unlike(p["media_id"])
                elif action == "repost":
                    data = await client.repost(p["media_id"])
                elif action == "get_timeline":
                    data = await client.get_timeline(max_id=p.get("max_id", ""))
                elif action == "onboard":
                    ok = await client.onboard(
                        bio=p.get("bio", ""),
                        funnel_url=p.get("funnel_url", ""),
                    )
                    data = {"onboarded": ok}
                elif action == "cross_post_session":
                    # Compound action: cross-post IG captions to Threads
                    from ..agents.specialists.threads_cross_post_agent import ThreadsCrossPostAgent
                    agent = ThreadsCrossPostAgent()
                    result = await agent.run_session(
                        account_id=task.account_id,
                        session=session,
                        caption_pool=p.get("caption_pool", []),
                        posts_target=p.get("posts_target", 1),
                        date_iso=p.get("date_iso"),
                        posts_done_today=p.get("posts_done_today", 0),
                        proxy_url=self._proxy_for_task(task),
                    )
                    return result
                elif action == "engagement_session":
                    # Compound action: like/follow/reply on trending Threads content
                    from ..agents.specialists.threads_engagement_agent import ThreadsEngagementAgent
                    from ..agents.specialists.trending_feed_agent import TrendingFeedAgent, TrendingFeed
                    agent = ThreadsEngagementAgent()
                    # Caller can pass a pre-built TrendingFeed or we build one on the fly
                    feed = p.get("trending_feed")
                    if feed is None:
                        trend_agent = TrendingFeedAgent()
                        feed = await trend_agent.fetch()
                    result = await agent.run_session(
                        account_id=task.account_id,
                        session=session,
                        trending_feed=feed,
                        date_iso=p.get("date_iso"),
                        likes_done_today=p.get("likes_done_today", 0),
                        follows_done_today=p.get("follows_done_today", 0),
                        replies_done_today=p.get("replies_done_today", 0),
                        proxy_url=self._proxy_for_task(task),
                    )
                    return result
                else:
                    return WorkerResult(
                        task_id=task.task_id, platform=self.PLATFORM,
                        account_id=task.account_id, success=False,
                        error=f"unknown_action:{action}",
                    )

                return WorkerResult(
                    task_id=task.task_id, platform=self.PLATFORM,
                    account_id=task.account_id, success=True,
                    data={"action": action, "response": data},
                )

        except ThreadsSessionExpired:
            return WorkerResult(
                task_id=task.task_id, platform=self.PLATFORM,
                account_id=task.account_id, success=False,
                error="session_expired",
            )
        except ThreadsRateLimited as exc:
            return WorkerResult(
                task_id=task.task_id, platform=self.PLATFORM,
                account_id=task.account_id, success=False,
                error=f"rate_limited:retry_after={exc.retry_after_sec}",
            )
        except ThreadsActionBlocked:
            return WorkerResult(
                task_id=task.task_id, platform=self.PLATFORM,
                account_id=task.account_id, success=False,
                error="action_blocked",
            )
        except Exception as exc:
            return WorkerResult(
                task_id=task.task_id, platform=self.PLATFORM,
                account_id=task.account_id, success=False,
                error=str(exc),
            )


class XAPIWorker(BackgroundWorker):
    """X private GraphQL API. Headers: ct0 CSRF, auth_token cookie, x-twitter-client-*."""
    PLATFORM = "x"

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        from .x_client import (
            XClient, XSession,
            XSessionExpired, XRateLimited,
        )

        assert self._headers is not None  # guaranteed by _safe_execute

        session = XSession(
            account_id=task.account_id,
            auth_token=self._headers.extra.get("auth_token", self._headers.session_token),
            ct0_csrf=self._headers.extra.get("ct0", ""),
            user_id=self._headers.extra.get("user_id", ""),
            username=self._headers.extra.get("username", ""),
            headers=self._headers,
        )

        try:
            async with XClient(session, proxy_url=self._proxy_for_task(task)) as client:
                action = task.action
                p = task.params

                if action == "follow":
                    data = await client.follow_user(p["user_id"])
                elif action == "unfollow":
                    data = await client.unfollow_user(p["user_id"])
                elif action == "like":
                    data = await client.like_tweet(p["tweet_id"])
                elif action == "unlike":
                    data = await client.unlike_tweet(p["tweet_id"])
                elif action == "retweet":
                    data = await client.retweet(p["tweet_id"])
                elif action == "dm_send":
                    data = await client.send_dm(p["recipient_id"], p["text"])
                elif action == "timeline":
                    data = await client.get_timeline(
                        count=p.get("count", 20),
                        cursor=p.get("cursor", ""),
                    )
                elif action == "search":
                    data = await client.search_recent(
                        query=p["query"],
                        count=p.get("count", 20),
                    )
                elif action == "ping":
                    ok = await client.ping_session()
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=ok,
                        error=None if ok else "session_invalid",
                    )
                else:
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=False,
                        error=f"unknown_action:{action}",
                    )

                return WorkerResult(
                    task_id=task.task_id,
                    platform=self.PLATFORM,
                    account_id=task.account_id,
                    success=True,
                    data=data if isinstance(data, dict) else {"raw": data},
                )

        except XSessionExpired as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"session_expired:{exc}",
            )
        except XRateLimited as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"rate_limited:retry_after={exc.retry_after_sec}",
            )


class RedditAPIWorker(BackgroundWorker):
    """Reddit OAuth API. Headers: Authorization Bearer, x-reddit-device-id, x-reddit-loid."""
    PLATFORM = "reddit"

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        from .reddit_client import (
            RedditClient, RedditSession,
            RedditSessionExpired, RedditRateLimited, RedditForbidden,
        )

        assert self._headers is not None

        session = RedditSession(
            account_id=task.account_id,
            access_token=self._headers.session_token,
            refresh_token=self._headers.extra.get("refresh_token", ""),
            user_id=self._headers.extra.get("user_id", ""),
            username=self._headers.extra.get("username", ""),
            headers=self._headers,
        )

        try:
            async with RedditClient(session, proxy_url=self._proxy_for_task(task)) as client:
                action = task.action
                p = task.params

                if action == "subscribe":
                    data = await client.subscribe_subreddit(p["subreddit"])
                elif action == "unsubscribe":
                    data = await client.subscribe_subreddit(
                        p["subreddit"], unsub=True
                    )
                elif action == "upvote":
                    data = await client.upvote(p["post_id"], direction=1)
                elif action == "downvote":
                    data = await client.upvote(p["post_id"], direction=-1)
                elif action == "comment":
                    data = await client.comment(p["post_id"], p["text"])
                elif action == "submit_post":
                    data = await client.submit_post(
                        subreddit=p["subreddit"],
                        title=p["title"],
                        text=p.get("text", ""),
                        kind=p.get("kind", "self"),
                        url=p.get("url", ""),
                    )
                elif action == "get_posts":
                    data = await client.get_subreddit_posts(
                        subreddit=p["subreddit"],
                        limit=p.get("limit", 25),
                        after=p.get("after", ""),
                        sort=p.get("sort", "hot"),
                    )
                elif action == "dm_send":
                    data = await client.send_pm(
                        username=p["username"],
                        subject=p.get("subject", ""),
                        text=p["text"],
                    )
                elif action == "inbox":
                    data = await client.get_inbox(
                        mark_read=p.get("mark_read", False)
                    )
                elif action == "ping":
                    ok = await client.ping_session()
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=ok,
                        error=None if ok else "session_invalid",
                    )
                else:
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=False,
                        error=f"unknown_action:{action}",
                    )

                return WorkerResult(
                    task_id=task.task_id,
                    platform=self.PLATFORM,
                    account_id=task.account_id,
                    success=True,
                    data=data if isinstance(data, dict) else {"raw": data},
                )

        except RedditSessionExpired as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"session_expired:{exc}",
            )
        except RedditRateLimited as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"rate_limited:retry_after={exc.retry_after_sec}",
            )
        except RedditForbidden as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"forbidden:{exc}",
            )


class TelegramMTProtoWorker(BackgroundWorker):
    """
    Telegram MTProto. Uses extracted auth_key + dc_id from the installed app's
    session database (tdata/). Connects to Telegram DCs via residential proxy.
    Current layer: Bot HTTP API (swappable to MTProto when pyrogram is available).
    """
    PLATFORM = "telegram"

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        from .telegram_client import (
            TelegramClient, TelegramSession,
            TelegramSessionExpired, TelegramFloodWait,
        )

        assert self._headers is not None

        session = TelegramSession(
            account_id=task.account_id,
            auth_key=self._headers.extra.get("auth_key", ""),
            dc_id=int(self._headers.extra.get("dc_id", 2)),
            user_id=self._headers.extra.get("user_id", ""),
            username=self._headers.extra.get("username", ""),
            phone=self._headers.extra.get("phone", ""),
            token=self._headers.session_token,
            headers=self._headers,
        )

        try:
            async with TelegramClient(session, proxy_url=self._proxy_for_task(task)) as client:
                action = task.action
                p = task.params

                if action == "dm_send":
                    data = await client.send_dm(p["user_id"], p["text"])
                elif action == "join_group":
                    data = await client.join_group(p["invite_link"])
                elif action == "get_members":
                    members = await client.get_group_members(
                        p["group_id"], limit=p.get("limit", 50)
                    )
                    data = {"members": members}
                elif action == "channel_post":
                    data = await client.send_channel_post(
                        p["channel_id"], p["text"]
                    )
                elif action == "forward":
                    data = await client.forward_message(
                        p["from_chat"], p["to_chat"], int(p["message_id"])
                    )
                elif action == "ping":
                    ok = await client.ping_session()
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=ok,
                        error=None if ok else "session_invalid",
                    )
                else:
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=False,
                        error=f"unknown_action:{action}",
                    )

                return WorkerResult(
                    task_id=task.task_id,
                    platform=self.PLATFORM,
                    account_id=task.account_id,
                    success=True,
                    data=data if isinstance(data, dict) else {"raw": data},
                )

        except TelegramSessionExpired as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"session_expired:{exc}",
            )
        except TelegramFloodWait as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"flood_wait:retry_after={exc.retry_after_sec}",
            )


class LinkedInVoyagerWorker(BackgroundWorker):
    """
    LinkedIn Voyager private API. Headers: li_at cookie, JSESSIONID, x-li-lang,
    x-li-track (JSON payload with client version + OS info from device profile).
    """
    PLATFORM = "linkedin"


class DiscordAPIWorker(BackgroundWorker):
    """
    Discord REST + Gateway. Token extracted from leveldb via DPAPI + AES-GCM
    (already implemented in Discord token extraction module).
    High ToS ban risk — agent manager gates this explicitly.
    """
    PLATFORM = "discord"

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        from .discord_client import (
            DiscordClient, DiscordSession,
            DiscordSessionExpired, DiscordRateLimited,
        )

        assert self._headers is not None

        session = DiscordSession(
            account_id=task.account_id,
            token=self._headers.session_token,
            user_id=self._headers.extra.get("user_id", ""),
            username=self._headers.extra.get("username", ""),
            discriminator=self._headers.extra.get("discriminator", "0"),
            headers=self._headers,
        )

        try:
            async with DiscordClient(session, proxy_url=self._proxy_for_task(task)) as client:
                action = task.action
                p = task.params

                if action == "send_message":
                    data = await client.send_message(p["channel_id"], p["content"])
                elif action == "join_server":
                    data = await client.join_server(p["invite_code"])
                elif action == "get_members":
                    members = await client.get_guild_members(
                        p["guild_id"],
                        limit=p.get("limit", 100),
                        after=p.get("after", "0"),
                    )
                    data = {"members": members}
                elif action == "react":
                    data = await client.react_to_message(
                        p["channel_id"], p["message_id"], p["emoji"]
                    )
                elif action == "dm_send":
                    data = await client.send_dm(p["user_id"], p["content"])
                elif action == "ping":
                    ok = await client.ping_session()
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=ok,
                        error=None if ok else "session_invalid",
                    )
                else:
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=False,
                        error=f"unknown_action:{action}",
                    )

                return WorkerResult(
                    task_id=task.task_id,
                    platform=self.PLATFORM,
                    account_id=task.account_id,
                    success=True,
                    data=data if isinstance(data, dict) else {"raw": data},
                )

        except DiscordSessionExpired as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"session_expired:{exc}",
            )
        except DiscordRateLimited as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"rate_limited:retry_after={exc.retry_after_sec}",
            )


class BlueSkyATProtoWorker(BackgroundWorker):
    """
    AT Protocol (Bluesky). Full public API — no signing complexity.
    createSession → get DID → all endpoints use DID + access JWT.
    """
    PLATFORM = "bluesky"

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        from .bluesky_client import (
            BlueSkyClient, BlueSkySession,
            BlueSkySessionExpired, BlueSkyRateLimited,
        )

        assert self._headers is not None

        session = BlueSkySession(
            account_id=task.account_id,
            did=self._headers.extra.get("did", ""),
            access_jwt=self._headers.session_token,
            refresh_jwt=self._headers.extra.get("refresh_jwt", ""),
            handle=self._headers.extra.get("handle", ""),
            headers=self._headers,
        )

        try:
            async with BlueSkyClient(session, proxy_url=self._proxy_for_task(task)) as client:
                action = task.action
                p = task.params

                if action == "post":
                    data = await client.create_post(
                        text=p["text"],
                        reply_to=p.get("reply_to"),
                    )
                elif action == "follow":
                    data = await client.follow_user(p["did"])
                elif action == "unfollow":
                    data = await client.unfollow_user(p["follow_rkey"])
                elif action == "like":
                    data = await client.like_post(p["uri"], p["cid"])
                elif action == "repost":
                    data = await client.repost(p["uri"], p["cid"])
                elif action == "timeline":
                    data = await client.get_timeline(
                        limit=p.get("limit", 20),
                        cursor=p.get("cursor", ""),
                    )
                elif action == "get_followers":
                    data = await client.get_followers(
                        actor=p["actor"],
                        limit=p.get("limit", 50),
                        cursor=p.get("cursor", ""),
                    )
                elif action == "search":
                    data = await client.search_posts(
                        query=p["query"],
                        limit=p.get("limit", 25),
                    )
                elif action == "ping":
                    ok = await client.ping_session()
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=ok,
                        error=None if ok else "session_invalid",
                    )
                else:
                    return WorkerResult(
                        task_id=task.task_id,
                        platform=self.PLATFORM,
                        account_id=task.account_id,
                        success=False,
                        error=f"unknown_action:{action}",
                    )

                return WorkerResult(
                    task_id=task.task_id,
                    platform=self.PLATFORM,
                    account_id=task.account_id,
                    success=True,
                    data=data if isinstance(data, dict) else {"raw": data},
                )

        except BlueSkySessionExpired as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"session_expired:{exc}",
            )
        except BlueSkyRateLimited as exc:
            return WorkerResult(
                task_id=task.task_id,
                platform=self.PLATFORM,
                account_id=task.account_id,
                success=False,
                error=f"rate_limited:retry_after={exc.retry_after_sec}",
            )


# ---------------------------------------------------------------------------
# Worker registry
# ---------------------------------------------------------------------------


WORKER_CLASSES: dict[str, type[BackgroundWorker]] = {
    "instagram": InstagramAPIWorker,
    "threads":   ThreadsAPIWorker,
    "x":         XAPIWorker,
    "reddit":    RedditAPIWorker,
    "telegram":  TelegramMTProtoWorker,
    "discord":   DiscordAPIWorker,
    "bluesky":   BlueSkyATProtoWorker,
    # LinkedIn excluded from OFM build — general brand only
}


# ---------------------------------------------------------------------------
# PhoneHybridRunner — coordinates foreground + all background workers for one phone
# ---------------------------------------------------------------------------


class PhoneHybridRunner:
    """
    Top-level coordinator for one physical phone.

    Owns:
        - 1 PhoneSlotLock (foreground mutex + per-account account locks)
        - N BackgroundWorkers (one per API-capable platform installed on phone)
        - References to platform manager task queues (platform managers enqueue tasks here)

    Throughput comparison:
        Onimator-style (foreground only):    ~20 accounts active at peak
        PhoneHybridRunner (foreground+API):  ~90 accounts active concurrently
                                             (6 API workers × 15 avg + 1 foreground × 20)

    Called by the ChiefAgentManager's scheduler at each slot boundary.
    """

    def __init__(self, device_profile: DeviceProfile, proxy_pool: "Optional[ISPProxyPool]" = None):
        self.device_profile = device_profile
        self.phone_serial   = device_profile.phone_serial
        self.slot_lock      = PhoneSlotLock(self.phone_serial)
        self._proxy_pool    = proxy_pool
        self._workers: dict[str, BackgroundWorker] = {}
        self._init_workers()

    def _init_workers(self) -> None:
        for platform in self.device_profile.supported_api_platforms():
            cls = WORKER_CLASSES.get(platform)
            if cls is None:
                continue
            self._workers[platform] = cls(
                phone_serial=self.phone_serial,
                device_profile=self.device_profile,
                slot_lock=self.slot_lock,
                proxy_pool=self._proxy_pool,
            )

    def worker_for(self, platform: str) -> Optional[BackgroundWorker]:
        return self._workers.get(platform)

    def enqueue_api_task(self, task: WorkerTask) -> bool:
        """Enqueue a task for the appropriate background worker. Returns False if not supported."""
        worker = self._workers.get(task.platform)
        if worker is None:
            return False
        worker.enqueue(task)
        return True

    async def run_background_workers(self) -> dict[str, list[WorkerResult]]:
        """
        Kick off all background API workers concurrently.
        Returns results keyed by platform.
        Called by the slot scheduler at each active slot boundary.
        """
        tasks = {
            platform: asyncio.create_task(worker.run())
            for platform, worker in self._workers.items()
        }
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)

        return {
            platform: await worker.drain_results()
            for platform, worker in self._workers.items()
        }

    def throughput_summary(self) -> dict:
        """Report active workers + queue depths for the Chief agent's status report."""
        return {
            "phone_serial": self.phone_serial,
            "foreground_platform": self.slot_lock.foreground_platform,
            "api_workers": list(self._workers.keys()),
            "queue_depths": {
                platform: worker._task_queue.qsize()
                for platform, worker in self._workers.items()
            },
        }


# ---------------------------------------------------------------------------
# Fleet-level runner factory
# ---------------------------------------------------------------------------


def build_fleet_runners(
    device_profiles: list[DeviceProfile],
    proxy_pool: "Optional[ISPProxyPool]" = None,
) -> dict[str, PhoneHybridRunner]:
    """
    Build one PhoneHybridRunner per physical phone.
    Called once at startup by ChiefAgentManager.

    Pass proxy_pool to enable per-account IP grouping — each runner's workers
    will call pool.get_for_account(serial, account_id) per task instead of
    sharing the phone's ADB tunnel IP across all accounts.
    """
    return {
        profile.phone_serial: PhoneHybridRunner(profile, proxy_pool=proxy_pool)
        for profile in device_profiles
    }
