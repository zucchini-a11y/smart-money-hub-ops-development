from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from smart_money_hub_bot.brief_photo_review import (
    NewsBriefPhotoPrompts,
    send_brief_with_optional_photo,
)

WAT = ZoneInfo("Africa/Lagos")


class FakeAPI:
    def __init__(self) -> None:
        self.admin_messages: list[dict] = []
        self.sent_text: list[dict] = []
        self.sent_photos: list[dict] = []

    def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.admin_messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )

    def send_message_with_result(self, chat_id, text, **kwargs):
        self.sent_text.append({"chat_id": chat_id, "text": text, **kwargs})
        return {"message_id": 81}

    def send_photo_with_result(self, chat_id, photo, **kwargs):
        self.sent_photos.append({"chat_id": chat_id, "photo": photo, **kwargs})
        return {"message_id": 80}


class NewsBriefPhotoPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "photos.sqlite3"
        self.api = FakeAPI()
        self.prompts = NewsBriefPhotoPrompts(
            self.api, self.database, admin_id=444
        )
        self.target_date = date(2026, 10, 29)
        self.scheduled_at = datetime(2026, 10, 29, 0, 0, tzinfo=WAT)
        self.prompt_time = datetime(2026, 10, 28, 22, 55, tzinfo=timezone.utc)

    def test_prompt_is_private_idempotent_and_explicitly_optional(self) -> None:
        sent = self.prompts.send_prompt_if_due(
            "daily",
            self.target_date,
            self.scheduled_at,
            destination="Market Analysis channel",
            now=self.prompt_time,
        )
        self.assertTrue(sent)
        self.assertFalse(
            self.prompts.send_prompt_if_due(
                "daily",
                self.target_date,
                self.scheduled_at,
                destination="Market Analysis channel",
                now=self.prompt_time,
            )
        )
        message = self.api.admin_messages[0]
        self.assertEqual(message["chat_id"], 444)
        self.assertIn("text-only", message["text"])
        keyboard = message["reply_markup"]["inline_keyboard"][0]
        self.assertEqual(keyboard[0]["callback_data"], "newsbrief:photo:daily:2026-10-29")
        self.assertEqual(keyboard[1]["callback_data"], "newsbrief:none:daily:2026-10-29")

    def test_prompt_is_not_sent_before_the_five_minute_window(self) -> None:
        self.assertFalse(
            self.prompts.send_prompt_if_due(
                "daily",
                self.target_date,
                self.scheduled_at,
                destination="Market Analysis channel",
                now=datetime(2026, 10, 28, 22, 54, 59, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(self.api.admin_messages)

    def test_selected_photo_persists_across_restart(self) -> None:
        self.prompts.send_prompt_if_due(
            "daily",
            self.target_date,
            self.scheduled_at,
            destination="Market Analysis channel",
            now=self.prompt_time,
        )
        self.assertTrue(
            self.prompts.handle_callback(
                "newsbrief:photo:daily:2026-10-29",
                actor_id=444,
                chat_id=444,
                is_private=True,
                now=datetime(2026, 10, 28, 22, 56, tzinfo=timezone.utc),
            )
        )
        self.assertTrue(
            self.prompts.handle_admin_photo(
                444,
                444,
                [{"file_id": "telegram-photo-file-id"}],
                is_private=True,
                now=datetime(2026, 10, 28, 22, 57, tzinfo=timezone.utc),
            )
        )

        restarted = NewsBriefPhotoPrompts(
            self.api, self.database, admin_id=444
        )
        self.assertEqual(
            restarted.photo_file_id("daily", self.target_date),
            "telegram-photo-file-id",
        )
        restarted.mark_published(
            "daily",
            self.target_date,
            now=datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc),
        )
        self.assertIsNone(restarted.photo_file_id("daily", self.target_date))

    def test_non_admin_cannot_select_or_attach_a_photo(self) -> None:
        self.prompts.send_prompt_if_due(
            "daily",
            self.target_date,
            self.scheduled_at,
            destination="Market Analysis channel",
            now=self.prompt_time,
        )
        self.assertTrue(
            self.prompts.handle_callback(
                "newsbrief:photo:daily:2026-10-29",
                actor_id=999,
                chat_id=999,
                is_private=True,
                now=self.prompt_time,
            )
        )
        self.assertFalse(
            self.prompts.handle_admin_photo(
                999,
                999,
                [{"file_id": "not-authorized"}],
                is_private=True,
                now=self.prompt_time,
            )
        )
        self.assertIsNone(self.prompts.photo_file_id("daily", self.target_date))

    def test_no_photo_still_sends_the_scheduled_text_brief(self) -> None:
        message_id, photo_status = send_brief_with_optional_photo(
            self.api,
            -1001234567890,
            "<b>Verified report</b>",
            photo_file_id=None,
            photo_caption="Daily news",
        )
        self.assertEqual(message_id, 81)
        self.assertEqual(photo_status, "not_requested")
        self.assertEqual(self.api.sent_text[0]["text"], "<b>Verified report</b>")
        self.assertEqual(self.api.sent_photos, [])

    def test_optional_photo_is_attached_without_delaying_text(self) -> None:
        message_id, photo_status = send_brief_with_optional_photo(
            self.api,
            -1001234567890,
            "Weekly report",
            photo_file_id="telegram-file",
            message_thread_id=3,
            photo_caption="Weekly news",
        )
        self.assertEqual(message_id, 81)
        self.assertEqual(photo_status, "sent")
        self.assertEqual(self.api.sent_photos[0]["message_thread_id"], 3)
        self.assertEqual(self.api.sent_text[0]["message_thread_id"], 3)
