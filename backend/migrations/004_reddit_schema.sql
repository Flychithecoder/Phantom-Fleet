-- Phantom Fleet migration 004
-- Adds: Reddit-specific account state, subreddit library, post/comment history,
--       shadowban queue, strategy state KV

BEGIN;

-- ---------------------------------------------------------------------------
-- Reddit state columns on accounts
-- Tracks per-account farming stage, karma, CQS, and daily action counters.
-- ---------------------------------------------------------------------------
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_farming_stage      INTEGER NOT NULL DEFAULT 1;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_cqs                INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_comment_karma      INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_link_karma         INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_account_age_days   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_comment_count      INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_unique_subreddits  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_posts_today        INTEGER NOT NULL DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_posts_reset_at     TIMESTAMPTZ;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_shadowban_status   TEXT NOT NULL DEFAULT 'clean';
    -- clean / uncertain / shadowbanned
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_shadowban_checked_at TIMESTAMPTZ;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS reddit_subscribed_subs    JSONB NOT NULL DEFAULT '[]'::jsonb;
    -- JSON array of subreddit names subscribed by this account

CREATE INDEX IF NOT EXISTS idx_accounts_reddit_stage
    ON accounts (reddit_farming_stage)
    WHERE platform = 'reddit';

CREATE INDEX IF NOT EXISTS idx_accounts_reddit_shadowban
    ON accounts (reddit_shadowban_status)
    WHERE platform = 'reddit';

-- ---------------------------------------------------------------------------
-- Subreddit library
-- Populated by SubredditDiscoveryAgent. Post scheduler reads from here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subreddit_library (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name            TEXT NOT NULL UNIQUE,
    nsfw            BOOLEAN NOT NULL DEFAULT false,
    subscribers     INTEGER NOT NULL DEFAULT 0,
    active_users    INTEGER NOT NULL DEFAULT 0,
    activity_score  FLOAT NOT NULL DEFAULT 0,
    competition     TEXT NOT NULL DEFAULT 'medium',    -- low / medium / high
    min_karma_req   INTEGER NOT NULL DEFAULT 0,
    allows_text     BOOLEAN NOT NULL DEFAULT true,
    allows_links    BOOLEAN NOT NULL DEFAULT false,
    category        TEXT NOT NULL DEFAULT 'general',   -- general / of_advice / nsfw_content / sfw_niche
    status          TEXT NOT NULL DEFAULT 'active',    -- active / banned / removed / unverified
    last_post_at    TIMESTAMPTZ,
    post_count      INTEGER NOT NULL DEFAULT 0,        -- posts made from this fleet to this subreddit
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sl_nsfw_score
    ON subreddit_library (nsfw, activity_score DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_sl_category
    ON subreddit_library (category, activity_score DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_sl_competition
    ON subreddit_library (competition, nsfw)
    WHERE status = 'active';

-- Curated seed data — pre-loaded subreddits for Stage 4 posting
-- Category key:
--   of_advice      = creator discussion subreddits (SFW, mention OF strategy freely)
--   nsfw_content   = NSFW subreddits accepting self-posts with bio CTAs
--   sfw_niche      = SFW niche subreddits for karma building
INSERT INTO subreddit_library (name, nsfw, subscribers, activity_score, competition, allows_text, allows_links, category)
VALUES
    -- OF-specific advice subreddits (SFW, career discussion)
    ('onlyfansadvice',         false, 180000,  45.0, 'medium', true, true, 'of_advice'),
    ('onlyfanstips',           false,  45000,  12.0, 'low',    true, true, 'of_advice'),
    ('OnlyFans101',            false,  90000,  25.0, 'medium', true, true, 'of_advice'),
    ('FanvueCreators',         false,  15000,   4.0, 'low',    true, true, 'of_advice'),
    ('CreatorsAdvice',         false,  30000,   8.0, 'low',    true, true, 'of_advice'),
    ('socialmediagirls',       false, 120000,  30.0, 'medium', true, true, 'of_advice'),
    -- NSFW self-post subreddits (verified allow text self-posts)
    ('gonewild',               true, 3500000, 900.0, 'high',   true, false, 'nsfw_content'),
    ('SFWNextDoor',            false, 2200000, 600.0, 'high',  true, false, 'nsfw_content'),
    ('RealGirls',              true, 2100000, 550.0, 'high',   true, false, 'nsfw_content'),
    ('amateur',                true,  900000, 250.0, 'high',   true, false, 'nsfw_content'),
    ('GoneWildStories',        true,  500000, 130.0, 'medium', true, false, 'nsfw_content'),
    ('nsfw',                   true, 4800000,1200.0, 'high',   true, false, 'nsfw_content'),
    ('Verification',           false, 300000,  80.0, 'medium', true, false, 'nsfw_content'),
    ('OnlyFansPromotion',      false, 200000,  50.0, 'medium', true, true,  'nsfw_content'),
    ('onlyfansgirls',          false, 500000, 130.0, 'high',   true, true,  'nsfw_content'),
    -- SFW niche subreddits for CQS building (low competition, high engagement)
    ('CasualConversation',     false, 900000, 220.0, 'medium', true, false, 'sfw_niche'),
    ('TrueOffMyChest',         false, 500000, 130.0, 'medium', true, false, 'sfw_niche'),
    ('Fitness',                false,1000000, 260.0, 'medium', true, true,  'sfw_niche'),
    ('self',                   false, 700000, 180.0, 'low',    true, false, 'sfw_niche')
ON CONFLICT (name) DO UPDATE SET
    updated_at = now();

-- ---------------------------------------------------------------------------
-- Reddit post history
-- Dedup + analytics for all posts made by fleet accounts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reddit_post_history (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    subreddit       TEXT NOT NULL,
    title_hash      TEXT NOT NULL,
    title           TEXT,
    post_url        TEXT,
    post_id         TEXT,
    nsfw            BOOLEAN NOT NULL DEFAULT false,
    category        TEXT NOT NULL DEFAULT 'general',  -- of_advice / nsfw_content / sfw_niche / general
    status          TEXT NOT NULL DEFAULT 'submitted',-- submitted / live / removed / shadowbanned
    score           INTEGER NOT NULL DEFAULT 0,
    comment_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, subreddit, title_hash)
);

CREATE INDEX IF NOT EXISTS idx_rph_account
    ON reddit_post_history (account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rph_subreddit
    ON reddit_post_history (subreddit, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rph_date
    ON reddit_post_history (created_at DESC);

-- ---------------------------------------------------------------------------
-- Reddit comment history
-- Tracks comments for karma building and dedup.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reddit_comment_history (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    subreddit       TEXT NOT NULL,
    post_id         TEXT NOT NULL,
    comment_text    TEXT NOT NULL,
    karma_earned    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'submitted',-- submitted / removed / shadowbanned
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rch_account
    ON reddit_comment_history (account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rch_subreddit
    ON reddit_comment_history (subreddit, created_at DESC);

-- ---------------------------------------------------------------------------
-- Reddit shadowban queue
-- Accounts flagged for shadowban check. Quarantine_until = re-check time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reddit_shadowban_queue (
    id                  TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    account_id          TEXT NOT NULL REFERENCES accounts(id) UNIQUE,
    queued_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    quarantine_until    TIMESTAMPTZ,
    last_check_result   TEXT,
    check_count         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rsq_quarantine
    ON reddit_shadowban_queue (quarantine_until)
    WHERE quarantine_until IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Reddit strategy state KV
-- Persists RedditAgentManager.state across restarts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reddit_strategy_state (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO reddit_strategy_state (key, value)
VALUES ('manager_state', '{}'::jsonb)
ON CONFLICT (key) DO NOTHING;

COMMIT;
