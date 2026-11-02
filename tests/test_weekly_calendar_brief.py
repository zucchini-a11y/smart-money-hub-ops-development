from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from smart_money_hub_bot.economic_calendar_phase1 import (
    OfficialCalendarRecord,
    OfficialCalendarRepository,
)
from smart_money_hub_bot.group_features import (
    DEFAULT_EDUCATION_GROUP_ID,
    EDUCATION_ANNOUNCEMENTS_THREAD_ID,
)
from smart_money_hub_bot.brief_photo_review import NewsBriefPhotoPrompts
from smart_money_hub_bot.telegram_api import TelegramAPIError
from smart_money_hub_bot.weekly_calendar_brief import (
    WeeklyCalendarBriefPublisher,
    WeeklyCalendarBriefStore,
    build_weekly_usd_gold_brief,
)

WEEK_START = date(2026, 11, 2)
NOW = datetime(2026, 11, 1, 23, 5, tzinfo=timezone.utc)  # Monday 00:05 WAT


def official_record(
    *,
    source_name: str,
    title: str,
    event_at_utc: str | None,
    release_date_text: str,
    release_time_text: str | None,
    verification_status: str = "verified_schedule",
    source_url: str,
    external_id: str,
    retrieved_at: datetime = NOW,
) -> OfficialCalendarRecord:
    event_at = (
        datetime.fromisoformat(event_at_utc) if event_at_utc is not None else None
    )
    return OfficialCalendarRecord(
        external_id=external_id,
        source_name=source_name,
        affected_instrument="USD / XAUUSD",
        title=title,
        source_url=source_url,
        retrieved_at=retrieved_at,
        release_date_text=release_date_text,
        release_time_text=release_time_text,
        event_at_utc=event_at,
        timezone_status=(
            "verified_source_timezone:US-Eastern"
            if event_at is not None and source_name.endswith("Statistics")
            else "unverified_no_timezone_in_source"
        ),
        verification_status=verification_status,
    )


def add_current_sources(database: Path, *, now: datetime) -> dict[str, int]:
    repository = OfficialCalendarRepository(database)
    records = [
        official_record(
            source_name="U.S. Bureau of Labor Statistics",
            title="Job Openings and Labor Turnover Survey",
            event_at_utc="2026-11-03T15:00:00+00:00",
            release_date_text="2026-11-03",
            release_time_text="DTSTART;TZID=US-Eastern:20261103T100000",
            source_url="https://www.bls.gov/schedule/news_release/bls.ics",
            external_id="bls:jolts-2026-11-03",
        ),
        official_record(
            source_name="U.S. Bureau of Labor Statistics",
            title="Employment Situation",
            event_at_utc="2026-11-06T13:30:00+00:00",
            release_date_text="2026-11-06",
            release_time_text="DTSTART;TZID=US-Eastern:20261106T083000",
            source_url="https://www.bls.gov/schedule/news_release/bls.ics",
            external_id="bls:employment-2026-11-06",
        ),
        official_record(
            source_name="U.S. Census Bureau",
            title="Construction Spending (Construction Put in Place)",
            event_at_utc=None,
            release_date_text="November 2, 2026",
            release_time_text="10:00 AM",
            verification_status="date_time_listed_timezone_unverified",
            source_url="https://www.census.gov/construction/",
            external_id="census:construction-2026-11-02",
        ),
    ]
    repository.save_records(records)
    for name, status in (
        ("BEA", "verified_schedule"),
        ("BLS", "verified_schedule"),
        ("Census", "verified_schedule"),
        ("Federal Reserve", "verified_schedule"),
        ("DOL", "UNAVAILABLE — SOURCE NOT VERIFIED"),
    ):
        repository.record_source_status(name, status=status, checked_at=now)
    return {"stored": len(records)}


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.channel_messages: list[dict] = []
        self.admin_messages: list[dict] = []
        self.send_attempts = 0
        self.uncertain_send = False
        self.chat_id = DEFAULT_EDUCATION_GROUP_ID
        self.chat_title = "Smart Money Hub Education Suite"
        self.member = {"status": "administrator", "can_send_messages": True}

    def get_me(self) -> dict:
        return {"id": 12345}

    def get_chat(self, chat_id: int) -> dict:
        return {
            "id": self.chat_id,
            "type": "supergroup",
            "title": self.chat_title,
            "is_forum": True,
        }

    def get_chat_member(self, chat_id: int, user_id: int) -> dict:
        return self.member

    def send_message_with_result(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
    ) -> dict:
        self.send_attempts += 1
        if self.uncertain_send:
            raise TelegramAPIError("delivery unknown", delivery_unknown=True)
        self.channel_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "message_thread_id": message_thread_id,
            }
        )
        return {"message_id": 77}

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        *,
        parse_mode: str | None = None,
    ) -> None:
        self.admin_messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )


class WeeklyCalendarBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "weekly.sqlite3"
        self.api = FakeTelegramAPI()

    def publisher(
        self,
        *,
        group_id: int = DEFAULT_EDUCATION_GROUP_ID,
        thread_id: int = EDUCATION_ANNOUNCEMENTS_THREAD_ID,
        photo_prompts: NewsBriefPhotoPrompts | None = None,
        refresh=add_current_sources,
    ):
        return WeeklyCalendarBriefPublisher(
            self.api,
            self.database,
            admin_id=444,
            group_id=group_id,
            thread_id=thread_id,
            photo_prompts=photo_prompts,
            source_refresh=refresh,
        )

    def test_weekly_photo_prompt_targets_monday_announcements_topic(self):
        prompts = NewsBriefPhotoPrompts(
            self.api, self.database, admin_id=444
        )
        publisher = self.publisher(photo_prompts=prompts)
        sunday_2355_wat = datetime(2026, 11, 1, 22, 55, tzinfo=timezone.utc)

        self.assertTrue(publisher.dispatch_photo_prompt(sunday_2355_wat))
        self.assertEqual(self.api.admin_messages[0]["chat_id"], 444)
        self.assertIn(
            "Education Suite Announcements topic",
            self.api.admin_messages[0]["text"],
        )
        self.assertIn("Scheduled: 00:00 WAT", self.api.admin_messages[0]["text"])
        self.assertIn("WEEKLY NEWS OUTLOOK", self.api.admin_messages[1]["text"])
        self.assertEqual(
            self.api.admin_messages[2]["reply_markup"]["inline_keyboard"][0][0][
                "callback_data"
            ],
            "newsbrief:photo:weekly:2026-11-02",
        )

    def test_weekly_preview_converts_verified_bls_times_and_hides_census_time(self):
        add_current_sources(self.database, now=NOW)
        repository = OfficialCalendarRepository(self.database)
        report = build_weekly_usd_gold_brief(
            WEEK_START,
            repository.list_records(),
            repository.list_source_status(),
            now=NOW,
        )
        self.assertIn("SMART MONEY HUB | WEEKLY NEWS OUTLOOK", report)
        self.assertIn("03 Nov", report)
        self.assertIn("16:00 WAT", report)
        self.assertIn("06 Nov", report)
        self.assertIn("14:30 WAT", report)
        self.assertIn("Construction Spending", report)
        self.assertIn("Time: Unavailable in WAT", report)
        self.assertNotIn("10:00 AM", report)
        self.assertIn("Impact: Unavailable", report)
        self.assertIn("Previous: Unavailable · 📊 Forecast: Unavailable", report)
        self.assertIn("DOL schedule coverage is unavailable", report)
        self.assertIn("NO CONFIRMATION, NO ENTRY", report)
        self.assertLessEqual(len(report.encode("utf-16-le")) // 2, 4096)

    def test_gemini_event_importance_is_labeled_as_estimated_not_official(self):
        add_current_sources(self.database, now=NOW)
        repository = OfficialCalendarRepository(self.database)
        report = build_weekly_usd_gold_brief(
            WEEK_START,
            repository.list_records(),
            repository.list_source_status(),
            now=NOW,
            impact_estimates={
                "census:construction-2026-11-02": "Low",
                "bls:jolts-2026-11-03": "High",
            },
        )
        self.assertIn("not official ratings or price-direction predictions", report)
        self.assertIn("Impact: Low (Gemini estimate; not official)", report)
        self.assertIn("Impact: High (Gemini estimate; not official)", report)

    def test_old_source_records_are_not_used_as_current_week_evidence(self):
        old = datetime(2026, 10, 29, tzinfo=timezone.utc)
        repository = OfficialCalendarRepository(self.database)
        repository.save_records(
            [
                official_record(
                    source_name="U.S. Bureau of Labor Statistics",
                    title="Employment Situation",
                    event_at_utc="2026-11-06T13:30:00+00:00",
                    release_date_text="2026-11-06",
                    release_time_text="08:30",
                    source_url="https://www.bls.gov/schedule/news_release/bls.ics",
                    external_id="bls:stale",
                    retrieved_at=old,
                )
            ]
        )
        repository.record_source_status("BEA", status="verified_schedule", checked_at=NOW)
        repository.record_source_status("BLS", status="verified_schedule", checked_at=NOW)
        report = build_weekly_usd_gold_brief(
            WEEK_START,
            repository.list_records(),
            repository.list_source_status(),
            now=NOW,
        )
        self.assertNotIn("Employment Situation", report)

    def test_non_monday_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Monday"):
            build_weekly_usd_gold_brief(
                date(2026, 11, 3), [], [], now=NOW
            )

    def test_monday_publish_is_persistent_and_not_duplicated_after_restart(self):
        publisher = self.publisher()
        self.assertEqual(publisher.dispatch(NOW), "published")
        self.assertEqual(len(self.api.channel_messages), 1)
        message = self.api.channel_messages[0]
        self.assertEqual(message["chat_id"], DEFAULT_EDUCATION_GROUP_ID)
        self.assertEqual(
            message["message_thread_id"], EDUCATION_ANNOUNCEMENTS_THREAD_ID
        )
        self.assertEqual(message["parse_mode"], "HTML")
        self.assertIn("16:00 WAT", message["text"])
        saved = WeeklyCalendarBriefStore(self.database).get(WEEK_START)
        self.assertEqual(saved["status"], "published")
        self.assertEqual(saved["telegram_message_id"], 77)

        restarted = self.publisher()
        self.assertEqual(restarted.dispatch(NOW), "already_published")
        self.assertEqual(self.api.send_attempts, 1)

    def test_recent_daily_ingestion_is_reused_instead_of_refetching_sources(self):
        add_current_sources(self.database, now=NOW)
        calls: list[datetime] = []

        def should_not_refresh(database: Path, *, now: datetime):
            calls.append(now)
            return {}

        publisher = self.publisher(refresh=should_not_refresh)
        self.assertEqual(publisher.dispatch(NOW), "published")
        self.assertEqual(calls, [])
        self.assertEqual(len(self.api.channel_messages), 1)

    def test_late_weekly_run_is_skipped_without_sending(self):
        late = datetime(2026, 11, 2, 0, 16, tzinfo=timezone.utc)  # 01:16 WAT
        self.assertEqual(self.publisher().dispatch(late), "skipped_late")
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(
            WeeklyCalendarBriefStore(self.database).get(WEEK_START)["status"],
            "skipped",
        )

    def test_bea_failure_holds_without_channel_send(self):
        def failed_refresh(database: Path, *, now: datetime):
            repository = OfficialCalendarRepository(database)
            repository.record_source_status(
                "BEA",
                status="UNAVAILABLE — SOURCE NOT VERIFIED",
                checked_at=now,
                failure_category="permission_error",
            )
            return {"BEA": "UNAVAILABLE — SOURCE NOT VERIFIED"}

        self.assertEqual(self.publisher(refresh=failed_refresh).dispatch(NOW), "held_source_unverified")
        self.assertEqual(self.api.channel_messages, [])
        self.assertTrue(self.api.admin_messages)

    def test_wrong_group_holds_without_send(self):
        self.assertEqual(
            self.publisher(group_id=-1001234567890).dispatch(NOW),
            "held",
        )

    def test_wrong_topic_holds_without_send(self):
        self.database = Path(self.temp_dir.name) / "wrong-topic.sqlite3"
        self.assertEqual(
            self.publisher(thread_id=5).dispatch(NOW),
            "held",
        )
        self.assertEqual(self.api.channel_messages, [])

    def test_uncertain_telegram_delivery_is_never_resent(self):
        self.api.uncertain_send = True
        publisher = self.publisher()
        self.assertEqual(publisher.dispatch(NOW), "delivery_unknown")
        self.assertEqual(publisher.dispatch(NOW), "already_delivery_unknown")
        self.assertEqual(self.api.send_attempts, 1)
        self.assertEqual(self.api.channel_messages, [])


if __name__ == "__main__":
    unittest.main()
