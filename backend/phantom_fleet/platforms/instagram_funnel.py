"""
Instagram funnel tracker — IG side of the conversion chain.

    post_posted → impression → profile_view → bio_link_click
                                           ↘  threads_tap  → subscribe
                                           ↘  dm_sent      → reply

post_posted and threads_tap sit in the middle of the fleet-wide chain
(the IG-side mirror of threads_funnel.reply_posted), so reading both
funnels side-by-side tells you which half of the cross-post pair is
dragging. For example, if IG impression → profile_view is healthy but
Threads reply_to_sub is cold, your Threads reply copy is the problem,
not your IG post selection.

In-memory ring + per-account counters, same shape as ThreadsFunnelTracker
so the UI can reuse the funnel widget verbatim.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

log = logging.getLogger("phantom_fleet.platforms.instagram_funnel")

IGEventKind = Literal[
    "post_posted",     # IG account published a feed post / reel
    "impression",      # The post surfaced in someone's feed
    "profile_view",    # Viewer tapped through to the IG profile
    "bio_link_click",  # Viewer tapped the external link
    "threads_tap",     # Viewer tapped the Threads badge to the linked account
    "dm_sent",         # Viewer DM'd the account
    "follow_back",     # Viewer followed after seeing the profile
]

FUNNEL_ORDER: tuple[IGEventKind, ...] = (
    "post_posted", "impression", "profile_view", "bio_link_click", "threads_tap",
)


@dataclass
class IGFunnelEvent:
    kind:          IGEventKind
    ig_account_id: str
    post_id:       Optional[str] = None
    target:        str = ""
    meta:          dict = field(default_factory=dict)
    ts:            str = ""

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()


def _safe_ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


@dataclass
class IGAccountFunnel:
    ig_account_id:  str
    post_posted:    int = 0
    impression:     int = 0
    profile_view:   int = 0
    bio_link_click: int = 0
    threads_tap:    int = 0
    dm_sent:        int = 0
    follow_back:    int = 0

    def as_dict(self) -> dict:
        return {
            "ig_account_id": self.ig_account_id,
            "counts": {
                "post_posted":    self.post_posted,
                "impression":     self.impression,
                "profile_view":   self.profile_view,
                "bio_link_click": self.bio_link_click,
                "threads_tap":    self.threads_tap,
                "dm_sent":        self.dm_sent,
                "follow_back":    self.follow_back,
            },
            "rates": {
                "post_to_impression":  _safe_ratio(self.impression, self.post_posted),
                "impression_to_view":  _safe_ratio(self.profile_view, self.impression),
                "view_to_bio_click":   _safe_ratio(self.bio_link_click, self.profile_view),
                "view_to_threads":     _safe_ratio(self.threads_tap, self.profile_view),
                "post_to_threads":     _safe_ratio(self.threads_tap, self.post_posted),  # end-to-end
            },
        }


class InstagramFunnelTracker:
    """In-memory IG funnel sink. Mirror of ThreadsFunnelTracker."""

    def __init__(self, ring_size: int = 2000):
        self._events: deque[IGFunnelEvent] = deque(maxlen=ring_size)
        self._counters: dict[str, IGAccountFunnel] = {}

    def record(self, event: IGFunnelEvent) -> IGAccountFunnel:
        self._events.append(event)
        c = self._counters.setdefault(
            event.ig_account_id,
            IGAccountFunnel(ig_account_id=event.ig_account_id),
        )
        if event.kind == "post_posted":    c.post_posted    += 1
        elif event.kind == "impression":   c.impression     += 1
        elif event.kind == "profile_view": c.profile_view   += 1
        elif event.kind == "bio_link_click": c.bio_link_click += 1
        elif event.kind == "threads_tap":  c.threads_tap    += 1
        elif event.kind == "dm_sent":      c.dm_sent        += 1
        elif event.kind == "follow_back":  c.follow_back    += 1
        return c

    def recent(self, limit: int = 100,
               ig_account_id: Optional[str] = None) -> list[dict]:
        rows: list[dict] = []
        for ev in reversed(self._events):
            if ig_account_id and ev.ig_account_id != ig_account_id:
                continue
            rows.append({
                "kind":          ev.kind,
                "ig_account_id": ev.ig_account_id,
                "post_id":       ev.post_id,
                "target":        ev.target,
                "ts":            ev.ts,
            })
            if len(rows) >= limit:
                break
        return rows

    def for_account(self, ig_account_id: str) -> IGAccountFunnel:
        return self._counters.get(
            ig_account_id,
            IGAccountFunnel(ig_account_id=ig_account_id),
        )

    def summary(self) -> dict:
        totals = IGAccountFunnel(ig_account_id="__all__")
        for c in self._counters.values():
            totals.post_posted    += c.post_posted
            totals.impression     += c.impression
            totals.profile_view   += c.profile_view
            totals.bio_link_click += c.bio_link_click
            totals.threads_tap    += c.threads_tap
            totals.dm_sent        += c.dm_sent
            totals.follow_back    += c.follow_back
        ranked = sorted(
            (c for c in self._counters.values() if c.post_posted > 0),
            key=lambda c: (_safe_ratio(c.threads_tap, c.post_posted), c.threads_tap),
            reverse=True,
        )
        return {
            "totals":    totals.as_dict(),
            "accounts":  len(self._counters),
            "top":       [c.as_dict() for c in ranked[:5]],
            "ring_size": len(self._events),
        }
