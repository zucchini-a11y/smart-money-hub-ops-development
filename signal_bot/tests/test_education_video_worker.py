import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import NetworkError

from smh.database import Database, now
from smh.education_video_worker import (
    process_education_video_once,
    recover_education_video_posts,
)


class EducationVideoWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = Database(root / "db")
        self.video_dir = root / "videos"
        self.video_dir.mkdir()
        self.config = SimpleNamespace(
            allow_publishing=True,
            isolated_test=True,
            signals=-100100,
            analysis=-100200,
            education_group_id=-100300,
            education_video_group_id=-100400,
            education_video_topic_id=8,
            education_video_data_dir=self.video_dir,
        )
        self.storage_name = "a" * 32 + ".mp4"
        content = b"synthetic-mp4-content"
        (self.video_dir / self.storage_name).write_bytes(content)
        import hashlib
        self.db.execute(
            "INSERT INTO education_video_posts "
            "(id,title,caption,file_name,storage_name,byte_size,file_sha256,status,created_by,"
            "created_by_name,request_id,publish_request_id,target_chat_id,target_thread_id,"
            "target_topic_name,created,updated) "
            "VALUES(?,?,?,?,?,?,?,'queued','owner-test','Test Owner','request-video-0001',"
            "'publish-video-0001',-100400,8,'Video tutorials',?,?)",
            ("b" * 32, "Lesson <One>", "A & B", "lesson.mp4", self.storage_name,
             len(content), hashlib.sha256(content).hexdigest(), now(), now()),
        )
        self.sent_video_bytes = []

        async def capture_video(**kwargs):
            self.sent_video_bytes.append(kwargs["video"].read())
            return SimpleNamespace(message_id=34)

        self.bot = SimpleNamespace(
            id=987654,
            get_chat=AsyncMock(return_value=SimpleNamespace(
                id=-100400, type="supergroup", is_forum=True, username=None)),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="administrator")),
            send_video=AsyncMock(side_effect=capture_video),
        )

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    async def test_video_is_sent_only_to_exact_video_topic_and_audited(self):
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_awaited_once()
        sent = self.bot.send_video.await_args.kwargs
        self.assertEqual(sent["chat_id"], -100400)
        self.assertEqual(sent["message_thread_id"], 8)
        self.assertEqual(sent["caption"], "<b>Lesson &lt;One&gt;</b>\n\nA &amp; B")
        self.assertEqual(self.sent_video_bytes, [b"synthetic-mp4-content"])
        self.assertEqual(
            self.db.rows("SELECT status,telegram_message_id FROM education_video_posts")[0],
            {"status": "published", "telegram_message_id": 34},
        )
        self.assertEqual(
            self.db.rows("SELECT action FROM portal_audit")[0]["action"],
            "education_video_published",
        )

    async def test_duplicate_worker_tick_does_not_send_twice(self):
        await process_education_video_once(self.db, self.bot, self.config)
        self.assertFalse(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_awaited_once()

    async def test_production_or_test_publish_lock_blocks_before_send(self):
        self.config.allow_publishing = False
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_not_awaited()
        row = self.db.rows("SELECT status,safe_result FROM education_video_posts")[0]
        self.assertEqual(row["status"], "blocked")
        self.assertIn("locked", row["safe_result"])

    async def test_wrong_destination_is_blocked_before_send(self):
        self.db.execute("UPDATE education_video_posts SET target_thread_id=9")
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_not_awaited()
        self.assertEqual(
            self.db.rows("SELECT status FROM education_video_posts")[0]["status"], "blocked")

    async def test_same_education_forum_allows_only_a_distinct_video_topic(self):
        self.config.education_group_id = -100400
        self.config.education_announcement_url = "https://t.me/c/400/7/35"
        self.config.education_episode_01_url = "https://t.me/c/400/6/23"
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_awaited_once()
        self.assertEqual(self.bot.send_video.await_args.kwargs["chat_id"], -100400)
        self.assertEqual(self.bot.send_video.await_args.kwargs["message_thread_id"], 8)

    async def test_same_education_topic_cannot_be_used_for_video(self):
        self.config.education_group_id = -100400
        self.config.education_video_topic_id = 6
        self.config.education_announcement_url = "https://t.me/c/400/7/35"
        self.config.education_episode_01_url = "https://t.me/c/400/6/23"
        self.db.execute("UPDATE education_video_posts SET target_chat_id=-100400,target_thread_id=6")
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_not_awaited()
        row = self.db.rows("SELECT status,safe_result FROM education_video_posts")[0]
        self.assertEqual(row["status"], "blocked")
        self.assertIn("distinct", row["safe_result"])

    async def test_production_cannot_use_same_education_forum_for_video(self):
        self.config.isolated_test = False
        self.config.education_group_id = -100400
        self.config.education_announcement_url = "https://t.me/c/400/7/35"
        self.config.education_episode_01_url = "https://t.me/c/400/6/23"
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_not_awaited()
        row = self.db.rows("SELECT status,safe_result FROM education_video_posts")[0]
        self.assertEqual(row["status"], "blocked")
        self.assertIn("isolated test", row["safe_result"])

    async def test_destination_overlap_with_signals_is_blocked_before_send(self):
        self.config.education_video_group_id = self.config.signals
        self.db.execute("UPDATE education_video_posts SET target_chat_id=?", (self.config.signals,))
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_not_awaited()
        self.assertEqual(
            self.db.rows("SELECT status FROM education_video_posts")[0]["status"], "blocked")

    async def test_uncertain_send_is_not_retried(self):
        self.bot.send_video.side_effect = NetworkError("synthetic timeout")
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.assertFalse(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_awaited_once()
        self.assertEqual(
            self.db.rows("SELECT status FROM education_video_posts")[0]["status"], "uncertain")

    async def test_restart_quarantines_inflight_video_instead_of_replaying(self):
        self.db.execute("UPDATE education_video_posts SET status='sending'")
        self.assertEqual(recover_education_video_posts(self.db), 1)
        self.assertFalse(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_not_awaited()
        self.assertEqual(
            self.db.rows("SELECT status FROM education_video_posts")[0]["status"], "uncertain")

    async def test_public_test_group_is_blocked_before_send(self):
        self.bot.get_chat.return_value.username = "public_group"
        self.assertTrue(await process_education_video_once(self.db, self.bot, self.config))
        self.bot.send_video.assert_not_awaited()
        self.assertEqual(
            self.db.rows("SELECT status FROM education_video_posts")[0]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
