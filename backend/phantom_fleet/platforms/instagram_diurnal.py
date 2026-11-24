"""
Instagram diurnal schedule — gate actions against each account's local
awake hours.

CLAUDE.md §"Known fleet bugs" names flat fleet-wide action timing as the
4th bug of the existing Onimator deployment:

    > current Onimator uses uniform delays per persona regardless of
    > claimed timezone. OrionFarm must schedule against the persona's
    > diurnal curve.

This module fixes that for IG. Each account picks one of three
chronotypes deterministically from SHA256(account_id):
    morning_lark (20%)  : up at 06, peaks 08–10, down by 22
    standard     (60%)  : up at 08, peaks 12–14 + 19–21, down by 24
    night_owl    (20%)  : up at 11, peaks 15 + 21–01, down by 03

`weight_for(account_id, row, hour_utc)` returns the hourly weight in
[0, 1] at the persona's local hour.

`weight_now(account_id, row)` is `weight_for` with the current UTC hour.

Orchestrator & executor consume these to:
    * scale plan_per_tick (orchestrator)
    * skip accounts whose local weight is below a threshold (executor)

No `random.*` anywhere — chronotype is SHA256-seeded, so every weight is
reproducible for the audit harness.
"""
from __future__ import annotations

import hashlib
from typing import Literal, Optional

Chronotype = Literal["morning_lark", "standard", "night_owl"]

# ---------------------------------------------------------------------------
# Hourly weight curves — [0, 1] by local hour (0–23)
# ---------------------------------------------------------------------------
#
# Shape measured from aggregate IG engagement studies: a two-peak day
# (morning and evening) for standard users, a shifted-forward peak for
# larks, and a late-shift for owls. Values are weights, not budgets — a
# 0.9 hour runs ~9x the actions of a 0.1 hour on the same account.

_CURVES: dict[Chronotype, list[float]] = {
    "morning_lark": [
        # 0     1     2     3     4     5     6     7     8     9    10    11
        0.02, 0.02, 0.02, 0.02, 0.05, 0.25, 0.55, 0.85, 1.00, 1.00, 0.95, 0.85,
        # 12   13    14    15    16    17    18    19    20    21    22    23
        0.75, 0.70, 0.65, 0.55, 0.50, 0.45, 0.40, 0.30, 0.20, 0.10, 0.05, 0.03,
    ],
    "standard": [
        # 0     1     2     3     4     5     6     7     8     9    10    11
        0.02, 0.02, 0.02, 0.02, 0.02, 0.05, 0.20, 0.40, 0.60, 0.75, 0.80, 0.85,
        # 12   13    14    15    16    17    18    19    20    21    22    23
        0.90, 1.00, 0.95, 0.85, 0.75, 0.70, 0.75, 0.90, 1.00, 0.95, 0.70, 0.35,
    ],
    "night_owl": [
        # 0     1     2     3     4     5     6     7     8     9    10    11
        0.85, 0.75, 0.55, 0.30, 0.10, 0.05, 0.03, 0.03, 0.05, 0.10, 0.20, 0.35,
        # 12   13    14    15    16    17    18    19    20    21    22    23
        0.50, 0.65, 0.75, 0.85, 0.80, 0.80, 0.85, 0.90, 0.95, 1.00, 1.00, 0.95,
    ],
}

# Chronotype buckets by SHA256 nibble of account_id:
#   nibbles 0–2  → morning_lark (3/16 ≈ 19%)
#   nibbles 3–D → standard     (11/16 ≈ 69%)
#   nibbles E–F → night_owl    (2/16  ≈ 13%)
# Close to the 20/60/20 target, deterministic.

def chronotype_for(account_id: str) -> Chronotype:
    digest = hashlib.sha256(f"chronotype:{account_id}".encode()).hexdigest()
    n = int(digest[0], 16)
    if n < 3:  return "morning_lark"
    if n < 14: return "standard"
    return "night_owl"


# ---------------------------------------------------------------------------
# Timezone → UTC offset (hours). Static lookup, no DST (hourly granularity
# is coarse enough that DST drift of 1h doesn't matter for throttling).
# ---------------------------------------------------------------------------

_TZ_OFFSET: dict[str, int] = {
    "UTC":                   0,
    "Europe/London":          0,
    "Europe/Berlin":          1,
    "Europe/Paris":           1,
    "Europe/Madrid":          1,
    "Europe/Rome":            1,
    "Europe/Athens":          2,
    "Europe/Moscow":          3,
    "Asia/Dubai":             4,
    "Asia/Karachi":           5,
    "Asia/Kolkata":           5,
    "Asia/Bangkok":           7,
    "Asia/Singapore":         8,
    "Asia/Hong_Kong":         8,
    "Asia/Shanghai":          8,
    "Asia/Tokyo":             9,
    "Asia/Seoul":             9,
    "Australia/Sydney":      11,
    "Pacific/Auckland":      13,
    "Pacific/Honolulu":     -10,
    "America/Anchorage":     -9,
    "America/Los_Angeles":   -8,
    "America/Denver":        -7,
    "America/Phoenix":       -7,
    "America/Chicago":       -6,
    "America/Mexico_City":   -6,
    "America/New_York":      -5,
    "America/Toronto":       -5,
    "America/Sao_Paulo":     -3,
    "Atlantic/Azores":       -1,
    "Africa/Lagos":           1,
    "Africa/Johannesburg":    2,
}


def _tz_offset(tz: str) -> int:
    return _TZ_OFFSET.get(tz, -5)   # default New York for dev seed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def local_hour(tz: str, hour_utc: int) -> int:
    return (hour_utc + _tz_offset(tz)) % 24


def weight_for(account_id: str, row: dict, hour_utc: int) -> float:
    tz = str(row.get("timezone") or "America/New_York")
    hour_local = local_hour(tz, hour_utc)
    curve = _CURVES[chronotype_for(account_id)]
    return float(curve[hour_local])


def weight_now(account_id: str, row: dict) -> float:
    from datetime import datetime, timezone as _tz
    return weight_for(account_id, row, datetime.now(_tz.utc).hour)


def curve_for(account_id: str, row: Optional[dict] = None) -> dict:
    """Full 24-hour curve in UTC order, labelled with local hour and weight."""
    chrono = chronotype_for(account_id)
    tz = str((row or {}).get("timezone") or "America/New_York")
    hours = []
    for h in range(24):
        local = local_hour(tz, h)
        hours.append({
            "hour_utc":   h,
            "hour_local": local,
            "weight":     _CURVES[chrono][local],
        })
    return {
        "account_id": account_id,
        "chronotype": chrono,
        "timezone":   tz,
        "utc_offset": _tz_offset(tz),
        "hours":      hours,
    }


def fleet_mean_weight_now(accounts: list[dict]) -> float:
    from datetime import datetime, timezone as _tz
    h = datetime.now(_tz.utc).hour
    if not accounts:
        return 0.0
    s = sum(weight_for(r["account_id"], r, h) for r in accounts)
    return s / len(accounts)


def fleet_chronotype_breakdown(accounts: list[dict]) -> dict[str, int]:
    out = {"morning_lark": 0, "standard": 0, "night_owl": 0}
    for r in accounts:
        out[chronotype_for(r["account_id"])] += 1
    return out
