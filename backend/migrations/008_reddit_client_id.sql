-- Phantom Fleet migration 008
-- Phone-backed Reddit Option 2: official app client_id storage.
--
-- When the Companion APK extracts a live session from the installed Reddit app,
-- it returns the official Reddit Android app client_id ("ohXpoqrZYxa1Ag").
-- We store that client_id on the account so token refreshes use it instead of
-- the developer app client_id — making every request indistinguishable from
-- the official Reddit app.
--
-- Empty string = not yet extracted / developer-app mode (falls back to env var).

BEGIN;

ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS reddit_client_id TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN accounts.reddit_client_id IS
    'OAuth client_id used for this account. '
    'Phone-backed: "ohXpoqrZYxa1Ag" (official Reddit Android app). '
    'Developer-app / seeded: "" (falls back to REDDIT_CLIENT_ID env var).';

-- Index to quickly find phone-backed vs developer-app accounts
CREATE INDEX IF NOT EXISTS idx_accounts_reddit_phone_backed
    ON accounts (id)
    WHERE platform = 'reddit'
      AND reddit_client_id = 'ohXpoqrZYxa1Ag'
      AND status != 'dead';

COMMIT;
