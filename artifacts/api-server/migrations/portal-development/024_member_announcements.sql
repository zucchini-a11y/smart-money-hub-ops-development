-- Development-only staff announcement drafts; member delivery remains in-app and uses 023.
BEGIN;
SET LOCAL search_path TO smh_test;

DO $$
BEGIN
    IF current_schema() <> 'smh_test' THEN
        RAISE EXCEPTION 'Member announcement migration is Development-only (smh_test).';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS member_announcements (
    announcement_id UUID PRIMARY KEY,
    created_by_staff_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    request_id UUID NOT NULL,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
    message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 500),
    target_path TEXT NOT NULL
        CHECK (target_path IN ('/member/learning', '/member/dashboard')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_by_staff_id TEXT REFERENCES portal_users(id) ON DELETE RESTRICT,
    published_at TIMESTAMPTZ,
    recipient_count INTEGER CHECK (recipient_count IS NULL OR recipient_count >= 0),
    UNIQUE (created_by_staff_id, request_id),
    CHECK (
        (status = 'draft' AND published_by_staff_id IS NULL AND published_at IS NULL AND recipient_count IS NULL)
        OR
        (status = 'published' AND published_by_staff_id IS NOT NULL AND published_at IS NOT NULL AND recipient_count IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS member_announcements_status_created
    ON member_announcements(status, created_at DESC);
CREATE INDEX IF NOT EXISTS member_announcements_creator_created
    ON member_announcements(created_by_staff_id, created_at DESC);

COMMIT;
