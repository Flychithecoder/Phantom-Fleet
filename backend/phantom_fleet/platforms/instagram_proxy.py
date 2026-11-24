"""
Instagram proxy pinning + rotation discipline.

The fleet-scale rule is simple: every active IG account is pinned to one
proxy. A proxy that is active on more than one account at a time is a
fleet-doxx — if IG correlates two accounts to the same egress IP in the
same hour, it learns they're the same operator. Cross-account reuse must
never happen on hot accounts; cold / retired reuse can be tolerated but
is still logged.

Rotation discipline:
    * each pin expires after a per-account TTL (default 72h)
    * rotation picks the least-recently-used proxy from the pool, scoped
      to the account's declared country (CLAUDE.md cross-field
      consistency — proxy country must match the persona timezone)
    * rotation is denied when a candidate was used by another LIVE
      account within the quarantine window (default 24h)
    * every pin, rotate, deny is written to an audit ring the UI polls

Nothing here uses `random.*`. Selection is deterministic: least-recently-
used, then smallest hash tiebreak.
"""
from __future__ import annotations

import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
from typing import Callable, Optional

from . import instagram_identity as ig_id

log = logging.getLogger("phantom_fleet.platforms.instagram_proxy")

_PIN_TTL_HOURS            = 72
_REUSE_QUARANTINE_HOURS   = 24
_HOT_STATUSES             = ("active", "warming")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class ProxyPin:
    account_id:   str
    proxy_id:     str
    country:      str
    pinned_at:    str
    expires_at:   str
    rotations:    int = 0
    source:       str = "auto"   # "auto" | "manual"


@dataclass
class ProxyUsage:
    proxy_id:     str
    last_account: Optional[str] = None
    last_used_at: Optional[str] = None
    total_uses:   int = 0


@dataclass
class ProxyEvent:
    ts:         str
    kind:       str                # "pin" | "rotate" | "deny" | "release"
    account_id: str
    proxy_id:   str
    reason:     str = ""


@dataclass
class ProxyStats:
    pool_size:        int = 0
    pinned:           int = 0
    expired:          int = 0
    rotated_total:    int = 0
    denied_total:     int = 0
    cross_reuse_live: int = 0
    last_tick_at:     Optional[str] = None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class InstagramProxyScheduler:
    """
    Keeps the per-account proxy pin fresh, enforces cross-account reuse
    quarantine, and raises the `cross_reuse_live` alarm if two LIVE
    accounts end up on the same proxy inside the quarantine window.

    Pool shape: every proxy row is a dict {proxy_id, country, label?}.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
        proxy_pool_getter:     Callable[[], list[dict]],
        pin_ttl_hours:         int = _PIN_TTL_HOURS,
        quarantine_hours:      int = _REUSE_QUARANTINE_HOURS,
    ):
        self._accounts = accounts_store_getter
        self._pool     = proxy_pool_getter
        self.pin_ttl_hours    = pin_ttl_hours
        self.quarantine_hours = quarantine_hours
        self._pins:   dict[str, ProxyPin]   = {}
        self._usage:  dict[str, ProxyUsage] = {}
        self._events: deque[ProxyEvent]     = deque(maxlen=400)
        self.stats = ProxyStats()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(_tz.utc)

    def _ig_accounts(self) -> list[dict]:
        return [r for r in self._accounts().values()
                if r.get("platform") == "instagram"]

    def _country_for(self, row: dict) -> str:
        c = row.get("proxy_country")
        if c:
            return str(c).upper()
        tz = row.get("timezone")
        if tz and tz in ig_id.TZ_COUNTRY:
            return ig_id.TZ_COUNTRY[tz]
        return "US"

    def _usage_for(self, proxy_id: str) -> ProxyUsage:
        u = self._usage.get(proxy_id)
        if u is None:
            u = ProxyUsage(proxy_id=proxy_id)
            self._usage[proxy_id] = u
        return u

    def _candidates_for_country(self, country: str) -> list[dict]:
        return [p for p in self._pool() if str(p.get("country", "")).upper() == country]

    def _is_live(self, account_id: str) -> bool:
        row = self._accounts().get(account_id, {})
        return row.get("status") in _HOT_STATUSES

    def _is_quarantined(self, proxy_id: str, except_account: str) -> Optional[str]:
        """Return the account that would make reusing proxy_id a doxx, if any."""
        u = self._usage.get(proxy_id)
        if u is None or u.last_used_at is None:
            return None
        if u.last_account == except_account:
            return None
        last = datetime.fromisoformat(u.last_used_at)
        if self._now() - last > timedelta(hours=self.quarantine_hours):
            return None
        if u.last_account and self._is_live(u.last_account):
            return u.last_account
        return None

    def _pick_proxy(self, account_id: str, country: str) -> Optional[dict]:
        """Least-recently-used proxy in the country scope, skipping quarantined."""
        candidates = self._candidates_for_country(country)
        if not candidates:
            return None

        def sort_key(p: dict) -> tuple:
            u = self._usage.get(p["proxy_id"])
            last = u.last_used_at if u and u.last_used_at else "0"
            hv = int(hashlib.sha256(
                f"{account_id}:{p['proxy_id']}".encode()).hexdigest()[:8], 16)
            return (last, hv)

        for proxy in sorted(candidates, key=sort_key):
            if self._is_quarantined(proxy["proxy_id"], account_id) is None:
                return proxy
        return None

    def _log_event(self, kind: str, account_id: str, proxy_id: str,
                   reason: str = "") -> None:
        self._events.append(ProxyEvent(
            ts=self._now().isoformat(),
            kind=kind, account_id=account_id,
            proxy_id=proxy_id, reason=reason,
        ))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(self) -> dict:
        """One sweep: expire stale pins, pin un-pinned accounts, detect reuse."""
        now = self._now()
        expired_total = 0
        for acc_id, pin in list(self._pins.items()):
            exp = datetime.fromisoformat(pin.expires_at)
            if now >= exp:
                self._log_event("release", acc_id, pin.proxy_id, "ttl_expired")
                del self._pins[acc_id]
                expired_total += 1

        for row in self._ig_accounts():
            if row.get("status") not in _HOT_STATUSES:
                continue
            if row["account_id"] in self._pins:
                continue
            self._pin_account(row)

        # Reuse detector — walk pins, group by proxy, flag any proxy held by
        # two live accounts.
        by_proxy: dict[str, list[str]] = {}
        for acc_id, pin in self._pins.items():
            if self._is_live(acc_id):
                by_proxy.setdefault(pin.proxy_id, []).append(acc_id)
        cross = sum(1 for aids in by_proxy.values() if len(aids) > 1)

        self.stats.pool_size = len(self._pool())
        self.stats.pinned    = len(self._pins)
        self.stats.expired  += expired_total
        self.stats.cross_reuse_live = cross
        self.stats.last_tick_at = now.isoformat()
        return {
            "pinned":              self.stats.pinned,
            "expired_this_tick":   expired_total,
            "cross_reuse_live":    cross,
        }

    def _pin_account(self, row: dict, *, manual_proxy_id: Optional[str] = None,
                      source: str = "auto") -> Optional[ProxyPin]:
        now = self._now()
        country = self._country_for(row)
        if manual_proxy_id is not None:
            proxy = next((p for p in self._pool()
                          if p.get("proxy_id") == manual_proxy_id), None)
            if proxy is None:
                self._log_event("deny", row["account_id"], manual_proxy_id,
                                "proxy not in pool")
                self.stats.denied_total += 1
                return None
            blocker = self._is_quarantined(manual_proxy_id, row["account_id"])
            if blocker is not None:
                self._log_event("deny", row["account_id"], manual_proxy_id,
                                f"quarantined: still used by live {blocker}")
                self.stats.denied_total += 1
                return None
        else:
            proxy = self._pick_proxy(row["account_id"], country)
            if proxy is None:
                self._log_event("deny", row["account_id"], "",
                                f"no candidate for country {country}")
                self.stats.denied_total += 1
                return None

        pin = ProxyPin(
            account_id=row["account_id"],
            proxy_id=proxy["proxy_id"],
            country=country,
            pinned_at=now.isoformat(),
            expires_at=(now + timedelta(hours=self.pin_ttl_hours)).isoformat(),
            source=source,
        )
        self._pins[row["account_id"]] = pin
        u = self._usage_for(proxy["proxy_id"])
        u.last_account = row["account_id"]
        u.last_used_at = now.isoformat()
        u.total_uses += 1
        self._log_event("pin", row["account_id"], proxy["proxy_id"],
                        f"country={country} source={source}")
        return pin

    def rotate(self, account_id: str) -> Optional[ProxyPin]:
        row = self._accounts().get(account_id)
        if row is None:
            return None
        current = self._pins.get(account_id)
        self._pins.pop(account_id, None)
        pin = self._pin_account(row)
        if pin is None:
            # Restore the previous pin on rotation failure so the account
            # isn't left unpinned.
            if current is not None:
                self._pins[account_id] = current
            return None
        pin.rotations = (current.rotations + 1) if current else 1
        self.stats.rotated_total += 1
        self._log_event("rotate", account_id, pin.proxy_id,
                        f"from {current.proxy_id if current else '-'}")
        return pin

    def pin_manual(self, account_id: str, proxy_id: str) -> Optional[ProxyPin]:
        row = self._accounts().get(account_id)
        if row is None:
            return None
        self._pins.pop(account_id, None)
        return self._pin_account(row, manual_proxy_id=proxy_id, source="manual")

    def release(self, account_id: str) -> bool:
        pin = self._pins.pop(account_id, None)
        if pin is None:
            return False
        self._log_event("release", account_id, pin.proxy_id, "manual")
        return True

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def pin_for(self, account_id: str) -> Optional[ProxyPin]:
        return self._pins.get(account_id)

    def summary(self) -> dict:
        now = self._now()
        by_proxy: dict[str, list[str]] = {}
        for acc_id, pin in self._pins.items():
            by_proxy.setdefault(pin.proxy_id, []).append(acc_id)
        hot_reuses = []
        for pid, aids in by_proxy.items():
            live = [a for a in aids if self._is_live(a)]
            if len(live) > 1:
                hot_reuses.append({"proxy_id": pid, "accounts": live})

        by_country: dict[str, int] = {}
        for pin in self._pins.values():
            by_country[pin.country] = by_country.get(pin.country, 0) + 1

        pool_country: dict[str, int] = {}
        for p in self._pool():
            c = str(p.get("country", "")).upper() or "??"
            pool_country[c] = pool_country.get(c, 0) + 1

        unpinned_live = [r["account_id"] for r in self._ig_accounts()
                         if r.get("status") in _HOT_STATUSES
                         and r["account_id"] not in self._pins]

        return {
            "stats": {
                "pool_size":        len(self._pool()),
                "pinned":           len(self._pins),
                "rotated_total":    self.stats.rotated_total,
                "denied_total":     self.stats.denied_total,
                "cross_reuse_live": self.stats.cross_reuse_live,
                "last_tick_at":     self.stats.last_tick_at,
                "pin_ttl_hours":    self.pin_ttl_hours,
                "quarantine_hours": self.quarantine_hours,
            },
            "pool_country":     pool_country,
            "pinned_country":   by_country,
            "hot_reuses":       hot_reuses,
            "unpinned_live":    unpinned_live[:20],
            "pins":             [{
                "account_id": p.account_id, "proxy_id": p.proxy_id,
                "country": p.country, "pinned_at": p.pinned_at,
                "expires_at": p.expires_at, "rotations": p.rotations,
                "source": p.source,
            } for p in self._pins.values()][:60],
        }

    def recent_events(self, limit: int = 30) -> list[dict]:
        rows = list(reversed(self._events))[:limit]
        return [{
            "ts": e.ts, "kind": e.kind, "account_id": e.account_id,
            "proxy_id": e.proxy_id, "reason": e.reason,
        } for e in rows]
