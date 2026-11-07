-- Candidate additive Production migration for the public website support widget.
-- Review against a schema-only copy of the live smh schema before applying.
-- This file creates new widget tables only. It does not alter existing bot-support
-- tables, portal users, staff teams, or support history.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $website_support_preflight$
DECLARE
  missing_columns TEXT;
BEGIN
  IF to_regnamespace('smh') IS NULL THEN
    RAISE EXCEPTION 'Required Production schema smh does not exist; no changes applied.';
  END IF;

  IF to_regclass('smh.portal_users') IS NULL
     OR to_regclass('smh.staff_teams') IS NULL
     OR to_regclass('smh.staff_team_members') IS NULL
     OR to_regclass('smh.portal_audit') IS NULL THEN
    RAISE EXCEPTION
      'Required existing portal tables are missing from smh; inspect Production schema before applying.';
  END IF;

  SELECT string_agg(format('%I.%I', required.table_name, required.column_name), ', ')
    INTO missing_columns
    FROM (VALUES
      ('portal_users', 'id'),
      ('portal_users', 'display_name'),
      ('portal_users', 'role'),
      ('portal_users', 'active'),
      ('staff_teams', 'id'),
      ('staff_teams', 'name'),
      ('staff_team_members', 'team_id'),
      ('staff_team_members', 'staff_id'),
      ('staff_team_members', 'team_role'),
      ('portal_audit', 'id'),
      ('portal_audit', 'actor_id'),
      ('portal_audit', 'action'),
      ('portal_audit', 'entity_id'),
      ('portal_audit', 'created'),
      ('portal_audit', 'detail')
    ) AS required(table_name, column_name)
   WHERE NOT EXISTS (
     SELECT 1
       FROM information_schema.columns existing
      WHERE existing.table_schema = 'smh'
        AND existing.table_name = required.table_name
        AND existing.column_name = required.column_name
   );

  IF missing_columns IS NOT NULL THEN
    RAISE EXCEPTION
      'Required columns are missing from existing smh portal tables: %. No changes applied.',
      missing_columns;
  END IF;

  IF EXISTS (
    SELECT 1
      FROM pg_class relation
      JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
     WHERE namespace.nspname = 'smh'
       AND relation.relkind IN ('r', 'p')
       AND relation.relname IN (
         'website_support_visitors',
         'website_support_settings',
         'website_support_agent_settings',
         'website_support_conversations',
         'website_support_messages',
         'website_support_rate_limits'
       )
  ) THEN
    RAISE EXCEPTION
      'One or more website-support tables already exist in smh. Inspect them and use a reviewed reconciliation migration; no changes applied.';
  END IF;
END
$website_support_preflight$;

CREATE TABLE smh.website_support_visitors (
  token_hash TEXT PRIMARY KEY,
  created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires TIMESTAMPTZ NOT NULL,
  last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX website_support_visitors_expiry
  ON smh.website_support_visitors(expires);

CREATE TABLE smh.website_support_settings (
  singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
  support_team_id TEXT REFERENCES smh.staff_teams(id) ON DELETE SET NULL,
  updated_by TEXT REFERENCES smh.portal_users(id) ON DELETE SET NULL,
  updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO smh.website_support_settings(singleton)
VALUES (TRUE);

CREATE TABLE smh.website_support_agent_settings (
  staff_id TEXT PRIMARY KEY REFERENCES smh.portal_users(id) ON DELETE CASCADE,
  female_support_eligible BOOLEAN NOT NULL DEFAULT FALSE,
  available BOOLEAN NOT NULL DEFAULT FALSE,
  updated_by TEXT REFERENCES smh.portal_users(id) ON DELETE SET NULL,
  updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE smh.website_support_conversations (
  id TEXT PRIMARY KEY,
  visitor_token_hash TEXT NOT NULL
    REFERENCES smh.website_support_visitors(token_hash) ON DELETE RESTRICT,
  create_request_id TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('assistant', 'human')),
  status TEXT NOT NULL CHECK (status IN ('ai', 'queued', 'assigned', 'in_progress', 'closed')),
  visitor_name TEXT,
  team_id TEXT REFERENCES smh.staff_teams(id) ON DELETE SET NULL,
  assigned_staff_id TEXT REFERENCES smh.portal_users(id) ON DELETE SET NULL,
  created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_by TEXT REFERENCES smh.portal_users(id) ON DELETE SET NULL,
  UNIQUE(visitor_token_hash, create_request_id),
  CHECK (visitor_name IS NULL OR length(visitor_name) BETWEEN 1 AND 80)
);
CREATE UNIQUE INDEX website_support_one_open_conversation
  ON smh.website_support_conversations(visitor_token_hash)
  WHERE status <> 'closed';
CREATE INDEX website_support_conversations_queue
  ON smh.website_support_conversations(team_id, status, last_message_at DESC);
CREATE INDEX website_support_conversations_assigned
  ON smh.website_support_conversations(assigned_staff_id, status, last_message_at DESC);

CREATE TABLE smh.website_support_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL
    REFERENCES smh.website_support_conversations(id) ON DELETE CASCADE,
  sender_type TEXT NOT NULL CHECK (sender_type IN ('visitor', 'assistant', 'staff', 'system')),
  sender_staff_id TEXT REFERENCES smh.portal_users(id) ON DELETE SET NULL,
  display_name TEXT NOT NULL,
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  request_id TEXT NOT NULL,
  in_reply_to_request_id TEXT,
  created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(conversation_id, request_id),
  CHECK ((sender_type = 'staff') = (sender_staff_id IS NOT NULL))
);
CREATE UNIQUE INDEX website_support_ai_reply_once
  ON smh.website_support_messages(conversation_id, in_reply_to_request_id)
  WHERE sender_type = 'assistant' AND in_reply_to_request_id IS NOT NULL;
CREATE INDEX website_support_messages_timeline
  ON smh.website_support_messages(conversation_id, created);

CREATE TABLE smh.website_support_rate_limits (
  key_hash TEXT NOT NULL,
  action TEXT NOT NULL,
  bucket_start TIMESTAMPTZ NOT NULL,
  hits INTEGER NOT NULL DEFAULT 1 CHECK (hits > 0),
  PRIMARY KEY(key_hash, action, bucket_start)
);
CREATE INDEX website_support_rate_limits_expiry
  ON smh.website_support_rate_limits(bucket_start);

COMMIT;
