"""
Instagram engagement lattice — seed inter-account likes / story-views
without tripping shadowban heuristics.

The fleet looks dead if every IG account only posts. Meta's shadowban
heuristics look for accounts with zero inbound engagement in the first
weeks — those are the exact accounts that get hidden from Explore and
hashtag pages. The lattice fixes that: a subset of our own IG accounts
act as "actors" and give controlled inbound engagement to other fleet
accounts.

But run naively, a lattice is MORE identifying than silence: if accounts
A, B, C all like account D every single day, that's a signal cluster IG
can bucket. The invariants here are the rules that keep that from
happening:

    1. per-target IN-DEGREE cap: no account receives more than N likes
       from fleet actors per day.
    2. per-actor OUT-DEGREE cap: no account gives more than M likes to
       fleet targets per day (budget cap already handles this; we check
       it here for safety).
    3. reciprocity cap: A likes B today → B cannot like A for
       RECIPROCITY_COOLDOWN_HOURS. Sustained A↔B reciprocity is the
       cleanest paired-operator signal in IG's book.
    4. country affinity: actor.proxy_country should match target's — a
       US fleet account getting likes only from GB accounts is a cluster
       flag (CLAUDE.md cross-field consistency rule, generalised to
       engagement).
    5. proxy diversity: two actors behind the SAME proxy never both like
       the same target in the same day.
    6. health gate: accounts flagged at_risk or shadowbanned are not
       actors (no amplification) and are not targets either (don't pour
       engagement into a dying account).
    7. chronotype gate: only actors whose diurnal weight is above
       _MIN_ACTOR_WEIGHT get picked — a lark acting at 3am is a signal.

Selection is deterministic: SHA256-keyed least-recently-used. Nothing
random. Plans are enqueued through the ig_queue so the executor fires
them under the same LogNormal cadence as organic actions.
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
from . import instagram_diurnal as ig_diurnal

log = logging.getLogger("phantom_fleet.platforms.instagram_lattice")


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

_IN_DEGREE_CAP_PER_DAY     = 4     # how many fleet likes a target may receive
_OUT_DEGREE_CAP_PER_DAY    = 6     # how many fleet actors one account may be
_RECIPROCITY_COOLDOWN_H    = 24
_MIN_ACTOR_WEIGHT          = 0.35  # diurnal weight floor to act
_PLAN_PER_TICK             = 8
_WHITELIST_KINDS           = ("like", "story_view")
_UNSAFE_HEALTH             = ("at_risk", "shadowbanned")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class LatticeEdge:
    actor_id:    str
    target_id:   str
    kind:        str                # "like" | "story_view"
    created_at:  str
    expires_at:  str                # reciprocity cooldown horizon


@dataclass
class LatticeStats:
    last_plan_at:   Optional[str] = None
    total_runs:     int = 0
    total_planned:  int = 0
    skipped_in_cap: int = 0
    skipped_recip:  int = 0
    skipped_proxy:  int = 0
    skipped_health: int = 0
    skipped_tz:     int = 0
    skipped_country:int = 0
    last_plan_size: int = 0


# ---------------------------------------------------------------------------
# Lattice
# ---------------------------------------------------------------------------


class InstagramEngagementLattice:
    """
    Plans a batch of safe (actor, target, kind) engagements per tick.

    Writes plans into the shared IG queue. Reads account health + proxy
    pins + funnel + diurnal to gate the selection.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        queue_getter:          Callable[[], list[dict]],
        health:                Optional[object] = None,
        proxy:                 Optional[object] = None,
        in_degree_cap_per_day: int = _IN_DEGREE_CAP_PER_DAY,
        out_degree_cap_per_day:int = _OUT_DEGREE_CAP_PER_DAY,
        reciprocity_cooldown_h:int = _RECIPROCITY_COOLDOWN_H,
        plan_per_tick:         int = _PLAN_PER_TICK,
        min_actor_weight:      float = _MIN_ACTOR_WEIGHT,
    ):
        self._accounts = accounts_store_getter
        self._queue    = queue_getter
        self.health = health
        self.proxy  = proxy
        self.in_degree_cap  = in_degree_cap_per_day
        self.out_degree_cap = out_degree_cap_per_day
        self.reciprocity_cooldown_h = reciprocity_cooldown_h
        self.plan_per_tick  = plan_per_tick
        self.min_actor_weight = min_actor_weight
        self._edges: deque[LatticeEdge] = deque(maxlen=2000)
        self.stats = LatticeStats()

    # ------------------------------------------------------------------
    # Internal views
    # ------------------------------------------------------------------

    def _ig_accounts(self) -> list[dict]:
        return [r for r in self._accounts().values()
                if r.get("platform") == "instagram"
                and r.get("status") in ("active", "warming")]

    def _is_safe_status(self, account_id: str) -> bool:
        if self.health is None:
            return True
        status = self.health.status_of(account_id)
        return status not in _UNSAFE_HEALTH

    def _proxy_of(self, account_id: str) -> Optional[str]:
        if self.proxy is None:
            return None
        pin = self.proxy.pin_for(account_id)
        return pin.proxy_id if pin else None

    def _country_of(self, row: dict) -> str:
        c = row.get("proxy_country")
        if c:
            return str(c).upper()
        return "US"

    def _today(self) -> str:
        return datetime.now(_tz.utc).date().isoformat()

    def _in_degree_today(self, target_id: str) -> int:
        today = self._today()
        return sum(1 for e in self._edges
                   if e.target_id == target_id
                   and e.created_at.startswith(today))

    def _out_degree_today(self, actor_id: str) -> int:
        today = self._today()
        return sum(1 for e in self._edges
                   if e.actor_id == actor_id
                   and e.created_at.startswith(today))

    def _in_reciprocity_window(self, actor_id: str, target_id: str) -> bool:
        """target → actor in the cooldown window blocks actor → target."""
        now = datetime.now(_tz.utc)
        cutoff = now - timedelta(hours=self.reciprocity_cooldown_h)
        for e in self._edges:
            if e.actor_id == target_id and e.target_id == actor_id:
                if datetime.fromisoformat(e.created_at) >= cutoff:
                    return True
        return False

    def _target_already_hit_by_proxy(self, proxy_id: Optional[str],
                                      target_id: str) -> bool:
        """Rule 5 — two actors behind same proxy never hit same target same day."""
        if proxy_id is None:
            return False
        today = self._today()
        for e in self._edges:
            if e.target_id == target_id and e.created_at.startswith(today):
                if self._proxy_of(e.actor_id) == proxy_id:
                    return True
        return False

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _rank(self, account_id: str) -> int:
        return int(hashlib.sha256(
            f"lattice:{account_id}:{self.stats.total_runs}".encode()
        ).hexdigest()[:8], 16)

    def plan_tick(self) -> list[dict]:
        accounts = self._ig_accounts()
        if not accounts:
            self.stats.last_plan_at = datetime.now(_tz.utc).isoformat()
            self.stats.total_runs += 1
            self.stats.last_plan_size = 0
            return []

        # Split: actors = ones awake enough + safe; targets = everyone safe.
        safe = [r for r in accounts if self._is_safe_status(r["account_id"])]
        safe_ids = {r["account_id"] for r in safe}

        actors: list[dict] = []
        for r in safe:
            w = ig_diurnal.weight_now(r["account_id"], r)
            if w >= self.min_actor_weight:
                actors.append(r)
            else:
                self.stats.skipped_tz += 1

        # Sort actors by (least out-degree today, hash tiebreak).
        actors.sort(key=lambda r: (
            self._out_degree_today(r["account_id"]),
            self._rank(r["account_id"]),
        ))
        # Sort targets by LEAST inbound today → spreads love.
        targets = sorted(safe, key=lambda r: (
            self._in_degree_today(r["account_id"]),
            self._rank(r["account_id"]),
        ))

        plan: list[dict] = []
        q = self._queue()
        now = datetime.now(_tz.utc)
        now_iso = now.isoformat()
        today = now.date().isoformat()
        exp_iso = (now + timedelta(hours=self.reciprocity_cooldown_h)).isoformat()

        for actor in actors:
            if len(plan) >= self.plan_per_tick:
                break
            if self._out_degree_today(actor["account_id"]) >= self.out_degree_cap:
                continue
            actor_country = self._country_of(actor)
            actor_proxy = self._proxy_of(actor["account_id"])
            for target in targets:
                if actor["account_id"] == target["account_id"]:
                    continue
                if target["account_id"] not in safe_ids:
                    self.stats.skipped_health += 1
                    continue
                if self._in_degree_today(target["account_id"]) >= self.in_degree_cap:
                    self.stats.skipped_in_cap += 1
                    continue
                if self._in_reciprocity_window(actor["account_id"], target["account_id"]):
                    self.stats.skipped_recip += 1
                    continue
                if self._country_of(target) != actor_country:
                    self.stats.skipped_country += 1
                    continue
                if self._target_already_hit_by_proxy(
                        actor_proxy, target["account_id"]):
                    self.stats.skipped_proxy += 1
                    continue
                kind = _WHITELIST_KINDS[
                    (self._rank(actor["account_id"] + target["account_id"]) %
                     len(_WHITELIST_KINDS))]
                edge = LatticeEdge(
                    actor_id=actor["account_id"],
                    target_id=target["account_id"],
                    kind=kind,
                    created_at=now_iso,
                    expires_at=exp_iso,
                )
                self._edges.append(edge)
                # Enqueue through the shared IG queue, same shape as the
                # orchestrator's output; the executor will fire it under
                # the usual LogNormal cadence.
                q.append({
                    "action_id":  f"ig-ltc-{uuid.uuid4().hex[:10]}",
                    "account_id": actor["account_id"],
                    "kind":       kind,
                    "target":     f"ig://account:{target['account_id']}",
                    "route":      ig_mod.ACTION_ROUTES[kind],
                    "date":       today,
                    "queued_at":  now_iso,
                    "status":     "queued",
                    "planner":    "ig_lattice",
                    "reason":     f"lattice · actor→target · country={actor_country}",
                })
                plan.append({
                    "actor_id":  actor["account_id"],
                    "target_id": target["account_id"],
                    "kind":      kind,
                    "country":   actor_country,
                })
                break

        self.stats.last_plan_at = now_iso
        self.stats.total_runs += 1
        self.stats.total_planned += len(plan)
        self.stats.last_plan_size = len(plan)
        return plan

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def recent_edges(self, limit: int = 40) -> list[dict]:
        return [{
            "actor_id":   e.actor_id, "target_id": e.target_id,
            "kind":       e.kind,     "created_at": e.created_at,
            "expires_at": e.expires_at,
        } for e in list(self._edges)[-limit:]][::-1]

    def summary(self) -> dict:
        accounts = self._ig_accounts()
        today = self._today()
        in_hist:  dict[str, int] = defaultdict(int)
        out_hist: dict[str, int] = defaultdict(int)
        for e in self._edges:
            if e.created_at.startswith(today):
                in_hist[e.target_id] += 1
                out_hist[e.actor_id] += 1

        hotspots = sorted(in_hist.items(), key=lambda kv: -kv[1])[:5]
        unsafe_targets = sum(1 for count in in_hist.values()
                             if count > self.in_degree_cap)
        over_actors    = sum(1 for count in out_hist.values()
                             if count > self.out_degree_cap)

        return {
            "stats": {
                "accounts_safe":     len(accounts),
                "last_plan_at":      self.stats.last_plan_at,
                "last_plan_size":    self.stats.last_plan_size,
                "total_runs":        self.stats.total_runs,
                "total_planned":     self.stats.total_planned,
                "skipped_in_cap":    self.stats.skipped_in_cap,
                "skipped_recip":     self.stats.skipped_recip,
                "skipped_proxy":     self.stats.skipped_proxy,
                "skipped_health":    self.stats.skipped_health,
                "skipped_tz":        self.stats.skipped_tz,
                "skipped_country":   self.stats.skipped_country,
                "unsafe_targets":    unsafe_targets,
                "over_actors":       over_actors,
            },
            "config": {
                "in_degree_cap":  self.in_degree_cap,
                "out_degree_cap": self.out_degree_cap,
                "reciprocity_h":  self.reciprocity_cooldown_h,
                "min_actor_w":    self.min_actor_weight,
                "plan_per_tick":  self.plan_per_tick,
                "kinds":          list(_WHITELIST_KINDS),
            },
            "hotspots":          [{"target_id": t, "likes_today": c}
                                  for t, c in hotspots],
            "today_in_degree":   dict(in_hist),
            "today_out_degree":  dict(out_hist),
            "recent_edges":      self.recent_edges(limit=20),
        }
