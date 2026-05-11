"""
Comment pod primitives — data structures for the engagement-pod system.

A CommentPod is a group of 8-15 Instagram accounts that coordinate to comment
on each other's posts within a short window after publishing. This boosts the
post's early engagement signal, which IG's ranking algorithm interprets as
organic interest and rewards with wider distribution.

FLEET-SCALE DETECTION NOTES (CLAUDE.md 20K account thought experiment):

1.  Pod size 8-15 accounts:  small enough that no single comment-graph edge
    appears across thousands of posts, large enough to create a visible
    engagement signal. Fixed-size pods (exactly 8 every time) would be a
    size-cluster fingerprint — enforce range, not exact count.

2.  Pod rotation (weekly, 1-2 members swapped):  prevents the fixed social
    graph A→B→C→... from becoming a detectable motif. After 4 weeks every
    member has been replaced at least once; the graph looks organic.

3.  Comment timing is LogNormal, NOT uniform:  real fan commenting follows a
    decay curve — first comments arrive fast (eager fans), later comments
    trickle in. LogNormal with mean=ln(180s) and σ=0.5 produces exactly that
    shape. Uniform stagger (e.g. every 3 minutes) is an ML-detectable artifact.

4.  Daily cap 5 pod comments per account:  keeps pod activity within the
    budget of a normal active IG user. The cap is CODE-enforced in the agent,
    not prompt-enforced.

5.  Dedup key (account_id, media_id):  no account comments on the same post
    twice. Implemented via a Set in the agent; the Set is persisted across
    session restarts by the caller.

6.  Niche alignment:  a fitness pod commenting on an NSFW-adjacent post, or a
    general pod commenting on a fitness post, produces cross-niche comments
    that look unnatural. Pod assignment should match account niche to post niche.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Valid niche identifiers
# ---------------------------------------------------------------------------

VALID_NICHES: frozenset[str] = frozenset([
    "fitness",
    "lifestyle",
    "general",
    "nsfw_adjacent",
    "beauty",
    "travel",
    "food",
    "fashion",
])

# Pod size constraints (code-enforced by IGCommentPodAgent)
POD_MIN_ACCOUNTS: int = 8
POD_MAX_ACCOUNTS: int = 15

# Daily comment cap per account across all pods (code-enforced)
POD_MAX_DAILY_COMMENTS_PER_ACCOUNT: int = 5

# How many members to swap on each rotation (1-2)
POD_ROTATION_SWAP_MIN: int = 1
POD_ROTATION_SWAP_MAX: int = 2

# Rotation interval in days
POD_ROTATION_INTERVAL_DAYS: int = 7


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CommentPod:
    """
    A named group of 8-15 Instagram accounts that mutually boost engagement.

    Attributes:
        pod_id            Unique identifier, e.g. "pod_fitness_001".
        account_ids       List of internal account IDs. Must be 8-15 items.
        niche             One of VALID_NICHES — used to match pods to post content.
        created_at_iso    ISO-8601 UTC creation timestamp.
        last_rotated_iso  ISO-8601 UTC timestamp of last membership rotation.
    """
    pod_id:           str
    account_ids:      list[str]
    niche:            str
    created_at_iso:   str
    last_rotated_iso: str

    def __post_init__(self) -> None:
        if not (POD_MIN_ACCOUNTS <= len(self.account_ids) <= POD_MAX_ACCOUNTS):
            raise ValueError(
                f"CommentPod {self.pod_id!r}: account_ids must have "
                f"{POD_MIN_ACCOUNTS}-{POD_MAX_ACCOUNTS} members, "
                f"got {len(self.account_ids)}"
            )
        if self.niche not in VALID_NICHES:
            raise ValueError(
                f"CommentPod {self.pod_id!r}: niche {self.niche!r} not in "
                f"VALID_NICHES={sorted(VALID_NICHES)}"
            )

    @property
    def needs_rotation(self) -> bool:
        """True if last_rotated_iso is older than POD_ROTATION_INTERVAL_DAYS."""
        try:
            last = datetime.fromisoformat(self.last_rotated_iso.replace("Z", "+00:00"))
        except ValueError:
            return True
        now = datetime.now(timezone.utc)
        delta = now - last
        return delta.days >= POD_ROTATION_INTERVAL_DAYS


@dataclass
class PodCommentTask:
    """
    Represents a scheduled comment action for one pod member on one post.

    Created by IGCommentPodAgent when a new post is detected. Each member of
    the poster's pod gets one PodCommentTask with a staggered scheduled_at_unix
    so comments arrive at LogNormal-distributed times after the post.

    Attributes:
        poster_account_id   Internal account ID of the account that posted.
        media_id            Instagram media ID of the post to comment on.
        pod_id              Which pod this task belongs to.
        commenter_account_id  The pod member who will execute this comment.
        scheduled_at_unix   Unix timestamp when this comment should fire.
    """
    poster_account_id:    str
    media_id:             str
    pod_id:               str
    commenter_account_id: str
    scheduled_at_unix:    float

    @property
    def scheduled_at_iso(self) -> str:
        """ISO-8601 UTC representation of scheduled_at_unix."""
        return datetime.fromtimestamp(self.scheduled_at_unix, tz=timezone.utc).isoformat()


@dataclass
class PodCommentStats:
    """
    Engagement stats for one pod over its lifetime.
    Populated by IGCommentPodAgent and surfaced via the API.
    """
    pod_id:             str
    total_comments:     int   = 0
    comments_today:     int   = 0
    members_active:     int   = 0
    avg_delay_seconds:  float = 0.0
    last_activity_iso:  Optional[str] = None
    errors:             list[str] = field(default_factory=list)
