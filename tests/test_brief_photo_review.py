from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

from smart_money_hub_bot.brief_photo_review import (
    NewsBriefPhotoPrompts,
    PHOTO_PROMPT_LEAD_SECONDS,
    append_verified_image_highlights,
    build_verified_image_evidence,
    send_brief_with_optional_photo,
)
from smart_money_hub_bot.news_brief_image_analysis import (
    GeminiNewsImageError,
    NewsImageAnalysis,
    VisibleCalendarEvent,
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

    def get_file(self, file_id):
        return {"file_path": "photos/admin-image.jpg"}

    def download_file(self, file_path, *, max_bytes):
        return b"test-image-bytes", "image/jpeg"


class FakeImageAnalyzer:
    def __init__(self, ids=("bea:event-1",)):
        self.ids = ids
        self.calls = []
        self.error = None
        self.events = (
            VisibleCalendarEvent(
                event_name="Personal Income and Outlays",
                currency="USD",
                time_text="8:30 AM",
            ),
        )

    def analyze(self, image_bytes, mime_type, verified_evidence):
        self.calls.append((image_bytes, mime_type, verified_evidence))
        if self.error is not None:
            raise self.error
        return NewsImageAnalysis(
            tuple(self.ids),
            self.events,
            "Thursday, October 29",
        )


class NewsBriefPhotoPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "photos.sqlite3"
        self.api = FakeAPI()
        self.evidence = [
            {
                "external_id": "bea:event-1",
                "source_name": "U.S. Bureau of Economic Analysis",
                "title": "Personal Income and Outlays",
                "source_url": "https://www.bea.gov/news/2026/personal-income-and-outlays",
                "release_date_text": "2026-10-29",
                "release_time_text": "08:30 AM ET",
                "event_at_utc": "2026-10-29T12:30:00+00:00",
                "timezone_status": "verified_explicit_utc_offset",
                "verification_status": "verified_schedule",
                "retrieved_at_utc": "2026-10-28T22:30:00+00:00",
            }
        ]
        self.image_analyzer = FakeImageAnalyzer()
        self.prompts = NewsBriefPhotoPrompts(
            self.api,
            self.database,
            admin_id=444,
            image_analyzer=self.image_analyzer,
        )
        self.target_date = date(2026, 10, 29)
        self.scheduled_at = datetime(2026, 10, 29, 0, 0, tzinfo=WAT)
        self.prompt_time = datetime(2026, 10, 28, 22, 30, tzinfo=timezone.utc)
        self.preview = "<b>Verified calendar report</b>"

    def _send_prompt(self):
        return self.prompts.send_prompt_if_due(
            "daily",
            self.target_date,
            self.scheduled_at,
            destination="Market Analysis channel",
            now=self.prompt_time,
            preview_content=self.preview,
            verified_evidence=self.evidence,
        )

    def test_prompt_is_private_idempotent_and_explicitly_optional(self) -> None:
        self.assertEqual(PHOTO_PROMPT_LEAD_SECONDS, 30 * 60)
        sent = self._send_prompt()
        self.assertTrue(sent)
        self.assertFalse(self._send_prompt())
        message = self.api.admin_messages[0]
        self.assertEqual(message["chat_id"], 444)
        self.assertIn("PREVIEW — NOT PUBLISHED", message["text"])
        self.assertIn("30 minutes", self.api.admin_messages[2]["text"])
        self.assertEqual(self.api.admin_messages[1]["text"], self.preview)
        self.assertIn("edit the news", self.api.admin_messages[2]["text"])
        keyboard = self.api.admin_messages[2]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual(keyboard[0]["callback_data"], "newsbrief:edit:daily:2026-10-29")
        self.assertEqual(keyboard[1]["callback_data"], "newsbrief:photo:daily:2026-10-29")
        self.assertEqual(
            self.api.admin_messages[2]["reply_markup"]["inline_keyboard"][1][0][
                "callback_data"
            ],
            "newsbrief:none:daily:2026-10-29",
        )

    def test_prompt_is_not_sent_before_the_thirty_minute_window(self) -> None:
        self.assertFalse(
            self.prompts.send_prompt_if_due(
                "daily",
                self.target_date,
                self.scheduled_at,
                destination="Market Analysis channel",
                now=datetime(2026, 10, 28, 22, 29, 59, tzinfo=timezone.utc),
                preview_content=self.preview,
                verified_evidence=self.evidence,
            )
        )
        self.assertFalse(self.api.admin_messages)

    def test_admin_can_replace_private_preview_and_scheduled_text_uses_it(self) -> None:
        self._send_prompt()
        self.assertTrue(
            self.prompts.handle_callback(
                "newsbrief:edit:daily:2026-10-29",
                actor_id=444,
                chat_id=444,
                is_private=True,
                now=datetime(2026, 10, 28, 22, 31, tzinfo=timezone.utc),
            )
        )
        self.assertTrue(self.prompts.has_text_edit_pending(444))
        replacement = "📊 Updated news & notes <for the admin>"
        self.assertTrue(
            self.prompts.handle_admin_text_edit(
                444,
                444,
                replacement,
                is_private=True,
                now=datetime(2026, 10, 28, 22, 32, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(self.prompts.has_text_edit_pending(444))
        self.assertEqual(
            self.api.admin_messages[-1]["text"],
            "📊 Updated news &amp; notes &lt;for the admin&gt;",
        )

        scheduled_report, photo_id = self.prompts.publication_media(
            "daily",
            self.target_date,
            "Fresh generated text",
            self.evidence,
            [],
            now=datetime(2026, 10, 28, 22, 33, tzinfo=timezone.utc),
        )
        self.assertEqual(
            scheduled_report,
            "📊 Updated news &amp; notes &lt;for the admin&gt;",
        )
        self.assertIsNone(photo_id)

    def test_photo_is_read_and_verified_before_updated_preview_and_persistence(self) -> None:
        self._send_prompt()
        self.assertTrue(
            self.prompts.handle_callback(
                "newsbrief:photo:daily:2026-10-29",
                actor_id=444,
                chat_id=444,
                is_private=True,
                now=datetime(2026, 10, 28, 22, 31, tzinfo=timezone.utc),
            )
        )
        self.assertTrue(
            self.prompts.handle_admin_photo(
                444,
                444,
                [{"file_id": "telegram-photo-file-id", "file_size": 1200}],
                is_private=True,
                now=datetime(2026, 10, 28, 22, 32, tzinfo=timezone.utc),
            )
        )
        self.assertEqual(
            self.image_analyzer.calls[0][2][0]["external_id"],
            "bea:event-1",
        )
        self.assertIn("RELATED EVENTS", self.api.admin_messages[-1]["text"])
        self.assertIn(
            "Personal Income and Outlays",
            self.api.admin_messages[-3]["text"],
        )
        self.assertIn(
            "image transcription, not a source record",
            self.api.admin_messages[-3]["text"],
        )

        restarted = NewsBriefPhotoPrompts(
            self.api,
            self.database,
            admin_id=444,
            image_analyzer=self.image_analyzer,
        )
        self.assertEqual(
            restarted.photo_file_id("daily", self.target_date),
            "telegram-photo-file-id",
        )
        report, photo_id = restarted.publication_media(
            "daily",
            self.target_date,
            self.preview,
            self.evidence,
            [
                {
                    "source_name": "BEA",
                    "status": "verified_schedule",
                    "checked_at_utc": "2026-10-28T22:32:00+00:00",
                }
            ],
            now=datetime(2026, 10, 28, 22, 33, tzinfo=timezone.utc),
        )
        self.assertEqual(photo_id, "telegram-photo-file-id")
        self.assertIn("RELATED EVENTS", report)
        restarted.mark_published(
            "daily",
            self.target_date,
            now=datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc),
        )
        self.assertIsNone(restarted.photo_file_id("daily", self.target_date))

    def test_non_admin_cannot_select_or_attach_a_photo(self) -> None:
        self._send_prompt()
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

    def test_unmatched_image_is_attached_without_changing_verified_brief(self) -> None:
        self._send_prompt()
        self.image_analyzer.ids = ("not-an-official-record",)
        self.image_analyzer.events = (
            VisibleCalendarEvent(
                event_name="ADP Non-Farm Employment Change",
                currency="USD",
                time_text="2:15pm",
                impact_marker="yellow crown icon",
            ),
        )
        self.prompts.handle_callback(
            "newsbrief:photo:daily:2026-10-29",
            actor_id=444,
            chat_id=444,
            is_private=True,
            now=datetime(2026, 10, 28, 22, 31, tzinfo=timezone.utc),
        )
        self.prompts.handle_admin_photo(
            444,
            444,
            [{"file_id": "telegram-photo-file-id"}],
            is_private=True,
            now=datetime(2026, 10, 28, 22, 32, tzinfo=timezone.utc),
        )
        self.assertEqual(
            self.prompts.photo_file_id("daily", self.target_date),
            "telegram-photo-file-id",
        )
        self.assertIn("none matched", self.api.admin_messages[-4]["text"])
        self.assertIn(
            "ADP Non-Farm Employment Change",
            self.api.admin_messages[-3]["text"],
        )
        report, photo_id = self.prompts.publication_media(
            "daily",
            self.target_date,
            self.preview,
            self.evidence,
            [
                {
                    "source_name": "BEA",
                    "status": "verified_schedule",
                    "checked_at_utc": "2026-10-28T22:32:00+00:00",
                }
            ],
            now=datetime(2026, 10, 28, 22, 33, tzinfo=timezone.utc),
        )
        self.assertEqual(report, self.preview)
        self.assertEqual(photo_id, "telegram-photo-file-id")

    def test_image_check_finishing_at_publication_time_is_not_attached(self) -> None:
        self._send_prompt()
        self.prompts.handle_callback(
            "newsbrief:photo:daily:2026-10-29",
            actor_id=444,
            chat_id=444,
            is_private=True,
            now=datetime(2026, 10, 28, 22, 59, 50, tzinfo=timezone.utc),
        )
        with patch(
            "smart_money_hub_bot.brief_photo_review.time.monotonic",
            side_effect=[100.0, 110.0],
        ):
            handled = self.prompts.handle_admin_photo(
                444,
                444,
                [{"file_id": "telegram-photo-file-id"}],
                is_private=True,
                now=datetime(2026, 10, 28, 22, 59, 55, tzinfo=timezone.utc),
            )
        self.assertTrue(handled)
        self.assertIsNone(self.prompts.photo_file_id("daily", self.target_date))
        self.assertIn("scheduled time arrived", self.api.admin_messages[-1]["text"])

    def test_missing_image_analyzer_still_attaches_photo_without_changing_text(self) -> None:
        self._send_prompt()
        without_analyzer = NewsBriefPhotoPrompts(
            self.api,
            self.database,
            admin_id=444,
        )
        without_analyzer.handle_callback(
            "newsbrief:photo:daily:2026-10-29",
            actor_id=444,
            chat_id=444,
            is_private=True,
            now=datetime(2026, 10, 28, 22, 31, tzinfo=timezone.utc),
        )
        handled = without_analyzer.handle_admin_photo(
            444,
            444,
            [{"file_id": "telegram-photo-file-id"}],
            is_private=True,
            now=datetime(2026, 10, 28, 22, 32, tzinfo=timezone.utc),
        )
        self.assertTrue(handled)
        self.assertEqual(
            without_analyzer.photo_file_id("daily", self.target_date),
            "telegram-photo-file-id",
        )
        self.assertIn(
            "image reading is unavailable",
            self.api.admin_messages[-3]["text"],
        )
        report, photo_id = without_analyzer.publication_media(
            "daily",
            self.target_date,
            self.preview,
            self.evidence,
            [],
            now=datetime(2026, 10, 28, 22, 33, tzinfo=timezone.utc),
        )
        self.assertEqual(report, self.preview)
        self.assertEqual(photo_id, "telegram-photo-file-id")

    def test_analysis_failure_is_not_reported_as_an_unreadable_picture(self) -> None:
        self._send_prompt()
        self.image_analyzer.error = GeminiNewsImageError("gemini_timeout")
        self.prompts.handle_callback(
            "newsbrief:photo:daily:2026-10-29",
            actor_id=444,
            chat_id=444,
            is_private=True,
            now=datetime(2026, 10, 28, 22, 31, tzinfo=timezone.utc),
        )

        self.prompts.handle_admin_photo(
            444,
            444,
            [{"file_id": "telegram-photo-file-id"}],
            is_private=True,
            now=datetime(2026, 10, 28, 22, 32, tzinfo=timezone.utc),
        )

        messages = [item["text"] for item in self.api.admin_messages]
        failure_message = next(
            message for message in messages if "image reading failed" in message
        )
        self.assertIn("does not mean the rows were unclear", failure_message)
        self.assertNotIn("couldn't read clear calendar rows", failure_message)

    def test_current_source_failure_keeps_admin_photo_but_drops_event_highlights(self) -> None:
        self._send_prompt()
        self.prompts.handle_callback(
            "newsbrief:photo:daily:2026-10-29",
            actor_id=444,
            chat_id=444,
            is_private=True,
            now=datetime(2026, 10, 28, 22, 31, tzinfo=timezone.utc),
        )
        self.prompts.handle_admin_photo(
            444,
            444,
            [{"file_id": "telegram-photo-file-id"}],
            is_private=True,
            now=datetime(2026, 10, 28, 22, 32, tzinfo=timezone.utc),
        )
        report, photo_id = self.prompts.publication_media(
            "daily",
            self.target_date,
            self.preview,
            self.evidence,
            [
                {
                    "source_name": "BEA",
                    "status": "unavailable",
                    "checked_at_utc": "2026-10-28T22:32:00+00:00",
                }
            ],
            now=datetime(2026, 10, 28, 22, 33, tzinfo=timezone.utc),
        )
        self.assertEqual(report, self.preview)
        self.assertEqual(photo_id, "telegram-photo-file-id")

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

    def test_verified_image_highlight_uses_concise_public_format(self) -> None:
        report = self.preview + "\n🔺 Impact: High"
        highlighted = append_verified_image_highlights(
            report,
            self.evidence,
            ["bea:event-1"],
        )
        self.assertIn("Personal Income and Outlays", highlighted)
        self.assertIn("Impact: High", highlighted)
        self.assertIn("13:30 WAT", highlighted)
        self.assertNotIn("Source:", highlighted)
        self.assertNotIn("Gemini", highlighted)
        self.assertNotIn("official", highlighted.casefold())
        self.assertNotIn("image-bytes", highlighted)
        self.assertLessEqual(len(highlighted.encode("utf-16-le")) // 2, 4096)

    def test_only_fresh_source_verified_records_can_be_sent_to_gemini(self) -> None:
        evidence = build_verified_image_evidence(
            "daily",
            self.target_date,
            self.evidence,
            [
                {
                    "source_name": "BEA",
                    "status": "verified_schedule",
                    "checked_at_utc": "2026-10-28T22:30:00+00:00",
                }
            ],
            now=datetime(2026, 10, 28, 22, 30, tzinfo=timezone.utc),
        )
        self.assertEqual([item["external_id"] for item in evidence], ["bea:event-1"])
        stale = build_verified_image_evidence(
            "daily",
            self.target_date,
            self.evidence,
            [
                {
                    "source_name": "BEA",
                    "status": "unavailable",
                    "checked_at_utc": "2026-10-28T22:30:00+00:00",
                }
            ],
            now=datetime(2026, 10, 28, 22, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(stale, [])

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
