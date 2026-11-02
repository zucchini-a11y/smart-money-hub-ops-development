from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from smart_money_hub_bot.daily_calendar_brief import (
    MARKET_ANALYSIS_CHANNEL_ID,
    DailyCalendarBriefPublisher,
    DailyCalendarBriefStore,
    build_daily_usd_gold_brief,
)
from smart_money_hub_bot.brief_photo_review import NewsBriefPhotoPrompts
from smart_money_hub_bot.economic_calendar_phase1 import (
    OfficialCalendarRecord,
    OfficialCalendarRepository,
)
from smart_money_hub_bot.telegram_api import TelegramAPIError

NOW = datetime(2026, 10, 28, 23, 5, tzinfo=timezone.utc)  # Oct 29, 00:05 WAT
BRIEF_DATE = date(2026, 10, 29)


def add_verified_sources(database: Path, now: datetime) -> None:
    repository = OfficialCalendarRepository(database)
    event = OfficialCalendarRecord(
        external_id="bea:gdp-2026-10-29",
        source_name="U.S. Bureau of Economic Analysis",
        affected_instrument="USD / XAUUSD",
        title="Gross Domestic Product",
        source_url="https://www.bea.gov/news/schedule",
        retrieved_at=now,
        release_date_text="Thu, 29 Oct 2026",
        release_time_text="2026-10-29T12:30:00+00:00",
        event_at_utc=datetime(2026, 10, 29, 12, 30, tzinfo=timezone.utc),
        timezone_status="verified_explicit_utc_offset",
    )
    census = OfficialCalendarRecord(
        external_id="census:retail-2026-10",
        source_name="U.S. Census Bureau",
        affected_instrument="USD / XAUUSD",
        title="Advance Monthly Sales for Retail and Food Services",
        source_url="https://www.census.gov/economic-indicators/calendar-listview.html",
        retrieved_at=now,
        release_date_text="October 29, 2026",
        release_time_text="8:30 AM",
        event_at_utc=None,
        timezone_status="unverified_no_timezone_in_source",
        verification_status="date_time_listed_timezone_unverified",
    )
    repository.save_records([event, census])
    for name, status, http_status in (
        ("BEA", "verified_schedule", None),
        ("Census", "verified_schedule", None),
        ("BLS", "UNAVAILABLE — SOURCE NOT VERIFIED", 403),
        ("DOL", "UNAVAILABLE — SOURCE NOT VERIFIED", 403),
    ):
        repository.record_source_status(
            name, status=status, checked_at=now, http_status=http_status
        )


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.channel_messages: list[dict] = []
        self.admin_messages: list[dict] = []
        self.send_attempts = 0
        self.uncertain_send = False
        self.chat_id = MARKET_ANALYSIS_CHANNEL_ID
        self.chat_title = "Smart Money Hub"
        self.member = {"status": "administrator", "can_post_messages": True}

    def get_me(self) -> dict:
        return {"id": 12345}

    def get_chat(self, chat_id: int) -> dict:
        return {"id": self.chat_id, "type": "channel", "title": self.chat_title}

    def get_chat_member(self, chat_id: int, user_id: int) -> dict:
        return self.member

    def send_message_with_result(
        self, chat_id: int, text: str, *, parse_mode: str | None = None
    ) -> dict:
        self.send_attempts += 1
        if self.uncertain_send:
            raise TelegramAPIError(
                "Telegram delivery is uncertain.", delivery_unknown=True
            )
        self.channel_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )
        return {"message_id": 987}

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        *,
        parse_mode: str | None = None,
    ) -> None:
        self.admin_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )


class DailyCalendarBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "brief.sqlite3"
        self.api = FakeTelegramAPI()

    def make_publisher(
        self,
        *,
        channel_id: int = MARKET_ANALYSIS_CHANNEL_ID,
        photo_prompts: NewsBriefPhotoPrompts | None = None,
        refresh=add_verified_sources,
    ) -> DailyCalendarBriefPublisher:
        return DailyCalendarBriefPublisher(
            self.api,
            self.database,
            admin_id=444,
            channel_id=channel_id,
            photo_prompts=photo_prompts,
            source_refresh=refresh,
        )

    def test_photo_prompt_is_private_and_ignored_photo_does_not_hold_brief(self) -> None:
        prompts = NewsBriefPhotoPrompts(
            self.api, self.database, admin_id=444
        )
        refresh_count = 0

        def refresh_once(database_path, *, now):
            nonlocal refresh_count
            refresh_count += 1
            add_verified_sources(database_path, now=now)

        publisher = self.make_publisher(
            photo_prompts=prompts,
            refresh=refresh_once,
        )
        prompt_time = datetime(2026, 10, 28, 22, 55, tzinfo=timezone.utc)

        self.assertTrue(publisher.dispatch_photo_prompt(prompt_time))
        self.assertEqual(self.api.admin_messages[0]["chat_id"], 444)
        self.assertIn("Market Analysis channel", self.api.admin_messages[0]["text"])
        self.assertIn("Scheduled: 00:00 WAT", self.api.admin_messages[0]["text"])
        self.assertIn("SMART MONEY HUB", self.api.admin_messages[1]["text"])
        self.assertFalse(publisher.dispatch_photo_prompt(prompt_time))
        self.assertEqual(refresh_count, 1)

        self.assertEqual(publisher.dispatch(NOW), "published")
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(self.api.send_attempts, 1)

    def test_publishes_verified_daily_brief_once_and_recovers_after_restart(self) -> None:
        publisher = self.make_publisher()

        self.assertEqual(publisher.dispatch(NOW), "published")
        self.assertEqual(len(self.api.channel_messages), 1)
        message = self.api.channel_messages[0]
        self.assertEqual(message["chat_id"], MARKET_ANALYSIS_CHANNEL_ID)
        self.assertEqual(message["parse_mode"], "HTML")
        self.assertIn("SMART MONEY HUB | DAILY NEWS", message["text"])
        self.assertIn("HIGH-IMPACT NEWS", message["text"])
        self.assertIn("MEDIUM-IMPACT NEWS", message["text"])
        self.assertIn("GOLD (XAUUSD) WATCH", message["text"])
        self.assertIn("VERIFIED U.S. RELEASES", message["text"])
        self.assertIn("SOURCES &amp; CHECK TIME", message["text"])
        self.assertIn("13:30 WAT", message["text"])
        self.assertIn("Gross Domestic Product", message["text"])
        self.assertIn("Forecast: Unavailable", message["text"])
        self.assertNotIn("HTTP 403", message["text"])
        self.assertIn("BLS and DOL schedule coverage is not verified", message["text"])
        self.assertNotIn("8:30 AM", message["text"])
        self.assertIn("Census dates are omitted from timed listings", message["text"])
        self.assertIn("Checked: Thu, 29 Oct 2026 at 00:05 WAT", message["text"])
        self.assertLessEqual(
            len(message["text"].encode("utf-16-le")) // 2, 4096
        )
        self.assertTrue(self.api.admin_messages)
        self.assertEqual(
            DailyCalendarBriefStore(self.database).get(BRIEF_DATE)["status"],
            "published",
        )

        restarted = self.make_publisher()
        self.assertEqual(restarted.dispatch(NOW), "already_published")
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(self.api.send_attempts, 1)

    def test_does_not_publish_a_missed_brief_late_before_next_midnight(self) -> None:
        publisher = self.make_publisher()
        late_evening = datetime(2026, 10, 28, 22, 59, tzinfo=timezone.utc)

        self.assertEqual(publisher.dispatch(late_evening), "skipped_late")
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(self.api.send_attempts, 0)
        self.assertEqual(
            DailyCalendarBriefStore(self.database)
            .get(date(2026, 10, 28))["status"],
            "skipped",
        )
        self.assertEqual(self.api.admin_messages, [])

    def test_missed_midnight_window_is_not_published_late(self) -> None:
        publisher = self.make_publisher()
        after_window = datetime(2026, 10, 29, 0, 20, tzinfo=timezone.utc)

        self.assertEqual(publisher.dispatch(after_window), "skipped_late")
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(
            DailyCalendarBriefStore(self.database).get(BRIEF_DATE)["status"],
            "skipped",
        )
        self.assertEqual(self.api.admin_messages, [])

    def test_wrong_destination_or_missing_permission_holds_without_channel_send(self) -> None:
        wrong_destination = self.make_publisher(channel_id=-1001234567890)
        self.assertEqual(wrong_destination.dispatch(NOW), "held")
        self.assertEqual(self.api.channel_messages, [])

        self.database.unlink(missing_ok=True)
        self.api.admin_messages.clear()
        self.api.member = {"status": "administrator", "can_post_messages": False}
        missing_permission = self.make_publisher()
        self.assertEqual(missing_permission.dispatch(NOW), "held")
        self.assertEqual(self.api.channel_messages, [])

    def test_unverified_bea_source_is_held_and_admin_is_notified(self) -> None:
        def failed_refresh(database: Path, *, now: datetime) -> dict:
            repository = OfficialCalendarRepository(database)
            repository.record_source_status(
                "BEA",
                status="UNAVAILABLE — SOURCE NOT VERIFIED",
                checked_at=now,
                failure_category="permission_error",
                http_status=403,
            )
            return {"BEA": "UNAVAILABLE — SOURCE NOT VERIFIED"}

        publisher = self.make_publisher(refresh=failed_refresh)

        self.assertEqual(publisher.dispatch(NOW), "held_source_unverified")
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(len(self.api.admin_messages), 1)
        self.assertIn("No channel post was sent", self.api.admin_messages[0]["text"])

    def test_held_brief_requires_private_preview_and_explicit_publish_action(self) -> None:
        publisher = self.make_publisher()
        store = DailyCalendarBriefStore(self.database)
        self.assertTrue(store.reserve(BRIEF_DATE, NOW))
        store.finish(
            BRIEF_DATE,
            status="held",
            now=NOW,
            failure_category="source_temporarily_unavailable",
        )

        status, preview = publisher.prepare_held_review(now=NOW)

        self.assertEqual(status, "awaiting_approval")
        self.assertIsNotNone(preview)
        self.assertIn("Not published", preview)
        self.assertIn("Market Analysis", preview)
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(self.api.send_attempts, 0)
        self.assertEqual(len(self.api.admin_messages), 1)
        controls = self.api.admin_messages[0]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual(controls[0]["text"], "Publish Now")
        self.assertEqual(controls[0]["callback_data"], "dailybrief:publish:2026-10-29")
        self.assertEqual(controls[1]["callback_data"], "dailybrief:cancel:2026-10-29")

        restarted = self.make_publisher()
        self.assertEqual(restarted.publish_reviewed(BRIEF_DATE, now=NOW), "published")
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(self.api.send_attempts, 1)
        self.assertEqual(
            publisher.publish_reviewed(BRIEF_DATE, now=NOW), "not_awaiting_approval"
        )
        self.assertEqual(self.api.send_attempts, 1)

    def test_cancelled_or_skipped_brief_cannot_be_published_by_recovery(self) -> None:
        publisher = self.make_publisher()
        store = DailyCalendarBriefStore(self.database)
        self.assertTrue(store.reserve(BRIEF_DATE, NOW))
        store.finish(BRIEF_DATE, status="held", now=NOW)
        self.assertEqual(publisher.prepare_held_review(now=NOW)[0], "awaiting_approval")
        self.assertTrue(publisher.cancel_review(BRIEF_DATE, now=NOW))
        self.assertEqual(
            store.get(BRIEF_DATE)["failure_category"], "admin_cancelled_retry"
        )
        self.assertEqual(publisher.publish_reviewed(BRIEF_DATE, now=NOW), "not_awaiting_approval")
        self.assertEqual(self.api.channel_messages, [])

        skipped_now = datetime(2026, 10, 29, 23, 20, tzinfo=timezone.utc)
        self.assertEqual(
            publisher.dispatch(skipped_now),
            "skipped_late",
        )
        self.assertEqual(
            publisher.prepare_held_review(now=skipped_now)[0],
            "not_recoverable:skipped",
        )
        self.assertEqual(self.api.channel_messages, [])

    def test_uncertain_telegram_send_is_not_retried(self) -> None:
        self.api.uncertain_send = True
        publisher = self.make_publisher()

        self.assertEqual(publisher.dispatch(NOW), "delivery_unknown")
        self.assertEqual(publisher.dispatch(NOW), "already_delivery_unknown")
        self.assertEqual(self.api.send_attempts, 1)
        self.assertEqual(self.api.channel_messages, [])

    def test_brief_escapes_event_title_and_never_infers_missing_values(self) -> None:
        add_verified_sources(self.database, NOW)
        repository = OfficialCalendarRepository(self.database)
        records = repository.list_records()
        for record in records:
            if record.get("source_name") == "U.S. Bureau of Economic Analysis":
                record["title"] = "<GDP & data>"
                break
        preview = build_daily_usd_gold_brief(
            BRIEF_DATE,
            records,
            repository.list_source_status(),
            now=NOW,
        )

        self.assertIn("&lt;GDP &amp; data&gt;", preview)
        self.assertNotIn("<GDP & data>", preview)
        self.assertIn("Previous: Unavailable", preview)
        self.assertIn("Forecast: Unavailable", preview)
        self.assertIn("Actual: Unavailable", preview)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", preview)

    def test_empty_calendar_brief_is_clear_and_does_not_pose_as_market_news(self) -> None:
        preview = build_daily_usd_gold_brief(
            BRIEF_DATE,
            [],
            [
                {"source_name": "BEA", "status": "verified_schedule"},
                {"source_name": "Census", "status": "verified_schedule"},
                {"source_name": "BLS", "status": "UNAVAILABLE — SOURCE NOT VERIFIED", "http_status": 403},
                {"source_name": "DOL", "status": "UNAVAILABLE — SOURCE NOT VERIFIED", "http_status": 403},
            ],
            now=NOW,
        )

        self.assertIn("SMART MONEY HUB | DAILY NEWS", preview)
        self.assertIn("HIGH-IMPACT NEWS", preview)
        self.assertIn("MEDIUM-IMPACT NEWS", preview)
        self.assertIn("GOLD (XAUUSD) WATCH", preview)
        self.assertIn("VERIFIED U.S. RELEASES", preview)
        self.assertIn("No verified BEA release is scheduled for this date.", preview)
        self.assertIn("No verified result or current market data", preview)
        self.assertIn("Census times are omitted until its timezone is confirmed", preview)
        self.assertNotIn("HTTP 403", preview)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", preview)


if __name__ == "__main__":
    unittest.main()
