from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from smart_money_hub_bot.education_morning import EducationMorningStore, MORNING_ZONE
from smart_money_hub_bot.education_polls import EXPECTED_EDUCATION_GROUP_ID
from smart_money_hub_bot.education_weekend_cleanup import (
    EducationWeekendCleanup,
    EducationWeekendCleanupStore,
)
from smart_money_hub_bot.storage import Repository
from smart_money_hub_bot.telegram_api import TelegramAPIError


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.deleted: list[tuple[int, int]] = []
        self.admin_messages: list[tuple[int, str]] = []
        self.fail_next_delete = False

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise TelegramAPIError(
                "Not enough rights to delete messages.", error_code=403
            )
        self.deleted.append((chat_id, message_id))
        return True

    def send_message(self, chat_id: int, text: str) -> None:
        self.admin_messages.append((chat_id, text))


class EducationWeekendCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "education.sqlite3"
        self.morning_store = EducationMorningStore(self.database)
        self.poll_store = Repository(self.database)
        self.api = FakeTelegramAPI()
        self.cleanup = EducationWeekendCleanup(
            self.api,
            self.database,
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            morning_store=self.morning_store,
            poll_store=self.poll_store,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_weekend_messages(self) -> None:
        saturday_morning = datetime(2026, 10, 31, 8, 0, tzinfo=MORNING_ZONE)
        self.morning_store.create(
            schedule_date="2026-10-31",
            scheduled_at=saturday_morning,
            topic="structure",
            content="Saturday lesson.",
            status="queued",
            failure_category=None,
            now=saturday_morning.astimezone(timezone.utc),
        )
        self.morning_store.finish(
            "2026-10-31",
            status="sent",
            message_id=900,
            now=saturday_morning.astimezone(timezone.utc),
        )
        sunday_morning = datetime(2026, 11, 1, 8, 0, tzinfo=MORNING_ZONE)
        self.morning_store.create(
            schedule_date="2026-11-01",
            scheduled_at=sunday_morning,
            topic="risk",
            content="Sunday lesson.",
            status="queued",
            failure_category=None,
            now=sunday_morning.astimezone(timezone.utc),
        )
        self.morning_store.finish(
            "2026-11-01",
            status="sent",
            message_id=901,
            now=sunday_morning.astimezone(timezone.utc),
        )
        saturday_poll = datetime(2026, 10, 31, 21, 0, tzinfo=MORNING_ZONE)
        self.poll_store.create_education_poll_run(
            run_key="weekly:2026-10-31",
            source="weekly",
            scheduled_at=saturday_poll.astimezone(timezone.utc).isoformat(),
            scenario_index=0,
            status="published",
            group_message_id=902,
            at=saturday_poll.astimezone(timezone.utc).isoformat(),
        )

    def test_sunday_cleanup_deletes_only_tracked_lesson_and_group_poll_once(self) -> None:
        self._seed_weekend_messages()
        due = datetime(2026, 11, 1, 23, 0, tzinfo=MORNING_ZONE)

        self.cleanup.dispatch_due(due)
        self.cleanup.dispatch_due(due.replace(minute=1))

        self.assertEqual(
            self.api.deleted,
            [
                (EXPECTED_EDUCATION_GROUP_ID, 900),
                (EXPECTED_EDUCATION_GROUP_ID, 902),
                (EXPECTED_EDUCATION_GROUP_ID, 901),
            ],
        )

    def test_cleanup_does_not_run_before_sunday_11pm(self) -> None:
        self._seed_weekend_messages()

        self.cleanup.dispatch_due(datetime(2026, 11, 1, 22, 59, tzinfo=MORNING_ZONE))

        self.assertEqual(self.api.deleted, [])

    def test_monday_recovery_respects_each_messages_48_hour_limit(self) -> None:
        self._seed_weekend_messages()
        monday = datetime(2026, 11, 2, 23, 0, tzinfo=MORNING_ZONE)

        self.cleanup.dispatch_due(monday)

        self.assertEqual(self.api.deleted, [(EXPECTED_EDUCATION_GROUP_ID, 901)])
        items = EducationWeekendCleanupStore(self.database).items("2026-11-01")
        poll = next(item for item in items if item["target_kind"] == "saturday_poll")
        saturday_lesson = next(
            item for item in items if item["target_kind"] == "saturday_lesson"
        )
        self.assertEqual(poll["status"], "skipped")
        self.assertEqual(poll["failure_category"], "telegram_delete_window_expired")
        self.assertEqual(saturday_lesson["status"], "skipped")
        self.assertEqual(
            saturday_lesson["failure_category"],
            "telegram_delete_window_expired",
        )

    def test_permission_failure_notifies_once_then_retries(self) -> None:
        self._seed_weekend_messages()
        self.api.fail_next_delete = True
        due = datetime(2026, 11, 1, 23, 0, tzinfo=MORNING_ZONE)

        self.cleanup.dispatch_due(due)
        self.cleanup.dispatch_due(due.replace(minute=3))

        self.assertEqual(len(self.api.admin_messages), 1)
        self.assertEqual(
            sorted(self.api.deleted),
            [
                (EXPECTED_EDUCATION_GROUP_ID, 900),
                (EXPECTED_EDUCATION_GROUP_ID, 901),
                (EXPECTED_EDUCATION_GROUP_ID, 902),
            ],
        )

    def test_legacy_cleanup_rows_survive_schema_upgrade(self) -> None:
        legacy_database = Path(self.temp_dir.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy_database)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE education_weekend_cleanup_items (
                    cleanup_date TEXT NOT NULL,
                    target_kind TEXT NOT NULL CHECK (
                        target_kind IN ('sunday_lesson', 'saturday_poll')
                    ),
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    sent_at_utc TEXT,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'deleted', 'skipped')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at_utc TEXT,
                    failure_category TEXT,
                    failure_notified INTEGER NOT NULL DEFAULT 0,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (cleanup_date, target_kind)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO education_weekend_cleanup_items (
                    cleanup_date, target_kind, chat_id, message_id, sent_at_utc,
                    status, updated_at_utc
                ) VALUES ('2026-11-01', 'sunday_lesson', -100123, 901,
                    '2026-11-01T07:00:00+00:00', 'pending',
                    '2026-11-01T22:00:00+00:00')
                """
            )

        store = EducationWeekendCleanupStore(legacy_database)
        rows = store.items("2026-11-01")
        store.ensure_item(
            cleanup_date="2026-11-01",
            target_kind="saturday_lesson",
            chat_id=-100123,
            message_id=900,
            sent_at_utc="2026-10-31T07:00:00+00:00",
            now=datetime(2026, 11, 1, 22, tzinfo=timezone.utc),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["message_id"], 901)
        self.assertEqual(
            [item["target_kind"] for item in store.items("2026-11-01")],
            ["saturday_lesson", "sunday_lesson"],
        )


if __name__ == "__main__":
    unittest.main()
