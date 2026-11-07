-- Development-only, member-owned notification center and in-app reminder settings.
-- Do not apply to Production; the migration is restricted to schema smh_test.
BEGIN;
SET LOCAL search_path TO smh_test;

DO $$
BEGIN
    IF current_schema() <> 'smh_test' THEN
        RAISE EXCEPTION 'Member notification migration is Development-only (smh_test).';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS member_notification_preferences (
    clerk_user_id TEXT PRIMARY KEY,
    learning_reminders_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    reminder_day_of_week SMALLINT NOT NULL DEFAULT 1
        CHECK (reminder_day_of_week BETWEEN 0 AND 6),
    reminder_local_time TIME WITHOUT TIME ZONE NOT NULL DEFAULT TIME '18:00',
    timezone TEXT NOT NULL DEFAULT 'UTC'
        CHECK (length(timezone) BETWEEN 1 AND 80),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS member_notifications (
    notification_id UUID PRIMARY KEY,
    clerk_user_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('learning_reminder', 'announcement')),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
    message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 500),
    target_path TEXT NOT NULL
        CHECK (target_path IN ('/member/learning', '/member/dashboard')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    UNIQUE (clerk_user_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS member_notifications_owner_created
    ON member_notifications(clerk_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS member_notifications_owner_unread
    ON member_notifications(clerk_user_id, created_at DESC)
    WHERE read_at IS NULL;

COMMIT;
