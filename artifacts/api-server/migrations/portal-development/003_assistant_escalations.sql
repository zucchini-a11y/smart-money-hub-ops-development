SET search_path TO smh_test;

CREATE TABLE IF NOT EXISTS assistant_escalations (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    reply TEXT NOT NULL DEFAULT '',
    replied_by BIGINT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant_escalations_status
    ON assistant_escalations(status,created);
CREATE INDEX IF NOT EXISTS assistant_escalations_user
    ON assistant_escalations(user_id,created);

ALTER TABLE schema_version ALTER COLUMN version SET DEFAULT 3;
UPDATE schema_version SET version=3;
