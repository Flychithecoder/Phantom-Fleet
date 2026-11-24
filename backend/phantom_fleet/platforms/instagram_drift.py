"""
Instagram device-drift detector — catches when a phone's claimed identity
shifts mid-session.

The invariant: once a phone has declared a device_model, os_version,
locale, timezone, carrier, hni, signing_cert, build_tag — those fields
MUST stay stable across every IG account bound to that phone. A drift
means one of three things, and all three are worth paging an operator:

    (a) persona-factory bug: a dimension got re-rolled after pinning
    (b) real identity shift: the phone was flashed, re-rooted, or had a
        SIM swap; the account map on it is now compromised
    (c) adversarial detection event: IG's integrity sweep forced a
        patch-bump or locale re-prompt and the clone didn't adapt

We snapshot a baseline the first time a phone is seen, then compare the
current row's identity fields on every scan. A dimension that disagrees
with the baseline for `_TRIP_STREAK` scans in a row trips a DriftEvent.
Hysteresis keeps a single flaky reading from firing.

Dimensions have three severity tiers:
    fail: device_model, signing_cert, locale  (hardware/APK/locale pin)
    warn: os_version, timezone, carrier, hni, build_tag
    info: everything else (logged, no gate)

Nothing random. Baselines are keyed by phone_serial; the audit harness
builds a synthetic baseline + drift and verifies the trip streak fires.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
from typing import Callable, Optional

log = logging.getLogger("phantom_fleet.platforms.instagram_drift")

_TRIP_STREAK = 2
_SEVERITY: dict[str, str] = {
    "device_model":  "fail",
    "signing_cert":  "fail",
    "locale":        "fail",
    "os_version":    "warn",
    "timezone":      "warn",
    "carrier":       "warn",
    "hni":           "warn",
    "build_tag":     "warn",
    "proxy_country": "warn",
    "package":       "fail",
}
_DIMENSIONS: tuple[str, ...] = tuple(_SEVERITY.keys())


def _get(row: dict, key: str) -> Optional[str]:
    for container in (row, row.get("device_profile") or {}, row.get("persona") or {}):
        v = container.get(key)
        if v not in (None, ""):
            return str(v)
    return None


def _fingerprint_of(row: dict) -> dict[str, Optional[str]]:
    return {d: _get(row, d) for d in _DIMENSIONS}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class DeviceBaseline:
    phone_serial: str
    snapshot:     dict[str, Optional[str]]
    first_seen:   str
    last_scan_at: Optional[str] = None


@dataclass
class DriftEvent:
    phone_serial: str
    dimension:    str
    baseline:     Optional[str]
    current:      Optional[str]
    severity:     str
    streak:       int
    tripped_at:   str

    def as_dict(self) -> dict:
        return {
            "phone_serial": self.phone_serial,
            "dimension":    self.dimension,
            "baseline":     self.baseline,
            "current":      self.current,
            "severity":     self.severity,
            "streak":       self.streak,
            "tripped_at":   self.tripped_at,
        }


@dataclass
class DriftStats:
    total_phones:   int = 0
    stable:         int = 0
    drifting:       int = 0
    tripped:        int = 0
    total_scans:    int = 0
    last_scan_at:   Optional[str] = None
    tripped_counts: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class InstagramDriftDetector:
    """
    Per-phone fingerprint-drift tracker. Hysteretic: a dimension must
    disagree with the baseline for _TRIP_STREAK consecutive scans before
    it trips. A trip stays reported until the dimension clears.

    Phones are discovered by walking the accounts store. Baselines are
    captured on first observation or via `snapshot(phone_serial)`.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
    ):
        self._accounts = accounts_store_getter
        self._baselines: dict[str, DeviceBaseline] = {}
        # phone_serial → dimension → consecutive-drift streak
        self._streaks:  dict[str, dict[str, int]] = defaultdict(dict)
        # phone_serial → dimension → DriftEvent (currently-tripped)
        self._tripped:  dict[str, dict[str, DriftEvent]] = defaultdict(dict)
        self._events:   deque[DriftEvent] = deque(maxlen=400)
        self.stats = DriftStats()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rows_by_phone(self) -> dict[str, dict]:
        """Representative row per phone — any IG row on that phone will do."""
        out: dict[str, dict] = {}
        for r in self._accounts().values():
            if r.get("platform") != "instagram":
                continue
            serial = r.get("phone_serial") or r.get("account_id")
            if serial not in out:
                out[serial] = r
        return out

    def _ensure_baseline(self, serial: str, row: dict) -> DeviceBaseline:
        bl = self._baselines.get(serial)
        if bl is None:
            bl = DeviceBaseline(
                phone_serial=serial,
                snapshot=_fingerprint_of(row),
                first_seen=datetime.now(_tz.utc).isoformat(),
            )
            self._baselines[serial] = bl
        return bl

    def _record_trip(self, serial: str, dim: str,
                     baseline_val: Optional[str],
                     current_val: Optional[str],
                     streak: int) -> DriftEvent:
        evt = DriftEvent(
            phone_serial=serial, dimension=dim,
            baseline=baseline_val, current=current_val,
            severity=_SEVERITY.get(dim, "info"),
            streak=streak,
            tripped_at=datetime.now(_tz.utc).isoformat(),
        )
        self._tripped[serial][dim] = evt
        self._events.append(evt)
        return evt

    def _clear_trip(self, serial: str, dim: str) -> None:
        self._tripped.get(serial, {}).pop(dim, None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_all(self) -> list[DriftEvent]:
        """One sweep over every phone. Returns newly-tripped events only."""
        new_events: list[DriftEvent] = []
        now = datetime.now(_tz.utc).isoformat()
        phones = self._rows_by_phone()

        # Clean up baselines for phones no longer present.
        for gone in set(self._baselines) - set(phones):
            self._baselines.pop(gone, None)
            self._streaks.pop(gone, None)
            self._tripped.pop(gone, None)

        for serial, row in phones.items():
            baseline = self._ensure_baseline(serial, row)
            baseline.last_scan_at = now
            current = _fingerprint_of(row)
            phone_streaks = self._streaks[serial]

            for dim in _DIMENSIONS:
                bl_val = baseline.snapshot.get(dim)
                cur_val = current.get(dim)
                # Only count as drift when the baseline actually has a value
                # and the current value differs. Missing-on-both is no drift.
                if bl_val is not None and cur_val is not None and bl_val != cur_val:
                    streak = phone_streaks.get(dim, 0) + 1
                    phone_streaks[dim] = streak
                    if streak >= _TRIP_STREAK and dim not in self._tripped[serial]:
                        evt = self._record_trip(serial, dim, bl_val, cur_val, streak)
                        new_events.append(evt)
                else:
                    if phone_streaks.get(dim, 0) > 0 and dim in self._tripped.get(serial, {}):
                        self._clear_trip(serial, dim)
                    phone_streaks[dim] = 0

        # Stats
        tripped_counts: dict[str, int] = {}
        drifting_phones = 0
        tripped_phones  = 0
        for serial in phones:
            trips = self._tripped.get(serial, {})
            if trips:
                tripped_phones += 1
                for dim in trips:
                    tripped_counts[dim] = tripped_counts.get(dim, 0) + 1
            elif any(v > 0 for v in self._streaks.get(serial, {}).values()):
                drifting_phones += 1

        self.stats.total_phones   = len(phones)
        self.stats.stable         = len(phones) - drifting_phones - tripped_phones
        self.stats.drifting       = drifting_phones
        self.stats.tripped        = tripped_phones
        self.stats.total_scans   += 1
        self.stats.last_scan_at   = now
        self.stats.tripped_counts = tripped_counts
        return new_events

    def snapshot(self, phone_serial: str) -> Optional[DeviceBaseline]:
        """Recapture the baseline for one phone (operator-initiated)."""
        row = next((r for r in self._accounts().values()
                    if (r.get("phone_serial") or r.get("account_id")) == phone_serial
                    and r.get("platform") == "instagram"), None)
        if row is None:
            return None
        self._baselines[phone_serial] = DeviceBaseline(
            phone_serial=phone_serial,
            snapshot=_fingerprint_of(row),
            first_seen=datetime.now(_tz.utc).isoformat(),
        )
        self._streaks.pop(phone_serial, None)
        self._tripped.pop(phone_serial, None)
        return self._baselines[phone_serial]

    def for_phone(self, phone_serial: str) -> Optional[dict]:
        bl = self._baselines.get(phone_serial)
        if bl is None:
            return None
        return {
            "phone_serial": phone_serial,
            "first_seen":   bl.first_seen,
            "last_scan_at": bl.last_scan_at,
            "baseline":     bl.snapshot,
            "streaks":      dict(self._streaks.get(phone_serial, {})),
            "tripped":      [e.as_dict() for e in
                             self._tripped.get(phone_serial, {}).values()],
        }

    def summary(self) -> dict:
        tripped_rows: list[dict] = []
        for serial, trips in self._tripped.items():
            for evt in trips.values():
                tripped_rows.append(evt.as_dict())
        # Sort fail > warn > info, then by streak desc.
        sev_rank = {"fail": 0, "warn": 1, "info": 2}
        tripped_rows.sort(key=lambda r: (sev_rank.get(r["severity"], 3), -r["streak"]))
        return {
            "stats": {
                "total_phones":   self.stats.total_phones,
                "stable":         self.stats.stable,
                "drifting":       self.stats.drifting,
                "tripped":        self.stats.tripped,
                "total_scans":    self.stats.total_scans,
                "last_scan_at":   self.stats.last_scan_at,
                "trip_streak":    _TRIP_STREAK,
            },
            "tripped_counts": self.stats.tripped_counts,
            "tripped":        tripped_rows[:40],
            "events":         [e.as_dict() for e in reversed(self._events)][:20],
        }
