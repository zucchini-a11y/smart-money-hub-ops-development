import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from smart_money_hub_bot.bot import (
    BOT_RECOVERY_NOTICES,
    BOT_RECOVERY_NOTICE_AFTER_SECONDS,
    POLLING_HEARTBEAT_INTERVAL_SECONDS,
    SmartMoneyHubBot,
)
from smart_money_hub_bot.admin_dashboard import CHANNEL_PROMO_TEXT, CHANNEL_PROMO_URL
from smart_money_hub_bot.coach import RuleBasedCoachService
from smart_money_hub_bot.economic_calendar_phase1 import (
    OfficialCalendarRepository,
    parse_bea_release_dates,
)
from smart_money_hub_bot.grading import RuleBasedWrittenAnswerEvaluator
from smart_money_hub_bot.questions import QUESTIONS, validate_questions
from smart_money_hub_bot.scoring import grade_answers
from smart_money_hub_bot.storage import Repository
from smart_money_hub_bot.telegram_api import TelegramAPIError


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.polls: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []
        self.chat_actions: list[dict[str, Any]] = []
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
        *,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
    ) -> None:
        message = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        if parse_mode is not None:
            message["parse_mode"] = parse_mode
        if message_thread_id is not None:
            message["message_thread_id"] = message_thread_id
        self.messages.append(message)

    def send_chat_action(
        self,
        chat_id: int,
        action: str = "typing",
        *,
        message_thread_id: int | None = None,
    ) -> None:
        chat_action = {"chat_id": chat_id, "action": action}
        if message_thread_id is not None:
            chat_action["message_thread_id"] = message_thread_id
        self.chat_actions.append(chat_action)

    def send_poll(
        self,
        chat_id: int,
        question: str,
        options: list[str],
        correct_option_id: int,
        explanation: str,
        *,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        poll = {
            "chat_id": chat_id,
            "question": question,
            "options": options,
            "correct_option_id": correct_option_id,
            "explanation": explanation,
        }
        if message_thread_id is not None:
            poll["message_thread_id"] = message_thread_id
        self.polls.append(poll)
        return {
            "message_id": len(self.polls),
            "date": 1_797_000_000,
            "poll": {
                "id": f"synthetic-poll-{len(self.polls)}",
                "question": question,
                "options": [{"text": option} for option in options],
                "correct_option_id": correct_option_id,
                "explanation": explanation,
            },
        }

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


class StrictTelegramHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open_tags: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"b", "code"}:
            self.errors.append(f"unsupported tag: {tag}")
        else:
            self.open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.open_tags or self.open_tags[-1] != tag:
            self.errors.append(f"unbalanced tag: {tag}")
        else:
            self.open_tags.pop()


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
        self.assertIn("Which confirmation does your chosen entry model require", reply.response)
        self.assertLessEqual(len(reply.response), 450)

    def test_fvg_entry_without_waiting_for_context_flags_possible_mistake(self) -> None:
        reply = self.coach.evaluate("I saw an FVG and entered immediately.")

        self.assertEqual(reply.detected_topic, "FVG / IFVG")
        self.assertIn("not an entry confirmation", reply.response)
        self.assertIn("Did price take liquidity", reply.response)
        self.assertIn(
            "Entered at an FVG without clear confirmation", reply.mistakes
        )

    def test_stop_out_review_identifies_reported_process_gaps(self) -> None:
        prompt = self.coach.evaluate("I got stopped out.")
        self.assertIn("that’s frustrating", prompt.response)
        self.assertIn("Did you follow your plan", prompt.response)
        self.assertEqual(prompt.response.count("?"), 1)

        reply = self.coach.evaluate(
            "POI: 15m bearish FVG\n"
            "Timeframe: 5m\n"
            "Entry: taken\n"
            "Liquidity: BSL swept\n"
            "Confirmation: none\n"
            "Retest: no\n"
            "Stop loss: above swing\n"
            "Followed plan: no\n"
            "My entry model requires a retest"
        )
        self.assertIn("Entry was taken without confirmation", reply.mistakes)
        self.assertIn("Entry was taken before a retest", reply.mistakes)
        self.assertIn("The written plan was not followed", reply.mistakes)
        self.assertIn("possible process issues", reply.response)
        self.assertIn("confirmation as absent", reply.response)
        self.assertIn("specific trigger", reply.response)
        self.assertIn("retest required by your stated model", reply.response)

    def test_hypothetical_choch_scenario_uses_given_facts_without_trade_verdict(self) -> None:
        scenario = (
            "Hypothetically, Gold has a bearish H1 bias. On M5, price sweeps BSL, "
            "closes below the prior higher low with bearish displacement, then "
            "retests that level. I have not entered. Explain whether this is a CHOCH, "
            "what displacement and the retest add, where invalidation and the stop "
            "belong, and how to assess risk and planned R:R."
        )

        reply = self.coach.evaluate(scenario)

        self.assertEqual(
            self.coach.classify_request_context(scenario), "hypothetical_scenario"
        )
        self.assertEqual(reply.detected_topic, "CHoCH")
        self.assertEqual(reply.mistakes, ())
        self.assertIn("Hypothetical walkthrough", reply.response)
        self.assertIn("M5 liquidity sweep", reply.response)
        self.assertIn("Displacement", reply.response)
        self.assertIn("not mandatory for every model", reply.response)
        self.assertIn("H1 context", reply.response)
        self.assertIn("2% risk per trade", reply.response)
        self.assertIn("minimum 1:3 planned R:R", reply.response)
        self.assertIn("maximum 3% daily loss", reply.response)
        self.assertIn("break-even at 1:1 R:R", reply.response)
        self.assertNotIn("Which swing level broke", reply.response)
        self.assertNotIn("possible process issues", reply.response)

    def test_missing_confirmation_is_not_a_trade_mistake_without_a_reported_entry(self) -> None:
        reply = self.coach.evaluate(
            "POI: 15m bearish FVG\n"
            "Confirmation: none\n"
            "Retest: no\n"
            "Stop loss: above swing\n"
            "I took notes about the setup"
        )

        self.assertNotIn("Entry was taken without confirmation", reply.mistakes)
        self.assertNotIn("Entry was taken before a retest", reply.mistakes)

    def test_missing_confirmation_is_flagged_for_reported_entry_without_retest_plan(self) -> None:
        reply = self.coach.evaluate(
            "POI: 15m bearish FVG\n"
            "Entry: taken\n"
            "Confirmation: none\n"
            "Retest: no"
        )

        self.assertIn("Entry was taken without confirmation", reply.mistakes)
        self.assertNotIn("Entry was taken before a retest", reply.mistakes)

    def test_missing_retest_requires_entry_and_explicit_model_requirement(self) -> None:
        required = self.coach.evaluate(
            "POI: 15m bearish FVG\n"
            "Entry: taken\n"
            "Confirmation: yes\n"
            "Retest: no\n"
            "My entry model requires a retest"
        )
        no_model_requirement = self.coach.evaluate(
            "POI: 15m bearish FVG\n"
            "Entry: taken\n"
            "Confirmation: yes\n"
            "Retest: no"
        )
        no_entry = self.coach.evaluate(
            "POI: 15m bearish FVG\n"
            "Confirmation: yes\n"
            "Retest: no\n"
            "My entry model requires a retest"
        )

        self.assertIn("Entry was taken before a retest", required.mistakes)
        self.assertNotIn("Entry was taken before a retest", no_model_requirement.mistakes)
        self.assertNotIn("Entry was taken before a retest", no_entry.mistakes)

    def test_request_context_distinguishes_real_trade_and_live_analysis(self) -> None:
        self.assertEqual(
            self.coach.classify_request_context("I entered Gold before confirmation."),
            "real_trade_review",
        )
        self.assertEqual(
            self.coach.classify_request_context("What is Gold doing right now?"),
            "live_market_analysis",
        )

    def test_coach_replies_to_greetings_wins_entries_and_unrelated_requests(self) -> None:
        greeting = self.coach.evaluate("Hey bro")
        self.assertIn("Yoo!", greeting.response)
        self.assertEqual(greeting.detected_topic, "Conversation")

        liquidity = self.coach.evaluate("What is liquidity?")
        self.assertIn("obvious highs and lows", liquidity.response)
        self.assertNotIn("HTF context and POI", liquidity.response)

        win = self.coach.evaluate("Gold hit my TP today!")
        self.assertIn("Nice one", win.response)
        self.assertEqual(win.response.count("?"), 1)

        entry = self.coach.evaluate("Should I buy Gold now?")
        self.assertIn("I can’t see live prices", entry.response)
        self.assertEqual(entry.response.count("?"), 1)

        unrelated = self.coach.evaluate("What is the weather today?")
        self.assertIn("I don’t have reliable information", unrelated.response)
        self.assertNotIn("No confirmation, no entry", unrelated.response)

    def test_coach_continues_from_member_history_and_personalizes_weak_topic(self) -> None:
        follow_up = self.coach.evaluate(
            "The 15m high.",
            history=[{"detected_topic": "CHoCH", "mistakes_identified": ""}],
        )
        self.assertIn("Got it", follow_up.response)
        self.assertIn("CHoCH", follow_up.detected_topic)

        personalized = self.coach.evaluate(
            "What is CHOCH?",
            profile={"latest_assessment_score": 4, "weakest_topic": "CHoCH"},
        )
        self.assertIn("Let’s keep it simple", personalized.response)
        self.assertIn("one of your current review topics", personalized.response)

        focused = self.coach.evaluate(
            "What is liquidity?",
            profile={"learning_goal": "Practise liquidity sweeps this week"},
        )
        self.assertIn("connects to your current focus", focused.response)


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

    def test_daily_education_morning_publisher_uses_existing_scheduler_tick(self) -> None:
        now = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)
        self.bot.education_polls.dispatch_due = Mock()
        self.bot.education_morning.dispatch_due = Mock()
        self.bot._dispatch_due_reminders(now)
        self.bot.education_polls.dispatch_due.assert_called_once_with(now)
        self.bot.education_morning.dispatch_due.assert_called_once_with(now)

    def test_daily_brief_recovery_callback_requires_admin_private_chat(self) -> None:
        publisher = Mock()
        self.bot.daily_calendar_brief = publisher
        self.bot.admin_id = self.user_id + 1

        self.bot._handle_daily_brief_callback(
            "dailybrief:review",
            chat_id=self.user_id,
            telegram_id=self.user_id,
            is_private=True,
        )

        publisher.prepare_held_review.assert_not_called()
        self.assertIn("restricted to the admin", self.api.messages[-1]["text"])

        self.bot.admin_id = self.user_id
        publisher.prepare_held_review.return_value = ("not_recoverable:skipped", None)
        self.bot._handle_daily_brief_callback(
            "dailybrief:review",
            chat_id=self.user_id,
            telegram_id=self.user_id,
            is_private=True,
        )
        self.assertIn("will not be sent late", self.api.messages[-1]["text"])
        publisher.prepare_held_review.assert_called_once_with()
        publisher.publish_reviewed.assert_not_called()

    def test_only_configured_market_analysis_channel_posts_are_archived(self) -> None:
        channel_id = -1004481197912
        bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            main_channel_id=channel_id,
        )
        post_date = int(datetime(2026, 10, 24, 9, tzinfo=timezone.utc).timestamp())
        bot.handle_update(
            {
                "channel_post": {
                    "chat": {"id": channel_id, "type": "channel"},
                    "message_id": 55,
                    "date": post_date,
                    "text": "A channel education post.",
                }
            }
        )
        bot.handle_update(
            {
                "channel_post": {
                    "chat": {"id": -1009999999999, "type": "channel"},
                    "message_id": 56,
                    "date": post_date,
                    "text": "A post from an unrelated destination.",
                }
            }
        )
        bot.handle_update(
            {
                "edited_channel_post": {
                    "chat": {"id": channel_id, "type": "channel"},
                    "message_id": 55,
                    "date": post_date,
                    "text": "The corrected channel education post.",
                }
            }
        )

        history = bot.store.get_recent_channel_post_contents(chat_id=channel_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "The corrected channel education post.")
        self.assertEqual(history[0]["source"], "channel")

    def test_content_overview_reflects_saved_auto_publish_setting(self) -> None:
        repository = self.bot.admin_dashboard.community_content.repository
        repository.set_setting("auto_publish_enabled", "1")
        self.bot.admin_dashboard._show_content_overview(self.user_id)
        self.assertIn(
            "Automatic publishing: ENABLED",
            self.api.messages[-1]["text"],
        )

        repository.set_setting("auto_publish_enabled", "0")
        self.bot.admin_dashboard._show_content_overview(self.user_id)
        self.assertIn(
            "Automatic publishing: DISABLED",
            self.api.messages[-1]["text"],
        )

    def test_group_id_command_sends_details_only_to_configured_admin(self) -> None:
        admin_id = 987654321
        group_id = -1001234567890
        bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=admin_id,
        )

        bot.handle_update(
            {
                "message": {
                    "text": "/groupid@SmartMoneyHubSignalsBot",
                    "chat": {
                        "id": group_id,
                        "type": "supergroup",
                        "title": "Smart Money Hub Education",
                        "is_forum": True,
                    },
                    "message_thread_id": 876543,
                    "from": {"id": admin_id},
                }
            }
        )

        self.assertEqual(len(self.api.messages), 1)
        self.assertEqual(self.api.messages[0]["chat_id"], admin_id)
        self.assertIn("Smart Money Hub Education", self.api.messages[0]["text"])
        self.assertIn(f"Group ID: {group_id}", self.api.messages[0]["text"])
        self.assertIn("Forum topic ID: 876543", self.api.messages[0]["text"])
        self.assertNotEqual(self.api.messages[0]["chat_id"], group_id)

    def test_group_id_command_requests_exact_topic_when_forum_thread_missing(self) -> None:
        admin_id = 987654321
        bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=admin_id,
        )

        bot.handle_update(
            {
                "message": {
                    "text": "/groupid",
                    "chat": {
                        "id": -1001234567890,
                        "type": "supergroup",
                        "title": "Smart Money Hub Education",
                        "is_forum": True,
                    },
                    "from": {"id": admin_id},
                }
            }
        )

        self.assertEqual(self.api.messages[0]["chat_id"], admin_id)
        self.assertIn(
            "not detected. Send /groupid inside the Announcements topic",
            self.api.messages[0]["text"],
        )

    def test_ordinary_message_in_education_group_does_not_show_a_menu(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "message_id": 9001,
                    "text": "Good morning everyone",
                    "chat": {
                        "id": -1003916437804,
                        "type": "supergroup",
                    },
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertEqual(self.api.messages, [])
        archived = self.bot.store.search_education_group_posts(
            -1003916437804, "good morning"
        )
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["content"], "Good morning everyone")

    def test_edited_group_post_updates_the_archive_in_place(self) -> None:
        group_id = -1003916437804
        self.bot.handle_update(
            {
                "message": {
                    "message_id": 9002,
                    "text": "An initial FVG lesson.",
                    "chat": {"id": group_id, "type": "supergroup"},
                    "from": {"id": self.user_id},
                }
            }
        )
        self.bot.handle_update(
            {
                "edited_message": {
                    "message_id": 9002,
                    "text": "The corrected FVG lesson.",
                    "chat": {"id": group_id, "type": "supergroup"},
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertEqual(
            self.bot.store.search_education_group_posts(group_id, "corrected FVG")[0][
                "content"
            ],
            "The corrected FVG lesson.",
        )
        self.assertEqual(
            self.bot.store.search_education_group_posts(group_id, "initial"), []
        )

    def test_explicit_menu_command_still_works_in_education_group(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "text": " MAIN MENU ",
                    "chat": {
                        "id": -1003916437804,
                        "type": "supergroup",
                    },
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertEqual(len(self.api.messages), 1)
        self.assertEqual(self.api.messages[0]["text"], "Choose an option:")
        self.assertIsNotNone(self.api.messages[0]["reply_markup"])

    def test_group_help_explains_opt_in_topic_commands(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "text": "/help",
                    "chat": {
                        "id": -1003916437804,
                        "type": "supergroup",
                    },
                    "message_thread_id": 7654,
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertEqual(len(self.api.messages), 1)
        self.assertIn("/ask What is a liquidity sweep?", self.api.messages[0]["text"])
        self.assertIn("@SmartMoneyHubSignalsBot", self.api.messages[0]["text"])
        self.assertIn("/scenario", self.api.messages[0]["text"])
        self.assertEqual(self.api.messages[0]["message_thread_id"], 7654)
        self.assertIsNone(self.api.messages[0]["reply_markup"])

    def test_natural_mentioned_question_uses_relevant_group_archive(self) -> None:
        group_id = -1003916437804
        self.bot.handle_update(
            {
                "message": {
                    "message_id": 70,
                    "text": "BOS is a break of a meaningful swing high or low.",
                    "chat": {"id": group_id, "type": "supergroup"},
                    "message_thread_id": 7654,
                    "from": {"id": 456789},
                }
            }
        )
        routed = Mock(
            reply=Mock(
                response="A BOS is a break of meaningful structure.",
                requires_review=False,
            ),
            assessment=None,
            response_path="gemini_success",
        )
        with patch.object(
            self.bot.message_router, "route", return_value=routed
        ) as route:
            self.bot.handle_update(
                {
                    "message": {
                        "message_id": 71,
                        "text": "@SmartMoneyHubSignalsBot, explain BOS simply.",
                        "chat": {"id": group_id, "type": "supergroup"},
                        "message_thread_id": 7654,
                        "from": {"id": self.user_id},
                    }
                }
            )

        args, kwargs = route.call_args
        self.assertEqual(args, (self.user_id, "explain BOS simply."))
        self.assertEqual(kwargs["history"], [])
        self.assertIn(
            "BOS is a break of a meaningful swing high or low.",
            [entry["content"] for entry in kwargs["profile"]["group_knowledge_context"]],
        )
        self.assertEqual(self.api.messages[-1]["message_thread_id"], 7654)
        self.assertEqual(
            self.api.messages[-1]["text"],
            "A BOS is a break of meaningful structure.",
        )
        connection = self.bot.store._connect()
        try:
            archived_count = connection.execute(
                "SELECT COUNT(*) FROM education_group_posts WHERE chat_id = ?",
                (group_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(archived_count, 1)

    def test_group_ask_uses_no_private_history_and_replies_in_same_topic(self) -> None:
        routed = Mock(
            reply=Mock(
                response="Liquidity may gather around obvious highs and lows.",
                requires_review=False,
            ),
            response_path="approved_knowledge",
            assessment=None,
        )
        with (
            patch.object(
                self.bot.message_router,
                "route",
                return_value=routed,
            ) as route,
            patch.object(
                self.bot.store,
                "recent_dm_coaching_interactions",
                side_effect=AssertionError("Group Q&A must not read private history."),
            ),
        ):
            self.bot.handle_update(
                {
                    "message": {
                        "text": "/ask@SmartMoneyHubSignalsBot What is liquidity?",
                        "chat": {
                            "id": -1003916437804,
                            "type": "supergroup",
                        },
                        "message_thread_id": 7654,
                        "from": {"id": self.user_id},
                    }
                }
            )

        args, kwargs = route.call_args
        self.assertEqual(args, (self.user_id, "What is liquidity?"))
        self.assertEqual(kwargs["history"], [])
        self.assertEqual(kwargs["profile"], {"group_knowledge_context": []})
        self.assertRegex(kwargs["request_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(len(self.api.messages), 1)
        self.assertEqual(
            self.api.messages[0]["text"],
            "Liquidity may gather around obvious highs and lows.",
        )
        self.assertEqual(self.api.messages[0]["message_thread_id"], 7654)
        self.assertIsNone(self.api.messages[0]["reply_markup"])

    def test_group_ask_requires_a_question(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "text": "/ask",
                    "chat": {
                        "id": -1003916437804,
                        "type": "supergroup",
                    },
                    "message_thread_id": 7654,
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertIn("Add your SMC question after /ask", self.api.messages[0]["text"])
        self.assertEqual(self.api.messages[0]["message_thread_id"], 7654)

    def test_group_question_needing_review_is_recorded_without_sender_identity(self) -> None:
        routed = Mock(
            reply=Mock(
                response="I could not verify that topic, so I flagged it for review.",
                requires_review=True,
                detected_topic="Unverified topic",
            ),
            assessment=None,
            response_path="fallback",
        )
        with patch.object(self.bot.message_router, "route", return_value=routed):
            self.bot.handle_update(
                {
                    "message": {
                        "message_id": 9003,
                        "text": "/ask What did @member 123456789 claim about a live signal?",
                        "chat": {
                            "id": -1003916437804,
                            "type": "supergroup",
                        },
                        "message_thread_id": 7654,
                        "from": {"id": self.user_id, "username": self.username},
                    }
                }
            )

        insights = self.bot.store.education_group_insights(-1003916437804)
        self.assertEqual(insights["open_question_count"], 1)
        preview = insights["open_questions"][0]["question_preview"]
        self.assertNotIn("@member", preview)
        self.assertNotIn("123456789", preview)

    def test_admin_can_start_hypothetical_quiz_poll_in_current_topic(self) -> None:
        bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=self.user_id,
        )
        bot.handle_update(
            {
                "message": {
                    "message_id": 14,
                    "text": "/scenario",
                    "chat": {
                        "id": -1003916437804,
                        "type": "supergroup",
                    },
                    "message_thread_id": 7654,
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertEqual(len(self.api.polls), 1)
        poll = self.api.polls[0]
        self.assertEqual(poll["chat_id"], -1003916437804)
        self.assertEqual(poll["message_thread_id"], 7654)
        self.assertIn("Hypothetical SMC scenario:", poll["question"])
        self.assertEqual(len(poll["options"]), 4)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", poll["explanation"])
        self.assertEqual(self.api.messages, [])
        archived = self.bot.store.search_education_group_posts(
            -1003916437804, "hypothetical SMC scenario"
        )
        self.assertEqual(len(archived), 1)
        self.assertIn("Correct option:", archived[0]["content"])

    def test_group_insights_are_private_and_admin_only(self) -> None:
        admin_bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=self.user_id,
        )
        admin_bot.store.record_education_group_post(
            chat_id=-1003916437804,
            message_id=91,
            thread_id=7654,
            topic_name="SMC Basics",
            message_kind="text",
            content="A safe education post.",
            source_status="configured_admin",
            posted_at="2026-10-24T10:00:00+00:00",
        )
        admin_bot.store.record_education_group_question(
            chat_id=-1003916437804,
            question="How can I confirm a retest?",
            topic="Confirmation",
            thread_id=7654,
        )

        admin_bot.handle_update(
            {
                "message": {
                    "text": "/groupinsights",
                    "chat": {"id": self.chat_id, "type": "private"},
                    "from": {"id": self.user_id},
                }
            }
        )
        self.assertIn("Archived posts: 1", self.api.messages[-1]["text"])
        self.assertIn("How can I confirm a retest?", self.api.messages[-1]["text"])

        outsider_bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=987654321,
        )
        outsider_bot.handle_update(
            {
                "message": {
                    "text": "/groupinsights",
                    "chat": {"id": self.chat_id, "type": "private"},
                    "from": {"id": self.user_id},
                }
            }
        )
        self.assertIn("only to the administrator", self.api.messages[-1]["text"])
        self.assertNotIn("Archived posts:", self.api.messages[-1]["text"])

    def test_only_configured_admin_can_start_group_scenario_polls(self) -> None:
        bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=987654321,
        )
        bot.handle_update(
            {
                "message": {
                    "message_id": 14,
                    "text": "/scenario",
                    "chat": {
                        "id": -1003916437804,
                        "type": "supergroup",
                    },
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertEqual(self.api.polls, [])
        self.assertIn("Only the group admin", self.api.messages[0]["text"])

    def test_group_learning_commands_are_limited_to_configured_group(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "text": "/ask What is liquidity?",
                    "chat": {
                        "id": -1008888888888,
                        "type": "supergroup",
                    },
                    "from": {"id": self.user_id},
                }
            }
        )

        self.assertEqual(self.api.messages, [])

    def test_group_id_command_is_silent_for_non_admins(self) -> None:
        bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=987654321,
        )

        bot.handle_update(
            {
                "message": {
                    "text": "/groupid",
                    "chat": {"id": -1001234567890, "type": "supergroup"},
                    "from": {"id": 123456789},
                }
            }
        )

        self.assertEqual(self.api.messages, [])

    def test_group_id_command_in_private_chat_instructs_admin_to_use_group(self) -> None:
        admin_id = 987654321
        bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=admin_id,
        )

        bot.handle_update(
            {
                "message": {
                    "text": "/groupid",
                    "chat": {"id": admin_id, "type": "private"},
                    "from": {"id": admin_id},
                }
            }
        )

        self.assertEqual(self.api.messages[0]["chat_id"], admin_id)
        self.assertIn("send /groupid inside that group", self.api.messages[0]["text"])
        self.assertNotIn("Group ID:", self.api.messages[0]["text"])

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

    def test_coach_shows_typing_action_while_generating_reply(self) -> None:
        self._text("What is liquidity?")

        self.assertEqual(
            self.api.chat_actions[0],
            {"chat_id": self.chat_id, "action": "typing"},
        )
        self.assertIn("liquidity", self.api.messages[-1]["text"].casefold())

    def test_typing_action_failure_does_not_block_coach_reply(self) -> None:
        def fail_typing_action(_chat_id: int, _action: str = "typing") -> None:
            raise TelegramAPIError("synthetic chat-action failure")

        self.api.send_chat_action = fail_typing_action  # type: ignore[method-assign]

        self._text("What is liquidity?")

        self.assertIn("liquidity", self.api.messages[-1]["text"].casefold())

    def test_dm_coach_saves_interactions_and_shows_private_admin_statistics(self) -> None:
        self._message("/start")
        self._click("menu:coach")
        self._click("coach:chat")
        self.assertIn("Chat with Coach is open", self.api.messages[-1]["text"])

        self._text("What is CHOCH?")
        self.assertIn("Change of Character", self.api.messages[-1]["text"])
        self._text("What is CHOCH?")
        self._text("I saw an FVG and entered immediately.")
        self.assertIn("not an entry confirmation", self.api.messages[-1]["text"])

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

    def test_active_assessment_consumes_text_before_coach_routing(self) -> None:
        provider = Mock()
        self.bot.message_router.coach_service = provider
        self._click("menu:assessment")

        with self.assertLogs("smart_money_hub_bot.bot", level="INFO") as logs:
            self._text("What is liquidity?")

        provider.evaluate.assert_not_called()
        self.assertIn(
            "Please choose one of the answer buttons", self.api.messages[-1]["text"]
        )
        self.assertTrue(
            any(
                "Coach bypassed: active conversation state kind=assessment."
                in message
                for message in logs.output
            )
        )

    def test_coach_modes_and_private_clear_history(self) -> None:
        self._click("menu:coach")
        labels = {
            button["text"]
            for row in self.api.messages[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        }
        self.assertTrue(
            {
                "💬 Chat with Coach",
                "🎯 Challenge Me",
                "🔍 Review My Setup",
                "📒 Review My Mistake",
                "🧠 Teach Me Something",
                "🔥 Daily Challenge",
                "🧹 Clear My Coach History",
            }.issubset(labels)
        )

        self._click("coach:challenge")
        for _ in range(3):
            markup = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
            answer_callback = markup[0][0]["callback_data"]
            self._callback(answer_callback, sender_id=self.user_id, chat_id=self.chat_id)
        self.assertIn("Challenge complete:", self.api.messages[-1]["text"])

        self._click("coach:daily")
        answer_callback = self.api.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]
        self._callback(answer_callback, sender_id=self.user_id, chat_id=self.chat_id)
        self.assertIn(
            "challenge complete:", self.api.messages[-1]["text"].casefold()
        )
        self.assertIn("/1", self.api.messages[-1]["text"])

        self._click("coach:mistake")
        self._text("I entered too early and then took a loss.")
        self._text("My plan said to wait for a close and retest.")
        self._text("I was afraid of missing the move; next time I will wait.")
        self.assertNotIn(self.user_id, self.bot.sessions)
        self.assertIn("Entry may have been earlier", self.api.messages[-1]["text"])
        self.assertIn("Fear of missing out", self.api.messages[-1]["text"])
        self.assertEqual(
            len(Repository(self.database_path).recent_dm_coaching_interactions(self.user_id)),
            1,
        )

        self._message("What is liquidity?", user_id=909091)
        self.assertEqual(
            len(Repository(self.database_path).recent_dm_coaching_interactions(909091)),
            1,
        )
        coach_keyboard = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        coach_buttons = [
            button["text"] for row in coach_keyboard for button in row
        ]
        self.assertNotIn("Coaching Modes", coach_buttons)
        self.assertIn("🏠 Main Menu", coach_buttons)

        self._message("/clearcoach")
        self.assertIn("Clear your saved Coach conversation history", self.api.messages[-1]["text"])
        self._click("coach:clear:cancel")
        self.assertEqual(
            len(Repository(self.database_path).recent_dm_coaching_interactions(self.user_id)),
            1,
        )

        self._message("/clearcoach")
        self._click("coach:clear:confirm")
        self.assertIn("Your assessments, trade journal", self.api.messages[-1]["text"])
        self.assertEqual(
            Repository(self.database_path).recent_dm_coaching_interactions(self.user_id),
            [],
        )
        self.assertEqual(
            len(Repository(self.database_path).recent_dm_coaching_interactions(909091)),
            1,
        )

    def test_challenge_questions_vary_between_rounds_and_do_not_repeat_in_a_round(self) -> None:
        def finish_round() -> list[str]:
            question_ids: list[str] = []
            for _ in range(3):
                markup = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
                callback_data = markup[0][0]["callback_data"]
                question_ids.append(callback_data.split("answer:", 1)[1].rsplit(":", 1)[0])
                self._click(callback_data)
            return question_ids

        self._click("coach:challenge")
        first_round = finish_round()
        self.assertEqual(len(set(first_round)), 3)

        self._click("coach:challenge")
        second_round = finish_round()
        self.assertEqual(len(set(second_round)), 3)
        self.assertTrue(set(first_round).isdisjoint(second_round))

    def test_optional_challenges_reward_practice_and_persist_per_member(self) -> None:
        self._message("/start")
        self._click("menu:coach")
        menu_text = self.api.messages[-1]["text"].casefold()
        self.assertIn("optional", menu_text)
        self.assertIn("no streaks to protect", menu_text)

        self._click("coach:challenge")
        for _ in range(3):
            session = self.bot.sessions[self.user_id]
            question = self.bot._current_coach_challenge(self.user_id, session)
            self.assertIsNotNone(question)
            wrong_index = (question["answer"] + 1) % len(question["options"])
            self._click(
                f"coach:challenge:answer:{question['id']}:{wrong_index}"
            )

        completion = self.api.messages[-1]["text"]
        self.assertIn("Challenge complete: 0/3", completion)
        self.assertIn("+5 Learning Points (total: 5)", completion)
        self.assertIn("Points reward practice, not only correct answers", completion)

        repository = Repository(self.database_path)
        reward = repository.coach_learning_progress_for(self.user_id)
        self.assertEqual(reward["learning_points"], 5)
        self.assertEqual(reward["questions_practiced"], 3)
        self.assertEqual(reward["correct_answers"], 0)
        self.assertEqual(reward["challenges_completed"], 1)
        self.assertEqual(
            repository.coach_learning_progress_for(self.user_id + 1)[
                "learning_points"
            ],
            0,
        )

        self._message("/progress")
        self.assertIn(
            "Learning points: 5 (3 questions practised)",
            self.api.messages[-1]["text"],
        )

    def test_simple_intents_are_varied_and_do_not_interrupt_active_flows(self) -> None:
        self._message("Hi")
        first_greeting = self.api.messages[-1]["text"]
        self._message("hello")
        second_greeting = self.api.messages[-1]["text"]
        self.assertNotEqual(first_greeting, second_greeting)
        self._message("Good morning")
        self.assertIn("morning", self.api.messages[-1]["text"].casefold())
        self._message("Thanks")
        self.assertNotIn(
            "I don’t have a vetted answer",
            self.api.messages[-1]["text"],
        )
        self.assertEqual(self.bot.store.knowledge_admin_summary()["awaiting_research"], 0)

        self._click("menu:assessment")
        self._message("Hi")
        self.assertIn("Please choose one of the answer buttons", self.api.messages[-1]["text"])
        self.assertEqual(self.bot.sessions[self.user_id].kind, "assessment")

        self._click("nav:home")
        self._click("menu:journal")
        self._click("journal:new")
        self._text("Thanks")
        self.assertEqual(self.bot.sessions[self.user_id].step, 1)
        self.assertNotIn("You’re welcome", self.api.messages[-1]["text"])

    def test_recovery_notice_follows_a_long_outage_once_per_private_member(self) -> None:
        recovered_at = self._record_poll_recovery(timedelta(hours=1))

        self._message("Hi", message_timestamp=int((recovered_at - timedelta(seconds=1)).timestamp()))
        self.assertEqual(
            self.api.messages[-2]["text"],
            BOT_RECOVERY_NOTICES[0],
        )

        self._message(
            "Thanks",
            message_timestamp=int((recovered_at + timedelta(seconds=1)).timestamp()),
        )
        self.assertFalse(
            any("Sorry for the delay" in item["text"] for item in self.api.messages[2:])
        )

        self._message(
            "Hi",
            user_id=self.user_id + 1,
            message_timestamp=int((recovered_at - timedelta(seconds=1)).timestamp()),
        )
        self.assertEqual(self.api.messages[-2]["text"], BOT_RECOVERY_NOTICES[0])

    def test_recovery_notice_is_followed_by_an_answer_to_the_original_message(self) -> None:
        recovered_at = self._record_poll_recovery(timedelta(hours=1))

        self._message(
            "What is liquidity?",
            message_timestamp=int((recovered_at - timedelta(seconds=1)).timestamp()),
        )

        self.assertEqual(self.api.messages[0]["text"], BOT_RECOVERY_NOTICES[0])
        self.assertIn("liquidity", self.api.messages[1]["text"].lower())
        self.assertNotIn("Sorry for the delay", self.api.messages[1]["text"])

    def test_recovery_notice_rotates_between_outages_for_each_member(self) -> None:
        recovered_at = self._record_poll_recovery(timedelta(hours=1))
        self._message(
            "Hi",
            message_timestamp=int((recovered_at - timedelta(seconds=1)).timestamp()),
        )
        first_notice = self.api.messages[-2]["text"]

        self.bot.store.record_successful_bot_poll(
            at="2026-10-24T00:00:00+00:00",
            started_at="2026-10-23T23:59:00+00:00",
        )
        second_recovery = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
        self._message("Hi", message_timestamp=int((second_recovery - timedelta(seconds=1)).timestamp()))
        second_notice = self.api.messages[-2]["text"]

        self.assertEqual(first_notice, BOT_RECOVERY_NOTICES[0])
        self.assertEqual(second_notice, BOT_RECOVERY_NOTICES[1])
        self.assertNotEqual(first_notice, second_notice)

    def test_recovery_notice_does_not_trigger_for_a_short_poll_gap(self) -> None:
        recovered_at = self._record_poll_recovery(timedelta(minutes=29))

        self._message(
            "Hi",
            message_timestamp=int((recovered_at - timedelta(seconds=1)).timestamp()),
        )

        self.assertEqual(len(self.api.messages), 1)
        self.assertNotIn("Sorry for the delay", self.api.messages[0]["text"])

    def test_recovery_notice_does_not_trigger_for_a_new_message_after_recovery(self) -> None:
        recovered_at = self._record_poll_recovery(timedelta(hours=1))

        self._message(
            "Hi",
            message_timestamp=int((recovered_at + timedelta(seconds=1)).timestamp()),
        )

        self.assertEqual(len(self.api.messages), 1)
        self.assertNotIn("Sorry for the delay", self.api.messages[0]["text"])

    def test_recovery_notice_does_not_trigger_for_a_message_from_before_the_outage(self) -> None:
        recovered_at = self._record_poll_recovery(timedelta(hours=1))

        self._message(
            "Hi",
            message_timestamp=int((recovered_at - timedelta(hours=2)).timestamp()),
        )

        self.assertEqual(len(self.api.messages), 1)
        self.assertNotIn("Sorry for the delay", self.api.messages[0]["text"])

    def test_long_poll_wait_does_not_count_as_bot_downtime(self) -> None:
        self.bot.store.record_successful_bot_poll(
            at="2026-10-23T19:00:00+00:00"
        )
        self.bot.store.record_successful_bot_poll(
            at="2026-10-23T19:30:00+00:00",
            started_at="2026-10-23T19:29:00+00:00",
        )

        self.assertIsNone(self.bot.store.pending_bot_recovery_notice(self.user_id))

    def test_recovery_notice_does_not_interrupt_an_active_assessment(self) -> None:
        self._click("menu:assessment")
        recovered_at = self._record_poll_recovery(timedelta(minutes=30))

        self._message(
            "I’m back",
            message_timestamp=int((recovered_at - timedelta(seconds=1)).timestamp()),
        )

        self.assertIn("Sorry for the delay", self.api.messages[-2]["text"])
        self.assertIn(
            "Please choose one of the answer buttons",
            self.api.messages[-1]["text"],
        )
        self.assertEqual(self.bot.sessions[self.user_id].kind, "assessment")

    def test_unknown_current_question_is_queued_without_inventing_live_information(self) -> None:
        self._message("What is the latest inflation report today?")
        response = self.api.messages[-1]["text"]
        self.assertIn("latest release", response)
        self.assertIn("Share the headline or figures", response)
        self.assertEqual(self.bot.store.knowledge_admin_summary()["awaiting_research"], 1)

    def test_guided_setup_review_asks_one_question_at_a_time(self) -> None:
        self._click("coach:setup")
        self.assertIn("Setup Review — 1/4", self.api.messages[-1]["text"])
        self._text("Gold, 15m, considering a short.")
        self.assertIn("Setup Review — 2/4", self.api.messages[-1]["text"])
        self._text("Bearish HTF, supply POI.")
        self._text("BSL swept, no confirmation yet.")
        self._text("Above the swing; fixed risk in my plan.")
        self.assertNotIn(self.user_id, self.bot.sessions)
        self.assertIn("I can’t verify a live chart", self.api.messages[-1]["text"])

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
        self.assertIn("Follow the confirmation and retest rules", review)
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
        self.assertIn("Do not chase a missed setup.", sunday)

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
        self.assertIn("not required by every entry model", self.api.messages[-1]["text"])

        self._click("menu:progress")
        self.assertIn("SMART MONEY HUB PROGRESS", self.api.messages[-1]["text"])
        self.assertIn("Weekly check-ins: 0", self.api.messages[-1]["text"])

        self._message("/myid")
        self.assertIn(str(self.user_id), self.api.messages[-1]["text"])
        self._message("/admin")
        self.assertIn("Admin access is restricted", self.api.messages[-1]["text"])
        self.assertNotIn("ADMIN_TELEGRAM_ID", self.api.messages[-1]["text"])
        self.assertNotIn("Send /myid", self.api.messages[-1]["text"])

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
                "📨 Send One-Time DM",
                "📣 Promote Bot in Channel",
            }.issubset(button_labels)
        )

        self._callback("admin:open", sender_id=self.user_id + 1, chat_id=self.chat_id + 1)
        self.assertIn("restricted", self.api.messages[-1]["text"])

    def test_admin_menu_text_opens_dashboard_only_for_configured_admin(self) -> None:
        self.bot.admin_id = self.user_id
        self.bot.admin_dashboard.admin_id = self.user_id

        self._message("  I WANNA SEE THE ADMIN MENU  ")
        self.assertIn(
            "SMART MONEY HUB — ADMIN DASHBOARD", self.api.messages[-1]["text"]
        )

        self._message("show me the admin menu", user_id=self.user_id + 1)
        self.assertIn("Admin access is restricted", self.api.messages[-1]["text"])
        self.assertNotIn(
            "SMART MONEY HUB — ADMIN DASHBOARD", self.api.messages[-1]["text"]
        )

    def test_market_awareness_review_is_admin_only_and_reads_saved_calendar_data(self) -> None:
        self.bot.admin_id = self.user_id
        self.bot.admin_dashboard.admin_id = self.user_id
        now = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)
        source_repository = OfficialCalendarRepository(self.database_path)
        records = parse_bea_release_dates(
            {
                "Gross Domestic Product": {
                    "release_dates": ["2026-10-29T12:30:00+00:00"]
                }
            },
            retrieved_at=now,
            start_at=now,
            end_at=datetime(2026, 11, 30, tzinfo=timezone.utc),
        )
        source_repository.save_records(records)
        before_count = len(source_repository.list_records())

        self._callback(
            "admin:market_awareness",
            sender_id=self.user_id + 1,
            chat_id=self.chat_id + 1,
        )
        self.assertIn("Admin access is restricted", self.api.messages[-1]["text"])
        self.assertNotIn("Gross Domestic Product", self.api.messages[-1]["text"])

        self._click("admin:market_awareness")
        rendered = self.api.messages[-1]
        self.assertIn("USD &amp; GOLD — ADMIN SOURCE REVIEW", rendered["text"])
        self.assertIn("Gross Domestic Product", rendered["text"])
        self.assertIn("WAT: Thu, 29 Oct 2026 13:30 WAT", rendered["text"])
        self.assertEqual(rendered["chat_id"], self.chat_id)
        self.assertEqual(rendered["parse_mode"], "HTML")
        self.assertEqual(len(source_repository.list_records()), before_count)
        self.assertFalse(any(
            message["chat_id"] == -1004481197912
            for message in self.api.messages
        ))

    def test_pro_channel_access_request_returns_other_bot_username(self) -> None:
        self._message("How can I join the Pro channel?")
        self.assertIn("@SMHProSignalsassistantbot", self.api.messages[-1]["text"])
        self.assertIn("request access", self.api.messages[-1]["text"])

        self._message("Explain liquidity in a Pro trading channel.")
        self.assertNotIn("@SMHProSignalsassistantbot", self.api.messages[-1]["text"])

    def test_pro_channel_access_shortcut_does_not_interrupt_active_quiz(self) -> None:
        self._click("menu:assessment")
        self._message("How can I join the Pro channel?")
        self.assertNotIn("@SMHProSignalsassistantbot", self.api.messages[-1]["text"])
        self.assertIn("choose one of the answer buttons", self.api.messages[-1]["text"])

    def test_member_quick_commands_keep_personal_details_private(self) -> None:
        self._message("/help")
        help_text = self.api.messages[-1]["text"]
        for command in ("/menu", "/progress", "/reminders", "/resume", "/stop"):
            self.assertIn(command, help_text)

        self._message("/progress")
        self.assertIn("SMART MONEY HUB PROGRESS", self.api.messages[-1]["text"])

        self._message("/reminders")
        reminder_text = self.api.messages[-1]["text"]
        self.assertIn("Zoom class check-ins: Automatic", reminder_text)
        self.assertIn("All scheduled reminders: Active", reminder_text)

        self._message("/stop")
        self.assertTrue(self.bot.store.reminders_stopped(self.user_id))
        self._message("/resume")
        self.assertFalse(self.bot.store.reminders_stopped(self.user_id))
        self.assertIn("All scheduled reminders: Active", self.api.messages[-1]["text"])

        self._message("/progress", user_id=self.user_id + 1, chat_id=-100123, chat_type="supergroup")
        self.assertIn("For privacy", self.api.messages[-1]["text"])
        self.assertNotIn("SMART MONEY HUB PROGRESS", self.api.messages[-1]["text"])

        self._message("/reminders", user_id=self.user_id + 1, chat_id=-100123, chat_type="supergroup")
        self.assertIn("private chat", self.api.messages[-1]["text"])

        self._message("/menu")
        self.assertEqual(
            self.api.messages[-1]["reply_markup"]["inline_keyboard"][0][0]["text"],
            "Start SMC Assessment",
        )

    def test_text_main_menu_aliases_are_case_insensitive_and_trimmed(self) -> None:
        for text in ("menu", "  MENU  ", "main menu", "  MaIn MeNu  "):
            with self.subTest(text=text):
                self._message(text)
                menu = self.api.messages[-1]
                self.assertEqual(menu["text"], "Choose an option:")
                self.assertEqual(
                    menu["reply_markup"]["inline_keyboard"][0][0]["text"],
                    "Start SMC Assessment",
                )

    def test_explicit_text_requests_open_existing_member_screens(self) -> None:
        self._message("Please open my trading journal")
        journal = self.api.messages[-1]
        self.assertEqual(journal["text"], "Trading Journal\n\nCreate a trade entry or review a previous one.")
        journal_buttons = [
            button["text"]
            for row in journal["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("New Trade Entry", journal_buttons)
        self.assertIn("Review Previous Trades", journal_buttons)

        self._message("Show me my progress")
        self.assertIn("SMART MONEY HUB PROGRESS", self.api.messages[-1]["text"])

        self._message("Can you open reminder settings?")
        self.assertIn("Weekly Sunday check-in:", self.api.messages[-1]["text"])
        self.assertIn("Zoom class check-ins: Automatic", self.api.messages[-1]["text"])

        self._message("Open Ask Coach")
        self.assertIn("Choose how you want to learn today", self.api.messages[-1]["text"])
        coach_buttons = [
            button["text"]
            for row in self.api.messages[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("💬 Chat with Coach", coach_buttons)

        self._message("Open Clear My Coach History")
        self.assertIn("Clear your saved Coach conversation history?", self.api.messages[-1]["text"])
        self.assertEqual(
            self.api.messages[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"],
            "coach:clear:confirm",
        )

    def test_explicit_open_request_does_not_interrupt_an_active_assessment(self) -> None:
        self._click("menu:assessment")
        session_before = self.bot.sessions[self.user_id]

        self._message("Open my trading journal")

        self.assertIs(self.bot.sessions[self.user_id], session_before)
        self.assertEqual(session_before.step, 0)
        self.assertIn("current activity is still open", self.api.messages[-1]["text"])
        self.assertIn("Question 1/10", self.api.messages[-2]["text"])
        self._click(f"answer:0:{QUESTIONS[0].correct_index}")
        self.assertEqual(self.bot.sessions[self.user_id].step, 1)

    def test_text_navigation_keeps_personal_journal_details_private(self) -> None:
        self._message(
            "Open my trade history",
            chat_id=-100123,
            chat_type="supergroup",
        )
        self.assertIn("For privacy, open a private chat", self.api.messages[-1]["text"])
        self.assertNotIn(
            "Your recent trade entries", self.api.messages[-1]["text"]
        )

    def test_ordinary_coaching_message_still_reaches_the_coach(self) -> None:
        self._message("What is liquidity?")
        reply = self.api.messages[-1]
        self.assertNotEqual(reply["text"], "Choose an option:")
        self.assertIn(
            "liquidity",
            reply["text"].casefold(),
        )
        self.assertEqual(
            len(Repository(self.database_path).recent_dm_coaching_interactions(self.user_id)),
            1,
        )

    def test_bot_marks_only_configured_admin_for_coach_context(self) -> None:
        self.bot.admin_id = self.user_id
        with patch.object(
            self.bot.message_router,
            "route",
            wraps=self.bot.message_router.route,
        ) as route:
            self._message("What is liquidity?")
            self.assertIs(route.call_args.kwargs["profile"]["is_admin"], True)

            self._message("What is liquidity?", user_id=self.user_id + 1)
            self.assertIs(route.call_args.kwargs["profile"]["is_admin"], False)

    def test_menu_words_in_ordinary_message_do_not_open_a_screen(self) -> None:
        self._message("I keep a trading journal to learn from my decisions.")
        self.assertNotEqual(
            self.api.messages[-1]["text"],
            "Trading Journal\n\nCreate a trade entry or review a previous one.",
        )

    def test_admin_can_preview_confirm_and_cancel_one_time_channel_promo(self) -> None:
        channel_id = -1004481197912
        self.bot.admin_id = self.user_id
        self.bot.admin_dashboard.admin_id = self.user_id
        self.bot.admin_dashboard.main_channel_id = channel_id

        self._callback(
            "admin:channel_promo",
            sender_id=self.user_id + 1,
            chat_id=self.user_id + 1,
        )
        self.assertIn("restricted", self.api.messages[-1]["text"])
        self.assertFalse(
            any(message["chat_id"] == channel_id for message in self.api.messages)
        )

        self._callback(
            "admin:channel_promo", sender_id=self.user_id, chat_id=self.chat_id
        )
        preview = self.api.messages[-1]
        self.assertIn(
            f"Destination channel ID: <code>{channel_id}</code>",
            preview["text"],
        )
        self.assertIn("CHANNEL PROMO PREVIEW — NOT PUBLISHED", preview["text"])
        self.assertIn("SMC Lessons", preview["text"])
        self.assertIn("Assessments &amp; Challenges", preview["text"])
        self.assertIn("choose a weekly focus in check-ins", preview["text"])
        self.assertIn("Monday and Thursday Zoom class reminders", preview["text"])
        self.assertIn("NO CONFIRMATION, NO ENTRY.", preview["text"])
        self.assertNotIn("Open Smart Money Hub", preview["text"])
        self.assertEqual(preview["parse_mode"], "HTML")
        self.assertEqual(preview["text"].count("<b>"), preview["text"].count("</b>"))
        self.assertEqual(preview["text"].count("<code>"), preview["text"].count("</code>"))
        parser = StrictTelegramHtmlParser()
        parser.feed(preview["text"])
        parser.close()
        self.assertEqual(parser.errors, [])
        self.assertEqual(parser.open_tags, [])
        self.assertLessEqual(len(preview["text"]), 4096)
        self.assertIn("🚀", CHANNEL_PROMO_TEXT)
        self.assertIn("SMART MONEY HUB", CHANNEL_PROMO_TEXT)
        self.assertIn("&amp;", CHANNEL_PROMO_TEXT)
        self.assertNotIn("& Challenges", CHANNEL_PROMO_TEXT)
        self.assertIn("send /start if prompted", CHANNEL_PROMO_TEXT)
        self.assertEqual(
            CHANNEL_PROMO_URL,
            "https://t.me/SmartMoneyHubSignalsBot",
        )
        self.assertIn("Nothing has been posted yet", preview["text"])
        self.assertFalse(
            any(message["chat_id"] == channel_id for message in self.api.messages)
        )

        buttons = [
            button
            for row in preview["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        coach_button = next(button for button in buttons if button["text"] == "Coach")
        self.assertEqual(
            coach_button["url"], "https://t.me/SmartMoneyHubSignalsBot"
        )
        self.assertTrue(
            any(
                button.get("callback_data") == "admin:channel_promo:confirm"
                for button in buttons
            )
        )
        self.assertTrue(
            any(
                button.get("callback_data") == "admin:channel_promo:cancel"
                for button in buttons
            )
        )

        self._callback(
            "admin:channel_promo:confirm",
            sender_id=self.user_id,
            chat_id=self.chat_id,
        )
        posted = [
            message for message in self.api.messages if message["chat_id"] == channel_id
        ]
        self.assertEqual(len(posted), 1)
        self.assertIn("SMART MONEY HUB", posted[0]["text"])
        self.assertEqual(
            posted[0]["reply_markup"]["inline_keyboard"][0][0],
            {
                "text": "Coach",
                "url": "https://t.me/SmartMoneyHubSignalsBot",
            },
        )
        self.assertEqual(posted[0]["parse_mode"], "HTML")
        self.assertNotIn("Open Smart Money Hub", posted[0]["text"])
        self.assertIn("posted to the channel", self.api.messages[-1]["text"])

        self._callback(
            "admin:channel_promo:confirm",
            sender_id=self.user_id,
            chat_id=self.chat_id,
        )
        self.assertEqual(
            sum(message["chat_id"] == channel_id for message in self.api.messages),
            1,
        )

    def test_channel_promo_cancel_and_missing_configuration_do_not_post(self) -> None:
        channel_id = -1004481197912
        self.bot.admin_id = self.user_id
        self.bot.admin_dashboard.admin_id = self.user_id
        self.bot.admin_dashboard.main_channel_id = channel_id

        self._callback(
            "admin:channel_promo", sender_id=self.user_id, chat_id=self.chat_id
        )
        self._callback(
            "admin:channel_promo:cancel",
            sender_id=self.user_id,
            chat_id=self.chat_id,
        )
        self.assertIn("Nothing was posted", self.api.messages[-1]["text"])
        self.assertFalse(
            any(message["chat_id"] == channel_id for message in self.api.messages)
        )

        self.bot.admin_dashboard.main_channel_id = None
        self._callback(
            "admin:channel_promo", sender_id=self.user_id, chat_id=self.chat_id
        )
        self.assertIn("not configured", self.api.messages[-1]["text"])
        self._callback(
            "admin:channel_promo:confirm",
            sender_id=self.user_id,
            chat_id=self.chat_id,
        )
        self.assertFalse(
            any(message["chat_id"] == channel_id for message in self.api.messages)
        )

    def test_channel_promo_requires_admin_private_chat(self) -> None:
        channel_id = -1004481197912
        self.bot.admin_id = self.user_id
        self.bot.admin_dashboard.admin_id = self.user_id
        self.bot.admin_dashboard.main_channel_id = channel_id
        self._callback(
            "admin:channel_promo",
            sender_id=self.user_id,
            chat_id=-100777,
            chat_type="supergroup",
        )
        self.assertIn("private chat", self.api.messages[-1]["text"])
        self.assertFalse(
            any(message["chat_id"] == channel_id for message in self.api.messages)
        )

    def test_admin_can_preview_confirm_and_cancel_one_time_dm(self) -> None:
        admin_id = self.user_id
        active_member_id = 770101
        stopped_member_id = 770102
        group_member_id = 770103
        self.bot.admin_id = admin_id
        self.bot.admin_dashboard.admin_id = admin_id
        self.bot.store.register_user(
            telegram_id=active_member_id,
            username="active_member",
            first_name="Active",
            chat_id=active_member_id,
            is_private=True,
        )
        self.bot.store.register_user(
            telegram_id=stopped_member_id,
            username="stopped_member",
            first_name="Stopped",
            chat_id=stopped_member_id,
            is_private=True,
        )
        self.bot.store.set_reminders_stopped(stopped_member_id, True)
        self.bot.store.register_user(
            telegram_id=group_member_id,
            username="group_member",
            first_name="Group",
            chat_id=-group_member_id,
            is_private=False,
        )

        self._callback(
            "admin:dm_broadcast",
            sender_id=admin_id + 1,
            chat_id=-(admin_id + 1),
            chat_type="supergroup",
        )
        self.assertIn("restricted", self.api.messages[-1]["text"])
        self.assertFalse(
            self.bot.admin_dashboard.broadcast_is_pending(admin_id + 1)
        )

        self._callback(
            "admin:dm_broadcast",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self.assertIn("Nothing is sent until", self.api.messages[-1]["text"])
        message_text = "Hello members,\n\nPlease remember to check the channel."
        self._message(message_text, user_id=admin_id, chat_id=self.chat_id)
        preview = self.api.messages[-1]
        self.assertIn("Recipients: 1", preview["text"])
        self.assertIn(message_text, preview["text"])
        self.assertFalse(
            any(message["chat_id"] == active_member_id for message in self.api.messages)
        )

        self._callback(
            "admin:dm_broadcast:confirm",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        direct_messages = [
            message
            for message in self.api.messages
            if message["chat_id"] == active_member_id
        ]
        self.assertEqual([message["text"] for message in direct_messages], [message_text])
        self.assertEqual(
            direct_messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"],
            "reminders:off",
        )
        self.assertFalse(
            any(message["chat_id"] == stopped_member_id for message in self.api.messages)
        )
        self.assertFalse(
            any(message["chat_id"] == -group_member_id for message in self.api.messages)
        )
        self.assertFalse(
            any(
                message["chat_id"] == self.chat_id and message["text"] == message_text
                for message in self.api.messages
            )
        )
        self.assertIn("Sent: 1. Failed: 0.", self.api.messages[-1]["text"])

        # A repeated confirmation cannot send the same one-time message again.
        self._callback(
            "admin:dm_broadcast:confirm",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self.assertEqual(
            sum(message["chat_id"] == active_member_id for message in self.api.messages),
            1,
        )

        self._callback(
            "admin:dm_broadcast",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self._message("This draft should not be sent.", user_id=admin_id, chat_id=self.chat_id)
        self._callback(
            "admin:dm_broadcast:cancel",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self._callback(
            "admin:dm_broadcast:confirm",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self.assertEqual(
            sum(message["chat_id"] == active_member_id for message in self.api.messages),
            1,
        )

    def test_admin_can_preview_and_confirm_one_time_dm_to_one_member(self) -> None:
        admin_id = self.user_id
        selected_member_id = 770201
        other_member_id = 770202
        self.bot.admin_id = admin_id
        self.bot.admin_dashboard.admin_id = admin_id
        for member_id, first_name in (
            (selected_member_id, "Selected"),
            (other_member_id, "Other"),
        ):
            self.bot.store.register_user(
                telegram_id=member_id,
                username=f"member_{member_id}",
                first_name=first_name,
                chat_id=member_id,
                is_private=True,
            )

        self._callback("admin:members", sender_id=admin_id, chat_id=self.chat_id)
        member_keyboard = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        dm_button = next(
            button
            for row in member_keyboard
            for button in row
            if button["callback_data"]
            == f"admin:dm_member:target:{selected_member_id}"
        )
        self.assertEqual(dm_button["text"], "✉️ DM")
        self._callback(
            dm_button["callback_data"],
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self.assertIn("Recipient selected: Selected", self.api.messages[-1]["text"])
        self.assertIn("Recipient selected: Selected", self.api.messages[-1]["text"])
        message_text = "A private note just for you."
        self._message(
            message_text,
            user_id=admin_id,
            chat_id=self.chat_id,
        )
        preview = self.api.messages[-1]
        self.assertIn("ONE-TIME MEMBER DM PREVIEW", preview["text"])
        self.assertIn(f"Telegram ID {selected_member_id}", preview["text"])
        self.assertIn(message_text, preview["text"])
        self.assertFalse(
            any(
                message["chat_id"] in {selected_member_id, other_member_id}
                for message in self.api.messages
            )
        )

        self._callback(
            "admin:dm_member:confirm",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self.assertEqual(
            [
                message["text"]
                for message in self.api.messages
                if message["chat_id"] == selected_member_id
            ],
            [message_text],
        )
        self.assertFalse(
            any(message["chat_id"] == other_member_id for message in self.api.messages)
        )

        self._callback(
            "admin:dm_member:confirm",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self.assertEqual(
            sum(
                message["chat_id"] == selected_member_id
                for message in self.api.messages
            ),
            1,
        )

    def test_one_member_dm_button_clears_pending_broadcast_input(self) -> None:
        admin_id = self.user_id
        member_id = 770205
        self.bot.admin_id = admin_id
        self.bot.admin_dashboard.admin_id = admin_id
        self.bot.store.register_user(
            telegram_id=member_id,
            username="member_770205",
            first_name="Member",
            chat_id=member_id,
            is_private=True,
        )

        self._callback(
            "admin:dm_broadcast",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self._callback(
            "admin:dm_member",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )
        self._message(str(member_id), user_id=admin_id, chat_id=self.chat_id)

        self.assertIn("Recipient selected: Member", self.api.messages[-1]["text"])
        self.assertFalse(
            any(
                message["chat_id"] == self.chat_id
                and "ONE-TIME DM PREVIEW" in message["text"]
                for message in self.api.messages
            )
        )
        self.assertFalse(
            any(message["chat_id"] == member_id for message in self.api.messages)
        )

    def test_single_member_dm_is_cancelled_if_member_opts_out_before_confirm(self) -> None:
        admin_id = self.user_id
        member_id = 770203
        self.bot.admin_id = admin_id
        self.bot.admin_dashboard.admin_id = admin_id
        self.bot.store.register_user(
            telegram_id=member_id,
            username="member_770203",
            first_name="Member",
            chat_id=member_id,
            is_private=True,
        )
        self._message(
            f"/memberdm {member_id} An update for you.",
            user_id=admin_id,
            chat_id=self.chat_id,
        )
        self.assertIn("ONE-TIME MEMBER DM PREVIEW", self.api.messages[-1]["text"])
        self.bot.store.set_reminders_stopped(member_id, True)

        self._callback(
            "admin:dm_member:confirm",
            sender_id=admin_id,
            chat_id=self.chat_id,
        )

        self.assertFalse(
            any(message["chat_id"] == member_id for message in self.api.messages)
        )
        self.assertIn("no longer eligible", self.api.messages[-1]["text"])

    def test_single_member_dm_command_is_admin_only(self) -> None:
        admin_id = self.user_id
        outsider_id = admin_id + 1
        member_id = 770204
        self.bot.admin_id = admin_id
        self.bot.admin_dashboard.admin_id = admin_id
        self.bot.store.register_user(
            telegram_id=member_id,
            username="member_770204",
            first_name="Member",
            chat_id=member_id,
            is_private=True,
        )

        self._message(
            f"/memberdm {member_id} This must not be sent.",
            user_id=outsider_id,
            chat_id=outsider_id,
        )

        self.assertIn("restricted", self.api.messages[-1]["text"].casefold())
        self.assertFalse(
            any(message["chat_id"] == member_id for message in self.api.messages)
        )
        self.assertFalse(
            self.bot.admin_dashboard.has_single_member_dm_state(admin_id)
        )

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
        profile_keyboard = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        self.assertTrue(
            any(
                button["callback_data"] == f"admin:dm_member:target:{member_id}"
                for row in profile_keyboard
                for button in row
            )
        )
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

    def test_sunday_checkins_are_private_default_on_idempotent_and_honor_optouts(self) -> None:
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
            telegram_id=303,
            username="new_private_member",
            first_name="Nneka",
            chat_id=303,
            is_private=True,
            at="2026-10-03T10:00:00+00:00",
        )
        self.bot.store.register_user(
            telegram_id=404,
            username="opted_out_member",
            first_name="Kemi",
            chat_id=404,
            is_private=True,
            at="2026-10-03T10:00:00+00:00",
        )
        self.assertTrue(self.bot.store.sunday_checkin_enabled(303))
        self.assertTrue(self.bot.store.set_reminders_enabled(404, False))
        self.assertFalse(self.bot.store.sunday_checkin_enabled(404))
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
        self.assertEqual(len(scheduled), 2)
        self.assertEqual(
            [message["chat_id"] for message in scheduled],
            [101, 303],
        )

        self._message("/stop", user_id=101, chat_id=101)
        self.bot._dispatch_due_reminders(
            datetime(2026, 10, 11, 9, 5, tzinfo=ZoneInfo("Africa/Lagos"))
        )
        scheduled = [
            message for message in self.api.messages
            if message["text"].startswith("🧠 Sunday Check-In")
        ]
        self.assertEqual(len(scheduled), 3)
        self.assertEqual(
            [message["chat_id"] for message in scheduled],
            [101, 303, 303],
        )

    def test_configured_admin_can_set_one_time_reminder_in_natural_language(self) -> None:
        self.bot.admin_id = self.user_id
        self._message("Remind me to review my journal tomorrow at 9am")

        self.assertIn("Reminder saved: review my journal", self.api.messages[-1]["text"])
        self.assertIn("Africa/Lagos", self.api.messages[-1]["text"])
        reminders = self.bot.store.pending_personal_reminders(self.user_id)
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]["reminder_text"], "review my journal")

    def test_personal_reminder_collects_missing_time_then_saves(self) -> None:
        self.bot.admin_id = self.user_id
        self._message("Remind me to review my journal")
        self.assertIn("What time should I remind you?", self.api.messages[-1]["text"])
        self.assertEqual(self.bot.sessions[self.user_id].kind, "personal_reminder")

        self._message("tomorrow at 9am")

        self.assertIn("Reminder saved: review my journal", self.api.messages[-1]["text"])
        self.assertNotIn(self.user_id, self.bot.sessions)
        self.assertEqual(
            len(self.bot.store.pending_personal_reminders(self.user_id)), 1
        )

    def test_due_personal_reminder_sends_only_once(self) -> None:
        self.bot.admin_id = self.user_id
        self._message("/start")
        lagos = ZoneInfo("Africa/Lagos")
        reminder_id = self.bot.store.create_personal_reminder(
            self.user_id,
            "Review my journal",
            datetime(2026, 10, 27, 10, 0, tzinfo=lagos),
        )
        self.assertIsNotNone(reminder_id)

        due_check = datetime(2026, 10, 27, 10, 1, tzinfo=lagos)
        self.bot._dispatch_due_reminders(due_check)
        self.bot._dispatch_due_reminders(due_check)

        sent = [
            item for item in self.api.messages
            if item["text"] == "⏰ Reminder: Review my journal"
        ]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["chat_id"], self.chat_id)
        self.assertEqual(
            self.bot.store.pending_personal_reminders(self.user_id), []
        )

    def test_stop_cancels_pending_personal_reminders(self) -> None:
        self.bot.admin_id = self.user_id
        self._message("/start")
        self.bot.store.create_personal_reminder(
            self.user_id,
            "Review my journal",
            datetime(2026, 10, 27, 10, 0, tzinfo=ZoneInfo("Africa/Lagos")),
        )

        self._message("/stop")

        self.assertIn("pending one-time reminders have been cancelled", self.api.messages[-1]["text"])
        self.assertEqual(
            self.bot.store.pending_personal_reminders(self.user_id), []
        )

    def test_personal_reminder_requires_private_chat(self) -> None:
        self.bot.admin_id = self.user_id
        self._message(
            "Remind me to review my journal tomorrow at 9am",
            user_id=707,
            chat_id=-707,
            chat_type="supergroup",
        )

        self.assertIn("private chat", self.api.messages[-1]["text"])
        self.assertEqual(self.bot.store.pending_personal_reminders(707), [])

    def test_personal_reminder_request_does_not_interrupt_active_assessment(self) -> None:
        self.bot.admin_id = self.user_id
        self._click("menu:assessment")

        self._message("Remind me to review my journal tomorrow at 9am")

        self.assertIn("Please choose one of the answer buttons", self.api.messages[-1]["text"])
        self.assertEqual(self.bot.sessions[self.user_id].kind, "assessment")
        self.assertEqual(
            self.bot.store.pending_personal_reminders(self.user_id), []
        )

    def test_personal_reminders_are_exclusive_to_configured_admin(self) -> None:
        self.bot.admin_id = 999
        self._message("Remind me to review my journal tomorrow at 9am")

        self.assertIn("aren’t available for this account", self.api.messages[-1]["text"])
        self.assertEqual(
            self.bot.store.pending_personal_reminders(self.user_id), []
        )

        self._message("/help", user_id=self.user_id + 1)
        self.assertNotIn("CEO reminder", self.api.messages[-1]["text"])
        self._message("/reminders", user_id=self.user_id + 1)
        self.assertNotIn("Pending one-time reminders", self.api.messages[-1]["text"])

    def test_personal_reminder_is_not_sent_to_non_admin(self) -> None:
        self.bot.admin_id = self.user_id
        other_user = self.user_id + 1
        self.bot.store.register_user(
            telegram_id=other_user,
            username=None,
            first_name=None,
            chat_id=other_user,
            is_private=True,
        )
        self.bot.store.create_personal_reminder(
            other_user,
            "A reminder created before the access restriction",
            datetime(2026, 10, 27, 10, 0, tzinfo=ZoneInfo("Africa/Lagos")),
        )

        self.bot._dispatch_due_reminders(
            datetime(2026, 10, 27, 10, 1, tzinfo=ZoneInfo("Africa/Lagos"))
        )

        self.assertFalse(
            any(
                item["chat_id"] == other_user
                and item["text"].startswith("⏰ Reminder:")
                for item in self.api.messages
            )
        )

    def test_zoom_class_checkins_are_automatic_and_honor_stop(self) -> None:
        self.bot.store.register_user(
            telegram_id=303,
            username="class_member",
            first_name="Chidi",
            chat_id=303,
            is_private=True,
            at="2026-10-01T10:00:00+00:00",
        )
        self.assertFalse(self.bot.store.reminders_enabled(303))
        self.assertFalse(self.bot.store.class_reminders_enabled(303))
        self.bot.store.register_user(
            telegram_id=404,
            username="group_member",
            first_name="Bola",
            chat_id=-404,
            is_private=False,
            at="2026-10-01T10:00:00+00:00",
        )

        lagos = ZoneInfo("Africa/Lagos")
        for day in (5, 8):  # Monday and Thursday in this week
            self.bot._dispatch_due_reminders(
                datetime(2026, 10, day, 19, 2, tzinfo=lagos)
            )
            self.bot._dispatch_due_reminders(
                datetime(2026, 10, day, 19, 2, tzinfo=lagos)
            )
            self.bot._dispatch_due_reminders(
                datetime(2026, 10, day, 20, 2, tzinfo=lagos)
            )
            self.bot._dispatch_due_reminders(
                datetime(2026, 10, day, 20, 2, tzinfo=lagos)
            )

        class_messages = [
            message for message in self.api.messages
            if "ZOOM CLASS" in message["text"]
        ]
        self.assertEqual(len(class_messages), 4)
        self.assertEqual(
            class_messages[0]["text"],
            "SMART MONEY HUB\n"
            "MONDAY ZOOM CLASS\n"
            "Your class begins in one hour, at 8:00 PM (Africa/Lagos).\n"
            "The Zoom link will be available in the channel.",
        )
        self.assertEqual(
            class_messages[1]["text"],
            "SMART MONEY HUB\n"
            "MONDAY ZOOM CLASS IS STARTING NOW\n"
            "The Zoom link will be available in the channel.",
        )
        self.assertEqual(
            class_messages[2]["text"],
            "SMART MONEY HUB\n"
            "THURSDAY ZOOM CLASS\n"
            "Your class begins in one hour, at 8:00 PM (Africa/Lagos).\n"
            "The Zoom link will be available in the channel.",
        )
        self.assertEqual(
            class_messages[3]["text"],
            "SMART MONEY HUB\n"
            "THURSDAY ZOOM CLASS IS STARTING NOW\n"
            "The Zoom link will be available in the channel.",
        )

        self._message("/stop", user_id=303, chat_id=303)
        self.assertFalse(self.bot.store.class_reminders_enabled(303))
        self.assertTrue(self.bot.store.reminders_stopped(303))
        self.assertEqual(self.bot.store.class_reminder_recipients(), [])

        self._message("/start", user_id=303, chat_id=303)
        self.assertTrue(self.bot.store.reminders_stopped(303))

        self._callback("reminders:on", sender_id=303, chat_id=303)
        self.assertFalse(self.bot.store.reminders_stopped(303))
        self.assertTrue(self.bot.store.reminders_enabled(303))
        self.assertEqual(
            [member["telegram_id"] for member in self.bot.store.class_reminder_recipients()],
            [303],
        )

    def test_reminder_settings_show_automatic_class_checkins(self) -> None:
        self._click("menu:reminders")
        self.assertIn("Zoom class check-ins: Automatic", self.api.messages[-1]["text"])
        self.assertIn("All scheduled reminders: Active", self.api.messages[-1]["text"])
        self.assertTrue(self.bot.store.sunday_checkin_enabled(self.user_id))
        self.assertFalse(self.bot.store.reminders_enabled(self.user_id))
        self._click("reminders:weekly:toggle")
        self.assertFalse(self.bot.store.sunday_checkin_enabled(self.user_id))
        self.assertFalse(self.bot.store.reminders_enabled(self.user_id))
        self.assertFalse(self.bot.store.reminders_stopped(self.user_id))
        self._click("reminders:off")
        self.assertTrue(self.bot.store.reminders_stopped(self.user_id))
        self.assertIn("All scheduled reminders: Stopped", self.api.messages[-1]["text"])
        self._click("reminders:on")
        self.assertFalse(self.bot.store.reminders_stopped(self.user_id))
        self.assertTrue(self.bot.store.sunday_checkin_enabled(self.user_id))

    def test_run_does_not_change_an_existing_webhook(self) -> None:
        self.api.webhook_info = {"url": "https://example.invalid/webhook"}
        with self.assertRaisesRegex(SystemExit, "will not change it automatically"):
            self.bot.run()

    def test_run_logs_telegram_business_capability_as_a_boolean(self) -> None:
        self.api.get_updates = Mock(side_effect=[KeyboardInterrupt()])
        with patch.object(
            self.api,
            "get_me",
            return_value={
                "username": "SmartMoneyHubTestBot",
                "can_connect_to_business": True,
            },
        ):
            with patch("smart_money_hub_bot.bot.threading.Thread"):
                with self.assertLogs("smart_money_hub_bot.bot", level="INFO") as logs:
                    with self.assertRaises(KeyboardInterrupt):
                        self.bot.run()

        self.assertTrue(
            any(
                "Telegram Business capability can_connect_to_business=True"
                in entry
                for entry in logs.output
            )
        )

    def test_run_persists_each_successful_telegram_poll(self) -> None:
        self.api.get_updates = Mock(side_effect=[[], KeyboardInterrupt()])
        with patch("smart_money_hub_bot.bot.threading.Thread") as thread_factory:
            with patch.object(
                self.bot.store, "record_successful_bot_poll"
            ) as record_poll:
                record_poll.return_value = None
                with self.assertRaises(KeyboardInterrupt):
                    self.bot.run()

        thread_factory.return_value.start.assert_called_once()
        self.assertEqual(record_poll.call_count, 1)
        self.assertEqual(
            record_poll.call_args.kwargs["recovery_threshold_seconds"],
            BOT_RECOVERY_NOTICE_AFTER_SECONDS,
        )
        self.assertIn("at", record_poll.call_args.kwargs)
        self.assertIn("started_at", record_poll.call_args.kwargs)

    def test_run_privately_notifies_admin_after_long_poll_outage(self) -> None:
        self.api.get_updates = Mock(side_effect=[[], KeyboardInterrupt()])
        with patch("smart_money_hub_bot.bot.threading.Thread"):
            with patch.object(
                self.bot.store, "record_successful_bot_poll", return_value=10_476
            ):
                with patch.object(self.bot, "_notify_content_admin") as notify:
                    with self.assertRaises(KeyboardInterrupt):
                        self.bot.run()

        notify.assert_called_once()
        message = notify.call_args.args[0]
        self.assertIn("2h 54m", message)
        self.assertIn("checking scheduled posts", message)
        self.assertIn("not sent late", message)

    def test_polling_heartbeat_reports_active_and_stale_poll_age(self) -> None:
        self.assertEqual(POLLING_HEARTBEAT_INTERVAL_SECONDS, 30)
        self.bot._last_successful_poll_at = 100.0

        with self.assertLogs("smart_money_hub_bot.bot", level="INFO") as logs:
            self.bot._log_polling_heartbeat(now=130.0)
        self.assertIn("polling_status=active", logs.output[0])
        self.assertIn("seconds_since_successful_poll=30", logs.output[0])

        with self.assertLogs("smart_money_hub_bot.bot", level="INFO") as logs:
            self.bot._log_polling_heartbeat(now=161.0)
        self.assertIn("polling_status=stale", logs.output[0])
        self.assertIn("seconds_since_successful_poll=61", logs.output[0])

    def _message(
        self,
        text: str,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        chat_type: str = "private",
        message_timestamp: int | None = None,
    ) -> None:
        member = user_id if user_id is not None else self.user_id
        private_chat = chat_id if chat_id is not None else (
            self.chat_id if member == self.user_id else member
        )
        message = {
            "text": text,
            "chat": {"id": private_chat, "type": chat_type},
            "from": {
                "id": member,
                "username": self.username if member == self.user_id else None,
                "first_name": self.first_name,
            },
        }
        if message_timestamp is not None:
            message["date"] = message_timestamp
        self.bot.handle_update({"message": message})

    def _record_poll_recovery(self, gap: timedelta) -> datetime:
        recovered_at = datetime(2026, 10, 23, 19, 0, tzinfo=timezone.utc)
        started_at = recovered_at - gap
        self.bot.store.record_successful_bot_poll(at=started_at.isoformat())
        self.bot.store.record_successful_bot_poll(at=recovered_at.isoformat())
        return recovered_at

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
    def test_existing_channel_drafts_get_admin_edit_approval_flag_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "channel-posts-legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE scheduled_channel_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_date TEXT NOT NULL UNIQUE,
                    schedule_time TEXT NOT NULL,
                    requested_category TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    destination_chat_id INTEGER NOT NULL,
                    is_promo INTEGER NOT NULL DEFAULT 0,
                    bot_username TEXT,
                    status TEXT NOT NULL,
                    preview_sent_at TEXT,
                    preview_last_attempt_at TEXT,
                    edit_admin_id INTEGER,
                    publishing_started_at TEXT,
                    retry_after_at TEXT,
                    publish_attempts INTEGER NOT NULL DEFAULT 0,
                    telegram_message_id INTEGER,
                    published_at TEXT,
                    failure_category TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO scheduled_channel_posts (
                    schedule_date, schedule_time, requested_category, category,
                    content, destination_chat_id, is_promo, bot_username, status,
                    edit_admin_id, created_at, updated_at
                ) VALUES (
                    '2026-10-24', '10:00', 'education', 'education',
                    'Saved post text.', -1004481197912, 1,
                    'SmartMoneyHubSignalsBot', 'awaiting_edit', 777,
                    '2026-10-24T10:00:00+00:00', '2026-10-24T10:00:00+00:00'
                )
                """
            )
            connection.commit()
            connection.close()

            Repository(path)

            connection = sqlite3.connect(path)
            try:
                saved = connection.execute(
                    """
                    SELECT content, status, edit_admin_id,
                           generation_source, admin_edit_approved
                    FROM scheduled_channel_posts WHERE schedule_date = '2026-10-24'
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(
                saved,
                ("Saved post text.", "awaiting_edit", 777, "local", 0),
            )

    def test_existing_user_table_gets_class_reminder_opt_in_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "existing.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    chat_id INTEGER,
                    is_private INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    last_interaction_at TEXT NOT NULL,
                    last_checkin_at TEXT,
                    reminders_enabled INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                INSERT INTO users (telegram_id, username, started_at, last_interaction_at)
                VALUES (555, 'existing_member', '2026-01-01', '2026-01-01')
                """
            )
            connection.execute(
                """
                INSERT INTO users (
                    telegram_id, username, started_at, last_interaction_at,
                    reminders_enabled
                )
                VALUES (556, 'existing_opted_in', '2026-01-02', '2026-01-02', 1)
                """
            )
            connection.commit()
            connection.close()

            repository = Repository(path)
            member = repository.get_user(555)
            self.assertEqual(member["username"], "existing_member")
            self.assertEqual(member["zoom_class_reminders_enabled"], 0)
            self.assertEqual(member["reminders_stopped"], 0)
            self.assertEqual(member["sunday_checkin_opt_out"], 1)
            opted_in = repository.get_user(556)
            self.assertEqual(opted_in["sunday_checkin_opt_out"], 0)

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
class DailyCalendarSchedulerIntegrationTests(unittest.TestCase):
    def test_bot_dispatches_the_enabled_daily_brief_with_its_normal_scheduler_tick(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            brief_publisher = Mock()
            bot = SmartMoneyHubBot(
                FakeTelegramAPI(),
                str(Path(temp_dir) / "bot.sqlite3"),
                daily_calendar_brief=brief_publisher,
            )
            now = datetime(2026, 10, 28, 23, 5, tzinfo=timezone.utc)

            bot._dispatch_due_reminders(now)

            brief_publisher.dispatch.assert_called_once_with(now)


if __name__ == "__main__":
    unittest.main()