from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from smart_money_hub_bot.admin_dashboard import AdminDashboard
from smart_money_hub_bot.channel_gemini import (
    ChannelDraft,
    GeminiChannelGenerationError,
)
from smart_money_hub_bot.community_content import (
    CommunityContentError,
    CommunityContentManager,
    render_telegram_html,
)
from smart_money_hub_bot.storage import Repository
from smart_money_hub_bot.telegram_api import TelegramAPIError


NOW = datetime(2026, 10, 25, 7, 2, tzinfo=timezone.utc)
GROUP_ID = -1001234567890
ADMIN_ID = 123456


class FakeWriter:
    def __init__(self, content: str = "📚 SMART MONEY HUB\n\nA useful lesson.") -> None:
        self.content = content
        self.calls = 0

    def generate(self, **_kwargs) -> ChannelDraft:
        self.calls += 1
        return ChannelDraft(category="education", content=self.content)


class FailingWriter:
    def generate(self, **_kwargs):
        raise GeminiChannelGenerationError("quota_exhausted", http_status=429)


class FakeAPI:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict]] = []
        self.documents: list[tuple[int, str, bytes, str | None]] = []
        self.send_count = 0
        self.chat_type = "supergroup"
        self.member_status = "administrator"
        self.can_send_messages = True
        self.send_error: TelegramAPIError | None = None

    def send_message(self, chat_id, text, reply_markup=None, *, parse_mode=None, **_kwargs):
        self.messages.append((chat_id, text, {"parse_mode": parse_mode, "keyboard": reply_markup}))

    def send_document(self, chat_id, filename, content, *, caption=None):
        self.documents.append((chat_id, filename, bytes(content), caption))
        return {"message_id": 555}

    def get_chat(self, chat_id):
        return {"id": chat_id, "type": self.chat_type}

    def get_me(self):
        return {"id": 987}

    def get_chat_member(self, _chat_id, _user_id):
        return {
            "status": self.member_status,
            "can_send_messages": self.can_send_messages,
        }

    def send_message_with_result(self, _chat_id, _text, *, parse_mode=None):
        self.send_count += 1
        if self.send_error:
            raise self.send_error
        return {"message_id": 444, "date": 1792911720}


class CommunityContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "bot.sqlite3"
        self.writer = FakeWriter()
        self.manager = CommunityContentManager(
            self.database,
            writer=self.writer,
            allowed_destinations={GROUP_ID: "supergroup"},
        )

    def _draft(self) -> str:
        return self.manager.generate_draft(
            "educational_reminder", GROUP_ID, now=NOW
        )

    def test_schedules_are_paused_by_default_and_persist(self):
        self.assertFalse(self.manager.repository.enabled())
        self.assertEqual(
            self.manager.repository.setting("auto_publish_enabled"), "0"
        )
        self.manager.repository.set_enabled(True, now=NOW)
        restored = CommunityContentManager(
            self.database, writer=self.writer, allowed_destinations={GROUP_ID: "supergroup"}
        )
        self.assertTrue(restored.repository.enabled())
        self.assertEqual(restored.repository.setting("auto_publish_enabled"), "0")

    def test_scheduler_creates_one_review_draft_and_never_sends_to_telegram(self):
        repo = self.manager.repository
        repo.set_enabled(True, now=NOW)
        self.manager.save_schedule(
            schedule_id="morning-education",
            category="good_morning",
            destination_chat_id=GROUP_ID,
            timezone_name="Africa/Lagos",
            local_time="08:00",
            frequency="weekly",
            weekday=6,
            enabled=True,
            now=NOW,
        )
        notifications: list[str] = []
        self.manager.dispatch_due(now=NOW, notify_admin=notifications.append)
        first = repo.list_drafts(limit=5)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["content_source"], "gemini")
        self.assertEqual(first[0]["status"], "draft")
        self.assertEqual(len(notifications), 1)

        restored = CommunityContentManager(
            self.database, writer=self.writer, allowed_destinations={GROUP_ID: "supergroup"}
        )
        restored.dispatch_due(now=NOW, notify_admin=notifications.append)
        self.assertEqual(len(restored.repository.list_drafts(limit=5)), 1)
        self.assertEqual(self.writer.calls, 1)

    def test_routine_auto_publication_needs_both_explicit_opt_ins(self):
        repo = self.manager.repository
        repo.set_enabled(True, now=NOW)
        self.manager.save_schedule(
            schedule_id="daily-routine",
            category="good_morning",
            destination_chat_id=GROUP_ID,
            timezone_name="Africa/Lagos",
            local_time="08:00",
            frequency="weekly",
            weekday=6,
            enabled=True,
            approval_mode="auto",
            now=NOW,
        )
        api = FakeAPI()
        # The schedule alone is not enough; global auto-publishing remains off.
        self.manager.dispatch_due(now=NOW, api=api)
        self.assertEqual(api.send_count, 0)
        self.assertEqual(repo.list_drafts(limit=1)[0]["status"], "draft")

    def test_explicitly_enabled_routine_schedule_publishes_once_after_checks(self):
        repo = self.manager.repository
        repo.set_enabled(True, now=NOW)
        repo.set_setting("auto_publish_enabled", "1", now=NOW)
        self.manager.save_schedule(
            schedule_id="daily-routine-auto",
            category="good_morning",
            destination_chat_id=GROUP_ID,
            timezone_name="Africa/Lagos",
            local_time="08:00",
            frequency="weekly",
            weekday=6,
            enabled=True,
            approval_mode="auto",
            now=NOW,
        )
        api = FakeAPI()
        notifications: list[str] = []
        self.manager.dispatch_due(now=NOW, api=api, notify_admin=notifications.append)
        self.manager.dispatch_due(now=NOW, api=api, notify_admin=notifications.append)
        self.assertEqual(api.send_count, 1)
        draft = repo.list_drafts(limit=1)[0]
        self.assertEqual(draft["status"], "published")
        self.assertTrue(any("was published" in notice for notice in notifications))

    def test_statistics_and_promotional_schedules_cannot_be_set_to_auto(self):
        for category in ("weekly_results", "successful_trade_recap", "premium_invitation"):
            with self.subTest(category=category):
                with self.assertRaisesRegex(
                    CommunityContentError, "administrator review"
                ):
                    self.manager.save_schedule(
                        schedule_id=f"unsafe-{category}",
                        category=category,
                        destination_chat_id=GROUP_ID,
                        timezone_name="Africa/Lagos",
                        local_time="08:00",
                        frequency="weekly",
                        weekday=6,
                        enabled=True,
                        approval_mode="auto",
                        now=NOW,
                    )

    def test_gemini_failure_holds_without_local_content_substitution(self):
        manager = CommunityContentManager(
            self.database, writer=FailingWriter(), allowed_destinations={GROUP_ID}
        )
        with self.assertRaisesRegex(CommunityContentError, "quota_exhausted"):
            manager.generate_draft("good_morning", GROUP_ID, now=NOW)
        self.assertEqual(manager.repository.list_drafts(limit=5), [])

        unconfigured = CommunityContentManager(
            self.database, allowed_destinations={GROUP_ID}
        )
        with self.assertRaisesRegex(CommunityContentError, "not configured"):
            unconfigured.generate_draft("good_morning", GROUP_ID, now=NOW)

    def test_unverified_trade_records_do_not_create_result_content(self):
        with self.assertRaisesRegex(CommunityContentError, "No verified closed trades"):
            self.manager.generate_draft("weekly_results", GROUP_ID, now=NOW)

    def test_premium_invitation_is_held_until_policy_and_link_are_verified(self):
        with self.assertRaisesRegex(CommunityContentError, "not verified"):
            self.manager.generate_draft("premium_invitation", GROUP_ID, now=NOW)

    def test_invalid_destination_and_unsafe_claims_are_rejected(self):
        with self.assertRaisesRegex(CommunityContentError, "configured destination"):
            self.manager.generate_draft("good_morning", -100999, now=NOW)
        with self.assertRaisesRegex(CommunityContentError, "prohibited"):
            self.manager.repository.create_draft(
                category="good_morning",
                content="SMART MONEY HUB\nGuaranteed profit today.",
                destination_chat_id=GROUP_ID,
                content_source="admin",
                now=NOW,
            )

    def test_editing_saves_prior_version_and_requires_new_approval(self):
        draft_id = self._draft()
        self.manager.repository.edit_draft(
            draft_id, "📚 SMART MONEY HUB\n\nRevised lesson.", now=NOW
        )
        draft = self.manager.repository.get_draft(draft_id)
        self.assertEqual(draft["revision"], 2)
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(self.manager.repository.draft_versions(draft_id)[0]["revision"], 1)

    def test_publish_requires_approval_checks_access_and_prevents_duplicates(self):
        draft_id = self._draft()
        api = FakeAPI()
        with self.assertRaisesRegex(CommunityContentError, "explicitly approved"):
            self.manager.publish_approved(draft_id, admin_id=ADMIN_ID, api=api, now=NOW)
        self.assertEqual(api.send_count, 0)

        self.manager.repository.decide(draft_id, "approved", admin_id=ADMIN_ID, now=NOW)
        result = self.manager.publish_approved(
            draft_id, admin_id=ADMIN_ID, api=api, now=NOW
        )
        self.assertEqual(result["telegram_message_id"], 444)
        self.assertEqual(api.send_count, 1)
        self.assertEqual(
            self.manager.repository.get_draft(draft_id)["status"], "published"
        )
        with self.assertRaisesRegex(CommunityContentError, "send attempt"):
            self.manager.publish_approved(
                draft_id, admin_id=ADMIN_ID, api=api, now=NOW
            )
        self.assertEqual(api.send_count, 1)

    def test_missing_permission_holds_send(self):
        draft_id = self._draft()
        self.manager.repository.decide(draft_id, "approved", admin_id=ADMIN_ID, now=NOW)
        api = FakeAPI()
        api.can_send_messages = False
        with self.assertRaisesRegex(CommunityContentError, "cannot send messages"):
            self.manager.publish_approved(draft_id, admin_id=ADMIN_ID, api=api, now=NOW)
        self.assertEqual(api.send_count, 0)

    def test_interrupted_or_unknown_send_is_not_automatically_retried(self):
        draft_id = self._draft()
        self.manager.repository.decide(draft_id, "approved", admin_id=ADMIN_ID, now=NOW)
        api = FakeAPI()
        api.send_error = TelegramAPIError(
            "network timeout", delivery_unknown=True
        )
        with self.assertRaisesRegex(CommunityContentError, "Check the destination"):
            self.manager.publish_approved(draft_id, admin_id=ADMIN_ID, api=api, now=NOW)
        self.assertEqual(
            self.manager.repository.get_draft(draft_id)["status"], "delivery_unknown"
        )
        with self.assertRaises(CommunityContentError):
            self.manager.publish_approved(draft_id, admin_id=ADMIN_ID, api=api, now=NOW)
        self.assertEqual(api.send_count, 1)

    def test_format_escapes_special_text_preserves_lines_and_enforces_utf16_cap(self):
        rendered = render_telegram_html(
            "📚 SMART MONEY HUB\n\nLESSON & NOTES\nPrice < level."
        )
        self.assertIn("<b>📚 SMART MONEY HUB</b>", rendered)
        self.assertIn("<b>LESSON &amp; NOTES</b>", rendered)
        self.assertIn("Price &lt; level.", rendered)
        self.assertEqual(rendered.count("\n"), 3)
        with self.assertRaisesRegex(CommunityContentError, "4096-character"):
            render_telegram_html("📚 SMART MONEY HUB\n" + ("x" * 4100))

    def test_admin_commands_are_private_and_reject_non_admin(self):
        api = FakeAPI()
        store = Repository(self.database)
        dashboard = AdminDashboard(
            api,
            store,
            ADMIN_ID,
            main_channel_id=-100111,
            education_group_id=GROUP_ID,
        )
        self.assertTrue(
            dashboard.handle_community_content_command(
                99, 99, True, "/content"
            )
        )
        self.assertIn("Admin access is restricted", api.messages[-1][1])
        self.assertTrue(
            dashboard.handle_community_content_command(
                99, ADMIN_ID, False, "/content"
            )
        )
        self.assertIn("private chat", api.messages[-1][1])
        self.assertTrue(
            dashboard.handle_community_content_command(
                ADMIN_ID, ADMIN_ID, True, "/content"
            )
        )
        self.assertIn("Automatic publishing: DISABLED", api.messages[-1][1])

    def test_resume_enables_draft_creation_but_not_automatic_publication(self):
        api = FakeAPI()
        dashboard = AdminDashboard(
            api,
            Repository(self.database),
            ADMIN_ID,
            main_channel_id=-100111,
            education_group_id=GROUP_ID,
        )
        self.assertTrue(
            dashboard.handle_community_content_command(
                ADMIN_ID, ADMIN_ID, True, "/contentresume"
            )
        )
        self.assertTrue(dashboard.community_content.repository.enabled())
        self.assertEqual(
            dashboard.community_content.repository.setting("auto_publish_enabled"),
            "0",
        )
        self.assertIn("Automatic publishing remains disabled", api.messages[-1][1])

    def test_admin_csv_export_uses_document_api_without_changing_ledger(self):
        api = FakeAPI()
        dashboard = AdminDashboard(
            api,
            Repository(self.database),
            ADMIN_ID,
            main_channel_id=-100111,
            education_group_id=GROUP_ID,
        )
        self.assertTrue(
            dashboard.handle_community_content_command(
                ADMIN_ID, ADMIN_ID, True, "/exportstats"
            )
        )
        self.assertEqual(len(api.documents), 1)
        chat_id, filename, content, caption = api.documents[0]
        self.assertEqual(chat_id, ADMIN_ID)
        self.assertEqual(filename, "smart-money-hub-trade-ledger.csv")
        self.assertIn(b"verification_status", content)
        self.assertIn("unverified rows", caption)


if __name__ == "__main__":
    unittest.main()
