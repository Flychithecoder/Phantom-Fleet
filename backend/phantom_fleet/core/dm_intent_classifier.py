"""
DMIntentClassifier — rule-based intent classification for incoming DMs.

DESIGN RATIONALE:
    Every incoming DM on Instagram needs a routing decision before we pay
    for an LLM call. This module makes that decision in microseconds using
    a deterministic priority-ordered rule chain.

    LLM is NOT called here. The LLM call happens in _BaseDMChatAgent after
    we know (a) which profile to use and (b) what max_tokens budget to apply.
    Using rules first means a LOW_INTENT thread costs $0 in LLM tokens.

CLASSIFICATION PRIORITY ORDER (top = wins):
    1. STORY_REPLY   — thread metadata is_story_reply == True (warm signal)
    2. NEGATIVE      — contains stop/block/spam keywords
    3. LOW_INTENT    — last 3 messages all ≤5 chars (not engaging)
    4. ENGAGED_FAN   — message_count >= 3 (genuine exchanges)
    5. NEW_FAN       — default bucket

FLEET-SCALE NOTES (CLAUDE.md 20K account thought experiment):
    - All matching is case-insensitive substring search — no regex compilation
      overhead per message.
    - Intent classification is per-thread, not per-account — no global mutable
      state beyond the caller's DMConversationState.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent enum
# ---------------------------------------------------------------------------


class DMIntent(str, Enum):
    NEW_FAN      = "new_fan"       # first contact, default
    ENGAGED_FAN  = "engaged_fan"   # 3+ genuine exchanges
    STORY_REPLY  = "story_reply"   # replied to a story (warm signal)
    LOW_INTENT   = "low_intent"    # one-word replies, not engaging
    NEGATIVE     = "negative"      # wants to be left alone


# ---------------------------------------------------------------------------
# Keyword signal sets
# ---------------------------------------------------------------------------

NEGATIVE_SIGNALS: frozenset[str] = frozenset([
    "stop",
    "leave me alone",
    "remove",
    "spam",
    "report",
    "block",
    "unfollow",
    "fuck off",
    "not interested",
    "unsubscribe",
    "do not contact",
    "stop messaging",
    "go away",
])

# One-word / emoji-only message: length ≤ 5 chars
LOW_INTENT_MAX_LEN: int = 5
LOW_INTENT_LOOKBACK: int = 3   # evaluate last N messages from target

# Engaged fan threshold
ENGAGED_FAN_MIN_MESSAGES: int = 3


# ---------------------------------------------------------------------------
# Intent → ChatModeProfile routing
# ---------------------------------------------------------------------------

INTENT_PROFILE_MAP: dict[DMIntent, Optional[str]] = {
    DMIntent.NEW_FAN:      "INSTAGRAM_CASUAL_SFW",
    DMIntent.ENGAGED_FAN:  "INSTAGRAM_FLIRTY_SFW",
    DMIntent.STORY_REPLY:  "INSTAGRAM_FLIRTY_SFW",
    DMIntent.LOW_INTENT:   None,   # skip — don't waste tokens
    DMIntent.NEGATIVE:     None,   # skip
}

# Intent → max_tokens budget for the LLM call
INTENT_MAX_TOKENS: dict[DMIntent, int] = {
    DMIntent.NEW_FAN:      80,
    DMIntent.ENGAGED_FAN:  120,
    DMIntent.STORY_REPLY:  80,
    DMIntent.LOW_INTENT:   0,
    DMIntent.NEGATIVE:     0,
}


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class DMIntentClassifier:
    """
    Classifies incoming DMs by intent WITHOUT an LLM call (rule-based + fast).

    The classifier is stateless: all thread/account state is passed in as
    arguments so this class has no per-instance mutable data and is safe to
    share across concurrent async tasks.

    Usage::

        classifier = DMIntentClassifier()
        intent = classifier.classify(
            message=last_message_text,
            thread=thread_dict,
            recent_target_messages=["k", "ok", "😐"],
        )
        profile_name = INTENT_PROFILE_MAP[intent]   # None → skip thread
        max_tokens   = INTENT_MAX_TOKENS[intent]

    Args for classify():
        message               (str)  — the latest inbound message text.
        thread                (dict) — IG thread dict; checked for:
                                         "is_story_reply" (bool),
                                         "message_count"  (int).
        account_state         (dict) — unused; kept for call-site compatibility.
        recent_target_messages (list[str]) — last N messages from the OTHER
                                       side (not our account). Used for
                                       LOW_INTENT detection. May be empty.
    """

    def classify(
        self,
        message: str,
        thread: dict,
        account_state: Optional[dict] = None,
        recent_target_messages: Optional[list[str]] = None,
    ) -> DMIntent:
        """
        Classify the intent of an incoming DM thread.

        Priority order: STORY_REPLY → NEGATIVE → LOW_INTENT →
                        ENGAGED_FAN → NEW_FAN
        """
        msg_lower = message.lower().strip()
        recent_msgs = recent_target_messages or []

        # ------------------------------------------------------------------
        # 1. STORY_REPLY — IG story reply flag set on thread metadata
        # ------------------------------------------------------------------
        if thread.get("is_story_reply", False):
            log.debug("intent=STORY_REPLY thread_id=%s", thread.get("thread_id", "?"))
            return DMIntent.STORY_REPLY

        # ------------------------------------------------------------------
        # 2. NEGATIVE — hostile / unsubscribe signals
        # ------------------------------------------------------------------
        if self._has_negative_signal(msg_lower):
            log.debug("intent=NEGATIVE msg_preview=%r", msg_lower[:40])
            return DMIntent.NEGATIVE

        # ------------------------------------------------------------------
        # 3. LOW_INTENT — last N messages all very short
        # ------------------------------------------------------------------
        if (
            len(recent_msgs) >= LOW_INTENT_LOOKBACK
            and self._is_low_intent(recent_msgs[-LOW_INTENT_LOOKBACK:])
        ):
            log.debug("intent=LOW_INTENT recent_msgs=%r", recent_msgs[-3:])
            return DMIntent.LOW_INTENT

        # ------------------------------------------------------------------
        # 4. ENGAGED_FAN — enough message history with genuine engagement
        # ------------------------------------------------------------------
        message_count = int(thread.get("message_count", 0))
        if message_count >= ENGAGED_FAN_MIN_MESSAGES:
            log.debug("intent=ENGAGED_FAN message_count=%d", message_count)
            return DMIntent.ENGAGED_FAN

        # ------------------------------------------------------------------
        # 5. NEW_FAN — default bucket
        # ------------------------------------------------------------------
        log.debug("intent=NEW_FAN (default)")
        return DMIntent.NEW_FAN

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_negative_signal(msg_lower: str) -> bool:
        """Return True if the lowercased message contains a negative/unsubscribe signal."""
        for signal in NEGATIVE_SIGNALS:
            if signal in msg_lower:
                return True
        return False

    @staticmethod
    def _is_low_intent(messages: list[str]) -> bool:
        """
        Return True if ALL messages in the window are short (≤ LOW_INTENT_MAX_LEN chars).

        Strips whitespace before length check so "  k  " is counted as 1 char,
        not 5.
        """
        if not messages:
            return False
        return all(len(m.strip()) <= LOW_INTENT_MAX_LEN for m in messages)


# ---------------------------------------------------------------------------
# Module-level singleton — reuse across the process for zero allocation overhead
# ---------------------------------------------------------------------------

CLASSIFIER = DMIntentClassifier()
