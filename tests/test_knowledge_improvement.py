import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_money_hub_bot.bot import SmartMoneyHubBot
from smart_money_hub_bot.knowledge_approval import can_approve
from smart_money_hub_bot.knowledge_base import find_approved_answer
from smart_money_hub_bot.knowledge_drafting import (
    parse_research_material,
    validate_answer_draft,
)
from smart_money_hub_bot.knowledge_feedback import requires_review
from smart_money_hub_bot.knowledge_research import UnavailableResearchProvider
from smart_money_hub_bot.knowledge_versions import next_version_number
from smart_money_hub_bot.question_detection import detect_member_question
from smart_money_hub_bot.storage import Repository


class KnowledgeImprovementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "knowledge.sqlite3"
        self.store = Repository(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _interaction(self, telegram_id: int, question: str) -> int:
        return self.store.save_dm_coaching_interaction(
            telegram_id=telegram_id,
            username=f"private_user_{telegram_id}",
            question=question,
            coach_response="Local Coach response.",
            detected_topic="General SMC",
            mistakes_identified=[],
            lesson_learned="",
        )

    def _candidate(
        self, telegram_id: int, question: str, topic: str = "General"
    ) -> int:
        interaction_id = self._interaction(telegram_id, question)
        return self.store.record_knowledge_question(
            question=question,
            topic=topic,
            confidence="low",
            review_reason="Needs research.",
            interaction_id=interaction_id,
        )

    def test_question_detector_skips_chat_but_tracks_unknown_and_current_questions(self) -> None:
        self.assertIsNone(detect_member_question("Hey, nice one!", "Conversation"))
        self.assertIsNone(detect_member_question("Gold hit my TP today!", "General SMC"))
        self.assertIsNone(detect_member_question("How are you?", "Conversation"))

        unknown = detect_member_question("What is the latest leverage rule today?", "General SMC")
        self.assertIsNotNone(unknown)
        self.assertEqual(unknown.confidence, "low")
        self.assertEqual(unknown.topic, "Broker and Platform Questions")

        known = detect_member_question("What is liquidity?", "Liquidity / SSL / BSL")
        self.assertIsNotNone(known)
        self.assertEqual(known.confidence, "high")

    def test_duplicate_questions_are_grouped_without_member_identifiers_in_queue(self) -> None:
        first_id = self._candidate(101, "What is the leverage rule?", "Broker and Platform Questions")
        second_id = self._candidate(
            202, "Explain the leverage rule", "Broker and Platform Questions"
        )

        self.assertEqual(first_id, second_id)
        total, items = self.store.knowledge_queue("repeated")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["occurrence_count"], 2)
        self.assertNotIn("telegram_id", items[0])
        self.assertNotIn("username", items[0])
        detail = self.store.knowledge_item_detail(first_id)
        self.assertEqual(len(detail["examples"]), 2)
        self.assertNotIn("telegram_id", detail["examples"][0])
        self.assertNotIn("username", detail["examples"][0])

    def test_research_is_explicitly_unavailable_and_sources_are_validated(self) -> None:
        result = UnavailableResearchProvider().research("Question?")
        self.assertEqual(result.status, "awaiting_research")
        self.assertIn("No automated web research provider is configured", result.message)
        self.assertFalse(can_approve("A long enough answer about this topic.", ""))

        parsed = parse_research_material(
            "https://example.com/reference\n"
            "NOTE: Published 2026-10-01; applies to this product only.\n"
            "CONFLICT: Another source uses a different definition.\n"
            "REVIEW_BY: 2099-01-01"
        )
        self.assertEqual(parsed["source_urls"], "https://example.com/reference")
        self.assertIn("Conflicting information", parsed["research_notes"])
        self.assertEqual(parsed["review_after"], "2099-01-01")
        with self.assertRaises(ValueError):
            parse_research_material("http://example.com/not-secure")
        with self.assertRaises(ValueError):
            validate_answer_draft("Too short.")

    def test_approval_versions_retrieval_and_rejection_preserve_live_answer(self) -> None:
        item_id = self._candidate(301, "What is liquidity?", "Liquidity")
        answer_v1 = (
            "Liquidity refers to orders that may rest around obvious highs and lows. "
            "Those areas provide context, not a stand-alone reason to enter a trade."
        )
        answer_v2 = (
            "In this lesson, liquidity means potential orders around obvious highs and lows. "
            "A sweep is context, not a guaranteed reversal or automatic entry."
        )
        self.assertTrue(self.store.set_knowledge_draft(item_id, answer_v1))
        with self.assertRaises(ValueError):
            self.store.approve_knowledge_item(item_id, 900)
        self.assertTrue(
            self.store.set_knowledge_research(
                item_id,
                **parse_research_material("https://example.com/liquidity"),
            )
        )
        self.assertEqual(self.store.approve_knowledge_item(item_id, 900), 1)
        first = find_approved_answer(
            "Explain liquidity", "Liquidity", self.store.approved_knowledge_items()
        )
        self.assertEqual(first["approved_answer"], answer_v1)

        self.store.set_knowledge_draft(item_id, answer_v2)
        with self.assertRaises(ValueError):
            self.store.approve_knowledge_item(item_id, 900)
        self.store.set_knowledge_research(
            item_id,
            **parse_research_material(
                "https://example.com/liquidity-update\nREVIEW_BY: 2099-01-01"
            ),
        )
        self.assertEqual(self.store.approve_knowledge_item(item_id, 900), 2)

        rejected_draft = (
            "This unverified draft should not replace the currently approved answer "
            "because its claims do not match the sources."
        )
        self.store.set_knowledge_draft(item_id, rejected_draft)
        self.store.set_knowledge_research(
            item_id,
            **parse_research_material("https://example.com/unverified"),
        )
        self.assertTrue(self.store.reject_knowledge_draft(item_id))
        detail = self.store.knowledge_item_detail(item_id)
        self.assertEqual(detail["approved_answer"], answer_v2)
        self.assertEqual([version["version"] for version in detail["versions"]], [2, 1])
        self.assertEqual(next_version_number(detail["versions"]), 3)
        self.assertEqual(
            find_approved_answer(
                "What is liquidity?", "Liquidity", self.store.approved_knowledge_items()
            )["approved_answer"],
            answer_v2,
        )

    def test_feedback_is_owned_and_clearing_history_removes_its_question_example(self) -> None:
        item_id = self._candidate(401, "What does CHOCH mean?", "BOS, CHOCH and MSS")
        interaction_id = self._interaction(401, "A second question?")
        # Only interactions linked to a genuine Coach question accept knowledge feedback.
        self.assertFalse(self.store.record_knowledge_feedback(999, interaction_id, "unhelpful"))
        connection = self.store._connect()
        try:
            stored_interaction = connection.execute(
                "SELECT interaction_id FROM knowledge_item_examples WHERE item_id = ?",
                (item_id,),
            ).fetchone()["interaction_id"]
        finally:
            connection.close()
        self.assertFalse(self.store.record_knowledge_feedback(999, stored_interaction, "unhelpful"))
        self.assertTrue(self.store.record_knowledge_feedback(401, stored_interaction, "unhelpful"))
        self.assertTrue(requires_review("unhelpful"))
        self.assertEqual(
            self.store.knowledge_item_detail(item_id)["status"], "awaiting_research"
        )
        self.assertEqual(self.store.clear_dm_coaching_history(401), 2)
        self.assertIsNone(self.store.knowledge_item_detail(item_id))
        self.assertEqual(self.store.knowledge_admin_summary()["unhelpful"], 0)

    def test_feedback_buttons_and_admin_knowledge_flow_are_private(self) -> None:
        api = _FakeTelegramAPI()
        admin_id = 8008
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_ID": str(admin_id)}):
            bot = SmartMoneyHubBot(api, str(self.database_path))

        member_id = 505
        bot._answer_coach_message(
            member_id, member_id, "member", "What is the latest leverage rule today?"
        )
        member_reply = api.messages[-1]
        self.assertIn("I don’t have a vetted answer", member_reply["text"])
        feedback_buttons = member_reply["reply_markup"]["inline_keyboard"][0]
        feedback_data = feedback_buttons[1]["callback_data"]
        self.assertTrue(feedback_data.startswith("coach:feedback:"))
        item_id = self.store.knowledge_queue("awaiting_research")[1][0]["id"]

        bot.handle_update(_callback_update(member_id, feedback_data))
        self.assertIn("flagged", api.messages[-1]["text"])
        self.assertEqual(
            Repository(self.database_path).knowledge_item_detail(item_id)["unhelpful_count"],
            1,
        )

        _send_message(bot, admin_id, "/admin")
        self.assertTrue(any("Knowledge Improvement" in message["text"] for message in api.messages))
        _send_callback(bot, admin_id, "admin:knowledge")
        _send_callback(bot, admin_id, "admin:knowledge:list:awaiting_research")
        _send_callback(bot, admin_id, f"admin:knowledge:item:{item_id}")
        self.assertNotIn("member", api.messages[-1]["text"])
        self.assertIn("Anonymized question examples", api.messages[-1]["text"])

        _send_callback(bot, admin_id, f"admin:knowledge:draft:{item_id}")
        answer = (
            "Broker leverage limits depend on the provider, jurisdiction, and product. "
            "Check the broker's current official terms before relying on a limit."
        )
        _send_message(bot, admin_id, answer)
        _send_callback(bot, admin_id, f"admin:knowledge:sources:{item_id}")
        _send_message(
            bot,
            admin_id,
            "https://example.com/broker-terms\n"
            "NOTE: Rules vary by jurisdiction; check publication date.\n"
            "REVIEW_BY: 2099-01-01",
        )
        _send_callback(bot, admin_id, f"admin:knowledge:approve:{item_id}")
        self.assertIn("version 1", api.messages[-1]["text"])

        bot._answer_coach_message(
            member_id, member_id, "member", "What is the latest leverage rule today?"
        )
        self.assertIn(answer, api.messages[-1]["text"])

        stranger = 606
        _send_callback(bot, stranger, f"admin:knowledge:retire:{item_id}")
        self.assertIn("restricted", api.messages[-1]["text"].lower())
        self.assertEqual(
            Repository(self.database_path).knowledge_item_detail(item_id)["status"],
            "approved",
        )


class _FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.answered_callbacks: list[str] = []

    def get_webhook_info(self) -> dict[str, object]:
        return {}

    def get_me(self) -> dict[str, object]:
        return {"username": "KnowledgeTestBot"}

    def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        self.messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )

    def answer_callback_query(self, callback_query_id: str, text=None, show_alert=False) -> None:
        self.answered_callbacks.append(callback_query_id)


def _send_message(bot: SmartMoneyHubBot, telegram_id: int, text: str) -> None:
    bot.handle_update(
        {
            "message": {
                "text": text,
                "from": {
                    "id": telegram_id,
                    "username": "test_admin",
                    "first_name": "Test",
                },
                "chat": {"id": telegram_id, "type": "private"},
            }
        }
    )


def _callback_update(telegram_id: int, data: str) -> dict[str, object]:
    return {
        "callback_query": {
            "id": f"callback-{telegram_id}",
            "from": {"id": telegram_id, "username": "test_user"},
            "message": {
                "message_id": 1,
                "chat": {"id": telegram_id, "type": "private"},
            },
            "data": data,
        }
    }


def _send_callback(bot: SmartMoneyHubBot, telegram_id: int, data: str) -> None:
    bot.handle_update(_callback_update(telegram_id, data))


if __name__ == "__main__":
    unittest.main()
