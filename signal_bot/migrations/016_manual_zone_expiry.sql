DO $$
DECLARE current_version INTEGER;
BEGIN
    IF current_schema() NOT IN ('smh', 'smh_test')
       AND current_schema() !~ '^test_[a-f0-9]+$' THEN
        RAISE EXCEPTION 'Run manual-zone-expiry migration only in smh or smh_test';
    END IF;
    SELECT version INTO current_version FROM schema_version LIMIT 1;
    IF current_version <> 9 THEN
        RAISE EXCEPTION 'Expected bot schema version 9; found %', current_version;
    END IF;
END $$;

BEGIN;
ALTER TABLE portal_signal_commands
    DROP CONSTRAINT IF EXISTS portal_signal_commands_action_check;
ALTER TABLE portal_signal_commands
    ADD CONSTRAINT portal_signal_commands_action_check CHECK(action IN (
        'create_zone_draft','publish_zone','record_confirmation',
        'cancel_setup','expire_setup','publish_signal','publish_analysis'
    ));
ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 10;
UPDATE schema_version SET version=10;
COMMIT;
