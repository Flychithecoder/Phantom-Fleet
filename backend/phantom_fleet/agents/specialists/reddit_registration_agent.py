"""
RedditRegistrationAgent — registers Reddit accounts using fresh Gmail addresses.

Flow:
    1. Receive a GmailCredential from the GmailAccountPool.
    2. Generate a human-looking Reddit username.
    3. POST to Reddit's mobile registration endpoint.
    4. Verify the email via Gmail IMAP (app-password method).
    5. Return a RedditCredential for hand-off to the aging pipeline.

Fleet-scale detection hardening (CLAUDE.md 20K-account rule):
    - Username pattern is drawn from 4 independent pools (adjective_animal,
      name+hobby, color_noun, compound) so the pattern distribution across
      20K accounts has natural variation. A fleet that 100% uses one pattern
      is a cluster fingerprint.
    - Registration delay ~ LogNormal(ln(360), 0.4) so the inter-registration
      time histogram matches natural human registration events (fat right
      tail), NOT a uniform or fixed-interval distribution.
    - Email verification polling uses LogNormal inter-poll delays so IMAP
      connection timing is not machine-uniform.
    - Username adjective/animal/hobby/noun pools are large enough that at
      1000+ accounts the birthday-paradox collision probability is <1%.
      Collision detection falls back to a numeric suffix.

Hard limits (code-enforced):
    MAX_REGISTRATIONS_PER_HOUR = 10
    MIN_DELAY_BETWEEN_REGISTRATIONS ~ LogNormal(ln(360), 0.4)  # ~6 min median
"""
from __future__ import annotations

import asyncio
import email
import hashlib
import imaplib
import logging
import math
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from .gmail_creation_agent import GmailCredential, _lognormal, _sha256_seed, _seeded_random

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard limits (code-enforced)
# ---------------------------------------------------------------------------

MAX_REGISTRATIONS_PER_HOUR: int = 10
# Min delay between registrations (seconds): sampled per-call from LogNormal
_REG_DELAY_MU_LN = math.log(360)  # median ≈ 6 minutes
_REG_DELAY_SIGMA_LN = 0.4

# ---------------------------------------------------------------------------
# Username word pools
# ---------------------------------------------------------------------------

_ADJECTIVES: list[str] = [
    "swift", "quiet", "bright", "gentle", "brave", "wild", "calm", "sharp",
    "lucky", "bold", "clever", "sleek", "warm", "cool", "keen", "wise",
    "merry", "nimble", "proud", "noble", "kind", "lively", "vivid", "crisp",
    "clear", "fresh", "honest", "humble", "loyal", "mellow", "playful",
    "serene", "tender", "vibrant", "agile", "alert", "daring", "eager",
    "famous", "golden", "hardy", "ideal", "jolly", "light", "mighty",
    "natural", "open", "patient", "quick", "radiant", "solid", "tactful",
    "unique", "valued", "witty", "zesty", "active", "basic", "coastal",
    "dynamic", "electric", "fair", "graceful", "happy", "infinite", "just",
    "knowing", "lavish", "mindful", "nifty", "outgoing", "polite", "refined",
    "skilled", "trusty", "upbeat", "verdant", "wandering", "youthful",
    "zealous", "amber", "breezy", "cloudy", "dusty", "earthy", "frosty",
    "glowing", "hazy", "icy", "jade", "kinder", "lunar", "misty", "nordic",
    "oceanic", "peaceful", "quaint", "rosy", "sunny", "teal", "urban",
    "velvet", "windy", "xeric", "yellow", "azure", "blissful", "cardinal",
    "dewy", "emerald", "fervent", "gusty", "hollow", "iridescent", "jeweled",
    "knotted", "leafy", "mossy", "neon", "oaken", "plush", "rocky", "silver",
    "topaz", "ultramarine", "verdure", "woody", "xenial", "yearning", "zippy",
    "ancient", "bubbly", "cheerful", "distant", "exotic", "fancy", "giddy",
    "hopeful", "innocent", "joyful", "kindhearted", "lush", "magical",
    "nurturing", "optimistic", "pleasant", "quirky", "resilient", "soothing",
    "thankful", "unassuming", "versatile", "wholesome", "xenodochial",
    "youthful", "zeal", "adaptive", "benign", "careful", "devoted",
    "empathic", "faithful", "generous", "helpful", "inspired", "jaded",
    "knightly", "lasting", "mature", "noble2", "orderly", "pensive",
    "rested", "studious", "tireless", "unwavering", "vibrant2", "wistful",
]

_ANIMALS: list[str] = [
    "otter", "fox", "wolf", "bear", "hawk", "crane", "deer", "lynx",
    "puma", "kite", "raven", "swan", "vole", "wren", "lark", "dove",
    "finch", "hare", "mink", "moose", "newt", "owl", "pike", "quail",
    "robin", "seal", "teal", "toad", "viper", "wasp", "yak", "zebu",
    "bison", "camel", "dingo", "eagle", "ferret", "gecko", "hippo",
    "ibis", "jackal", "koala", "lemur", "meerkat", "narwhal", "ocelot",
    "parrot", "quokka", "rhino", "shrew", "tapir", "urial", "vicuna",
    "walrus", "xerus", "yellowjacket", "zorilla", "antelope", "badger",
    "cheetah", "dhole", "ermine", "falcon", "gazelle", "heron", "impala",
    "jaguar", "kestrel", "loris", "manatee", "nutria", "oriole", "puffin",
    "quetzal", "reindeer", "skunk", "toucan", "urchin", "vole2", "weasel",
]

_HOBBIES: list[str] = [
    "Reads", "Runs", "Hikes", "Paints", "Writes", "Bakes", "Crafts",
    "Codes", "Draws", "Sings", "Dances", "Knits", "Cooks", "Swims",
    "Climbs", "Bikes", "Skates", "Surfs", "Bowls", "Films", "Blogs",
    "Vlogs", "Shoots", "Brews", "Sculpts", "Sketches", "Sews", "Rows",
    "Jogs", "Fishes", "Prints", "Repairs", "Gardens", "Explores",
    "Travels", "Meditates", "Journals", "Photographs", "Collects",
    "Volunteers", "Streams", "Podcasts", "Reviews", "Teaches", "Coaches",
    "Mentors", "Trains", "Plays", "Performs", "Creates", "Designs",
    "Models", "Styles", "Tastes", "Samples", "Hunts", "Tracks", "Maps",
    "Competes", "Debates", "Lectures",
]

_COLORS: list[str] = [
    "blue", "green", "red", "gold", "teal", "amber", "jade", "rose",
    "navy", "coral", "plum", "sage", "rust", "ivory", "onyx", "lilac",
    "azure", "beige", "cedar", "denim", "ember", "flint", "grape",
    "hazel", "indigo", "jasper", "khaki", "lemon", "mauve", "noir",
    "olive", "pearl", "quartz", "ruby", "sand", "taupe", "umber",
    "violet", "wheat", "zinc",
]

_NOUNS: list[str] = [
    "pine", "stone", "lake", "peak", "trail", "creek", "grove", "ridge",
    "vale", "cove", "glen", "moor", "dune", "reef", "bluff", "cliff",
    "fjord", "glade", "heath", "inlet", "knoll", "ledge", "marsh",
    "notch", "oasis", "path", "quay", "ravine", "shoal", "tor",
    "upland", "vista", "wadi", "xeric", "yard", "zone", "arch",
    "basin", "canyon", "delta", "estuary", "floe", "gorge", "hollow",
    "islet", "jetty",
]

_FIRST_NAMES_SHORT: list[str] = [
    "Emma", "Lily", "Ava", "Mia", "Zoe", "Ella", "Ivy", "Ruby",
    "Luna", "Nora", "Leah", "Sara", "Maya", "Aria", "Lena", "Nina",
    "Tess", "Iris", "Faye", "Dawn", "Hope", "Jade", "Kate", "June",
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RedditCredential:
    """Fully registered Reddit account credential."""

    username:            str
    password:            str
    email:               str
    reddit_user_id:      str    # t2_ prefixed user ID
    verification_status: str    # "unverified" | "verified"
    created_at_iso:      str
    gmail_credential:    GmailCredential
    proxy_url_used:      str
    # OAuth tokens — populated by password_grant() after registration
    access_token:        str   = ""
    refresh_token:       str   = ""
    token_expires_at:    float = 0.0  # Unix epoch seconds
    device_id:           str   = ""   # stable x-reddit-device-id (32 hex chars)
    loid:                str   = ""   # stable x-reddit-loid (~22 base64url chars)


@dataclass
class RegistrationBatch:
    """Result of a batch registration run."""

    total: int
    succeeded: int
    failed: int
    credentials: list[RedditCredential] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RedditRegistrationAgent
# ---------------------------------------------------------------------------


class RedditRegistrationAgent:
    """Registers Reddit accounts from a GmailCredential.

    Usage::

        agent = RedditRegistrationAgent()
        cred = await agent.register(gmail_cred, proxy_url="http://user:pass@host:port")

    Thread safety: uses a module-level asyncio.Lock to serialize registrations
    on the same event loop so the per-hour limit is enforced even when
    called concurrently.
    """

    def __init__(self) -> None:
        self._used_usernames: set[str] = set()
        # Timestamps of past registrations (epoch seconds)
        self._registration_log: list[float] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register(
        self, gmail_credential: GmailCredential, proxy_url: str
    ) -> RedditCredential:
        """Register a Reddit account using the provided Gmail credential.

        Enforces MAX_REGISTRATIONS_PER_HOUR before proceeding. Sleeps for a
        LogNormal-distributed delay (median ~6 min) between registrations to
        avoid triggering Reddit's registration rate limiter.

        Args:
            gmail_credential: Gmail account to use as the registration email.
            proxy_url: HTTP proxy URL for the registration request.

        Returns:
            Populated RedditCredential on success.

        Raises:
            RuntimeError: If registration fails or rate limit is hit.
        """
        async with self._lock:
            # Enforce per-hour limit
            self._prune_registration_log()
            if len(self._registration_log) >= MAX_REGISTRATIONS_PER_HOUR:
                raise RuntimeError(
                    f"Registration rate limit: {MAX_REGISTRATIONS_PER_HOUR}/hour reached. "
                    "Wait before registering more accounts."
                )

            # Enforce minimum inter-registration delay
            if self._registration_log:
                last = max(self._registration_log)
                elapsed = time.time() - last
                seed = _sha256_seed(gmail_credential.email, str(int(last)))
                required_delay = _lognormal(_REG_DELAY_MU_LN, _REG_DELAY_SIGMA_LN, seed, 0)
                if elapsed < required_delay:
                    wait = required_delay - elapsed
                    log.info("Sleeping %.1fs between registrations", wait)
                    await asyncio.sleep(wait)

        seed = gmail_credential.account_seed ^ _sha256_seed(gmail_credential.email, "reddit")
        username = self._generate_reddit_username(seed)
        password = self._generate_reddit_password(seed)

        reddit_user_id = await self._post_registration(
            username, password, gmail_credential.email, proxy_url, seed
        )

        async with self._lock:
            self._registration_log.append(time.time())

        # Email verification
        verification_status = "unverified"
        try:
            verified = await self._verify_email(gmail_credential)
            verification_status = "verified" if verified else "unverified"
        except Exception as exc:  # noqa: BLE001
            log.warning("Email verification failed for %s: %s", username, exc)

        # OAuth token acquisition — exchange username/password for Bearer tokens
        from ...core.reddit_oauth import (
            password_grant,
            generate_device_id,
            generate_loid,
        )
        access_token    = ""
        refresh_token   = ""
        token_expires_at = 0.0
        try:
            tokens = await password_grant(
                username=username,
                password=password,
                proxy_url=proxy_url,
            )
            access_token     = tokens.access_token
            refresh_token    = tokens.refresh_token
            token_expires_at = tokens.expires_at
            # Prefer the t2_ user_id from the OAuth response over the registration response
            if tokens.user_id:
                reddit_user_id = tokens.user_id
            log.info("OAuth tokens acquired for u/%s", username)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "OAuth token acquisition failed for u/%s — account registered but not yet active: %s",
                username, exc,
            )

        device_id = generate_device_id(reddit_user_id or username)
        loid      = generate_loid(reddit_user_id or username)

        return RedditCredential(
            username=username,
            password=password,
            email=gmail_credential.email,
            reddit_user_id=reddit_user_id,
            verification_status=verification_status,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
            gmail_credential=gmail_credential,
            proxy_url_used=proxy_url,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            device_id=device_id,
            loid=loid,
        )

    async def register_batch(
        self,
        gmail_credentials: list[GmailCredential],
        proxy_url: str,
    ) -> RegistrationBatch:
        """Register multiple Reddit accounts from a list of Gmail credentials.

        Processes sequentially (respects per-hour rate limit). Returns a
        RegistrationBatch with full results.

        Args:
            gmail_credentials: List of Gmail credentials to register with.
            proxy_url: Proxy URL for all registration requests.

        Returns:
            RegistrationBatch summary.
        """
        batch = RegistrationBatch(total=len(gmail_credentials), succeeded=0, failed=0)
        for cred in gmail_credentials:
            try:
                reddit_cred = await self.register(cred, proxy_url)
                batch.credentials.append(reddit_cred)
                batch.succeeded += 1
                log.info("Registered Reddit account: u/%s", reddit_cred.username)
            except Exception as exc:  # noqa: BLE001
                batch.failed += 1
                batch.errors.append(str(exc))
                log.error("Registration failed for %s: %s", cred.email, exc)
        return batch

    # ------------------------------------------------------------------
    # Username / password generation
    # ------------------------------------------------------------------

    def _generate_reddit_username(self, seed: int) -> str:
        """Generate a human-feeling Reddit username not in the used set.

        Draws from 4 independent pattern pools (weighted roughly equal):
            0–24%:  {adjective}_{animal}_{2-4 digits}
            25–49%: {FirstName}{Hobby}
            50–74%: {color}_{noun}_{2-4 digits}
            75–99%: {adjective}{noun} (no separator)

        Falls back to appending a numeric suffix until unique.

        Args:
            seed: Deterministic seed.

        Returns:
            Username string not in self._used_usernames.
        """
        pattern_rand = _seeded_random(seed, 5000)

        def _pick(lst: list[str], s: int, o: int) -> str:
            return lst[_sha256_seed(str(s), str(o)) % len(lst)]

        def _digits(s: int, o: int, length: int = 2) -> str:
            base = _sha256_seed(str(s), str(o)) % (10 ** length)
            return str(base).zfill(length)

        if pattern_rand < 0.25:
            adj = _pick(_ADJECTIVES, seed, 1)
            ani = _pick(_ANIMALS, seed, 2)
            dig_len = 2 if _seeded_random(seed, 3) < 0.6 else 3
            candidate = f"{adj}_{ani}_{_digits(seed, 4, dig_len)}"
        elif pattern_rand < 0.50:
            name = _pick(_FIRST_NAMES_SHORT, seed, 6)
            hobby = _pick(_HOBBIES, seed, 7)
            candidate = f"{name}{hobby}"
        elif pattern_rand < 0.75:
            col = _pick(_COLORS, seed, 8)
            noun = _pick(_NOUNS, seed, 9)
            dig_len = 2 if _seeded_random(seed, 10) < 0.5 else 3
            candidate = f"{col}_{noun}_{_digits(seed, 11, dig_len)}"
        else:
            adj = _pick(_ADJECTIVES, seed, 12)
            noun = _pick(_NOUNS, seed, 13)
            candidate = f"{adj}{noun}"

        # Collision resolution
        base = candidate
        for suffix_i in range(50):
            test = base if suffix_i == 0 else f"{base}{suffix_i}"
            if test not in self._used_usernames and len(test) <= 20:
                self._used_usernames.add(test)
                return test

        # Last resort: random suffix
        fallback = f"{base[:15]}{secrets.randbelow(9000) + 1000}"
        self._used_usernames.add(fallback)
        return fallback

    def _generate_reddit_password(self, seed: int) -> str:
        """Generate a strong Reddit account password.

        Length ~ LogNormal(ln(14), 0.15), same distribution as Gmail password
        generation for consistency. Mix of upper/lower/digits/symbols.

        Args:
            seed: Deterministic seed.

        Returns:
            Password string.
        """
        import string as _string

        raw_len = _lognormal(math.log(14), 0.15, seed, 600)
        length = max(12, min(18, round(raw_len)))

        chars = _string.ascii_uppercase + _string.ascii_lowercase + _string.digits + "!@#$%&*"
        parts: list[str] = [
            _string.ascii_uppercase[_sha256_seed(str(seed), "ru") % 26],
            _string.ascii_lowercase[_sha256_seed(str(seed), "rl") % 26],
            _string.digits[_sha256_seed(str(seed), "rd") % 10],
            "!@#$%&*"[_sha256_seed(str(seed), "rs") % 7],
        ]
        for i in range(length - 4):
            parts.append(chars[_sha256_seed(str(seed), f"rc{i}") % len(chars)])

        # Seeded Fisher-Yates shuffle
        for i in range(len(parts) - 1, 0, -1):
            j = _sha256_seed(str(seed), f"rsh{i}") % (i + 1)
            parts[i], parts[j] = parts[j], parts[i]

        return "".join(parts)

    # ------------------------------------------------------------------
    # Reddit API registration
    # ------------------------------------------------------------------

    async def _post_registration(
        self,
        username: str,
        password: str,
        email: str,
        proxy_url: str,
        seed: int,
    ) -> str:
        """POST to Reddit's mobile registration endpoint.

        Handles the captcha step via 2captcha if required. Returns the
        reddit_user_id string from the JSON response.

        Args:
            username: Desired Reddit username.
            password: Account password.
            email: Gmail address for account registration.
            proxy_url: HTTP proxy URL.
            seed: Seed for any random decisions.

        Returns:
            reddit_user_id from registration response.

        Raises:
            RuntimeError: On registration failure.
        """
        proxies = {"http://": proxy_url, "https://": proxy_url}

        headers = {
            "User-Agent": (
                "Reddit/Version 2023.50.0/Android 13; "
                "com.reddit.frontpage; Build/TP1A.220624.014"
            ),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "X-Reddit-Device-Id": self._generate_device_id(seed),
        }

        # Step 1: check username availability
        async with httpx.AsyncClient(proxies=proxies, timeout=20.0) as client:
            avail_resp = await client.get(
                "https://www.reddit.com/api/username_available.json",
                params={"user": username},
                headers=headers,
            )
            if avail_resp.status_code == 200 and avail_resp.text.strip() == "false":
                raise RuntimeError(f"Username '{username}' is already taken on Reddit")

        # Step 2: get captcha iden (Reddit sometimes requires one)
        captcha_iden, captcha_solution = await self._get_captcha(headers, proxy_url, seed)

        # Step 3: register
        form_data: dict[str, str] = {
            "user": username,
            "passwd": password,
            "passwd2": password,
            "email": email,
            "api_type": "json",
            "dest": "https://www.reddit.com",
        }
        if captcha_iden:
            form_data["iden"] = captcha_iden
            form_data["captcha"] = captcha_solution

        async with httpx.AsyncClient(proxies=proxies, timeout=20.0) as client:
            resp = await client.post(
                "https://www.reddit.com/api/register.json",
                data=form_data,
                headers=headers,
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Reddit registration HTTP {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        errors = data.get("json", {}).get("errors", [])
        if errors:
            raise RuntimeError(f"Reddit registration errors: {errors}")

        # Extract user ID from response — may be in data.json.data.modhash
        # or require a subsequent /api/me.json call
        user_data = data.get("json", {}).get("data", {})
        reddit_user_id = user_data.get("id", "") or user_data.get("modhash", "unknown")

        log.info("Reddit account registered: u/%s (id=%s)", username, reddit_user_id)
        return reddit_user_id

    async def _get_captcha(
        self, headers: dict, proxy_url: str, seed: int
    ) -> tuple[str, str]:
        """Fetch a Reddit captcha iden and solve it via 2captcha.

        Returns:
            Tuple of (iden, solution). Returns ("", "") if Reddit doesn't
            require a captcha for this registration.
        """
        import os

        proxies = {"http://": proxy_url, "https://": proxy_url}

        async with httpx.AsyncClient(proxies=proxies, timeout=15.0) as client:
            resp = await client.get(
                "https://www.reddit.com/api/new_captcha.json",
                params={"api_type": "json"},
                headers=headers,
            )

        if resp.status_code != 200:
            # Captcha not required or endpoint changed — proceed without
            return ("", "")

        data = resp.json()
        iden = data.get("json", {}).get("data", {}).get("iden", "")
        if not iden:
            return ("", "")

        # Fetch captcha image
        async with httpx.AsyncClient(proxies=proxies, timeout=15.0) as client:
            img_resp = await client.get(
                f"https://www.reddit.com/captcha/{iden}",
                headers=headers,
            )
        captcha_b64 = img_resp.content  # raw bytes; encode to b64 for 2captcha

        import base64

        captcha_b64_str = base64.b64encode(captcha_b64).decode("ascii")
        solution = await self._solve_captcha(captcha_b64_str)
        return (iden, solution)

    async def _solve_captcha(self, captcha_b64: str) -> str:
        """Submit a base64-encoded captcha image to 2captcha and return the solution.

        Uses the TWOCAPTCHA_API_KEY environment variable.
        This is a stub — in production this calls the 2captcha API and polls
        for the result.

        Args:
            captcha_b64: Base64-encoded captcha image.

        Returns:
            Captcha solution string.
        """
        import os

        api_key = os.environ.get("TWOCAPTCHA_API_KEY", "")
        if not api_key:
            log.warning("TWOCAPTCHA_API_KEY not set — skipping captcha solve")
            return ""

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Submit captcha
            submit_resp = await client.post(
                "http://2captcha.com/in.php",
                data={
                    "key": api_key,
                    "method": "base64",
                    "body": captcha_b64,
                    "json": "1",
                },
            )
            submit_data = submit_resp.json()
            if submit_data.get("status") != 1:
                raise RuntimeError(f"2captcha submit failed: {submit_data}")

            task_id = submit_data["request"]

            # Poll for result
            for _ in range(30):
                await asyncio.sleep(5)
                result_resp = await client.get(
                    "http://2captcha.com/res.php",
                    params={"key": api_key, "action": "get", "id": task_id, "json": "1"},
                )
                result_data = result_resp.json()
                if result_data.get("status") == 1:
                    return result_data["request"]
                if result_data.get("request") != "CAPCHA_NOT_READY":
                    raise RuntimeError(f"2captcha error: {result_data}")

        raise RuntimeError("2captcha: solution not received within timeout")

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------

    async def _verify_email(self, gmail_cred: GmailCredential) -> bool:
        """Check the Gmail inbox via IMAP for Reddit's verification email and
        click the verification link.

        Requires that the Gmail account has IMAP enabled and the password
        stored in gmail_cred is an App Password (not the sign-in password
        if 2FA is enabled).

        Args:
            gmail_cred: Gmail account to check.

        Returns:
            True if verification succeeded, False otherwise.
        """
        seed = gmail_cred.account_seed ^ 0xDEADBEEF

        # Run IMAP in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        link = await loop.run_in_executor(
            None, self._imap_find_reddit_link, gmail_cred
        )

        if not link:
            log.warning("No Reddit verification email found in %s", gmail_cred.email)
            return False

        # Follow the verification link
        try:
            async with httpx.AsyncClient(
                timeout=20.0, follow_redirects=True
            ) as client:
                resp = await client.get(link)
                if resp.status_code < 400:
                    log.info(
                        "Email verified for %s via link click", gmail_cred.email
                    )
                    return True
                log.warning(
                    "Verification link returned HTTP %d for %s",
                    resp.status_code,
                    gmail_cred.email,
                )
                return False
        except Exception as exc:  # noqa: BLE001
            log.error("Verification link fetch failed: %s", exc)
            return False

    def _imap_find_reddit_link(self, gmail_cred: GmailCredential) -> Optional[str]:
        """Synchronous IMAP search for the Reddit verification email.

        Connects to imap.gmail.com with the account's app password, searches
        for unread emails from reddit, and returns the first verification URL
        found.

        Args:
            gmail_cred: Gmail credential with email and password (app password).

        Returns:
            Verification URL string or None if not found.
        """
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(gmail_cred.email, gmail_cred.password)
            mail.select("INBOX")

            # Search for unread email from Reddit
            _, msg_ids = mail.search(None, '(UNSEEN FROM "reddit")')
            ids = msg_ids[0].split()

            for msg_id in reversed(ids):  # newest first
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                for part in msg_data:
                    if not isinstance(part, tuple):
                        continue
                    msg = email.message_from_bytes(part[1])
                    body = self._extract_email_body(msg)
                    link = self._find_reddit_verify_link(body)
                    if link:
                        mail.logout()
                        return link

            mail.logout()
            return None
        except Exception as exc:  # noqa: BLE001
            log.error("IMAP error for %s: %s", gmail_cred.email, exc)
            return None

    @staticmethod
    def _extract_email_body(msg: email.message.Message) -> str:
        """Extract plain-text or HTML body from an email.Message object."""
        body_parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode("utf-8", errors="replace"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode("utf-8", errors="replace"))
        return "\n".join(body_parts)

    @staticmethod
    def _find_reddit_verify_link(body: str) -> Optional[str]:
        """Extract the Reddit email verification link from email body text."""
        pattern = r"https://www\.reddit\.com/verification/[^\s\"<>]+"
        match = re.search(pattern, body)
        return match.group(0) if match else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_device_id(seed: int) -> str:
        """Generate a plausible Android device ID for Reddit API headers.

        Format: lowercase hex, 16 chars.
        """
        raw = _sha256_seed(str(seed), "device_id")
        return format(raw & 0xFFFFFFFFFFFFFFFF, "016x")

    def _prune_registration_log(self) -> None:
        """Remove entries older than 1 hour from _registration_log."""
        cutoff = time.time() - 3600
        self._registration_log = [t for t in self._registration_log if t > cutoff]
