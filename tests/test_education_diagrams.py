from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smart_money_hub_bot.education_diagrams import EducationDiagramManager
from smart_money_hub_bot.storage import Repository


class FakeAPI:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict | None]] = []

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        **kwargs,
    ) -> None:
        self.messages.append((chat_id, text, reply_markup))


class EducationDiagramManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.store = Repository(self.database_path)
        self.api = FakeAPI()
        self.admin_id = 123456
        self.manager = EducationDiagramManager(
            self.api, self.store, self.admin_id
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_only_admin_can_start_or_upload_a_diagram(self) -> None:
        self.manager.handle_callback(
            99, 99, True, "admin:education_diagrams:add"
        )
        self.assertFalse(self.manager.is_upload_pending(99))
        self.assertFalse(
            self.manager.handle_admin_photo(
                99,
                99,
                [{"file_id": "untrusted"}],
                caption="BOS | structure",
                is_private=True,
            )
        )
        self.assertEqual(self.store.education_diagrams(), [])

    def test_admin_upload_is_saved_and_retrieved_by_topic(self) -> None:
        self.manager.handle_callback(
            self.admin_id,
            self.admin_id,
            True,
            "admin:education_diagrams:add",
        )
        handled = self.manager.handle_admin_photo(
            self.admin_id,
            self.admin_id,
            [
                {"file_id": "small-image"},
                {"file_id": "best-image"},
            ],
            caption=(
                "BOS | BOS, break of structure, market structure | "
                "A close beyond a relevant swing."
            ),
            is_private=True,
        )
        self.assertTrue(handled)
        saved = self.store.education_diagrams()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["photo_file_id"], "best-image")
        self.assertEqual(saved[0]["title"], "BOS")
        match = self.manager.diagram_for_question(
            "Can you explain a break of structure?"
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["id"], saved[0]["id"])
        self.assertIn("Saved “BOS”", self.api.messages[-1][1])

    def test_unmatched_question_does_not_receive_a_diagram(self) -> None:
        self.store.add_education_diagram(
            title="CHoCH",
            tags="CHoCH, change of character",
            description="Possible shift only.",
            photo_file_id="choch-file",
            admin_telegram_id=self.admin_id,
        )
        self.assertIsNone(
            self.manager.diagram_for_question(
                "How should I manage my risk?"
            )
        )
        self.assertIsNotNone(
            self.manager.diagram_for_question(
                "What does change of character mean?"
            )
        )

    def test_hiding_diagram_keeps_record_but_stops_matching(self) -> None:
        diagram_id = self.store.add_education_diagram(
            title="FVG",
            tags="FVG, fair value gap",
            description="Educational diagram",
            photo_file_id="fvg-file",
            admin_telegram_id=self.admin_id,
        )
        self.manager.handle_callback(
            self.admin_id,
            self.admin_id,
            True,
            f"admin:education_diagrams:hide:{diagram_id}",
        )
        self.assertEqual(self.store.education_diagrams(), [])
        all_rows = self.store.education_diagrams(active_only=False)
        self.assertEqual(len(all_rows), 1)
        self.assertEqual(all_rows[0]["active"], 0)
        self.assertIsNone(self.store.matching_education_diagram("Explain FVG"))


if __name__ == "__main__":
    unittest.main()
