"""
IPRoyal Royal Residential Unlimited proxy orchestrator.

Responsibilities:
    - Build proxy URLs with state/city/sticky parameters matching persona region
    - Force-rotate on block signals (bumps session suffix → new IP)
    - Track per-account IP history (24h cooldown window — avoid reusing IPs
      that were recently seen by the platform)
    - Verify IP health before assigning to a session (HTTPS GET to checkip.amazonaws.com)
    - Enforce the safety gate: no session starts without verified routing

IPRoyal session format:
    username_country-US_state-{STATE}_city-{CITY}_session-{ID}_lifetime-{N}s

Rotation strategy:
    IPRoyal issues a NEW IP on every new session. To force rotation mid-session,
    call force_rotate(account_id) — it bumps the session suffix so the next
    build_session_url() call gets a fresh IP.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger("phantom_fleet.proxy")

_IP_CHECK_URL    = "https://checkip.amazonaws.com"
_IP_CHECK_TIMEOUT = 8.0   # seconds
_IP_COOLDOWN_SEC  = 86400  # 24 hours — don't reuse an IP within same day


@dataclass
class IPRoyalConfig:
    base_host:    str = "geo.iproyal.com"
    port_socks5:  int = 12321
    port_http:    int = 8080
    username:     str = ""
    password:     str = ""


@dataclass
class ProxyAssignment:
    account_id:   str
    proxy_url:    str
    external_ip:  str
    assigned_at:  float = field(default_factory=time.time)
    session_id:   str   = ""


class IPRoyalOrchestrator:
    """
    Build per-session proxy URLs with persona-region stickiness.
    Verifies IP before returning to callers — no session starts on a dead proxy.
    """

    def __init__(self, config: IPRoyalConfig):
        self.config = config
        # account_id → ProxyAssignment (current IP in use)
        self._assignments: dict[str, ProxyAssignment] = {}
        # account_id → list of (ip, assigned_at) tuples for cooldown tracking
        self._ip_history: dict[str, list[tuple[str, float]]] = {}
        # account_id → session suffix counter (bump to force rotation)
        self._session_counters: dict[str, int] = {}

    # ------------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------------

    def build_session_url(
        self,
        *,
        account_id: str,
        state: str,
        city: str,
        session_duration_sec: int = 900,
        scheme: str = "socks5",
    ) -> str:
        """
        Build an IPRoyal session URL for the given account.

        IPRoyal expects username parameters like:
            phantomfleet_country-US_state-NY_city-NewYork_session-abc_lifetime-15m

        Each account gets a deterministic-but-unique session suffix so
        different accounts in the same city get DIFFERENT IPs (IP isolation
        between accounts — required for detection safety).
        """
        counter = self._session_counters.get(account_id, 0)
        # Hash of account_id + counter → 8-char hex session suffix
        raw = f"{account_id}:{counter}".encode()
        session_suffix = hashlib.sha256(raw).hexdigest()[:8]

        parts = [
            self.config.username,
            "country-US",
            f"state-{state}",
            f"city-{city.replace(' ', '').replace(',', '')}",
            f"session-{session_suffix}",
            f"lifetime-{session_duration_sec}s",
        ]
        user = "_".join(parts)
        port = self.config.port_socks5 if scheme == "socks5" else self.config.port_http
        return f"{scheme}://{user}:{self.config.password}@{self.config.base_host}:{port}"

    # ------------------------------------------------------------------
    # IP verification
    # ------------------------------------------------------------------

    async def verify_ip(self, proxy_url: str) -> Optional[str]:
        """
        Make an HTTPS request through the proxy to checkip.amazonaws.com.
        Returns the external IP string on success, None on failure.

        Used by the safety gate before any account session starts.
        """
        try:
            async with httpx.AsyncClient(
                proxies=proxy_url,
                timeout=_IP_CHECK_TIMEOUT,
            ) as client:
                resp = await client.get(_IP_CHECK_URL)
                resp.raise_for_status()
                return resp.text.strip()
        except Exception as exc:
            log.warning("Proxy verify failed for %s: %s", proxy_url, exc)
            return None

    # ------------------------------------------------------------------
    # Assignment + rotation
    # ------------------------------------------------------------------

    async def assign_proxy(
        self,
        account_id: str,
        state: str,
        city: str,
        session_duration_sec: int = 900,
        scheme: str = "socks5",
        max_retries: int = 3,
    ) -> Optional[ProxyAssignment]:
        """
        Build a proxy URL, verify it works, and record the assignment.
        Retries up to max_retries times if the IP check fails.
        Returns None if all retries fail (caller should log + skip account).
        """
        for attempt in range(max_retries):
            url = self.build_session_url(
                account_id=account_id,
                state=state,
                city=city,
                session_duration_sec=session_duration_sec,
                scheme=scheme,
            )
            external_ip = await self.verify_ip(url)
            if external_ip is None:
                log.warning(
                    "Proxy IP check failed (attempt %d/%d) for account=%s",
                    attempt + 1, max_retries, account_id,
                )
                # Bump session counter so next attempt gets a different IP
                self._session_counters[account_id] = (
                    self._session_counters.get(account_id, 0) + 1
                )
                continue

            # Check cooldown — skip IPs seen in the last 24h for this account
            now = time.time()
            history = self._ip_history.get(account_id, [])
            recent_ips = {ip for ip, ts in history if now - ts < _IP_COOLDOWN_SEC}
            if external_ip in recent_ips:
                log.info(
                    "IP %s in 24h cooldown for account=%s, rotating",
                    external_ip, account_id,
                )
                self._session_counters[account_id] = (
                    self._session_counters.get(account_id, 0) + 1
                )
                continue

            # Record the assignment
            assignment = ProxyAssignment(
                account_id=account_id,
                proxy_url=url,
                external_ip=external_ip,
                session_id=f"{account_id}:{self._session_counters.get(account_id, 0)}",
            )
            self._assignments[account_id] = assignment

            # Track IP history
            if account_id not in self._ip_history:
                self._ip_history[account_id] = []
            self._ip_history[account_id].append((external_ip, now))
            # Prune old entries beyond 7 days
            cutoff = now - 7 * 86400
            self._ip_history[account_id] = [
                (ip, ts) for ip, ts in self._ip_history[account_id]
                if ts > cutoff
            ]

            log.info("Proxy assigned for account=%s ip=%s", account_id, external_ip)
            return assignment

        log.error(
            "All %d proxy attempts failed for account=%s — account will be skipped",
            max_retries, account_id,
        )
        return None

    def force_rotate(self, account_id: str) -> None:
        """
        Force IP rotation on next assign_proxy() call for this account.
        Called when the platform returns a 429 / block signal.
        """
        self._session_counters[account_id] = (
            self._session_counters.get(account_id, 0) + 1
        )
        # Remove stale assignment so callers can't accidentally reuse blocked IP
        self._assignments.pop(account_id, None)
        log.info("Force-rotate triggered for account=%s", account_id)

    def current_assignment(self, account_id: str) -> Optional[ProxyAssignment]:
        """Return the current live assignment for an account, or None."""
        return self._assignments.get(account_id)

    def fleet_status(self) -> dict:
        """Summary for ops dashboard: how many accounts have active proxies."""
        return {
            "accounts_with_proxy": len(self._assignments),
            "total_ips_tracked": sum(len(v) for v in self._ip_history.values()),
        }


def iproyal_from_env() -> "IPRoyalOrchestrator":
    """
    Build an IPRoyalOrchestrator from environment variables.

    Required env vars:
        IPROYAL_USER — IPRoyal username
        IPROYAL_PASS — IPRoyal password

    Optional:
        IPROYAL_HOST       — default: geo.iproyal.com
        IPROYAL_PORT_SOCKS — default: 12321
        IPROYAL_PORT_HTTP  — default: 8080

    Raises RuntimeError if credentials are missing.
    """
    import os
    user = os.environ.get("IPROYAL_USER", "")
    pwd  = os.environ.get("IPROYAL_PASS", "")
    if not user or not pwd:
        raise RuntimeError(
            "IPROYAL_USER and IPROYAL_PASS environment variables must be set. "
            "Get credentials at dashboard.iproyal.com."
        )
    return IPRoyalOrchestrator(IPRoyalConfig(
        username=user,
        password=pwd,
        base_host=os.environ.get("IPROYAL_HOST", "geo.iproyal.com"),
        port_socks5=int(os.environ.get("IPROYAL_PORT_SOCKS", "12321")),
        port_http=int(os.environ.get("IPROYAL_PORT_HTTP", "8080")),
    ))


# ══════════════════════════════════════════════════════════════════════════════
# ISP Proxy Pool — for static IPRoyal ISP proxies (1 IP per phone, no rotation)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ISPProxy:
    """One static ISP proxy entry as delivered by IPRoyal."""
    host:     str
    port:     int
    username: str
    password: str

    def url(self, scheme: str = "socks5") -> str:
        return f"{scheme}://{self.username}:{self.password}@{self.host}:{self.port}"

    @classmethod
    def parse(cls, line: str) -> "ISPProxy":
        """
        Parse a single proxy line.  IPRoyal delivers ISP proxies in either:
            host:port:user:pass
            host:port  (shared creds supplied separately)
        """
        parts = line.strip().split(":")
        if len(parts) == 4:
            return cls(host=parts[0], port=int(parts[1]),
                       username=parts[2], password=parts[3])
        if len(parts) == 2:
            return cls(host=parts[0], port=int(parts[1]),
                       username="", password="")
        raise ValueError(f"Cannot parse proxy line: {line!r}")


class ISPProxyPool:
    """
    Manages a fixed pool of static ISP proxies.

    Assignment strategy: each account_id is hashed to a slot in the pool
    (deterministic — same account always gets the same proxy so the IP is
    stable across restarts, which is what Instagram expects from a WiFi
    household connection).

    Per-account grouping: with accounts_per_ip=4 and accounts_per_phone=12,
    each phone's 12 accounts are split into 3 groups of 4. Each group gets
    its own proxy slot, reducing accounts-per-IP from 12 to 4.

    To reassign an account's group to a different proxy (e.g. IP flagged),
    call reassign_account(phone_serial, account_id).
    """

    def __init__(
        self,
        proxies: list[ISPProxy],
        accounts_per_ip: int = 4,
        accounts_per_phone: int = 12,
    ):
        if not proxies:
            raise ValueError("ISPProxyPool requires at least one proxy")
        self._pool = proxies
        self.accounts_per_ip = accounts_per_ip
        self.groups_per_phone = math.ceil(accounts_per_phone / accounts_per_ip)
        # slot-key → offset (bumped on reassign)
        self._overrides: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def _slot(self, key: str) -> int:
        base = int(hashlib.sha256(key.encode()).hexdigest(), 16)
        offset = self._overrides.get(key, 0)
        return (base + offset) % len(self._pool)

    def _group_key(self, phone_serial: str, account_id: str) -> str:
        """
        Deterministically assign account_id to one of groups_per_phone groups
        within its phone. Accounts in the same group share an IP; accounts in
        different groups get different IPs.
        """
        account_hash = int(hashlib.sha256(account_id.encode()).hexdigest(), 16)
        group = account_hash % self.groups_per_phone
        return f"{phone_serial}:g{group}"

    # ------------------------------------------------------------------
    # Per-account assignment (preferred — reduces accounts-per-IP)
    # ------------------------------------------------------------------

    def get_for_account(self, phone_serial: str, account_id: str, scheme: str = "socks5") -> str:
        """
        Return the proxy URL for a specific account on a device.

        Accounts are split into groups_per_phone groups. Each group of
        accounts_per_ip accounts shares one proxy slot, so IP exposure per
        account is bounded rather than all 12 accounts sharing one IP.
        """
        key = self._group_key(phone_serial, account_id)
        return self._pool[self._slot(key)].url(scheme)

    def get_proxy_for_account(self, phone_serial: str, account_id: str) -> ISPProxy:
        """Return the ISPProxy assigned to this (phone, account) pair."""
        key = self._group_key(phone_serial, account_id)
        return self._pool[self._slot(key)]

    def reassign_account(self, phone_serial: str, account_id: str) -> str:
        """
        Move this account's group to the next proxy.
        Affects all accounts in the same group (they share an IP slot).
        Call when Instagram flags the current IP for this account.
        """
        key = self._group_key(phone_serial, account_id)
        self._overrides[key] = self._overrides.get(key, 0) + 1
        new_url = self._pool[self._slot(key)].url()
        log.info("Proxy group reassigned for key=%s → slot=%d", key, self._slot(key))
        return new_url

    def get_for_device(self, phone_serial: str, scheme: str = "socks5") -> str:
        """
        Return the proxy URL for a phone.  All accounts on the same physical
        device MUST call this with the device serial — not with account_id —
        so they all route through the same IP (matching real-device behaviour
        where every app shares the same WiFi connection).
        """
        return self._pool[self._slot(phone_serial)].url(scheme)

    def get_proxy_for_device(self, phone_serial: str) -> ISPProxy:
        """Return the ISPProxy dataclass assigned to this device."""
        return self._pool[self._slot(phone_serial)]

    # Keep account_id-keyed helpers for callers that don't have a serial
    def get(self, account_id: str, scheme: str = "socks5") -> str:
        """Return the SOCKS5 (or HTTP) proxy URL assigned to this account.
        Prefer get_for_device(phone_serial) when the serial is available."""
        return self._pool[self._slot(account_id)].url(scheme)

    def get_proxy(self, account_id: str) -> ISPProxy:
        """Return the ISPProxy dataclass assigned to this account."""
        return self._pool[self._slot(account_id)]

    def reassign(self, key: str) -> str:
        """
        Shift this device/account to the next proxy in the pool.
        Pass phone_serial when reassigning a whole device (recommended),
        or account_id to reassign a single account.
        Call when Instagram flags the current IP.
        Returns the new proxy URL.
        """
        self._overrides[key] = self._overrides.get(key, 0) + 1
        new_url = self._pool[self._slot(key)].url()
        log.info("ISP proxy reassigned for key=%s → slot=%d", key, self._slot(key))
        return new_url

    async def verify_device(self, phone_serial: str) -> Optional[str]:
        """
        Verify the proxy assigned to a phone is alive.
        Returns external IP string on success, None on failure.
        All accounts on this phone share this result.
        """
        url = self.get_for_device(phone_serial)
        try:
            async with httpx.AsyncClient(
                proxies=url,
                timeout=_IP_CHECK_TIMEOUT,
            ) as client:
                resp = await client.get(_IP_CHECK_URL)
                resp.raise_for_status()
                ip = resp.text.strip()
                log.info("ISP proxy verified for device=%s ip=%s", phone_serial, ip)
                return ip
        except Exception as exc:
            log.warning("ISP proxy verify failed for device=%s: %s", phone_serial, exc)
            return None

    async def verify(self, account_id: str) -> Optional[str]:
        """Legacy: verify by account_id. Use verify_device(serial) instead."""
        return await self.verify_device(account_id)

    def fleet_status(self) -> dict:
        return {
            "pool_size": len(self._pool),
            "accounts_per_ip": self.accounts_per_ip,
            "groups_per_phone": self.groups_per_phone,
            "reassigned_keys": len(self._overrides),
        }


def smartproxy_pool_from_env() -> Optional["ISPProxyPool"]:
    """
    Build an ISPProxyPool from Smartproxy static residential proxies.

    Set ONE of:
        SMARTPROXY_PROXIES  — comma-separated lines: host:port:user:pass,...
        SMARTPROXY_FILE     — path to a text file with one proxy per line

    Shared-credential form (if Smartproxy delivers host:port only):
        SMARTPROXY_USER / SMARTPROXY_PASS
    """
    import os

    shared_user = os.environ.get("SMARTPROXY_USER", "")
    shared_pass = os.environ.get("SMARTPROXY_PASS", "")

    raw_lines: list[str] = []

    inline = os.environ.get("SMARTPROXY_PROXIES", "")
    if inline:
        raw_lines = [l.strip() for l in inline.split(",") if l.strip()]
    else:
        fpath = os.environ.get("SMARTPROXY_FILE", "")
        if fpath and os.path.isfile(fpath):
            with open(fpath) as f:
                raw_lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    if not raw_lines:
        return None

    proxies: list[ISPProxy] = []
    for line in raw_lines:
        p = ISPProxy.parse(line)
        if not p.username and shared_user:
            p.username = shared_user
            p.password = shared_pass
        proxies.append(p)

    accounts_per_ip    = int(os.environ.get("SMARTPROXY_ACCOUNTS_PER_IP",    "6"))
    accounts_per_phone = int(os.environ.get("SMARTPROXY_ACCOUNTS_PER_PHONE", "12"))
    log.info("Loaded %d Smartproxy proxies from environment", len(proxies))
    return ISPProxyPool(proxies, accounts_per_ip=accounts_per_ip, accounts_per_phone=accounts_per_phone)


def isp_pool_from_env() -> Optional["ISPProxyPool"]:
    """
    Build an ISPProxyPool from environment variables.

    Set ONE of:
        IPROYAL_ISP_PROXIES  — comma-separated proxy lines: host:port:user:pass,...
        IPROYAL_ISP_FILE     — path to a text file with one proxy per line

    If neither is set, returns None (caller falls back to residential pool).

    Shared-credential form:
        If lines are host:port only, also set:
            IPROYAL_ISP_USER / IPROYAL_ISP_PASS
        and those creds will be injected into every entry.
    """
    import os

    shared_user = os.environ.get("IPROYAL_ISP_USER", "")
    shared_pass = os.environ.get("IPROYAL_ISP_PASS", "")

    raw_lines: list[str] = []

    inline = os.environ.get("IPROYAL_ISP_PROXIES", "")
    if inline:
        raw_lines = [l.strip() for l in inline.split(",") if l.strip()]
    else:
        fpath = os.environ.get("IPROYAL_ISP_FILE", "")
        if fpath and os.path.isfile(fpath):
            with open(fpath) as f:
                raw_lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    if not raw_lines:
        return None

    proxies: list[ISPProxy] = []
    for line in raw_lines:
        p = ISPProxy.parse(line)
        # Inject shared creds if individual creds absent
        if not p.username and shared_user:
            p.username = shared_user
            p.password = shared_pass
        proxies.append(p)

    log.info("Loaded %d ISP proxies from environment", len(proxies))
    return ISPProxyPool(proxies)
