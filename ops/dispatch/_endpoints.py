"""Scheduler kind -> APK endpoint spec.

The APK's HTTP surface (verified in the audit; see companion-apk/app/
src/main/java/com/scalerpro/phantomfleet/http/LocalHttpServer.kt):

    POST /instagram/engage/follow        {clonePackage, targetUsername}
    POST /instagram/engage/like          {clonePackage, mediaCode}
    POST /instagram/engage/view_stories  {clonePackage, usernames[]}
    POST /instagram/engage/comment       {clonePackage, mediaCode, text}
    POST /instagram/engage/send_dm       {clonePackage, username, text}
    POST /instagram/engage/scroll_reels  {clonePackage, duration_s}
    GET  /instagram/engage/check_session?clonePackage=<pkg>

The scheduler currently emits `follows | likes | stories | comments`.
(`stories` -> `view_stories` normalisation happens here.) `send_dm`,
`scroll_reels`, `unfollow` exist on the APK side but the scheduler
does not emit them in Phase 0.

For Phase 0 we don't own the target-picking logic (what to like, who
to follow); so `params_json` from the action_queue row supplies the
missing fields. Scheduler already writes `warming_day` in params; a
later step will populate `target_username` / `media_code` from the
Content Vault or a target-pool table. Until then unresolved actions
are recorded with outcome='missing_target' and skipped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class Endpoint:
    method: str
    path: str
    body_fields: list[str]   # keys we lift from (clone_package, action.params)
    # which params are REQUIRED to dispatch; missing ones -> missing_target
    required: list[str]


def spec_for_kind(kind: str) -> Endpoint | None:
    if kind in ("follow", "follows"):
        return Endpoint(
            "POST", "/instagram/engage/follow",
            body_fields=["clonePackage", "targetUsername"],
            required=["targetUsername"],
        )
    if kind in ("like", "likes"):
        return Endpoint(
            "POST", "/instagram/engage/like",
            body_fields=["clonePackage", "mediaCode"],
            required=["mediaCode"],
        )
    if kind in ("story", "stories", "view_stories"):
        return Endpoint(
            "POST", "/instagram/engage/view_stories",
            body_fields=["clonePackage", "usernames"],
            required=["usernames"],
        )
    if kind in ("comment", "comments"):
        return Endpoint(
            "POST", "/instagram/engage/comment",
            body_fields=["clonePackage", "mediaCode", "text"],
            required=["mediaCode", "text"],
        )
    if kind in ("unfollow",):
        return Endpoint(
            "POST", "/instagram/engage/unfollow",
            body_fields=["clonePackage", "targetUsername"],
            required=["targetUsername"],
        )
    if kind in ("scroll_reels",):
        return Endpoint(
            "POST", "/instagram/engage/scroll_reels",
            body_fields=["clonePackage", "duration_s"],
            required=[],
        )
    if kind in ("check_session",):
        return Endpoint(
            "GET", "/instagram/engage/check_session",
            body_fields=["clonePackage"],
            required=["clonePackage"],
        )
    return None


def build_payload(
    endpoint: Endpoint, clone_package: str, action_params: dict,
) -> tuple[dict | None, list[str]]:
    """Return (payload | None, missing_fields). If any `required` field
    is not available from params / clone_package, returns (None, [...])
    so the dispatcher can mark the row missing_target instead of posting
    a 400-guaranteed request."""
    payload: dict = {"clonePackage": clone_package}
    missing: list[str] = []
    for field in endpoint.body_fields:
        if field == "clonePackage":
            continue
        val = action_params.get(field) or action_params.get(_snake(field))
        if val is None and field in endpoint.required:
            missing.append(field)
        elif val is not None:
            payload[field] = val
    if missing:
        return None, missing
    return payload, []


def _snake(s: str) -> str:
    """mediaCode -> media_code, targetUsername -> target_username."""
    out = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def dumps(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")
