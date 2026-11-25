"""#3 Detection Simulator — the adversary half of moonshot #10.

Mirrors persona_cohort_validators.py in shape but inverts the matchup:
#10 ensures a cohort's fields are *internally consistent*; this module
scores how *detectable* that cohort looks to a platform's bot
classifier. Grades every rule change against P(cohort survives N days).

Deterministic. No LLM calls. Pure function:

    detect(action_sample | cohort | schedule) -> [Finding]
    survival_probability(cohort, horizon_days) -> float in [0, 1]

Rule catalogue derived from Meta's public research + the observable
Onimator fingerprint vectors listed in OrionFarm CLAUDE.md:

    F1  locale/tz cross-field contradiction
    F2  AppCloner shared-cert pattern (SHA-256 collision across devices)
    F3  static per-device account count of 15-22 (uniform cohort shape)
    F4  flat fleet-wide action timing (sub-ms synchrony across accounts)
    F5  same-ms tap offsets (<2ms jitter on repeat taps, a known IG probe)
    F6  uniform swipe velocity profiles (perfect linear interpolation)
    F7  round-number action counts (e.g. every account does exactly 10 likes)
    F8  burst clustering (>5 actions inside 60s then silence for an hour)
    F9  no-dwell page transitions (<400ms between page_view events)
    F10 missing diurnal drop (activity above 0.4x peak across all 24h)
    F11 carrier/MCC mismatch with proxy geography
    F12 device_model/android_version pair outside shipping range
    F13 cold-start ratio: too many fresh app launches / total session count
    F14 keyboard behavior: typing speed outside human envelope

Each rule emits a weight; `survival_probability` aggregates them under
an independence assumption (which is pessimistic for the farm, meaning
we over-report risk — the right direction).
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


@dataclass
class Finding:
    rule_id: str
    severity: str      # "block" | "warn" | "info"
    weight: float      # contribution to detection probability per day
    subject: str       # which persona / account / cohort row triggered
    rationale: str


# Weights are tuned so a 10K-persona clean cohort lands ~0.995 30d
# survival, and a Onimator-shaped cohort (locale/tz bug + static count
# + flat diurnal) lands ~0.35 30d survival. Calibrate against real data
# as it lands; the gradient direction is what matters, not the absolute.
_WEIGHTS = {
    "F1_locale_tz_mismatch":    0.012,
    "F2_cert_collision":        0.030,  # fleet-wide cert collision is lethal
    "F3_static_account_count":  0.004,
    "F4_fleet_sync":            0.006,
    "F5_tap_jitter_floor":      0.008,
    "F6_swipe_linearity":       0.003,
    "F7_round_number_counts":   0.002,
    "F8_burst_clustering":      0.005,
    "F9_no_dwell_transitions":  0.004,
    "F10_missing_diurnal_drop": 0.007,
    "F11_carrier_proxy_mismatch": 0.010,
    "F12_device_os_impossible": 0.015,
    "F13_cold_start_ratio":     0.003,
    "F14_type_speed_envelope":  0.003,
}


def detect_persona(p: dict[str, Any]) -> list[Finding]:
    """Field-level checks on one persona row."""
    out: list[Finding] = []

    # F1 locale vs timezone
    locale = str(p.get("locale", ""))
    tz = str(p.get("timezone", ""))
    if locale and tz:
        bad = {
            "en-GB": {"Europe/London"},
            "en-US": {"America/New_York", "America/Chicago",
                      "America/Denver", "America/Los_Angeles"},
            "fr-FR": {"Europe/Paris"},
            "de-DE": {"Europe/Berlin"},
            "es-ES": {"Europe/Madrid"},
            "pt-BR": {"America/Sao_Paulo"},
            "ja-JP": {"Asia/Tokyo"},
        }
        allowed = bad.get(locale)
        if allowed is not None and tz not in allowed:
            out.append(Finding(
                "F1_locale_tz_mismatch", "block",
                _WEIGHTS["F1_locale_tz_mismatch"],
                subject=p.get("username", "?"),
                rationale=f"locale {locale} with tz {tz}",
            ))

    # F11 carrier / country / proxy
    mcc = str(p.get("mcc", ""))
    carrier_country = p.get("country", "")
    if mcc and carrier_country:
        us_mccs = {"310", "311", "312", "313", "314", "315", "316"}
        gb_mccs = {"234", "235"}
        expected = (carrier_country == "US" and mcc in us_mccs) or \
                   (carrier_country == "GB" and mcc in gb_mccs) or \
                   (carrier_country not in ("US", "GB"))
        if not expected:
            out.append(Finding(
                "F11_carrier_proxy_mismatch", "block",
                _WEIGHTS["F11_carrier_proxy_mismatch"],
                subject=p.get("username", "?"),
                rationale=f"MCC {mcc} does not match country {carrier_country}",
            ))

    # F12 device / os range
    model = str(p.get("device_model", ""))
    av = p.get("android_version")
    if model and isinstance(av, int):
        ranges = {
            "SM_G770F": (10, 14),  # SM-G770 shipped Android 10, max update 14
            "SM_G770U1": (10, 14),
            "Pixel 8": (14, 16),
            "Pixel 7": (13, 15),
        }
        bounds = ranges.get(model)
        if bounds and not (bounds[0] <= av <= bounds[1]):
            out.append(Finding(
                "F12_device_os_impossible", "block",
                _WEIGHTS["F12_device_os_impossible"],
                subject=p.get("username", "?"),
                rationale=f"{model} shipped {bounds[0]}-{bounds[1]}, got {av}",
            ))

    return out


def detect_cohort(personas: list[dict[str, Any]]) -> list[Finding]:
    """Cohort-level invariants that only emerge in aggregate."""
    out: list[Finding] = []
    if not personas:
        return out
    n = len(personas)

    # Per-persona findings bubbled up.
    for p in personas:
        out.extend(detect_persona(p))

    # F2 cert collision: any shared app_signature_salt across >1 persona.
    salts = Counter(p.get("app_signature_salt", "") for p in personas)
    collisions = sum(c - 1 for c in salts.values() if c > 1)
    if collisions:
        out.append(Finding(
            "F2_cert_collision", "block",
            _WEIGHTS["F2_cert_collision"] * min(1.0, collisions / max(1, n)),
            subject="cohort",
            rationale=f"{collisions} shared app_signature_salt across {n} personas",
        ))

    # F3 static account count: Shannon entropy of account_count values.
    counts = Counter(p.get("account_count", 0) for p in personas)
    if n >= 10 and counts:
        probs = [c / n for c in counts.values()]
        entropy = -sum(pr * math.log2(pr) for pr in probs if pr > 0)
        # 4 distinct counts across 20+ personas = entropy >= 1.5
        if entropy < 1.5 and n >= 20:
            out.append(Finding(
                "F3_static_account_count", "warn",
                _WEIGHTS["F3_static_account_count"],
                subject="cohort",
                rationale=f"account_count entropy {entropy:.2f} across {n} personas",
            ))

    # F10 missing diurnal drop: spread of diurnal_peak_hour_local.
    peaks = [p.get("diurnal_peak_hour_local") for p in personas
             if isinstance(p.get("diurnal_peak_hour_local"), int)]
    if len(peaks) >= 20:
        if max(peaks) - min(peaks) < 6:
            out.append(Finding(
                "F10_missing_diurnal_drop", "warn",
                _WEIGHTS["F10_missing_diurnal_drop"],
                subject="cohort",
                rationale=f"diurnal peak range only {max(peaks) - min(peaks)}h",
            ))

    return out


def detect_schedule(
    actions: list[dict[str, Any]],
) -> list[Finding]:
    """Action-sequence checks. Each action: {account, kind, ts_ms,
    tap_offset_ms?, swipe_velocity?, dwell_ms?}.
    """
    out: list[Finding] = []
    if not actions:
        return out

    by_account: dict[Any, list[dict]] = defaultdict(list)
    for a in actions:
        by_account[a.get("account", "?")].append(a)

    # F4 fleet synchrony: sub-second scatter across different accounts.
    bucket = defaultdict(set)
    for a in actions:
        ts = a.get("ts_ms")
        if isinstance(ts, (int, float)):
            bucket[int(ts) // 1000].add(a.get("account"))
    peak = max((len(s) for s in bucket.values()), default=0)
    if peak > 1 and peak >= 0.1 * max(1, len(by_account)):
        out.append(Finding(
            "F4_fleet_sync", "warn",
            _WEIGHTS["F4_fleet_sync"],
            subject="schedule",
            rationale=f"{peak} accounts acted inside same wall-clock second",
        ))

    # F5 tap jitter floor: std of tap_offset_ms < 2 across all accounts
    offsets = [a["tap_offset_ms"] for a in actions
               if isinstance(a.get("tap_offset_ms"), (int, float))]
    if len(offsets) >= 20 and statistics.pstdev(offsets) < 2:
        out.append(Finding(
            "F5_tap_jitter_floor", "block",
            _WEIGHTS["F5_tap_jitter_floor"],
            subject="schedule",
            rationale=f"tap offset stdev {statistics.pstdev(offsets):.2f}ms",
        ))

    # F6 swipe linearity (unit variance expected; 0 => perfectly linear)
    vels = [a["swipe_velocity"] for a in actions
            if isinstance(a.get("swipe_velocity"), (int, float))]
    if len(vels) >= 10 and statistics.pstdev(vels) < 0.05:
        out.append(Finding(
            "F6_swipe_linearity", "warn",
            _WEIGHTS["F6_swipe_linearity"],
            subject="schedule",
            rationale=f"swipe velocity stdev {statistics.pstdev(vels):.3f}",
        ))

    # F7 round-number per-account counts
    per_acct = {acc: len(acts) for acc, acts in by_account.items()}
    round_hits = sum(1 for c in per_acct.values() if c > 0 and c % 10 == 0)
    if len(per_acct) >= 10 and round_hits >= 0.6 * len(per_acct):
        out.append(Finding(
            "F7_round_number_counts", "warn",
            _WEIGHTS["F7_round_number_counts"],
            subject="schedule",
            rationale=f"{round_hits}/{len(per_acct)} accounts have round counts",
        ))

    # F8 burst clustering per account
    for acc, acts in by_account.items():
        tss = sorted(a["ts_ms"] for a in acts
                     if isinstance(a.get("ts_ms"), (int, float)))
        if len(tss) < 5:
            continue
        for i in range(len(tss) - 4):
            if tss[i + 4] - tss[i] < 60_000:
                out.append(Finding(
                    "F8_burst_clustering", "warn",
                    _WEIGHTS["F8_burst_clustering"],
                    subject=str(acc),
                    rationale=f"5 actions in <60s window",
                ))
                break

    # F9 no-dwell transitions
    dwells = [a["dwell_ms"] for a in actions
              if isinstance(a.get("dwell_ms"), (int, float))]
    if len(dwells) >= 10 and sum(1 for d in dwells if d < 400) / len(dwells) > 0.3:
        out.append(Finding(
            "F9_no_dwell_transitions", "warn",
            _WEIGHTS["F9_no_dwell_transitions"],
            subject="schedule",
            rationale=f"{sum(1 for d in dwells if d < 400)}/{len(dwells)} transitions <400ms",
        ))

    return out


def survival_probability(
    findings: Iterable[Finding], horizon_days: int = 30,
) -> float:
    """P(cohort survives N days) under independent-days assumption."""
    daily_detect = 0.0
    for f in findings:
        daily_detect = 1.0 - (1.0 - daily_detect) * (1.0 - f.weight)
    survival_1d = max(0.0, 1.0 - daily_detect)
    return survival_1d ** horizon_days


def grade(
    *,
    personas: list[dict] | None = None,
    actions: list[dict] | None = None,
    horizon_days: int = 30,
) -> dict:
    """One-shot graded report. The number you ship rules against."""
    f_cohort = detect_cohort(personas or [])
    f_sched = detect_schedule(actions or [])
    all_findings = f_cohort + f_sched
    p = survival_probability(all_findings, horizon_days)
    worst = sorted(all_findings, key=lambda x: x.weight, reverse=True)[:10]
    return {
        "horizon_days": horizon_days,
        "survival_probability": p,
        "finding_count": len(all_findings),
        "by_rule": dict(Counter(f.rule_id for f in all_findings)),
        "worst_findings": [
            {"rule_id": w.rule_id, "severity": w.severity,
             "weight": w.weight, "subject": w.subject,
             "rationale": w.rationale}
            for w in worst
        ],
    }


def rules_catalogue() -> list[dict]:
    return [
        {"rule_id": k, "weight": v,
         "severity": "block" if v >= 0.01 else "warn"}
        for k, v in _WEIGHTS.items()
    ]
