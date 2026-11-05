import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from smh.database import Database, now, uid
from smh.portal_signal_worker import (
    process_signal_command,
    recover_interrupted_commands,
    run_portal_signal_command_worker,
)
from smh.zones import save_in


class FakePublisher:
    def __init__(self, result="done"):
        self.verified = True
        self.result = result
        self.operations = {}
        self.prepare_calls = []
        self.send_calls = []

    def prepare(self, actor, kind, payload):
        op = uid()
        self.operations[op] = {
            "row": {"id": op, "kind": kind, "status": "prepared"},
            "payload": payload,
        }
        self.prepare_calls.append((actor, kind, payload))
        return op

    def operation(self, op):
        item = self.operations[op]
        return dict(item["row"]), item["payload"]

    async def send(self, actor, op):
        self.send_calls.append((actor, op))
        self.operations[op]["row"]["status"] = self.result


class FakeBot:
    def __init__(self, error=None):
        self.error = error
        self.edits = []

    async def edit_message_caption(self, **kwargs):
        self.edits.append(kwargs)
        if self.error:
            raise self.error


class PortalSignalWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name), schema="smh_test")
        self.config = SimpleNamespace(
            admin=9001,
            signals=-1009002,
            analysis=-1009003,
            allow_publishing=True,
            isolated_test=True,
        )
        self.publisher = FakePublisher()
        self.bot = FakeBot()
        self.db.execute(
            "INSERT INTO portal_users"
            "(id,email,display_name,password_hash,role,active,must_change_password,created,updated) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("owner-1", "owner@example.test", "Test Owner", "test-hash", "admin", 1, 0, now(), now()),
        )

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    def create_command(self, action, values, status="queued", actor="owner-1"):
        command_id = uid()
        self.db.execute(
            "INSERT INTO portal_signal_commands"
            "(id,actor_staff_id,action,input_json,request_id,command_status,created,updated) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (command_id, actor, action, json.dumps(values), uid(), status, now(), now()),
        )
        return command_id

    def create_setup(self, confirmed=True):
        setup_id = uid()
        setup = {
            "id": setup_id,
            "market": "XAUUSD",
            "zone": "4150.00–4155.00",
            "timeframe": "M15",
            "condition": "M15 bullish candle close",
            "expires": time.time() + 3600,
            "status": "active",
            "created": now(),
            "setup_message_id": 771,
            "image": "image-ref",
        }
        if confirmed:
            setup["confirmation"] = "M15 bullish candle close observed"
        with self.db.transaction() as cursor:
            save_in(cursor, setup)
        return setup

    @staticmethod
    def signal_input(setup, direction):
        buy = direction == "BUY"
        return {
            "setup_id": setup["id"],
            "direction": direction,
            "entry_range": "4151-4154",
            "stop_loss": "4140" if buy else "4160",
            "take_profits": "4160, 4170" if buy else "4140, 4130",
        }

    async def test_site_zone_draft_waits_for_chart_in_private_bot(self):
        command_id = self.create_command(
            "create_zone_draft",
            {
                "market": "XAUUSD",
                "low": "4150",
                "high": "4155",
                "timeframe": "M15",
                "minutes": "60",
                "condition": "M15 bullish candle close",
            },
        )

        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        draft = self.db.draft(self.config.admin)
        self.assertEqual(draft["kind"], "zone")
        self.assertEqual(draft["step"], "chart")
        self.assertEqual(draft["setup"]["zone"], "4150–4155")
        self.assertIsNone(draft["setup"]["expires"])
        self.assertIsNone(draft.get("image"))
        self.assertEqual(self.publisher.prepare_calls, [])
        self.assertEqual(self.publisher.send_calls, [])
        row = self.db.rows(
            "SELECT command_status FROM portal_signal_commands WHERE id=?", (command_id,))
        self.assertEqual(row[0]["command_status"], "completed")
        self.assertFalse(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        self.assertEqual(self.publisher.send_calls, [])

    async def test_signal_preview_is_private_destination_and_sends_only_after_approval(self):
        setup = self.create_setup()
        command_id = self.create_command(
            "publish_signal", self.signal_input(setup, "BUY"))

        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        row = self.db.rows(
            "SELECT command_status,preview_text,safe_result FROM portal_signal_commands WHERE id=?",
            (command_id,),
        )[0]
        self.assertEqual(row["command_status"], "preview_ready")
        self.assertIn("BUY NOW", row["preview_text"])
        self.assertIn("<b>🟢 BUY NOW</b>", row["preview_text"])
        self.assertIn("Entry range: 4151–4154", row["safe_result"])
        self.assertIn("Stop Loss: 4140", row["safe_result"])
        self.assertIn("Take Profit: 4160, 4170", row["safe_result"])
        self.assertNotIn(setup["id"], row["preview_text"])
        self.assertEqual(self.publisher.prepare_calls[0][2]["destination"], "signals")
        self.assertEqual(self.publisher.send_calls, [])

        self.db.execute(
            "UPDATE portal_signal_commands SET command_status='approved' WHERE id=?", (command_id,))
        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "approved"))
        self.assertEqual(len(self.publisher.send_calls), 1)
        self.assertEqual(self.publisher.operations[self.publisher.send_calls[0][1]]["row"]["status"], "done")
        self.assertTrue(self.bot.edits)
        self.assertEqual(self.bot.edits[0]["chat_id"], self.config.signals)

    async def test_signal_without_recorded_confirmation_is_rejected(self):
        setup = self.create_setup(confirmed=False)
        command_id = self.create_command(
            "publish_signal", {"setup_id": setup["id"], "direction": "SELL"})

        self.assertFalse(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        row = self.db.rows(
            "SELECT command_status,safe_result FROM portal_signal_commands WHERE id=?",
            (command_id,),
        )[0]
        self.assertEqual(row["command_status"], "failed")
        self.assertIn("Record the confirmation", row["safe_result"])
        self.assertEqual(self.publisher.send_calls, [])

    async def test_signal_without_entry_stop_or_target_is_rejected_before_prepare(self):
        setup = self.create_setup()
        command_id = self.create_command(
            "publish_signal", {"setup_id": setup["id"], "direction": "BUY"})

        self.assertFalse(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        row = self.db.rows(
            "SELECT command_status,safe_result FROM portal_signal_commands WHERE id=?",
            (command_id,),
        )[0]
        self.assertEqual(row["command_status"], "failed")
        self.assertIn("Entry range", row["safe_result"])
        self.assertEqual(self.publisher.prepare_calls, [])
        self.assertEqual(self.publisher.send_calls, [])

    async def test_used_and_expired_setups_cannot_prepare_new_signals(self):
        for status, expired in (("used", False), ("active", True)):
            with self.subTest(status=status, expired=expired):
                setup = self.create_setup(confirmed=True)
                if status == "used":
                    setup["status"] = "used"
                if expired:
                    setup["expires"] = time.time() - 1
                with self.db.transaction() as cursor:
                    save_in(cursor, setup)
                command_id = self.create_command(
                    "publish_signal", self.signal_input(setup, "BUY"))

                self.assertFalse(await process_signal_command(
                    self.db, self.publisher, self.config, self.bot, command_id, "queued"))
                self.assertEqual(self.db.rows(
                    "SELECT command_status FROM portal_signal_commands WHERE id=?", (command_id,)
                )[0]["command_status"], "failed")
                self.assertEqual(self.publisher.send_calls, [])

    async def test_analysis_preview_and_send_use_analysis_destination_only(self):
        command_id = self.create_command(
            "publish_analysis",
            {"text": "Educational review: higher highs have formed on the recent structure."},
        )
        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        self.assertEqual(self.publisher.prepare_calls[0][2]["destination"], "analysis")
        self.assertNotIn("signals", self.publisher.prepare_calls[0][2]["destination"])
        self.assertEqual(self.publisher.send_calls, [])

        self.db.execute(
            "UPDATE portal_signal_commands SET command_status='approved' WHERE id=?", (command_id,))
        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "approved"))
        self.assertEqual(len(self.publisher.send_calls), 1)
        self.assertFalse(self.bot.edits)

    async def test_confirmation_only_edits_after_explicit_review(self):
        setup = self.create_setup(confirmed=False)
        command_id = self.create_command(
            "record_confirmation",
            {"setup_id": setup["id"], "confirmation": "Observed M15 bullish close"},
        )

        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        self.assertEqual(self.db.rows(
            "SELECT command_status FROM portal_signal_commands WHERE id=?", (command_id,)
        )[0]["command_status"], "preview_ready")
        self.assertEqual(self.bot.edits, [])
        self.assertIsNone(self.db.get("active_setup").get("confirmation"))

        self.db.execute(
            "UPDATE portal_signal_commands SET command_status='approved' WHERE id=?", (command_id,))
        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "approved"))
        self.assertEqual(len(self.bot.edits), 1)
        self.assertEqual(self.bot.edits[0]["message_id"], setup["setup_message_id"])
        self.assertEqual(
            self.db.get("active_setup")["confirmation"],
            "Observed M15 bullish close",
        )
        self.assertEqual(self.publisher.send_calls, [])

    async def test_manual_expiry_waits_for_review_then_updates_zone_post(self):
        setup = self.create_setup()
        command_id = self.create_command("expire_setup", {"setup_id": setup["id"]})

        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        row = self.db.rows(
            "SELECT command_status,preview_text FROM portal_signal_commands WHERE id=?",
            (command_id,),
        )[0]
        self.assertEqual(row["command_status"], "preview_ready")
        self.assertIn("Expired", row["preview_text"])
        self.assertEqual(self.bot.edits, [])

        self.db.execute(
            "UPDATE portal_signal_commands SET command_status='approved' WHERE id=?", (command_id,))
        self.assertTrue(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "approved"))
        expired = self.db.get("setup:" + setup["id"])
        self.assertEqual(expired["status"], "expired")
        self.assertIsNone(expired["expires"])
        self.assertIn("<b>Expired</b>", self.bot.edits[-1]["caption"])
        self.assertEqual(self.publisher.send_calls, [])

    async def test_uncertain_send_is_quarantined_and_never_blindly_retried(self):
        setup = self.create_setup()
        command_id = self.create_command(
            "publish_signal", self.signal_input(setup, "SELL"))
        await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued")
        self.db.execute(
            "UPDATE portal_signal_commands SET command_status='approved' WHERE id=?", (command_id,))
        self.publisher.result = "uncertain"

        self.assertFalse(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "approved"))
        self.assertEqual(self.db.rows(
            "SELECT command_status FROM portal_signal_commands WHERE id=?", (command_id,)
        )[0]["command_status"], "uncertain")
        await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "uncertain")
        self.assertEqual(len(self.publisher.send_calls), 1)

    async def test_zone_edit_network_error_becomes_uncertain(self):
        setup = self.create_setup(confirmed=False)
        command_id = self.create_command(
            "cancel_setup", {"setup_id": setup["id"]})
        await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued")
        self.db.execute(
            "UPDATE portal_signal_commands SET command_status='approved' WHERE id=?", (command_id,))
        self.bot.error = TimeoutError("simulated network timeout")

        self.assertFalse(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "approved"))
        self.assertEqual(self.db.rows(
            "SELECT command_status FROM portal_signal_commands WHERE id=?", (command_id,)
        )[0]["command_status"], "uncertain")
        self.assertEqual(len(self.bot.edits), 1)

    async def test_interrupted_command_recovers_as_uncertain(self):
        command_id = self.create_command("publish_analysis", {"text": "Market structure."}, "processing")
        recover_interrupted_commands(self.db)
        self.assertEqual(self.db.rows(
            "SELECT command_status FROM portal_signal_commands WHERE id=?", (command_id,)
        )[0]["command_status"], "uncertain")

    async def test_inactive_staff_cannot_publish(self):
        command_id = self.create_command(
            "publish_analysis", {"text": "Market structure."}, actor="disabled-owner")
        self.db.execute(
            "INSERT INTO portal_users"
            "(id,email,display_name,password_hash,role,active,must_change_password,created,updated) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("disabled-owner", "disabled@example.test", "Disabled", "test-hash", "admin", 0, 0, now(), now()),
        )
        self.assertFalse(await process_signal_command(
            self.db, self.publisher, self.config, self.bot, command_id, "queued"))
        self.assertEqual(self.db.rows(
            "SELECT command_status FROM portal_signal_commands WHERE id=?", (command_id,)
        )[0]["command_status"], "failed")
        self.assertEqual(self.publisher.send_calls, [])

    async def test_non_test_instance_does_not_start_signal_worker(self):
        self.config.isolated_test = False
        stop = asyncio.Event()
        await run_portal_signal_command_worker(
            self.db, self.publisher, self.config, self.bot, stop)
        status = self.db.get("portal_signal_worker_status")
        self.assertEqual(status["status"], "disabled")
        self.assertEqual(self.publisher.send_calls, [])


if __name__ == "__main__":
    unittest.main()
