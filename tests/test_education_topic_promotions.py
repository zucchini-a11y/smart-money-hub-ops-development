from __future__ import annotations

import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from smart_money_hub_bot.education_topic_promotions import (
    EducationTopicPromotionManager,
    EducationTopicPromotionStore,
)
from smart_money_hub_bot.channel_gemini import GeminiChannelGenerationError
from smart_money_hub_bot.telegram_api import TelegramAPIError
from smart_money_hub_bot.education_polls import (
    EXPECTED_EDUCATION_GROUP_ID,
    EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
)
from smart_money_hub_bot.admin_dashboard import AdminDashboard
from smart_money_hub_bot.storage import Repository

ADMIN_ID = 4242
BOT_ID = 9898
TOPIC_LINK = "https://t.me/c/3916437804/3/13"
NOW = datetime(2026, 10, 29, 11, 0, tzinfo=timezone.utc)
MONDAY_REVIEW = datetime(2026, 11, 2, 17, 55, tzinfo=timezone.utc)
MONDAY_PUBLISH = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
THURSDAY_REVIEW = datetime(2026, 11, 5, 17, 55, tzinfo=timezone.utc)
THURSDAY_PUBLISH = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)

_PROMO_OPENERS = (
    ("📚 BUILD A BETTER CHART ROUTINE", "Start with one clear question before drawing a zone."),
    ("🧠 LET PROCESS LEAD THE CHART", "A written plan can help keep attention on evidence, not excitement."),
    ("🎯 MAKE EVERY MARK ON YOUR CHART COUNT", "Choose what you are studying before you decide what a level means."),
    ("💬 LEARN, REVIEW, AND KEEP IMPROVING", "A thoughtful review can turn one chart observation into a useful lesson."),
)


class FakePromotionWriter:
    model = "gemini-3.5-flash-lite"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[str | Exception] = []

    def generate_promotion(
        self,
        *,
        recent_captions: list[dict[str, Any]],
        promotion_type: str = "manual",
        weekday: str | None = None,
        retry_feedback: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "recent_captions": list(recent_captions),
                "promotion_type": promotion_type,
                "weekday": weekday,
                "retry_feedback": retry_feedback,
            }
        )
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        opener, lead = _PROMO_OPENERS[(len(self.calls) - 1) % len(_PROMO_OPENERS)]
        return f"{opener}\n\n{lead}"


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.photos: list[dict[str, Any]] = []
        self.sent_results = 0
        self.channel_can_post = True
        self.group_can_manage_topics = True
        self.group_is_forum = True
        self.channel_id = EXPECTED_MARKET_ANALYSIS_CHANNEL_ID
        self.target_lookup_fails = False
        self.uncertain_group_send = False

    def get_me(self) -> dict[str, Any]:
        return {"id": BOT_ID, "username": "SmartMoneyHubSignalsBot"}

    def get_chat(self, chat_id: int) -> dict[str, Any]:
        if self.target_lookup_fails:
            raise TelegramAPIError("synthetic target verification failure")
        if chat_id == EXPECTED_EDUCATION_GROUP_ID:
            return {
                "id": chat_id,
                "type": "supergroup",
                "is_forum": self.group_is_forum,
                "title": "🧠 Smart Money Hub | Trading Education",
            }
        return {
            "id": self.channel_id,
            "type": "channel",
            "title": "Smart Money Hub",
            "invite_link": "https://t.me/+verifiedMarketAnalysisInvite",
        }

    def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        if user_id != BOT_ID:
            raise AssertionError("Unexpected bot user ID in permission check.")
        if chat_id == EXPECTED_EDUCATION_GROUP_ID:
            return {
                "status": "administrator",
                "can_manage_topics": self.group_can_manage_topics,
            }
        return {
            "status": "administrator",
            "can_post_messages": self.channel_can_post,
        }

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                **kwargs,
            }
        )

    def send_message_with_result(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.sent_results += 1
        record = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            **kwargs,
        }
        self.messages.append(record)
        if (
            self.uncertain_group_send
            and chat_id == EXPECTED_EDUCATION_GROUP_ID
        ):
            raise TelegramAPIError(
                "synthetic uncertain delivery", delivery_unknown=True
            )
        return {"message_id": 7000 + self.sent_results}

    def send_photo_with_result(
        self,
        chat_id: int,
        photo_file_id: str,
        *,
        caption: str,
        reply_markup: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.sent_results += 1
        self.photos.append(
            {
                "chat_id": chat_id,
                "photo": photo_file_id,
                "caption": caption,
                "reply_markup": reply_markup,
                **kwargs,
            }
        )
        return {"message_id": 7000 + self.sent_results}


class EducationTopicPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "promotions.sqlite"
        self.api = FakeTelegramAPI()
        self.writer = FakePromotionWriter()
        self.manager = self.make_manager()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_manager(
        self,
        *,
        topic_link: str = TOPIC_LINK,
        api: FakeTelegramAPI | None = None,
        channel_id: int = EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
        writer: Any | None = None,
    ) -> EducationTopicPromotionManager:
        return EducationTopicPromotionManager(
            api or self.api,
            self.database_path,
            admin_id=ADMIN_ID,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            market_channel_id=channel_id,
            topic_message_link=topic_link,
            writer=writer if writer is not None else self.writer,
        )

    def create_review(self) -> tuple[dict[str, Any], str]:
        handled = self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )
        self.assertTrue(handled)
        row = self.manager.store.get(1)
        self.assertIsNotNone(row)
        preview = self.api.messages[-1]
        self.assertEqual(preview["chat_id"], ADMIN_ID)
        self.assertIn("PRIVATE REVIEW — NOT PUBLISHED", preview["text"])
        self.assertEqual(row["status"], "review")
        callback = preview["reply_markup"]["inline_keyboard"][2][0]["callback_data"]
        return row, callback

    def test_admin_only_private_preview_has_exact_group_and_topic(self) -> None:
        self.manager.handle_callback(
            chat_id=99,
            admin_id=99,
            is_private=True,
            data="admin:education_topic_promo:create",
            now=NOW,
        )
        self.manager.handle_callback(
            chat_id=ADMIN_ID,
            admin_id=ADMIN_ID,
            is_private=False,
            data="admin:education_topic_promo:create",
            now=NOW,
        )
        self.assertEqual(self.api.messages, [])
        self.assertEqual(self.api.photos, [])

        row, _callback = self.create_review()
        self.assertEqual(row["group_chat_id"], -1003916437804)
        self.assertEqual(row["thread_id"], 3)
        self.assertEqual(row["topic_source_link"], TOPIC_LINK)
        self.assertEqual(row["group_title"], "🧠 Smart Money Hub | Trading Education")
        self.assertEqual(row["channel_title"], "Smart Money Hub")
        self.assertEqual(
            row["channel_link"], "https://t.me/+verifiedMarketAnalysisInvite"
        )
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

    def test_each_manual_start_uses_gemini_and_cancelled_copy_is_history(self) -> None:
        first, _approve_callback = self.create_review()
        cancel_callback = next(
            button.get("callback_data", "")
            for row in self.api.messages[-1]["reply_markup"]["inline_keyboard"]
            for button in row
            if button.get("callback_data", "").startswith(
                "admin:education_topic_promo:cancel:"
            )
        )
        self.manager.handle_callback(
            ADMIN_ID, ADMIN_ID, True, cancel_callback, now=NOW + timedelta(seconds=1)
        )
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW + timedelta(seconds=2),
        )

        self.assertEqual(len(self.writer.calls), 2)
        self.assertEqual(self.manager.store.get(int(first["id"]))["status"], "cancelled")
        self.assertEqual(self.writer.calls[0]["promotion_type"], "manual")
        self.assertTrue(
            any(
                item["body"] == first["body"] and item["status"] == "cancelled"
                for item in self.writer.calls[1]["recent_captions"]
            )
        )
        regenerated = self.manager.store.get(2)
        self.assertIsNotNone(regenerated)
        self.assertNotEqual(regenerated["body"], first["body"])
        self.assertFalse(
            any(
                message["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
                for message in self.api.messages
            )
        )

    def test_gemini_rate_limit_fails_closed_and_is_logged(self) -> None:
        class RateLimitedWriter:
            model = "gemini-3.5-flash-lite"

            def generate_promotion(self, **_kwargs):
                raise GeminiChannelGenerationError("gemini_rate_limit", 429)

        manager = self.make_manager(writer=RateLimitedWriter())
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )

        self.assertEqual(manager.store.recent(), [])
        self.assertIn("Gemini is rate-limited", self.api.messages[-1]["text"])
        self.assertFalse(
            any(
                message["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
                for message in self.api.messages
            )
        )
        with sqlite3.connect(self.database_path) as connection:
            event = connection.execute(
                """
                SELECT action, details FROM education_topic_promo_actions
                WHERE promotion_id IS NULL ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        self.assertEqual(event[0], "gemini_generation_failed")
        self.assertIn("gemini-3.5-flash-lite", event[1])
        self.assertIn("gemini_rate_limit", event[1])

    def test_invalid_gemini_caption_retries_once_then_saves_only_valid_result(self) -> None:
        valid_hook = (
            "🎯 PLAN BEFORE YOU FOLLOW A LEVEL\n\n"
            "Choose one clear question to guide your chart review today."
        )
        self.writer.responses = [
            "A plain headline without the required destinations.",
            valid_hook,
        ]
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )

        self.assertEqual(len(self.writer.calls), 2)
        self.assertIn("failed this check", self.writer.calls[1]["retry_feedback"])
        saved = self.manager.store.get(1)
        self.assertIsNotNone(saved)
        self.assertTrue(saved["body"].startswith(valid_hook))
        self.assertIn("Trade breakdowns are shared in the Education Group", saved["body"])
        self.assertIn("8:00 PM", saved["body"]) if False else None
        self.assertFalse(
            any(
                message["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
                for message in self.api.messages
            )
        )

    def test_two_invalid_gemini_captions_are_held_without_a_fallback(self) -> None:
        self.writer.responses = ["plain text", "still plain text"]
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )

        self.assertEqual(len(self.writer.calls), 2)
        self.assertEqual(self.manager.store.recent(), [])
        self.assertIn("failed content checks after two attempts", self.api.messages[-1]["text"])
        self.assertFalse(
            any(
                message["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
                for message in self.api.messages
            )
        )

    def test_scheduled_class_preview_uses_gemini_and_still_requires_approval(self) -> None:
        self.manager.store.set_schedule_enabled(
            True, admin_id=ADMIN_ID, at=NOW.isoformat()
        )
        self.manager.dispatch_due(MONDAY_REVIEW)

        self.assertEqual(len(self.writer.calls), 1)
        self.assertEqual(self.writer.calls[0]["promotion_type"], "scheduled_class")
        self.assertEqual(self.writer.calls[0]["weekday"], "Monday")
        saved = self.manager.store.get(1)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["status"], "review")
        self.assertIn("8:00 PM WAT", saved["body"])
        self.assertFalse(
            any(
                message["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
                for message in self.api.messages
            )
        )

    def test_only_explicit_approval_publishes_once_to_topic_three(self) -> None:
        row, approve_callback = self.create_review()
        self.assertEqual(
            sum(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages),
            0,
        )
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            approve_callback,
            now=NOW + timedelta(minutes=1),
        )
        group_posts = [
            item
            for item in self.api.messages
            if item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
        ]
        self.assertEqual(len(group_posts), 1)
        self.assertEqual(group_posts[0]["message_thread_id"], 3)
        self.assertEqual(group_posts[0]["parse_mode"], "HTML")
        buttons = group_posts[0]["reply_markup"]["inline_keyboard"]
        self.assertEqual(buttons[0][0]["url"], row["channel_link"])
        self.assertEqual(buttons[1][0]["text"], "Coach")
        self.assertEqual(buttons[1][0]["url"], "https://t.me/SmartMoneyHubSignalsBot")
        self.assertEqual(self.manager.store.get(row["id"])["status"], "published")

        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            approve_callback,
            now=NOW + timedelta(minutes=2),
        )
        self.assertEqual(
            sum(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages),
            1,
        )

    def test_repeated_create_callback_does_not_create_multiple_active_drafts(self) -> None:
        self.create_review()
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(len(self.manager.store.recent(10)), 1)
        self.assertEqual(
            sum(item["chat_id"] == ADMIN_ID for item in self.api.messages), 2
        )
        self.assertIn("still pending", self.api.messages[-1]["text"])

    def test_expired_review_is_held_and_never_published_late(self) -> None:
        row, _callback = self.create_review()
        self.manager.dispatch_due(NOW + timedelta(minutes=6))
        self.assertEqual(self.manager.store.get(row["id"])["status"], "expired")
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )
        self.assertIn("expired without approval", self.api.messages[-1]["text"])

    def test_cancel_prevents_publication(self) -> None:
        row, _approve_callback = self.create_review()
        version = row["review_version"]
        cancel_callback = (
            f"admin:education_topic_promo:cancel:{row['id']}:{version}"
        )
        self.manager.handle_callback(
            ADMIN_ID, ADMIN_ID, True, cancel_callback, now=NOW + timedelta(minutes=1)
        )
        self.assertEqual(self.manager.store.get(row["id"])["status"], "cancelled")
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

    def test_edit_escapes_html_and_old_review_button_cannot_approve_new_copy(self) -> None:
        row, old_approve = self.create_review()
        edit_callback = (
            f"admin:education_topic_promo:edit:{row['id']}:{row['review_version']}"
        )
        self.manager.handle_callback(
            ADMIN_ID, ADMIN_ID, True, edit_callback, now=NOW + timedelta(minutes=1)
        )
        self.assertTrue(
            self.manager.handle_admin_text(
                ADMIN_ID,
                ADMIN_ID,
                "A & <fresh> Market Analysis note.",
                is_private=True,
                now=NOW + timedelta(minutes=1, seconds=1),
            )
        )
        updated = self.manager.store.get(row["id"])
        self.assertEqual(updated["review_version"], row["review_version"] + 1)
        updated_preview = self.api.messages[-1]
        self.assertIn("A &amp; &lt;fresh&gt;", updated_preview["text"])
        self.manager.handle_callback(
            ADMIN_ID, ADMIN_ID, True, old_approve, now=NOW + timedelta(minutes=2)
        )
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )
        self.assertEqual(updated["status"], "review")

    def test_optional_photo_is_previewed_then_sent_to_same_forum_thread(self) -> None:
        row, _approve_callback = self.create_review()
        photo_request = (
            f"admin:education_topic_promo:photo:{row['id']}:{row['review_version']}"
        )
        self.manager.handle_callback(
            ADMIN_ID, ADMIN_ID, True, photo_request, now=NOW + timedelta(minutes=1)
        )
        self.assertTrue(
            self.manager.handle_admin_photo(
                ADMIN_ID,
                ADMIN_ID,
                [{"file_id": "synthetic-chart-file-id", "file_size": 1024}],
                is_private=True,
                now=NOW + timedelta(minutes=1, seconds=1),
            )
        )
        updated = self.manager.store.get(row["id"])
        self.assertEqual(updated["photo_file_id"], "synthetic-chart-file-id")
        preview = self.api.photos[-1]
        self.assertEqual(preview["chat_id"], ADMIN_ID)
        approve = preview["reply_markup"]["inline_keyboard"][2][0]["callback_data"]
        self.manager.handle_callback(
            ADMIN_ID, ADMIN_ID, True, approve, now=NOW + timedelta(minutes=2)
        )
        sent = self.api.photos[-1]
        self.assertEqual(sent["chat_id"], EXPECTED_EDUCATION_GROUP_ID)
        self.assertEqual(sent["message_thread_id"], 3)
        self.assertEqual(sent["photo"], "synthetic-chart-file-id")

    def test_wrong_topic_and_missing_channel_permission_fail_closed(self) -> None:
        wrong_topic = self.make_manager(topic_link="https://t.me/c/3916437804/4/13")
        wrong_topic.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )
        self.assertIsNone(wrong_topic.store.get(1))
        self.assertIn("not the approved Market Analysis topic", self.api.messages[-1]["text"])

        self.api.messages.clear()
        self.api.channel_can_post = False
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )
        self.assertIsNone(self.manager.store.get(1))
        self.assertIn("posting permission", self.api.messages[-1]["text"])
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

    def test_wrong_configured_channel_and_missing_group_rights_fail_closed(self) -> None:
        wrong_channel = self.make_manager(channel_id=-1009999999999)
        wrong_channel.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )
        self.assertIsNone(wrong_channel.store.get(1))
        self.assertIn("not configured", self.api.messages[-1]["text"])

        self.api.messages.clear()
        self.api.group_can_manage_topics = False
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )
        self.assertIsNone(self.manager.store.get(1))
        self.assertIn("forum group", self.api.messages[-1]["text"])

    def test_telegram_destination_lookup_failure_holds_before_preview(self) -> None:
        self.api.target_lookup_fails = True
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
            now=NOW,
        )
        self.assertIsNone(self.manager.store.get(1))
        self.assertIn("could not verify", self.api.messages[-1]["text"])

    def test_uncertain_send_is_not_retried(self) -> None:
        row, approve_callback = self.create_review()
        self.api.uncertain_group_send = True
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            approve_callback,
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(
            self.manager.store.get(row["id"])["status"], "delivery_unknown"
        )
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            approve_callback,
            now=NOW + timedelta(minutes=2),
        )
        self.assertEqual(
            sum(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages),
            1,
        )
        self.assertTrue(
            any("will not retry" in item["text"] for item in self.api.messages)
        )

    def test_dashboard_exposes_admin_button_and_routes_to_private_review(self) -> None:
        repository = Repository(str(self.database_path))
        dashboard = AdminDashboard(
            self.api,
            repository,
            ADMIN_ID,
            EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
            education_group_id=EXPECTED_EDUCATION_GROUP_ID,
            education_market_analysis_topic_link=TOPIC_LINK,
        )
        buttons = dashboard._dashboard_keyboard()["inline_keyboard"]
        self.assertTrue(
            any(
                button.get("callback_data") == "admin:education_topic_promo"
                for row in buttons
                for button in row
            )
        )
        dashboard.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            "admin:education_topic_promo:create",
        )
        self.assertEqual(self.api.messages[-1]["chat_id"], ADMIN_ID)
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

    def test_restart_marks_interrupted_send_unknown_without_retry(self) -> None:
        row, approve_callback = self.create_review()
        self.manager.store.claim_publish(
            row["id"],
            admin_id=ADMIN_ID,
            version=row["review_version"],
            at=(NOW + timedelta(minutes=1)).isoformat(),
        )
        restarted = self.make_manager()
        restarted.dispatch_due(NOW + timedelta(minutes=2))
        self.assertEqual(
            restarted.store.get(row["id"])["status"], "delivery_unknown"
        )
        restarted.dispatch_due(NOW + timedelta(minutes=3))
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )
        self.assertIn("will not retry", self.api.messages[-1]["text"])
        self.assertNotEqual(approve_callback, "")

    def test_recovery_persists_across_store_instances_and_frequency_is_configurable(self) -> None:
        store = EducationTopicPromotionStore(self.database_path)
        self.assertEqual(store.settings()["cooldown_days"], 14)
        self.assertTrue(
            store.set_cooldown(28, admin_id=ADMIN_ID, at=NOW.isoformat())
        )
        self.assertEqual(
            EducationTopicPromotionStore(self.database_path).settings()["cooldown_days"],
            28,
        )

    def test_existing_promotion_draft_survives_title_column_migration(self) -> None:
        store = EducationTopicPromotionStore(self.database_path)
        row, error = store.create_draft(
            body="A saved promotion draft.",
            group_chat_id=EXPECTED_EDUCATION_GROUP_ID,
            group_title="🧠 Smart Money Hub | Trading Education",
            thread_id=3,
            topic_source_link=TOPIC_LINK,
            channel_link="https://t.me/+verifiedMarketAnalysisInvite",
            channel_title="Smart Money Hub",
            bot_username="SmartMoneyHubSignalsBot",
            admin_id=ADMIN_ID,
            now=NOW,
        )
        self.assertIsNone(error)
        assert row is not None
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "ALTER TABLE education_topic_promotions DROP COLUMN group_title"
            )
            connection.execute(
                "ALTER TABLE education_topic_promotions DROP COLUMN channel_title"
            )

        migrated = EducationTopicPromotionStore(self.database_path).get(row["id"])
        self.assertEqual(migrated["body"], "A saved promotion draft.")
        self.assertEqual(migrated["group_title"], "Education group")
        self.assertEqual(migrated["channel_title"], "Market Analysis channel")

    def test_legacy_database_adds_schedule_columns_before_building_index(self) -> None:
        legacy_path = Path(self.temporary.name) / "legacy-promotions.sqlite"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript(
                """
                CREATE TABLE education_topic_promo_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cooldown_days INTEGER NOT NULL DEFAULT 14,
                    next_variant_index INTEGER NOT NULL DEFAULT 0,
                    last_published_at TEXT,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO education_topic_promo_settings (id, updated_at)
                VALUES (1, CURRENT_TIMESTAMP);
                CREATE TABLE education_topic_promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    body TEXT NOT NULL,
                    body_hash TEXT NOT NULL,
                    group_chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    topic_source_link TEXT NOT NULL,
                    channel_link TEXT NOT NULL,
                    bot_username TEXT NOT NULL,
                    status TEXT NOT NULL,
                    photo_file_id TEXT,
                    review_started_at TEXT NOT NULL,
                    review_deadline_at TEXT NOT NULL,
                    review_version INTEGER NOT NULL DEFAULT 1,
                    review_sent_at TEXT,
                    edit_admin_id INTEGER,
                    photo_upload_pending INTEGER NOT NULL DEFAULT 0,
                    photo_upload_admin_id INTEGER,
                    publish_attempts INTEGER NOT NULL DEFAULT 0,
                    telegram_message_id INTEGER,
                    published_at TEXT,
                    failure_category TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO education_topic_promotions (
                    body, body_hash, group_chat_id, thread_id, topic_source_link,
                    channel_link, bot_username, status, review_started_at,
                    review_deadline_at, created_at, updated_at
                ) VALUES (
                    'Preserve this old draft.', 'old-hash', -1003916437804, 3,
                    'https://t.me/c/3916437804/3/13',
                    'https://t.me/+verifiedMarketAnalysisInvite',
                    'SmartMoneyHubSignalsBot', 'review',
                    '2026-10-29T10:00:00+00:00',
                    '2026-10-29T10:05:00+00:00',
                    '2026-10-29T10:00:00+00:00',
                    '2026-10-29T10:00:00+00:00'
                );
                """
            )

        migrated_store = EducationTopicPromotionStore(legacy_path)
        saved = migrated_store.get(1)
        self.assertEqual(saved["body"], "Preserve this old draft.")
        self.assertEqual(saved["schedule_key"], None)
        self.assertEqual(saved["group_title"], "Education group")
        with sqlite3.connect(legacy_path) as connection:
            promotion_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(education_topic_promotions)"
                )
            }
            settings_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(education_topic_promo_settings)"
                )
            }
            index_names = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(education_topic_promotions)"
                )
            }
        self.assertIn("schedule_key", promotion_columns)
        self.assertIn("scheduled_for", promotion_columns)
        self.assertIn("approved_at", promotion_columns)
        self.assertIn("scheduled_enabled", settings_columns)
        self.assertIn("scheduled_variant_index", settings_columns)
        self.assertIn("education_topic_promo_schedule_key", index_names)

    def test_caption_validation_rejects_urls_and_unverified_profit_claims(self) -> None:
        self.assertIsNotNone(
            self.manager._validate_body("Join us at https://t.me/wrongchannel")
        )
        self.assertIsNotNone(
            self.manager._validate_body("We guarantee profits from every setup.")
        )
        self.assertIsNone(self.manager._validate_body("A fresh educational community note."))

    def test_monday_preview_is_private_and_approval_queues_for_1900_wat(self) -> None:
        self.manager.dispatch_due(MONDAY_REVIEW)
        row = self.manager.store.get(1)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["scheduled_for"], MONDAY_PUBLISH.isoformat())
        self.assertEqual(row["schedule_key"], "education-topic-promo:2026-11-02:monday")
        self.assertIn("MONDAY", row["body"])
        self.assertIn("8:00 PM WAT", row["body"])
        self.assertIn(
            "link will be posted in the channel when the class begins", row["body"]
        )
        self.assertIn("Trade breakdowns are shared in the Education Group", row["body"])
        self.assertNotIn("https://", row["body"])
        self.assertEqual(self.api.messages[-1]["chat_id"], ADMIN_ID)
        self.assertIn("Monday, 02 Nov 2026 at 07:00 PM WAT", self.api.messages[-1]["text"])
        self.assertEqual(
            len(
                [
                    item
                    for item in self.api.messages
                    if item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
                ]
            ),
            0,
        )

        keyboard = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        approve_callback = keyboard[2][0]["callback_data"]
        self.assertEqual(keyboard[2][0]["text"], "✅ Approve for 19:00 WAT")
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            approve_callback,
            now=MONDAY_REVIEW + timedelta(minutes=3),
        )
        self.assertEqual(self.manager.store.get(1)["approved_at"], (MONDAY_REVIEW + timedelta(minutes=3)).isoformat())
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

        self.manager.dispatch_due(MONDAY_PUBLISH)
        posts = [
            item
            for item in self.api.messages
            if item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
        ]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["message_thread_id"], 3)
        self.assertEqual(self.manager.store.get(1)["status"], "published")
        self.assertEqual(
            self.manager.store.schedule_run(row["schedule_key"])["status"], "published"
        )
        self.manager.dispatch_due(MONDAY_PUBLISH + timedelta(seconds=30))
        self.assertEqual(
            len(
                [
                    item
                    for item in self.api.messages
                    if item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
                ]
            ),
            1,
        )

    def test_thursday_copy_reminds_members_and_does_not_include_a_zoom_url(self) -> None:
        self.manager.dispatch_due(THURSDAY_REVIEW)
        row = self.manager.store.get(1)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("THURSDAY", row["body"])
        self.assertIn("8:00 PM WAT", row["body"])
        self.assertIn("link will be posted in the channel when the class begins", row["body"])
        self.assertNotIn("http", row["body"].casefold())
        self.assertNotIn("zoom.us", row["body"].casefold())
        self.assertEqual(row["group_chat_id"], EXPECTED_EDUCATION_GROUP_ID)
        self.assertEqual(row["thread_id"], 3)
        self.assertEqual(row["scheduled_for"], THURSDAY_PUBLISH.isoformat())

    def test_scheduled_post_expires_without_approval_and_is_not_sent_late(self) -> None:
        self.manager.dispatch_due(MONDAY_REVIEW)
        self.manager.dispatch_due(MONDAY_PUBLISH)
        row = self.manager.store.get(1)
        self.assertEqual(row["status"], "expired")
        self.assertEqual(
            self.manager.store.schedule_run(row["schedule_key"])["status"], "expired"
        )
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

    def test_approved_post_that_misses_publish_window_is_held_not_sent_late(self) -> None:
        self.manager.dispatch_due(MONDAY_REVIEW)
        row = self.manager.store.get(1)
        callback = self.api.messages[-1]["reply_markup"]["inline_keyboard"][2][0]["callback_data"]
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            callback,
            now=MONDAY_REVIEW + timedelta(minutes=2),
        )
        self.manager.dispatch_due(MONDAY_PUBLISH + timedelta(minutes=3))
        expired = self.manager.store.get(row["id"])
        self.assertEqual(expired["status"], "expired")
        self.assertEqual(expired["failure_category"], "approved_schedule_missed")
        self.assertEqual(
            self.manager.store.schedule_run(row["schedule_key"])["details"],
            "approved post missed its scheduled window",
        )
        self.assertTrue(
            any("missed its scheduled publication window" in item["text"] for item in self.api.messages)
        )
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

    def test_missed_review_window_is_recorded_once_without_a_late_preview(self) -> None:
        missed_at = MONDAY_PUBLISH + timedelta(minutes=1)
        self.manager.dispatch_due(missed_at)
        first_count = len(self.api.messages)
        self.manager.dispatch_due(missed_at + timedelta(seconds=30))
        self.assertEqual(len(self.api.messages), first_count)
        run = self.manager.store.schedule_run("education-topic-promo:2026-11-02:monday")
        self.assertEqual(run["status"], "missed")
        self.assertIn("review window missed", run["details"])
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

    def test_schedule_pause_blocks_previews_and_posts(self) -> None:
        self.manager.store.set_schedule_enabled(
            False, admin_id=ADMIN_ID, at=NOW.isoformat()
        )
        self.manager.dispatch_due(MONDAY_REVIEW)
        self.manager.dispatch_due(MONDAY_PUBLISH)
        self.assertIsNone(self.manager.store.get(1))
        self.assertEqual(self.api.messages, [])
        self.assertEqual(self.api.photos, [])

    def test_approved_scheduled_draft_recovers_after_restart_without_duplicate(self) -> None:
        self.manager.dispatch_due(MONDAY_REVIEW)
        row = self.manager.store.get(1)
        callback = self.api.messages[-1]["reply_markup"]["inline_keyboard"][2][0]["callback_data"]
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            True,
            callback,
            now=MONDAY_REVIEW + timedelta(minutes=2),
        )
        restarted = self.make_manager()
        restarted.dispatch_due(MONDAY_PUBLISH)
        restarted.dispatch_due(MONDAY_PUBLISH + timedelta(seconds=20))
        posts = [
            item
            for item in self.api.messages
            if item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID
        ]
        self.assertEqual(len(posts), 1)
        self.assertEqual(restarted.store.get(row["id"])["status"], "published")

    def test_scheduled_destination_verification_failure_holds_post(self) -> None:
        self.api.target_lookup_fails = True
        self.manager.dispatch_due(MONDAY_REVIEW)
        self.assertIsNone(self.manager.store.get(1))
        run = self.manager.store.schedule_run("education-topic-promo:2026-11-02:monday")
        self.assertEqual(run["status"], "failed")
        self.assertIn("destination verification failed", run["details"])
        self.assertTrue(any("destination verification failed" in m["text"] for m in self.api.messages))
        self.assertFalse(
            any(item["chat_id"] == EXPECTED_EDUCATION_GROUP_ID for item in self.api.messages)
        )

