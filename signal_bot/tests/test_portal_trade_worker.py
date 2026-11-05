import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from smh.database import Database, now
from smh.portal_trade_worker import (
    _build_preview,
    process_trade_command,
    recover_interrupted_commands,
)
from smh.publishing import Publisher


class FakeConfig:
    def __init__(self):
        self.admin = 42
        self.signals = -1001001
        self.analysis = -1001002
        self.allow_publishing = True
        self.isolated_test = False
        self.ready = True

    def authorize(self, actor):
        if actor != self.admin:
            raise PermissionError("Administrator only.")

    def destination(self, _kind, destination=None):
        if destination == "signals":
            return self.signals
        if destination == "analysis":
            return self.analysis
        raise ValueError("Unknown test destination.")


class PortalTradeWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "data")
        self.config = FakeConfig()
        self.bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=9001)))
        self.publisher = Publisher(self.db, self.config, self.bot)
        stamp = now()
        self.db.execute(
            "INSERT INTO portal_users "
            "(id,email,display_name,password_hash,role,active,must_change_password,created,updated) "
            "VALUES ('owner-1','owner@example.test','Test Owner','not-a-password','admin',1,0,?,?)",
            (stamp, stamp),
        )
        self.add_trade()

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    def add_trade(self, *, entered=True, trade_id="trade-internal-123"):
        stamp = now()
        data = {
            "id": trade_id,
            "symbol": "XAUUSD",
            "direction": "BUY",
            "state": "CONFIRMED_BUY",
            "entry": "100.00" if entered else "",
            "sl": "95.00",
            "targets": {"1": {"price": "110.00", "hit": False}},
            "message_id": 8123 if entered else None,
            "setup_message_id": None if entered else 7123,
            "version": 0,
        }
        self.db.execute(
            "INSERT INTO trades(id,data,state,created,updated,version) VALUES(?,?,?,?,?,0)",
            (trade_id, json.dumps(data), data["state"], stamp, stamp),
        )
        return trade_id

    def add_command(self, action, values, *, trade_id="trade-internal-123",
                    command_id="command-1", request_id="request-1234567890"):
        stamp = now()
        self.db.execute(
            "INSERT INTO portal_trade_commands "
            "(id,trade_id,actor_staff_id,action,input_json,expected_version,request_id,"
            "command_status,created,updated) VALUES(?,?,?,?,?,0,?,'queued',?,?)",
            (command_id, trade_id, "owner-1", action, json.dumps(values), request_id, stamp, stamp),
        )
        return command_id

    async def prepare(self, command_id="command-1"):
        return await process_trade_command(self.db, self.publisher, self.config, command_id, "queued")

    async def test_review_preview_is_local_only_and_does_not_send(self):
        self.add_command("sl_tp", {
            "stop_loss": "98.00",
            "target_number": "2",
            "target_price": "115.00",
        })

        self.assertTrue(await self.prepare())
        command = self.db.rows("SELECT * FROM portal_trade_commands WHERE id='command-1'")[0]
        self.assertEqual(command["command_status"], "preview_ready")
        self.assertIn("98.00", command["preview_text"])
        self.assertIn("TP2: 115.00", command["preview_text"])
        self.assertNotIn("trade-internal-123", command["preview_text"])
        self.assertNotIn("8123", command["preview_text"])
        self.bot.send_message.assert_not_awaited()
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM portal_trade_command_events")[0]["n"], 2)

    async def test_approved_update_replies_to_original_signal_and_saves_changed_trade(self):
        self.add_command("sl_tp", {
            "stop_loss": "98.00",
            "target_number": "2",
            "target_price": "115.00",
        })
        await self.prepare()
        self.db.execute(
            "UPDATE portal_trade_commands SET command_status='approved',updated=? WHERE id='command-1'",
            (now(),),
        )

        self.assertTrue(await process_trade_command(
            self.db, self.publisher, self.config, "command-1", "approved",
        ))
        self.bot.send_message.assert_awaited_once()
        args, kwargs = self.bot.send_message.await_args
        self.assertEqual(args[0], -1001001)
        self.assertNotEqual(args[0], -1001002)
        self.assertEqual(kwargs["reply_parameters"].message_id, 8123)
        self.assertNotIn("trade-internal-123", args[1])
        self.assertNotIn("847291", args[1])
        saved = self.db.trade("trade-internal-123")
        self.assertEqual(saved["sl"], "98.00")
        self.assertEqual(saved["targets"]["2"]["price"], "115.00")
        self.assertEqual(saved["version"], 1)
        self.assertEqual(
            self.db.rows("SELECT command_status FROM portal_trade_commands")[0]["command_status"],
            "completed",
        )

    async def test_pre_entry_update_replies_to_original_setup_zone(self):
        trade_id = self.add_trade(entered=False, trade_id="pre-entry-trade")
        self.add_command(
            "custom",
            {"text": "The setup is still awaiting the required confirmation."},
            trade_id=trade_id,
        )
        await self.prepare()
        self.db.execute(
            "UPDATE portal_trade_commands SET command_status='approved',updated=? WHERE id='command-1'",
            (now(),),
        )

        self.assertTrue(await process_trade_command(
            self.db, self.publisher, self.config, "command-1", "approved",
        ))

        _args, kwargs = self.bot.send_message.await_args
        self.assertEqual(kwargs["reply_parameters"].message_id, 7123)

    async def test_duplicate_approval_tap_does_not_send_twice(self):
        self.add_command("sl", {"stop_loss": "97.50"})
        await self.prepare()
        self.db.execute(
            "UPDATE portal_trade_commands SET command_status='approved',updated=? WHERE id='command-1'",
            (now(),),
        )
        self.assertTrue(await process_trade_command(
            self.db, self.publisher, self.config, "command-1", "approved",
        ))
        self.assertFalse(await process_trade_command(
            self.db, self.publisher, self.config, "command-1", "approved",
        ))
        self.bot.send_message.assert_awaited_once()

    async def test_uncertain_telegram_send_is_quarantined_and_never_replayed(self):
        self.add_command("sl", {"stop_loss": "97.50"})
        await self.prepare()
        self.db.execute(
            "UPDATE portal_trade_commands SET command_status='approved',updated=? WHERE id='command-1'",
            (now(),),
        )
        self.bot.send_message.side_effect = TimeoutError("synthetic private test timeout")

        self.assertFalse(await process_trade_command(
            self.db, self.publisher, self.config, "command-1", "approved",
        ))
        self.assertFalse(await process_trade_command(
            self.db, self.publisher, self.config, "command-1", "approved",
        ))
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(
            self.db.rows("SELECT command_status FROM portal_trade_commands")[0]["command_status"],
            "uncertain",
        )
        self.assertEqual(
            self.db.rows("SELECT status FROM operations")[0]["status"],
            "uncertain",
        )

    async def test_restart_recovery_marks_interrupted_action_uncertain(self):
        self.add_command("sl", {"stop_loss": "97.50"})
        self.db.execute(
            "UPDATE portal_trade_commands SET command_status='processing' WHERE id='command-1'",
        )

        recover_interrupted_commands(self.db)

        row = self.db.rows("SELECT command_status,safe_result FROM portal_trade_commands")[0]
        self.assertEqual(row["command_status"], "uncertain")
        self.assertIn("No automatic retry", row["safe_result"])
        self.assertEqual(
            self.db.rows(
                "SELECT event_type FROM portal_trade_command_events WHERE command_id='command-1' "
                "ORDER BY created DESC LIMIT 1",
            )[0]["event_type"],
            "uncertain",
        )
        self.bot.send_message.assert_not_awaited()

    async def test_non_admin_or_inactive_owner_cannot_process_command(self):
        self.add_command("sl", {"stop_loss": "97.50"})
        self.db.execute("UPDATE portal_users SET role='agent' WHERE id='owner-1'")

        self.assertFalse(await self.prepare())
        self.assertEqual(
            self.db.rows("SELECT command_status FROM portal_trade_commands")[0]["command_status"],
            "failed",
        )
        self.bot.send_message.assert_not_awaited()

    async def test_missing_values_fail_without_sending(self):
        self.add_command("sl_tp", {"target_number": "1", "target_price": "110.00"})

        self.assertFalse(await self.prepare())

        row = self.db.rows("SELECT command_status,safe_result FROM portal_trade_commands")[0]
        self.assertEqual(row["command_status"], "failed")
        self.assertIn("stop loss", row["safe_result"].lower())
        self.bot.send_message.assert_not_awaited()

    async def test_stale_trade_version_invalidates_queued_preview(self):
        self.add_command("sl", {"stop_loss": "97.50"})
        self.db.execute("UPDATE trades SET version=version+1 WHERE id='trade-internal-123'")

        self.assertFalse(await self.prepare())
        self.assertEqual(
            self.db.rows("SELECT command_status FROM portal_trade_commands")[0]["command_status"],
            "stale",
        )
        self.bot.send_message.assert_not_awaited()

    async def test_cancel_and_invalidation_are_distinct_and_require_the_right_entry_state(self):
        unentered_id = self.add_trade(entered=False, trade_id="unentered-trade")
        unentered = self.db.trade(unentered_id)
        _changed, cancel_text = _build_preview(unentered, "cancel", {"reason": "Zone no longer valid"})
        self.assertIn("Unentered Setup Cancelled", cancel_text)
        with self.assertRaisesRegex(ValueError, "Cancel Setup"):
            _build_preview(unentered, "invalidate", {"reason": "Zone no longer valid"})

        entered = self.db.trade("trade-internal-123")
        changed, invalidate_text = _build_preview(
            entered, "invalidate", {"reason": "Structure invalidated"},
        )
        self.assertEqual(changed["state"], "INVALIDATED")
        self.assertIn("Trade Invalidated", invalidate_text)
        with self.assertRaisesRegex(ValueError, "Invalidate Trade"):
            _build_preview(entered, "cancel", {"reason": "Structure invalidated"})

    async def test_breakeven_requires_explicit_stop_moved_confirmation(self):
        trade = self.db.trade("trade-internal-123")
        with self.assertRaisesRegex(ValueError, "actually moved"):
            _build_preview(trade, "be", {"stop_moved": False})
        changed, preview = _build_preview(trade, "be", {"stop_moved": True})
        self.assertEqual(changed["sl"], "100.00")
        self.assertIn("Stop Loss Moved to Breakeven", preview)


if __name__ == "__main__":
    unittest.main()
