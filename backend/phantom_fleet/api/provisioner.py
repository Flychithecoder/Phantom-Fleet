"""
AccountProvisioner — take credentials, bootstrap a session, store the account.

Design constraints:
    1. PROXY GATE IS ABSOLUTE: if a phone_serial is given, the phone MUST be
       in PhoneState.PROXY_READY before any network call is attempted. If not,
       raise ProxyNotVerified immediately — no silent skip, no fallback.

    2. LOGIN VIA IGLoginFlow: the actual HTTP login call goes through
       IGLoginFlow (ig_session_manager) which routes through the phone's
       SOCKS5 proxy. Sessions are stored encrypted by IGSessionStore.

    3. STORE IS INJECTED: the provisioner writes to whatever dict/DB is injected
       at construction time. In tests this is an empty dict. In production it's
       an asyncpg pool write.

    4. PER-ACCOUNT IDEMPOTENCY: if an account with the same (username, platform)
       already exists, skip rather than duplicating.

Flow for one credential:
    a. Validate proxy state (if phone given)
    b. Call _bootstrap_ig_session() → runs IGLoginFlow → returns IGSession
    c. Write account row to store
    d. Return account_id
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from ..core.phone_controller import PhoneFleet, PhoneState, ProxyNotVerified
from ..core.instagram_client import IGSession
from ..core.hybrid_runner import PlatformHeaders, DeviceProfile
from ..core.ig_session_manager import (
    IGLoginFlow,
    TOTPProvider,
    TwoFALiveProvider,
    SMSActivateProvider,
    IGLoginFailed,
    IGCheckpointRequired,
)
from ..core.ig_session_store import IGSessionStore
from ..core.threads_client import ThreadsClient, ThreadsSessionExpired

log = logging.getLogger("phantom_fleet.provisioner")


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------


class AccountProvisioner:
    """
    Bootstrap accounts from credentials and store them.

    Args:
        fleet:         PhoneFleet singleton (used for proxy state check).
        store:         dict[account_id, dict] — the account store to write to.
                       In production, wrap an asyncpg INSERT here.
        session_store: IGSessionStore instance for encrypted session persistence.
                       If None, a default store is created.
    """

    def __init__(
        self,
        fleet: PhoneFleet,
        store: dict[str, dict],
        session_store: Optional[IGSessionStore] = None,
    ) -> None:
        self.fleet = fleet
        self.store = store
        self._session_store = session_store or IGSessionStore()

    async def provision_one(
        self,
        *,
        username: str,
        password: str,
        platform: str = "instagram",
        phone_serial: Optional[str] = None,
        two_fa_secret: Optional[str] = None,
        two_fa_provider: str = "totp",  # "totp" | "2fa_live" | "sms_activate"
        auto_setup_threads: bool = True,
        threads_bio: str = "",
        threads_funnel_url: str = "",
    ) -> str:
        """
        Provision a single account.

        Returns the account_id string on success.
        Raises ProxyNotVerified if phone_serial given but proxy not ready.
        Raises RuntimeError on any other bootstrap failure.
        """
        # ------------------------------------------------------------------
        # 1. Idempotency check — skip if already provisioned
        # ------------------------------------------------------------------
        existing = self._find_existing(username, platform)
        if existing:
            log.info("Account %s/%s already provisioned as %s — skipping", username, platform, existing)
            return existing

        # ------------------------------------------------------------------
        # 2. PROXY GATE — hard stop if phone not ready
        # ------------------------------------------------------------------
        proxy_url = "socks5://127.0.0.1:8089"
        if phone_serial is not None:
            phone = self.fleet.get(phone_serial)
            if phone is None:
                raise RuntimeError(
                    f"Phone {phone_serial!r} is not registered in the fleet. "
                    "Run POST /api/fleet/scan first."
                )
            if phone.state != PhoneState.PROXY_READY:
                raise ProxyNotVerified(
                    f"Phone {phone_serial} is in state {phone.state.value!r}. "
                    "Proxy must be PROXY_READY before provisioning any account. "
                    "Run POST /api/fleet/{serial}/verify-proxy first."
                )
            proxy_url = f"socks5://{phone.proxy_host}:{phone.proxy_port}"

        # ------------------------------------------------------------------
        # 3. Bootstrap the session
        # ------------------------------------------------------------------
        account_id = str(uuid.uuid4())

        if platform == "instagram":
            session = await self._bootstrap_ig_session(
                account_id=account_id,
                username=username,
                password=password,
                proxy_url=proxy_url,
                two_fa_secret=two_fa_secret,
                two_fa_provider=two_fa_provider,
            )
            session_valid = session.is_valid
        else:
            # Non-IG platforms: stub session (extend per-platform in production)
            session = None
            session_valid = True

        # ------------------------------------------------------------------
        # 4. Write to store
        # ------------------------------------------------------------------
        now_iso = datetime.now(timezone.utc).isoformat()
        row: dict = {
            "account_id": account_id,
            "username": username,
            "platform": platform,
            "phone_serial": phone_serial,
            "clone_index": None,
            "warmup_day": 0,
            "status": "active",
            "created_at": now_iso,
            "session_valid": session_valid,
            "proxy_url": proxy_url,
            "_ig_session": session,        # private: used by health check
        }
        self.store[account_id] = row

        log.info(
            "Provisioned account %s username=%s platform=%s phone=%s",
            account_id, username, platform, phone_serial,
        )

        # ------------------------------------------------------------------
        # 5. Auto-setup Threads (runs only for Instagram accounts with a valid session)
        # ------------------------------------------------------------------
        if platform == "instagram" and auto_setup_threads and session is not None and session.is_valid:
            try:
                await self._setup_threads_account(
                    session=session,
                    proxy_url=proxy_url,
                    bio=threads_bio,
                    funnel_url=threads_funnel_url,
                )
                self.store[account_id]["threads_onboarded"] = True
                log.info(
                    "Threads auto-setup complete for account %s (@%s)",
                    account_id, username,
                )
            except Exception as exc:
                # Threads setup failure must NOT block IG provisioning
                self.store[account_id]["threads_onboarded"] = False
                self.store[account_id]["threads_setup_error"] = str(exc)
                log.warning(
                    "Threads auto-setup failed for account %s (@%s): %s",
                    account_id, username, exc,
                )

        return account_id

    # ------------------------------------------------------------------
    # Session bootstrap
    # ------------------------------------------------------------------

    async def _bootstrap_ig_session(
        self,
        *,
        account_id: str,
        username: str,
        password: str,
        proxy_url: str,
        two_fa_secret: Optional[str] = None,
        two_fa_provider: str = "totp",
    ) -> IGSession:
        """
        Full Instagram mobile API login flow.

        Builds a DeviceProfile from env/defaults if no phone-extracted profile
        is available, then delegates to IGLoginFlow for the real HTTP handshake.
        Stores the resulting session in IGSessionStore (encrypted on disk).

        Args:
            account_id:       Our internal UUID for this account.
            username:         Instagram username.
            password:         Plaintext password (never logged).
            proxy_url:        SOCKS5 proxy URL routing through the phone.
            two_fa_secret:    2FA secret for TOTP/2fa.live (optional).
            two_fa_provider:  One of "totp", "2fa_live", "sms_activate".
        """
        # Build a minimal DeviceProfile if no phone-extracted one is available.
        # In production, the DeviceProfile comes from the Companion APK extraction
        # stored in the phones table and injected here via the PhoneController.
        device = _build_default_device_profile(account_id)

        # Build the code provider for 2FA if a secret was supplied
        code_provider: Optional[Callable[[str], Awaitable[str]]] = None
        if two_fa_secret:
            if two_fa_provider == "totp":
                code_provider = TOTPProvider(two_fa_secret)
            elif two_fa_provider == "2fa_live":
                # Accepts "Username:password:2fakey" or raw 2fakey
                code_provider = TwoFALiveProvider.from_credential_string(two_fa_secret)
            elif two_fa_provider == "sms_activate":
                # For SMS-Activate the secret is expected to be "{api_key}:{activation_id}"
                parts = two_fa_secret.split(":", 1)
                if len(parts) != 2:
                    raise ValueError(
                        "sms_activate two_fa_secret must be 'api_key:activation_id'"
                    )
                code_provider = SMSActivateProvider(
                    api_key=parts[0], activation_id=parts[1]
                )
            else:
                raise ValueError(
                    f"Unknown two_fa_provider: {two_fa_provider!r}. "
                    "Expected 'totp', '2fa_live', or 'sms_activate'."
                )

        flow = IGLoginFlow(device=device, proxy_url=proxy_url)
        session = await flow.login(
            account_id=account_id,
            username=username,
            password=password,
            code_provider=code_provider,
        )

        # Persist encrypted session to disk
        try:
            await self._session_store.save(account_id, session)
        except RuntimeError as exc:
            # PHANTOM_SESSION_KEY not set — log warning and continue.
            # Session still usable in memory; just won't survive a restart.
            log.warning(
                "Could not persist session for %s: %s. "
                "Set PHANTOM_SESSION_KEY to enable encrypted session storage.",
                account_id,
                exc,
            )

        log.info(
            "Login successful for %s (ig_user_id=%s)", username, session.ig_user_id
        )
        return session

    async def _setup_threads_account(
        self,
        *,
        session: "IGSession",
        proxy_url: str,
        bio: str = "",
        funnel_url: str = "",
    ) -> None:
        """
        Onboard and configure a Threads profile for a freshly provisioned IG account.

        Uses the same IGSession — no separate Threads login needed.

        Steps:
            1. Verify Threads accessibility (profile fetch via Threads App ID)
            2. Set bio + external funnel URL on the profile
            3. Done — the Threads worker can now post/follow on this account

        Called automatically by provision_one() for Instagram accounts.
        Not called if auto_setup_threads=False.
        """
        async with ThreadsClient(session=session, proxy_url=proxy_url) as client:
            success = await client.onboard(bio=bio, funnel_url=funnel_url)
            if not success:
                raise RuntimeError(
                    f"Threads onboard() returned False for account {session.account_id} "
                    f"(@{session.username}) — account may need manual Threads setup"
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_existing(self, username: str, platform: str) -> Optional[str]:
        """Return account_id if (username, platform) already in store, else None."""
        for account_id, row in self.store.items():
            if row.get("username") == username and row.get("platform") == platform:
                return account_id
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_default_device_profile(account_id: str) -> DeviceProfile:
    """
    Build a minimal DeviceProfile for login when no phone-extracted profile
    is available (e.g. in tests or before the Companion APK has run).

    In production, DeviceProfile is extracted from the physical phone via
    PhoneController.get_device_info() and injected into the provisioner.
    This fallback uses deterministic-but-plausible values derived from the
    account_id so that each account gets a stable unique fingerprint within
    a process. These values will NOT match a real physical device — for
    production use always supply a real DeviceProfile.
    """
    # Derive stable but account-unique hardware IDs
    seed = account_id.replace("-", "")
    android_id = seed[:16]
    adv_id = f"{seed[:8]}-{seed[8:12]}-{seed[12:16]}-{seed[16:20]}-{seed[20:32]}"

    headers = PlatformHeaders(
        platform="instagram",
        session_token="",
        device_id=f"android-{android_id}",
        user_agent=(
            "Instagram 319.0.0.34.109 Android "
            "(28/9; 420dpi; 1080x2220; Samsung; SM-G975F; beyond1; "
            "exynos9820; en_US; 532654130)"
        ),
        app_version="319.0.0.34.109",
        android_id=android_id,
        advertising_id=adv_id,
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        locale="en_US",
        timezone="America/New_York",
        extra={
            "mid": seed[:24],
            "family_device_id": str(uuid.uuid4()),
            "phone_id": str(uuid.uuid4()),
        },
    )

    return DeviceProfile(
        phone_serial="default",
        model="Samsung Galaxy S10 Lite",
        android_version="9",
        android_id=android_id,
        advertising_id=adv_id,
        carrier_name="T-Mobile",
        carrier_mcc_mnc="310260",
        timezone="America/New_York",
        locale="en_US",
        platform_headers={"instagram": headers},
    )
