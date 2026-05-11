"""
RedditHeaderExtractor — extract real Reddit device headers from physical phones.

Architecture:
    1. APKClient opens an ADB port-forward to the Companion APK server (port 8090)
    2. Calls POST /reddit/extract-headers — APK reads the Reddit app's
       SharedPreferences via root shell and returns device_id + loid
    3. Results are persisted to accounts.reddit_device_id / accounts.reddit_loid
    4. If phone extraction fails, falls back to deterministic seeded generation
       (same as the pure-API path) so the account remains usable

Phone-backed mode is strongly preferred because:
    - device_id and loid are bound to the physical phone's Reddit app install
    - Using the real values means Reddit's backend sees a consistent fingerprint
      between the mobile app sessions and API calls
    - Generated (seeded) values are statistically correct but don't have a
      matching app install trail — usable but weaker signal
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Package name for the Reddit Android app
REDDIT_PACKAGE = "com.reddit.frontpage"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_and_store_reddit_headers(
    serial:       str,
    account_id:   str,
    pool,
    package_name: str = REDDIT_PACKAGE,
) -> dict:
    """
    Extract the full Reddit session from the installed app on a physical phone
    and persist it to the accounts table.

    Phone extraction (Option 2 — preferred):
        1. ADB port-forward to Companion APK HTTP server
        2. Call POST /reddit/extract-headers on the APK
        3. APK reads SharedPreferences via root shell — returns:
               access_token, refresh_token, token_expiry,
               device_id, loid, client_id, user_agent, app_version, android_id
        4. Persist everything — the account is now fully phone-backed:
               reddit_access_token     = live token from the real app
               reddit_refresh_token    = long-lived refresh from the real app
               reddit_token_expires_at = from the real app
               reddit_device_id        = from the real app install
               reddit_loid             = from the real app install
               reddit_client_id        = "ohXpoqrZYxa1Ag" (official app client_id)
               metadata                = { reddit_user_agent, reddit_app_version, ... }
               reddit_headers_source   = 'phone'

        Every subsequent API call uses this token + official client_id + real UA.
        Reddit sees it as the official app making normal API calls.

    Seeded fallback (if phone unreachable):
        - Generates deterministic device_id + loid
        - Does NOT set access_token (account still needs password_grant)
        - Marks source = 'seeded'

    Args:
        serial:       ADB serial of the phone (e.g. "192.168.1.42:5555").
        account_id:   UUID of the Reddit account in the accounts table.
        pool:         asyncpg connection pool.
        package_name: Reddit package name (default: com.reddit.frontpage).

    Returns:
        {
            "device_id":     str,
            "loid":          str,
            "access_token":  str,   # populated only on 'phone' source
            "client_id":     str,   # "ohXpoqrZYxa1Ag" on phone, "" on seeded
            "source":        "phone" | "seeded",
            "account_id":    str,
        }
    """
    from .apk_client import APKClient, APKCallFailed

    client = APKClient(serial=serial)
    extracted: Optional[dict] = None

    # -- attempt phone extraction --
    try:
        await client.setup_forward()
        try:
            extracted = await client.reddit_extract_headers(package_name)
        finally:
            await client.teardown_forward()

        device_id    = _require(extracted, "device_id",    serial)
        loid         = _require(extracted, "loid",         serial)
        access_token = _require(extracted, "access_token", serial)
        source       = "phone"

        log.info(
            "Reddit full session extracted from phone %s for account %s "
            "(device_id=%.8s... client_id=%s)",
            serial, account_id, device_id,
            extracted.get("client_id", "?"),
        )

    except APKCallFailed as exc:
        log.warning(
            "APK extraction failed for phone %s (account %s): %s — "
            "falling back to seeded device_id/loid only",
            serial, account_id, exc,
        )
        device_id, loid, source = await _seeded_fallback(account_id, pool)
        access_token = ""

    except Exception as exc:
        log.warning(
            "Unexpected error extracting Reddit session from phone %s "
            "(account %s): %s — falling back to seeded",
            serial, account_id, exc,
        )
        device_id, loid, source = await _seeded_fallback(account_id, pool)
        access_token = ""

    # -- persist device identity --
    await _persist(pool, account_id, device_id, loid, source)

    # -- persist full token set + official client_id if phone extraction succeeded --
    if source == "phone" and extracted:
        await _persist_token_set(pool, account_id, extracted)
        await _persist_extra(pool, account_id, extracted)

    return {
        "device_id":    device_id,
        "loid":         loid,
        "access_token": access_token,
        "client_id":    extracted.get("client_id", "") if extracted else "",
        "source":       source,
        "account_id":   account_id,
    }


async def extract_headers_for_phone(
    serial: str,
    pool,
    package_name: str = REDDIT_PACKAGE,
) -> list[dict]:
    """
    Extract Reddit headers for ALL Reddit accounts assigned to a phone.

    Looks up accounts.phone_id → phones.serial match, then calls
    extract_and_store_reddit_headers for each account.

    Returns a list of result dicts (one per account).
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.id AS account_id
            FROM accounts a
            JOIN phones p ON p.id = a.phone_id
            WHERE p.serial = $1
              AND a.platform = 'reddit'
              AND a.status != 'dead'
        """, serial)

    if not rows:
        log.info("No Reddit accounts assigned to phone %s", serial)
        return []

    results = []
    for row in rows:
        account_id = row["account_id"]
        result = await extract_and_store_reddit_headers(
            serial=serial,
            account_id=account_id,
            pool=pool,
            package_name=package_name,
        )
        results.append(result)

    log.info(
        "Phone %s: extracted Reddit headers for %d accounts "
        "(%d from phone, %d seeded)",
        serial,
        len(results),
        sum(1 for r in results if r["source"] == "phone"),
        sum(1 for r in results if r["source"] == "seeded"),
    )
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require(extracted: dict, key: str, serial: str) -> str:
    """Pull a required field from extraction result, raise if missing/empty."""
    val = extracted.get(key, "").strip()
    if not val:
        raise ValueError(
            f"Companion APK on phone {serial} returned empty '{key}' — "
            "check that the Reddit app is installed and the APK has root access"
        )
    return val


async def _seeded_fallback(account_id: str, pool) -> tuple[str, str, str]:
    """
    Generate deterministic device_id + loid from account_id seed.

    Falls back to the account's existing DB values if already set,
    otherwise generates fresh ones.
    """
    from .reddit_oauth import generate_device_id, generate_loid

    # Check if the account already has values — don't overwrite a good phone value
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT reddit_device_id, reddit_loid, reddit_headers_source
            FROM accounts WHERE id = $1
        """, account_id)

    if row and row["reddit_headers_source"] == "phone":
        # Already has real phone values — keep them, don't downgrade to seeded
        existing_did  = row["reddit_device_id"]
        existing_loid = row["reddit_loid"]
        if existing_did and existing_loid:
            log.info(
                "Account %s already has phone-anchored headers, skipping seeded fallback",
                account_id,
            )
            return existing_did, existing_loid, "phone"

    device_id = generate_device_id(account_id)
    loid      = generate_loid(account_id)
    return device_id, loid, "seeded"


async def _persist(
    pool,
    account_id: str,
    device_id:  str,
    loid:       str,
    source:     str,
) -> None:
    """Write device_id, loid, and source to the accounts table."""
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE accounts
            SET reddit_device_id        = $1,
                reddit_loid             = $2,
                reddit_headers_source   = $3
            WHERE id = $4
        """, device_id, loid, source, account_id)


async def _persist_token_set(pool, account_id: str, extracted: dict) -> None:
    """
    Persist the full OAuth token set extracted from the phone.

    Writes access_token, refresh_token, token_expiry, and client_id.
    Also marks the account as 'active' if it was still in 'warming' state
    (the phone extraction proves the account is live and authenticated).
    """
    from datetime import datetime, timezone

    access_token  = extracted.get("access_token", "")
    refresh_token = extracted.get("refresh_token", "")
    client_id     = extracted.get("client_id", "")

    # token_expiry from APK is Unix seconds (float or int)
    raw_expiry = extracted.get("token_expiry", 0)
    try:
        expires_ts = datetime.fromtimestamp(float(raw_expiry), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        # If expiry is missing or invalid, default to now + 1h
        import time
        expires_ts = datetime.fromtimestamp(time.time() + 3600, tz=timezone.utc)

    if not access_token:
        return

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE accounts
            SET reddit_access_token     = $1,
                reddit_refresh_token    = CASE WHEN $2 != '' THEN $2 ELSE reddit_refresh_token END,
                reddit_token_expires_at = $3,
                reddit_client_id        = $4,
                status = CASE WHEN status = 'warming' THEN 'active' ELSE status END
            WHERE id = $5
        """, access_token, refresh_token, expires_ts, client_id, account_id)


async def _persist_extra(pool, account_id: str, extracted: dict) -> None:
    """
    Persist additional extracted fields (user_agent, app_version) into
    accounts.metadata JSONB so they're available for header building.
    """
    user_agent  = extracted.get("user_agent", "")
    app_version = extracted.get("app_version", "")
    android_id  = extracted.get("android_id", "")

    if not any([user_agent, app_version, android_id]):
        return

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE accounts
            SET metadata = metadata || jsonb_build_object(
                'reddit_user_agent',  $1::text,
                'reddit_app_version', $2::text,
                'reddit_android_id',  $3::text
            )
            WHERE id = $4
        """, user_agent, app_version, android_id, account_id)
