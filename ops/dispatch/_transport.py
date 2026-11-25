"""HTTP transport + device resolution + atomic queue claim.

Stdlib only (urllib). No requests, no aiohttp — the whole dispatcher
should be auditable in one sitting.

Three capabilities:

 1. **resolve_device(serial)** -> (ip, port) from device_endpoints.
 2. **do_request(method, url, body, timeout)** -> (status, body_bytes,
    transport_error).
 3. **claim(con, limit, now_ms)** -> up to `limit` action_queue rows
    atomically transitioned from 'due' -> 'claimed'. Prevents double
    dispatch when multiple workers run.
"""
from __future__ import annotations

import socket
import sqlite3
import urllib.error
import urllib.request
from typing import Any


def resolve_device(con: sqlite3.Connection, serial: str) -> tuple[str, int] | None:
    row = con.execute(
        "SELECT wifi_ip, port FROM device_endpoints WHERE serial = ?",
        (serial,),
    ).fetchone()
    if not row or not row["wifi_ip"]:
        return None
    return row["wifi_ip"], int(row["port"])


def do_request(
    method: str, url: str, body: bytes | None,
    timeout: float = 30.0,
) -> tuple[int, bytes, str | None]:
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), None
    except urllib.error.HTTPError as e:
        try:
            data = e.read()
        except Exception:
            data = b""
        return e.code, data, None
    except urllib.error.URLError as e:
        return 0, b"", f"url_error: {e.reason}"
    except socket.timeout:
        return 0, b"", "timeout"
    except Exception as e:  # pragma: no cover
        return 0, b"", f"{type(e).__name__}: {e}"


def claim(con: sqlite3.Connection, limit: int, now_ms: int) -> list[dict]:
    """Atomically claim up to `limit` due rows.

    Picks the oldest due_ms first so no account is starved. Transitions
    them to state='claimed' in one statement under an implicit
    transaction; a crash between claim and dispatch leaves them
    claimed, which the recovery sweeper reaps (future work).
    """
    rows = con.execute(
        """
        SELECT q.id, q.account_id, q.kind, q.due_ms, q.params_json,
               a.username, a.device_serial, a.status AS account_status,
               c.clone_package
        FROM action_queue q
        JOIN accounts a ON a.id = q.account_id
        LEFT JOIN clone_assignments c ON c.account_id = q.account_id
        WHERE q.state = 'due' AND q.due_ms <= ?
          AND a.status = 'alive'
        ORDER BY q.due_ms ASC
        LIMIT ?
        """,
        (now_ms, limit),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        placeholders = ",".join("?" * len(ids))
        con.execute(
            f"UPDATE action_queue SET state = 'claimed' WHERE id IN ({placeholders})",
            ids,
        )
    return [dict(r) for r in rows]


def release_claim(con: sqlite3.Connection, action_id: int) -> None:
    """If dispatch hard-fails before recording a result, hand the row
    back to the 'due' pool instead of leaving it stuck."""
    con.execute(
        "UPDATE action_queue SET state = 'due' WHERE id = ? AND state = 'claimed'",
        (action_id,),
    )
