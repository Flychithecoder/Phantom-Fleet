"""Pre-dispatch brief redactor.

Strips secrets, owner PII, and fleet-internal paths from a mission brief
BEFORE it crosses to a non-US-jurisdictional model endpoint (e.g. z.ai).
Applied only when the dispatch targets the GLM team; the Claude team
runs on Anthropic infra under US jurisdiction and skips this pass.

Patterns mirror server/mission-memory.js redactSecrets for consistency:
if a secret shape is redacted on the recall side, it must also be
redacted on the dispatch side. Diverging the two surfaces would leave a
gap where a secret survives dispatch but gets redacted on recall, and
the owner would never see the leak.
"""

from __future__ import annotations

import re

# Ordered list; first match wins per span. Anchored patterns go first so
# shape-specific labels ([REDACTED_SR_TOKEN], etc.) are applied before
# the generic long-hex/base64 fallback.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sr_mcp_[A-Za-z0-9_\-]{10,}"), "[REDACTED_SR_TOKEN]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"hf_[A-Za-z0-9]{10,}"), "[REDACTED_HF_TOKEN]"),
    (re.compile(r"ghp_[A-Za-z0-9]{10,}"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"xoxb-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_.]{10,}", re.I), "Bearer [REDACTED]"),
    (re.compile(r"Authorization:\s*\S+", re.I), "Authorization: [REDACTED]"),
    (re.compile(r"password[\"']?\s*[:=]\s*\"?[^\"\s]{6,}", re.I), "password: [REDACTED]"),
    # Fleet-internal paths that should never leave the host.
    (re.compile(r"[A-Za-z]:[\\\/][^\s\"']*\.env(?:\.[a-z]+)?", re.I), "[REDACTED_ENV_PATH]"),
    (re.compile(r"iguserdatabase\.db|notificationdatabase\.db", re.I),
     "[REDACTED_DB_NAME]"),
    (re.compile(r"staffroom_session=[A-Za-z0-9]{10,}"),
     "staffroom_session=[REDACTED]"),
    # Emails (owner PII).
    (re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+"),
     "[REDACTED_EMAIL]"),
    # Long opaque base64 / hex blobs — catch-all AFTER specific shapes.
    (re.compile(r"\b[A-Fa-f0-9]{48,}\b"), "[REDACTED_HEX]"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "[REDACTED_BLOB]"),
]


def redact(text: str) -> str:
    """Return the brief with every shape-matched secret replaced."""
    if not text:
        return ""
    out = text
    for pat, label in _PATTERNS:
        out = pat.sub(label, out)
    return out


def redaction_report(text: str) -> dict:
    """Describe how many hits each pattern produced. Useful for an
    owner-side review before enabling GLM dispatch at scale."""
    if not text:
        return {"total_hits": 0, "by_pattern": {}}
    by_pattern: dict[str, int] = {}
    total = 0
    for pat, label in _PATTERNS:
        n = len(pat.findall(text))
        if n:
            by_pattern[label] = n
            total += n
    return {"total_hits": total, "by_pattern": by_pattern}
