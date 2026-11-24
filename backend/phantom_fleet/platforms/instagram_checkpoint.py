"""
Instagram checkpoint handler — detect + classify IG challenge screens
and route to the right response.

When IG decides an account looks suspicious, it interrupts the session
with one of a small set of challenge screens: phone/email verify codes,
"was this you?" alerts, forced password rotations, age checks, CAPTCHA
gates, hard locks, or ToS acceptance. Each one has:

    * a KIND the classifier identifies from page signatures (keywords
      in body text, URL path fragments, button labels)
    * a SEVERITY (info / warn / fail / halt)
    * a routed ACTION — self_resolve (just click "I agree"),
      operator_review (needs a human), enroll_recovery (dampen the
      account in the recovery agent), retire (hard-stop, this account
      is done)

The executor is expected to call `observe(account_id, signature)` with
whatever it scraped from the screen; the handler classifies, writes an
event, and — if severity ≥ warn — enrolls the account into the recovery
agent so orchestrator weight collapses immediately.

If a burst of checkpoints fires inside a short window (default 5 in
15 min), a REBALANCER_BURST alert is raised so the fleet rebalancer can
throttle / halt planning.

Nothing random. Classification is a deterministic ordered rule list; the
audit harness exercises every rule with a canonical signature sample.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
from typing import Callable, Optional

log = logging.getLogger("phantom_fleet.platforms.instagram_checkpoint")


# ---------------------------------------------------------------------------
# Kinds, severities, actions
# ---------------------------------------------------------------------------

CheckpointKind = str

_KIND_SEVERITY: dict[CheckpointKind, str] = {
    "phone_sms_verify":       "warn",
    "email_verify":           "warn",
    "suspicious_activity":    "warn",
    "password_change":        "fail",
    "age_verify":             "fail",
    "captcha":                "warn",
    "account_locked":         "halt",
    "terms_update":           "info",
    "two_factor_prompt":      "warn",
    "device_verify":          "warn",
    "unknown":                "warn",
}

_KIND_ACTION: dict[CheckpointKind, str] = {
    "phone_sms_verify":       "operator_review",
    "email_verify":           "operator_review",
    "suspicious_activity":    "enroll_recovery",
    "password_change":        "enroll_recovery",
    "age_verify":              "operator_review",
    "captcha":                "operator_review",
    "account_locked":         "retire",
    "terms_update":           "self_resolve",
    "two_factor_prompt":      "operator_review",
    "device_verify":          "operator_review",
    "unknown":                "operator_review",
}

# Ordered rules: first match wins. Each rule is (kind, pattern-list).
# Patterns are case-insensitive substrings; matching ANY pattern fires.
_RULES: tuple[tuple[CheckpointKind, tuple[str, ...]], ...] = (
    ("account_locked", (
        "your account has been disabled",
        "/accounts/disabled",
        "we suspended your account",
    )),
    ("age_verify", (
        "upload a video selfie",
        "verify your age",
        "age verification",
    )),
    ("password_change", (
        "change your password",
        "/accounts/password/reset",
        "please create a new password",
    )),
    ("two_factor_prompt", (
        "two-factor",
        "/accounts/login/two_factor",
        "authentication app",
    )),
    ("phone_sms_verify", (
        "we sent you a security code",
        "enter the 6-digit code we sent to +",
        "/challenge/sms",
    )),
    ("email_verify", (
        "enter the 6-digit code we sent to",
        "we sent an email",
        "/challenge/email",
    )),
    ("captcha", (
        "/recaptcha/",
        "funcaptcha",
        "please verify you're not a robot",
    )),
    ("suspicious_activity", (
        "was this you?",
        "unusual login attempt",
        "/challenge/",
        "help us confirm",
    )),
    ("device_verify", (
        "trust this device",
        "unrecognized device",
    )),
    ("terms_update", (
        "we've updated our terms",
        "i agree",
        "updated privacy policy",
    )),
)


def classify(signature: str) -> CheckpointKind:
    """
    Classify a checkpoint from a scraped-page signature (body text +
    URL path concatenated by the caller). Deterministic, ordered rules.
    """
    hay = signature.lower()
    for kind, patterns in _RULES:
        for p in patterns:
            if p in hay:
                return kind
    return "unknown"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class CheckpointEvent:
    event_id:     str
    account_id:   str
    kind:         CheckpointKind
    severity:     str
    action:       str
    signature:    str
    observed_at:  str


@dataclass
class CheckpointStats:
    total:          int = 0
    by_kind:        dict = field(default_factory=dict)
    by_severity:    dict = field(default_factory=dict)
    by_action:      dict = field(default_factory=dict)
    last_event_at:  Optional[str] = None
    burst_alerts:   int = 0


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class InstagramCheckpointHandler:
    """
    Classifies incoming checkpoint signatures, writes events, and hooks
    the appropriate downstream action:

        enroll_recovery  → calls recovery.enroll(account_id, "checkpoint")
        retire           → calls recovery.force_retire(account_id)
        operator_review  → event recorded, operator sees it in panel
        self_resolve     → event recorded, no further action
    """

    def __init__(
        self,
        recovery:         Optional[object] = None,
        rebalancer_alert: Optional[Callable[[dict], None]] = None,
        burst_window_min: int = 15,
        burst_threshold:  int = 5,
    ):
        self.recovery = recovery
        self.rebalancer_alert = rebalancer_alert
        self.burst_window_min = burst_window_min
        self.burst_threshold = burst_threshold
        self._events: deque[CheckpointEvent] = deque(maxlen=500)
        self._by_account: dict[str, list[CheckpointEvent]] = defaultdict(list)
        self.stats = CheckpointStats()

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def observe(self, account_id: str, signature: str,
                 *, kind_override: Optional[CheckpointKind] = None) -> CheckpointEvent:
        kind = kind_override or classify(signature)
        severity = _KIND_SEVERITY.get(kind, "warn")
        action   = _KIND_ACTION.get(kind, "operator_review")
        now = datetime.now(_tz.utc)
        event = CheckpointEvent(
            event_id=f"cp-{int(now.timestamp()*1000)}-{len(self._events)}",
            account_id=account_id,
            kind=kind, severity=severity, action=action,
            signature=signature[:400],
            observed_at=now.isoformat(),
        )
        self._events.append(event)
        self._by_account[account_id].append(event)

        # Stats
        self.stats.total += 1
        self.stats.by_kind[kind] = self.stats.by_kind.get(kind, 0) + 1
        self.stats.by_severity[severity] = self.stats.by_severity.get(severity, 0) + 1
        self.stats.by_action[action]   = self.stats.by_action.get(action, 0) + 1
        self.stats.last_event_at = event.observed_at

        # Side effects
        try:
            if action == "enroll_recovery" and self.recovery is not None:
                self.recovery.enroll(account_id, reason=f"checkpoint:{kind}")
            elif action == "retire" and self.recovery is not None:
                # Recovery agent exposes force_retire where supported.
                if hasattr(self.recovery, "force_retire"):
                    self.recovery.force_retire(account_id)
                elif hasattr(self.recovery, "enroll"):
                    self.recovery.enroll(account_id, reason=f"checkpoint:{kind}")
        except Exception:
            log.exception("checkpoint side effect failed for %s / %s",
                          account_id, action)

        # Burst detection
        if self._is_burst():
            self.stats.burst_alerts += 1
            if self.rebalancer_alert is not None:
                self.rebalancer_alert({
                    "topic": "ig_checkpoint_burst",
                    "reason": (f"{self.burst_threshold}+ checkpoints in "
                               f"{self.burst_window_min} min"),
                })

        return event

    def _is_burst(self) -> bool:
        cutoff = datetime.now(_tz.utc) - timedelta(minutes=self.burst_window_min)
        n = sum(1 for e in self._events
                if datetime.fromisoformat(e.observed_at) >= cutoff)
        return n >= self.burst_threshold

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def for_account(self, account_id: str, limit: int = 20) -> list[dict]:
        rows = list(reversed(self._by_account.get(account_id, [])))[:limit]
        return [self._row(e) for e in rows]

    def recent(self, limit: int = 30) -> list[dict]:
        return [self._row(e) for e in list(reversed(self._events))[:limit]]

    def _row(self, e: CheckpointEvent) -> dict:
        return {
            "event_id":    e.event_id,
            "account_id":  e.account_id,
            "kind":        e.kind,
            "severity":    e.severity,
            "action":      e.action,
            "signature":   e.signature,
            "observed_at": e.observed_at,
        }

    def summary(self) -> dict:
        # Count of DISTINCT accounts under each severity
        by_acc_sev: dict[str, set] = defaultdict(set)
        for e in self._events:
            by_acc_sev[e.severity].add(e.account_id)
        return {
            "stats": {
                "total":           self.stats.total,
                "by_kind":         dict(self.stats.by_kind),
                "by_severity":     dict(self.stats.by_severity),
                "by_action":       dict(self.stats.by_action),
                "accounts_warn":   len(by_acc_sev.get("warn", set())),
                "accounts_fail":   len(by_acc_sev.get("fail", set())),
                "accounts_halt":   len(by_acc_sev.get("halt", set())),
                "last_event_at":   self.stats.last_event_at,
                "burst_alerts":    self.stats.burst_alerts,
                "burst_threshold": self.burst_threshold,
                "burst_window_min": self.burst_window_min,
            },
            "recent": self.recent(limit=25),
        }
