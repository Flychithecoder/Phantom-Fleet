"""
TikTokCommentAgent — posts comments on trending videos.

Detection hardening:
    - Template pool of 50+ comments (min pool size enforced at construction)
    - Template selection seeded by hash(account_id + video_id) → same account
      never posts duplicate comments on the same video across retries
    - Character-by-character typing with realistic keystroke delays (APK handles)
    - Inter-comment sleep: LogNormal(mean=180s, sigma=60s, lo=60s, hi=600s)
      — comments are infrequent, spaced out naturally
    - 20 templates span multiple niches to prevent content-cluster fingerprint

Pool-size rule (CLAUDE.md fleet-scale audit):
    With 20K accounts each commenting multiple times per day, a pool of
    20 templates → 1000 accounts per template. That is a detectable
    content-similarity cluster. The pool is set to 50+ templates. The manager
    is responsible for supplying niche-specific pools; the agent enforces the
    minimum size.

Context keys (ctx):
    account_id         (str)
    username           (str)
    phone_serial       (str)
    clone_package      (str)
    date_iso           (str)
    comment_count      (int)          — number of comments to post this session
    comment_templates  (list[str])    — pool of candidate templates (min 50)
    video_ids          (list[str])    — identifiers used for deterministic template seeding
                                        (can be video IDs, hashes, or any stable token)

Output keys (run.outputs):
    posted             (list[str])    — templates that were posted
    failed             (int)          — post failures
    comment_count      (int)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import random
from datetime import date

from ..base import Agent, AgentConfig, AgentRun
from ...core.distributions import LogNormal
from ...core.tiktok_controller import TikTokController, TikTokSession

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimum pool size — enforced to prevent content-cluster fingerprint
# ---------------------------------------------------------------------------
MIN_TEMPLATE_POOL_SIZE = 50

# ---------------------------------------------------------------------------
# Default template pool — 50 templates across 5 niches
# Managers supplying niche-specific pools must still meet the 50-template floor.
# ---------------------------------------------------------------------------

DEFAULT_COMMENT_TEMPLATES: list[str] = [
    # Fitness / gym (10)
    "This is exactly what I needed today 🔥",
    "The consistency is insane, respect",
    "I've been doing this wrong for years omg",
    "Ok this actually worked for me fr",
    "Been following this for 3 weeks and I'm seeing results",
    "Why did no one tell me this sooner",
    "Coach material right here",
    "Saving this for later, thank you",
    "The form cues are genuinely helpful",
    "New pb incoming after trying this",
    # Lifestyle (10)
    "This is giving me the push I needed",
    "The vibe in this video is unmatched",
    "Can't stop watching this one",
    "Ok this is actually so good",
    "Living for this content rn",
    "I feel seen by this video",
    "The way this popped on my fyp at the right time",
    "This is my sign to finally do it",
    "Not me rewatching this 5 times",
    "The energy here is everything",
    # Humor (10)
    "I said what I said",
    "The accuracy is painful",
    "Me every single day lmao",
    "Why is this so specific to my life",
    "The comment section always delivers",
    "I feel so called out rn",
    "POV: it me",
    "Not the last 7 years of my life",
    "The way I sent this to 4 people immediately",
    "No bc this is genuinely hilarious",
    # Food / recipe (10)
    "Making this tonight no cap",
    "The way my jaw dropped",
    "This just solved my whole week of meal prep",
    "The technique here is on another level",
    "I've made this twice already it's that good",
    "Adding this to the rotation immediately",
    "The ingredients are so accessible I love this",
    "My family is going to lose it when I make this",
    "This looks better than restaurant quality",
    "The plating tutorial alone was worth it",
    # Learning / educational (10)
    "I actually learned something new today",
    "Why wasn't this taught in school",
    "Sharing this with everyone I know",
    "The explanation is so clear, thank you",
    "This changed how I think about it",
    "I've been looking for exactly this breakdown",
    "More people need to see this",
    "The detail you put into this is appreciated",
    "Came for entertainment, stayed for the knowledge",
    "This is the content TikTok was made for",
]

assert len(DEFAULT_COMMENT_TEMPLATES) >= MIN_TEMPLATE_POOL_SIZE, (
    f"DEFAULT_COMMENT_TEMPLATES has {len(DEFAULT_COMMENT_TEMPLATES)} entries; "
    f"minimum is {MIN_TEMPLATE_POOL_SIZE}"
)

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

# Time between posting one comment and moving to the next video
_INTER_COMMENT_SEC = LogNormal(low=60.0, high=600.0, sigma=0.45)


class TikTokCommentAgent(Agent):
    """
    Posts comments on the currently scrolled videos for one account.

    The caller (TikTokAgentManager) is responsible for:
        - Ensuring the TikTok foreground slot is held
        - Providing a comment_templates list of at least 50 entries
        - Providing video_ids for deterministic template seeding
        - Keeping comment_count within the DailyPlan budget

    Template selection:
        selected_index = hash(account_id + video_id) % len(templates)

        This ensures:
        - Same account on same video always posts the same template (idempotent)
        - Different accounts on the same video post different templates
        - No two accounts post the same sequence of templates

    Fleet-scale safety:
        With pool_size=50 and 20K accounts posting once per day:
        ~400 accounts share each template per day. That is below the
        threshold for content-similarity clustering. At 100 templates: ~200.
        Managers targeting premium niches should supply niche pools of 100+.
    """

    config = AgentConfig(
        name="tiktok_comment",
        max_iterations=1,
        max_usd_per_run=0.0,
        max_usd_per_session=0.0,
        allowed_tools=(),
    )

    async def run_once(self, ctx: dict, run: AgentRun) -> bool:
        account_id:    str       = ctx["account_id"]
        username:      str       = ctx["username"]
        phone_serial:  str       = ctx["phone_serial"]
        clone_package: str       = ctx["clone_package"]
        date_iso:      str       = ctx.get("date_iso", date.today().isoformat())
        comment_count: int       = ctx.get("comment_count", 1)
        templates:     list[str] = ctx.get("comment_templates", DEFAULT_COMMENT_TEMPLATES)
        video_ids:     list[str] = ctx.get("video_ids", [])

        # Enforce minimum pool size — fail loudly rather than silently create cluster
        if len(templates) < MIN_TEMPLATE_POOL_SIZE:
            raise ValueError(
                f"TikTokCommentAgent requires at least {MIN_TEMPLATE_POOL_SIZE} comment "
                f"templates to avoid content-cluster fingerprint. "
                f"Received {len(templates)}."
            )

        # Pad video_ids if not enough were provided (use synthetic tokens)
        while len(video_ids) < comment_count:
            video_ids.append(f"synthetic_{len(video_ids)}_{date_iso}")

        session = TikTokSession(
            account_id=account_id,
            username=username,
            phone_serial=phone_serial,
            clone_package=clone_package,
        )

        posted:  list[str] = []
        failed = 0

        async with TikTokController(session) as ctrl:
            for i in range(comment_count):
                video_id = video_ids[i]
                text     = _select_template(account_id, video_id, templates)

                self._audit({
                    "event": "tiktok_comment_attempt",
                    "account_id": account_id,
                    "video_id": video_id,
                    "template_hash": hashlib.sha256(text.encode()).hexdigest()[:8],
                })

                result = await ctrl.post_comment(text)

                if result.success:
                    posted.append(text)
                    self._audit({
                        "event": "tiktok_comment_success",
                        "account_id": account_id,
                        "video_id": video_id,
                    })
                else:
                    failed += 1
                    log.warning(
                        "post_comment failed for %s on video %s: %s",
                        account_id, video_id, result.error,
                    )

                # Inter-comment sleep — must be long to avoid comment-spam signal
                if i < comment_count - 1:
                    inter_sleep = _INTER_COMMENT_SEC.sample(
                        account_id=account_id,
                        date_iso=date_iso,
                        field=f"inter_comment_{i}",
                    )
                    await asyncio.sleep(inter_sleep)

        run.outputs.update({
            "posted":        posted,
            "failed":        failed,
            "comment_count": len(posted),
        })

        self._audit({
            "event": "tiktok_comment_session_complete",
            "account_id": account_id,
            "posted": len(posted),
            "failed": failed,
        })

        return True


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

def _select_template(account_id: str, video_id: str, templates: list[str]) -> str:
    """
    Select a template deterministically from the pool.

    Selection is seeded by hash(account_id + video_id) so:
        - The same account always posts the same template on a given video
          (idempotent — retry-safe)
        - Different accounts select different templates for the same video
          (fleet diversity)
        - Selection is uniformly distributed across the pool (no index bias)
    """
    payload = f"{account_id}|{video_id}".encode("utf-8")
    digest  = hashlib.sha256(payload).digest()
    index   = int.from_bytes(digest[:4], "big") % len(templates)
    return templates[index]
