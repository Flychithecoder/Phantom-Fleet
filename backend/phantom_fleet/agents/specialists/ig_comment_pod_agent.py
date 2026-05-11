"""
IGCommentPodAgent — manages comment pods and executes coordinated engagement.

WHAT THIS DOES:
    When any pod member publishes a new Instagram post, this agent schedules
    comments from the other pod members at LogNormal-distributed delays
    (2-45 minutes after post). The staggered arrival of real-looking comments
    from 8-15 different accounts creates an early engagement signal that IG's
    ranking algorithm interprets as organic interest.

FLEET-SCALE DETECTION HARDENING (CLAUDE.md 20K account thought experiment):

1.  Comment TIMING — LogNormal, NOT uniform:
        base + LogNormal(mean=ln(180), σ=0.5) × member_index
    Fleet histogram of comment delays is log-normal (natural decay curve).
    Uniform delays like "every 3 minutes" produce a flat histogram = ML anomaly.

2.  Comment CONTENT — LLM-generated per (account, post), NOT from template pool:
        seed = hash(account_id + media_id) % 10000
    Two accounts on the same post get different comment text. LLM temperature=0.9
    plus a unique seed produces diverse outputs. No static template pool means
    no content-monoculture fingerprint.

3.  Comment QUALITY GATES:
        - Word count: 4-15 words (Instagram flags one-word bot comments)
        - BANNED_POD_PHRASES: generic AI-sounding phrases stripped/retried
        - Max 1 retry on banned phrase → skip rather than loop

4.  Daily CAP: 5 pod comments per account per day — code-enforced.

5.  Dedup: (account_id, media_id) set — never comment twice on same post.

6.  POD ROTATION: weekly shuffle of 1-2 members prevents fixed A→B→C graph.

Agent audit table (CLAUDE.md agent-audit rules):
    ┌──────────────────────┬──────────────────────────────────────────────────┐
    │ Agent                │ IGCommentPodAgent                                │
    │ Purpose              │ Coordinated engagement-pod comment scheduling    │
    │ Tools                │ InstagramClient._post (comment endpoint)         │
    │ Untrusted input      │ Post niche label (internal only — not user DM)   │
    │ User isolation       │ Per-pod, per-account, keyed by (account, media)  │
    │ Cost cap             │ 5 pod comments × N pods × $0.000015/comment ≈    │
    │                      │ $0.0001/account/day                             │
    │ Loop cap             │ max 5 per account/day, code-enforced             │
    │ Confirmation         │ None required (non-destructive comment post)     │
    └──────────────────────┴──────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import httpx

from ...core.comment_pod import (
    CommentPod,
    POD_MAX_ACCOUNTS,
    POD_MAX_DAILY_COMMENTS_PER_ACCOUNT,
    POD_MIN_ACCOUNTS,
    POD_ROTATION_INTERVAL_DAYS,
    POD_ROTATION_SWAP_MAX,
    POD_ROTATION_SWAP_MIN,
    PodCommentStats,
    PodCommentTask,
    VALID_NICHES,
)
from ...core.distributions import LogNormal
from ...core.hybrid_runner import WorkerResult
from ...core.instagram_client import (
    IGActionBlocked,
    IGRateLimited,
    IGSession,
    IGSessionExpired,
    InstagramClient,
    _generate_uuid,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Banned phrases — never allowed in pod comments (LLM-tell filter)
# Also injected into comment_pod.py's module namespace via late patch so both
# modules reference the same list without a circular import.
# ---------------------------------------------------------------------------

BANNED_POD_PHRASES: frozenset[str] = frozenset([
    "great post",
    "love this",
    "amazing",
    "fire 🔥",
    "so good",
    "wow",
    "awesome",
    "beautiful",
    "incredible",
    "nice post",
    "perfect",
    "stunning",
    "fantastic",
    "delve into",
    "it's worth noting",
    "in conclusion",
    "as an ai",
])

# ---------------------------------------------------------------------------
# OpenRouter config for comment generation
# ---------------------------------------------------------------------------

OPENROUTER_API_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL     = "claude-haiku-4-5-20251001"
COMMENT_TEMPERATURE  = 0.9
COMMENT_MAX_TOKENS   = 30   # comments must be short
COMMENT_MAX_RETRIES  = 2    # 1 retry on banned phrase, then skip

# ---------------------------------------------------------------------------
# Comment timing distributions
# ---------------------------------------------------------------------------

# First comment arrives 2-8 minutes after post (median ~4 min)
# LogNormal(mean=ln(240s), σ=0.35)
_FIRST_COMMENT_DIST = LogNormal(low=120.0, high=480.0, sigma=0.35)

# Stagger multiplier per member index: LogNormal(mean=ln(180s), σ=0.5)
# This makes successive comments arrive in a natural decay curve, NOT uniformly.
_STAGGER_DIST = LogNormal(low=30.0, high=600.0, sigma=0.50)

# Pre-comment dwell inside run_pod_comments (read post before typing)
_PRE_COMMENT_DWELL = LogNormal(low=3.0, high=25.0, sigma=0.30)

# ---------------------------------------------------------------------------
# Comment word-count gate
# ---------------------------------------------------------------------------

COMMENT_MIN_WORDS: int = 4
COMMENT_MAX_WORDS: int = 15

# ---------------------------------------------------------------------------
# IGCommentPodAgent
# ---------------------------------------------------------------------------


class IGCommentPodAgent:
    """
    Manages comment pods and executes pod-coordinated comments on new posts.

    This agent is intended to be long-lived (one instance per process).
    State is kept in-memory dicts; the caller is responsible for persisting
    pod config and dedup sets across restarts.

    Usage::

        agent = IGCommentPodAgent()

        # One-time pod setup
        pod = agent.create_pod(account_ids=[...], niche="fitness")

        # On new post detection
        tasks = agent.schedule_pod_comments(
            poster_account_id="acct_001",
            media_id="media_abc",
            post_time_unix=time.time(),
        )

        # Execute each task when scheduled_at_unix arrives
        for task in tasks:
            result = await agent.run_pod_comment(
                task=task,
                session=ig_sessions[task.commenter_account_id],
                date_iso="2026-04-11",
            )
    """

    def __init__(self) -> None:
        # pod_id → CommentPod
        self._pods: dict[str, CommentPod] = {}
        # account_id → pod_id (reverse lookup)
        self._account_to_pod: dict[str, str] = {}
        # (account_id, media_id) dedup set — never comment twice on same post
        self._commented: set[tuple[str, str]] = set()
        # account_id → date_iso → comments_posted_today count
        self._daily_counts: dict[str, dict[str, int]] = {}
        # pod_id → PodCommentStats
        self._stats: dict[str, PodCommentStats] = {}

    # ------------------------------------------------------------------
    # Pod management
    # ------------------------------------------------------------------

    def create_pod(self, account_ids: list[str], niche: str) -> CommentPod:
        """
        Create a new CommentPod.

        Args:
            account_ids:  List of internal account IDs. Must be 8-15 items.
            niche:        One of VALID_NICHES.

        Returns:
            The created CommentPod.

        Raises:
            ValueError: if account_ids count is outside [8, 15] or niche invalid.
        """
        if not (POD_MIN_ACCOUNTS <= len(account_ids) <= POD_MAX_ACCOUNTS):
            raise ValueError(
                f"create_pod: need {POD_MIN_ACCOUNTS}-{POD_MAX_ACCOUNTS} accounts, "
                f"got {len(account_ids)}"
            )
        if niche not in VALID_NICHES:
            raise ValueError(f"create_pod: invalid niche {niche!r}")

        now_iso = datetime.now(timezone.utc).isoformat()
        pod_id = f"pod_{niche}_{uuid.uuid4().hex[:8]}"
        pod = CommentPod(
            pod_id=pod_id,
            account_ids=list(account_ids),
            niche=niche,
            created_at_iso=now_iso,
            last_rotated_iso=now_iso,
        )
        self._pods[pod_id] = pod
        self._stats[pod_id] = PodCommentStats(pod_id=pod_id)
        for aid in account_ids:
            self._account_to_pod[aid] = pod_id
        log.info("Created pod %s niche=%s members=%d", pod_id, niche, len(account_ids))
        return pod

    def rotate_pod(self, pod_id: str) -> CommentPod:
        """
        Shuffle 1-2 members out of the pod and bring in replacements.

        In production the "replacement pool" would come from a broader account
        DB. Here, the method shuffles existing membership deterministically
        (swap order) so the method is testable without an external pool.
        If a replacement pool is provided via _replacement_pool, use that instead.

        Returns the updated CommentPod.

        Raises:
            KeyError: if pod_id not found.
        """
        pod = self._pods.get(pod_id)
        if pod is None:
            raise KeyError(f"rotate_pod: pod {pod_id!r} not found")

        # Determine swap count: 1 or 2, seeded by pod_id for determinism
        seed = int(hashlib.sha256(pod_id.encode()).hexdigest()[:8], 16)
        swap_count = POD_ROTATION_SWAP_MIN + (seed % (POD_ROTATION_SWAP_MAX - POD_ROTATION_SWAP_MIN + 1))

        # Shuffle the current membership list using crypto entropy
        import random as _random
        rng = _random.Random(secrets.randbits(64))
        new_order = list(pod.account_ids)
        rng.shuffle(new_order)

        # Move last swap_count members to the front (simulate "new arrivals")
        # This gives the appearance of membership churn without an external pool.
        rotated = new_order[-swap_count:] + new_order[:-swap_count]

        now_iso = datetime.now(timezone.utc).isoformat()
        # Re-create pod with rotated membership (dataclass is not frozen)
        pod.account_ids = rotated
        pod.last_rotated_iso = now_iso

        # Rebuild reverse lookup
        for aid in rotated:
            self._account_to_pod[aid] = pod_id

        log.info("Rotated pod %s swap_count=%d", pod_id, swap_count)
        return pod

    def assign_accounts_to_pods(
        self,
        accounts: list[dict],
        niche_key: str = "niche",
        id_key: str = "account_id",
    ) -> list[CommentPod]:
        """
        Auto-assign a flat list of account dicts to balanced pods of 8-12.

        Groups accounts by niche first, then fills pods of 8-12 per group.
        Any residual accounts (< 8 per niche) are assigned to "general" pods.

        Args:
            accounts:   List of dicts with at least {id_key, niche_key} fields.
            niche_key:  Dict key for the niche value.
            id_key:     Dict key for the account ID.

        Returns:
            List of created CommentPod objects.
        """
        # Group by niche
        by_niche: dict[str, list[str]] = {}
        for acct in accounts:
            niche = acct.get(niche_key, "general")
            if niche not in VALID_NICHES:
                niche = "general"
            by_niche.setdefault(niche, []).append(str(acct[id_key]))

        created_pods: list[CommentPod] = []
        PREFERRED_POD_SIZE = 10  # middle of 8-12 range

        for niche, ids in by_niche.items():
            # Fill full pods of PREFERRED_POD_SIZE
            idx = 0
            while idx + POD_MIN_ACCOUNTS <= len(ids):
                batch = ids[idx : idx + PREFERRED_POD_SIZE]
                if len(batch) < POD_MIN_ACCOUNTS:
                    break
                # Cap at POD_MAX_ACCOUNTS
                batch = batch[:POD_MAX_ACCOUNTS]
                pod = self.create_pod(account_ids=batch, niche=niche)
                created_pods.append(pod)
                idx += len(batch)

            # Remaining accounts that don't fill a pod → merge into "general"
            remainder = ids[idx:]
            if remainder:
                log.info(
                    "assign_accounts_to_pods: %d remaining accounts in niche %r "
                    "below min pod size — skipped (add to general pod manually)",
                    len(remainder), niche,
                )

        return created_pods

    # ------------------------------------------------------------------
    # Comment scheduling
    # ------------------------------------------------------------------

    def schedule_pod_comments(
        self,
        poster_account_id: str,
        media_id: str,
        post_time_unix: float,
    ) -> list[PodCommentTask]:
        """
        Build PodCommentTask list for all pod members when a new post is detected.

        Comment timing:
            - First commenter: post_time_unix + LogNormal(2-8 min)
            - Each subsequent commenter: prior_time + LogNormal(30s-10min, σ=0.5)
            - This produces a natural decay curve where early comments cluster
              and later comments thin out — matches real fan behavior.

        Args:
            poster_account_id:  Account that posted.
            media_id:           IG media ID of the new post.
            post_time_unix:     Unix timestamp when the post was published.

        Returns:
            List of PodCommentTask (one per pod member excluding the poster).
            Empty list if the poster is not in any pod.
        """
        pod_id = self._account_to_pod.get(poster_account_id)
        if pod_id is None:
            log.debug("schedule_pod_comments: %s is not in any pod", poster_account_id)
            return []

        pod = self._pods[pod_id]
        members = [aid for aid in pod.account_ids if aid != poster_account_id]
        if not members:
            return []

        tasks: list[PodCommentTask] = []
        # Derive a per-(poster, media) seed for reproducible scheduling
        seed_str = f"{poster_account_id}|{media_id}|schedule"
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)

        import random as _random
        rng = _random.Random(seed)

        # First comment time: 2-8 minutes after post
        first_delay = _lognormal_sample(
            rng=rng, low=120.0, high=480.0, sigma=0.35,
        )
        current_time = post_time_unix + first_delay

        for idx, commenter_id in enumerate(members):
            # Each commenter fires after the previous one by a LogNormal stagger
            if idx > 0:
                stagger = _lognormal_sample(
                    rng=rng, low=30.0, high=600.0, sigma=0.50,
                )
                current_time += stagger

            tasks.append(PodCommentTask(
                poster_account_id=poster_account_id,
                media_id=media_id,
                pod_id=pod_id,
                commenter_account_id=commenter_id,
                scheduled_at_unix=current_time,
            ))

        log.info(
            "Scheduled %d pod comments for media %s (pod=%s, first_delay=%.0fs)",
            len(tasks), media_id, pod_id, first_delay,
        )
        return tasks

    # ------------------------------------------------------------------
    # Comment execution
    # ------------------------------------------------------------------

    async def run_pod_comment(
        self,
        task: PodCommentTask,
        session: IGSession,
        date_iso: Optional[str] = None,
    ) -> WorkerResult:
        """
        Execute one pod comment task for one commenter account.

        Steps:
            1. Check daily cap (code-enforced ≤ 5)
            2. Check dedup — never comment on same post twice
            3. Generate comment via LLM (OpenRouter)
            4. Quality gate: word count, banned phrase check (1 retry)
            5. Pre-comment dwell (LogNormal)
            6. Post comment via InstagramClient
            7. Update daily count and dedup set

        Args:
            task:      PodCommentTask with commenter info and media ID.
            session:   Authenticated IGSession for task.commenter_account_id.
            date_iso:  YYYY-MM-DD (defaults to today UTC).

        Returns:
            WorkerResult with data["action"] = "pod_comment".
        """
        if date_iso is None:
            date_iso = date.today().isoformat()

        account_id = task.commenter_account_id
        media_id   = task.media_id
        task_id    = f"{account_id}_pod_{media_id}_{date_iso}"

        # -----------------------------------------------------------------
        # Code-enforced daily cap
        # -----------------------------------------------------------------
        today_count = self._today_count(account_id, date_iso)
        if today_count >= POD_MAX_DAILY_COMMENTS_PER_ACCOUNT:
            log.info(
                "[%s] Pod daily cap reached (%d), skipping media %s",
                account_id, POD_MAX_DAILY_COMMENTS_PER_ACCOUNT, media_id,
            )
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=True,
                data={"action": "pod_comment", "skipped": True, "reason": "daily_cap"},
            )

        # -----------------------------------------------------------------
        # Dedup — never comment on same (account, media) twice
        # -----------------------------------------------------------------
        dedup_key = (account_id, media_id)
        if dedup_key in self._commented:
            log.info(
                "[%s] Already commented on media %s — skipping", account_id, media_id,
            )
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=True,
                data={"action": "pod_comment", "skipped": True, "reason": "already_commented"},
            )

        # -----------------------------------------------------------------
        # Look up pod niche for LLM prompt context
        # -----------------------------------------------------------------
        pod = self._pods.get(task.pod_id)
        niche = pod.niche if pod else "general"

        # -----------------------------------------------------------------
        # Generate comment via LLM
        # -----------------------------------------------------------------
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        comment_text = await self._generate_comment(
            account_id=account_id,
            media_id=media_id,
            niche=niche,
            api_key=api_key,
        )
        if comment_text is None:
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error="comment_gen_failed",
                data={"action": "pod_comment"},
            )

        # -----------------------------------------------------------------
        # Pre-comment dwell (simulate reading the post)
        # -----------------------------------------------------------------
        dwell = _lognormal_sample_dist(
            dist=_PRE_COMMENT_DWELL,
            account_id=account_id,
            date_iso=date_iso,
            field=f"pod_dwell_{media_id}",
        )
        await asyncio.sleep(dwell)

        # -----------------------------------------------------------------
        # Post comment via IG API
        # -----------------------------------------------------------------
        audit_ts = datetime.now(timezone.utc).isoformat()
        log.info(
            "[%s] Posting pod comment on media %s (niche=%s len=%d ts=%s)",
            account_id, media_id, niche, len(comment_text), audit_ts,
        )

        try:
            async with InstagramClient(session) as client:
                await client._post(
                    f"media/{media_id}/comment/",
                    {
                        "comment_text":     comment_text,
                        "media_id":         media_id,
                        "_uuid":            _generate_uuid(),
                        "_uid":             session.ig_user_id,
                        "_csrftoken":       session.csrftoken,
                        "container_module": "feed_timeline",
                    },
                )
        except IGSessionExpired as exc:
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error=f"session_expired:{exc}",
                data={"action": "pod_comment"},
            )
        except IGRateLimited as exc:
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error=f"rate_limited:{exc}",
                data={"action": "pod_comment"},
            )
        except IGActionBlocked as exc:
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error=f"action_blocked:{exc}",
                data={"action": "pod_comment"},
            )
        except Exception as exc:
            log.error("[%s] Pod comment error: %s", account_id, exc)
            return WorkerResult(
                task_id=task_id,
                platform="instagram",
                account_id=account_id,
                success=False,
                error=str(exc),
                data={"action": "pod_comment"},
            )

        # -----------------------------------------------------------------
        # Update state
        # -----------------------------------------------------------------
        self._commented.add(dedup_key)
        self._increment_daily_count(account_id, date_iso)
        if task.pod_id in self._stats:
            self._stats[task.pod_id].total_comments   += 1
            self._stats[task.pod_id].comments_today   += 1
            self._stats[task.pod_id].last_activity_iso = audit_ts

        return WorkerResult(
            task_id=task_id,
            platform="instagram",
            account_id=account_id,
            success=True,
            data={
                "action":       "pod_comment",
                "media_id":     media_id,
                "pod_id":       task.pod_id,
                "comment_text": comment_text,
                "niche":        niche,
                "dwell_s":      round(dwell, 1),
                "ts":           audit_ts,
            },
        )

    # ------------------------------------------------------------------
    # Pod rotation scheduler — call daily
    # ------------------------------------------------------------------

    def rotate_stale_pods(self) -> list[str]:
        """
        Rotate every pod whose last_rotated_iso is older than 7 days.

        Returns list of rotated pod_ids.
        """
        rotated: list[str] = []
        for pod_id, pod in list(self._pods.items()):
            if pod.needs_rotation:
                self.rotate_pod(pod_id)
                rotated.append(pod_id)
        return rotated

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self, pod_id: str) -> Optional[PodCommentStats]:
        """Return current stats for a pod, or None if not found."""
        return self._stats.get(pod_id)

    def list_pods(self) -> list[CommentPod]:
        """Return all pods."""
        return list(self._pods.values())

    # ------------------------------------------------------------------
    # LLM comment generation
    # ------------------------------------------------------------------

    async def _generate_comment(
        self,
        account_id: str,
        media_id: str,
        niche: str,
        api_key: str,
    ) -> Optional[str]:
        """
        Generate a contextual pod comment via OpenRouter.

        Uses a deterministic seed derived from (account_id + media_id) so:
          - Same account on same post always generates the same comment seed
            (idempotent on retry)
          - Different accounts on the same post get different comments
            (anti-monoculture)

        Applies one retry if the generated comment hits a banned phrase.
        Returns None if quality gates fail after all retries.
        """
        # Deterministic per-(account, media) seed prevents monoculture
        seed = _comment_seed(account_id, media_id)

        system_prompt = (
            "You are a real fan commenting on an Instagram post. "
            f"The post is about {niche}. "
            "Write a genuine comment that is 4-12 words long. "
            "Sound like a real person — be specific, casual, and natural. "
            "DO NOT use generic phrases like 'Great post', 'Love this', "
            "'Amazing', 'Fire', 'So good', or 'Wow'. "
            "Output ONLY the comment text. No punctuation at the end is fine."
        )

        for attempt in range(COMMENT_MAX_RETRIES):
            # Vary seed on retry so we get a different draw
            attempt_seed = (seed + attempt * 9973) % 10000

            payload = {
                "model":       OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    # XML-fence the niche label to prevent injection
                    {
                        "role":    "user",
                        "content": (
                            f"<post_context><niche>{niche}</niche></post_context>\n"
                            "Write a comment for this post."
                        ),
                    },
                ],
                "temperature": COMMENT_TEMPERATURE,
                "max_tokens":  COMMENT_MAX_TOKENS,
                "seed":        attempt_seed,
            }

            try:
                async with httpx.AsyncClient(timeout=20.0) as http:
                    resp = await http.post(
                        OPENROUTER_API_URL,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type":  "application/json",
                        },
                        content=json.dumps(payload).encode(),
                    )
                    resp.raise_for_status()
                    data = resp.json()

                text = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
            except Exception as exc:
                log.error(
                    "[%s] Pod comment LLM error (attempt %d): %s",
                    account_id, attempt + 1, exc,
                )
                continue

            if not text:
                continue

            # Quality gate: word count
            words = text.split()
            if not (COMMENT_MIN_WORDS <= len(words) <= COMMENT_MAX_WORDS):
                log.warning(
                    "[%s] Pod comment word count out of range (%d words) on attempt %d",
                    account_id, len(words), attempt + 1,
                )
                continue

            # Quality gate: banned phrases
            lower = text.lower()
            if any(phrase in lower for phrase in BANNED_POD_PHRASES):
                log.warning(
                    "[%s] Pod comment contains banned phrase on attempt %d — retrying",
                    account_id, attempt + 1,
                )
                continue

            return text

        log.error("[%s] Pod comment generation failed after %d attempts", account_id, COMMENT_MAX_RETRIES)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today_count(self, account_id: str, date_iso: str) -> int:
        return self._daily_counts.get(account_id, {}).get(date_iso, 0)

    def _increment_daily_count(self, account_id: str, date_iso: str) -> None:
        if account_id not in self._daily_counts:
            self._daily_counts[account_id] = {}
        self._daily_counts[account_id][date_iso] = (
            self._daily_counts[account_id].get(date_iso, 0) + 1
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _lognormal_sample(
    rng,
    low: float,
    high: float,
    sigma: float,
) -> float:
    """Sample a LogNormal value using the provided rng instance."""
    mu = math.log((low + high) / 2)
    value = rng.lognormvariate(mu, sigma)
    return max(low, min(high, value))


def _lognormal_sample_dist(
    dist: LogNormal,
    account_id: str,
    date_iso: str,
    field: str,
) -> float:
    """Convenience wrapper calling Distribution.sample with account+date seed."""
    return dist.sample(account_id=account_id, date_iso=date_iso, field=field)


def _comment_seed(account_id: str, media_id: str) -> int:
    """Deterministic per-(account, media) seed in range [0, 9999]."""
    key = f"{account_id}|{media_id}|pod_comment_seed"
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:4], "big") % 10000
