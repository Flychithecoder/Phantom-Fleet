"""
IGForegroundPostAgent — Posts Instagram grid posts, stories, and reels by
pushing media to the phone's gallery via ADB and driving the Instagram UI
through the Companion APK's AccessibilityService.

NEVER uses Meta's third-party media upload API. All posting goes through the
physical phone gallery → accessibility service path, which is indistinguishable
from a real user posting from their camera roll.

Architecture:
    1. ADB push media file → /sdcard/DCIM/PhantomFleet/<uuid>.<ext>
    2. Trigger MediaScanner via APK endpoint so gallery sees the file
    3. POST /instagram/post to the Companion APK's LocalHttpServer
       (APK opens IG clone, selects from gallery, types caption, posts)
    4. ADB rm staging file (always — success or failure)

Daily hard caps (code-enforced, NOT prompt-based):
    GRID:  max 3 per account per day
    STORY: max 5 per account per day
    REEL:  max 2 per account per day

Foreground lock:
    Only one account posts at a time per phone. The foreground lock is
    acquired before any IG UI action and released in a finally block.

Context keys (task.params):
    media_files    (list[str])   — local host paths to media files
    captions       (list[str])   — captions, one per media file
    post_type      (str)         — "grid", "story", or "reel"
    account_id     (str)         — Phantom Fleet account ID
    phone_serial   (str)         — ADB serial of the target phone
    clone_package  (str)         — e.g. com.instagram.android.clone1
    phone_ip       (str)         — LAN IP of the phone (for APK HTTP calls)
    apk_port       (int)         — APK HTTP server port (default 8090)
    daily_counts   (dict)        — {post_type: count_already_posted_today}
                                   used by the scheduler to enforce caps

Output keys (WorkerResult.data):
    posts_submitted  (int)
    posts_failed     (int)
    post_type        (str)
    errors           (list[str])
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx

from ...core import human_post_behavior
from ...core.hybrid_runner import PhoneSlotLock, WorkerResult
from ...core.phone_controller import ADBCommandFailed, PhoneController

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Daily hard caps — code-enforced, never configurable via prompt
# ---------------------------------------------------------------------------

_DAILY_CAPS: dict[str, int] = {
    "grid":  3,
    "story": 5,
    "reel":  2,
}

# ---------------------------------------------------------------------------
# Supported file extensions by post type
# ---------------------------------------------------------------------------

_VALID_EXTENSIONS: dict[str, frozenset[str]] = {
    "grid":  frozenset({".jpg", ".jpeg", ".png", ".mp4", ".mov"}),
    "story": frozenset({".jpg", ".jpeg", ".png", ".mp4", ".mov"}),
    "reel":  frozenset({".mp4", ".mov"}),
}


# ---------------------------------------------------------------------------
# Task input / output types
# ---------------------------------------------------------------------------

@dataclass
class IGPostTask:
    """Validated, normalised input for one IGForegroundPostAgent run."""
    account_id:    str
    phone_serial:  str
    clone_package: str
    phone_ip:      str
    post_type:     str                  # "grid", "story", "reel" (lowercase)
    media_files:   list[str]            # host-side absolute paths
    captions:      list[str]            # one per media file
    apk_port:      int = 8090
    daily_counts:  dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IGForegroundPostAgent:
    """
    Posts Instagram grid posts, stories, and reels by pushing media to the
    phone gallery and using the Companion APK accessibility service to post —
    identical to a real user posting from their camera roll.

    Never uses Meta's third-party media upload API.
    """

    STAGING_DIR = "/sdcard/DCIM/PhantomFleet"

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        # http_client is injectable for testing; real usage creates one per run
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(
        self,
        task: IGPostTask,
        phone_controller: PhoneController,
        slot_lock: PhoneSlotLock,
    ) -> WorkerResult:
        """
        Execute a posting session for one account on one phone.

        Steps:
            1. Validate inputs
            2. Enforce daily cap (code-level)
            3. Require proxy verification
            4. Acquire foreground lock (only one account posts at a time)
            5. Pre-post human behaviour delay
            6. For each (media_file, caption): push → scan → dwell → post → cleanup
            7. Release foreground lock
            8. Return WorkerResult

        Args:
            task:             Validated task parameters.
            phone_controller: PhoneController for ADB operations.
            slot_lock:        PhoneSlotLock for foreground exclusion.

        Returns:
            WorkerResult with posts_submitted, posts_failed, post_type, errors.
        """
        errors: list[str] = []
        posts_submitted = 0
        posts_failed    = 0

        # ------------------------------------------------------------------
        # 1. Validate inputs
        # ------------------------------------------------------------------
        validate_errors = _validate_task(task)
        if validate_errors:
            for e in validate_errors:
                log.error("[%s] validation error: %s", task.account_id, e)
            return _failure_result(task, validate_errors)

        # ------------------------------------------------------------------
        # 2. Daily cap check (code-enforced — not prompt-based)
        # ------------------------------------------------------------------
        already_posted = task.daily_counts.get(task.post_type, 0)
        cap = _DAILY_CAPS[task.post_type]
        remaining = cap - already_posted
        if remaining <= 0:
            msg = (
                f"daily_cap_reached:{task.post_type}:"
                f"{already_posted}/{cap} for account {task.account_id}"
            )
            log.warning("[%s] %s", task.account_id, msg)
            return _failure_result(task, [msg])

        # Slice to remaining quota
        media_files = task.media_files[:remaining]
        captions    = task.captions[:remaining]

        if len(media_files) < len(task.media_files):
            log.info(
                "[%s] truncated batch from %d to %d (daily cap)",
                task.account_id, len(task.media_files), len(media_files),
            )

        # ------------------------------------------------------------------
        # 3. Require proxy
        # ------------------------------------------------------------------
        phone_controller.require_proxy()

        # ------------------------------------------------------------------
        # 4. Acquire foreground lock
        # ------------------------------------------------------------------
        acquired = await slot_lock.acquire_foreground("instagram")
        if not acquired:
            msg = f"foreground_lock_timeout:phone={task.phone_serial}"
            log.error("[%s] %s", task.account_id, msg)
            return _failure_result(task, [msg])

        try:
            # ------------------------------------------------------------------
            # 5. Pre-post human behaviour
            # ------------------------------------------------------------------
            await human_post_behavior.pre_post_browse_delay()

            # ------------------------------------------------------------------
            # 6. Post each media file
            # ------------------------------------------------------------------
            apk_base_url = f"http://{task.phone_ip}:{task.apk_port}"

            async with (self._http_client or httpx.AsyncClient(timeout=30.0)) as client:
                for i, (media_file, caption) in enumerate(zip(media_files, captions)):
                    staged_path: Optional[str] = None
                    try:
                        # a) Push to gallery
                        staged_path = _make_remote_path(media_file)
                        log.info(
                            "[%s] adb_push %s → %s",
                            task.account_id, media_file, staged_path,
                        )
                        await phone_controller.adb_push(media_file, staged_path)

                        # b) Trigger MediaScanner
                        scan_resp = await client.post(
                            f"{apk_base_url}/media/scan",
                            json={"path": staged_path},
                        )
                        scan_resp.raise_for_status()

                        # c) Compose dwell (simulates opening compose screen)
                        await human_post_behavior.compose_dwell()

                        # d) Rethink pause (15% probability)
                        if human_post_behavior.should_rethink():
                            log.debug("[%s] rethink pause triggered", task.account_id)
                            await human_post_behavior.rethink_pause()

                        # e) Post via APK accessibility service
                        log.info(
                            "[%s] posting %s type=%s",
                            task.account_id, os.path.basename(media_file), task.post_type,
                        )
                        post_resp = await client.post(
                            f"{apk_base_url}/instagram/post",
                            json={
                                "mediaPath":    staged_path,
                                "caption":      caption,
                                "accountId":    task.account_id,
                                "clonePackage": task.clone_package,
                                "postType":     task.post_type.upper(),
                            },
                        )
                        post_resp.raise_for_status()
                        post_data = post_resp.json()

                        # f) Verify response
                        if not post_data.get("success"):
                            err = post_data.get("error", "unknown_apk_error")
                            log.warning("[%s] APK post failed: %s", task.account_id, err)
                            errors.append(f"post_{i}:apk_error:{err}")
                            posts_failed += 1
                        else:
                            log.info(
                                "[%s] post %d/%d succeeded",
                                task.account_id, i + 1, len(media_files),
                            )
                            posts_submitted += 1

                        # g) Inter-post delay if more posts remain
                        if i < len(media_files) - 1:
                            await human_post_behavior.inter_post_delay()

                    except ADBCommandFailed as exc:
                        err = f"post_{i}:adb_error:{exc}"
                        log.error("[%s] %s", task.account_id, err)
                        errors.append(err)
                        posts_failed += 1

                    except httpx.HTTPError as exc:
                        err = f"post_{i}:http_error:{exc}"
                        log.error("[%s] %s", task.account_id, err)
                        errors.append(err)
                        posts_failed += 1

                    except Exception as exc:
                        err = f"post_{i}:unexpected:{type(exc).__name__}:{exc}"
                        log.exception("[%s] unexpected error at post %d", task.account_id, i)
                        errors.append(err)
                        posts_failed += 1

                    finally:
                        # g) Always delete the staging file — success OR failure
                        if staged_path:
                            await _delete_staging_file(phone_controller, staged_path, task.account_id)

        finally:
            # ------------------------------------------------------------------
            # Release foreground lock — always, even on exception
            # ------------------------------------------------------------------
            slot_lock.release_foreground()
            log.debug("[%s] foreground lock released", task.account_id)

        return WorkerResult(
            task_id    = f"ig_post_{task.account_id}_{task.post_type}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = posts_submitted > 0,
            error      = "; ".join(errors) if errors else None,
            data       = {
                "posts_submitted": posts_submitted,
                "posts_failed":    posts_failed,
                "post_type":       task.post_type,
                "errors":          errors,
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_task(task: IGPostTask) -> list[str]:
    """Return a list of validation error strings, empty if all valid."""
    errors: list[str] = []

    if task.post_type not in _DAILY_CAPS:
        errors.append(
            f"invalid_post_type:{task.post_type!r} — must be one of {list(_DAILY_CAPS)}"
        )

    if not task.media_files:
        errors.append("media_files is empty")

    if len(task.media_files) != len(task.captions):
        errors.append(
            f"media_files ({len(task.media_files)}) and captions "
            f"({len(task.captions)}) length mismatch"
        )

    valid_exts = _VALID_EXTENSIONS.get(task.post_type, frozenset())
    for path in task.media_files:
        ext = os.path.splitext(path)[1].lower()
        if ext not in valid_exts:
            errors.append(
                f"invalid_extension:{ext!r} for post_type={task.post_type!r} "
                f"(path={path!r})"
            )

    if not task.account_id:
        errors.append("account_id is empty")
    if not task.phone_serial:
        errors.append("phone_serial is empty")
    if not task.clone_package:
        errors.append("clone_package is empty")
    if not task.phone_ip:
        errors.append("phone_ip is empty")

    return errors


def _make_remote_path(local_path: str) -> str:
    """
    Build the on-device staging path for a media file.

    Uses uuid4 hex so no two staging files ever collide, and so the
    filename is not predictable from the local path (prevents any
    cross-account pattern if multiple accounts share a phone).
    """
    ext = os.path.splitext(local_path)[1].lower() or ".jpg"
    return f"{IGForegroundPostAgent.STAGING_DIR}/{uuid.uuid4().hex}{ext}"


async def _delete_staging_file(
    phone_controller: PhoneController,
    remote_path: str,
    account_id: str,
) -> None:
    """
    Delete the staging file from the device's DCIM folder.

    Called in a finally block — always runs whether the post succeeded
    or failed. Suppresses errors so cleanup failures don't mask the
    original post error.
    """
    try:
        await phone_controller.adb_shell(f"rm -f {remote_path}")
        log.debug("[%s] deleted staging file: %s", account_id, remote_path)
    except Exception as exc:
        log.warning(
            "[%s] failed to delete staging file %s: %s",
            account_id, remote_path, exc,
        )


def _failure_result(task: IGPostTask, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id    = f"ig_post_{task.account_id}_{task.post_type}",
        platform   = "instagram",
        account_id = task.account_id,
        success    = False,
        error      = "; ".join(errors),
        data       = {
            "posts_submitted": 0,
            "posts_failed":    0,
            "post_type":       task.post_type,
            "errors":          errors,
        },
    )
