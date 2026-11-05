-- Development-only schema for the public website support widget.
-- This migration must only be applied to the isolated smh_test schema.
BEGIN;
SET LOCAL search_path TO smh_test;

CREATE TABLE IF NOT EXISTS website_support_visitors (
    token_hash TEXT PRIMARY KEY,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS website_support_visitors_expiry
    ON website_support_visitors(expires);

CREATE TABLE IF NOT EXISTS website_support_settings (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    support_team_id TEXT REFERENCES staff_teams(id) ON DELETE SET NULL,
    updated_by TEXT REFERENCES portal_users(id) ON DELETE SET NULL,
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO website_support_settings(singleton)
VALUES (TRUE)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS website_support_agent_settings (
    staff_id TEXT PRIMARY KEY REFERENCES portal_users(id) ON DELETE CASCADE,
    female_support_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    available BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by TEXT REFERENCES portal_users(id) ON DELETE SET NULL,
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS website_support_conversations (
    id TEXT PRIMARY KEY,
    visitor_token_hash TEXT NOT NULL REFERENCES website_support_visitors(token_hash) ON DELETE CASCADE,
    create_request_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('assistant','human')),
    status TEXT NOT NULL CHECK (status IN ('ai','queued','assigned','in_progress','closed')),
    visitor_name TEXT,
    team_id TEXT REFERENCES staff_teams(id) ON DELETE SET NULL,
    assigned_staff_id TEXT REFERENCES portal_users(id) ON DELETE SET NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_by TEXT REFERENCES portal_users(id) ON DELETE SET NULL,
    UNIQUE(visitor_token_hash, create_request_id),
    CHECK (visitor_name IS NULL OR length(visitor_name) BETWEEN 1 AND 80)
);
CREATE UNIQUE INDEX IF NOT EXISTS website_support_one_open_conversation
    ON website_support_conversations(visitor_token_hash)
    WHERE status <> 'closed';
CREATE INDEX IF NOT EXISTS website_support_conversations_queue
    ON website_support_conversations(team_id,status,last_message_at DESC);
CREATE INDEX IF NOT EXISTS website_support_conversations_assigned
    ON website_support_conversations(assigned_staff_id,status,last_message_at DESC);

CREATE TABLE IF NOT EXISTS website_support_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES website_support_conversations(id) ON DELETE CASCADE,
    sender_type TEXT NOT NULL CHECK (sender_type IN ('visitor','assistant','staff','system')),
    sender_staff_id TEXT REFERENCES portal_users(id) ON DELETE SET NULL,
    display_name TEXT NOT NULL,
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
    request_id TEXT NOT NULL,
    in_reply_to_request_id TEXT,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(conversation_id,request_id),
    CHECK ((sender_type = 'staff') = (sender_staff_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS website_support_ai_reply_once
    ON website_support_messages(conversation_id,in_reply_to_request_id)
    WHERE sender_type = 'assistant' AND in_reply_to_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS website_support_messages_timeline
    ON website_support_messages(conversation_id,created);

CREATE TABLE IF NOT EXISTS website_support_rate_limits (
    key_hash TEXT NOT NULL,
    action TEXT NOT NULL,
    bucket_start TIMESTAMPTZ NOT NULL,
    hits INTEGER NOT NULL DEFAULT 1 CHECK (hits > 0),
    PRIMARY KEY(key_hash,action,bucket_start)
);
CREATE INDEX IF NOT EXISTS website_support_rate_limits_expiry
    ON website_support_rate_limits(bucket_start);

COMMIT;
