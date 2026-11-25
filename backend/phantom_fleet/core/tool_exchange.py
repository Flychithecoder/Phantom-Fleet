"""Tool exchange — moonshot #3 (`staffroom_propose_tool`).

A registry where agents propose new MCP tools. Approval is owner-gated;
execution is never automatic. An approved proposal only unlocks the
discovery surface — a human operator still wires the implementation.

Core table (SQLite, in `.data/tool-exchange.sqlite`):
  tool_proposals(
    id TEXT PRIMARY KEY,         -- 16-hex
    name TEXT,                   -- namespace: `staffroom_propose_<slug>` style
    description TEXT,
    schema_json TEXT,            -- JSON string of input schema
    use_case TEXT,
    implementation_hint TEXT,
    proposed_by TEXT,            -- agent id / bot id / caller tag
    status TEXT,                 -- needs_approval | approved | rejected
    reason TEXT,                 -- rejection reason, when status=rejected
    created_unix_ms INTEGER,
    decided_unix_ms INTEGER      -- nullable
  )

Rate limit: an agent can file at most 10 proposals per hour. Hard wall
in-code; the UI should say so too.

Validation:
  - name matches ^[a-z][a-z0-9_]{2,63}$ (MCP tool naming)
  - schema_json parses to a dict with `type` and `properties`
  - description + use_case non-empty
  - implementation_hint <=2000 chars
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_RATE_LIMIT_PER_HOUR = 10


def _db_path() -> str:
    env = os.environ.get("PF_TOOL_EXCHANGE_DB")
    if env:
        return env
    base = Path(__file__).resolve().parents[2] / ".data"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "tool-exchange.sqlite")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    c.execute("""
      CREATE TABLE IF NOT EXISTS tool_proposals (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        schema_json TEXT NOT NULL,
        use_case TEXT NOT NULL,
        implementation_hint TEXT NOT NULL DEFAULT '',
        proposed_by TEXT NOT NULL,
        status TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_unix_ms INTEGER NOT NULL,
        decided_unix_ms INTEGER
      )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS ix_tp_status ON tool_proposals(status)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_tp_by ON tool_proposals(proposed_by, created_unix_ms)")
    c.commit()
    return c


def _validate_schema(schema_json: str) -> dict[str, Any]:
    try:
        s = json.loads(schema_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"schema_json not valid JSON: {exc}") from exc
    if not isinstance(s, dict):
        raise ValueError("schema_json must be a JSON object")
    if s.get("type") != "object":
        raise ValueError("schema top-level must be {'type': 'object', ...}")
    if not isinstance(s.get("properties"), dict):
        raise ValueError("schema must have a 'properties' object")
    return s


def propose_tool(
    *,
    name: str,
    description: str,
    schema_json: str,
    use_case: str,
    implementation_hint: str = "",
    proposed_by: str,
) -> dict[str, Any]:
    """File a tool proposal. Returns the row as-dict, status needs_approval."""
    if not _NAME_RE.match(name or ""):
        raise ValueError("name must match ^[a-z][a-z0-9_]{2,63}$")
    if not description or not description.strip():
        raise ValueError("description required")
    if not use_case or not use_case.strip():
        raise ValueError("use_case required")
    if len(description) > 1000:
        raise ValueError("description must be <=1000 chars")
    if len(use_case) > 2000:
        raise ValueError("use_case must be <=2000 chars")
    if len(implementation_hint) > 2000:
        raise ValueError("implementation_hint must be <=2000 chars")
    if not proposed_by or len(proposed_by) > 120:
        raise ValueError("proposed_by must be 1..120 chars")
    _validate_schema(schema_json)
    now = int(time.time() * 1000)
    hour_ago = now - 3600_000
    with _conn() as c:
        rate = c.execute(
            "SELECT COUNT(*) FROM tool_proposals "
            "WHERE proposed_by=? AND created_unix_ms>=?",
            (proposed_by, hour_ago),
        ).fetchone()[0]
        if rate >= _RATE_LIMIT_PER_HOUR:
            raise PermissionError(
                f"rate limit: {proposed_by} has filed {rate} proposals in the "
                f"last hour (cap {_RATE_LIMIT_PER_HOUR})"
            )
        pid = secrets.token_hex(8)
        c.execute(
            "INSERT INTO tool_proposals "
            "(id,name,description,schema_json,use_case,implementation_hint,"
            " proposed_by,status,created_unix_ms) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, name, description, schema_json, use_case,
             implementation_hint, proposed_by, "needs_approval", now),
        )
    return get_proposal(pid)


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        d["schema"] = json.loads(d.pop("schema_json"))
    except (KeyError, json.JSONDecodeError):
        d["schema"] = None
    return d


def get_proposal(proposal_id: str) -> dict[str, Any]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM tool_proposals WHERE id=?", (proposal_id,)
        ).fetchone()
    if not row:
        raise LookupError(f"no such proposal: {proposal_id}")
    return _row_to_dict(row)


def list_proposals(status: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    if status and status not in ("needs_approval", "approved", "rejected"):
        raise ValueError("status must be one of needs_approval|approved|rejected")
    limit = max(1, min(limit, 500))
    with _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM tool_proposals WHERE status=? "
                "ORDER BY created_unix_ms DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM tool_proposals "
                "ORDER BY created_unix_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return {
        "proposals": [_row_to_dict(r) for r in rows],
        "count": len(rows),
        "status_filter": status,
    }


def approve_proposal(proposal_id: str) -> dict[str, Any]:
    with _conn() as c:
        row = c.execute(
            "SELECT status FROM tool_proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        if not row:
            raise LookupError(f"no such proposal: {proposal_id}")
        if row["status"] != "needs_approval":
            raise ValueError(f"proposal is {row['status']}, not needs_approval")
        c.execute(
            "UPDATE tool_proposals SET status='approved', decided_unix_ms=? "
            "WHERE id=?",
            (int(time.time() * 1000), proposal_id),
        )
    return get_proposal(proposal_id)


def reject_proposal(proposal_id: str, reason: str) -> dict[str, Any]:
    if not reason or not reason.strip():
        raise ValueError("reason required for rejection")
    if len(reason) > 1000:
        raise ValueError("reason must be <=1000 chars")
    with _conn() as c:
        row = c.execute(
            "SELECT status FROM tool_proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        if not row:
            raise LookupError(f"no such proposal: {proposal_id}")
        if row["status"] != "needs_approval":
            raise ValueError(f"proposal is {row['status']}, not needs_approval")
        c.execute(
            "UPDATE tool_proposals SET status='rejected', reason=?, "
            "decided_unix_ms=? WHERE id=?",
            (reason, int(time.time() * 1000), proposal_id),
        )
    return get_proposal(proposal_id)


def discover_approved() -> dict[str, Any]:
    """Return every approved proposal — the public catalogue a worker
    can look at to see which new tools the owner has unlocked. The tools
    themselves still require human wiring before they do anything;
    this is a discovery surface, not an execution surface."""
    return list_proposals(status="approved", limit=500)
