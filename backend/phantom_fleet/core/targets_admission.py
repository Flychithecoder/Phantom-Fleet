"""Target & comment admission — Staffroom-gated.

Candidates land in `target_pool.status='needs_approval'` (or
`comment_pool.status='needs_approval'`). The owner approves via Staffroom
MCP tools; approval flips status to 'active'; the picker reads only
'active' rows. Rejection keeps the row for audit with rejected_reason.

Shared store (same SQLite as the sched stack):
  backend/.data/persona-store.sqlite

This module is the single canonical surface the API route and the
Staffroom MCP tools both call into.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

# Reuse the sched store's migrations + path resolution so one DB holds
# everything (accounts, queue, target_pool, comment_pool).
_REPO = Path(__file__).resolve().parents[3]
_OPS = _REPO / "ops"
import sys  # noqa: E402
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from ops.sched import _store  # noqa: E402


# ---------- target_pool ----------

def ingest_targets(rows: Iterable[dict], source: str) -> dict:
    """Ingest a batch of candidate targets.

    Each row: {kind, handle, media_code?, tags?, locale?, farm_id?}.
    Lands as status='needs_approval'. Deduped by (farm_id, kind, handle,
    media_code): a duplicate is kept but not re-inserted.

    Returns {inserted, duplicates, rejected: [(row, reason), ...]}.
    """
    now_ms = int(time.time() * 1000)
    inserted = 0
    duplicates = 0
    rejected: list[tuple[dict, str]] = []

    _store.apply_migrations()
    with _store.connect() as con:
        for raw in rows:
            kind = (raw.get("kind") or "").strip()
            handle = (raw.get("handle") or "").strip()
            media_code = (raw.get("media_code") or None)
            if kind not in ("account", "media") or not handle:
                rejected.append((raw, "invalid kind/handle"))
                continue
            if kind == "media" and not media_code:
                rejected.append((raw, "media row needs media_code"))
                continue

            farm_id = raw.get("farm_id")
            tags = raw.get("tags") or []
            if not isinstance(tags, list):
                rejected.append((raw, "tags must be a list"))
                continue

            dup = con.execute(
                """
                SELECT id FROM target_pool
                WHERE COALESCE(farm_id,'') = COALESCE(?, '')
                  AND kind = ? AND handle = ?
                  AND COALESCE(media_code,'') = COALESCE(?, '')
                LIMIT 1
                """,
                (farm_id, kind, handle, media_code),
            ).fetchone()
            if dup:
                duplicates += 1
                continue

            con.execute(
                "INSERT INTO target_pool "
                "(farm_id, kind, handle, media_code, tags_json, locale, "
                " status, source, imported_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, 'needs_approval', ?, ?)",
                (farm_id, kind, handle, media_code,
                 json.dumps(tags, sort_keys=True),
                 raw.get("locale"), source, now_ms),
            )
            inserted += 1
        con.commit()

    return {"inserted": inserted, "duplicates": duplicates,
            "rejected": rejected, "ts_ms": now_ms}


def list_pending_targets(farm_id: str | None = None, limit: int = 100) -> list[dict]:
    _store.apply_migrations()
    with _store.connect() as con:
        if farm_id is None:
            rows = con.execute(
                "SELECT * FROM target_pool WHERE status='needs_approval' "
                "ORDER BY imported_ms DESC LIMIT ?", (limit,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM target_pool WHERE status='needs_approval' "
                "AND (farm_id = ? OR farm_id IS NULL) "
                "ORDER BY imported_ms DESC LIMIT ?",
                (farm_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def approve_target(target_id: int, approver: str) -> dict:
    now_ms = int(time.time() * 1000)
    _store.apply_migrations()
    with _store.connect() as con:
        cur = con.execute(
            "UPDATE target_pool SET status='active', approved_by=?, "
            "approved_ms=? WHERE id=? AND status='needs_approval'",
            (approver, now_ms, target_id),
        )
        if cur.rowcount == 0:
            return {"ok": False, "reason": "not found or already decided"}
        con.commit()
    return {"ok": True, "id": target_id, "status": "active", "ts_ms": now_ms}


def reject_target(target_id: int, approver: str, reason: str) -> dict:
    now_ms = int(time.time() * 1000)
    _store.apply_migrations()
    with _store.connect() as con:
        cur = con.execute(
            "UPDATE target_pool SET status='rejected', approved_by=?, "
            "approved_ms=?, rejected_reason=? WHERE id=? "
            "AND status='needs_approval'",
            (approver, now_ms, reason, target_id),
        )
        if cur.rowcount == 0:
            return {"ok": False, "reason": "not found or already decided"}
        con.commit()
    return {"ok": True, "id": target_id, "status": "rejected", "ts_ms": now_ms}


# ---------- comment_pool ----------

def ingest_comments(rows: Iterable[dict], source: str) -> dict:
    now_ms = int(time.time() * 1000)
    inserted = duplicates = 0
    rejected: list[tuple[dict, str]] = []
    _store.apply_migrations()
    with _store.connect() as con:
        for raw in rows:
            text = (raw.get("text") or "").strip()
            niche = (raw.get("niche") or "generic").strip()
            if not text:
                rejected.append((raw, "empty text"))
                continue
            if len(text) > 500:
                rejected.append((raw, "text too long"))
                continue
            dup = con.execute(
                "SELECT id FROM comment_pool WHERE text = ? LIMIT 1", (text,),
            ).fetchone()
            if dup:
                duplicates += 1
                continue
            con.execute(
                "INSERT INTO comment_pool "
                "(text, niche, status, source, imported_ms) "
                "VALUES (?, ?, 'needs_approval', ?, ?)",
                (text, niche, source, now_ms),
            )
            inserted += 1
        con.commit()
    return {"inserted": inserted, "duplicates": duplicates,
            "rejected": rejected, "ts_ms": now_ms}


def list_pending_comments(limit: int = 100) -> list[dict]:
    _store.apply_migrations()
    with _store.connect() as con:
        rows = con.execute(
            "SELECT * FROM comment_pool WHERE status='needs_approval' "
            "ORDER BY imported_ms DESC LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def approve_comment(comment_id: int, approver: str) -> dict:
    now_ms = int(time.time() * 1000)
    _store.apply_migrations()
    with _store.connect() as con:
        cur = con.execute(
            "UPDATE comment_pool SET status='active', approved_by=?, "
            "approved_ms=? WHERE id=? AND status='needs_approval'",
            (approver, now_ms, comment_id),
        )
        if cur.rowcount == 0:
            return {"ok": False, "reason": "not found or already decided"}
        con.commit()
    return {"ok": True, "id": comment_id, "status": "active", "ts_ms": now_ms}


def reject_comment(comment_id: int, approver: str, reason: str) -> dict:
    now_ms = int(time.time() * 1000)
    _store.apply_migrations()
    with _store.connect() as con:
        cur = con.execute(
            "UPDATE comment_pool SET status='rejected', approved_by=?, "
            "approved_ms=? WHERE id=? AND status='needs_approval'",
            (approver, now_ms, comment_id),
        )
        if cur.rowcount == 0:
            return {"ok": False, "reason": "not found or already decided"}
        con.commit()
    return {"ok": True, "id": comment_id, "status": "rejected", "ts_ms": now_ms}


# ---------- owner_brief signals ----------

def pending_counts() -> dict:
    _store.apply_migrations()
    with _store.connect() as con:
        t = con.execute(
            "SELECT COUNT(*) AS n FROM target_pool WHERE status='needs_approval'"
        ).fetchone()["n"]
        c = con.execute(
            "SELECT COUNT(*) AS n FROM comment_pool WHERE status='needs_approval'"
        ).fetchone()["n"]
    return {"pending_target_approvals": int(t),
            "pending_comment_approvals": int(c)}
