"""
Scheduler Executor — fires pro_schedule_queue posts when scheduled_at arrives.

This is the background loop that makes Scheduler Pro actually work.
Without this, the calendar gets populated but nothing ever posts.

Architecture:
    - Runs as an asyncio task started at app lifespan
    - Polls every 60s for posts due in the next window
    - For each due post: fetch account session → generate caption if needed → post
    - Marks status='posted' or 'failed' with error message
    - Caption generation: ai mode → ThreadsContentGenerator, template mode → format string

Caption modes:
    ai          — generate via ThreadsContentGenerator (uses persona from groups)
    template    — use caption_template with {date}, {username} substitution
    manual      — caption was pre-filled in the queue row, use as-is

Fleet-scale note:
    - Posts are spread across the day by the seeded posting time generator in scheduler_pro.py
    - Each account posts at a different seeded time → no fleet-wide posting cluster
    - Caption is unique per account via ThreadsContentGenerator's seeded content type selection
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("phantom_fleet.scheduler_executor")


class SchedulerExecutor:
    """
    Background loop that polls and executes due Scheduler Pro posts.

    Usage:
        executor = SchedulerExecutor(pool)
        await executor.start()   # at app lifespan
        await executor.stop()    # at shutdown
    """

    def __init__(self, pool, poll_interval_sec: int = 60) -> None:
        self._pool = pool
        self._poll_interval = poll_interval_sec
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="scheduler_executor")
        log.info("SchedulerExecutor started (poll every %ds)", self._poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("SchedulerExecutor stopped")

    # ------------------------------------------------------------------
    # Main poll loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                log.error("SchedulerExecutor tick error: %s", exc)
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        """Find all posts due in the last 5 minutes and execute them."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=5)   # catch anything we may have missed

        async with self._pool.acquire() as conn:
            due_posts = await conn.fetch(
                """
                SELECT q.*, ps.caption_mode, ps.caption_template, ps.vault_model,
                       ps.post_type, ps.group_id,
                       a.id AS account_db_id, a.username, a.sessionid, a.csrftoken,
                       a.user_id AS ig_user_id, a.mid, a.proxy_id, a.warmup_phase
                FROM pro_schedule_queue q
                JOIN pro_schedules ps ON ps.id = q.schedule_id
                JOIN accounts a ON a.id = q.account_id
                WHERE q.status = 'pending'
                  AND q.scheduled_at >= $1
                  AND q.scheduled_at <= $2
                  AND ps.status = 'active'
                  AND a.status = 'active'
                ORDER BY q.scheduled_at ASC
                LIMIT 50
                """,
                window_start, now,
            )

        if not due_posts:
            return

        log.info("SchedulerExecutor: %d posts due", len(due_posts))

        # Execute concurrently but cap at 5 simultaneous posts
        sem = asyncio.Semaphore(5)
        tasks = [asyncio.create_task(self._execute_post(dict(p), sem)) for p in due_posts]
        await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # Execute one queued post
    # ------------------------------------------------------------------

    async def _execute_post(self, post: dict, sem: asyncio.Semaphore) -> None:
        async with sem:
            queue_id = post["id"]
            account_id = post["account_id"]
            username = post.get("username", account_id)

            # Mark as processing
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE pro_schedule_queue SET status='processing' WHERE id=$1", queue_id
                )

            try:
                caption = await self._get_caption(post)
                if not caption:
                    caption = "✨"  # absolute fallback

                # Build session + client
                from .instagram_client import IGSession
                from .threads_client import ThreadsClient
                from .hybrid_runner import PlatformHeaders

                proxy_url: Optional[str] = None
                if post.get("proxy_id"):
                    async with self._pool.acquire() as conn:
                        proxy = await conn.fetchrow("SELECT * FROM proxies WHERE id=$1", post["proxy_id"])
                        if proxy:
                            proxy_url = f"socks5://{proxy['host']}:{proxy['port']}"

                session = IGSession(
                    account_id=str(account_id),
                    ig_user_id=post.get("ig_user_id", ""),
                    username=username,
                    session_id=post.get("sessionid", ""),
                    csrftoken=post.get("csrftoken", ""),
                    mid=post.get("mid", ""),
                    ds_user_id=post.get("ig_user_id", ""),
                    headers=PlatformHeaders(),
                )

                async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
                    resp = await client.post_text(caption)

                media_id = resp.get("media", {}).get("pk") or resp.get("media_id", "")

                async with self._pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE pro_schedule_queue
                        SET status='posted', posted_at=now(), caption=$1, media_id=$2
                        WHERE id=$3
                        """,
                        caption, str(media_id), queue_id,
                    )
                    await conn.execute(
                        """
                        INSERT INTO activity_log (account_id, action, target, status, message)
                        VALUES ($1, 'scheduled_post', $2, 'success', $3)
                        """,
                        account_id, str(media_id), caption[:100],
                    )

                log.info("[%s] Scheduled post fired (queue_id=%s)", username, queue_id)

            except Exception as exc:
                err_str = str(exc)[:500]
                log.warning("[%s] Scheduled post failed: %s", username, err_str)
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE pro_schedule_queue SET status='failed', error=$1 WHERE id=$2",
                        err_str, queue_id,
                    )
                    await conn.execute(
                        """
                        INSERT INTO activity_log (account_id, action, status, message)
                        VALUES ($1, 'scheduled_post', 'failed', $2)
                        """,
                        account_id, err_str,
                    )

    # ------------------------------------------------------------------
    # Caption generation
    # ------------------------------------------------------------------

    async def _get_caption(self, post: dict) -> str:
        """Generate or fetch caption based on caption_mode."""
        mode = post.get("caption_mode", "ai")

        # If caption was pre-filled in the queue row, use it
        if post.get("caption") and post["caption"].strip():
            return post["caption"].strip()

        if mode == "manual":
            return post.get("caption") or ""

        if mode == "template":
            template = post.get("caption_template") or ""
            # format_map with defaultdict avoids KeyError for unknown placeholders
            from collections import defaultdict
            return template.format_map(defaultdict(str, {
                "username": post.get("username", ""),
                "date":     datetime.now(timezone.utc).strftime("%B %d"),
            }))

        # ai mode — use ThreadsContentGenerator
        try:
            from ..agents.specialists.threads_content_generator import (
                ThreadsContentGenerator, PersonaContext
            )
            from datetime import date

            gen = ThreadsContentGenerator()

            # Pull persona from group if available
            persona = PersonaContext()
            if post.get("group_id"):
                async with self._pool.acquire() as conn:
                    group = await conn.fetchrow(
                        "SELECT * FROM groups WHERE id=$1", post["group_id"]
                    )
                    if group:
                        persona.name = group.get("name", "")
                        # link_in_bio is the Telegram funnel URL
                        if group.get("link_in_bio"):
                            persona.funnel_dest = group["link_in_bio"]

            # Pull learning context
            learning_context = ""
            try:
                from .learning_engine import get_learning_context
                lc = await get_learning_context(
                    self._pool,
                    context=f"threads_post_{post['account_id']}",
                    categories=["threads_post", "content_performance"],
                )
                learning_context = lc.get("prompt_text", "")
            except Exception:
                pass

            generated = await gen.generate_post(
                account_id=post["account_id"],
                persona=persona,
                date_iso=date.today().isoformat(),
                learning_context=learning_context,
            )
            return generated.text
        except Exception as exc:
            log.warning("Caption generation failed for %s: %s", post["account_id"], exc)
            return "✨"
