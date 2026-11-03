from __future__ import annotations

from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from smart_money_hub_bot.channel_content import (
    CHANNEL_CONTENT_CATEGORIES,
    PROMO_FEATURES,
    compose_promo_post,
    compose_routine_post,
    describe_channel_post_rejection,
    is_promotional_content,
    normalize_weekend_brand_header,
    render_weekend_post_html,
    validate_channel_post,
    validate_weekend_post_format,
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
FORMATTED_WEEKEND_POST = (
    "💧 SMART MONEY HUB | LIQUIDITY\n\n"
    "THE SWEEP IS NOT THE SIGNAL\n\n"
    "A sweep takes an obvious high or low; it does not confirm a reversal.\n\n"
    "🔍 WHAT TO UNDERSTAND\n"
    "• Wait for the structure evidence in your plan.\n\n"
    "✅ WHAT TO DO\n"
    "Mark invalidation and wait for confirmation.\n\n"
    "⚠️ REMEMBER\n"
    "NO CONFIRMATION, NO ENTRY."
)
TELEGRAM_LAYOUT_SAMPLES = (
    (
        "📚 SMART MONEY HUB\n"
        "━━━━━━━━━━━━━━\n\n"
        "🎯 TODAY’S TRADING LESSON\n\n"
        "A POI is not an entry signal. Price reaching a Point of Interest does not "
        "automatically mean you should enter.\n\n"
        "🔍 WHAT TO LOOK FOR\n\n"
        "✅ Observe the reaction at the zone.\n"
        "✅ Wait for the confirmation required by your setup.\n\n"
        "📌 KEY TAKEAWAY\n\n"
        "A marked zone is context, not proof of a trade.\n\n"
        "🛡️ RISK REMINDER\n"
        "Protect your capital. Follow your trading plan.\n\n"
        "⚠️ THE GOLDEN RULE\n"
        "NO CONFIRMATION, NO ENTRY.\n\n"
        "💬 What confirmation would you wait for before entering?\n\n"
        "— VAYDA | Smart Money Hub"
    ),
    (
        "📊 SMART MONEY HUB\n"
        "━━━━━━━━━━━━━━\n\n"
        "📊 MARKET PREPARATION\n\n"
        "No verified session levels are included here, so this is a process "
        "checklist rather than a live market update.\n\n"
        "🔍 CONDITIONS TO WATCH\n\n"
        "✅ Review your higher-timeframe context.\n"
        "✅ Mark levels only from your verified chart.\n"
        "✅ Define confirmation and invalidation before entry.\n\n"
        "🛡️ RISK REMINDER\n"
        "Protect your capital. Follow your trading plan.\n\n"
        "⚠️ THE GOLDEN RULE\n"
        "NO CONFIRMATION, NO ENTRY.\n\n"
        "— VAYDA | Smart Money Hub"
    ),
    (
        "🧠 SMART MONEY HUB\n"
        "━━━━━━━━━━━━━━\n\n"
        "🧠 TRADING PSYCHOLOGY\n\n"
        "A common mistake is chasing a move after missing the planned entry. It "
        "often comes from fear of being left behind.\n\n"
        "⚠️ COMMON TRAP\n\n"
        "Entering late can mean the original setup and its invalidation no longer "
        "apply.\n\n"
        "✅ ONE PRACTICAL RESET\n\n"
        "Pause, review your rules, and decide only when calm.\n\n"
        "🛡️ RISK REMINDER\n"
        "Protect your capital. Follow your trading plan.\n\n"
        "⚠️ THE GOLDEN RULE\n"
        "NO CONFIRMATION, NO ENTRY.\n\n"
        "— VAYDA | Smart Money Hub"
    ),
)


class FakeTelegramAPI:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.channel_messages: list[dict] = []
        self.channel_attempts: list[dict] = []
        self.send_failures: list[TelegramAPIError] = []
        self.message_failures: list[TelegramAPIError] = []
        self.get_chat_error: Exception | None = None
        self.get_member_error: Exception | None = None
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
        if self.get_chat_error:
            raise self.get_chat_error
        return self.chat

    def get_chat_member(self, chat_id: int, user_id: int) -> dict:
        assert chat_id == CHANNEL_ID
        assert user_id == self.bot_info["id"]
        if self.get_member_error:
            raise self.get_member_error
        return self.member

    def send_message(
        self, chat_id: int, text: str, reply_markup=None, *, parse_mode=None
    ) -> None:
        if self.message_failures:
            raise self.message_failures.pop(0)
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )

    def send_message_with_result(
        self, chat_id: int, text: str, reply_markup=None, *, parse_mode=None
    ) -> dict:
        self.channel_attempts.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        if self.send_failures:
            raise self.send_failures.pop(0)
        result = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
            "message_id": 9000 + len(self.channel_attempts),
        }
        self.channel_messages.append(result)
        return result

    def send_photo_with_result(
        self,
        chat_id: int,
        photo_file_id: str,
        *,
        caption: str,
        reply_markup=None,
        parse_mode=None,
    ) -> dict:
        self.channel_attempts.append(
            {
                "chat_id": chat_id,
                "photo": photo_file_id,
                "caption": caption,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        if self.send_failures:
            raise self.send_failures.pop(0)
        result = {
            "chat_id": chat_id,
            "photo": photo_file_id,
            "caption": caption,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
            "message_id": 9000 + len(self.channel_attempts),
        }
        self.channel_messages.append(result)
        return result


class FakeChannelWriter:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.failures: list[GeminiChannelGenerationError] = []
        self.drafts: list[ChannelDraft] = []

    def generate(self, **kwargs) -> ChannelDraft:
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        if self.drafts:
            return self.drafts.pop(0)
        category = kwargs["preferred_category"]
        topic = category.replace("_", " ").upper()
        content = (
            f"📚 SMART MONEY HUB | {topic}\n\n"
            f"{topic} NEEDS A CLEAR PLAN\n\n"
            f"Focus on process, evidence, and patience for "
            f"{kwargs['schedule_date']}."
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


def final_review_time(day: int) -> datetime:
    target_date = datetime(2026, 10, day, 12, tzinfo=TZ).date()
    publish_hour = 18 if target_date.weekday() == 6 else 10
    scheduled = datetime.combine(
        target_date,
        datetime.min.time().replace(hour=publish_hour),
        tzinfo=TZ,
    )
    return scheduled - timedelta(minutes=5)


class ChannelPostingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = Repository(
            f"{self.temp_dir.name}/channel-posts.sqlite3"
        )
        self.weekend_auto_publish_default = bool(
            self.store.get_channel_posting_settings()[
                "weekend_auto_publish_enabled"
            ]
        )
        # Existing automatic-publishing tests exercise the approved state.
        self.store.set_weekend_auto_publish_enabled(True)
        self.api = FakeTelegramAPI()
        self.writer = FakeChannelWriter()
        self.manager = ChannelPostManager(
            self.api,
            self.store,
            ADMIN_ID,
            CHANNEL_ID,
            channel_writer=self.writer,
        )

    def test_weekend_posts_wait_for_template_approval_without_affecting_previews(self) -> None:
        self.assertFalse(self.weekend_auto_publish_default)
        self.store.set_weekend_auto_publish_enabled(False)

        # Saturday evening: create Sunday's private preview as usual.
        self.manager.dispatch_due(local_time(24, 18))
        post = self.store.get_scheduled_channel_post("2026-10-25")
        self.assertIsNotNone(post)
        self.assertEqual(post["status"], "draft")
        self.assertTrue(self.api.messages)

        # Sunday schedule time: hold the post rather than sending it publicly.
        self.manager.dispatch_due(local_time(25, 18))
        post = self.store.get_scheduled_channel_post("2026-10-25")
        self.assertEqual(post["status"], "failed")
        self.assertEqual(post["failure_category"], "template_approval_pending")
        self.assertEqual(self.api.channel_messages, [])
        self.assertTrue(
            any("waiting for your approval" in message["text"].lower()
                for message in self.api.messages)
        )

        self.manager.show_post(ADMIN_ID, post)
        buttons = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        self.assertFalse(
            any(
                button["text"] == "🚀 Publish Now"
                for row in buttons
                for button in row
            )
        )

    def test_weekend_format_escapes_html_and_rejects_oversized_posts(self) -> None:
        self.assertIsNone(validate_weekend_post_format(FORMATTED_WEEKEND_POST))
        rendered = render_weekend_post_html(
            FORMATTED_WEEKEND_POST.replace("obvious high or low", "high & <low>")
        )
        self.assertTrue(rendered.startswith("<b>💧 SMART MONEY HUB | LIQUIDITY</b>"))
        self.assertIn("<b>THE SWEEP IS NOT THE SIGNAL</b>", rendered)
        self.assertIn("&amp; &lt;low&gt;", rendered)
        self.assertIn("<b>NO CONFIRMATION, NO ENTRY.</b>", rendered)
        self.assertNotIn("<low>", rendered)

        oversized = (
            "💧 SMART MONEY HUB | LIQUIDITY\n\n"
            "A VALID HEADLINE\n\n"
            + ("x" * 4050)
            + "\n\nNO CONFIRMATION, NO ENTRY."
        )
        self.assertEqual(
            validate_channel_post(oversized, is_promo=False),
            "content_too_long",
        )
        with self.assertRaisesRegex(ValueError, "content_too_long"):
            render_weekend_post_html(oversized)

    def test_repeated_headline_is_rejected_even_when_body_is_new(self) -> None:
        previous = (
            "📚 SMART MONEY HUB\n━━━━━━━━━━━━━━\n"
            "A FRESH WAY TO REVIEW THE PLAN\n\n"
            "Write down what your setup requires before the chart is active.\n\n"
            "📌 KEY TAKEAWAY\nA clear plan supports consistent decisions."
        )
        changed_body = previous.replace(
            "Write down what your setup requires before the chart is active.",
            "Compare the planned invalidation with the conditions you can verify.",
        ).replace(
            "A clear plan supports consistent decisions.",
            "A short review can help identify the next useful question.",
        )
        self.store.record_channel_history_post(
            CHANNEL_ID,
            9876,
            previous,
            "2026-10-26T09:00:00+01:00",
        )

        self.assertTrue(self.manager._is_duplicate(changed_body))

    def test_requested_category_samples_render_as_safe_telegram_html(self) -> None:
        expected_headings = (
            "🎯 TODAY’S TRADING LESSON",
            "📊 MARKET PREPARATION",
            "🧠 TRADING PSYCHOLOGY",
        )
        for content, heading in zip(TELEGRAM_LAYOUT_SAMPLES, expected_headings):
            with self.subTest(heading=heading):
                self.assertIsNone(validate_channel_post(content, is_promo=False))
                self.assertIsNone(validate_weekend_post_format(content))
                rendered = render_weekend_post_html(content)
                self.assertIn(f"<b>{heading}</b>", rendered)
                self.assertIn("<b>NO CONFIRMATION, NO ENTRY.</b>", rendered)
                self.assertNotIn("**", rendered)
                self.assertNotIn("```", rendered)

    def test_all_routine_categories_and_promo_use_the_branded_layout(self) -> None:
        for category in CHANNEL_CONTENT_CATEGORIES:
            with self.subTest(category=category):
                post = compose_routine_post(category, sequence=0)
                self.assertIsNone(validate_channel_post(post, is_promo=False))
                self.assertIsNone(validate_weekend_post_format(post))
                self.assertIn("━━━━━━━━━━━━━━", post)

        promo = compose_promo_post(
            compose_routine_post("education", sequence=0),
            "SmartMoneyHubSignalsBot",
            0,
        )
        self.assertIsNone(
            validate_channel_post(
                promo,
                is_promo=True,
                bot_username="SmartMoneyHubSignalsBot",
            )
        )
        self.assertIsNone(validate_weekend_post_format(promo))
        self.assertIn("🤖 HOW THE BOT CAN HELP", promo)

    def test_routine_layout_places_explanation_under_topic_heading(self) -> None:
        education = compose_routine_post("education", sequence=0)
        self.assertIn(
            "🔍 WHAT TO LOOK FOR\n"
            "A liquidity sweep shows that an obvious high or low was taken; "
            "it does not, by itself, confirm a reversal. Wait for the structure "
            "and confirmation in your plan.\n\n"
            "📌 KEY TAKEAWAY",
            education,
        )

    def test_markdown_is_rejected_before_telegram_html_rendering(self) -> None:
        markdown = TELEGRAM_LAYOUT_SAMPLES[0].replace(
            "A POI is not an entry signal.",
            "**A POI is not an entry signal.**",
        )
        self.assertEqual(
            validate_weekend_post_format(markdown),
            "markdown_not_supported",
        )
        self.assertIn(
            "Markdown markers",
            describe_channel_post_rejection(markdown, "markdown_not_supported"),
        )

    def test_weekend_format_requires_leading_emoji_brand_and_uppercase_headline(
        self,
    ) -> None:
        self.assertEqual(
            validate_weekend_post_format(
                "SMART MONEY HUB | LIQUIDITY\n\nA SHORT HEADLINE"
            ),
            "weekend_brand_header_missing",
        )
        self.assertEqual(
            validate_weekend_post_format(
                "🎣 SMART MONEY HUB\n━━━━━━━━━━━━━━\n\n"
                "UNDERSTANDING LIQUIDITY SWEEPS"
            ),
            "weekend_brand_header_missing",
        )
        self.assertEqual(
            validate_weekend_post_format(
                "💧 SMART MONEY HUB | LIQUIDITY\n\nA headline in sentence case"
            ),
            "weekend_headline_not_uppercase",
        )

    def test_unsupported_emoji_brand_header_is_corrected_before_full_validation(
        self,
    ) -> None:
        generated = (
            "🎣 SMART MONEY HUB | LIQUIDITY\n"
            "━━━━━━━━━━━━━━\n\n"
            "LIQUIDITY SWEEPS IN CONTEXT\n\n"
            "A liquidity sweep occurs when price moves beyond a recognizable high "
            "or low where liquidity may be resting. It does not identify who placed "
            "orders or guarantee a reversal.\n\n"
            "⚠️ REMEMBER\n"
            "NO CONFIRMATION, NO ENTRY."
        )

        corrected = normalize_weekend_brand_header(generated, "education")

        self.assertTrue(corrected.startswith("💧 SMART MONEY HUB | LIQUIDITY\n"))
        self.assertIsNone(validate_channel_post(corrected, is_promo=False))
        self.assertIsNone(validate_weekend_post_format(corrected))
        self.assertIn("<b>💧 SMART MONEY HUB | LIQUIDITY</b>",
                      render_weekend_post_html(corrected))

    def test_non_emoji_prefix_is_not_silently_rewritten(self) -> None:
        generated = (
            "LATEST NEWS SMART MONEY HUB | LIQUIDITY\n"
            "━━━━━━━━━━━━━━\n\n"
            "A LIQUIDITY LESSON\n\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        self.assertEqual(
            normalize_weekend_brand_header(generated, "education"),
            generated,
        )
        self.assertEqual(
            validate_weekend_post_format(generated),
            "weekend_brand_header_missing",
        )

    def test_generated_header_is_normalized_before_draft_is_saved(self) -> None:
        settings = self.store.get_channel_posting_settings()
        sequence = int(settings["next_category_index"])
        post, created = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-24",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=sequence,
            next_promo_feature_index=int(settings["next_promo_feature_index"]),
            last_promo_date=settings.get("last_promo_date"),
            status="failed",
            failure_category="gemini_generation_pending",
            generation_source="gemini_pending",
        )
        self.assertTrue(created)
        self.writer.drafts.append(
            ChannelDraft(
                category="education",
                content=(
                    "🎣 SMART MONEY HUB | LIQUIDITY\n"
                    "━━━━━━━━━━━━━━\n\n"
                    "LIQUIDITY SWEEPS IN CONTEXT\n\n"
                    "A liquidity sweep occurs when price moves beyond a recognizable "
                    "high or low where liquidity may be resting. It does not identify "
                    "who placed orders or guarantee a reversal.\n\n"
                    "⚠️ REMEMBER\n"
                    "NO CONFIRMATION, NO ENTRY."
                ),
            )
        )

        saved = self.manager._generate_gemini_post(
            post,
            preferred_category="education",
            sequence=sequence,
            settings=settings,
        )

        self.assertEqual(saved["status"], "draft")
        self.assertTrue(saved["content"].startswith("💧 SMART MONEY HUB | LIQUIDITY"))
        self.assertIsNone(validate_channel_post(saved["content"], is_promo=False))
        self.assertIsNone(validate_weekend_post_format(saved["content"]))
        self.assertEqual(self.api.channel_attempts, [])

    def test_generated_weekend_validation_failure_keeps_editable_draft_and_retries_same_row(
        self,
    ) -> None:
        rejected = ChannelDraft(
            category="education",
            content=(
                "A useful but unbranded SMC lesson.\n\n"
                f"{PROMO_FEATURES[0]}\n"
                "Open @SmartMoneyHubSignalsBot and tap Start: "
                "https://t.me/SmartMoneyHubSignalsBot\n\n"
                "The learning Coach is separate from PRO Signals.\n\n"
                "NO CONFIRMATION, NO ENTRY."
            ),
        )
        self.writer.drafts.append(rejected)
        self.manager.dispatch_due(local_time(23, 18))

        saved = self.store.get_scheduled_channel_post("2026-10-24")
        assert saved is not None
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(
            saved["failure_category"],
            "gemini_content_rejected_weekend_brand_header_missing",
        )
        self.assertEqual(saved["content"], rejected.content)
        self.assertEqual(saved["generation_source"], "gemini_pending")
        self.assertEqual(self.api.channel_attempts, [])

        self.manager.show_post(ADMIN_ID, saved)
        self.assertIn("failed this check", self.api.messages[-1]["text"])
        buttons = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        self.assertTrue(
            any(
                button["text"] == "Retry AI Draft"
                for row in buttons
                for button in row
            )
        )

        post_id = int(saved["id"])
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:retry_generation:{post_id}",
            local_time(23, 18, 5),
        )
        retried = self.store.get_scheduled_channel_post("2026-10-24")
        assert retried is not None
        self.assertEqual(retried["id"], post_id)
        self.assertEqual(retried["status"], "draft")
        self.assertEqual(retried["generation_source"], "gemini")
        self.assertEqual(self.api.channel_attempts, [])
        same_date_posts = [
            post
            for post in self.store.list_channel_posts(limit=20)
            if post["schedule_date"] == "2026-10-24"
        ]
        self.assertEqual(len(same_date_posts), 1)

    def test_generated_draft_gets_required_rule_appended_before_validation(self) -> None:
        post, created = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-26",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=0,
            next_promo_feature_index=0,
            last_promo_date=None,
            status="failed",
            failure_category="gemini_generation_pending",
            generation_source="gemini_pending",
        )
        self.assertTrue(created)
        self.writer.drafts.append(
            ChannelDraft(
                category="education",
                content=(
                    "📚 SMART MONEY HUB | EDUCATION\n\n"
                    "WAIT FOR EVIDENCE BEFORE DECIDING\n\n"
                    "A useful lesson about waiting for evidence before deciding."
                ),
            )
        )

        settings = self.store.get_channel_posting_settings()
        saved = self.manager._generate_gemini_post(
            post,
            preferred_category="education",
            sequence=0,
            settings=settings,
        )

        self.assertEqual(saved["status"], "draft")
        self.assertTrue(saved["content"].endswith("NO CONFIRMATION, NO ENTRY."))
        self.assertIsNone(validate_channel_post(saved["content"], is_promo=False))
        self.assertEqual(self.api.channel_attempts, [])
        normalized = self.manager._with_required_trading_rule(
            "A reminder: no confirmation, no entry"
        )
        self.assertEqual(normalized, "A reminder: NO CONFIRMATION, NO ENTRY.")

    def test_admin_can_add_required_rule_to_saved_rejected_draft_for_review(self) -> None:
        original = (
            "📚 SMART MONEY HUB | EDUCATION\n\n"
            "WAIT FOR EVIDENCE BEFORE DECIDING\n\n"
            "A useful lesson about waiting for evidence before deciding."
        )
        post, created = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-26",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=0,
            next_promo_feature_index=0,
            last_promo_date=None,
            status="failed",
            failure_category="gemini_generation_pending",
            generation_source="gemini_pending",
        )
        self.assertTrue(created)
        self.store.set_channel_post_status(
            int(post["id"]),
            "failed",
            action="gemini_generation_failed",
            failure_category="gemini_content_rejected_missing_golden_rule",
            rejected_content=original,
        )
        failed = self.store.get_channel_post(int(post["id"]))
        assert failed is not None

        self.manager.show_post(ADMIN_ID, failed)
        buttons = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        self.assertIn(
            f"admin:channel_posts:add_required_rule:{post['id']}",
            {button["callback_data"] for row in buttons for button in row},
        )
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:add_required_rule:{post['id']}",
            local_time(26, 8, 20),
        )

        corrected = self.store.get_channel_post(int(post["id"]))
        assert corrected is not None
        self.assertEqual(corrected["status"], "draft")
        self.assertTrue(corrected["content"].endswith("NO CONFIRMATION, NO ENTRY."))
        self.assertEqual(self.api.channel_attempts, [])
        self.assertTrue(
            any(
                "nothing was sent to the channel" in message["text"].lower()
                for message in self.api.messages
            )
        )

    def test_existing_gemini_draft_missing_brand_format_can_be_retried_safely(
        self,
    ) -> None:
        original = "Older Gemini draft without its required branded heading.\n\nNO CONFIRMATION, NO ENTRY."
        post, created = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-24",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content=original,
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=1,
            next_promo_feature_index=0,
            last_promo_date=None,
            generation_source="gemini",
        )
        self.assertTrue(created)

        self.manager.dispatch_due(final_review_time(24))
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(24, 9, 56),
        )
        post = self.store.get_channel_post(post["id"])
        assert post is not None
        self.manager._publish(
            post,
            self.manager._as_utc(local_time(24, 10)),
            automatic=False,
            admin_id=ADMIN_ID,
        )
        rejected = self.store.get_channel_post(post["id"])
        assert rejected is not None
        self.assertEqual(
            rejected["failure_category"],
            "weekend_brand_header_missing",
        )
        self.assertEqual(rejected["content"], original)
        self.assertEqual(self.api.channel_attempts, [])

        self.manager.show_post(ADMIN_ID, rejected)
        self.assertIn("branded divider", self.api.messages[-1]["text"])
        buttons = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        labels = {button["text"] for row in buttons for button in row}
        self.assertIn("Retry AI Draft", labels)
        self.assertNotIn("🚀 Publish Now", labels)

        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:retry_generation:{post['id']}",
            local_time(24, 10, 5),
        )
        retried = self.store.get_channel_post(post["id"])
        assert retried is not None
        self.assertEqual(retried["status"], "draft")
        self.assertEqual(retried["generation_source"], "gemini")
        self.assertTrue(retried["content"].startswith("📚 SMART MONEY HUB | EDUCATION"))
        self.assertEqual(self.api.channel_attempts, [])

    def test_daily_schedule_sends_one_post_after_admin_preview(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        store.set_weekend_auto_publish_enabled(False)
        monday_preview = datetime(2026, 10, 26, 8, 15, tzinfo=ZoneInfo("UTC"))
        manager.dispatch_due(monday_preview)

        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        assert post["schedule_time"] == "10:00"
        assert post["preview_sent_at"] is not None
        self.assertEqual(post["generation_source"], "gemini")
        self.assertEqual(len(self.writer.calls), 1)
        assert api.messages[-1]["chat_id"] == ADMIN_ID
        assert api.channel_messages == []

        manager.dispatch_due(final_review_time(26))
        review = api.messages[-1]
        self.assertIn("FINAL SCHEDULED POST REVIEW", review["text"])
        self.assertIn(f"ID {CHANNEL_ID}", review["text"])
        self.assertIn("Monday, 26 October 2026 at 10:00 WAT", review["text"])
        self.assertIn(post["content"], review["text"])
        self.assertEqual(
            [
                button["text"]
                for button in review["reply_markup"]["inline_keyboard"][0]
            ],
            ["✅ Approve", "✏️ Edit", "❌ Cancel"],
        )
        self.assertEqual(
            review["reply_markup"]["inline_keyboard"][1][0]["text"],
            "📷 Add photo",
        )
        self.assertIn("If you do not send a photo", review["text"])
        self.assertIn("No review response is required", review["text"])
        manager.dispatch_due(final_review_time(26))
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
        manager.dispatch_due(local_time(26, 10))
        manager.dispatch_due(local_time(26, 10, 1))

        saved = store.get_scheduled_channel_post("2026-10-26")
        assert saved is not None
        assert saved["status"] == "published"
        assert saved["destination_chat_id"] == CHANNEL_ID
        assert saved["telegram_message_id"] == 9001
        assert len(api.channel_messages) == 1
        assert {message["chat_id"] for message in api.channel_attempts} == {CHANNEL_ID}
        assert api.channel_messages[0]["parse_mode"] == "HTML"
        assert api.channel_messages[0]["text"].startswith(
            "<b>📚 SMART MONEY HUB | EDUCATION</b>"
        )

    def test_weekday_gemini_failure_holds_post_without_local_fallback(self) -> None:
        self.writer.failures.append(
            GeminiChannelGenerationError("gemini_rate_limit", 429)
        )

        self.manager.dispatch_due(local_time(26, 9, 15))

        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.assertEqual(post["status"], "failed")
        self.assertEqual(post["generation_source"], "gemini_pending")
        self.assertEqual(post["content"], "")
        self.assertEqual(len(self.writer.calls), 1)
        self.assertEqual(self.api.channel_messages, [])
        self.assertFalse(
            any(
                "FINAL SCHEDULED POST REVIEW" in message["text"]
                for message in self.api.messages
            )
        )
        self.assertTrue(
            any(
                "no Market Analysis post was sent" in message["text"]
                for message in self.api.messages
            )
        )

    def test_scheduled_gemini_timeout_retries_after_restart_without_duplicate_posts(self) -> None:
        self.writer.failures.append(
            GeminiChannelGenerationError("gemini_timeout")
        )
        self.manager.dispatch_due(local_time(26, 9, 15))

        failed = self.store.get_scheduled_channel_post("2026-10-26")
        assert failed is not None
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["generation_retry_count"], 0)
        self.assertEqual(
            failed["generation_retry_at"],
            local_time(26, 9, 20).astimezone(ZoneInfo("UTC")).isoformat(),
        )
        self.assertEqual(self.api.channel_messages, [])
        self.assertIn("retry automatically", self.api.messages[0]["text"].lower())

        restarted_store = Repository(
            f"{self.temp_dir.name}/channel-posts.sqlite3"
        )
        restarted_manager = ChannelPostManager(
            self.api,
            restarted_store,
            ADMIN_ID,
            CHANNEL_ID,
            channel_writer=self.writer,
        )
        restarted_manager.dispatch_due(local_time(26, 9, 19))
        self.assertEqual(len(self.writer.calls), 1)
        restarted_manager.dispatch_due(local_time(26, 9, 20))

        saved = restarted_store.get_scheduled_channel_post("2026-10-26")
        assert saved is not None
        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["generation_retry_count"], 1)
        self.assertIsNone(saved["generation_retry_at"])
        self.assertEqual(len(self.writer.calls), 2)
        self.assertEqual(self.api.channel_messages, [])
        self.assertTrue(saved["preview_sent_at"])
        self.assertEqual(
            sum("CHANNEL POST —" in message["text"] for message in self.api.messages),
            1,
        )

        # Repeated scheduler ticks after success reuse the same saved draft.
        restarted_manager.dispatch_due(local_time(26, 9, 20))
        self.assertEqual(len(self.writer.calls), 2)
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(
            sum("CHANNEL POST —" in message["text"] for message in self.api.messages),
            1,
        )

    def test_interrupted_generation_retry_is_recovered_after_restart(self) -> None:
        self.writer.failures.append(
            GeminiChannelGenerationError("gemini_timeout")
        )
        self.manager.dispatch_due(local_time(26, 9, 15))
        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None

        claimed = self.store.claim_channel_post_generation_retry(
            int(post["id"]),
            at=local_time(26, 9, 20).astimezone(ZoneInfo("UTC")).isoformat(),
            lease_until=local_time(26, 9, 22).astimezone(ZoneInfo("UTC")).isoformat(),
            max_retries=2,
        )
        assert claimed is not None
        self.assertEqual(claimed["generation_retry_count"], 1)

        restarted_store = Repository(
            f"{self.temp_dir.name}/channel-posts.sqlite3"
        )
        restarted_manager = ChannelPostManager(
            self.api,
            restarted_store,
            ADMIN_ID,
            CHANNEL_ID,
            channel_writer=self.writer,
        )
        restarted_manager.dispatch_due(local_time(26, 9, 23))
        recovered = restarted_store.get_channel_post(post["id"])
        assert recovered is not None
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["generation_retry_count"], 1)
        self.assertEqual(
            recovered["generation_retry_at"],
            local_time(26, 9, 38).astimezone(ZoneInfo("UTC")).isoformat(),
        )

        restarted_manager.dispatch_due(local_time(26, 9, 38))
        completed = restarted_store.get_channel_post(post["id"])
        assert completed is not None
        self.assertEqual(completed["status"], "draft")
        self.assertEqual(completed["generation_retry_count"], 2)
        self.assertEqual(len(self.writer.calls), 2)
        self.assertEqual(self.api.channel_messages, [])
        self.assertTrue(completed["preview_sent_at"])

    def test_scheduled_gemini_timeout_retries_are_bounded(self) -> None:
        self.writer.failures.extend(
            [
                GeminiChannelGenerationError("gemini_timeout"),
                GeminiChannelGenerationError("gemini_timeout"),
                GeminiChannelGenerationError("gemini_timeout"),
            ]
        )
        self.manager.dispatch_due(local_time(26, 9, 15))
        self.manager.dispatch_due(local_time(26, 9, 20))
        self.manager.dispatch_due(local_time(26, 9, 35))

        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.assertEqual(post["status"], "failed")
        self.assertEqual(post["generation_retry_count"], 2)
        self.assertIsNone(post["generation_retry_at"])
        self.assertEqual(post["content"], "")
        self.assertEqual(len(self.writer.calls), 3)
        self.assertEqual(self.api.channel_messages, [])
        self.assertIn(
            "retries are exhausted",
            self.api.messages[-1]["text"].lower(),
        )

        self.manager.dispatch_due(local_time(26, 9, 36))
        self.assertEqual(len(self.writer.calls), 3)

    def test_timeout_retry_is_not_started_if_final_review_window_is_too_close(self) -> None:
        self.writer.failures.append(
            GeminiChannelGenerationError("gemini_timeout")
        )
        self.manager.dispatch_due(local_time(26, 9, 50))

        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.assertEqual(post["status"], "failed")
        self.assertIsNone(post["generation_retry_at"])
        self.assertEqual(len(self.writer.calls), 1)
        self.assertEqual(self.api.channel_messages, [])
        self.assertIn(
            "not enough time to retry",
            self.api.messages[-1]["text"].lower(),
        )

    def test_photo_uploaded_during_final_review_publishes_with_post_once(self) -> None:
        self.manager.dispatch_due(local_time(26, 9, 15))
        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.manager.dispatch_due(final_review_time(26))

        self.assertTrue(
            self.manager.handle_callback(
                ADMIN_ID,
                ADMIN_ID,
                f"admin:channel_posts:photo:{post['id']}",
                local_time(26, 9, 56),
            )
        )

        # The requested upload survives a bot restart because the pending state
        # and the eventual Telegram file_id are stored with the scheduled post.
        restarted_store = Repository(
            f"{self.temp_dir.name}/channel-posts.sqlite3"
        )
        restarted_manager = ChannelPostManager(
            self.api,
            restarted_store,
            ADMIN_ID,
            CHANNEL_ID,
            channel_writer=self.writer,
        )
        self.assertTrue(
            restarted_manager.handle_admin_photo(
                ADMIN_ID,
                ADMIN_ID,
                [
                    {"file_id": "small-photo-id", "file_size": 100},
                    {"file_id": "large-photo-id", "file_size": 500},
                ],
                is_private=True,
                now=local_time(26, 9, 57),
            )
        )
        saved = restarted_store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["photo_file_id"], "large-photo-id")
        self.assertEqual(saved["review_status"], "pending")

        restarted_manager.dispatch_due(local_time(26, 10))
        restarted_manager.dispatch_due(local_time(26, 10, 1))

        saved = restarted_store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["status"], "published")
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(self.api.channel_messages[0]["photo"], "large-photo-id")
        self.assertEqual(self.api.channel_messages[0]["chat_id"], CHANNEL_ID)
        self.assertEqual(self.api.channel_messages[0]["parse_mode"], "HTML")
        self.assertIn("<b>", self.api.channel_messages[0]["caption"])

    def test_no_review_or_photo_response_publishes_text_only_at_schedule(self) -> None:
        self.manager.dispatch_due(local_time(26, 9, 15))
        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.manager.dispatch_due(final_review_time(26))
        self.manager.dispatch_due(local_time(26, 10))

        saved = self.store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["status"], "published")
        self.assertEqual(saved["review_status"], "timed_out")
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertNotIn("photo", self.api.channel_messages[0])
        self.assertEqual(self.api.channel_messages[0]["chat_id"], CHANNEL_ID)

    def test_review_approval_is_persisted_until_scheduled_publication(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.assertEqual(post["review_status"], "pending")

        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
        self.assertEqual(store.get_channel_post(post["id"])["review_status"], "approved")
        self.assertEqual(api.channel_messages, [])
        manager.dispatch_due(local_time(26, 10))

        saved = store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["status"], "published")
        self.assertEqual(saved["publish_attempts"], 1)
        self.assertEqual(len(api.channel_messages), 1)

    def test_review_cancel_prevents_publication(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_cancel:{post['id']}",
            local_time(26, 9, 56),
        )
        manager.dispatch_due(local_time(26, 10))

        saved = store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["review_status"], "cancelled")
        self.assertEqual(saved["status"], "skipped")
        self.assertEqual(api.channel_messages, [])

    def test_review_edit_is_validated_and_published_at_schedule(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        edited = TELEGRAM_LAYOUT_SAMPLES[0]
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:edit:{post['id']}",
            local_time(26, 9, 56),
        )
        self.assertTrue(
            manager.handle_edit_message(
                ADMIN_ID,
                ADMIN_ID,
                edited,
                True,
                now=local_time(26, 9, 57),
            )
        )
        saved = store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["review_status"], "edited")
        self.assertEqual(saved["content"], edited)
        manager.dispatch_due(local_time(26, 10))

        self.assertEqual(store.get_channel_post(post["id"])["status"], "published")
        self.assertIn("TODAY’S TRADING LESSON", api.channel_messages[0]["text"])

    def test_review_timeout_recovers_after_restart_without_duplicate_send(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        reopened = Repository(store.database_path)
        restarted = ChannelPostManager(api, reopened, ADMIN_ID, CHANNEL_ID)
        restarted.dispatch_due(local_time(26, 10))
        restarted.dispatch_due(local_time(26, 10, 1))

        saved = reopened.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["review_status"], "timed_out")
        self.assertEqual(saved["status"], "published")
        self.assertEqual(saved["publish_attempts"], 1)
        self.assertEqual(len(api.channel_messages), 1)

    def test_missing_review_window_auto_publishes_on_time_without_approval(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(local_time(23, 18))
        manager.dispatch_due(local_time(24, 10))
        post = store.get_scheduled_channel_post("2026-10-24")
        assert post is not None
        self.assertEqual(post["review_status"], "missed")
        self.assertEqual(post["status"], "published")
        self.assertEqual(post["publish_attempts"], 1)
        self.assertEqual(len(api.channel_messages), 1)
        self.assertTrue(
            any(
                "published at its scheduled time without approval"
                in message["text"]
                for message in api.messages
            )
        )
        manager.dispatch_due(local_time(24, 10, 1))
        published = store.get_channel_post(post["id"])
        assert published is not None
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["review_status"], "missed")
        self.assertEqual(published["publish_attempts"], 1)
        self.assertEqual(len(api.channel_messages), 1)
        self.assertEqual(api.channel_messages[0]["chat_id"], CHANNEL_ID)
        connection = store._connect()
        try:
            actions = connection.execute(
                "SELECT action, admin_id FROM channel_post_actions WHERE post_id=?",
                (post["id"],),
            ).fetchall()
        finally:
            connection.close()
        self.assertTrue(
            any(action["action"] == "published" for action in actions)
        )

        # Subsequent scheduler passes cannot create a duplicate.
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{post['id']}",
            local_time(24, 10, 3),
        )
        self.assertEqual(len(api.channel_messages), 1)

    def test_review_missed_outside_on_time_grace_remains_held(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(local_time(23, 18))
        manager.dispatch_due(local_time(24, 10, 2))
        post = store.get_scheduled_channel_post("2026-10-24")
        assert post is not None
        self.assertEqual(post["review_status"], "missed")
        self.assertEqual(post["status"], "draft")
        self.assertEqual(post["publish_attempts"], 0)
        self.assertEqual(api.channel_messages, [])
        self.assertTrue(
            any("published late" in message["text"] for message in api.messages)
        )
        manager.dispatch_due(local_time(24, 10, 5))
        self.assertEqual(api.channel_messages, [])

        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{post['id']}",
            local_time(24, 10, 6),
        )
        published = store.get_channel_post(post["id"])
        assert published is not None
        self.assertEqual(published["status"], "published")
        self.assertEqual(len(api.channel_messages), 1)

    def test_admin_publish_now_recovers_draft_when_review_was_never_sent(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.assertEqual(post["status"], "draft")
        self.assertEqual(post["review_status"], "not_requested")

        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{post['id']}",
            local_time(26, 10),
        )

        published = store.get_channel_post(post["id"])
        assert published is not None
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["publish_attempts"], 1)
        self.assertEqual(len(api.channel_messages), 1)
        self.assertFalse(
            any(
                "not approved for publication" in message["text"]
                for message in api.messages
            )
        )

    def test_admin_publish_now_does_not_publish_unreviewed_draft_early(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None

        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{post['id']}",
            local_time(26, 9, 59),
        )

        saved = store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["publish_attempts"], 0)
        self.assertEqual(api.channel_messages, [])
        self.assertTrue(
            any("will not publish early" in message["text"] for message in api.messages)
        )

    def test_admin_publish_now_rejects_a_past_scheduled_date(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None

        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{post['id']}",
            local_time(27, 10),
        )

        saved = store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["publish_attempts"], 0)
        self.assertEqual(api.channel_messages, [])
        self.assertTrue(
            any(
                "only on this post's scheduled WAT date" in message["text"]
                for message in api.messages
            )
        )

    def test_failed_review_delivery_auto_publishes_at_schedule_if_checks_pass(self) -> None:
        manager, store, api = self.manager, self.store, self.api
        manager.dispatch_due(local_time(26, 9))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        api.message_failures.append(
            TelegramAPIError("sanitized review delivery failure", error_code=500)
        )

        manager.dispatch_due(final_review_time(26))
        manager.dispatch_due(local_time(26, 10))

        saved = store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["review_status"], "missed")
        self.assertEqual(saved["status"], "published")
        self.assertEqual(len(api.channel_messages), 1)
        self.assertTrue(
            any(
                "final private review message could not be delivered"
                in message["text"].casefold()
                for message in api.messages
            )
        )
        self.assertTrue(
            any(
                "published at its scheduled time without approval"
                in message["text"]
                for message in api.messages
            )
        )

    def test_weekend_post_uses_safe_html_and_accepts_confirmed_generic_channel_title(
        self,
    ) -> None:
        self.api.chat = {
            "id": CHANNEL_ID,
            "type": "channel",
            "title": "Smart Money Hub",
        }
        self.manager.dispatch_due(local_time(23, 18))
        self.manager.dispatch_due(final_review_time(24))
        self.manager.dispatch_due(local_time(24, 10))

        post = self.store.get_scheduled_channel_post("2026-10-24")
        assert post is not None
        self.assertEqual(post["status"], "published")
        self.assertEqual(len(self.api.channel_messages), 1)
        sent = self.api.channel_messages[0]
        self.assertEqual(sent["parse_mode"], "HTML")
        self.assertIn("<b>📚 SMART MONEY HUB | EDUCATION</b>", sent["text"])
        self.assertIn("<b>NO CONFIRMATION, NO ENTRY.</b>", sent["text"])

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

        manager.dispatch_due(final_review_time(24))
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

        manager.dispatch_due(final_review_time(25))
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
            "Gemini reached a usage or rate limit" in message["text"]
            and "no Market Analysis post was sent" in message["text"]
            for message in self.api.messages
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
        self.manager.show_post(ADMIN_ID, held)
        retry_buttons = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        self.assertTrue(
            any(
                button["text"] == "Retry AI Draft"
                for row in retry_buttons
                for button in row
            )
        )
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
        self.assertEqual(
            self.store.get_scheduled_channel_post("2026-10-24")["id"],
            legacy["id"],
        )
        self.assertEqual(self.api.channel_attempts, [])
        self.assertTrue(
            any(
                "passed the content checks" in message["text"]
                for message in self.api.messages
            )
        )

        self.manager.dispatch_due(final_review_time(24))
        self.manager.dispatch_due(local_time(24, 10))
        assert self.store.get_channel_post(legacy["id"])["status"] == "published"
        assert len(self.api.channel_messages) == 1

    def test_legacy_local_weekday_draft_is_held_until_gemini_replaces_it(self) -> None:
        legacy, created = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-26",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="Old weekday draft.\n\nNO CONFIRMATION, NO ENTRY.",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=1,
            next_promo_feature_index=0,
            last_promo_date=None,
        )
        self.assertTrue(created)

        self.manager.dispatch_due(local_time(25, 18))

        held = self.store.get_channel_post(legacy["id"])
        assert held is not None
        self.assertEqual(held["status"], "failed")
        self.assertEqual(held["failure_category"], "gemini_legacy_draft_held")
        self.assertEqual(held["content"], "Old weekday draft.\n\nNO CONFIRMATION, NO ENTRY.")
        self.assertEqual(held["generation_source"], "local")
        self.assertEqual(self.api.channel_messages, [])
        self.assertEqual(len(self.writer.calls), 0)

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

    def test_held_legacy_post_can_be_recovered_with_a_valid_admin_edit(self) -> None:
        legacy, _ = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-24",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="Saved legacy draft.\n\nNO CONFIRMATION, NO ENTRY.",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=1,
            next_promo_feature_index=0,
            last_promo_date=None,
        )
        held = self.manager._hold_legacy_channel_draft(legacy)
        self.assertEqual(held["status"], "failed")

        self.manager.show_post(ADMIN_ID, held)
        held_buttons = self.api.messages[-1]["reply_markup"]["inline_keyboard"]
        self.assertTrue(
            any(button["text"] == "✏️ Edit Post" for row in held_buttons for button in row)
        )

        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:edit:{legacy['id']}",
            local_time(24, 9),
        )
        revised = (
            "📚 SMART MONEY HUB | EDUCATION\n\n"
            "WAIT FOR PLANNED CONFIRMATION\n\n"
            "Wait for planned structure confirmation before entry.\n\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        self.assertTrue(
            self.manager.handle_edit_message(ADMIN_ID, ADMIN_ID, revised, True)
        )
        saved = self.store.get_channel_post(legacy["id"])
        self.assertEqual(saved["status"], "draft")
        self.assertIsNone(saved["failure_category"])
        self.assertEqual(saved["admin_edit_approved"], 1)
        self.assertFalse(self.api.channel_messages)

        self.manager.dispatch_due(final_review_time(24))
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{legacy['id']}",
            local_time(24, 9, 56),
        )
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{legacy['id']}",
            local_time(24, 10),
        )
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(self.api.channel_messages[0]["parse_mode"], "HTML")
        self.assertIn("<b>📚 SMART MONEY HUB | EDUCATION</b>", self.api.channel_messages[0]["text"])

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

        manager.dispatch_due(final_review_time(26))
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

        edited = TELEGRAM_LAYOUT_SAMPLES[0]
        if post["is_promo"]:
            edited = compose_promo_post(
                edited,
                post["bot_username"],
                0,
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
        manager.dispatch_due(final_review_time(26))
        review_post = store.get_scheduled_channel_post("2026-10-26")
        assert review_post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{review_post['id']}",
            local_time(26, 9, 56),
        )
        manager.dispatch_due(local_time(26, 10))

        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        assert post["status"] == "failed"
        assert post["failure_category"] == "destination_not_verified"
        assert api.channel_messages == []
        self.assertTrue(
            any(
                "Smart Money Hub PRO Signals" in message["text"]
                and str(CHANNEL_ID) in message["text"]
                for message in api.messages
            )
        )

        manager.show_post(ADMIN_ID, post)
        self.assertIn("Status: Destination Not Verified", api.messages[-1]["text"])
        failed_post_buttons = api.messages[-1]["reply_markup"]["inline_keyboard"]
        self.assertTrue(
            any(
                button["text"] == "✏️ Edit Post"
                for row in failed_post_buttons
                for button in row
            )
        )
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:edit:{post['id']}",
            local_time(26, 10, 1),
        )
        corrected = TELEGRAM_LAYOUT_SAMPLES[0]
        if post["is_promo"]:
            corrected = compose_promo_post(
                corrected,
                post["bot_username"],
                0,
            )
        self.assertTrue(
            manager.handle_edit_message(ADMIN_ID, ADMIN_ID, corrected, True)
        )
        corrected_post = store.get_channel_post(post["id"])
        self.assertEqual(corrected_post["status"], "draft")
        self.assertEqual(corrected_post["admin_edit_approved"], 1)
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{post['id']}",
            local_time(26, 10, 2),
        )
        blocked_again = store.get_channel_post(post["id"])
        self.assertEqual(blocked_again["status"], "failed")
        self.assertEqual(blocked_again["failure_category"], "destination_not_verified")
        self.assertEqual(api.channel_messages, [])

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
        manager.dispatch_due(final_review_time(27))
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{store.get_scheduled_channel_post('2026-10-27')['id']}",
            local_time(27, 9, 56),
        )
        manager.dispatch_due(local_time(27, 10))
        permission_blocked = store.get_scheduled_channel_post("2026-10-27")
        assert permission_blocked is not None
        assert permission_blocked["status"] == "failed"
        assert permission_blocked["failure_category"] == "posting_permission_missing"

    def test_wrong_configured_channel_id_is_blocked_before_telegram_send(self) -> None:
        self.manager.dispatch_due(local_time(26, 9))
        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.manager.destination_chat_id = CHANNEL_ID + 1

        self.manager.dispatch_due(final_review_time(26))
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
        self.manager.dispatch_due(local_time(26, 10))

        saved = self.store.get_channel_post(post["id"])
        assert saved is not None
        self.assertEqual(saved["failure_category"], "destination_mismatch")
        self.assertEqual(self.api.channel_attempts, [])

    def test_telegram_destination_verification_api_error_is_reported_safely(
        self,
    ) -> None:
        self.api.get_chat_error = TelegramAPIError("sanitized test transport failure")
        self.manager.dispatch_due(local_time(26, 9))
        self.manager.dispatch_due(final_review_time(26))
        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
        self.manager.dispatch_due(local_time(26, 10))

        post = self.store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        self.assertEqual(post["failure_category"], "destination_verification_unavailable")
        self.assertEqual(self.api.channel_attempts, [])
        self.assertTrue(
            any(
                str(CHANNEL_ID) in message["text"]
                and "check the bot's channel access" in message["text"].casefold()
                for message in self.api.messages
            )
        )

    def test_telegram_rate_limit_gets_one_bounded_retry(self) -> None:
        store, api, manager = self.store, self.api, self.manager
        manager.dispatch_due(local_time(26, 9))
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
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
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
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
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
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
        manager.dispatch_due(final_review_time(26))
        post = store.get_scheduled_channel_post("2026-10-26")
        assert post is not None
        manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(26, 9, 56),
        )
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

    def test_unverified_institutional_intent_claim_is_rejected(self) -> None:
        claim = (
            "Institutional participants frequently use liquidity zones to absorb "
            "orders before shifting direction."
        )
        post = f"{claim}\n\nNO CONFIRMATION, NO ENTRY."

        self.assertEqual(
            validate_channel_post(post, is_promo=False),
            "unsupported_institutional_intent",
        )
        self.assertIn(
            "institutions or other market participants",
            describe_channel_post_rejection(
                post, "unsupported_institutional_intent"
            ).casefold(),
        )
        self.assertIsNone(
            validate_channel_post(
                post,
                is_promo=False,
                verified_information=[claim],
            )
        )

    def test_timeout_notice_does_not_claim_an_unsaved_draft_exists(self) -> None:
        message = describe_channel_post_rejection("", "gemini_timeout")
        self.assertIn("No publishable draft was saved", message)
        self.assertIn("request timed out", message)
        self.assertNotIn("review the saved draft", message.casefold())

    def test_unverified_current_market_claim_is_rejected(self) -> None:
        post = "Gold is bullish today.\n\nNO CONFIRMATION, NO ENTRY."

        self.assertEqual(
            validate_channel_post(post, is_promo=False),
            "unverified_market_claim",
        )
        self.assertIsNone(
            validate_channel_post(
                post,
                is_promo=False,
                verified_information=["Gold is bullish today."],
            )
        )

    def test_unsourced_liquidity_and_sweep_frequency_claims_are_rejected(self) -> None:
        overconfident = (
            "Liquidity often rests beyond swing highs where orders naturally "
            "accumulate. A sweep frequently triggers a reaction.\n\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        cautious = (
            "A liquidity sweep occurs when price moves beyond a recognizable high "
            "or low where liquidity may be resting.\n\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        self.assertEqual(
            validate_channel_post(overconfident, is_promo=False),
            "unsupported_liquidity_assertion",
        )
        self.assertIsNone(validate_channel_post(cautious, is_promo=False))

    def test_unsupported_liquidity_claim_is_saved_as_held_draft(self) -> None:
        settings = self.store.get_channel_posting_settings()
        sequence = int(settings["next_category_index"])
        post, created = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-24",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content="",
            destination_chat_id=CHANNEL_ID,
            is_promo=False,
            bot_username=None,
            next_category_index=sequence,
            next_promo_feature_index=int(settings["next_promo_feature_index"]),
            last_promo_date=settings.get("last_promo_date"),
            status="failed",
            failure_category="gemini_generation_pending",
            generation_source="gemini_pending",
        )
        self.assertTrue(created)
        rejected = (
            "📚 SMART MONEY HUB\n"
            "━━━━━━━━━━━━━━\n\n"
            "UNDERSTANDING LIQUIDITY SWEEPS\n\n"
            "Liquidity often rests beyond swing highs where orders naturally "
            "accumulate. A sweep frequently triggers a reaction.\n\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        self.writer.drafts.append(ChannelDraft("education", rejected))

        saved = self.manager._generate_gemini_post(
            post,
            preferred_category="education",
            sequence=sequence,
            settings=settings,
        )

        self.assertEqual(saved["status"], "failed")
        self.assertEqual(
            saved["failure_category"],
            "gemini_content_rejected_unsupported_liquidity_assertion",
        )
        self.assertEqual(
            saved["content"],
            normalize_weekend_brand_header(rejected, "education"),
        )
        self.assertEqual(self.api.channel_attempts, [])

    def test_unverified_promo_error_names_claim_and_safe_correction(self) -> None:
        claim = "The Smart Money Hub bot predicts exact Gold entries for you."
        text = (
            f"{claim}\n"
            "Open @SmartMoneyHubSignalsBot and tap Start: "
            "https://t.me/SmartMoneyHubSignalsBot\n"
            "NO CONFIRMATION, NO ENTRY."
        )

        self.assertEqual(
            validate_channel_post(
                text,
                is_promo=True,
                bot_username="SmartMoneyHubSignalsBot",
            ),
            "unverified_promo_feature",
        )
        explanation = describe_channel_post_rejection(
            text,
            "unverified_promo_feature",
            bot_username="SmartMoneyHubSignalsBot",
        )
        self.assertIn(f"“{claim}”", explanation)
        self.assertIn(PROMO_FEATURES[0], explanation)
        self.assertIn("remove the bot promotion completely", explanation)
        self.assertIn("saved draft is unchanged", explanation)

    def test_verified_promo_and_nonpromo_education_both_validate(self) -> None:
        valid_promo = (
            f"{PROMO_FEATURES[1]}\n"
            "Open @SmartMoneyHubSignalsBot and tap Start: "
            "https://t.me/SmartMoneyHubSignalsBot\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        education = (
            "A liquidity sweep alone does not confirm a reversal. Wait for "
            "the evidence required by your plan.\n\nNO CONFIRMATION, NO ENTRY."
        )

        self.assertTrue(is_promotional_content(valid_promo))
        self.assertIsNone(
            validate_channel_post(
                valid_promo,
                is_promo=True,
                bot_username="SmartMoneyHubSignalsBot",
            )
        )
        self.assertFalse(is_promotional_content(education))
        self.assertIsNone(validate_channel_post(education, is_promo=False))

    def test_missing_golden_rule_has_a_plain_language_correction(self) -> None:
        text = "A useful educational post without its required footer."
        self.assertEqual(
            validate_channel_post(text, is_promo=False),
            "missing_golden_rule",
        )
        explanation = describe_channel_post_rejection(
            text,
            "missing_golden_rule",
        )
        self.assertIn("NO CONFIRMATION, NO ENTRY.", explanation)
        self.assertIn("Add required rule", explanation)
        self.assertIn("Nothing will be published automatically", explanation)

    def test_admin_can_retry_edit_remove_promo_and_publish_only_on_action(self) -> None:
        original = (
            f"Weekly learning reminder.\n\n{PROMO_FEATURES[0]}\n"
            "Open @SmartMoneyHubSignalsBot and tap Start: "
            "https://t.me/SmartMoneyHubSignalsBot\n"
            "The learning Coach is separate from PRO Signals.\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        post, _ = self.store.create_scheduled_channel_post(
            schedule_date="2026-10-24",
            schedule_time="10:00",
            requested_category="education",
            category="education",
            content=original,
            destination_chat_id=CHANNEL_ID,
            is_promo=True,
            bot_username="SmartMoneyHubSignalsBot",
            next_category_index=1,
            next_promo_feature_index=1,
            last_promo_date="2026-10-24",
        )
        self.assertTrue(
            self.store.start_channel_post_edit(post["id"], admin_id=ADMIN_ID)
        )

        invalid = (
            "Weekly learning reminder.\n\n"
            "The Smart Money Hub bot predicts exact Gold entries for you.\n"
            "Open @SmartMoneyHubSignalsBot and tap Start: "
            "https://t.me/SmartMoneyHubSignalsBot\n"
            "NO CONFIRMATION, NO ENTRY."
        )
        self.assertTrue(
            self.manager.handle_edit_message(ADMIN_ID, ADMIN_ID, invalid, True)
        )
        awaiting = self.store.get_channel_post(post["id"])
        self.assertEqual(awaiting["status"], "awaiting_edit")
        self.assertEqual(awaiting["content"], original)
        self.assertIn("predicts exact Gold entries", self.api.messages[-2]["text"])
        self.assertIn(original, self.api.messages[-1]["text"])

        education = (
            "💧 SMART MONEY HUB | LIQUIDITY\n\n"
            "WAIT FOR CONFIRMATION\n\n"
            "A sweep alone does not confirm a reversal. Wait for your planned "
            "evidence.\n\nNO CONFIRMATION, NO ENTRY."
        )
        self.assertTrue(
            self.manager.handle_edit_message(ADMIN_ID, ADMIN_ID, education, True)
        )
        saved = self.store.get_channel_post(post["id"])
        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["content"], education)
        self.assertEqual(saved["is_promo"], 0)
        self.assertEqual(saved["generation_source"], "local")
        self.assertEqual(saved["admin_edit_approved"], 1)
        self.assertEqual(self.api.channel_messages, [])

        reopened = Repository(self.store.database_path)
        persisted = reopened.get_channel_post(post["id"])
        self.assertEqual(persisted["content"], education)
        self.assertEqual(persisted["is_promo"], 0)
        self.assertEqual(persisted["admin_edit_approved"], 1)
        self.assertEqual(self.api.channel_messages, [])

        self.manager.dispatch_due(final_review_time(24))
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:review_approve:{post['id']}",
            local_time(24, 9, 56),
        )
        self.manager.handle_callback(
            ADMIN_ID,
            ADMIN_ID,
            f"admin:channel_posts:publish:{post['id']}",
            local_time(24, 10),
        )
        self.assertEqual(len(self.api.channel_messages), 1)
        self.assertEqual(self.api.channel_messages[0]["parse_mode"], "HTML")
        self.assertIn("<b>💧 SMART MONEY HUB | LIQUIDITY</b>", self.api.channel_messages[0]["text"])
        self.assertIn("<b>NO CONFIRMATION, NO ENTRY.</b>", self.api.channel_messages[0]["text"])

    def test_admin_controls_use_plain_action_labels(self) -> None:
        self.manager.dispatch_due(local_time(23, 18))
        post = self.store.get_scheduled_channel_post("2026-10-24")
        self.assertIsNotNone(post)

        self.manager.show_controls(ADMIN_ID)
        controls_markup = self.api.messages[-1]["reply_markup"]
        control_labels = {
            button["text"]
            for row in controls_markup["inline_keyboard"]
            for button in row
        }
        self.assertIn("⏸ Pause Channel Posts", control_labels)
        self.assertIn("👁 Preview Post — 2026-10-24", control_labels)

        self.manager.show_post(ADMIN_ID, post)
        post_markup = self.api.messages[-1]["reply_markup"]
        post_labels = {
            button["text"]
            for row in post_markup["inline_keyboard"]
            for button in row
        }
        self.assertIn("✏️ Edit Post", post_labels)
        self.assertIn("🚀 Publish Now", post_labels)
        self.assertIn("❌ Reject Post", post_labels)
        self.assertIn("⏭ Skip This Post", post_labels)

if __name__ == "__main__":
    unittest.main()
