import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import Forbidden

from smh.assistant import process_portal_reply_once, recover_portal_replies
from smh.database import Database


class PortalReplyWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "data")
        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('case-1',4242,'How do I update my application?','reply_sending','now','now')"
        )
        self.db.execute(
            "INSERT INTO portal_users "
            "(id,email,display_name,password_hash,role,active,must_change_password,created,updated) "
            "VALUES ('staff-1','agent@example.test','Jordan A.','test-hash','agent',1,0,'now','now')"
        )
        self.db.execute(
            "INSERT INTO assistant_support_replies "
            "(id,case_id,staff_id,responder_name,text,status,request_id,created,updated) "
            "VALUES ('reply-1','case-1','staff-1','Jordan A.','I can help with that.','queued',"
            "'request-1234567890123456','now','now')"
        )
        self.bot = SimpleNamespace(send_message=AsyncMock())

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    async def test_queued_reply_is_sent_with_responder_name_and_audited(self):
        self.assertTrue(await process_portal_reply_once(self.db, self.bot))
        self.bot.send_message.assert_awaited_once()
        kwargs = self.bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 4242)
        self.assertIn("VAYDA | Support · Jordan A.", kwargs["text"])
        self.assertIn("I can help with that.", kwargs["text"])
        case = self.db.rows("SELECT status,reply,replied_by_name,replied_by_staff_id FROM assistant_escalations")[0]
        self.assertEqual(case["status"], "replied")
        self.assertEqual(case["reply"], "I can help with that.")
        self.assertEqual(case["replied_by_name"], "Jordan A.")
        self.assertEqual(case["replied_by_staff_id"], "staff-1")
        self.assertEqual(self.db.rows("SELECT status FROM assistant_support_replies")[0]["status"], "sent")
        self.assertEqual(self.db.rows("SELECT action FROM portal_audit")[0]["action"], "reply_sent")

    async def test_administrator_reply_is_labeled_as_administrator(self):
        self.db.execute("UPDATE portal_users SET role='admin' WHERE id='staff-1'")
        self.assertTrue(await process_portal_reply_once(self.db, self.bot))
        kwargs = self.bot.send_message.await_args.kwargs
        self.assertIn("VAYDA | Administrator · Jordan A.", kwargs["text"])

    async def test_uncertain_send_is_not_retried(self):
        self.bot.send_message.side_effect = TimeoutError("synthetic timeout")
        self.assertTrue(await process_portal_reply_once(self.db, self.bot))
        self.assertFalse(await process_portal_reply_once(self.db, self.bot))
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.db.rows("SELECT status FROM assistant_support_replies")[0]["status"], "uncertain")
        self.assertEqual(
            self.db.rows("SELECT status FROM assistant_escalations")[0]["status"], "reply_uncertain")
        self.assertEqual(self.db.rows("SELECT action FROM portal_audit")[0]["action"], "reply_uncertain")
        self.assertEqual(self.db.rows("SELECT action FROM portal_audit")[0]["action"], "reply_uncertain")

    async def test_restart_quarantines_inflight_send_without_replaying(self):
        self.db.execute(
            "UPDATE assistant_support_replies SET status='sending' WHERE id='reply-1'")
        self.assertEqual(recover_portal_replies(self.db), 1)
        self.assertFalse(await process_portal_reply_once(self.db, self.bot))
        self.bot.send_message.assert_not_awaited()
        self.assertEqual(self.db.rows("SELECT status FROM assistant_support_replies")[0]["status"], "uncertain")
        self.assertEqual(
            self.db.rows("SELECT status FROM assistant_escalations")[0]["status"], "reply_uncertain")

    async def test_definite_telegram_rejection_reopens_case_without_retry(self):
        self.bot.send_message.side_effect = Forbidden("member blocked bot")
        self.assertTrue(await process_portal_reply_once(self.db, self.bot))
        self.assertFalse(await process_portal_reply_once(self.db, self.bot))
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.db.rows("SELECT status FROM assistant_support_replies")[0]["status"], "failed")
        self.assertEqual(self.db.rows("SELECT status FROM assistant_escalations")[0]["status"], "open")

    async def test_inactive_staff_reply_is_not_sent(self):
        self.db.execute("UPDATE portal_users SET active=0 WHERE id='staff-1'")
        self.assertFalse(await process_portal_reply_once(self.db, self.bot))
        self.bot.send_message.assert_not_awaited()

    async def test_reply_containing_credentials_is_rejected_before_telegram(self):
        self.db.execute(
            "UPDATE assistant_support_replies SET text='Password: synthetic-secret' WHERE id='reply-1'")
        self.assertTrue(await process_portal_reply_once(self.db, self.bot))
        self.bot.send_message.assert_not_awaited()
        self.assertEqual(self.db.rows("SELECT status FROM assistant_support_replies")[0]["status"], "failed")
        self.assertEqual(self.db.rows("SELECT status FROM assistant_escalations")[0]["status"], "open")
        self.assertEqual(self.db.rows("SELECT action FROM portal_audit")[0]["action"], "reply_rejected")
