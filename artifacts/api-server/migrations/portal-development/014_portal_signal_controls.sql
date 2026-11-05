SET search_path TO smh_test;

-- Additive, audited queue for owner-approved Development signal controls.
-- Run only in the schema for the intended bot environment.
DO $$
DECLARE current_version INTEGER;
BEGIN
    IF current_schema() NOT IN ('smh', 'smh_test')
       AND current_schema() !~ '^test_[a-f0-9]+$' THEN
        RAISE EXCEPTION 'Run signal-controls migration only in smh or smh_test';
    END IF;
    SELECT version INTO current_version FROM schema_version LIMIT 1;
    IF current_version <> 7 THEN
        RAISE EXCEPTION 'Expected bot schema version 7; found %', current_version;
    END IF;
END $$;

BEGIN;
CREATE TABLE IF NOT EXISTS portal_signal_commands (
    id TEXT PRIMARY KEY,
    actor_staff_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'create_zone_draft','publish_zone','record_confirmation',
        'cancel_setup','publish_signal','publish_analysis'
    )),
    input_json TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    command_status TEXT NOT NULL DEFAULT 'queued' CHECK(command_status IN (
        'queued','processing','preview_ready','approved','completed',
        'failed','uncertain','stale','cancelled'
    )),
    preview_text TEXT NOT NULL DEFAULT '',
    operation_id TEXT,
    safe_result TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created TIMESTAMPTZ NOT NULL,
    updated TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS portal_signal_commands_queue
    ON portal_signal_commands(command_status,created)
    WHERE command_status IN ('queued','approved');
CREATE TABLE IF NOT EXISTS portal_signal_command_events (
    id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL REFERENCES portal_signal_commands(id) ON DELETE CASCADE,
    actor_staff_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS portal_signal_command_events_command
    ON portal_signal_command_events(command_id,created);
ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 8;
UPDATE schema_version SET version=8;
COMMIT;
