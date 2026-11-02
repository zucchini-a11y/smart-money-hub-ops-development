"""Persistent daily channel-post scheduling and administrator review controls."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time as wall_time, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from .channel_content import (
    CHANNEL_CONTENT_CATEGORIES,
    describe_channel_post_rejection,
    is_promotional_content,
    normalize_weekend_brand_header,
    next_category,
    render_weekend_post_html,
    validate_channel_post,
    validate_weekend_post_format,
)
from .channel_gemini import (
    GeminiChannelContentService,
    GeminiChannelGenerationError,
)
from .daily_calendar_brief import DAILY_BRIEF_TIME, DailyCalendarBriefStore
from .storage import Repository
from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)
_MAX_FEEDBACK_CHARS = 300

CHANNEL_TIMEZONE = ZoneInfo("Africa/Lagos")
WEEKDAY_PUBLISH_TIME = wall_time(hour=10)
SATURDAY_PUBLISH_TIME = wall_time(hour=10)
SUNDAY_PUBLISH_TIME = wall_time(hour=18)
EVENING_PREVIEW_TIME = wall_time(hour=18)
PREVIEW_RETRY_DELAY = timedelta(minutes=5)
FINAL_REVIEW_LEAD = timedelta(minutes=5)
CHANNEL_POSTS_PAGE_SIZE = 5
MAX_AUTOMATIC_RATE_LIMIT_RETRIES = 1
MAX_AUTOMATIC_GENERATION_TIMEOUT_RETRIES = 2
_GENERATION_TIMEOUT_RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
)
_GENERATION_RETRY_LEASE = timedelta(minutes=2)
_GENERATION_RETRY_RECOVERY_DELAY = timedelta(minutes=1)
_GENERATION_RETRY_ATTEMPT_BUDGET = timedelta(minutes=1)
_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_SHARED_FOOTER = re.compile(
    r"no confirmation,\s*no entry\.?", re.IGNORECASE
)
_PROMO_LINK = re.compile(r"open\s+@\w+.*?https://t\.me/\w+", re.IGNORECASE | re.DOTALL)
_AI_RETRYABLE_CONTENT_FAILURES = {
    "content_too_long",
    "missing_golden_rule",
    "prohibited_signal_or_promise",
    "unverified_market_claim",
    "unsupported_institutional_intent",
    "unsupported_liquidity_assertion",
    "unexpected_bot_promotion",
    "weekend_brand_header_missing",
    "weekend_headline_missing",
    "weekend_headline_not_uppercase",
}


class ChannelPostManager:
    def __init__(
        self,
        api: TelegramAPI,
        store: Repository,
        admin_id: int | None,
        destination_chat_id: int | None,
        *,
        channel_writer: GeminiChannelContentService | None = None,
        daily_brief_store: DailyCalendarBriefStore | None = None,
        daily_brief_enabled: bool = False,
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self.destination_chat_id = destination_chat_id
        self.channel_writer = channel_writer
        self.daily_brief_store = daily_brief_store
        self.daily_brief_enabled = daily_brief_enabled
        self.timezone = CHANNEL_TIMEZONE
        self._recovered_inflight = False

    def has_edit_pending(self, admin_id: int) -> bool:
        return bool(self.store.pending_channel_post_edit(admin_id))

    def cancel_edit(self, admin_id: int) -> None:
        self.store.cancel_channel_post_edit(admin_id)

    def dispatch_due(self, now: datetime | None = None) -> None:
        if self.admin_id is None or self.destination_chat_id is None:
            logger.warning("Channel posting disabled: admin or destination is not configured.")
            return
        current_utc = self._as_utc(now or datetime.now(timezone.utc))
        local_now = current_utc.astimezone(self.timezone)

        if not self._recovered_inflight:
            self._notify_recovered_inflight()
            self._recovered_inflight = True

        settings = self.store.get_channel_posting_settings()
        today = local_now.date()
        local_time = local_now.time().replace(tzinfo=None)
        if local_time >= self._same_day_preview_time(today):
            self._ensure_and_preview(today, current_utc)
        if local_time >= EVENING_PREVIEW_TIME:
            self._ensure_and_preview(today + timedelta(days=1), current_utc)

        publish_time = self._publish_time(today)
        scheduled_at = datetime.combine(today, publish_time, tzinfo=self.timezone)
        review_at = scheduled_at - FINAL_REVIEW_LEAD
        post = self.store.get_scheduled_channel_post(today.isoformat())
        if (
            post
            and post["status"] == "draft"
            and post.get("review_status") == "not_requested"
            and review_at <= local_now < scheduled_at
        ):
            self._send_scheduled_review(post, current_utc, scheduled_at)
            post = self.store.get_channel_post(int(post["id"])) or post

        if settings["paused"] or local_now < scheduled_at:
            return
        if not post:
            return
        status = post["status"]
        if (
            today.weekday() in {5, 6}
            and not settings.get("weekend_auto_publish_enabled")
            and status in {"draft", "retry_wait"}
        ):
            changed = self.store.set_channel_post_status(
                int(post["id"]),
                "failed",
                action="template_approval_pending",
                failure_category="template_approval_pending",
                details="Weekend content template has not been approved.",
            )
            if changed:
                self.api.send_message(
                    self.admin_id,
                    "Weekend post held: the new template is waiting for your "
                    "approval. No channel post was sent. Weekend private previews "
                    "will continue.",
                )
            return
        if status == "awaiting_edit" and post.get("review_status") == "editing":
            if self.store.mark_channel_post_review_missed(
                int(post["id"]), at=current_utc.isoformat()
            ):
                missed = self.store.get_channel_post(int(post["id"])) or post
                self._notify_failure(missed, "scheduled_review_edit_incomplete")
            return
        if status == "draft" and post.get("review_status") == "pending":
            if self.store.timeout_channel_post_review(
                int(post["id"]), at=current_utc.isoformat()
            ):
                post = self.store.get_channel_post(int(post["id"])) or post
            else:
                return
        if status == "draft" and post.get("review_status") in {
            "not_requested",
            "sending",
        }:
            if self.store.mark_channel_post_review_missed(
                int(post["id"]), at=current_utc.isoformat()
            ):
                missed = self.store.get_channel_post(int(post["id"])) or post
                category = (
                    "scheduled_review_delivery_uncertain"
                    if post.get("review_status") == "sending"
                    else "scheduled_review_missed"
                )
                self._notify_failure(missed, category)
            return
        if status == "draft" and post.get("review_status") in {
            "approved",
            "edited",
            "timed_out",
        }:
            review_decision_at = self._parse_datetime(
                post.get("review_decision_at")
            )
            if (
                post.get("review_status") == "edited"
                and review_decision_at
                and self._as_utc(review_decision_at) > scheduled_at.astimezone(timezone.utc)
            ):
                self.store.set_channel_post_status(
                    int(post["id"]),
                    "failed",
                    action="scheduled_review_edit_late",
                    details="A late edit was saved; the post was held rather than published late.",
                    failure_category="scheduled_review_edit_late",
                )
                failed = self.store.get_channel_post(int(post["id"])) or post
                self._notify_failure(failed, "scheduled_review_edit_late")
                return
            self._publish(post, current_utc, automatic=True)
        elif status == "retry_wait" and self._retry_is_due(post, current_utc):
            self._publish(post, current_utc, automatic=True)

    def show_controls(
        self,
        chat_id: int,
        *,
        page: int = 0,
        now: datetime | None = None,
    ) -> None:
        settings = self.store.get_channel_posting_settings()
        paused = bool(settings["paused"])
        current_utc = self._as_utc(now or datetime.now(timezone.utc))
        local_now = current_utc.astimezone(self.timezone)
        from_date = local_now.date().isoformat()
        upcoming_count = self.store.count_upcoming_channel_posts(
            from_date=from_date,
            destination_chat_id=self.destination_chat_id,
        )
        page_count = max(
            1,
            (upcoming_count + CHANNEL_POSTS_PAGE_SIZE - 1)
            // CHANNEL_POSTS_PAGE_SIZE,
        )
        page = min(max(page, 0), page_count - 1)
        upcoming = self.store.list_upcoming_channel_posts(
            from_date=from_date,
            destination_chat_id=self.destination_chat_id,
            limit=CHANNEL_POSTS_PAGE_SIZE,
            offset=page * CHANNEL_POSTS_PAGE_SIZE,
        )
        recent = self.store.list_channel_posts(limit=5)
        today_brief = (
            self.daily_brief_store.get(local_now.date())
            if self.daily_brief_enabled and self.daily_brief_store is not None
            else None
        )
        next_brief_date = local_now.date()
        if self.daily_brief_enabled and (
            today_brief is not None
            or local_now.time().replace(tzinfo=None) > DAILY_BRIEF_TIME
        ):
            next_brief_date += timedelta(days=1)
        lines = [
            "CHANNEL CONTENT SCHEDULER",
            (
                f"Saved posts in queue: {upcoming_count} "
                f"(page {page + 1} of {page_count}). Use each Preview button to read the complete post."
            ),
            "Weekday/Saturday schedule: 10:00 WAT; Sunday: 18:00 WAT.",
            "Admin preview: 18:00 WAT the evening before; one hour before if missing.",
            "Additional session-open posts: Tokyo, London, and New York on weekdays; "
            "see Session Open Posts for upcoming times and review links.",
            "Destination: the configured Market Analysis channel only.",
            "Pause/resume affects all scheduled channel posts, including weekdays.",
            "Gemini drafts scheduled Market Analysis posts using archived channel posts and saved admin feedback.",
            f"Publishing: {'PAUSED' if paused else 'ACTIVE'}",
            (
                "Bot promotion interval: about once every "
                f"{int(settings.get('promo_interval_days', 14)) // 7} "
                "weekend(s); it replaces that day's routine post."
            ),
            "Changing the interval affects future drafts; existing previews stay unchanged.",
            "Market recap posts use an evergreen review when verified market data is unavailable.",
            (
                "Weekend automatic publishing: "
                f"{'ACTIVE' if settings.get('weekend_auto_publish_enabled') else 'WAITING FOR TEMPLATE APPROVAL'}"
            ),
            "",
            "Saved queue:",
        ]
        if upcoming:
            for post in upcoming:
                try:
                    scheduled_date = datetime.fromisoformat(
                        str(post["schedule_date"])
                    ).date()
                    publish_time = self._publish_time(scheduled_date)
                    scheduled_time = publish_time.strftime("%H:%M")
                    passed_note = (
                        " · scheduled time passed"
                        if scheduled_date < local_now.date()
                        or (
                            scheduled_date == local_now.date()
                            and publish_time
                            <= local_now.time().replace(tzinfo=None)
                        )
                        else ""
                    )
                except (TypeError, ValueError):
                    scheduled_time = "time unavailable"
                    passed_note = ""
                promo_note = " · bot awareness" if post["is_promo"] else ""
                lines.append(
                    f"• {post['schedule_date']} at {scheduled_time} WAT — "
                    f"{self._category_label(post['category'])}{promo_note} — "
                    f"{self._status_label(post)}{passed_note}"
                )
        else:
            lines.append("• No saved upcoming posts.")
        if self.daily_brief_enabled:
            brief_status = (
                str(today_brief.get("status"))
                if today_brief
                else "not generated yet"
            )
            lines.extend(
                [
                    "",
                    "Daily USD & Gold brief:",
                    (
                        f"Today's run: {brief_status}. Next scheduled slot: "
                        f"{next_brief_date.isoformat()} at 00:00 WAT."
                    ),
                    "The brief is generated separately; it is not a saved draft until the source checks run.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "Daily USD & Gold brief:",
                    "Not enabled in the current runtime configuration; no next run is scheduled.",
                ]
            )
        lines.extend(["", "Recent archive:"])
        if recent:
            for post in recent:
                promo_note = " · bot awareness" if post["is_promo"] else ""
                lines.append(
                    f"• {post['schedule_date']} — {self._category_label(post['category'])}"
                    f"{promo_note} — {self._status_label(post)}"
                )
        else:
            lines.append("• No posts recorded yet.")

        keyboard_rows: list[list[dict[str, str]]] = []
        for post in upcoming:
            keyboard_rows.append(
                [
                    {
                        "text": f"👁 Preview Post — {post['schedule_date']}",
                        "callback_data": f"admin:channel_posts:preview:{post['id']}",
                    }
                ]
            )
        if upcoming_count > CHANNEL_POSTS_PAGE_SIZE:
            navigation: list[dict[str, str]] = []
            if page > 0:
                navigation.append(
                    {
                        "text": "⬅️ Previous",
                        "callback_data": f"admin:channel_posts:upcoming:{page - 1}",
                    }
                )
            if page + 1 < page_count:
                navigation.append(
                    {
                        "text": "Next ➡️",
                        "callback_data": f"admin:channel_posts:upcoming:{page + 1}",
                    }
                )
            if navigation:
                keyboard_rows.append(navigation)
        if recent and recent[0].get("status") in {"published", "rejected", "skipped"}:
            keyboard_rows.append(
                [
                    {
                        "text": f"👁 Preview Latest — {recent[0]['schedule_date']}",
                        "callback_data": f"admin:channel_posts:preview:{recent[0]['id']}",
                    }
                ]
            )
        if today_brief and today_brief.get("status") in {"held", "awaiting_approval"}:
            keyboard_rows.append(
                [
                    {
                        "text": "🧾 Review Held Daily Brief",
                        "callback_data": "dailybrief:review",
                    }
                ]
            )
        keyboard_rows.extend(
            [
                [
                    {
                        "text": (
                            "▶️ Resume Channel Posts"
                            if paused
                            else "⏸ Pause Channel Posts"
                        ),
                        "callback_data": (
                            "admin:channel_posts:resume"
                            if paused
                            else "admin:channel_posts:pause"
                        ),
                    }
                ],
                [
                    {
                        "text": "🕒 Session Open Posts",
                        "callback_data": "admin:session_open:view",
                    }
                ],
                [
                    {
                        "text": f"Every weekend ({'✓' if settings.get('promo_interval_days') == 7 else ''})",
                        "callback_data": "admin:channel_posts:promo_interval:7",
                    },
                    {
                        "text": f"Every 2 weekends ({'✓' if settings.get('promo_interval_days') == 14 else ''})",
                        "callback_data": "admin:channel_posts:promo_interval:14",
                    },
                ],
                [
                    {
                        "text": f"Every 4 weekends ({'✓' if settings.get('promo_interval_days') == 28 else ''})",
                        "callback_data": "admin:channel_posts:promo_interval:28",
                    }
                ],
                [{"text": "🔙 Back to Admin Dashboard", "callback_data": "admin:home"}],
            ]
        )
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            {"inline_keyboard": keyboard_rows},
        )

    def handle_callback(
        self, chat_id: int, admin_id: int, data: str, now: datetime | None = None
    ) -> bool:
        current_utc = self._as_utc(now or datetime.now(timezone.utc))
        if data == "admin:channel_posts":
            self.show_controls(chat_id, now=current_utc)
            return True
        page_match = re.fullmatch(r"admin:channel_posts:upcoming:(\d+)", data)
        if page_match:
            self.show_controls(
                chat_id,
                page=int(page_match.group(1)),
                now=current_utc,
            )
            return True
        if data == "admin:channel_posts:pause":
            self.store.set_channel_posting_paused(True, admin_id=admin_id)
            self.api.send_message(chat_id, "Scheduled channel publishing is paused.")
            self.show_controls(chat_id)
            return True
        if data == "admin:channel_posts:resume":
            self.store.set_channel_posting_paused(False, admin_id=admin_id)
            self.api.send_message(chat_id, "Scheduled channel publishing is resumed.")
            self.show_controls(chat_id)
            return True

        parts = data.split(":")
        if len(parts) < 4 or parts[:2] != ["admin", "channel_posts"]:
            return False
        action = parts[2]
        if action == "promo_interval" and len(parts) == 4:
            try:
                interval = int(parts[3])
                self.store.set_channel_promo_interval(interval, admin_id=admin_id)
            except (ValueError, TypeError):
                self.api.send_message(chat_id, "That promotion interval is not supported.")
            else:
                self.api.send_message(
                    chat_id,
                    f"Bot-promotion interval set to once every {interval // 7} weekend(s).",
                )
            self.show_controls(chat_id)
            return True
        if action == "preview" and len(parts) == 4:
            post = self._post_from_callback(parts[3])
            if post:
                self.show_post(chat_id, post)
            else:
                self.api.send_message(chat_id, "That channel post is no longer available.")
            return True
        if action == "photo" and len(parts) == 4:
            post = self._post_from_callback(parts[3])
            if not post:
                self.api.send_message(chat_id, "That channel post is no longer available.")
                return True
            if self.store.request_channel_post_photo(
                int(post["id"]),
                admin_id=admin_id,
                at=current_utc.isoformat(),
            ):
                self.api.send_message(
                    chat_id,
                    "Send one photo now. It will be attached to this scheduled "
                    "Market Analysis post and published at its scheduled time only "
                    "if all checks pass. If no photo arrives before the review "
                    "deadline, the text-only post remains eligible to publish.",
                )
            else:
                self.api.send_message(
                    chat_id,
                    "The five-minute review window is closed or this post is no "
                    "longer waiting for review. No photo was attached.",
                )
            return True
        if action in {
            "edit",
            "revise",
            "edit_cancel",
            "publish",
            "reject",
            "skip",
            "review_approve",
            "review_cancel",
            "confirm_posted",
            "retry_checked",
            "retry_generation",
            "retry_revision",
        } and len(parts) == 4:
            post = self._post_from_callback(parts[3])
            if not post:
                self.api.send_message(chat_id, "That channel post is no longer available.")
                return True
            post_id = int(post["id"])
            if action == "edit":
                if self.store.start_channel_post_edit(post_id, admin_id=admin_id):
                    promo_note = (
                        " Keep one approved feature statement, the verified bot "
                        "username/link, and the Start call to action."
                        if post["is_promo"]
                        else ""
                    )
                    self.api.send_message(
                        chat_id,
                        "The complete saved draft is shown next. Send your complete "
                        "replacement in one message. It will be checked before saving; "
                        "a rejected edit will not replace the saved draft. Keep "
                        "“NO CONFIRMATION, NO ENTRY.” in the post."
                        f"{promo_note} Send /cancel to stop editing.",
                    )
                else:
                    self.api.send_message(
                        chat_id, "Only an unpublished draft can be edited."
                    )
            elif action in {"review_approve", "review_cancel"}:
                decision = (
                    "approved" if action == "review_approve" else "cancelled"
                )
                changed = self.store.decide_channel_post_review(
                    post_id,
                    decision,
                    admin_id=admin_id,
                    at=current_utc.isoformat(),
                )
                if changed and decision == "approved":
                    self.api.send_message(
                        chat_id,
                        "Approved. The post will publish at its scheduled WAT time "
                        "if all pre-send checks pass.",
                    )
                elif changed:
                    self.api.send_message(chat_id, "Cancelled. This post will not publish.")
                else:
                    self.api.send_message(
                        chat_id,
                        "The review window is closed or this post is no longer waiting "
                        "for a decision.",
                    )
            elif action == "revise":
                if self.store.start_channel_post_revision(post_id, admin_id=admin_id):
                    self.api.send_message(
                        chat_id,
                        "Send one concise note about how Gemini should revise this "
                        "draft. It will use the saved channel history and keep the "
                        "channel safety rules. Send /cancel to stop.",
                    )
                else:
                    self.api.send_message(
                        chat_id, "Only an unpublished draft can be revised."
                    )
            elif action == "edit_cancel":
                self.store.cancel_channel_post_edit(admin_id)
                self.show_post(chat_id, self.store.get_channel_post(post_id) or post)
            elif action == "publish":
                self._publish(post, current_utc, automatic=False, admin_id=admin_id)
            elif action in {"reject", "skip"}:
                new_status = "rejected" if action == "reject" else "skipped"
                changed = self.store.set_channel_post_status(
                    post_id,
                    new_status,
                    action=action,
                    admin_id=admin_id,
                )
                self.api.send_message(
                    chat_id,
                    "Post rejected; it will not be published."
                    if action == "reject" and changed
                    else (
                        "Post skipped; its daily slot will remain empty."
                        if action == "skip" and changed
                        else "This post can no longer be changed."
                    ),
                )
            elif action == "confirm_posted":
                self._confirm_unknown_posted(chat_id, post, admin_id)
            elif action == "retry_checked":
                self._retry_after_admin_check(chat_id, post, admin_id, current_utc)
            elif action == "retry_generation":
                self._retry_generation(chat_id, post, admin_id, current_utc)
            elif action == "retry_revision":
                self._retry_revision(chat_id, post, admin_id, current_utc)
            refreshed = self.store.get_channel_post(post_id)
            if refreshed:
                self.show_post(chat_id, refreshed)
            return True
        return False

    def handle_admin_photo(
        self,
        chat_id: int,
        admin_id: int,
        photos: Any,
        *,
        is_private: bool,
        now: datetime | None = None,
    ) -> bool:
        if (
            not is_private
            or self.admin_id is None
            or admin_id != self.admin_id
            or chat_id != self.admin_id
        ):
            return False
        current_utc = self._as_utc(now or datetime.now(timezone.utc))
        post = self.store.pending_channel_post_photo_for_admin(
            admin_id,
            at=current_utc.isoformat(),
        )
        if post is None:
            return False
        if not isinstance(photos, list) or not photos:
            self.api.send_message(chat_id, "Telegram did not provide a usable photo.")
            return True
        photo = max(
            (
                item
                for item in photos
                if isinstance(item, dict)
                and isinstance(item.get("file_id"), str)
                and 0 < len(item["file_id"].strip()) <= 2048
            ),
            key=lambda item: (
                item.get("file_size")
                if isinstance(item.get("file_size"), int)
                and not isinstance(item.get("file_size"), bool)
                else 0
            ),
            default=None,
        )
        if photo is None:
            self.api.send_message(
                chat_id,
                "I could not read a valid Telegram photo. Send one image again "
                "before the review window closes, or the text-only post will remain.",
            )
            return True
        saved = self.store.attach_channel_post_photo(
            int(post["id"]),
            photo["file_id"],
            admin_id=admin_id,
            at=current_utc.isoformat(),
        )
        if saved:
            self.api.send_message(
                chat_id,
                "Photo attached to the scheduled post. It will publish with the "
                "post at the scheduled WAT time if all checks pass. You can still "
                "Cancel the post during the review window.",
            )
        else:
            self.api.send_message(
                chat_id,
                "The review window closed before the photo was saved. No photo was "
                "attached; the scheduled text follows the existing review rules.",
            )
        return True

    def handle_edit_message(
        self,
        chat_id: int,
        admin_id: int,
        text: str,
        is_private: bool,
        *,
        now: datetime | None = None,
    ) -> bool:
        if not is_private or self.admin_id is None or admin_id != self.admin_id:
            self.cancel_edit(admin_id)
            return False
        current = self._as_utc(now or datetime.now(timezone.utc))
        post = self.store.pending_channel_post_edit(admin_id)
        if not post:
            return False
        if post.get("edit_mode") == "feedback":
            feedback = text.strip()
            if feedback.casefold() == "/cancel":
                self.store.cancel_channel_post_edit(admin_id)
                self.api.send_message(chat_id, "Gemini revision cancelled.")
                return True
            if not feedback or len(feedback) > _MAX_FEEDBACK_CHARS:
                self.api.send_message(
                    chat_id,
                    f"Please send revision feedback of 1–{_MAX_FEEDBACK_CHARS} "
                    "characters, or /cancel.",
                )
                return True
            self.store.record_channel_post_action(
                int(post["id"]),
                "revision_feedback",
                admin_id=admin_id,
                details=feedback,
            )
            settings = self.store.get_channel_posting_settings()
            revised = self._generate_gemini_post(
                post,
                preferred_category=str(post["requested_category"]),
                sequence=int(settings["next_category_index"]),
                settings=settings,
                revision_feedback=feedback,
                admin_id=admin_id,
            )
            if revised.get("status") == "draft":
                self._send_preview(revised, current)
                self.api.send_message(chat_id, "Revised draft is ready for review.")
            return True
        username = post["bot_username"]
        is_promo = is_promotional_content(text)
        rejection = validate_channel_post(
            text,
            is_promo=is_promo,
            bot_username=username,
        )
        if not rejection:
            rejection = validate_weekend_post_format(text)
        if rejection:
            logger.info("Channel post edit rejected category=%s.", rejection)
            self.api.send_message(
                chat_id,
                describe_channel_post_rejection(
                    text,
                    rejection,
                    bot_username=username,
                ),
            )
            self.show_post(chat_id, post)
            return True
        if self._is_duplicate(text, exclude_post_id=int(post["id"])):
            self.api.send_message(
                chat_id,
                "That wording is too close to a recent post. Please send a fresh "
                "version or /cancel. Your saved draft is unchanged.",
            )
            self.show_post(chat_id, post)
            return True
        saved = self.store.save_channel_post_edit(
            int(post["id"]),
            text.strip(),
            admin_id=admin_id,
            is_promo=is_promo,
            at=current.isoformat(),
        )
        if not saved:
            self.api.send_message(chat_id, "This draft is no longer waiting for an edit.")
            return True
        refreshed = self.store.get_channel_post(int(post["id"]))
        if refreshed:
            self._send_preview(refreshed, current)
        return True

    def show_post(self, chat_id: int, post: dict[str, Any]) -> None:
        status = post["status"]
        failure_category = str(post.get("failure_category") or "")
        scheduled_weekend = (
            date.fromisoformat(str(post["schedule_date"])).weekday() in {5, 6}
        )
        template_pending = (
            failure_category == "template_approval_pending"
            or (
                scheduled_weekend
                and not self.store.get_channel_posting_settings().get(
                    "weekend_auto_publish_enabled"
                )
            )
        )
        display_status = (
            "Awaiting Template Approval"
            if template_pending
            else self._status_label(post)
        )
        category = self._category_label(post["category"])
        content = post["content"]
        if status == "delivery_unknown":
            intro = (
                "DELIVERY NEEDS CHECKING\nTelegram may have accepted this post, but "
                "the bot did not record a confirmation. Check the channel before "
                "choosing an action.\n\n"
            )
        else:
            intro = (
                f"CHANNEL POST — {post['schedule_date']} at "
                f"{post['schedule_time']} WAT\n"
                f"Category: {category}\n"
                f"Status: {display_status}\n"
                f"Destination: configured Market Analysis channel\n\n"
            )
            if post.get("failure_category") and status != "awaiting_edit":
                intro += (
                    describe_channel_post_rejection(
                        content,
                        str(post["failure_category"]),
                        bot_username=post.get("bot_username"),
                    )
                    + "\n\n"
                )
        rows: list[list[dict[str, str]]] = []
        if status == "draft":
            main_row = [
                {
                    "text": "✨ Revise with Gemini",
                    "callback_data": f"admin:channel_posts:revise:{post['id']}",
                },
                {
                    "text": "✏️ Edit Post",
                    "callback_data": f"admin:channel_posts:edit:{post['id']}",
                },
            ]
            if not template_pending:
                main_row.append(
                    {
                        "text": "🚀 Publish Now",
                        "callback_data": f"admin:channel_posts:publish:{post['id']}",
                    }
                )
            rows.extend(
                [
                    main_row,
                    [
                        {
                            "text": "❌ Reject Post",
                            "callback_data": f"admin:channel_posts:reject:{post['id']}",
                        },
                        {
                            "text": "⏭ Skip This Post",
                            "callback_data": f"admin:channel_posts:skip:{post['id']}",
                        },
                    ],
                ]
            )
        elif status == "awaiting_edit":
            rows.append(
                [
                    {
                        "text": "🔙 Back to Post",
                        "callback_data": f"admin:channel_posts:edit_cancel:{post['id']}",
                    }
                ]
            )
        elif status == "delivery_unknown":
            rows.extend(
                [
                    [
                        {
                            "text": "I checked — it was posted",
                            "callback_data": (
                                f"admin:channel_posts:confirm_posted:{post['id']}"
                            ),
                        }
                    ],
                    [
                        {
                            "text": "I checked — retry",
                            "callback_data": (
                                f"admin:channel_posts:retry_checked:{post['id']}"
                            ),
                        }
                    ],
                ]
            )
        elif status in {"failed", "retry_wait"}:
            failure_category = str(post.get("failure_category") or "")
            if failure_category.startswith("gemini_revision_") or (
                status == "failed" and self._can_retry_ai_draft(post)
            ):
                retry_action = (
                    "retry_revision"
                    if failure_category.startswith("gemini_revision_")
                    else "retry_generation"
                )
                rows.append(
                    [
                        {
                            "text": "Retry AI Revision"
                            if retry_action == "retry_revision"
                            else "Retry AI Draft",
                            "callback_data": (
                                f"admin:channel_posts:{retry_action}:{post['id']}"
                            ),
                        }
                    ]
                )
            if status == "failed" and post.get("content"):
                rows.append(
                    [
                        {
                            "text": "✏️ Edit Post",
                            "callback_data": f"admin:channel_posts:edit:{post['id']}",
                        }
                    ]
                )
            if (
                not template_pending
                and post.get("content")
                and (
                    post.get("generation_source") == "gemini"
                    or post.get("admin_edit_approved")
                )
                and not self._can_retry_ai_draft(post)
            ):
                rows.append(
                    [
                        {
                            "text": "🚀 Publish Now",
                            "callback_data": (
                                f"admin:channel_posts:publish:{post['id']}"
                            ),
                        }
                    ]
                )
            rows.append(
                [
                        {
                            "text": "❌ Reject Post",
                            "callback_data": (
                                f"admin:channel_posts:reject:{post['id']}"
                            ),
                        },
                        {
                            "text": "⏭ Skip This Post",
                            "callback_data": (
                                f"admin:channel_posts:skip:{post['id']}"
                            ),
                        },
                ]
            )
        rows.append(
            [{"text": "🔙 Back to Channel Posts", "callback_data": "admin:channel_posts"}]
        )
        self.api.send_message(
            chat_id,
            intro + content if content else intro.rstrip(),
            {"inline_keyboard": rows},
        )

    @staticmethod
    def _status_label(post: dict[str, Any]) -> str:
        status = str(post.get("status") or "")
        failure = str(post.get("failure_category") or "")
        review_status = str(post.get("review_status") or "")
        if status == "failed" and post.get("generation_retry_started_at"):
            return "Retrying Draft Generation"
        if status == "failed" and post.get("generation_retry_at"):
            return "Draft Retry Scheduled"
        if status == "draft" and review_status == "pending":
            return "Awaiting Final Review"
        if status == "draft" and review_status == "approved":
            return "Approved — Scheduled"
        if status == "draft" and review_status == "edited":
            return "Edited — Scheduled"
        if review_status == "delivery_failed":
            return "Review Delivery Failed"
        if review_status == "missed":
            return "Review Missed — Held"
        if failure in {
            "destination_not_verified",
            "destination_mismatch",
            "destination_verification_unavailable",
        }:
            return "Destination Not Verified"
        if failure == "template_approval_pending":
            return "Awaiting Template Approval"
        return {
            "draft": "Draft",
            "awaiting_edit": "Awaiting Approval (Edit Pending)",
            "published": "Published",
            "failed": "Failed",
            "retry_wait": "Retry Scheduled",
            "delivery_unknown": "Delivery Unknown",
            "rejected": "Rejected",
            "skipped": "Skipped",
            "publishing": "Publishing",
        }.get(status, status.replace("_", " ").title())

    @staticmethod
    def _can_retry_ai_draft(post: dict[str, Any]) -> bool:
        failure = str(post.get("failure_category") or "")
        source = str(post.get("generation_source") or "")
        content = bool(post.get("content"))
        if failure.startswith("gemini_revision_"):
            return False
        if failure.startswith("gemini_"):
            return source != "gemini" or not content
        return source == "gemini" and failure in _AI_RETRYABLE_CONTENT_FAILURES

    def _ensure_and_preview(self, target_date: date, now_utc: datetime) -> None:
        post = self.store.get_scheduled_channel_post(target_date.isoformat())
        if not post:
            local_now = now_utc.astimezone(self.timezone)
            if (
                target_date == local_now.date()
                and local_now.time().replace(tzinfo=None)
                >= self._publish_time(target_date)
            ):
                return
            post = self._create_post(target_date, now_utc=now_utc)
        if post:
            post = self._process_generation_retry(post, now_utc)
        if (
            post
            and post.get("generation_source") == "local"
            and not post.get("admin_edit_approved")
            and post["status"]
            not in {"published", "rejected", "skipped", "awaiting_edit"}
        ):
            post = self._hold_legacy_channel_draft(post)
        if (
            post
            and post["status"] not in {"rejected", "skipped", "published"}
            and not (
                post["status"] == "failed"
                and str(post.get("failure_category") or "").startswith("gemini_")
                and not post.get("content")
            )
        ):
            self._send_preview(post, now_utc)

    def _generation_retry_fits_review_window(
        self, post: dict[str, Any], retry_at: datetime
    ) -> bool:
        try:
            scheduled_at = datetime.combine(
                date.fromisoformat(str(post["schedule_date"])),
                wall_time.fromisoformat(str(post["schedule_time"])),
                tzinfo=self.timezone,
            )
        except (KeyError, TypeError, ValueError):
            return False
        final_review_at = (
            self._as_utc(scheduled_at) - FINAL_REVIEW_LEAD
        )
        return (
            self._as_utc(retry_at) + _GENERATION_RETRY_ATTEMPT_BUDGET
            <= final_review_at
        )

    def _process_generation_retry(
        self, post: dict[str, Any], now_utc: datetime
    ) -> dict[str, Any]:
        if (
            post.get("status") != "failed"
            or post.get("failure_category") != "gemini_timeout"
            or post.get("generation_source") != "gemini_pending"
            or post.get("content")
        ):
            return post

        now = self._as_utc(now_utc)
        retry_count = int(post.get("generation_retry_count") or 0)
        started_value = post.get("generation_retry_started_at")
        if started_value:
            started_at = self._parse_datetime(str(started_value))
            if (
                started_at is not None
                and now - self._as_utc(started_at) < _GENERATION_RETRY_LEASE
            ):
                return post

            recovered_retry_at: datetime | None = None
            if retry_count < MAX_AUTOMATIC_GENERATION_TIMEOUT_RETRIES:
                recovered_retry_at = (
                    now
                    + _GENERATION_TIMEOUT_RETRY_DELAYS[retry_count]
                )
                if not self._generation_retry_fits_review_window(
                    post, recovered_retry_at
                ):
                    recovered_retry_at = None
            outcome = self.store.recover_stale_channel_post_generation_retry(
                int(post["id"]),
                stale_before=(now - _GENERATION_RETRY_LEASE).isoformat(),
                retry_at=(
                    recovered_retry_at.isoformat()
                    if recovered_retry_at is not None
                    else None
                ),
                at=now.isoformat(),
            )
            refreshed = self.store.get_channel_post(int(post["id"])) or post
            if outcome == "exhausted":
                self._notify_failure(
                    refreshed,
                    "gemini_timeout",
                    additional_note=(
                        "An interrupted retry could not be safely resumed before "
                        "the final review window. The post remains held."
                    ),
                )
            return refreshed

        retry_at = self._parse_datetime(
            str(post.get("generation_retry_at") or "")
        )
        if retry_at is None or self._as_utc(retry_at) > now:
            return post

        if retry_count >= MAX_AUTOMATIC_GENERATION_TIMEOUT_RETRIES:
            self.store.set_channel_post_status(
                int(post["id"]),
                "failed",
                action="generation_retry_exhausted",
                details="automatic_retry_limit",
                failure_category="gemini_timeout",
                at=now.isoformat(),
            )
            exhausted = self.store.get_channel_post(int(post["id"])) or post
            self._notify_failure(
                exhausted,
                "gemini_timeout",
                additional_note=(
                    "Automatic draft retries are exhausted; the post remains held."
                ),
            )
            return exhausted

        if not self._generation_retry_fits_review_window(
            post, now + _GENERATION_RETRY_ATTEMPT_BUDGET
        ):
            self.store.set_channel_post_status(
                int(post["id"]),
                "failed",
                action="generation_retry_window_missed",
                details="final_review_window",
                failure_category="gemini_timeout",
                at=now.isoformat(),
            )
            held = self.store.get_channel_post(int(post["id"])) or post
            self._notify_failure(
                held,
                "gemini_timeout",
                additional_note=(
                    "There was not enough time to retry before the final review "
                    "window, so the post remains held."
                ),
            )
            return held

        claimed = self.store.claim_channel_post_generation_retry(
            int(post["id"]),
            at=now.isoformat(),
            lease_until=(now + _GENERATION_RETRY_LEASE).isoformat(),
            max_retries=MAX_AUTOMATIC_GENERATION_TIMEOUT_RETRIES,
        )
        if claimed is None:
            return self.store.get_channel_post(int(post["id"])) or post

        settings = self.store.get_channel_posting_settings()
        generated = self._generate_gemini_post(
            claimed,
            preferred_category=str(claimed["requested_category"]),
            sequence=int(settings["next_category_index"]),
            settings=settings,
            now_utc=now,
            allow_automatic_retries=True,
        )
        if generated.get("status") == "draft":
            self._send_preview(generated, now)
        return generated

    def _create_post(
        self, target_date: date, *, now_utc: datetime
    ) -> dict[str, Any] | None:
        settings = self.store.get_channel_posting_settings()
        sequence = int(settings["next_category_index"])
        requested_category = next_category(CHANNEL_CONTENT_CATEGORIES, sequence)
        schedule_time = self._publish_time(target_date).strftime("%H:%M")
        promo_interval = int(settings.get("promo_interval_days", 14))
        is_promo = self._promo_due(
            target_date,
            settings.get("last_promo_date"),
            promo_interval,
        )
        username: str | None = None
        if is_promo:
            try:
                username = self._verified_bot_username(self.api.get_me())
            except (TelegramAPIError, ValueError, TypeError):
                return self._create_generation_failure(
                    target_date,
                    requested_category,
                    schedule_time,
                    is_promo=True,
                    username=None,
                    sequence=sequence,
                    failure_category="gemini_bot_username_unverified",
                    settings=settings,
                )
        return self._create_gemini_post(
            target_date,
            requested_category,
            schedule_time,
            is_promo,
            username,
            sequence,
            settings,
            now_utc=now_utc,
        )

    def _create_gemini_post(
        self,
        target_date: date,
        preferred_category: str,
        schedule_time: str,
        is_promo: bool,
        username: str | None,
        sequence: int,
        settings: dict[str, Any],
        *,
        now_utc: datetime,
    ) -> dict[str, Any]:
        post, created = self.store.create_scheduled_channel_post(
            schedule_date=target_date.isoformat(),
            schedule_time=schedule_time,
            requested_category=preferred_category,
            category=preferred_category,
            content="",
            destination_chat_id=int(self.destination_chat_id or 0),
            is_promo=is_promo,
            bot_username=username,
            next_category_index=sequence,
            next_promo_feature_index=int(settings["next_promo_feature_index"]),
            last_promo_date=settings.get("last_promo_date"),
            status="failed",
            failure_category="gemini_generation_pending",
            generation_source="gemini_pending",
        )
        if not created:
            return post
        return self._generate_gemini_post(
            post,
            preferred_category=preferred_category,
            sequence=sequence,
            settings=settings,
            now_utc=now_utc,
            allow_automatic_retries=True,
        )

    def _generate_gemini_post(
        self,
        post: dict[str, Any],
        *,
        preferred_category: str,
        sequence: int,
        settings: dict[str, Any],
        now_utc: datetime | None = None,
        allow_automatic_retries: bool = False,
        revision_feedback: str | None = None,
        admin_id: int | None = None,
    ) -> dict[str, Any]:
        if self.channel_writer is None:
            return self._record_generation_failure(
                post,
                "gemini_not_configured",
                admin_id=admin_id,
                revision=revision_feedback is not None,
                now_utc=now_utc,
                allow_automatic_retries=allow_automatic_retries,
            )
        try:
            verified_information: list[str] = []
            draft = self.channel_writer.generate(
                schedule_date=str(post["schedule_date"]),
                schedule_time=str(post["schedule_time"]),
                preferred_category=preferred_category,
                history=self.store.get_recent_channel_post_contents(
                    limit=12,
                    chat_id=self.destination_chat_id,
                ),
                admin_feedback=self.store.get_recent_channel_post_feedback(limit=5),
                verified_information=verified_information,
                promo_username=post.get("bot_username"),
                promo_due=bool(post.get("is_promo")),
                revision_feedback=revision_feedback,
                existing_draft=str(post.get("content") or "") or None,
            )
        except GeminiChannelGenerationError as error:
            return self._record_generation_failure(
                post,
                error.category,
                admin_id=admin_id,
                revision=revision_feedback is not None,
                now_utc=now_utc,
                allow_automatic_retries=allow_automatic_retries,
            )
        except Exception:
            logger.warning(
                "Market Analysis Gemini draft failed category=unexpected_provider_error."
            )
            return self._record_generation_failure(
                post,
                "gemini_unexpected_error",
                admin_id=admin_id,
                revision=revision_feedback is not None,
                now_utc=now_utc,
                allow_automatic_retries=allow_automatic_retries,
            )

        content = normalize_weekend_brand_header(draft.content, draft.category)
        rejection = validate_channel_post(
            content,
            is_promo=bool(post["is_promo"]),
            bot_username=post.get("bot_username"),
            verified_information=verified_information,
        )
        if not rejection:
            rejection = validate_weekend_post_format(content)
        if rejection or self._is_duplicate(content, exclude_post_id=int(post["id"])):
            category = rejection or "duplicate_content"
            return self._record_generation_failure(
                post,
                f"gemini_content_rejected_{category}",
                admin_id=admin_id,
                revision=revision_feedback is not None,
                rejected_content=content,
                now_utc=now_utc,
            )

        next_feature_index = int(settings["next_promo_feature_index"])
        last_promo_date = settings.get("last_promo_date")
        advance_rotation = revision_feedback is None
        saved_category = (
            "weekly_market_recap_evergreen"
            if draft.category == "weekly_market_recap" and not verified_information
            else draft.category
        )
        if post["is_promo"] and advance_rotation:
            next_feature_index += 1
            last_promo_date = str(post["schedule_date"])
        action = "gemini_revised" if revision_feedback else "gemini_generated"
        if not self.store.complete_channel_post_generation(
            int(post["id"]),
            category=saved_category,
            content=content,
            bot_username=post.get("bot_username"),
            next_category_index=sequence + 1 if advance_rotation else sequence,
            next_promo_feature_index=next_feature_index,
            last_promo_date=last_promo_date,
            action=action,
            admin_id=admin_id,
            at=self._as_utc(now_utc).isoformat() if now_utc else None,
        ):
            return self._record_generation_failure(
                post,
                "gemini_post_state_changed",
                admin_id=admin_id,
                revision=revision_feedback is not None,
                now_utc=now_utc,
            )
        saved = self.store.get_channel_post(int(post["id"])) or post
        logger.info(
            "Market Analysis Gemini draft generated category=%s promo=%s.",
            saved_category,
            bool(post["is_promo"]),
        )
        return saved

    def _retry_generation(
        self,
        chat_id: int,
        post: dict[str, Any],
        admin_id: int,
        now_utc: datetime,
    ) -> None:
        if post.get("status") != "failed" or not self._can_retry_ai_draft(post):
            self.api.send_message(chat_id, "This post is not waiting for AI draft generation.")
            return
        if post.get("is_promo"):
            try:
                username = self._verified_bot_username(self.api.get_me())
            except (TelegramAPIError, ValueError, TypeError):
                self.api.send_message(
                    chat_id,
                    "The bot username could not be verified, so the promotional "
                    "draft remains on hold.",
                )
                return
            if not self.store.update_channel_post_bot_username(
                int(post["id"]), username
            ):
                self.api.send_message(
                    chat_id, "The promotional draft changed and cannot be retried."
                )
                return
            post = {**post, "bot_username": username}
        settings = self.store.get_channel_posting_settings()
        generated = self._generate_gemini_post(
            post,
            preferred_category=str(post["requested_category"]),
            sequence=int(settings["next_category_index"]),
            settings=settings,
            admin_id=admin_id,
            now_utc=now_utc,
            allow_automatic_retries=True,
        )
        if generated.get("status") == "draft":
            self._send_preview(generated, now_utc)
            self.api.send_message(
                chat_id,
                "The AI draft passed the content checks and is ready for review. "
                "Nothing was sent to the channel.",
            )

    def _retry_revision(
        self,
        chat_id: int,
        post: dict[str, Any],
        admin_id: int,
        now_utc: datetime,
    ) -> None:
        if post.get("status") != "failed" or not post.get("content"):
            self.api.send_message(chat_id, "This post is not waiting for an AI revision.")
            return
        feedback = self.store.get_latest_channel_post_feedback(int(post["id"]))
        if not feedback:
            self.api.send_message(
                chat_id,
                "No saved revision feedback is available. Open the draft and "
                "choose Revise with Gemini.",
            )
            return
        settings = self.store.get_channel_posting_settings()
        revised = self._generate_gemini_post(
            post,
            preferred_category=str(post["requested_category"]),
            sequence=int(settings["next_category_index"]),
            settings=settings,
            revision_feedback=feedback,
            admin_id=admin_id,
            now_utc=now_utc,
        )
        if revised.get("status") == "draft":
            self._send_preview(revised, now_utc)

    def _create_generation_failure(
        self,
        target_date: date,
        requested_category: str,
        schedule_time: str,
        *,
        is_promo: bool,
        username: str | None,
        sequence: int,
        failure_category: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        post, _ = self.store.create_scheduled_channel_post(
            schedule_date=target_date.isoformat(),
            schedule_time=schedule_time,
            requested_category=requested_category,
            category=requested_category,
            content="",
            destination_chat_id=int(self.destination_chat_id or 0),
            is_promo=is_promo,
            bot_username=username,
            next_category_index=sequence,
            next_promo_feature_index=int(settings["next_promo_feature_index"]),
            last_promo_date=settings.get("last_promo_date"),
            status="failed",
            failure_category=failure_category,
            generation_source="gemini_pending",
        )
        return self._record_generation_failure(post, failure_category)

    def _record_generation_failure(
        self,
        post: dict[str, Any],
        failure_category: str,
        *,
        admin_id: int | None = None,
        revision: bool = False,
        rejected_content: str | None = None,
        now_utc: datetime | None = None,
        allow_automatic_retries: bool = False,
    ) -> dict[str, Any]:
        category = (
            f"gemini_revision_{failure_category.removeprefix('gemini_')}"
            if revision
            else (
                failure_category
                if failure_category.startswith("gemini_")
                else f"gemini_{failure_category}"
            )
        )
        failed_at = self._as_utc(now_utc or datetime.now(timezone.utc))
        retry_at: datetime | None = None
        retry_count = int(post.get("generation_retry_count") or 0)
        timeout_retry = (
            allow_automatic_retries
            and not revision
            and category == "gemini_timeout"
            and post.get("generation_source") == "gemini_pending"
            and not post.get("content")
        )
        if timeout_retry and retry_count < MAX_AUTOMATIC_GENERATION_TIMEOUT_RETRIES:
            retry_candidate = (
                failed_at + _GENERATION_TIMEOUT_RETRY_DELAYS[retry_count]
            )
            if self._generation_retry_fits_review_window(post, retry_candidate):
                retry_at = retry_candidate
        self.store.set_channel_post_status(
            int(post["id"]),
            "failed",
            action="gemini_revision_failed" if revision else "gemini_generation_failed",
            admin_id=admin_id,
            details=category,
            failure_category=category,
            rejected_content=rejected_content,
            generation_retry_at=retry_at.isoformat() if retry_at else None,
            at=failed_at.isoformat(),
        )
        logger.warning(
            "Market Analysis draft held failure_category=%s.",
            category,
        )
        saved = self.store.get_channel_post(int(post["id"])) or post
        if retry_at is not None:
            if retry_count == 0:
                self._notify_generation_retry_scheduled(
                    saved,
                    retry_at,
                    remaining=MAX_AUTOMATIC_GENERATION_TIMEOUT_RETRIES - retry_count,
                )
        else:
            additional_note = None
            if timeout_retry:
                if retry_count >= MAX_AUTOMATIC_GENERATION_TIMEOUT_RETRIES:
                    additional_note = (
                        "Automatic draft retries are exhausted; the post remains held."
                    )
                else:
                    additional_note = (
                        "There was not enough time to retry before the final review "
                        "window, so the post remains held."
                    )
            self._notify_failure(
                saved,
                category,
                additional_note=additional_note,
            )
        return saved

    def _hold_legacy_channel_draft(
        self, post: dict[str, Any]
    ) -> dict[str, Any]:
        if post.get("failure_category") != "gemini_legacy_draft_held":
            self.store.set_channel_post_status(
                int(post["id"]),
                "failed",
                action="legacy_weekend_draft_held",
                details="gemini_legacy_draft_held",
                failure_category="gemini_legacy_draft_held",
            )
            held = self.store.get_channel_post(int(post["id"])) or post
            self._notify_failure(held, "gemini_legacy_draft_held")
            return held
        return post

    def _send_preview(self, post: dict[str, Any], now_utc: datetime) -> None:
        if self.admin_id is None or post.get("preview_sent_at"):
            return
        last_attempt = self._parse_datetime(post.get("preview_last_attempt_at"))
        if last_attempt and now_utc - self._as_utc(last_attempt) < PREVIEW_RETRY_DELAY:
            return
        self.store.mark_channel_post_preview_attempted(
            int(post["id"]), at=now_utc.isoformat()
        )
        refreshed = self.store.get_channel_post(int(post["id"])) or post
        try:
            self.show_post(self.admin_id, refreshed)
            self.store.mark_channel_post_preview_sent(
                int(post["id"]), at=now_utc.isoformat()
            )
        except TelegramAPIError:
            logger.warning("Channel post admin preview delivery failed post_id=%s.", post["id"])

    def _send_scheduled_review(
        self,
        post: dict[str, Any],
        now_utc: datetime,
        scheduled_at: datetime,
    ) -> None:
        if self.admin_id is None:
            return
        post_id = int(post["id"])
        if not self.store.reserve_channel_post_review(
            post_id, at=now_utc.isoformat()
        ):
            return
        local_schedule = scheduled_at.astimezone(self.timezone)
        text = (
            "FINAL SCHEDULED POST REVIEW\n"
            f"Destination: Market Analysis channel "
            f"(ID {int(post['destination_chat_id'])})\n"
            f"Scheduled: {local_schedule.strftime('%A, %d %B %Y at %H:%M WAT')}\n"
            "Decision window: 5 minutes, ending at the scheduled time.\n\n"
            f"{post['content']}\n\n"
            "Would you like to add a picture? Tap “Add photo” and send one image "
            "privately to this bot. If you do not send a photo, the post will be "
            "text-only. No review response is required for automatic publication "
            "at the scheduled time if all checks pass.\n\n"
            "Choose Approve to allow automatic publication at the scheduled time, "
            "Edit to submit a checked replacement, or Cancel to skip this post. "
            "If you do not respond by the scheduled time, the reviewed draft will "
            "publish automatically, including any photo you attached, if all checks pass."
        )
        markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ Approve",
                        "callback_data": (
                            f"admin:channel_posts:review_approve:{post_id}"
                        ),
                    },
                    {
                        "text": "✏️ Edit",
                        "callback_data": f"admin:channel_posts:edit:{post_id}",
                    },
                    {
                        "text": "❌ Cancel",
                        "callback_data": (
                            f"admin:channel_posts:review_cancel:{post_id}"
                        ),
                    },
                ],
                [
                    {
                        "text": "📷 Add photo",
                        "callback_data": f"admin:channel_posts:photo:{post_id}",
                    }
                ],
            ]
        }
        try:
            self.api.send_message(self.admin_id, text, markup)
        except TelegramAPIError:
            self.store.fail_channel_post_review(
                post_id,
                failure_category="scheduled_review_delivery_failed",
                at=now_utc.isoformat(),
            )
            refreshed = self.store.get_channel_post(post_id) or post
            self._notify_failure(refreshed, "scheduled_review_delivery_failed")
            logger.warning("Scheduled post review delivery failed post_id=%s.", post_id)
            return
        deadline = scheduled_at.astimezone(timezone.utc)
        if not self.store.complete_channel_post_review(
            post_id,
            sent_at=now_utc.isoformat(),
            deadline_at=deadline.isoformat(),
        ):
            logger.warning(
                "Scheduled post review send could not be recorded post_id=%s.", post_id
            )

    def _publish(
        self,
        post: dict[str, Any],
        now_utc: datetime,
        *,
        automatic: bool,
        admin_id: int | None = None,
    ) -> None:
        if self.admin_id is None or self.destination_chat_id is None:
            return
        review_status = str(post.get("review_status") or "not_requested")
        explicit_publish_after_missed_review = (
            not automatic
            and admin_id is not None
            and post.get("status") == "draft"
            and review_status == "missed"
            and post.get("failure_category") == "scheduled_review_missed"
            and int(post.get("publish_attempts") or 0) == 0
        )
        if (
            not explicit_publish_after_missed_review
            and (
                review_status not in {"approved", "edited", "timed_out"}
                or not post.get("review_sent_at")
            )
        ):
            if not automatic:
                self.api.send_message(
                    self.admin_id,
                    "This post is not approved for publication. The scheduler sends "
                    "the final review 5 minutes before the scheduled time; missed "
                    "reviews stay held unless an administrator explicitly chooses "
                    "Publish Now on the scheduled WAT date.",
                )
            return
        scheduled_date = date.fromisoformat(str(post["schedule_date"]))
        scheduled_time = wall_time.fromisoformat(str(post["schedule_time"]))
        scheduled_at = datetime.combine(
            scheduled_date, scheduled_time, tzinfo=self.timezone
        )
        if (
            post.get("generation_source") == "local"
            and not post.get("admin_edit_approved")
        ):
            self._hold_legacy_channel_draft(post)
            if not automatic:
                self.api.send_message(
                    self.admin_id,
                    "This draft has not passed Gemini review or administrator "
                    "editing. It remains on hold; use Retry Gemini draft or Edit Post "
                    "before publishing.",
                )
            return
        settings = self.store.get_channel_posting_settings()
        if settings["paused"]:
            if not automatic:
                self.api.send_message(
                    self.admin_id,
                    "Publishing is paused. Resume channel publishing first.",
                )
            return
        if (
            scheduled_date.weekday() in {5, 6}
            and not settings.get("weekend_auto_publish_enabled")
        ):
            if not automatic:
                self.api.send_message(
                    self.admin_id,
                    "Weekend publishing is waiting for template approval. "
                    "No channel post was sent.",
                )
            return
        local_now = now_utc.astimezone(self.timezone)
        if post["schedule_date"] != local_now.date().isoformat():
            if not automatic:
                self.api.send_message(
                    self.admin_id,
                    "To keep the one-post-per-day limit, Publish now is available "
                    "only on this post's scheduled WAT date.",
                )
            return
        if not automatic and local_now < scheduled_at:
            self.api.send_message(
                self.admin_id,
                "This post is approved for its scheduled time. It will not publish early.",
            )
            return
        if int(post["destination_chat_id"]) != int(self.destination_chat_id):
            self._fail_before_send(post, "destination_mismatch", admin_id)
            return
        if post["status"] == "delivery_unknown":
            self.api.send_message(
                self.admin_id,
                "Delivery is uncertain. Check the channel and use one of the "
                "confirmation buttons before retrying.",
            )
            return
        if automatic and post["status"] == "failed":
            return

        rejection = validate_channel_post(
            post["content"],
            is_promo=bool(post["is_promo"]),
            bot_username=post.get("bot_username"),
        )
        if not rejection:
            rejection = validate_weekend_post_format(str(post["content"]))
        if rejection:
            self._fail_before_send(post, rejection, admin_id)
            return
        try:
            channel_text = render_weekend_post_html(str(post["content"]))
        except ValueError as error:
            self._fail_before_send(post, str(error), admin_id)
            return
        photo_file_id = str(post.get("photo_file_id") or "").strip()
        if photo_file_id and len(str(post["content"]).encode("utf-16-le")) // 2 > 1024:
            self._fail_before_send(post, "photo_caption_too_long", admin_id)
            return
        try:
            username = self.verify_destination(post)
        except DestinationVerificationError as error:
            self._fail_before_send(
                post,
                error.category,
                admin_id,
                verification_detail=error.safe_detail,
            )
            return
        except (TelegramAPIError, TypeError, ValueError, AttributeError):
            self._fail_before_send(
                post,
                "destination_verification_unavailable",
                admin_id,
                verification_detail=(
                    "Telegram could not confirm the configured channel or bot "
                    f"permissions for destination ID {self.destination_chat_id}. "
                    "Check the bot's channel access and try verification again."
                ),
            )
            return

        attempts = self.store.reserve_channel_post_publish(int(post["id"]))
        if attempts is None:
            self.api.send_message(
                self.admin_id,
                "This post is no longer available to publish. Open Channel Posts to "
                "check its current status.",
            )
            return
        markup = (
            {
                "inline_keyboard": [
                    [
                        {
                            "text": f"Open @{username}",
                            "url": f"https://t.me/{username}",
                        }
                    ]
                ]
            }
            if post["is_promo"]
            else None
        )
        try:
            if photo_file_id:
                result = self.api.send_photo_with_result(
                    int(self.destination_chat_id),
                    photo_file_id,
                    caption=channel_text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            else:
                result = self.api.send_message_with_result(
                    int(self.destination_chat_id),
                    channel_text,
                    markup,
                    parse_mode="HTML",
                )
            message_id = result.get("message_id")
            if not isinstance(message_id, int):
                self.store.fail_channel_post_publish(
                    int(post["id"]),
                    status="delivery_unknown",
                    failure_category="telegram_confirmation_missing",
                )
                self._notify_delivery_unknown(post)
                return
            self.store.complete_channel_post_publish(
                int(post["id"]),
                telegram_message_id=message_id,
                at=now_utc.isoformat(),
                admin_id=admin_id,
            )
            logger.info(
                "Channel post published post_id=%s category=%s promo=%s.",
                post["id"],
                post["category"],
                bool(post["is_promo"]),
            )
            self._notify_admin(
                f"Channel post for {post['schedule_date']} was published successfully."
            )
        except TelegramAPIError as error:
            if error.error_code == 429 or error.http_status == 429:
                if attempts <= MAX_AUTOMATIC_RATE_LIMIT_RETRIES:
                    retry_seconds = min(max(1, error.retry_after or 5), 3600)
                    retry_at = now_utc + timedelta(seconds=retry_seconds)
                    self.store.fail_channel_post_publish(
                        int(post["id"]),
                        status="retry_wait",
                        failure_category="telegram_rate_limit",
                        retry_after_at=retry_at.isoformat(),
                    )
                    self._notify_failure(post, "telegram_rate_limit_retry_scheduled")
                    return
                self.store.fail_channel_post_publish(
                    int(post["id"]),
                    status="failed",
                    failure_category="telegram_rate_limit",
                )
                self._notify_failure(post, "telegram_rate_limit")
                return
            if error.delivery_unknown or (
                error.http_status is not None and error.http_status >= 500
            ):
                self.store.fail_channel_post_publish(
                    int(post["id"]),
                    status="delivery_unknown",
                    failure_category="telegram_delivery_unknown",
                )
                self._notify_delivery_unknown(post)
                return
            category = (
                "telegram_permission_error"
                if error.error_code == 403 or error.http_status == 403
                else "telegram_send_rejected"
            )
            self.store.fail_channel_post_publish(
                int(post["id"]),
                status="failed",
                failure_category=category,
            )
            self._notify_failure(post, category)

    def _preflight_keyboard(self, post: dict[str, Any]) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "Confirm posted",
                        "callback_data": f"admin:channel_posts:confirm_posted:{post['id']}",
                    }
                ],
                [
                    {
                        "text": "Checked — retry",
                        "callback_data": f"admin:channel_posts:retry_checked:{post['id']}",
                    }
                ],
            ]
        }

    def _notify_delivery_unknown(self, post: dict[str, Any]) -> None:
        if self.admin_id is None:
            return
        self._notify_admin(
            f"Delivery of the {post['schedule_date']} channel post is uncertain. "
            "Check the Market Analysis channel before retrying.",
            self._preflight_keyboard(post),
        )

    def _notify_failure(
        self,
        post: dict[str, Any],
        category: str,
        *,
        verification_detail: str | None = None,
        additional_note: str | None = None,
    ) -> None:
        if self.admin_id is None:
            return
        reason = describe_channel_post_rejection(
            str(post.get("content") or ""),
            category,
            bot_username=post.get("bot_username"),
        )
        message = f"{post['schedule_date']}: {reason}"
        if verification_detail:
            message += f"\n\nTelegram destination response: {verification_detail}"
        if additional_note:
            message += f"\n\n{additional_note}"
        self._notify_admin(
            message,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "👁 Review Post",
                            "callback_data": f"admin:channel_posts:preview:{post['id']}",
                        }
                    ]
                ]
            },
        )

    def _notify_generation_retry_scheduled(
        self,
        post: dict[str, Any],
        retry_at: datetime,
        *,
        remaining: int,
    ) -> None:
        if self.admin_id is None:
            return
        retry_local = self._as_utc(retry_at).astimezone(self.timezone)
        retry_time = retry_local.strftime("%H:%M WAT")
        message = (
            f"{post['schedule_date']}: Gemini timed out while preparing the "
            "scheduled Market Analysis post. I will retry automatically at "
            f"{retry_time}"
        )
        if remaining > 1:
            message += " and make one more retry if needed"
        message += (
            ". The post stays held until it passes validation and review; "
            "nothing has been sent to the channel."
        )
        self._notify_admin(
            message,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "👁 Review Post",
                            "callback_data": f"admin:channel_posts:preview:{post['id']}",
                        }
                    ]
                ]
            },
        )

    def _notify_admin(
        self, text: str, reply_markup: dict[str, Any] | None = None
    ) -> None:
        if self.admin_id is None:
            return
        try:
            self.api.send_message(self.admin_id, text, reply_markup)
        except TelegramAPIError:
            logger.warning("Administrator notification delivery failed.")

    def _fail_before_send(
        self,
        post: dict[str, Any],
        category: str,
        admin_id: int | None,
        *,
        verification_detail: str | None = None,
    ) -> None:
        self.store.set_channel_post_status(
            int(post["id"]),
            "failed",
            action="preflight_failed",
            admin_id=admin_id,
            details=category,
            failure_category=category,
        )
        logger.warning(
            "Channel post withheld post_id=%s category=%s.", post["id"], category
        )
        self._notify_failure(
            post,
            category,
            verification_detail=verification_detail,
        )

    def _confirm_unknown_posted(
        self, chat_id: int, post: dict[str, Any], admin_id: int
    ) -> None:
        changed = self.store.confirm_unknown_channel_post(
            int(post["id"]), admin_id=admin_id
        )
        self.api.send_message(
            chat_id,
            "The post is marked as published."
            if changed
            else "That delivery is no longer awaiting confirmation.",
        )

    def _retry_after_admin_check(
        self,
        chat_id: int,
        post: dict[str, Any],
        admin_id: int,
        now_utc: datetime,
    ) -> None:
        changed = self.store.resolve_unknown_channel_post_for_retry(
            int(post["id"]), admin_id=admin_id
        )
        if not changed:
            self.api.send_message(
                chat_id, "That delivery is no longer awaiting confirmation."
            )
            return
        refreshed = self.store.get_channel_post(int(post["id"]))
        if refreshed:
            self._publish(
                refreshed,
                now_utc,
                automatic=False,
                admin_id=admin_id,
            )

    def _notify_recovered_inflight(self) -> None:
        try:
            posts = self.store.recover_inflight_channel_posts()
        except Exception:
            logger.exception("Channel post recovery state could not be read.")
            return
        for post in posts:
            logger.warning(
                "Channel post send was interrupted; duplicate-safe review required post_id=%s.",
                post["id"],
            )
            self._notify_delivery_unknown(post)

    def _preview_was_available_before_schedule(
        self, post: dict[str, Any]
    ) -> bool:
        preview_at = self._parse_datetime(post.get("preview_sent_at"))
        if not preview_at:
            return False
        try:
            scheduled_time = wall_time.fromisoformat(str(post["schedule_time"]))
        except ValueError:
            scheduled_time = self._publish_time(date.fromisoformat(post["schedule_date"]))
        schedule_at = datetime.combine(
            date.fromisoformat(post["schedule_date"]),
            scheduled_time,
            tzinfo=self.timezone,
        )
        return self._as_utc(preview_at) <= schedule_at.astimezone(timezone.utc)

    @staticmethod
    def _publish_time(target_date: date) -> wall_time:
        if target_date.weekday() == 6:
            return SUNDAY_PUBLISH_TIME
        if target_date.weekday() == 5:
            return SATURDAY_PUBLISH_TIME
        return WEEKDAY_PUBLISH_TIME

    @classmethod
    def _same_day_preview_time(cls, target_date: date) -> wall_time:
        scheduled = cls._publish_time(target_date)
        return wall_time(
            hour=max(0, scheduled.hour - 1),
            minute=scheduled.minute,
        )

    @staticmethod
    def _retry_is_due(post: dict[str, Any], now_utc: datetime) -> bool:
        retry_at = ChannelPostManager._parse_datetime(post.get("retry_after_at"))
        return bool(retry_at and ChannelPostManager._as_utc(retry_at) <= now_utc)

    def _is_duplicate(
        self, content: str, *, exclude_post_id: int | None = None
    ) -> bool:
        normalized = self._canonical_content(content)
        headline = self._canonical_content(self._post_headline(content))
        for previous in self.store.get_recent_channel_post_contents(
            limit=30,
            chat_id=self.destination_chat_id,
        ):
            if (
                previous.get("source") == "scheduled"
                and exclude_post_id is not None
                and int(previous["id"]) == exclude_post_id
            ):
                continue
            previous_content = str(previous["content"])
            previous_normalized = self._canonical_content(previous_content)
            previous_headline = self._canonical_content(
                self._post_headline(previous_content)
            )
            if previous_normalized == normalized:
                return True
            if SequenceMatcher(None, previous_normalized, normalized).ratio() >= 0.97:
                return True
            if (
                headline
                and previous_headline
                and SequenceMatcher(None, previous_headline, headline).ratio() >= 0.90
            ):
                return True
        return False

    @staticmethod
    def _post_headline(content: str) -> str:
        lines = [line.strip() for line in content.splitlines()]
        for index, line in enumerate(lines):
            if "━" in line:
                return next((item for item in lines[index + 1 :] if item), "")
        return next((item for item in lines if item), "")

    @staticmethod
    def _canonical_content(content: str) -> str:
        text = _SHARED_FOOTER.sub("", content.casefold())
        text = _PROMO_LINK.sub("", text)
        return re.sub(r"[^a-z0-9]+", "", text)

    @staticmethod
    def _promo_due(
        target_date: date,
        last_promo_date: str | None,
        interval_days: int = 14,
    ) -> bool:
        if target_date.weekday() != 5:
            return False
        if not last_promo_date:
            return True
        try:
            previous = date.fromisoformat(last_promo_date)
        except ValueError:
            return True
        return (target_date - previous).days >= interval_days

    @staticmethod
    def _verified_bot_username(bot_info: dict[str, Any]) -> str:
        username = str(bot_info.get("username") or "").removeprefix("@")
        if not _USERNAME.fullmatch(username):
            raise ValueError("Telegram did not return a valid bot username.")
        return username

    def verify_destination(self, post: dict[str, Any]) -> str:
        """Verify the configured channel and bot posting permission before a send."""
        if self.destination_chat_id is None:
            raise DestinationVerificationError("destination_not_configured")
        bot_info = self.api.get_me()
        username = self._verified_bot_username(bot_info)
        bot_id = int(bot_info.get("id", 0))
        if bot_id <= 0:
            raise DestinationVerificationError("bot_identity_unavailable")
        if post.get("is_promo") and username.casefold() != str(
            post.get("bot_username") or ""
        ).casefold():
            raise DestinationVerificationError("bot_username_changed")
        chat = self.api.get_chat(int(self.destination_chat_id))
        title = re.sub(r"[\r\n]+", " ", str(chat.get("title") or "")).strip()
        title_folded = title.casefold()
        unsafe_title = (
            "pro signals" in title_folded
            or bool(re.search(r"\b(?:test|testing|sandbox)\b", title_folded))
        )
        if (
            int(chat.get("id", 0)) != int(self.destination_chat_id)
            or chat.get("type") != "channel"
            or unsafe_title
        ):
            detail = (
                f"Telegram returned “{title[:120]}” "
                f"(type {str(chat.get('type') or 'unknown')}, "
                f"ID {chat.get('id', 'unknown')}); the configured destination "
                f"ID is {self.destination_chat_id}."
            )
            raise DestinationVerificationError("destination_not_verified", detail)
        member = self.api.get_chat_member(int(self.destination_chat_id), bot_id)
        status = member.get("status")
        can_post = status == "creator" or (
            status == "administrator" and member.get("can_post_messages") is True
        )
        if not can_post:
            raise DestinationVerificationError(
                "posting_permission_missing",
                f"Telegram returned “{title[:120]}” (ID "
                f"{chat.get('id', 'unknown')}); the bot lacks confirmed "
                "channel posting permission.",
            )
        return username

    def _post_from_callback(self, value: str) -> dict[str, Any] | None:
        try:
            return self.store.get_channel_post(int(value))
        except ValueError:
            return None

    @staticmethod
    def _category_label(category: str) -> str:
        labels = {
            "weekly_market_recap_evergreen": "Weekly review (evergreen fallback)",
            "new_week_preparation": "New-week preparation",
            "trading_psychology": "Trading psychology",
            "weekly_market_recap": "Weekly market recap",
        }
        return labels.get(category, category.replace("_", " ").title())

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            result = datetime.fromisoformat(value)
        except ValueError:
            return None
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class DestinationVerificationError(Exception):
    def __init__(self, category: str, safe_detail: str | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.safe_detail = safe_detail


