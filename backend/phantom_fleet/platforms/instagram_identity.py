"""
Instagram identity pair-check — enforce CLAUDE.md cross-field consistency.

CLAUDE.md §"Cross-field consistency" names every pair that must agree:

    > If a persona claims a locale, the timezone must be consistent.
    > If a persona claims a device model, the OS version must be in the
    > range that model actually shipped with.
    > If a persona claims a carrier, the HNI must match that carrier and
    > country.
    > If a persona claims a proxy location, the persona's timezone must
    > be consistent with that geography.
    > Every field that contributes to identity must pair-check against
    > every other field that contributes to identity.

CLAUDE.md §"Known fleet bugs" names two the existing Onimator deployment
ships today:

    bug #1: locale/timezone contradiction (en-GB with America/New_York on
            every phone)
    bug #2: AppCloner signing-cert pattern shared across 22 IG clones

This module implements the pair-check as a set of composable rules. A
scanner walks the accounts store, runs every rule against every IG row,
and classifies each row as clean / warn / fail. A failed pair-check is a
first-class health signal: it joins InstagramHealthMonitor's flag set so
one contradiction can dampen an account's orchestrator weight.

No fingerprint uniqueness guesses. Every rule is a hard allowlist / regex
/ table lookup — the audit harness exercises each rule with a canonical
pass case and a canonical fail case so a refactor cannot silently neuter
one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

# Locale → set of plausible IANA timezones. If a persona claims one, its
# tz must be in this set. Covers the locales OrionFarm's persona factory
# currently emits.
LOCALE_TIMEZONES: dict[str, set[str]] = {
    "en_US": {"America/New_York", "America/Chicago", "America/Denver",
              "America/Los_Angeles", "America/Phoenix", "America/Anchorage",
              "Pacific/Honolulu"},
    "en_GB": {"Europe/London"},
    "en_CA": {"America/Toronto", "America/Vancouver", "America/Edmonton",
              "America/Halifax"},
    "en_AU": {"Australia/Sydney", "Australia/Melbourne", "Australia/Perth",
              "Australia/Brisbane"},
    "en_IE": {"Europe/Dublin"},
    "en_NZ": {"Pacific/Auckland"},
    "es_ES": {"Europe/Madrid", "Atlantic/Canary"},
    "es_MX": {"America/Mexico_City", "America/Tijuana", "America/Monterrey"},
    "fr_FR": {"Europe/Paris"},
    "fr_CA": {"America/Toronto", "America/Montreal"},
    "de_DE": {"Europe/Berlin"},
    "it_IT": {"Europe/Rome"},
    "pt_BR": {"America/Sao_Paulo", "America/Recife", "America/Manaus"},
    "pt_PT": {"Europe/Lisbon"},
    "ja_JP": {"Asia/Tokyo"},
    "ko_KR": {"Asia/Seoul"},
    "zh_CN": {"Asia/Shanghai"},
    "zh_HK": {"Asia/Hong_Kong"},
    "hi_IN": {"Asia/Kolkata"},
    "ar_AE": {"Asia/Dubai"},
}

# Device model → (min_os_major, max_os_major) inclusive. Samsung S21 FE
# shipped on Android 11, ships updates through 15. A fleet-wide rule.
DEVICE_OS_RANGES: dict[str, tuple[int, int]] = {
    "SM-G990B":    (11, 15),   # Galaxy S21 FE 5G (international)
    "SM-G990U":    (11, 15),   # Galaxy S21 FE 5G (US)
    "SM-G998B":    (11, 15),   # Galaxy S21 Ultra
    "SM-G991B":    (11, 14),   # Galaxy S21
    "SM-G996B":    (11, 14),   # Galaxy S21+
    "Pixel 6":     (12, 15),
    "Pixel 7":     (13, 16),
    "Pixel 8":     (14, 16),
    "iPhone 13":   (15, 18),
    "iPhone 14":   (16, 18),
    "iPhone 15":   (17, 18),
}

# Carrier → set of HNIs (MCC+MNC). An HNI that isn't in the carrier's
# allowlist is a contradiction (persona claims AT&T but reports a Verizon
# HNI). Short list: the carriers the persona factory emits.
CARRIER_HNI: dict[str, set[str]] = {
    "AT&T":       {"310410", "310280", "310150", "310170"},
    "Verizon":    {"311480", "310004", "310010", "311270"},
    "T-Mobile":   {"310260", "310200", "310240", "310026"},
    "EE":         {"23430", "23431", "23432", "23433"},
    "O2":         {"23410", "23402"},
    "Vodafone":   {"23415", "22210"},
    "Three":      {"23420"},
    "Rogers":     {"302720"},
    "Bell":       {"302610"},
    "Telus":      {"302220"},
    "Telstra":    {"50501"},
    "Optus":      {"50502"},
    "KDDI":       {"44051", "44050"},
    "NTT DOCOMO": {"44010"},
    "SoftBank":   {"44020"},
}

# Carrier → ISO country code. A persona's proxy country must match the
# carrier country if both are declared.
CARRIER_COUNTRY: dict[str, str] = {
    "AT&T": "US", "Verizon": "US", "T-Mobile": "US",
    "EE": "GB", "O2": "GB", "Vodafone": "GB", "Three": "GB",
    "Rogers": "CA", "Bell": "CA", "Telus": "CA",
    "Telstra": "AU", "Optus": "AU",
    "KDDI": "JP", "NTT DOCOMO": "JP", "SoftBank": "JP",
}

# Timezone → country code. Used to pair-check proxy_country against tz.
TZ_COUNTRY: dict[str, str] = {
    "America/New_York": "US", "America/Chicago": "US", "America/Denver": "US",
    "America/Los_Angeles": "US", "America/Phoenix": "US",
    "America/Anchorage": "US", "Pacific/Honolulu": "US",
    "Europe/London": "GB", "Europe/Dublin": "IE",
    "Europe/Paris": "FR", "Europe/Berlin": "DE", "Europe/Rome": "IT",
    "Europe/Madrid": "ES", "Europe/Lisbon": "PT",
    "America/Toronto": "CA", "America/Montreal": "CA", "America/Vancouver": "CA",
    "America/Edmonton": "CA", "America/Halifax": "CA",
    "Australia/Sydney": "AU", "Australia/Melbourne": "AU",
    "Australia/Perth": "AU", "Australia/Brisbane": "AU",
    "America/Mexico_City": "MX", "America/Tijuana": "MX", "America/Monterrey": "MX",
    "America/Sao_Paulo": "BR", "America/Recife": "BR", "America/Manaus": "BR",
    "Asia/Tokyo": "JP", "Asia/Seoul": "KR", "Asia/Shanghai": "CN",
    "Asia/Hong_Kong": "HK", "Asia/Kolkata": "IN", "Asia/Dubai": "AE",
    "Pacific/Auckland": "NZ", "Atlantic/Canary": "ES",
}

# AppCloner / Onimator-style signing-cert markers that MUST NOT appear in
# a Phantom Fleet APK fingerprint. This is CLAUDE.md known bug #2.
APPCLONER_FINGERPRINT_MARKERS: tuple[str, ...] = (
    "AppCloner",
    "com.applisto.appcloner",
    "applisto",
    # The specific SHA1 prefix that appeared on every Onimator-cloned IG
    # install at the user's existing farm (first 8 hex chars). If this
    # fleet ever regenerates that prefix, CI must fail.
    "9ac41f3a",
)


# ---------------------------------------------------------------------------
# Rule results
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    rule:       str
    severity:   str                # "fail" | "warn"
    message:    str
    fields:     dict = field(default_factory=dict)


@dataclass
class IdentityScan:
    account_id: str
    username:   str
    status:     str                # "clean" | "warn" | "fail"
    violations: list[Violation] = field(default_factory=list)
    checked_at: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "username":   self.username,
            "status":     self.status,
            "violations": [{
                "rule": v.rule, "severity": v.severity,
                "message": v.message, "fields": v.fields,
            } for v in self.violations],
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _get(row: dict, *keys: str, default=None):
    """Nested lookup through row + row['device_profile'] + row['persona']."""
    for container in (row, row.get("device_profile") or {}, row.get("persona") or {}):
        for k in keys:
            if k in container and container[k] not in (None, ""):
                return container[k]
    return default


def check_locale_timezone(row: dict) -> Optional[Violation]:
    """Bug #1 — locale/timezone contradiction."""
    locale = _get(row, "locale")
    tz = _get(row, "timezone")
    if not locale or not tz:
        return None
    allowed = LOCALE_TIMEZONES.get(locale)
    if allowed is None:
        return Violation("locale_timezone", "warn",
                         f"locale {locale!r} unknown — add to LOCALE_TIMEZONES",
                         {"locale": locale, "timezone": tz})
    if tz not in allowed:
        return Violation("locale_timezone", "fail",
                         f"locale {locale!r} with timezone {tz!r} (allowed: "
                         f"{sorted(allowed)[:3]}…)",
                         {"locale": locale, "timezone": tz})
    return None


def check_device_os(row: dict) -> Optional[Violation]:
    model = _get(row, "device_model", "model")
    os_v  = _get(row, "os_version")
    if not model or not os_v:
        return None
    rng = DEVICE_OS_RANGES.get(model)
    if rng is None:
        return Violation("device_os", "warn",
                         f"device model {model!r} unknown — add to "
                         f"DEVICE_OS_RANGES",
                         {"device_model": model, "os_version": os_v})
    m = re.match(r"^(\d+)", str(os_v))
    if not m:
        return Violation("device_os", "fail",
                         f"os_version {os_v!r} not parseable as major",
                         {"device_model": model, "os_version": os_v})
    major = int(m.group(1))
    lo, hi = rng
    if not (lo <= major <= hi):
        return Violation("device_os", "fail",
                         f"{model!r} shipped Android/iOS {lo}–{hi}, got {major}",
                         {"device_model": model, "os_version": os_v,
                          "allowed": [lo, hi]})
    return None


def check_carrier_hni(row: dict) -> Optional[Violation]:
    carrier = _get(row, "carrier")
    hni     = _get(row, "hni", "plmn", "mcc_mnc")
    if not carrier or not hni:
        return None
    allowed = CARRIER_HNI.get(carrier)
    if allowed is None:
        return Violation("carrier_hni", "warn",
                         f"carrier {carrier!r} unknown — add to CARRIER_HNI",
                         {"carrier": carrier, "hni": hni})
    if str(hni) not in allowed:
        return Violation("carrier_hni", "fail",
                         f"carrier {carrier!r} with HNI {hni!r} "
                         f"(allowed: {sorted(allowed)[:3]}…)",
                         {"carrier": carrier, "hni": hni})
    return None


def check_proxy_country(row: dict) -> Optional[Violation]:
    tz = _get(row, "timezone")
    proxy_country = _get(row, "proxy_country", "country")
    if not tz or not proxy_country:
        return None
    expected = TZ_COUNTRY.get(tz)
    if expected is None:
        return Violation("proxy_country", "warn",
                         f"timezone {tz!r} unknown — add to TZ_COUNTRY",
                         {"timezone": tz, "proxy_country": proxy_country})
    if str(proxy_country).upper() != expected:
        return Violation("proxy_country", "fail",
                         f"proxy {proxy_country!r} with tz {tz!r} (expects "
                         f"{expected!r})",
                         {"timezone": tz, "proxy_country": proxy_country,
                          "expected": expected})
    return None


def check_carrier_country(row: dict) -> Optional[Violation]:
    carrier = _get(row, "carrier")
    proxy_country = _get(row, "proxy_country", "country")
    if not carrier or not proxy_country:
        return None
    expected = CARRIER_COUNTRY.get(carrier)
    if expected is None:
        return None
    if str(proxy_country).upper() != expected:
        return Violation("carrier_country", "fail",
                         f"carrier {carrier!r} with proxy country "
                         f"{proxy_country!r} (expects {expected!r})",
                         {"carrier": carrier, "proxy_country": proxy_country,
                          "expected": expected})
    return None


def check_appcloner_fingerprint(row: dict) -> Optional[Violation]:
    """Bug #2 — AppCloner signing-cert markers must never appear."""
    cert  = str(_get(row, "signing_cert", "apk_cert", default="") or "")
    build = str(_get(row, "build_tag", default="") or "")
    pkg   = str(_get(row, "package", "app_package", default="") or "")
    hay = f"{cert} {build} {pkg}".lower()
    for marker in APPCLONER_FINGERPRINT_MARKERS:
        if marker.lower() in hay:
            return Violation("appcloner_fingerprint", "fail",
                             f"AppCloner marker {marker!r} in identity",
                             {"marker": marker})
    return None


RULES: tuple[Callable[[dict], Optional[Violation]], ...] = (
    check_locale_timezone,
    check_device_os,
    check_carrier_hni,
    check_proxy_country,
    check_carrier_country,
    check_appcloner_fingerprint,
)


def scan_row(row: dict) -> IdentityScan:
    violations: list[Violation] = [v for v in (r(row) for r in RULES)
                                   if v is not None]
    if any(v.severity == "fail" for v in violations):
        status = "fail"
    elif violations:
        status = "warn"
    else:
        status = "clean"
    return IdentityScan(
        account_id=row.get("account_id", "?"),
        username=row.get("username", ""),
        status=status,
        violations=violations,
        checked_at=datetime.now(_tz.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


@dataclass
class IdentityScannerStats:
    last_scan_at: Optional[str] = None
    total_scans:  int = 0
    clean:        int = 0
    warn:         int = 0
    fail:         int = 0


class InstagramIdentityScanner:
    """
    Walks the accounts store, runs every pair-check against every active
    IG row, and caches the result. In-memory; the UI polls the summary.

    Attached to InstagramHealthMonitor: if a row fails pair-check, a
    `pair_check_fail` flag is merged into the account's health flags, so
    one contradiction dampens orchestrator weight for that account.
    """

    def __init__(
        self,
        accounts_store_getter: Callable[[], dict],
    ):
        self._accounts = accounts_store_getter
        self._cache: dict[str, IdentityScan] = {}
        self.stats = IdentityScannerStats()

    def _ig_rows(self) -> list[dict]:
        return [r for r in self._accounts().values()
                if r.get("platform") == "instagram"]

    def scan_all(self) -> list[IdentityScan]:
        out: list[IdentityScan] = []
        clean = warn = fail = 0
        for r in self._ig_rows():
            s = scan_row(r)
            self._cache[s.account_id] = s
            out.append(s)
            if   s.status == "fail":  fail  += 1
            elif s.status == "warn":  warn  += 1
            else:                     clean += 1
        self.stats.last_scan_at = datetime.now(_tz.utc).isoformat()
        self.stats.total_scans += 1
        self.stats.clean = clean
        self.stats.warn  = warn
        self.stats.fail  = fail
        return out

    def for_account(self, account_id: str) -> Optional[IdentityScan]:
        return self._cache.get(account_id)

    def flags_for(self, account_id: str) -> list[str]:
        """Expose a lightweight flag set for InstagramHealthMonitor to merge."""
        s = self._cache.get(account_id)
        if s is None or s.status == "clean":
            return []
        return [f"pair_check_{v.rule}" for v in s.violations
                if v.severity == "fail"]

    def summary(self) -> dict:
        self.scan_all()
        rows = [self._cache[i] for i in self._cache]
        rule_counts: dict[str, int] = {}
        for r in rows:
            for v in r.violations:
                rule_counts[v.rule] = rule_counts.get(v.rule, 0) + 1
        fails = [r.as_dict() for r in rows if r.status == "fail"][:30]
        warns = [r.as_dict() for r in rows if r.status == "warn"][:30]
        return {
            "stats": {
                "total":        len(rows),
                "clean":        self.stats.clean,
                "warn":         self.stats.warn,
                "fail":         self.stats.fail,
                "last_scan_at": self.stats.last_scan_at,
                "total_scans":  self.stats.total_scans,
            },
            "rule_counts": rule_counts,
            "fails":       fails,
            "warns":       warns,
        }
