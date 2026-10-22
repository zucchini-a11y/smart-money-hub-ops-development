"""Telegram menus and stateful SMC education, journaling, and assessment flows."""

import logging
import random
import re
import time as time_module
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time as ClockTime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .admin_dashboard import AdminDashboard
from .coach import CoachService, RuleBasedCoachService
from .education import EDUCATION
from .flows import SUNDAY_FIELDS, TRADE_FIELDS, WEEKLY_FIELDS
from .message_router import CoachMessageRouter
from .questions import QUESTIONS
from .scoring import AssessmentResult, grade_answers
from .storage import Repository
from .telegram_api import TelegramAPI, TelegramAPIError


logger = logging.getLogger(__name__)
MAIN_MENU: tuple[tuple[str, str], ...] = (
    ("Start SMC Assessment", "menu:assessment"),
    ("💬 Ask Coach", "menu:coach"),
    ("🎯 Challenge Me", "coach:challenge"),
    ("🔍 Review My Setup", "coach:setup"),
    ("📒 Review My Mistake", "coach:mistake"),
    ("🧠 Teach Me Something", "coach:teach"),
    ("🔥 Daily Challenge", "coach:daily"),
    ("Trading Journal", "menu:journal"),
    ("Weekly Check-In", "menu:weekly"),
    ("Sunday Preparation", "menu:sunday"),
    ("My Progress", "menu:progress"),
    ("Learn SMC", "menu:learn"),
    ("Reminder Settings", "menu:reminders"),
)
COACH_GUIDED_PROMPTS: dict[str, tuple[str, ...]] = {
    "coach_setup": (
        "What asset and timeframe are you looking at, and are you considering a long or short?",
        "What is the higher-timeframe context, and where is your point of interest?",
        "What liquidity was taken, and what confirmation or retest did you see?",
        "Where would the setup be invalidated, and what risk limit is in your plan?",
    ),
    "coach_mistake": (
        "What happened? Share the trade decision or moment you want to review.",
        "What did your written plan say you would do?",
        "What got in the way, and what one rule would you like to reinforce next time?",
    ),
}
COACH_CHALLENGES: tuple[dict[str, Any], ...] = (
    {
        "id": "liquidity",
        "topic": "Liquidity / SSL / BSL",
        "difficulty": 0,
        "prompt": "Where is buy-side liquidity (BSL) commonly found?",
        "options": (
            "Below obvious lows",
            "Above obvious highs",
            "Only inside an FVG",
            "At every candle close",
        ),
        "answer": 1,
        "explanation": "BSL is commonly watched above obvious highs; SSL is commonly below lows.",
    },
    {
        "id": "fvg",
        "topic": "FVG / IFVG",
        "difficulty": 0,
        "prompt": "Does an FVG alone confirm an entry?",
        "options": ("Yes, always", "No; it is an area to watch", "Only on gold", "Only on 1-minute charts"),
        "answer": 1,
        "explanation": "An FVG may be a POI, but you still need the confirmation your plan calls for.",
    },
    {
        "id": "retest",
        "topic": "Retest",
        "difficulty": 1,
        "prompt": "In a retest-based entry model, price breaks a relevant swing and runs without returning. What is the disciplined choice?",
        "options": ("Chase the move", "Increase size", "Wait for another setup", "Move the stop closer"),
        "answer": 2,
        "explanation": "If the chosen model requires a retest and it never comes, skip that setup rather than chase it; other models may use different entry triggers.",
    },
    {
        "id": "risk",
        "topic": "Risk Management",
        "difficulty": 1,
        "prompt": "When should invalidation and acceptable risk be decided?",
        "options": ("Before entry", "After price moves against you", "Only after a win", "Whenever the chart feels uncertain"),
        "answer": 0,
        "explanation": "Define invalidation and risk before entry so the decision is not improvised under pressure.",
    },
    {
        "id": "choch",
        "topic": "CHoCH",
        "difficulty": 1,
        "prompt": "A CHoCH is best treated as…",
        "options": (
            "A guaranteed reversal",
            "An early sign order flow may be shifting",
            "A reason to ignore the higher timeframe",
            "An automatic entry signal",
        ),
        "answer": 1,
        "explanation": "A CHoCH can warn that structure is changing, but it does not guarantee a reversal or entry.",
    },
    {
        "id": "bos_context",
        "topic": "BOS",
        "difficulty": 0,
        "prompt": "What does a Break of Structure (BOS) describe?",
        "options": (
            "A break through a relevant swing in the current move's direction",
            "Any candle with a long wick",
            "A guaranteed reversal",
            "A fixed take-profit level",
        ),
        "answer": 0,
        "explanation": "A BOS is a break of a relevant swing in the direction of the move; context and the close matter.",
    },
    {
        "id": "mss_liquidity",
        "topic": "MSS",
        "difficulty": 2,
        "prompt": "Which sequence gives a Market Structure Shift stronger context?",
        "options": (
            "A random wick with no nearby level",
            "A liquidity event followed by displacement and a structure shift",
            "An indicator changing colour",
            "Price touching any moving average",
        ),
        "answer": 1,
        "explanation": "A liquidity event and decisive displacement can add context to a shift, but it is still not a guaranteed entry.",
    },
    {
        "id": "ssl_location",
        "topic": "Liquidity / SSL / BSL",
        "difficulty": 0,
        "prompt": "Where is sell-side liquidity (SSL) commonly watched?",
        "options": (
            "Above obvious highs",
            "Below obvious lows",
            "Only inside an order block",
            "At every candle open",
        ),
        "answer": 1,
        "explanation": "SSL is commonly watched below obvious lows; BSL is commonly watched above highs.",
    },
    {
        "id": "order_block_context",
        "topic": "Order Blocks",
        "difficulty": 1,
        "prompt": "How should an order block be treated in a trade plan?",
        "options": (
            "As an automatic entry signal",
            "As a possible area of interest that still needs confirmation",
            "As proof price must reverse",
            "As a replacement for a stop loss",
        ),
        "answer": 1,
        "explanation": "An order block is a possible POI, not a guaranteed reaction or entry.",
    },
    {
        "id": "ifvg_invalidation",
        "topic": "FVG / IFVG",
        "difficulty": 2,
        "prompt": "What makes a fair value gap an inverse FVG (IFVG) concept?",
        "options": (
            "It has never been revisited",
            "It is invalidated and may act as an opposing area",
            "It appears on a higher timeframe",
            "It contains exactly three candles",
        ),
        "answer": 1,
        "explanation": "An IFVG describes an invalidated gap that may act as an opposing area; it still needs context.",
    },
    {
        "id": "displacement_evidence",
        "topic": "Displacement",
        "difficulty": 1,
        "prompt": "What is the most useful evidence that a move is displacement?",
        "options": (
            "A decisive move away from an area that breaks meaningful structure",
            "Any single candle that is larger than the last",
            "A price gap with no context",
            "A series of small candles inside a range",
        ),
        "answer": 0,
        "explanation": "Displacement is a decisive, impulsive move; look at what it moved from and what structure it affected.",
    },
    {
        "id": "poi_role",
        "topic": "POI",
        "difficulty": 0,
        "prompt": "What is a Point of Interest (POI) used for?",
        "options": (
            "To mark an area to watch for a planned setup",
            "To guarantee an entry",
            "To choose position size without a stop",
            "To predict the next candle",
        ),
        "answer": 0,
        "explanation": "A POI is an area to watch; it is not an entry trigger by itself.",
    },
    {
        "id": "timeframe_context",
        "topic": "HTF / LTF Analysis",
        "difficulty": 1,
        "prompt": "What is a common role for higher- and lower-timeframe analysis?",
        "options": (
            "Use the lower timeframe for bias and ignore the higher timeframe",
            "Use the higher timeframe for context and lower timeframe for timing",
            "Use both only after entering",
            "Treat any timeframe conflict as a guaranteed reversal",
        ),
        "answer": 1,
        "explanation": "The higher timeframe can frame context while the lower timeframe helps with timing and confirmation.",
    },
    {
        "id": "risk_reward_ratio",
        "topic": "Risk:Reward",
        "difficulty": 1,
        "prompt": "A plan risks 10 points to target 20 points. What is its planned risk-to-reward ratio?",
        "options": ("1:1", "1:2", "2:1", "1:3"),
        "answer": 1,
        "explanation": "The target distance is twice the risk distance, so the planned ratio is 1:2. That does not guarantee the outcome.",
    },
    {
        "id": "stop_loss_logic",
        "topic": "Stop Loss",
        "difficulty": 1,
        "prompt": "What should guide a stop-loss level?",
        "options": (
            "The setup's invalidation, with position size adjusted to risk",
            "The amount you hope to make",
            "A level moved farther away after every loss",
            "A fixed number unrelated to the setup",
        ),
        "answer": 0,
        "explanation": "Place the stop where the setup is invalidated and size the position to fit your risk limit.",
    },
    {
        "id": "take_profit_plan",
        "topic": "Take Profit",
        "difficulty": 1,
        "prompt": "When is it best to decide your planned take-profit level?",
        "options": (
            "Before entry, using the plan and relevant levels",
            "Only after price starts moving against you",
            "After seeing another trader's result",
            "Whenever you feel excited",
        ),
        "answer": 0,
        "explanation": "Planning a target before entry helps avoid decisions driven only by fear or excitement.",
    },
    {
        "id": "fomo_pause",
        "topic": "FOMO",
        "difficulty": 0,
        "prompt": "You feel FOMO after price has already moved. What is the disciplined response?",
        "options": (
            "Chase immediately with a larger position",
            "Pause and check whether a planned setup still exists",
            "Remove your stop to give the trade room",
            "Enter because you might miss the move",
        ),
        "answer": 1,
        "explanation": "Pause and check the written rules; being willing to miss a move is part of a disciplined process.",
    },
    {
        "id": "revenge_trading_pause",
        "topic": "Revenge Trading",
        "difficulty": 1,
        "prompt": "What is a useful first step after noticing revenge-trading urges?",
        "options": (
            "Increase size to recover the loss faster",
            "Pause, review your risk limit, and wait for a planned setup",
            "Take several trades quickly",
            "Move the next stop farther away",
        ),
        "answer": 1,
        "explanation": "A pause helps prevent a previous loss from dictating the next decision.",
    },
    {
        "id": "breakeven_timing",
        "topic": "Break-Even",
        "difficulty": 1,
        "prompt": "What should determine when you move a stop to break-even?",
        "options": (
            "A rule or milestone written in the plan",
            "The first small candle in profit",
            "A feeling that the market looks uncertain",
            "The result of your previous trade",
        ),
        "answer": 0,
        "explanation": "Use a planned milestone so the stop move is not an emotional reaction to normal price noise.",
    },
    {
        "id": "swing_structure",
        "topic": "Market Structure",
        "difficulty": 0,
        "prompt": "Which sequence most commonly describes upward market structure?",
        "options": (
            "Lower highs and lower lows",
            "Higher highs and higher lows",
            "Equal highs only",
            "One large candle in either direction",
        ),
        "answer": 1,
        "explanation": "A sequence of higher highs and higher lows commonly indicates upward structure; a range may be less clear.",
    },
    {
        "id": "confirmation_plan",
        "topic": "Confirmation",
        "difficulty": 2,
        "prompt": "Which is a stronger confirmation rule for a setup?",
        "options": (
            "Enter whenever price touches the POI",
            "Wait for the specific structure or displacement event in the plan",
            "Enter after a social-media signal",
            "Use the same confirmation on every chart without context",
        ),
        "answer": 1,
        "explanation": "A useful confirmation is defined in advance and fits the setup context; a POI alone is not enough.",
    },
)
CLASS_REMINDER_WEEKDAYS = {0: "Monday", 3: "Thursday"}
CLASS_REMINDER_TIME = ClockTime(19, 0)
CLASS_START_TIME = ClockTime(20, 0)
CLASS_REMINDER_GRACE = timedelta(minutes=5)
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
        main_channel_id: int | None = None,
        reminder_timezone: str = "Africa/Lagos",
        reminder_time: str = "09:00",
        coach_service: CoachService | None = None,
    ) -> None:
        self.api = api
        self.store = Repository(database_path)
        self.admin_id = admin_id
        self.admin_dashboard = AdminDashboard(
            api, self.store, admin_id, main_channel_id
        )
        self.reminder_zone = ZoneInfo(reminder_timezone)
        self.reminder_time = ClockTime.fromisoformat(reminder_time)
        if self.reminder_time.tzinfo is not None:
            raise ValueError("The reminder time must be local wall time without a UTC offset.")
        # One active conversation per member; saved records live in SQLite.
        self.sessions: dict[int, Conversation] = {}
        self.coach_service: CoachService = coach_service or RuleBasedCoachService()
        self.message_router = CoachMessageRouter(self.coach_service, self.store)

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
        if command.startswith("/") and command != "/cancel":
            self.admin_dashboard.cancel_knowledge_action(telegram_id)

        if command == "/start":
            self.sessions.pop(telegram_id, None)
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.cancel_broadcast(telegram_id)
            self.admin_dashboard.cancel_channel_promo(telegram_id)
            self._show_welcome(
                chat_id,
                sender.get("first_name"),
            )
            return
        if command == "/help":
            self.api.send_message(
                chat_id,
                "Use 💬 Ask Coach to discuss SMC in a private chat, or use the "
                "buttons to assess your knowledge, journal trades, review progress, "
                "and prepare for the week. This is educational, not a promise or "
                "prediction of trading results.\n\n"
                "Quick commands: /menu for the main menu, /progress for your "
                "private progress summary, /reminders to check your schedule, "
                "/resume to turn scheduled reminders back on, and /stop to turn "
                "them off. Use /clearcoach to review and clear your saved Coach chats.",
                self._nav_keyboard(),
            )
            return
        if command == "/menu":
            self.sessions.pop(telegram_id, None)
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.cancel_broadcast(telegram_id)
            self.admin_dashboard.cancel_channel_promo(telegram_id)
            self._show_main_menu(chat_id)
            return
        if command == "/progress":
            self.sessions.pop(telegram_id, None)
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.cancel_broadcast(telegram_id)
            if not is_private:
                self.api.send_message(
                    chat_id,
                    "For privacy, open a private chat with this bot to view your progress.",
                    self._nav_keyboard(),
                )
                return
            self._show_progress(chat_id, telegram_id)
            return
        if command == "/reminders":
            self.sessions.pop(telegram_id, None)
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.cancel_broadcast(telegram_id)
            if not is_private:
                self._reminder_private_chat_required(chat_id)
                return
            self._show_reminder_settings(chat_id, telegram_id)
            return
        if command == "/resume":
            self.sessions.pop(telegram_id, None)
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.cancel_broadcast(telegram_id)
            if not is_private:
                self._reminder_private_chat_required(chat_id)
                return
            self._change_reminder_setting(
                chat_id, telegram_id, is_private, "reminders:on"
            )
            return
        if command == "/coach":
            self._show_coach_menu(chat_id, is_private)
            return
        if command in {"/clearcoach", "/forgetcoach"}:
            if not is_private:
                self.api.send_message(
                    chat_id,
                    "For privacy, clear your coaching history in a private chat with this bot.",
                    self._nav_keyboard(),
                )
                return
            self._confirm_clear_coach_history(chat_id)
            return
        if command in {"/stop", "/unsubscribe"}:
            self.admin_dashboard.cancel_broadcast(telegram_id)
            self.store.set_reminders_stopped(telegram_id, True)
            self.api.send_message(
                chat_id,
                "All scheduled Sunday and Zoom class reminders are off. You can still "
                "use the bot; open Reminder Settings to resume them.",
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
            self.admin_dashboard.cancel_broadcast(telegram_id)
            self.admin_dashboard.cancel_channel_promo(telegram_id)
            self.admin_dashboard.open(chat_id, telegram_id, is_private)
            return
        if command == "/cancel" and (
            self.admin_dashboard.search_is_pending(telegram_id)
            or self.admin_dashboard.has_broadcast_state(telegram_id)
            or self.admin_dashboard.has_channel_promo_state(telegram_id)
            or self.admin_dashboard.has_knowledge_state(telegram_id)
        ):
            self.admin_dashboard.cancel_search(telegram_id)
            self.admin_dashboard.cancel_broadcast(telegram_id)
            self.admin_dashboard.cancel_channel_promo(telegram_id)
            self.admin_dashboard.cancel_knowledge_action(telegram_id)
            self.admin_dashboard.open(chat_id, telegram_id, is_private)
            return

        if self.admin_dashboard.search_is_pending(telegram_id):
            logger.info("Coach bypassed: pending admin search flow.")
            self.admin_dashboard.handle_search_message(
                chat_id, telegram_id, is_private, text
            )
            return
        if self.admin_dashboard.broadcast_is_pending(telegram_id):
            logger.info("Coach bypassed: pending admin broadcast flow.")
            self.admin_dashboard.handle_broadcast_message(
                chat_id, telegram_id, is_private, text
            )
            return
        if self.admin_dashboard.knowledge_is_pending(telegram_id):
            logger.info("Coach bypassed: pending admin knowledge flow.")
            self.admin_dashboard.handle_knowledge_message(
                chat_id, telegram_id, is_private, text
            )
            return

        session = self.sessions.get(telegram_id)
        if session and session.chat_id == chat_id:
            logger.info(
                "Coach bypassed: active conversation state kind=%s.",
                session.kind,
            )
            if session.kind == "assessment":
                self.api.send_message(
                    chat_id,
                    "Please choose one of the answer buttons, or use Back or Main Menu.",
                    self._nav_keyboard(),
                )
            elif session.kind in COACH_GUIDED_PROMPTS:
                self._accept_guided_coach_answer(telegram_id, text)
            elif session.kind in {"coach_challenge", "coach_daily"}:
                self.api.send_message(
                    chat_id,
                    "Tap one of the answer buttons, or return to the main menu.",
                    self._coach_keyboard(),
                )
            else:
                self._accept_text_answer(session, text)
            return
        if is_private:
            self._answer_coach_message(
                chat_id,
                telegram_id,
                sender.get("username"),
                text,
            )
        else:
            self.api.send_message(
                chat_id,
                "DM Coach is private. Open a private chat with this bot and send "
                "/start or /coach to begin.",
                self._main_menu_keyboard(),
            )

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
        if data.startswith("coach:challenge:answer:") or data.startswith(
            "coach:daily:answer:"
        ):
            match = re.fullmatch(
                r"coach:(?:challenge|daily):answer:([a-z_]+):(\d+)", data
            )
            if not match or not 0 <= int(match.group(2)) < len(
                COACH_CHALLENGES[0]["options"]
            ):
                self.api.answer_callback_query(callback_id, "That answer is not valid.")
                return
        if data.startswith("coach:feedback:") and not re.fullmatch(
            r"coach:feedback:\d+:(?:helpful|unhelpful|unclear)", data
        ):
            self.api.answer_callback_query(callback_id, "That feedback button is invalid.")
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

        if data not in {
            "admin:dm_broadcast",
            "admin:dm_broadcast:confirm",
            "admin:dm_broadcast:cancel",
        }:
            self.admin_dashboard.cancel_broadcast(telegram_id)
        if not data.startswith("admin:"):
            self.admin_dashboard.cancel_knowledge_action(telegram_id)

        feedback_match = re.fullmatch(
            r"coach:feedback:(\d+):(helpful|unhelpful|unclear)", data
        )
        if feedback_match:
            self._handle_coach_feedback(
                chat_id,
                telegram_id,
                is_private,
                int(feedback_match.group(1)),
                feedback_match.group(2),
            )
            return

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
        elif data == "menu:coach":
            self.sessions.pop(telegram_id, None)
            self._show_coach_menu(chat_id, is_private)
        elif data == "coach:chat":
            self.sessions.pop(telegram_id, None)
            self._enter_coach(chat_id, telegram_id, is_private)
        elif data == "coach:challenge":
            self._start_coach_challenge(telegram_id, chat_id, sender, is_private)
        elif data == "coach:daily":
            self._start_coach_challenge(
                telegram_id, chat_id, sender, is_private, daily=True
            )
        elif data in {"coach:setup", "coach:mistake"}:
            kind = "coach_setup" if data == "coach:setup" else "coach_mistake"
            self._begin_guided_coach_session(
                kind, telegram_id, chat_id, sender, is_private
            )
        elif data == "coach:teach":
            self.sessions.pop(telegram_id, None)
            if is_private:
                self._show_education_menu(chat_id)
            else:
                self._enter_coach(chat_id, telegram_id, is_private)
        elif data == "coach:clear:prompt":
            self._confirm_clear_coach_history(chat_id, is_private=is_private)
        elif data == "coach:clear:confirm":
            if not is_private:
                self._confirm_clear_coach_history(chat_id, is_private=False)
            else:
                deleted = self.store.clear_dm_coaching_history(telegram_id)
                session = self.sessions.get(telegram_id)
                if session and session.kind in {
                    "coach_challenge",
                    "coach_daily",
                    *COACH_GUIDED_PROMPTS,
                }:
                    self.sessions.pop(telegram_id, None)
                self.api.send_message(
                    chat_id,
                    f"Done — I cleared {deleted} saved coaching conversation"
                    f"{'' if deleted == 1 else 's'} for this account. Your assessments, "
                    "trade journal, and reminder settings are unchanged.",
                    self._coach_menu_keyboard(),
                )
        elif data == "coach:clear:cancel":
            self._show_coach_menu(chat_id, is_private)
        elif data.startswith("coach:challenge:answer:") or data.startswith(
            "coach:daily:answer:"
        ):
            self._handle_coach_challenge_answer(
                telegram_id, chat_id, data, is_private
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
        elif data in {
            "reminders:toggle",
            "reminders:weekly:toggle",
            "reminders:class:toggle",
            "reminders:on",
            "reminders:off",
        }:
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

    def _enter_coach(self, chat_id: int, telegram_id: int, is_private: bool) -> None:
        if not is_private:
            self.api.send_message(
                chat_id,
                "For member privacy, open a private chat with this bot and send /coach.",
                self._main_menu_keyboard(),
            )
            return
        self.sessions.pop(telegram_id, None)
        self.api.send_message(
            chat_id,
            "Chat with Coach is open. Ask a question, tell me what happened, or "
            "continue where we left off. I’ll help you think it through without "
            "pretending to see a live chart or giving you an entry.",
            self._coach_keyboard(),
        )

    def _show_coach_menu(self, chat_id: int, is_private: bool) -> None:
        if not is_private:
            self.api.send_message(
                chat_id,
                "Coaching modes are private. Open a private chat with this bot to continue.",
                self._main_menu_keyboard(),
            )
            return
        self.api.send_message(
            chat_id,
            "Choose how you want to work today. Challenges and guided reviews are "
            "optional; the bot won’t send extra challenge messages on its own.",
            self._coach_menu_keyboard(),
        )

    @staticmethod
    def _coach_menu_keyboard() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": "💬 Chat with Coach", "callback_data": "coach:chat"}],
                [{"text": "🎯 Challenge Me", "callback_data": "coach:challenge"}],
                [{"text": "🔍 Review My Setup", "callback_data": "coach:setup"}],
                [{"text": "📒 Review My Mistake", "callback_data": "coach:mistake"}],
                [{"text": "🧠 Teach Me Something", "callback_data": "coach:teach"}],
                [{"text": "🔥 Daily Challenge", "callback_data": "coach:daily"}],
                [{"text": "🧹 Clear My Coach History", "callback_data": "coach:clear:prompt"}],
                SmartMoneyHubBot._nav_row(),
            ]
        }

    def _confirm_clear_coach_history(
        self, chat_id: int, *, is_private: bool = True
    ) -> None:
        if not is_private:
            self.api.send_message(
                chat_id,
                "For privacy, clear coaching history in a private chat with this bot.",
                self._nav_keyboard(),
            )
            return
        self.api.send_message(
            chat_id,
            "Clear your saved Coach conversation history? This removes your saved "
            "Coach chats and Coach mistake notes. Your assessments, trade journal, "
            "and reminder settings will stay unchanged.",
            {
                "inline_keyboard": [
                    [{"text": "Clear Coach History", "callback_data": "coach:clear:confirm"}],
                    [{"text": "Cancel", "callback_data": "coach:clear:cancel"}],
                    self._nav_row(),
                ]
            },
        )

    def _begin_guided_coach_session(
        self,
        kind: str,
        telegram_id: int,
        chat_id: int,
        sender: dict[str, Any],
        is_private: bool,
    ) -> None:
        if not is_private:
            self._show_coach_menu(chat_id, is_private)
            return
        self.sessions[telegram_id] = Conversation(
            kind=kind,
            chat_id=chat_id,
            username=sender.get("username"),
            first_name=sender.get("first_name"),
        )
        self._ask_guided_coach_question(telegram_id)

    def _ask_guided_coach_question(self, telegram_id: int) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.kind not in COACH_GUIDED_PROMPTS:
            return
        prompts = COACH_GUIDED_PROMPTS[session.kind]
        if session.step >= len(prompts):
            self._finish_guided_coach_session(telegram_id)
            return
        title = "Setup Review" if session.kind == "coach_setup" else "Mistake Review"
        self.api.send_message(
            session.chat_id,
            f"{title} — {session.step + 1}/{len(prompts)}\n\n"
            f"{prompts[session.step]}\n\nReply with one answer. You can use Back or Main Menu.",
            self._nav_keyboard(),
        )

    def _accept_guided_coach_answer(self, telegram_id: int, text: str) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.kind not in COACH_GUIDED_PROMPTS:
            return
        value = text.strip()
        if not value:
            self._ask_guided_coach_question(telegram_id)
            return
        if len(value) > 400:
            self.api.send_message(
                session.chat_id,
                "Please keep each answer under 400 characters so I can review it clearly.",
                self._nav_keyboard(),
            )
            return
        session.answers.append(value)
        if session.step < len(COACH_GUIDED_PROMPTS[session.kind]):
            self._ask_guided_coach_question(telegram_id)
        else:
            self._finish_guided_coach_session(telegram_id)

    def _finish_guided_coach_session(self, telegram_id: int) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.kind not in COACH_GUIDED_PROMPTS:
            return
        label = "Setup review" if session.kind == "coach_setup" else "Mistake review"
        prompts = COACH_GUIDED_PROMPTS[session.kind]
        prompt = "\n".join(
            f"{question}\nMember: {answer}"
            for question, answer in zip(prompts, session.answers)
        )
        self.sessions.pop(telegram_id, None)
        self._answer_coach_message(
            session.chat_id,
            telegram_id,
            session.username,
            f"{label}:\n{prompt}",
        )

    def _start_coach_challenge(
        self,
        telegram_id: int,
        chat_id: int,
        sender: dict[str, Any],
        is_private: bool,
        *,
        daily: bool = False,
    ) -> None:
        if not is_private:
            self._show_coach_menu(chat_id, is_private)
            return
        kind = "coach_daily" if daily else "coach_challenge"
        self.sessions[telegram_id] = Conversation(
            kind=kind,
            chat_id=chat_id,
            username=sender.get("username"),
            first_name=sender.get("first_name"),
        )
        self._send_coach_challenge(telegram_id)

    def _current_coach_challenge(
        self, telegram_id: int, session: Conversation
    ) -> dict[str, Any] | None:
        if session.answers and session.answers[-1].get("pending"):
            pending_id = str(session.answers[-1]["pending"])
            return next(
                (
                    question
                    for question in COACH_CHALLENGES
                    if question["id"] == pending_id
                ),
                None,
            )
        used = {
            str(answer["id"])
            for answer in session.answers
            if answer.get("id")
        }
        remaining = [
            question for question in COACH_CHALLENGES if question["id"] not in used
        ]
        if not remaining:
            return None
        recent = set(self.store.recent_coach_challenge_ids(telegram_id, limit=12))
        fresh = [question for question in remaining if question["id"] not in recent]
        pool = fresh or remaining

        if session.kind == "coach_daily":
            if session.answers:
                return None
            progress = self.store.progress_for(telegram_id)
            weak_topic = str(progress.get("weakest_topic") or "").casefold()
            matching = [
                question
                for question in pool
                if weak_topic and weak_topic in question["topic"].casefold()
            ]
            return random.choice(matching or pool)

        correct = sum(bool(answer["correct"]) for answer in session.answers)
        accuracy = correct / len(session.answers) if session.answers else 0
        target_difficulty = 2 if accuracy >= 0.75 else 1 if accuracy >= 0.5 else 0
        closest = min(
            abs(question["difficulty"] - target_difficulty) for question in pool
        )
        return random.choice(
            [
                question
                for question in pool
                if abs(question["difficulty"] - target_difficulty) == closest
            ]
        )

    def _send_coach_challenge(self, telegram_id: int) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.kind not in {"coach_challenge", "coach_daily"}:
            return
        limit = 1 if session.kind == "coach_daily" else 3
        if len(session.answers) >= limit:
            self._finish_coach_challenge(telegram_id)
            return
        question = self._current_coach_challenge(telegram_id, session)
        if question is None:
            self._finish_coach_challenge(telegram_id)
            return
        if not session.answers or not session.answers[-1].get("pending"):
            session.answers.append({"pending": question["id"]})
            self.store.record_coach_challenge_question(
                telegram_id,
                str(question["id"]),
                "daily" if session.kind == "coach_daily" else "challenge",
            )
        completed = sum("correct" in answer for answer in session.answers)
        rows = [
            [
                {
                    "text": option,
                    "callback_data": (
                        f"coach:{'daily' if session.kind == 'coach_daily' else 'challenge'}:"
                        f"answer:{question['id']}:{index}"
                    ),
                }
            ]
            for index, option in enumerate(question["options"])
        ]
        rows.append(self._nav_row())
        self.api.send_message(
            session.chat_id,
            (
                f"{'Daily Challenge' if session.kind == 'coach_daily' else 'Challenge Me'}"
                f" — {completed + 1}/{limit}\n"
                f"Topic: {question['topic']}\n\n{question['prompt']}"
            ),
            {"inline_keyboard": rows},
        )

    def _handle_coach_challenge_answer(
        self, telegram_id: int, chat_id: int, data: str, is_private: bool
    ) -> None:
        session = self.sessions.get(telegram_id)
        expected_kind = "coach_daily" if data.startswith("coach:daily:") else "coach_challenge"
        match = re.fullmatch(
            r"coach:(?:daily|challenge):answer:([a-z_]+):(\d+)", data
        )
        if (
            not is_private
            or not session
            or session.kind != expected_kind
            or session.chat_id != chat_id
            or not match
        ):
            self._show_coach_menu(chat_id, is_private)
            return
        question = self._current_coach_challenge(telegram_id, session)
        question_id, answer_text = match.groups()
        if not question or question["id"] != question_id:
            self.api.send_message(
                chat_id,
                "That challenge has moved on. Use the current answer buttons.",
                self._coach_keyboard(),
            )
            return
        answer_index = int(answer_text)
        if not 0 <= answer_index < len(question["options"]):
            return
        is_correct = answer_index == question["answer"]
        session.answers[-1] = {
            "id": question_id,
            "correct": is_correct,
            "topic": question["topic"],
        }
        feedback = "That’s right. " if is_correct else "Not quite — that’s okay. "
        feedback += question["explanation"]
        limit = 1 if session.kind == "coach_daily" else 3
        if len(session.answers) == limit:
            score = sum(bool(answer["correct"]) for answer in session.answers)
            self.sessions.pop(telegram_id, None)
            feedback += (
                f"\n\nChallenge complete: {score}/{limit}. "
                "You can try another round whenever you like."
            )
            self.api.send_message(chat_id, feedback, self._coach_menu_keyboard())
            return
        self.api.send_message(chat_id, feedback, self._coach_keyboard())
        self._send_coach_challenge(telegram_id)

    def _finish_coach_challenge(self, telegram_id: int) -> None:
        session = self.sessions.pop(telegram_id, None)
        if not session:
            return
        limit = 1 if session.kind == "coach_daily" else 3
        score = sum(bool(answer.get("correct")) for answer in session.answers)
        self.api.send_message(
            session.chat_id,
            f"Challenge complete: {score}/{limit}. Nice work showing up to practise.",
            self._coach_menu_keyboard(),
        )

    def _answer_coach_message(
        self,
        chat_id: int,
        telegram_id: int,
        username: str | None,
        question: str,
    ) -> None:
        request_id = uuid.uuid4().hex
        logger.info("Coach request received. request_id=%s.", request_id)
        try:
            history = self.store.recent_dm_coaching_interactions(telegram_id)
            profile = self.store.progress_for(telegram_id)
            sunday_plan = self.store.latest_sunday_preparation(telegram_id)
            recent_checkins = self.store.recent_checkins(telegram_id, limit=1)
            if sunday_plan:
                profile["learning_goal"] = (
                    sunday_plan.get("concept_focus")
                    or sunday_plan.get("weekly_goal")
                    or sunday_plan.get("mistake_to_avoid")
                )
            elif recent_checkins:
                profile["learning_goal"] = recent_checkins[0].get("next_focus")
        except Exception:
            logger.exception("Could not load saved coaching context.")
            history = []
            profile = {}
        routed = self.message_router.route(
            telegram_id,
            question,
            history=history,
            profile=profile,
            request_id=request_id,
        )
        reply = routed.reply
        assessment = routed.assessment
        response_text = reply.response

        interaction_id: int | None = None
        question_recorded = False
        try:
            interaction_id = self.store.save_dm_coaching_interaction(
                telegram_id=telegram_id,
                username=username,
                question=question,
                coach_response=response_text,
                detected_topic=reply.detected_topic,
                mistakes_identified=reply.mistakes,
                lesson_learned=reply.lesson_learned,
            )
            response = response_text
        except Exception:
            logger.exception("Could not save a DM coaching interaction.")
            response = (
                response_text
                + "\n\nI couldn't save this coaching interaction locally. "
                "Please try again later."
            )
        if assessment and interaction_id is not None:
            try:
                self.store.record_knowledge_question(
                    question=question,
                    topic=assessment.topic,
                    confidence=assessment.confidence,
                    review_reason=assessment.review_reason,
                    interaction_id=interaction_id,
                )
                question_recorded = True
            except Exception:
                logger.exception("Could not add Coach question to the knowledge queue.")
        markup = (
            self._coach_feedback_keyboard(interaction_id)
            if question_recorded and interaction_id is not None
            else self._coach_keyboard()
        )
        try:
            self.api.send_message(chat_id, response, markup)
        except TelegramAPIError:
            logger.warning("Coach Telegram send failed. request_id=%s.", request_id)
            raise
        logger.info(
            "Coach reply sent to Telegram (path=%s). request_id=%s.",
            routed.response_path,
            request_id,
        )

    def _handle_coach_feedback(
        self,
        chat_id: int,
        telegram_id: int,
        is_private: bool,
        interaction_id: int,
        reaction: str,
    ) -> None:
        if not is_private:
            self.api.send_message(
                chat_id,
                "Please send Coach feedback in your private chat with the bot.",
                self._coach_keyboard(),
            )
            return
        try:
            recorded = self.store.record_knowledge_feedback(
                telegram_id, interaction_id, reaction
            )
        except Exception:
            logger.exception("Could not save member feedback on Coach answer.")
            recorded = False
        if not recorded:
            self.api.send_message(
                chat_id,
                "I couldn't match that button to your recent Coach question.",
                self._coach_keyboard(),
            )
            return
        messages = {
            "helpful": "Thanks for the feedback. I’ll keep this reviewed explanation available.",
            "unhelpful": "Thanks for telling me. I’ve flagged this answer for administrator review.",
            "unclear": "Thanks for letting me know. I’ve flagged it for a clearer explanation.",
        }
        self.api.send_message(chat_id, messages[reaction], self._coach_keyboard())

    @staticmethod
    def _coach_feedback_keyboard(interaction_id: int) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "✅ Helpful", "callback_data": f"coach:feedback:{interaction_id}:helpful"},
                    {"text": "👎 Not helpful", "callback_data": f"coach:feedback:{interaction_id}:unhelpful"},
                    {"text": "❓ Still unclear", "callback_data": f"coach:feedback:{interaction_id}:unclear"},
                ],
                [{"text": "Coaching Modes", "callback_data": "menu:coach"}],
                [{"text": "🏠 Main Menu", "callback_data": "nav:home"}],
            ]
        }

    @staticmethod
    def _coach_keyboard() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": "Coaching Modes", "callback_data": "menu:coach"}],
                [{"text": "🏠 Main Menu", "callback_data": "nav:home"}],
            ]
        }

    def _show_welcome(self, chat_id: int, first_name: str | None) -> None:
        greeting = f" {first_name}" if first_name else ""
        self.api.send_message(
            chat_id,
            (
                f"Welcome{greeting} to Smart Money Hub.\n\n"
                "I can help you learn SMC, test your knowledge, journal trades, "
                "ask the DM Coach, review mistakes, track discipline, prepare for the trading week, "
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
            potential_issues.append("You recorded no retest; check whether your entry model required one.")
        if not data["followed_plan"]:
            potential_issues.append("You noted that the written plan was not followed.")
        if not data["liquidity_swept"]:
            potential_issues.append("No liquidity sweep was recorded; consider whether it mattered to your setup.")
        lines.append("\nPotential issue:")
        lines.extend(potential_issues or ["No process issue was reported in this entry."])
        lines.append("\nReminder: Follow the confirmation and retest rules of your chosen entry model. Do not chase a missed setup.")
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
            "Follow your chosen entry model's confirmation and retest rules. Do not chase a missed setup."
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
        weekly_enabled = self.store.reminders_enabled(telegram_id)
        reminders_stopped = self.store.reminders_stopped(telegram_id)
        weekly_state = "On" if weekly_enabled else "Off"
        all_state = "Stopped" if reminders_stopped else "Active"
        settings_rows = []
        if not reminders_stopped:
            settings_rows.append(
                [
                    {
                        "text": (
                            "Turn Sunday check-in off"
                            if weekly_enabled
                            else "Turn Sunday check-in on"
                        ),
                        "callback_data": "reminders:weekly:toggle",
                    }
                ]
            )
        settings_rows.append(
            [
                {
                    "text": (
                        "Resume all scheduled reminders"
                        if reminders_stopped
                        else "Stop all scheduled reminders"
                    ),
                    "callback_data": (
                        "reminders:on" if reminders_stopped else "reminders:off"
                    ),
                }
            ]
        )
        self.api.send_message(
            chat_id,
            f"Weekly Sunday check-in: {weekly_state} — "
            f"{self.reminder_time.strftime('%H:%M')} ({self.reminder_zone.key}).\n"
            f"Zoom class check-ins: Automatic — Monday and Thursday at "
            f"{CLASS_REMINDER_TIME.strftime('%H:%M')} and "
            f"{CLASS_START_TIME.strftime('%H:%M')} "
            f"({self.reminder_zone.key}).\n"
            f"All scheduled reminders: {all_state}.\n\n"
            "Only members who have started the bot in a private chat receive DMs. "
            "Use /stop to turn all scheduled reminders off.",
            self._menu_keyboard(settings_rows),
        )

    def _change_reminder_setting(
        self, chat_id: int, telegram_id: int, is_private: bool, action: str
    ) -> None:
        if action in {"reminders:on", "reminders:off"}:
            enabled = action == "reminders:on"
            if enabled and not is_private:
                self._reminder_private_chat_required(chat_id)
                return
            self.store.set_reminders_stopped(telegram_id, not enabled)
            if enabled:
                self.store.set_reminders_enabled(telegram_id, True)
            self._show_reminder_settings(chat_id, telegram_id)
            return

        if action == "reminders:class:toggle":
            self.api.send_message(
                chat_id,
                "Zoom class check-ins are sent automatically to members who have "
                "started a private chat. Use /stop to turn off all scheduled reminders.",
                self._nav_keyboard(),
            )
            return

        reminder_setting = (
            "class"
            if action == "reminders:class:toggle"
            else "weekly"
        )
        current = (
            self.store.class_reminders_enabled(telegram_id)
            if reminder_setting == "class"
            else self.store.reminders_enabled(telegram_id)
        )
        enabled = not current
        if enabled and not is_private:
            self._reminder_private_chat_required(chat_id)
            return
        saved = (
            self.store.set_class_reminders_enabled(telegram_id, enabled)
            if reminder_setting == "class"
            else self.store.set_reminders_enabled(telegram_id, enabled)
        )
        if not saved:
            self.api.send_message(
                chat_id,
                "Open this bot in a private chat and send /start before enabling reminders.",
                self._nav_keyboard(),
            )
            return
        self._show_reminder_settings(chat_id, telegram_id)

    def _reminder_private_chat_required(self, chat_id: int) -> None:
        self.api.send_message(
            chat_id,
            "Open this bot in a private chat and send /start before enabling reminders.",
            self._nav_keyboard(),
        )

    def _dispatch_due_reminders(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        local_now = current.astimezone(self.reminder_zone)
        if (
            local_now.weekday() == 6
            and local_now.time().replace(tzinfo=None) >= self.reminder_time
        ):
            self._dispatch_weekly_checkin(local_now)

        class_day = CLASS_REMINDER_WEEKDAYS.get(local_now.weekday())
        if class_day:
            self._dispatch_class_reminders(local_now, class_day)

    def _dispatch_weekly_checkin(self, local_now: datetime) -> None:
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
                    "🧠 Sunday Check-In — how is your trading going?\n\n"
                    "Take a moment to review your week or prepare your plan.",
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
                self._handle_reminder_send_error(telegram_id, error)
                continue
            self.store.record_reminder_sent(
                telegram_id, "weekly_sunday", schedule_key
            )

    def _dispatch_class_reminders(
        self, local_now: datetime, class_day: str
    ) -> None:
        for reminder_time, reminder_type, message in (
            (
                CLASS_REMINDER_TIME,
                "zoom_class_one_hour",
                f"SMART MONEY HUB\n"
                f"{class_day.upper()} ZOOM CLASS\n"
                f"Your class begins in one hour, at 8:00 PM "
                f"({self.reminder_zone.key}).\n"
                "The Zoom link will be available in the channel.",
            ),
            (
                CLASS_START_TIME,
                "zoom_class_start",
                f"SMART MONEY HUB\n"
                f"{class_day.upper()} ZOOM CLASS IS STARTING NOW\n"
                "The Zoom link will be available in the channel.",
            ),
        ):
            scheduled_at = datetime.combine(
                local_now.date(), reminder_time, tzinfo=self.reminder_zone
            )
            if not scheduled_at <= local_now <= scheduled_at + CLASS_REMINDER_GRACE:
                continue
            schedule_key = f"{local_now.date().isoformat()}:{reminder_time:%H%M}"
            for member in self.store.class_reminder_recipients():
                telegram_id = int(member["telegram_id"])
                if self.store.reminder_was_sent(
                    telegram_id, reminder_type, schedule_key
                ):
                    continue
                try:
                    self.api.send_message(
                        int(member["chat_id"]),
                        message,
                        {
                            "inline_keyboard": [
                                [{"text": "Stop All Reminders", "callback_data": "reminders:off"}]
                            ]
                        },
                    )
                except TelegramAPIError as error:
                    self._handle_reminder_send_error(telegram_id, error)
                    continue
                self.store.record_reminder_sent(
                    telegram_id, reminder_type, schedule_key
                )

    def _handle_reminder_send_error(
        self, telegram_id: int, error: TelegramAPIError
    ) -> None:
        if any(part in str(error).casefold() for part in BLOCKED_CHAT_ERRORS):
            self.store.set_reminders_stopped(telegram_id, True)
            logger.info("Disabled reminders for a Telegram chat that is unavailable.")
        else:
            logger.warning("Could not send a scheduled reminder: %s", error)

    def _go_back(self, telegram_id: int, chat_id: int) -> None:
        session = self.sessions.get(telegram_id)
        if not session or session.chat_id != chat_id:
            self._show_main_menu(chat_id)
            return
        if session.kind in COACH_GUIDED_PROMPTS:
            if session.answers:
                session.answers.pop()
                self._ask_guided_coach_question(telegram_id)
            else:
                self.sessions.pop(telegram_id, None)
                self._show_coach_menu(chat_id, True)
            return
        if session.kind in {"coach_challenge", "coach_daily"}:
            self.sessions.pop(telegram_id, None)
            self._show_coach_menu(chat_id, True)
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