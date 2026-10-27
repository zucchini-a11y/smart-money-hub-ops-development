from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from smart_money_hub_bot.channel_gemini import ChannelDraft, GeminiChannelGenerationError
from smart_money_hub_bot.channel_posting import ChannelPostManager
from smart_money_hub_bot.session_open_posts import (
    SessionOpenPostManager,
    SessionOpenPostStore,
    session_occurrences,
    validate_session_open_post,
)
from smart_money_hub_bot.storage import Repository

WAT = ZoneInfo("Africa/Lagos")
ADMIN_ID = 777
CHANNEL_ID = -1004481197912

SESSION_POST = (
    "📊 SMART MONEY HUB | MARKET PREPARATION\n"
    "━━━━━━━━━━━━━━\n\n"
    "🇬🇧 LONDON SESSION OPEN\n\n"
    "The London open is 08:00 Europe/London (09:00 WAT). Before the session, "
    "review your higher-timeframe context and mark only "
    "levels from your own verified chart.\n\n"
    "🔍 CONDITIONS TO WATCH\n"
    "✅ Define the confirmation and invalidation your plan requires.\n"
    "✅ Check the verified economic calendar before making decisions.\n\n"
    "🛡️ RISK REMINDER\n"
    "Set your invalidation before considering any setup.\n\n"
    "⚠️ REMEMBER\n"
    "NO CONFIRMATION, NO ENTRY.\n\n"
    "— VAYDA | Smart Money Hub"
)

LATE_SESSION_POST = (
    "📊 SMART MONEY HUB | SESSION CHECK-IN\n"
    "━━━━━━━━━━━━━━\n\n"
    "🇯🇵 TOKYO SESSION CHECK-IN | STAY SELECTIVE\n\n"
    "The Tokyo session is already underway. A session being active does not confirm "
    "a trade direction or validate an entry.\n\n"
    "🔍 SESSION CHECKLIST\n"
    "✅ Revisit the levels already marked in your plan.\n"
    "✅ Wait for the setup confirmation and invalidation you defined.\n"
    "✅ Step aside if the conditions are unclear.\n\n"
    "🛡️ RISK REMINDER\n"
    "Keep decisions within your plan; do not chase a move because it has started.\n\n"
    "⚠️ THE GOLDEN RULE\n"
    "NO CONFIRMATION, NO ENTRY.\n\n"
    "— VAYDA | Smart Money Hub"
)


class FakeWriter:
    def __init__(self, content: str = SESSION_POST, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return ChannelDraft("new_week_preparation", self.content)


class FakeAPI:
    def __init__(self):
        self.admin_messages: list[tuple] = []
        self.channel_messages: list[tuple] = []
        self.photo_messages: list[tuple] = []
        self.member = {"status": "administrator", "can_post_messages": True}
        self.chat = {
            "id": CHANNEL_ID,
            "type": "channel",
            "title": "Smart Money Hub Market Analysis",
        }
        self.next_message_id = 100

    def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.admin_messages.append((chat_id, text, reply_markup, parse_mode))
        return {"message_id": self.next_message_id}

    def get_me(self):
        return {"id": 4242, "username": "SmartMoneyHubSignalsBot"}

    def get_chat(self, chat_id):
        assert chat_id == CHANNEL_ID
        return self.chat

    def get_chat_member(self, chat_id, user_id):
        assert chat_id == CHANNEL_ID
        assert user_id == 4242
        return self.member

    def send_message_with_result(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.next_message_id += 1
        self.channel_messages.append((chat_id, text, reply_markup, parse_mode))
        return {"message_id": self.next_message_id}

    def send_photo_with_result(
        self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None
    ):
        self.next_message_id += 1
        self.photo_messages.append((chat_id, photo, caption, reply_markup, parse_mode))
        return {"message_id": self.next_message_id}


class SessionOpenPostTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.database = f"{self.temp.name}/session.sqlite3"
        self.repository = Repository(self.database)
        self.api = FakeAPI()
        self.writer = FakeWriter()
        self.channel_posts = ChannelPostManager(
            self.api,
            self.repository,
            ADMIN_ID,
            CHANNEL_ID,
            channel_writer=self.writer,
        )
        self.manager = SessionOpenPostManager(
            self.api,
            self.database,
            admin_id=ADMIN_ID,
            destination_chat_id=CHANNEL_ID,
            writer=self.writer,
            history_store=self.repository,
            channel_post_manager=self.channel_posts,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _occurrence(self, session_code: str, day: date = date(2026, 10, 26)):
        return next(
            item
            for item in session_occurrences(day)
            if item.definition.code == session_code
        )

    def test_local_session_opens_convert_to_wat_across_dst(self):
        winter = {x.definition.code: x for x in session_occurrences(date(2026, 1, 5))}
        summer = {x.definition.code: x for x in session_occurrences(date(2026, 7, 6))}
        transition = {
            x.definition.code: x for x in session_occurrences(date(2026, 10, 26))
        }

        self.assertEqual(winter["asia"].wat_at.strftime("%H:%M"), "01:00")
        self.assertEqual(winter["london"].wat_at.strftime("%H:%M"), "09:00")
        self.assertEqual(winter["new_york"].wat_at.strftime("%H:%M"), "14:00")
        self.assertEqual(summer["asia"].wat_at.strftime("%H:%M"), "01:00")
        self.assertEqual(summer["london"].wat_at.strftime("%H:%M"), "08:00")
        self.assertEqual(summer["new_york"].wat_at.strftime("%H:%M"), "13:00")
        self.assertEqual(transition["london"].wat_at.strftime("%H:%M"), "09:00")
        self.assertEqual(transition["new_york"].wat_at.strftime("%H:%M"), "13:00")
        self.assertEqual(session_occurrences(date(2026, 10, 25)), [])

    def test_session_post_keeps_schedule_times_in_metadata_not_public_copy(self):
        occurrence = self._occurrence("london")
        post = {
            "category": "new_week_preparation",
            "session_code": "london",
            "session_local_time": occurrence.local_at.strftime("%H:%M"),
            "schedule_time_wat": occurrence.wat_at.strftime("%H:%M"),
        }
        self.assertIsNone(validate_session_open_post(SESSION_POST, post))
        without_visible_times = SESSION_POST.replace(
            "The London open is 08:00 Europe/London (09:00 WAT). ",
            "The London session is underway. ",
        )
        self.assertEqual(
            validate_session_open_post(without_visible_times, post),
            None,
        )
        self.assertEqual(
            validate_session_open_post(
                without_visible_times,
                {**post, "session_local_time": ""},
            ),
            "session_schedule_time_missing",
        )
        self.assertEqual(
            validate_session_open_post(
                SESSION_POST.replace("🛡️ RISK REMINDER", "📌 KEY POINT"), post
            ),
            "session_risk_reminder_missing",
        )

    def test_generates_fifteen_minutes_before_reviews_five_minutes_before_and_posts_once(self):
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "draft")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=10))
        self.assertEqual(len(self.writer.calls), 1)
        self.assertEqual(self.writer.calls[0]["preferred_category"], "new_week_preparation")
        self.assertEqual(
            self.writer.calls[0]["session_context"]["session_timezone"],
            "Europe/London",
        )
        self.assertEqual(self.api.channel_messages, [])

        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=5))
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "review_pending")
        self.assertIn("SESSION-OPEN POST REVIEW", self.api.admin_messages[-1][1])
        self.assertIn("09:00 WAT", self.api.admin_messages[-1][1])
        self.assertIn("Add a photo", self.api.admin_messages[-1][1])
        self.assertEqual(self.api.channel_messages, [])

        self.manager.dispatch_due(occurrence.utc_at)
        self.manager.dispatch_due(occurrence.utc_at + timedelta(seconds=1))
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(self.api.channel_messages[0][0], CHANNEL_ID)
        self.assertEqual(self.manager.store.get_by_key(occurrence)["status"], "published")

    def test_admin_can_cancel_before_open_and_no_message_is_sent(self):
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=5))
        post = self.manager.store.get_by_key(occurrence)
        handled = self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:session_open:cancel:{post['id']}",
            now=occurrence.utc_at - timedelta(minutes=4),
        )
        self.assertTrue(handled)
        self.manager.dispatch_due(occurrence.utc_at)
        self.assertEqual(self.manager.store.get_by_key(occurrence)["status"], "cancelled")
        self.assertEqual(self.api.channel_messages, [])

    def test_non_admin_cannot_review_or_cancel(self):
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=5))
        post = self.manager.store.get_by_key(occurrence)
        self.assertFalse(
            self.manager.handle_callback(
                123,
                123,
                f"admin:session_open:cancel:{post['id']}",
                now=occurrence.utc_at - timedelta(minutes=4),
            )
        )
        self.assertEqual(self.manager.store.get_by_key(occurrence)["status"], "review_pending")

    def test_gemini_failure_is_held_without_fallback_or_publication(self):
        self.writer.error = GeminiChannelGenerationError("gemini_rate_limit", 429)
        occurrence = self._occurrence("asia")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["failure_category"], "gemini_rate_limit")
        self.assertEqual(self.api.channel_messages, [])
        self.assertTrue(any("Gemini could not prepare" in item[1] for item in self.api.admin_messages))

    def test_admin_can_retry_failed_gemini_draft_on_the_same_slot(self):
        occurrence = self._occurrence("london")
        self.writer.error = GeminiChannelGenerationError("gemini_rate_limit", 429)
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        failed = self.manager.store.get_by_key(occurrence)
        self.assertEqual(failed["status"], "failed")
        original_id = failed["id"]

        self.manager._show_post(ADMIN_ID, failed)
        retry_markup = self.api.admin_messages[-1][2]
        retry_button = retry_markup["inline_keyboard"][0][0]
        self.assertEqual(retry_button["text"], "♻️ Retry AI draft")
        self.assertEqual(
            retry_button["callback_data"],
            f"admin:session_open:retry_generation:{original_id}",
        )

        self.writer.error = None
        self.assertFalse(
            self.manager.handle_callback(
                ADMIN_ID + 1,
                ADMIN_ID + 1,
                f"admin:session_open:retry_generation:{original_id}",
                now=occurrence.utc_at - timedelta(minutes=10),
            )
        )
        self.assertEqual(len(self.writer.calls), 1)

        self.assertTrue(
            self.manager.handle_callback(
                ADMIN_ID,
                ADMIN_ID,
                f"admin:session_open:retry_generation:{original_id}",
                now=occurrence.utc_at - timedelta(minutes=10),
            )
        )
        retried = self.manager.store.get_by_key(occurrence)
        self.assertEqual(retried["id"], original_id)
        self.assertEqual(retried["status"], "draft")
        self.assertTrue(retried["content"])
        self.assertEqual(len(self.writer.calls), 2)
        self.assertEqual(self.api.channel_messages, [])

        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=5))
        self.assertEqual(
            self.manager.store.get_by_key(occurrence)["status"], "review_pending"
        )
        self.assertEqual(self.api.channel_messages, [])
        self.manager.dispatch_due(occurrence.utc_at)
        self.manager.dispatch_due(occurrence.utc_at + timedelta(seconds=1))
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(
            self.manager.store.get_by_key(occurrence)["status"], "published"
        )

    def test_gemini_retry_failure_reports_exact_category_and_stays_held(self):
        occurrence = self._occurrence("london")
        self.writer.error = GeminiChannelGenerationError("gemini_rate_limit", 429)
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        post = self.manager.store.get_by_key(occurrence)
        self.writer.error = GeminiChannelGenerationError(
            "gemini_unexpected_error", 500
        )

        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:session_open:retry_generation:{post['id']}",
            now=occurrence.utc_at - timedelta(minutes=10),
        )

        failed = self.manager.store.get_by_key(occurrence)
        self.assertEqual(failed["id"], post["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_category"], "gemini_unexpected_error")
        self.assertTrue(
            any(
                "gemini_unexpected_error" in item[1]
                and "unexpected error" in item[1]
                for item in self.api.admin_messages
            )
        )
        self.assertEqual(self.api.channel_messages, [])

    def test_gemini_retry_is_refused_once_the_review_window_starts(self):
        occurrence = self._occurrence("london")
        self.writer.error = GeminiChannelGenerationError("gemini_rate_limit", 429)
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        post = self.manager.store.get_by_key(occurrence)

        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:session_open:retry_generation:{post['id']}",
            now=occurrence.utc_at - timedelta(minutes=4),
        )

        held = self.manager.store.get_by_key(occurrence)
        self.assertEqual(held["status"], "failed")
        self.assertEqual(held["failure_category"], "gemini_rate_limit")
        self.assertEqual(len(self.writer.calls), 1)
        self.assertTrue(
            any("too close to the session opening" in item[1] for item in self.api.admin_messages)
        )
        self.assertEqual(self.api.channel_messages, [])

    def test_archived_channel_history_is_supplied_to_session_generation(self):
        self.repository.record_channel_history_post(
            CHANNEL_ID,
            881,
            "Recent Market Analysis post about waiting for confirmation.",
            "2026-10-26T06:00:00+00:00",
        )
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))

        history = self.writer.calls[0]["history"]
        self.assertTrue(
            any(
                item["source"] == "channel"
                and item["content"]
                == "Recent Market Analysis post about waiting for confirmation."
                for item in history
            )
        )
        self.assertEqual(self.api.channel_messages, [])

    def test_restart_after_open_generates_fresh_time_free_recovery_and_posts_once(self):
        self.writer.content = LATE_SESSION_POST
        occurrence = self._occurrence("asia")
        after_open = occurrence.utc_at + timedelta(minutes=6)
        self.manager.dispatch_due(after_open)
        self.manager.dispatch_due(after_open + timedelta(seconds=20))
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "published")
        self.assertEqual(saved["late_recovery"], 1)
        self.assertEqual(saved["publish_attempts"], 1)
        self.assertEqual(len(self.writer.calls), 1)
        self.assertTrue(self.writer.calls[0]["session_context"]["late_recovery"])
        self.assertEqual(len(self.api.channel_messages), 1)
        sent_text = self.api.channel_messages[0][1]
        for forbidden in ("09:00", "01:00", "WAT", "JST", "Asia/Tokyo"):
            self.assertNotIn(forbidden, sent_text)
        notices = [
            item
            for item in self.api.admin_messages
            if "fresh, time-free check-in" in item[1]
        ]
        self.assertEqual(len(notices), 1)

    def test_missed_session_after_close_is_not_recovered_or_published(self):
        occurrence = self._occurrence("asia")
        after_close = occurrence.utc_at + timedelta(hours=10)
        self.manager.dispatch_due(after_close)
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "missed")
        self.assertEqual(saved["failure_category"], "session_open_recovery_window_expired")
        self.assertEqual(self.writer.calls, [])
        self.assertEqual(self.api.channel_messages, [])

    def test_interrupted_late_generation_recovers_after_restart(self):
        self.writer.content = LATE_SESSION_POST
        occurrence = self._occurrence("asia")
        post, created = self.manager.store.create_slot(
            occurrence, CHANNEL_ID, at=(occurrence.utc_at + timedelta(minutes=6)).isoformat()
        )
        self.assertTrue(created)
        self.manager.store.update(
            int(post["id"]),
            expected=("generating",),
            status="generating",
            at=(occurrence.utc_at + timedelta(minutes=6)).isoformat(),
            late_recovery=1,
            failure_category="session_open_late_recovery",
        )

        restarted = SessionOpenPostManager(
            self.api,
            self.database,
            admin_id=ADMIN_ID,
            destination_chat_id=CHANNEL_ID,
            writer=self.writer,
            history_store=self.repository,
            channel_post_manager=self.channel_posts,
        )
        recovered = restarted.store.get_by_key(occurrence)
        self.assertEqual(recovered["status"], "missed")
        self.assertEqual(
            recovered["failure_category"],
            "session_open_late_generation_interrupted",
        )
        restarted.dispatch_due(occurrence.utc_at + timedelta(minutes=7))
        published = restarted.store.get_by_key(occurrence)
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["publish_attempts"], 1)
        self.assertEqual(len(self.writer.calls), 1)
        self.assertEqual(len(self.api.channel_messages), 1)

    def test_late_recovery_rejects_public_schedule_times(self):
        occurrence = self._occurrence("asia")
        candidate = {
            "category": "new_week_preparation",
            "session_code": "asia",
            "session_local_time": occurrence.local_at.strftime("%H:%M"),
            "schedule_time_wat": occurrence.wat_at.strftime("%H:%M"),
            "late_recovery": True,
        }
        self.assertEqual(
            validate_session_open_post(
                LATE_SESSION_POST + "\nThe scheduled opening is 09:00 JST.",
                candidate,
            ),
            "session_recovery_time_in_copy",
        )

    def test_session_layout_must_differ_from_last_published_session(self):
        previous = self._occurrence("london", date(2026, 10, 23))
        old, created = self.manager.store.create_slot(
            previous, CHANNEL_ID, at="2026-10-23T06:45:00+00:00"
        )
        self.assertTrue(created)
        self.manager.store.update(
            int(old["id"]),
            expected=("generating",),
            status="published",
            at="2026-10-23T07:00:00+00:00",
            content=SESSION_POST,
            telegram_message_id=101,
            published_at="2026-10-23T07:00:00+00:00",
        )
        current, created = self.manager.store.create_slot(
            self._occurrence("london", date(2026, 10, 26)),
            CHANNEL_ID,
            at="2026-10-26T06:45:00+00:00",
        )
        self.assertTrue(created)
        repeated = LATE_SESSION_POST.replace(
            "TOKYO SESSION CHECK-IN", "LONDON SESSION CHECK-IN"
        ).replace("TOKYO", "LONDON").replace("SESSION CHECKLIST", "CONDITIONS TO WATCH")
        self.assertTrue(
            self.manager._repeats_recent_session_layout(
                repeated, int(current["id"])
            )
        )

    def test_unverified_live_market_claim_is_held(self):
        self.writer.content = SESSION_POST.replace(
            "review your higher-timeframe context",
            "gold is currently rising, so review your higher-timeframe context",
        )
        occurrence = self._occurrence("new_york")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "failed")
        self.assertIn("unverified_market_claim", saved["failure_category"])
        self.assertEqual(self.api.channel_messages, [])

    def test_missing_destination_permission_holds_post(self):
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=5))
        self.api.member = {"status": "administrator", "can_post_messages": False}
        self.manager.dispatch_due(occurrence.utc_at)
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["failure_category"], "posting_permission_missing")
        self.assertEqual(self.api.channel_messages, [])

    def test_photo_is_attached_and_used_only_after_the_open(self):
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=5))
        post = self.manager.store.get_by_key(occurrence)
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:session_open:photo:{post['id']}",
            now=occurrence.utc_at - timedelta(minutes=4),
        )
        self.assertTrue(
            self.manager.handle_admin_photo(
                ADMIN_ID,
                ADMIN_ID,
                [{"file_id": "synthetic-photo-file-id"}],
                is_private=True,
            )
        )
        self.manager.dispatch_due(occurrence.utc_at)
        self.assertEqual(len(self.api.photo_messages), 1)
        self.assertEqual(self.api.photo_messages[0][1], "synthetic-photo-file-id")
        self.assertEqual(self.api.channel_messages, [])

    def test_interrupted_send_is_marked_uncertain_and_never_retried(self):
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=5))
        post = self.manager.store.get_by_key(occurrence)
        self.manager.store.update(
            int(post["id"]),
            expected=("review_pending",),
            status="publishing",
            at=occurrence.utc_at.isoformat(),
        )
        restarted_manager = SessionOpenPostManager(
            self.api,
            self.database,
            admin_id=ADMIN_ID,
            destination_chat_id=CHANNEL_ID,
            writer=self.writer,
            history_store=self.repository,
            channel_post_manager=self.channel_posts,
        )
        restarted_manager.dispatch_due(occurrence.utc_at + timedelta(seconds=10))
        saved = restarted_manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "delivery_unknown")
        self.assertEqual(self.api.channel_messages, [])
        self.assertTrue(
            any("is uncertain after restart" in item[1] for item in self.api.admin_messages)
        )

    def test_pause_blocks_session_posts(self):
        self.repository.set_channel_posting_paused(True, admin_id=ADMIN_ID)
        occurrence = self._occurrence("london")
        self.manager.dispatch_due(occurrence.utc_at - timedelta(minutes=15))
        saved = self.manager.store.get_by_key(occurrence)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["failure_category"], "channel_publishing_paused")
        self.assertEqual(self.writer.calls, [])

    def test_identical_recent_session_content_is_held_as_duplicate(self):
        previous = self._occurrence("london", date(2026, 10, 23))
        old, created = self.manager.store.create_slot(
            previous, CHANNEL_ID, at="2026-10-23T06:45:00+00:00"
        )
        self.assertTrue(created)
        self.manager.store.update(
            int(old["id"]),
            expected=("generating",),
            status="published",
            at="2026-10-23T07:00:00+00:00",
            content=SESSION_POST,
            telegram_message_id=101,
            published_at="2026-10-23T07:00:00+00:00",
        )
        current = self._occurrence("london", date(2026, 10, 26))
        self.manager.dispatch_due(current.utc_at - timedelta(minutes=15))
        saved = self.manager.store.get_by_key(current)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["failure_category"], "content_rejected_duplicate_content")
        self.assertEqual(self.api.channel_messages, [])


if __name__ == "__main__":
    unittest.main()
