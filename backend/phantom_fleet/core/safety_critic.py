"""Pre-dispatch safety critic — moonshot #6.

Scan a brief for policy violations rooted in OrionFarm's hard rules
(never flash a phone without confirmation, never factory-reset, never
push the companion APK fleet-wide without confirmation, never modify
Onimator DBs without backup, never delete from iguserdatabase.db or
notificationdatabase.db) plus general safety signals (billing moves
without approval, external publish without approval, leaked secrets in
the prompt itself).

Returns {verdict, findings} where:
  verdict ∈ {"block", "warn", "ok"}
  findings: [{rule_id, severity, kind, match, rationale, line_hint?}]

verdict precedence: any block -> block; else any warn -> warn; else ok.

The critic NEVER mutates anything. Staffroom dispatch should treat a
"block" verdict as a hard gate (refuse dispatch), a "warn" verdict as
a signal to prepend the warning to the owner-approval card, and "ok"
as silent.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    kind: str
    severity: str  # block | warn | info
    rationale: str


# Order within a category doesn't matter; verdict precedence is global.
_RULES: tuple[Rule, ...] = (
    # ---- device-destructive (block) ----
    Rule("device.flash_firmware",
         re.compile(r"\b(flash(?:ing)?\s+(?:the\s+)?(?:phone|device|rom|firmware)|re-?flash)\b", re.I),
         "device_destructive", "block",
         "OrionFarm rule: never flash a phone without owner confirmation. "
         "This action is irreversible on at least one device."),
    Rule("device.factory_reset",
         re.compile(r"\bfactory[- ]?reset|wipe\s+(?:the\s+)?(?:phone|device|data)|erase\s+all\s+(?:data|content)\b", re.I),
         "factory_reset", "block",
         "OrionFarm rule: never factory-reset without owner confirmation. "
         "Destroys every account on the device."),
    Rule("device.companion_apk_fleetwide",
         re.compile(r"\b(push|roll[- ]?out|deploy)\s+(?:the\s+)?(?:companion\s+)?apk\s+(?:to\s+)?(?:the\s+)?(?:whole\s+)?fleet\b", re.I),
         "companion_apk_wide_push", "block",
         "OrionFarm rule: companion APK must pilot on 1 phone before "
         "fleet-wide; this needs owner confirmation."),
    # ---- data-destructive (block) ----
    Rule("data.iguserdatabase_delete",
         re.compile(r"\b(delete|drop|truncate|remove)\s+(?:rows?\s+)?(?:from\s+)?iguserdatabase\.db\b", re.I),
         "data_destructive", "block",
         "OrionFarm rule: never delete from iguserdatabase.db. "
         "Destroys the account corpus."),
    Rule("data.notificationdatabase_delete",
         re.compile(r"\b(delete|drop|truncate|remove)\s+(?:rows?\s+)?(?:from\s+)?notificationdatabase\.db\b", re.I),
         "data_destructive", "block",
         "OrionFarm rule: never delete from notificationdatabase.db."),
    Rule("data.onimator_without_backup",
         re.compile(r"\b(modify|write|update|alter)\s+(?:the\s+)?onimator\s+(?:db|database|tables?)\b(?!.*\bbackup\b)", re.I),
         "data_destructive", "block",
         "OrionFarm rule: never modify Onimator DBs without a backup. "
         "No backup word in the brief."),
    # ---- financial (warn, needs owner approval in words) ----
    Rule("fin.send_money",
         re.compile(r"\b(?:send|wire|transfer|pay|charge|refund)\s+(?:usd|\$|eur|€|gbp|£)?\s*\d+(?:[.,]\d+)?\b", re.I),
         "billing_unapproved", "warn",
         "A financial action is implied; owner must approve amount, "
         "recipient, and reversibility in chat."),
    Rule("fin.standing_grant",
         re.compile(r"\b(standing\s+grant|auto[- ]?pay|recurring\s+(?:charge|payment|transfer))\b", re.I),
         "billing_unapproved", "warn",
         "Standing/recurring payment setup; owner must approve in chat."),
    # ---- external publish (warn) ----
    Rule("publish.external_post",
         re.compile(r"\b(publish|post|share|tweet|upload)\s+(?:to\s+)?(?:instagram|tiktok|threads|reddit|twitter|x\.com|bluesky|public|customer|audience)\b", re.I),
         "external_publish", "warn",
         "External publish; owner must approve content + channel."),
    # ---- secrets in prompt (block) ----
    Rule("secret.sr_mcp_token",
         re.compile(r"sr_mcp_[A-Za-z0-9_-]{30,}"),
         "secret_in_prompt", "block",
         "A Staffroom MCP token appears in the brief; redact before "
         "dispatch. Prompts must never carry raw tokens."),
    Rule("secret.openrouter_key",
         re.compile(r"sk-or-v\d-[A-Za-z0-9]{32,}"),
         "secret_in_prompt", "block",
         "OpenRouter API key appears in the brief; redact before dispatch."),
    Rule("secret.bearer",
         re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
         "secret_in_prompt", "block",
         "Bearer token appears in the brief; redact before dispatch."),
    Rule("secret.treg",
         re.compile(r"\btreg[_-]?(?:key|token|secret)\b\s*[:=]\s*\S{8,}", re.I),
         "secret_in_prompt", "block",
         "Treg credential reference in brief; Treg credentials stay "
         "server-side only."),
    Rule("secret.email",
         re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
         "pii", "info",
         "Email address in the brief; make sure it belongs to the task."),
    # ---- info: audit log reminder ----
    Rule("audit.destructive_action",
         re.compile(r"\b(delete|drop|wipe|clear|revoke|reset)\b", re.I),
         "destructive_hint", "info",
         "A destructive verb is present; agent must write audit log "
         "before and after per OrionFarm agent-rule."),
)


def critique(brief: str) -> dict[str, Any]:
    """Scan `brief` and return a verdict + findings list. Fast (regex-
    only); runs in well under 10ms for a 16KB brief."""
    if brief is None:
        raise ValueError("brief required")
    if not isinstance(brief, str):
        raise ValueError("brief must be a string")
    if len(brief) > 32_000:
        raise ValueError("brief must be <=32000 chars")
    t0 = time.monotonic()

    findings: list[dict[str, Any]] = []
    has_block = False
    has_warn = False
    for rule in _RULES:
        for m in rule.pattern.finditer(brief):
            snippet = m.group(0)
            # Line hint: 1-indexed line number of the first char of the match.
            line_hint = brief.count("\n", 0, m.start()) + 1
            findings.append({
                "rule_id": rule.rule_id,
                "severity": rule.severity,
                "kind": rule.kind,
                "match": snippet[:80],
                "rationale": rule.rationale,
                "line_hint": line_hint,
            })
            if rule.severity == "block":
                has_block = True
            elif rule.severity == "warn":
                has_warn = True

    verdict = "block" if has_block else ("warn" if has_warn else "ok")
    # Sort findings by severity (block > warn > info) then by line.
    _order = {"block": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: (_order.get(f["severity"], 3), f["line_hint"]))

    return {
        "verdict": verdict,
        "findings": findings,
        "finding_count": len(findings),
        "block_count": sum(1 for f in findings if f["severity"] == "block"),
        "warn_count": sum(1 for f in findings if f["severity"] == "warn"),
        "info_count": sum(1 for f in findings if f["severity"] == "info"),
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


def rule_catalogue() -> dict[str, Any]:
    """Expose the rules the critic knows about, for an owner audit UI."""
    return {
        "rules": [
            {
                "rule_id": r.rule_id,
                "kind": r.kind,
                "severity": r.severity,
                "rationale": r.rationale,
                "pattern": r.pattern.pattern,
            }
            for r in _RULES
        ],
        "count": len(_RULES),
    }
