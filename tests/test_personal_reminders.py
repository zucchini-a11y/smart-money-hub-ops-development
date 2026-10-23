import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from smart_money_hub_bot.personal_reminders import (
    parse_personal_reminder_request,
    parse_reminder_timing,
)


class PersonalReminderParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zone = ZoneInfo("Africa/Lagos")
        self.now = datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc)

    def test_parses_reminder_for_tomorrow_and_preserves_task(self) -> None:
        request = parse_personal_reminder_request(
            "Remind me to review my journal tomorrow at 9am",
            self.now,
            self.zone,
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.task, "review my journal")
        self.assertEqual(
            request.due_at,
            datetime(2026, 10, 24, 9, 0, tzinfo=self.zone),
        )
        self.assertIsNone(request.error)

    def test_parses_time_before_date_without_adding_it_to_the_task(self) -> None:
        request = parse_personal_reminder_request(
            "Remind me to check my journal at 9pm tomorrow",
            self.now,
            self.zone,
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.task, "check my journal")
        self.assertEqual(
            request.due_at,
            datetime(2026, 10, 24, 21, 0, tzinfo=self.zone),
        )

    def test_parses_relative_time(self) -> None:
        request = parse_personal_reminder_request(
            "Remind me to call the bank in 2 hours",
            self.now,
            self.zone,
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.task, "call the bank")
        self.assertEqual(
            request.due_at,
            datetime(2026, 10, 23, 11, 0, tzinfo=self.zone),
        )

    def test_missing_time_is_reported_without_guessing(self) -> None:
        request = parse_personal_reminder_request(
            "Remind me to review my journal tomorrow", self.now, self.zone
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.task, "review my journal")
        self.assertIsNone(request.due_at)
        self.assertEqual(request.needs, "time")

    def test_missing_date_is_reported_for_time_only(self) -> None:
        request = parse_personal_reminder_request(
            "Remind me to review my journal at 9pm", self.now, self.zone
        )

        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.task, "review my journal")
        self.assertIsNone(request.due_at)
        self.assertEqual(request.needs, "date")

    def test_ambiguous_time_and_non_reminder_text_are_not_guessed(self) -> None:
        request = parse_personal_reminder_request(
            "Remind me to review my journal tomorrow at 9", self.now, self.zone
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.error, "invalid_time")
        self.assertIsNone(
            parse_personal_reminder_request(
                "I should review my journal tomorrow at 9am",
                self.now,
                self.zone,
            )
        )

    def test_time_follow_up_accepts_date_and_time_together(self) -> None:
        timing = parse_reminder_timing(
            "tomorrow at 9am", self.now, self.zone
        )

        self.assertIsNotNone(timing)
        assert timing is not None
        self.assertEqual(
            timing.due_at,
            datetime(2026, 10, 24, 9, 0, tzinfo=self.zone),
        )


if __name__ == "__main__":
    unittest.main()
