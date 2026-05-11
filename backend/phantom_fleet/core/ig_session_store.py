"""
IGSessionStore — encrypted on-disk storage for Instagram sessions.

Sessions are sensitive (equivalent to login credentials).
All data is encrypted with Fernet symmetric encryption before writing to disk.
The encryption key is derived from the PHANTOM_SESSION_KEY environment variable.

Storage path:
    {PHANTOM_STATE_DIR}/sessions/{account_id}.enc
    PHANTOM_STATE_DIR defaults to ~/.phantom_fleet/state if not set.

Key derivation:
    PHANTOM_SESSION_KEY → UTF-8 → SHA-256 → URL-safe base64 → Fernet key
    This allows the env var to be any length/entropy without Fernet format
    restrictions.

Session validity:
    is_valid() checks:
        - File exists
        - Decrypts without error
        - Session.is_valid flag is True
        - Session age < SESSION_MAX_AGE_HOURS (default 72h — IG sessions
          typically stay valid for several days with activity)
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .instagram_client import IGSession
from .hybrid_runner import PlatformHeaders

log = logging.getLogger("phantom_fleet.ig_session_store")

SESSION_MAX_AGE_HOURS = 72
_SESSIONS_DIR_NAME = "sessions"


def _fernet_key_from_env() -> bytes:
    """
    Derive a 32-byte Fernet key from PHANTOM_SESSION_KEY.
    Raises RuntimeError if the env var is not set.
    """
    raw = os.environ.get("PHANTOM_SESSION_KEY", "")
    if not raw:
        raise RuntimeError(
            "PHANTOM_SESSION_KEY environment variable is not set. "
            "Set it to a strong random secret before using IGSessionStore."
        )
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_sessions_dir() -> Path:
    state_dir = os.environ.get(
        "PHANTOM_STATE_DIR",
        str(Path.home() / ".phantom_fleet" / "state"),
    )
    sessions_dir = Path(state_dir) / _SESSIONS_DIR_NAME
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _session_to_dict(session: IGSession) -> dict:
    h = session.headers
    return {
        "account_id": session.account_id,
        "ig_user_id": session.ig_user_id,
        "username": session.username,
        "session_id": session.session_id,
        "csrftoken": session.csrftoken,
        "mid": session.mid,
        "ds_user_id": session.ds_user_id,
        "is_valid": session.is_valid,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "headers": {
            "platform": h.platform,
            "session_token": h.session_token,
            "device_id": h.device_id,
            "user_agent": h.user_agent,
            "app_version": h.app_version,
            "android_id": h.android_id,
            "advertising_id": h.advertising_id,
            "carrier_name": h.carrier_name,
            "carrier_mcc_mnc": h.carrier_mcc_mnc,
            "locale": h.locale,
            "timezone": h.timezone,
            "extra": h.extra,
        },
    }


def _dict_to_session(data: dict) -> IGSession:
    hd = data["headers"]
    headers = PlatformHeaders(
        platform=hd["platform"],
        session_token=hd["session_token"],
        device_id=hd["device_id"],
        user_agent=hd["user_agent"],
        app_version=hd["app_version"],
        android_id=hd["android_id"],
        advertising_id=hd["advertising_id"],
        carrier_name=hd["carrier_name"],
        carrier_mcc_mnc=hd["carrier_mcc_mnc"],
        locale=hd["locale"],
        timezone=hd["timezone"],
        extra=hd.get("extra", {}),
    )
    return IGSession(
        account_id=data["account_id"],
        ig_user_id=data["ig_user_id"],
        username=data["username"],
        session_id=data["session_id"],
        csrftoken=data["csrftoken"],
        mid=data["mid"],
        ds_user_id=data["ds_user_id"],
        headers=headers,
        is_valid=data.get("is_valid", True),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class IGSessionStore:
    """
    Encrypted on-disk session storage.

    All I/O is synchronous under the hood (file ops) but wrapped in async
    methods so callers can use await throughout without changing their
    concurrency model when we move to async file I/O later.
    """

    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        max_age_hours: int = SESSION_MAX_AGE_HOURS,
    ) -> None:
        self._sessions_dir = sessions_dir or _get_sessions_dir()
        self._max_age_hours = max_age_hours

    def _path(self, account_id: str) -> Path:
        # Sanitise account_id to prevent path traversal
        safe_id = "".join(c for c in account_id if c.isalnum() or c in "-_")
        return self._sessions_dir / f"{safe_id}.enc"

    def _fernet(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise RuntimeError(
                "cryptography is required: pip install cryptography"
            )
        return Fernet(_fernet_key_from_env())

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def save(self, account_id: str, session: IGSession) -> None:
        """Encrypt and write session to disk."""
        fernet = self._fernet()
        data = _session_to_dict(session)
        plaintext = json.dumps(data).encode("utf-8")
        ciphertext = fernet.encrypt(plaintext)
        path = self._path(account_id)
        path.write_bytes(ciphertext)
        log.debug("Session saved for account %s → %s", account_id, path)

    async def load(self, account_id: str) -> Optional[IGSession]:
        """Decrypt and return session, or None if not found."""
        path = self._path(account_id)
        if not path.exists():
            return None
        try:
            fernet = self._fernet()
            ciphertext = path.read_bytes()
            plaintext = fernet.decrypt(ciphertext)
            data = json.loads(plaintext.decode("utf-8"))
            return _dict_to_session(data)
        except Exception as exc:
            log.warning("Failed to load/decrypt session for %s: %s", account_id, exc)
            return None

    async def delete(self, account_id: str) -> None:
        """Remove stored session file."""
        path = self._path(account_id)
        if path.exists():
            path.unlink()
            log.debug("Session deleted for account %s", account_id)

    async def list_accounts(self) -> list[str]:
        """Return account IDs of all stored sessions."""
        return [p.stem for p in self._sessions_dir.glob("*.enc")]

    async def is_valid(self, account_id: str) -> bool:
        """
        Return True if a valid, non-expired session exists for the account.
        Checks: file exists + decrypts + is_valid flag + age < max_age_hours.
        """
        path = self._path(account_id)
        if not path.exists():
            return False
        try:
            fernet = self._fernet()
            ciphertext = path.read_bytes()
            plaintext = fernet.decrypt(ciphertext)
            data = json.loads(plaintext.decode("utf-8"))
        except Exception:
            return False

        if not data.get("is_valid", True):
            return False

        saved_at_str = data.get("saved_at")
        if saved_at_str:
            try:
                saved_at = datetime.fromisoformat(saved_at_str)
                if saved_at.tzinfo is None:
                    saved_at = saved_at.replace(tzinfo=timezone.utc)
                age_hours = (
                    datetime.now(timezone.utc) - saved_at
                ).total_seconds() / 3600
                if age_hours > self._max_age_hours:
                    log.debug(
                        "Session for %s is %.1fh old (max %dh) — expired",
                        account_id,
                        age_hours,
                        self._max_age_hours,
                    )
                    return False
            except (ValueError, TypeError):
                pass

        return True

    async def refresh(
        self,
        account_id: str,
        client,  # InstagramClient — typed loosely to avoid circular import
    ) -> IGSession:
        """
        Refresh session validity via ping_session().
        If the ping fails, marks the stored session as invalid and raises
        IGSessionExpired so the caller knows to re-login.
        """
        from .instagram_client import IGSessionExpired

        session = await self.load(account_id)
        if session is None:
            raise IGSessionExpired(f"No stored session for account {account_id}")

        async with client as c:
            alive = await c.ping_session()

        if not alive:
            session.is_valid = False
            await self.save(account_id, session)
            raise IGSessionExpired(
                f"Session for account {account_id} is no longer valid"
            )

        # Update the saved_at timestamp so the age clock resets
        await self.save(account_id, session)
        return session
