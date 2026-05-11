"""
IGLookalikeAgent — builds lookalike target lists from converted fans' profiles.

A "converter" is someone who became an engaged fan (intent=ENGAGED_FAN) or replied
to a story. We analyze their profile characteristics and find similar accounts to target.

This produces the highest-quality cold targeting possible: accounts that
look like your actual buyers, not just followers of competitors.

Detection hardening (CLAUDE.md 20K account fleet-level):
    - Scoring is pure computation over already-fetched profiles; no extra API
      calls needed per candidate beyond the source account's follower list.
    - Hard cap of 500 candidates per session, code-enforced.
    - Deduplication against existing target pool.
    - Signature ranges use 5th–95th percentile to avoid outlier distortion;
      the resulting range naturally excludes bot-looking extremes.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ...core.hybrid_runner import WorkerResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius constant (code-enforced)
# ---------------------------------------------------------------------------

MAX_CANDIDATES_PER_SESSION: int = 500

# ---------------------------------------------------------------------------
# Stopwords for bio keyword extraction
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "during",
    "i", "me", "my", "we", "our", "you", "your", "he", "his", "she", "her",
    "it", "its", "they", "them", "their", "this", "that", "these", "those",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "not", "no", "nor", "so", "yet", "both", "either",
    "neither", "just", "only", "also", "here", "there", "when", "where",
    "how", "all", "each", "every", "any", "some", "such", "than", "too",
    "very", "s", "t", "can", "now", "d", "ll", "m", "o", "re", "ve", "y",
})

_WORD_RE = re.compile(r"[a-zA-Z]{2,}")


def _extract_bio_keywords(bios: list[str], top_n: int = 5) -> list[str]:
    """
    Extract the top-N most frequent words across all converter bios,
    after removing stopwords.

    Returns at most top_n keywords, sorted by frequency descending.
    """
    counter: Counter[str] = Counter()
    for bio in bios:
        words = _WORD_RE.findall(bio.lower())
        for w in words:
            if w not in _STOPWORDS:
                counter[w] += 1
    return [word for word, _ in counter.most_common(top_n)]


# ---------------------------------------------------------------------------
# Percentile helper (5th–95th)
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """
    Compute the `pct`-th percentile of a sorted list.
    pct is in [0, 100]. Uses linear interpolation.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    index = (pct / 100.0) * (n - 1)
    lower = int(index)
    upper = min(lower + 1, n - 1)
    frac  = index - lower
    return sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower])


# ---------------------------------------------------------------------------
# ProfileSignature — the "shape" of a buyer
# ---------------------------------------------------------------------------


@dataclass
class ProfileSignature:
    """
    Statistical profile of converted fans' Instagram accounts.

    Numeric ranges use the 5th–95th percentile (not min/max) to avoid
    outlier distortion. A very-high-follower converter or a zero-follower
    edge case doesn't widen the range to uselessness.
    """
    follower_range:       tuple[int, int]    # (p5, p95)
    following_range:      tuple[int, int]    # (p5, p95)
    has_bio:              bool               # majority of converters had a bio
    bio_keywords:         list[str]          # top 5 keywords from converter bios
    avg_post_count_range: tuple[int, int]    # (p5, p95) — informational
    is_public:            bool = True
    engagement_proxy:     str = "medium"     # "low" | "medium" | "high"


# ---------------------------------------------------------------------------
# Engagement proxy classifier
# ---------------------------------------------------------------------------


def _classify_engagement(follower_count: int, following_count: int) -> str:
    """
    Estimate engagement quality from the follower/following ratio.

    High-engagement accounts follow fewer people than follow them.
    Low-engagement accounts follow many but have few followers (often bots).
    """
    if follower_count == 0:
        return "low"
    ratio = following_count / max(follower_count, 1)
    if ratio < 0.5:
        return "high"
    if ratio < 2.0:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Lookalike candidate dataclass
# ---------------------------------------------------------------------------


@dataclass
class LookalikeCandidate:
    """A discovered lookalike candidate with its similarity score."""
    user_id:        str
    username:       str
    follower_count: int
    following_count: int
    bio_keywords_matched: list[str]
    engagement_proxy: str
    score:          int
    raw:            dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# IGLookalikeAgent
# ---------------------------------------------------------------------------


class IGLookalikeAgent:
    """
    Builds lookalike target lists based on converted fans' profiles.

    A 'converter' is someone who became an engaged fan (intent=ENGAGED_FAN)
    or replied to a story. We analyze their profile characteristics and find
    similar accounts.

    This is the highest-quality targeting method — targeting people who
    look like your most engaged fans.

    Usage:
        agent = IGLookalikeAgent()
        result = await agent.find_lookalikes(task)

    task.params keys:
        converter_profiles  list[dict]         — raw IG user dicts for converters
        seed_candidates     list[dict]          — raw IG user dicts to score against sig
        top_n               int (default 300)   — how many top candidates to return
        already_seen        set[str]            — user_ids already in target pool
        date_iso            str                 — YYYY-MM-DD; optional
    """

    # ------------------------------------------------------------------
    # Signature builder
    # ------------------------------------------------------------------

    @staticmethod
    def build_signature_from_converters(
        converter_profiles: list[dict],
    ) -> Optional[ProfileSignature]:
        """
        Compute ProfileSignature from a list of converter profile dicts.

        Numeric fields use 5th–95th percentile to avoid outlier distortion.
        Returns None if converter_profiles is empty.
        """
        if not converter_profiles:
            return None

        follower_counts:    list[float] = []
        following_counts:   list[float] = []
        post_counts:        list[float] = []
        bios:               list[str]   = []
        bio_present_count:  int         = 0
        engagement_votes:   Counter     = Counter()

        for p in converter_profiles:
            fc  = float(p.get("follower_count", 0) or 0)
            fwc = float(p.get("following_count", p.get("follow_count", 0)) or 0)
            pc  = float(p.get("media_count", 0) or 0)
            bio = p.get("biography", p.get("bio", "")) or ""

            follower_counts.append(fc)
            following_counts.append(fwc)
            post_counts.append(pc)

            if bio.strip():
                bio_present_count += 1
                bios.append(bio)

            engagement_votes[_classify_engagement(int(fc), int(fwc))] += 1

        has_bio          = bio_present_count > len(converter_profiles) // 2
        bio_kws          = _extract_bio_keywords(bios, top_n=5)
        dominant_eng     = engagement_votes.most_common(1)[0][0] if engagement_votes else "medium"

        follower_range   = (
            int(_percentile(follower_counts, 5)),
            int(_percentile(follower_counts, 95)),
        )
        following_range  = (
            int(_percentile(following_counts, 5)),
            int(_percentile(following_counts, 95)),
        )
        post_count_range = (
            int(_percentile(post_counts, 5)),
            int(_percentile(post_counts, 95)),
        )

        return ProfileSignature(
            follower_range       = follower_range,
            following_range      = following_range,
            has_bio              = has_bio,
            bio_keywords         = bio_kws,
            avg_post_count_range = post_count_range,
            is_public            = True,
            engagement_proxy     = dominant_eng,
        )

    # ------------------------------------------------------------------
    # Candidate scorer
    # ------------------------------------------------------------------

    @staticmethod
    def _score_candidate(
        user: dict,
        sig: ProfileSignature,
    ) -> LookalikeCandidate:
        """
        Score a candidate profile against the converter signature.

        Scoring is additive; each dimension is independently auditable.
        """
        fc  = int(user.get("follower_count", 0) or 0)
        fwc = int(user.get("following_count", user.get("follow_count", 0)) or 0)
        bio = (user.get("biography", user.get("bio", "")) or "").lower()
        uid = str(user.get("pk") or user.get("id") or "")
        eng = _classify_engagement(fc, fwc)

        # follower_count in signature range: +2
        fc_in_range = sig.follower_range[0] <= fc <= sig.follower_range[1]
        # following_count in range: +1
        fw_in_range = sig.following_range[0] <= fwc <= sig.following_range[1]
        # engagement_proxy match: +2
        eng_match   = eng == sig.engagement_proxy

        # bio keywords: +2 per match, max +4
        matched_kws: list[str] = [kw for kw in sig.bio_keywords if kw in bio]
        bio_score   = min(len(matched_kws) * 2, 4)

        score = (
            (2 if fc_in_range else 0)
            + (1 if fw_in_range else 0)
            + (2 if eng_match else 0)
            + bio_score
        )

        return LookalikeCandidate(
            user_id              = uid,
            username             = user.get("username", ""),
            follower_count       = fc,
            following_count      = fwc,
            bio_keywords_matched = matched_kws,
            engagement_proxy     = eng,
            score                = score,
            raw                  = user,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def find_lookalikes(self, task) -> WorkerResult:
        """
        Score seed_candidates against the signature derived from converter_profiles.

        Returns WorkerResult with data["candidates"] = list of LookalikeCandidate
        sorted by score descending, capped at top_n (hard cap: 500).
        """
        params             = task.params
        converter_profiles: list[dict] = params.get("converter_profiles", [])
        seed_candidates:    list[dict] = params.get("seed_candidates", [])
        top_n:              int        = int(params.get("top_n", 300))
        already_seen:       set[str]   = params.get("already_seen") or set()
        date_iso:           str        = params.get("date_iso") or date.today().isoformat()

        # Build signature
        sig = self.build_signature_from_converters(converter_profiles)
        if sig is None:
            return WorkerResult(
                task_id    = getattr(task, "task_id", "lookalike"),
                platform   = "instagram",
                account_id = "lookalike",
                success    = False,
                error      = "No converter_profiles provided — cannot build signature",
            )

        log.info(
            "[lookalike] Signature built: follower_range=%s following_range=%s "
            "bio_keywords=%s engagement=%s",
            sig.follower_range, sig.following_range, sig.bio_keywords, sig.engagement_proxy,
        )

        # Score all seed candidates
        scored: list[LookalikeCandidate] = []
        for user in seed_candidates:
            uid = str(user.get("pk") or user.get("id") or "")
            if not uid or uid in already_seen:
                continue
            candidate = self._score_candidate(user, sig)
            scored.append(candidate)

        # Sort by score descending
        scored.sort(key=lambda c: c.score, reverse=True)

        # Hard cap: code-enforced at MAX_CANDIDATES_PER_SESSION
        capped_n = min(top_n, MAX_CANDIDATES_PER_SESSION)
        selected = scored[:capped_n]

        # Mark selected as seen
        for c in selected:
            already_seen.add(c.user_id)

        log.info(
            "[lookalike] Scored %d candidates, selected top %d (cap=%d)",
            len(scored), len(selected), MAX_CANDIDATES_PER_SESSION,
        )

        return WorkerResult(
            task_id    = getattr(task, "task_id", "lookalike"),
            platform   = "instagram",
            account_id = "lookalike",
            success    = True,
            data       = {
                "action":          "lookalike_targeting",
                "signature":       {
                    "follower_range":       sig.follower_range,
                    "following_range":      sig.following_range,
                    "bio_keywords":         sig.bio_keywords,
                    "engagement_proxy":     sig.engagement_proxy,
                    "has_bio":              sig.has_bio,
                    "avg_post_count_range": sig.avg_post_count_range,
                },
                "candidates_scored":   len(scored),
                "candidates_selected": len(selected),
                "candidates":          [
                    {
                        "user_id":              c.user_id,
                        "username":             c.username,
                        "follower_count":       c.follower_count,
                        "following_count":      c.following_count,
                        "score":                c.score,
                        "bio_keywords_matched": c.bio_keywords_matched,
                        "engagement_proxy":     c.engagement_proxy,
                    }
                    for c in selected
                ],
            },
        )
