-- Additive Development-first migration for activity reports and task effort.
-- Apply to Development schema smh only; do not apply to Production implicitly.
SET search_path TO smh_test;

BEGIN;

ALTER TABLE staff_tasks
    ADD COLUMN IF NOT EXISTS effort_points SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE staff_tasks
    DROP CONSTRAINT IF EXISTS staff_tasks_effort_points_check;
ALTER TABLE staff_tasks
    ADD CONSTRAINT staff_tasks_effort_points_check
    CHECK (effort_points BETWEEN 1 AND 5);

ALTER TABLE staff_activity_reports
    DROP CONSTRAINT IF EXISTS staff_activity_reports_review_status_check;
ALTER TABLE staff_activity_reports
    ADD CONSTRAINT staff_activity_reports_review_status_check
    CHECK (review_status IN ('submitted','reviewed','revision_requested'));

CREATE TABLE IF NOT EXISTS staff_activity_report_events (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES staff_activity_reports(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN ('submitted','reviewed','revision_requested','resubmitted')),
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    feedback TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS staff_activity_report_events_timeline
    ON staff_activity_report_events(report_id,created);

COMMIT;
