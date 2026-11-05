-- Owner-managed educational video drafts and a Telegram publication outbox.
-- Apply only after setting search_path to the intended schema (smh_test first).
-- This file does not run automatically and must not be applied to Production
-- without a separate migration approval.
DO $$
DECLARE
    current_version INTEGER;
BEGIN
    IF current_schema() NOT IN ('smh', 'smh_test')
       AND current_schema() !~ '^test_[a-f0-9]+$' THEN
        RAISE EXCEPTION 'Set search_path to smh_test or smh before applying this migration.';
    END IF;
    SELECT version INTO current_version FROM schema_version LIMIT 1;
    IF current_version IS NULL OR current_version NOT IN (4, 5) THEN
        RAISE EXCEPTION 'Apply prior portal migrations before migration 011.';
    END IF;
END;
$$;

BEGIN;

CREATE TABLE IF NOT EXISTS education_video_posts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    caption TEXT NOT NULL,
    file_name TEXT NOT NULL,
    storage_name TEXT NOT NULL UNIQUE,
    byte_size BIGINT NOT NULL CHECK (byte_size BETWEEN 1 AND 50000000),
    file_sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN (
        'awaiting_upload','draft','queued','sending','published',
        'uncertain','failed','blocked'
    )),
    created_by TEXT NOT NULL,
    created_by_name TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    publish_request_id TEXT UNIQUE,
    target_chat_id BIGINT,
    target_thread_id BIGINT,
    target_topic_name TEXT NOT NULL DEFAULT 'Video tutorials',
    telegram_message_id BIGINT,
    safe_result TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    published_at TEXT
);

CREATE INDEX IF NOT EXISTS education_video_posts_queue
    ON education_video_posts(status,created)
    WHERE status='queued';
CREATE INDEX IF NOT EXISTS education_video_posts_created
    ON education_video_posts(created DESC);

ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 5;
UPDATE schema_version SET version=5;

COMMIT;
