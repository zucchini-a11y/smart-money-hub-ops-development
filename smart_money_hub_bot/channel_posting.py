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
    compose_promo_post,
    compose_routine_post,
    next_category,
    validate_channel_post,
)
from .channel_gemini import (
    ChannelDraft,
    GeminiChannelContentService,
    GeminiChannelGenerationError,
)
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
MAX_AUTOMATIC_RATE_LIMIT_RETRIES = 1
_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_SHARED_FOOTER = re.compile(
    r"no confirmation,\s*no entry\.?", re.IGNORECASE
)
_PROMO_LINK = re.compile(r"open\s+@\w+.*?https://t\.me/\w+", re.IGNORECASE | re.DOTALL)


class ChannelPostManager:
    def __init__(
        self,
        api: TelegramAPI,
        store: Repository,
        admin_id: int | None,
        destination_chat_id: int | None,
        *,
        channel_writer: GeminiChannelContentService | None = None,
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self.destination_chat_id = destination_chat_id
        self.channel_writer = channel_writer
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
        if settings["paused"] or local_time < publish_time:
            return
        post = self.store.get_scheduled_channel_post(today.isoformat())
        if not post:
            return
        status = post["status"]
        if status == "draft" and self._preview_was_available_before_schedule(post):
            self._publish(post, current_utc, automatic=True)
        elif status == "retry_wait" and self._retry_is_due(post, current_utc):
            self._publish(post, current_utc, automatic=True)

    def show_controls(self, chat_id: int) -> None:
        settings = self.store.get_channel_posting_settings()
        paused = bool(settings["paused"])
        pending = self.store.list_channel_posts(limit=5, pending_only=True)
        recent = self.store.list_channel_posts(limit=5)
        lines = [
            "CHANNEL CONTENT SCHEDULER",
            "Weekday/Saturday schedule: 10:00 WAT; Sunday: 18:00 WAT.",
            "Admin preview: 18:00 WAT the evening before; one hour before if missing.",
            "Destination: the configured Market Analysis channel only.",
            "Gemini drafts weekend posts using archived channel posts and saved admin feedback.",
            f"Publishing: {'PAUSED' if paused else 'ACTIVE'}",
            (
                "Bot promotion interval: about once every "
                f"{int(settings.get('promo_interval_days', 14)) // 7} "
                "weekend(s); it replaces that day's routine post."
            ),
            "Changing the interval affects future drafts; existing previews stay unchanged.",
            "Market recap posts use an evergreen review when verified market data is unavailable.",
            "",
            "Pending posts:",
        ]
        if pending:
            for post in pending:
                lines.append(
                    f"• {post['schedule_date']} — {self._category_label(post['category'])} "
                    f"({post['status'].replace('_', ' ')})"
                )
        else:
            lines.append("• None")
        lines.extend(["", "Recent archive:"])
        if recent:
            for post in recent:
                promo_note = " · bot awareness" if post["is_promo"] else ""
                lines.append(
                    f"• {post['schedule_date']} — {self._category_label(post['category'])}"
                    f"{promo_note} — {post['status'].replace('_', ' ')}"
                )
        else:
            lines.append("• No posts recorded yet.")

        keyboard_rows: list[list[dict[str, str]]] = []
        for post in pending[:4]:
            keyboard_rows.append(
                [
                    {
                        "text": f"Review {post['schedule_date']}",
                        "callback_data": f"admin:channel_posts:preview:{post['id']}",
                    }
                ]
            )
        if recent:
            keyboard_rows.append(
                [
                    {
                        "text": f"Open latest ({recent[0]['schedule_date']})",
                        "callback_data": f"admin:channel_posts:preview:{recent[0]['id']}",
                    }
                ]
            )
        keyboard_rows.extend(
            [
                [
                    {
                        "text": "Resume publishing" if paused else "Pause publishing",
                        "callback_data": (
                            "admin:channel_posts:resume"
                            if paused
                            else "admin:channel_posts:pause"
                        ),
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
                [{"text": "Admin Dashboard", "callback_data": "admin:home"}],
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
            self.show_controls(chat_id)
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
        if action in {
            "edit",
            "revise",
            "edit_cancel",
            "publish",
            "reject",
            "skip",
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
                        "Send the complete replacement text in one message. Keep "
                        "“NO CONFIRMATION, NO ENTRY.” in the post."
                        f"{promo_note} Send /cancel to stop editing.",
                    )
                else:
                    self.api.send_message(
                        chat_id, "Only an unpublished draft can be edited."
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

    def handle_edit_message(
        self, chat_id: int, admin_id: int, text: str, is_private: bool
    ) -> bool:
        if not is_private or self.admin_id is None or admin_id != self.admin_id:
            self.cancel_edit(admin_id)
            return False
        post = self.store.pending_channel_post_edit(admin_id)
        if not post:
            return False
        username = post["bot_username"]
        rejection = validate_channel_post(
            text,
            is_promo=bool(post["is_promo"]),
            bot_username=username,
        )
        if rejection:
            logger.info("Channel post edit rejected category=%s.", rejection)
            self.api.send_message(
                chat_id,
                "I couldn't save that edit because it failed the publishing checks "
                f"({rejection}). Please send a corrected version or /cancel.",
            )
            return True
        if self._is_duplicate(text, exclude_post_id=int(post["id"])):
            self.api.send_message(
                chat_id,
                "That wording is too close to a recent post. Please send a fresh "
                "version or /cancel.",
            )
            return True
        saved = self.store.save_channel_post_edit(
            int(post["id"]), text.strip(), admin_id=admin_id
        )
        if not saved:
            self.api.send_message(chat_id, "This draft is no longer waiting for an edit.")
            return True
        refreshed = self.store.get_channel_post(int(post["id"]))
        if refreshed:
            self._send_preview(refreshed, datetime.now(timezone.utc))
        return True

    def show_post(self, chat_id: int, post: dict[str, Any]) -> None:
        status = post["status"]
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
                f"Status: {status.replace('_', ' ')}\n"
                f"Destination: configured Market Analysis channel\n\n"
            )
            if post.get("failure_category"):
                intro += f"Failure: {post['failure_category']}\n\n"
        rows: list[list[dict[str, str]]] = []
        if status == "draft":
            rows.extend(
                [
                    [
                        {
                            "text": "Revise with Gemini",
                            "callback_data": (
                                f"admin:channel_posts:revise:{post['id']}"
                            ),
                        },
                        {
                            "text": "Edit",
                            "callback_data": f"admin:channel_posts:edit:{post['id']}",
                        },
                        {
                            "text": "Publish now",
                            "callback_data": f"admin:channel_posts:publish:{post['id']}",
                        },
                    ],
                    [
                        {
                            "text": "Reject",
                            "callback_data": f"admin:channel_posts:reject:{post['id']}",
                        },
                        {
                            "text": "Skip",
                            "callback_data": f"admin:channel_posts:skip:{post['id']}",
                        },
                    ],
                ]
            )
        elif status == "awaiting_edit":
            rows.append(
                [
                    {
                        "text": "Cancel edit",
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
            if str(post.get("failure_category") or "").startswith("gemini_"):
                retry_action = (
                    "retry_revision"
                    if str(post.get("failure_category") or "").startswith(
                        "gemini_revision_"
                    )
                    else "retry_generation"
                )
                rows.append(
                    [
                        {
                            "text": "Retry Gemini revision"
                            if retry_action == "retry_revision"
                            else "Retry Gemini draft",
                            "callback_data": (
                                f"admin:channel_posts:{retry_action}:{post['id']}"
                            ),
                        }
                    ]
                )
            if post.get("content"):
                rows.append(
                    [
                        {
                            "text": "Publish now",
                            "callback_data": (
                                f"admin:channel_posts:publish:{post['id']}"
                            ),
                        }
                    ]
                )
            rows.append(
                [
                        {
                            "text": "Reject",
                            "callback_data": (
                                f"admin:channel_posts:reject:{post['id']}"
                            ),
                        },
                        {
                            "text": "Skip",
                            "callback_data": (
                                f"admin:channel_posts:skip:{post['id']}"
                            ),
                        },
                ]
            )
        rows.append(
            [{"text": "Channel Posts", "callback_data": "admin:channel_posts"}]
        )
        self.api.send_message(
            chat_id,
            intro + content if content else intro.rstrip(),
            {"inline_keyboard": rows},
        )

    def _ensure_and_preview(self, target_date: date, now_utc: datetime) -> None:
        post = self.store.get_scheduled_channel_post(target_date.isoformat())
        if not post:
            post = self._create_post(target_date)
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

    def _create_post(self, target_date: date) -> dict[str, Any] | None:
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
        if target_date.weekday() in {5, 6}:
            return self._create_weekend_post(
                target_date,
                requested_category,
                schedule_time,
                is_promo,
                username,
                sequence,
                settings,
            )

        routine = compose_routine_post(requested_category, sequence)
        category = (
            "weekly_market_recap_evergreen"
            if requested_category == "weekly_market_recap"
            else requested_category
        )
        feature_index = int(settings["next_promo_feature_index"])
        content = (
            compose_promo_post(routine, username, feature_index, hook_index=sequence)
            if is_promo and username
            else routine
        )
        if self._is_duplicate(content):
            for variant in range(1, 6):
                routine = compose_routine_post(requested_category, sequence + variant)
                content = (
                    compose_promo_post(
                        routine,
                        username,
                        feature_index,
                        hook_index=sequence + variant,
                    )
                    if is_promo and username
                    else routine
                )
                if not self._is_duplicate(content):
                    break
            else:
                logger.warning("Channel post draft withheld: duplicate content detected.")
                return None
        rejection = validate_channel_post(
            content,
            is_promo=is_promo,
            bot_username=username,
        )
        if rejection:
            logger.error("Channel post draft withheld category=%s.", rejection)
            return None
        post, created = self.store.create_scheduled_channel_post(
            schedule_date=target_date.isoformat(),
            schedule_time=schedule_time,
            requested_category=requested_category,
            category=category,
            content=content,
            destination_chat_id=int(self.destination_chat_id or 0),
            is_promo=is_promo,
            bot_username=username,
            next_category_index=sequence + 1,
            next_promo_feature_index=feature_index + 1 if is_promo else feature_index,
            last_promo_date=(
                target_date.isoformat()
                if is_promo
                else settings.get("last_promo_date")
            ),
        )
        return post if created or post else None

    def _create_weekend_post(
        self,
        target_date: date,
        preferred_category: str,
        schedule_time: str,
        is_promo: bool,
        username: str | None,
        sequence: int,
        settings: dict[str, Any],
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
        )
        if not created:
            return post
        return self._generate_weekend_post(
            post,
            preferred_category=preferred_category,
            sequence=sequence,
            settings=settings,
        )

    def _generate_weekend_post(
        self,
        post: dict[str, Any],
        *,
        preferred_category: str,
        sequence: int,
        settings: dict[str, Any],
        revision_feedback: str | None = None,
        admin_id: int | None = None,
    ) -> dict[str, Any]:
        if self.channel_writer is None:
            return self._record_generation_failure(
                post,
                "gemini_not_configured",
                admin_id=admin_id,
            )
        try:
            draft = self.channel_writer.generate(
                schedule_date=str(post["schedule_date"]),
                schedule_time=str(post["schedule_time"]),
                preferred_category=preferred_category,
                history=self.store.get_recent_channel_post_contents(
                    limit=12,
                    chat_id=self.destination_chat_id,
                ),
                admin_feedback=self.store.get_recent_channel_post_feedback(limit=5),
                verified_information=[],
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
            )
        except Exception:
            logger.exception(
                "Weekend Gemini draft failed category=unexpected_provider_error "
                "post_id=%s.",
                post["id"],
            )
            return self._record_generation_failure(
                post,
                "gemini_unexpected_error",
                admin_id=admin_id,
                revision=revision_feedback is not None,
            )

        rejection = validate_channel_post(
            draft.content,
            is_promo=bool(post["is_promo"]),
            bot_username=post.get("bot_username"),
        )
        if rejection or self._is_duplicate(
            draft.content,
            exclude_post_id=int(post["id"]),
        ):
            category = rejection or "duplicate_content"
            return self._record_generation_failure(
                post,
                f"gemini_content_rejected_{category}",
                admin_id=admin_id,
                revision=revision_feedback is not None,
            )

        next_feature_index = int(settings["next_promo_feature_index"])
        last_promo_date = settings.get("last_promo_date")
        advance_rotation = revision_feedback is None
        if post["is_promo"] and advance_rotation:
            next_feature_index += 1
            last_promo_date = str(post["schedule_date"])
        action = "gemini_revised" if revision_feedback else "gemini_generated"
        if not self.store.complete_channel_post_generation(
            int(post["id"]),
            category=draft.category,
            content=draft.content,
            bot_username=post.get("bot_username"),
            next_category_index=sequence + 1 if advance_rotation else sequence,
            next_promo_feature_index=next_feature_index,
            last_promo_date=last_promo_date,
            action=action,
            admin_id=admin_id,
        ):
            return self._record_generation_failure(
                post,
                "gemini_post_state_changed",
                admin_id=admin_id,
                revision=revision_feedback is not None,
            )
        saved = self.store.get_channel_post(int(post["id"])) or post
        logger.info(
            "Weekend channel draft generated category=%s promo=%s.",
            draft.category,
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
        if post.get("status") != "failed" or post.get("content"):
            self.api.send_message(chat_id, "This post is not waiting for Gemini generation.")
            return
        settings = self.store.get_channel_posting_settings()
        generated = self._generate_weekend_post(
            post,
            preferred_category=str(post["requested_category"]),
            sequence=int(settings["next_category_index"]),
            settings=settings,
            admin_id=admin_id,
        )
        if generated.get("status") == "draft":
            self._send_preview(generated, now_utc)

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
        revised = self._generate_weekend_post(
            post,
            preferred_category=str(post["requested_category"]),
            sequence=int(settings["next_category_index"]),
            settings=settings,
            revision_feedback=feedback,
            admin_id=admin_id,
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
        )
        return self._record_generation_failure(post, failure_category)

    def _record_generation_failure(
        self,
        post: dict[str, Any],
        failure_category: str,
        *,
        admin_id: int | None = None,
        revision: bool = False,
    ) -> dict[str, Any]:
        category = (
            f"gemini_revision_{failure_category}"
            if revision
            else f"gemini_{failure_category}"
        )
        self.store.set_channel_post_status(
            int(post["id"]),
            "failed",
            action="gemini_revision_failed" if revision else "gemini_generation_failed",
            admin_id=admin_id,
            details=category,
            failure_category=category,
        )
        logger.warning(
            "Weekend channel draft held failure_category=%s.",
            category,
        )
        saved = self.store.get_channel_post(int(post["id"])) or post
        self._notify_failure(saved, category)
        return saved

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
        settings = self.store.get_channel_posting_settings()
        if settings["paused"]:
            if not automatic:
                self.api.send_message(
                    self.admin_id,
                    "Publishing is paused. Resume channel publishing first.",
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
        if rejection:
            self._fail_before_send(post, rejection, admin_id)
            return
        try:
            bot_info = self.api.get_me()
            username = self._verified_bot_username(bot_info)
            bot_id = int(bot_info.get("id", 0))
            if bot_id <= 0:
                raise _PreflightFailure("bot_identity_unavailable")
            if post["is_promo"] and username.casefold() != str(
                post.get("bot_username") or ""
            ).casefold():
                raise _PreflightFailure("bot_username_changed")
            chat = self.api.get_chat(int(self.destination_chat_id))
            if (
                int(chat.get("id", 0)) != int(self.destination_chat_id)
                or chat.get("type") != "channel"
                or "market analysis" not in str(chat.get("title", "")).casefold()
            ):
                raise _PreflightFailure("destination_not_verified")
            member = self.api.get_chat_member(int(self.destination_chat_id), bot_id)
            status = member.get("status")
            can_post = status == "creator" or (
                status == "administrator" and member.get("can_post_messages") is True
            )
            if not can_post:
                raise _PreflightFailure("posting_permission_missing")
        except _PreflightFailure as error:
            self._fail_before_send(post, error.category, admin_id)
            return
        except (TelegramAPIError, TypeError, ValueError, AttributeError):
            self._fail_before_send(post, "destination_verification_unavailable", admin_id)
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
            result = self.api.send_message_with_result(
                int(self.destination_chat_id),
                post["content"],
                markup,
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

    def _notify_failure(self, post: dict[str, Any], category: str) -> None:
        if self.admin_id is None:
            return
        self._notify_admin(
            f"The {post['schedule_date']} channel post was not confirmed. "
            f"Failure category: {category}. You can review it in Channel Posts.",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "Review post",
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
        self, post: dict[str, Any], category: str, admin_id: int | None
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
        self._notify_failure(post, category)

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
        schedule_at = datetime.combine(
            date.fromisoformat(post["schedule_date"]),
            DAILY_PUBLISH_TIME,
            tzinfo=self.timezone,
        )
        return self._as_utc(preview_at) <= schedule_at.astimezone(timezone.utc)

    @staticmethod
    def _retry_is_due(post: dict[str, Any], now_utc: datetime) -> bool:
        retry_at = ChannelPostManager._parse_datetime(post.get("retry_after_at"))
        return bool(retry_at and ChannelPostManager._as_utc(retry_at) <= now_utc)

    def _is_duplicate(
        self, content: str, *, exclude_post_id: int | None = None
    ) -> bool:
        normalized = self._canonical_content(content)
        for previous in self.store.get_recent_channel_post_contents(limit=30):
            if exclude_post_id is not None and int(previous["id"]) == exclude_post_id:
                continue
            if self._canonical_content(previous["content"]) == normalized:
                return True
            if SequenceMatcher(
                None,
                self._canonical_content(previous["content"]),
                normalized,
            ).ratio() >= 0.97:
                return True
        return False

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


class _PreflightFailure(Exception):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category
