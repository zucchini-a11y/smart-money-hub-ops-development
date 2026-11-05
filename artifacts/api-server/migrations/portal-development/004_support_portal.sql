SET search_path TO smh_test;

ALTER TABLE assistant_escalations
    ADD COLUMN IF NOT EXISTS replied_by_name TEXT;
ALTER TABLE assistant_escalations
    ADD COLUMN IF NOT EXISTS replied_by_staff_id TEXT;

CREATE TABLE IF NOT EXISTS portal_users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','agent')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    last_login TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS portal_users_email_lower
    ON portal_users (lower(email));

CREATE TABLE IF NOT EXISTS portal_sessions (
    token_hash TEXT PRIMARY KEY,
    staff_id TEXT NOT NULL REFERENCES portal_users(id),
    created TEXT NOT NULL,
    expires TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS portal_sessions_expiry
    ON portal_sessions(expires);

CREATE TABLE IF NOT EXISTS assistant_support_replies (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES assistant_escalations(id),
    staff_id TEXT NOT NULL REFERENCES portal_users(id),
    responder_name TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','sending','sent','uncertain','failed')),
    request_id TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    UNIQUE(case_id, request_id)
);
CREATE INDEX IF NOT EXISTS assistant_support_replies_queue
    ON assistant_support_replies(status,created);

CREATE TABLE IF NOT EXISTS portal_audit (
    id TEXT PRIMARY KEY,
    actor_id TEXT,
    action TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    created TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 4;
UPDATE schema_version SET version=4;
