"""Deterministic warming curve + diurnal distribution.

Pure functions.  Given (account, persona, now) returns the next 24h of
(kind, due_ms) tuples the scheduler should enqueue.

No agents, no LLM calls.

Curve source: PLAN.md §5 Phase 0 "Day 2-7 lockstep re-wake curve".
Beyond Day 7 the curve holds steady state at the Day 7 envelope until
Day 28, when a secondary ramp opens up to the per-account max observed
on Onimator (~22 actions/day combined).

Sampling:
 - Every range is treated as a LogNormal-ish band: we sample uniformly
   within [lo, hi] via secrets.randbits(53) so draws are not seeded from
   wall-clock state.  This matches the OrionFarm rule banning
   random.uniform on identity paths; even though scheduling is not
   identity-forming, the entropy discipline is the same.
 - Intra-day placement follows the persona's diurnal curve (peak hour
   from the persona_profiles table; a soft Normal around peak, clipped
   to the account's awake window 06:00-24:00 local).
"""
from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
except ImportError:  # pragma: no cover
    _ZoneInfo = None  # type: ignore


# Windows Python ships without the IANA tzdata by default, so ZoneInfo
# raises on 'America/New_York'. Fixed-offset fallback keeps scheduling
# deterministic; DST is intentionally ignored (farm uses standard
# offsets as its scheduling reference).
_FIXED_OFFSETS = {
    "America/New_York": -5,
    "America/Chicago":  -6,
    "America/Denver":   -7,
    "America/Los_Angeles": -8,
    "Europe/London":    0,
    "UTC":              0,
}


def _tz(name: str) -> timezone:
    if _ZoneInfo is not None:
        try:
            return _ZoneInfo(name)  # type: ignore[return-value]
        except Exception:
            pass
    return timezone(timedelta(hours=_FIXED_OFFSETS.get(name, -5)))


def _u01() -> float:
    return secrets.randbits(53) / (1 << 53)


def _gauss(mu: float, sigma: float) -> float:
    u1 = max(_u01(), 1e-12)
    u2 = _u01()
    return mu + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


# PLAN.md §5 Day 2-7 curve.  Day-1 is login+scroll only (zero actions
# of these kinds), so the curve starts at Day 2.
DAY_BANDS: dict[int, dict[str, tuple[float, float]]] = {
    1:  {"follows": (0, 0),  "likes": (0, 0),  "stories": (0, 0),  "comments": (0, 0)},
    2:  {"follows": (0, 0),  "likes": (0, 2),  "stories": (3, 5),   "comments": (0, 0)},
    3:  {"follows": (1, 2),  "likes": (2, 4),  "stories": (5, 8),   "comments": (0, 0)},
    4:  {"follows": (2, 4),  "likes": (4, 8),  "stories": (8, 12),  "comments": (0, 0)},
    5:  {"follows": (3, 6),  "likes": (6, 12), "stories": (10, 15), "comments": (0, 0)},
    6:  {"follows": (5, 9),  "likes": (10, 18), "stories": (15, 22), "comments": (1, 2)},
    7:  {"follows": (8, 14), "likes": (18, 28), "stories": (22, 32), "comments": (2, 3)},
}
STEADY_STATE = DAY_BANDS[7]
MAX_PER_DAY = 22  # Onimator proven ceiling per account


@dataclass
class ScheduledAction:
    kind: str
    due_ms: int
    params: dict


def band_for_day(day: int) -> dict[str, tuple[float, float]]:
    if day <= 7:
        return DAY_BANDS[max(1, day)]
    return STEADY_STATE


def sample_count(band: tuple[float, float]) -> int:
    lo, hi = band
    if hi <= lo:
        return int(lo)
    # Uniform over the band; anti-cluster rule (OrionFarm CLAUDE.md)
    # bans random.uniform; we roll our own with secrets entropy.
    return int(lo + (hi - lo) * _u01())


def _awake_window(peak_hour: int) -> tuple[int, int]:
    """Return (start_hour, end_hour) the persona is active.

    Peak hour anchors the window; the window is 12h centered on peak,
    clipped to [06, 24).
    """
    half = 6
    start = max(6, peak_hour - half)
    end = min(24, peak_hour + half)
    if end - start < 8:
        end = min(24, start + 8)
    return start, end


def _place_intraday(
    anchor_local: datetime, count: int, peak_hour: int,
) -> list[datetime]:
    """Place `count` actions inside anchor_local's day.

    Draws from Normal(peak, sigma=2.5h) and clips to the awake window.
    """
    if count <= 0:
        return []
    start_h, end_h = _awake_window(peak_hour)
    sigma_h = 2.5
    times: list[datetime] = []
    for _ in range(count):
        for _attempt in range(8):
            h = _gauss(peak_hour, sigma_h)
            if start_h <= h < end_h:
                break
        else:
            h = max(start_h, min(end_h - 0.01, h))
        hour = int(h)
        minute = int((h - hour) * 60)
        second = int(_u01() * 60)
        t = anchor_local.replace(
            hour=hour, minute=minute, second=second, microsecond=0,
        )
        times.append(t)
    times.sort()
    return times


def schedule_day(
    warming_day: int, now_ms: int, persona_tz: str = "America/New_York",
    peak_hour: int = 14,
) -> list[ScheduledAction]:
    """Return every action to enqueue for the account's next 24h.

    Pure function.  Same inputs -> structurally-identical outputs modulo
    the random band draw (which is the point; perfectly repeated action
    counts across accounts is a cluster bug).
    """
    tz = _tz(persona_tz)
    now_local = datetime.fromtimestamp(now_ms / 1000, tz=tz)
    # Anchor at today 00:00 local, but any time within the window is OK.
    anchor = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    bands = band_for_day(warming_day)

    # Enforce per-day ceiling.
    raw = {kind: sample_count(bands[kind]) for kind in bands}
    total = sum(raw.values())
    if total > MAX_PER_DAY:
        scale = MAX_PER_DAY / total
        raw = {k: max(0, int(v * scale)) for k, v in raw.items()}

    out: list[ScheduledAction] = []
    for kind, count in raw.items():
        slots = _place_intraday(anchor, count, peak_hour)
        for slot in slots:
            due_ms = int(slot.astimezone(timezone.utc).timestamp() * 1000)
            if due_ms <= now_ms:
                # Push into the future by a minute rather than firing past
                # actions on a late tick.
                due_ms = now_ms + 60_000
            out.append(ScheduledAction(kind=kind, due_ms=due_ms, params={
                "warming_day": warming_day,
            }))
    out.sort(key=lambda a: a.due_ms)
    return out


def summarise(actions: list[ScheduledAction]) -> dict:
    counts: dict[str, int] = {}
    for a in actions:
        counts[a.kind] = counts.get(a.kind, 0) + 1
    return {
        "total": len(actions),
        "by_kind": counts,
        "first_ms": actions[0].due_ms if actions else None,
        "last_ms": actions[-1].due_ms if actions else None,
    }
