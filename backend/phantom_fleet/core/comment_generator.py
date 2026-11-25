"""AI comment-candidate generator — the single AI write-path.

Produces candidate comments for a niche, runs them through the safety
filter and dedup/length checks, and lands the survivors in
`comment_pool.status='needs_approval'` via
`targets_admission.ingest_comments`.

Hard rules (CLAUDE.md agent-rules):
  - This module NEVER posts a comment.
  - This module NEVER calls `approve_comment`.
  - Every candidate lands as `needs_approval`; the owner approves via
    `/approvals` (frontend) or Staffroom MCP.
  - Every run writes an audit-log record (ndjson) with the receipt.

The underlying model call is routed through the Scaler Pro
`cost_quality_router.recommend_team(workflow=..., role=...)`; the
actual text production is pluggable via the `generator_fn` argument so
tests can mock it. In production the default stub returns an empty
batch — a real model client is wired later. The admission gate does
not care which model produced the text.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Callable, Iterable

from . import targets_admission as ta
from . import comment_safety
from .cost_quality_router import recommend_team

log = logging.getLogger("phantom_fleet.comment_generator")

_WORKFLOW = "comment_generation"
_ROLE = "content_writer"
_MAX_TEXT_LEN = 500

_REPO = Path(__file__).resolve().parents[3]
_AUDIT_LOG = _REPO / "backend" / ".data" / "comment_generator-audit.ndjson"


GeneratorFn = Callable[[str, int, list[str]], list[str]]


def _default_generator(niche: str, n: int, style_hints: list[str]) -> list[str]:
    """No-op production default. A real model client is wired upstream
    by passing `generator_fn=` into `generate_comments`. Returning an
    empty list keeps the admission gate the only path that can add
    rows to `comment_pool`."""
    log.warning(
        "comment_generator: no generator_fn provided; returning empty batch "
        "(niche=%s n=%d)", niche, n,
    )
    return []


def _audit(record: dict) -> None:
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception as exc:
        log.warning("comment_generator audit write failed: %s", exc)


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def generate_comments(
    niche: str,
    n: int,
    style_hints: list[str] | None = None,
    *,
    generator_fn: GeneratorFn | None = None,
    source: str | None = None,
) -> dict:
    """Generate `n` candidate comments for `niche`, land survivors as
    `needs_approval` rows in `comment_pool`.

    Pipeline (in order):
      1. route recommendation (cost_quality_router)
      2. call `generator_fn(niche, n, style_hints)` for raw candidates
      3. strip + length filter (<=500 chars, non-empty)
      4. exact-text dedupe within the batch
      5. safety filter (links, @-mentions, phone, email, blocklist)
      6. `targets_admission.ingest_comments(..., source=...)`

    Returns a receipt dict with the per-stage counts and the admission
    result. NEVER approves a row — approval stays owner-gated.
    """
    t0 = time.time()
    run_id = f"cg_{int(t0)}_{uuid.uuid4().hex[:8]}"
    niche = (niche or "").strip() or "generic"
    style_hints = list(style_hints or [])
    if not isinstance(n, int) or n <= 0:
        raise ValueError("n must be a positive int")
    if n > 200:
        raise ValueError("n must be <= 200 per run")
    fn = generator_fn or _default_generator
    src = source or f"ai.comment_generator:{run_id}"

    route = recommend_team(_WORKFLOW, role=_ROLE)

    raw = fn(niche, n, style_hints) or []
    raw = [str(c) for c in raw]

    stripped = [c.strip() for c in raw if c and c.strip()]
    length_ok = [c for c in stripped if len(c) <= _MAX_TEXT_LEN]
    length_dropped = len(stripped) - len(length_ok)

    deduped = _dedupe_preserve_order(length_ok)
    dup_dropped = len(length_ok) - len(deduped)

    safe, unsafe = comment_safety.filter_safe(deduped)

    rows = [{"text": t, "niche": niche} for t in safe]
    admission = ta.ingest_comments(rows, source=src) if rows else {
        "inserted": 0, "duplicates": 0, "rejected": [], "ts_ms": int(t0 * 1000),
    }

    receipt = {
        "run_id": run_id,
        "niche": niche,
        "style_hints": style_hints,
        "requested": n,
        "raw_candidates": len(raw),
        "length_dropped": length_dropped,
        "within_batch_duplicates": dup_dropped,
        "safety_dropped": [{"text": t, "reason": r} for t, r in unsafe],
        "submitted_to_admission": len(rows),
        "admission": {
            "inserted": admission.get("inserted", 0),
            "duplicates": admission.get("duplicates", 0),
            "rejected_count": len(admission.get("rejected") or []),
        },
        "route_recommendation": {
            "recommended_team": route.get("recommended_team"),
            "role": route.get("role"),
        },
        "source": src,
        "duration_ms": int((time.time() - t0) * 1000),
    }
    _audit({"event": "run", **receipt})
    return receipt
