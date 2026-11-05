-- Additive portal-to-bot trade-management queue.
-- Run only in the schema for the intended bot environment.
DO $$
DECLARE current_version INTEGER;
BEGIN
    IF current_schema() NOT IN ('smh', 'smh_test')
       AND current_schema() !~ '^test_[a-f0-9]+$' THEN
        RAISE EXCEPTION 'Run trade-management migration only in smh or smh_test';
    END IF;
    SELECT version INTO current_version FROM schema_version LIMIT 1;
    IF current_version NOT IN (6, 7) THEN
        RAISE EXCEPTION 'Expected bot schema version 6 or 7; found %', current_version;
    END IF;
END $$;

BEGIN;
CREATE TABLE IF NOT EXISTS portal_trade_commands (
    id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    actor_staff_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'entry_bundle','sl_tp','sl','tp','hit','partial','be','trail',
        'close','cancel','invalidate','custom','edit'
    )),
    input_json TEXT NOT NULL,
    expected_version INTEGER NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    command_status TEXT NOT NULL DEFAULT 'queued' CHECK(command_status IN (
        'queued','processing','preview_ready','approved','completed',
        'failed','uncertain','stale','cancelled'
    )),
    preview_text TEXT NOT NULL DEFAULT '',
    prepared_trade TEXT NOT NULL DEFAULT '',
    operation_id TEXT,
    safe_result TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created TIMESTAMPTZ NOT NULL,
    updated TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS portal_trade_commands_queue
    ON portal_trade_commands(command_status,created)
    WHERE command_status IN ('queued','approved');
CREATE INDEX IF NOT EXISTS portal_trade_commands_trade
    ON portal_trade_commands(trade_id,created DESC);
CREATE TABLE IF NOT EXISTS portal_trade_command_events (
    id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL REFERENCES portal_trade_commands(id) ON DELETE CASCADE,
    actor_staff_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS portal_trade_command_events_command
    ON portal_trade_command_events(command_id,created);
ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 7;
UPDATE schema_version SET version=7;
COMMIT;
