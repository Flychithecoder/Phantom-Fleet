-- Phantom Fleet migration 008
-- Adds per-account engagement scheduler settings and daily action count tracking.
-- These columns power the EngagementExecutor background loop.

BEGIN;

-- Active window + tags on accounts
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS start_hour          INTEGER NOT NULL DEFAULT 8,
    ADD COLUMN IF NOT EXISTS end_hour            INTEGER NOT NULL DEFAULT 22,
    ADD COLUMN IF NOT EXISTS tags                TEXT    NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS phone_serial        TEXT,
    ADD COLUMN IF NOT EXISTS follow_enabled      BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS follow_daily_max    INTEGER NOT NULL DEFAULT 25,
    ADD COLUMN IF NOT EXISTS follow_min_delay    INTEGER NOT NULL DEFAULT 90,
    ADD COLUMN IF NOT EXISTS follow_max_delay    INTEGER NOT NULL DEFAULT 300,
    ADD COLUMN IF NOT EXISTS like_enabled        BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS like_daily_max      INTEGER NOT NULL DEFAULT 75,
    ADD COLUMN IF NOT EXISTS like_min_delay      INTEGER NOT NULL DEFAULT 30,
    ADD COLUMN IF NOT EXISTS like_max_delay      INTEGER NOT NULL DEFAULT 90,
    ADD COLUMN IF NOT EXISTS story_enabled       BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS story_daily_max     INTEGER NOT NULL DEFAULT 150,
    ADD COLUMN IF NOT EXISTS comment_enabled     BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS comment_daily_max   INTEGER NOT NULL DEFAULT 8,
    ADD COLUMN IF NOT EXISTS dm_enabled          BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS dm_daily_max        INTEGER NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS unfollow_enabled    BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS unfollow_daily_max  INTEGER NOT NULL DEFAULT 25;

-- Denormalised phone_serial for fast scheduler queries (avoids join on every tick)
CREATE INDEX IF NOT EXISTS idx_accounts_phone_serial ON accounts (phone_serial)
    WHERE phone_serial IS NOT NULL;

-- Daily action count tracking — resets each calendar day via date = CURRENT_DATE
CREATE TABLE IF NOT EXISTS daily_action_counts (
    account_id    TEXT        NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date          DATE        NOT NULL DEFAULT CURRENT_DATE,
    action_type   TEXT        NOT NULL,   -- follow/like/story/comment/dm/unfollow
    count         INTEGER     NOT NULL DEFAULT 0,
    last_action_at TIMESTAMPTZ,
    PRIMARY KEY (account_id, date, action_type)
);

CREATE INDEX IF NOT EXISTS idx_dac_account_date
    ON daily_action_counts (account_id, date DESC);

-- Heartbeat table — companion APK pings this on startup + every 5 min
CREATE TABLE IF NOT EXISTS phone_heartbeats (
    serial          TEXT        PRIMARY KEY,
    wifi_ip         TEXT        NOT NULL,
    apk_version     TEXT,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    companion_port  INTEGER     NOT NULL DEFAULT 8090
);

COMMIT;
