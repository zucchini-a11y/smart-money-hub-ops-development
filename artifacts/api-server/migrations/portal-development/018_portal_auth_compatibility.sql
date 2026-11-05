-- Preserve the existing Development owner/manager/agent accounts while adding
-- the password-state field expected by the expanded portal API.
ALTER TABLE smh_test.portal_users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

-- Older portal schema variants use "admin"; the shared portal stores "owner".
ALTER TABLE smh_test.portal_users
    DROP CONSTRAINT IF EXISTS portal_users_role_check;
ALTER TABLE smh_test.portal_users
    ADD CONSTRAINT portal_users_role_check
    CHECK (role IN ('admin', 'owner', 'manager', 'agent'));
