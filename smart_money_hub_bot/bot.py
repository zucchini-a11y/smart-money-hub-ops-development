"""Telegram menus and stateful SMC education, journaling, and assessment flows."""

import logging
import re
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, time as ClockTime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .admin_dashboard import AdminDashboard
from .education import EDUCATION
from .flows import SUNDAY_FIELDS, TRADE_FIELDS, WEEKLY_FIELDS
from .questions import QUESTIONS
from .scoring import AssessmentResult, grade_answers
from .storage import Repository
from .telegram_api import TelegramAPI, TelegramAPIError


logger = logging.getLogger(__name__)
MAIN_MENU: tuple[tuple[str, str], ...] = (
    ("Start SMC Assessment", "menu:assessment"),
    ("Trading Journal", "menu:journal"),
    ("Weekly Check-In", "menu:weekly"),
    ("Sunday Preparation", "menu:sunday"),
    ("My Progress", "menu:progress"),
    ("Learn SMC", "menu:learn"),
    ("Reminder Settings", "menu:reminders"),
)
FLOW_FIELDS = {
    "journal": TRADE_FIELDS,
    "weekly": WEEKLY_FIELDS,
    "sunday": SUNDAY_FIELDS,
}
BLOCKED_CHAT_ERRORS = (
    "bot was blocked by the user",
    "chat not found",
    "bot can't initiate conversation",
    "bot cannot initiate conversation",
)
@dataclass
class Conversation:
    kind: str
    chat_id: int
    username: str | None
    first_name: str | None
    answers: list[Any] = field(default_factory=list)

    @property
    def step(self) -> int:
        return len(self.answers)


class SmartMoneyHubBot:
    def __init__(
        self,
        api: TelegramAPI,
        database_path: str,
        *,
        admin_id: int | None = None,
        reminder_timezone: str = "Africa/Lagos",
        reminder_time: str = "09:00",
    ) -> None:
        self.api = api
        self.store = Repository(database_path)
        self.admin_id = admin_id
        self.admin_dashboard = AdminDashboard(api, self.store, admin_id)
        self.reminder_zone = ZoneInfo(reminder_timezone)
        self.reminder_time = ClockTime.fromisoformat(reminder_time)
        if self.reminder_time.tzinfo is not None:
            raise ValueError("The reminder time must be local wall time without a UTC offset.")
        # One active conversation per member; saved records live in SQLite.
        self.sessions: dict[int, Conversation] = {}

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
                self._dispatch_due_reminders()
                time_module.sleep(retry_delay)
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
            self._dispatch_due_reminders()

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(message)
            return

        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._handle_callback(callback)

    def _register(
        self, sender: dict[str, Any], chat: dict[str, Any]
    ) -> tuple[int, int, bool]:
        telegram_id = sender.get("id")
        chat_id = chat.get("id")
        if not isinstance(telegram_id, int) or not isinstance(chat_id, int):
            raise ValueError("Telegram update is missing member or chat information.")
        is_private = chat.get("type") == "private"
        self.store.register_user(
            telegram_id=telegram_id,
            username=sender.get("username"),
            first_name=sender.get("first_name"),
            chat_id=chat_id,
            is_private=is_private,
        )
        return telegram_id, chat_id, is_private

    def _handle_message(self, message: dict[str, Any]) -> None:
        text = message.get("text")
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        if not isinstance(text, str):
            return
        telegram_id, chat_id, is_private = self._register(sender, chat)
        command = text.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()

        if command == "/start":
            self.sessions.pop(telegram_id, None)
            self.admin_dashboard.cancel_search(telegram_id)
            self._show_welcome(
                chat_id,
                sender.get("first_name"),
            )
            return
        if command == "/help":
            self.api.send_message(
                chat_id,
                "Use the buttons to assess your SMC knowledge, journal trades, "
                "review progress, and prepare for the week. This is educational, "
                "not a promise or prediction of trading results.",
                self._nav_keyboard(),
            )
            return
        if command in {"/stop", "/unsubscribe"}:
            self.store.set_reminders_enabled(telegram_id, False)
            self.api.send_message(
                chat_id,
                "Scheduled reminders are off. You can still use the bot; turn "
                "reminders on again from Reminder Settings.",
                self._nav_keyboard(),
            )
            return
        if command == "/myid":
            self.api.send_message(
                chat_id,
                f"Your Telegram user ID is {telegram_id}.\n\nTo enable the admin "
                "section, save this number as the Replit Secret "
                "`ADMIN_TELEGRAM_ID`.",
                self._nav_keyboard(),
            )
            return
        if command == "/admin":
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.open(chat_id, telegram_id, is_private)
            return
        if command == "/cancel" and self.admin_dashboard.search_is_pending(telegram_id):
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.open(chat_id, telegram_id, is_private)
            return

        if self.admin_dashboard.search_is_pending(telegram_id):
            self.admin_dashboard.handle_search_message(
                chat_id, telegram_id, is_private, text
            )
            return

        session = self.sessions.get(telegram_id)
        if session and session.chat_id == chat_id:
            if session.kind == "assessment":
                self.api.send_message(
                    chat_id,
                    "Please choose one of the answer buttons, or use Back or Main Menu.",
                    self._nav_keyboard(),
                )
            else:
                self._accept_text_answer(session, text)
            return
        self._show_main_menu(chat_id)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = callback.get("id")
        sender = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        data = callback.get("data")
        if (
            not isinstance(callback_id, str)
            or not isinstance(data, str)
            or not isinstance(sender.get("id"), int)
            or not isinstance(chat.get("id"), int)
        ):
            return

        telegram_id, chat_id, is_private = self._register(sender, chat)
        if data.startswith("quiz:answer:") or data.startswith("answer:"):
            match = re.fullmatch(r"(?:quiz:)?answer:(\d+):(\d+)", data)
            if match:
                question_index, answer_index = map(int, match.groups())
                if (
                    question_index < len(QUESTIONS)
                    and not 0 <= answer_index < len(QUESTIONS[question_index].options)
                ):
                    self.api.answer_callback_query(
                        callback_id, "That answer is not valid."
                    )
                    return
        try:
            self.api.answer_callback_query(callback_id)
        except TelegramAPIError as error:
            # Telegram may expire button callbacks while the bot is offline.
            # The acknowledgement is best-effort; a stale answer must not stop
            # the bot from handling the callback and sending a useful reply.
            logger.warning(
                "Could not acknowledge Telegram callback; continuing to process it: %s",
                error,
            )

        if data.startswith("admin:"):
            self.admin_dashboard.handle_callback(
                chat_id, telegram_id, is_private, data
            )
            return

        if data in {"nav:home", "menu"}:
            self.sessions.pop(telegram_id, None)
            self._show_main_menu(chat_id)
        elif data == "nav:back":
            self._go_back(telegram_id, chat_id)
        elif data in {"start_test", "take_again", "menu:assessment"}:
            self._begin_assessment(
                telegram_id, chat_id, sender.get("username"), sender.get("first_name")
            )
        elif data.startswith("quiz:answer:") or data.startswith("answer:"):
            self._handle_assessment_answer(telegram_id, chat_id, data)
        elif data == "menu:journal":
            self.sessions.pop(telegram_id, None)
            self._show_journal_menu(chat_id)
        elif data == "journal:new":
            self._begin_flow("journal", telegram_id, chat_id, sender)
        elif data == "journal:history":
            self.sessions.pop(telegram_id, None)
            self._show_trade_history(chat_id, telegram_id)
        elif data.startswith("trade:"):
            self._show_trade_detail(chat_id, telegram_id, data)
        elif data == "menu:weekly":
            self._begin_flow("weekly", telegram_id, chat_id, sender)
        elif data == "menu:sunday":
            self._begin_flow("sunday", telegram_id, chat_id, sender)
        elif data == "menu:progress":
            self.sessions.pop(telegram_id, None)
            self._show_progress(chat_id, telegram_id)
        elif data == "menu:learn":
            self.sessions.pop(telegram_id, None)
            self._show_education_menu(chat_id)
        elif data.startswith("edu:"):
            self._show_education_card(chat_id, data.partition(":")[2])
        elif data == "menu:reminders":
            self.sessions.pop(telegram_id, None)
            self._show_reminder_settings(chat_id, telegram_id)
        elif data in {"reminders:toggle", "reminders:on", "reminders:off"}:
            self._change_reminder_setting(
                chat_id, telegram_id, is_private, data
            )
        elif data.startswith("flow:choice:"):
            self._handle_flow_choice(
                telegram_id, chat_id, data.partition("flow:choice:")[2]
            )
        else:
            self.api.send_message(
                chat_id, "That button is no longer active. Choose an option below.",
                self._main_menu_keyboard(),
            )

    def _show_welcome(self, chat_id: int, first_name: str | None) -> None:
        greeting = f" {first_name}" if first_name else ""
        self.api.send_message(
            chat_id,
            (
                f"Welcome{greeting} to Smart Money Hub.\n\n"
                "I can help you learn SMC, test your knowledge, journal trades, "
                "review mistakes, track discipline, prepare for the trading week, "
                "and check in on your progress.\n\n"
                "This bot is for education and journaling. It does not predict "
                "trades or promise profits. Choose where you want to begin."
            ),
            self._main_menu_keyboard(),
        )

    @staticmethod
    def _main_menu_keyboard() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": label, "callback_data": data}]
                for label, data in MAIN_MENU
            ]
        }

    @staticmethod
    def _nav_row() -> list[dict[str, str]]:
        return [
            {"text": "⬅️ Back", "callback_data": "nav:back"},
            {"text": "🏠 Main Menu", "callback_data": "nav:home"},
        ]

    @classmethod
    def _nav_keyboard(cls) -> dict[str, Any]:
        return {"inline_keyboard": [cls._nav_row()]}

    @classmethod
    def _menu_keyboard(
        cls, rows: list[list[dict[str, str]]] | None = None
    ) -> dict[str, Any]:
        return {"inline_keyboard": (rows or []) + [cls._nav_row()]}

    def _begin_assessment(
        self,
        telegram_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
    ) -> None:
        self.sessions[telegram_id] = Conversation(
            "assessment", chat_id, username, first_name
        )
        self._send_assessment_question(telegram_id)

    def _send_assessment_question(self, telegram_id: int) -> None:
        session = self.sessions[telegram_id]
        question_index = session.step
        question = QUESTIONS[question_index]
        rows = [
            [
                {
                    "text": option,
                    "callback_data": f"quiz:answer:{question_index}:{answer_index}",
                }
            ]
            for answer_index, option in enumerate(question.options)
        ]
        rows.append(self._nav_row())
        self.api.send_message(
            session.chat_id,
            (
                f"Question {question_index + 1}/{len(QUESTIONS)} — {question.topic}\n\n"
                f"{question.prompt}"
            ),
            {"inline_keyboard": rows},
        )

    def _handle_assessment_answer(
        self, telegram_id: int, chat_id: int, callback_data: str
    ) -> None:
        session = self.sessions.get(telegram_id)
        if session is None or session.kind != "assessment" or session.chat_id != chat_id:
            self.api.send_message(
                chat_id, "Start a new assessment from the main menu.",
                self._main_menu_keyboard(),
            )
            return
        match = re.fullmatch(r"(?:quiz:)?answer:(\d+):(\d+)", callback_data)
        if not match:
            return
        question_index, answer_index = map(int, match.groups())
        if question_index != session.step or question_index >= len(QUESTIONS):
            self.api.send_message(
                chat_id,
                "That question is no longer active. Use the current answer buttons.",
                self._nav_keyboard(),
            )
            return
        if not 0 <= answer_index < len(QUESTIONS[question_index].options):
            return
        session.answers.append(answer_index)
        if session.step < len(QUESTIONS):
            self._send_assessment_question(telegram_id)
        else:
            self._finish_assessment(telegram_id)

    def _finish_assessment(self, telegram_id: int) -> None:
        session = self.sessions[telegram_id]
        result = grade_answers(session.answers)
        saved = True
        try:
            self.store.save_assessment(telegram_id, session.username, result)
        except Exception:
            saved = False
            logger.exception("Could not save a completed assessment.")
        self.sessions.pop(telegram_id, None)
        self.api.send_message(
            session.chat_id,
            self._format_result(result, saved),
            self._menu_keyboard(
                [[
                    {"text": "Take Test Again", "callback_data": "take_again"},
                    {"text": "My Progress", "callback_data": "menu:progress"},
                ]]
            ),
        )

    @staticmethod
    def _format_result(result: AssessmentResult, saved: bool) -> str:
        lines = [
            "SMC assessment complete",
            f"Score: {result.score}/{result.total} ({result.percentage}%)",
            f"Percentage: {result.percentage}%",
            "Strong areas: " + (", ".join(result.strong_areas) or "Keep building your foundation"),
            "Needs work: " + (", ".join(result.weak_areas) or "No missed topics"),
        ]
        if result.incorrect_answers:
            lines.append("\nQuestions to review:")
            for answer in result.incorrect_answers:
                lines.extend(
                    [
                        f"\nQuestion {answer.question_number} — {answer.topic}",
                        f"Your answer: {answer.selected_answer}",
                        f"Correct answer: {answer.correct_answer}",
                        f"Why: {answer.explanation}",
                    ]
                )
        else:
            lines.append("\nYou got every question right. Keep applying your plan consistently.")
        if not saved:
            lines.append("\nThe result could not be saved. Please tell a Smart Money Hub admin.")
        return "\n".join(lines)

    def _show_journal_menu(self, chat_id: int) -> None:
        self.api.send_message(
            chat_id,
            "Trading Journal\n\nCreate a trade entry or review a previous one.",
            self._menu_keyboard(
                [
                    [{"text": "New Trade Entry", "callback_data": "journal:new"}],
                    [{"text": "Review Previous Trades", "callback_data": "journal:history"}],
                ]
            ),
        )

    def _begin_flow(
        self,
        kind: str,
        telegram_id: int,
        chat_id: int,
        sender: dict[str, Any],
    ) -> None:
        if kind not in FLOW_FIELDS:
            return
        self.sessions[telegram_id] = Conversation(
            kind=kind,
            chat_id=chat_id,
            username=sender.get("username"),
            first_name=sender.get("first_name"),
        )
        self._ask_flow_question(telegram_id)

    def _ask_flow_question(self, telegram_id: int) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.kind not in FLOW_FIELDS:
            return
        fields = FLOW_FIELDS[session.kind]
        if session.step >= len(fields):
            self._finish_flow(telegram_id)
            return
        field = fields[session.step]
        prompt = f"{session.kind.replace('_', ' ').title()} — {session.step + 1}/{len(fields)}\n\n{field.prompt}"
        rows: list[list[dict[str, str]]] = []
        if field.choices:
            rows = [
                [
                    {
                        "text": choice,
                        "callback_data": f"flow:choice:{session.step}:{index}",
                    }
                ]
                for index, choice in enumerate(field.choices)
            ]
        rows.append(self._nav_row())
        if field.kind in {"text", "integer"}:
            prompt += "\n\nReply with your answer."
        self.api.send_message(
            session.chat_id,
            prompt,
            {"inline_keyboard": rows},
        )

    def _accept_text_answer(self, session: Conversation, text: str) -> None:
        fields = FLOW_FIELDS[session.kind]
        field = fields[session.step]
        if field.kind not in {"text", "integer"}:
            self._ask_flow_question_for(session)
            return
        value: Any = text.strip()
        if not value:
            self.api.send_message(
                session.chat_id, "Please enter an answer, or use Back or Main Menu.",
                self._nav_keyboard(),
            )
            return
        if len(value) > 300:
            self.api.send_message(
                session.chat_id, "Please keep the answer under 300 characters.",
                self._nav_keyboard(),
            )
            return
        if field.kind == "integer":
            try:
                value = int(value)
            except ValueError:
                self.api.send_message(
                    session.chat_id, "Please reply with a whole number, such as 3.",
                    self._nav_keyboard(),
                )
                return
            if value < 0 or value > 10000:
                self.api.send_message(
                    session.chat_id, "Enter a number from 0 to 10,000.",
                    self._nav_keyboard(),
                )
                return
            if field.key == "winners" and value > session.answers[0]:
                self.api.send_message(
                    session.chat_id, "Winners cannot exceed the number of trades taken.",
                    self._nav_keyboard(),
                )
                return
            if field.key == "losses" and value + session.answers[1] > session.answers[0]:
                self.api.send_message(
                    session.chat_id,
                    "Winners plus losses cannot exceed the number of trades. Re-enter losses.",
                    self._nav_keyboard(),
                )
                return
        self._accept_flow_answer(session, value)

    def _ask_flow_question_for(self, session: Conversation) -> None:
        self.api.send_message(
            session.chat_id,
            "Please choose one of the buttons for this question.",
            self._menu_keyboard(),
        )

    def _handle_flow_choice(
        self, telegram_id: int, chat_id: int, choice_text: str
    ) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.kind not in FLOW_FIELDS or session.chat_id != chat_id:
            self.api.send_message(
                chat_id, "Start a new flow from the main menu.", self._main_menu_keyboard()
            )
            return
        field = FLOW_FIELDS[session.kind][session.step]
        try:
            step_text, choice_text = choice_text.split(":", maxsplit=1)
            if int(step_text) != session.step:
                self._ask_flow_question(telegram_id)
                return
            choice_index = int(choice_text)
            value = field.choices[choice_index]
        except (ValueError, IndexError):
            self._ask_flow_question(telegram_id)
            return
        if field.kind == "boolean":
            value = value == "Yes"
        self._accept_flow_answer(session, value)

    def _accept_flow_answer(self, session: Conversation, value: Any) -> None:
        session.answers.append(value)
        if session.step < len(FLOW_FIELDS[session.kind]):
            self._ask_flow_question(self._session_id(session))
        else:
            self._finish_flow(self._session_id(session))

    def _session_id(self, session: Conversation) -> int:
        for telegram_id, active in self.sessions.items():
            if active is session:
                return telegram_id
        raise RuntimeError("Conversation session is no longer active.")

    def _finish_flow(self, telegram_id: int) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.kind not in FLOW_FIELDS:
            return
        fields = FLOW_FIELDS[session.kind]
        data = {
            field.key: value for field, value in zip(fields, session.answers)
        }

        try:
            if session.kind == "journal":
                summary = self._trade_review(data)
                trade_id = self.store.save_trade(telegram_id, data, summary)
                self.store.record_reminder_sent(
                    telegram_id, "trade_review", f"trade:{trade_id}"
                )
                response = (
                    f"Trade saved.\n\n{summary}\n\n"
                    "📋 Trade Review Reminder — Have you reviewed today’s trade?\n"
                    "This is an "
                    "educational reflection, not a prediction."
                )
                markup = self._menu_keyboard(
                    [[{"text": "Review Previous Trades", "callback_data": "journal:history"}]]
                )
            elif session.kind == "weekly":
                summary = self._weekly_summary(data)
                self.store.save_weekly_checkin(telegram_id, data, summary)
                response = f"Weekly check-in saved.\n\n{summary}"
                markup = self._menu_keyboard()
            else:
                self.store.save_sunday_preparation(telegram_id, data)
                response = self._sunday_summary(data)
                markup = self._menu_keyboard()
        except Exception:
            logger.exception("Could not save member flow.")
            response = "I couldn't save that entry locally. Please try again later."
            markup = self._menu_keyboard()

        self.sessions.pop(telegram_id, None)
        self.api.send_message(session.chat_id, response, markup)

    @staticmethod
    def _trade_review(data: dict[str, Any]) -> str:
        lines = [
            "TRADE REVIEW",
            f"Asset: {data['asset']}",
            f"Direction: {data['direction']}",
            f"POI: {data['poi']}",
            f"Timeframe: {data['timeframe']}",
            f"Confirmation: {data['confirmation']}",
            f"Liquidity swept: {'Yes' if data['liquidity_swept'] else 'No'}",
            f"Retest: {'Yes' if data['waited_for_retest'] else 'No'}",
            f"Stop loss: {data['stop_loss']}",
            f"Take profit: {data['take_profit']}",
            f"Partial profit: {'Yes' if data['partial_profit'] else 'No'}",
            f"SL moved to BE: {'Yes' if data['moved_sl_to_be'] else 'No'}",
            f"Result: {data['result']}",
            f"Followed plan: {'Yes' if data['followed_plan'] else 'No'}",
            f"Mistake: {data['mistake']}",
            f"Lesson: {data['lesson']}",
        ]
        potential_issues: list[str] = []
        if data["confirmation"].strip().casefold() in {
            "none",
            "no confirmation",
            "n/a",
        }:
            potential_issues.append("You recorded no confirmation.")
        if not data["waited_for_retest"]:
            potential_issues.append("You recorded no retest; review whether you entered before it.")
        if not data["followed_plan"]:
            potential_issues.append("You noted that the written plan was not followed.")
        if not data["liquidity_swept"]:
            potential_issues.append("No liquidity sweep was recorded; consider whether it mattered to your setup.")
        lines.append("\nPotential issue:")
        lines.extend(potential_issues or ["No process issue was reported in this entry."])
        lines.append("\nReminder: No confirmation, no entry. No retest, no entry. Do not chase.")
        return "\n".join(lines)

    @staticmethod
    def _weekly_summary(data: dict[str, Any]) -> str:
        lines = [
            f"Trades: {data['trades_taken']} | Wins: {data['winners']} | Losses: {data['losses']}",
            "Discipline notes:",
        ]
        observations = []
        if not data["followed_plan"]:
            observations.append("You reported that you did not follow your plan.")
        if data["entered_without_confirmation"]:
            observations.append("You reported entering without confirmation.")
        if data["chased_missed_trade"]:
            observations.append("You reported chasing a missed setup.")
        if data["moved_sl_unnecessarily"]:
            observations.append("You reported moving your stop loss unnecessarily.")
        if not data["secured_partials"]:
            observations.append("Review how partials and break-even fit your plan.")
        lines.extend(observations or ["You reported following your plan this week."])
        lines.extend(
            [
                f"Biggest mistake: {data['biggest_mistake']}",
                f"Next week's focus: {data['next_focus']}",
                "No trade outcome is guaranteed. Keep risk and process first.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _sunday_summary(data: dict[str, Any]) -> str:
        return (
            "Your week is set.\n\n"
            f"Goal: {data['weekly_goal']}\n"
            f"SMC focus: {data['concept_focus']}\n"
            f"Mistake to avoid: {data['mistake_to_avoid']}\n"
            f"If you miss a setup: {data['missed_setup_plan']}\n\n"
            "No confirmation, no entry. No retest, no entry. Do not chase."
        )

    def _show_trade_history(self, chat_id: int, telegram_id: int) -> None:
        trades = self.store.recent_trades(telegram_id, 8)
        if not trades:
            self.api.send_message(
                chat_id, "You don't have saved journal entries yet.",
                self._menu_keyboard(
                    [[{"text": "New Trade Entry", "callback_data": "journal:new"}]]
                ),
            )
            return
        rows: list[list[dict[str, str]]] = []
        for trade in trades:
            when = str(trade["created_at"])[:10]
            label = f"{when} · {trade['asset']} {trade['direction']} · {trade['result']}"
            rows.append(
                [{"text": label[:60], "callback_data": f"trade:{trade['id']}"}]
            )
        self.api.send_message(
            chat_id,
            "Your recent trade entries. Select one to review the saved details.",
            self._menu_keyboard(rows),
        )

    def _show_trade_detail(self, chat_id: int, telegram_id: int, data: str) -> None:
        try:
            trade_id = int(data.partition(":")[2])
        except ValueError:
            return
        trade = self.store.trade_by_id(telegram_id, trade_id)
        if not trade:
            self.api.send_message(
                chat_id, "That trade entry wasn't found.",
                self._menu_keyboard(
                    [[{"text": "Trade History", "callback_data": "journal:history"}]]
                ),
            )
            return
        self.api.send_message(
            chat_id,
            f"Saved trade from {trade['created_at'][:10]}\n\n{trade['review_summary']}",
            self._menu_keyboard(
                [[{"text": "Trade History", "callback_data": "journal:history"}]]
            ),
        )

    def _show_progress(self, chat_id: int, telegram_id: int) -> None:
        progress = self.store.progress_for(telegram_id)
        weekly = self.store.recent_checkins(telegram_id, 3)
        sunday_plan = self.store.latest_sunday_preparation(telegram_id)
        current_focus = "Set a focus in Sunday Preparation"
        if weekly:
            current_focus = weekly[0]["next_focus"]
        if (
            sunday_plan
            and (
                not weekly
                or sunday_plan["completed_at"] >= weekly[0]["completed_at"]
            )
        ):
            current_focus = sunday_plan["concept_focus"]
        average = progress.get("assessment_average")
        lines = [
            "SMART MONEY HUB PROGRESS",
            f"Tests completed: {progress.get('tests_completed', 0)}",
            f"Assessment average: {str(average) + '%' if average is not None else '—'}",
            f"Latest score: {str(progress.get('latest_assessment_score')) + '/10' if progress.get('latest_assessment_score') is not None else '—'}",
            f"Trades journaled: {progress.get('trades_journaled', 0)}",
            f"Winning trades: {progress.get('winning_trades', 0)}",
            f"Losing trades: {progress.get('losing_trades', 0)}",
            f"Most common mistake: {progress.get('most_common_mistake') or 'Not enough journal history'}",
            f"Strongest SMC topic: {progress.get('strongest_topic') or 'Complete an assessment to see this'}",
            f"Weakest SMC topic: {progress.get('weakest_topic') or 'Complete an assessment to see this'}",
            f"Current focus: {current_focus}",
            f"Weekly check-ins: {progress.get('weekly_checkins_count', 0)}",
        ]
        if weekly:
            lines.append("\nRecent weekly check-ins:")
            for item in weekly:
                lines.append(
                    f"{item['completed_at'][:10]} — {item['trades_taken']} trades, "
                    f"{item['winners']} wins, {item['losses']} losses; focus: {item['next_focus']}"
                )
        self.api.send_message(chat_id, "\n".join(lines), self._nav_keyboard())

    def _show_education_menu(self, chat_id: int) -> None:
        topics = list(EDUCATION.items())
        rows = [
            [
                {"text": topics[index][1][0], "callback_data": f"edu:{topics[index][0]}"}
                for index in range(start, min(start + 2, len(topics)))
            ]
            for start in range(0, len(topics), 2)
        ]
        self.api.send_message(
            chat_id,
            "Learn SMC\n\nChoose a short lesson. The content is educational, not a trade signal.",
            self._menu_keyboard(rows),
        )

    def _show_education_card(self, chat_id: int, slug: str) -> None:
        card = EDUCATION.get(slug)
        if not card:
            self._show_education_menu(chat_id)
            return
        self.api.send_message(
            chat_id,
            f"{card[0]}\n\n{card[1]}",
            self._menu_keyboard(
                [[{"text": "All Lessons", "callback_data": "menu:learn"}]]
            ),
        )

    def _show_reminder_settings(self, chat_id: int, telegram_id: int) -> None:
        enabled = self.store.reminders_enabled(telegram_id)
        state = "On" if enabled else "Off"
        toggle_text = "Turn reminders off" if enabled else "Turn reminders on"
        self.api.send_message(
            chat_id,
            f"Scheduled Sunday check-ins: {state}.\n"
            f"Schedule: Sunday at {self.reminder_time.strftime('%H:%M')} "
            f"({self.reminder_zone.key}).\n\n"
            "Only members who have started the bot in a private chat and opted "
            "in receive reminders. Use /stop at any time to unsubscribe.",
            self._menu_keyboard(
                [[{"text": toggle_text, "callback_data": "reminders:toggle"}]]
            ),
        )

    def _change_reminder_setting(
        self, chat_id: int, telegram_id: int, is_private: bool, action: str
    ) -> None:
        current = self.store.reminders_enabled(telegram_id)
        enabled = action == "reminders:on" or (
            action == "reminders:toggle" and not current
        )
        if not enabled:
            self.store.set_reminders_enabled(telegram_id, False)
            self._show_reminder_settings(chat_id, telegram_id)
            return
        if not is_private or not self.store.set_reminders_enabled(telegram_id, True):
            self.api.send_message(
                chat_id,
                "Open this bot in a private chat and send /start before enabling reminders.",
                self._nav_keyboard(),
            )
            return
        self._show_reminder_settings(chat_id, telegram_id)

    def _dispatch_due_reminders(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        local_now = current.astimezone(self.reminder_zone)
        if local_now.weekday() != 6 or local_now.time().replace(tzinfo=None) < self.reminder_time:
            return
        schedule_key = local_now.date().isoformat()
        for member in self.store.reminder_recipients():
            telegram_id = int(member["telegram_id"])
            if self.store.reminder_was_sent(
                telegram_id, "weekly_sunday", schedule_key
            ):
                continue
            try:
                self.api.send_message(
                    int(member["chat_id"]),
                    "🧠 Sunday Check-In — are you prepared for the week?\n\n"
                    "Choose a check-in or set your weekly plan.",
                    {
                        "inline_keyboard": [
                            [
                                {"text": "Weekly Check-In", "callback_data": "menu:weekly"},
                                {"text": "Sunday Preparation", "callback_data": "menu:sunday"},
                            ],
                            [{"text": "Stop Reminders", "callback_data": "reminders:off"}],
                        ]
                    },
                )
            except TelegramAPIError as error:
                if any(part in str(error).casefold() for part in BLOCKED_CHAT_ERRORS):
                    self.store.set_reminders_enabled(telegram_id, False)
                    logger.info("Disabled reminders for a Telegram chat that is unavailable.")
                else:
                    logger.warning("Could not send a scheduled reminder: %s", error)
                continue
            self.store.record_reminder_sent(
                telegram_id, "weekly_sunday", schedule_key
            )

    def _go_back(self, telegram_id: int, chat_id: int) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.chat_id != chat_id:
            self._show_main_menu(chat_id)
            return
        if session.kind == "assessment":
            if session.answers:
                session.answers.pop()
                self._send_assessment_question(telegram_id)
            else:
                self.sessions.pop(telegram_id, None)
                self._show_main_menu(chat_id)
            return
        if session.answers:
            session.answers.pop()
            self._ask_flow_question(telegram_id)
            return
        self.sessions.pop(telegram_id, None)
        if session.kind == "journal":
            self._show_journal_menu(chat_id)
        else:
            self._show_main_menu(chat_id)

    def _show_main_menu(self, chat_id: int) -> None:
        self.api.send_message(
            chat_id, "Choose an option:", self._main_menu_keyboard()
        )