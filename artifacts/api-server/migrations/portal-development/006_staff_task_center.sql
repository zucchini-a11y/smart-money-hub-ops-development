-- Additive task-center schema. Apply only to Development for isolated testing
-- until a separately approved production migration is prepared.
SET search_path TO smh_test;

BEGIN;

CREATE TABLE IF NOT EXISTS staff_teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS staff_team_members (
    team_id TEXT NOT NULL REFERENCES staff_teams(id) ON DELETE CASCADE,
    staff_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    team_role TEXT NOT NULL CHECK (team_role IN ('manager','worker')),
    created TEXT NOT NULL,
    PRIMARY KEY(team_id, staff_id)
);

CREATE TABLE IF NOT EXISTS staff_tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    instructions TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low','normal','high','urgent')),
    due_at TEXT,
    team_id TEXT REFERENCES staff_teams(id) ON DELETE RESTRICT,
    assigned_staff_id TEXT REFERENCES portal_users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN (
        'assigned','accepted','in_progress','submitted_for_review',
        'revision_requested','approved','cancelled'
    )),
    created_by TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    submission_note TEXT,
    review_feedback TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    CHECK (team_id IS NOT NULL OR assigned_staff_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS staff_tasks_assignee_status_due
    ON staff_tasks(assigned_staff_id,status,due_at);
CREATE INDEX IF NOT EXISTS staff_tasks_team_status_due
    ON staff_tasks(team_id,status,due_at);

CREATE TABLE IF NOT EXISTS staff_task_events (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES staff_tasks(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    feedback TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS staff_task_events_timeline
    ON staff_task_events(task_id,created);

CREATE TABLE IF NOT EXISTS staff_task_notifications (
    id TEXT PRIMARY KEY,
    recipient_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES staff_tasks(id) ON DELETE CASCADE,
    notification_type TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    read_at TEXT,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS staff_task_notifications_inbox
    ON staff_task_notifications(recipient_id,read_at,created);

CREATE TABLE IF NOT EXISTS staff_activity_reports (
    id TEXT PRIMARY KEY,
    staff_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE RESTRICT,
    period TEXT NOT NULL CHECK (period IN ('daily','weekly')),
    period_start TEXT NOT NULL,
    completed_work TEXT NOT NULL,
    outstanding_work TEXT NOT NULL,
    blockers TEXT NOT NULL DEFAULT '',
    plans TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (review_status IN ('submitted','reviewed')),
    reviewed_by TEXT REFERENCES portal_users(id) ON DELETE RESTRICT,
    review_note TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    reviewed_at TEXT,
    UNIQUE(staff_id,period,period_start)
);
CREATE INDEX IF NOT EXISTS staff_activity_reports_review
    ON staff_activity_reports(review_status,created);

COMMIT;
