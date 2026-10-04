import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from smart_money_hub_bot.bot import SmartMoneyHubBot
from smart_money_hub_bot.questions import QUESTIONS, validate_questions
from smart_money_hub_bot.scoring import grade_answers


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []
        self.webhook_info: dict[str, Any] = {}

    def get_webhook_info(self) -> dict[str, Any]:
        return self.webhook_info

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


class AssessmentContentTests(unittest.TestCase):
    def test_has_ten_questions_with_four_options_each(self) -> None:
        validate_questions()
        self.assertEqual(len(QUESTIONS), 10)
        self.assertTrue(all(len(question.options) == 4 for question in QUESTIONS))

    def test_scoring_returns_percentage_and_specific_review(self) -> None:
        answers = [question.correct_index for question in QUESTIONS]
        answers[1] = (answers[1] + 1) % 4
        answers[8] = (answers[8] + 1) % 4

        result = grade_answers(answers)

        self.assertEqual((result.score, result.total, result.percentage), (8, 10, 80))
        self.assertEqual(
            [wrong.question_number for wrong in result.incorrect_answers], [2, 9]
        )
        self.assertTrue(
            all(wrong.selected_answer and wrong.explanation for wrong in result.incorrect_answers)
        )

    def test_result_explains_every_wrong_answer_within_telegram_message_limit(self) -> None:
        answers = [(question.correct_index + 1) % 4 for question in QUESTIONS]
        result = grade_answers(answers)
        message = SmartMoneyHubBot._format_result(result, saved=True)

        self.assertEqual(result.score, 0)
        self.assertEqual(len(result.incorrect_answers), 10)
        self.assertEqual(message.count("Why:"), 10)
        self.assertTrue(all(f"Question {number} —" in message for number in range(1, 11)))
        self.assertLessEqual(len(message), 4096)

    def test_scoring_rejects_incomplete_or_invalid_answers(self) -> None:
        with self.assertRaises(ValueError):
            grade_answers([0])

        answers = [question.correct_index for question in QUESTIONS]
        answers[0] = 4
        with self.assertRaises(ValueError):
            grade_answers(answers)


class BotFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "scores.sqlite3"
        self.api = FakeTelegramAPI()
        self.bot = SmartMoneyHubBot(self.api, str(self.database_path))
        self.user_id = 123456
        self.chat_id = 654321
        self.username = "smc_member"
        self.callback_counter = 0

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_start_assessment_saves_score_and_shows_wrong_answer_explanations(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "text": "/start",
                    "chat": {"id": self.chat_id},
                    "from": {"id": self.user_id, "username": self.username},
                }
            }
        )

        welcome = self.api.messages[-1]
        self.assertIn("Welcome to Smart Money Hub", welcome["text"])
        self.assertEqual(
            welcome["reply_markup"]["inline_keyboard"][0][0]["text"],
            "Start SMC Test",
        )

        self._click("start_test")
        first_question = self.api.messages[-1]
        self.assertIn("Question 1/10", first_question["text"])
        self.assertEqual(len(first_question["reply_markup"]["inline_keyboard"]), 4)

        selected_answers: list[int] = []
        for question_index, question in enumerate(QUESTIONS):
            selected = question.correct_index
            if question_index in {2, 7, 9}:
                selected = (selected + 1) % 4
            selected_answers.append(selected)
            self._click(f"answer:{question_index}:{selected}")

        final = self.api.messages[-1]
        self.assertIn("Score: 7/10", final["text"])
        self.assertIn("Percentage: 70%", final["text"])
        self.assertIn("Question 3 — Change of Character (CHoCH)", final["text"])
        self.assertIn("Correct answer:", final["text"])
        self.assertIn("Why:", final["text"])
        self.assertEqual(
            final["reply_markup"]["inline_keyboard"][0][0]["text"],
            "Take Test Again",
        )
        self.assertEqual(self.bot.sessions, {})

        connection = sqlite3.connect(self.database_path)
        try:
            row = connection.execute(
                """
                SELECT telegram_id, username, score, percentage, completed_at
                FROM assessment_results
                """
            ).fetchone()
        finally:
            connection.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[:4], (self.user_id, self.username, 7, 70))
        self.assertTrue(row[4])

    def test_retake_starts_a_fresh_ten_question_session(self) -> None:
        self._click("start_test")
        for question_index, question in enumerate(QUESTIONS):
            self._click(f"answer:{question_index}:{question.correct_index}")

        self._click("take_again")
        self.assertIn("Question 1/10", self.api.messages[-1]["text"])
        self.assertEqual(self.bot.sessions[self.user_id].answers, [])
        self.assertEqual(len(self.api.answered_callbacks), 12)

    def test_invalid_answer_does_not_advance_the_test(self) -> None:
        self._click("start_test")
        self._click("answer:0:4")

        self.assertEqual(self.bot.sessions[self.user_id].answers, [])
        self.assertEqual(
            self.api.answered_callbacks[-1]["text"], "That answer is not valid."
        )

    def test_run_does_not_change_an_existing_webhook(self) -> None:
        self.api.webhook_info = {"url": "https://example.invalid/webhook"}

        with self.assertRaisesRegex(SystemExit, "will not change it automatically"):
            self.bot.run()

    def _click(self, data: str) -> None:
        self.callback_counter += 1
        self.bot.handle_update(
            {
                "callback_query": {
                    "id": f"callback-{self.callback_counter}",
                    "from": {
                        "id": self.user_id,
                        "username": self.username,
                    },
                    "message": {
                        "message_id": self.callback_counter,
                        "chat": {"id": self.chat_id},
                    },
                    "data": data,
                }
            }
        )


if __name__ == "__main__":
    unittest.main()