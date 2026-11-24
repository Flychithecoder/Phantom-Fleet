"""
Instagram session manager — per-account login state, TTL, 2FA tracking.

The fleet accumulates sessions the executor assumes are valid. Without
tracking, a stale cookie or a silently expired token just makes every
dispatch fail with no signal pointing at "the token died". This module
makes session state first-class.

Per-account state machine:
    fresh                 → never logged in
    active                → token valid, within TTL
    aging                 → > 60% through TTL; re-login soon
    expired               → past TTL; executor must skip
    two_factor_pending    → IG asked for a 2FA code, awaiting operator
    password_reset_required → forced rotation seen, awaiting operator
    locked                → session rejected repeatedly or IG hard-locked

Transitions:
    fresh → active   via login(ok=True)
    active → aging   on tick when >60% TTL consumed
    aging → expired  on tick at TTL
    * → two_factor_pending via mark_2fa_pending()   (e.g. from checkpoint handler)
    two_factor_pending → active via complete_2fa()
    * → password_reset_required via mark_password_reset()
    * → locked via mark_locked()
    locked → active via login(ok=True)  (after operator fixes it)

Nothing random. Tokens come from secrets.token_hex() when a real executor
runs — this module stores whatever the caller provides.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
from typing import Callable, Optional

log = logging.getLogger("phantom_fleet.platforms.instagram_session")


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

_SESSION_TTL_DAYS       = 7
_AGING_THRESHOLD        = 0.60   # fraction of TTL consumed before aging
_TWO_FACTOR_OP_TIMEOUT  = 24     # hours operator has to clear 2FA

_STATES: tuple[str, ...] = (
    "fresh", "active", "aging", "expired",
    "two_factor_pending", "password_reset_required", "locked",
)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class SessionRecord:
    account_id:                str
    state:                     str = "fresh"
    session_token:             Optional[str] = None
    last_login_at:             Optional[str] = None
    last_activity_at:          Optional[str] = None
    expires_at:                Optional[str] = None
    re_login_attempts:         int = 0
    two_factor_pending_since:  Optional[str] = None
    locked_reason:             Optional[str] = None
    notes:                     list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "account_id":        self.account_id,
            "state":             self.state,
            "has_token":         self.session_token is not None,
            "last_login_at":     self.last_login_at,
            "last_activity_at":  self.last_activity_at,
            "expires_at":        self.expires_at,
            "re_login_attempts": self.re_login_attempts,
            "two_factor_pending_since": self.two_factor_pending_since,
            "locked_reason":     self.locked_reason,
            "notes":             list(self.notes[-6:]),
        }


@dataclass
class SessionStats:
    last_tick_at:   Optional[str] = None
    total_ticks:    int = 0
    aged_this_tick: int = 0
    expired_this_tick: int = 0
    by_state:       dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class InstagramSessionManager:
    """
    Per-account session state tracker. The executor calls `is_dispatchable()`
    before every action; the checkpoint handler calls `mark_2fa_pending()`
    or `mark_password_reset()` when it sees the matching screen.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        session_ttl_days:      int = _SESSION_TTL_DAYS,
        aging_threshold:       float = _AGING_THRESHOLD,
    ):
        self._accounts = accounts_store_getter
        self.ttl = timedelta(days=session_ttl_days)
        self.aging_threshold = aging_threshold
        self._records: dict[str, SessionRecord] = {}
        self._events:  deque[dict] = deque(maxlen=400)
        self.stats = SessionStats()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(_tz.utc)

    def _ig_accounts(self) -> list[dict]:
        return [r for r in self._accounts().values()
                if r.get("platform") == "instagram"]

    def _ensure(self, account_id: str) -> SessionRecord:
        rec = self._records.get(account_id)
        if rec is None:
            rec = SessionRecord(account_id=account_id)
            self._records[account_id] = rec
        return rec

    def _emit(self, account_id: str, event: str, detail: str = "") -> None:
        self._events.append({
            "ts":         self._now().isoformat(),
            "account_id": account_id,
            "event":      event,
            "detail":     detail,
        })

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def login(self, account_id: str, *, ok: bool, token: Optional[str] = None,
              needs_2fa: bool = False, note: str = "") -> SessionRecord:
        rec = self._ensure(account_id)
        now = self._now()
        if not ok:
            rec.re_login_attempts += 1
            rec.notes.append(f"login_fail · {note or 'no reason'}")
            if rec.re_login_attempts >= 3:
                rec.state = "locked"
                rec.locked_reason = "3+ login failures"
                self._emit(account_id, "locked", "3+ login failures")
            else:
                self._emit(account_id, "login_fail", note)
            return rec
        if needs_2fa:
            rec.state = "two_factor_pending"
            rec.two_factor_pending_since = now.isoformat()
            rec.notes.append("login_ok · awaiting 2fa")
            self._emit(account_id, "two_factor_pending", "login ok, 2fa requested")
            return rec
        rec.state = "active"
        rec.session_token = token or f"sess-{now.timestamp()}"
        rec.last_login_at = now.isoformat()
        rec.last_activity_at = now.isoformat()
        rec.expires_at = (now + self.ttl).isoformat()
        rec.re_login_attempts = 0
        rec.two_factor_pending_since = None
        rec.locked_reason = None
        rec.notes.append(f"login_ok · {note or 'ok'}")
        self._emit(account_id, "login_ok", note)
        return rec

    def refresh(self, account_id: str) -> Optional[SessionRecord]:
        rec = self._records.get(account_id)
        if rec is None or rec.state not in ("active", "aging"):
            return rec
        rec.last_activity_at = self._now().isoformat()
        return rec

    def complete_2fa(self, account_id: str,
                     code: Optional[str] = None) -> Optional[SessionRecord]:
        rec = self._records.get(account_id)
        if rec is None or rec.state != "two_factor_pending":
            return rec
        now = self._now()
        rec.state = "active"
        rec.session_token = f"sess-2fa-{now.timestamp()}"
        rec.last_login_at = now.isoformat()
        rec.last_activity_at = now.isoformat()
        rec.expires_at = (now + self.ttl).isoformat()
        rec.two_factor_pending_since = None
        rec.notes.append("2fa_complete")
        self._emit(account_id, "2fa_complete", code or "")
        return rec

    def mark_2fa_pending(self, account_id: str, note: str = "") -> SessionRecord:
        rec = self._ensure(account_id)
        rec.state = "two_factor_pending"
        rec.two_factor_pending_since = self._now().isoformat()
        rec.notes.append(f"2fa_pending · {note}")
        self._emit(account_id, "two_factor_pending", note)
        return rec

    def mark_password_reset(self, account_id: str, note: str = "") -> SessionRecord:
        rec = self._ensure(account_id)
        rec.state = "password_reset_required"
        rec.notes.append(f"password_reset · {note}")
        self._emit(account_id, "password_reset_required", note)
        return rec

    def mark_locked(self, account_id: str, reason: str = "") -> SessionRecord:
        rec = self._ensure(account_id)
        rec.state = "locked"
        rec.locked_reason = reason
        rec.notes.append(f"locked · {reason}")
        self._emit(account_id, "locked", reason)
        return rec

    def expire(self, account_id: str) -> Optional[SessionRecord]:
        rec = self._records.get(account_id)
        if rec is None:
            return None
        rec.state = "expired"
        rec.notes.append("expired")
        self._emit(account_id, "expired", "manual")
        return rec

    # ------------------------------------------------------------------
    # Tick (TTL sweep)
    # ------------------------------------------------------------------

    def tick(self) -> dict:
        now = self._now()
        aged_n = 0
        expired_n = 0

        # Ensure every live IG account has a record (fresh by default).
        for r in self._ig_accounts():
            self._ensure(r["account_id"])

        for rec in self._records.values():
            if rec.state == "active" and rec.expires_at and rec.last_login_at:
                started = datetime.fromisoformat(rec.last_login_at)
                expires = datetime.fromisoformat(rec.expires_at)
                consumed = (now - started) / (expires - started) if expires > started else 1.0
                if consumed >= 1.0:
                    rec.state = "expired"
                    rec.notes.append("expired · ttl")
                    self._emit(rec.account_id, "expired", "ttl")
                    expired_n += 1
                elif consumed >= self.aging_threshold:
                    rec.state = "aging"
                    rec.notes.append("aged · ttl>60%")
                    self._emit(rec.account_id, "aging", "ttl>60%")
                    aged_n += 1
            elif rec.state == "aging" and rec.expires_at:
                if now >= datetime.fromisoformat(rec.expires_at):
                    rec.state = "expired"
                    rec.notes.append("expired · ttl")
                    self._emit(rec.account_id, "expired", "ttl")
                    expired_n += 1
            elif rec.state == "two_factor_pending" and rec.two_factor_pending_since:
                pending_since = datetime.fromisoformat(rec.two_factor_pending_since)
                if now - pending_since > timedelta(hours=_TWO_FACTOR_OP_TIMEOUT):
                    rec.state = "expired"
                    rec.notes.append("expired · 2fa_timeout")
                    self._emit(rec.account_id, "expired", "2fa_timeout")
                    expired_n += 1

        # Stats refresh
        by_state: dict[str, int] = {s: 0 for s in _STATES}
        for rec in self._records.values():
            by_state[rec.state] = by_state.get(rec.state, 0) + 1
        self.stats.last_tick_at = now.isoformat()
        self.stats.total_ticks += 1
        self.stats.aged_this_tick = aged_n
        self.stats.expired_this_tick = expired_n
        self.stats.by_state = by_state
        return {"aged": aged_n, "expired": expired_n, "by_state": by_state}

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def is_dispatchable(self, account_id: str) -> bool:
        rec = self._records.get(account_id)
        if rec is None:
            return True   # unknown → assume ok, executor's other gates still apply
        return rec.state in ("active", "aging")

    def for_account(self, account_id: str) -> Optional[dict]:
        rec = self._records.get(account_id)
        return rec.as_dict() if rec else None

    def summary(self, limit_rows: int = 40) -> dict:
        now = self._now()
        soon: list[dict] = []
        for rec in self._records.values():
            if rec.state == "aging" and rec.expires_at:
                exp = datetime.fromisoformat(rec.expires_at)
                hours_left = max(0.0, (exp - now).total_seconds() / 3600.0)
                soon.append({"account_id": rec.account_id,
                             "hours_left": round(hours_left, 1)})
        soon.sort(key=lambda r: r["hours_left"])
        two_fa_waiting: list[dict] = []
        for rec in self._records.values():
            if rec.state == "two_factor_pending" and rec.two_factor_pending_since:
                started = datetime.fromisoformat(rec.two_factor_pending_since)
                mins = (now - started).total_seconds() / 60.0
                two_fa_waiting.append({"account_id": rec.account_id,
                                        "waiting_min": round(mins, 1)})
        two_fa_waiting.sort(key=lambda r: -r["waiting_min"])
        return {
            "stats": {
                "total":          len(self._records),
                "by_state":       dict(self.stats.by_state),
                "aged_last_tick": self.stats.aged_this_tick,
                "expired_last_tick": self.stats.expired_this_tick,
                "last_tick_at":   self.stats.last_tick_at,
                "total_ticks":    self.stats.total_ticks,
                "ttl_days":       self.ttl.days,
                "aging_threshold": self.aging_threshold,
                "two_fa_timeout_hours": _TWO_FACTOR_OP_TIMEOUT,
            },
            "soon_expiring":   soon[:20],
            "two_fa_waiting":  two_fa_waiting[:20],
            "records":         [r.as_dict() for r in self._records.values()][:limit_rows],
            "events":          [e for e in reversed(self._events)][:30],
        }
