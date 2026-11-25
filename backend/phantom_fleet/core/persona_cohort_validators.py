"""Persona pair-check validators — moonshot #10.

CLAUDE.md: "Every field that contributes to identity must pair-check
against every other field that contributes to identity."

A pair-check is an independent read of the generator's output. If the
generator drifts away from the reference tables, this catches it.
"""

from __future__ import annotations

from typing import Any

from .persona_cohort import (
    LOCALE_TIMEZONES,
    DEVICE_OS_RANGES,
    CARRIERS,
    LOCALE_COUNTRY,
)


def _v(ok: bool, code: str, detail: str) -> dict[str, Any] | None:
    return None if ok else {"code": code, "detail": detail}


def validate_persona(p: dict[str, Any]) -> dict[str, Any]:
    """Pair-check every identity field against every other. Returns
    {ok, violations[]}."""
    V: list[dict[str, Any]] = []

    locale = p.get("locale")
    timezone = p.get("timezone")
    country = p.get("country")
    device = p.get("device_model")
    android = p.get("android_version")
    carrier = p.get("carrier")
    mcc = p.get("mcc")
    mnc = p.get("mnc")
    hni = p.get("hni")

    # 1. locale <-> timezone
    lt = LOCALE_TIMEZONES.get(locale)
    if lt is None:
        V.append({"code": "locale_unknown", "detail": f"locale {locale!r} has no reference row"})
    elif timezone not in lt.items:
        V.append({"code": "locale_timezone_mismatch",
                  "detail": f"locale {locale} does not ship timezone {timezone}"})

    # 2. locale <-> country (locale implies a country)
    expected_country = LOCALE_COUNTRY.get(locale)
    if expected_country and country != expected_country:
        V.append({"code": "locale_country_mismatch",
                  "detail": f"locale {locale} implies country {expected_country}, got {country}"})

    # 3. device <-> android version
    rng = DEVICE_OS_RANGES.get(device)
    if rng is None:
        V.append({"code": "device_unknown", "detail": f"device {device!r} not in reference"})
    else:
        lo, hi = rng
        if not isinstance(android, int) or android < lo or android > hi:
            V.append({"code": "device_os_out_of_range",
                      "detail": f"{device} shipped Android {lo}-{hi}, got {android}"})

    # 4. carrier <-> country + MCC + MNC
    cmeta = CARRIERS.get(carrier)
    if cmeta is None:
        V.append({"code": "carrier_unknown", "detail": f"carrier {carrier!r} not in reference"})
    else:
        if cmeta["country"] != country:
            V.append({"code": "carrier_country_mismatch",
                      "detail": f"carrier {carrier} is {cmeta['country']}, persona country is {country}"})
        if cmeta["mcc"] != mcc:
            V.append({"code": "carrier_mcc_mismatch",
                      "detail": f"carrier {carrier} MCC is {cmeta['mcc']}, got {mcc}"})
        if mnc not in cmeta["mncs"]:
            V.append({"code": "carrier_mnc_mismatch",
                      "detail": f"carrier {carrier} MNCs are {cmeta['mncs']}, got {mnc}"})

    # 5. HNI = MCC + MNC
    if hni != (mcc or "") + (mnc or ""):
        V.append({"code": "hni_concat_mismatch",
                  "detail": f"HNI {hni} != MCC+MNC {mcc}+{mnc}"})

    # 6. account_count positive int
    ac = p.get("account_count")
    if not isinstance(ac, int) or ac < 1:
        V.append({"code": "account_count_invalid",
                  "detail": f"account_count must be positive int, got {ac!r}"})

    # 7. device_age_days positive int
    da = p.get("device_age_days")
    if not isinstance(da, int) or da < 1:
        V.append({"code": "device_age_invalid",
                  "detail": f"device_age_days must be positive int, got {da!r}"})

    # 8. app_signature_salt shape (32 hex)
    salt = p.get("app_signature_salt")
    if not isinstance(salt, str) or len(salt) != 32 or not all(c in "0123456789abcdef" for c in salt):
        V.append({"code": "signature_salt_invalid",
                  "detail": "app_signature_salt must be 32-char hex"})

    # 9. diurnal peak hour in [0, 23]
    peak = p.get("diurnal_peak_hour_local")
    if not isinstance(peak, int) or peak < 0 or peak > 23:
        V.append({"code": "diurnal_peak_invalid",
                  "detail": f"diurnal_peak_hour_local must be int 0..23, got {peak!r}"})

    return {"ok": not V, "violations": V}


def validate_cohort(personas: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a batch + report cohort-level invariants.
      - Signature salts unique (Onimator bug #2 fix)
      - Account counts NOT static (Onimator bug #3 fix)
      - Diurnal peaks spread (Onimator bug #4 fix)
    """
    per_persona: list[dict[str, Any]] = []
    bad = 0
    for p in personas:
        v = validate_persona(p)
        if v["violations"]:
            bad += 1
            per_persona.append({"persona_id": p.get("persona_id"), "violations": v["violations"]})

    salts = {p["app_signature_salt"] for p in personas}
    account_counts = {p["account_count"] for p in personas}
    peaks = {p["diurnal_peak_hour_local"] for p in personas}

    cohort_findings = []
    if len(salts) != len(personas):
        cohort_findings.append({
            "code": "signature_salt_collision",
            "detail": f"{len(personas) - len(salts)} shared salt(s) across {len(personas)} personas",
        })
    if len(personas) >= 50 and len(account_counts) < 8:
        cohort_findings.append({
            "code": "account_count_too_uniform",
            "detail": f"only {len(account_counts)} distinct account_counts across {len(personas)} personas",
        })
    if len(personas) >= 50 and len(peaks) < 6:
        cohort_findings.append({
            "code": "diurnal_peak_too_narrow",
            "detail": f"only {len(peaks)} distinct peak hours across {len(personas)} personas",
        })

    return {
        "ok": not per_persona and not cohort_findings,
        "personas_checked": len(personas),
        "personas_with_violations": bad,
        "sample_violations": per_persona[:5],
        "cohort_findings": cohort_findings,
        "stats": {
            "unique_salts": len(salts),
            "distinct_account_counts": len(account_counts),
            "distinct_diurnal_peaks": len(peaks),
        },
    }
