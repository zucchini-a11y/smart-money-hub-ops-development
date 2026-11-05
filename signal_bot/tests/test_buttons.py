"""Offline handler-level checks: no live channel messages are sent by these tests."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import ANY, AsyncMock, patch
from PIL import Image
from smh.config import Config
from smh.database import Database
from smh.handlers import Handlers
from smh.health import Health
from smh.publishing import Publisher


class ButtonFlows(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name)
        self.config = Config("123456789:TEST_TOKEN_NOT_REAL", 42, -1001, -1002, Path(self.temp.name))
        self.bot = NS(send_message=AsyncMock(return_value=NS(message_id=123)),
                      send_photo=AsyncMock(return_value=NS(message_id=124)),
                      send_document=AsyncMock(), edit_message_text=AsyncMock(return_value=NS(message_id=123)),
                      edit_message_caption=AsyncMock(return_value=NS(message_id=124)),
                      get_me=AsyncMock(return_value=NS(id=999)),
                      get_chat_member=AsyncMock(return_value=NS(status="member")),
                      create_chat_invite_link=AsyncMock(return_value=NS(invite_link="https://t.me/+test")))
        self.pub = Publisher(self.db, self.config, self.bot)
        self.pub.verified = True
        from dataclasses import replace
        self.config = replace(self.config, allow_publishing=True)
        self.pub.config = self.config
        self.ui = Handlers(self.db, self.config, self.bot, self.pub, Health(self.db, self.config, self.bot))
        self.u = NS(effective_user=NS(id=42), effective_chat=NS(id=42, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    async def click(self, action, payload=None):
        self.u.callback_query.data = self.db.button(42, action, payload)
        await self.ui.callback(self.u, None)

    async def test_stale_callback_diagnostic_is_redacted(self):
        opaque_callback = "private-callback-payload"
        self.u.callback_query.data = opaque_callback
        with self.assertLogs("smh", level="WARNING") as captured:
            with self.assertRaises(ValueError):
                await self.ui.callback(self.u, None)
        output = "\n".join(captured.output)
        self.assertIn("callback_rejected:invalid_or_stale", output)
        self.assertNotIn(opaque_callback, output)
        self.assertNotIn("42", output)

    async def test_say_adds_telegram_bold_entities_without_changing_template_text(self):
        text = "📬 SUPPORT REQUEST\nStatus: Open\nA team member will respond soon."
        await self.ui.say(self.u, text, admin_chrome=False)
        sent = self.bot.send_message.await_args_list[-1]
        self.assertEqual(sent.args[1], text)
        self.assertEqual(sent.kwargs["parse_mode"], None)
        entities = sent.kwargs["entities"]
        self.assertEqual([entity.type for entity in entities], ["bold", "bold"])
        heading_length = len(text.splitlines()[0].encode("utf-16-le")) // 2
        self.assertEqual((entities[0].offset, entities[0].length), (0, heading_length))
        status_start = len(text[:text.index("Status")].encode("utf-16-le")) // 2
        self.assertEqual((entities[1].offset, entities[1].length),
                         (status_start, len("Status")))

    async def test_direct_telegram_messages_and_captions_get_native_emphasis(self):
        from smh.telegram_style import styled_call_arguments

        class PlainBot:
            def __init__(self):
                self.calls = []

            async def send_message(self, chat_id, text, parse_mode=None, entities=None):
                self.calls.append(("message", text, parse_mode, entities))

            async def send_photo(self, chat_id, photo, caption=None, parse_mode=None, caption_entities=None):
                self.calls.append(("photo", caption, parse_mode, caption_entities))

            async def edit_message_text(self, text, chat_id=None, message_id=None, parse_mode=None, entities=None):
                self.calls.append(("edit", text, parse_mode, entities))

        bot = PlainBot()
        for method_name, text_parameter, entities_parameter, args, kwargs in (
            ("send_message", "text", "entities", (42, "📩 SUPPORT UPDATE\nStatus: Received"), {}),
            ("send_photo", "caption", "caption_entities", (42, b"image"), {"caption": "📊 CHART REVIEW\nMarket: XAUUSD"}),
            ("edit_message_text", "text", "entities", ("✅ Review complete",), {"chat_id": 42, "message_id": 7}),
            ("send_message", "text", "entities", (42, "<b>Already formatted</b>"), {"parse_mode": "HTML"}),
        ):
            method = getattr(bot, method_name)
            styled_args, styled_kwargs = styled_call_arguments(
                method, args, kwargs, text_parameter, entities_parameter)
            await method(*styled_args, **styled_kwargs)

        self.assertEqual([len(call[3] or []) for call in bot.calls], [2, 2, 1, 0])
        self.assertEqual(bot.calls[0][1], "📩 SUPPORT UPDATE\nStatus: Received")
        self.assertEqual(bot.calls[1][1], "📊 CHART REVIEW\nMarket: XAUUSD")

    async def test_callback_failure_logs_safe_action_and_error_type_only(self):
        opaque_reference = "private-request-reference"
        self.u.callback_query.data = self.db.button(
            42, "member_pro_registration", {"request_id": opaque_reference})
        self.ui.member_action = AsyncMock(side_effect=ValueError("private raw detail"))
        with self.assertLogs("smh", level="INFO") as captured:
            with self.assertRaises(ValueError):
                await self.ui.callback(self.u, None)
        output = "\n".join(captured.output)
        self.assertIn("callback_action:member_pro_registration", output)
        self.assertIn("callback_action_error:member_pro_registration:ValueError", output)
        self.assertNotIn(opaque_reference, output)
        self.assertNotIn("private raw detail", output)
        self.assertNotIn("42", output)

    def mark_education_user_unjoined(self, user_id, group_id):
        async def membership(chat_id, member_id):
            if chat_id == group_id and member_id == user_id:
                return NS(status="left")
            return NS(status="administrator", can_post_messages=True,
                      can_edit_messages=True, can_invite_users=True)
        self.bot.get_chat_member.side_effect = membership

    def revision(self, **more):
        return {"revision": self.db.draft(42)["revision"], **more}

    def member_update(self, user_id):
        return NS(
            effective_user=NS(id=user_id, username=f"member{user_id}"),
            effective_chat=NS(id=user_id, type="private"),
            message=NS(text="", photo=[], document=None, forward_origin=None, caption=None),
            callback_query=NS(answer=AsyncMock()),
        )

    def add_pro_request(self, request_id, user_id, *, status="pending_review",
                        registration="verified", funding="not_submitted", evidence=None):
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,username,destination,answers,status,registration_status,funding_status,"
            "evidence_file_id,source,created,updated) "
            "VALUES (?,?,?,'pro','[]',?,?,?,?,?,'now','now')",
            (request_id, user_id, f"member{user_id}", status, registration, funding, evidence, "new"))

    async def text(self, text):
        self.u.message.text = text
        self.u.message.forward_origin = None
        await self.ui.text(self.u, None)

    async def upload_zone_chart(self):
        async def download(path):
            Image.new("RGB", (80, 60), "#486078").save(path, format="PNG")
        item = NS(file_size=400, get_file=AsyncMock(
            return_value=NS(download_to_drive=AsyncMock(side_effect=download))))
        self.u.message.photo = [item]
        self.u.message.document = None
        self.u.message.caption = None
        await self.ui.photo(self.u, None)
        self.u.message.photo = []

    async def forward_market_analysis(self, caption, source_channel=-1002, message_id=9876):
        async def download(path):
            Image.new("RGB", (160, 100), "#334455").save(path, format="PNG")
        item = NS(file_size=400, mime_type="image/jpeg", get_file=AsyncMock(
            return_value=NS(download_to_drive=AsyncMock(side_effect=download))))
        self.u.message = NS(
            text="", caption=caption, photo=[item], document=None,
            forward_origin=NS(
                type="channel",
                chat=NS(id=source_channel, type="channel", title="Market Analysis"),
                message_id=message_id,
            ),
        )
        self.u.effective_message = self.u.message
        await self.ui.photo(self.u, None)

    def assert_no_channel_posts(self):
        self.assertFalse(any(
            call.args[0] in (self.config.analysis, self.config.signals)
            for call in self.bot.send_photo.await_args_list
        ))
        self.assertFalse(any(
            call.args[0] in (self.config.analysis, self.config.signals)
            for call in self.bot.send_message.await_args_list
        ))

    @staticmethod
    def existing_poi_caption(buy_low="3,921.54", buy_high="3,965.00"):
        return (
            "📊 SMART MONEY HUB | MARKET ANALYSIS 🥇\n\n"
            "📍 MARKET: Gold Spot / U.S. Dollar (XAUUSD)\n"
            "⏱️ TIMEFRAME: 1h\n\n"
            "🎯 KEY AREAS OF INTEREST:\n"
            f"🩷 POI ZONE: Pink shaded box (approx. {buy_low} – {buy_high})\n\n"
            "⚠️ Confirmation has not yet been established.\n"
            "❌ NO CONFIRMATION, NO ENTRY."
        )

    async def test_forwarded_market_analysis_poi_previews_then_posts_only_to_pro_and_links_source(self):
        await self.click("pro_import_start")
        await self.forward_market_analysis(self.existing_poi_caption())

        draft = self.db.draft(42)
        self.assertEqual(draft["kind"], "pro_import")
        self.assertEqual(draft["source_channel"], self.config.analysis)
        self.assertEqual(draft["source_message_id"], 9876)
        self.assertEqual(len(draft["pro_zones"]), 1)
        self.assertEqual(
            draft["pro_zones"][0]["setup"]["market_analysis_message_id"], 9876)
        self.assertIn("will not be sent again", self.bot.send_message.await_args_list[-1].args[1])
        self.assert_no_channel_posts()
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])

        await self.click("pro_import_publish", self.revision())
        setup_posts = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == self.config.signals
        ]
        self.assertEqual(len(setup_posts), 1)
        self.assertFalse(any(
            call.args[0] == self.config.analysis for call in self.bot.send_photo.await_args_list))
        self.assertIn("ACTIVE SETUP ZONE", setup_posts[0].kwargs["caption"])
        self.assertNotIn("9876", setup_posts[0].kwargs["caption"])
        self.assertNotIn(str(self.config.analysis), setup_posts[0].kwargs["caption"])

        from smh import zones
        setups = zones.active_setups(self.db)
        self.assertEqual(len(setups), 1)
        self.assertEqual(setups[0]["market_analysis_message_id"], 9876)
        self.assertTrue(setups[0]["setup_message_id"])
        source_key = self.ui.pro_import_source_key(self.config.analysis, 9876)
        self.assertEqual(self.db.get(source_key)["status"], "done")

        await self.click("pro_import_start")
        await self.forward_market_analysis(self.existing_poi_caption())
        self.assertIn("already been processed", self.bot.send_message.await_args_list[-1].args[1])
        self.assertEqual(len([
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == self.config.signals
        ]), 1)

    async def test_zone_tapped_reuses_verified_forward_link_for_both_channel_replies(self):
        await self.click("pro_import_start")
        await self.forward_market_analysis(self.existing_poi_caption(), message_id=9883)
        await self.click("pro_import_publish", self.revision())

        from smh import zones
        setup = zones.active_setups(self.db)[0]
        # Simulate the already-active setup created before source-channel
        # metadata was added; its completed import marker is the verification.
        setup.pop("market_analysis_source_channel_id", None)
        setup.pop("market_analysis_source_verified", None)
        with self.db.transaction() as connection:
            zones.save_in(connection, setup)

        self.pub.verify_destinations = AsyncMock()
        operations = self.pub.prepare_zone_tapped(42, setup["id"])
        await self.pub.send(42, operations["signals"])
        self.assertEqual(self.pub.prepare_zone_tapped(42, setup["id"]), operations)
        await self.pub.send(42, operations["analysis"])
        await self.pub.send(42, operations["analysis"])

        channel_calls = [
            call for call in self.bot.send_message.await_args_list
            if call.args[0] in (self.config.signals, self.config.analysis)
        ]
        self.assertEqual(len(channel_calls), 2)
        replies = {call.args[0]: call.kwargs["reply_parameters"].message_id
                   for call in channel_calls}
        self.assertEqual(replies[self.config.signals], setup["setup_message_id"])
        self.assertEqual(replies[self.config.analysis], 9883)

    async def test_forwarded_multiple_pois_publish_as_independent_pro_posts(self):
        caption = (
            "📊 SMART MONEY HUB | MARKET ANALYSIS\n"
            "📍 MARKET: XAUUSD\n"
            "⏱️ TIMEFRAME: H1\n"
            "BUY POI (approx. 3,989.21 - 4,007.00)\n"
            "SELL POI (approx. 4,107.96 - 4,087.28)\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        await self.click("pro_import_start")
        await self.forward_market_analysis(caption, message_id=9877)
        self.assertEqual(len(self.db.draft(42)["pro_zones"]), 2)
        await self.click("pro_import_publish", self.revision())
        posts = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == self.config.signals
        ]
        self.assertEqual(len(posts), 2)
        from smh import zones
        setups = zones.active_setups(self.db)
        self.assertEqual(len(setups), 2)
        self.assertTrue(all(item.get("status") == "active" for item in setups))
        self.assertTrue(all(item["market_analysis_message_id"] == 9877 for item in setups))
        self.assertFalse(any(
            call.args[0] == self.config.analysis for call in self.bot.send_photo.await_args_list))

    async def test_pro_import_rejects_wrong_source_and_unlabelled_poi_without_channel_posts(self):
        await self.click("pro_import_start")
        await self.forward_market_analysis(
            self.existing_poi_caption(), source_channel=-1999, message_id=9878)
        self.assertEqual(self.db.draft(42)["kind"], "pro_import_wait")
        self.assert_no_channel_posts()
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])

        await self.forward_market_analysis(
            "📍 MARKET: XAUUSD\n⏱️ TIMEFRAME: H1\nThe marked box is my POI.",
            message_id=9879,
        )
        self.assertEqual(self.db.draft(42)["kind"], "pro_import_wait")
        self.assertIn("labelled POI range", self.bot.send_message.await_args_list[-1].args[1])
        self.assert_no_channel_posts()
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])

    async def test_pro_import_publishing_off_blocks_before_outbox_or_channel_send(self):
        from dataclasses import replace
        self.config = replace(self.config, allow_publishing=False)
        self.pub.config = self.config
        self.ui.config = self.config
        await self.click("pro_import_start")
        await self.forward_market_analysis(self.existing_poi_caption(), message_id=9880)
        await self.click("pro_import_publish", self.revision())
        self.assertIn("Publishing is OFF", self.bot.send_message.await_args_list[-1].args[1])
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assert_no_channel_posts()

    async def test_pro_import_edit_and_cancel_do_not_publish(self):
        await self.click("pro_import_start")
        await self.forward_market_analysis(self.existing_poi_caption(), message_id=9881)
        await self.click("pro_import_edit", self.revision())
        await self.text(self.existing_poi_caption("3,922.00", "3,966.00"))
        self.assertEqual(self.db.draft(42)["pro_zones"][0]["setup"]["zone"], "3922.00–3966.00")
        self.assertEqual(self.db.draft(42)["source_message_id"], 9881)
        await self.click("cancel")
        self.assertIsNone(self.db.draft(42))
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assert_no_channel_posts()

    async def test_pro_import_review_resumes_after_handler_recreation(self):
        await self.click("pro_import_start")
        await self.forward_market_analysis(self.existing_poi_caption(), message_id=9882)
        self.ui = Handlers(
            self.db, self.config, self.bot, self.pub,
            Health(self.db, self.config, self.bot),
        )
        await self.click("preview")
        self.assertEqual(self.db.draft(42)["kind"], "pro_import")
        self.assertIn("Review the private previews", self.bot.send_message.await_args_list[-1].args[1])
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assert_no_channel_posts()

    def analysis_draft_with_chart(self):
        chart_path = Path(self.temp.name) / "analysis-chart.png"
        Image.new("RGB", (160, 100), "#334455").save(chart_path, format="PNG")
        self.db.save_draft(42, {
            "kind": "analysis",
            "step": "ready",
            "destination": "analysis",
            "text": "📊 SMART MONEY HUB | MARKET ANALYSIS\n\n"
                    "Watch the marked POI and wait for confirmed structure.",
            "original": str(chart_path),
            "image": str(chart_path),
        })

    async def prepare_analysis_zone_bundle(self):
        self.analysis_draft_with_chart()
        await self.click("analysis_pro_zone_add", self.revision())
        await self.fill_zone_wizard(
            market="Gold", low="2650", high="2655", timeframe="M15",
            confirmation="Wait for an observed M5 structure shift", minutes=60,
        )
        self.assertEqual(self.db.draft(42)["step"], "ready")
        self.assertTrue(self.db.draft(42)["attached_to_analysis"])
        await self.click("analysis_pro_zone_attach", self.revision())
        self.assertEqual(self.db.draft(42)["kind"], "analysis")
        self.assertEqual(self.db.draft(42)["pro_zone"]["setup"]["zone"], "2650–2655")

    async def fill_zone_wizard(self, market="Gold", other_market="TEST ONLY", symbol=None,
                               low="100", high="101", timeframe="M15",
                               confirmation=None, minutes=60, confirm=True):
        from smh.zone_wizard import OTHER, SKIP

        await self.click("zone_wizard_select", self.revision(field="market", value=market))
        if market == "Other":
            await self.text(other_market)
        if market != "Gold":
            if symbol:
                await self.text(symbol)
            elif market == "Other":
                await self.click("zone_wizard_select", self.revision(field="symbol", value=SKIP))
            else:
                raise AssertionError("A symbol is required for this market in the test fixture.")
        await self.text(low)
        await self.text(high)
        if timeframe in (None, ""):
            await self.click("zone_wizard_select", self.revision(field="timeframe", value=SKIP))
        elif timeframe in ("M5", "M15", "M30", "H1", "H4", "D1"):
            await self.click("zone_wizard_select", self.revision(field="timeframe", value=timeframe))
        else:
            await self.click("zone_wizard_select", self.revision(field="timeframe", value=OTHER))
            if timeframe == "SKIP":
                await self.click("zone_wizard_select",
                                 self.revision(field="timeframe_other", value=SKIP))
            else:
                await self.text(timeframe)
        if confirmation is None:
            await self.click("zone_wizard_select", self.revision(field="confirmation", value=SKIP))
        else:
            await self.text(confirmation)
        if confirm:
            await self.click("zone_wizard_confirm", self.revision())
            if self.db.draft(42).get("step") == "replacement":
                await self.click("zone_replace", self.revision())

    async def signal(self, direction="BUY"):
        from smh.zones import parse_zone, activate
        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        setup["confirmation"] = "Mock administrator-confirmed setup"
        setup["setup_message_id"] = 700
        old = self.db.get("active_setup")
        activate(self.db, setup, old["id"] if old else None)
        from smh import zones
        levels = zones.validate_signal_levels(
            setup, direction, "2653",
            "2640" if direction == "BUY" else "2660",
            "2670, 2680" if direction == "BUY" else "2635, 2620",
        )
        payload = zones.signal_payload(setup, direction, 42, levels=levels)
        operation = self.pub.prepare(42, "signal", payload)
        result_record, _ = self.db.create_signal_result(payload["trade"]["id"], 42)
        await self.pub.send(42, operation)
        operation_row, _ = self.pub.operation(operation)
        self.db.update_signal_result(
            payload["trade"]["id"],
            {"signal_message_id": operation_row["message_id"],
             "zone_message_id": setup["setup_message_id"],
             "signal_text": payload["text"]},
            expected_statuses=(result_record["status"],),
        )
        await self.ui.trade_screen(self.u, payload["trade"]["id"])
        return payload["trade"]["id"]

    async def publish_update(self):
        if not self.db.draft(42).get("destination"):
            await self.click("destination", self.revision(destination="signals"))
        await self.click("publish", self.revision())

    def reopen_runtime(self):
        old_db = self.db
        schema = old_db.schema
        db_url = ((os.getenv("SMH_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL"))
                  if old_db.postgres else None)
        old_db.conn.close()
        self.db = Database(self.temp.name, db_url, schema)
        self.pub = Publisher(self.db, self.config, self.bot)
        self.pub.verified = True
        self.ui = Handlers(self.db, self.config, self.bot, self.pub,
                           Health(self.db, self.config, self.bot))

    async def test_complete_buy_and_sell_buttons(self):
        for direction in ("BUY", "SELL"):
            await self.signal(direction)
        self.assertEqual(len(self.db.rows("SELECT * FROM trades")), 2)
        self.assertEqual(len(self.db.rows("SELECT * FROM events")), 2)

    def isolated_signal_setup(self, *, allow_publishing=True, confirmation=True, expires_in=3600):
        from dataclasses import replace
        from smh.zones import activate, parse_zone

        self.config = replace(
            self.config, isolated_test=True, allow_publishing=allow_publishing)
        self.ui.config = self.config
        self.pub.config = self.config
        self.pub.verified = True
        self.pub.verify_destinations = AsyncMock()
        self.ui.update_setup_post = AsyncMock(return_value=True)

        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        if confirmation:
            setup["confirmation"] = "M15 rejection observed"
        setup["setup_message_id"] = 700
        setup["expires"] = __import__("time").time() + max(expires_in, 1)
        activate(self.db, setup, None)
        if expires_in <= 0:
            setup["expires"] = __import__("time").time() - 1
            from smh.zones import save_in
            with self.db.transaction() as conn:
                save_in(conn, setup)
        return setup

    async def test_isolated_signal_has_validated_preview_and_explicit_publish(self):
        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        channel_posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(channel_posts), 1)
        self.assertEqual(channel_posts[0].args[1], "<b>🔴 SELL NOW</b>")
        self.assertEqual(
            channel_posts[0].kwargs["reply_parameters"].message_id, setup["setup_message_id"])
        trade_id = self.db.rows("SELECT id FROM trades")[0]["id"]
        trade = self.db.trade(trade_id)
        self.assertTrue(trade["levels_pending"])
        self.assertEqual(trade["entry"], "")

        await self.click("manage", {"id": trade_id, "action": "entry"})
        await self.text("2653")
        await self.text("2660")
        preview_call = self.bot.send_message.await_args_list[-1]
        preview = preview_call.args[1]
        for expected in (
            "TRADE DETAILS UPDATE", "Entry: 2653", "Stop Loss: 2660",
            "TP1: 2652.80", "TP2: 2652.60", "TP3: 2652.40",
            "TP4: 2652.20", "20-pip steps",
        ):
            self.assertIn(expected, preview)
        self.assertEqual(
            [button.text for row in preview_call.kwargs["reply_markup"].inline_keyboard
             for button in row],
            ["Edit Entry Price", "Edit Stop Loss", "Edit Take Profit",
             "Publish reviewed message", "Cancel Draft", "Main Menu"],
        )
        await self.click("entry_bundle_edit", self.revision(field="targets"))
        await self.text("2640, 2625")
        preview = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("TP1: 2640", preview)
        self.assertIn("TP2: 2625", preview)
        await self.publish_update()
        trade = self.db.trade(trade_id)
        self.assertEqual(trade["entry"], "2653")
        self.assertEqual(trade["sl"], "2660")
        self.assertFalse(trade["targets_auto"])
        self.assertIsNone(self.ui.next_automatic_tp(trade))
        self.assertEqual(
            [trade["targets"][key]["price"] for key in ("1", "2")], ["2640", "2625"])
        channel_posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(channel_posts), 2)
        self.assertIn("Entry: 2653", channel_posts[1].args[1])
        self.assertIn("TP1: 2640", channel_posts[1].args[1])
        self.assertTrue(self.pub.verify_destinations.await_count)

    async def test_isolated_signal_requires_stop_loss_and_rejects_bad_price_relationships(self):
        from smh.zones import validate_signal_levels

        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        trade_id = self.db.rows("SELECT id FROM trades")[0]["id"]
        await self.click("manage", {"id": trade_id, "action": "entry"})
        await self.text("2656")
        self.assertEqual(self.db.draft(42)["step"], "entry")
        await self.text("2653")
        self.assertEqual(self.db.draft(42)["step"], "sl")
        await self.text("skip")
        self.assertEqual(self.db.draft(42)["step"], "sl")
        await self.text("2652")
        self.assertEqual(self.db.draft(42)["step"], "sl")
        self.assertEqual(len(self.db.rows("SELECT * FROM trades")), 1)
        self.assertEqual(len([
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]), 1)

        with self.assertRaisesRegex(ValueError, "Stop Loss"):
            validate_signal_levels(setup, "BUY", "2653", "2654", "2670")
        with self.assertRaisesRegex(ValueError, "Take Profit"):
            validate_signal_levels(setup, "BUY", "2653", "2640", "2645")
        with self.assertRaisesRegex(ValueError, "Stop Loss"):
            validate_signal_levels(setup, "SELL", "2653", "", "2630")
        with self.assertRaisesRegex(ValueError, "Take Profit"):
            validate_signal_levels(setup, "SELL", "2653", "2660", "2665")
        with self.assertRaisesRegex(ValueError, "Take Profit"):
            validate_signal_levels(setup, "BUY", "2653", "2640", "")

    async def test_zone_signal_auto_calculates_gold_tp1_and_requires_exact_entry(self):
        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        trade_id = self.db.rows("SELECT id FROM trades")[0]["id"]
        await self.click("manage", {"id": trade_id, "action": "entry"})
        await self.text("2651-2653")
        self.assertEqual(self.db.draft(42)["step"], "entry")
        self.assertIn("one exact", self.bot.send_message.await_args_list[-1].args[1])

        await self.text("2653")
        draft = self.db.draft(42)
        self.assertEqual(draft["targets_text"], "2652.80, 2652.60, 2652.40, 2652.20")
        self.assertTrue(draft["targets_auto"])
        await self.text("2660")
        review = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("Entry: 2653", review)
        for target_line in (
                "TP1: 2652.80", "TP2: 2652.60",
                "TP3: 2652.40", "TP4: 2652.20"):
            self.assertIn(target_line, review)
        self.assertIn("20-pip steps", review)
        self.assertEqual(len(self.db.rows("SELECT * FROM operations WHERE kind='signal'")), 1)
        channel_posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(channel_posts), 1)
        self.assertEqual(channel_posts[0].args[1], "<b>🔴 SELL NOW</b>")

    async def test_zone_signal_auto_calculates_forex_tp1_from_symbol(self):
        from smh.zones import activate, parse_zone

        setup = parse_zone("Forex/EURUSD | 1.0800-1.0850 | H1 | 60 | M15 close")
        setup["setup_message_id"] = 701
        setup["confirmation"] = "M15 close observed"
        activate(self.db, setup, None)
        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        signal_posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(signal_posts), 1)
        self.assertEqual(signal_posts[0].args[1], "<b>🔴 SELL NOW</b>")
        self.assertEqual(
            signal_posts[0].kwargs["reply_parameters"].message_id, 701)
        trade_id = self.db.rows("SELECT id FROM trades")[0]["id"]
        saved_trade = self.db.trade(trade_id)
        self.assertTrue(saved_trade["levels_pending"])
        self.assertEqual((saved_trade["entry"], saved_trade["sl"]), ("", ""))

        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        signal_posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(signal_posts), 1)

        await self.click("manage", {"id": trade_id, "action": "entry"})
        await self.text("1.08250")
        draft = self.db.draft(42)
        self.assertEqual(
            draft["targets_text"], "1.08050, 1.07850, 1.07650, 1.07450")
        self.assertTrue(draft["targets_auto"])
        await self.text("1.0900")
        preview_text = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("Entry: 1.08250", preview_text)
        self.assertIn("Stop Loss: 1.0900", preview_text)
        for target_line in (
                "TP1: 1.08050", "TP2: 1.07850",
                "TP3: 1.07650", "TP4: 1.07450"):
            self.assertIn(target_line, preview_text)
        await self.publish_update()
        saved_trade = self.db.trade(trade_id)
        self.assertTrue(saved_trade["targets_auto"])
        self.assertEqual(
            [saved_trade["targets"][str(number)]["price"] for number in range(1, 5)],
            ["1.08050", "1.07850", "1.07650", "1.07450"],
        )
        await self.ui.trade_screen(self.u, trade_id)
        active_screen = self.bot.send_message.await_args_list[-1]
        self.assertIn("TP4: 1.07450", active_screen.args[1])
        labels = [
            button.text for row in active_screen.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertFalse(any(label.startswith("➕ Add TP") for label in labels))

        self.assertEqual(set(saved_trade["targets"]), {"1", "2", "3", "4"})
        self.assertTrue(saved_trade["targets_auto"])
        posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(posts), 2)
        self.assertIn("TP2: 1.07850", posts[-1].args[1])
        self.assertIn("TP4: 1.07450", posts[-1].args[1])

    async def test_isolated_signal_cancel_keeps_setup_and_sends_nothing(self):
        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        await self.click("zone_signal_cancel", self.revision())
        self.assertIsNone(self.db.draft(42))
        self.assertEqual(self.db.get("setup:" + setup["id"])["status"], "active")
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))
        self.assertFalse([
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ])

    async def test_buy_direction_posts_first_then_details_are_validated_and_reviewed(self):
        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        preview = self.bot.send_message.await_args_list[-1]
        self.assertIn("PRIVATE BUY NOW PREVIEW", preview.args[1])
        self.assertIn("<b>🟢 BUY NOW</b>", preview.args[1])
        self.assertIn("a separate reviewed update", preview.args[1])
        labels = [
            button.text for row in preview.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("✅ Confirm & Publish BUY NOW", labels)
        self.assertIn("Cancel", labels)
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))
        self.assertFalse([
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ])

        confirm_token = self.db.button(
            42, "zone_signal_confirm", {"revision": self.db.draft(42)["revision"]})
        self.u.callback_query.data = confirm_token
        await self.ui.callback(self.u, None)
        with self.assertRaisesRegex(ValueError, "expired or was already used"):
            await self.ui.callback(self.u, None)

        signal_posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(signal_posts), 1)
        self.assertEqual(signal_posts[0].args[1], "<b>🟢 BUY NOW</b>")
        self.assertEqual(
            signal_posts[0].kwargs["reply_parameters"].message_id,
            setup["setup_message_id"],
        )
        trade = self.db.rows("SELECT id FROM trades")[0]
        trade_id = trade["id"]
        saved_trade = self.db.trade(trade_id)
        self.assertEqual(saved_trade["entry"], "")
        self.assertEqual(saved_trade["sl"], "")
        self.assertEqual(saved_trade["targets"], {})
        self.assertTrue(saved_trade["levels_pending"])

        screen = self.bot.send_message.await_args_list[-1]
        screen_labels = [
            button.text for row in screen.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("📍 Set Buy Entry, SL & Auto TP1–TP4", screen_labels)

        self.reopen_runtime()
        self.pub.verified = True
        self.pub.verify_destinations = AsyncMock(return_value=True)
        await self.click("manage", {"id": trade_id, "action": "entry"})
        await self.text("2656")
        self.assertIn("within the active setup zone",
                      self.bot.send_message.await_args_list[-1].args[1])
        await self.text("2653")
        await self.text("skip")
        self.assertIn("Stop Loss is required",
                      self.bot.send_message.await_args_list[-1].args[1])
        await self.text("2654")
        self.assertIn("Stop Loss must be below",
                      self.bot.send_message.await_args_list[-1].args[1])
        await self.text("2640")
        detail_preview = self.bot.send_message.await_args_list[-1].args[1]
        for expected in (
                "TRADE DETAILS UPDATE", "Entry: 2653", "Stop Loss: 2640",
                "TP1: 2653.20", "TP2: 2653.40", "TP3: 2653.60",
                "TP4: 2653.80", "TP1–TP4 were calculated in 20-pip steps"):
            self.assertIn(expected, detail_preview)
        self.assertTrue(self.db.trade(trade_id)["levels_pending"])
        edit_labels = [
            button.text
            for row in self.bot.send_message.await_args_list[-1].kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Edit Entry Price", edit_labels)
        self.assertIn("Edit Stop Loss", edit_labels)
        self.assertIn("Edit Take Profit", edit_labels)

        await self.click("entry_bundle_edit", self.revision(field="targets"))
        await self.text("2635")
        self.assertIn("Take Profit must be above",
                      self.bot.send_message.await_args_list[-1].args[1])
        self.assertEqual(self.db.draft(42)["step"], "tp")
        await self.text("2675, 2685")
        self.assertIn("TP1: 2675", self.bot.send_message.await_args_list[-1].args[1])
        self.assertIn("TP2: 2685", self.bot.send_message.await_args_list[-1].args[1])

        await self.publish_update()
        updated_trade = self.db.trade(trade_id)
        self.assertFalse(updated_trade["levels_pending"])
        self.assertEqual((updated_trade["entry"], updated_trade["sl"]),
                         ("2653", "2640"))
        self.assertEqual(
            [updated_trade["targets"][key]["price"] for key in ("1", "2")],
            ["2675", "2685"],
        )
        posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].args[1], "<b>🟢 BUY NOW</b>")
        self.assertIn("Entry: 2653", posts[1].args[1])
        self.assertIn("Stop Loss: 2640", posts[1].args[1])
        self.assertIn("TP1: 2675", posts[1].args[1])
        self.assertEqual(posts[1].kwargs["reply_parameters"].message_id, 123)
        result_record = self.db.signal_result(trade_id)
        self.assertEqual((result_record["entry"], result_record["sl"]), ("2653", "2640"))

    async def test_isolated_signal_publish_off_blocks_before_channel_request(self):
        setup = self.isolated_signal_setup(allow_publishing=False)
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        self.assertIn("LOCKED", self.bot.send_message.await_args_list[-1].args[1])
        await self.click("zone_signal_confirm", self.revision())
        self.assertIn("Publishing is OFF", self.bot.send_message.await_args_list[-1].args[1])
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))
        self.assertFalse([
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ])
        self.assertFalse(self.bot.send_photo.await_args_list)
        self.pub.verify_destinations.assert_not_awaited()

    async def test_sell_now_still_requires_confirmation_live_zone_and_publishing(self):
        setup = self.isolated_signal_setup(confirmation=False)
        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        self.assertIn(
            "Confirmation is still missing",
            self.bot.send_message.await_args_list[-1].args[1],
        )
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse([
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ])

    async def test_isolated_signal_revalidates_confirmation_and_recovers_preview_after_restart(self):
        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        self.reopen_runtime()
        await self.click("preview")
        self.assertIn("PRIVATE BUY NOW PREVIEW", self.bot.send_message.await_args_list[-1].args[1])

        setup["confirmation"] = ""
        from smh.zones import save_in
        with self.db.transaction() as conn:
            save_in(conn, setup)
        await self.click("zone_signal_confirm", self.revision())
        self.assertIn("confirmation", self.bot.send_message.await_args_list[-1].args[1].lower())
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))

    async def test_isolated_signal_rejects_zone_replaced_after_preview(self):
        from smh.zones import activate, parse_zone

        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        replacement = parse_zone("Gold/XAUUSD | 2660-2665 | M15 | 60 | -")
        replacement["confirmation"] = "Replacement confirmation"
        replacement["setup_message_id"] = 701
        activate(self.db, replacement, setup["id"])

        await self.click("zone_signal_confirm", self.revision())
        self.assertIn(
            "no longer valid",
            self.bot.send_message.await_args_list[-1].args[1].lower(),
        )
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))
        self.assertFalse([
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ])

    async def test_isolated_signal_rejects_expired_setup_before_preview(self):
        setup = self.isolated_signal_setup(expires_in=-1)
        with self.assertRaisesRegex(ValueError, "expired"):
            await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))

    async def test_isolated_signal_requires_active_zone_and_recorded_confirmation(self):
        self.isolated_signal_setup()
        self.db.put("active_setup", None)
        with self.assertRaisesRegex(ValueError, "stale"):
            await self.click("new_signal", {"direction": "BUY", "setup_id": "missing-setup"})
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))

        setup = self.isolated_signal_setup(confirmation=False)
        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        self.assertIn("Confirmation is still missing",
                      self.bot.send_message.await_args_list[-1].args[1])
        self.assertIsNone(self.db.draft(42))
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))

        await self.click("zone_confirmation", {"setup_id": setup["id"]})
        await self.text("Bullish M15 candle close observed.")
        self.assertEqual(
            self.db.get("setup:" + setup["id"])["confirmation"],
            "Bullish M15 candle close observed.",
        )
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        self.assertIn("PRIVATE BUY NOW PREVIEW", self.bot.send_message.await_args_list[-1].args[1])
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT * FROM operations"))

    async def test_isolated_sell_signal_preview_uses_directional_levels(self):
        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].args[1], "<b>🔴 SELL NOW</b>")
        trade_id = self.db.rows("SELECT id FROM trades")[0]["id"]
        self.assertEqual(self.db.trade(trade_id)["direction"], "SELL")
        self.assertTrue(self.db.trade(trade_id)["levels_pending"])
        await self.ui.trade_screen(self.u, trade_id)
        trade_screen = self.bot.send_message.await_args_list[-1]
        self.assertIn("Stop loss: \n", trade_screen.args[1])
        self.assertIn("Take-profit targets: none recorded", trade_screen.args[1])

    async def test_signal_controls_precede_publish_and_sell_channel_post_is_direction_only(self):
        setup = self.isolated_signal_setup()
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        controls = self.bot.send_message.await_args_list[-1]
        labels = [
            button.text for row in controls.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("✅ Confirm & Publish BUY NOW", labels)
        self.assertIn("Cancel", labels)
        self.assertNotIn("Set Buy Range", labels)
        self.assertFalse([
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ])
        await self.click("zone_signal_cancel", self.revision())

        await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        entry_prompt = self.bot.send_message.await_args_list[-1]
        self.assertIn("Enter the exact Sell Entry", entry_prompt.args[1])
        self.assertIn("TP1–TP4", entry_prompt.args[1])
        self.assertIn("Stop Loss is required next", entry_prompt.args[1])

        channel_posts = [
            call for call in self.bot.send_message.await_args_list
            if call.args and call.args[0] == self.config.signals
        ]
        self.assertEqual(len(channel_posts), 1)
        self.assertEqual(channel_posts[0].args[1], "<b>🔴 SELL NOW</b>")
        self.assertEqual(
            channel_posts[0].kwargs["reply_parameters"].message_id,
            setup["setup_message_id"],
        )
        for private_detail in ("XAUUSD", "2653", "2660", "2635", "M15"):
            self.assertNotIn(private_detail, channel_posts[0].args[1])

    async def test_zone_prerequisite_missing_confirmation_and_controls(self):
        await self.click("menu")
        first_menu = self.bot.send_message.await_args_list[-1]
        self.assertIn("No active setup.", first_menu.args[1])
        self.assertIn("📍 Zone & Signals", [
            button.text for row in first_menu.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])
        await self.click("admin_category", {"category": "zone"})
        zone_menu = self.bot.send_message.await_args_list[-1]
        zone_menu_labels = [
            button.text for row in zone_menu.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("📊 Market Analysis + PRO POI", zone_menu_labels)
        await self.click("new_analysis", {"paired_pro_zone": True})
        self.assertTrue(self.db.draft(42)["paired_pro_zone_requested"])
        self.assertIn("Label each POI range in the caption",
                      self.bot.send_message.call_args.args[1])
        await self.click("cancel")
        with self.assertRaises(ValueError):
            await self.click("new_signal", {"direction": "BUY"})
        await self.click("zone_new")
        market_question = self.bot.send_message.await_args_list[-1]
        self.assertIn("Question 1 of 6 — Which market?", market_question.args[1])
        market_buttons = [
            button.text for row in market_question.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Gold (XAUUSD)", market_buttons)
        self.assertIn("Forex", market_buttons)
        self.assertIn("Other", market_buttons)
        self.assertIn("Cancel", market_buttons)
        self.assertIn("↩️ Return to Main Menu", market_buttons)
        await self.click("zone_wizard_select", self.revision(field="market", value="Gold"))
        self.assertIn("Question 3 of 6", self.bot.send_message.call_args.args[1])
        await self.text("2650")
        self.assertIn("Question 4 of 6", self.bot.send_message.call_args.args[1])
        await self.text("2655")
        self.assertIn("Question 5 of 6", self.bot.send_message.call_args.args[1])
        await self.click("zone_wizard_select", self.revision(field="timeframe", value="M15"))
        self.assertIn("Question 6 of 6", self.bot.send_message.call_args.args[1])
        await self.text("M15 candle close")
        review = self.bot.send_message.await_args_list[-1]
        self.assertIn("SETUP DETAILS — REVIEW", review.args[1])
        self.assertIn("Gold (XAUUSD)", review.args[1])
        self.assertIn("2650", review.args[1])
        self.assertIn("2655", review.args[1])
        self.assertIn("M15 candle close", review.args[1])
        self.assertIn("Manual", review.args[1])
        self.assertIsNone(self.db.get("active_setup"))
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        review_buttons = [
            button.text for row in review.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("✏️ Edit", review_buttons)
        self.assertIn("✅ Confirm details", review_buttons)
        self.assertIn("Cancel", review_buttons)
        await self.click("zone_wizard_confirm", self.revision())
        self.assertIsNone(self.db.get("active_setup"))
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assertEqual(self.db.draft(42)["step"], "chart")
        self.assertEqual(self.db.draft(42)["setup"]["zone"], "2650–2655")
        await self.upload_zone_chart()
        zone_review = self.bot.send_message.await_args_list[-1]
        self.assertIn("does not publish a BUY/SELL signal", zone_review.args[1])
        self.assertIn("📍 Publish Zone + Chart to PRO Signals", [
            button.text for row in zone_review.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])
        await self.click("zone_publish", self.revision())
        zone_success = self.bot.send_message.await_args_list[-1]
        self.assertIn("Zone + chart posted to PRO Signals", zone_success.args[1])
        self.assertIn("No signal was sent yet", zone_success.args[1])
        setup = self.db.get("active_setup")
        self.assertEqual(setup["zone"], "2650–2655")
        self.assertTrue(setup["setup_message_id"])
        setup_post = next(c for c in self.bot.send_photo.await_args_list if c.args[0] == self.config.signals)
        self.assertIn("ACTIVE SETUP ZONE", setup_post.kwargs["caption"])
        self.assertNotIn(setup["id"], setup_post.kwargs["caption"])
        self.assertNotIn("Setup ID", setup_post.kwargs["caption"])
        self.assertEqual(setup_post.kwargs["parse_mode"], "HTML")
        self.assertIn("<b>Awaiting Confirmation</b>", setup_post.kwargs["caption"])
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        self.assertIn("Confirmation is still missing", self.bot.send_message.call_args.args[1])
        await self.click("zone_confirmation", {"setup_id": setup["id"]})
        await self.text("Bullish M15 candle close observed.")
        confirmation_post = self.bot.edit_message_caption.await_args_list[-1]
        self.assertEqual(confirmation_post.kwargs["message_id"], setup["setup_message_id"])
        self.assertEqual(confirmation_post.kwargs["parse_mode"], "HTML")
        self.assertIn("<b>Confirmation Recorded</b>", confirmation_post.kwargs["caption"])
        self.assertEqual(
            self.db.get("setup:" + setup["id"])["caption_status"], "Confirmation Recorded"
        )
        confirmation_menu = self.bot.send_message.await_args_list[-1]
        self.assertIn("Confirmation recorded", confirmation_menu.args[1])
        await self.click("admin_category", {"category": "zone"})
        confirmation_menu = self.bot.send_message.await_args_list[-1]
        confirmation_labels = [
            button.text for row in confirmation_menu.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("📊 Market Analysis + PRO POI", confirmation_labels)
        self.assertIn("🟢 BUY NOW", confirmation_labels)
        self.assertIn("🔴 SELL NOW", confirmation_labels)
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        direction_preview = self.bot.send_message.await_args_list[-1]
        self.assertIn("PRIVATE BUY NOW PREVIEW", direction_preview.args[1])
        self.assertIn("<b>🟢 BUY NOW</b>", direction_preview.args[1])
        self.assertFalse(self.db.rows("SELECT * FROM trades"))
        self.assertFalse(self.db.rows("SELECT id FROM operations WHERE kind='signal'"))
        self.assertEqual(
            self.db.get("setup:" + setup["id"])["status"], "active"
        )

    async def test_uncertain_zone_chart_post_requires_reconciliation_before_buy(self):
        from telegram.error import NetworkError
        await self.click("zone_new")
        await self.fill_zone_wizard(
            market="Other", other_market="TEST ONLY", low="100", high="101",
            timeframe="TEST", confirmation=None, minutes=60,
        )
        async def send_photo(chat_id, image, **kwargs):
            if chat_id == self.config.signals:
                raise NetworkError("ambiguous setup post timeout")
            return NS(message_id=124)
        self.bot.send_photo.side_effect = send_photo
        await self.upload_zone_chart()
        await self.click("zone_publish", self.revision())
        op = self.db.rows("SELECT id FROM operations WHERE kind='setup'")[0]["id"]
        self.assertEqual(self.pub.operation(op)[0]["status"], "uncertain")
        self.assertIsNone(self.db.get("active_setup"))
        with self.assertRaisesRegex(ValueError, "uncertain"):
            await self.pub.send(42, op)
        self.assertEqual(sum(c.args[0] == self.config.signals for c in self.bot.send_photo.call_args_list), 1)
        await self.pub.reconcile(42, op, 987)
        self.assertEqual(self.db.get("active_setup")["setup_message_id"], 987)

    async def test_manual_zone_expiry_and_replace_confirmation(self):
        from smh.zones import parse_zone, activate
        old = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        old["setup_message_id"] = 600
        activate(self.db, old, None)
        await self.click("zone_new")
        await self.click("zone_wizard_select", self.revision(field="market", value="Forex"))
        await self.text("EURUSD")
        await self.text("broken")
        self.assertEqual(self.db.draft(42)["step"], "low")
        self.assertIn("positive price", self.bot.send_message.call_args.args[1])
        await self.text("1.0800")
        await self.text("1.0700")
        self.assertEqual(self.db.draft(42)["step"], "high")
        self.assertIn("greater than the lower price", self.bot.send_message.call_args.args[1])
        await self.text("1.0850")
        await self.click("zone_wizard_select", self.revision(field="timeframe", value="H1"))
        await self.click("zone_wizard_select", self.revision(field="confirmation", value="__skip__"))
        self.assertEqual(self.db.draft(42)["step"], "preview")
        self.assertEqual(self.db.get("active_setup")["id"], old["id"])
        await self.click("zone_wizard_confirm", self.revision())
        first = self.db.get("active_setup")
        self.assertEqual(first["id"], old["id"])
        self.assertEqual(self.db.draft(42)["step"], "replacement")
        await self.click("zone_replace", self.revision())
        self.assertEqual(self.db.get("active_setup")["id"], first["id"])
        await self.upload_zone_chart()
        await self.click("zone_publish", self.revision())
        self.assertEqual(self.db.get("active_setup")["market"], "Forex/EURUSD")
        setup = self.db.get("active_setup")
        setup["expires"] = 0
        self.db.put("active_setup", setup)
        with self.assertRaisesRegex(ValueError, "expired"):
            await self.click("new_signal", {"direction": "SELL", "setup_id": setup["id"]})
        await self.click("menu")
        self.assertEqual(self.db.get("active_setup")["status"], "expired")
        expired_post = self.bot.edit_message_caption.await_args_list[-1]
        self.assertIn("<b>Expired</b>", expired_post.kwargs["caption"])
        self.assertIn("SETUP EXPIRED", expired_post.kwargs["caption"])
        self.assertNotIn("ACTIVE SETUP ZONE", expired_post.kwargs["caption"])
        self.assertEqual(
            self.db.get("setup:" + setup["id"])["caption_status"], "Expired"
        )

    async def test_new_zone_can_publish_after_previous_setup_was_used(self):
        from smh.zones import parse_zone, save_in

        used = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | M15 candle close")
        used.update(status="used", setup_message_id=600, confirmation="Bullish M15 candle close observed.")
        with self.db.transaction() as conn:
            save_in(conn, used)

        await self.click("zone_new")
        await self.fill_zone_wizard(
            market="Other", other_market="TEST ONLY", low="100", high="101",
            timeframe="TEST", confirmation=None, minutes=60,
        )
        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "chart")
        self.assertNotIn("replaces", draft)
        await self.upload_zone_chart()
        await self.click("zone_publish", self.revision())

        active = self.db.get("active_setup")
        self.assertEqual(active["market"], "TEST ONLY")
        self.assertEqual(active["status"], "active")
        self.assertNotEqual(active["id"], used["id"])
        self.assertEqual(self.db.get("setup:" + used["id"])["status"], "used")
        self.assertEqual(
            self.db.rows("SELECT status FROM operations WHERE kind='setup' ORDER BY created DESC")[0]["status"],
            "done",
        )
        self.assertTrue(any(call.args[0] == self.config.signals
                            for call in self.bot.send_photo.await_args_list))

    async def test_stale_live_replacement_is_still_blocked_after_active_setup_changes(self):
        from smh.zones import activate, parse_zone

        old = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        old["setup_message_id"] = 600
        activate(self.db, old, None)
        await self.click("zone_new")
        await self.fill_zone_wizard(
            market="Other", other_market="TEST ONLY", low="100", high="101",
            timeframe="TEST", confirmation=None, minutes=60, confirm=False,
        )
        await self.click("zone_wizard_confirm", self.revision())
        await self.click("zone_replace", self.revision())
        await self.upload_zone_chart()

        replacement = parse_zone("Forex/EURUSD | 1.0800-1.0850 | H1 | 60 | -")
        replacement["setup_message_id"] = 601
        activate(self.db, replacement, old["id"])
        with self.assertRaisesRegex(ValueError, "Active setup changed"):
            await self.click("zone_publish", self.revision())

        self.assertEqual(self.db.get("active_setup")["id"], replacement["id"])
        self.assertEqual(self.db.rows("SELECT * FROM operations WHERE kind='setup'"), [])
        self.assertFalse(any(call.args[0] == self.config.signals
                             for call in self.bot.send_photo.await_args_list))

    async def test_zone_wizard_back_edit_cancel_and_menu_resume(self):
        await self.click("zone_new")
        await self.click("zone_wizard_select", self.revision(field="market", value="Forex"))
        await self.text("EURUSD")
        await self.click("zone_wizard_back", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "symbol")
        await self.text("GBPUSD")
        self.assertEqual(self.db.draft(42)["step"], "low")

        # Starting the wizard twice resumes the existing draft rather than erasing it.
        await self.click("zone_new")
        self.assertEqual(self.db.draft(42)["answers"]["symbol"], "GBPUSD")
        await self.text("1.0800")
        await self.text("1.0850")
        await self.click("menu")
        self.assertEqual(self.db.draft(42)["step"], "timeframe")
        await self.click("preview")
        self.assertIn("Question 5 of 6", self.bot.send_message.call_args.args[1])
        await self.click("zone_wizard_select", self.revision(field="timeframe", value="M15"))
        await self.click("zone_wizard_select", self.revision(field="confirmation", value="__skip__"))
        self.assertEqual(self.db.draft(42)["step"], "preview")

        await self.click("zone_wizard_edit", self.revision())
        edit_labels = [
            button.text for row in self.bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Edit Lower zone price", edit_labels)
        await self.click("zone_wizard_edit_field", self.revision(field="low"))
        await self.text("1.0810")
        self.assertEqual(self.db.draft(42)["step"], "preview")
        self.assertIn("1.0810", self.bot.send_message.call_args.args[1])

        await self.click("zone_wizard_cancel", self.revision())
        self.assertIsNone(self.db.draft(42))
        self.assertIsNone(self.db.get("active_setup"))
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])

    async def test_zone_wizard_state_recovers_after_runtime_reopen(self):
        await self.click("zone_new")
        await self.click("zone_wizard_select", self.revision(field="market", value="Bitcoin"))
        await self.text("BTCUSD")
        self.assertEqual(self.db.draft(42)["step"], "low")

        self.reopen_runtime()
        await self.click("preview")
        self.assertIn("Question 3 of 6", self.bot.send_message.call_args.args[1])
        self.assertEqual(self.db.draft(42)["answers"]["symbol"], "BTCUSD")
        self.assertEqual(self.db.draft(42)["step"], "low")

    async def test_legacy_empty_zone_prompt_migrates_to_first_wizard_question(self):
        self.db.save_draft(42, {"kind": "zone", "step": "input"})
        await self.click("preview")
        self.assertEqual(self.db.draft(42)["wizard_version"], 1)
        self.assertEqual(self.db.draft(42)["step"], "market")
        self.assertIn("Which market?", self.bot.send_message.call_args.args[1])

    async def test_cancelled_replacement_keeps_existing_active_setup(self):
        from smh.zones import activate, parse_zone

        old = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        old["setup_message_id"] = 600
        activate(self.db, old, None)
        await self.click("zone_new")
        await self.fill_zone_wizard(
            market="Forex", symbol="EURUSD", low="1.0800", high="1.0850",
            timeframe="H1", confirmation=None, minutes=60, confirm=False,
        )
        await self.click("zone_wizard_confirm", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "replacement")
        self.assertEqual(self.db.get("active_setup")["id"], old["id"])
        await self.click("zone_wizard_back", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "preview")
        self.assertEqual(self.db.get("active_setup")["id"], old["id"])
        await self.click("zone_wizard_confirm", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "replacement")
        await self.click("zone_wizard_cancel", self.revision())
        self.assertIsNone(self.db.draft(42))
        self.assertEqual(self.db.get("active_setup")["id"], old["id"])
        self.assertEqual(self.db.get("active_setup")["status"], "active")
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])

    async def test_zone_wizard_confirm_is_single_use_and_rejects_nonadmin(self):
        self.u.effective_user.id = 77
        self.u.effective_chat.id = 77
        self.u.callback_query.data = self.db.button(77, "zone_new", {})
        with self.assertRaises(PermissionError):
            await self.ui.callback(self.u, None)
        self.assertIsNone(self.db.draft(77))

        self.u.effective_user.id = 42
        self.u.effective_chat.id = 42
        await self.click("zone_new")
        await self.fill_zone_wizard(
            market="Other", other_market="TEST ONLY", low="100", high="101",
            timeframe=None, confirmation=None, minutes=60, confirm=False,
        )
        self.assertIsNone(self.db.get("active_setup"))
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        preview_call = self.bot.send_message.await_args_list[-1]
        confirm_button = next(
            button for row in preview_call.kwargs["reply_markup"].inline_keyboard
            for button in row if button.text == "✅ Confirm details"
        )
        old_revision = self.db.draft(42)["revision"]
        self.u.callback_query.data = confirm_button.callback_data
        await self.ui.callback(self.u, None)
        self.assertEqual(self.db.draft(42)["step"], "chart")
        self.assertIsNone(self.db.get("active_setup"))
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        with self.assertRaisesRegex(ValueError, "expired or was already used"):
            await self.ui.callback(self.u, None)

        stale = self.db.button(42, "zone_wizard_confirm", {"revision": old_revision})
        self.u.callback_query.data = stale
        with self.assertRaisesRegex(ValueError, "out of date"):
            await self.ui.callback(self.u, None)
        self.assertEqual(self.db.draft(42)["step"], "chart")

    async def test_cancelled_zone_updates_its_original_post(self):
        from smh.zones import parse_zone, activate
        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | M15 candle close")
        setup["setup_message_id"] = 777
        activate(self.db, setup, None)

        await self.click("zone_cancel", {"setup_id": setup["id"]})

        self.assertEqual(self.db.get("active_setup")["status"], "cancelled")
        edited = self.bot.edit_message_caption.await_args_list[-1]
        self.assertEqual(edited.kwargs["message_id"], 777)
        self.assertIn("SETUP CANCELLED", edited.kwargs["caption"])
        self.assertIn("<b>Cancelled</b>", edited.kwargs["caption"])
        self.assertNotIn("ACTIVE SETUP ZONE", edited.kwargs["caption"])
        self.assertEqual(
            self.db.get("setup:" + setup["id"])["caption_status"], "Cancelled"
        )

    async def test_admin_can_mark_zone_expired_and_update_its_existing_post(self):
        from smh import zones

        setup = zones.parse_zone("Gold/XAUUSD | 2650-2655 | M15 | manual | M15 candle close")
        setup["setup_message_id"] = 778
        zones.activate(self.db, setup, None)
        await self.click("admin_category", {"category": "zone"})
        labels = [
            button.text for row in self.bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("🚫 Mark Zone Expired", labels)

        await self.click("zone_expire", {"setup_id": setup["id"]})
        expired = self.db.get("setup:" + setup["id"])
        self.assertEqual(expired["status"], "expired")
        self.assertIsNone(expired["expires"])
        edited = self.bot.edit_message_caption.await_args_list[-1]
        self.assertEqual(edited.kwargs["message_id"], setup["setup_message_id"])
        self.assertIn("<b>Expired</b>", edited.kwargs["caption"])
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        with self.assertRaisesRegex(ValueError, "expired"):
            zones.active(self.db, setup["id"])

    async def test_buy_sell_visibility_requires_active_unused_zone_and_confirmation(self):
        from smh.zones import parse_zone, activate
        from dataclasses import replace
        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        setup["confirmation"] = "Mock confirmation"
        setup["setup_message_id"] = 777
        activate(self.db, setup, None)

        async def zone_labels():
            await self.click("menu")
            await self.click("admin_category", {"category": "zone"})
            markup = self.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
            return [button.text for row in markup.inline_keyboard for button in row]

        self.config = replace(self.config, allow_publishing=False)
        self.pub.config = self.config
        self.ui.config = self.config
        labels = await zone_labels()
        self.assertIn("🟢 BUY NOW", labels)
        self.assertIn("🔴 SELL NOW", labels)
        self.config = replace(self.config, allow_publishing=True)
        self.pub.config = self.config
        self.ui.config = self.config
        labels = await zone_labels()
        self.assertIn("🟢 BUY NOW", labels)
        self.assertIn("🔴 SELL NOW", labels)
        setup["status"] = "cancelled"
        self.db.put("active_setup", setup)
        labels = await zone_labels()
        self.assertNotIn("🟢 BUY NOW", labels)
        self.assertNotIn("🔴 SELL NOW", labels)

    async def test_isolated_test_mode_rejects_public_channel(self):
        from dataclasses import replace
        self.config = replace(self.config, isolated_test=True)
        self.pub.config = self.config
        async def chat(ident):
            return NS(id=ident, type="private" if ident == 42 else "channel",
                      username="public_test_name" if ident == self.config.signals else None)
        self.bot.get_chat = AsyncMock(side_effect=chat)
        self.bot.get_me = AsyncMock(return_value=NS(id=999))
        self.bot.get_chat_member = AsyncMock(return_value=NS(status="administrator",
            can_post_messages=True, can_edit_messages=True, can_invite_users=True))
        with self.assertRaisesRegex(ValueError, "must be private"):
            await self.pub.verify_destinations()
        self.assertFalse(self.pub.verified)

    async def test_uncertain_direction_first_send_is_quarantined_without_retry(self):
        from smh.zones import parse_zone, activate
        from telegram.error import NetworkError
        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        setup["confirmation"] = "Mock administrator-confirmed setup"
        setup["setup_message_id"] = 888
        activate(self.db, setup, None)
        async def send_message(chat_id, text, **kwargs):
            if chat_id == self.config.signals:
                raise NetworkError("timeout")
            return NS(message_id=123)
        self.bot.send_message.side_effect = send_message
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        await self.click("zone_signal_confirm", self.revision())
        self.assertEqual(self.db.rows("SELECT status FROM operations")[0]["status"], "uncertain")
        replies_before = self.bot.send_message.await_count
        self.assertTrue(any(c.args[0] == 42 and "uncertain" in c.args[1].lower()
                            for c in self.bot.send_message.call_args_list[1:]))
        await self.click("new_signal", {"direction": "BUY", "setup_id": setup["id"]})
        self.assertEqual(self.bot.send_message.await_count, replies_before + 1)
        self.assertEqual(sum(c.args[0] == self.config.signals for c in self.bot.send_message.call_args_list), 1)

    async def test_trade_management_callbacks(self):
        tid = await self.signal()
        original_message_id = self.db.trade(tid)["message_id"]
        await self.click("manage", {"id": tid, "action": "entry"})
        await self.text("2600-2605")
        self.assertIn(
            "exact entry",
            self.bot.send_message.await_args_list[-1].args[1],
        )
        self.assertEqual(self.db.draft(42)["step"], "entry")
        await self.text("2600")
        await self.text("2580")
        await self.text("1 2700")
        self.assertEqual(self.db.trade(tid)["entry"], "2653")
        await self.publish_update()
        trade = self.db.trade(tid)
        self.assertEqual(trade["entry"], "2600")
        self.assertEqual(trade["sl"], "2580")
        self.assertEqual(trade["targets"]["1"]["price"], "2700")
        for action, value in (("sl", "2580"), ("tp", "1 2700"),
                              ("trail", "2590"), ("custom", "Spread update: administrator observation."),
                              ("edit", "BUY NOW — XAUUSD\nRevised wording.")):
            await self.click("manage", {"id": tid, "action": action})
            await self.click("preview")
            await self.text(value)
            await self.publish_update()
        await self.click("manage", {"id": tid, "action": "partial"})
        await self.click("partial_choice", self.revision(percent="25", mode="recommendation"))
        await self.publish_update()
        await self.click("manage", {"id": tid, "action": "partial"})
        await self.click("partial_custom", self.revision())
        await self.text("33")
        await self.click("preview")
        await self.click("partial_mode", self.revision(mode="reported"))
        await self.click("partial_target_choice", self.revision(target="2700"))
        await self.click("partial_remaining_skip", self.revision())
        await self.publish_update()
        await self.click("manage", {"id": tid, "action": "hit"})
        await self.click("hit_target_choice", self.revision(target="1"))
        await self.click("hit_status", self.revision(status="partial"))
        await self.publish_update()
        await self.click("manage", {"id": tid, "action": "be"})
        await self.click("be_confirm", self.revision())
        await self.publish_update()
        await self.click("manage", {"id": tid, "action": "close"})
        await self.click("preview")
        await self.click("choose_value", self.revision(value="Win"))
        await self.text("2700 | Reported manual close")
        await self.publish_update()
        self.assertEqual(self.db.trade(tid)["state"], "CLOSED")
        update_posts = [call for call in self.bot.send_message.await_args_list
                        if call.args[0] == self.config.signals and
                        call.kwargs.get("reply_parameters")]
        self.assertTrue(update_posts[1:])
        self.assertTrue(all(call.kwargs["reply_parameters"].message_id == original_message_id
                            for call in update_posts[1:]))

    async def test_trade_controls_use_requested_mobile_rows_and_preserve_secondary_actions(self):
        tid = await self.signal()
        markup = self.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
        self.assertEqual(
            [[button.text for button in row] for row in markup.inline_keyboard],
            [["🛡️ Set SL + TP together"],
             ["💰 Partial Profit", "🔒 Move to BE"],
             ["📸 Post TP1 Profit Screenshot"],
             ["📈 Trailing SL", "🏁 Close Trade"],
             ["🚫 Cancel / Invalidate Setup"],
             ["📸 Capture Signal Screenshot", "📤 Post Result to Market Analysis Group"],
             ["📋 Trade Details", "↩️ Back to Admin"]])
        await self.click("trade_details", {"id": tid})
        detail_markup = self.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
        details = [button.text for row in detail_markup.inline_keyboard for button in row]
        self.assertIn("🛡️ Update SL", details)
        self.assertIn("🎯 Update TP", details)
        self.assertIn("Add Entry", details)
        self.assertIn("TP Hit", details)
        self.assertIn("Custom Trade Update", details)
        self.assertIn("Edit Original Signal", details)

    async def test_signal_result_record_is_listed_and_duplicate_creation_is_ignored(self):
        tid = await self.signal()
        original = self.db.signal_result(tid)
        duplicate, created = self.db.create_signal_result(tid, 42)

        self.assertFalse(created)
        self.assertEqual(duplicate["id"], original["id"])
        self.assertEqual(duplicate["trade_id"], str(tid))
        self.assertIn(
            str(tid),
            {item["trade_id"] for item in self.db.signal_results()},
        )

    async def test_set_sl_and_tp_together_after_signal_is_one_reviewed_linked_update(self):
        tid = await self.signal("BUY")
        original_message_id = self.db.trade(tid)["message_id"]
        markup = self.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
        self.assertIn("🛡️ Set SL + TP together", [
            button.text for row in markup.inline_keyboard for button in row
        ])
        await self.click("manage", {"id": tid, "action": "sl_tp"})
        self.assertIn("Enter both confirmed values in one message",
                      self.bot.send_message.call_args.args[1])
        self.assertIn("SL 2580 | TP1 2700", self.bot.send_message.call_args.args[1])

        with self.assertRaisesRegex(ValueError, "positive price"):
            await self.text("SL 0 | TP1 2700")
        self.assertEqual(self.db.trade(tid).get("sl"), "2640")

        await self.text("SL 2580 | TP1 2700")
        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "ready")
        self.assertIn("Stop Loss: 2580", draft["text"])
        self.assertIn("TP1: 2700", draft["text"])
        self.assertNotIn(str(original_message_id), draft["text"])
        self.assertNotIn("Trade #", draft["text"])
        self.assertNotIn("Operation", draft["text"])
        self.assertEqual(self.db.trade(tid).get("sl"), "2640")
        self.assertEqual(self.db.trade(tid)["targets"]["1"]["price"], "2670")

        await self.publish_update()
        trade = self.db.trade(tid)
        self.assertEqual(trade["sl"], "2580")
        self.assertEqual(trade["targets"]["1"]["price"], "2700")
        updates = [call for call in self.bot.send_message.await_args_list
                   if call.args[0] == self.config.signals and call.kwargs.get("reply_parameters")]
        self.assertEqual(updates[-1].kwargs["reply_parameters"].message_id, original_message_id)
        self.assertIn("Stop Loss: 2580", updates[-1].args[1])
        self.assertIn("TP1: 2700", updates[-1].args[1])
        self.assertNotIn(str(original_message_id), updates[-1].args[1])
        self.assertNotIn(tid, updates[-1].args[1])
        self.assertNotIn("Original channel post", updates[-1].args[1])

    async def test_custom_update_preview_and_post_hide_internal_references(self):
        tid = await self.signal("SELL")
        original_message_id = self.db.trade(tid)["message_id"]
        await self.click("manage", {"id": tid, "action": "custom"})
        await self.text(
            f"Market remains responsive.\nTrade ID: {tid}\nOperation: 847291\n"
            f"Original channel post #{original_message_id}"
        )

        draft = self.db.draft(42)
        self.assertIn("Market remains responsive.", draft["text"])
        for reference in (tid, "Trade ID", "847291", str(original_message_id), "Original channel post"):
            self.assertNotIn(reference, draft["text"])
        preview = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("Internal references are kept", preview)
        self.assertIn(draft["text"], preview)

        await self.publish_update()
        post = next(call for call in reversed(self.bot.send_message.await_args_list)
                    if call.args[0] == self.config.signals)
        self.assertEqual(post.args[0], self.config.signals)
        self.assertEqual(post.kwargs["reply_parameters"].message_id, original_message_id)
        for reference in (tid, "Trade ID", "847291", str(original_message_id), "Original channel post"):
            self.assertNotIn(reference, post.args[1])
        self.assertEqual(self.db.trade(tid)["id"], tid)

    async def test_duplicate_publish_tap_does_not_post_twice(self):
        tid = await self.signal()
        original_message_id = self.db.trade(tid)["message_id"]
        await self.click("manage", {"id": tid, "action": "sl_tp"})
        await self.text("SL 2580 | TP1 2700")
        markup = self.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
        token = next(button.callback_data for row in markup.inline_keyboard for button in row
                     if button.text == "Publish reviewed message")
        self.u.callback_query.data = token
        await self.ui.callback(self.u, None)
        sent = [call for call in self.bot.send_message.await_args_list
                if call.args[0] == self.config.signals]
        self.assertEqual(len(sent), 2)  # Original signal plus one trade update.
        self.assertEqual(sent[-1].kwargs["reply_parameters"].message_id, original_message_id)
        self.u.callback_query.data = token
        with self.assertRaisesRegex(ValueError, "already used"):
            await self.ui.callback(self.u, None)
        sent_after_duplicate = [call for call in self.bot.send_message.await_args_list
                                if call.args[0] == self.config.signals]
        self.assertEqual(len(sent_after_duplicate), 2)
        self.assertFalse(any(call.args[0] == self.config.analysis
                             for call in self.bot.send_message.await_args_list))
        self.assertEqual(self.db.trade(tid)["sl"], "2580")
        self.assertEqual(self.db.trade(tid)["targets"]["1"]["price"], "2700")

    async def test_partial_update_can_attach_chart_and_uses_one_final_post_button(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "tp"})
        await self.text("1 2700")
        await self.publish_update()
        await self.click("manage", {"id": tid, "action": "partial"})
        await self.click("partial_choice", self.revision(percent="25", mode="reported"))
        await self.click("partial_target_choice", self.revision(target="2700"))
        await self.click("partial_remaining_skip", self.revision())
        draft = self.db.draft(42)
        self.assertEqual(draft["destination"], "signals")
        markup = self.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertIn("Attach chart (optional)", labels)
        self.assertIn("Publish partial update", labels)
        self.assertFalse(any("Choose destination" in label for label in labels))

        channel_posts_before = sum(call.args[0] == self.config.signals
                                   for call in self.bot.send_message.await_args_list)
        await self.click("partial_chart", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "chart")
        await self.upload_zone_chart()
        preview = self.db.draft(42)
        self.assertTrue(preview.get("image"))
        self.assertEqual(preview["step"], "ready")
        self.assertEqual(sum(call.args[0] == self.config.signals
                             for call in self.bot.send_message.await_args_list), channel_posts_before)

        await self.publish_update()
        post = next(call for call in self.bot.send_photo.await_args_list
                    if call.args[0] == self.config.signals)
        self.assertIn("Partial Profits Secured", post.kwargs["caption"])
        self.assertIn("Target: 2700", post.kwargs["caption"])
        self.assertIn("Closed: 25%", post.kwargs["caption"])
        self.assertIn("RISK MANAGEMENT UPDATE", post.kwargs["caption"])
        self.assertIn("Moving SL to breakeven does not eliminate all market risk.",
                      post.kwargs["caption"])
        self.assertEqual(post.kwargs["reply_parameters"].message_id, self.db.trade(tid)["message_id"])
        self.assertEqual(self.db.trade(tid)["targets"]["1"]["price"], "2700")

    async def test_tp_screenshot_advances_from_tp1_to_tp2_and_posts_calculated_pips(self):
        tid = await self.signal()
        initial_screen = self.bot.send_message.await_args_list[-1]
        initial_labels = [button.text for row in initial_screen.kwargs["reply_markup"].inline_keyboard
                          for button in row]
        self.assertIn("📸 Post TP1 Profit Screenshot", initial_labels)
        self.assertFalse(self.db.trade(tid)["targets"]["1"]["hit"])

        channel_photos_before = sum(
            call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list)
        analysis_sends_before = len([
            call for call in (
                self.bot.send_message.await_args_list + self.bot.send_photo.await_args_list
            ) if call.args and call.args[0] == self.config.analysis
        ])
        await self.click(
            "manage", {"id": tid, "action": "tp1_profit_screenshot", "target_number": 1})
        self.assertIn("Upload the TP1 profit screenshot",
                      self.bot.send_message.await_args_list[-1].args[1])
        self.assertEqual(self.db.draft(42)["target_number"], 1)
        self.assertEqual(sum(
            call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list),
            channel_photos_before)

        signal_message_id = self.db.trade(tid)["message_id"]
        draft = self.db.draft(42)
        self.assertEqual(draft["action"], "tp1_profit_screenshot")
        self.assertEqual(draft["destination"], "signals")
        self.assertEqual(draft["step"], "chart")
        with patch("smh.handlers.read_screenshot_prices",
                   return_value={"entry": "2653", "exit": "2670"}):
            await self.upload_zone_chart()

        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "prices_review")
        self.assertEqual(draft["pips"], "170")
        price_review = self.bot.send_message.await_args_list[-1]
        self.assertIn("TP1 SCREENSHOT", price_review.args[1])
        self.assertIn("Calculated result: +170 pips", price_review.args[1])
        self.assertIn("✅ Confirm detected prices", [
            button.text for row in price_review.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])
        await self.click("tp1_screenshot_values_confirm", self.revision())
        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "ready")
        self.assertIn("TP1 HIT — PROFIT SCREENSHOT", draft["text"])
        self.assertIn("Take Profit 1: 2670", draft["text"])
        self.assertIn("Calculated result: +170 pips", draft["text"])
        self.assertTrue(draft["image"])
        self.assertEqual(
            sum(call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list),
            channel_photos_before,
        )
        preview = self.bot.send_message.await_args_list[-1]
        preview_labels = [button.text for row in preview.kwargs["reply_markup"].inline_keyboard
                          for button in row]
        self.assertIn("📤 Publish TP1 Profit Screenshot", preview_labels)
        self.assertIn("Replace TP1 screenshot", preview_labels)
        self.assertIn("❌ Cancel Screenshot", preview_labels)

        self.reopen_runtime()
        await self.click("preview")
        resumed_preview = self.bot.send_message.await_args_list[-1]
        self.assertIn("TP1 HIT — PROFIT SCREENSHOT", resumed_preview.args[1])
        self.assertIn("📤 Publish TP1 Profit Screenshot", [
            button.text for row in resumed_preview.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])
        await self.publish_update()
        post = next(
            call for call in reversed(self.bot.send_photo.await_args_list)
            if call.args[0] == self.config.signals
        )
        self.assertIn("TP1 HIT — PROFIT SCREENSHOT", post.kwargs["caption"])
        self.assertIn("Take Profit 1: 2670", post.kwargs["caption"])
        self.assertEqual(post.kwargs["reply_parameters"].message_id, signal_message_id)
        self.assertEqual(len([
            call for call in (
                self.bot.send_message.await_args_list + self.bot.send_photo.await_args_list
            ) if call.args and call.args[0] == self.config.analysis
        ]), analysis_sends_before)
        self.reopen_runtime()
        saved = self.db.trade(tid)["tp1_profit_screenshot"]
        self.assertTrue(saved["image"].startswith("asset:"))
        self.assertEqual(saved["message_id"], 124)
        self.assertEqual(saved["entry"], "2653")
        self.assertEqual(saved["exit"], "2670")
        self.assertEqual(saved["pips"], "170")
        self.assertEqual(saved["price_movement"], "17")
        self.assertIn("📸 Post TP2 Profit Screenshot", [
            button.text
            for row in self.bot.send_message.await_args_list[-1].kwargs[
                "reply_markup"].inline_keyboard
            for button in row
        ])

        await self.click(
            "manage", {"id": tid, "action": "tp1_profit_screenshot", "target_number": 2})
        self.assertEqual(self.db.draft(42)["target_number"], 2)
        with patch("smh.handlers.read_screenshot_prices",
                   return_value={"entry": "2653", "exit": "2681"}):
            await self.upload_zone_chart()
        draft = self.db.draft(42)
        self.assertEqual(draft["pips"], "280")
        await self.click("tp1_screenshot_values_confirm", self.revision())
        self.assertIn("TP2 HIT — PROFIT SCREENSHOT", self.db.draft(42)["text"])
        self.assertIn("Calculated result: +280 pips", self.db.draft(42)["text"])
        await self.publish_update()
        tp2_post = next(
            call for call in reversed(self.bot.send_photo.await_args_list)
            if call.args[0] == self.config.signals
        )
        self.assertIn("TP2 HIT — PROFIT SCREENSHOT", tp2_post.kwargs["caption"])
        self.assertIn("Calculated result: +280 pips", tp2_post.kwargs["caption"])
        self.assertEqual(tp2_post.kwargs["reply_parameters"].message_id, signal_message_id)
        self.assertNotIn("Post TP", self.bot.send_message.await_args_list[-1].args[1])
        saved_targets = self.db.trade(tid)["target_profit_screenshots"]
        self.assertEqual(set(saved_targets), {"1", "2"})
        with self.assertRaisesRegex(ValueError, "already been published"):
            await self.click(
                "manage", {"id": tid, "action": "tp1_profit_screenshot",
                           "target_number": 1})

    async def test_tp1_profit_screenshot_cancel_and_publishing_off_are_safe(self):
        from dataclasses import replace

        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "tp1_profit_screenshot"})
        draft = self.db.draft(42)
        await self.click("tp1_profit_screenshot_cancel", self.revision())
        self.assertIsNone(self.db.draft(42))
        self.assertFalse(self.db.trade(tid).get("tp1_profit_screenshot"))

        await self.click("manage", {"id": tid, "action": "tp1_profit_screenshot"})
        with patch("smh.handlers.read_screenshot_prices",
                   return_value={"entry": "2653", "exit": "2670"}):
            await self.upload_zone_chart()
        await self.click("tp1_screenshot_values_confirm", self.revision())
        channel_photos_before = sum(
            call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list)
        self.config = replace(self.config, allow_publishing=False, isolated_test=True)
        self.pub.config = self.config
        self.ui.config = self.config
        with self.assertRaisesRegex(ValueError, "locked"):
            await self.publish_update()
        self.assertEqual(
            sum(call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list),
            channel_photos_before,
        )
        self.assertEqual(self.db.trade(tid).get("tp1_profit_screenshot"), None)

    async def test_tp1_screenshot_with_multiple_positions_requires_admin_row_selection(self):
        tid = await self.signal("SELL")
        trade = self.db.trade(tid)
        trade.update(
            market="XAUUSD.s",
            symbol="XAUUSD.s",
            entry="4026.81",
            targets={
                "1": {"price": "4024.81", "hit": False},
                "2": {"price": "4022.81", "hit": False},
            },
            targets_auto=False,
        )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE trades SET data=? WHERE id=?",
                (json.dumps(trade), tid),
            )

        await self.click("manage", {"id": tid, "action": "tp1_profit_screenshot"})
        candidates = [
            {
                "symbol": "XAUUSD.s",
                "direction": "SELL",
                "entry": "4026.81",
                "exit": "4022.65",
            },
            {
                "symbol": "XAUUSD.s",
                "direction": "SELL",
                "entry": "4027.81",
                "exit": "4022.65",
            },
        ]
        channel_photos_before = sum(
            call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list)
        with patch("smh.handlers.read_screenshot_prices",
                   return_value={"candidates": candidates}):
            await self.upload_zone_chart()

        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "candidate_choice")
        screen = self.bot.send_message.await_args_list[-1]
        self.assertIn("more than one matching position", screen.args[1])
        options = [
            button.text
            for row in screen.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertEqual(len([text for text in options if text.startswith("Use XAUUSD.s")]), 2)
        self.assertTrue(any("+42 pips" in text for text in options))
        self.assertTrue(all(len(text) <= 64 for text in options))
        self.assertEqual(
            sum(call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list),
            channel_photos_before,
        )

        await self.click(
            "tp1_screenshot_candidate_choose",
            self.revision(index=0),
        )
        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "prices_review")
        self.assertEqual(draft["observed_entry"], "4026.81")
        self.assertEqual(draft["observed_exit"], "4022.65")
        self.assertEqual(draft["pips"], "42")
        self.assertEqual(draft["detected_position"]["symbol"], "XAUUSD.s")
        self.assertIn("Entry price: 4026.81", self.bot.send_message.await_args_list[-1].args[1])
        self.assertEqual(
            sum(call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list),
            channel_photos_before,
        )

        await self.click("tp1_screenshot_values_confirm", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "ready")
        self.assertEqual(
            sum(call.args[0] == self.config.signals for call in self.bot.send_photo.await_args_list),
            channel_photos_before,
        )

    async def test_tp1_screenshot_unreadable_prices_require_manual_entry_and_confirmation(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "tp1_profit_screenshot"})
        with patch("smh.handlers.read_screenshot_prices", return_value=None):
            await self.upload_zone_chart()

        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "prices_manual_input")
        self.assertIn("No values were guessed", draft["ocr_issue"])
        with self.assertRaisesRegex(ValueError, "not reached TP"):
            await self.text("2670 | 2653")
        await self.text("2653 | 2670")
        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "prices_review")
        self.assertEqual(draft["price_source"], "administrator entry")
        self.assertEqual(draft["pips"], "170")
        self.assertFalse(draft.get("prices_confirmed", False))
        await self.click("tp1_screenshot_values_confirm", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "ready")
        self.assertTrue(self.db.draft(42)["prices_confirmed"])

    async def test_second_partial_template_requires_published_breakeven_confirmation(self):
        tid = await self.signal()

        # Record an entry and TP so the partial and breakeven controls have confirmed values.
        await self.click("manage", {"id": tid, "action": "entry"})
        await self.text("2600")
        await self.text("skip")
        await self.text("skip")
        await self.publish_update()
        await self.click("manage", {"id": tid, "action": "tp"})
        await self.text("1 2700")
        await self.publish_update()

        async def prepare_reported_partial():
            await self.click("manage", {"id": tid, "action": "partial"})
            await self.click("partial_choice", self.revision(percent="25", mode="reported"))
            await self.click("partial_target_choice", self.revision(target="2700"))
            await self.click("partial_remaining_skip", self.revision())

        await prepare_reported_partial()
        first_draft = self.db.draft(42)
        self.assertEqual(first_draft["trade"]["partial_count"], 1)
        self.assertIn("RISK MANAGEMENT UPDATE", first_draft["text"])
        self.assertNotIn("SECOND PARTIAL UPDATE", first_draft["text"])
        await self.publish_update()
        self.assertEqual(self.db.trade(tid)["partial_count"], 1)
        self.assertFalse(self.db.trade(tid).get("breakeven_confirmed", False))
        self.reopen_runtime()
        self.assertEqual(self.db.trade(tid)["partial_count"], 1)

        # A second partial before the explicit BE action must not claim SL is at breakeven.
        await prepare_reported_partial()
        second_draft = self.db.draft(42)
        self.assertEqual(second_draft["trade"]["partial_count"], 2)
        self.assertNotIn("SECOND PARTIAL UPDATE", second_draft["text"])
        await self.click("cancel")

        await self.click("manage", {"id": tid, "action": "be"})
        await self.click("be_confirm", self.revision())
        self.assertFalse(self.db.trade(tid).get("breakeven_confirmed", False))
        await self.publish_update()
        self.assertTrue(self.db.trade(tid)["breakeven_confirmed"])

        await prepare_reported_partial()
        second_after_be = self.db.draft(42)
        self.assertEqual(second_after_be["trade"]["partial_count"], 2)
        self.assertIn("SECOND PARTIAL UPDATE", second_after_be["text"])
        await self.publish_update()
        self.assertEqual(self.db.trade(tid)["partial_count"], 2)

    async def test_partial_profit_rejects_unrelated_target_price(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "partial"})
        await self.click("partial_choice", self.revision(percent="50", mode="reported"))
        with self.assertRaisesRegex(ValueError, "listed take-profit target"):
            await self.click("partial_target_choice", self.revision(target="9999"))
        self.assertEqual(self.db.draft(42)["step"], "partial_target")
        self.assertEqual(self.db.trade(tid)["targets"]["1"]["price"], "2670")
        self.assertEqual(self.db.trade(tid)["targets"]["2"]["price"], "2680")

    async def test_pending_partial_target_prompt_recovers_after_database_reopen(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "tp"})
        await self.text("1 2700")
        await self.publish_update()
        await self.click("manage", {"id": tid, "action": "partial"})
        await self.click("partial_choice", self.revision(percent="50", mode="reported"))
        self.assertEqual(self.db.draft(42)["step"], "partial_target")
        channel_posts_before = sum(call.args[0] == self.config.signals
                                   for call in self.bot.send_message.await_args_list)

        self.reopen_runtime()
        await self.ui.preview(self.u)
        self.assertEqual(self.db.draft(42)["step"], "partial_target")
        labels = [button.text for row in self.bot.send_message.await_args_list[-1].kwargs[
            "reply_markup"].inline_keyboard for button in row]
        self.assertIn("TP1 · 2700", labels)
        self.assertEqual(sum(call.args[0] == self.config.signals
                             for call in self.bot.send_message.await_args_list), channel_posts_before)

    async def test_tp_hit_requires_number_and_partial_or_final_and_recovers(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "tp"})
        await self.text("1 2700")
        await self.publish_update()
        original_message_id = self.db.trade(tid)["message_id"]

        await self.click("manage", {"id": tid, "action": "hit"})
        self.assertEqual(self.db.draft(42)["step"], "hit_target")
        target_labels = [button.text for row in self.bot.send_message.await_args_list[-1].kwargs[
            "reply_markup"].inline_keyboard for button in row]
        self.assertIn("TP1 · 2700", target_labels)
        await self.click("hit_target_choice", self.revision(target="1"))
        self.assertEqual(self.db.draft(42)["step"], "hit_status")

        self.reopen_runtime()
        await self.ui.preview(self.u)
        status_markup = self.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
        statuses = [button.text for row in status_markup.inline_keyboard for button in row]
        self.assertIn("Partial target", statuses)
        self.assertIn("Final target", statuses)
        await self.click("hit_status", self.revision(status="final"))
        self.assertIn("Status: FINAL TARGET", self.db.draft(42)["text"])
        await self.publish_update()

        trade = self.db.trade(tid)
        self.assertTrue(trade["targets"]["1"]["hit"])
        self.assertEqual(trade["targets"]["1"]["hit_status"], "final")
        update_post = next(call for call in self.bot.send_message.await_args_list
                           if call.args[0] == self.config.signals and
                           "TP1 Hit" in call.args[1])
        self.assertEqual(update_post.kwargs["reply_parameters"].message_id, original_message_id)

    async def test_uncertain_chart_partial_update_is_not_retried(self):
        from telegram.error import NetworkError
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "partial"})
        await self.click("partial_choice", self.revision(percent="50", mode="recommendation"))
        await self.click("partial_chart", self.revision())
        await self.upload_zone_chart()

        async def send_photo(chat_id, image, **kwargs):
            if chat_id == self.config.signals:
                raise NetworkError("partial update send timed out")
            return NS(message_id=124)
        self.bot.send_photo.side_effect = send_photo
        op = self.pub.prepare(42, "update", self.db.draft(42))
        with self.assertRaisesRegex(ValueError, "uncertain"):
            await self.pub.send(42, op)
        with self.assertRaisesRegex(ValueError, "uncertain"):
            await self.pub.send(42, op)
        self.assertEqual(self.pub.operation(op)[0]["status"], "uncertain")
        self.assertEqual(sum(call.args[0] == self.config.signals
                             for call in self.bot.send_photo.call_args_list), 1)

    async def test_add_entry_validates_sl_tp_and_keeps_values_draft_only_until_publish(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "entry"})
        await self.text("2600")
        self.assertEqual(self.db.draft(42)["step"], "sl")
        await self.text("0")
        self.assertEqual(self.db.draft(42)["step"], "sl")
        self.assertIn("positive price", self.bot.send_message.await_args_list[-1].args[1])
        await self.text("2580")
        self.assertEqual(self.db.draft(42)["step"], "tp")
        await self.text("take profit later")
        self.assertEqual(self.db.draft(42)["step"], "tp")
        self.assertIn(
            "take-profit number and price",
            self.bot.send_message.await_args_list[-1].args[1],
        )
        self.assertEqual(self.db.trade(tid)["entry"], "2653")
        await self.text("1 2700")
        draft = self.db.draft(42)
        self.assertEqual(draft["step"], "ready")
        self.assertIn("Entry: 2600", draft["text"])
        self.assertIn("Stop Loss: 2580", draft["text"])
        self.assertIn("TP1: 2700", draft["text"])
        self.assertNotIn(tid, draft["text"])
        self.assertNotIn("Trade #", draft["text"])
        self.assertNotIn("Original channel post", draft["text"])
        self.assertEqual(self.db.trade(tid)["entry"], "2653")
        await self.publish_update()
        trade = self.db.trade(tid)
        self.assertEqual((trade["entry"], trade["sl"], trade["targets"]["1"]["price"]),
                         ("2600", "2580", "2700"))

    async def test_add_entry_can_leave_unsupplied_sl_and_tp_unset(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "entry"})
        await self.text("2650")
        await self.text("skip")
        await self.text("skip")
        self.assertIn("Stop Loss: 2640", self.db.draft(42)["text"])
        self.assertIn("TP1: 2650.20", self.db.draft(42)["text"])
        self.assertNotIn(tid, self.db.draft(42)["text"])
        self.assertNotIn("Operation", self.db.draft(42)["text"])
        self.assertEqual(self.db.trade(tid)["entry"], "2653")
        await self.publish_update()
        trade = self.db.trade(tid)
        self.assertEqual(trade["entry"], "2650")
        self.assertEqual(trade["sl"], "2640")
        self.assertEqual(trade["targets"]["1"]["price"], "2650.20")

    async def test_cancel_setup_and_close_skip(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "cancel"})
        await self.text("The setup confirmation was withdrawn.")
        await self.publish_update()
        self.assertEqual(self.db.trade(tid)["state"], "INVALIDATED")
        with self.assertRaisesRegex(ValueError, "Only open trades"):
            await self.ui.manage(self.u, tid, "sl")
        tid = await self.signal("SELL")
        await self.click("manage", {"id": tid, "action": "close"})
        await self.click("choose_value", self.revision(value="Unrecorded"))
        await self.click("close_skip", self.revision())
        await self.publish_update()
        self.assertEqual(self.db.trade(tid)["state"], "CLOSED")

    async def test_active_setup_invalidation_requires_reason_and_removes_controls(self):
        tid = await self.signal()
        await self.click("manage", {"id": tid, "action": "entry"})
        await self.text("2600")
        await self.text("skip")
        await self.text("skip")
        await self.publish_update()
        self.assertEqual(self.db.trade(tid)["state"], "ACTIVE")

        await self.click("manage", {"id": tid, "action": "invalidate"})
        await self.text("The confirmed zone failed.")
        await self.publish_update()
        trade = self.db.trade(tid)
        self.assertEqual(trade["state"], "INVALIDATED")
        self.assertEqual(trade["reason"], "The confirmed zone failed.")
        with self.assertRaisesRegex(ValueError, "Only open trades"):
            await self.ui.manage(self.u, tid, "sl")

        await self.click("trade", {"id": tid})
        labels = [button.text for row in self.bot.send_message.await_args_list[-1].kwargs[
            "reply_markup"].inline_keyboard for button in row]
        self.assertEqual(labels, [
            "📸 Capture Signal Screenshot",
            "📤 Post Result to Market Analysis Group",
            "📋 Trade Details",
            "↩️ Back to Admin",
        ])

    async def test_chart_upload_annotation_caption_and_publish(self):
        await self.click("new_analysis")
        await self.click("template", {"name": "Higher-timeframe bias"})
        await self.text("H4 bullish bias. Liquidity above the recent high.")
        await self.click("upload")
        async def download(path):
            Image.new("RGB", (800, 600), "#203040").save(path, format="PNG")
        self.u.message.photo = [NS(file_size=1000, get_file=AsyncMock(return_value=NS(download_to_drive=download)))]
        await self.ui.photo(self.u, None)
        await self.click("annotate")
        await self.text("zone 10 20 80 50 FVG\nlabel 20 10 POI")
        await self.click("annotate")
        await self.click("undo", self.revision())
        await self.click("caption")
        await self.text("H4 structure: bullish bias. Manual POI shown.")
        await self.click("analysis_publish")
        await self.click("destination", self.revision(destination="analysis"))
        await self.click("publish", self.revision())
        self.assertEqual(self.db.rows("SELECT kind FROM operations")[0]["kind"], "analysis")
        self.assertEqual(self.bot.send_photo.call_args.args[0], -1002)

    async def test_analysis_zone_bundle_shows_formatted_review_then_posts_separately(self):
        await self.prepare_analysis_zone_bundle()
        draft = self.db.draft(42)
        chart_ref = draft["image"]
        self.assertEqual(draft["destination"], "analysis")
        self.assertEqual(draft["pro_zone"]["image"], chart_ref)

        private_previews = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == 42 and "PRO SIGNALS" in str(call.kwargs.get("caption", ""))
        ]
        self.assertTrue(private_previews)
        self.assertIn("<b>", private_previews[-1].kwargs["caption"])
        review_text = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("PRO SIGNALS POSTS — PRIVATE REVIEW", review_text)
        self.assertIn("Gold/XAUUSD · 2650–2655 · M15", review_text)
        self.assertIn("same chart will be included", review_text)
        self.assertIn("Market Analysis is posted first", review_text)
        review_buttons = [
            button.text
            for row in self.bot.send_message.await_args_list[-1].kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("📤 Publish Analysis + PRO POI", review_buttons)

        await self.click("publish", self.revision())
        channel_posts = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] in (self.config.signals, self.config.analysis)
        ]
        self.assertEqual(
            [call.args[0] for call in channel_posts],
            [self.config.analysis, self.config.signals],
        )
        operations = self.db.rows(
            "SELECT id,kind,status,payload FROM operations ORDER BY created,id")
        self.assertEqual([row["kind"] for row in operations], ["setup", "analysis"])
        self.assertEqual([row["status"] for row in operations], ["done", "done"])
        setup = self.db.get("active_setup")
        self.assertEqual(setup["market_analysis_operation_id"], operations[1]["id"])
        self.assertEqual(setup["market_analysis_message_id"], 124)
        self.assertEqual(self.db.rows("SELECT * FROM trades"), [])

    async def test_analysis_zone_bundle_off_sends_nothing_and_creates_no_operations(self):
        from dataclasses import replace

        await self.prepare_analysis_zone_bundle()
        self.config = replace(self.config, allow_publishing=False)
        self.pub.config = self.config
        self.ui.config = self.config
        await self.click("publish", self.revision())

        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assertFalse(any(
            call.args[0] in (self.config.signals, self.config.analysis)
            for call in self.bot.send_photo.await_args_list
        ))
        self.assertEqual(self.db.draft(42)["kind"], "analysis")

    async def test_analysis_publishes_first_then_each_labeled_poi_to_pro(self):
        from smh import zones

        self.analysis_draft_with_chart()
        draft = self.db.draft(42)
        draft["text"] = (
            "📊 SMART MONEY HUB | MARKET ANALYSIS\n\n"
            "📍 MARKET: Gold Spot / U.S. Dollar (XAUUSD)\n"
            "⏱️ TIMEFRAME: 1h\n\n"
            "🎯 KEY AREAS OF INTEREST\n"
            "BUY POI (approx 3,989.21 - 4,007.00) and "
            "SELL POI (approx 4,107.96 - 4,087.28)\n\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        self.db.save_draft(42, draft)

        await self.click("preview")
        draft = self.db.draft(42)
        self.assertEqual(len(draft["pro_zones"]), 2)
        self.assertEqual(
            [item["setup"]["poi_direction"] for item in draft["pro_zones"]],
            ["BUY", "SELL"],
        )
        self.assertTrue(all(item["independent"] for item in draft["pro_zones"]))
        self.assertTrue(all(
            item["image"] == draft["image"] for item in draft["pro_zones"]
        ))
        review_text = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("POI 1 (BUY POI)", review_text)
        self.assertIn("POI 2 (SELL POI)", review_text)
        self.assertIn("final confirmation publishes the reviewed set", review_text)
        private_previews = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == 42 and "PRIVATE PREVIEW" in call.kwargs.get("caption", "")
        ]
        self.assertEqual(len(private_previews), 2)

        await self.click("publish", self.revision())
        destination_order = [
            call.args[0]
            for call in self.bot.send_photo.await_args_list
            if call.args[0] in (self.config.signals, self.config.analysis)
        ]
        self.assertEqual(
            destination_order,
            [self.config.analysis, self.config.signals, self.config.signals],
        )
        setup_posts = [
            call for call in self.bot.send_photo.await_args_list
            if call.args[0] == self.config.signals
        ]
        self.assertIn("<b>BUY POI</b>", setup_posts[0].kwargs["caption"])
        self.assertIn("<b>SELL POI</b>", setup_posts[1].kwargs["caption"])
        self.assertEqual(
            self.db.rows("SELECT kind,status FROM operations WHERE kind='setup'"),
            [{"kind": "setup", "status": "done"}] * 2,
        )
        active = zones.active_setups(self.db)
        self.assertEqual(len(active), 2)
        self.assertTrue(all(
            setup["market_analysis_message_id"] == 124 for setup in active
        ))
        self.assertEqual(self.db.rows("SELECT * FROM trades"), [])

    async def test_malformed_market_analysis_poi_blocks_both_posts(self):
        self.analysis_draft_with_chart()
        draft = self.db.draft(42)
        draft["text"] = (
            "MARKET: XAUUSD\nTIMEFRAME: M15\n"
            "POI ZONE: 4,124.00"
        )
        self.db.save_draft(42, draft)

        await self.click("preview")
        message = self.bot.send_message.await_args_list[-1]
        self.assertIn("cannot prepare its PRO post safely", message.args[1])
        self.assertIn("exactly two readable prices", message.args[1])
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assertFalse(any(
            call.args[0] in (self.config.signals, self.config.analysis)
            for call in self.bot.send_photo.await_args_list
        ))

    async def test_automatic_multi_poi_bundle_is_blocked_when_publishing_is_off(self):
        from dataclasses import replace

        self.config = replace(self.config, allow_publishing=False)
        self.pub.config = self.config
        self.ui.config = self.config
        self.analysis_draft_with_chart()
        draft = self.db.draft(42)
        draft["text"] = (
            "MARKET: XAUUSD\nTIMEFRAME: M15\n"
            "BUY POI: 4124.00 - 4132.00\n"
            "SELL POI: 4107.00 - 4113.00"
        )
        self.db.save_draft(42, draft)

        await self.click("preview")
        self.assertEqual(len(self.db.draft(42)["pro_zones"]), 2)
        await self.click("publish", self.revision())

        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assertFalse(any(
            call.args[0] in (self.config.signals, self.config.analysis)
            for call in self.bot.send_photo.await_args_list
        ))
        self.assertEqual(self.db.draft(42)["kind"], "analysis")
        self.assertIn("Publishing is OFF", self.bot.send_message.await_args_list[-1].args[1])

    async def test_analysis_first_bundle_retries_only_rejected_post_after_explicit_tap(self):
        from telegram.error import Forbidden

        await self.prepare_analysis_zone_bundle()
        self.bot.send_photo.reset_mock()
        self.bot.send_photo.side_effect = Forbidden("mocked permission rejection")
        await self.click("publish", self.revision())

        rows = self.db.rows("SELECT id,kind,status FROM operations ORDER BY created,id")
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {(row["kind"], row["status"]) for row in rows},
            {("setup", "prepared"), ("analysis", "failed")},
        )
        self.assertEqual([call.args[0] for call in self.bot.send_photo.await_args_list],
                         [self.config.analysis])

        self.bot.send_photo.side_effect = None
        await self.click("analysis_zone_retry", {"operation_kind": "analysis"})
        rows = self.db.rows("SELECT id,kind,status FROM operations ORDER BY created,id")
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {(row["kind"], row["status"]) for row in rows},
            {("setup", "done"), ("analysis", "failed"), ("analysis", "done")},
        )
        self.assertEqual(
            [call.args[0] for call in self.bot.send_photo.await_args_list],
            [self.config.analysis, self.config.analysis, self.config.signals],
        )
        calls_before_duplicate = self.bot.send_photo.await_count
        completed_setup = self.db.rows(
            "SELECT id FROM operations WHERE kind='setup' AND status='done'")
        self.assertIn(
            "Already completed",
            await self.pub.send(42, completed_setup[0]["id"]),
        )
        self.assertEqual(self.bot.send_photo.await_count, calls_before_duplicate)

    async def test_uncertain_analysis_send_reconciles_before_pro_poi_continues(self):
        await self.prepare_analysis_zone_bundle()
        self.bot.send_photo.reset_mock()
        self.bot.send_photo.side_effect = RuntimeError("simulated network timeout")
        await self.click("publish", self.revision())

        analysis_operation = self.db.rows(
            "SELECT id,status FROM operations WHERE kind='analysis'")[0]
        self.assertEqual(analysis_operation["status"], "uncertain")
        self.assertEqual(
            self.db.rows("SELECT status FROM operations WHERE kind='setup'")[0]["status"],
            "prepared",
        )
        self.assertEqual([call.args[0] for call in self.bot.send_photo.await_args_list],
                         [self.config.analysis])

        self.bot.send_photo.side_effect = None
        await self.click("operation", {"id": analysis_operation["id"]})
        await self.click("reconcile", {"id": analysis_operation["id"]})
        await self.text("9876")
        await self.click("reconcile_confirm", self.revision())
        self.assertEqual(self.db.draft(42)["kind"], "analysis")
        self.assertEqual(self.db.draft(42)["publish_bundle"]["setup"],
                         self.db.rows("SELECT id FROM operations WHERE kind='setup'")[0]["id"])

        await self.click("analysis_zone_publish")
        self.assertEqual([call.args[0] for call in self.bot.send_photo.await_args_list],
                         [self.config.analysis, self.config.signals])
        self.assertEqual(
            self.db.rows("SELECT status FROM operations WHERE kind='setup'")[0]["status"],
            "done",
        )
        self.assertEqual(
            self.db.rows("SELECT status FROM operations WHERE kind='analysis'")[0]["status"],
            "done",
        )

    async def test_attached_zone_details_can_be_edited_before_final_publish(self):
        await self.prepare_analysis_zone_bundle()
        await self.click("analysis_pro_zone_edit", self.revision())
        await self.click("zone_wizard_edit", self.revision())
        await self.click("zone_wizard_edit_field", self.revision(field="low"))
        await self.text("2651")
        await self.click("zone_wizard_confirm", self.revision())
        self.assertEqual(self.db.draft(42)["step"], "ready")
        await self.click("analysis_pro_zone_attach", self.revision())
        self.assertEqual(
            self.db.draft(42)["pro_zone"]["setup"]["zone"], "2651–2655")
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])

    async def test_cancelling_attached_zone_details_restores_analysis_without_posting(self):
        self.analysis_draft_with_chart()
        await self.click("analysis_pro_zone_add", self.revision())
        await self.fill_zone_wizard(
            market="Gold", low="2650", high="2655", confirmation="M5 shift",
            confirm=False,
        )
        await self.click("zone_wizard_cancel", self.revision())
        draft = self.db.draft(42)
        self.assertEqual(draft["kind"], "analysis")
        self.assertEqual(draft["text"].splitlines()[0],
                         "📊 SMART MONEY HUB | MARKET ANALYSIS")
        self.assertNotIn("pro_zone", draft)
        self.assertEqual(self.db.rows("SELECT * FROM operations"), [])
        self.assertFalse(any(
            call.args[0] in (self.config.signals, self.config.analysis)
            for call in self.bot.send_photo.await_args_list
        ))

    async def test_annotate_without_chart_starts_draft_and_guides_upload(self):
        await self.click("annotate")
        draft = self.db.draft(42)
        self.assertEqual(draft["kind"], "analysis")
        self.assertEqual(draft["step"], "upload")
        message = self.bot.send_message.await_args_list[-1]
        self.assertIn("add your own labels, lines, arrows, and marked zones", message.args[1])
        self.assertIn("original image is kept unchanged", message.args[1])
        self.assertIn("does not infer prices", message.args[1])
        labels = [
            button.text for row in message.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertEqual(labels, [
            "📸 Upload Chart Now", "Cancel Draft", "↩️ Analysis & Drafts",
        ])

        await self.click("upload")
        self.assertEqual(self.db.draft(42)["step"], "upload")
        self.assertIn("Send a chart as a photo", self.bot.send_message.await_args_list[-1].args[1])

    async def test_annotate_does_not_replace_another_active_draft(self):
        self.db.save_draft(42, {"kind": "zone", "step": "chart", "setup": {"market": "Gold"}})
        await self.click("annotate")
        self.assertEqual(self.db.draft(42)["kind"], "zone")
        message = self.bot.send_message.await_args_list[-1]
        self.assertIn("another draft in progress", message.args[1])
        labels = [
            button.text for row in message.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Resume Current Draft", labels)
        self.assertIn("Cancel Current Draft", labels)

    async def test_unverified_chart_review_publishes_only_to_analysis_with_branded_image(self):
        from dataclasses import replace
        from unittest.mock import patch

        await self.click("new_analysis")
        await self.click("upload")
        chart = Path(__file__).parent / "fixtures" / "test_only_zone_chart.png"

        async def download(path):
            shutil.copyfile(chart, path)

        item = NS(
            file_size=chart.stat().st_size,
            get_file=AsyncMock(return_value=NS(download_to_drive=AsyncMock(side_effect=download))),
        )
        self.u.message.photo = [item]
        self.u.message.document = None
        self.u.message.caption = None
        production_config = self.ui.config
        self.ui.config = replace(production_config, isolated_test=True)
        try:
            with patch("smh.chart_analysis.shutil.which", return_value=None):
                await self.ui.photo(self.u, None)
        finally:
            self.ui.config = production_config

        draft = self.db.draft(42)
        self.assertEqual(draft["recognition"]["status"], "unavailable")
        self.assertIn("Unknown — manual review required", draft["text"])
        self.assertNotEqual(draft["original"], draft["image"])
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM operations")[0]["n"], 0)
        self.assertTrue(all(call.args[0] == 42 for call in self.bot.send_photo.await_args_list))
        review_image_path = Path(self.db.image_path(draft["image"]))
        preview_image_paths = {
            Path(call.args[1].name)
            for call in self.bot.send_photo.await_args_list
            if len(call.args) > 1 and getattr(call.args[1], "name", None)
        }
        self.assertIn(review_image_path, preview_image_paths)
        preview = self.bot.send_message.await_args_list[-1]
        self.assertIn("LOCAL CHART REVIEW — DRAFT", preview.args[1])
        self.assertIn("No automatic zones were drawn", preview.args[1])
        labels = [button.text for row in preview.kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertIn("✏️ Correct chart fields", labels)
        self.assertIn("Cancel Draft", labels)

        await self.click("chart_fields", self.revision())
        self.assertIn("Market: Unknown", self.bot.send_message.await_args_list[-1].args[1])
        await self.text(
            "Market: XAUUSD\nTimeframe: M15\nProposed zones: 4150–4155\n"
            "Directional bias: Unknown"
        )
        self.assertIn("Market: XAUUSD", self.db.draft(42)["text"])
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM operations")[0]["n"], 0)

        await self.click("destination", self.revision(destination="analysis"))
        ready = self.bot.send_message.await_args_list[-1]
        ready_labels = [button.text for row in ready.kwargs["reply_markup"].inline_keyboard
                        for button in row]
        self.assertIn("Approve & Publish Analysis", ready_labels)
        self.assertEqual(self.db.draft(42)["step"], "ready")
        with self.assertRaisesRegex(ValueError, "not allowed"):
            self.pub.prepare(42, "analysis", {
                **self.db.draft(42),
                "destination": "signals",
            })
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM operations")[0]["n"], 0)

        await self.click("publish", self.revision())
        operation = self.db.rows("SELECT payload FROM operations WHERE kind='analysis'")[0]
        payload = json.loads(operation["payload"])
        self.assertEqual(payload["destination"], "analysis")
        self.assertNotEqual(payload["image"], payload["original"])
        sent_path = Path(self.bot.send_photo.await_args_list[-1].args[1].name)
        self.assertEqual(self.bot.send_photo.await_args_list[-1].args[0], -1002)
        self.assertEqual(sent_path, Path(self.db.image_path(payload["image"])))
        self.assertNotEqual(sent_path, Path(self.db.image_path(payload["original"])))

    async def test_gemini_chart_analysis_stays_private_until_admin_approval(self):
        from unittest.mock import patch

        generated = (
            "📍 MARKET: XAUUSD\n"
            "⏱️ TIMEFRAME: M15\n\n"
            "🎯 KEY AREAS OF INTEREST:\n\n"
            "🩷 POI ZONE: The blue rectangle is your marked POI; exact bounds are unclear.\n"
            "➖ REFERENCE LEVEL: Not clearly visible.\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🔎 WHAT WE’RE WATCHING:\n\n"
            "Price reaction around your marked POI and surrounding market structure.\n\n"
            "We need to observe:\n"
            "💧 Liquidity behaviour\n"
            "📉 Displacement\n"
            "🔄 CHoCH / BOS\n"
            "📊 FVG formation\n"
            "🎯 Retest and entry confirmation\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🚦 CONFIRMATION STATUS:\n\n"
            "⚠️ Confirmation has not yet been established.\n\n"
            "❌ NO CONFIRMATION, NO ENTRY.\n\n"
            "Do not enter simply because price reaches the POI. Wait for the required "
            "confirmation before considering a trade.\n\n"
            "🛡️ Protect your capital and manage your risk responsibly.\n\n"
            "SMART MONEY HUB\n"
            "Learn • Confirm • Execute • Grow 🎯"
        )
        await self.click("new_analysis")
        start = self.bot.send_message.await_args_list[-1]
        start_labels = [
            button.text for row in start.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("⚡ Quick Chart Review", start_labels)
        await self.click("analysis_ai")
        await self.text("My POI is the blue rectangle; watch for a close back above it.")
        self.assertEqual(self.db.draft(42)["step"], "ai_upload")

        with patch("smh.handlers.analyze_chart_with_gemini", return_value=generated) as analyze:
            await self.upload_zone_chart()
        draft = self.db.draft(42)
        self.assertEqual(draft["ai_analysis"]["provider"], "Gemini")
        self.assertIn("blue rectangle", draft["text"])
        analysis_title_at = draft["text"].find("📊 SMART MONEY HUB | MARKET ANALYSIS")
        chart_context_at = draft["text"].find("📍 MARKET:")
        self.assertGreaterEqual(analysis_title_at, 0)
        self.assertGreater(chart_context_at, analysis_title_at)
        self.assertNotIn("AI DRAFT", draft["text"].upper())
        self.assertEqual(
            draft["ai_analysis"]["watch_note"],
            "My POI is the blue rectangle; watch for a close back above it.",
        )
        analyze.assert_called_once()
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM operations")[0]["n"], 0)
        self.assertFalse([
            call for call in self.bot.send_photo.await_args_list
            if call.args and call.args[0] in (self.config.signals, self.config.analysis)
        ])
        review = self.bot.send_message.await_args_list[-1]
        self.assertIn("PRIVATE CHART REVIEW", review.args[1])
        self.assertIn("Review analysis", review.args[1])
        self.assertNotIn("DRAFT", review.args[1].upper())
        await self.click("destination", self.revision(destination="analysis"))
        review = self.bot.send_message.await_args_list[-1]
        labels = [
            button.text for row in review.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("✏️ Edit Market Analysis", labels)
        self.assertNotIn("Approve & Publish Analysis", labels)
        self.assertIn("cannot prepare its PRO post safely", review.args[1])

    async def test_gemini_chart_failure_has_manual_fallback_without_publish(self):
        from unittest.mock import patch
        from smh.gemini_analysis import GeminiAnalysisError

        await self.click("new_analysis")
        await self.click("analysis_ai")
        await self.click("analysis_ai_skip", self.revision())
        chart = Path(__file__).parent / "fixtures" / "test_only_zone_chart.png"

        async def download(path):
            shutil.copyfile(chart, path)

        self.u.message.photo = [NS(
            file_size=chart.stat().st_size,
            get_file=AsyncMock(return_value=NS(
                download_to_drive=AsyncMock(side_effect=download))),
        )]
        self.u.message.document = None
        self.u.message.caption = None
        with patch(
                "smh.handlers.analyze_chart_with_gemini",
                side_effect=GeminiAnalysisError("Gemini is temporarily rate-limited.")):
            await self.ui.photo(self.u, None)
        self.u.message.photo = []
        self.assertEqual(self.db.draft(42)["step"], "ai_error")
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM operations")[0]["n"], 0)
        error_message = self.bot.send_message.await_args_list[-1]
        self.assertIn("No analysis was posted", error_message.args[1])
        labels = [
            button.text for row in error_message.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("Continue with manual review", labels)
        self.assertFalse(any("Publish" in label for label in labels))
        await self.click("analysis_ai_manual")
        self.assertNotIn("ai_analysis", self.db.draft(42))
        self.assertEqual(self.db.draft(42)["step"], "ready")
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM operations")[0]["n"], 0)

    async def test_production_chart_upload_does_not_invoke_ocr(self):
        await self.click("new_analysis")
        await self.click("upload")
        chart = Path(__file__).parent / "fixtures" / "test_only_zone_chart.png"

        async def download(path):
            shutil.copyfile(chart, path)

        self.u.message.photo = [NS(
            file_size=chart.stat().st_size,
            get_file=AsyncMock(return_value=NS(download_to_drive=AsyncMock(side_effect=download))),
        )]
        self.u.message.document = None
        self.u.message.caption = None
        with patch("smh.chart_analysis._run_local_ocr") as run_ocr:
            run_ocr.side_effect = AssertionError("Production must not invoke OCR.")
            await self.ui.photo(self.u, None)
        run_ocr.assert_not_called()
        report = self.db.draft(42)["recognition"]
        self.assertEqual(report["status"], "disabled")
        self.assertEqual(report["engine"], "Disabled outside isolated test")
        self.assertIn("isolated test bot", report["uncertainty"])

    async def test_nonadmin_cannot_upload_chart_for_analysis(self):
        get_file = AsyncMock()
        self.u.effective_user.id = 77
        self.u.message.photo = [NS(file_size=1, get_file=get_file)]
        with self.assertRaises(PermissionError):
            await self.ui.photo(self.u, None)
        get_file.assert_not_awaited()

    async def test_uncertain_analysis_send_is_quarantined_without_retry(self):
        from telegram.error import NetworkError

        chart = Path(__file__).parent / "fixtures" / "test_only_zone_chart.png"
        op = self.pub.prepare(42, "analysis", {
            "destination": "analysis",
            "text": "Visual chart observations require manual review.",
            "image": str(chart),
        })
        self.bot.send_photo.side_effect = NetworkError("simulated timeout")
        with self.assertRaisesRegex(ValueError, "uncertain result"):
            await self.pub.send(42, op)
        row, _ = self.pub.operation(op)
        self.assertEqual(row["status"], "uncertain")
        with self.assertRaisesRegex(ValueError, "uncertain or not retryable"):
            await self.pub.send(42, op)
        self.assertEqual(self.bot.send_photo.await_count, 1)

    async def test_readonly_menus_history_filters_and_maintenance(self):
        tid = await self.signal()
        for action in ("menu", "controls", "trades", "history", "applications", "settings", "health", "errors", "backup", "cleanup", "operations"):
            await self.click(action)
        await self.click("trade", {"id": tid})
        await self.click("timeline", {"id": tid})
        await self.click("history_filter")
        await self.text("market=Gold/XAUUSD; direction=BUY; status=CONFIRMED_BUY; from=2020-01-01; to=2099-01-01")
        await self.click("history_filter")
        await self.text("all")
        await self.click("cancel")
        self.bot.send_document.assert_awaited_once()

    async def test_admin_menu_groups_actions_into_scoped_categories(self):
        await self.click("menu")
        root = self.bot.send_message.await_args_list[-1]
        root_labels = [
            button.text for row in root.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertEqual(root_labels, [
            "📍 Zone & Signals",
            "💼 Trade Management",
            "📊 Analysis & Drafts",
            "👥 Members & Access",
            "⚙️ System & Records",
        ])
        self.assertNotIn("📨 Applications / Member Access", root_labels)
        self.assertNotIn("💾 Backup Database", root_labels)

        expected = {
            "trades": {
                "📋 Active Trades", "📤 Pending Result Posts",
                "🎛️ Signal Management Controls", "📚 Trade History",
                "📊 Trade Statistics",
                "↩️ Admin Home",
            },
            "analysis": {
                "📊 Prepare Market Analysis", "📤 Send posted POI to PRO",
                "📸 Upload Chart", "🖍️ Annotate a Chart",
                "✍️ Edit Caption", "👁️ Preview Draft / Resume", "📢 Publish Analysis",
                "↩️ Admin Home",
            },
            "members": {
                "📨 Applications / Member Access", "🤝 Member Support & FAQs",
                "⏰ Applicant Follow-ups",
                "↩️ Admin Home",
            },
            "system": {
                "🔎 Verify Administrator", "🔎 Verify PRO Signals",
                "🔎 Verify Market Analysis", "🔐 Check & Enable Publishing",
                "🩺 Health Status", "📋 Recent Errors", "💾 Backup Database",
                "🔄 Retry / Reconcile Operations", "⚙️ Settings / Channel Discovery",
                "↩️ Admin Home",
            },
        }
        for category, labels in expected.items():
            await self.click("admin_category", {"category": category})
            message = self.bot.send_message.await_args_list[-1]
            actual = {
                button.text for row in message.kwargs["reply_markup"].inline_keyboard
                for button in row
            }
            self.assertEqual(actual, labels)
        await self.click("admin_category", {"category": "zone"})
        zone = self.bot.send_message.await_args_list[-1]
        zone_labels = {
            button.text for row in zone.kwargs["reply_markup"].inline_keyboard
            for button in row
        }
        self.assertIn("📍 Start Zone Setup", zone_labels)
        self.assertEqual(zone_labels, {
            "📊 Market Analysis + PRO POI", "📍 Start Zone Setup", "↩️ Admin Home"})

    async def test_trade_statistics_are_available_to_admin_without_channel_posts(self):
        await self.click("admin_category", {"category": "trades"})
        trade_menu = self.bot.send_message.await_args_list[-1]
        menu_labels = [
            button.text for row in trade_menu.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn("📊 Trade Statistics", menu_labels)

        await self.click("trade_stats")
        report = self.bot.send_message.await_args_list[-1]
        self.assertIn("STATISTICS · YEAR TO DATE", report.args[1])
        self.assertIn("Wins: 0", report.args[1])
        self.assertIn("📚 Trade History", [
            button.text for row in report.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])
        self.bot.send_photo.assert_not_awaited()
        self.assertTrue(all(
            call.args[0] == 42
            for call in self.bot.send_message.await_args_list
            if call.args
        ))

    async def test_isolated_admin_home_hides_used_setup_but_keeps_history(self):
        from dataclasses import replace
        from smh.zones import parse_zone, save_in

        self.ui.config = replace(self.config, isolated_test=True)
        setup = parse_zone("Gold/XAUUSD | 4150-4155 | M15 | 60 | M15 bullish candle close")
        setup.update(status="used", setup_message_id=None)
        with self.db.transaction() as conn:
            save_in(conn, setup)

        await self.click("menu")
        text = self.bot.send_message.await_args_list[-1].args[1]

        self.assertNotIn(setup["id"], text)
        self.assertNotIn("XAUUSD", text)
        self.assertIn("No active setup.", text)
        self.assertEqual(self.db.get("setup:" + setup["id"])["status"], "used")
        self.assertEqual(self.db.get("active_setup")["id"], setup["id"])
        self.bot.edit_message_caption.assert_not_awaited()

    async def test_isolated_admin_home_hides_expired_setup_but_keeps_history(self):
        import time
        from dataclasses import replace
        from smh.zones import parse_zone, save_in

        self.ui.config = replace(self.config, isolated_test=True)
        setup = parse_zone("Gold/XAUUSD | 4150-4155 | M15 | 60 | M15 bullish candle close")
        setup["expires"] = time.time() - 1
        with self.db.transaction() as conn:
            save_in(conn, setup)

        await self.click("menu")
        text = self.bot.send_message.await_args_list[-1].args[1]

        self.assertNotIn(setup["id"], text)
        self.assertNotIn("XAUUSD", text)
        self.assertIn("No active setup.", text)
        self.assertEqual(self.db.get("setup:" + setup["id"])["status"], "expired")
        self.assertEqual(self.db.get("active_setup")["id"], setup["id"])

    async def test_isolated_admin_home_still_shows_active_unexpired_setup(self):
        from dataclasses import replace
        from smh.zones import parse_zone, save_in

        self.ui.config = replace(self.config, isolated_test=True)
        setup = parse_zone("Gold/XAUUSD | 4150-4155 | M15 | 60 | M15 bullish candle close")
        setup["setup_message_id"] = 987
        setup["caption_status"] = self.ui.setup_public_status(setup)
        with self.db.transaction() as conn:
            save_in(conn, setup)

        await self.click("menu")
        text = self.bot.send_message.await_args_list[-1].args[1]

        self.assertIn("Setup #" + setup["id"], text)
        self.assertIn("XAUUSD", text)
        self.assertEqual(self.db.get("setup:" + setup["id"])["status"], "active")
        self.bot.edit_message_caption.assert_not_awaited()

    async def test_production_admin_home_keeps_its_existing_setup_summary(self):
        from smh.zones import parse_zone, save_in

        setup = parse_zone("Gold/XAUUSD | 4150-4155 | M15 | 60 | M15 bullish candle close")
        setup.update(status="used", setup_message_id=None)
        with self.db.transaction() as conn:
            save_in(conn, setup)

        await self.click("menu")
        text = self.bot.send_message.await_args_list[-1].args[1]

        self.assertIn("Setup #" + setup["id"], text)
        self.assertIn("Used", text)
        self.assertIn("XAUUSD", text)

    async def test_admin_categories_reject_non_admin_and_unknown_category(self):
        self.u.effective_user.id = 77
        self.u.effective_chat.id = 77
        self.u.callback_query.data = self.db.button(
            77, "admin_category", {"category": "system"})
        with self.assertRaises(PermissionError):
            await self.ui.callback(self.u, None)

        self.u.effective_user.id = 42
        self.u.effective_chat.id = 42
        with self.assertRaisesRegex(ValueError, "Choose a category"):
            await self.click("admin_category", {"category": "unknown"})

    async def test_system_menu_exposes_admin_channel_and_explicit_enable_controls(self):
        await self.click("admin_category", {"category": "system"})
        labels = {
            button.text
            for row in self.bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        }
        self.assertIn("🔎 Verify Administrator", labels)
        self.assertIn("🔎 Verify PRO Signals", labels)
        self.assertIn("🔎 Verify Market Analysis", labels)
        self.assertIn("🔐 Check & Enable Publishing", labels)

    async def test_verification_is_read_only_and_does_not_implicitly_enable_publishing(self):
        from dataclasses import replace

        self.bot.get_chat = AsyncMock(side_effect=lambda chat_id: NS(
            id=chat_id, type="private" if chat_id == 42 else "channel"))
        self.bot.get_chat_member = AsyncMock(return_value=NS(
            status="administrator", can_post_messages=True,
            can_edit_messages=True, can_invite_users=True))
        self.pub.verified = False

        await self.click("publishing_verify", {"scope": "administrator"})

        report = self.bot.send_message.call_args.args[1]
        self.assertIn("Administrator: ✅ Verified", report)
        self.assertIn("PRO Signals: ✅", report)
        self.assertIn("Market Analysis: ✅", report)
        self.assertIn("Read-only verification only; no channel messages were sent.", report)
        self.assertFalse(self.pub.verified)
        self.assertTrue(all(call.args[0] == 42 for call in self.bot.send_message.await_args_list))

        self.config = replace(self.config, allow_publishing=False)
        self.ui.config = self.config
        self.pub.config = self.config
        await self.click("publishing_enable")

        report = self.bot.send_message.call_args.args[1]
        self.assertIn("Environment publishing setting: OFF", report)
        self.assertIn("Publishing remains locked", report)
        self.assertFalse(self.pub.verified)
        self.assertTrue(all(call.args[0] == 42 for call in self.bot.send_message.await_args_list))

    async def test_enable_check_fails_closed_on_missing_channel_permission(self):
        from dataclasses import replace

        self.bot.get_chat = AsyncMock(side_effect=lambda chat_id: NS(
            id=chat_id, type="private" if chat_id == 42 else "channel"))

        async def membership(channel_id, user_id):
            return NS(
                status="administrator",
                can_post_messages=True,
                can_edit_messages=True,
                can_invite_users=not (channel_id == -1002 and user_id == 999),
            )

        self.bot.get_chat_member = AsyncMock(side_effect=membership)
        self.pub.verified = False
        self.config = replace(self.config, allow_publishing=True)
        self.ui.config = self.config
        self.pub.config = self.config

        await self.click("publishing_enable")

        report = self.bot.send_message.call_args.args[1]
        self.assertIn("Market Analysis: ⚠️", report)
        self.assertIn("bot needs Post Messages, Edit Messages, and Invite Users", report)
        self.assertIn("Publishing remains locked", report)
        self.assertFalse(self.pub.verified)
        self.assertTrue(all(call.args[0] == 42 for call in self.bot.send_message.await_args_list))

    async def test_explicit_enable_requires_all_checks_and_existing_setting(self):
        self.bot.get_chat = AsyncMock(side_effect=lambda chat_id: NS(
            id=chat_id, type="private" if chat_id == 42 else "channel"))
        self.bot.get_chat_member = AsyncMock(return_value=NS(
            status="administrator", can_post_messages=True,
            can_edit_messages=True, can_invite_users=True))
        self.pub.verified = False

        await self.click("publishing_enable")

        report = self.bot.send_message.call_args.args[1]
        self.assertIn("Result: Publishing is enabled by the existing setting", report)
        self.assertTrue(self.pub.verified)
        self.assertTrue(all(call.args[0] == 42 for call in self.bot.send_message.await_args_list))

    async def test_publishing_verification_controls_are_admin_only(self):
        self.u.effective_user.id = 77
        self.u.effective_chat.id = 77
        self.u.callback_query.data = self.db.button(77, "publishing_verify", {"scope": "signals"})
        with self.assertRaises(PermissionError):
            await self.ui.callback(self.u, None)

    async def test_applications_approval_invite_membership_callbacks(self):
        from dataclasses import replace
        self.config = replace(self.config, education_link="https://example.org/education",
                              education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute(
            "INSERT INTO member_requests (id,user_id,username,destination,answers,status,"
            "registration_status,funding_status,source,created,updated) "
            "VALUES ('edu-77',77,'member','education',?,'pending_review','not_required','not_required','new','now','now')",
            (json.dumps(["beginner"] * 5),))
        with self.assertRaisesRegex(ValueError, "self-service"):
            await self.ui.member_request_approve_prompt(self.u, "edu-77")
        member = NS(effective_user=NS(id=77, username="member"),
                    effective_chat=NS(id=77, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))
        await self.ui.member_action(member, "member_apply_dest", {"destination": "education"})
        education_messages = [call for call in self.bot.send_message.await_args_list
                              if call.args[0] == 77 and "self-service" in call.args[1]]
        self.assertEqual(len(education_messages), 1)
        education_button = education_messages[0].kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(education_button.text, "Join Educational Group")
        self.assertEqual(education_button.url, "https://example.org/education")
        with self.assertRaisesRegex(ValueError, "self-service"):
            await self.ui.member_request_approve_confirm(self.u, "edu-77")
        self.bot.create_chat_invite_link.assert_not_awaited()
        self.assertEqual(self.db.rows("SELECT status FROM member_requests WHERE id='edu-77'")[0]["status"],
                         "pending_review")
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=77"), [])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=77 AND channel=?",
                                      (self.config.signals,)), [])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=77 AND channel=?",
                                      (self.config.analysis,)), [])
        education_join = NS(
            chat=NS(id=self.config.education_group_id),
            new_chat_member=NS(user=NS(id=77), status="member"))
        await self.ui.membership_event(NS(chat_member=education_join), None)
        self.assertEqual(self.db.rows("SELECT status FROM access WHERE user_id=77 AND channel=?",
                                      (self.config.education_group_id,))[0]["status"], "member")
        signals_request = NS(chat=NS(id=self.config.signals), from_user=NS(id=77),
                             invite_link=NS(invite_link="https://t.me/+test"),
                             approve=AsyncMock(), decline=AsyncMock())
        await self.ui.join_request(NS(chat_join_request=signals_request), None)
        signals_request.decline.assert_awaited_once()
        before = self.bot.get_chat_member.await_count
        await self.click("membership", {"user": 77})
        self.assertEqual(self.bot.get_chat_member.await_count, before + 1)

    async def test_analysis_request_approval_does_not_grant_pro(self):
        self.db.execute(
            "INSERT INTO member_requests (id,user_id,destination,answers,status,registration_status,"
            "funding_status,source,created,updated) "
            "VALUES ('analysis-78',78,'analysis',?,'pending_review','not_required','not_required','new','now','now')",
            (json.dumps(["advanced"] * 5),))
        await self.click("member_request_approve", {"request_id": "analysis-78"})
        await self.click("member_request_approve_confirm", {"request_id": "analysis-78"})
        self.assertEqual(self.bot.create_chat_invite_link.await_count, 1)
        self.assertEqual(self.bot.create_chat_invite_link.await_args.args[0], self.config.analysis)
        access = self.db.rows("SELECT channel,status FROM access WHERE user_id=78")
        self.assertEqual({(row["channel"], row["status"]) for row in access},
                         {(self.config.analysis, "invite_issued")})
        member_message = next(call.args[1] for call in self.bot.send_message.await_args_list
                              if call.args[0] == 78)
        self.assertIn("Market Analysis", member_message)
        self.assertNotIn("PRO Signals", member_message)

    async def test_pro_requires_registration_funding_review_and_final_approval(self):
        from dataclasses import replace
        self.config = replace(self.config, exness_partner_link="https://one.exnessonelink.com/a/test",
                              allow_publishing=False)
        self.pub.config = self.config
        self.ui = Handlers(self.db, self.config, self.bot, self.pub,
                           Health(self.db, self.config, self.bot))
        member = NS(effective_user=NS(id=79, username="applicant"),
                    effective_chat=NS(id=79, type="private"),
                    message=NS(text="", photo=[], document=None, forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))
        await self.ui.member_action(member, "member_apply_dest", {"destination": "pro"})
        screening = [
            (0, "yes"),
            (1, "yes"),
            (2, "ready"),
        ]
        for step, answer in screening:
            draft = self.db.draft(79)
            await self.ui.member_action(
                member, "member_pro_screening_answer",
                {"revision": draft["revision"], "step": step, "answer": answer})
        self.assertEqual(self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=79 AND destination='pro'"), [])
        self.assertIn("Submit Application", self.bot.send_message.await_args_list[-1].args[1])
        summary_draft = self.db.draft(79)
        self.assertEqual(summary_draft["step"], "summary")
        await self.ui.member_action(
            member, "member_pro_screening_submit", {"revision": summary_draft["revision"]})
        self.assertEqual(self.db.draft(79)["kind"], "destination_application")
        self.assertIn("1/5", self.bot.send_message.await_args_list[-1].args[1])
        answers = ["Beginner", "Gold", "I understand losses", "I wait for confirmation", "I use a stop loss"]
        for answer in answers:
            member.message.text = answer
            await self.ui.destination_application_answer(member, self.db.draft(79))
        request = self.db.rows("SELECT * FROM member_requests WHERE user_id=79 AND destination='pro'")[0]
        request_id = request["id"]
        self.assertEqual(request["status"], "awaiting_registration")
        self.assertEqual(len(json.loads(request["answers"])), 5)
        screening_event = self.db.rows(
            "SELECT detail FROM member_request_events WHERE request_id=? AND action='pro_screening_completed'",
            (request_id,))
        self.assertEqual(json.loads(screening_event[0]["detail"]), ["yes", "yes", "ready"])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=79"), [])
        register_call = next(call for call in self.bot.send_message.await_args_list
                             if call.args[0] == 79 and "EXNESS REGISTRATION" in call.args[1])
        register_text = register_call.args[1]
        self.assertIn("register through the official Exness link below", register_text)
        self.assertIn("administrator review", register_text)
        self.assertNotIn("SMART MONEY HUB", register_text)
        self.assertNotIn("HOW TO APPLY", register_text)
        self.assertNotIn("PRO PROFITS &amp; FUNDING", register_text)
        self.assertEqual(register_call.kwargs["parse_mode"], "HTML")
        self.assertIn("tap the verification button below", register_text)
        self.assertIn("it does not grant PRO access", register_text)
        register_buttons = [button for row in register_call.kwargs["reply_markup"].inline_keyboard
                            for button in row]
        self.assertEqual(len(register_buttons), 2)
        self.assertEqual(register_buttons[0].text, "Register with Exness")
        self.assertEqual(register_buttons[0].url, self.config.exness_partner_link)
        self.assertEqual(register_buttons[1].text, "I've Registered — Submit for Verification")
        self.assertIsNone(register_buttons[1].url)
        self.assertNotIn(self.config.exness_partner_link, register_text)
        self.assertNotIn(self.config.signals, [call.args[0] for call in self.bot.send_message.await_args_list
                                               if call.args and isinstance(call.args[0], int)])

        await self.ui.member_action(member, "member_status", {})
        status_message = next(call for call in reversed(self.bot.send_message.await_args_list)
                              if call.args[0] == 79)
        status_buttons = [button for row in status_message.kwargs["reply_markup"].inline_keyboard
                          for button in row]
        status_button_texts = [button.text for button in status_buttons]
        self.assertIn("I've Registered — Submit for Verification", status_button_texts)
        self.assertNotIn("Submit Funding Evidence", status_button_texts,
                         "Funding evidence must remain gated until registration approval.")

        member.callback_query.data = register_buttons[1].callback_data
        await self.ui.callback(member, None)
        request = self.db.rows("SELECT * FROM member_requests WHERE id=?", (request_id,))[0]
        self.assertEqual((request["status"], request["registration_status"]),
                         ("pending_review", "pending_review"))
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=79"), [])
        with self.assertRaises(ValueError):
            await self.ui.member_action(
                member, "member_pro_registered", {"request_id": request_id})

        await self.ui.member_request_screen(self.u, request_id)
        admin_review = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("PRO application questions", admin_review)
        self.assertIn("risk management: accepted", admin_review)

        callback_data = self.db.button(
            79, "member_pro_registration", {"request_id": request_id})
        member.callback_query.data = callback_data
        with self.assertLogs("smh", level="INFO") as captured:
            await self.ui.callback(member, None)
        log_output = "\n".join(captured.output)
        self.assertIn("callback_action:member_pro_registration", log_output)
        self.assertNotIn(callback_data, log_output)
        self.assertNotIn("79", log_output)
        pending_prompt = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("🔎 <b>EXNESS REGISTRATION REVIEW</b>", pending_prompt)
        self.assertIn("awaiting administrator verification", pending_prompt)
        self.assertNotIn("SMART MONEY HUB", pending_prompt)
        self.assertEqual(self.bot.send_message.await_args_list[-1].kwargs["parse_mode"], "HTML")

        with self.assertRaises(ValueError):
            await self.ui.member_action(member, "member_funding_evidence", {"request_id": request_id})
        self.assertIsNone(self.db.draft(79), "Funded-account evidence must wait for registration approval.")

        await self.ui.member_verify_prompt(self.u, request_id, "registration")
        await self.ui.member_verify_confirm(self.u, request_id, "registration")
        request = self.db.rows("SELECT * FROM member_requests WHERE id=?", (request_id,))[0]
        self.assertEqual((request["status"], request["registration_status"], request["funding_status"]),
                         ("pending_review", "approved", "not_submitted"))
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=79"), [],
                         "Registration approval must not issue a channel invite.")
        registration_notice = next(call for call in reversed(self.bot.send_message.await_args_list)
                                   if call.args[0] == 79 and "PRO REGISTRATION APPROVED" in call.args[1])
        self.assertIn("education entitlement", registration_notice.args[1])
        self.assertNotIn("PRO Signals 24-hour", registration_notice.args[1])

        await self.ui.member_action(member, "member_funding_evidence", {"request_id": request_id})
        self.assertIsNone(self.db.draft(79), "Evidence upload must not open before the applicant confirms the warning.")
        await self.ui.member_action(member, "member_evidence_confirm", {"request_id": request_id})
        self.assertEqual(self.db.draft(79)["kind"], "pro_evidence")
        member.message.document = NS(file_id="private-evidence-reference", file_size=1200,
                                     mime_type="application/pdf")
        await self.ui.save_funding_evidence(member)
        member.message.document = None
        request = self.db.rows("SELECT * FROM member_requests WHERE id=?", (request_id,))[0]
        self.assertEqual(request["funding_status"], "pending_review")
        self.assertEqual(request["evidence_file_id"], "private-evidence-reference")
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=79"), [])
        with self.assertRaises(PermissionError):
            await self.ui.member_request_evidence(member, request_id)

        await self.ui.member_verify_prompt(self.u, request_id, "funding")
        await self.ui.member_verify_confirm(self.u, request_id, "funding")
        request = self.db.rows("SELECT * FROM member_requests WHERE id=?", (request_id,))[0]
        self.assertEqual((request["registration_status"], request["funding_status"]),
                         ("approved", "verified"))
        self.assertEqual(self.db.rows("SELECT status FROM access WHERE user_id=79 AND channel=?",
                                      (self.config.signals,))[0]["status"], "invite_issued")
        self.bot.create_chat_invite_link.assert_awaited_once()
        with self.assertRaises(PermissionError):
            await self.ui.member_verify_confirm(member, request_id, "funding")

        with self.assertRaises(ValueError):
            await self.ui.member_pro_approve_confirm(self.u, request_id)
        self.assertEqual(self.bot.create_chat_invite_link.await_args.args[0], self.config.signals)
        actions = [row["action"] for row in self.db.rows(
            "SELECT action FROM member_request_events WHERE request_id=?", (request_id,))]
        self.assertIn("registration_approved", actions)
        self.assertIn("funding_verified", actions)
        self.assertIn("pro_two_stage_access_granted", actions)
        self.bot.create_chat_invite_link.assert_awaited_once()
        await self.ui.member_action(member, "member_status", {})
        status_view = next(call.args[1] for call in reversed(self.bot.send_message.await_args_list)
                           if call.args[0] == 79)
        self.assertIn("<b>PRO Signals application:</b> <b>APPROVED</b>", status_view)
        invite_notice = next(call.args[1] for call in self.bot.send_message.await_args_list
                             if call.args[0] == 79 and "24-hour PRO Signals" in call.args[1])
        self.assertIn("Your profits belong to you", invite_notice)
        self.assertIn(
            "subject to Exness policies, account conditions, and processing requirements",
            invite_notice)

    def pro_member(self, user_id):
        return NS(
            effective_user=NS(id=user_id, username="applicant"),
            effective_chat=NS(id=user_id, type="private"),
            message=NS(text="", photo=[], document=None, forward_origin=None, caption=None),
            callback_query=NS(answer=AsyncMock()),
        )

    async def answer_pro_screening(self, member, step, answer):
        user = member.effective_user.id
        draft = self.db.draft(user)
        return await self.ui.member_action(
            member, "member_pro_screening_answer",
            {"revision": draft["revision"], "step": step, "answer": answer})

    async def test_pro_screening_rejected_answers_do_not_start_application(self):
        member = self.pro_member(83)
        await self.ui.member_action(member, "member_apply_dest", {"destination": "pro"})
        await self.answer_pro_screening(member, 0, "no")
        self.assertEqual(self.db.draft(83)["step"], "declined")
        self.assertIn("understand", self.bot.send_message.await_args_list[-1].args[1].lower())
        self.assertEqual(self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=83 AND destination='pro'"), [])

        draft = self.db.draft(83)
        await self.ui.member_action(
            member, "member_pro_screening_restart", {"revision": draft["revision"]})
        await self.answer_pro_screening(member, 0, "yes")
        await self.answer_pro_screening(member, 1, "no")
        self.assertEqual(self.db.draft(83)["step"], "declined")
        self.assertEqual(self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=83 AND destination='pro'"), [])

    async def test_pro_screening_not_ready_can_resume_from_saved_draft(self):
        member = self.pro_member(84)
        await self.ui.member_action(member, "member_apply_dest", {"destination": "pro"})
        await self.answer_pro_screening(member, 0, "yes")
        await self.answer_pro_screening(member, 1, "yes")
        await self.answer_pro_screening(member, 2, "not_yet")
        saved = self.db.draft(84)
        self.assertEqual(saved["step"], "not_ready")
        self.assertEqual(saved["screening_answers"], ["yes", "yes", "not_yet"])
        self.assertEqual(self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=84 AND destination='pro'"), [])
        draft = self.db.draft(84)
        await self.ui.member_action(
            member, "member_pro_screening_resume", {"revision": draft["revision"]})
        resumed = self.db.draft(84)
        self.assertEqual(resumed["step"], 2)
        self.assertEqual(resumed["screening_answers"], ["yes", "yes"])
        self.assertIn("3/3", self.bot.send_message.await_args_list[-1].args[1])

    async def test_pro_screening_survives_handler_recreation_and_cancel_clears_it(self):
        member = self.pro_member(85)
        await self.ui.member_action(member, "member_apply_dest", {"destination": "pro"})
        await self.answer_pro_screening(member, 0, "yes")

        self.pub = Publisher(self.db, self.config, self.bot)
        self.pub.verified = True
        self.ui = Handlers(self.db, self.config, self.bot, self.pub,
                           Health(self.db, self.config, self.bot))
        await self.ui.member_start(member)
        welcome = self.bot.send_message.await_args_list[-1]
        self.assertIn(
            "▶️ Continue my saved step",
            [button.text for row in welcome.kwargs["reply_markup"].inline_keyboard for button in row])
        await self.ui.assistant_resume(member)
        self.assertEqual(self.db.draft(85)["step"], 1)
        self.assertIn("2/3", self.bot.send_message.await_args_list[-1].args[1])

        await self.ui.member_action(member, "member_cancel", {})
        self.assertIsNone(self.db.draft(85))

    async def test_pro_screening_submit_is_single_use_and_existing_request_blocks_duplicates(self):
        member = self.pro_member(86)
        await self.ui.member_action(member, "member_apply_dest", {"destination": "pro"})
        for step, answer in enumerate(("yes", "yes", "ready")):
            await self.answer_pro_screening(member, step, answer)
        draft = self.db.draft(86)
        callback = self.db.button(
            86, "member_pro_screening_submit", {"revision": draft["revision"]})
        member.callback_query.data = callback
        await self.ui.callback(member, None)
        self.assertEqual(self.db.draft(86)["kind"], "destination_application")
        self.assertEqual(self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=86 AND destination='pro'"), [])
        with self.assertRaises(ValueError):
            await self.ui.callback(member, None)
        self.assertEqual(self.db.draft(86)["kind"], "destination_application")

        self.db.execute(
            "INSERT INTO member_requests (id,user_id,destination,answers,status,registration_status,"
            "funding_status,source,created,updated) VALUES "
            "('existing-pro-86',86,'pro','[]','awaiting_registration','not_submitted',"
            "'not_submitted','new','now','now')")
        await self.ui.member_action(member, "member_apply_dest", {"destination": "pro"})
        self.assertEqual(len(self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=86 AND destination='pro'")), 1)

    async def test_approved_pro_member_can_update_balance_without_losing_access(self):
        request_id = "pro-approved-balance-update"
        member_id = 104
        self.add_pro_request(request_id, member_id, status="approved", registration="verified",
                             funding="verified", evidence="old-balance-reference")
        self.db.execute("INSERT INTO applications VALUES (?,?,?,?)",
                        (member_id, "[]", "destination_applicant", "now"))
        self.db.execute("INSERT INTO access VALUES (?,?,?,?)",
                        (member_id, self.config.signals, "invite_issued", "now"))
        member = self.member_update(member_id)

        await self.ui.member_action(member, "member_status", {})
        status_call = next(call for call in reversed(self.bot.send_message.await_args_list)
                           if call.args[0] == member_id)
        self.assertIn("Update Funding Screenshot",
                      [button.text for row in status_call.kwargs["reply_markup"].inline_keyboard
                       for button in row])
        self.assertIn("Your profits belong to you", status_call.args[1])

        await self.ui.member_action(member, "member_funding_evidence", {"request_id": request_id})
        await self.ui.member_action(member, "member_evidence_confirm", {"request_id": request_id})
        member.message.photo = [NS(file_id="updated-balance-reference", file_size=1024,
                                   mime_type="image/jpeg")]
        await self.ui.save_funding_evidence(member)
        member.message.photo = []

        request = self.db.rows("SELECT * FROM member_requests WHERE id=?", (request_id,))[0]
        access = self.db.rows("SELECT status FROM access WHERE user_id=? AND channel=?",
                              (member_id, self.config.signals))[0]
        self.assertEqual((request["status"], request["registration_status"], request["funding_status"]),
                         ("approved", "verified", "pending_review"))
        self.assertEqual(request["evidence_file_id"], "updated-balance-reference")
        self.assertEqual(access["status"], "invite_issued")
        event = self.db.rows("SELECT action,detail FROM member_request_events WHERE request_id=? "
                             "ORDER BY created DESC LIMIT 1", (request_id,))[0]
        self.assertEqual(event["action"], "funding_balance_update_submitted")
        self.assertIn("old-balance-reference", event["detail"])
        self.assertEqual(self.db.draft(member_id), None)
        with self.assertRaises(ValueError):
            await self.ui.save_funding_evidence(member)
        with self.assertRaises(ValueError):
            await self.ui.member_action(member, "member_funding_evidence", {"request_id": request_id})
        await self.ui.member_action(member, "member_pro_recheck", {"request_id": request_id})
        recheck_message = self.bot.send_message.await_args.args[1]
        self.assertIn("APPROVED — UPDATED BALANCE UNDER REVIEW", recheck_message)
        self.assertIn("existing PRO access remains unchanged", recheck_message)

        await self.ui.member_request_screen(self.u, request_id)
        admin_call = next(call for call in reversed(self.bot.send_message.await_args_list)
                          if call.args[0] == self.config.admin)
        admin_buttons = [button.text for row in admin_call.kwargs["reply_markup"].inline_keyboard
                         for button in row]
        self.assertIn("View Funding Evidence (admin only)", admin_buttons)
        self.assertIn("Verify Funded Account", admin_buttons)
        self.assertIn("Disapprove this destination", admin_buttons)
        await self.ui.member_request_evidence(self.u, request_id)
        self.bot.send_photo.assert_awaited_once_with(
            self.config.admin, "updated-balance-reference",
            caption=ANY)
        await self.ui.member_verify_prompt(self.u, request_id, "funding")
        verify_prompt = self.bot.send_message.await_args.args[1]
        self.assertIn("updated balance screenshot", verify_prompt)
        await self.ui.member_verify_confirm(self.u, request_id, "funding")
        request = self.db.rows("SELECT status,funding_status FROM member_requests WHERE id=?",
                               (request_id,))[0]
        self.assertEqual((request["status"], request["funding_status"]), ("approved", "verified"))
        self.assertEqual(self.db.rows("SELECT status FROM access WHERE user_id=? AND channel=?",
                                      (member_id, self.config.signals))[0]["status"], "invite_issued")

        destinations = {self.config.signals, self.config.analysis}
        self.assertFalse(any(call.args[0] in destinations
                             for call in self.bot.send_message.await_args_list))
        self.assertFalse(any(call.args[0] in destinations
                             for call in self.bot.send_photo.await_args_list))
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_pro_verification_pending_cannot_be_rejected_or_marked_ineligible(self):
        self.add_pro_request("pro-pending-review", 79, registration="pending_review")
        member = self.member_update(79)
        with self.assertRaises(PermissionError):
            await self.ui.member_pro_not_eligible_prompt(member, "pro-pending-review")
        for action in (self.ui.member_request_reject_prompt,
                       self.ui.member_request_reject_confirm,
                       self.ui.member_pro_not_eligible_prompt,
                       self.ui.member_pro_not_eligible_confirm):
            with self.assertRaisesRegex(ValueError, "pending|ready"):
                await action(self.u, "pro-pending-review")
        request = self.db.rows("SELECT * FROM member_requests WHERE id='pro-pending-review'")[0]
        self.assertEqual(request["status"], "pending_review")
        self.assertIsNone(request["admin_decision_at"])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=79"), [])
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_pro_more_information_has_its_own_status_and_resumes_review(self):
        self.add_pro_request("pro-more-info", 86, status="pending_review",
                             registration="verified", funding="pending_review", evidence="evidence-86")
        await self.ui.member_request_more(self.u, "pro-more-info")
        request = self.db.rows("SELECT * FROM member_requests WHERE id='pro-more-info'")[0]
        self.assertEqual(request["status"], "information_requested")
        notice = next(call for call in self.bot.send_message.await_args_list if call.args[0] == 86)
        self.assertIn("Status: MORE_INFORMATION_REQUIRED", notice.args[1])
        self.assertIn("pending verification is not a rejection", notice.args[1])

        member = self.member_update(86)
        await self.ui.member_action(member, "member_more_info", {"request_id": "pro-more-info"})
        member.message.text = "I am providing the requested clarification."
        await self.ui.member_info_response(member, self.db.draft(86))
        request = self.db.rows("SELECT * FROM member_requests WHERE id='pro-more-info'")[0]
        self.assertEqual((request["status"], request["followup_text"]),
                         ("pending_review", "I am providing the requested clarification."))
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=86"), [])

    async def test_pro_outcome_delivery_failure_is_recorded_without_retry(self):
        async def private_send(chat_id, *args, **kwargs):
            if chat_id == 87:
                raise RuntimeError("private delivery unavailable")
            return None

        self.bot.send_message.side_effect = private_send
        self.add_pro_request("pro-delivery-failure", 87, registration="verified",
                             funding="not_submitted")
        await self.ui.member_pro_not_eligible_confirm(self.u, "pro-delivery-failure")
        request = self.db.rows("SELECT * FROM member_requests WHERE id='pro-delivery-failure'")[0]
        self.assertEqual(request["status"], "not_yet_eligible")
        errors = self.db.rows("SELECT category,detail FROM errors WHERE category='pro_outcome_notification'")
        self.assertEqual(len(errors), 1)
        self.assertNotIn("private delivery unavailable", errors[0]["detail"])
        with self.assertRaisesRegex(ValueError, "changed"):
            await self.ui.member_pro_not_eligible_confirm(self.u, "pro-delivery-failure")
        self.assertEqual(len(self.db.rows(
            "SELECT * FROM errors WHERE category='pro_outcome_notification'")), 1)

    async def test_education_join_is_self_service_and_direct(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=0,
                              education_link="https://t.me/+education-test")
        self.pub.config = self.config
        self.ui.config = self.config
        member = NS(effective_user=NS(id=86, username="member"),
                    effective_chat=NS(id=86, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))

        await self.ui.member_start(member)
        start_message = next(
            call for call in self.bot.send_message.await_args_list
            if call.args[0] == 86 and call.kwargs.get("reply_markup") and
            any(button.text == "🔐 Member Access"
                for row in call.kwargs["reply_markup"].inline_keyboard for button in row))
        start_buttons = [button for row in start_message.kwargs["reply_markup"].inline_keyboard
                         for button in row]
        self.assertEqual(len(start_buttons), 3)
        self.assertNotIn("Join Educational Group", [button.text for button in start_buttons])
        self.bot.create_chat_invite_link.assert_not_awaited()
        self.assertEqual(self.db.rows("SELECT * FROM member_requests WHERE user_id=86"), [])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=86"), [])
        await self.ui.request_destination_selection(member)
        access_menu = self.bot.send_message.await_args
        self.assertIn("🔐 <b>MEMBER ACCESS</b>", access_menu.args[1])
        self.assertIn("Joining is optional.", access_menu.args[1])
        self.assertIn("Apply separately. An administrator reviews each request.",
                      access_menu.args[1])
        self.assertIn("verified Exness registration", access_menu.args[1])
        self.assertIn("final administrator approval", access_menu.args[1])
        self.assertIn("My Access / Status", access_menu.args[1])
        self.assertNotIn("one-use invite", access_menu.args[1])
        self.assertEqual(access_menu.kwargs["parse_mode"], "HTML")
        access_button = next(button for row in access_menu.kwargs["reply_markup"].inline_keyboard
                             for button in row if button.text == "Join Educational Group")
        self.assertEqual(access_button.url, "https://t.me/+education-test")
        self.assertEqual(sum(len(row) for row in access_menu.kwargs["reply_markup"].inline_keyboard), 3)

    async def test_member_access_menu_explains_missing_education_link_clearly(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=0, education_link="")
        self.pub.config = self.config
        self.ui.config = self.config
        member = NS(effective_user=NS(id=86, username="member"),
                    effective_chat=NS(id=86, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))

        await self.ui.request_destination_selection(member)

        call = self.bot.send_message.await_args
        text = call.args[1]
        labels = [button.text for row in call.kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertIn("🔐 <b>MEMBER ACCESS</b>", text)
        self.assertIn("Educational Group link is not configured", text)
        self.assertIn("<b>Market Analysis</b>", text)
        self.assertIn("<b>PRO Signals</b>", text)
        self.assertNotIn("Join Educational Group", labels)
        self.assertNotIn("one-use invite", text)
        self.assertEqual(call.kwargs["parse_mode"], "HTML")

    async def test_education_direct_link_does_not_issue_invites_or_grant_other_destinations(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=0,
                              education_link="https://t.me/+education-test")
        self.pub.config = self.config
        self.ui.config = self.config
        self.bot.create_chat_invite_link.side_effect = TimeoutError("simulated timeout")
        member = NS(effective_user=NS(id=89, username="member"),
                    effective_chat=NS(id=89, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))

        await self.ui.member_action(member, "member_apply_dest", {"destination": "education"})
        direct_message = self.bot.send_message.await_args
        button = direct_message.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.url, "https://t.me/+education-test")
        self.bot.create_chat_invite_link.assert_not_awaited()
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=89"), [])
        with self.assertRaises(PermissionError):
            self.pub.prepare(89, "invite", {
                "user": 89, "channel": self.config.signals, "self_service_education": True})
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=89 AND channel=?",
                                      (self.config.signals,)), [])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=89 AND channel=?",
                                      (self.config.analysis,)), [])

    async def test_education_self_service_does_not_bypass_disapproval(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
                        (87, "[]", "destination_applicant", "now"))
        self.db.execute("INSERT INTO access VALUES (?,?,?,?)",
                        (87, -1003, "access_revoked", "now"))
        member = NS(effective_user=NS(id=87, username="member"),
                    effective_chat=NS(id=87, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))

        await self.ui.member_action(member, "member_apply_dest", {"destination": "education"})

        self.bot.get_chat_member.assert_not_awaited()
        self.bot.create_chat_invite_link.assert_not_awaited()
        self.assertEqual(self.db.rows("SELECT status FROM access WHERE user_id=87 AND channel=-1003")[0]["status"],
                         "access_revoked")

    async def test_education_button_uses_configured_link_without_rotating_old_invites(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003,
                              education_link="https://t.me/+education-test")
        self.pub.config = self.config
        self.ui.config = self.config
        self.bot.revoke_chat_invite_link = AsyncMock()
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('education-88',88,'education','[]','approved','not_required','not_required','new','now','now')")
        self.db.execute("INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
                        (88, "[]", "destination_applicant", "now"))
        old_op = self.pub.prepare(self.config.admin, "invite",
                                  {"user": 88, "channel": self.config.education_group_id})
        self.db.execute("UPDATE operations SET status='done' WHERE id=?", (old_op,))
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",
                        (f"invite:{old_op}", json.dumps({
                            "invite_link": "https://t.me/+legacy",
                            "expires_at": "2099-01-01T00:00:00+00:00",
                        })))
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",
                        (f"current_invite:88:{self.config.education_group_id}", json.dumps(old_op)))
        self.db.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                        (88, self.config.education_group_id, "invite_issued", "now"))
        member = NS(effective_user=NS(id=88, username="member"),
                    effective_chat=NS(id=88, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))

        await self.ui.member_action(member, "member_apply_dest", {"destination": "education"})

        self.bot.create_chat_invite_link.assert_not_awaited()
        self.bot.revoke_chat_invite_link.assert_not_awaited()
        self.assertEqual(self.pub.operation(old_op)[0]["status"], "done")
        self.assertEqual(self.pub.current_invite_operation(88, self.config.education_group_id), old_op)
        button = self.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.url, "https://t.me/+education-test")

    async def test_education_alternative_stays_unavailable_without_group_configuration(self):
        self.add_pro_request("pro-no-education-config", 88, status="rejected",
                             registration="unverified", funding="not_submitted")
        member = self.member_update(88)
        await self.ui.member_pro_alternative(member, "pro-no-education-config", "education")
        self.assertIsNone(self.db.draft(88))
        self.assertEqual(self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=88 AND destination='education'"), [])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=88"), [])
        notice = next(call for call in self.bot.send_message.await_args_list if call.args[0] == 88)
        self.assertIn("Educational Group link is not configured", notice.args[1])
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_pro_not_yet_eligible_sends_alternatives_and_prevents_repeat(self):
        self.config = __import__("dataclasses").replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.add_pro_request("pro-not-eligible", 79, registration="verified", funding="not_submitted")
        await self.click("member_pro_not_eligible", {"request_id": "pro-not-eligible"})
        await self.click("member_pro_not_eligible_confirm", {"request_id": "pro-not-eligible"})
        request = self.db.rows("SELECT * FROM member_requests WHERE id='pro-not-eligible'")[0]
        self.assertEqual(request["status"], "not_yet_eligible")
        self.assertEqual(request["admin_decision_by"], self.config.admin)
        self.assertTrue(request["admin_decision_at"])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=79"), [])
        self.assertEqual(self.db.rows(
            "SELECT action FROM member_request_events WHERE request_id='pro-not-eligible'")[-1]["action"],
            "pro_not_yet_eligible")
        member_calls = [call for call in self.bot.send_message.await_args_list if call.args[0] == 79]
        self.assertEqual(len(member_calls), 1)
        text = member_calls[0].args[1]
        self.assertIn("<b>Status:</b> NOT_YET_ELIGIBLE", text)
        self.assertIn("<b>Funded-account verification:</b> NOT_SUBMITTED", text)
        self.assertIn("<b>Status:</b> NOT_YET_ELIGIBLE", text)
        self.assertEqual(self.bot.send_message.await_args_list[-1].kwargs["parse_mode"], "HTML")
        self.assertIn("There is no pressure to make a deposit.", text)
        labels = [button.text for row in member_calls[0].kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertEqual(labels, [
            "Request Educational Group access",
            "Request Market Analysis access",
            "Request both",
            "Check PRO eligibility again",
        ])
        self.assertIn("Member Access", text)
        with self.assertRaisesRegex(ValueError, "changed"):
            await self.ui.member_pro_not_eligible_confirm(self.u, "pro-not-eligible")
        self.assertEqual(len([call for call in self.bot.send_message.await_args_list
                              if call.args[0] == 79]), 1)
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_pro_rejection_is_distinct_and_notifies_once(self):
        self.add_pro_request("pro-rejected", 80, registration="unverified", funding="not_submitted")
        await self.click("member_request_reject", {"request_id": "pro-rejected"})
        await self.click("member_request_reject_confirm", {"request_id": "pro-rejected"})
        request = self.db.rows("SELECT * FROM member_requests WHERE id='pro-rejected'")[0]
        self.assertEqual(request["status"], "rejected")
        self.assertEqual(request["admin_decision_by"], self.config.admin)
        self.assertTrue(request["admin_decision_at"])
        member_calls = [call for call in self.bot.send_message.await_args_list if call.args[0] == 80]
        self.assertEqual(len(member_calls), 1)
        self.assertIn("<b>Status:</b> REJECTED", member_calls[0].args[1])
        labels = [button.text for row in member_calls[0].kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertEqual(labels, [
            "Request Educational Group access",
            "Request Market Analysis access",
            "Request both",
            "Check PRO eligibility again",
        ])
        self.assertIn("Member Access", member_calls[0].args[1])
        with self.assertRaisesRegex(ValueError, "closed"):
            await self.ui.member_request_reject_confirm(self.u, "pro-rejected")
        self.assertEqual(len([call for call in self.bot.send_message.await_args_list
                              if call.args[0] == 80]), 1)
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_pro_recheck_resumes_registration_and_records_new_review(self):
        self.config = __import__("dataclasses").replace(
            self.config, exness_partner_link="https://one.exnessonelink.com/a/test")
        self.pub.config = self.config
        self.ui.config = self.config
        self.add_pro_request("pro-recheck-registration", 81, status="rejected",
                             registration="unverified", funding="not_submitted")
        member = self.member_update(81)
        await self.ui.member_pro_recheck(member, "pro-recheck-registration")
        request = self.db.rows(
            "SELECT * FROM member_requests WHERE id='pro-recheck-registration'")[0]
        self.assertEqual(request["status"], "awaiting_registration")
        self.assertIsNone(request["admin_decision_at"])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=81"), [])
        self.assertEqual(self.db.rows(
            "SELECT COUNT(*) AS n FROM member_requests WHERE user_id=81 AND destination='pro'")[0]["n"], 1)
        outcome = next(call for call in self.bot.send_message.await_args_list if call.args[0] == 81)
        self.assertIn("<b>Status:</b> NOT_YET_ELIGIBLE", outcome.args[1])
        await self.ui.member_action(member, "member_pro_registered",
                                    {"request_id": "pro-recheck-registration"})
        request = self.db.rows(
            "SELECT * FROM member_requests WHERE id='pro-recheck-registration'")[0]
        self.assertEqual((request["status"], request["registration_status"]),
                         ("pending_review", "pending_review"))
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=81"), [])
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_pro_recheck_with_verified_requirements_requests_admin_review_not_access(self):
        self.add_pro_request("pro-recheck-final", 82, status="not_yet_eligible",
                             registration="verified", funding="verified", evidence="evidence-82")
        member = self.member_update(82)
        await self.ui.member_pro_recheck(member, "pro-recheck-final")
        request = self.db.rows("SELECT * FROM member_requests WHERE id='pro-recheck-final'")[0]
        self.assertEqual(request["status"], "pending_review")
        self.assertIsNone(request["admin_decision_at"])
        events = [r["action"] for r in self.db.rows(
            "SELECT action FROM member_request_events WHERE request_id='pro-recheck-final'")]
        self.assertIn("pro_recheck_requested", events)
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=82"), [])
        self.bot.create_chat_invite_link.assert_not_awaited()
        self.assertTrue(any(call.args[0] == self.config.admin and
                            "another PRO eligibility review" in call.args[1]
                            for call in self.bot.send_message.await_args_list))

    async def test_alternative_both_gives_education_direct_access_and_reviews_analysis_separately(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=0,
                              education_link="https://t.me/+education-test")
        self.pub.config = self.config
        self.ui.config = self.config
        self.add_pro_request("pro-alt-both", 83, status="rejected",
                             registration="unverified", funding="not_submitted")
        member = self.member_update(83)
        await self.ui.member_pro_alternative(member, "pro-alt-both", "both")
        self.assertEqual(self.db.draft(83)["destination"], "analysis")
        for answer in ("Beginner", "Gold", "I understand risk", "I wait for confirmation", "I use a plan"):
            member.message.text = answer
            await self.ui.destination_application_answer(member, self.db.draft(83))
        requests = self.db.rows("SELECT * FROM member_requests WHERE user_id=83 ORDER BY destination")
        self.assertEqual(sorted((r["destination"], r["status"]) for r in requests),
                         [("analysis", "pending_review"), ("pro", "rejected")])
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=83"), [])
        self.bot.create_chat_invite_link.assert_not_awaited()
        self.assertTrue(any(
            call.args[0] == 83 and
            any(button.url == "https://t.me/+education-test"
                for row in call.kwargs["reply_markup"].inline_keyboard for button in row)
            for call in self.bot.send_message.await_args_list if call.kwargs.get("reply_markup")))
        await self.ui.member_pro_alternative(member, "pro-alt-both", "both")
        self.assertEqual(self.db.rows("SELECT COUNT(*) AS n FROM member_requests WHERE user_id=83")[0]["n"], 2)
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_legacy_pro_access_is_flagged_without_revocation_or_new_invite(self):
        self.db.execute("INSERT INTO applications VALUES (81,'[]','approved','now')")
        self.db.execute("INSERT INTO access VALUES (81,?,'joined','now')", (self.config.signals,))
        Handlers(self.db, self.config, self.bot, self.pub,
                 Health(self.db, self.config, self.bot))
        request = self.db.rows("SELECT * FROM member_requests WHERE id='legacy-pro-81'")[0]
        self.assertEqual(request["status"], "legacy_review")
        self.assertEqual(request["source"], "legacy")
        self.assertEqual(self.db.rows("SELECT status FROM access WHERE user_id=81")[0]["status"], "joined")
        self.assertFalse(self.pub.invite_authorized(81, self.config.signals))
        with self.assertRaisesRegex(ValueError, "approved application"):
            self.pub.prepare(self.config.admin, "invite",
                             {"user": 81, "channel": self.config.signals})
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_pro_invite_requires_final_admin_approval(self):
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('pro-pending',82,'pro','[]','pending_review','verified','verified','new','now','now')")
        self.assertFalse(self.pub.invite_authorized(82, self.config.signals))
        with self.assertRaisesRegex(ValueError, "approved application"):
            self.pub.prepare(self.config.admin, "invite",
                             {"user": 82, "channel": self.config.signals})
        self.bot.create_chat_invite_link.assert_not_awaited()

    async def test_application_does_not_store_credential_fields_or_duplicate_pending_requests(self):
        member = NS(effective_user=NS(id=83, username="member"),
                    effective_chat=NS(id=83, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))
        await self.ui.member_action(member, "member_apply_dest", {"destination": "analysis"})
        member.message.text = "password: do-not-store"
        with self.assertRaisesRegex(ValueError, "will not store"):
            await self.ui.destination_application_answer(member, self.db.draft(83))
        self.assertEqual(self.db.draft(83)["answers"], [])
        member.message.text = "Beginner"
        draft = self.db.draft(83)
        await self.ui.destination_application_answer(member, draft)
        for answer in ("Gold", "I understand losses", "I wait for confirmation", "I use a stop loss"):
            member.message.text = answer
            await self.ui.destination_application_answer(member, self.db.draft(83))
        self.assertEqual(len(self.db.rows(
            "SELECT id FROM member_requests WHERE user_id=83 AND destination='analysis' "
            "AND status='pending_review'")), 1)
        before = len(self.db.rows(
            "SELECT id FROM member_requests WHERE user_id=83 AND destination='analysis'"))
        await self.ui.member_action(member, "member_apply_dest", {"destination": "analysis"})
        after = len(self.db.rows(
            "SELECT id FROM member_requests WHERE user_id=83 AND destination='analysis'"))
        self.assertEqual(before, after)

    async def test_application_draft_resumes_after_sqlite_reopen(self):
        path = tempfile.mkdtemp()
        try:
            first = Database(path)
            first.save_draft(84, {"kind": "destination_application", "destination": "analysis",
                                  "answers": ["Beginner", "Gold"], "step": "answer"})
            first.conn.close()
            recovered = Database(path)
            self.assertEqual(recovered.draft(84)["answers"], ["Beginner", "Gold"])
            recovered.conn.close()
        finally:
            shutil.rmtree(path, ignore_errors=True)

    async def test_test_environment_does_not_fall_back_to_production_partner_link(self):
        from unittest.mock import patch
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "123456:TEST_TOKEN_NOT_REAL",
            "SMH_TEST_ADMIN_TELEGRAM_ID": "42",
            "SMH_TEST_PRO_SIGNALS_CHANNEL_ID": "-1001",
            "SMH_TEST_MARKET_ANALYSIS_CHANNEL_ID": "-1002",
            "SMH_TEST_MODE": "1",
            "EXNESS_PARTNER_LINK": "https://one.exnessonelink.com/a/production-placeholder",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config.load()
        self.assertEqual(config.exness_partner_link, "")
        env["SMH_TEST_EXNESS_PARTNER_LINK"] = "https://one.exnessonelink.com/a/test-placeholder"
        with patch.dict(os.environ, env, clear=True):
            config = Config.load()
        self.assertEqual(config.exness_partner_link, env["SMH_TEST_EXNESS_PARTNER_LINK"])

    async def test_more_information_and_rejection_are_scoped_and_audited(self):
        answers = json.dumps(["beginner"] * 5)
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('analysis-85',85,'analysis',?,'pending_review','not_required','not_required','new','now','now')",
            (answers,))
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('education-85',85,'education',?,'pending_review','not_required','not_required','new','now','now')",
            (answers,))
        await self.ui.member_request_more(self.u, "analysis-85")
        member = NS(effective_user=NS(id=85, username="member"),
                    effective_chat=NS(id=85, type="private"),
                    message=NS(text="I use a written risk plan.", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))
        await self.ui.member_action(member, "member_more_info", {"request_id": "analysis-85"})
        await self.ui.member_info_response(member, self.db.draft(85))
        analysis = self.db.rows("SELECT * FROM member_requests WHERE id='analysis-85'")[0]
        education = self.db.rows("SELECT * FROM member_requests WHERE id='education-85'")[0]
        self.assertEqual((analysis["status"], analysis["followup_text"]),
                         ("pending_review", "I use a written risk plan."))
        self.assertEqual(education["status"], "pending_review")
        self.assertIn("more_information_requested", [row["action"] for row in self.db.rows(
            "SELECT action FROM member_request_events WHERE request_id='analysis-85'")])
        await self.ui.member_request_reject_prompt(self.u, "education-85")
        await self.ui.member_request_reject_confirm(self.u, "education-85")
        self.assertEqual(self.db.rows(
            "SELECT status FROM member_requests WHERE id='education-85'")[0]["status"], "rejected")
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=85"), [])
        with self.assertRaisesRegex(ValueError, "already closed"):
            await self.ui.member_request_reject_confirm(self.u, "education-85")

    async def test_group_invite_supplies_welcome_when_education_site_link_is_missing(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (79,?,'pending','now')", (json.dumps(["beginner"]*5),))
        await self.click("review", {"user": 79, "status": "approved"})
        await self.click("review_access", {"user": 79, "channels": [self.config.education_group_id]})
        await self.click("review_confirm", {"user": 79, "status": "approved",
                                            "channels": [self.config.education_group_id]})
        self.assertEqual(self.db.rows("SELECT status FROM applications WHERE user_id=79")[0]["status"],
                         "approved")
        education_message = next(call for call in self.bot.send_message.await_args_list
                                 if call.args[0] == 79 and call.args[1].startswith("🎉 Welcome"))
        self.assertEqual(education_message.kwargs["reply_markup"].inline_keyboard[0][0].url,
                         "https://t.me/+test")
        self.assertFalse(self.db.rows(
            "SELECT category FROM errors WHERE category='education_link_missing'"))

    async def test_education_welcome_is_not_sent_when_group_access_was_not_selected(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003,
                              education_link="https://example.org/education")
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (88,?,'pending','now')",
                        (json.dumps(["beginner"]*5),))
        await self.click("review", {"user": 88, "status": "approved"})
        await self.click("review_access", {"user": 88, "channels": [self.config.analysis]})
        await self.click("review_confirm", {"user": 88, "status": "approved",
                                            "channels": [self.config.analysis]})
        self.assertFalse(any(call.args[0] == 88 and call.args[1].startswith("🎉 Welcome")
                             for call in self.bot.send_message.await_args_list))
        self.assertEqual(self.db.rows("SELECT channel FROM access WHERE user_id=88"),
                         [{"channel": self.config.analysis}])

    async def test_admin_can_revoke_current_group_invite_without_removing_member(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.bot.revoke_chat_invite_link = AsyncMock(return_value=True)
        self.db.execute("INSERT INTO applications VALUES (89,'[]','approved','now')")
        op = self.pub.prepare(42, "invite", {"user": 89, "channel": self.config.education_group_id})
        await self.pub.send(42, op)
        self.db.execute("UPDATE access SET status='joined' WHERE user_id=89 AND channel=?",
                        (self.config.education_group_id,))
        await self.ui.revoke_access_invite(self.u, 89, self.config.education_group_id)
        self.bot.revoke_chat_invite_link.assert_awaited_once_with(
            chat_id=self.config.education_group_id, invite_link="https://t.me/+test")
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=89 AND channel=?",
            (self.config.education_group_id,))[0]["status"], "joined")
        self.assertIsNone(self.pub.current_invite_operation(89, self.config.education_group_id))

    async def test_disapprove_approved_destination_removes_member_and_preserves_other_access(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (89,'[]','destination_applicant','now')")
        for request_id, destination in (
                ("education-89", "education"), ("analysis-89", "analysis")):
            self.db.execute(
                "INSERT INTO member_requests "
                "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
                "VALUES (?,89,?,'[]','approved','not_required','not_required','new','now','now')",
                (request_id, destination))
        self.db.execute("INSERT INTO access VALUES (89,-1003,'joined','now')")
        self.db.execute("INSERT INTO access VALUES (89,-1002,'member','now')")
        op = self.pub.prepare(42, "invite", {"user": 89, "channel": -1003})
        await self.pub.send(42, op)
        self.db.execute("UPDATE access SET status='joined' WHERE user_id=89 AND channel=-1003")
        self.bot.revoke_chat_invite_link = AsyncMock(return_value=True)
        self.bot.get_chat_member = AsyncMock(side_effect=[
            NS(status="member"),
            NS(status="administrator", can_restrict_members=True),
        ])
        self.bot.ban_chat_member = AsyncMock(return_value=True)

        await self.ui.member_request_screen(self.u, "education-89")
        member_request_markup = self.bot.send_message.await_args.kwargs["reply_markup"]
        member_request_labels = [
            button.text for row in member_request_markup.inline_keyboard for button in row
        ]
        self.assertIn("Disapprove this destination", member_request_labels)

        await self.click("access_disapprove", {
            "user": 89, "channel": -1003, "request_id": "education-89",
        })
        prompt = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("Only this destination is affected", prompt)
        await self.click("access_disapprove_confirm", {
            "user": 89, "channel": -1003, "request_id": "education-89",
        })

        self.bot.revoke_chat_invite_link.assert_awaited_once_with(
            chat_id=-1003, invite_link="https://t.me/+test")
        self.bot.ban_chat_member.assert_awaited_once()
        self.assertEqual(self.bot.ban_chat_member.await_args.kwargs["chat_id"], -1003)
        self.assertEqual(self.bot.ban_chat_member.await_args.kwargs["user_id"], 89)
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=89 AND channel=-1003")[0]["status"],
            "access_revoked")
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=89 AND channel=-1002")[0]["status"],
            "member")
        self.assertEqual(self.db.rows(
            "SELECT status FROM member_requests WHERE id='education-89'")[0]["status"],
            "revoked")
        self.assertEqual(self.db.rows(
            "SELECT status FROM member_requests WHERE id='analysis-89'")[0]["status"],
            "approved")
        self.assertFalse(self.pub.invite_authorized(89, -1003))
        self.assertTrue(self.pub.invite_authorized(89, -1002))
        self.assertTrue(self.db.rows(
            "SELECT id FROM member_request_events WHERE request_id='education-89' "
            "AND action='access_disapproved'"))
        self.assertTrue(any(call.args[0] == 89 and "access has been disapproved" in call.args[1]
                            for call in self.bot.send_message.await_args_list))

        with self.assertRaisesRegex(ValueError, "already been disapproved"):
            await self.ui.access_disapprove_confirm(
                self.u, 89, -1003, "education-89")
        self.assertEqual(self.bot.ban_chat_member.await_count, 1)

    async def test_disapproval_fails_closed_without_member_removal_permission(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (90,'[]','destination_applicant','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('education-90',90,'education','[]','approved','not_required','not_required','new','now','now')")
        self.db.execute("INSERT INTO access VALUES (90,-1003,'joined','now')")
        self.bot.get_chat_member = AsyncMock(side_effect=[
            NS(status="member"),
            NS(status="administrator", can_restrict_members=False),
        ])
        self.bot.ban_chat_member = AsyncMock()

        await self.ui.access_disapprove_confirm(self.u, 90, -1003, "education-90")

        self.bot.ban_chat_member.assert_not_awaited()
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=90 AND channel=-1003")[0]["status"],
            "disapproval_pending")
        self.assertEqual(self.db.rows(
            "SELECT status FROM member_requests WHERE id='education-90'")[0]["status"],
            "approved")
        self.assertFalse(self.pub.invite_authorized(90, -1003))
        self.assertIn("needs administrator permission",
                      self.bot.send_message.await_args_list[-1].args[1])
        self.bot.get_chat_member = AsyncMock(return_value=NS(status="left"))
        await self.ui.access_disapprove_confirm(self.u, 90, -1003, "education-90")
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=90 AND channel=-1003")[0]["status"],
            "access_revoked")
        self.assertEqual(self.db.rows(
            "SELECT status FROM member_requests WHERE id='education-90'")[0]["status"],
            "revoked")

    async def test_uncertain_direct_education_invite_revocation_warns_link_may_work(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (97,'[]','destination_applicant','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('education-97',97,'education','[]','approved','not_required','not_required','new','now','now')")
        self.db.execute("INSERT INTO access VALUES (97,-1003,'invite_issued','now')")
        op = self.pub.prepare(42, "invite", {"user": 97, "channel": -1003})
        await self.pub.send(42, op)
        self.bot.revoke_chat_invite_link = AsyncMock(side_effect=TimeoutError("offline mock only"))
        self.bot.get_chat_member = AsyncMock(return_value=NS(status="left"))

        await self.ui.access_disapprove_confirm(self.u, 97, -1003, "education-97")

        self.assertEqual(self.pub.current_invite_operation(97, -1003), op)
        self.assertIn("may still work", self.bot.send_message.await_args_list[-1].args[1])
        self.assertNotIn("join requests are blocked", self.bot.send_message.await_args_list[-1].args[1])

    async def test_uncertain_member_removal_is_not_retried_blindly(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (93,'[]','destination_applicant','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('education-93',93,'education','[]','approved','not_required','not_required','new','now','now')")
        self.db.execute("INSERT INTO access VALUES (93,-1003,'joined','now')")
        self.bot.get_chat_member = AsyncMock(side_effect=[
            NS(status="member"),
            NS(status="administrator", can_restrict_members=True),
            NS(status="member"),
        ])
        self.bot.ban_chat_member = AsyncMock(side_effect=TimeoutError("offline mock only"))

        await self.ui.access_disapprove_confirm(self.u, 93, -1003, "education-93")

        self.bot.ban_chat_member.assert_awaited_once()
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=93 AND channel=-1003")[0]["status"],
            "disapproval_pending")
        self.assertFalse(self.pub.invite_authorized(93, -1003))

        # An administrator checks Telegram and confirms the member is now absent.
        self.bot.get_chat_member = AsyncMock(return_value=NS(status="left"))
        await self.ui.access_disapprove_confirm(self.u, 93, -1003, "education-93")
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=93 AND channel=-1003")[0]["status"],
            "access_revoked")
        self.bot.ban_chat_member.assert_awaited_once()

    async def test_disapproval_callback_is_admin_only_and_member_events_preserve_revocation(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (91,'[]','approved','now')")
        self.db.execute("INSERT INTO access VALUES (91,-1003,'access_revoked','now')")
        nonadmin = self.member_update(77)
        with self.assertRaises(PermissionError):
            await self.ui.access_disapprove_prompt(nonadmin, 91, -1003)

        event = NS(
            chat=NS(id=-1003),
            new_chat_member=NS(user=NS(id=91), status="member"),
        )
        await self.ui.membership_event(NS(chat_member=event), None)
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=91 AND channel=-1003")[0]["status"],
            "access_revoked")

    async def test_legacy_application_screen_offers_destination_disapproval(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (92,'[]','approved','now')")
        self.db.execute("INSERT INTO access VALUES (92,-1003,'joined','now')")
        await self.ui.application(self.u, 92)
        markup = self.bot.send_message.await_args.kwargs["reply_markup"]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertIn("Disapprove Educational Group access", labels)

    async def test_disapproval_button_remains_available_after_invite_revocation(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (96,'[]','approved','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('education-96',96,'education','[]','approved','not_required','not_required','new','now','now')")
        self.db.execute("INSERT INTO access VALUES (96,-1003,'invite_revoked','now')")
        self.bot.get_chat_member = AsyncMock(return_value=NS(status="left"))
        self.bot.ban_chat_member = AsyncMock()

        await self.ui.application(self.u, 96)
        application_markup = self.bot.send_message.await_args.kwargs["reply_markup"]
        application_labels = [
            button.text for row in application_markup.inline_keyboard for button in row
        ]
        self.assertIn("Disapprove Educational Group access", application_labels)

        await self.ui.member_request_screen(self.u, "education-96")
        request_markup = self.bot.send_message.await_args.kwargs["reply_markup"]
        request_labels = [button.text for row in request_markup.inline_keyboard for button in row]
        self.assertIn("Disapprove this destination", request_labels)

        await self.ui.access_disapprove_confirm(self.u, 96, -1003, "education-96")

        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=96 AND channel=-1003")[0]["status"],
            "access_revoked")
        self.assertEqual(self.db.rows(
            "SELECT status FROM member_requests WHERE id='education-96'")[0]["status"],
            "revoked")
        self.assertFalse(self.pub.invite_authorized(96, -1003))
        self.bot.ban_chat_member.assert_not_awaited()

    async def test_legacy_pro_access_can_be_disapproved_after_explicit_admin_review(self):
        self.db.execute("INSERT INTO applications VALUES (94,'[]','destination_applicant','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('legacy-pro-94',94,'pro','[]','legacy_review','unverified','unverified','legacy','now','now')")
        self.db.execute("INSERT INTO access VALUES (94,-1001,'joined','now')")
        self.bot.get_chat_member = AsyncMock(side_effect=[
            NS(status="member"),
            NS(status="administrator", can_restrict_members=True),
        ])
        self.bot.ban_chat_member = AsyncMock(return_value=True)

        await self.ui.member_request_screen(self.u, "legacy-pro-94")
        markup = self.bot.send_message.await_args.kwargs["reply_markup"]
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertIn("Disapprove existing PRO access", labels)
        await self.ui.access_disapprove_confirm(self.u, 94, -1001, "legacy-pro-94")

        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=94 AND channel=-1001")[0]["status"],
            "access_revoked")
        self.assertEqual(self.db.rows(
            "SELECT status FROM member_requests WHERE id='legacy-pro-94'")[0]["status"],
            "revoked")

    async def test_member_can_start_a_fresh_destination_request_after_disapproval(self):
        self.db.execute("INSERT INTO applications VALUES (95,'[]','destination_applicant','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('analysis-95',95,'analysis','[]','revoked','not_required','not_required','new','now','now')")
        self.db.execute("INSERT INTO access VALUES (95,-1002,'access_revoked','now')")

        member = self.member_update(95)
        await self.ui.begin_destination_application(member, "analysis")

        self.assertEqual(self.db.draft(95)["kind"], "destination_application")
        self.assertEqual(self.db.draft(95)["destination"], "analysis")

    async def test_failed_group_invite_can_be_retried_without_duplicate_link(self):
        from dataclasses import replace
        from telegram.error import BadRequest
        group_id = -1003
        self.config = replace(self.config, education_group_id=group_id)
        self.pub.config = self.config
        self.ui.config = self.config
        self.bot.create_chat_invite_link.side_effect = BadRequest("permission denied")
        self.db.execute("INSERT INTO applications VALUES (91,'[]','pending','now')")
        await self.ui.approve(self.u, {"user": 91, "status": "approved", "channels": [group_id]})
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=91 AND channel=?", (group_id,))[0]["status"],
            "invite_failed")
        self.assertFalse(any("https://t.me/+test" in row["detail"]
                             for row in self.db.rows("SELECT detail FROM errors")))
        await self.ui.application(self.u, 91)
        labels = [button.text for row in self.bot.send_message.await_args_list[-1].kwargs[
            "reply_markup"].inline_keyboard for button in row]
        self.assertIn("Retry Educational Group Invite", labels)
        self.bot.create_chat_invite_link.side_effect = None
        await self.ui.admin_action(self.u, "invite_confirm", {"user": 91, "channel": group_id})
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=91 AND channel=?", (group_id,))[0]["status"],
            "invite_issued")
        self.assertEqual(self.bot.create_chat_invite_link.await_count, 2)

    async def test_access_selection_callback_cannot_be_replayed(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        token = self.db.button(42, "review_access_toggle", {
            "user": 92, "channels": [], "channel": self.config.education_group_id})
        self.u.callback_query.data = token
        await self.ui.callback(self.u, None)
        with self.assertRaisesRegex(ValueError, "already used"):
            await self.ui.callback(self.u, None)

    async def test_education_group_option_is_hidden_until_group_id_is_configured(self):
        await self.ui.access_selection(self.u, 93, [])
        text = self.bot.send_message.await_args.args[1]
        labels = [button.text for row in self.bot.send_message.await_args.kwargs[
            "reply_markup"].inline_keyboard for button in row]
        self.assertIn("EDUCATION_GROUP_ID", text)
        self.assertNotIn("Educational Group", " ".join(labels))

    async def test_invalid_education_link_is_not_sent(self):
        from dataclasses import replace
        link = "javascript:alert(1)"
        self.config = replace(self.config, education_link=link, education_group_id=-1003)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute("INSERT INTO applications VALUES (81,?,'pending','now')", (json.dumps(["beginner"]*5),))
        await self.click("review", {"user": 81, "status": "approved"})
        await self.click("review_access", {"user": 81, "channels": [self.config.education_group_id]})
        await self.click("review_confirm", {"user": 81, "status": "approved",
                                            "channels": [self.config.education_group_id]})
        self.assertEqual(self.db.rows("SELECT status FROM applications WHERE user_id=81")[0]["status"],
                         "approved")
        education_message = next(call for call in self.bot.send_message.await_args_list
                                 if call.args[0] == 81 and call.args[1].startswith("🎉 Welcome"))
        self.assertEqual(education_message.kwargs["reply_markup"].inline_keyboard[0][0].url,
                         "https://t.me/+test")
        self.assertEqual(self.db.rows(
            "SELECT category FROM errors WHERE category='education_link_invalid'")[0]["category"],
            "education_link_invalid")

    async def test_group_invite_wins_over_configured_education_site_link(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003,
                              education_link="https://example.org/education")
        self.pub.config = self.config
        self.ui.config = self.config
        result = await self.ui.send_education_welcome(80, "https://t.me/+private-group-invite")
        self.assertEqual(result, "sent")
        call = self.bot.send_message.await_args
        button = call.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.url, "https://t.me/+private-group-invite")
        self.assertNotEqual(button.url, self.config.education_link)

    async def test_group_invite_missing_does_not_send_site_link_as_group_access(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003,
                              education_link="https://example.org/education")
        self.pub.config = self.config
        self.ui.config = self.config
        result = await self.ui.send_education_welcome(81)
        self.assertEqual(result, "group_missing")
        self.bot.send_message.assert_not_awaited()
        error = self.db.rows(
            "SELECT category FROM errors WHERE category='education_group_invite_missing'")
        self.assertEqual(len(error), 1)

    async def test_education_site_link_is_used_when_no_group_is_configured(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=0,
                              education_link="https://example.org/education")
        self.pub.config = self.config
        self.ui.config = self.config
        result = await self.ui.send_education_welcome(82)
        self.assertEqual(result, "sent")
        call = self.bot.send_message.await_args
        button = call.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.url, "https://example.org/education")

    async def test_education_direct_url_does_not_change_application_state(self):
        from dataclasses import replace
        education_link = "https://example.org/education"
        self.config = replace(self.config, education_link=education_link, education_group_id=0)
        self.pub.config = self.config
        self.ui.config = self.config
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('education-80',80,'education',?,'pending_review','not_required','not_required','new','now','now')",
            (json.dumps(["experienced"] * 5),))
        member = NS(effective_user=NS(id=80, username="member"),
                    effective_chat=NS(id=80, type="private"),
                    message=NS(text="", forward_origin=None, caption=None),
                    callback_query=NS(answer=AsyncMock()))
        await self.ui.member_action(member, "member_apply_dest", {"destination": "education"})
        self.assertEqual(self.db.rows("SELECT status FROM member_requests WHERE id='education-80'")[0]["status"],
                         "pending_review")
        self.assertEqual(self.db.rows(
            "SELECT source FROM member_requests WHERE id='education-80'")[0]["source"], "new")
        self.assertEqual(self.db.rows("SELECT * FROM access WHERE user_id=80"), [])
        self.assertEqual(self.db.rows("SELECT * FROM errors WHERE category='education_invitation_delivery'"), [])
        self.bot.create_chat_invite_link.assert_not_awaited()
        call = self.bot.send_message.await_args
        button = call.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.url, education_link)
        self.assertEqual(button.text, "Join Educational Group")

    async def test_operation_retry_abandon_and_reconciliation_callbacks(self):
        payload = {"destination": "analysis", "text": "H4 structure commentary."}
        op = self.pub.prepare(42, "analysis", payload)
        await self.click("operation", {"id": op})
        await self.click("retry", {"id": op})
        self.assertEqual(self.pub.operation(op)[0]["status"], "done")
        op = self.pub.prepare(42, "analysis", payload)
        await self.click("abandon", {"id": op})
        await self.click("abandon_confirm", {"id": op})
        self.assertEqual(self.pub.operation(op)[0]["status"], "abandoned")
        op = self.pub.prepare(42, "analysis", payload)
        self.db.execute("UPDATE operations SET status='uncertain' WHERE id=?", (op,))
        await self.click("reconcile", {"id": op})
        await self.text("777")
        await self.click("reconcile_confirm", self.revision())
        self.assertEqual(self.pub.operation(op)[0]["message_id"], 777)

    async def test_all_commands_and_channel_discovery(self):
        for cmd in ("/myid", "/help", "/start", "/admin", "/health", "/cancel"):
            self.u.message.text = cmd
            await self.ui.command(self.u, None)
        channel = NS(effective_chat=NS(type="channel", id=-900, title="Test channel"),
                     channel_post=NS(text="/channelid"))
        await self.ui.discover_channel(channel, None)
        self.assertIn(-900, self.db.get("channels"))

    async def test_help_hides_admin_controls_from_members(self):
        self.u.effective_user.id = 77
        self.u.effective_chat = NS(id=77, type="private")
        self.u.message.text = "/help"
        await self.ui.command(self.u, None)
        member_help = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("Member Access", member_help)
        self.assertNotIn("/", member_help)

        self.u.message.text = "/admin"
        with self.assertRaises(PermissionError):
            await self.ui.command(self.u, None)

        self.u.effective_user.id = self.config.admin
        self.u.effective_chat = NS(id=self.config.admin, type="private")
        self.u.message.text = "/help"
        await self.ui.command(self.u, None)
        admin_help = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("administrator menu", admin_help.lower())
        self.assertIn("Operations", admin_help)
        self.assertNotIn("/", admin_help)

    async def test_member_start_cancel_and_resume(self):
        self.u.effective_user.id = 77
        self.u.effective_chat.id = 77
        await self.ui.member_start(self.u)
        welcome = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("👋 <b>WELCOME TO VAYDA SMART MONEY HUB</b>", welcome)
        self.assertIn("📚 <b>EDUCATION</b> — Self-service access", welcome)
        self.assertIn("📊 <b>MARKET ANALYSIS</b> — Separate application and review", welcome)
        self.assertIn("💎 <b>PRO SIGNALS</b> — Separate application and eligibility review", welcome)
        self.assertIn("does not automatically grant access to a specific destination", welcome)
        self.assertIn("Trading involves risk", welcome)
        self.assertIn("does not place trades", welcome)
        self.assertIn("<b>PRO SIGNALS — PROFITS &amp; FUNDING POLICY</b>", welcome)
        self.assertIn("Your profits belong to you.", welcome)
        self.assertIn("Never deposit money solely to qualify for PRO Signals.", welcome)
        self.assertNotIn("<i>", welcome)
        self.assertEqual(self.bot.send_message.await_args.kwargs["parse_mode"], "HTML")
        await self.ui.member_action(self.u, "member_apply", {})
        await self.ui.member_action(self.u, "member_apply_dest", {"destination": "analysis"})
        self.assertIn("1/5", self.bot.send_message.await_args_list[-1].args[1])
        self.u.message.text = "Beginner."
        await self.ui.destination_application_answer(self.u, self.db.draft(77))
        self.assertIn("2/5", self.bot.send_message.await_args_list[-1].args[1])
        await self.ui.member_action(self.u, "member_apply_dest", {"destination": "analysis"})
        self.assertEqual(len(self.db.draft(77)["answers"]), 1)
        await self.ui.member_action(self.u, "member_status", {})
        await self.ui.member_action(self.u, "member_cancel", {})
        self.assertIsNone(self.db.draft(77))

    async def test_completed_application_thanks_applicant_and_confirms_review_pending(self):
        self.u.effective_user.id = 77
        self.u.effective_chat = NS(id=77, type="private")
        self.db.save_draft(77, {"kind": "application", "answers": [], "step": "answer"})
        for answer in ("Beginner", "Gold", "I use small risk", "I wait for confirmation", "I follow a plan"):
            self.u.message.text = answer
            await self.ui.application_answer(self.u, self.db.draft(77))
        user_reply = next(call.args[1] for call in reversed(self.bot.send_message.await_args_list)
                          if call.args[0] == 77 and "Application submitted" in call.args[1])
        self.assertIn("Thanks for your interest", user_reply)
        self.assertIn("awaiting administrator review", user_reply)
        self.assertEqual(self.db.rows("SELECT status FROM applications WHERE user_id=77")[0]["status"],
                         "pending")

    async def test_rejection_message_is_respectful(self):
        self.db.execute("INSERT INTO applications VALUES (82,?,'pending','now')",
                        (json.dumps(["beginner"] * 5),))
        await self.ui.approve(self.u, {"user": 82, "status": "rejected"})
        rejection = next(call.args[1] for call in self.bot.send_message.await_args_list if call.args[0] == 82)
        self.assertIn("Thank you for applying", rejection)
        self.assertIn("unable to approve your request at this time", rejection)
        self.assertNotIn("not good enough", rejection.lower())


if __name__ == "__main__":
    unittest.main()
