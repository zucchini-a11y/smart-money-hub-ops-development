import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from smart_money_hub_bot.bot import SmartMoneyHubBot
from smart_money_hub_bot.coach import RuleBasedCoachService
from smart_money_hub_bot.grading import RuleBasedWrittenAnswerEvaluator
from smart_money_hub_bot.questions import QUESTIONS, validate_questions
from smart_money_hub_bot.scoring import grade_answers
from smart_money_hub_bot.storage import Repository
from smart_money_hub_bot.telegram_api import TelegramAPIError


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []
        self.webhook_info: dict[str, Any] = {}
        self.callback_ack_error: TelegramAPIError | None = None

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
        if self.callback_ack_error:
            raise self.callback_ack_error
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


class CoachTests(unittest.TestCase):
    def setUp(self) -> None:
        self.coach = RuleBasedCoachService()

    def test_choch_answer_teaches_then_checks_understanding(self) -> None:
        reply = self.coach.evaluate("What is CHOCH?")

        self.assertEqual(reply.detected_topic, "CHoCH")
        self.assertIn("Change of Character", reply.response)
        self.assertIn("does not guarantee a reversal", reply.response)
        self.assertIn("Which swing level broke", reply.response)

    def test_fvg_entry_without_waiting_for_context_flags_possible_mistake(self) -> None:
        reply = self.coach.evaluate("I saw an FVG and entered immediately.")

        self.assertEqual(reply.detected_topic, "FVG / IFVG")
        self.assertIn("not an entry confirmation", reply.response)
        self.assertIn("Did price take SSL/BSL", reply.response)
        self.assertIn(
            "Entered at an FVG without clear confirmation", reply.mistakes
        )

    def test_stop_out_review_identifies_reported_process_gaps(self) -> None:
        prompt = self.coach.evaluate("I got stopped out.")
        self.assertIn("What was your POI?", prompt.response)
        self.assertIn("Did you follow your plan?", prompt.response)

        reply = self.coach.evaluate(
            "POI: 15m bearish FVG\n"
            "Timeframe: 5m\n"
            "Liquidity: BSL swept\n"
            "Confirmation: none\n"
            "Retest: no\n"
            "Stop loss: above swing\n"
            "Followed plan: no"
        )
        self.assertIn("Entry was taken without confirmation", reply.mistakes)
        self.assertIn("Entry was taken before a retest", reply.mistakes)
        self.assertIn("The written plan was not followed", reply.mistakes)
        self.assertIn("possible process issues", reply.response)


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
        self.assertEqual(menu[1][0]["text"], "💬 Ask Coach")
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

    def test_expired_callback_acknowledgement_does_not_drop_the_action(self) -> None:
        self.api.callback_ack_error = TelegramAPIError(
            "Bad Request: query is too old and response timeout expired"
        )
        self._click("menu:progress")
        self.assertIn("SMART MONEY HUB PROGRESS", self.api.messages[-1]["text"])

    def test_dm_coach_saves_interactions_and_shows_private_admin_statistics(self) -> None:
        self._message("/start")
        self._click("menu:coach")
        self.assertIn("Ask Coach is on", self.api.messages[-1]["text"])

        self._text("What is CHOCH?")
        self.assertIn("Change of Character", self.api.messages[-1]["text"])
        self._text("What is CHOCH?")
        self._text("I saw an FVG and entered immediately.")
        self.assertIn("No confirmation, no entry.", self.api.messages[-1]["text"])

        stats = Repository(self.database_path).admin_dm_coach_stats()
        self.assertEqual(stats["members_using_coach"], 1)
        self.assertEqual(stats["total_interactions"], 3)
        self.assertEqual(stats["common_questions"][0]["question"], "What is CHOCH?")
        self.assertEqual(stats["common_questions"][0]["occurrences"], 2)
        self.assertEqual(stats["weak_topics"][0]["topic"], "FVG / IFVG")
        self.assertIn(
            "Entered at an FVG without clear confirmation",
            [item["mistake"] for item in stats["common_mistakes"]],
        )
        self.assertEqual(stats["recent_activity"][0]["username"], self.username)

        connection = sqlite3.connect(self.database_path)
        try:
            saved = connection.execute(
                """
                SELECT telegram_id, username, question, detected_topic,
                       mistakes_identified, lesson_learned
                FROM dm_coaching_interactions
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(saved[0:4], (
            self.user_id,
            self.username,
            "I saw an FVG and entered immediately.",
            "FVG / IFVG",
        ))
        self.assertIn("Entered at an FVG", saved[4])
        self.assertTrue(saved[5])

        # Coaching stays private; messages in group chats are not stored.
        self._message(
            "What is CHOCH?",
            user_id=909090,
            chat_id=-100909090,
            chat_type="supergroup",
        )
        self.assertIn("DM Coach is private", self.api.messages[-1]["text"])
        self.assertEqual(
            Repository(self.database_path).admin_dm_coach_stats()["total_interactions"],
            3,
        )

        self.bot.admin_id = self.user_id
        self.bot.admin_dashboard.admin_id = self.user_id
        self._message("/admin")
        labels = {
            button["text"]
            for row in self.api.messages[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        }
        self.assertIn("💬 DM Coach Stats", labels)
        self._click("admin:dm_coach")
        dashboard = self.api.messages[-1]["text"]
        for expected in (
            "DM COACH STATISTICS",
            "Members using coach: 1",
            "Most common questions:",
            "Most common weak SMC topics:",
            "Most common trading mistakes:",
            "Recent coaching activity:",
            "What is CHOCH?",
        ):
            self.assertIn(expected, dashboard)

        self._callback(
            "admin:dm_coach",
            sender_id=self.user_id + 1,
            chat_id=self.user_id + 1,
        )
        self.assertIn("restricted", self.api.messages[-1]["text"])

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
        self.bot.admin_dashboard.admin_id = self.user_id
        self._message("/admin")
        self.assertIn("SMART MONEY HUB — ADMIN DASHBOARD", self.api.messages[-1]["text"])
        self.assertIn("Total registered members: 1", self.api.messages[-1]["text"])
        button_labels = {
            button["text"]
            for row in self.api.messages[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        }
        self.assertTrue(
            {
                "👥 All Members",
                "📊 Statistics",
                "📚 Weak Topics",
                "📒 Trade Journals",
                "🔍 Search Member",
                "📈 Member Progress",
            }.issubset(button_labels)
        )

        self._callback("admin:open", sender_id=self.user_id + 1, chat_id=self.chat_id + 1)
        self.assertIn("restricted", self.api.messages[-1]["text"])

    def test_admin_dashboard_records_are_private_and_persist_across_reopen(self) -> None:
        admin_id = self.user_id
        member_id = 770077
        low_score_id = 880088
        self.bot.admin_id = admin_id
        self.bot.admin_dashboard.admin_id = admin_id
        self.bot.store.register_user(
            telegram_id=member_id,
            username="tayo_trades",
            first_name="Tayo",
            chat_id=member_id,
            is_private=True,
        )
        self.bot.store.register_user(
            telegram_id=low_score_id,
            username="low_score",
            first_name="Low",
            chat_id=low_score_id,
            is_private=True,
        )

        member_answers = [question.correct_index for question in QUESTIONS]
        member_answers[2] = (member_answers[2] + 1) % 4
        self.bot.store.save_assessment(
            member_id, "tayo_trades", grade_answers(member_answers)
        )
        self.bot.store.save_assessment(
            low_score_id,
            "low_score",
            grade_answers(
                [(question.correct_index + 1) % 4 for question in QUESTIONS]
            ),
        )
        trade_id = self.bot.store.save_trade(
            member_id,
            {
                "asset": "EURUSD",
                "direction": "Buy",
                "poi": "Bullish FVG",
                "timeframe": "15m",
                "confirmation": "MSS",
                "liquidity_swept": True,
                "waited_for_retest": True,
                "stop_loss": "1.0800",
                "take_profit": "1.0900",
                "partial_profit": True,
                "moved_sl_to_be": False,
                "result": "Win",
                "followed_plan": True,
                "mistake": "Chased entry",
                "lesson": "Wait for a retest",
            },
            "Trade review summary",
        )
        self.bot.store.save_weekly_checkin(
            member_id,
            {
                "trades_taken": 2,
                "winners": 1,
                "losses": 1,
                "followed_plan": True,
                "entered_without_confirmation": False,
                "chased_missed_trade": False,
                "moved_sl_unnecessarily": False,
                "secured_partials": True,
                "biggest_mistake": "Chased entry",
                "next_focus": "Wait for the retest",
            },
            "Weekly summary",
        )

        # Reopening the existing SQLite database must retain all member records.
        reopened = Repository(self.database_path)
        saved_detail = reopened.admin_member_detail(member_id)
        self.assertIsNotNone(saved_detail)
        self.assertEqual(saved_detail["trade_total"], 1)
        self.assertEqual(saved_detail["wins"], 1)
        self.assertEqual(len(saved_detail["assessment_history"]), 1)
        self.assertEqual(len(saved_detail["weekly_checkins"]), 1)

        self._message("/admin")
        self.assertIn("Latest score below 60%: 1 members", self.api.messages[-1]["text"])
        self._click("admin:statistics")
        self.assertIn("Top-performing members", self.api.messages[-1]["text"])
        self.assertIn("Tayo", self.api.messages[-1]["text"])
        self.assertIn("Low", self.api.messages[-1]["text"])
        self._click("admin:weak_topics")
        self.assertIn(QUESTIONS[2].topic, self.api.messages[-1]["text"])
        self._click("admin:members")
        self.assertTrue(
            any(
                button["callback_data"] == f"admin:member:{member_id}"
                for row in self.api.messages[-1]["reply_markup"]["inline_keyboard"]
                for button in row
            )
        )
        self._click(f"admin:member:{member_id}")
        profile = self.api.messages[-1]["text"]
        for expected in (
            "@tayo_trades",
            "First name: Tayo",
            "Average score:",
            "Strong topics:",
            "Weak topics:",
            "Trades journaled: 1",
            "1 wins, 0 losses",
            "Chased entry",
            "Weekly check-in history",
            "Wait for the retest",
        ):
            self.assertIn(expected, profile)

        self._click("admin:member_trades:{}:0".format(member_id))
        trade_page = self.api.messages[-1]
        self.assertIn("1 entries", trade_page["text"])
        self.assertTrue(
            any(
                "EURUSD" in button["text"]
                for row in trade_page["reply_markup"]["inline_keyboard"]
                for button in row
            )
        )
        self._click(f"admin:trade:{trade_id}")
        self.assertIn("Wait for a retest", self.api.messages[-1]["text"])
        self._click("admin:search")
        self._message("tayo_trades")
        self.assertIn("Search results", self.api.messages[-1]["text"])

        # A regular member cannot read a page even if they forge its callback data.
        self._callback(
            "admin:member:{}".format(member_id),
            sender_id=member_id,
            chat_id=member_id,
        )
        self.assertIn("restricted", self.api.messages[-1]["text"])
        self.assertNotIn("Tayo", self.api.messages[-1]["text"])
        # The authorized admin is also refused in a group chat.
        self._callback(
            "admin:statistics",
            sender_id=admin_id,
            chat_id=-100123,
            chat_type="supergroup",
        )
        self.assertIn("private chat", self.api.messages[-1]["text"])

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
        self,
        text: str,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        chat_type: str = "private",
    ) -> None:
        member = user_id if user_id is not None else self.user_id
        private_chat = chat_id if chat_id is not None else (
            self.chat_id if member == self.user_id else member
        )
        self.bot.handle_update(
            {
                "message": {
                    "text": text,
                    "chat": {"id": private_chat, "type": chat_type},
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

    def _callback(
        self,
        data: str,
        *,
        sender_id: int,
        chat_id: int,
        chat_type: str = "private",
    ) -> None:
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
                        "chat": {"id": chat_id, "type": chat_type},
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