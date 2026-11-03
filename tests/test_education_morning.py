from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from smart_money_hub_bot.education_morning import (
    EducationMorningPublisher,
    EducationMorningStore,
    MORNING_LESSONS,
    MORNING_TIME,
    MORNING_ZONE,
    MorningLesson,
    render_morning_post,
)
from smart_money_hub_bot.education_polls import EXPECTED_EDUCATION_GROUP_ID
from smart_money_hub_bot.storage import Repository

WAT = ZoneInfo("Africa/Lagos")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


class StrictTelegramHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "b" or attrs:
            self.errors.append(f"unsupported tag: {tag}")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(f"mismatched tag: {tag}")

    def handle_entityref(self, name: str) -> None:
        if not name:
            self.errors.append("empty entity")

    def handle_charref(self, name: str) -> None:
        if not name:
            self.errors.append("empty character reference")


class FakeTelegram:
    def __init__(self) -> None:
        self.group_sends: list[tuple[int, str, str | None]] = []
        self.admin_sends: list[tuple[int, str]] = []
        self.group_id = EXPECTED_EDUCATION_GROUP_ID
        self.group_type = "supergroup"
        self.member_status = "administrator"
        self.fail_send = None

    def get_me(self):
        return {"id": 987654}

    def get_chat(self, chat_id: int):
        return {"id": self.group_id, "type": self.group_type, "title": "Education"}

    def get_chat_member(self, chat_id: int, user_id: int):
        return {"status": self.member_status}

    def send_message_with_result(self, chat_id: int, text: str, *, parse_mode=None):
        self.group_sends.append((chat_id, text, parse_mode))
        if self.fail_send:
            raise self.fail_send
        return {
            "message_id": 1000 + len(self.group_sends),
            "date": int(datetime.now(timezone.utc).timestamp()),
        }

    def send_message(self, chat_id: int, text: str):
        self.admin_sends.append((chat_id, text))


class EducationMorningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "bot.sqlite3"
        self.history = Repository(self.database)
        self.api = FakeTelegram()
        self.admin_id = 77
        self.publisher = EducationMorningPublisher(
            self.api,
            self.database,
            admin_id=self.admin_id,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            group_history_store=self.history,
        )
        self.publisher.store.set_enabled(True, now=NOW)

    def test_morning_auto_posts_are_paused_by_default(self):
        store = EducationMorningStore(Path(self.temp_dir.name) / "paused.sqlite3")
        paused = EducationMorningPublisher(
            self.api,
            Path(self.temp_dir.name) / "paused.sqlite3",
            admin_id=self.admin_id,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            group_history_store=self.history,
        )
        paused.dispatch_due(datetime(2026, 10, 26, 8, 0, tzinfo=WAT))
        self.assertFalse(store.is_enabled())
        self.assertEqual(self.api.group_sends, [])
        self.assertIsNone(store.get("2026-10-26"))

    def test_daily_schedule_sends_once_at_0800_wat_and_archives_post(self):
        due = datetime(2026, 10, 26, 8, 0, tzinfo=WAT)
        self.publisher.dispatch_due(due)
        self.publisher.dispatch_due(due + timedelta(minutes=1))
        self.assertEqual(len(self.api.group_sends), 1)
        chat_id, text, parse_mode = self.api.group_sends[0]
        self.assertEqual(chat_id, EXPECTED_EDUCATION_GROUP_ID)
        self.assertEqual(parse_mode, "HTML")
        self.assertIn("SMART MONEY HUB | TRADING EDUCATION", text)
        self.assertIn("TODAY’S LESSON:", text)
        self.assertNotIn("GOOD MORNING", text)
        self.assertNotIn("TODAY’S LEARNING FOCUS", text)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", text)
        run = EducationMorningStore(self.database).get("2026-10-26")
        self.assertEqual(run["status"], "sent")
        self.assertIsInstance(run["telegram_message_id"], int)
        archived = self.history.recent_education_group_posts(
            EXPECTED_EDUCATION_GROUP_ID,
            since="2026-10-26T00:00:00+00:00",
            limit=10,
        )
        self.assertEqual(len(archived), 1)
        run = EducationMorningStore(self.database).get("2026-10-26")
        self.assertEqual(archived[0]["topic_name"], run["topic"])
        self.assertTrue(archived[0]["content"])

    def test_each_scheduled_day_uses_a_different_message(self):
        first = datetime(2026, 10, 26, 8, 0, tzinfo=WAT)
        second = first + timedelta(days=1)
        self.publisher.dispatch_due(first)
        self.publisher.dispatch_due(second)
        self.assertEqual(len(self.api.group_sends), 2)
        self.assertNotEqual(self.api.group_sends[0][1], self.api.group_sends[1][1])
        self.assertNotEqual(
            EducationMorningStore(self.database).get("2026-10-26")["content_hash"],
            EducationMorningStore(self.database).get("2026-10-27")["content_hash"],
        )

    def test_saturday_post_mentions_only_the_configured_weekly_poll(self):
        saturday = datetime(2026, 10, 31, 8, 0, tzinfo=WAT)
        self.publisher.dispatch_due(saturday)
        self.assertIn("9:00 PM WAT tonight", self.api.group_sends[0][1])
        monday = datetime(2026, 11, 2, 8, 0, tzinfo=WAT)
        self.publisher.dispatch_due(monday)
        self.assertNotIn("9:00 PM WAT tonight", self.api.group_sends[1][1])

    def test_missed_window_is_recorded_and_not_sent_late(self):
        late = datetime(2026, 10, 26, 8, 31, tzinfo=WAT)
        self.publisher.dispatch_due(late)
        self.assertEqual(self.api.group_sends, [])
        run = EducationMorningStore(self.database).get("2026-10-26")
        self.assertEqual(run["status"], "skipped")
        self.assertEqual(run["failure_category"], "missed_morning_window")
        self.assertEqual(self.api.admin_sends[0][0], self.admin_id)

    def test_post_is_sent_once_inside_30_minute_late_window(self):
        late = datetime(2026, 10, 26, 8, 20, tzinfo=WAT)
        self.publisher.dispatch_due(late)
        self.publisher.dispatch_due(late + timedelta(minutes=1))
        self.assertEqual(len(self.api.group_sends), 1)
        run = EducationMorningStore(self.database).get("2026-10-26")
        self.assertEqual(run["status"], "sent")
        self.assertIsInstance(run["telegram_message_id"], int)

    def test_exact_30_minute_boundary_is_eligible(self):
        boundary = datetime(2026, 10, 26, 8, 30, tzinfo=WAT)
        self.publisher.dispatch_due(boundary)
        self.assertEqual(len(self.api.group_sends), 1)
        self.assertEqual(
            EducationMorningStore(self.database).get("2026-10-26")["status"],
            "sent",
        )

    def test_unverified_destination_or_permissions_hold_without_group_send(self):
        due = datetime(2026, 10, 26, 8, 0, tzinfo=WAT)
        self.api.group_type = "group"
        self.publisher.dispatch_due(due)
        self.assertEqual(self.api.group_sends, [])
        run = EducationMorningStore(self.database).get("2026-10-26")
        self.assertEqual(run["status"], "failed")
        self.assertTrue(self.api.admin_sends)

    def test_interrupted_send_is_marked_unknown_and_never_resent(self):
        store = EducationMorningStore(self.database)
        due = datetime(2026, 10, 26, 8, 0, tzinfo=WAT)
        store.create(
            schedule_date="2026-10-26",
            scheduled_at=due,
            topic="risk",
            content="Stored before interruption",
            status="sending",
            failure_category=None,
            now=due,
        )
        self.publisher.dispatch_due(due + timedelta(minutes=1))
        self.publisher.dispatch_due(due + timedelta(minutes=2))
        self.assertEqual(self.api.group_sends, [])
        run = store.get("2026-10-26")
        self.assertEqual(run["status"], "delivery_unknown")
        self.assertEqual(run["failure_category"], "interrupted_during_send")

    def test_telegram_html_is_escaped_well_formed_and_within_limit(self):
        lesson = MorningLesson(
            topic="test",
            title="A & B < C",
            lesson="Review <this> & consider the context.",
            practice="Check <confirmation> before entry.",
            keywords=("test",),
        )
        text = render_morning_post(
            lesson,
        )
        self.assertIn("&lt;this&gt; &amp;", text)
        parser = StrictTelegramHTML()
        parser.feed(text)
        parser.close()
        self.assertEqual(parser.errors, [])
        self.assertEqual(parser.stack, [])
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)

    def test_poi_education_post_uses_branded_lesson_layout_without_greeting(self):
        lesson = next(item for item in MORNING_LESSONS if item.topic == "poi")
        text = render_morning_post(lesson)
        self.assertTrue(text.startswith("📊 <b>SMART MONEY HUB | TRADING EDUCATION</b>"))
        self.assertIn(
            "📚 <b>TODAY’S LESSON: A POINT OF INTEREST IS NOT AN ENTRY</b>",
            text,
        )
        self.assertIn(
            "A POI identifies where to pay attention, not when to enter.", text
        )
        self.assertIn("<b>BEFORE CONSIDERING ANY TRADE</b>", text)
        self.assertIn(
            "✅ Wait for price to confirm the setup; do not enter simply because it reached the zone.",
            text,
        )
        self.assertIn("🛡️ <b>NO CONFIRMATION, NO ENTRY.</b>", text)
        self.assertNotIn("GOOD MORNING", text.upper())

    def test_recent_group_archive_informs_topic_novelty_without_private_history(self):
        self.history.record_education_group_post(
            chat_id=EXPECTED_EDUCATION_GROUP_ID,
            message_id=2001,
            thread_id=None,
            topic_name="risk",
            message_kind="text",
            content="Recent risk and invalidation discussion",
            source_status="configured_admin",
            posted_at="2026-10-25T08:00:00+00:00",
        )
        self.history.record_education_group_post(
            chat_id=EXPECTED_EDUCATION_GROUP_ID,
            message_id=2002,
            thread_id=None,
            topic_name="risk",
            message_kind="text",
            content="Not trusted for topic selection",
            source_status="unverified",
            posted_at="2026-10-25T09:00:00+00:00",
        )
        recent = self.history.recent_education_group_posts(
            EXPECTED_EDUCATION_GROUP_ID,
            since="2026-10-24T00:00:00+00:00",
            limit=30,
        )
        self.assertEqual(len(recent), 1)
        selected = self.publisher._select_content(datetime(2026, 10, 26).date())
        self.assertIsNotNone(selected)
        self.assertNotIn("risk", selected[0].topic)

    def test_recent_education_lesson_subject_is_not_reused(self):
        previous = datetime(2026, 10, 25, 8, tzinfo=MORNING_ZONE)
        self.publisher.store.create(
            schedule_date="2026-10-25",
            scheduled_at=previous,
            topic="poi",
            content="Previously sent POI lesson.",
            status="sent",
            failure_category=None,
            now=previous.astimezone(timezone.utc),
        )

        selected = self.publisher._select_content(datetime(2026, 10, 26).date())

        self.assertIsNotNone(selected)
        self.assertNotEqual(selected[0].topic, "poi")


if __name__ == "__main__":
    unittest.main()
