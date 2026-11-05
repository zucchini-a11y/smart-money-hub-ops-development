import json
import hashlib
import os
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from PIL import Image
from smh.database import Database, uid
from smh.publishing import Publisher
from smh.transfer import V6_TABLES, export_bundle, restore_bundle
from tests import test_core
from tests import test_buttons
from smh.handlers import Handlers
from smh.health import Health


def pg_database(directory):
    import psycopg
    url = os.environ.get("SMH_TEST_POSTGRES_URL") or os.environ["DATABASE_URL"]
    schema = "test_" + uid()
    with psycopg.connect(url) as c:
        for migration in sorted(Path("migrations").glob("[0-9][0-9][0-9]_*.sql")):
            if migration.name.startswith("011_"):
                c.execute(f'SET search_path TO "{schema}"')
                c.execute(migration.read_text())
            else:
                c.execute(migration.read_text().replace("smh", schema))
        c.execute(f'SET search_path TO "{schema}"')
    return Database(directory, url, schema)


def cleanup_pg(db):
    schema = db.schema
    db.conn.raw.execute(f"DROP SCHEMA {schema} CASCADE")
    db.conn.close()


class VersionedTransferTests(unittest.TestCase):
    def _v8_database(self, directory):
        db = Database(directory)
        for table in (
            "applicant_followup_state",
            "applicant_followup_deliveries",
            "applicant_followup_events",
        ):
            db.execute(f"DROP TABLE {table}")
        db.conn.execute("PRAGMA user_version=8")
        return db

    def test_schema_v8_export_and_restore_do_not_require_v9_tables(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source = self._v8_database(source_dir)
            target = self._v8_database(target_dir)
            archive = Path(source_dir) / "v8-backup.zip"
            try:
                export_bundle(source, archive)
                with zipfile.ZipFile(archive) as zipped:
                    manifest = json.loads(zipped.read("manifest.json"))
                    tables = json.loads(zipped.read("database.json"))
                self.assertEqual(manifest["format"], 6)
                self.assertEqual(set(tables), set(V6_TABLES))
                restore_bundle(target, archive)
                self.assertEqual(target.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                source.conn.close()
                target.conn.close()

    def test_postgres_export_serializes_channel_history_timestamp(self):
        if not (os.getenv("SMH_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL")):
            self.skipTest("PostgreSQL test database is not configured.")
        with tempfile.TemporaryDirectory() as temp:
            source = pg_database(Path(temp) / "pg")
            try:
                source.execute(
                    "INSERT INTO channel_history "
                    "(update_id,chat_id,message_id,destination,event_type,message_text,attachment_label,recorded_at) "
                    "VALUES (990901,-1001,91,'PRO Signals','posted','TEST ONLY history','Photo attached',NOW())"
                )
                bundle = export_bundle(source, Path(temp) / "postgres-export.zip")
                with zipfile.ZipFile(bundle) as zipped:
                    records = json.loads(zipped.read("database.json"))["channel_history"]
                self.assertEqual(len(records), 1)
                self.assertIsInstance(records[0]["recorded_at"], str)
                self.assertIn("+", records[0]["recorded_at"])
            finally:
                cleanup_pg(source)


def verified_bot(bot, signals, analysis):
    async def chat(ident):
        chat_type = ("private" if ident == 42 else
                     "channel" if ident in (signals, analysis) else "supergroup")
        return NS(id=ident, type=chat_type)
    bot.get_chat = AsyncMock(side_effect=chat)
    bot.get_chat_member = AsyncMock(return_value=NS(status="administrator", can_post_messages=True,
                                                   can_edit_messages=True, can_invite_users=True))


@unittest.skipUnless(os.getenv("SMH_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL"), "PostgreSQL test connection not configured")
class PostgreSQLCore(test_core.AsyncTests):
    def setUp(self):
        super().setUp()
        self.db.conn.close()
        self.db = pg_database(self.tmp.name)
        self.config = replace(self.config, allow_publishing=True)
        verified_bot(self.bot, self.config.signals, self.config.analysis)
        self.pub = Publisher(self.db, self.config, self.bot)
        self.pub.verified = True

    def tearDown(self):
        cleanup_pg(self.db)
        self.tmp.cleanup()

    async def test_channel_history_migration_and_duplicate_update_protection(self):
        self.db.execute(
            "INSERT INTO channel_history "
            "(update_id,chat_id,message_id,destination,event_type,message_text,attachment_label,recorded_at) "
            "VALUES (901,-1001,91,'PRO Signals','posted','TEST ONLY','Photo attached','2026-10-21T10:00:00+00:00')"
        )
        self.db.execute(
            "INSERT INTO channel_history "
            "(update_id,chat_id,message_id,destination,event_type,message_text,attachment_label,recorded_at) "
            "VALUES (901,-1001,91,'PRO Signals','posted','duplicate','Photo attached','2026-10-21T10:00:00+00:00') "
            "ON CONFLICT(update_id) DO NOTHING"
        )
        self.assertEqual(
            self.db.rows("SELECT message_text FROM channel_history WHERE update_id=901"),
            [{"message_text": "TEST ONLY"}],
        )

    async def test_publishing_default_locked(self):
        self.pub.config = replace(self.config, allow_publishing=False)
        with self.assertRaises(ValueError):
            await self.pub.send(42, self.signal())
        self.bot.send_message.assert_not_called()

    async def test_wrong_admin_or_channel_blocks(self):
        self.bot.get_chat.return_value = NS(id=99, type="private")
        self.bot.get_chat.side_effect = None
        with self.assertRaises(ValueError):
            await self.pub.verify_destinations()
        self.assertFalse(self.pub.verified)

    async def test_missing_channel_permission_blocks(self):
        self.bot.get_chat_member.return_value = NS(status="member")
        with self.assertRaises(ValueError):
            await self.pub.verify_destinations()
        self.assertFalse(self.pub.verified)

    async def test_postgres_export_restore_completed_send_never_replayed(self):
        op = self.signal()
        await self.pub.send(42, op)
        bundle = export_bundle(self.db, Path(self.tmp.name) / "pg-export.zip")
        target = pg_database(Path(self.tmp.name) / "restored")
        try:
            restore_bundle(target, bundle)
            recovered = Publisher(target, self.config, self.bot)
            recovered.verified = True
            recovered.recover()
            await recovered.send(42, op)
            self.assertEqual(self.bot.send_message.await_count, 1)
            self.assertEqual(target.trade("trade1")["message_id"], 90)
            target.error("restored", "Sequence remains usable.")
        finally:
            cleanup_pg(target)


class SQLiteSchemaMigrationTests(unittest.TestCase):
    @staticmethod
    def drop_portal_tables(db):
        for table in ("education_video_posts", "assistant_support_replies", "portal_sessions",
                      "portal_audit", "portal_users"):
            db.execute(f"DROP TABLE {table}")

    def test_sqlite_v2_migrates_assistant_table_without_losing_member_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "version-two"
            db = Database(path)
            db.execute("INSERT INTO applications VALUES (901,'[]','approved','old')")
            db.execute(
                "INSERT INTO member_requests "
                "(id,user_id,username,destination,answers,status,created,updated) "
                "VALUES ('education-901',901,'member','education','[]','approved','old','old')"
            )
            self.drop_portal_tables(db)
            db.execute("DROP TABLE assistant_escalations")
            db.conn.execute("PRAGMA user_version=2")
            db.conn.close()

            upgraded = Database(path)
            self.assertEqual(upgraded.conn.execute("PRAGMA user_version").fetchone()[0], 11)
            self.assertEqual(upgraded.rows(
                "SELECT status FROM applications WHERE user_id=901")[0]["status"], "approved")
            self.assertEqual(upgraded.rows(
                "SELECT status FROM member_requests WHERE id='education-901'")[0]["status"], "approved")
            self.assertTrue(upgraded.rows(
                "SELECT name FROM sqlite_master WHERE name='assistant_escalations'"))
            upgraded.conn.close()

    def test_sqlite_v1_migrates_without_losing_member_access(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy"
            old = Database(path)
            old.execute("INSERT INTO applications VALUES (900,'[]','approved','old')")
            old.execute("INSERT INTO access VALUES (900,-1001,'joined','old')")
            self.drop_portal_tables(old)
            old.execute("DROP TABLE assistant_escalations")
            old.execute("DROP TABLE member_request_events")
            old.execute("DROP TABLE member_requests")
            old.conn.execute("PRAGMA user_version=1")
            old.conn.close()
            upgraded = Database(path)
            self.assertEqual(upgraded.conn.execute("PRAGMA user_version").fetchone()[0], 11)
            self.assertEqual(upgraded.rows(
                "SELECT status FROM applications WHERE user_id=900")[0]["status"], "approved")
            self.assertEqual(upgraded.rows(
                "SELECT status FROM access WHERE user_id=900")[0]["status"], "joined")
            self.assertTrue(upgraded.rows(
                "SELECT name FROM sqlite_master WHERE name='member_requests'"))
            upgraded.conn.close()

    def test_sqlite_v3_migration_preserves_assistant_cases_and_adds_portal_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "version-three"
            db = Database(path)
            db.execute("DROP TABLE education_video_posts")
            db.execute("DROP TABLE assistant_support_replies")
            db.execute("DROP TABLE portal_sessions")
            db.execute("DROP TABLE portal_audit")
            db.execute("DROP TABLE portal_users")
            db.execute("DROP TABLE assistant_escalations")
            db.conn.executescript("""
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
                CREATE INDEX assistant_escalations_status ON assistant_escalations(status,created);
                CREATE INDEX assistant_escalations_user ON assistant_escalations(user_id,created);
                INSERT INTO assistant_escalations
                    (id,user_id,question,status,created,updated)
                    VALUES ('help-v3',99,'Need support','open','old','old');
                PRAGMA user_version=3;
            """)
            db.conn.close()
            upgraded = Database(path)
            self.assertEqual(upgraded.conn.execute("PRAGMA user_version").fetchone()[0], 11)
            self.assertEqual(
                dict(upgraded.rows(
                    "SELECT question,status FROM assistant_escalations WHERE id='help-v3'")[0]),
                {"question": "Need support", "status": "open"},
            )
            self.assertTrue(upgraded.rows(
                "SELECT name FROM sqlite_master WHERE name='assistant_support_replies'"))
            upgraded.conn.close()


class RestoreTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("SMH_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL"), "PostgreSQL not configured")
    def test_fresh_schema_only_deployment(self):
        with tempfile.TemporaryDirectory() as temp:
            db = pg_database(temp)
            schema = db.schema
            url = os.environ.get("SMH_TEST_POSTGRES_URL") or os.environ["DATABASE_URL"]
            db.execute("DELETE FROM schema_version")
            db.conn.close()
            db = Database(temp, url, schema)
            try:
                self.assertEqual(db.integrity(), "ok")
            finally:
                cleanup_pg(db)

    def test_export_restore_images_records_restart_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Database(Path(temp) / "old")
            chart = source.directory / "images" / "source.png"
            Image.new("RGB", (400, 300), "blue").save(chart)
            source.save_draft(42, {"kind": "analysis", "step": "ready", "text": "Bullish H4 structure.",
                                   "original": str(chart), "image": str(chart)})
            source.put("telegram_offset", 101)
            source.put("operator_setting", "value")
            source.execute("INSERT INTO applications VALUES (42,'[]','approved','now')")
            source.execute("INSERT INTO access VALUES (42,-1001,'joined','now')")
            source.execute(
                "INSERT INTO member_requests "
                "(id,user_id,username,destination,answers,status,registration_status,funding_status,source,"
                "evidence_file_id,evidence_kind,evidence_submitted_at,created,updated) "
                "VALUES ('pro-42',42,'member','pro','[]','pending_review','verified','pending_review','new',"
                "'telegram-private-file-id','application/pdf','evidence-time','now','now')")
            source.execute(
                "INSERT INTO member_request_events(request_id,actor,action,detail,created) "
                "VALUES ('pro-42',42,'funding_evidence_submitted','private file reference','now')")
            source.execute(
                "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
                "VALUES ('help-42',42,'How do I check my access?','reply_sending','now','now')")
            source.execute(
                "INSERT INTO portal_users "
                "(id,email,display_name,password_hash,role,active,must_change_password,created,updated) "
                "VALUES ('staff-1','staff@example.test','A. Support','scrypt$demo','agent',1,1,'now','now')")
            source.execute(
                "INSERT INTO portal_sessions(token_hash,staff_id,created,expires) "
                "VALUES ('session-hash','staff-1','now','2099-01-01T00:00:00Z')")
            source.execute(
                "INSERT INTO assistant_support_replies "
                "(id,case_id,staff_id,responder_name,text,status,request_id,created,updated) "
                "VALUES ('reply-1','help-42','staff-1','A. Support','I can help with that.','sending',"
                "'request-1234567890123456','now','now')")
            source.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "VALUES ('audit-1','staff-1','reply_queued','help-42','now','reply-1')")
            source.execute("INSERT INTO operations VALUES ('pending','analysis','{}','sending',NULL,'now','now')")
            source.execute("INSERT INTO trades VALUES ('restored-trade',?,'CLOSED','now','now',2)",
                           (json.dumps({"id": "restored-trade", "symbol": "XAUUSD", "direction": "BUY", "entry": "2600"}),))
            source.execute("INSERT INTO operations VALUES ('completed','update','{}','done',91,'now','now')")
            source.execute("INSERT INTO events(trade_id,operation_id,actor,text,message_id,created) VALUES ('restored-trade','completed',42,'Trade closed — Profit',91,'now')")
            source.execute(
                "INSERT INTO channel_history "
                "(update_id,chat_id,message_id,destination,event_type,message_text,attachment_label,recorded_at) "
                "VALUES (901,-1001,91,'PRO Signals','posted','TEST ONLY history','Photo attached','2026-10-21T10:00:00+00:00')")
            key = source.button(42, "publish")
            bundle = export_bundle(source, Path(temp) / "export.zip")
            for postgres in (False, True):
                if postgres and not (os.getenv("SMH_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL")):
                    continue
                target = pg_database(Path(temp) / "pg") if postgres else Database(Path(temp) / "new")
                try:
                    restore_bundle(target, bundle)
                    self.assertEqual(target.get("telegram_offset"), 101)
                    self.assertEqual(target.get("operator_setting"), "value")
                    self.assertEqual(target.rows("SELECT status FROM access")[0]["status"], "joined")
                    self.assertEqual(
                        target.rows("SELECT destination,message_text,attachment_label FROM channel_history"),
                        [{"destination": "PRO Signals", "message_text": "TEST ONLY history",
                          "attachment_label": "Photo attached"}],
                    )
                    self.assertEqual(target.rows("SELECT status FROM applications")[0]["status"], "approved")
                    member_request = target.rows("SELECT * FROM member_requests WHERE id='pro-42'")[0]
                    self.assertEqual(member_request["funding_status"], "pending_review")
                    self.assertEqual(member_request["evidence_file_id"], "telegram-private-file-id")
                    self.assertEqual(target.rows(
                        "SELECT action FROM member_request_events WHERE request_id='pro-42'")[0]["action"],
                        "funding_evidence_submitted")
                    self.assertEqual(
                        target.rows("SELECT question,status FROM assistant_escalations WHERE id='help-42'")[0]["question"],
                        "How do I check my access?")
                    self.assertEqual(target.rows(
                        "SELECT status FROM assistant_escalations WHERE id='help-42'")[0]["status"],
                        "reply_uncertain")
                    restored_reply = target.rows(
                        "SELECT status,responder_name,text FROM assistant_support_replies WHERE id='reply-1'")[0]
                    self.assertEqual(restored_reply["status"], "uncertain")
                    self.assertEqual(restored_reply["responder_name"], "A. Support")
                    self.assertEqual(restored_reply["text"], "I can help with that.")
                    self.assertEqual(target.rows(
                        "SELECT email FROM portal_users WHERE id='staff-1'")[0]["email"], "staff@example.test")
                    self.assertEqual(target.rows("SELECT count(*) AS n FROM portal_sessions")[0]["n"], 0)
                    self.assertEqual(target.rows(
                        "SELECT action FROM portal_audit WHERE id='audit-1'")[0]["action"], "reply_queued")
                    self.assertEqual(target.rows("SELECT status FROM operations WHERE id='pending'")[0]["status"], "uncertain")
                    self.assertEqual(target.trade("restored-trade")["entry"], "2600")
                    self.assertEqual(target.trade("restored-trade")["state"], "CLOSED")
                    history = target.rows("SELECT * FROM events WHERE trade_id='restored-trade'")
                    self.assertEqual(history[0]["text"], "Trade closed — Profit")
                    self.assertEqual(history[0]["message_id"], 91)
                    import zipfile
                    with zipfile.ZipFile(bundle) as archive:
                        manifest = json.loads(archive.read("manifest.json"))
                    image_id = target.draft(42)["image"][6:]
                    record = next(r for r in manifest["images"] if r["id"] == image_id)
                    self.assertTrue(any(r["table"] == "drafts" and r["id"] == 42 and r["role"] == "image"
                                        for r in record["references"]))
                    with self.assertRaises(ValueError):
                        target.consume(key, 42)
                    image = target.image_path(target.draft(42)["image"])
                    self.assertEqual(Path(image).read_bytes(), chart.read_bytes())
                    Path(image).unlink()
                    self.assertTrue(Path(target.image_path(target.draft(42)["image"])).exists())
                    with self.assertRaises(ValueError):
                        restore_bundle(target, bundle)
                    self.assertEqual(target.integrity(), "ok")
                finally:
                    cleanup_pg(target) if postgres else target.conn.close()
            source.conn.close()


@unittest.skipUnless(os.getenv("SMH_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL"), "PostgreSQL test connection not configured")
class PostgreSQLButtons(test_buttons.ButtonFlows):
    def setUp(self):
        super().setUp()
        self.db.conn.close()
        self.db = pg_database(self.temp.name)
        self.config = replace(self.config, allow_publishing=True)
        verified_bot(self.bot, self.config.signals, self.config.analysis)
        self.pub = Publisher(self.db, self.config, self.bot)
        self.pub.verified = True
        self.ui = Handlers(self.db, self.config, self.bot, self.pub, Health(self.db, self.config, self.bot))

    def tearDown(self):
        cleanup_pg(self.db)
        self.temp.cleanup()


class EducationVideoBackupTests(unittest.TestCase):
    def test_export_restore_preserves_video_and_quarantines_queued_send(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = Database(root / "source-db")
            source.education_video_data_dir = root / "source-videos"
            source.education_video_data_dir.mkdir()
            content = b"portable test video bytes"
            digest = hashlib.sha256(content).hexdigest()
            draft_name = "1" * 32 + ".mp4"
            queued_name = "2" * 32 + ".mp4"
            for name in (draft_name, queued_name):
                (source.education_video_data_dir / name).write_bytes(content)
            created = "2026-10-21T10:00:00+00:00"
            source.execute(
                "INSERT INTO education_video_posts "
                "(id,title,caption,file_name,storage_name,byte_size,file_sha256,status,created_by,"
                "created_by_name,request_id,target_chat_id,target_thread_id,target_topic_name,created,updated) "
                "VALUES(?,?,?,?,?,?,?,'draft','owner-test','Test Owner','request-video-restore-1',"
                "-100401,8,'Video tutorials',?,?)",
                ("a" * 32, "Draft lesson", "Caption", "draft.mp4", draft_name,
                 len(content), digest, created, created),
            )
            source.execute(
                "INSERT INTO education_video_posts "
                "(id,title,caption,file_name,storage_name,byte_size,file_sha256,status,created_by,"
                "created_by_name,request_id,publish_request_id,target_chat_id,target_thread_id,"
                "target_topic_name,created,updated) "
                "VALUES(?,?,?,?,?,?,?,'queued','owner-test','Test Owner','request-video-restore-2',"
                "'publish-video-restore-2',-100401,8,'Video tutorials',?,?)",
                ("b" * 32, "Queued lesson", "Caption", "queued.mp4", queued_name,
                 len(content), digest, created, created),
            )
            bundle = export_bundle(source, root / "education-export.zip")
            target = Database(root / "target-db")
            target.education_video_data_dir = root / "restored-videos"
            restored_counts = restore_bundle(target, bundle)
            self.assertEqual(restored_counts["education_video_posts"], 2)
            restored = target.rows(
                "SELECT id,status,storage_name,file_sha256 FROM education_video_posts ORDER BY id")
            self.assertEqual([row["status"] for row in restored], ["draft", "uncertain"])
            for row in restored:
                restored_file = target.education_video_data_dir / row["storage_name"]
                self.assertEqual(restored_file.read_bytes(), content)
                self.assertEqual(hashlib.sha256(restored_file.read_bytes()).hexdigest(),
                                 row["file_sha256"])
            source.conn.close()
            target.conn.close()
