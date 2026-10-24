from __future__ import annotations

from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from smart_money_hub_bot.channel_content import (
    CHANNEL_CONTENT_CATEGORIES,
    PROMO_FEATURES,
    validate_channel_post,
)
from smart_money_hub_bot.channel_gemini import (
    ChannelDraft,
    GeminiChannelGenerationError,
)
from smart_money_hub_bot.channel_posting import ChannelPostManager
from smart_money_hub_bot.storage import Repository
from smart_money_hub_bot.telegram_api import TelegramAPIError

TZ = ZoneInfo("Africa/Lagos")
ADMIN_ID = 777
CHANNEL_ID = -1004481197912


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.channel_messages: list[dict] = []
        self.channel_attempts: list[dict] = []
        self.send_failures: list[TelegramAPIError] = []
        self.chat: dict = {
            "id": CHANNEL_ID,
            "type": "channel",
            "title": "Smart Money Hub Market Analysis",
        }
        self.member: dict = {
            "status": "administrator",
            "can_post_messages": True,
        }
        self.bot_info: dict = {
            "id": 4242,
            "username": "SmartMoneyHubSignalsBot",
        }

    def get_me(self) -> dict:
        return self.bot_info

    def get_chat(self, chat_id: int) -> dict:
        assert chat_id == CHANNEL_ID
        return self.chat

    def get_chat_member(self, chat_id: int, user_id: int) -> dict:
        assert chat_id == CHANNEL_ID
        assert user_id == self.bot_info["id"]
        return self.member

    def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        self.messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )

    def send_message_with_result(
        self, chat_id: int, text: str, reply_markup=None
    ) -> dict:
        self.channel_attempts.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )
        if self.send_failures:
            raise self.send_failures.pop(0)
        result = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "message_id": 9000 + len(self.channel_attempts),
        }
        self.channel_messages.append(result)
        return result


class FakeChannelWriter:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.failures: list[GeminiChannelGenerationError] = []

    def generate(self, **kwargs) -> ChannelDraft:
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        category = kwargs["preferred_category"]
        content = (
            f"{category.replace('_', ' ').title()} reflection for "
            f"{kwargs['schedule_date']}: focus on process, evidence, and patience."
        )
        if kwargs.get("promo_due"):
            username = kwargs["promo_username"]
            content += (
                f"\n\n{PROMO_FEATURES[0]}\n"
                f"Open @{username} and tap Start: https://t.me/{username}\n"
                "The learning Coach is separate from PRO Signals."
            )
        content += "\n\nNO CONFIRMATION, NO ENTRY."
        return ChannelDraft(category=category, content=content)


def local_time(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


class ChannelPostingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = Repository(
            f"{self.temp_dir.name}/channel-posts.sqlite3"
        )
        self.api = FakeTelegramAPI()
        self.writer = FakeChannelWriter()
        self.manager = ChannelPostManager(
            self.api,
            self.store,
            ADMIN_ID,
            CHANNEL_ID,
            channel_writer=self.writer,
        )

    def test_daily_schedule_sends_one_post_after_admin_preview(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        monday_preview = datetime(2026, 10, 26, 8, 15, tzinfo=ZoneInfo("UTC"))
        manager.dispatch_due(monday_preview)

        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        assert post["schedule_time"] == "10:00"
        assert post["preview_sent_at"] is not None
        assert api.messages[-1]["chat_id"] == ADMIN_ID
        assert api.channel_messages == []

        manager.dispatch_due(local_time(26, 10))
        manager.dispatch_due(local_time(26, 10, 1))

        saved = store.get_scheduled_channel_post("2026-10-26")
        assert saved is not None
        assert saved["status"] == "published"
        assert saved["destination_chat_id"] == CHANNEL_ID
        assert saved["telegram_message_id"] == 9001
        assert len(api.channel_messages) == 1
        assert {message["chat_id"] for message in api.channel_attempts} == {CHANNEL_ID}

    def test_lagos_timezone_and_category_rotation_are_persistent(self) -> None:
        store, manager = self.store, self.manager
        utc_preview = datetime(2026, 10, 26, 8, 0, tzinfo=ZoneInfo("UTC"))
        manager.dispatch_due(utc_preview)

        first = store.get_scheduled_channel_post("2026-10-26")
        assert first is not None
        assert first["requested_category"] == CHANNEL_CONTENT_CATEGORIES[0]

        manager.dispatch_due(local_time(27, 9))
        second = store.get_scheduled_channel_post("2026-10-27")
        assert second is not None
        assert second["requested_category"] == CHANNEL_CONTENT_CATEGORIES[1]
        assert second["category"] == "weekly_market_recap_evergreen"
        assert "NO CONFIRMATION, NO ENTRY." in second["content"]
        assert "currently trading at" not in second["content"].casefold()

        reopened = Repository(store.database_path)
        settings = reopened.get_channel_posting_settings()
        assert settings["next_category_index"] == 2

    def test_weekend_promotion_is_integrated_and_links_to_verified_bot(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        friday_evening = local_time(23, 18)
        manager.dispatch_due(friday_evening)

        saturday_post = store.get_scheduled_channel_post("2026-10-24")
        assert saturday_post is not None
        assert saturday_post["is_promo"] == 1
        assert "@SmartMoneyHubSignalsBot" in saturday_post["content"]
        assert "https://t.me/SmartMoneyHubSignalsBot" in saturday_post["content"]
        assert "tap Start" in saturday_post["content"]
        assert "separate from PRO Signals" in saturday_post["content"]
        assert validate_channel_post(
            saturday_post["content"],
            is_promo=True,
            bot_username="SmartMoneyHubSignalsBot",
        ) is None
        assert api.channel_messages == []

        manager.dispatch_due(local_time(24, 10))
        published = api.channel_messages[-1]
        assert published["chat_id"] == CHANNEL_ID
        assert published["reply_markup"]["inline_keyboard"][0][0]["url"] == (
            "https://t.me/SmartMoneyHubSignalsBot"
        )

    def test_sunday_preview_is_saturday_evening_and_publish_is_sunday_at_six(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(local_time(24, 18))

        sunday_post = store.get_scheduled_channel_post("2026-10-25")
        assert sunday_post is not None
        assert sunday_post["schedule_time"] == "18:00"
        assert sunday_post["preview_sent_at"] is not None
        assert not api.channel_messages
        assert "2026-10-25 at 18:00 WAT" in api.messages[-1]["text"]

        manager.dispatch_due(local_time(25, 18))
        published = store.get_scheduled_channel_post("2026-10-25")
        assert published is not None
        assert published["status"] == "published"
        assert len(api.channel_messages) == 1

    def test_missed_same_day_publish_time_does_not_create_a_late_draft(self) -> None:
        self.manager.dispatch_due(local_time(24, 13))
        self.assertIsNone(self.store.get_scheduled_channel_post("2026-10-24"))
        self.assertEqual(self.writer.calls, [])
        self.assertEqual(self.api.channel_messages, [])

    def test_gemini_rate_limit_holds_weekend_post_without_local_publication(self) -> None:
        self.writer.failures.append(
            GeminiChannelGenerationError("gemini_rate_limit", 429)
        )

        self.manager.dispatch_due(local_time(23, 18))

        post = self.store.get_scheduled_channel_post("2026-10-24")
        assert post is not None
        assert post["status"] == "failed"
        assert post["failure_category"] == "gemini_rate_limit"
        assert post["content"] == ""
        assert not self.api.channel_messages
        assert any(
            "gemini_rate_limit" in message["text"] for message in self.api.messages
        )
        assert len(self.writer.calls) == 1

    def test_legacy_local_weekend_draft_is_held_until_gemini_replaces_it(self) -> None:
        legacy_content = (
            "Older routine text.\n\nNO CONFIRMATION, NO ENTRY."
        )
        legacy, created = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-24",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content=legacy_content,
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=1,
            next_promo_feature_index=0,
            last_promo_date=None,
        )
        assert created

        self.manager.dispatch_due(local_time(23, 18))
        held = self.store.get_channel_post(legacy["id"])
        assert held is not None
        assert held["status"] == "failed"
        assert held["failure_category"] == "gemini_legacy_draft_held"
        assert held["generation_source"] == "local"
        assert not self.api.channel_messages

        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:retry_generation:{legacy['id']}",
            local_time(23, 18, 5),
        )
        replaced = self.store.get_channel_post(legacy["id"])
        assert replaced is not None
        assert replaced["status"] == "draft"
        assert replaced["generation_source"] == "gemini"
        assert self.writer.calls[-1]["existing_draft"] == legacy_content

        self.manager.dispatch_due(local_time(24, 10))
        assert self.store.get_channel_post(legacy["id"])["status"] == "published"
        assert len(self.api.channel_messages) == 1

    def test_restart_does_not_cancel_an_admin_edit_already_in_progress(self) -> None:
        legacy, _ = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-24",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="Draft being edited.\n\nNO CONFIRMATION, NO ENTRY.",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=1,
            next_promo_feature_index=0,
            last_promo_date=None,
        )
        self.assertTrue(
            self.store.start_channel_post_edit(legacy["id"], admin_id=ADMIN_ID)
        )

        self.manager.dispatch_due(local_time(24, 14))

        saved = self.store.get_channel_post(legacy["id"])
        self.assertEqual(saved["status"], "awaiting_edit")
        self.assertEqual(saved["edit_admin_id"], ADMIN_ID)
        self.assertFalse(self.writer.calls)
        self.assertFalse(self.api.channel_messages)

    def test_admin_feedback_revises_weekend_draft_with_saved_context(self) -> None:
        self.manager.dispatch_due(local_time(23, 18))
        post = self.store.get_scheduled_channel_post("2026-10-24")
        assert post is not None and post["status"] == "draft"

        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:revise:{post['id']}",
            local_time(23, 18, 5),
        )
        feedback = "Make the teaching prompt more practical and ask members to reflect."
        assert self.manager.handle_edit_message(
            ADMIN_ID, ADMIN_ID, feedback, True
        )

        revised = self.store.get_channel_post(post["id"])
        assert revised is not None and revised["status"] == "draft"
        assert len(self.writer.calls) == 2
        assert self.writer.calls[-1]["revision_feedback"] == feedback
        assert self.writer.calls[-1]["existing_draft"]
        assert self.store.get_latest_channel_post_feedback(post["id"]) == feedback

    def test_weekend_generation_receives_archived_posts_and_prior_admin_feedback(
        self,
    ) -> None:
        self.store.record_channel_history_post(
            CHANNEL_ID,
            123,
            "Earlier channel lesson about patience and FOMO.",
            "2026-10-22T10:00:00+01:00",
        )
        prior, _ = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-22",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="Past admin-reviewed draft.\n\nNO CONFIRMATION, NO ENTRY.",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=1,
            next_promo_feature_index=0,
            last_promo_date=None,
        )
        self.store.record_channel_post_action(
            prior["id"],
            "revision_feedback",
            admin_id=ADMIN_ID,
            details="Prefer practical examples and clear questions.",
        )

        self.manager.dispatch_due(local_time(23, 18))

        context = self.writer.calls[-1]
        self.assertTrue(
            any(
                item["content"].startswith("Earlier channel lesson")
                for item in context["history"]
            )
        )
        self.assertEqual(
            context["admin_feedback"][0]["details"],
            "Prefer practical examples and clear questions.",
        )

    def test_promotion_interval_can_be_changed_by_admin(self) -> None:
        store, manager = self.store, self.manager
        manager.dispatch_due(local_time(23, 18))
        store.set_channel_promo_interval(7, admin_id=ADMIN_ID)

        manager.dispatch_due(local_time(30, 18))
        following_saturday = store.get_scheduled_channel_post("2026-10-31")
        assert following_saturday is not None
        assert following_saturday["is_promo"] == 1
        assert store.get_channel_posting_settings()["promo_interval_days"] == 7

    def test_pause_blocks_automatic_posting_and_resume_allows_it(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        store.set_channel_posting_paused(True, admin_id=ADMIN_ID)

        manager.dispatch_due(local_time(26, 10))
        assert api.channel_messages == []

        manager.handle_callback(
            ADMIN_ID, ADMIN_ID, "admin:channel_posts:resume", local_time(26, 10, 1)
        )
        manager.dispatch_due(local_time(26, 10, 2))
        assert len(api.channel_messages) == 1

    def test_reject_and_skip_prevent_publication(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None

        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:reject:{post['id']}",
            local_time(26, 9, 10),
        )
        manager.dispatch_due(local_time(26, 10))
        assert store.get_channel_post(post["id"])["status"] == "rejected"
        assert api.channel_messages == []

        next_post = manager._create_post(datetime(2026, 10, 27).date())
        assert next_post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:skip:{next_post['id']}",
            local_time(26, 10, 1),
        )
        assert store.get_channel_post(next_post["id"])["status"] == "skipped"

    def test_admin_can_edit_draft_and_updated_copy_is_previewed(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:edit:{post['id']}",
            local_time(26, 9, 5),
        )

        edited = (
            "Pause before entry. Check that your planned structure and confirmation "
            "are present, and define what would invalidate the idea.\n\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        assert manager.handle_edit_message(ADMIN_ID, ADMIN_ID, edited, True)
        saved = store.get_channel_post(post["id"])
        assert saved is not None
        assert saved["status"] == "draft"
        assert saved["content"] == edited
        assert saved["preview_sent_at"] is not None
        assert any(edited in message["text"] for message in api.messages)

    def test_non_market_analysis_destination_and_missing_permission_are_blocked(
        self,
    ) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        api.chat = {
            "id": CHANNEL_ID,
            "type": "channel",
            "title": "Smart Money Hub PRO Signals",
        }
        manager.dispatch_due(local_time(26, 10))

        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        assert post["status"] == "failed"
        assert post["failure_category"] == "destination_not_verified"
        assert api.channel_messages == []

        api.chat = {
            "id": CHANNEL_ID,
            "type": "channel",
            "title": "Smart Money Hub Market Analysis",
        }
        api.member = {
            "status": "administrator",
            "can_post_messages": False,
        }
        manager.dispatch_due(local_time(27, 9))
        manager.dispatch_due(local_time(27, 10))
        permission_blocked = store.get_scheduled_channel_post("2026-10-27")
        assert permission_blocked is not None
        assert permission_blocked["status"] == "failed"
        assert permission_blocked["failure_category"] == "posting_permission_missing"

    def test_telegram_rate_limit_gets_one_bounded_retry(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        api.send_failures.append(
            TelegramAPIError(
                "rate limited",
                error_code=429,
                retry_after=20,
            )
        )
        manager.dispatch_due(local_time(26, 10))

        retry_wait = store.get_scheduled_channel_post("2026-10-26")
        assert retry_wait is not None
        assert retry_wait["status"] == "retry_wait"
        assert retry_wait["publish_attempts"] == 1
        assert api.channel_messages == []

        manager.dispatch_due(local_time(26, 10) + timedelta(seconds=21))
        published = store.get_scheduled_channel_post("2026-10-26")
        assert published is not None
        assert published["status"] == "published"
        assert published["publish_attempts"] == 2
        assert len(api.channel_attempts) == 2
        assert len(api.channel_messages) == 1

    def test_failed_preflight_after_rate_limit_stops_automatic_retry(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        api.send_failures.append(
            TelegramAPIError("rate limited", error_code=429, retry_after=10)
        )
        manager.dispatch_due(local_time(26, 10))
        api.chat = {
            "id": CHANNEL_ID,
            "type": "channel",
            "title": "Smart Money Hub PRO Signals",
        }

        manager.dispatch_due(local_time(26, 10) + timedelta(seconds=11))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        assert post["status"] == "failed"
        assert post["failure_category"] == "destination_not_verified"

        manager.dispatch_due(local_time(26, 10) + timedelta(seconds=20))
        assert store.get_scheduled_channel_post("2026-10-26")["status"] == "failed"
        assert len(api.channel_attempts) == 1

    def test_ambiguous_send_is_not_retried_after_restart(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        assert store.reserve_channel_post_publish(post["id"])

        restarted_manager = ChannelPostManager(api, store, ADMIN_ID, CHANNEL_ID)
        restarted_manager.dispatch_due(local_time(26, 10))

        recovered = store.get_channel_post(post["id"])
        assert recovered is not None
        assert recovered["status"] == "delivery_unknown"
        assert api.channel_messages == []
        assert any(
            "check the market analysis channel" in message["text"].casefold()
            for message in api.messages
        )

    def test_admin_check_is_required_before_retrying_ambiguous_delivery(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        assert store.reserve_channel_post_publish(post["id"])
        store.fail_channel_post_publish(
            post["id"],
            status="delivery_unknown",
            failure_category="telegram_delivery_unknown",
        )

        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:retry_checked:{post['id']}",
            local_time(26, 10),
        )

        saved = store.get_channel_post(post["id"])
        assert saved is not None
        assert saved["status"] == "published"
        assert len(api.channel_messages) == 1

    def test_promo_copy_cannot_claim_unverified_signals_or_prices(self) -> None:
        unsafe = (
            "BUY NOW: gold is currently trading at $9999. "
            "NO CONFIRMATION, NO ENTRY."
        )
        assert validate_channel_post(unsafe, is_promo=False) == (
            "prohibited_signal_or_promise"
        )
        assert validate_channel_post(
            "Open @wrongbot and tap Start: https://t.me/wrongbot\n"
            "Ask the private Coach for educational explanations of Smart Money Concepts.\n"
            "NO CONFIRMATION, NO ENTRY.",
            is_promo=True,
            bot_username="SmartMoneyHubSignalsBot",
        ) == "promo_link_mismatch"

if __name__ == "__main__":
    unittest.main()
