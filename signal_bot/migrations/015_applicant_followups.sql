-- Persistent, gated applicant follow-up scheduling and delivery audit.
-- Run only in the intended bot schema; this migration does not enable sending.
DO $$
DECLARE current_version INTEGER;
BEGIN
    IF current_schema() NOT IN ('smh', 'smh_test')
       AND current_schema() !~ '^test_[a-f0-9]+$' THEN
        RAISE EXCEPTION 'Run applicant-followups migration only in smh or smh_test';
    END IF;
    SELECT version INTO current_version FROM schema_version LIMIT 1;
    IF current_version <> 8 THEN
        RAISE EXCEPTION 'Expected bot schema version 8; found %', current_version;
    END IF;
END $$;

BEGIN;
CREATE TABLE applicant_followup_state (
    user_id BIGINT PRIMARY KEY,
    private_status TEXT NOT NULL DEFAULT 'available'
        CHECK(private_status IN ('available','blocked','unknown')),
    first_interaction TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    consent_notice_at TEXT,
    stage TEXT NOT NULL DEFAULT 'welcome',
    destinations TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','completed','paused','opted_out','unable_to_contact')),
    pause_reason TEXT NOT NULL DEFAULT '',
    reminders_sent INTEGER NOT NULL DEFAULT 0 CHECK(reminders_sent >= 0),
    stage_reminders INTEGER NOT NULL DEFAULT 0 CHECK(stage_reminders >= 0),
    schedule_anchor TEXT NOT NULL,
    last_followup TEXT,
    next_followup TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX applicant_followup_due
    ON applicant_followup_state(status,next_followup);
CREATE TABLE applicant_followup_deliveries (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES applicant_followup_state(user_id),
    request_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    reminder_number INTEGER NOT NULL DEFAULT 0 CHECK(reminder_number >= 0),
    status TEXT NOT NULL CHECK(status IN (
        'draft','sending','sent','failed','uncertain','cancelled','skipped'
    )),
    message TEXT NOT NULL DEFAULT '',
    error_category TEXT NOT NULL DEFAULT '',
    created_by BIGINT,
    telegram_message_id BIGINT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    sent_at TEXT
);
CREATE INDEX applicant_followup_delivery_user
    ON applicant_followup_deliveries(user_id,created DESC);
CREATE INDEX applicant_followup_delivery_status
    ON applicant_followup_deliveries(status,created);
CREATE TABLE applicant_followup_events (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    delivery_id TEXT,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
CREATE INDEX applicant_followup_events_user
    ON applicant_followup_events(user_id,created DESC);
ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 9;
UPDATE schema_version SET version=9;
COMMIT;
