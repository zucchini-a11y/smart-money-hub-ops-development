"""Telegram update handling and the Smart Money Hub assessment flow."""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .questions import QUESTIONS, Question
from .scoring import AssessmentResult, grade_answers
from .storage import ScoreStore
from .telegram_api import TelegramAPI, TelegramAPIError


logger = logging.getLogger(__name__)
START_TEST_BUTTON = "Start SMC Test"
RETAKE_BUTTON = "Take Test Again"


@dataclass
class AssessmentSession:
    telegram_id: int
    username: str | None
    chat_id: int
    answers: list[int] = field(default_factory=list)


class SmartMoneyHubBot:
    def __init__(self, api: TelegramAPI, database_path: str) -> None:
        self.api = api
        self.store = ScoreStore(database_path)
        # Each Telegram member has one active assessment at a time.
        self.sessions: dict[int, AssessmentSession] = {}

    def run(self) -> None:
        webhook_info = self.api.get_webhook_info()
        if webhook_info.get("url"):
            raise SystemExit(
                "This Telegram bot already has a webhook configured. Stop the "
                "webhook-based service and remove its webhook before starting "
                "this polling bot; this program will not change it automatically."
            )

        bot_info = self.api.get_me()
        logger.info(
            "Polling started for Smart Money Hub bot @%s.",
            bot_info.get("username", "unknown"),
        )
        offset: int | None = None
        retry_delay = 1

        while True:
            try:
                updates = self.api.get_updates(offset=offset)
                retry_delay = 1
            except TelegramAPIError as error:
                logger.error(
                    "Telegram polling failed: %s. Retrying in %s seconds.",
                    error,
                    retry_delay,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
                continue

            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                try:
                    self.handle_update(update)
                except TelegramAPIError as error:
                    logger.error("Could not reply to a Telegram update: %s", error)
                except Exception:
                    logger.exception("Could not process a Telegram update.")

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(message)
            return

        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._handle_callback(callback)

    def _handle_message(self, message: dict[str, Any]) -> None:
        text = message.get("text")
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        if not isinstance(text, str) or not isinstance(chat_id, int):
            return

        command = text.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0]
        if command == "/start":
            self._send_welcome(chat_id)
        elif command == "/help":
            self.api.send_message(
                chat_id,
                "Use /start to open Smart Money Hub's SMC assessment.",
            )

    def _send_welcome(self, chat_id: int) -> None:
        self.api.send_message(
            chat_id,
            (
                "Welcome to Smart Money Hub.\n\n"
                "Test your Smart Money Concepts knowledge with a 10-question "
                "assessment. You'll get your score and explanations for any "
                "questions you miss.\n\n"
                "Ready to begin?"
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": START_TEST_BUTTON,
                            "callback_data": "start_test",
                        }
                    ]
                ]
            },
        )

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = callback.get("id")
        sender = callback.get("from") or {}
        sender_id = sender.get("id")
        message = callback.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        data = callback.get("data")

        if (
            not isinstance(callback_id, str)
            or not isinstance(sender_id, int)
            or not isinstance(chat_id, int)
            or not isinstance(data, str)
        ):
            return

        if data in {"start_test", "take_again"}:
            self.api.answer_callback_query(callback_id)
            self._begin_assessment(
                telegram_id=sender_id,
                username=sender.get("username"),
                chat_id=chat_id,
            )
            return

        if data.startswith("answer:"):
            self._record_answer(
                callback_id=callback_id,
                telegram_id=sender_id,
                chat_id=chat_id,
                callback_data=data,
            )
            return

        self.api.answer_callback_query(callback_id, "That button is not recognized.")

    def _begin_assessment(
        self, *, telegram_id: int, username: str | None, chat_id: int
    ) -> None:
        self.sessions[telegram_id] = AssessmentSession(
            telegram_id=telegram_id,
            username=username,
            chat_id=chat_id,
        )
        self._send_question(chat_id, 0)

    def _send_question(self, chat_id: int, question_index: int) -> None:
        question = QUESTIONS[question_index]
        keyboard = [
            [
                {
                    "text": answer,
                    "callback_data": f"answer:{question_index}:{answer_index}",
                }
            ]
            for answer_index, answer in enumerate(question.options)
        ]
        self.api.send_message(
            chat_id,
            self._format_question(question, question_index),
            reply_markup={"inline_keyboard": keyboard},
        )

    @staticmethod
    def _format_question(question: Question, question_index: int) -> str:
        return (
            f"Question {question_index + 1}/{len(QUESTIONS)} — {question.topic}\n\n"
            f"{question.prompt}"
        )

    def _record_answer(
        self,
        *,
        callback_id: str,
        telegram_id: int,
        chat_id: int,
        callback_data: str,
    ) -> None:
        session = self.sessions.get(telegram_id)
        if session is None or session.chat_id != chat_id:
            self.api.answer_callback_query(
                callback_id,
                "Start a new test with /start.",
                show_alert=False,
            )
            return

        match = re.fullmatch(r"answer:(\d+):(\d+)", callback_data)
        if match is None:
            self.api.answer_callback_query(callback_id, "That answer is not valid.")
            return

        question_index, answer_index = map(int, match.groups())
        expected_question_index = len(session.answers)
        if question_index != expected_question_index:
            self.api.answer_callback_query(
                callback_id,
                "That question was already answered or is no longer active.",
            )
            return

        if (
            question_index >= len(QUESTIONS)
            or answer_index < 0
            or answer_index >= len(QUESTIONS[question_index].options)
        ):
            self.api.answer_callback_query(callback_id, "That answer is not valid.")
            return

        self.api.answer_callback_query(callback_id)
        session.answers.append(answer_index)

        next_question_index = len(session.answers)
        if next_question_index < len(QUESTIONS):
            self._send_question(chat_id, next_question_index)
            return

        self._finish_assessment(session)

    def _finish_assessment(self, session: AssessmentSession) -> None:
        result = grade_answers(session.answers)
        saved = True
        try:
            self.store.save_result(
                telegram_id=session.telegram_id,
                username=session.username,
                score=result.score,
                percentage=result.percentage,
            )
        except Exception:
            saved = False
            logger.exception("Could not save a completed assessment to SQLite.")

        self.sessions.pop(session.telegram_id, None)
        message = self._format_result(result, saved=saved)
        self.api.send_message(
            session.chat_id,
            message,
            reply_markup={
                "inline_keyboard": [
                    [{"text": RETAKE_BUTTON, "callback_data": "take_again"}]
                ]
            },
        )

    @staticmethod
    def _format_result(result: AssessmentResult, *, saved: bool) -> str:
        lines = [
            "SMC assessment complete",
            f"Score: {result.score}/{result.total}",
            f"Percentage: {result.percentage}%",
        ]

        if result.incorrect_answers:
            lines.append("\nReview these answers:")
            for wrong in result.incorrect_answers:
                lines.extend(
                    [
                        f"\nQuestion {wrong.question_number} — {wrong.topic}",
                        f"Your answer: {wrong.selected_answer}",
                        f"Correct answer: {wrong.correct_answer}",
                        f"Why: {wrong.explanation}",
                    ]
                )
        else:
            lines.append(
                "\nYou got every question right. Keep applying confirmation, "
                "retests, and planned risk consistently."
            )

        if not saved:
            lines.append(
                "\nYour score could not be saved locally. Please try again later "
                "or tell a Smart Money Hub admin."
            )

        lines.append("\nYou can take the test again whenever you're ready.")
        return "\n".join(lines)