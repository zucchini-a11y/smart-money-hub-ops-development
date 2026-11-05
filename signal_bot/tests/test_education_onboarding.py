import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import InlineKeyboardButton

from smh.database import Database
from smh.education_onboarding import (
    EducationOnboardingFlows,
    _day1_text,
    _next_day2_due,
    process_education_onboarding_once,
    recover_education_onboarding,
)
from smh.handlers import Handlers
from smh.members import MemberFlows


class TestFlows(EducationOnboardingFlows):
    def __init__(self, db, config, bot):
        self.db = db
        self.config = config
        self.bot = bot

    def button(self, user, label, action, data=None):
        return InlineKeyboardButton(
            label, callback_data=self.db.button(user, action, data or {}))


class MemberMenu(MemberFlows):
    def __init__(self, db, config):
        self.db = db
        self.config = config


class EducationOnboardingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name))
        self.config = SimpleNamespace(
            admin=12345,
            isolated_test=True,
            education_onboarding_enabled=True,
            education_group_id=-1003916437804,
            education_link="https://t.me/+private-test-invite",
            education_announcement_url="https://t.me/c/3916437804/3",
            education_demo_account_url="https://t.me/c/3916437804/2/57",
            education_episode_01_url="https://t.me/c/3916437804/6/23",
            education_market_structure_video_url="https://t.me/c/3916437804/8/125",
            education_episode_02_video_url="https://t.me/c/3916437804/8/143",
            education_episode_02_pdf_url="https://t.me/c/3916437804/6/24",
            education_day2_mode="online",
            allow_publishing=False,
        )
        self.bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member", is_member=True)),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        )
        self.flow = TestFlows(self.db, self.config, self.bot)
        self.update = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private", id=12345),
            effective_user=SimpleNamespace(id=12345),
        )

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    def progress(self):
        return self.db.get("education:onboarding:12345")

    def test_day1_does_not_reference_demo_guide_when_link_is_missing(self):
        message = _day1_text("")
        self.assertIn("Use the guide if you need help setting up a demo account", message)
        self.assertIn("Today is strictly for orientation", message)
        self.assertIn("Tomorrow — Day 2: Episode 01 | Understanding Market Structure", message)
        self.assertIn("Episode 01 will be delivered when Bot 1 is online", message)

    async def test_membership_event_without_explicit_education_start_does_not_enroll(self):
        await self.flow.education_onboarding_membership_changed(12345, "member")
        self.bot.get_chat_member.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()
        self.assertIsNone(self.progress())

    async def test_member_access_menu_routes_education_through_explicit_start(self):
        button, note = await MemberMenu(self.db, self.config).education_join_button(self.update)
        self.assertEqual(button, ("Start Education", "education_onboarding_start", {}))
        self.assertEqual(note, "")

    async def test_start_requires_verified_membership_and_sends_day1_once(self):
        self.bot.get_chat_member.return_value = SimpleNamespace(status="left", is_member=False)
        await self.flow.education_onboarding_action(self.update, "education_onboarding_start")
        self.assertEqual(self.progress()["day1_status"], "pending")
        self.assertEqual(self.bot.send_message.await_args.kwargs["chat_id"], 12345)
        self.assertIn("Check membership", [
            button.text for row in self.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])

        self.bot.get_chat_member.return_value = SimpleNamespace(status="member", is_member=True)
        await self.flow.education_onboarding_action(self.update, "education_onboarding_check")
        self.assertEqual(self.progress()["day1_status"], "sent")
        self.assertEqual(self.progress()["day2_status"], "pending")
        day1_message = self.bot.send_message.await_args.kwargs
        self.assertIn("DAY 1: EDUCATION ORIENTATION", day1_message["text"])
        self.assertIn("Today is strictly for orientation", day1_message["text"])
        self.assertIn("Tomorrow — Day 2: Episode 01 | Understanding Market Structure", day1_message["text"])
        self.assertIn("Education Announcements", day1_message["text"])
        day1_buttons = {
            button.text: button.url
            for row in day1_message["reply_markup"].inline_keyboard
            for button in row
        }
        self.assertEqual(day1_buttons["Education access link"], self.config.education_link)
        self.assertEqual(
            day1_buttons["How to open a demo account"], self.config.education_demo_account_url)
        self.assertEqual(
            day1_buttons["Open Education announcements"], self.config.education_announcement_url)
        self.assertEqual(
            sum("DAY 1: EDUCATION ORIENTATION" in call.kwargs.get("text", "")
                for call in self.bot.send_message.await_args_list),
            1,
        )
        await self.flow.education_onboarding_action(self.update, "education_onboarding_check")
        self.assertEqual(
            sum("DAY 1: EDUCATION ORIENTATION" in call.kwargs.get("text", "")
                for call in self.bot.send_message.await_args_list),
            1,
        )

    async def test_day2_waits_for_next_lagos_day_and_survives_as_persisted_state(self):
        self.assertEqual(
            _next_day2_due("2026-10-26T12:00:00+00:00", "online"),
            "2026-10-26T23:00:00+00:00",
        )
        await self.flow.education_onboarding_action(self.update, "education_onboarding_start")
        due = self.progress()["day2_due_at"]
        self.assertEqual(due, _next_day2_due(self.progress()["day1_sent_at"], "online"))
        sent_before = self.bot.send_message.await_count

        self.assertTrue(await process_education_onboarding_once(
            self.db, self.bot, self.config,
            now_override=(datetime.fromisoformat(due) + timedelta(seconds=1)).isoformat()))
        self.assertEqual(self.progress()["day2_status"], "sent")
        self.assertEqual(self.progress()["episode1_status"], "in_progress")
        self.assertEqual(self.bot.send_message.await_count, sent_before + 1)
        day2_message = self.bot.send_message.await_args.kwargs
        self.assertIn("SMART MONEY HUB | DAY 2: EPISODE 01", day2_message["text"])
        self.assertIn("UNDERSTANDING MARKET STRUCTURE", day2_message["text"])
        self.assertIn("LEARNING OBJECTIVE", day2_message["text"])
        self.assertIn("bullish, bearish or ranging", day2_message["text"])
        self.assertIn("at least two significant swing highs", day2_message["text"])
        self.assertIn("NO CONFIRMATION, NO ENTRY.", day2_message["text"])
        self.assertEqual(
            day2_message["reply_markup"].inline_keyboard[0][0].url,
            self.config.education_episode_01_url,
        )
        video_button = day2_message["reply_markup"].inline_keyboard[1][0]
        self.assertEqual(video_button.text, "Watch Market Structure video")
        self.assertEqual(video_button.url, self.config.education_market_structure_video_url)
        self.assertFalse(await process_education_onboarding_once(
            self.db, self.bot, self.config, now_override="2026-10-28T00:00:00+00:00"))
        self.assertEqual(self.bot.send_message.await_count, sent_before + 1)

    async def test_coach_button_is_shown_only_when_a_verified_link_is_configured(self):
        self.config.education_coach_bot_url = "https://t.me/smh_coach_test_bot"
        await self.flow.education_onboarding_preview(self.update)
        self.assertEqual(self.bot.send_message.await_count, 3)
        day1_buttons = [
            button.text for row in self.bot.send_message.await_args_list[0].kwargs[
                "reply_markup"].inline_keyboard for button in row
        ]
        day2_buttons = [
            button.text for row in self.bot.send_message.await_args_list[1].kwargs[
                "reply_markup"].inline_keyboard for button in row
        ]
        self.assertIn("Open Smart Money Hub Coach", day1_buttons)
        self.assertIn("Open Smart Money Hub Coach", day2_buttons)
        day3_buttons = [
            button.text for row in self.bot.send_message.await_args_list[2].kwargs[
                "reply_markup"].inline_keyboard for button in row
        ]
        self.assertIn("Watch Episode 02 video", day3_buttons)
        self.assertIn("Open Episode 02 PDF", day3_buttons)

    async def test_episode_message_does_not_claim_a_missing_video_link(self):
        self.config.education_market_structure_video_url = ""
        await self.flow.education_onboarding_preview(self.update)
        day2 = self.bot.send_message.await_args_list[1].kwargs["text"]
        self.assertNotIn("Market Structure video button below", day2)

    async def test_assignment_is_saved_without_inventing_completion_or_later_episode(self):
        await self.flow.education_onboarding_action(self.update, "education_onboarding_start")
        due = self.progress()["day2_due_at"]
        await process_education_onboarding_once(
            self.db, self.bot, self.config,
            now_override=(datetime.fromisoformat(due) + timedelta(seconds=1)).isoformat())
        await self.flow.education_onboarding_action(self.update, "education_onboarding_assignment")
        handled = await self.flow.education_onboarding_handle_text(
            self.update, "XAUUSD is 4,000. BUY means opening a position expecting price to rise.")
        self.assertTrue(handled)
        progress = self.progress()
        self.assertEqual(progress["assignment_status"], "submitted")
        self.assertEqual(progress["episode1_status"], "assignment_submitted")
        self.assertEqual(
            progress["assignment_text"],
            "XAUUSD is 4,000. BUY means opening a position expecting price to rise.")
        self.assertEqual(progress["day3_status"], "pending")
        self.assertIn("Episode 02 is scheduled for the next Lagos day",
                      self.bot.send_message.await_args.kwargs["text"])
        due_day3 = progress["day3_due_at"]
        self.assertEqual(
            due_day3,
            _next_day2_due(progress["assignment_submitted_at"], "online"),
        )
        sent_before_day3 = self.bot.send_message.await_count
        self.assertTrue(await process_education_onboarding_once(
            self.db, self.bot, self.config,
            now_override=(datetime.fromisoformat(due_day3) + timedelta(seconds=1)).isoformat()))
        self.assertEqual(self.progress()["day3_status"], "sent")
        self.assertEqual(self.progress()["episode2_status"], "in_progress")
        day3_message = self.bot.send_message.await_args.kwargs
        self.assertIn("DAY 3: EPISODE 02", day3_message["text"])
        self.assertIn("BREAK OF STRUCTURE (BOS)", day3_message["text"])
        self.assertEqual(
            day3_message["reply_markup"].inline_keyboard[0][0].url,
            self.config.education_episode_02_video_url,
        )
        self.assertEqual(
            day3_message["reply_markup"].inline_keyboard[1][0].url,
            self.config.education_episode_02_pdf_url,
        )
        self.assertFalse(await process_education_onboarding_once(
            self.db, self.bot, self.config,
            now_override=(datetime.fromisoformat(due_day3) + timedelta(days=1)).isoformat()))
        self.assertEqual(self.bot.send_message.await_count, sent_before_day3 + 1)

    async def test_admin_preview_sends_both_messages_without_enrolling_or_saving_progress(self):
        await self.flow.education_onboarding_preview(self.update)

        self.assertEqual(self.bot.send_message.await_count, 3)
        day1, day2, day3 = [call.kwargs for call in self.bot.send_message.await_args_list]
        self.assertNotIn("ONBOARDING PREVIEW", day1["text"])
        self.assertIn("DAY 1: EDUCATION ORIENTATION", day1["text"])
        self.assertIn("Today is strictly for orientation", day1["text"])
        day1_buttons = {
            button.text: button.url
            for row in day1["reply_markup"].inline_keyboard
            for button in row
        }
        self.assertEqual(day1_buttons["Education access link"], self.config.education_link)
        self.assertEqual(
            day1_buttons["How to open a demo account"], self.config.education_demo_account_url)
        self.assertNotIn("ONBOARDING PREVIEW", day2["text"])
        self.assertIn("SMART MONEY HUB | DAY 2: EPISODE 01", day2["text"])
        self.assertIn("UNDERSTANDING MARKET STRUCTURE", day2["text"])
        self.assertIn("identify whether the market is bullish, bearish or ranging", day2["text"])
        self.assertIn("Submit your completed assignment privately", day2["text"])
        buttons = day2["reply_markup"].inline_keyboard
        self.assertEqual(buttons[0][0].url, self.config.education_episode_01_url)
        self.assertEqual(buttons[1][0].text, "Watch Market Structure video")
        self.assertEqual(buttons[1][0].url, self.config.education_market_structure_video_url)
        self.assertEqual(self.db.consume(buttons[2][0].callback_data, 12345)[0],
                         "admin_education_preview_assignment")
        self.assertIn("DAY 3: EPISODE 02", day3["text"])
        episode_02_video = day3["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(episode_02_video.text, "Watch Episode 02 video")
        self.assertEqual(episode_02_video.url, self.config.education_episode_02_video_url)
        episode_02_pdf = day3["reply_markup"].inline_keyboard[1][0]
        self.assertEqual(episode_02_pdf.text, "Open Episode 02 PDF")
        self.assertEqual(episode_02_pdf.url, self.config.education_episode_02_pdf_url)
        self.assertIsNone(self.progress())

        await self.flow.education_onboarding_preview_assignment(self.update)
        self.assertIn("Send your Episode 01 assignment as a text message", self.bot.send_message.await_args.kwargs["text"])
        self.assertIsNone(self.progress())

    async def test_education_preview_is_blocked_outside_isolated_test_bot(self):
        self.config.isolated_test = False
        with self.assertRaises(PermissionError):
            await self.flow.education_onboarding_preview(self.update)
        self.bot.send_message.assert_not_awaited()

    async def test_disabled_environment_sends_nothing(self):
        self.config.education_onboarding_enabled = False
        self.assertFalse(await process_education_onboarding_once(
            self.db, self.bot, self.config, now_override=datetime.now(timezone.utc).isoformat()))
        self.bot.send_message.assert_not_awaited()

    async def test_disabled_onboarding_rejects_start_without_creating_progress(self):
        self.config.education_onboarding_enabled = False
        await self.flow.education_onboarding_action(self.update, "education_onboarding_start")
        self.assertIn("not enabled", self.bot.send_message.await_args.kwargs["text"])
        self.assertIsNone(self.progress())
        self.bot.get_chat_member.assert_not_awaited()

    async def test_restart_quarantines_interrupted_lesson_sends_without_replaying(self):
        self.db.put("education:onboarding:12345", {
            "version": 1,
            "user_id": 12345,
            "initiated": True,
            "day1_status": "sending",
            "day2_status": "sending",
        })
        self.assertEqual(recover_education_onboarding(self.db), 1)
        progress = self.progress()
        self.assertEqual(progress["day1_status"], "uncertain")
        self.assertEqual(progress["day2_status"], "uncertain")
        self.bot.send_message.assert_not_awaited()

    async def test_uncertain_day1_is_not_retried(self):
        self.bot.send_message.side_effect = TimeoutError()
        await self.flow.education_onboarding_action(self.update, "education_onboarding_start")
        self.assertEqual(self.progress()["day1_status"], "uncertain")
        self.bot.send_message.side_effect = None
        await self.flow.education_onboarding_action(self.update, "education_onboarding_check")
        self.assertEqual(self.progress()["day1_status"], "uncertain")
        self.assertEqual(self.bot.send_message.await_count, 1)


class EducationAdminPreviewCallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name))
        self.config = SimpleNamespace(
            admin=12345,
            isolated_test=True,
            education_onboarding_enabled=False,
            education_announcement_url="https://t.me/c/3916437804/3",
            education_demo_account_url="https://t.me/c/3916437804/2/57",
            education_episode_01_url="https://t.me/c/3916437804/6/23",
            education_market_structure_video_url="https://t.me/c/3916437804/8/125",
            education_episode_02_video_url="https://t.me/c/3916437804/8/143",
            education_episode_02_pdf_url="https://t.me/c/3916437804/6/24",
        )
        self.bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)))
        self.handlers = object.__new__(Handlers)
        self.handlers.db = self.db
        self.handlers.config = self.config
        self.handlers.bot = self.bot
        self.update = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private", id=12345),
            effective_user=SimpleNamespace(id=12345),
            callback_query=SimpleNamespace(
                answer=AsyncMock(),
                data=self.db.button(12345, "admin_education_preview", {}),
            ),
        )

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    async def test_admin_button_delivers_preview_and_assignment_button_is_non_mutating(self):
        await self.handlers.callback(self.update, None)
        self.assertEqual(self.bot.send_message.await_count, 3)
        preview = self.bot.send_message.await_args_list[1].kwargs
        self.assertNotIn("ONBOARDING PREVIEW", preview["text"])
        self.assertIn("SMART MONEY HUB | DAY 2: EPISODE 01", preview["text"])

        video_button = preview["reply_markup"].inline_keyboard[1][0]
        self.assertEqual(video_button.text, "Watch Market Structure video")
        self.assertEqual(video_button.url, self.config.education_market_structure_video_url)
        assignment_button = preview["reply_markup"].inline_keyboard[2][0]
        self.update.callback_query.data = assignment_button.callback_data
        await self.handlers.callback(self.update, None)
        self.assertEqual(self.bot.send_message.await_count, 4)
        self.assertIn("Send your Episode 01 assignment as a text message",
                      self.bot.send_message.await_args.kwargs["text"])
        self.assertIsNone(self.db.get("education:onboarding:12345"))


if __name__ == "__main__":
    unittest.main()
