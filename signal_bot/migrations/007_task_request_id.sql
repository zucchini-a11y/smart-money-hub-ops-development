-- Idempotency key for owner task creation; apply to Development before testing.
SET search_path TO smh;
BEGIN;
ALTER TABLE staff_tasks ADD COLUMN IF NOT EXISTS request_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS staff_tasks_creator_request_unique
    ON staff_tasks(created_by,request_id) WHERE request_id IS NOT NULL;
COMMIT;
