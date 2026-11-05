SET search_path TO smh_test;

-- Additive outbox and audit trail for owner-initiated PRO review decisions.
-- Apply only to the explicitly selected support schema. Do not apply to Production
-- until a separate Production migration is approved.
BEGIN;

CREATE TABLE IF NOT EXISTS portal_member_review_commands (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES member_requests(id) ON DELETE RESTRICT,
    actor_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (action IN ('approve','reject','request_evidence')),
    previous_status TEXT NOT NULL,
    previous_funding_status TEXT NOT NULL,
    expected_updated TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 1200),
    idempotency_key TEXT NOT NULL UNIQUE,
    command_status TEXT NOT NULL DEFAULT 'queued'
        CHECK (command_status IN ('queued','processing','completed','failed','uncertain','stale')),
    delivery_status TEXT NOT NULL DEFAULT 'not_attempted'
        CHECK (delivery_status IN ('not_attempted','sent','failed','uncertain','not_needed')),
    safe_result TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS portal_member_review_commands_request
    ON portal_member_review_commands(request_id,created DESC);

CREATE INDEX IF NOT EXISTS portal_member_review_commands_queue
    ON portal_member_review_commands(command_status,created)
    WHERE command_status='queued';

CREATE UNIQUE INDEX IF NOT EXISTS portal_member_review_one_open_command
    ON portal_member_review_commands(request_id)
    WHERE command_status IN ('queued','processing','uncertain');

COMMIT;
