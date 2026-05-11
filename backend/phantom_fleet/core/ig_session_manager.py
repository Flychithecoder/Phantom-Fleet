"""
IGLoginFlow — full Instagram mobile API login flow.

Steps:
    1. Register device / fetch experiment assignments
    2. Pre-login flow — fetch CSRF token
    3. Fetch password public key
    4. Send encrypted credentials
    5. Handle 2FA if required (SMS, TOTP, email)
    6. Handle checkpoint/challenge if triggered
    7. Extract and return IGSession

2FA provider implementations:
    TOTPProvider        — generates TOTP from a secret (pyotp, no network)
    TwoFALiveProvider   — fetches code from 2fa.live API
    SMSActivateProvider — polls sms-activate.org until code arrives

Password encryption:
    Instagram encrypts passwords client-side using hybrid RSA+AES-GCM.
    Output format: #PWD_INSTAGRAM:4:{timestamp}:{b64_payload}

Detection hardening:
    - All requests carry full IG mobile header set derived from DeviceProfile
    - Passwords never logged (even partial)
    - CSRF token and public key fetched fresh per login, not cached globally
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Awaitable, Optional

import httpx

from .instagram_client import IGSession, IGSessionExpired
from .hybrid_runner import PlatformHeaders, DeviceProfile

log = logging.getLogger("phantom_fleet.ig_session_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IG_API_BASE = "https://i.instagram.com/api/v1"
IG_APP_ID = "567067343352427"
IG_CAPABILITIES = "3brTvx0="
IG_CONNECTION_TYPE = "WIFI"
IG_SIG_KEY = "9193488027538fd3450b83b7d05286d4ca9599572d10f60bb7f3fc2e5b5e0f7b"

_DEFAULT_TIMEOUT = httpx.Timeout(20.0)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IGLoginFailed(Exception):
    """Raised on bad credentials or unrecoverable login error."""


class IGCheckpointRequired(Exception):
    """Raised when login triggers a checkpoint that requires manual resolution."""

    def __init__(self, checkpoint_url: str, message: str = ""):
        self.checkpoint_url = checkpoint_url
        super().__init__(message or f"Checkpoint required: {checkpoint_url}")


class IGTwoFactorRequired(Exception):
    """Raised when 2FA is required but no code_provider was supplied."""


class IGRateLimited(Exception):
    """Raised on HTTP 429 responses during login."""


# ---------------------------------------------------------------------------
# 2FA method enum
# ---------------------------------------------------------------------------


class TwoFactorMethod(str, Enum):
    SMS = "sms"
    TOTP = "totp"
    EMAIL = "email"


# ---------------------------------------------------------------------------
# 2FA provider implementations
# ---------------------------------------------------------------------------


class TOTPProvider:
    """
    Generates TOTP codes from a base-32 secret.
    No network call — pure local computation via pyotp.
    """

    def __init__(self, totp_secret: str) -> None:
        self._secret = totp_secret

    def get_code(self, totp_secret: Optional[str] = None) -> str:
        try:
            import pyotp
        except ImportError:
            raise RuntimeError("pyotp is required for TOTP: pip install pyotp")
        secret = totp_secret or self._secret
        return pyotp.TOTP(secret).now()

    async def __call__(self, hint: str = "") -> str:
        return self.get_code()


class TwoFALiveProvider:
    """
    Fetches 2FA codes from the 2fa.live API.

    Account credential format (as supplied by the user):
        Username:password:2fakey

    The 2fakey is the base-32 TOTP secret we pass to 2fa.live to generate
    the 6-digit code at login time.

    2fa.live endpoint:
        GET https://2fa.live/tok/{2fakey} → {"token": "123456", "valid": 27}

    Falls back to the legacy /grab/{secret} path if /tok/ returns 404.
    Retries once if the first code is near expiry (valid < 5s), so we never
    hand Instagram a code that is about to expire mid-POST.
    """

    def __init__(self, credential_string: str) -> None:
        """
        Accept either:
          - "Username:password:2fakey"  (full credential string from the user)
          - "2fakey"                    (raw secret, legacy)
        """
        parts = credential_string.strip().split(":")
        if len(parts) >= 3:
            self._username = parts[0]
            self._password = parts[1]
            self._secret   = ":".join(parts[2:])  # 2fakey may contain colons
        else:
            # Legacy: raw secret only
            self._username = None
            self._password = None
            self._secret   = credential_string.strip()

    @property
    def username(self) -> Optional[str]:
        return self._username

    @property
    def password(self) -> Optional[str]:
        return self._password

    async def get_code(self, account_id: Optional[str] = None) -> str:
        """Fetch a fresh 6-digit TOTP code from 2fa.live."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            # Primary endpoint: /tok/{secret} (returns validity window too)
            url = f"https://2fa.live/tok/{self._secret}"
            resp = await client.get(url)

            if resp.status_code == 404:
                # Fallback to legacy /grab/ path
                url = f"https://2fa.live/grab/{self._secret}"
                resp = await client.get(url)

            resp.raise_for_status()
            data = resp.json()
            token = data.get("token") or data.get("TOKEN")
            if not token:
                raise IGLoginFailed(f"2fa.live returned no token: {data}")

            token = str(token).strip()

            # If the code expires in < 5 seconds, wait for the next window
            # (TOTP rotates every 30 seconds — waiting max 5s is safe)
            valid_sec = data.get("valid", 30)
            if isinstance(valid_sec, int) and valid_sec < 5:
                log.info(
                    "2fa.live: code valid for only %ds — waiting %ds for next window",
                    valid_sec, valid_sec + 1,
                )
                await asyncio.sleep(valid_sec + 1)
                # Fetch fresh code after window rotation
                resp2 = await client.get(url)
                resp2.raise_for_status()
                data2 = resp2.json()
                token = str(data2.get("token") or data2.get("TOKEN") or token).strip()

            log.debug("2fa.live code obtained (username=%s)", self._username or "raw-secret")
            return token

    async def __call__(self, hint: str = "") -> str:
        return await self.get_code()

    @classmethod
    def from_credential_string(cls, cred: str) -> "TwoFALiveProvider":
        """
        Convenience constructor.  Accepts the format:
            Username:password:2fakey
        and returns a provider pre-loaded with the 2fakey.
        """
        return cls(cred)


class SMSActivateProvider:
    """
    Fetches SMS codes from sms-activate.org.
    Polls GET /stubs/handler_api.php?action=getStatus&id={activation_id}
    until status 2 (code received) or timeout.
    """

    BASE_URL = "https://sms-activate.org/stubs/handler_api.php"

    def __init__(self, api_key: str, activation_id: str) -> None:
        self._api_key = api_key
        self._activation_id = activation_id

    async def get_code(
        self,
        activation_id: Optional[str] = None,
        max_wait_sec: int = 120,
    ) -> str:
        act_id = activation_id or self._activation_id
        deadline = time.monotonic() + max_wait_sec
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            while time.monotonic() < deadline:
                resp = await client.get(
                    self.BASE_URL,
                    params={
                        "api_key": self._api_key,
                        "action": "getStatus",
                        "id": act_id,
                    },
                )
                text = resp.text.strip()
                if text.startswith("STATUS_OK:"):
                    return text.split(":", 1)[1].strip()
                if text == "STATUS_WAIT_CODE":
                    await asyncio.sleep(5)
                    continue
                if text in ("STATUS_CANCEL", "NO_ACTIVATION", "BAD_KEY", "BAD_ACTION"):
                    raise IGLoginFailed(f"SMS-Activate status: {text}")
                await asyncio.sleep(5)
        raise IGLoginFailed(
            f"SMSActivate: code not received within {max_wait_sec}s for id={act_id}"
        )

    async def __call__(self, hint: str = "") -> str:
        return await self.get_code()


# ---------------------------------------------------------------------------
# Password encryption helpers
# ---------------------------------------------------------------------------


def _encrypt_password(password: str, pub_key_b64: str, pub_key_id: int) -> str:
    """
    Instagram hybrid RSA+AES-GCM password encryption.

    Algorithm:
        1. Generate a random 32-byte AES key and 12-byte IV.
        2. Encrypt the password with AES-256-GCM.
        3. Encrypt the AES key with RSA-OAEP (SHA-256) using IG's public key.
        4. Pack into a binary envelope and base64-encode.
        5. Return "#PWD_INSTAGRAM:4:{unix_timestamp}:{b64_envelope}"

    The pub_key_b64 is the raw base64 payload returned by Instagram —
    it needs to be wrapped in PEM headers before loading.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        from cryptography.hazmat.primitives import hashes, serialization
    except ImportError:
        raise RuntimeError(
            "cryptography is required for password encryption: pip install cryptography"
        )

    # Wrap in PEM if not already
    pub_key_pem_str = pub_key_b64.strip()
    if not pub_key_pem_str.startswith("-----"):
        pub_key_pem_str = (
            "-----BEGIN PUBLIC KEY-----\n"
            + "\n".join(
                pub_key_pem_str[i : i + 64]
                for i in range(0, len(pub_key_pem_str), 64)
            )
            + "\n-----END PUBLIC KEY-----"
        )
    public_key = serialization.load_pem_public_key(pub_key_pem_str.encode())

    # AES-GCM encryption of the password
    aes_key = os.urandom(32)
    iv = os.urandom(12)
    timestamp = int(time.time())
    additional_data = str(timestamp).encode("utf-8")

    aesgcm = AESGCM(aes_key)
    encrypted_password_with_tag = aesgcm.encrypt(iv, password.encode("utf-8"), additional_data)
    # AESGCM.encrypt returns ciphertext + 16-byte tag concatenated
    encrypted_password = encrypted_password_with_tag[:-16]
    tag = encrypted_password_with_tag[-16:]

    # RSA-OAEP encryption of the AES key
    encrypted_aes_key = public_key.encrypt(
        aes_key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    # Binary envelope layout (Instagram wire format):
    # [1 byte: version=1]
    # [1 byte: key_id]
    # [2 bytes LE: len(encrypted_aes_key)]
    # [len(encrypted_aes_key) bytes: RSA-encrypted AES key]
    # [12 bytes: IV]
    # [16 bytes: GCM auth tag]
    # [remaining bytes: encrypted password]
    header = struct.pack(
        "<BBH",
        1,                          # version
        pub_key_id & 0xFF,          # key_id truncated to 1 byte
        len(encrypted_aes_key),     # RSA block length (little-endian uint16)
    )
    envelope = (
        header
        + encrypted_aes_key
        + iv
        + tag
        + encrypted_password
    )

    encoded = base64.b64encode(envelope).decode("utf-8")
    return f"#PWD_INSTAGRAM:4:{timestamp}:{encoded}"


# ---------------------------------------------------------------------------
# Signing helper
# ---------------------------------------------------------------------------


def _sign_payload(data: dict) -> str:
    """HMAC-SHA256 sign a request body (Instagram API requirement)."""
    payload = json.dumps(data, separators=(",", ":"))
    sig = hmac.new(
        IG_SIG_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"ig_sig_key_version=4&signed_body={sig}.{payload}"


def _tz_offset(timezone: str) -> str:
    """Convert timezone string to UTC offset seconds."""
    offsets = {
        "America/New_York": "-18000",
        "America/Chicago": "-21600",
        "America/Denver": "-25200",
        "America/Los_Angeles": "-28800",
        "America/Phoenix": "-25200",
        "Europe/London": "0",
        "Europe/Paris": "3600",
    }
    return offsets.get(timezone, "-18000")


# ---------------------------------------------------------------------------
# Main login flow
# ---------------------------------------------------------------------------


class IGLoginFlow:
    """
    Full Instagram mobile API login flow.

    Instantiate per-login (not shared across accounts).
    """

    def __init__(
        self,
        device: DeviceProfile,
        proxy_url: str = "socks5://127.0.0.1:8089",
    ) -> None:
        self._device = device
        self._proxy_url = proxy_url
        self._cookies: dict[str, str] = {}
        self._csrf_token: str = ""
        self._pub_key: str = ""
        self._pub_key_id: int = 0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def login(
        self,
        account_id: str,
        username: str,
        password: str,
        code_provider: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> IGSession:
        """
        Execute the full login flow and return an authenticated IGSession.

        Args:
            account_id:    Our internal account ID.
            username:      Instagram username.
            password:      Plaintext password (never logged).
            code_provider: Async callable that returns a 2FA/SMS code string.
                           Called with a hint string ("sms" / "totp" / "email").
                           Required if 2FA is configured on the account.
        """
        async with self._build_client() as client:
            # Step 1 — register device + get pub key from sync
            sync_resp = await self._register_device(client)
            self._extract_pubkey_from_sync(sync_resp)

            # Step 2 — pre-login headers (CSRF token)
            csrf_token = await self._pre_login_flow(client)
            self._csrf_token = csrf_token

            # Step 3 — send credentials
            login_resp = await self._send_credentials(
                client, username, password, csrf_token
            )

            # Step 4 — interpret response
            return await self._interpret_login_response(
                account_id=account_id,
                username=username,
                login_resp=login_resp,
                client=client,
                code_provider=code_provider,
            )

    # ------------------------------------------------------------------
    # HTTP client factory
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict:
        d = self._device
        h = d.platform_headers.get("instagram")
        ua = (
            h.user_agent
            if h
            else (
                "Instagram 319.0.0.34.109 Android "
                "(28/9; 420dpi; 1080x2220; Samsung; SM-G975F; beyond1; "
                "exynos9820; en_US; 532654130)"
            )
        )
        device_id = h.device_id if h else f"android-{d.android_id}"
        phone_id = (
            h.extra.get("phone_id", str(uuid.uuid4())) if h else str(uuid.uuid4())
        )
        family_device_id = (
            h.extra.get("family_device_id", str(uuid.uuid4()))
            if h
            else str(uuid.uuid4())
        )
        return {
            "User-Agent": ua,
            "X-IG-App-ID": IG_APP_ID,
            "X-IG-Device-ID": device_id,
            "X-IG-Android-ID": f"android-{d.android_id}",
            "X-IG-Family-Device-ID": family_device_id,
            "X-IG-Capabilities": IG_CAPABILITIES,
            "X-IG-Connection-Type": IG_CONNECTION_TYPE,
            "X-IG-Timezone-Offset": _tz_offset(d.timezone),
            "X-Pigeon-Session-Id": str(uuid.uuid4()),
            "X-Pigeon-Rawclienttime": f"{time.time():.3f}",
            "X-Bloks-Version-Id": "ce555e5500576acd8e84a66018f54a05720f2dce29b8a3a1f6e1d4b3d7e4c2a1",
            "X-FB-HTTP-Engine": "Liger",
            "X-IG-WWW-Claim": "0",
            "Accept-Language": d.locale.replace("_", "-"),
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=self._proxy_url,
            headers=self._build_headers(),
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Step 1 — Device registration
    # ------------------------------------------------------------------

    async def _register_device(self, client: httpx.AsyncClient) -> dict:
        """
        POST /api/v1/qe/sync/
        Registers device, returns experiment assignments + may contain pub key.
        """
        d = self._device
        payload = {
            "id": str(uuid.uuid4()),
            "server_config_retrieval": "1",
            "_uuid": str(uuid.uuid4()),
            "experiments": (
                "ig_android_reg_nux_headers_cleanup_universe,"
                "ig_android_device_detection_info_upload,"
                "ig_android_nglite_gating"
            ),
        }
        try:
            resp = await client.post(
                f"{IG_API_BASE}/qe/sync/",
                content=_sign_payload(payload).encode(),
            )
            if resp.status_code in (200, 201):
                return resp.json()
            # Non-fatal — continue without experiment assignments
            log.debug("qe/sync returned %d — continuing", resp.status_code)
            return {}
        except httpx.HTTPError as exc:
            log.debug("qe/sync failed: %s — continuing", exc)
            return {}

    def _extract_pubkey_from_sync(self, sync_resp: dict) -> None:
        """Try to extract the password public key from the sync response."""
        # IG sometimes embeds it in qe/sync under different keys
        pk = (
            sync_resp.get("password_encryption_pub_key")
            or sync_resp.get("public_key")
            or sync_resp.get("enc_password_pub_key")
        )
        pk_id = (
            sync_resp.get("password_encryption_key_id")
            or sync_resp.get("pub_key_id")
            or 0
        )
        if pk:
            self._pub_key = pk
            self._pub_key_id = int(pk_id)

    # ------------------------------------------------------------------
    # Step 2 — Pre-login flow (CSRF token)
    # ------------------------------------------------------------------

    async def _pre_login_flow(self, client: httpx.AsyncClient) -> str:
        """
        GET /api/v1/si/fetch_headers/?challenge_type=signup
        Returns CSRF token from response cookies.
        """
        resp = await client.get(
            f"{IG_API_BASE}/si/fetch_headers/",
            params={"challenge_type": "signup", "guid": str(uuid.uuid4())},
        )
        # CSRF token is in the Set-Cookie header
        csrf = resp.cookies.get("csrftoken", "")
        if csrf:
            self._cookies["csrftoken"] = csrf
        # Also accept from response body
        if not csrf:
            try:
                data = resp.json()
                csrf = data.get("csrftoken", "") or data.get("csrf_token", "")
            except Exception:
                pass
        if not csrf:
            # Generate a fallback — Instagram sometimes skips it for new devices
            csrf = uuid.uuid4().hex[:32]
            log.debug("CSRF token not returned by fetch_headers — using generated token")
        return csrf

    # ------------------------------------------------------------------
    # Step 2b — Fetch password public key (if not obtained from qe/sync)
    # ------------------------------------------------------------------

    async def _fetch_password_pubkey(
        self, client: httpx.AsyncClient
    ) -> tuple[str, int]:
        """
        GET /api/v1/qe/sync/ or dedicated endpoint to fetch the RSA public key
        used for password encryption.

        Returns (pub_key_b64, key_id).
        """
        if self._pub_key:
            return self._pub_key, self._pub_key_id

        # Try the dedicated encryption key endpoint
        try:
            resp = await client.get(
                f"{IG_API_BASE}/qe/sync/",
                params={"server_config_retrieval": "1"},
            )
            if resp.status_code == 200:
                data = resp.json()
                pk = (
                    data.get("password_encryption_pub_key")
                    or data.get("public_key")
                    or data.get("enc_password_pub_key", "")
                )
                pk_id = int(
                    data.get("password_encryption_key_id")
                    or data.get("pub_key_id", 0)
                )
                if pk:
                    self._pub_key = pk
                    self._pub_key_id = pk_id
                    return pk, pk_id
        except httpx.HTTPError:
            pass

        raise IGLoginFailed("Failed to fetch password encryption public key from Instagram")

    # ------------------------------------------------------------------
    # Step 3 — Send credentials
    # ------------------------------------------------------------------

    async def _send_credentials(
        self,
        client: httpx.AsyncClient,
        username: str,
        password: str,
        csrf_token: str,
    ) -> dict:
        """
        POST /api/v1/accounts/login/
        Sends encrypted credentials. Returns raw API response dict.
        """
        pub_key, pub_key_id = await self._fetch_password_pubkey(client)
        encrypted_password = _encrypt_password(password, pub_key, pub_key_id)

        d = self._device
        h = d.platform_headers.get("instagram")
        device_id = h.device_id if h else f"android-{d.android_id}"
        phone_id = (
            h.extra.get("phone_id", str(uuid.uuid4())) if h else str(uuid.uuid4())
        )

        payload = {
            "jazoest": _compute_jazoest(phone_id),
            "country_codes": '[{"country_code":"1","source":["default"]}]',
            "phone_id": phone_id,
            "enc_password": encrypted_password,
            "username": username,
            "adid": d.advertising_id,
            "guid": str(uuid.uuid4()),
            "device_id": device_id,
            "google_tokens": "[]",
            "login_attempt_count": "0",
            "_csrftoken": csrf_token,
            "should_check_sso_session": "false",
        }

        try:
            resp = await client.post(
                f"{IG_API_BASE}/accounts/login/",
                content=_sign_payload(payload).encode(),
            )
        except httpx.HTTPError as exc:
            raise IGLoginFailed(f"Network error during login: {exc}") from exc

        if resp.status_code == 429:
            raise IGRateLimited("Instagram rate-limited login attempt")

        try:
            return resp.json()
        except Exception as exc:
            raise IGLoginFailed(
                f"Non-JSON login response (HTTP {resp.status_code})"
            ) from exc

    # ------------------------------------------------------------------
    # Step 4 — Interpret response
    # ------------------------------------------------------------------

    async def _interpret_login_response(
        self,
        *,
        account_id: str,
        username: str,
        login_resp: dict,
        client: httpx.AsyncClient,
        code_provider: Optional[Callable[[str], Awaitable[str]]],
    ) -> IGSession:
        # Success
        if login_resp.get("logged_in_user") or login_resp.get("status") == "ok":
            return self._extract_session(account_id, username, login_resp, client)

        # Two-factor required
        if login_resp.get("two_factor_required"):
            if code_provider is None:
                raise IGTwoFactorRequired(
                    f"2FA required for {username} but no code_provider was supplied"
                )
            two_fa_resp = await self.handle_2fa(
                username=username,
                two_factor_info=login_resp.get("two_factor_info", {}),
                code_provider=code_provider,
                client=client,
            )
            return self._extract_session(account_id, username, two_fa_resp, client)

        # Checkpoint / suspicious login challenge
        if login_resp.get("checkpoint_url") or login_resp.get("challenge"):
            checkpoint_url = login_resp.get("checkpoint_url") or (
                login_resp.get("challenge", {}).get("url", "")
            )
            # Attempt auto-resolution; raises IGCheckpointRequired if it needs manual help
            try:
                checkpoint_resp = await self.handle_checkpoint(
                    checkpoint_url=checkpoint_url,
                    session_cookies=dict(client.cookies),
                    client=client,
                    code_provider=code_provider,
                )
                return self._extract_session(
                    account_id, username, checkpoint_resp, client
                )
            except IGCheckpointRequired:
                raise
            except Exception as exc:
                raise IGCheckpointRequired(
                    checkpoint_url,
                    f"Checkpoint could not be auto-resolved: {exc}",
                ) from exc

        # Bad credentials
        message: str = login_resp.get("message", "")
        if "incorrect" in message.lower() or "password" in message.lower():
            raise IGLoginFailed(f"Bad credentials for {username}: {message}")

        # Any other failure
        raise IGLoginFailed(
            f"Login failed for {username}: status={login_resp.get('status')!r} "
            f"message={message!r}"
        )

    # ------------------------------------------------------------------
    # Step 5 — 2FA handler
    # ------------------------------------------------------------------

    async def handle_2fa(
        self,
        username: str,
        two_factor_info: dict,
        code_provider: Callable[[str], Awaitable[str]],
        client: httpx.AsyncClient,
    ) -> dict:
        """
        POST /api/v1/accounts/two_factor_login/
        Exchanges the 2FA code for a logged-in session.
        """
        # Determine method hint for code_provider
        method_type = two_factor_info.get("two_factor_identifier", "")
        totp_enabled = two_factor_info.get("totp_two_factor_on", False)
        sms_enabled = two_factor_info.get("sms_two_factor_on", True)

        if totp_enabled:
            method_hint = TwoFactorMethod.TOTP.value
        elif sms_enabled:
            method_hint = TwoFactorMethod.SMS.value
        else:
            method_hint = TwoFactorMethod.EMAIL.value

        code = await code_provider(method_hint)

        payload = {
            "username": username,
            "verification_code": code,
            "two_factor_identifier": two_factor_info.get("two_factor_identifier", ""),
            "identifier": two_factor_info.get("obfuscated_phone_number", ""),
            "_csrftoken": self._csrf_token,
            "_uuid": str(uuid.uuid4()),
            "trust_this_device": "1",
            "verification_method": "1" if totp_enabled else "0",
        }

        try:
            resp = await client.post(
                f"{IG_API_BASE}/accounts/two_factor_login/",
                content=_sign_payload(payload).encode(),
            )
        except httpx.HTTPError as exc:
            raise IGLoginFailed(f"Network error during 2FA: {exc}") from exc

        data = resp.json()
        if data.get("logged_in_user") or data.get("status") == "ok":
            return data

        raise IGLoginFailed(
            f"2FA login failed: {data.get('message', 'unknown error')}"
        )

    # ------------------------------------------------------------------
    # Step 6 — Checkpoint handler
    # ------------------------------------------------------------------

    async def handle_checkpoint(
        self,
        checkpoint_url: str,
        session_cookies: dict,
        client: httpx.AsyncClient,
        code_provider: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> dict:
        """
        Navigate the Instagram checkpoint challenge.

        Flow:
            GET  checkpoint_url  → inspect available verification methods
            POST challenge method selection
            GET  code from code_provider
            POST code to challenge

        Raises IGCheckpointRequired if manual intervention is needed
        (e.g. no code_provider, or unrecognised challenge type).
        """
        if not checkpoint_url:
            raise IGCheckpointRequired("", "Empty checkpoint URL")

        # Normalise URL
        if checkpoint_url.startswith("/"):
            checkpoint_url = f"https://i.instagram.com{checkpoint_url}"

        # GET the checkpoint page to discover the challenge form
        try:
            get_resp = await client.get(checkpoint_url)
            checkpoint_data = get_resp.json() if get_resp.status_code == 200 else {}
        except Exception:
            checkpoint_data = {}

        challenge_url = checkpoint_data.get("challenge", {}).get("url") or checkpoint_url

        # If we have no code provider, we cannot auto-resolve
        if code_provider is None:
            raise IGCheckpointRequired(
                checkpoint_url,
                "No code_provider supplied — checkpoint requires manual resolution",
            )

        # Select SMS verification (most common, method_type=0 or "SMS")
        select_payload = {
            "choice": "0",
            "_csrftoken": self._csrf_token,
            "_uuid": str(uuid.uuid4()),
        }
        try:
            await client.post(
                challenge_url,
                content=_sign_payload(select_payload).encode(),
            )
        except httpx.HTTPError:
            pass

        # Get verification code from provider
        code = await code_provider("checkpoint_sms")

        # Submit code
        submit_payload = {
            "security_code": code,
            "_csrftoken": self._csrf_token,
            "_uuid": str(uuid.uuid4()),
        }
        try:
            resp = await client.post(
                challenge_url,
                content=_sign_payload(submit_payload).encode(),
            )
            data = resp.json()
        except Exception as exc:
            raise IGCheckpointRequired(
                checkpoint_url,
                f"Failed to submit checkpoint code: {exc}",
            ) from exc

        if data.get("logged_in_user") or data.get("status") == "ok":
            return data

        raise IGCheckpointRequired(
            checkpoint_url,
            f"Checkpoint resolution failed: {data.get('message', 'unknown')}",
        )

    # ------------------------------------------------------------------
    # Step 7 — Session extraction
    # ------------------------------------------------------------------

    def _extract_session(
        self,
        account_id: str,
        username: str,
        login_response: dict,
        client: httpx.AsyncClient,
    ) -> IGSession:
        """Build an IGSession from the successful login response + client cookies."""
        user_data = login_response.get("logged_in_user", {})
        ig_user_id = str(
            user_data.get("pk")
            or user_data.get("id")
            or login_response.get("pk", "")
        )
        username_verified = user_data.get("username", username)

        cookies = dict(client.cookies)
        session_id = cookies.get("sessionid", "")
        csrf_token = cookies.get("csrftoken", self._csrf_token)
        mid = cookies.get("mid", "")
        ds_user_id = cookies.get("ds_user_id", ig_user_id)

        if not session_id:
            raise IGLoginFailed(
                f"Login succeeded but no sessionid cookie returned for {username}"
            )

        d = self._device
        h = d.platform_headers.get("instagram")
        platform_headers = PlatformHeaders(
            platform="instagram",
            session_token=session_id,
            device_id=h.device_id if h else f"android-{d.android_id}",
            user_agent=(
                h.user_agent
                if h
                else (
                    "Instagram 319.0.0.34.109 Android "
                    "(28/9; 420dpi; 1080x2220; Samsung; SM-G975F; beyond1; "
                    "exynos9820; en_US; 532654130)"
                )
            ),
            app_version=h.app_version if h else "319.0.0.34.109",
            android_id=d.android_id,
            advertising_id=d.advertising_id,
            carrier_name=d.carrier_name,
            carrier_mcc_mnc=d.carrier_mcc_mnc,
            locale=d.locale,
            timezone=d.timezone,
            extra={
                "mid": mid,
                "family_device_id": (
                    h.extra.get("family_device_id", str(uuid.uuid4())) if h else str(uuid.uuid4())
                ),
                "phone_id": (
                    h.extra.get("phone_id", str(uuid.uuid4())) if h else str(uuid.uuid4())
                ),
            },
        )

        return IGSession(
            account_id=account_id,
            ig_user_id=ig_user_id,
            username=username_verified,
            session_id=session_id,
            csrftoken=csrf_token,
            mid=mid,
            ds_user_id=ds_user_id,
            headers=platform_headers,
            is_valid=True,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_jazoest(phone_id: str) -> str:
    """
    Instagram's jazoest value: sum of ASCII codepoints in phone_id + 2.
    Prevents certain bot detection signals.
    """
    total = sum(ord(c) for c in phone_id) + 2
    return str(total)
