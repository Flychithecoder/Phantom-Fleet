"""Scheduler kind -> APK endpoint spec.

Verified against companion-apk/app/src/main/java/com/scalerpro/
phantomfleet/http/LocalHttpServer.kt (data classes at line 1059+).
APK HTTP surface, EXACT field names:

    POST /instagram/engage/follow    {username, clonePackage}
    POST /instagram/engage/unfollow  {username, clonePackage}
    POST /instagram/engage/like      {mediaId, clonePackage}
    POST /instagram/engage/comment   {mediaId, commentText, clonePackage}
    POST /instagram/engage/view_stories {username, storyCount?, clonePackage}
    POST /instagram/engage/scroll_reels {watchCount?, clonePackage}
    POST /instagram/engage/send_dm   {username, message, clonePackage}
    GET  /instagram/engage/check_session?clonePackage=<pkg>

The hydrator (ops/targets/hydrator.py) writes params in PICKER shape
(targetUsername / mediaCode / text / usernames[]) because that's the
pool-facing vocabulary. We translate here, so the APK contract and the
picker contract stay independent and neither has to flinch when the
other evolves.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


# Picker-shape key -> APK-shape key, per endpoint.
_PICKER_TO_APK = {
    "targetUsername": "username",
    "mediaCode":      "mediaId",
    "text":           "commentText",
}


@dataclass
class Endpoint:
    method: str
    path: str
    # Picker-shape params the hydrator writes, in the order they should
    # be lifted. Required ones must be present or we skip the row.
    picker_fields: list[str]
    required: list[str]
    # APK-shape constants we add (e.g. storyCount=5 default).
    extras: dict = field(default_factory=dict)


def spec_for_kind(kind: str) -> Endpoint | None:
    if kind in ("follow", "follows"):
        return Endpoint(
            "POST", "/instagram/engage/follow",
            picker_fields=["targetUsername"], required=["targetUsername"],
        )
    if kind in ("unfollow",):
        return Endpoint(
            "POST", "/instagram/engage/unfollow",
            picker_fields=["targetUsername"], required=["targetUsername"],
        )
    if kind in ("like", "likes"):
        return Endpoint(
            "POST", "/instagram/engage/like",
            picker_fields=["mediaCode"], required=["mediaCode"],
        )
    if kind in ("comment", "comments"):
        return Endpoint(
            "POST", "/instagram/engage/comment",
            picker_fields=["mediaCode", "text"],
            required=["mediaCode", "text"],
        )
    if kind in ("story", "stories", "view_stories"):
        # APK takes ONE username per call; picker emits a list of up
        # to 3. Dispatcher uses the first; if downstream wants all
        # three viewed, enqueue three queue rows upstream.
        return Endpoint(
            "POST", "/instagram/engage/view_stories",
            picker_fields=["usernames"], required=["usernames"],
            extras={"storyCount": 5},
        )
    if kind in ("scroll_reels",):
        return Endpoint(
            "POST", "/instagram/engage/scroll_reels",
            picker_fields=[], required=[],
            extras={"watchCount": 5},
        )
    if kind in ("check_session",):
        return Endpoint(
            "GET", "/instagram/engage/check_session",
            picker_fields=[], required=[],
        )
    return None


def build_payload(
    endpoint: Endpoint, clone_package: str, action_params: dict,
) -> tuple[dict | None, list[str]]:
    """Return (payload | None, missing_fields) in APK shape."""
    payload: dict = {"clonePackage": clone_package}
    missing: list[str] = []

    for field_name in endpoint.picker_fields:
        val = action_params.get(field_name) or action_params.get(_snake(field_name))
        if val is None:
            if field_name in endpoint.required:
                missing.append(field_name)
            continue

        # Special case: view_stories takes one `username`, picker hands
        # us an array under `usernames`.
        if field_name == "usernames":
            if isinstance(val, list) and val:
                payload["username"] = val[0]
            elif isinstance(val, str):
                payload["username"] = val
            else:
                missing.append(field_name)
            continue

        apk_key = _PICKER_TO_APK.get(field_name, field_name)
        payload[apk_key] = val

    if missing:
        return None, missing

    for k, v in endpoint.extras.items():
        payload.setdefault(k, v)
    return payload, []


def _snake(s: str) -> str:
    out = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def dumps(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")
