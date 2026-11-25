"""Deterministic target picker.

Given (account, kind), return params to merge into an action_queue row:

    follows / unfollow  -> {"targetUsername": str}
    likes / comments    -> {"mediaCode": str, "text"?: str}
    stories             -> {"usernames": [str, ...]}

Pure function. No LLM. No `random.*`. Staffroom owns pool admission;
this module only picks from rows already in status='active'.

Score = recency_bonus + fleet_pressure_penalty + niche_affinity
      + locale_match + per_account_jitter

Highest score wins. Ties broken by target.id (stable across runs).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any


# Weights — all additive, roughly in [-1, +1] range so tuning later is
# mechanical. Keep the picker transparent rather than ML'd; Staffroom
# is where judgment lives.
W_RECENCY         = +0.8    # higher when THIS account hasn't touched this target lately
W_FLEET_PRESSURE  = -1.2    # heavy penalty when many of our accounts touched the target in 7d
W_NICHE_AFFINITY  = +0.9    # matching persona_tag ∩ target.tags_json
W_LOCALE_MATCH    = +0.2
W_JITTER          = 0.05    # sub-score tie-breaker, deterministic per (account, target)

RECENCY_CAP_DAYS = 90
FLEET_PRESSURE_WINDOW_MS = 7 * 86_400 * 1000
FLEET_PRESSURE_CAP = 10


@dataclass
class TargetRow:
    id: int
    farm_id: str | None
    kind: str
    handle: str
    media_code: str | None
    tags: list[str]
    locale: str | None


def _candidates(
    con: sqlite3.Connection, target_kind: str, farm_id: str | None,
) -> list[TargetRow]:
    rows = con.execute(
        """
        SELECT id, farm_id, kind, handle, media_code, tags_json, locale
        FROM target_pool
        WHERE status = 'active'
          AND kind = ?
          AND (farm_id IS NULL OR farm_id = ?)
        """,
        (target_kind, farm_id or ""),
    ).fetchall()
    out: list[TargetRow] = []
    for r in rows:
        try:
            tags = list(json.loads(r["tags_json"] or "[]"))
        except Exception:
            tags = []
        out.append(TargetRow(
            id=r["id"], farm_id=r["farm_id"], kind=r["kind"],
            handle=r["handle"], media_code=r["media_code"],
            tags=tags, locale=r["locale"],
        ))
    return out


def _account_touched_days_ago(
    con: sqlite3.Connection, account_id: int, target_id: int, now_ms: int,
) -> float | None:
    row = con.execute(
        "SELECT MAX(ts_ms) AS last FROM target_history "
        "WHERE account_id = ? AND target_id = ?",
        (account_id, target_id),
    ).fetchone()
    last = row["last"] if row else None
    if last is None:
        return None
    return (now_ms - int(last)) / 86_400_000


def _fleet_pressure(
    con: sqlite3.Connection, target_id: int, now_ms: int,
) -> int:
    row = con.execute(
        "SELECT COUNT(DISTINCT account_id) AS n FROM target_history "
        "WHERE target_id = ? AND ts_ms >= ?",
        (target_id, now_ms - FLEET_PRESSURE_WINDOW_MS),
    ).fetchone()
    return int(row["n"] if row else 0)


def _persona_tags(con: sqlite3.Connection, persona: str) -> set[str]:
    rows = con.execute(
        "SELECT tag FROM persona_tags WHERE persona = ?", (persona,),
    ).fetchall()
    return {r["tag"] for r in rows}


def _jitter(account_id: int, target_id: int) -> float:
    # Deterministic per pair; keeps two accounts from always picking the
    # same winner when scores are tied.
    seed = f"{account_id}:{target_id}".encode()
    h = hashlib.sha256(seed).digest()
    return (int.from_bytes(h[:4], "big") / 2**32) * W_JITTER


def _score(
    cand: TargetRow,
    *,
    touched_days_ago: float | None,
    fleet_pressure: int,
    persona_tags: set[str],
    account_locale: str | None,
    account_id: int,
) -> float:
    s = 0.0
    if touched_days_ago is not None:
        s += W_RECENCY * min(touched_days_ago, RECENCY_CAP_DAYS) / RECENCY_CAP_DAYS
    else:
        s += W_RECENCY  # fully novel target gets the full bonus
    s += W_FLEET_PRESSURE * min(fleet_pressure, FLEET_PRESSURE_CAP) / FLEET_PRESSURE_CAP
    overlap = len(persona_tags & set(cand.tags))
    if persona_tags:
        s += W_NICHE_AFFINITY * (overlap / max(1, len(persona_tags)))
    if account_locale and cand.locale and cand.locale == account_locale:
        s += W_LOCALE_MATCH
    s += _jitter(account_id, cand.id)
    return s


def pick_for(
    con: sqlite3.Connection,
    account: dict,
    kind: str,
    now_ms: int,
) -> dict | None:
    """Return a params dict or None if the pool is exhausted.

    `account` must carry: id, persona, locale, device_serial, farm_id (nullable).
    """
    # Normalise scheduler kind -> pool kind.
    if kind in ("follows", "follow", "unfollow"):
        pool_kind, field = "account", "targetUsername"
    elif kind in ("stories", "story", "view_stories"):
        pool_kind, field = "account", "usernames"
    elif kind in ("likes", "like"):
        pool_kind, field = "media", "mediaCode"
    elif kind in ("comments", "comment"):
        pool_kind, field = "media", "mediaCode"
    else:
        return None

    cands = _candidates(con, pool_kind, account.get("farm_id"))
    if not cands:
        return None
    ptags = _persona_tags(con, account.get("persona") or "")
    acct_locale = account.get("locale")

    best: tuple[float, TargetRow] | None = None
    for c in cands:
        days = _account_touched_days_ago(con, account["id"], c.id, now_ms)
        # Skip if touched in the last day (micro-cooldown).
        if days is not None and days < 1.0:
            continue
        pressure = _fleet_pressure(con, c.id, now_ms)
        if pressure >= FLEET_PRESSURE_CAP:
            continue
        s = _score(
            c, touched_days_ago=days, fleet_pressure=pressure,
            persona_tags=ptags, account_locale=acct_locale,
            account_id=account["id"],
        )
        if best is None or s > best[0]:
            best = (s, c)
    if best is None:
        return None

    c = best[1]
    if pool_kind == "account" and field == "targetUsername":
        return {field: c.handle, "_target_id": c.id}
    if pool_kind == "account" and field == "usernames":
        # Stories take a small list; pick up to 3 by score.
        top = sorted(cands, key=lambda x: _score(
            x, touched_days_ago=_account_touched_days_ago(con, account["id"], x.id, now_ms),
            fleet_pressure=_fleet_pressure(con, x.id, now_ms),
            persona_tags=ptags, account_locale=acct_locale,
            account_id=account["id"],
        ), reverse=True)[:3]
        return {"usernames": [t.handle for t in top], "_target_ids": [t.id for t in top]}
    if pool_kind == "media":
        payload = {"mediaCode": c.media_code, "_target_id": c.id}
        if kind in ("comments", "comment"):
            text = _pick_comment(con, c.tags)
            if text is None:
                return None
            payload["text"] = text
        return payload
    return None


def _pick_comment(con: sqlite3.Connection, tags: list[str]) -> str | None:
    # Prefer niche overlap; fall back to 'generic'. Only 'active' rows.
    # Deterministic least-recently-used: order by last_picked_ms ASC
    # (NULLs first via COALESCE(0)), then by id ASC as tiebreak. Stamp
    # last_picked_ms after reading so the next call rotates to a
    # different row — fixes the "lowest-id-wins-forever" bug.
    row = None
    for niche in list(tags) + ["generic"]:
        row = con.execute(
            "SELECT id, text FROM comment_pool "
            "WHERE status = 'active' AND niche = ? "
            "ORDER BY COALESCE(last_picked_ms, 0) ASC, id ASC LIMIT 1",
            (niche,),
        ).fetchone()
        if row:
            break
    if not row:
        return None
    import time as _time
    con.execute(
        "UPDATE comment_pool SET last_picked_ms = ? WHERE id = ?",
        (int(_time.time() * 1000), int(row["id"])),
    )
    return row["text"]


def record_touch(
    con: sqlite3.Connection, account_id: int, target_id: int,
    kind: str, now_ms: int, outcome: str = "picked",
) -> None:
    con.execute(
        "INSERT INTO target_history "
        "(account_id, target_id, kind, ts_ms, outcome) VALUES (?, ?, ?, ?, ?)",
        (account_id, target_id, kind, now_ms, outcome),
    )
