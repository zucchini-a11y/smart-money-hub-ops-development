-- Production migration for the private member-course video library.
-- Apply only through the approved Hostinger release process after a backup.
BEGIN;
SET LOCAL search_path TO smh;

DO $$
BEGIN
    IF current_schema() <> 'smh' THEN
        RAISE EXCEPTION 'Member course videos Production migration must run in schema smh.';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS member_course_videos (
    id UUID PRIMARY KEY,
    title VARCHAR(140) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    file_name VARCHAR(180) NOT NULL,
    storage_name VARCHAR(64) NOT NULL UNIQUE,
    byte_size BIGINT NOT NULL CHECK (byte_size BETWEEN 1 AND 262144000),
    file_sha256 CHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(24) NOT NULL CHECK (status IN ('awaiting_upload', 'draft', 'published')),
    created_by TEXT NOT NULL,
    created_by_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS member_course_videos_published
    ON member_course_videos (created_at DESC, id)
    WHERE status = 'published';

COMMIT;
