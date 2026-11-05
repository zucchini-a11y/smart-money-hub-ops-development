-- Development/test only. Never apply this file to a production database.
CREATE SCHEMA IF NOT EXISTS smh_test;

CREATE TABLE IF NOT EXISTS smh_test.portal_users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner','manager','agent')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  last_login TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS portal_users_email_lower
  ON smh_test.portal_users (lower(email));

CREATE TABLE IF NOT EXISTS smh_test.portal_sessions (
  token_hash TEXT PRIMARY KEY,
  staff_id TEXT NOT NULL REFERENCES smh_test.portal_users(id) ON DELETE CASCADE,
  created TEXT NOT NULL,
  expires TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS smh_test.assistant_escalations (
  id TEXT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  question TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','reply_sending','reply_uncertain','replied','closed')),
  reply TEXT,
  replied_by_name TEXT,
  replied_by_staff_id TEXT,
  source_bot TEXT NOT NULL DEFAULT 'signals'
    CHECK (source_bot IN ('signals','coach')),
  request_id TEXT,
  category TEXT NOT NULL DEFAULT 'general',
  priority TEXT NOT NULL DEFAULT 'normal'
    CHECK (priority IN ('low','normal','high','urgent')),
  workflow_status TEXT NOT NULL DEFAULT 'new'
    CHECK (workflow_status IN ('new','assigned','in_progress','waiting_for_member','resolved','closed')),
  assigned_staff_id TEXT REFERENCES smh_test.portal_users(id) ON DELETE SET NULL,
  created TEXT NOT NULL,
  updated TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS assistant_escalations_request_once
  ON smh_test.assistant_escalations (source_bot, request_id)
  WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS assistant_escalations_queue
  ON smh_test.assistant_escalations (workflow_status, updated DESC);
CREATE INDEX IF NOT EXISTS assistant_escalations_member
  ON smh_test.assistant_escalations (source_bot, user_id, created DESC);

CREATE TABLE IF NOT EXISTS smh_test.assistant_support_replies (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES smh_test.assistant_escalations(id) ON DELETE CASCADE,
  staff_id TEXT NOT NULL REFERENCES smh_test.portal_users(id),
  responder_name TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','sending','sent','uncertain','failed')),
  request_id TEXT NOT NULL,
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  UNIQUE (case_id, request_id)
);
CREATE INDEX IF NOT EXISTS assistant_support_replies_queue
  ON smh_test.assistant_support_replies (status, created);

CREATE TABLE IF NOT EXISTS smh_test.assistant_case_messages (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES smh_test.assistant_escalations(id) ON DELETE CASCADE,
  sender_type TEXT NOT NULL CHECK (sender_type = 'member'),
  sender_id TEXT NOT NULL,
  text TEXT NOT NULL,
  request_id TEXT NOT NULL,
  created TEXT NOT NULL,
  UNIQUE (case_id, sender_type, request_id)
);
CREATE INDEX IF NOT EXISTS assistant_case_messages_timeline
  ON smh_test.assistant_case_messages (case_id, created);

CREATE TABLE IF NOT EXISTS smh_test.assistant_case_notes (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES smh_test.assistant_escalations(id) ON DELETE CASCADE,
  staff_id TEXT NOT NULL REFERENCES smh_test.portal_users(id),
  responder_name TEXT NOT NULL,
  note TEXT NOT NULL,
  created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS smh_test.assistant_case_events (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES smh_test.assistant_escalations(id) ON DELETE CASCADE,
  actor_id TEXT NOT NULL,
  event_type TEXT NOT NULL
    CHECK (event_type IN ('assigned','unassigned','status_changed')),
  old_value TEXT NOT NULL DEFAULT '',
  new_value TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS smh_test.portal_audit (
  id TEXT PRIMARY KEY,
  actor_id TEXT,
  action TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  created TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
