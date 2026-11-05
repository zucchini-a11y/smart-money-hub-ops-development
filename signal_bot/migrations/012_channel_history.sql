-- Isolated bot channel-history capture. Additive; never copies Telegram media.
DO $$
DECLARE current_version INTEGER;
BEGIN
    IF current_schema() NOT IN ('smh', 'smh_test')
       AND current_schema() !~ '^test_[a-f0-9]+$' THEN
        RAISE EXCEPTION 'Run channel-history migration only in smh or smh_test';
    END IF;
    SELECT version INTO current_version FROM schema_version LIMIT 1;
    IF current_version NOT IN (5, 6) THEN
        RAISE EXCEPTION 'Expected bot schema version 5 or 6; found %', current_version;
    END IF;
END $$;

BEGIN;
CREATE TABLE IF NOT EXISTS channel_history (
    update_id BIGINT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    destination TEXT NOT NULL CHECK (destination IN (
        'PRO Signals', 'Market Analysis', 'Educational Group · Video tutorials'
    )),
    event_type TEXT NOT NULL CHECK (event_type IN ('posted', 'edited')),
    message_text TEXT NOT NULL DEFAULT '',
    attachment_label TEXT NOT NULL DEFAULT 'No attachment',
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS channel_history_recorded
    ON channel_history(recorded_at DESC);
ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 6;
UPDATE schema_version SET version=6;
COMMIT;
