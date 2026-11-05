"""Isolated result-post workflow tests; all Telegram calls are mocked."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from PIL import Image

from smh.config import Config
from smh.database import Database
from smh.handlers import Handlers
from smh.health import Health
from smh.publishing import Publisher
from smh.signal_results import (
    default_result_caption,
    telegram_message_link,
    validate_result_caption,
)


class SignalResultFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name)
        config = Config(
            "123456789:TEST_TOKEN_NOT_REAL", 42, -1001, -1002, Path(self.temp.name))
        self.config = replace(config, allow_publishing=True)
        self.bot = NS(
            send_message=AsyncMock(return_value=NS(message_id=123)),
            send_photo=AsyncMock(return_value=NS(message_id=124)),
            send_document=AsyncMock(return_value=NS(message_id=125)),
            edit_message_text=AsyncMock(return_value=NS(message_id=123)),
            edit_message_caption=AsyncMock(return_value=NS(message_id=124)),
            get_me=AsyncMock(return_value=NS(id=999)),
            get_chat_member=AsyncMock(return_value=NS(status="administrator")),
        )
        self.publisher = Publisher(self.db, self.config, self.bot)
        self.publisher.verified = True
        self.ui = Handlers(
            self.db, self.config, self.bot, self.publisher,
            Health(self.db, self.config, self.bot),
        )
        self.update = NS(
            effective_user=NS(id=42),
            effective_chat=NS(id=42, type="private"),
            message=NS(text="", forward_origin=None, caption=None, photo=[], document=None),
            callback_query=NS(answer=AsyncMock()),
        )

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    async def click(self, action, payload=None):
        self.update.callback_query.data = self.db.button(42, action, payload)
        return await self.ui.callback(self.update, None)

    async def text(self, value):
        self.update.message.text = value
        return await self.ui.text(self.update, None)

    async def create_signal(self):
        from smh.zones import activate, parse_zone
        from smh import zones

        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        setup["confirmation"] = "Observed test confirmation"
        setup["setup_message_id"] = 700
        activate(self.db, setup, None)
        levels = zones.validate_signal_levels(setup, "BUY", "2653", "2640", "2670, 2680")
        payload = zones.signal_payload(setup, "BUY", 42, levels=levels)
        operation = self.publisher.prepare(42, "signal", payload)
        await self.publisher.send(42, operation)
        trade_id = payload["trade"]["id"]
        result_record, _ = self.db.create_signal_result(trade_id, 42)
        operation_row, _ = self.publisher.operation(operation)
        self.db.update_signal_result(
            trade_id,
            {"signal_message_id": operation_row["message_id"],
             "zone_message_id": setup["setup_message_id"],
             "signal_text": payload["text"]},
            expected_statuses=(result_record["status"],),
        )
        await self.ui.trade_screen(self.update, trade_id)
        return trade_id

    async def attach_result_image(self, trade_id):
        record = self.db.signal_result(trade_id)
        await self.click("signal_result_attach", {
            "trade_id": trade_id, "updated": record["updated"]})

        async def download_to_drive(path):
            Image.new("RGB", (96, 72), "#27634a").save(path, format="PNG")

        item = NS(
            file_size=500,
            mime_type="image/png",
            get_file=AsyncMock(return_value=NS(download_to_drive=AsyncMock(
                side_effect=download_to_drive))),
        )
        self.update.message.photo = [item]
        await self.ui.photo(self.update, None)
        self.update.message.photo = []

    async def set_profit_result(self, trade_id):
        record = self.db.signal_result(trade_id)
        await self.click("signal_result_outcome", {
            "trade_id": trade_id, "updated": record["updated"], "outcome": "profit"})

    async def test_published_signal_creates_private_pending_result_controls_only(self):
        trade_id = await self.create_signal()
        trade = self.db.trade(trade_id)
        result = self.db.signal_result(trade_id)

        self.assertEqual(trade["state"], "CONFIRMED_BUY")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["signal_message_id"], trade["message_id"])
        self.assertEqual(result["zone_message_id"], trade["setup_message_id"])
        self.assertEqual(result["outcome"], "")
        self.assertEqual(result["profit_image"], "")
        analysis_sends = [
            call for call in self.bot.send_message.await_args_list
            if call.args[0] == self.config.analysis
        ]
        analysis_photos = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == self.config.analysis
        ]
        self.assertEqual(analysis_sends, [])
        self.assertEqual(analysis_photos, [])
        latest = self.bot.send_message.await_args_list[-1]
        labels = [
            button.text for row in latest.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("📸 Capture Signal Screenshot", labels)
        self.assertIn("📤 Post Result to Market Analysis Group", labels)

    async def test_capture_and_uploaded_result_image_are_private_and_persist(self):
        trade_id = await self.create_signal()
        record = self.db.signal_result(trade_id)
        await self.ui.signal_result_capture(self.update, trade_id, record["updated"])
        record = self.db.signal_result(trade_id)
        self.assertTrue(record["signal_capture"].startswith("asset:"))
        self.assertEqual(self.bot.send_photo.await_args.args[0], 42)
        self.assertTrue(Path(self.db.image_path(record["signal_capture"])).is_file())

        await self.attach_result_image(trade_id)
        record = self.db.signal_result(trade_id)
        self.assertTrue(record["profit_image"].startswith("asset:"))
        self.assertEqual(record["status"], "pending")
        self.assertEqual(self.db.draft(42), None)
        self.assertFalse(any(
            call.args[0] == self.config.analysis
            for call in self.bot.send_photo.await_args_list
        ))

    async def test_confirmed_result_preview_and_analysis_post_are_separate_and_idempotent(self):
        trade_id = await self.create_signal()
        await self.attach_result_image(trade_id)
        await self.set_profit_result(trade_id)
        record = self.db.signal_result(trade_id)
        self.assertEqual(record["status"], "ready")

        await self.ui.signal_result_preview(self.update, trade_id, record["updated"])
        self.assertFalse(any(
            call.args[0] == self.config.analysis
            for call in self.bot.send_photo.await_args_list
        ))
        preview_message = self.bot.send_message.await_args_list[-1]
        self.assertIn("Result: Profit", preview_message.args[1])
        self.assertIn("PREVIEW — NOT PUBLISHED", preview_message.args[1])

        record = self.db.signal_result(trade_id)
        await self.ui.signal_result_confirm_screen(self.update, trade_id, record["updated"])
        final_preview = self.bot.send_message.await_args_list[-1]
        self.assertIn("FINAL CONFIRMATION", final_preview.args[1])
        self.assertIn("✅ Confirm & Publish to Market Analysis Group", [
            button.text for row in final_preview.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])

        record = self.db.signal_result(trade_id)
        await self.ui.signal_result_publish_confirm(
            self.update, trade_id, record["updated"])
        posted = self.db.signal_result(trade_id)
        self.assertEqual(posted["status"], "posted")
        self.assertIsNotNone(posted["analysis_message_id"])
        analysis_posts = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == self.config.analysis
        ]
        self.assertEqual(len(analysis_posts), 1)
        self.assertFalse(any(
            call.args[0] == self.config.signals for call in analysis_posts
        ))
        _operation, payload = self.publisher.operation(posted["operation_id"])
        self.assertEqual(payload["channel"], self.config.analysis)
        self.assertNotIn(trade_id, payload["text"])
        self.assertNotIn(str(posted["signal_message_id"]), payload["text"])
        self.assertNotIn(str(posted["zone_message_id"]), payload["text"])

        await self.ui.signal_result_publish_confirm(
            self.update, trade_id, posted["updated"])
        self.assertEqual(len([
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == self.config.analysis
        ]), 1)

    async def test_caption_edit_cancel_and_pending_result_reopen_do_not_post(self):
        trade_id = await self.create_signal()
        await self.attach_result_image(trade_id)
        await self.set_profit_result(trade_id)
        record = self.db.signal_result(trade_id)
        await self.click("signal_result_edit_caption", {
            "trade_id": trade_id, "updated": record["updated"]})
        custom_caption = default_result_caption("BUY", "profit").replace(
            "SMART MONEY HUB — TRADE UPDATE", "MARKET ANALYSIS — TRADE UPDATE")
        await self.text(custom_caption)

        edited = self.db.signal_result(trade_id)
        self.assertEqual(edited["caption"], custom_caption)
        self.assertEqual(edited["status"], "ready")
        await self.ui.signal_result_preview(self.update, trade_id, edited["updated"])
        preview_buttons = [
            button.text for row in self.bot.send_message.await_args_list[-1].kwargs[
                "reply_markup"].inline_keyboard for button in row
        ]
        self.assertIn("❌ Cancel", preview_buttons)
        await self.ui.signal_result_cancel(self.update, trade_id, edited["updated"])
        self.assertEqual(self.db.signal_result(trade_id)["status"], "ready")
        self.assertFalse(any(
            call.args[0] == self.config.analysis
            for call in self.bot.send_photo.await_args_list
        ))

    async def test_publishing_off_blocks_result_before_channel_operation(self):
        trade_id = await self.create_signal()
        await self.attach_result_image(trade_id)
        await self.set_profit_result(trade_id)
        disabled = replace(self.config, allow_publishing=False)
        self.config = disabled
        self.publisher.config = disabled
        self.ui.config = disabled
        self.publisher.send = AsyncMock(side_effect=AssertionError("must not send"))
        self.publisher.prepare = Mock(side_effect=AssertionError("must not prepare"))
        record = self.db.signal_result(trade_id)

        await self.ui.signal_result_publish_confirm(
            self.update, trade_id, record["updated"])
        self.publisher.send.assert_not_awaited()
        self.publisher.prepare.assert_not_called()
        self.assertEqual(self.db.signal_result(trade_id)["status"], "ready")
        self.assertFalse(any(
            call.args[0] == self.config.analysis
            for call in self.bot.send_photo.await_args_list
        ))

    async def test_save_for_later_and_database_reopen_preserve_result_and_images(self):
        trade_id = await self.create_signal()
        await self.attach_result_image(trade_id)
        await self.set_profit_result(trade_id)
        record = self.db.signal_result(trade_id)
        await self.ui.signal_result_save(self.update, trade_id, record["updated"])
        saved = self.db.signal_result(trade_id)
        self.assertEqual(saved["status"], "ready")
        self.assertEqual(saved["outcome"], "profit")
        self.assertTrue(saved["profit_image"].startswith("asset:"))
        self.assertFalse(any(
            call.args[0] == self.config.analysis
            for call in self.bot.send_photo.await_args_list
        ))
        await self.ui.signal_results_list(self.update)
        result_list = self.bot.send_message.await_args_list[-1]
        self.assertIn("Open a saved result", result_list.args[1])
        self.assertTrue(any(
            "Gold/XAUUSD" in button.text
            for row in result_list.kwargs["reply_markup"].inline_keyboard
            for button in row
        ))
        await self.click("signal_result_open", {"trade_id": trade_id})
        self.assertIn("Screenshot and result are saved", self.bot.send_message.await_args_list[-1].args[1])

        db_dir = self.temp.name
        self.db.conn.close()
        reopened = Database(db_dir)
        try:
            restored = reopened.signal_result(trade_id)
            self.assertEqual(restored["caption"], saved["caption"])
            self.assertEqual(restored["profit_image"], saved["profit_image"])
            self.assertTrue(Path(reopened.image_path(restored["profit_image"])).is_file())
        finally:
            reopened.conn.close()
            self.db = Database(db_dir)
            self.publisher.db = self.db
            self.ui.db = self.db

    async def test_missing_screenshot_result_and_stale_controls_are_rejected(self):
        trade_id = await self.create_signal()
        record = self.db.signal_result(trade_id)
        await self.ui.signal_result_confirm_screen(self.update, trade_id, record["updated"])
        self.assertEqual(self.db.signal_result(trade_id)["status"], "pending")
        await self.attach_result_image(trade_id)
        record = self.db.signal_result(trade_id)
        stale = record["updated"]
        await self.set_profit_result(trade_id)
        with self.assertRaisesRegex(ValueError, "changed"):
            await self.ui.signal_result_preview(self.update, trade_id, stale)

    async def test_caption_must_match_confirmed_direction_and_result_and_remain_educational(self):
        caption = default_result_caption("BUY", "profit")
        self.assertEqual(validate_result_caption(caption, "BUY", "profit"), caption)
        with self.assertRaisesRegex(ValueError, "Result"):
            validate_result_caption(
                caption.replace("Result: Profit", "Result: Loss"), "BUY", "profit")
        with self.assertRaisesRegex(ValueError, "Direction"):
            validate_result_caption(caption, "SELL", "profit")
        with self.assertRaisesRegex(ValueError, "specific trade instruction"):
            validate_result_caption(
                caption + "\nBuy XAUUSD at 2653.", "BUY", "profit")

    async def test_only_admin_can_open_result_posts(self):
        trade_id = await self.create_signal()
        member = NS(
            effective_user=NS(id=77),
            effective_chat=NS(id=77, type="private"),
            message=NS(text="", forward_origin=None, caption=None),
            callback_query=NS(answer=AsyncMock()),
        )
        with self.assertRaises(PermissionError):
            await self.ui.signal_result_screen(member, trade_id)

    def test_message_link_requires_a_valid_private_channel_message(self):
        self.assertEqual(
            telegram_message_link(-1001234567890, 55),
            "https://t.me/c/1234567890/55",
        )
        self.assertIsNone(telegram_message_link(-1001, 55))
        self.assertIsNone(telegram_message_link(-1001234567890, None))


if __name__ == "__main__":
    unittest.main()
