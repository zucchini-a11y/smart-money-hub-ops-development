import tempfile
import unittest
from pathlib import Path

from smart_money_hub_bot.group_knowledge import (
    addressed_group_question,
    archived_group_post,
    fts_query_terms,
    format_group_context,
    topic_update_from_message,
)
from smart_money_hub_bot.storage import Repository


class GroupKnowledgeHelperTests(unittest.TestCase):
    def test_archive_filters_commands_bots_and_redacts_identifiers(self) -> None:
        self.assertIsNone(
            archived_group_post(
                {
                    "message_id": 1,
                    "text": "/ask What is BOS?",
                    "from": {"id": 100, "is_bot": False},
                },
                configured_admin_id=100,
            )
        )
        self.assertIsNone(
            archived_group_post(
                {
                    "message_id": 2,
                    "text": "A lesson",
                    "from": {"id": 2, "is_bot": True},
                },
                configured_admin_id=100,
            )
        )

        record = archived_group_post(
            {
                "message_id": 3,
                "message_thread_id": 55,
                "date": 1_797_000_000,
                "text": "Email me at trader@example.com or @member 123456789.",
                "from": {"id": 200, "username": "member_name"},
            },
            configured_admin_id=100,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["source_status"], "unverified")
        self.assertEqual(record["thread_id"], 55)
        self.assertNotIn("member_name", record["content"])
        self.assertNotIn("example.com", record["content"])
        self.assertNotIn("123456789", record["content"])

    def test_poll_archive_includes_question_options_and_explanation(self) -> None:
        record = archived_group_post(
            {
                "message_id": 9,
                "poll": {
                    "id": "poll-one",
                    "question": "What confirms a setup?",
                    "options": [{"text": "A"}, {"text": "B"}],
                    "correct_option_id": 1,
                    "explanation": "Wait for confirmation.",
                },
                "from": {"id": 100},
            },
            configured_admin_id=100,
        )
        self.assertEqual(record["message_kind"], "poll")
        self.assertIn("Correct option: B", record["content"])
        self.assertIn("Wait for confirmation.", record["content"])

    def test_forum_topic_names_are_taken_only_from_topic_service_events(self) -> None:
        update = topic_update_from_message(
            {
                "message_id": 100,
                "message_thread_id": 100,
                "forum_topic_created": {"name": "  SMC Lessons  "},
            }
        )
        self.assertEqual(update, {"thread_id": 100, "topic_name": "SMC Lessons"})
        self.assertIsNone(topic_update_from_message({"text": "invented topic"}))

    def test_natural_question_requires_bot_mention_or_reply(self) -> None:
        self.assertIsNone(
            addressed_group_question(
                {"text": "What is liquidity?"},
                bot_username="SmartMoneyHubSignalsBot",
            )
        )
        self.assertEqual(
            addressed_group_question(
                {"text": "@SmartMoneyHubSignalsBot, what is liquidity?"},
                bot_username="@SmartMoneyHubSignalsBot",
            ),
            "what is liquidity?",
        )
        self.assertEqual(
            addressed_group_question(
                {
                    "text": "Can you explain this?",
                    "reply_to_message": {
                        "from": {
                            "is_bot": True,
                            "username": "SmartMoneyHubSignalsBot",
                        }
                    },
                },
                bot_username="SmartMoneyHubSignalsBot",
            ),
            "Can you explain this?",
        )

    def test_context_is_bounded_and_fts_tokens_are_safe(self) -> None:
        self.assertEqual(fts_query_terms('BOS " FVG --'), '"bos" OR "fvg"')
        context = format_group_context(
            [
                {
                    "topic_name": "Lessons",
                    "source_status": "unverified",
                    "content": "A" * 1500,
                }
                for _ in range(5)
            ]
        )
        self.assertLessEqual(len(context), 4)
        self.assertLessEqual(sum(len(item["content"]) for item in context), 3200)


class GroupKnowledgeStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "group.sqlite3"
        self.store = Repository(self.db)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_search_crosses_topics_and_edits_update_without_duplicates(self) -> None:
        self.store.record_education_group_topic(-1001, 10, "Structure")
        self.store.record_education_group_topic(-1001, 20, "Risk")
        self.store.record_education_group_post(
            chat_id=-1001,
            message_id=1,
            thread_id=10,
            topic_name="Structure",
            message_kind="text",
            content="A BOS is a break of a meaningful swing point.",
            source_status="configured_admin",
            posted_at="2026-10-24T10:00:00+00:00",
        )
        self.store.record_education_group_post(
            chat_id=-1001,
            message_id=2,
            thread_id=20,
            topic_name="Risk",
            message_kind="text",
            content="Risk management defines the loss before entry.",
            source_status="unverified",
            posted_at="2026-10-24T10:01:00+00:00",
        )
        matches = self.store.search_education_group_posts(
            -1001, "What is a break of structure?"
        )
        self.assertEqual([item["message_id"] for item in matches], [1])
        self.assertEqual(matches[0]["topic_name"], "Structure")

        self.store.record_education_group_post(
            chat_id=-1001,
            message_id=1,
            thread_id=10,
            topic_name="Structure",
            message_kind="text",
            content="Edited lesson explains the BOS and displacement.",
            source_status="configured_admin",
            posted_at="2026-10-24T10:00:00+00:00",
        )
        self.assertEqual(
            [
                item["message_id"]
                for item in self.store.search_education_group_posts(
                    -1001, "edited lesson displacement"
                )
            ],
            [1],
        )
        connection = self.store._connect()
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM education_group_posts WHERE chat_id = ?",
                (-1001,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 2)

    def test_group_question_deduplication_and_review_do_not_store_sender_ids(self) -> None:
        first_hash = self.store.record_education_group_question(
            chat_id=-1001,
            question="Why did @member 123456789 move stop loss?",
            topic="Risk management",
            thread_id=10,
            at="2026-10-24T10:00:00+00:00",
        )
        second_hash = self.store.record_education_group_question(
            chat_id=-1001,
            question="Why did @another 987654321 move stop loss?",
            topic="Risk management",
            thread_id=10,
            at="2026-10-24T10:05:00+00:00",
        )
        self.assertEqual(first_hash, second_hash)
        insights = self.store.education_group_insights(-1001)
        self.assertEqual(insights["open_question_count"], 2)
        question = insights["open_questions"][0]
        self.assertNotIn("member", question["question_preview"])
        self.assertNotIn("123456789", question["question_preview"])
        self.assertTrue(
            self.store.mark_education_group_question_reviewed(
                -1001, first_hash[:8]
            )
        )
        self.assertEqual(
            self.store.education_group_insights(-1001)["open_question_count"], 0
        )

    def test_quiz_insights_store_only_aggregate_poll_results(self) -> None:
        self.store.record_education_group_poll(
            poll_id="quiz-1",
            chat_id=-1001,
            message_id=8,
            thread_id=10,
            topic_name="Structure",
            question="Which is a possible BOS?",
            correct_option_id=0,
        )
        self.assertTrue(
            self.store.update_education_group_poll(
                {
                    "id": "quiz-1",
                    "total_voter_count": 6,
                    "options": [
                        {"voter_count": 4},
                        {"voter_count": 2},
                    ],
                }
            )
        )
        insights = self.store.education_group_insights(-1001)
        self.assertEqual(insights["poll_count"], 1)
        self.assertEqual(insights["votes_seen"], 6)


if __name__ == "__main__":
    unittest.main()
