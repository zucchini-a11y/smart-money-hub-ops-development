import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from smart_money_hub_bot.education_polls import (
    EducationPollError,
    EXPECTED_EDUCATION_GROUP_ID,
    EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
    EducationPollPublisher,
    format_channel_poll_preview,
    group_poll_message_url,
    is_on_demand_poll_request,
    parse_education_poll_message_link,
    scheduled_occurrence,
    verify_poll_destinations,
)
from smart_money_hub_bot.group_features import ScenarioPoll
from smart_money_hub_bot.bot import Conversation, SmartMoneyHubBot
from smart_money_hub_bot.storage import Repository
from smart_money_hub_bot.telegram_api import TelegramAPIError


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.polls: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.channel_messages: list[dict[str, Any]] = []
        self.group_status = "administrator"
        self.channel_status = "administrator"
        self.channel_can_post = True
        self.raise_get_chat = False
        self.raise_channel_send = False

    def get_me(self) -> dict[str, Any]:
        return {"id": 123, "username": "SmartMoneyHubSignalsBot"}

    def get_chat(self, chat_id: int) -> dict[str, Any]:
        if self.raise_get_chat:
            raise TelegramAPIError("unavailable", http_status=503)
        if chat_id == EXPECTED_EDUCATION_GROUP_ID:
            return {
                "id": chat_id,
                "type": "supergroup",
                "title": "Smart Money Hub Education Suite",
            }
        return {
            "id": chat_id,
            "type": "channel",
            "title": "Smart Money Hub Market Analysis",
        }

    def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        if chat_id == EXPECTED_EDUCATION_GROUP_ID:
            return {"status": self.group_status}
        return {
            "status": self.channel_status,
            "can_post_messages": self.channel_can_post,
        }

    def send_poll(
        self,
        chat_id: int,
        question: str,
        options: list[str],
        correct_option_id: int,
        explanation: str,
    ) -> dict[str, Any]:
        self.polls.append(
            {
                "chat_id": chat_id,
                "question": question,
                "options": options,
                "correct_option_id": correct_option_id,
                "explanation": explanation,
            }
        )
        message_id = 500 + len(self.polls)
        return {
            "message_id": message_id,
            "poll": {"id": f"poll-{message_id}"},
        }

    def send_message_with_result(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        *,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        if self.raise_channel_send:
            raise TelegramAPIError("send failed", http_status=400)
        message = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.channel_messages.append(message)
        return {"message_id": 900 + len(self.channel_messages)}

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                **kwargs,
            }
        )


class _TelegramHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "b":
            self.errors.append(tag)
        else:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(f"unbalanced {tag}")


class EducationPollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp_dir.name) / "education.sqlite3")
        self.api = FakeTelegramAPI()
        self.publisher = EducationPollPublisher(
            self.api,
            self.repo,
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
            started_at=datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_weekly_schedule_is_saturday_9pm_wat(self) -> None:
        schedule_date, scheduled_utc = scheduled_occurrence(
            datetime(2026, 10, 24, 20, 3, tzinfo=timezone.utc)
        )
        self.assertEqual(schedule_date, "2026-10-24")
        self.assertEqual(scheduled_utc.isoformat(), "2026-10-24T20:00:00+00:00")

    def test_existing_poll_runs_database_gets_thread_column(self) -> None:
        database_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                CREATE TABLE education_poll_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    scenario_index INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    group_message_id INTEGER,
                    channel_message_id INTEGER,
                    failure_category TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()
        Repository(database_path)
        connection = sqlite3.connect(database_path)
        try:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(education_poll_runs)")
            }
        finally:
            connection.close()
        self.assertIn("group_thread_id", columns)

    def test_late_weekly_poll_is_skipped_not_published(self) -> None:
        self.publisher.dispatch_due(
            datetime(2026, 10, 24, 20, 6, tzinfo=timezone.utc)
        )
        run = self.repo.education_poll_run("weekly:2026-10-24")
        self.assertEqual(run["status"], "skipped")
        self.assertEqual(run["failure_category"], "missed_schedule_window")
        self.assertEqual(self.api.polls, [])
        self.assertEqual(self.api.channel_messages, [])

    def test_scheduler_started_after_due_skips_current_occurrence(self) -> None:
        late_publisher = EducationPollPublisher(
            self.api,
            self.repo,
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
            started_at=datetime(2026, 10, 24, 20, 1, tzinfo=timezone.utc),
        )
        late_publisher.dispatch_due(
            datetime(2026, 10, 24, 20, 2, tzinfo=timezone.utc)
        )
        run = self.repo.education_poll_run("weekly:2026-10-24")
        self.assertEqual(run["status"], "skipped")
        self.assertEqual(
            run["failure_category"], "poll_scheduler_started_after_due"
        )
        self.assertEqual(self.api.polls, [])

    def test_scheduler_does_not_publish_before_saturday_time(self) -> None:
        self.publisher.dispatch_due(
            datetime(2026, 10, 24, 19, 59, tzinfo=timezone.utc)
        )
        self.assertIsNone(self.repo.education_poll_run("weekly:2026-10-24"))
        self.assertEqual(self.api.polls, [])

    def test_weekly_poll_and_channel_preview_publish_once(self) -> None:
        due = datetime(2026, 10, 24, 20, 1, tzinfo=timezone.utc)
        self.publisher.dispatch_due(due)
        self.publisher.dispatch_due(due)
        run = self.repo.education_poll_run("weekly:2026-10-24")
        self.assertEqual(run["status"], "published")
        self.assertEqual(len(self.api.polls), 1)
        self.assertEqual(len(self.api.channel_messages), 1)
        button = self.api.channel_messages[0]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "Vote in Education Group")
        self.assertEqual(button["url"], "https://t.me/c/3916437804/501")
        self.assertIn("This is a preview", self.api.channel_messages[0]["text"])
        self.assertEqual(self.api.channel_messages[0]["parse_mode"], "HTML")
        restarted_publisher = EducationPollPublisher(
            self.api,
            self.repo,
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
            started_at=datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc),
        )
        restarted_publisher.dispatch_due(due)
        self.assertEqual(len(self.api.polls), 1)
        self.assertEqual(len(self.api.channel_messages), 1)

    def test_manual_retry_does_not_duplicate_a_completed_run(self) -> None:
        now = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(self.publisher.post_now("update-55", now), "published")
        self.assertEqual(self.publisher.post_now("update-55", now), "published")
        self.assertEqual(len(self.api.polls), 1)
        self.assertEqual(len(self.api.channel_messages), 1)

    def test_existing_poll_link_mirrors_only_to_channel_and_is_idempotent(self) -> None:
        link = "https://t.me/c/3916437804/1/113"
        self.assertEqual(
            parse_education_poll_message_link(link),
            (EXPECTED_EDUCATION_GROUP_ID, 1, 113),
        )
        now = datetime(2026, 10, 24, 20, 20, tzinfo=timezone.utc)
        self.assertEqual(
            self.publisher.publish_existing_poll_preview(
                link, scenario_index=0, now=now
            ),
            "published",
        )
        self.assertEqual(
            self.publisher.publish_existing_poll_preview(
                link, scenario_index=0, now=now
            ),
            "published",
        )
        self.assertEqual(self.api.polls, [])
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(
            self.api.channel_messages[0]["reply_markup"]["inline_keyboard"][0][0][
                "url"
            ],
            link,
        )

    def test_existing_poll_link_for_wrong_group_is_rejected(self) -> None:
        with self.assertRaises(EducationPollError) as raised:
            parse_education_poll_message_link("https://t.me/c/3916437805/1/113")
        self.assertEqual(
            raised.exception.category, "education_group_destination_mismatch"
        )

    def test_channel_failure_does_not_resend_group_poll(self) -> None:
        self.api.raise_channel_send = True
        self.assertEqual(
            self.publisher.post_now(
                "update-56",
                datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc),
            ),
            "channel_failed",
        )
        self.publisher.dispatch_pending()
        self.assertEqual(len(self.api.polls), 1)
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(
            self.repo.education_poll_run("manual:update-56")["status"],
            "channel_failed",
        )

    def test_interrupted_group_send_is_not_retried_after_restart(self) -> None:
        self.repo.create_education_poll_run(
            run_key="weekly:2026-10-24",
            source="weekly",
            scheduled_at="2026-10-24T20:00:00+00:00",
            scenario_index=0,
            status="sending_group",
        )
        self.publisher.dispatch_pending(
            datetime(2026, 10, 24, 20, 2, tzinfo=timezone.utc)
        )
        run = self.repo.education_poll_run("weekly:2026-10-24")
        self.assertEqual(run["status"], "delivery_unknown")
        self.assertEqual(len(self.api.polls), 0)

    def test_wrong_destination_and_missing_permissions_hold_poll(self) -> None:
        wrong_group = EducationPollPublisher(
            self.api,
            self.repo,
            admin_id=77,
            education_group_id=-1009999999999,
            channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
        )
        self.assertEqual(
            wrong_group.post_now("wrong-group", datetime.now(timezone.utc)),
            "failed",
        )
        wrong_channel = EducationPollPublisher(
            self.api,
            self.repo,
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            channel_id=-1009999999999,
        )
        self.assertEqual(
            wrong_channel.post_now("wrong-channel", datetime.now(timezone.utc)),
            "failed",
        )
        self.api.channel_can_post = False
        self.assertEqual(
            self.publisher.post_now("no-channel-permission", datetime.now(timezone.utc)),
            "failed",
        )
        self.assertEqual(self.api.polls, [])
        self.assertEqual(self.api.channel_messages, [])

    def test_missing_education_group_admin_permission_holds_poll(self) -> None:
        self.api.group_status = "member"
        self.assertEqual(
            self.publisher.post_now(
                "no-group-permission",
                datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc),
            ),
            "failed",
        )
        self.assertEqual(self.api.polls, [])
        self.assertEqual(self.api.channel_messages, [])

    def test_destination_verification_handles_api_failure(self) -> None:
        self.api.raise_get_chat = True
        with self.assertRaises(EducationPollError) as raised:
            verify_poll_destinations(
                self.api,
                education_group_id=EXPECTED_EDUCATION_GROUP_ID,
                channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
            )
        self.assertEqual(
            raised.exception.category, "telegram_destination_verification_unavailable"
        )

    def test_private_or_public_group_poll_link(self) -> None:
        self.assertEqual(
            group_poll_message_url(
                group_id=EXPECTED_EDUCATION_GROUP_ID,
                group_chat={"type": "supergroup"},
                message_id=501,
            ),
            "https://t.me/c/3916437804/501",
        )
        self.assertEqual(
            group_poll_message_url(
                group_id=EXPECTED_EDUCATION_GROUP_ID,
                group_chat={"username": "SMHEducation"},
                message_id=501,
            ),
            "https://t.me/SMHEducation/501",
        )
        self.assertEqual(
            group_poll_message_url(
                group_id=EXPECTED_EDUCATION_GROUP_ID,
                group_chat={"type": "supergroup"},
                message_id=113,
                thread_id=1,
            ),
            "https://t.me/c/3916437804/1/113",
        )

    def test_channel_preview_escapes_html_and_uses_balanced_telegram_tags(self) -> None:
        scenario = ScenarioPoll(
            question="What does <BOS> & CHOCH mean?",
            options=("Wait for <confirmation>", "Enter now", "Guess", "Ignore risk"),
            correct_option_id=0,
            explanation="Use the plan.",
        )
        rendered = format_channel_poll_preview(scenario)
        parser = _TelegramHtmlParser()
        parser.feed(rendered)
        parser.close()
        self.assertEqual(parser.errors, [])
        self.assertFalse(parser.stack)
        self.assertIn("🧠 <b>SMART MONEY HUB", rendered)
        self.assertIn("&lt;BOS&gt; &amp; CHOCH", rendered)
        self.assertIn("&lt;confirmation&gt;", rendered)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", rendered)
        self.assertIn("\n\n", rendered)

    def test_natural_language_trigger_is_specific(self) -> None:
        self.assertTrue(is_on_demand_poll_request("  Post a new SMC poll now! "))
        self.assertTrue(is_on_demand_poll_request("Could you create an education poll today?"))
        self.assertFalse(is_on_demand_poll_request("What is a poll?"))
        self.assertFalse(is_on_demand_poll_request("Post this poll later"))

    def test_admin_private_text_triggers_immediate_poll(self) -> None:
        bot = SmartMoneyHubBot(
            self.api,
            str(Path(self.temp_dir.name) / "bot.sqlite3"),
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            main_channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
        )
        bot.education_polls.post_now = Mock(return_value="published")
        bot.handle_update(
            {
                "update_id": 12345,
                "message": {
                    "from": {"id": 77, "is_bot": False, "first_name": "Admin"},
                    "chat": {"id": 77, "type": "private"},
                    "text": "Please post a new SMC poll now",
                },
            }
        )
        bot.education_polls.post_now.assert_called_once_with("update-12345")

    def test_active_admin_session_keeps_precedence_over_poll_request(self) -> None:
        bot = SmartMoneyHubBot(
            self.api,
            str(Path(self.temp_dir.name) / "bot-session.sqlite3"),
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            main_channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
        )
        bot.education_polls.post_now = Mock(return_value="published")
        bot.sessions[77] = Conversation(
            kind="assessment",
            chat_id=77,
            username=None,
            first_name=None,
        )
        bot.handle_update(
            {
                "update_id": 12346,
                "message": {
                    "from": {"id": 77, "is_bot": False, "first_name": "Admin"},
                    "chat": {"id": 77, "type": "private"},
                    "text": "Post a poll now",
                },
            }
        )
        bot.education_polls.post_now.assert_not_called()
        self.assertEqual(self.api.messages[-1]["chat_id"], 77)

    def test_non_admin_private_text_does_not_trigger_poll(self) -> None:
        bot = SmartMoneyHubBot(
            self.api,
            str(Path(self.temp_dir.name) / "bot-non-admin.sqlite3"),
            admin_id=77,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            main_channel_id=EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
        )
        bot.education_polls.post_now = Mock(return_value="published")
        bot.handle_update(
            {
                "update_id": 12347,
                "message": {
                    "from": {"id": 88, "is_bot": False, "first_name": "Member"},
                    "chat": {"id": 88, "type": "private"},
                    "text": "Post a poll now",
                },
            }
        )
        bot.education_polls.post_now.assert_not_called()


if __name__ == "__main__":
    unittest.main()
