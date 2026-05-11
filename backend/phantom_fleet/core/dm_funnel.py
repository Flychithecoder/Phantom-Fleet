"""
DM Funnel — core data structures for multi-step Instagram DM nurture sequences.

A funnel sequence is a time-gated drip that mirrors email marketing automation
but runs entirely inside Instagram DMs. Each step can view stories, like posts,
visit profiles, or send AI-generated DMs — advancing the target through an
awareness → interest → CTA pipeline.

Fleet-scale design notes (CLAUDE.md 20K account rule):
    - Template selection uses hash(account_id + target_id + step_index) so
      every (account, target, step) triple produces a deterministically unique
      template pick — no monoculture even with a 15-item pool.
    - day_offset gates are checked by the FunnelAgent, not baked into structs,
      so they can be tested without real wall-clock delay.
    - FunnelEnrollment.state dict is for agent scratch space (store last known
      media_id, story reel_id, etc.) without polluting the core schema.
    - Conversion signals are a keyword list — agent checks inbox, not a webhook.

Agent audit table (CLAUDE.md agent-audit rules):
    ┌─────────────────────┬────────────────────────────────────────────────────┐
    │ Agents using this   │ IGDMFunnelAgent, IGFunnelEnrollmentAgent           │
    │ Untrusted input     │ target DM bodies (checked for conversion signals)  │
    │ User isolation      │ keyed by (account_id, target_user_id)              │
    │ Cost cap            │ 30 funnel actions/account/day (code-enforced)      │
    │ Loop cap            │ one step per enrollment per run                    │
    └─────────────────────┴────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .chat_modes import ChatTier


# ---------------------------------------------------------------------------
# Conversion signal keywords
# ---------------------------------------------------------------------------

# These are the words that appear in a target's reply when they want to buy.
# Checked case-insensitively against inbox messages by the funnel agent.
CONVERSION_SIGNALS: frozenset[str] = frozenset([
    "link", "price", "how much", "send me", "how do i", "where do i",
    "subscribe", "subscription", "sign up", "sign me up", "interested",
    "i want", "i'm in", "im in", "tell me more", "more info",
    "$", "onlyfans", "fanvue", "of link", "your page",
])

# Daily action cap — code-enforced in IGDMFunnelAgent, not prompt-enforced
FUNNEL_DAILY_ACTION_CAP: int = 30

# Inter-step stagger distribution parameters
# LogNormal(mean=ln(180), sigma=0.5) → median ~180s between steps across
# different enrollments in one session. Heavy right tail keeps timing natural.
_STAGGER_LOW: float = 30.0
_STAGGER_HIGH: float = 900.0
_STAGGER_SIGMA: float = 0.5

# Funnel AI DM model config
FUNNEL_OPENROUTER_MODEL: str = "claude-haiku-4-5-20251001"
FUNNEL_OPENROUTER_TEMPERATURE: float = 0.85
FUNNEL_OPENROUTER_MAX_TOKENS: int = 100
FUNNEL_MAX_LLM_RETRIES: int = 3


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FunnelStep:
    """
    One step in a funnel sequence.

    action must be one of:
        "story_view"     — view the target's current stories
        "like_post"      — like the target's most recent post
        "profile_visit"  — fetch target profile (registers as a profile view)
        "dm"             — send an AI-generated DM from the template pool

    condition (optional):
        "if_followed_back"      — only execute if target follows us back
        "if_story_viewed_back"  — only execute if target has viewed our story
        None                    — always execute when day_offset is reached

    dm_template_pool must have ≥ 15 entries when action == "dm".
    Template is selected via hash(account_id + target_id + step_index) % len(pool)
    to ensure no two accounts send the same message to the same target on the
    same step (diversity by default, deterministic for replay).
    """

    day_offset: int
    action: str  # "story_view" | "like_post" | "profile_visit" | "dm"
    dm_template_pool: Optional[list[str]] = None
    condition: Optional[str] = None  # "if_followed_back" | "if_story_viewed_back" | None
    max_tokens: int = FUNNEL_OPENROUTER_MAX_TOKENS

    def __post_init__(self) -> None:
        valid_actions = {"story_view", "like_post", "profile_visit", "dm"}
        if self.action not in valid_actions:
            raise ValueError(
                f"FunnelStep.action must be one of {valid_actions!r}, got {self.action!r}"
            )
        if self.action == "dm":
            if not self.dm_template_pool:
                raise ValueError("FunnelStep with action='dm' must provide dm_template_pool")
            if len(self.dm_template_pool) < 15:
                raise ValueError(
                    f"dm_template_pool must have ≥ 15 templates for diversity "
                    f"(got {len(self.dm_template_pool)})"
                )
        valid_conditions = {None, "if_followed_back", "if_story_viewed_back"}
        if self.condition not in valid_conditions:
            raise ValueError(
                f"FunnelStep.condition must be one of {valid_conditions!r}, "
                f"got {self.condition!r}"
            )


@dataclass
class FunnelSequence:
    """
    A named collection of FunnelSteps that execute in day_offset order.

    steps must be sorted in ascending day_offset order. The FunnelAgent
    asserts this at load time.

    chat_tier controls the AI tone at each DM step — FLIRTY_SFW for Instagram.
    """

    sequence_id: str
    name: str
    steps: list[FunnelStep]
    chat_tier: ChatTier = ChatTier.FLIRTY_SFW

    def __post_init__(self) -> None:
        if not self.sequence_id:
            raise ValueError("FunnelSequence.sequence_id must not be empty")
        if not self.steps:
            raise ValueError("FunnelSequence must have at least one step")
        offsets = [s.day_offset for s in self.steps]
        if offsets != sorted(offsets):
            raise ValueError(
                "FunnelSequence.steps must be sorted by ascending day_offset"
            )


@dataclass
class FunnelEnrollment:
    """
    Tracks one account's nurture progress toward one target.

    enrollment_id:    globally unique ID for this enrollment record
    account_id:       which of our accounts is running this funnel
    target_user_id:   Instagram user ID of the person being nurtured
    sequence_id:      which FunnelSequence this enrollment follows
    enrolled_at_iso:  ISO-8601 timestamp when enrollment was created
    current_step_index: index into sequence.steps — 0-based, advances per step
    last_action_at_iso: ISO-8601 timestamp of last executed step (or None)
    completed:        True when all steps have been executed
    converted:        True when target DM'd back with a conversion signal
    state:            scratch dict for agent use (e.g. {"last_media_id": "..."})
    """

    enrollment_id: str
    account_id: str
    target_user_id: str
    sequence_id: str
    enrolled_at_iso: str
    current_step_index: int = 0
    last_action_at_iso: Optional[str] = None
    completed: bool = False
    converted: bool = False
    state: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "enrollment_id": self.enrollment_id,
            "account_id": self.account_id,
            "target_user_id": self.target_user_id,
            "sequence_id": self.sequence_id,
            "enrolled_at_iso": self.enrolled_at_iso,
            "current_step_index": self.current_step_index,
            "last_action_at_iso": self.last_action_at_iso,
            "completed": self.completed,
            "converted": self.converted,
            "state": self.state,
        }

    @staticmethod
    def from_dict(d: dict) -> "FunnelEnrollment":
        return FunnelEnrollment(
            enrollment_id=d["enrollment_id"],
            account_id=d["account_id"],
            target_user_id=d["target_user_id"],
            sequence_id=d["sequence_id"],
            enrolled_at_iso=d["enrolled_at_iso"],
            current_step_index=d.get("current_step_index", 0),
            last_action_at_iso=d.get("last_action_at_iso"),
            completed=d.get("completed", False),
            converted=d.get("converted", False),
            state=d.get("state", {}),
        )


# ---------------------------------------------------------------------------
# Default 14-day OFM sequence
# ---------------------------------------------------------------------------

#
# Casual opener templates — day 6 first DM
# pool must be ≥ 15 for diversity (hash-indexed, no monoculture)
#
_CASUAL_OPENER_POOL: list[str] = [
    "hey 👋 saw your profile, love your vibe",
    "hey! your page is so cool, loving the aesthetic 😊",
    "omg hey! your content is genuinely amazing 🔥",
    "hi! stumbled on your profile and had to say hi 👋",
    "hey! your feed is everything rn honestly",
    "hey i keep seeing your posts and finally followed lol, love it",
    "hi!! your vibe is literally so good, love your page",
    "hey 👋 just found you and your content is so 🔥",
    "hi! i love your style honestly, your page is adorable",
    "hey! been following for a bit, love what you post 💕",
    "hiii i saw your profile and literally had to follow, amazing vibes",
    "hey! your aesthetic is so different and i love it",
    "hi!! love your page, you seem so fun 😊",
    "hey just wanted to say i love your content, so good",
    "hey 👋 your profile literally made me smile, love it 💕",
    "hi! love your page, you have such a great vibe honestly",
    "hey!! saw you on my explore and your content is SO good",
]

#
# Tease templates — day 11 second DM
# Hints at exclusive content without naming the platform
#
_TEASE_POOL: list[str] = [
    "been posting some exclusive content lately 🔥",
    "just dropped something really private for my close people 👀",
    "been putting out some content i can't post publicly lol 🙈",
    "honestly been creating stuff lately that's way too spicy for here 😏",
    "got some exclusive stuff that only my vip people have been seeing",
    "been sharing content privately that's way more my real self 👀",
    "i've been creating some really personal content lately that i can't post here lol",
    "honestly my private stuff has been hitting different lately 🔥",
    "been making content on the side that my followers here never see 👀",
    "dropped something really exclusive this week, people are going crazy 😏",
    "got exclusive content that's been getting wild reactions lately 🙈",
    "been posting the real me somewhere else lately lol",
    "my private people have been seeing a whole different side of me 😏",
    "recently started sharing content that's way too personal for this page",
    "been creating some stuff i'm actually really proud of, just not here 👀",
    "honestly the content i've been posting privately is way better 🔥",
    "my vip content lately has been unreal honestly",
]

#
# CTA templates — day 14 final DM
# Direct call to action — link or DM trigger
#
_CTA_POOL: list[str] = [
    "drop your email / DM me 'link' for access 💌",
    "DM me 'link' if you want access to my exclusive content 💌",
    "reply 'link' and i'll send you my private page 🔥",
    "DM me 'access' and i'll hook you up with my exclusive content 💌",
    "want the link to my private page? just DM me 👀",
    "i'm sharing my exclusive link with people who want it — DM me 💌",
    "drop me a DM if you want access, i'll send you the link 🔥",
    "DM me and i'll send you the link to my private content 💌",
    "send me a DM saying 'link' and i'll get you in 😏",
    "reply 'send me' and i'll drop my exclusive link for you 💌",
    "want exclusive access? just DM me back 🔥",
    "my private page link is going out to anyone who DMs me today 💌",
    "DM me if you're interested in my exclusive content — link is waiting 👀",
    "first ones to DM me get my exclusive link right away 💌",
    "you seem like someone who'd love my private content — DM me 'link' 🔥",
    "dropping my exclusive link to anyone who asks — DM me 💌",
    "want to see what i can't post here? DM me the word 'link' 😏",
]


DEFAULT_OFM_SEQUENCE = FunnelSequence(
    sequence_id="default_ofm_14day",
    name="OFM 14-day warm",
    chat_tier=ChatTier.FLIRTY_SFW,
    steps=[
        # Day 0: follow is handled by the follow agent — enrollment happens here
        # Day 2: view their stories (no condition — build familiarity)
        FunnelStep(
            day_offset=2,
            action="story_view",
            condition=None,
        ),
        # Day 4: like their most recent post
        FunnelStep(
            day_offset=4,
            action="like_post",
            condition=None,
        ),
        # Day 6: casual opener DM
        FunnelStep(
            day_offset=6,
            action="dm",
            dm_template_pool=_CASUAL_OPENER_POOL,
            condition=None,
        ),
        # Day 9: view stories again — only if they followed us back
        FunnelStep(
            day_offset=9,
            action="story_view",
            condition="if_followed_back",
        ),
        # Day 11: tease exclusive content
        FunnelStep(
            day_offset=11,
            action="dm",
            dm_template_pool=_TEASE_POOL,
            condition=None,
        ),
        # Day 14: CTA — drop link / DM trigger
        FunnelStep(
            day_offset=14,
            action="dm",
            dm_template_pool=_CTA_POOL,
            condition=None,
        ),
    ],
)


# ---------------------------------------------------------------------------
# Registry — sequences loaded at module init + runtime additions via API
# ---------------------------------------------------------------------------

# sequence_id → FunnelSequence
SEQUENCE_REGISTRY: dict[str, FunnelSequence] = {
    DEFAULT_OFM_SEQUENCE.sequence_id: DEFAULT_OFM_SEQUENCE,
}
