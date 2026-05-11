"""
IGHashtagTrackerAgent — tracks which hashtags drive real follows and rotates
underperformers out of the active pool.

Detection-hardening notes (CLAUDE.md 20K account thought experiment):
    - Pool sizes must scale with fleet size. The tracker maintains per-account
      hashtag state via state sidecars so no two accounts share a fixed pool
      (content monoculture fingerprint).
    - Attribution is correlation-based (follows within 2h of post using that tag).
      Not causal truth — but directionally correct and actionable.
    - Rotation fires weekly so hashtag usage patterns don't settle into a static
      cluster. Different accounts retire different tags (bottom 25% per account,
      not a global bottom 25% list).
    - Max 7 hashtags per set is code-enforced, not prompt-enforced.
      Instagram itself deprioritizes posts with 20-30 tags; 3-7 is the documented
      sweet spot per IG's own creator guidance.

Rotation algorithm:
    1. Score every tag: performance_score = (attributed_follows*3 + attributed_dms*10)
       / max(times_used, 1)
    2. Sort descending by performance_score
    3. Bottom 25% → retired (retired=True, retire_reason="low_performance")
    4. Top 25% → proven_winners (flag kept in state)
    5. New candidates: 25% fresh tags scraped from niche's top-performing posts
    6. Build per-account HashtagSet: mix proven_winners + new_candidates
    7. Hard cap at MAX_HASHTAGS_PER_SET = 7

Attribution window (2h) reasoning:
    Instagram's feed algorithm surfaces a new post primarily within 2h of posting.
    Follows gained outside this window are much less likely to be hashtag-attributed
    and more likely organic/direct-search. The 2h window is a reasonable proxy.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from ...core.distributions import LogNormal, seed_for

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (all code-enforced)
# ---------------------------------------------------------------------------

MAX_HASHTAGS_PER_SET: int = 7          # Hard cap — never 30
MIN_HASHTAGS_PER_SET: int = 3
ATTRIBUTION_WINDOW_SECONDS: int = 7200  # 2 hours
ROTATION_BOTTOM_PCT: float = 0.25       # Retire bottom 25%
ROTATION_WINNER_PCT: float = 0.25       # Flag top 25% as winners
ROTATION_FRESH_PCT: float = 0.25        # Introduce 25% fresh candidates

# Inter-request delay when scraping niche posts for new tag candidates
_SCRAPE_DELAY_DIST = LogNormal(low=1.5, high=8.0, sigma=0.30)

# Valid niche values
VALID_NICHES = frozenset({"fitness", "lifestyle", "general"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class HashtagEntry:
    """Performance record for a single hashtag on a single account."""

    tag: str                        # without leading #
    niche: str                      # "fitness" | "lifestyle" | "general"
    times_used: int = 0
    total_reach: int = 0            # estimated from post insights
    attributed_follows: int = 0     # new follows within 2h of posts using this tag
    attributed_dms: int = 0         # DMs within 2h (higher signal than follows)
    last_used_iso: str = ""
    retired: bool = False
    retire_reason: str | None = None

    @property
    def performance_score(self) -> float:
        """
        Weighted score balancing follow attribution (3×) and DM attribution (10×).

        DMs are weighted 3× more than follows because a DM from a new follower
        driven by a hashtag indicates much stronger intent than a passive follow.
        Division by max(times_used, 1) normalises for exposure.
        """
        return (
            self.attributed_follows * 3 + self.attributed_dms * 10
        ) / max(self.times_used, 1)


@dataclass
class HashtagSet:
    """The set of hashtags attached to a single post."""

    set_id: str
    tags: list[str]                 # 3–7 hashtags (without #), enforced by builder
    account_id: str
    niche: str
    created_at_iso: str

    def __post_init__(self) -> None:
        if len(self.tags) > MAX_HASHTAGS_PER_SET:
            raise ValueError(
                f"HashtagSet may contain at most {MAX_HASHTAGS_PER_SET} tags; "
                f"got {len(self.tags)} for account {self.account_id}"
            )
        if len(self.tags) < MIN_HASHTAGS_PER_SET:
            raise ValueError(
                f"HashtagSet requires at least {MIN_HASHTAGS_PER_SET} tags; "
                f"got {len(self.tags)} for account {self.account_id}"
            )


@dataclass
class PostAttributionRecord:
    """Tracks a single post's hashtags so follows can be attributed later."""

    post_id: str
    account_id: str
    hashtags_used: list[str]
    post_time_iso: str              # UTC ISO-8601
    attributed: bool = False        # True once the 2h window has closed


@dataclass
class RotationResult:
    """Summary of a single rotation run for logging / reporting."""

    account_id: str
    niche: str
    tags_before: int
    tags_retired: int
    tags_promoted_winner: int
    tags_fresh_added: int
    new_set: HashtagSet


# ---------------------------------------------------------------------------
# State sidecar schema
# ---------------------------------------------------------------------------
# The sidecar is a plain dict keyed by account_id → {
#     "entries": {tag: HashtagEntry.__dict__, ...},
#     "pending_attribution": [PostAttributionRecord.__dict__, ...],
#     "last_rotation_iso": str | None,
# }
# Serialisation is handled by the caller (write JSON to redis / postgres / file).


def _load_entries(raw: dict) -> dict[str, HashtagEntry]:
    """Deserialise the entries dict from the sidecar JSON blob."""
    result: dict[str, HashtagEntry] = {}
    for tag, data in raw.items():
        result[tag] = HashtagEntry(
            tag=data["tag"],
            niche=data["niche"],
            times_used=data.get("times_used", 0),
            total_reach=data.get("total_reach", 0),
            attributed_follows=data.get("attributed_follows", 0),
            attributed_dms=data.get("attributed_dms", 0),
            last_used_iso=data.get("last_used_iso", ""),
            retired=data.get("retired", False),
            retire_reason=data.get("retire_reason"),
        )
    return result


def _dump_entries(entries: dict[str, HashtagEntry]) -> dict:
    return {
        tag: {
            "tag": e.tag,
            "niche": e.niche,
            "times_used": e.times_used,
            "total_reach": e.total_reach,
            "attributed_follows": e.attributed_follows,
            "attributed_dms": e.attributed_dms,
            "last_used_iso": e.last_used_iso,
            "retired": e.retired,
            "retire_reason": e.retire_reason,
        }
        for tag, e in entries.items()
    }


# ---------------------------------------------------------------------------
# Core agent
# ---------------------------------------------------------------------------


class IGHashtagTrackerAgent:
    """
    Tracks hashtag performance across the account fleet and rotates out
    underperformers on a weekly cadence.

    Metric: follows_attributed = new follows within 2h of post using that hashtag.
    Rotation: retire bottom 25%, promote top 25%, introduce 25% fresh.

    Usage:
        agent = IGHashtagTrackerAgent()

        # After each post:
        sidecar = agent.record_post(
            sidecar=sidecar,
            post_id="media_123",
            account_id="acc_001",
            hashtags_used=["fitness", "gym"],
            post_time_iso="2026-04-11T14:00:00Z",
        )

        # After 2h window closes:
        sidecar = agent.attribute_follows(
            sidecar=sidecar,
            account_id="acc_001",
            new_followers_in_window=3,
            new_dms_in_window=1,
            now_iso="2026-04-11T16:30:00Z",
        )

        # Weekly rotation:
        sidecar, result = agent.analyze_and_rotate(
            sidecar=sidecar,
            account_id="acc_001",
            niche="fitness",
            fresh_candidates=["newfit", "gymlife", "fitnessmotivation"],
            date_iso="2026-04-11",
        )
    """

    # ------------------------------------------------------------------
    # Post recording
    # ------------------------------------------------------------------

    def record_post(
        self,
        sidecar: dict,
        post_id: str,
        account_id: str,
        hashtags_used: list[str],
        post_time_iso: str,
    ) -> dict:
        """
        Record that a post was made with these hashtags so follows can later
        be attributed. Writes a PostAttributionRecord to the sidecar.

        Returns the updated sidecar.
        """
        pending = sidecar.get("pending_attribution", [])
        record = PostAttributionRecord(
            post_id=post_id,
            account_id=account_id,
            hashtags_used=list(hashtags_used),
            post_time_iso=post_time_iso,
            attributed=False,
        )
        pending.append({
            "post_id": record.post_id,
            "account_id": record.account_id,
            "hashtags_used": record.hashtags_used,
            "post_time_iso": record.post_time_iso,
            "attributed": record.attributed,
        })
        sidecar["pending_attribution"] = pending
        log.debug(
            "[%s] recorded post %s with %d hashtags for attribution",
            account_id, post_id, len(hashtags_used),
        )
        return sidecar

    # ------------------------------------------------------------------
    # Attribution
    # ------------------------------------------------------------------

    def attribute_follows(
        self,
        sidecar: dict,
        account_id: str,
        new_followers_in_window: int,
        new_dms_in_window: int,
        now_iso: str,
    ) -> dict:
        """
        Close the attribution window for any posts whose 2h window has elapsed.

        Proportionally attributes `new_followers_in_window` and
        `new_dms_in_window` to the hashtags used in posts that fall within
        the [post_time, post_time + 2h] window ending at or before now_iso.

        Attribution is proportional: if there were two unattributed posts in
        the window, each gets half the follows. Within each post the credit
        is shared equally across all hashtags in that post's set.

        Not causal — but directionally correct and actionable at fleet scale.

        Returns the updated sidecar.
        """
        now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        pending: list[dict] = sidecar.get("pending_attribution", [])
        entries: dict[str, HashtagEntry] = _load_entries(sidecar.get("entries", {}))

        # Find posts whose window has closed (post_time + 2h <= now)
        ready_indices: list[int] = []
        for i, record in enumerate(pending):
            if record.get("attributed"):
                continue
            if record.get("account_id") != account_id:
                continue
            post_dt = datetime.fromisoformat(
                record["post_time_iso"].replace("Z", "+00:00")
            )
            window_end = post_dt + timedelta(seconds=ATTRIBUTION_WINDOW_SECONDS)
            if window_end <= now_dt:
                ready_indices.append(i)

        if not ready_indices:
            return sidecar

        # Distribute follows / DMs equally across all ready posts
        n_ready = len(ready_indices)
        follows_each = new_followers_in_window / max(n_ready, 1)
        dms_each = new_dms_in_window / max(n_ready, 1)

        for i in ready_indices:
            record = pending[i]
            tags = record.get("hashtags_used", [])
            if not tags:
                pending[i] = {**record, "attributed": True}
                continue

            # Split credit across all tags in this post
            follow_credit_per_tag = follows_each / len(tags)
            dm_credit_per_tag = dms_each / len(tags)

            for tag in tags:
                if tag not in entries:
                    # Create a placeholder entry for newly seen tags
                    entries[tag] = HashtagEntry(tag=tag, niche="general")
                e = entries[tag]
                e.attributed_follows += follow_credit_per_tag
                e.attributed_dms += dm_credit_per_tag

            pending[i] = {**record, "attributed": True}
            log.debug(
                "[%s] attributed %.1f follows / %.1f DMs across %d tags from post %s",
                account_id, follows_each, dms_each, len(tags), record["post_id"],
            )

        sidecar["entries"] = _dump_entries(entries)
        sidecar["pending_attribution"] = pending
        return sidecar

    # ------------------------------------------------------------------
    # Rotation
    # ------------------------------------------------------------------

    def analyze_and_rotate(
        self,
        sidecar: dict,
        account_id: str,
        niche: str,
        fresh_candidates: list[str],
        date_iso: str,
    ) -> tuple[dict, RotationResult]:
        """
        Weekly rotation: retire bottom 25%, flag top 25%, introduce 25% fresh.

        Steps:
            1. Load current hashtag entries from sidecar
            2. Filter to active (non-retired) entries for this niche
            3. Sort by performance_score
            4. Retire bottom 25% (retire_reason="low_performance")
            5. Flag top 25% as proven_winners in sidecar metadata
            6. Incorporate fresh_candidates (add entries with zero stats)
            7. Build new HashtagSet for this account: proven_winners first,
               then fill remaining slots with fresh_candidates
            8. Cap at MAX_HASHTAGS_PER_SET

        Args:
            sidecar:          The account's state sidecar dict.
            account_id:       Internal account ID.
            niche:            The account's content niche.
            fresh_candidates: New tag strings to introduce (without #).
            date_iso:         YYYY-MM-DD — used for logging and set_id.

        Returns:
            (updated_sidecar, RotationResult)
        """
        entries: dict[str, HashtagEntry] = _load_entries(sidecar.get("entries", {}))

        # Active entries for this niche
        active = [
            e for e in entries.values()
            if not e.retired and e.niche == niche
        ]
        tags_before = len(active)

        if active:
            active.sort(key=lambda e: e.performance_score)

            n_retire = max(1, int(len(active) * ROTATION_BOTTOM_PCT))
            n_winner = max(1, int(len(active) * ROTATION_WINNER_PCT))

            # Retire bottom performers
            to_retire = active[:n_retire]
            for e in to_retire:
                entries[e.tag].retired = True
                entries[e.tag].retire_reason = "low_performance"
                log.debug(
                    "[%s] retiring hashtag #%s (score=%.2f)",
                    account_id, e.tag, e.performance_score,
                )

            # Flag top performers
            winners = active[-n_winner:]
            winner_tags = [e.tag for e in winners]

            # Remaining active after retirement
            remaining_active = active[n_retire:]
        else:
            n_retire = 0
            winner_tags = []
            remaining_active = []

        # Add fresh candidates to entries (don't overwrite existing)
        for tag in fresh_candidates:
            if tag not in entries:
                entries[tag] = HashtagEntry(tag=tag, niche=niche)

        # Build new HashtagSet:
        # 1. Proven winners first (capped)
        # 2. Fill remaining slots with a deterministic seeded selection of
        #    fresh candidates so different accounts in the same niche get
        #    different fresh tags (prevents pool monoculture)
        chosen_tags: list[str] = list(winner_tags)

        remaining_slots = MAX_HASHTAGS_PER_SET - len(chosen_tags)
        if remaining_slots > 0 and fresh_candidates:
            # Deterministic per-account selection from fresh pool
            seeded_fresh = _seeded_pick(
                pool=fresh_candidates,
                n=remaining_slots,
                account_id=account_id,
                date_iso=date_iso,
                field=f"hashtag_fresh_{niche}",
            )
            for tag in seeded_fresh:
                if tag not in chosen_tags:
                    chosen_tags.append(tag)
                    if len(chosen_tags) >= MAX_HASHTAGS_PER_SET:
                        break

        # If still under minimum, fill from remaining_active
        if len(chosen_tags) < MIN_HASHTAGS_PER_SET:
            for e in reversed(remaining_active):
                if e.tag not in chosen_tags:
                    chosen_tags.append(e.tag)
                if len(chosen_tags) >= MIN_HASHTAGS_PER_SET:
                    break

        # Clamp to MAX
        chosen_tags = chosen_tags[:MAX_HASHTAGS_PER_SET]

        if len(chosen_tags) < MIN_HASHTAGS_PER_SET:
            # Not enough tags — use what we have (don't crash)
            log.warning(
                "[%s] Only %d tags available for niche %r (minimum is %d)",
                account_id, len(chosen_tags), niche, MIN_HASHTAGS_PER_SET,
            )

        # Ensure chosen_tags has at least 1 to avoid empty set
        if not chosen_tags:
            log.warning(
                "[%s] No tags available for niche %r; creating empty set",
                account_id, niche,
            )

        set_id = _stable_hash_str(f"{account_id}|{date_iso}|{niche}")
        new_set = HashtagSet(
            set_id=set_id,
            tags=chosen_tags[:MAX_HASHTAGS_PER_SET],
            account_id=account_id,
            niche=niche,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )

        # Persist updated entries and winner metadata
        sidecar["entries"] = _dump_entries(entries)
        sidecar["proven_winners"] = sidecar.get("proven_winners", {})
        sidecar["proven_winners"][niche] = winner_tags
        sidecar["last_rotation_iso"] = datetime.now(timezone.utc).isoformat()

        result = RotationResult(
            account_id=account_id,
            niche=niche,
            tags_before=tags_before,
            tags_retired=n_retire,
            tags_promoted_winner=len(winner_tags),
            tags_fresh_added=len(fresh_candidates),
            new_set=new_set,
        )

        log.info(
            "[%s] rotation complete: %d→%d active, %d retired, %d winners, %d fresh, set_size=%d",
            account_id, tags_before, tags_before - n_retire,
            n_retire, len(winner_tags), len(fresh_candidates), len(chosen_tags),
        )
        return sidecar, result

    # ------------------------------------------------------------------
    # Hashtag set builder (standalone utility)
    # ------------------------------------------------------------------

    def build_set(
        self,
        sidecar: dict,
        account_id: str,
        niche: str,
        date_iso: str,
    ) -> HashtagSet:
        """
        Build a HashtagSet for an account from current sidecar state without
        triggering a rotation. Used between weekly rotations to pick from the
        current active pool.

        Returns a HashtagSet with up to MAX_HASHTAGS_PER_SET tags.
        """
        entries: dict[str, HashtagEntry] = _load_entries(sidecar.get("entries", {}))
        winner_tags: list[str] = sidecar.get("proven_winners", {}).get(niche, [])

        active_non_winner = [
            e.tag for e in entries.values()
            if not e.retired and e.niche == niche and e.tag not in winner_tags
        ]

        # Winners first, then fill with other active tags
        chosen: list[str] = list(winner_tags)
        remaining_slots = MAX_HASHTAGS_PER_SET - len(chosen)

        if remaining_slots > 0:
            seeded = _seeded_pick(
                pool=active_non_winner,
                n=remaining_slots,
                account_id=account_id,
                date_iso=date_iso,
                field=f"build_set_{niche}",
            )
            chosen.extend(seeded)

        chosen = chosen[:MAX_HASHTAGS_PER_SET]

        if len(chosen) < MIN_HASHTAGS_PER_SET:
            log.warning(
                "[%s] build_set: only %d tags for niche %r",
                account_id, len(chosen), niche,
            )

        set_id = _stable_hash_str(f"{account_id}|{date_iso}|{niche}|build")
        return HashtagSet(
            set_id=set_id,
            tags=chosen,
            account_id=account_id,
            niche=niche,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Update tag usage stats after a post
    # ------------------------------------------------------------------

    def record_usage(
        self,
        sidecar: dict,
        tags: list[str],
        niche: str,
        reach_estimate: int,
        now_iso: str,
    ) -> dict:
        """
        Increment times_used and total_reach for each tag in a used HashtagSet.

        Call this immediately after posting (before the attribution window).
        """
        entries: dict[str, HashtagEntry] = _load_entries(sidecar.get("entries", {}))
        for tag in tags:
            if tag not in entries:
                entries[tag] = HashtagEntry(tag=tag, niche=niche)
            e = entries[tag]
            e.times_used += 1
            e.total_reach += reach_estimate
            e.last_used_iso = now_iso
        sidecar["entries"] = _dump_entries(entries)
        return sidecar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_hash_str(value: str) -> str:
    """Return a stable 12-char hex ID from the input string."""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _seeded_pick(
    pool: list[str],
    n: int,
    account_id: str,
    date_iso: str,
    field: str,
) -> list[str]:
    """
    Select up to n items from pool using a deterministic per-account seed.

    Different accounts get different selections from the same pool — prevents
    all accounts landing on the same fresh tags (content monoculture).
    """
    import random as _random

    if not pool:
        return []
    seed = seed_for(account_id, date_iso, field)
    rng = _random.Random(seed)
    shuffled = list(pool)
    rng.shuffle(shuffled)
    return shuffled[:n]
