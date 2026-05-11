"""
IGStoryAgent — Full Instagram story management via Companion APK accessibility service.

Covers:
    - Standard story post with optional poll/question sticker injection
    - Story + highlight reel
    - Close Friends story
    - Story with link sticker (OF CTA)
    - Mother→child repost with per-child visual variation (the killer feature)

Architecture (mirrors IGForegroundPostAgent):
    1. ADB push media file → /sdcard/DCIM/PhantomFleet/<uuid>.<ext>
    2. Trigger MediaScanner via APK endpoint
    3. POST /instagram/story + optional sticker injection
    4. Optional: add link sticker, close friends, highlight
    5. ADB rm staging file (always — success or failure)

Mother→child drop:
    1. Download mother's story frame to temp file
    2. For each child:
       a. POST /media/transform (per-child visual variation seeded by accountId+postIndex)
       b. ADB push transformed frame + MediaScanner
       c. POST /instagram/story + OF link sticker
       d. LogNormal stagger before next child (NEVER fixed sleep)
    3. Audit log per child

Fleet-scale detection notes (CLAUDE.md 20K account thought experiment):
    - Visual transform: seeded by hash(accountId + postIndex) → every child gets a
      unique image. No two accounts share pixel hash, colour histogram, or file size.
    - Mother→child stagger is LogNormal, not fixed — histogram is log-normal bell curve.
    - Story cap is code-enforced at 5/day.

Daily hard caps (code-enforced):
    STORY: max 5 per account per day
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import secrets
import tempfile
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

_DAILY_STORY_CAP: int = 5

# ---------------------------------------------------------------------------
# Staging directory (shared with IGForegroundPostAgent)
# ---------------------------------------------------------------------------

_STAGING_DIR = "/sdcard/DCIM/PhantomFleet"


# ---------------------------------------------------------------------------
# Mother→child stagger
# ---------------------------------------------------------------------------

_DEFAULT_STAGGER_MEAN_SEC: float = 120.0
_STAGGER_SIGMA: float = 0.4
# Minimum same-phone gap — two accounts on the same phone never post within 90s
_MIN_PHONE_SERIAL_GAP_SEC: float = 90.0


# ---------------------------------------------------------------------------
# Task input types
# ---------------------------------------------------------------------------

@dataclass
class IGMotherChildDropTask:
    """Task for the mother→child story drop flow."""
    mother_account_id:   str
    child_account_ids:   list[str]
    story_media_url:     str            # URL of mother's story frame to download
    of_link:             str            # OF link to add as sticker on every child post
    phone_serial:        str
    phone_ip:            str
    clone_packages:      dict[str, str] # {account_id: clone_package}
    apk_port:            int = 8090
    stagger_seconds_mean: float = _DEFAULT_STAGGER_MEAN_SEC
    stories_today:       dict[str, int] = field(default_factory=dict)   # {account_id: count}


@dataclass
class IGStoryTask:
    """Validated, normalised input for one IGStoryAgent run."""
    account_id:      str
    phone_serial:    str
    clone_package:   str
    phone_ip:        str
    media_files:     list[str]
    apk_port:        int = 8090
    daily_counts:    dict[str, int] = field(default_factory=dict)
    # Sticker parameters — all optional
    poll:            Optional[dict] = None            # {"question", "option1", "option2"}
    question_prompt: Optional[str]  = None
    # New story features
    of_link:         Optional[str]  = None            # link sticker URL
    add_to_highlight: Optional[str] = None            # highlight reel name
    close_friends:   bool = False


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IGStoryAgent:
    """
    Posts Instagram stories via the Companion APK, with optional poll and
    question sticker injection.

    Never uses Meta's third-party media upload API.  All posting goes through
    the physical phone gallery → accessibility service path.

    Usage:
        agent = IGStoryAgent()
        result = await agent.run_session(task, phone_controller, slot_lock)
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        # http_client is injectable for testing; real usage creates one per run
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_session(
        self,
        task: IGStoryTask,
        phone_controller: PhoneController,
        slot_lock: PhoneSlotLock,
    ) -> WorkerResult:
        """
        Execute a story-posting session for one account on one phone.

        Steps:
            1. Validate inputs
            2. Enforce daily cap (code-level)
            3. Require proxy verification
            4. Acquire foreground lock
            5. Pre-post human behaviour delay
            6. For each media file:
               a. ADB push → MediaScanner → compose dwell → post story
               b. If poll provided:           POST /instagram/story/add_poll
               c. If question_prompt provided: POST /instagram/story/add_question
               d. Cleanup staging file (always)
            7. Release foreground lock
            8. Return WorkerResult
        """
        errors:          list[str] = []
        posts_submitted: int       = 0
        posts_failed:    int       = 0
        poll_added:      bool      = False
        question_added:  bool      = False

        # ------------------------------------------------------------------
        # 1. Validate inputs
        # ------------------------------------------------------------------
        validate_errors = _validate_task(task)
        if validate_errors:
            for e in validate_errors:
                log.error("[%s] validation error: %s", task.account_id, e)
            return _failure_result(task, validate_errors)

        # ------------------------------------------------------------------
        # 2. Daily cap check (code-enforced)
        # ------------------------------------------------------------------
        already_posted = task.daily_counts.get("story", 0)
        remaining = _DAILY_STORY_CAP - already_posted
        if remaining <= 0:
            msg = (
                f"daily_cap_reached:story:"
                f"{already_posted}/{_DAILY_STORY_CAP} for account {task.account_id}"
            )
            log.warning("[%s] %s", task.account_id, msg)
            return _failure_result(task, [msg])

        media_files = task.media_files[:remaining]
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
            # 5. Pre-post human behaviour delay
            # ------------------------------------------------------------------
            await human_post_behavior.pre_post_browse_delay()

            apk_base_url = f"http://{task.phone_ip}:{task.apk_port}"

            async with (self._http_client or httpx.AsyncClient(timeout=30.0)) as client:
                for i, media_file in enumerate(media_files):
                    staged_path: Optional[str] = None
                    try:
                        # a) ADB push to gallery staging dir
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

                        # c) Compose dwell before opening story editor
                        await human_post_behavior.compose_dwell()

                        if human_post_behavior.should_rethink():
                            log.debug("[%s] rethink pause triggered", task.account_id)
                            await human_post_behavior.rethink_pause()

                        # d) Open story editor + select media (stops before final send)
                        log.info(
                            "[%s] opening story editor for %s",
                            task.account_id, os.path.basename(media_file),
                        )
                        story_open_resp = await client.post(
                            f"{apk_base_url}/instagram/story",
                            json={
                                "mediaPath":    staged_path,
                                "caption":      "",
                                "accountId":    task.account_id,
                                "clonePackage": task.clone_package,
                                "postType":     "STORY",
                            },
                        )
                        story_open_resp.raise_for_status()
                        story_open_data = story_open_resp.json()

                        if not story_open_data.get("success"):
                            err = story_open_data.get("error", "unknown_apk_error")
                            log.warning("[%s] APK story open failed: %s", task.account_id, err)
                            errors.append(f"story_{i}:apk_error:{err}")
                            posts_failed += 1
                            continue

                        # e) Inject poll sticker if provided
                        if task.poll is not None:
                            poll_resp = await client.post(
                                f"{apk_base_url}/instagram/story/add_poll",
                                json={
                                    "question": task.poll["question"],
                                    "option1":  task.poll["option1"],
                                    "option2":  task.poll["option2"],
                                },
                            )
                            poll_resp.raise_for_status()
                            poll_ok = poll_resp.json().get("success", False)
                            if poll_ok:
                                poll_added = True
                                log.info("[%s] poll sticker added", task.account_id)
                            else:
                                log.warning(
                                    "[%s] poll sticker failed — continuing without it",
                                    task.account_id,
                                )
                                errors.append(f"story_{i}:poll_sticker_failed")

                        # f) Inject question sticker if provided
                        if task.question_prompt is not None:
                            q_resp = await client.post(
                                f"{apk_base_url}/instagram/story/add_question",
                                json={"prompt": task.question_prompt},
                            )
                            q_resp.raise_for_status()
                            q_ok = q_resp.json().get("success", False)
                            if q_ok:
                                question_added = True
                                log.info("[%s] question sticker added", task.account_id)
                            else:
                                log.warning(
                                    "[%s] question sticker failed — continuing without it",
                                    task.account_id,
                                )
                                errors.append(f"story_{i}:question_sticker_failed")

                        posts_submitted += 1
                        log.info(
                            "[%s] story %d/%d submitted",
                            task.account_id, i + 1, len(media_files),
                        )

                        # g) Inter-post delay if more stories remain
                        if i < len(media_files) - 1:
                            await human_post_behavior.inter_post_delay()

                    except ADBCommandFailed as exc:
                        err = f"story_{i}:adb_error:{exc}"
                        log.error("[%s] %s", task.account_id, err)
                        errors.append(err)
                        posts_failed += 1

                    except httpx.HTTPError as exc:
                        err = f"story_{i}:http_error:{exc}"
                        log.error("[%s] %s", task.account_id, err)
                        errors.append(err)
                        posts_failed += 1

                    except Exception as exc:
                        err = f"story_{i}:unexpected:{type(exc).__name__}:{exc}"
                        log.exception("[%s] unexpected error at story %d", task.account_id, i)
                        errors.append(err)
                        posts_failed += 1

                    finally:
                        # Always delete staging file — success OR failure
                        if staged_path:
                            await _delete_staging_file(
                                phone_controller, staged_path, task.account_id,
                            )

        finally:
            slot_lock.release_foreground()
            log.debug("[%s] foreground lock released", task.account_id)

        return WorkerResult(
            task_id    = f"ig_story_{task.account_id}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = posts_submitted > 0,
            error      = "; ".join(errors) if errors else None,
            data       = {
                "posts_submitted": posts_submitted,
                "posts_failed":    posts_failed,
                "errors":          errors,
                "poll_added":      poll_added,
                "question_added":  question_added,
            },
        )

    # ------------------------------------------------------------------
    # post_story — single story with link sticker, close friends, highlight
    # ------------------------------------------------------------------

    async def post_story(
        self,
        task: IGStoryTask,
        phone_controller: PhoneController,
        slot_lock: PhoneSlotLock,
    ) -> WorkerResult:
        """
        Post one story for one account with full feature support.

        Supports: link sticker, close friends audience, add to highlight.
        Delegates to run_session for the base story post + stickers,
        then calls additional APK endpoints for the extended features.

        Daily cap is enforced at 5 stories/day (code-enforced).
        Staging file is deleted in a try/finally block — always cleaned up.
        """
        # Validate daily cap
        already_posted = task.daily_counts.get("story", 0)
        if already_posted >= _DAILY_STORY_CAP:
            msg = f"daily_cap_reached:story:{already_posted}/{_DAILY_STORY_CAP} for {task.account_id}"
            log.warning("[%s] %s", task.account_id, msg)
            return _failure_result(task, [msg])

        if not task.media_files:
            return _failure_result(task, ["media_files is empty"])

        phone_controller.require_proxy()

        acquired = await slot_lock.acquire_foreground("instagram")
        if not acquired:
            return _failure_result(task, [f"foreground_lock_timeout:phone={task.phone_serial}"])

        apk_base_url = f"http://{task.phone_ip}:{task.apk_port}"
        staged_path: Optional[str] = None
        posts_submitted = 0
        errors: list[str] = []

        try:
            media_file = task.media_files[0]  # post_story handles one file per call
            staged_path = _make_remote_path(media_file)
            log.info("[%s] adb_push %s → %s", task.account_id, media_file, staged_path)
            await phone_controller.adb_push(media_file, staged_path)

            async with (self._http_client or httpx.AsyncClient(timeout=30.0)) as client:

                # MediaScanner
                (await client.post(f"{apk_base_url}/media/scan", json={"path": staged_path})).raise_for_status()

                # Compose dwell
                await human_post_behavior.compose_dwell()

                # Post the story
                log.info("[%s] posting story media=%s", task.account_id, os.path.basename(media_file))
                resp = await client.post(
                    f"{apk_base_url}/instagram/story",
                    json={
                        "mediaPath":    staged_path,
                        "caption":      "",
                        "accountId":    task.account_id,
                        "clonePackage": task.clone_package,
                        "postType":     "STORY",
                    },
                )
                resp.raise_for_status()
                story_data = resp.json()

                if not story_data.get("success"):
                    err = story_data.get("error", "unknown_apk_story_error")
                    errors.append(f"apk_error:{err}")
                else:
                    posts_submitted = 1

                    # Optional: OF link sticker
                    if task.of_link:
                        lr = await client.post(
                            f"{apk_base_url}/instagram/story/add_link_sticker",
                            json={"url": task.of_link, "stickerLabel": "Subscribe"},
                        )
                        if not lr.is_success or not lr.json().get("success"):
                            errors.append("link_sticker_failed")

                    # Optional: close friends
                    if task.close_friends:
                        cfr = await client.post(
                            f"{apk_base_url}/instagram/story/close_friends",
                            json={
                                "mediaPath":    staged_path,
                                "caption":      "",
                                "clonePackage": task.clone_package,
                            },
                        )
                        if not cfr.is_success or not cfr.json().get("success"):
                            errors.append("close_friends_failed")

                    # Optional: add to highlight
                    if task.add_to_highlight:
                        hr = await client.post(
                            f"{apk_base_url}/instagram/story/add_to_highlight",
                            json={"highlightName": task.add_to_highlight, "createIfMissing": True},
                        )
                        if not hr.is_success or not hr.json().get("success"):
                            errors.append("highlight_failed")

        except ADBCommandFailed as exc:
            errors.append(f"adb_error:{exc}")
        except httpx.HTTPError as exc:
            errors.append(f"http_error:{exc}")
        except Exception as exc:
            log.exception("[%s] unexpected error in post_story", task.account_id)
            errors.append(f"unexpected:{type(exc).__name__}:{exc}")
        finally:
            if staged_path:
                await _delete_staging_file(phone_controller, staged_path, task.account_id)
            slot_lock.release_foreground()

        return WorkerResult(
            task_id    = f"ig_story_{task.account_id}",
            platform   = "instagram",
            account_id = task.account_id,
            success    = posts_submitted > 0,
            error      = "; ".join(errors) if errors else None,
            data       = {
                "action":          "story_post",
                "posts_submitted": posts_submitted,
                "errors":          errors,
            },
        )

    # ------------------------------------------------------------------
    # run_mother_child_drop — the killer feature
    # ------------------------------------------------------------------

    async def run_mother_child_drop(
        self,
        task: IGMotherChildDropTask,
        phone_controller: PhoneController,
    ) -> WorkerResult:
        """
        Mother→child story drop with per-child visual variation.

        1. Download mother's story frame from task.story_media_url
        2. For each child account:
           a. POST /media/transform to APK — unique image per child
              (seeded by accountId + postIndex — deterministic, reproducible)
           b. ADB push transformed file to phone gallery
           c. Trigger MediaScanner
           d. POST /instagram/story + OF link sticker
           e. Sleep LogNormal(mean=ln(stagger_mean), σ=0.4) before next child
        3. Log all posts for audit

        Anti-fingerprint guarantees (CLAUDE.md 20K account rule):
            - Every child gets a visually unique image (pixel hash differs)
            - Stagger is LogNormal, not fixed (histogram is log-normal)
            - Same-phone minimum gap ≥90s enforced by code

        Returns:
            WorkerResult with data.children_posted and data.errors.
        """
        task_id = f"ig_mother_child_drop_{task.mother_account_id}"
        errors: list[str] = []
        children_posted = 0

        if not task.child_account_ids:
            return WorkerResult(
                task_id=task_id, platform="instagram",
                account_id=task.mother_account_id, success=False,
                error="child_account_ids is empty", data={},
            )

        # Enforce per-child daily caps (code-enforced)
        eligible_children = [
            acct for acct in task.child_account_ids
            if task.stories_today.get(acct, 0) < _DAILY_STORY_CAP
        ]
        skipped = len(task.child_account_ids) - len(eligible_children)
        if skipped:
            log.info("[%s] skipping %d children at daily cap", task.mother_account_id, skipped)
        if not eligible_children:
            return WorkerResult(
                task_id=task_id, platform="instagram",
                account_id=task.mother_account_id, success=False,
                error="all_children_at_daily_cap", data={"skipped_cap": skipped},
            )

        phone_controller.require_proxy()

        apk_base_url = f"http://{task.phone_ip}:{task.apk_port}"

        # Download the mother's story frame to a local temp file
        source_path: Optional[str] = None
        try:
            source_path = await _download_story_frame(task.story_media_url, task.mother_account_id)
        except Exception as exc:
            err = f"download_failed:{exc}"
            log.error("[%s] %s", task.mother_account_id, err)
            return WorkerResult(
                task_id=task_id, platform="instagram",
                account_id=task.mother_account_id, success=False,
                error=err, data={},
            )

        log.info(
            "[%s] starting mother→child drop: %d children stagger_mean=%.0fs",
            task.mother_account_id, len(eligible_children), task.stagger_seconds_mean,
        )

        try:
            async with (self._http_client or httpx.AsyncClient(timeout=60.0)) as client:
                for i, account_id in enumerate(eligible_children):
                    clone_package = task.clone_packages.get(account_id, "")
                    if not clone_package:
                        errors.append(f"no_clone_package:{account_id}")
                        continue

                    child_remote_input: Optional[str] = None
                    child_remote_output: Optional[str] = None

                    try:
                        # a. Push source frame to phone so APK can read it
                        child_remote_input  = _make_remote_path(source_path)
                        child_remote_output = f"{_STAGING_DIR}/t_{uuid.uuid4().hex}.jpg"
                        await phone_controller.adb_push(source_path, child_remote_input)

                        # a. Apply visual transform on-device
                        transform_resp = await client.post(
                            f"{apk_base_url}/media/transform",
                            json={
                                "inputPath":  child_remote_input,
                                "outputPath": child_remote_output,
                                "accountId":  account_id,
                                "postIndex":  task.stories_today.get(account_id, 0),
                            },
                        )
                        transform_resp.raise_for_status()
                        transform_data = transform_resp.json()

                        # Clean up raw source push regardless of transform success
                        await _delete_staging_file(phone_controller, child_remote_input, account_id)
                        child_remote_input = None

                        if not transform_data.get("ok"):
                            errors.append(f"transform_failed:{account_id}")
                            continue

                        # b. Trigger MediaScanner on transformed file
                        (await client.post(
                            f"{apk_base_url}/media/scan",
                            json={"path": child_remote_output},
                        )).raise_for_status()

                        # c. Post story via APK
                        log.info(
                            "[%s] posting story for child %s (%d/%d)",
                            task.mother_account_id, account_id, i + 1, len(eligible_children),
                        )
                        story_resp = await client.post(
                            f"{apk_base_url}/instagram/story",
                            json={
                                "mediaPath":    child_remote_output,
                                "caption":      "",
                                "accountId":    account_id,
                                "clonePackage": clone_package,
                                "postType":     "STORY",
                            },
                        )
                        story_resp.raise_for_status()
                        story_data = story_resp.json()

                        if not story_data.get("success"):
                            err_msg = story_data.get("error", "unknown")
                            errors.append(f"child_story_failed:{account_id}:{err_msg}")
                        else:
                            children_posted += 1

                            # d. Add OF link sticker to each child's story
                            link_resp = await client.post(
                                f"{apk_base_url}/instagram/story/add_link_sticker",
                                json={"url": task.of_link, "stickerLabel": "Subscribe"},
                            )
                            if not link_resp.is_success or not link_resp.json().get("success"):
                                errors.append(f"link_sticker_failed:{account_id}")

                            log.info(
                                "[%s] child %s posted (%d/%d)",
                                task.mother_account_id, account_id,
                                children_posted, len(eligible_children),
                            )

                    except ADBCommandFailed as exc:
                        errors.append(f"adb_error:{account_id}:{exc}")
                    except httpx.HTTPError as exc:
                        errors.append(f"http_error:{account_id}:{exc}")
                    except Exception as exc:
                        log.exception("[%s] error for child %s", task.mother_account_id, account_id)
                        errors.append(f"unexpected:{account_id}:{type(exc).__name__}:{exc}")
                    finally:
                        if child_remote_input:
                            await _delete_staging_file(phone_controller, child_remote_input, account_id)
                        if child_remote_output:
                            await _delete_staging_file(phone_controller, child_remote_output, account_id)

                    # e. Stagger: LogNormal, NOT fixed sleep — CLAUDE.md requirement
                    if i < len(eligible_children) - 1:
                        stagger_sec = _lognormal_sample(
                            mean=task.stagger_seconds_mean,
                            sigma=_STAGGER_SIGMA,
                        )
                        # Enforce ≥90s same-phone minimum gap
                        stagger_sec = max(stagger_sec, _MIN_PHONE_SERIAL_GAP_SEC)
                        log.debug(
                            "[%s] stagger before next child: %.1fs",
                            task.mother_account_id, stagger_sec,
                        )
                        await asyncio.sleep(stagger_sec)

        finally:
            if source_path and os.path.exists(source_path):
                try:
                    os.unlink(source_path)
                except OSError:
                    pass

        log.info(
            "[%s] mother→child drop complete: %d/%d posted",
            task.mother_account_id, children_posted, len(eligible_children),
        )

        return WorkerResult(
            task_id    = task_id,
            platform   = "instagram",
            account_id = task.mother_account_id,
            success    = children_posted > 0,
            error      = "; ".join(errors) if errors else None,
            data       = {
                "action":          "mother_child_drop",
                "children_posted": children_posted,
                "children_total":  len(eligible_children),
                "skipped_cap":     skipped,
                "errors":          errors,
            },
        )

    # ------------------------------------------------------------------
    # manage_highlights
    # ------------------------------------------------------------------

    async def manage_highlights(
        self,
        task: IGStoryTask,
        phone_controller: PhoneController,
        slot_lock: PhoneSlotLock,
        action: str = "create",
        highlight_name: str = "",
    ) -> WorkerResult:
        """
        Creates, adds to, or renames highlight reels.

        Args:
            action:          "create" | "add_story" | "rename"
            highlight_name:  Name for the highlight operation.
        """
        task_id = f"ig_highlight_{task.account_id}_{action}"

        if not highlight_name:
            return _failure_result(task, ["highlight_name is empty"])

        phone_controller.require_proxy()
        acquired = await slot_lock.acquire_foreground("instagram")
        if not acquired:
            return _failure_result(task, [f"foreground_lock_timeout:phone={task.phone_serial}"])

        apk_base_url = f"http://{task.phone_ip}:{task.apk_port}"
        errors: list[str] = []
        ok = False

        try:
            async with (self._http_client or httpx.AsyncClient(timeout=30.0)) as client:
                if action in ("create", "add_story"):
                    resp = await client.post(
                        f"{apk_base_url}/instagram/story/add_to_highlight",
                        json={"highlightName": highlight_name, "createIfMissing": True},
                    )
                    resp.raise_for_status()
                    ok = resp.json().get("success", False)
                    if not ok:
                        errors.append(f"highlight_{action}_failed")
                else:
                    log.warning("[%s] highlight rename not yet implemented in APK", task.account_id)
                    errors.append("highlight_rename_not_implemented")
        except httpx.HTTPError as exc:
            errors.append(f"http_error:{exc}")
        except Exception as exc:
            errors.append(f"unexpected:{type(exc).__name__}:{exc}")
        finally:
            slot_lock.release_foreground()

        return WorkerResult(
            task_id    = task_id,
            platform   = "instagram",
            account_id = task.account_id,
            success    = ok,
            error      = "; ".join(errors) if errors else None,
            data       = {"action": f"highlight_{action}", "highlight_name": highlight_name, "errors": errors},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_task(task: IGStoryTask) -> list[str]:
    """Return a list of validation error strings, empty if all valid."""
    errors: list[str] = []

    if not task.media_files:
        errors.append("media_files is empty")

    valid_exts = frozenset({".jpg", ".jpeg", ".png", ".mp4", ".mov"})
    for path in task.media_files:
        ext = os.path.splitext(path)[1].lower()
        if ext not in valid_exts:
            errors.append(
                f"invalid_extension:{ext!r} for story (path={path!r})"
            )

    if not task.account_id:
        errors.append("account_id is empty")
    if not task.phone_serial:
        errors.append("phone_serial is empty")
    if not task.clone_package:
        errors.append("clone_package is empty")
    if not task.phone_ip:
        errors.append("phone_ip is empty")

    # Validate poll dict keys if provided
    if task.poll is not None:
        for key in ("question", "option1", "option2"):
            if not task.poll.get(key):
                errors.append(f"poll.{key} is missing or empty")

    return errors


def _make_remote_path(local_path: str) -> str:
    """
    Build the on-device staging path for a media file.

    Uses uuid4 hex so no two staging files ever collide, and so the filename
    is not predictable from the local path (prevents cross-account patterns
    if multiple accounts share a phone).
    """
    ext = os.path.splitext(local_path)[1].lower() or ".jpg"
    return f"{_STAGING_DIR}/{uuid.uuid4().hex}{ext}"


async def _delete_staging_file(
    phone_controller: PhoneController,
    remote_path: str,
    account_id: str,
) -> None:
    """
    Delete the staging file from the device's DCIM folder.

    Called in a finally block — always runs whether the post succeeded or
    failed.  Suppresses errors so cleanup failures don't mask the original
    post error.
    """
    try:
        await phone_controller.adb_shell(f"rm -f {remote_path}")
        log.debug("[%s] deleted staging file: %s", account_id, remote_path)
    except Exception as exc:
        log.warning(
            "[%s] failed to delete staging file %s: %s",
            account_id, remote_path, exc,
        )


def _failure_result(task: IGStoryTask, errors: list[str]) -> WorkerResult:
    return WorkerResult(
        task_id    = f"ig_story_{task.account_id}",
        platform   = "instagram",
        account_id = task.account_id,
        success    = False,
        error      = "; ".join(errors),
        data       = {
            "posts_submitted": 0,
            "posts_failed":    0,
            "errors":          errors,
            "poll_added":      False,
            "question_added":  False,
        },
    )


async def _download_story_frame(url: str, account_id: str) -> str:
    """
    Download a story frame from a URL to a local temp file.
    Returns the absolute path. Caller must delete when done.
    """
    tmpdir = tempfile.gettempdir()
    tmp_path = os.path.join(tmpdir, f"phantom_{account_id}_{uuid.uuid4().hex}.jpg")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        with open(tmp_path, "wb") as f:
            f.write(resp.content)
    log.debug("[%s] downloaded story frame to %s (%d bytes)", account_id, tmp_path, len(resp.content))
    return tmp_path


def _lognormal_sample(mean: float, sigma: float) -> float:
    """
    Sample from LogNormal(mean, sigma) using secrets-based entropy.

    Using secrets.randbits ensures stagger timing is non-deterministic
    (timing must NOT be reproducible — each run needs independent randomness
    to prevent temporal cluster fingerprints at fleet scale).

    mean  — desired mean in the original (non-log) domain
    sigma — shape parameter; 0.4 matches CLAUDE.md specification
    """
    import random as _random
    rng = _random.Random(secrets.randbits(64))
    mu = math.log(mean) - 0.5 * sigma ** 2
    z = rng.gauss(0.0, 1.0)
    value = math.exp(mu + sigma * z)
    # Clamp to [0.3×mean, 3×mean] — prevent extreme outliers
    return float(max(mean * 0.3, min(mean * 3.0, value)))
