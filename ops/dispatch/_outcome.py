"""HTTP response (status, body) -> outcome string the recovery state
machine understands.

The strings must match ops/sched/recovery.py's rules exactly:

    ok                    successful action
    login_required        session expired; user needs to re-auth
    checkpoint            IG asked for a human / disabled the account
    account_disabled      IG hard-killed the account
    ig_rate_limited       IG rate-limited this account
    network_error         couldn't reach the phone or the phone couldn't reach IG
    accessibility_unbound APK is up but Accessibility service is disabled
    missing_target        we had no media_code / username to act on
    unknown               fallthrough
"""
from __future__ import annotations

import json
import re
from typing import Any


CHECKPOINT_PATTERNS = [
    re.compile(r"(We noticed unusual activity|Help us confirm|suspicious login)", re.IGNORECASE),
    re.compile(r"checkpoint required", re.IGNORECASE),
]
DISABLED_PATTERNS = [
    re.compile(r"(Your account has been disabled|account has been disabled)", re.IGNORECASE),
]
LOGIN_PATTERNS = [
    re.compile(r"(login_required|session expired|please log in again)", re.IGNORECASE),
]
RATE_LIMIT_PATTERNS = [
    re.compile(r"(please wait a few minutes|rate limit|try again later)", re.IGNORECASE),
]


def classify(
    status: int, body_bytes: bytes | None, transport_error: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (outcome, signal_dict)."""
    if transport_error:
        return "network_error", {"transport": transport_error}

    if status == 0:  # host unreachable; dispatcher sets this
        return "network_error", {"status": status}

    if status in (429,):
        return "ig_rate_limited", {"status": status}
    if status in (502, 503, 504):
        return "network_error", {"status": status}

    body_text = ""
    body_json: dict | None = None
    if body_bytes:
        try:
            body_text = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        try:
            body_json = json.loads(body_text)
        except Exception:
            body_json = None

    # APK-specific signals (JSON-encoded)
    if isinstance(body_json, dict):
        err = body_json.get("error")
        if err == "accessibility_unbound":
            return "accessibility_unbound", {"error": err}
        if err in ("session_expired", "login_required"):
            return "login_required", {"error": err}
        if err == "checkpoint":
            return "checkpoint", {"error": err}
        verdict = body_json.get("verdict")  # from /check_session responses
        if verdict == "dead":
            return "account_disabled", {"verdict": verdict}
        if verdict == "needs_reset":
            return "login_required", {"verdict": verdict}
        if verdict == "alive":
            return "ok", {"verdict": verdict}

    # Plain-text body patterns (IG app surfaces these in UI dumps the
    # APK returns verbatim).
    for pat in CHECKPOINT_PATTERNS:
        if pat.search(body_text):
            return "checkpoint", {"match": pat.pattern[:60]}
    for pat in DISABLED_PATTERNS:
        if pat.search(body_text):
            return "account_disabled", {"match": pat.pattern[:60]}
    for pat in LOGIN_PATTERNS:
        if pat.search(body_text):
            return "login_required", {"match": pat.pattern[:60]}
    for pat in RATE_LIMIT_PATTERNS:
        if pat.search(body_text):
            return "ig_rate_limited", {"match": pat.pattern[:60]}

    if 200 <= status < 300:
        if isinstance(body_json, dict) and body_json.get("ok") is False:
            return "unknown", {"body_ok_false": True}
        return "ok", {"status": status}
    if 400 <= status < 500:
        return "unknown", {"status": status, "client_error": True}
    return "unknown", {"status": status}
