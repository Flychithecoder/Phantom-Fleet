"""
EngagementExecutor — the core automation loop for Phantom Fleet.

Every 60 seconds this loop:
  1. Loads all active accounts whose time window includes the current UTC hour.
  2. Groups accounts by phone.
  3. For each phone (one action at a time — per-phone asyncio.Lock):
       a. Picks the highest-priority action type with quota remaining today.
       b. Calls the companion APK directly over WiFi.
       c. Logs the result to action_log.
       d. Increments the daily_action_counts counter on success.

Action priority (lightest → heaviest platform risk):
    story  →  like  →  follow  →  unfollow  →  comment  →  dm

Per-phone serialization prevents two accounts on the same phone from running
simultaneously — Android only has one foreground app.

Target selection:
    - follow/unfollow: picks a random token from the account's `tags` field
    - like: scroll_reels (no explicit target, just scrolls the feed and likes)
    - story: view_stories of followed users (no explicit target)
    - comment/dm: reserved for future expansion

Delay enforcement:
    After each action, the executor checks `last_action_at` for that type
    and waits for `follow_min_delay` / `like_min_delay` seconds before
    dispatching again. This produces natural action spacing — no bursts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Optional

import httpx

log = logging.getLogger("phantom_fleet.engagement_executor")

# ---------------------------------------------------------------------------
# Action priority order
# ---------------------------------------------------------------------------

_ACTION_PRIORITY = ["story", "like", "follow", "unfollow", "comment", "dm"]

# APK endpoint map: (platform, action_type) → (method, path, body_builder)
# body_builder receives (account_dict, target) and returns JSON body dict.

def _ig_follow_body(acc: dict, target: str) -> dict:
    return {"username": target, "clonePackage": acc["clone_package"]}

def _ig_unfollow_body(acc: dict, target: str) -> dict:
    return {"username": target, "clonePackage": acc["clone_package"]}

def _ig_like_body(acc: dict, target: str) -> dict:
    return {"watchCount": 3, "clonePackage": acc["clone_package"]}

def _ig_story_body(acc: dict, target: str) -> dict:
    return {"username": "feed", "storyCount": 5, "clonePackage": acc["clone_package"]}

def _th_follow_body(acc: dict, target: str) -> dict:
    return {"username": target, "clonePackage": acc["clone_package"]}

def _th_unfollow_body(acc: dict, target: str) -> dict:
    return {"username": target, "clonePackage": acc["clone_package"]}

def _th_like_body(acc: dict, target: str) -> dict:
    return {"scrollCount": 5, "clonePackage": acc["clone_package"]}

_APK_ROUTES: dict[tuple[str, str], tuple[str, str, callable]] = {
    ("instagram", "follow"):   ("POST", "/instagram/engage/follow",       _ig_follow_body),
    ("instagram", "unfollow"): ("POST", "/instagram/engage/unfollow",     _ig_unfollow_body),
    ("instagram", "like"):     ("POST", "/instagram/engage/scroll_reels", _ig_like_body),
    ("instagram", "story"):    ("POST", "/instagram/engage/view_stories", _ig_story_body),
    ("threads",   "follow"):   ("POST", "/threads/engage/follow",         _th_follow_body),
    ("threads",   "unfollow"): ("POST", "/threads/engage/unfollow",       _th_unfollow_body),
    ("threads",   "like"):     ("POST", "/threads/engage/scroll_feed",    _th_like_body),
}


# ---------------------------------------------------------------------------
# EngagementExecutor
# ---------------------------------------------------------------------------

class EngagementExecutor:
    """
    Background loop that runs engagement actions for the entire fleet.

    Args:
        pool:              asyncpg pool.
        poll_interval_sec: How often the loop ticks (default 60 s).
    """

    def __init__(self, pool, poll_interval_sec: int = 60) -> None:
        self._pool = pool
        self._poll_interval = poll_interval_sec
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Per-phone lock — only one action runs per phone at a time
        self._phone_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="engagement_executor")
        log.info("EngagementExecutor started (poll every %ds)", self._poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("EngagementExecutor stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                log.error("EngagementExecutor tick error: %s", exc, exc_info=True)
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        """One scheduler tick: load eligible accounts, dispatch one action per phone."""
        now_utc = datetime.now(timezone.utc)
        current_hour = now_utc.hour

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        a.id, a.username, a.platform, a.clone_package,
                        a.phone_serial,
                        a.start_hour, a.end_hour, a.tags,
                        a.follow_enabled, a.follow_daily_max,
                        a.follow_min_delay, a.follow_max_delay,
                        a.like_enabled, a.like_daily_max,
                        a.like_min_delay, a.like_max_delay,
                        a.story_enabled, a.story_daily_max,
                        a.comment_enabled, a.comment_daily_max,
                        a.dm_enabled, a.dm_daily_max,
                        a.unfollow_enabled, a.unfollow_daily_max,
                        COALESCE(ph.wifi_ip, p.wifi_ip) AS wifi_ip
                    FROM accounts a
                    LEFT JOIN phone_heartbeats ph ON ph.serial = a.phone_serial
                    LEFT JOIN phones p ON p.serial = a.phone_serial
                    WHERE a.status = 'active'
                      AND a.phone_serial IS NOT NULL
                      AND a.clone_package IS NOT NULL
                      AND a.clone_package != ''
                      AND $1 >= a.start_hour
                      AND $1 <  a.end_hour
                    """,
                    current_hour,
                )
        except Exception as exc:
            log.warning("EngagementExecutor: DB query failed: %s", exc)
            return

        if not rows:
            return

        # Group by phone
        by_phone: dict[str, list[dict]] = {}
        for row in rows:
            acc = dict(row)
            if not acc.get("wifi_ip"):
                continue  # phone IP unknown — skip until heartbeat registers it
            by_phone.setdefault(acc["phone_serial"], []).append(acc)

        if not by_phone:
            return

        log.debug(
            "EngagementExecutor tick: %d phones, %d accounts",
            len(by_phone), len(rows),
        )

        # Dispatch one action per phone concurrently (phones are independent)
        tasks = [
            asyncio.create_task(
                self._dispatch_phone(serial, phone_accounts),
                name=f"engage_{serial[:8]}",
            )
            for serial, phone_accounts in by_phone.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.warning("Phone dispatch error: %s", r)

    # ------------------------------------------------------------------
    # Per-phone dispatch
    # ------------------------------------------------------------------

    async def _dispatch_phone(self, serial: str, accounts: list[dict]) -> None:
        """Dispatch exactly one action on this phone, holding the phone lock."""
        lock = self._phone_locks.setdefault(serial, asyncio.Lock())
        if lock.locked():
            log.debug("Phone %s is busy — skipping tick", serial)
            return

        async with lock:
            item = await self._pick_action(accounts)
            if item is None:
                return
            account, action_type, target = item
            await self._execute_action(account, action_type, target)

    async def _pick_action(
        self, accounts: list[dict]
    ) -> Optional[tuple[dict, str, str]]:
        """
        Pick the highest-priority (action_type, account, target) triple
        for this phone's account list.

        Returns None if every account has exhausted all quotas or no
        valid target exists for follow/unfollow.
        """
        # Build today's counts for all accounts in one query
        account_ids = [a["id"] for a in accounts]
        today_counts = await self._load_today_counts(account_ids)
        last_action_ats = await self._load_last_action_ats(account_ids)

        now_ts = datetime.now(timezone.utc).timestamp()

        for action_type in _ACTION_PRIORITY:
            for acc in accounts:
                enabled_key  = f"{action_type}_enabled"
                max_key      = f"{action_type}_daily_max"
                min_delay_key = f"{action_type}_min_delay"

                if not acc.get(enabled_key, False):
                    continue

                daily_max = acc.get(max_key, 0)
                if daily_max <= 0:
                    continue

                today_count = today_counts.get((acc["id"], action_type), 0)
                if today_count >= daily_max:
                    continue

                # Enforce min delay since last action of this type
                min_delay = acc.get(min_delay_key, 60)
                last_at = last_action_ats.get((acc["id"], action_type))
                if last_at is not None:
                    elapsed = now_ts - last_at.timestamp()
                    # Add jitter: actual delay = min_delay + random(0, min_delay)
                    required = min_delay + random.uniform(0, min_delay)
                    if elapsed < required:
                        continue

                # Determine target
                target = ""
                if action_type in ("follow", "unfollow"):
                    target = _pick_target(acc.get("tags", ""))
                    if not target:
                        continue  # no targets configured

                return acc, action_type, target

        return None

    # ------------------------------------------------------------------
    # APK call
    # ------------------------------------------------------------------

    async def _execute_action(
        self, account: dict, action_type: str, target: str
    ) -> None:
        platform = account.get("platform", "instagram")
        wifi_ip  = account["wifi_ip"]
        serial   = account["phone_serial"]

        route = _APK_ROUTES.get((platform, action_type))
        if route is None:
            log.debug(
                "No APK route for platform=%s action=%s — skipping",
                platform, action_type,
            )
            return

        method, path, body_fn = route
        body = body_fn(account, target)
        url  = f"http://{wifi_ip}:8090{path}"

        started_at = datetime.now(timezone.utc)
        result: dict = {}
        error: Optional[str] = None
        success = False

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method == "POST":
                    resp = await client.post(url, json=body)
                else:
                    resp = await client.get(url, params=body)

            if 200 <= resp.status_code < 300:
                result  = resp.json()
                success = bool(result.get("success", False))
                if not success:
                    error = result.get("error") or f"APK returned success=false"
            else:
                error = f"HTTP {resp.status_code}: {resp.text[:200]}"

        except httpx.ConnectError:
            error = f"Cannot reach phone {wifi_ip}:8090 — APK offline or IP changed"
        except httpx.TimeoutException:
            error = f"APK timeout after 30s (phone={wifi_ip})"
        except Exception as exc:
            error = str(exc)

        finished_at = datetime.now(timezone.utc)

        if error:
            log.warning(
                "[%s] %s/%s → ERROR: %s",
                account["username"], platform, action_type, error,
            )
        else:
            log.info(
                "[%s] %s/%s → OK (target=%r)",
                account["username"], platform, action_type, target or "feed",
            )

        await self._persist(
            account     = account,
            serial      = serial,
            action_type = action_type,
            target      = target,
            result      = result,
            error       = error,
            success     = success,
            started_at  = started_at,
            finished_at = finished_at,
        )

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _load_today_counts(
        self, account_ids: list[str]
    ) -> dict[tuple[str, str], int]:
        """Return {(account_id, action_type): count} for today."""
        if not account_ids:
            return {}
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT account_id, action_type, count
                    FROM daily_action_counts
                    WHERE date = CURRENT_DATE
                      AND account_id = ANY($1::text[])
                    """,
                    account_ids,
                )
            return {(r["account_id"], r["action_type"]): r["count"] for r in rows}
        except Exception as exc:
            log.warning("_load_today_counts failed: %s", exc)
            return {}

    async def _load_last_action_ats(
        self, account_ids: list[str]
    ) -> dict[tuple[str, str], datetime]:
        """Return {(account_id, action_type): last_action_at} for today."""
        if not account_ids:
            return {}
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT account_id, action_type, last_action_at
                    FROM daily_action_counts
                    WHERE date = CURRENT_DATE
                      AND account_id = ANY($1::text[])
                      AND last_action_at IS NOT NULL
                    """,
                    account_ids,
                )
            return {
                (r["account_id"], r["action_type"]): r["last_action_at"]
                for r in rows
            }
        except Exception as exc:
            log.warning("_load_last_action_ats failed: %s", exc)
            return {}

    async def _persist(
        self,
        account:     dict,
        serial:      str,
        action_type: str,
        target:      str,
        result:      dict,
        error:       Optional[str],
        success:     bool,
        started_at:  datetime,
        finished_at: datetime,
    ) -> None:
        """Write action_log row and increment daily_action_counts on success."""
        try:
            async with self._pool.acquire() as conn:
                # action_log
                await conn.execute(
                    """
                    INSERT INTO action_log
                        (account_id, agent_name, action_type, target_username,
                         phone_serial, executed_at, status, error, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    account["id"],
                    "engagement_executor",
                    action_type,
                    target or None,
                    serial,
                    finished_at,
                    "success" if success else "failed",
                    error,
                    json.dumps(result),
                )

                # daily_action_counts (only on success)
                if success:
                    await conn.execute(
                        """
                        INSERT INTO daily_action_counts
                            (account_id, date, action_type, count, last_action_at)
                        VALUES ($1, CURRENT_DATE, $2, 1, $3)
                        ON CONFLICT (account_id, date, action_type)
                        DO UPDATE SET
                            count          = daily_action_counts.count + 1,
                            last_action_at = EXCLUDED.last_action_at
                        """,
                        account["id"],
                        action_type,
                        finished_at,
                    )
        except Exception as exc:
            log.warning("_persist failed for %s/%s: %s", account["username"], action_type, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_target(tags: str) -> str:
    """
    Pick a random target from the account's tags field.

    Tags are space-separated tokens. @ and # prefixes are stripped so the
    APK receives a bare username or keyword.
    """
    if not tags or not tags.strip():
        return ""
    parts = [
        t.strip().lstrip("@").lstrip("#")
        for t in tags.split()
        if t.strip()
    ]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return random.choice(parts)
