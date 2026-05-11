"""
IGActionDispatcher — routes IG specialist agent actions to the correct phone.

The dispatcher:
    1. Looks up which phone serial + clone_package an account is assigned to
    2. Gets (or creates) the PhoneController for that serial
    3. Calls PhoneController.execute_ig_action(action, **kwargs)
    4. Logs every call to the action_log table

Usage:
    dispatcher = IGActionDispatcher(fleet=phone_fleet, db=db_conn)
    result = await dispatcher.dispatch(
        account_id="acct_001",
        action="follow",
        username="target_user",
    )
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .phone_controller import PhoneFleet, PhoneController

logger = logging.getLogger("phantom.ig_dispatcher")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AccountNotMapped(KeyError):
    """Raised when an account_id has no phone/clone mapping registered."""


# ---------------------------------------------------------------------------
# Account mapping entry
# ---------------------------------------------------------------------------

class _AccountEntry:
    """Internal entry linking an account to a phone serial and clone package."""

    __slots__ = ("account_id", "phone_serial", "clone_package")

    def __init__(self, account_id: str, phone_serial: str, clone_package: str) -> None:
        self.account_id    = account_id
        self.phone_serial  = phone_serial
        self.clone_package = clone_package


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class IGActionDispatcher:
    """
    Routes Instagram automation actions to the physical phone assigned to
    each account.

    The mapping from account_id → (phone_serial, clone_package) must be
    loaded via ``load_account_map`` before dispatching.  All dispatch calls
    are fully async and safe to run concurrently across different accounts.

    Args:
        fleet: The ``PhoneFleet`` instance that manages all PhoneControllers.
        db:    Optional DB connection for persisting action logs. If None,
               logging goes only to the Python logger. The db object is
               expected to have an ``execute`` coroutine compatible with
               aiosqlite / asyncpg / databases-style APIs.
    """

    def __init__(self, fleet: PhoneFleet, db: Optional[Any] = None) -> None:
        self._fleet: PhoneFleet = fleet
        self._db    = db
        # account_id → _AccountEntry
        self._account_map: dict[str, _AccountEntry] = {}

    # ------------------------------------------------------------------
    # Account map management
    # ------------------------------------------------------------------

    async def load_account_map(self, accounts: list[dict]) -> None:
        """
        Populate the internal account map from a list of account dicts.

        Each dict must have:
            {
                "account_id":    str,   # unique account identifier
                "phone_serial":  str,   # ADB serial e.g. "192.168.1.42:5555"
                "clone_package": str,   # e.g. "com.instagram.android.clone_01"
            }

        Existing entries are overwritten if the same account_id appears again
        (supports hot-reload of assignments without restarting the process).

        Args:
            accounts: List of account assignment dicts.
        """
        loaded = 0
        for entry in accounts:
            account_id    = entry["account_id"]
            phone_serial  = entry["phone_serial"]
            clone_package = entry["clone_package"]

            self._account_map[account_id] = _AccountEntry(
                account_id    = account_id,
                phone_serial  = phone_serial,
                clone_package = clone_package,
            )

            # Ensure the phone is registered in the fleet (no-op if already present)
            self._fleet.register(phone_serial)
            loaded += 1

        logger.info("IGActionDispatcher: loaded %d account mappings", loaded)

    def get_dispatcher_for_account(self, account_id: str) -> tuple[str, str]:
        """
        Return ``(phone_serial, clone_package)`` for the given account.

        Raises:
            AccountNotMapped: if account_id is not in the mapping.
        """
        entry = self._account_map.get(account_id)
        if entry is None:
            raise AccountNotMapped(
                f"No phone mapping found for account_id={account_id!r}. "
                "Call load_account_map() first."
            )
        return entry.phone_serial, entry.clone_package

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        account_id: str,
        action: str,
        **kwargs: Any,
    ) -> dict:
        """
        Dispatch a single Instagram action for a specific account.

        Looks up the phone and clone package for ``account_id``, injects
        ``clone_pkg`` into kwargs, calls
        ``PhoneController.execute_ig_action(action, **kwargs)``, logs the
        result, and returns the result dict.

        Args:
            account_id: The Phantom Fleet account identifier.
            action:     Action name — one of: follow, unfollow, like, comment,
                        view_stories, scroll_reels, send_dm, check_session,
                        post, story, reel.
            **kwargs:   Action-specific parameters. ``clone_pkg`` is injected
                        automatically from the account mapping and must NOT be
                        supplied by the caller.

        Returns:
            The result dict from the Companion APK (e.g. ``{"success": true}``).

        Raises:
            AccountNotMapped:  account_id not in the mapping.
            ProxyNotVerified:  phone proxy gate not passed.
            APKCallFailed:     APK returned a non-2xx response.
            KeyError:          required kwarg missing for the chosen action.
            ValueError:        unknown action string.
        """
        phone_serial, clone_package = self.get_dispatcher_for_account(account_id)

        phone: PhoneController | None = self._fleet.get(phone_serial)
        if phone is None:
            # Phone was in the map but not yet in the fleet — register it now.
            phone = self._fleet.register(phone_serial)

        # Inject clone_pkg — callers should not supply it directly
        if "clone_pkg" in kwargs:
            logger.warning(
                "dispatch: clone_pkg was supplied directly for account %s — "
                "ignoring and using mapped value %s",
                account_id,
                clone_package,
            )
        kwargs["clone_pkg"] = clone_package

        started_at = datetime.now(tz=timezone.utc)
        result: dict = {}
        error: Optional[str] = None

        try:
            result = await phone.execute_ig_action(action, **kwargs)
        except Exception as exc:
            error = str(exc)
            logger.error(
                "IGActionDispatcher.dispatch error: account=%s action=%s error=%s",
                account_id, action, error,
            )
            raise
        finally:
            finished_at = datetime.now(tz=timezone.utc)
            await self._log_action(
                account_id  = account_id,
                phone_serial= phone_serial,
                action      = action,
                kwargs      = {k: v for k, v in kwargs.items() if k != "clone_pkg"},
                result      = result,
                error       = error,
                started_at  = started_at,
                finished_at = finished_at,
            )

        logger.debug(
            "dispatch: account=%s action=%s → success=%s",
            account_id, action, result.get("success"),
        )
        return result

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------

    async def dispatch_many(
        self,
        dispatches: list[dict],
        concurrency: int = 5,
    ) -> list[dict]:
        """
        Dispatch multiple actions concurrently, bounded by ``concurrency``.

        Each item in ``dispatches`` is a dict with keys:
            ``account_id``, ``action``, and any action-specific kwargs.

        Returns a list of result dicts in the same order as ``dispatches``.
        Individual failures are caught: the result dict for a failed dispatch
        will be ``{"success": False, "error": "<message>"}``.

        Args:
            dispatches:   List of dispatch descriptors.
            concurrency:  Max simultaneous dispatches (default 5).
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _guarded(item: dict) -> dict:
            account_id = item["account_id"]
            action     = item["action"]
            kwargs     = {k: v for k, v in item.items() if k not in ("account_id", "action")}
            async with semaphore:
                try:
                    return await self.dispatch(account_id, action, **kwargs)
                except Exception as exc:
                    return {"success": False, "error": str(exc)}

        results = await asyncio.gather(*[_guarded(item) for item in dispatches])
        return list(results)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    async def _log_action(
        self,
        account_id:   str,
        phone_serial: str,
        action:       str,
        kwargs:       dict,
        result:       dict,
        error:        Optional[str],
        started_at:   datetime,
        finished_at:  datetime,
    ) -> None:
        """
        Persist an action log entry.

        If ``self._db`` is set, attempts to INSERT into an ``action_log``
        table. Falls back to Python logger on any DB error so the main
        dispatch path is never blocked by logging failures.

        Expected table schema:
            CREATE TABLE action_log (
                id           SERIAL PRIMARY KEY,
                account_id   TEXT NOT NULL,
                phone_serial TEXT NOT NULL,
                action       TEXT NOT NULL,
                kwargs       JSONB,
                result       JSONB,
                error        TEXT,
                started_at   TIMESTAMPTZ NOT NULL,
                finished_at  TIMESTAMPTZ NOT NULL,
                duration_ms  INTEGER GENERATED ALWAYS AS
                                 (EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000) STORED
            );
        """
        duration_ms = int(
            (finished_at - started_at).total_seconds() * 1000
        )

        logger.debug(
            "action_log: account=%s action=%s success=%s duration_ms=%d",
            account_id,
            action,
            result.get("success"),
            duration_ms,
        )

        if self._db is None:
            return

        try:
            import json

            await self._db.execute(
                """
                INSERT INTO action_log
                    (account_id, phone_serial, action, kwargs, result, error,
                     started_at, finished_at)
                VALUES
                    (:account_id, :phone_serial, :action, :kwargs, :result, :error,
                     :started_at, :finished_at)
                """,
                {
                    "account_id":   account_id,
                    "phone_serial": phone_serial,
                    "action":       action,
                    "kwargs":       json.dumps(kwargs),
                    "result":       json.dumps(result),
                    "error":        error,
                    "started_at":   started_at.isoformat(),
                    "finished_at":  finished_at.isoformat(),
                },
            )
        except Exception as log_exc:
            # Never let a logging failure crash the dispatcher
            logger.warning(
                "IGActionDispatcher: failed to write action_log: %s", log_exc
            )
