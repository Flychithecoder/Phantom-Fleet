-- Phantom Fleet migration 005
-- Adds session credential columns to accounts table.
-- These are populated by the mass-login / session-import flow and read
-- by ThreadsClient, ProfileBuilder, Scraper, Pods, Warmup, and SchedulerExecutor.
--
-- Column naming convention matches the cookie names used by Instagram:
--   sessionid   — session token cookie
--   csrftoken   — CSRF token cookie
--   mid         — machine ID cookie
--   user_id     — Instagram numeric user ID (their platform UID)

BEGIN;

ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS sessionid   TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS csrftoken   TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS mid         TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS user_id     TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts (user_id)
    WHERE user_id != '';

COMMENT ON COLUMN accounts.sessionid  IS 'Instagram sessionid cookie — refreshed after each mass-login';
COMMENT ON COLUMN accounts.csrftoken  IS 'Instagram csrftoken cookie';
COMMENT ON COLUMN accounts.mid        IS 'Instagram machine-id cookie (device binding)';
COMMENT ON COLUMN accounts.user_id    IS 'Instagram numeric user ID (their platform UID)';

COMMIT;
