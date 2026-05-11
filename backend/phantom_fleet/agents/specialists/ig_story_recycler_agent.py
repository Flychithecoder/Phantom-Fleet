"""
IGStoryRecyclerAgent — Recycles top-performing stories after a cooldown period.

Stories expire after 24 hours but the media lives forever. Top-performing
stories (high view count) still have shelf life — they just need a visual
transform before reposting to avoid being flagged as duplicate content.

Design decisions (CLAUDE.md fleet-scale audit):

    Visual transform seed:
        Each recycle is seeded by hash(account_id + story_id + repost_number).
        This means:
        - First recycle of a story always gets the same transform (stable)
        - Second recycle always gets a different transform (variety)
        - Different accounts recycling the same story each get unique transforms
        - No two recycles across the fleet share pixel hash → no content cluster

    Cooldown filter (>= 7 days):
        Code-enforced. Prevents the same story appearing twice in the same
        week, which looks obviously automated.

    Repost count cap (< 3):
        Code-enforced. Diminishing returns after 3 reposts; also prevents
        a single viral story from crowding out fresh content.

    Sort by view_count descending:
        Best performers first — we recycle the highest-value content when the
        daily cap allows only 1-2 recycles.

    Stagger between recycles:
        LogNormal(mean=ln(3600), sigma=0.5) — median ~1 hour, heavy right tail.
        Prevents multiple recycles being posted in rapid succession.

    Daily cap 2/day:
        Code-enforced. More than 2 recycled stories per day is spammy and
        crowds the creator's story feed, suppressing fresh content performance.

Agent audit table (CLAUDE.md):
    ┌─────────────────┬──────────────────────────────────────────────────────┐
    │ Agent           │ IGStoryRecyclerAgent                                 │
    │ Purpose         │ Recycle high-view stories after 7-day cooldown       │
    │ Tools           │ APK /media/transform + IGForegroundPostAgent         │
    │ Untrusted input │ story_log from caller (trusted internal source)       │
    │ User isolation  │ Keyed by account_id — no shared state                │
    │ Cost cap        │ No LLM — zero per-run LLM cost                       │
    │ Loop cap        │ 2 recycles/day (code-enforced)                       │
    │ Confirmation    │ None required                                        │
    └─────────────────┴──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import IGSession

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Daily hard cap — code-enforced
# ---------------------------------------------------------------------------

_DAILY_RECYCLE_CAP: int = 2

# ---------------------------------------------------------------------------
# Cooldown / quality filters — code-enforced
# ---------------------------------------------------------------------------

_MIN_DAYS_BEFORE_RECYCLE: int  = 7     # must be at least 7 days since original post
_MAX_REPOST_COUNT: int         = 3     # never recycle more than 3 times total
_DEFAULT_VIEW_THRESHOLD: int   = 500   # minimum view count to qualify for recycling

# ---------------------------------------------------------------------------
# Stagger between recycles
# LogNormal(mean=ln(3600), sigma=0.5) → median ~1hr, heavy tail to several hrs
# ---------------------------------------------------------------------------

_RECYCLE_STAGGER_DIST = LogNormal(low=300.0, high=14400.0, sigma=0.50)


# ---------------------------------------------------------------------------
# Story log entry
# ---------------------------------------------------------------------------

@dataclass
class StoryLogEntry:
    """Performance record for a previously-posted story."""
    story_id:       str
    media_url:      str
    view_count:     int
    posted_at_iso:  str   # "YYYY-MM-DDTHH:MM:SS+00:00" ISO 8601
    reposted_count: int   = 0


# ---------------------------------------------------------------------------
# Task type
# ---------------------------------------------------------------------------

@dataclass
class IGStoryRecyclerTask:
    """Input for one IGStoryRecyclerAgent run."""
    account_id:       str
    ig_session:       IGSession
    story_log:        list[StoryLogEntry]
    phone_ip:         str
    phone_serial:     str
    clone_package:    str
    of_link:          Optional[str] = None     # optional link sticker on recycled story
    apk_port:         int = 8090
    recycles_today:   int = 0
    view_threshold:   int = _DEFAULT_VIEW_THRESHOLD
    proxy_url:        str = "socks5://127.0.0.1:8089"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IGStoryRecyclerAgent:
    """
    Recycles top-performing stories after a cooldown period.
    Applies fresh visual transform before reposting so it's not identical.
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        # http_client is injectable for testing; real usage creates one per run
        self._http_client = http_client

    async def run_recycler(
        self,
        task: IGStoryRecyclerTask,
    ) -> WorkerResult:
        """
        Filter eligible stories, transform + repost the top performers.

        Steps:
            1. Check daily cap
            2. Filter: view_count >= threshold AND days_since >= 7 AND reposted_count < 3
            3. Sort by view_count descending (best performers first)
            4. For each candidate (up to remaining cap):
               a. Download media via URL
               b. Apply StoryTransformHelper via /media/transform APK endpoint
               c. Post as new story via /instagram/story APK endpoint
               d. Increment reposted_count in task.story_log
               e. LogNormal stagger before next recycle
            5. Return WorkerResult with per-recycle audit log
        """
        # Step 1: daily cap check
        if task.recycles_today >= _DAILY_RECYCLE_CAP:
            msg = (
                f"daily_recycle_cap_reached:"
                f"{task.recycles_today}/{_DAILY_RECYCLE_CAP} "
                f"for account {task.account_id}"
            )
            log.warning("[%s] %s", task.account_id, msg)
            return _failure_result(task, [msg])

        remaining_cap = _DAILY_RECYCLE_CAP - task.recycles_today

        # Step 2: filter candidates
        now_ts = datetime.now(timezone.utc).timestamp()
        candidates: list[StoryLogEntry] = []
        for entry in task.story_log:
            try:
                posted_ts = datetime.fromisoformat(entry.posted_at_iso).timestamp()
            except (ValueError, TypeError):
                log.warning(
                    "[%s] bad posted_at_iso for story %s: %r",
                    task.account_id, entry.story_id, entry.posted_at_iso,
                )
                continue

            days_since = (now_ts - posted_ts) / 86400.0

            if entry.view_count < task.view_threshold:
                continue
            if days_since < _MIN_DAYS_BEFORE_RECYCLE:
                continue
            if entry.reposted_count >= _MAX_REPOST_COUNT:
                continue

            candidates.append(entry)

        if not candidates:
            log.info(
                "[%s] no eligible stories to recycle "
                "(threshold=%d, min_days=%d, max_reposts=%d)",
                task.account_id,
                task.view_threshold,
                _MIN_DAYS_BEFORE_RECYCLE,
                _MAX_REPOST_COUNT,
            )
            return WorkerResult(
                task_id    = f"ig_story_recycler_{task.account_id}",
                platform   = "instagram",
                account_id = task.account_id,
                success    = True,
                error      = None,
                data       = {
                    "recycled_count": 0,
                    "recycled":       [],
                    "reason":         "no_eligible_stories",
                },
            )

        # Step 3: sort best performers first
        candidates.sort(key=lambda e: e.view_count, reverse=True)
        batch = candidates[:remaining_cap]

        apk_base_url = f"http://{task.phone_ip}:{task.apk_port}"
        recycled: list[dict] = []
        errors:   list[str]  = []

        async with (self._http_client or httpx.AsyncClient(timeout=60.0)) as client:
            for i, entry in enumerate(batch):
                repost_number = entry.reposted_count + 1   # 1-based repost index

                # Step 4a: download media
                try:
                    media_resp = await client.get(entry.media_url, timeout=30.0)
                    media_resp.raise_for_status()
                    media_bytes = media_resp.content
                    content_type = media_resp.headers.get("content-type", "image/jpeg")
                except Exception as exc:
                    err = (
                        f"media_download_failed:story_id={entry.story_id}:"
                        f"{type(exc).__name__}:{exc}"
                    )
                    log.error("[%s] %s", task.account_id, err)
                    errors.append(err)
                    continue

                # Step 4b: visual transform via APK /media/transform
                transform_seed = _make_transform_seed(
                    task.account_id, entry.story_id, repost_number,
                )
                try:
                    transform_resp = await client.post(
                        f"{apk_base_url}/media/transform",
                        content=media_bytes,
                        headers={"Content-Type": content_type},
                        params={
                            "seed":       str(transform_seed),
                            "accountId":  task.account_id,
                        },
                    )
                    transform_resp.raise_for_status()
                    transformed_bytes = transform_resp.content
                    transformed_content_type = transform_resp.headers.get(
                        "content-type", content_type,
                    )
                except Exception as exc:
                    err = (
                        f"transform_failed:story_id={entry.story_id}:"
                        f"seed={transform_seed}:"
                        f"{type(exc).__name__}:{exc}"
                    )
                    log.error("[%s] %s", task.account_id, err)
                    errors.append(err)
                    continue

                # Step 4c: post as new story via APK /instagram/story
                ext = ".jpg" if "jpeg" in transformed_content_type else ".mp4"
                staged_path = f"/sdcard/DCIM/PhantomFleet/{task.account_id}_recycle_{transform_seed}{ext}"

                story_payload: dict = {
                    "mediaPath":    staged_path,
                    "caption":      "",
                    "accountId":    task.account_id,
                    "clonePackage": task.clone_package,
                    "postType":     "STORY",
                    "mediaBytes":   transformed_bytes.hex(),
                    "transformSeed": transform_seed,
                }
                if task.of_link:
                    story_payload["linkSticker"] = task.of_link

                try:
                    story_resp = await client.post(
                        f"{apk_base_url}/instagram/story",
                        json=story_payload,
                    )
                    story_resp.raise_for_status()
                    story_data = story_resp.json()
                except Exception as exc:
                    err = (
                        f"story_post_failed:story_id={entry.story_id}:"
                        f"{type(exc).__name__}:{exc}"
                    )
                    log.error("[%s] %s", task.account_id, err)
                    errors.append(err)
                    continue

                if not story_data.get("success"):
                    apk_err = story_data.get("error", "unknown_apk_error")
                    err = f"story_post_apk_error:story_id={entry.story_id}:{apk_err}"
                    log.warning("[%s] %s", task.account_id, err)
                    errors.append(err)
                    continue

                # Step 4d: increment repost count
                entry.reposted_count += 1
                recycled.append({
                    "story_id":       entry.story_id,
                    "view_count":     entry.view_count,
                    "repost_number":  repost_number,
                    "transform_seed": transform_seed,
                })
                log.info(
                    "[%s] recycled story %s (views=%d, repost_number=%d, seed=%d)",
                    task.account_id,
                    entry.story_id,
                    entry.view_count,
                    repost_number,
                    transform_seed,
                )

                # Step 4e: stagger (except after the last recycle)
                if i < len(batch) - 1:
                    gap = _RECYCLE_STAGGER_DIST.sample()
                    log.debug(
                        "[%s] sleeping %.0fs before next recycle",
                        task.account_id, gap,
                    )
                    await asyncio.sleep(gap)

        return WorkerResult(
            task_id    = f"ig_story_recycler_{task.account_id}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = len(recycled) > 0 or (not errors and not recycled),
            error      = "; ".join(errors) if errors else None,
            data       = {
                "recycled_count": len(recycled),
                "recycled":       recycled,
                "errors":         errors,
            },
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _make_transform_seed(
    account_id: str,
    story_id: str,
    repost_number: int,
) -> int:
    """
    Deterministic transform seed for one (account, story, repost) combination.

    - Same account + same story + same repost_number → always the same transform
    - Different account → different transform (no two accounts share the same output)
    - Different repost_number → different transform (each recycle looks fresh)

    Uses SHA-256 for diffusion so sequential inputs don't produce correlated seeds.
    Truncated to a 31-bit positive integer for APK compatibility.
    """
    payload = f"{account_id}|{story_id}|{repost_number}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF  # 31-bit positive int


def _failure_result(task: IGStoryRecyclerTask, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id    = f"ig_story_recycler_{task.account_id}",
        platform   = "instagram",
        account_id = task.account_id,
        success    = False,
        error      = "; ".join(errors),
        data       = {
            "recycled_count": 0,
            "errors":         errors,
        },
    )
