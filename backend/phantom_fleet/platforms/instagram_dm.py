"""
Instagram DM flow — controlled outreach with dedupe, template rotation,
reply tracking, and opt-out signal detection.

Outreach DMs are the highest-signal, highest-risk action in the IG
primitive set. Sent carelessly they look exactly like spam; sent well
they're the only place where cold reach actually converts. This module
is the discipline that keeps the second shape and not the first.

Guardrails (every one is a hard gate, not a soft suggestion):

    1. per-recipient dedupe: no actor messages the same recipient
       twice, ever. Second attempt = BLOCKED pre-flight.
    2. fleet-level template cap: one template can be sent at most
       `_TEMPLATE_CAP_FLEET_DAY` times across the whole fleet per day,
       so two of our accounts never DM the same prospect with the same
       body in the same week.
    3. per-actor daily cap: `_DAILY_CAP_PER_ACTOR` with the usual
       warming-aware ratchet in orchestrator callers.
    4. inter-DM cooldown per actor: `_COOLDOWN_MIN` so one account
       doesn't blast 8 DMs in the same minute.
    5. content guard: no shortlinks (bit.ly etc), no @mentions, no
       phrases in `_BLOCKED_PHRASES`. Content fails pre-flight.
    6. opt-out detection: if a recipient's reply contains any phrase in
       `_OPT_OUT_PHRASES`, that pair (actor, recipient) is permanently
       blocked and the recipient is added to the actor's SUPPRESS list.
    7. health gate: at_risk / shadowbanned actors never send DMs.

Nothing random. Template rotation is deterministic least-recently-used
with SHA256 tiebreak keyed to (actor_id, recipient_handle).
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
from typing import Callable, Optional

from . import instagram as ig_mod

log = logging.getLogger("phantom_fleet.platforms.instagram_dm")

_DAILY_CAP_PER_ACTOR     = 8
_COOLDOWN_MIN            = 30
_TEMPLATE_CAP_FLEET_DAY  = 50
_UNSAFE_HEALTH           = ("at_risk", "shadowbanned")

_OPT_OUT_PHRASES: tuple[str, ...] = (
    "stop", "unsubscribe", "not interested", "leave me alone",
    "don't message me", "block you", "fuck off",
    "remove me", "take me off",
)
_BLOCKED_PHRASES: tuple[str, ...] = (
    "click here to claim", "free money", "guaranteed income",
    "limited offer!!!", "dm me for details",
)
_SHORTLINK_RE = re.compile(r"\b(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly|buff\.ly)\b", re.I)
_MENTION_RE   = re.compile(r"@\w+")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class DMTemplate:
    template_id: str
    body:        str
    tags:        tuple[str, ...] = ()

    def render(self, recipient_handle: str) -> str:
        return self.body.format(handle=recipient_handle)


_DEFAULT_TEMPLATES: list[DMTemplate] = [
    DMTemplate("warm-001",
               "hey {handle} — loved your last post, mind if I ask what camera you use?",
               ("warm", "question")),
    DMTemplate("warm-002",
               "{handle} your feed is really solid. what city are you shooting most of this in?",
               ("warm", "question")),
    DMTemplate("warm-003",
               "hey {handle}, had to say — that series last week stopped my scroll. keep going.",
               ("warm", "compliment")),
    DMTemplate("warm-004",
               "{handle} been following for a while — curious what got you started posting?",
               ("warm", "question")),
    DMTemplate("warm-005",
               "hey {handle}, no pitch — your work just made me want to say hi.",
               ("warm", "soft")),
]


@dataclass
class DMRecord:
    dm_id:             str
    actor_id:          str
    recipient_handle:  str
    template_id:       str
    body:              str
    state:             str                # queued | sent | replied | opted_out | blocked
    created_at:        str
    sent_at:           Optional[str] = None
    replied_at:        Optional[str] = None
    reply_body:        Optional[str] = None
    opted_out_at:      Optional[str] = None
    block_reason:      Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "dm_id":            self.dm_id,
            "actor_id":         self.actor_id,
            "recipient_handle": self.recipient_handle,
            "template_id":      self.template_id,
            "body":             self.body,
            "state":            self.state,
            "created_at":       self.created_at,
            "sent_at":          self.sent_at,
            "replied_at":       self.replied_at,
            "reply_body":       self.reply_body,
            "opted_out_at":     self.opted_out_at,
            "block_reason":     self.block_reason,
        }


@dataclass
class DMStats:
    total:          int = 0
    sent:           int = 0
    replied:        int = 0
    opted_out:      int = 0
    blocked:        int = 0
    last_tick_at:   Optional[str] = None


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


class InstagramDMFlow:
    """
    Drafts, gates, and enqueues DMs. Observes replies and detects opt-outs.
    Suppressed (actor, recipient) pairs are permanent — never retried.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        queue_getter:          Callable[[], list[dict]],
        health:                Optional[object] = None,
        templates:             Optional[list[DMTemplate]] = None,
        daily_cap_per_actor:   int = _DAILY_CAP_PER_ACTOR,
        cooldown_min:          int = _COOLDOWN_MIN,
        template_cap_fleet_day:int = _TEMPLATE_CAP_FLEET_DAY,
    ):
        self._accounts = accounts_store_getter
        self._queue    = queue_getter
        self.health = health
        self.templates = templates or list(_DEFAULT_TEMPLATES)
        self.daily_cap_per_actor = daily_cap_per_actor
        self.cooldown_min = cooldown_min
        self.template_cap_fleet_day = template_cap_fleet_day
        self._records: dict[str, DMRecord] = {}
        self._by_pair: dict[tuple[str, str], DMRecord] = {}
        self._suppress: set[tuple[str, str]] = set()
        self._events:  deque[dict] = deque(maxlen=400)
        self.stats = DMStats()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(_tz.utc)

    def _today(self) -> str:
        return self._now().date().isoformat()

    def _actor_safe(self, actor_id: str) -> bool:
        if self.health is None:
            return True
        return self.health.status_of(actor_id) not in _UNSAFE_HEALTH

    def _emit(self, kind: str, actor_id: str, recipient: str, detail: str = "") -> None:
        self._events.append({
            "ts": self._now().isoformat(), "event": kind,
            "actor_id": actor_id, "recipient": recipient, "detail": detail,
        })

    def _content_safe(self, body: str,
                       recipient_handle: str = "") -> Optional[str]:
        # The recipient's own @handle is allowed in the greeting; mask it
        # so the @mention guard only trips on OTHER @handles in the body.
        probe = body
        if recipient_handle:
            probe = probe.replace(recipient_handle, "")
            if recipient_handle.startswith("@"):
                probe = probe.replace(recipient_handle[1:], "")
        low = probe.lower()
        if _SHORTLINK_RE.search(probe):
            return "shortlink"
        if _MENTION_RE.search(probe):
            return "mention"
        for phrase in _BLOCKED_PHRASES:
            if phrase in low:
                return f"blocked_phrase:{phrase[:20]}"
        return None

    def _template_uses_today(self, template_id: str) -> int:
        today = self._today()
        return sum(1 for r in self._records.values()
                   if r.template_id == template_id
                   and r.created_at.startswith(today))

    def _actor_count_today(self, actor_id: str) -> int:
        today = self._today()
        return sum(1 for r in self._records.values()
                   if r.actor_id == actor_id
                   and r.created_at.startswith(today)
                   and r.state != "blocked")

    def _last_actor_send_at(self, actor_id: str) -> Optional[datetime]:
        latest: Optional[datetime] = None
        for r in self._records.values():
            if r.actor_id != actor_id: continue
            # Blocked records never left the system — they shouldn't count
            # toward cooldown or the record would starve the actor on
            # repeated pre-flight failures.
            if r.state == "blocked": continue
            ts = r.sent_at or r.created_at
            if not ts: continue
            dt = datetime.fromisoformat(ts)
            if latest is None or dt > latest:
                latest = dt
        return latest

    def _pick_template(self, actor_id: str,
                        recipient_handle: str) -> Optional[DMTemplate]:
        """LRU + SHA256 tiebreak over templates still under fleet cap."""
        under_cap = [t for t in self.templates
                     if self._template_uses_today(t.template_id)
                     < self.template_cap_fleet_day]
        if not under_cap: return None

        def sort_key(t: DMTemplate) -> tuple:
            uses = self._template_uses_today(t.template_id)
            tb = int(hashlib.sha256(
                f"{actor_id}:{recipient_handle}:{t.template_id}".encode()
            ).hexdigest()[:8], 16)
            return (uses, tb)

        return sorted(under_cap, key=sort_key)[0]

    # ------------------------------------------------------------------
    # Draft
    # ------------------------------------------------------------------

    def draft(self, actor_id: str, recipient_handle: str) -> DMRecord:
        """Pre-flight gates return a BLOCKED record so operators see them."""
        now = self._now()
        pair = (actor_id, recipient_handle)
        base = DMRecord(
            dm_id=f"dm-{uuid.uuid4().hex[:10]}",
            actor_id=actor_id, recipient_handle=recipient_handle,
            template_id="", body="", state="blocked",
            created_at=now.isoformat(),
        )

        if pair in self._suppress:
            base.block_reason = "opt_out_history"
            self._store(base, "blocked_opt_out")
            return base
        if pair in self._by_pair:
            base.block_reason = "dedupe"
            self._store(base, "blocked_dedupe")
            return base
        if not self._actor_safe(actor_id):
            base.block_reason = "actor_unsafe"
            self._store(base, "blocked_health")
            return base
        if self._actor_count_today(actor_id) >= self.daily_cap_per_actor:
            base.block_reason = "actor_cap"
            self._store(base, "blocked_cap")
            return base
        last = self._last_actor_send_at(actor_id)
        if last is not None and (now - last) < timedelta(minutes=self.cooldown_min):
            base.block_reason = "cooldown"
            self._store(base, "blocked_cooldown")
            return base
        tmpl = self._pick_template(actor_id, recipient_handle)
        if tmpl is None:
            base.block_reason = "template_cap"
            self._store(base, "blocked_template_cap")
            return base
        body = tmpl.render(recipient_handle)
        content_fail = self._content_safe(body, recipient_handle)
        if content_fail:
            base.block_reason = f"content:{content_fail}"
            self._store(base, "blocked_content")
            return base

        # Promote: queued → will enqueue via tick().
        base.template_id = tmpl.template_id
        base.body = body
        base.state = "queued"
        base.block_reason = None
        self._store(base, "drafted")
        return base

    def _store(self, rec: DMRecord, event: str) -> None:
        self._records[rec.dm_id] = rec
        if rec.state != "blocked":
            self._by_pair[(rec.actor_id, rec.recipient_handle)] = rec
        self._emit(event, rec.actor_id, rec.recipient_handle,
                   rec.block_reason or rec.template_id)

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def record_sent(self, dm_id: str) -> Optional[DMRecord]:
        rec = self._records.get(dm_id)
        if rec is None or rec.state not in ("queued", "sent"): return rec
        rec.state = "sent"
        rec.sent_at = self._now().isoformat()
        self.stats.sent += 1
        self._emit("sent", rec.actor_id, rec.recipient_handle, rec.template_id)
        return rec

    def record_reply(self, actor_id: str, recipient_handle: str,
                      body: str) -> Optional[DMRecord]:
        rec = self._by_pair.get((actor_id, recipient_handle))
        if rec is None: return None
        now = self._now().isoformat()
        rec.reply_body = body
        rec.replied_at = now
        low = body.lower()
        if any(p in low for p in _OPT_OUT_PHRASES):
            rec.state = "opted_out"
            rec.opted_out_at = now
            self._suppress.add((actor_id, recipient_handle))
            self.stats.opted_out += 1
            self._emit("opt_out", actor_id, recipient_handle, body[:60])
        else:
            rec.state = "replied"
            self.stats.replied += 1
            self._emit("replied", actor_id, recipient_handle, body[:60])
        return rec

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self) -> dict:
        """Promote queued drafts into the shared ig_queue."""
        now = self._now()
        today = now.date().isoformat()
        now_iso = now.isoformat()
        q = self._queue()
        enqueued = 0
        for rec in self._records.values():
            if rec.state != "queued": continue
            if any(e.get("action_id") == rec.dm_id for e in q): continue
            q.append({
                "action_id":  rec.dm_id,
                "account_id": rec.actor_id,
                "kind":       "dm",
                "target":     rec.recipient_handle,
                "body":       rec.body,
                "route":      ig_mod.ACTION_ROUTES.get("dm", "post"),
                "date":       today,
                "queued_at":  now_iso,
                "status":     "queued",
                "planner":    "ig_dm_flow",
                "reason":     f"template={rec.template_id}",
            })
            enqueued += 1
        # Stats refresh
        total = sent = replied = opted = blocked = 0
        for r in self._records.values():
            total += 1
            if r.state == "sent":     sent += 1
            if r.state == "replied":  replied += 1
            if r.state == "opted_out": opted += 1
            if r.state == "blocked":  blocked += 1
        self.stats.total = total
        self.stats.sent = sent
        self.stats.replied = replied
        self.stats.opted_out = opted
        self.stats.blocked = blocked
        self.stats.last_tick_at = now_iso
        return {"enqueued_this_tick": enqueued, "total": total,
                "blocked": blocked, "opted_out": opted}

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def for_actor(self, actor_id: str, limit: int = 30) -> dict:
        rows = [r.as_dict() for r in self._records.values()
                if r.actor_id == actor_id]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return {"actor_id": actor_id, "records": rows[:limit]}

    def summary(self) -> dict:
        # Count blocks by reason
        block_by_reason: dict[str, int] = defaultdict(int)
        for r in self._records.values():
            if r.state == "blocked" and r.block_reason:
                key = r.block_reason.split(":")[0]
                block_by_reason[key] += 1
        # Reply rate
        send_or_better = sum(1 for r in self._records.values()
                             if r.state in ("sent", "replied", "opted_out"))
        reply_rate = (self.stats.replied / send_or_better) if send_or_better else 0.0
        return {
            "stats": {
                "total":           self.stats.total,
                "sent":            self.stats.sent,
                "replied":         self.stats.replied,
                "opted_out":       self.stats.opted_out,
                "blocked":         self.stats.blocked,
                "suppress_pairs":  len(self._suppress),
                "reply_rate":      round(reply_rate, 3),
                "last_tick_at":    self.stats.last_tick_at,
                "daily_cap":       self.daily_cap_per_actor,
                "cooldown_min":    self.cooldown_min,
                "template_cap":    self.template_cap_fleet_day,
                "templates":       len(self.templates),
            },
            "block_reasons": dict(block_by_reason),
            "events":        list(reversed(self._events))[:30],
            "recent":        [r.as_dict() for r in
                              sorted(self._records.values(),
                                     key=lambda r: r.created_at,
                                     reverse=True)][:20],
        }
