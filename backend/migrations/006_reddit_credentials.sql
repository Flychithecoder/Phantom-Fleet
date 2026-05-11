-- Phantom Fleet migration 006
-- Reddit OAuth credential columns on the accounts table.
--
-- These columns are populated by two paths:
--   1. gmail_reddit_pipeline.py /provision endpoint (bulk pipeline import)
--   2. POST /api/reddit/accounts/{id}/refresh-token (manual token refresh)
--
-- Design note: tokens are stored as plain-text columns (not inside
-- credentials_ref JSONB) so background tasks can read them in a single
-- parameterised SELECT without JSONB parsing, matching the IG session
-- column pattern established in migration 005.

BEGIN;

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_access_token     TEXT NOT NULL DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_refresh_token    TEXT NOT NULL DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_token_expires_at TIMESTAMPTZ;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_device_id        TEXT NOT NULL DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_loid             TEXT NOT NULL DEFAULT '';

-- Fast lookup: find active Reddit accounts whose token is still valid
CREATE INDEX IF NOT EXISTS idx_accounts_reddit_token
    ON accounts (reddit_token_expires_at)
    WHERE platform = 'reddit' AND reddit_access_token != '';

COMMENT ON COLUMN accounts.reddit_access_token     IS 'Reddit OAuth bearer token — expires after 1h';
COMMENT ON COLUMN accounts.reddit_refresh_token    IS 'Reddit OAuth refresh token — long-lived';
COMMENT ON COLUMN accounts.reddit_token_expires_at IS 'When reddit_access_token expires';
COMMENT ON COLUMN accounts.reddit_device_id        IS 'Stable per-account x-reddit-device-id (32-char hex)';
COMMENT ON COLUMN accounts.reddit_loid             IS 'Stable per-account x-reddit-loid (~22-char base64url)';

COMMIT;
