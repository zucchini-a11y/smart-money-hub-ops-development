import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from smh.config import Config
from smh.database import Database
from smh.handlers import Handlers


class ChannelHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name)
        self.config = Config(
            token="TEST_TOKEN_NOT_REAL",
            admin=42,
            signals=-1001,
            analysis=-1002,
            data=Path(self.tmp.name),
            isolated_test=True,
            education_video_group_id=-1003,
            education_video_topic_id=8,
        )
        self.handlers = object.__new__(Handlers)
        self.handlers.db = self.db
        self.handlers.config = self.config

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def message(self, chat_id=-1001, chat_type="channel", message_id=90, text="Signal text",
                caption=None, photo=None, thread_id=None, sender_id=None, sender_chat=None):
        return NS(
            message_id=message_id,
            chat=NS(id=chat_id, type=chat_type),
            text=text,
            caption=caption,
            photo=photo,
            video=None,
            animation=None,
            document=None,
            audio=None,
            voice=None,
            sticker=None,
            date=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
            message_thread_id=thread_id,
            from_user=NS(id=sender_id) if sender_id is not None else None,
            sender_chat=NS(id=sender_chat) if sender_chat is not None else None,
        )

    def update(self, message, update_id=100, edited=False):
        return NS(
            update_id=update_id,
            effective_chat=message.chat,
            effective_message=message,
            channel_post=None if edited else message,
            edited_channel_post=message if edited else None,
        )

    async def test_channel_posts_and_edits_are_recorded_once_without_media(self):
        post = self.message(photo=[NS(file_id="must-not-be-stored")], caption="Zone caption", text=None)
        update = self.update(post)
        await self.handlers.discover_channel(update, None)
        await self.handlers.discover_channel(update, None)

        edited = self.message(message_id=90, text="Corrected caption")
        await self.handlers.discover_channel(self.update(edited, update_id=101, edited=True), None)
        rows = self.db.rows("SELECT * FROM channel_history ORDER BY update_id")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["destination"], "PRO Signals")
        self.assertEqual(rows[0]["event_type"], "posted")
        self.assertEqual(rows[0]["message_text"], "Zone caption")
        self.assertEqual(rows[0]["attachment_label"], "Photo attached")
        self.assertEqual(rows[1]["event_type"], "edited")
        self.assertEqual(rows[1]["message_text"], "Corrected caption")
        self.assertNotIn("file_id", rows[0])
        self.assertNotIn("must-not-be-stored", str(rows))

    async def test_only_configured_broadcast_channels_are_captured(self):
        for update_id, chat_id in ((200, -1002), (201, -1999)):
            post = self.message(chat_id=chat_id, message_id=update_id, text="Analysis")
            await self.handlers.discover_channel(self.update(post, update_id=update_id), None)
        rows = self.db.rows("SELECT destination FROM channel_history")
        self.assertEqual(rows, [{"destination": "Market Analysis"}])

    async def test_video_topic_captures_admin_posts_but_not_member_messages(self):
        admin_post = self.message(
            chat_id=-1003, chat_type="supergroup", message_id=301, text="Lesson note",
            thread_id=8, sender_id=42,
        )
        member_post = self.message(
            chat_id=-1003, chat_type="supergroup", message_id=302, text="Member conversation",
            thread_id=8, sender_id=77,
        )
        self.handlers.record_education_topic_post(self.update(admin_post, 300), None)
        self.handlers.record_education_topic_post(self.update(member_post, 301), None)
        rows = self.db.rows("SELECT destination,message_text FROM channel_history")
        self.assertEqual(rows, [{
            "destination": "Educational Group · Video tutorials",
            "message_text": "Lesson note",
        }])

    async def test_production_instance_does_not_capture_channel_history(self):
        production_config = Config(
            token="TEST_TOKEN_NOT_REAL",
            admin=42,
            signals=-1001,
            analysis=-1002,
            data=Path(self.tmp.name),
            isolated_test=False,
        )
        self.handlers.config = production_config
        post = self.message()
        await self.handlers.discover_channel(self.update(post, 400), None)
        self.assertEqual(self.db.rows("SELECT * FROM channel_history"), [])


if __name__ == "__main__":
    unittest.main()
