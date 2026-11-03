import tempfile
import unittest
from pathlib import Path

from smart_money_hub_bot.curriculum_retrieval import (
    curriculum_source_summary,
    episode_unavailable_reply,
    requested_episode_number,
    retrieve_curriculum_context,
)
from smart_money_hub_bot.storage import Repository


class CurriculumRetrievalTests(unittest.TestCase):
    def test_retrieves_an_actual_lesson_card_with_provenance(self) -> None:
        results = retrieve_curriculum_context("Explain a POI")

        self.assertTrue(results)
        self.assertEqual(results[0]["title"], "Points of Interest")
        self.assertEqual(results[0]["source_type"], "built_in_lesson_card")
        self.assertIn("not", results[0]["content"].casefold())

    def test_episode_parser_handles_zero_padding_and_ignores_longer_number(self) -> None:
        self.assertEqual(requested_episode_number("Explain Episode 01"), 1)
        self.assertEqual(requested_episode_number("Episode #12, please"), 12)
        self.assertIsNone(requested_episode_number("Episode 120"))

    def test_missing_episode_does_not_claim_general_card_is_episode_content(self) -> None:
        related = retrieve_curriculum_context("Episode 01 points of interest")
        response = episode_unavailable_reply(1, related)

        self.assertIn("actual Episode 01 lesson indexed", response)
        self.assertIn("not a summary of Episode 01", response)
        self.assertIn("Share the episode text or a screenshot", response)

    def test_source_status_reports_only_in_app_resources(self) -> None:
        self.assertEqual(
            curriculum_source_summary(),
            {
                "lesson_cards": 10,
                "episode_records": 0,
                "external_documents": 0,
            },
        )

    def test_episode_archive_lookup_is_exact_and_group_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Repository(Path(temp_dir) / "coach.sqlite3")
            for chat_id, message_id, text, source in (
                (101, 1, "Episode 01 — market structure lesson", "configured_admin"),
                (101, 2, "Episode 10 — risk management lesson", "configured_admin"),
                (101, 3, "Episode 01 — unverified member message", "unverified"),
                (202, 4, "Episode 01 — other group", "configured_admin"),
            ):
                store.record_education_group_post(
                    chat_id=chat_id,
                    message_id=message_id,
                    thread_id=None,
                    topic_name="Lessons",
                    message_kind="text",
                    content=text,
                    source_status=source,
                    posted_at="2026-11-01T10:00:00+00:00",
                )

            found = store.education_episode_posts(101, 1)
            summary = store.education_group_archive_summary(101)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["message_id"], 1)
        self.assertEqual(summary["episode_numbers"], [1, 10])
        self.assertEqual(summary["post_count"], 3)

    def test_provider_health_keeps_only_aggregates_and_latest_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Repository(Path(temp_dir) / "coach.sqlite3")
            store.record_coach_provider_event(
                feature="chart_image",
                outcome="failure",
                failure_kind="http_timeout",
                http_status=504,
                provider_status="DEADLINE_EXCEEDED",
                at="2026-11-01T10:00:00+00:00",
            )
            store.record_coach_provider_event(
                feature="coach_text",
                outcome="success",
                at="2026-11-01T10:01:00+00:00",
            )

            result = store.coach_provider_health(days=7)
            connection = store._connect()
            try:
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(coach_provider_events)"
                    )
                }
            finally:
                connection.close()

        self.assertEqual(result["coach_text_success"], 1)
        self.assertEqual(result["chart_image_failure"], 1)
        self.assertEqual(result["latest_failure"]["failure_kind"], "http_timeout")
        self.assertNotIn("message", columns)
        self.assertNotIn("telegram_id", columns)
        self.assertNotIn("prompt", columns)


if __name__ == "__main__":
    unittest.main()
