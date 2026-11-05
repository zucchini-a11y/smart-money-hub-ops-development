SET search_path TO smh_test;

-- Development-only expansion for the separated PRO registration/funding review actions.
-- Run with search_path set to smh_test. Never apply this migration to Production.
DO $$
DECLARE current_version INTEGER;
BEGIN
    IF current_schema() <> 'smh_test' AND
       current_schema() NOT LIKE 'test\_%' ESCAPE '\' THEN
        RAISE EXCEPTION 'Run PRO access stages migration only in smh_test';
    END IF;
    SELECT version INTO current_version FROM schema_version LIMIT 1;
    IF current_version <> 10 THEN
        RAISE EXCEPTION 'Expected bot schema version 10; found %', current_version;
    END IF;
END $$;

BEGIN;
CREATE TABLE portal_member_review_commands_new (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES member_requests(id) ON DELETE RESTRICT,
    actor_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK(action IN (
        'approve_registration','reject_registration','verify_funding','reject_funding',
        'approve','reject','request_evidence'
    )),
    previous_status TEXT NOT NULL,
    previous_funding_status TEXT NOT NULL,
    expected_updated TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(char_length(reason) BETWEEN 1 AND 1200),
    idempotency_key TEXT NOT NULL UNIQUE,
    command_status TEXT NOT NULL DEFAULT 'queued'
        CHECK(command_status IN ('queued','processing','completed','failed','uncertain','stale')),
    delivery_status TEXT NOT NULL DEFAULT 'not_attempted'
        CHECK(delivery_status IN ('not_attempted','sent','failed','uncertain','not_needed')),
    safe_result TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    completed_at TEXT
);

INSERT INTO portal_member_review_commands_new
SELECT * FROM portal_member_review_commands;

DROP INDEX IF EXISTS portal_member_review_commands_request;
DROP INDEX IF EXISTS portal_member_review_commands_queue;
DROP INDEX IF EXISTS portal_member_review_one_open_command;
DROP TABLE portal_member_review_commands;
ALTER TABLE portal_member_review_commands_new RENAME TO portal_member_review_commands;

CREATE INDEX portal_member_review_commands_request
    ON portal_member_review_commands(request_id,created DESC);
CREATE INDEX portal_member_review_commands_queue
    ON portal_member_review_commands(command_status,created)
    WHERE command_status='queued';
CREATE UNIQUE INDEX portal_member_review_one_open_command
    ON portal_member_review_commands(request_id)
    WHERE command_status IN ('queued','processing','uncertain');

ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 11;
UPDATE schema_version SET version=11;
COMMIT;
