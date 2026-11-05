CREATE TABLE IF NOT EXISTS smh_test.member_telegram_links (
    clerk_user_id TEXT PRIMARY KEY,
    telegram_user_id TEXT NOT NULL UNIQUE,
    telegram_username TEXT,
    telegram_auth_hash TEXT NOT NULL UNIQUE,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
