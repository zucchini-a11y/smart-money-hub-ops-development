from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from smart_money_hub_bot.channel_posting import ChannelPostManager
from smart_money_hub_bot.daily_calendar_brief import DailyCalendarBriefStore
from smart_money_hub_bot.storage import Repository

ADMIN_ID = 444
CHANNEL_ID = -1004481197912
WAT = ZoneInfo("Africa/Lagos")


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        **_kwargs,
    ) -> None:
        self.messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )


class ChannelContentQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "channel-content.sqlite3"
        self.store = Repository(self.database_path)
        self.api = FakeTelegramAPI()
        self.daily_brief_store = DailyCalendarBriefStore(self.database_path)
        self.manager = ChannelPostManager(
            self.api,
            self.store,
            ADMIN_ID,
            CHANNEL_ID,
            daily_brief_store=self.daily_brief_store,
            daily_brief_enabled=True,
        )

    def test_all_upcoming_posts_are_paged_without_omissions_or_duplicates(self) -> None:
        base_date = datetime(2026, 10, 25).date()
        expected_ids: set[int] = set()
        for index in range(12):
            scheduled_date = base_date + timedelta(days=index)
            post, created = self.store.create_scheduled_channel_post(
                schedule_date=scheduled_date.isoformat(),
                schedule_time="10:00",
                requested_category="education",
                category="education",
                content=f"📚 SMART MONEY HUB\n\nSaved lesson {index + 1}.",
                destination_chat_id=CHANNEL_ID,
                is_promo=index == 8,
                bot_username="SmartMoneyHubSignalsBot" if index == 8 else None,
                next_category_index=0,
                next_promo_feature_index=0,
                last_promo_date=None,
                at="2026-10-24T00:00:00+00:00",
            )
            self.assertTrue(created)
            expected_ids.add(int(post["id"]))

        now = datetime(2026, 10, 24, 9, 0, tzinfo=WAT)
        observed_ids: list[int] = []
        first_preview_callback = ""
        for page in range(3):
            self.manager.show_controls(ADMIN_ID, page=page, now=now)
            message = self.api.messages[-1]
            self.assertIn(
                f"Saved posts in queue: 12 (page {page + 1} of 3)",
                message["text"],
            )
            self.assertIn("Daily USD & Gold brief:", message["text"])
            self.assertIn(
                "Next scheduled slot: 2026-10-25 at 00:00 WAT",
                message["text"],
            )
            buttons = [
                button
                for row in message["reply_markup"]["inline_keyboard"]
                for button in row
            ]
            preview_ids = [
                int(button["callback_data"].rsplit(":", 1)[1])
                for button in buttons
                if button["callback_data"].startswith(
                    "admin:channel_posts:preview:"
                )
            ]
            self.assertEqual(len(preview_ids), 5 if page < 2 else 2)
            observed_ids.extend(preview_ids)
            if page == 0:
                first_preview_callback = next(
                    button["callback_data"]
                    for button in buttons
                    if button["callback_data"].startswith(
                        "admin:channel_posts:preview:"
                    )
                )
            page_buttons = [
                button["callback_data"]
                for button in buttons
                if button["callback_data"].startswith(
                    "admin:channel_posts:upcoming:"
                )
            ]
            if page == 0:
                self.assertIn(
                    f"admin:channel_posts:upcoming:{page + 1}", page_buttons
                )
                self.assertEqual(len(page_buttons), 1)
            elif page < 2:
                self.assertIn(
                    f"admin:channel_posts:upcoming:{page - 1}", page_buttons
                )
                self.assertIn(
                    f"admin:channel_posts:upcoming:{page + 1}", page_buttons
                )
            else:
                self.assertEqual(
                    page_buttons, [f"admin:channel_posts:upcoming:{page - 1}"]
                )

        self.assertEqual(len(observed_ids), 12)
        self.assertEqual(len(set(observed_ids)), 12)
        self.assertEqual(set(observed_ids), expected_ids)
        self.assertTrue(
            self.manager.handle_callback(
                ADMIN_ID,
                ADMIN_ID,
                first_preview_callback,
                now=now,
            )
        )
        self.assertIn("Saved lesson 1", self.api.messages[-1]["text"])

    def test_channel_content_shows_held_daily_brief_review_action(self) -> None:
        now = datetime(2026, 10, 24, 9, 0, tzinfo=WAT)
        today = now.date()
        self.assertTrue(self.daily_brief_store.reserve(today, now))
        self.daily_brief_store.finish(
            today,
            status="held",
            now=now,
            failure_category="bea_source_not_verified",
        )

        self.manager.show_controls(ADMIN_ID, now=now)

        message = self.api.messages[-1]
        self.assertIn("Today's run: held", message["text"])
        callbacks = [
            button["callback_data"]
            for row in message["reply_markup"]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("dailybrief:review", callbacks)

    def test_disabled_daily_brief_is_not_shown_as_scheduled(self) -> None:
        self.manager.daily_brief_enabled = False
        self.manager.show_controls(
            ADMIN_ID,
            now=datetime(2026, 10, 24, 9, 0, tzinfo=WAT),
        )

        text = self.api.messages[-1]["text"]
        self.assertIn("Not enabled in the current runtime configuration", text)
        self.assertNotIn("Next scheduled slot:", text)

    def test_channel_content_page_callback_opens_requested_page(self) -> None:
        base_date = datetime(2026, 10, 25).date()
        for index in range(6):
            scheduled_date = base_date + timedelta(days=index)
            self.store.create_scheduled_channel_post(
                schedule_date=scheduled_date.isoformat(),
                schedule_time="10:00",
                requested_category="education",
                category="education",
                content=f"📚 SMART MONEY HUB\n\nLesson {index + 1}.",
                destination_chat_id=CHANNEL_ID,
                is_promo=False,
                bot_username=None,
                next_category_index=0,
                next_promo_feature_index=0,
                last_promo_date=None,
                at="2026-10-24T00:00:00+00:00",
            )
        now = datetime(2026, 10, 24, 9, 0, tzinfo=WAT)

        handled = self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            "admin:channel_posts:upcoming:1",
            now=now,
        )

        self.assertTrue(handled)
        self.assertIn("page 2 of 2", self.api.messages[-1]["text"])
        self.assertIn("2026-10-30", self.api.messages[-1]["text"])


if __name__ == "__main__":
    unittest.main()
