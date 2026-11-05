"""SQLite transactions, persisted UI state, outbox, audit, and safe backups."""
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def uid():
    return secrets.token_hex(6)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Database:
    def __init__(self, directory, url=None, schema="smh"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("images", "backups", "logs"):
            (self.directory / name).mkdir(exist_ok=True, mode=0o700)
        self.path = self.directory / "hub.sqlite3"
        self.postgres = bool(url)
        self.schema = schema
        if url:
            from .postgres import Connection
            self.conn = Connection(url, schema)
            row = self.conn.execute("SELECT version FROM schema_version").fetchone()
            # Managed schema-only deploys copy DDL, not migration metadata rows.
            # The schema default is a version marker carried in the DDL itself.
            marker = self.conn.execute(
                "SELECT column_default FROM information_schema.columns WHERE table_schema=? "
                "AND table_name='schema_version' AND column_name='version'", (schema,)).fetchone()
            # Versions 6–10 add isolated portal and bot features; version 11
            # expands the review outbox for separate PRO registration/funding decisions.
            if (not marker or str(marker[0]) not in ("5", "6", "7", "8", "9", "10", "11") or
                    (row and str(row[0]) != str(marker[0]))):
                raise RuntimeError("Apply migrations before startup.")
            return
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.migrate()
        self.conn.executescript("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, content BLOB NOT NULL);"
                               "CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, result TEXT NOT NULL);")

    def migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > 11:
            raise RuntimeError("Database schema is newer than this application.")
        if version == 0:
            self.conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE trades (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL, state TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX trades_state ON trades(state,created);
                CREATE TABLE operations (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, message_id INTEGER, created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE INDEX operations_status ON operations(status,created);
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY, trade_id TEXT REFERENCES trades(id),
                    operation_id TEXT UNIQUE REFERENCES operations(id), actor INTEGER NOT NULL,
                    text TEXT NOT NULL, message_id INTEGER, created TEXT NOT NULL
                );
                CREATE INDEX events_trade ON events(trade_id,id);
                CREATE TABLE drafts (owner INTEGER PRIMARY KEY, data TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE buttons (
                    id TEXT PRIMARY KEY, owner INTEGER NOT NULL, action TEXT NOT NULL,
                    data TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE applications (
                    user_id INTEGER PRIMARY KEY, answers TEXT NOT NULL,
                    status TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE access (
                    user_id INTEGER NOT NULL REFERENCES applications(user_id),
                    channel INTEGER NOT NULL, status TEXT NOT NULL, updated TEXT NOT NULL,
                    PRIMARY KEY(user_id,channel)
                );
                CREATE TABLE errors (
                    id INTEGER PRIMARY KEY, category TEXT NOT NULL, detail TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                PRAGMA user_version=1;
                COMMIT;
            """)
            version = 1
        if version == 1:
            self.conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE member_requests (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    destination TEXT NOT NULL,
                    answers TEXT NOT NULL,
                    status TEXT NOT NULL,
                    registration_status TEXT NOT NULL DEFAULT 'not_required',
                    funding_status TEXT NOT NULL DEFAULT 'not_required',
                    evidence_file_id TEXT,
                    evidence_kind TEXT,
                    evidence_submitted_at TEXT,
                    followup_text TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'new',
                    admin_decision_by INTEGER,
                    admin_decision_at TEXT,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL
                );
                CREATE INDEX member_requests_user_destination
                    ON member_requests(user_id,destination,updated);
                CREATE INDEX member_requests_status ON member_requests(destination,status,updated);
                CREATE TABLE member_request_events (
                    id INTEGER PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES member_requests(id),
                    actor INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created TEXT NOT NULL
                );
                CREATE INDEX member_request_events_request
                    ON member_request_events(request_id,id);
                PRAGMA user_version=2;
                COMMIT;
            """)
            version = 2
        if version == 2:
            self.conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE assistant_escalations (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reply TEXT NOT NULL DEFAULT '',
                    replied_by INTEGER,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL
                );
                CREATE INDEX assistant_escalations_status
                    ON assistant_escalations(status,created);
                CREATE INDEX assistant_escalations_user
                    ON assistant_escalations(user_id,created);
                PRAGMA user_version=3;
                COMMIT;
            """)
            version = 3
        if version == 3:
            self.conn.executescript("""
                BEGIN IMMEDIATE;
                ALTER TABLE assistant_escalations ADD COLUMN replied_by_name TEXT;
                ALTER TABLE assistant_escalations ADD COLUMN replied_by_staff_id TEXT;
                CREATE TABLE portal_users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','agent')),
                    active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    last_login TEXT
                );
                CREATE TABLE portal_sessions (
                    token_hash TEXT PRIMARY KEY,
                    staff_id TEXT NOT NULL REFERENCES portal_users(id),
                    created TEXT NOT NULL,
                    expires TEXT NOT NULL
                );
                CREATE INDEX portal_sessions_expiry ON portal_sessions(expires);
                CREATE TABLE assistant_support_replies (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES assistant_escalations(id),
                    staff_id TEXT NOT NULL REFERENCES portal_users(id),
                    responder_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','sending','sent','uncertain','failed')),
                    request_id TEXT NOT NULL,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    UNIQUE(case_id, request_id)
                );
                CREATE INDEX assistant_support_replies_queue
                    ON assistant_support_replies(status,created);
                CREATE TABLE portal_audit (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT,
                    action TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    created TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                );
                PRAGMA user_version=4;
                COMMIT;
            """)
            version = 4
        if version == 4:
            self.conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS education_video_posts (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    storage_name TEXT NOT NULL UNIQUE,
                    byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 50000000),
                    file_sha256 TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN (
                        'awaiting_upload','draft','queued','sending','published',
                        'uncertain','failed','blocked'
                    )),
                    created_by TEXT NOT NULL,
                    created_by_name TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    publish_request_id TEXT UNIQUE,
                    target_chat_id INTEGER,
                    target_thread_id INTEGER,
                    target_topic_name TEXT NOT NULL DEFAULT 'Video tutorials',
                    telegram_message_id INTEGER,
                    safe_result TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    published_at TEXT
                );
                CREATE INDEX IF NOT EXISTS education_video_posts_queue
                    ON education_video_posts(status,created)
                    WHERE status='queued';
                CREATE INDEX IF NOT EXISTS education_video_posts_created
                    ON education_video_posts(created DESC);
                PRAGMA user_version=5;
                COMMIT;
            """)
            version = 5
        if version == 5:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS portal_member_review_commands (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES member_requests(id) ON DELETE RESTRICT,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('approve','reject','request_evidence')),
                previous_status TEXT NOT NULL,
                previous_funding_status TEXT NOT NULL,
                expected_updated TEXT NOT NULL,
                reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1200),
                idempotency_key TEXT NOT NULL UNIQUE,
                command_status TEXT NOT NULL DEFAULT 'queued'
                    CHECK(command_status IN ('queued','processing','completed','failed','uncertain','stale')),
                delivery_status TEXT NOT NULL DEFAULT 'not_attempted'
                    CHECK(delivery_status IN ('not_attempted','sent','failed','uncertain','not_needed')),
                safe_result TEXT NOT NULL DEFAULT '',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL,
                updated TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS portal_member_review_commands_request
                ON portal_member_review_commands(request_id,created DESC);
            CREATE INDEX IF NOT EXISTS portal_member_review_commands_queue
                ON portal_member_review_commands(command_status,created)
                WHERE command_status='queued';
            CREATE UNIQUE INDEX IF NOT EXISTS portal_member_review_one_open_command
                ON portal_member_review_commands(request_id)
                WHERE command_status IN ('queued','processing','uncertain');
            CREATE TABLE IF NOT EXISTS channel_history (
                update_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                destination TEXT NOT NULL CHECK(destination IN (
                    'PRO Signals','Market Analysis','Educational Group · Video tutorials'
                )),
                event_type TEXT NOT NULL CHECK(event_type IN ('posted','edited')),
                message_text TEXT NOT NULL DEFAULT '',
                attachment_label TEXT NOT NULL DEFAULT 'No attachment',
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS channel_history_recorded
                ON channel_history(recorded_at DESC);
            PRAGMA user_version=6;
            """)
            version = 6
        if version == 6:
            self.conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS portal_trade_commands (
                    id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    actor_staff_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN (
                        'entry_bundle','sl_tp','sl','tp','hit','partial','be','trail',
                        'close','cancel','invalidate','custom','edit'
                    )),
                    input_json TEXT NOT NULL,
                    expected_version INTEGER NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    command_status TEXT NOT NULL DEFAULT 'queued' CHECK(command_status IN (
                        'queued','processing','preview_ready','approved','completed',
                        'failed','uncertain','stale','cancelled'
                    )),
                    preview_text TEXT NOT NULL DEFAULT '',
                    prepared_trade TEXT NOT NULL DEFAULT '',
                    operation_id TEXT,
                    safe_result TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS portal_trade_commands_queue
                    ON portal_trade_commands(command_status,created)
                    WHERE command_status IN ('queued','approved');
                CREATE INDEX IF NOT EXISTS portal_trade_commands_trade
                    ON portal_trade_commands(trade_id,created DESC);
                CREATE TABLE IF NOT EXISTS portal_trade_command_events (
                    id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL REFERENCES portal_trade_commands(id) ON DELETE CASCADE,
                    actor_staff_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS portal_trade_command_events_command
                    ON portal_trade_command_events(command_id,created);
                PRAGMA user_version=7;
                COMMIT;
            """)
            version = 7
        if version == 7:
            # Some pre-release v7 databases already contain these columns.
            # SQLite has no portable ADD COLUMN IF NOT EXISTS, so inspect the
            # table before building the additive migration.
            escalation_columns = {
                row["name"] for row in self.conn.execute(
                    "PRAGMA table_info(assistant_escalations)").fetchall()
            }
            additions = []
            if "category" not in escalation_columns:
                additions.append(
                    "ALTER TABLE assistant_escalations ADD COLUMN category TEXT NOT NULL "
                    "DEFAULT 'unclassified' CHECK(category IN "
                    "('unclassified','general','pro_access','registration','classes','technical','other'));"
                )
            if "priority" not in escalation_columns:
                additions.append(
                    "ALTER TABLE assistant_escalations ADD COLUMN priority TEXT NOT NULL "
                    "DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent'));"
                )
            if "workflow_status" not in escalation_columns:
                additions.append(
                    "ALTER TABLE assistant_escalations ADD COLUMN workflow_status TEXT NOT NULL "
                    "DEFAULT 'new' CHECK(workflow_status IN "
                    "('new','assigned','in_progress','waiting_for_member','resolved','closed'));"
                )
            if "assigned_staff_id" not in escalation_columns:
                additions.append(
                    "ALTER TABLE assistant_escalations ADD COLUMN assigned_staff_id TEXT;"
                )
            self.conn.executescript("BEGIN IMMEDIATE;\n" + "\n".join(additions) + """
                UPDATE assistant_escalations
                   SET workflow_status=CASE
                       WHEN status='closed' THEN 'closed'
                       WHEN status='replied' THEN 'waiting_for_member'
                       ELSE 'new'
                   END;
                CREATE INDEX IF NOT EXISTS assistant_escalations_assigned_queue
                    ON assistant_escalations(assigned_staff_id,workflow_status,updated);
                CREATE TABLE IF NOT EXISTS portal_signal_commands (
                    id TEXT PRIMARY KEY,
                    actor_staff_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN (
                        'create_zone_draft','publish_zone','record_confirmation',
                        'cancel_setup','publish_signal','publish_analysis'
                    )),
                    input_json TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    command_status TEXT NOT NULL DEFAULT 'queued' CHECK(command_status IN (
                        'queued','processing','preview_ready','approved','completed',
                        'failed','uncertain','stale','cancelled'
                    )),
                    preview_text TEXT NOT NULL DEFAULT '',
                    operation_id TEXT,
                    safe_result TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS portal_signal_commands_queue
                    ON portal_signal_commands(command_status,created)
                    WHERE command_status IN ('queued','approved');
                CREATE TABLE IF NOT EXISTS portal_signal_command_events (
                    id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL REFERENCES portal_signal_commands(id) ON DELETE CASCADE,
                    actor_staff_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS portal_signal_command_events_command
                    ON portal_signal_command_events(command_id,created);
                PRAGMA user_version=8;
                COMMIT;
            """)
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 8:
            self.conn.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS applicant_followup_state (
                    user_id INTEGER PRIMARY KEY,
                    private_status TEXT NOT NULL DEFAULT 'available'
                        CHECK(private_status IN ('available','blocked','unknown')),
                    first_interaction TEXT NOT NULL,
                    last_activity TEXT NOT NULL,
                    consent_notice_at TEXT,
                    stage TEXT NOT NULL DEFAULT 'welcome',
                    destinations TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','completed','paused','opted_out','unable_to_contact')),
                    pause_reason TEXT NOT NULL DEFAULT '',
                    reminders_sent INTEGER NOT NULL DEFAULT 0 CHECK(reminders_sent >= 0),
                    stage_reminders INTEGER NOT NULL DEFAULT 0 CHECK(stage_reminders >= 0),
                    schedule_anchor TEXT NOT NULL,
                    last_followup TEXT,
                    next_followup TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS applicant_followup_due
                    ON applicant_followup_state(status,next_followup);
                CREATE TABLE IF NOT EXISTS applicant_followup_deliveries (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES applicant_followup_state(user_id),
                    request_key TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    reminder_number INTEGER NOT NULL DEFAULT 0 CHECK(reminder_number >= 0),
                    status TEXT NOT NULL CHECK(status IN (
                        'draft','sending','sent','failed','uncertain','cancelled','skipped'
                    )),
                    message TEXT NOT NULL DEFAULT '',
                    error_category TEXT NOT NULL DEFAULT '',
                    created_by INTEGER,
                    telegram_message_id INTEGER,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    sent_at TEXT
                );
                CREATE INDEX IF NOT EXISTS applicant_followup_delivery_user
                    ON applicant_followup_deliveries(user_id,created DESC);
                CREATE INDEX IF NOT EXISTS applicant_followup_delivery_status
                    ON applicant_followup_deliveries(status,created);
                CREATE TABLE IF NOT EXISTS applicant_followup_events (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    delivery_id TEXT,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS applicant_followup_events_user
                    ON applicant_followup_events(user_id,created DESC);
                PRAGMA user_version=9;
                COMMIT;
            """)
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 9:
            self.conn.executescript("""
                PRAGMA foreign_keys=OFF;
                BEGIN IMMEDIATE;
                ALTER TABLE portal_signal_command_events
                    RENAME TO portal_signal_command_events_old;
                ALTER TABLE portal_signal_commands
                    RENAME TO portal_signal_commands_old;
                CREATE TABLE portal_signal_commands (
                    id TEXT PRIMARY KEY,
                    actor_staff_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN (
                        'create_zone_draft','publish_zone','record_confirmation',
                        'cancel_setup','expire_setup','publish_signal','publish_analysis'
                    )),
                    input_json TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    command_status TEXT NOT NULL DEFAULT 'queued' CHECK(command_status IN (
                        'queued','processing','preview_ready','approved','completed',
                        'failed','uncertain','stale','cancelled'
                    )),
                    preview_text TEXT NOT NULL DEFAULT '',
                    operation_id TEXT,
                    safe_result TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    completed_at TEXT
                );
                INSERT INTO portal_signal_commands
                    SELECT * FROM portal_signal_commands_old;
                CREATE TABLE portal_signal_command_events (
                    id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL REFERENCES portal_signal_commands(id) ON DELETE CASCADE,
                    actor_staff_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL
                );
                INSERT INTO portal_signal_command_events
                    SELECT * FROM portal_signal_command_events_old;
                DROP TABLE portal_signal_command_events_old;
                DROP TABLE portal_signal_commands_old;
                CREATE INDEX portal_signal_commands_queue
                    ON portal_signal_commands(command_status,created)
                    WHERE command_status IN ('queued','approved');
                CREATE INDEX portal_signal_command_events_command
                    ON portal_signal_command_events(command_id,created);
                PRAGMA user_version=10;
                COMMIT;
                PRAGMA foreign_keys=ON;
            """)
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 10:
            self.conn.executescript("""
                PRAGMA foreign_keys=OFF;
                BEGIN IMMEDIATE;
                ALTER TABLE portal_member_review_commands
                    RENAME TO portal_member_review_commands_old;
                CREATE TABLE portal_member_review_commands (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES member_requests(id) ON DELETE RESTRICT,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN (
                        'approve_registration','reject_registration','verify_funding','reject_funding',
                        'approve','reject','request_evidence'
                    )),
                    previous_status TEXT NOT NULL,
                    previous_funding_status TEXT NOT NULL,
                    expected_updated TEXT NOT NULL,
                    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1200),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    command_status TEXT NOT NULL DEFAULT 'queued'
                        CHECK(command_status IN ('queued','processing','completed','failed','uncertain','stale')),
                    delivery_status TEXT NOT NULL DEFAULT 'not_attempted'
                        CHECK(delivery_status IN ('not_attempted','sent','failed','uncertain','not_needed')),
                    safe_result TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    completed_at TEXT
                );
                INSERT INTO portal_member_review_commands
                    SELECT * FROM portal_member_review_commands_old;
                DROP TABLE portal_member_review_commands_old;
                CREATE INDEX portal_member_review_commands_request
                    ON portal_member_review_commands(request_id,created DESC);
                CREATE INDEX portal_member_review_commands_queue
                    ON portal_member_review_commands(command_status,created)
                    WHERE command_status='queued';
                CREATE UNIQUE INDEX portal_member_review_one_open_command
                    ON portal_member_review_commands(request_id)
                    WHERE command_status IN ('queued','processing','uncertain');
                PRAGMA user_version=11;
                COMMIT;
                PRAGMA foreign_keys=ON;
            """)

    @contextmanager
    def transaction(self):
        with self.conn:
            if not self.postgres:
                self.conn.execute("BEGIN IMMEDIATE")
            yield self.conn

    def rows(self, sql, args=()):
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.conn:
            return self.conn.execute(sql, args)

    def get(self, key, default=None):
        r = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def put(self, key, value):
        self.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))

    def draft(self, owner):
        r = self.conn.execute("SELECT data FROM drafts WHERE owner=?", (owner,)).fetchone()
        return json.loads(r[0]) if r else None

    def save_draft(self, owner, data):
        self.persist_images(data)
        data["revision"] = uid()
        self.execute("INSERT OR REPLACE INTO drafts VALUES (?,?,?)", (owner, json.dumps(data), now()))

    def clear_draft(self, owner):
        self.execute("DELETE FROM drafts WHERE owner=?", (owner,))

    def button(self, owner, action, data=None):
        key = uid()
        self.execute("INSERT INTO buttons VALUES (?,?,?,?,?,0)",
                     (key, owner, action, json.dumps(data or {}), time.time() + 86400))
        return key

    def consume(self, key, owner):
        with self.transaction() as c:
            r = c.execute("SELECT * FROM buttons WHERE id=?", (key,)).fetchone()
            if not r or r["owner"] != owner or r["used"] or r["expires"] < time.time():
                raise ValueError("This button has expired or was already used. Open the menu again.")
            c.execute("UPDATE buttons SET used=1 WHERE id=?", (key,))
            return r["action"], json.loads(r["data"])

    def trade(self, trade_id):
        r = self.conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not r:
            raise ValueError("Trade not found.")
        return {**json.loads(r["data"]), "state": r["state"], "version": r["version"],
                "created": r["created"], "updated": r["updated"]}

    @staticmethod
    def _signal_result_key(trade_id):
        trade_id = str(trade_id or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", trade_id):
            raise ValueError("Invalid saved trade reference.")
        return f"signal_result:{trade_id}"

    def signal_result(self, trade_id):
        return self.get(self._signal_result_key(trade_id))

    def signal_results(self):
        results = []
        for row in self.rows(
                "SELECT value FROM kv WHERE key LIKE ?", ("signal_result:%",)):
            try:
                result = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(result, dict) and result.get("trade_id"):
                results.append(result)
        return sorted(results, key=lambda item: item.get("updated", ""), reverse=True)

    def create_signal_result(self, trade_id, actor):
        trade = self.trade(trade_id)
        key = self._signal_result_key(trade_id)
        timestamp = now()
        record = {
            "id": uid(),
            "trade_id": str(trade_id),
            "setup_id": trade.get("setup_id"),
            "direction": trade.get("direction"),
            "symbol": trade.get("symbol") or trade.get("market"),
            "market": trade.get("market"),
            "entry": trade.get("entry"),
            "sl": trade.get("sl"),
            "targets": trade.get("targets", {}),
            "signal_text": trade.get("original_text", ""),
            "signal_message_id": trade.get("message_id"),
            "zone_message_id": trade.get("setup_message_id"),
            "signal_capture": "",
            "profit_image": "",
            "outcome": "",
            "caption": "",
            "status": "awaiting_signal",
            "operation_id": "",
            "analysis_message_id": None,
            "created_by": int(actor),
            "created": timestamp,
            "updated": timestamp,
        }
        with self.transaction() as connection:
            existing = connection.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            if existing:
                return json.loads(existing[0]), False
            connection.execute(
                "INSERT INTO kv (key,value) VALUES (?,?) ON CONFLICT(key) DO NOTHING",
                (key, json.dumps(record)),
            )
            saved = connection.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json.loads(saved[0]), True

    def update_signal_result(
            self, trade_id, updates, expected_statuses=None, expected_updated=None):
        allowed_fields = {
            "signal_capture", "profit_image", "outcome", "caption", "status",
            "operation_id", "analysis_message_id", "signal_message_id",
            "zone_message_id", "signal_text",
        }
        if not isinstance(updates, dict) or set(updates) - allowed_fields:
            raise ValueError("Unsupported result record update.")
        key = self._signal_result_key(trade_id)
        with self.transaction() as connection:
            row = connection.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            if not row:
                raise ValueError("No saved result is linked to this signal.")
            record = json.loads(row[0])
            if expected_statuses and record.get("status") not in set(expected_statuses):
                raise ValueError("This result changed. Reopen it and review the latest status.")
            if expected_updated and record.get("updated") != expected_updated:
                raise ValueError("This result changed. Reopen it and review the latest status.")
            status = updates.get("status")
            if status is not None and status not in (
                    "awaiting_signal", "pending", "ready", "publishing", "posted", "uncertain"):
                raise ValueError("Invalid result-post status.")
            record.update(updates)
            record["updated"] = now()
            connection.execute("UPDATE kv SET value=? WHERE key=?",
                               (json.dumps(record), key))
            return record

    def error(self, category, detail):
        # Callers supply safe, classified descriptions, never raw provider exceptions.
        self.execute("INSERT INTO errors(category,detail,created) VALUES (?,?,?)", (category, detail, now()))

    def backup(self, retention=14):
        if self.postgres:
            from .transfer import export_bundle
            path = self.directory / "backups" / f"hub-{uid()}.zip"
            export_bundle(self, path)
            for old in sorted(path.parent.glob("hub-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[retention:]:
                old.unlink()
            return path
        path = self.directory / "backups" / f"hub-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}-{uid()}.sqlite3"
        with sqlite3.connect(path) as target:
            self.conn.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed.")
        for old in sorted(path.parent.glob("hub-*.sqlite3"), reverse=True)[retention:]:
            old.unlink()
        return path

    def cleanup(self):
        self.execute("DELETE FROM buttons WHERE expires<?", (time.time() - 86400,))
        referenced = set()
        for table, column in (("drafts", "data"), ("operations", "payload")):
            for row in self.rows(f"SELECT {column} AS data FROM {table}"):
                obj = json.loads(row["data"])
                for key in ("original", "image", "signal_capture", "profit_image"):
                    if obj.get(key):
                        referenced.add(obj[key])
        for result in self.signal_results():
            for key in ("signal_capture", "profit_image"):
                if result.get(key):
                    referenced.add(result[key])
        removed = 0
        for p in (self.directory / "images").iterdir():
            if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".webp"):
                continue
            if str(p) not in referenced and p.stat().st_mtime < time.time() - 7 * 86400:
                p.unlink()
                removed += 1
        return removed

    def integrity(self):
        if self.postgres:
            self.conn.execute("SELECT 1")
            return "ok"
        return self.conn.execute("PRAGMA integrity_check").fetchone()[0]

    def persist_images(self, data):
        import hashlib
        for key in ("original", "image", "signal_capture", "profit_image"):
            value = data.get(key)
            if not value or (isinstance(value, str) and value.startswith("asset:")):
                continue
            if not isinstance(value, str):
                raise ValueError("Image reference must be a saved file or asset.")
            path = Path(value)
            content = path.read_bytes()
            ident = hashlib.sha256(content).hexdigest() + path.suffix
            self.execute("INSERT INTO assets(id,content) VALUES (?,?) ON CONFLICT(id) DO NOTHING", (ident, content))
            data[key] = "asset:" + ident

    def image_path(self, reference):
        if not reference.startswith("asset:"):
            return reference
        import hashlib
        ident = reference[6:]
        if not __import__("re").fullmatch(r"[a-f0-9]{64}\.(png|jpg|jpeg|webp)", ident):
            raise ValueError("Invalid asset reference.")
        rows = self.rows("SELECT content FROM assets WHERE id=?", (ident,))
        if not rows:
            raise ValueError("Persistent chart is missing.")
        content = bytes(rows[0]["content"])
        if hashlib.sha256(content).hexdigest() != ident.split(".")[0]:
            raise ValueError("Chart integrity failure.")
        path = self.directory / "images" / ident
        path.write_bytes(content)
        return str(path)
