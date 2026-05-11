-- Phantom Fleet migration 007
-- Phone-backed Reddit headers support.
--
-- Adds:
--   accounts.reddit_headers_source  — tracks whether device_id/loid came from
--                                     a physical phone ('phone') or were
--                                     deterministically generated ('seeded').
--                                     Empty string = not yet extracted.
--
--   accounts.metadata               — already exists as JSONB; used by
--                                     reddit_header_extractor.py to cache
--                                     reddit_user_agent, reddit_app_version,
--                                     reddit_android_id from the Companion APK.
--                                     No schema change needed for that column.
--
--   idx_accounts_phone_id           — index on accounts.phone_id for fast
--                                     lookup of "which accounts are on phone X"
--                                     used by extract_headers_for_phone().

BEGIN;

ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS reddit_headers_source TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN accounts.reddit_headers_source IS
    'Source of reddit_device_id/reddit_loid: ''phone'' (Companion APK extraction) '
    'or ''seeded'' (deterministic generation). Empty = not yet extracted.';

-- Index for phone-to-account lookups (used by header extractor + session loader)
CREATE INDEX IF NOT EXISTS idx_accounts_phone_id
    ON accounts (phone_id)
    WHERE phone_id IS NOT NULL;

-- Partial index to find accounts needing header extraction
CREATE INDEX IF NOT EXISTS idx_accounts_reddit_needs_headers
    ON accounts (id)
    WHERE platform = 'reddit'
      AND reddit_headers_source = ''
      AND status != 'dead';

COMMIT;
