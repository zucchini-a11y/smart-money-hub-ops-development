import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from smart_money_hub_bot.bot import SmartMoneyHubBot
from smart_money_hub_bot.grading import RuleBasedWrittenAnswerEvaluator
from smart_money_hub_bot.questions import QUESTIONS, validate_questions
from smart_money_hub_bot.scoring import grade_answers
from smart_money_hub_bot.storage import Repository


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []
        self.webhook_info: dict[str, Any] = {}

    def get_webhook_info(self) -> dict[str, Any]:
        return self.webhook_info

    def get_me(self) -> dict[str, Any]:
        return {"username": "SmartMoneyHubTestBot"}

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        self.messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        self.answered_callbacks.append(
            {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            }
        )


class AssessmentTests(unittest.TestCase):
    def test_has_ten_questions_with_four_options_each(self) -> None:
        validate_questions()
        self.assertEqual(len(QUESTIONS), 10)
        self.assertTrue(all(len(question.options) == 4 for question in QUESTIONS))

    def test_scoring_returns_percentage_topic_breakdown_and_review(self) -> None:
        answers = [question.correct_index for question in QUESTIONS]
        answers[1] = (answers[1] + 1) % 4
        answers[8] = (answers[8] + 1) % 4

        result = grade_answers(answers)

        self.assertEqual((result.score, result.total, result.percentage), (8, 10, 80))
        self.assertEqual(
            [wrong.question_number for wrong in result.incorrect_answers], [2, 9]
        )
        self.assertEqual(len(result.answers), 10)
        self.assertTrue(
            all(wrong.selected_answer and wrong.explanation for wrong in result.incorrect_answers)
        )
        self.assertEqual(len(result.strong_areas), 8)
        self.assertEqual(len(result.weak_areas), 2)

    def test_result_explains_every_wrong_answer_within_telegram_limit(self) -> None:
        answers = [(question.correct_index + 1) % 4 for question in QUESTIONS]
        result = grade_answers(answers)
        message = SmartMoneyHubBot._format_result(result, saved=True)

        self.assertEqual(result.score, 0)
        self.assertEqual(len(result.incorrect_answers), 10)
        self.assertEqual(message.count("Why:"), 10)
        self.assertTrue(
            all(f"Question {number} —" in message for number in range(1, 11))
        )
        self.assertIn("Percentage: 0%", message)
        self.assertLessEqual(len(message), 4096)

    def test_scoring_rejects_incomplete_or_invalid_answers(self) -> None:
        with self.assertRaises(ValueError):
            grade_answers([0])
        answers = [question.correct_index for question in QUESTIONS]
        answers[0] = 4
        with self.assertRaises(ValueError):
            grade_answers(answers)

    def test_written_answer_evaluator_is_deterministic_and_provider_neutral(self) -> None:
        result = RuleBasedWrittenAnswerEvaluator().evaluate(
            "Wait for a liquidity sweep and confirmation before entry.",
            ["liquidity sweep", "confirmation"],
        )
        self.assertEqual((result.score, result.maximum_score), (2, 2))
        self.assertFalse(result.missing_concepts)


class BotFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "smart_money.sqlite3"
        self.api = FakeTelegramAPI()
        self.bot = SmartMoneyHubBot(self.api, str(self.database_path))
        self.user_id = 123456
        self.chat_id = 654321
        self.username = "smc_member"
        self.first_name = "Amara"
        self.callback_counter = 0

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_start_assessment_saves_answers_and_explains_missed_questions(self) -> None:
        self._message("/start")
        welcome = self.api.messages[-1]
        self.assertIn("Welcome Amara to Smart Money Hub", welcome["text"])
        menu = welcome["reply_markup"]["inline_keyboard"]
        self.assertEqual(menu[0][0]["text"], "Start SMC Assessment")
        self.assertTrue(any(row[0]["text"] == "Sunday Preparation" for row in menu))

        self._click("menu:assessment")
        self.assertIn("Question 1/10", self.api.messages[-1]["text"])
        self.assertEqual(len(self.api.messages[-1]["reply_markup"]["inline_keyboard"]), 5)

        for question_index, question in enumerate(QUESTIONS):
            selected = question.correct_index
            if question_index in {2, 7, 9}:
                selected = (selected + 1) % 4
            self._click(f"answer:{question_index}:{selected}")

        final = self.api.messages[-1]
        self.assertIn("Score: 7/10 (70%)", final["text"])
        self.assertIn("Percentage: 70%", final["text"])
        self.assertIn("Question 3 — Change of Character (CHoCH)", final["text"])
        self.assertIn("Strong areas:", final["text"])
        self.assertIn("Needs work:", final["text"])
        self.assertIn("Correct answer:", final["text"])
        self.assertIn("Why:", final["text"])
        self.assertEqual(self.bot.sessions, {})

        connection = sqlite3.connect(self.database_path)
        try:
            assessment = connection.execute(
                """
                SELECT telegram_id, score, total, percentage, weak_areas
                FROM assessments
                """
            ).fetchone()
            answers_saved = connection.execute(
                "SELECT COUNT(*) FROM assessment_answers"
            ).fetchone()[0]
            member = connection.execute(
                "SELECT username, first_name, chat_id, is_private FROM users"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(assessment[:4], (self.user_id, 7, 10, 70))
        self.assertIn("Change of Character (CHoCH)", assessment[4])
        self.assertEqual(answers_saved, 10)
        self.assertEqual(member, (self.username, self.first_name, self.chat_id, 1))

    def test_retake_starts_a_fresh_ten_question_session(self) -> None:
        self._click("menu:assessment")
        for question_index, question in enumerate(QUESTIONS):
            self._click(f"answer:{question_index}:{question.correct_index}")
        self._click("take_again")
        self.assertIn("Question 1/10", self.api.messages[-1]["text"])
        self.assertEqual(self.bot.sessions[self.user_id].answers, [])

    def test_invalid_answer_does_not_advance_the_test(self) -> None:
        self._click("menu:assessment")
        self._click("answer:0:4")
        self.assertEqual(self.bot.sessions[self.user_id].answers, [])
        self.assertEqual(
            self.api.answered_callbacks[-1]["text"], "That answer is not valid."
        )

    def test_back_and_main_menu_clear_or_rewind_active_assessments(self) -> None:
        self._click("menu:assessment")
        self._click("answer:0:0")
        self.assertEqual(self.bot.sessions[self.user_id].step, 1)
        self._click("nav:back")
        self.assertEqual(self.bot.sessions[self.user_id].step, 0)
        self.assertIn("Question 1/10", self.api.messages[-1]["text"])
        self._click("nav:home")
        self.assertNotIn(self.user_id, self.bot.sessions)
        self.assertEqual(
            self.api.messages[-1]["reply_markup"]["inline_keyboard"][0][0]["text"],
            "Start SMC Assessment",
        )

    def test_journal_saves_structured_review_and_can_retrieve_trade(self) -> None:
        self._click("menu:journal")
        self._click("journal:new")
        self._text("Gold")
        self._click("flow:choice:1:0")  # Buy
        self._text("15M FVG")
        self._text("15m")
        self._text("None")
        self._click("flow:choice:5:1")  # No liquidity sweep
        self._click("flow:choice:6:1")  # No retest
        self._text("2320")
        self._text("2300")
        self._click("flow:choice:9:1")  # No partial
        self._click("flow:choice:10:0")  # Moved to BE
        self._click("flow:choice:11:1")  # Loss
        self._click("flow:choice:12:1")  # Did not follow plan
        self._text("Entered before confirmation")
        self._text("Wait for displacement and a retest")

        review = self.api.messages[-1]["text"]
        self.assertIn("TRADE REVIEW", review)
        self.assertIn("Potential issue:", review)
        self.assertIn("No confirmation, no entry.", review)
        self.assertIn("Trade Review Reminder", review)
        self.assertNotIn(self.user_id, self.bot.sessions)

        progress = self.bot.store.progress_for(self.user_id)
        self.assertEqual(progress["trades_journaled"], 1)
        self.assertEqual(progress["losing_trades"], 1)
        self.assertEqual(progress["most_common_mistake"], "Entered before confirmation")

        self._click("journal:history")
        self.assertIn("Gold", self.api.messages[-1]["reply_markup"]["inline_keyboard"][0][0]["text"])
        self._click("trade:1")
        self.assertIn("Wait for displacement and a retest", self.api.messages[-1]["text"])

    def test_stale_flow_buttons_cannot_answer_a_different_question(self) -> None:
        self._click("menu:journal")
        self._click("journal:new")
        self._text("Gold")
        self.assertEqual(self.bot.sessions[self.user_id].step, 1)
        self._click("flow:choice:0:0")
        self.assertEqual(self.bot.sessions[self.user_id].step, 1)
        self.assertIn("buy or a sell", self.api.messages[-1]["text"].casefold())

    def test_weekly_checkin_and_sunday_preparation_are_saved(self) -> None:
        self._click("menu:weekly")
        self._text("4")
        self._text("2")
        self._text("1")
        self._click("flow:choice:3:0")  # Followed plan
        self._click("flow:choice:4:0")  # Entered without confirmation
        self._click("flow:choice:5:1")  # Did not chase a missed trade
        self._click("flow:choice:6:1")  # Did not move SL unnecessarily
        self._click("flow:choice:7:0")  # Secured partials / BE
        self._text("Entered before confirmation")
        self._text("Wait for the retest")
        summary = self.api.messages[-1]["text"]
        self.assertIn("Weekly check-in saved.", summary)
        self.assertIn("entering without confirmation", summary)
        self.assertIn("Wait for the retest", summary)

        self._click("menu:sunday")
        self._text("Follow my plan")
        self._text("Liquidity")
        self._text("Chasing missed trades")
        self._text("Wait for another setup")
        sunday = self.api.messages[-1]["text"]
        self.assertIn("Do not chase.", sunday)

        progress = self.bot.store.progress_for(self.user_id)
        self.assertEqual(progress["weekly_checkins_count"], 1)
        self.assertEqual(
            self.bot.store.recent_checkins(self.user_id, 1)[0]["next_focus"],
            "Wait for the retest",
        )
        self._click("menu:progress")
        self.assertIn("Current focus: Liquidity", self.api.messages[-1]["text"])
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM sunday_preparations").fetchone()[0],
                1,
            )
        finally:
            connection.close()

    def test_education_progress_and_admin_sections_render(self) -> None:
        self._click("menu:learn")
        self.assertTrue(self.api.messages[-1]["reply_markup"]["inline_keyboard"])
        self._click("edu:retest")
        self.assertIn("No retest, no entry.", self.api.messages[-1]["text"])

        self._click("menu:progress")
        self.assertIn("SMART MONEY HUB PROGRESS", self.api.messages[-1]["text"])
        self.assertIn("Weekly check-ins: 0", self.api.messages[-1]["text"])

        self._message("/myid")
        self.assertIn(str(self.user_id), self.api.messages[-1]["text"])
        self._message("/admin")
        self.assertIn("Admin access is not configured", self.api.messages[-1]["text"])

        self.bot.admin_id = self.user_id
        self._message("/admin")
        self.assertIn("SMART MONEY HUB ADMIN", self.api.messages[-1]["text"])
        self.assertIn("Members: 1", self.api.messages[-1]["text"])

        self._callback("admin:open", sender_id=self.user_id + 1, chat_id=self.chat_id + 1)
        self.assertIn("only available", self.api.messages[-1]["text"])

    def test_scheduled_reminders_are_private_opt_in_and_idempotent(self) -> None:
        self.bot.store.register_user(
            telegram_id=101,
            username="private_member",
            first_name="Ada",
            chat_id=101,
            is_private=True,
            at="2026-10-03T10:00:00+00:00",
        )
        self.assertTrue(self.bot.store.set_reminders_enabled(101, True))
        self.bot.store.register_user(
            telegram_id=202,
            username="group_member",
            first_name="Bola",
            chat_id=-202,
            is_private=False,
            at="2026-10-03T10:00:00+00:00",
        )
        self.assertFalse(self.bot.store.set_reminders_enabled(202, True))

        sunday = datetime(
            2026, 10, 4, 9, 5, tzinfo=ZoneInfo("Africa/Lagos")
        )
        self.bot._dispatch_due_reminders(sunday)
        self.bot._dispatch_due_reminders(sunday)
        scheduled = [
            message for message in self.api.messages
            if message["text"].startswith("🧠 Sunday Check-In")
        ]
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]["chat_id"], 101)

        self._message("/stop", user_id=101, chat_id=101)
        self.bot._dispatch_due_reminders(
            datetime(2026, 10, 11, 9, 5, tzinfo=ZoneInfo("Africa/Lagos"))
        )
        scheduled = [
            message for message in self.api.messages
            if message["text"].startswith("🧠 Sunday Check-In")
        ]
        self.assertEqual(len(scheduled), 1)

    def test_run_does_not_change_an_existing_webhook(self) -> None:
        self.api.webhook_info = {"url": "https://example.invalid/webhook"}
        with self.assertRaisesRegex(SystemExit, "will not change it automatically"):
            self.bot.run()

    def _message(
        self, text: str, *, user_id: int | None = None, chat_id: int | None = None
    ) -> None:
        member = user_id if user_id is not None else self.user_id
        private_chat = chat_id if chat_id is not None else (
            self.chat_id if member == self.user_id else member
        )
        self.bot.handle_update(
            {
                "message": {
                    "text": text,
                    "chat": {"id": private_chat, "type": "private"},
                    "from": {
                        "id": member,
                        "username": self.username if member == self.user_id else None,
                        "first_name": self.first_name,
                    },
                }
            }
        )

    def _text(self, text: str) -> None:
        self._message(text)

    def _click(self, data: str) -> None:
        self.callback_counter += 1
        self._callback(data, sender_id=self.user_id, chat_id=self.chat_id)

    def _callback(self, data: str, *, sender_id: int, chat_id: int) -> None:
        self.callback_counter += 1
        self.bot.handle_update(
            {
                "callback_query": {
                    "id": f"callback-{self.callback_counter}",
                    "from": {
                        "id": sender_id,
                        "username": self.username if sender_id == self.user_id else None,
                        "first_name": self.first_name,
                    },
                    "message": {
                        "message_id": self.callback_counter,
                        "chat": {"id": chat_id, "type": "private"},
                    },
                    "data": data,
                }
            }
        )


class StorageMigrationTests(unittest.TestCase):
    def test_legacy_assessment_rows_survive_repeated_database_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE assessment_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    username TEXT,
                    score INTEGER NOT NULL,
                    percentage INTEGER NOT NULL,
                    completed_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO assessment_results
                    (telegram_id, username, score, percentage, completed_at)
                VALUES (456, 'legacy_user', 8, 80, '2025-09-01T12:00:00+00:00')
                """
            )
            connection.commit()
            connection.close()

            Repository(path)
            repository = Repository(path)
            progress = repository.progress_for(456)
            self.assertEqual(progress["tests_completed"], 1)
            self.assertEqual(progress["latest_assessment_score"], 8)

            connection = sqlite3.connect(path)
            try:
                count = connection.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
                legacy_count = connection.execute(
                    "SELECT COUNT(*) FROM assessment_results"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 1)
            self.assertEqual(legacy_count, 1)


if __name__ == "__main__":
    unittest.main()