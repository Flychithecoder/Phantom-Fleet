"""
GmailAccountPool — encrypted at-rest storage for Gmail and Reddit credentials.

Acts as the inventory layer between GmailCreationAgent output and
RedditRegistrationAgent input. Credentials are persisted to a JSON file
encrypted with Fernet symmetric encryption using the PHANTOM_SESSION_KEY
environment variable.

File layout (after decryption)::

    {
        "gmails": [
            {
                "email": "...",
                "password": "...",
                "first_name": "...",
                "last_name": "...",
                "phone_number_used": "...",
                "created_at_iso": "...",
                "phone_serial": "...",
                "account_seed": 123456,
                "reddit_credential": null | { ... }
            },
            ...
        ]
    }

Security notes:
    - The Fernet key is loaded from env var PHANTOM_SESSION_KEY at runtime.
      Never hardcode or log it.
    - Writes are atomic: new content is written to a temp file then renamed
      so a crash during write cannot corrupt the pool file.
    - All in-memory credential dicts are plain Python dicts — never logged.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Default pool file location (relative to this file's package config dir)
_DEFAULT_POOL_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "gmail_pool.json"
)


@dataclass
class PoolStats:
    """Snapshot statistics of the Gmail/Reddit credential pool."""

    total_gmails: int
    unregistered: int       # Gmails not yet used for Reddit
    registered: int         # Gmails used, Reddit account created
    verified_reddit: int    # Reddit accounts with verified email


class GmailAccountPool:
    """Encrypted persistent pool for Gmail + Reddit credentials.

    All reads/writes go through Fernet symmetric encryption.  The key is read
    once from ``PHANTOM_SESSION_KEY`` at construction time and kept in memory
    for the lifetime of the pool object.

    Thread safety: this class is NOT async-safe by itself.  Callers should
    use an asyncio.Lock when accessing a shared pool instance concurrently.

    Args:
        pool_path: Path to the encrypted JSON pool file.  Created on first
                   write if it doesn't exist.
    """

    def __init__(self, pool_path: Path = _DEFAULT_POOL_PATH) -> None:
        self._path = pool_path
        self._fernet = self._load_fernet()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_gmail(self, cred: "GmailCredential") -> None:  # noqa: F821
        """Add a newly created Gmail credential to the pool.

        Idempotent — if the email address already exists in the pool,
        the call is a no-op (no duplicate entries).

        Args:
            cred: GmailCredential returned by GmailCreationAgent.
        """
        from ..agents.specialists.gmail_creation_agent import GmailCredential

        pool = self._load()
        existing_emails = {entry["email"] for entry in pool["gmails"]}
        if cred.email in existing_emails:
            log.warning("GmailAccountPool.add_gmail: %s already in pool", cred.email)
            return

        entry = asdict(cred)
        entry["reddit_credential"] = None
        pool["gmails"].append(entry)
        self._save(pool)
        log.info("GmailAccountPool: added %s (pool size now %d)", cred.email, len(pool["gmails"]))

    def get_unregistered(self, limit: int = 10) -> list["GmailCredential"]:  # noqa: F821
        """Return up to ``limit`` Gmail credentials not yet registered on Reddit.

        Credentials are returned oldest-first (FIFO) so the first created
        accounts age the longest before being promoted to Reddit.

        Args:
            limit: Maximum number of credentials to return.

        Returns:
            List of GmailCredential instances with no associated Reddit account.
        """
        from ..agents.specialists.gmail_creation_agent import GmailCredential

        pool = self._load()
        unregistered = [
            entry for entry in pool["gmails"]
            if entry.get("reddit_credential") is None
        ]
        # Return oldest first
        unregistered.sort(key=lambda e: e.get("created_at_iso", ""))
        slice_ = unregistered[:limit]
        return [self._dict_to_gmail_credential(e) for e in slice_]

    def mark_registered(
        self,
        email: str,
        reddit_cred: "RedditCredential",  # noqa: F821
    ) -> None:
        """Associate a Reddit credential with the given Gmail address.

        Args:
            email: Gmail address to look up.
            reddit_cred: Fully populated RedditCredential from registration.

        Raises:
            KeyError: If the email is not found in the pool.
        """
        from ..agents.specialists.reddit_registration_agent import RedditCredential

        pool = self._load()
        for entry in pool["gmails"]:
            if entry["email"] == email:
                reddit_dict = asdict(reddit_cred)
                # Drop the nested gmail_credential to avoid circular storage
                reddit_dict.pop("gmail_credential", None)
                entry["reddit_credential"] = reddit_dict
                self._save(pool)
                log.info(
                    "GmailAccountPool: marked %s registered → u/%s",
                    email, reddit_cred.username,
                )
                return
        raise KeyError(f"Email not found in pool: {email}")

    def get_pool_stats(self) -> PoolStats:
        """Return a snapshot of pool statistics.

        Returns:
            PoolStats dataclass with counts for each credential state.
        """
        pool = self._load()
        total = len(pool["gmails"])
        unregistered = sum(
            1 for e in pool["gmails"] if e.get("reddit_credential") is None
        )
        registered = total - unregistered
        verified = sum(
            1 for e in pool["gmails"]
            if e.get("reddit_credential")
            and e["reddit_credential"].get("verification_status") == "verified"
        )
        return PoolStats(
            total_gmails=total,
            unregistered=unregistered,
            registered=registered,
            verified_reddit=verified,
        )

    def get_all_reddit_credentials(self) -> list[dict]:
        """Return all pool entries that have an associated Reddit credential.

        Returns a list of raw dicts (not typed dataclasses) suitable for
        JSON serialisation in API responses.

        Returns:
            List of pool entries with non-null reddit_credential fields.
        """
        pool = self._load()
        return [e for e in pool["gmails"] if e.get("reddit_credential") is not None]

    def export_reddit_csv(self) -> str:
        """Export all registered Reddit credentials as a CSV string.

        Columns: username, password, email, verification_status, created_at_iso,
        proxy_url_used.

        Returns:
            CSV string (including header row).
        """
        import csv
        import io

        rows = self.get_all_reddit_credentials()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "username", "password", "email",
            "verification_status", "created_at_iso", "proxy_url_used",
        ])
        for entry in rows:
            rc = entry["reddit_credential"]
            writer.writerow([
                rc.get("username", ""),
                rc.get("password", ""),
                entry.get("email", ""),
                rc.get("verification_status", ""),
                rc.get("created_at_iso", ""),
                rc.get("proxy_url_used", ""),
            ])
        return output.getvalue()

    # ------------------------------------------------------------------
    # Encryption / persistence
    # ------------------------------------------------------------------

    def _load_fernet(self):
        """Load a Fernet instance from PHANTOM_SESSION_KEY env var.

        Falls back to a deterministic dev key when the env var is unset
        (never use in production — logs a warning).

        Returns:
            cryptography.fernet.Fernet instance.
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            log.warning(
                "cryptography package not installed — pool stored in plaintext. "
                "Run: pip install cryptography"
            )
            return None

        key = os.environ.get("PHANTOM_SESSION_KEY", "")
        if not key:
            log.warning(
                "PHANTOM_SESSION_KEY not set — using dev key. "
                "NEVER use this in production."
            )
            # Deterministic dev key (32 URL-safe base64 bytes)
            import base64
            import hashlib
            raw = hashlib.sha256(b"phantom_fleet_dev_key_do_not_use").digest()
            key = base64.urlsafe_b64encode(raw).decode("ascii")

        return Fernet(key.encode("ascii") if isinstance(key, str) else key)

    def _load(self) -> dict:
        """Load and decrypt the pool file.

        Returns:
            Pool dict with a "gmails" list.  Returns an empty pool if the
            file doesn't exist.
        """
        if not self._path.exists():
            return {"gmails": []}

        raw = self._path.read_bytes()

        if self._fernet is None:
            # Plaintext fallback
            return json.loads(raw.decode("utf-8"))

        try:
            decrypted = self._fernet.decrypt(raw)
            return json.loads(decrypted.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to decrypt pool file: %s — returning empty pool", exc)
            return {"gmails": []}

    def _save(self, pool: dict) -> None:
        """Encrypt and atomically write the pool dict to disk.

        Uses a temp file + rename for atomic writes so a crash during write
        cannot corrupt the pool.

        Args:
            pool: Pool dict to persist.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(pool, indent=2).encode("utf-8")

        if self._fernet is not None:
            data = self._fernet.encrypt(raw)
        else:
            data = raw

        # Atomic write via temp file in same directory
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, prefix=".gmail_pool_tmp_"
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dict_to_gmail_credential(entry: dict) -> "GmailCredential":  # noqa: F821
        """Convert a pool entry dict back to a GmailCredential dataclass.

        Args:
            entry: Raw pool entry dict.

        Returns:
            GmailCredential instance.
        """
        from ..agents.specialists.gmail_creation_agent import GmailCredential

        return GmailCredential(
            email=entry["email"],
            password=entry["password"],
            first_name=entry["first_name"],
            last_name=entry["last_name"],
            phone_number_used=entry["phone_number_used"],
            created_at_iso=entry["created_at_iso"],
            phone_serial=entry["phone_serial"],
            account_seed=entry["account_seed"],
        )
