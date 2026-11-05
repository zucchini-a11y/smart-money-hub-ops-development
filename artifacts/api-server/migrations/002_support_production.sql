-- Add the shared Support Portal fields to the existing Signal production schema.
-- This migration is additive: it preserves current staff accounts and support history.
BEGIN;

ALTER TABLE smh.assistant_escalations
  ADD COLUMN IF NOT EXISTS source_bot TEXT NOT NULL DEFAULT 'signals',
  ADD COLUMN IF NOT EXISTS request_id TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_constraint
     WHERE conrelid = 'smh.assistant_escalations'::regclass
       AND conname = 'assistant_escalations_source_bot_check'
  ) THEN
    ALTER TABLE smh.assistant_escalations
      ADD CONSTRAINT assistant_escalations_source_bot_check
      CHECK (source_bot IN ('signals', 'coach'));
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS assistant_escalations_request_once
  ON smh.assistant_escalations (source_bot, request_id)
  WHERE request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS smh.assistant_case_messages (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES smh.assistant_escalations(id) ON DELETE CASCADE,
  sender_type TEXT NOT NULL CHECK (sender_type = 'member'),
  sender_id TEXT NOT NULL,
  text TEXT NOT NULL,
  request_id TEXT NOT NULL,
  created TEXT NOT NULL,
  UNIQUE (case_id, sender_type, request_id)
);

CREATE INDEX IF NOT EXISTS assistant_case_messages_timeline
  ON smh.assistant_case_messages (case_id, created);

COMMIT;
