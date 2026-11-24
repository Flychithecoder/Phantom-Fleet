"""
Instagram unfollow discipline — keep follow:follower ratios clean
without tipping IG's spam heuristics.

The problem: a fleet account that follows 2000 people but only 50 follow
back looks like outreach spam to IG. Over time that ratio is one of the
clearest signals in the shadowban bucket. But blindly unfollowing
everyone who doesn't follow back is ALSO a signal — "mass unfollow in
one burst" is itself a flagged pattern.

This module tracks every outbound follow, waits for a follow-back window
(default 72h), and stages unfollows under a paced daily cap. The
staging is deterministic, hysteretic, and whitelist-aware:

    * every follow writes a FollowRecord: actor + target + followed_at
    * follow-back is recorded when observed (via funnel event, webhook,
      or operator mark)
    * after `_MIN_DWELL_H`, any record without follow-back becomes an
      unfollow CANDIDATE
    * candidates are sorted stale-first; `_DAILY_UNFOLLOW_CAP` of them
      are enqueued per account per day
    * when follow:follower ratio exceeds `_RATIO_TRIP`, the daily cap
      doubles (we're already in signal territory — clear faster)
    * records marked "retained" (converters, DM chains, repeat engagers)
      are never unfollowed, even past the window
    * unfollow enqueues go through the shared ig_queue so the executor
      fires them under the same LogNormal cadence as organic actions

Nothing random. Candidate ordering is (stale desc, hash tiebreak); the
audit harness verifies the invariants hold over a mixed fleet.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
from typing import Callable, Optional

from . import instagram as ig_mod

log = logging.getLogger("phantom_fleet.platforms.instagram_unfollow")


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

_MIN_DWELL_H           = 48    # never unfollow in the first 2 days
_FOLLOW_BACK_WINDOW_H  = 72    # give IG 3 days to deliver a follow-back
_DAILY_UNFOLLOW_CAP    = 10    # per account per day (ratio-boosted below)
_RATIO_TRIP            = 3.0   # follows:followers trip → double cap
_RATIO_CAP_MULT        = 2.0


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class FollowRecord:
    follow_id:          str
    actor_id:           str
    target_handle:      str
    followed_at:        str
    follow_back_at:     Optional[str] = None
    unfollowed_at:      Optional[str] = None
    retained:           bool = False
    notes:              list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.unfollowed_at: return "unfollowed"
        if self.retained:      return "retained"
        if self.follow_back_at: return "follow_back"
        return "pending"

    def age_hours(self, now: datetime) -> float:
        return (now - datetime.fromisoformat(self.followed_at)).total_seconds() / 3600.0

    def as_dict(self) -> dict:
        return {
            "follow_id":      self.follow_id,
            "actor_id":       self.actor_id,
            "target_handle":  self.target_handle,
            "followed_at":    self.followed_at,
            "follow_back_at": self.follow_back_at,
            "unfollowed_at":  self.unfollowed_at,
            "retained":       self.retained,
            "status":         self.status,
        }


@dataclass
class UnfollowStats:
    total_follows:   int = 0
    pending:         int = 0
    follow_back:     int = 0
    retained:        int = 0
    unfollowed:      int = 0
    candidates:      int = 0
    enqueued_today:  int = 0
    ratio_tripped:   int = 0
    last_tick_at:    Optional[str] = None


# ---------------------------------------------------------------------------
# Discipline
# ---------------------------------------------------------------------------


class InstagramUnfollowDiscipline:
    """
    Walks follow records, promotes stale ones to unfollow candidates,
    and paces them into the shared ig_queue under a daily cap per actor.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        queue_getter:          Callable[[], list[dict]],
        health:                Optional[object] = None,
        min_dwell_h:           int = _MIN_DWELL_H,
        follow_back_window_h:  int = _FOLLOW_BACK_WINDOW_H,
        daily_cap:             int = _DAILY_UNFOLLOW_CAP,
        ratio_trip:            float = _RATIO_TRIP,
    ):
        self._accounts = accounts_store_getter
        self._queue    = queue_getter
        self.health    = health
        self.min_dwell_h          = min_dwell_h
        self.follow_back_window_h = follow_back_window_h
        self.daily_cap            = daily_cap
        self.ratio_trip           = ratio_trip
        self._records: dict[str, FollowRecord] = {}
        self._events:  deque[dict] = deque(maxlen=400)
        self.stats = UnfollowStats()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(_tz.utc)

    def _actor_row(self, actor_id: str) -> dict:
        return self._accounts().get(actor_id, {})

    def _records_for_actor(self, actor_id: str) -> list[FollowRecord]:
        return [r for r in self._records.values() if r.actor_id == actor_id]

    def _enqueued_today_for(self, actor_id: str) -> int:
        today = self._now().date().isoformat()
        return sum(1 for e in self._queue()
                   if e.get("account_id") == actor_id
                   and e.get("kind") == "unfollow"
                   and e.get("date") == today)

    def _ratio_for(self, actor_id: str) -> Optional[float]:
        row = self._actor_row(actor_id)
        f_out = row.get("follows_out") or len(self._records_for_actor(actor_id))
        f_in  = row.get("followers_in")
        if f_in is None or f_in == 0:
            # If we have outbound follows but no inbound known, treat as
            # "high" to trigger ratio guard early.
            return float("inf") if f_out > 0 else None
        return f_out / max(1, f_in)

    def _cap_for(self, actor_id: str) -> int:
        ratio = self._ratio_for(actor_id)
        if ratio is not None and ratio > self.ratio_trip:
            return int(self.daily_cap * _RATIO_CAP_MULT)
        return self.daily_cap

    def _emit(self, kind: str, actor_id: str, detail: str = "") -> None:
        self._events.append({
            "ts": self._now().isoformat(),
            "event": kind, "actor_id": actor_id, "detail": detail,
        })

    # ------------------------------------------------------------------
    # Record intake
    # ------------------------------------------------------------------

    def record_follow(self, actor_id: str, target_handle: str,
                       *, followed_at: Optional[str] = None) -> FollowRecord:
        fid = f"flw-{uuid.uuid4().hex[:10]}"
        now_iso = followed_at or self._now().isoformat()
        rec = FollowRecord(
            follow_id=fid, actor_id=actor_id,
            target_handle=target_handle, followed_at=now_iso,
        )
        self._records[fid] = rec
        self._emit("follow", actor_id, target_handle)
        return rec

    def record_follow_back(self, actor_id: str, target_handle: str,
                            *, when: Optional[str] = None) -> Optional[FollowRecord]:
        for rec in self._records.values():
            if (rec.actor_id == actor_id
                    and rec.target_handle == target_handle
                    and rec.follow_back_at is None
                    and rec.unfollowed_at is None):
                rec.follow_back_at = when or self._now().isoformat()
                self._emit("follow_back", actor_id, target_handle)
                return rec
        return None

    def mark_retained(self, actor_id: str, target_handle: str) -> Optional[FollowRecord]:
        for rec in self._records.values():
            if (rec.actor_id == actor_id
                    and rec.target_handle == target_handle):
                rec.retained = True
                rec.notes.append("retained")
                self._emit("retained", actor_id, target_handle)
                return rec
        return None

    # ------------------------------------------------------------------
    # Candidate selection + enqueue
    # ------------------------------------------------------------------

    def candidates_for(self, actor_id: str) -> list[FollowRecord]:
        now = self._now()
        out: list[FollowRecord] = []
        for rec in self._records.values():
            if rec.actor_id != actor_id: continue
            if rec.unfollowed_at or rec.retained: continue
            if rec.follow_back_at: continue
            age = rec.age_hours(now)
            if age < self.min_dwell_h: continue
            if age < self.follow_back_window_h:
                # Still inside the window — give IG time to deliver the
                # follow-back. Exception: ratio tripped → pull early.
                ratio = self._ratio_for(actor_id)
                if ratio is None or ratio <= self.ratio_trip: continue
            out.append(rec)
        out.sort(key=lambda r: (
            -r.age_hours(now),
            int(hashlib.sha256(r.follow_id.encode()).hexdigest()[:8], 16),
        ))
        return out

    def tick(self) -> dict:
        """Promote candidates into the ig_queue under per-actor daily cap."""
        now = self._now()
        now_iso = now.isoformat()
        today = now.date().isoformat()
        q = self._queue()
        actors = {r.actor_id for r in self._records.values()}
        enqueued = 0
        ratio_trips = 0

        for actor_id in sorted(actors):
            if self.health is not None:
                status = self.health.status_of(actor_id)
                if status in ("at_risk", "shadowbanned"):
                    # Never pile unfollows on an account IG is already
                    # watching — that's the worst time.
                    continue
            ratio = self._ratio_for(actor_id)
            tripped = ratio is not None and ratio > self.ratio_trip
            if tripped: ratio_trips += 1
            cap = self._cap_for(actor_id)
            already = self._enqueued_today_for(actor_id)
            room = max(0, cap - already)
            if room <= 0: continue
            for cand in self.candidates_for(actor_id)[:room]:
                action_id = f"ig-unf-{uuid.uuid4().hex[:10]}"
                q.append({
                    "action_id":  action_id,
                    "account_id": actor_id,
                    "kind":       "unfollow",
                    "target":     cand.target_handle,
                    "route":      ig_mod.ACTION_ROUTES.get("unfollow", "follow"),
                    "date":       today,
                    "queued_at":  now_iso,
                    "status":     "queued",
                    "planner":    "ig_unfollow_discipline",
                    "reason":     (f"age {cand.age_hours(now):.0f}h, "
                                   f"ratio={ratio!r}, cap={cap}"),
                })
                cand.unfollowed_at = now_iso
                cand.notes.append(f"queued unfollow · {action_id}")
                self._emit("queued_unfollow", actor_id, cand.target_handle)
                enqueued += 1

        # Stats refresh
        pending = follow_back = retained_n = unfollowed = 0
        for rec in self._records.values():
            if   rec.unfollowed_at: unfollowed += 1
            elif rec.retained:      retained_n += 1
            elif rec.follow_back_at: follow_back += 1
            else:                    pending += 1
        self.stats.total_follows  = len(self._records)
        self.stats.pending        = pending
        self.stats.follow_back    = follow_back
        self.stats.retained       = retained_n
        self.stats.unfollowed     = unfollowed
        self.stats.enqueued_today += enqueued
        self.stats.ratio_tripped  = ratio_trips
        self.stats.last_tick_at   = now_iso
        # Rebuild candidate count using current state
        self.stats.candidates = sum(
            len(self.candidates_for(a)) for a in actors
        )
        return {
            "enqueued_this_tick": enqueued,
            "ratio_tripped":      ratio_trips,
            "candidates":         self.stats.candidates,
        }

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def for_actor(self, actor_id: str, limit: int = 30) -> dict:
        rows = [r.as_dict() for r in self._records_for_actor(actor_id)]
        return {
            "actor_id":   actor_id,
            "ratio":      self._ratio_for(actor_id),
            "cap":        self._cap_for(actor_id),
            "records":    rows[:limit],
            "candidates": [c.as_dict() for c in self.candidates_for(actor_id)[:20]],
        }

    def summary(self, limit_actors: int = 20) -> dict:
        actors = {r.actor_id for r in self._records.values()}
        actor_rows: list[dict] = []
        for actor_id in sorted(actors):
            recs = self._records_for_actor(actor_id)
            actor_rows.append({
                "actor_id":   actor_id,
                "follows":    sum(1 for r in recs),
                "pending":    sum(1 for r in recs if r.status == "pending"),
                "retained":   sum(1 for r in recs if r.retained),
                "candidates": len(self.candidates_for(actor_id)),
                "ratio":      self._ratio_for(actor_id),
                "cap":        self._cap_for(actor_id),
            })
        actor_rows.sort(key=lambda r: -r["candidates"])
        return {
            "stats": {
                "total_follows":   self.stats.total_follows,
                "pending":         self.stats.pending,
                "follow_back":     self.stats.follow_back,
                "retained":        self.stats.retained,
                "unfollowed":      self.stats.unfollowed,
                "candidates":      self.stats.candidates,
                "enqueued_today":  self.stats.enqueued_today,
                "ratio_tripped":   self.stats.ratio_tripped,
                "last_tick_at":    self.stats.last_tick_at,
                "min_dwell_h":     self.min_dwell_h,
                "window_h":        self.follow_back_window_h,
                "daily_cap":       self.daily_cap,
                "ratio_trip":      self.ratio_trip,
            },
            "actors":  actor_rows[:limit_actors],
            "events":  list(reversed(self._events))[:30],
        }
