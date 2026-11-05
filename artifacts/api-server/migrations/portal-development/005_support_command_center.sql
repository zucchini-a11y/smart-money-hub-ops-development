-- Forward-only additive migration for the support command center.
-- Run once per support schema (smh for production, smh_test for isolated testing).
-- Existing cases remain intact; historical cases are assigned a safe workflow state.
SET search_path TO smh_test;

BEGIN;

ALTER TABLE assistant_escalations
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'unclassified'
        CHECK (category IN ('unclassified','general','pro_access','registration','classes','technical','other')),
    ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low','normal','high','urgent')),
    ADD COLUMN IF NOT EXISTS workflow_status TEXT NOT NULL DEFAULT 'new'
        CHECK (workflow_status IN ('new','assigned','in_progress','waiting_for_member','resolved','closed')),
    ADD COLUMN IF NOT EXISTS assigned_staff_id TEXT;

CREATE TABLE IF NOT EXISTS portal_schema_version (
    version INTEGER NOT NULL
);
INSERT INTO portal_schema_version(version)
SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM portal_schema_version);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM portal_schema_version WHERE version = 0) THEN
        UPDATE assistant_escalations
           SET workflow_status = CASE
               WHEN status = 'closed' THEN 'closed'
               WHEN status = 'replied' THEN 'waiting_for_member'
               ELSE 'new'
           END;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS assistant_escalations_assigned_queue
    ON assistant_escalations(assigned_staff_id, workflow_status, updated);

CREATE TABLE IF NOT EXISTS assistant_case_notes (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES assistant_escalations(id) ON DELETE CASCADE,
    staff_id TEXT NOT NULL,
    responder_name TEXT NOT NULL,
    note TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant_case_notes_timeline
    ON assistant_case_notes(case_id, created);

CREATE TABLE IF NOT EXISTS assistant_case_events (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES assistant_escalations(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('assigned','unassigned','status_changed','category_changed','priority_changed')),
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant_case_events_timeline
    ON assistant_case_events(case_id, created);

CREATE TABLE IF NOT EXISTS portal_manager_roles (
    staff_id TEXT PRIMARY KEY REFERENCES portal_users(id) ON DELETE CASCADE,
    created TEXT NOT NULL
);

UPDATE portal_schema_version SET version = 1 WHERE version = 0;

COMMIT;
