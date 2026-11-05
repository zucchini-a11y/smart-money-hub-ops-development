-- Report outcome notices for staff. Apply to Development before Production.
SET search_path TO smh_test;

BEGIN;

CREATE TABLE IF NOT EXISTS staff_report_notifications (
    id TEXT PRIMARY KEY,
    recipient_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
    report_id TEXT NOT NULL REFERENCES staff_activity_reports(id) ON DELETE CASCADE,
    report_event_id TEXT NOT NULL REFERENCES staff_activity_report_events(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL CHECK (outcome IN ('approved','revision_requested')),
    reviewer_feedback TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    created TEXT NOT NULL,
    read_at TEXT,
    UNIQUE(report_event_id,recipient_id)
);
CREATE INDEX IF NOT EXISTS staff_report_notifications_inbox
    ON staff_report_notifications(recipient_id,read_at,created);

COMMIT;
