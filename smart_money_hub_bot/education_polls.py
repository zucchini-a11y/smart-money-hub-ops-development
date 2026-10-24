"""Safe, persistent education-group quiz poll publishing."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .group_features import SCENARIO_POLLS, ScenarioPoll
from .telegram_api import TelegramAPIError

logger = logging.getLogger(__name__)
POLL_TIMEZONE = ZoneInfo("Africa/Lagos")
POLL_WEEKDAY = 5  # Saturday
POLL_LOCAL_TIME = time(21, 0)
POLL_LATE_GRACE = timedelta(minutes=5)
EXPECTED_EDUCATION_GROUP_ID = -1003916437804
EXPECTED_MARKET_ANALYSIS_CHANNEL_ID = -1004481197912


class EducationPollError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def scheduled_occurrence(now: datetime) -> tuple[str, datetime]:
    """Return the most recent Saturday 21:00 WAT occurrence and its date key."""
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(POLL_TIMEZONE)
    days_since_saturday = (local_now.weekday() - POLL_WEEKDAY) % 7
    scheduled_date = local_now.date() - timedelta(days=days_since_saturday)
    scheduled_local = datetime.combine(
        scheduled_date, POLL_LOCAL_TIME, tzinfo=POLL_TIMEZONE
    )
    if local_now < scheduled_local:
        scheduled_date -= timedelta(days=7)
        scheduled_local = datetime.combine(
            scheduled_date, POLL_LOCAL_TIME, tzinfo=POLL_TIMEZONE
        )
    return scheduled_date.isoformat(), scheduled_local.astimezone(timezone.utc)


def is_on_demand_poll_request(text: str) -> bool:
    normalized = " ".join(text.strip().casefold().split())
    return bool(
        re.fullmatch(
            r"(?:(?:please\s+)?(?:can|could)\s+you\s+|"
            r"(?:please\s+)?|i want you to\s+)"
            r"(?:post|publish|send|create|make)\s+"
            r"(?:(?:a|an)\s+)?(?:new\s+)?"
            r"(?:(?:smc|education(?:al)?(?:\s+group)?)\s+)?"
            r"poll\s+(?:now|today|right now)[.!?]?",
            normalized,
        )
    )


def group_poll_message_url(
    *,
    group_id: int,
    group_chat: dict[str, Any],
    message_id: int,
    thread_id: int | None = None,
) -> str:
    username = group_chat.get("username")
    if isinstance(username, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        if thread_id is not None:
            return f"https://t.me/{username}/{thread_id}/{message_id}"
        return f"https://t.me/{username}/{message_id}"
    group_text = str(group_id)
    if not group_text.startswith("-100") or not group_text[4:].isdigit():
        raise EducationPollError("education_group_link_unavailable")
    if thread_id is not None:
        return f"https://t.me/c/{group_text[4:]}/{thread_id}/{message_id}"
    return f"https://t.me/c/{group_text[4:]}/{message_id}"


def parse_education_poll_message_link(link: str) -> tuple[int, int | None, int]:
    parsed = urlsplit(link.strip())
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "t.me"
        or len(parts) not in {3, 4}
        or parts[0] != "c"
        or not parts[1].isdigit()
        or any(not part.isdigit() for part in parts[2:])
    ):
        raise EducationPollError("education_poll_link_invalid")
    group_id = int(f"-100{parts[1]}")
    if group_id != EXPECTED_EDUCATION_GROUP_ID:
        raise EducationPollError("education_group_destination_mismatch")
    if len(parts) == 3:
        thread_id = None
        message_id = int(parts[2])
    else:
        thread_id = int(parts[2])
        message_id = int(parts[3])
    if message_id <= 0 or (thread_id is not None and thread_id <= 0):
        raise EducationPollError("education_poll_link_invalid")
    return group_id, thread_id, message_id


def format_channel_poll_preview(scenario: ScenarioPoll) -> str:
    return (
        "📊 <b>SMART MONEY HUB | EDUCATION POLL</b>\n\n"
        "<b>Test your SMC understanding</b>\n\n"
        f"{html.escape(scenario.question)}\n\n"
        "🗳️ Tap below to vote in the Education Group.\n\n"
        "⚠️ <b>NO CONFIRMATION, NO ENTRY.</b>"
    )


def _is_prohibited_destination_title(title: str) -> bool:
    normalized = " ".join(title.split()).casefold()
    return "pro signals" in normalized or bool(
        re.search(r"\b(?:test(?:ing)?|sandbox)\b", normalized)
    )


def verify_poll_destinations(
    api: Any,
    *,
    education_group_id: int | None,
    channel_id: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify configured destinations and bot permissions without sending posts."""
    if education_group_id != EXPECTED_EDUCATION_GROUP_ID:
        raise EducationPollError("education_group_destination_mismatch")
    if channel_id != EXPECTED_MARKET_ANALYSIS_CHANNEL_ID:
        raise EducationPollError("market_analysis_destination_mismatch")

    try:
        bot = api.get_me()
        bot_id = bot.get("id")
        if not isinstance(bot_id, int) or bot_id <= 0:
            raise EducationPollError("bot_identity_unavailable")
        group = api.get_chat(education_group_id)
        channel = api.get_chat(channel_id)
        group_title = " ".join(str(group.get("title") or "").split()).casefold()
        channel_title = " ".join(str(channel.get("title") or "").split()).casefold()
        if (
            group.get("id") != education_group_id
            or group.get("type") != "supergroup"
            or _is_prohibited_destination_title(group_title)
        ):
            raise EducationPollError("education_group_destination_not_verified")
        if (
            channel.get("id") != channel_id
            or channel.get("type") != "channel"
            or _is_prohibited_destination_title(channel_title)
        ):
            raise EducationPollError("market_analysis_destination_not_verified")

        group_member = api.get_chat_member(education_group_id, bot_id)
        if group_member.get("status") not in {"administrator", "creator"}:
            raise EducationPollError("education_group_poll_permission_missing")
        channel_member = api.get_chat_member(channel_id, bot_id)
        status = channel_member.get("status")
        if not (
            status == "creator"
            or (
                status == "administrator"
                and channel_member.get("can_post_messages") is True
            )
        ):
            raise EducationPollError("market_analysis_post_permission_missing")
        return group, channel
    except EducationPollError:
        raise
    except (TelegramAPIError, TypeError, ValueError, AttributeError):
        raise EducationPollError("telegram_destination_verification_unavailable") from None
    except Exception:
        logger.warning("Unexpected error while checking education poll destinations.")
        raise EducationPollError("telegram_destination_verification_unavailable") from None


class EducationPollPublisher:
    """Publishes a vetted group quiz and a channel preview without duplicate sends."""

    def __init__(
        self,
        api: Any,
        store: Any,
        *,
        admin_id: int | None,
        education_group_id: int | None,
        channel_id: int | None,
        started_at: datetime | None = None,
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self.education_group_id = education_group_id
        self.channel_id = channel_id
        self.started_at = started_at or datetime.now(timezone.utc)
        if self.started_at.tzinfo is None:
            self.started_at = self.started_at.replace(tzinfo=timezone.utc)

    def dispatch_due(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        local_now = current.astimezone(POLL_TIMEZONE)
        if (
            local_now.weekday() == POLL_WEEKDAY
            and local_now.time().replace(tzinfo=None) >= POLL_LOCAL_TIME
        ):
            schedule_date = local_now.date().isoformat()
            scheduled_at = datetime.combine(
                local_now.date(), POLL_LOCAL_TIME, tzinfo=POLL_TIMEZONE
            ).astimezone(timezone.utc)
            run_key = f"weekly:{schedule_date}"
            if self.store.education_poll_run(run_key) is None:
                late_by = current.astimezone(timezone.utc) - scheduled_at
                started_after_due = self.started_at.astimezone(
                    timezone.utc
                ) >= scheduled_at
                status = (
                    "skipped"
                    if late_by > POLL_LATE_GRACE or started_after_due
                    else "queued"
                )
                category = (
                    "poll_scheduler_started_after_due"
                    if started_after_due
                    else "missed_schedule_window" if status == "skipped" else None
                )
                self.store.create_education_poll_run(
                    run_key=run_key,
                    source="weekly",
                    scheduled_at=scheduled_at.isoformat(),
                    scenario_index=self.store.next_education_poll_scenario_index(),
                    status=status,
                    failure_category=category,
                )
                if status == "skipped":
                    self._notify_admin(
                        "The scheduled Education group poll was skipped because the "
                        "bot started too late or was unavailable more than five "
                        "minutes after Saturday 9:00 PM WAT. It was not posted late."
                    )
        self.dispatch_pending(current)

    def post_now(self, request_key: str, now: datetime | None = None) -> str:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        run_key = f"manual:{request_key}"[:160]
        run = self.store.education_poll_run(run_key)
        if run is None:
            run = self.store.create_education_poll_run(
                run_key=run_key,
                source="manual",
                scheduled_at=current.astimezone(timezone.utc).isoformat(),
                scenario_index=self.store.next_education_poll_scenario_index(),
            )
        self._dispatch_run(run, current)
        updated = self.store.education_poll_run(run_key) or run
        return str(updated["status"])

    def publish_existing_poll_preview(
        self,
        poll_link: str,
        *,
        scenario_index: int,
        now: datetime | None = None,
    ) -> str:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        group_id, thread_id, message_id = parse_education_poll_message_link(poll_link)
        if not 0 <= scenario_index < len(SCENARIO_POLLS):
            raise EducationPollError("scenario_unavailable")
        existing = self.store.education_poll_run_for_group_message(
            message_id, thread_id
        )
        if existing is not None:
            if existing.get("status") == "group_sent":
                self._dispatch_run(existing, current)
            updated = self.store.education_poll_run(str(existing["run_key"])) or existing
            return str(updated["status"])
        thread_key = str(thread_id) if thread_id is not None else "general"
        run_key = f"manual:mirror:{group_id}:{thread_key}:{message_id}"
        run = self.store.create_education_poll_run(
            run_key=run_key,
            source="manual",
            scheduled_at=current.astimezone(timezone.utc).isoformat(),
            scenario_index=scenario_index,
            status="group_sent",
            group_message_id=message_id,
            group_thread_id=thread_id,
        )
        self._dispatch_run(run, current)
        updated = self.store.education_poll_run(run_key) or run
        return str(updated["status"])

    def edit_existing_poll_preview(self, poll_link: str) -> str:
        group_id, thread_id, message_id = parse_education_poll_message_link(poll_link)
        run = self.store.education_poll_run_for_group_message(message_id, thread_id)
        if (
            run is None
            or run.get("status") != "published"
            or not isinstance(run.get("channel_message_id"), int)
        ):
            raise EducationPollError("existing_channel_preview_not_found")
        scenario_index = int(run.get("scenario_index", -1))
        if not 0 <= scenario_index < len(SCENARIO_POLLS):
            raise EducationPollError("scenario_unavailable")

        verify_poll_destinations(
            self.api,
            education_group_id=self.education_group_id,
            channel_id=self.channel_id,
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "Vote in Education Group",
                        "url": poll_link.strip(),
                    }
                ]
            ]
        }
        try:
            self.api.edit_message_text(
                int(self.channel_id),
                int(run["channel_message_id"]),
                format_channel_poll_preview(SCENARIO_POLLS[scenario_index]),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except TelegramAPIError as error:
            if "message is not modified" in str(error).casefold():
                return "already_current"
            raise EducationPollError("existing_channel_preview_edit_failed") from None
        logger.info("Existing Education poll channel preview updated.")
        return "edited"

    def dispatch_pending(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        for run in self.store.pending_education_poll_runs():
            self._dispatch_run(run, current)

    def _dispatch_run(self, run: dict[str, Any], now: datetime) -> None:
        run_key = str(run["run_key"])
        status = str(run["status"])
        if status in {
            "published",
            "failed",
            "delivery_unknown",
            "channel_failed",
            "channel_delivery_unknown",
            "skipped",
        }:
            return
        if run.get("source") == "weekly" and status in {"queued", "group_sent"}:
            scheduled_at = datetime.fromisoformat(str(run["scheduled_at"]))
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
            if now.astimezone(timezone.utc) - scheduled_at.astimezone(timezone.utc) > POLL_LATE_GRACE:
                final_status = "skipped" if status == "queued" else "channel_failed"
                category = (
                    "missed_schedule_window"
                    if status == "queued"
                    else "missed_channel_preview_window"
                )
                if self.store.fail_education_poll_run(
                    run_key, status=final_status, failure_category=category
                ):
                    self._notify_admin(
                        "The scheduled Education poll was not completed within five "
                        "minutes of Saturday 9:00 PM WAT. I did not send it late."
                    )
                return
        if status in {"sending_group", "sending_channel"}:
            failure_status = (
                "delivery_unknown" if status == "sending_group"
                else "channel_delivery_unknown"
            )
            category = (
                "poll_send_interrupted"
                if status == "sending_group"
                else "channel_preview_send_interrupted"
            )
            if self.store.fail_education_poll_run(
                run_key, status=failure_status, failure_category=category
            ):
                self._notify_admin(
                    "A poll send was interrupted during restart and Telegram delivery "
                    "could not be confirmed. I did not retry it to avoid duplicates. "
                    "Check the Education group and channel before requesting another."
                )
            return
        if self.admin_id is None:
            if self.store.fail_education_poll_run(
                run_key, status="failed", failure_category="admin_not_configured"
            ):
                logger.warning("Education poll held: admin is not configured.")
            return

        try:
            group, _channel = verify_poll_destinations(
                self.api,
                education_group_id=self.education_group_id,
                channel_id=self.channel_id,
            )
        except EducationPollError as error:
            if self.store.fail_education_poll_run(
                run_key, status="failed", failure_category=error.category
            ):
                if status == "group_sent":
                    self._notify_admin(
                        "The poll is already live in the Education group, but its "
                        f"channel preview was held ({error.category}). No additional "
                        "poll was sent."
                    )
                    return
                self._notify_admin(
                    f"Education poll held: destination check failed ({error.category}). "
                    "No new poll or channel preview was sent."
                )
            return

        scenario = SCENARIO_POLLS[
            int(run["scenario_index"]) % len(SCENARIO_POLLS)
        ]
        if status == "queued":
            if not self.store.reserve_education_poll_group(run_key):
                return
            try:
                result = self.api.send_poll(
                    int(self.education_group_id),
                    scenario.question,
                    list(scenario.options),
                    scenario.correct_option_id,
                    scenario.explanation,
                )
            except TelegramAPIError as error:
                outcome = (
                    "delivery_unknown" if error.delivery_unknown else "failed"
                )
                category = (
                    "telegram_poll_delivery_unknown"
                    if error.delivery_unknown
                    else f"telegram_poll_error_{error.http_status or error.error_code or 'unknown'}"
                )
                if self.store.fail_education_poll_run(
                    run_key, status=outcome, failure_category=category
                ):
                    self._notify_admin(
                        f"Education poll send failed ({category}). "
                        "No automatic retry was made."
                    )
                return
            message_id = result.get("message_id")
            if not isinstance(message_id, int):
                self.store.fail_education_poll_run(
                    run_key,
                    status="delivery_unknown",
                    failure_category="telegram_poll_confirmation_missing",
                )
                self._notify_admin(
                    "Telegram did not confirm the Education poll message ID. "
                    "I did not retry to avoid posting a duplicate."
                )
                return
            if not self.store.mark_education_poll_group_sent(run_key, message_id):
                self._notify_admin(
                    "Telegram accepted an Education poll, but its delivery state "
                    "could not be saved. Check the group before retrying."
                )
                return
            poll = result.get("poll")
            poll_id = str(poll.get("id") or "") if isinstance(poll, dict) else ""
            archive_content = (
                f"{scenario.question}\nOptions:\n"
                + "\n".join(
                    f"{index + 1}. {option}"
                    for index, option in enumerate(scenario.options)
                )
                + f"\nCorrect option: {scenario.options[scenario.correct_option_id]}"
                + f"\nExplanation: {scenario.explanation}"
            )
            try:
                self.store.record_education_group_post(
                    chat_id=int(self.education_group_id),
                    message_id=message_id,
                    thread_id=None,
                    topic_name="",
                    message_kind="poll",
                    content=archive_content,
                    source_status="bot_authored",
                    posted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
                if poll_id:
                    self.store.record_education_group_poll(
                        poll_id=poll_id,
                        chat_id=int(self.education_group_id),
                        message_id=message_id,
                        thread_id=None,
                        topic_name="",
                        question=scenario.question,
                        correct_option_id=scenario.correct_option_id,
                    )
            except Exception:
                logger.warning("Could not archive the scheduled education poll.")
            run = self.store.education_poll_run(run_key) or run
            status = str(run["status"])

        if status == "group_sent":
            if not self.store.reserve_education_poll_channel(run_key):
                return
            message_id = run.get("group_message_id")
            if not isinstance(message_id, int):
                self.store.fail_education_poll_run(
                    run_key,
                    status="channel_failed",
                    failure_category="group_poll_message_id_missing",
                )
                self._notify_admin(
                    "The group poll exists, but its message link is unavailable. "
                    "The channel preview was not sent."
                )
                return
            try:
                poll_url = group_poll_message_url(
                    group_id=int(self.education_group_id),
                    group_chat=group,
                    message_id=message_id,
                    thread_id=run.get("group_thread_id"),
                )
                preview = format_channel_poll_preview(scenario)
                result = self.api.send_message_with_result(
                    int(self.channel_id),
                    preview,
                    {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Vote in Education Group",
                                    "url": poll_url,
                                }
                            ]
                        ]
                    },
                    parse_mode="HTML",
                )
            except EducationPollError as error:
                self.store.fail_education_poll_run(
                    run_key,
                    status="channel_failed",
                    failure_category=error.category,
                )
                self._notify_admin(
                    f"The Education poll is live, but its channel preview failed "
                    f"({error.category}). No second group poll was sent."
                )
                return
            except TelegramAPIError as error:
                outcome = (
                    "channel_delivery_unknown"
                    if error.delivery_unknown
                    else "channel_failed"
                )
                category = (
                    "telegram_channel_preview_delivery_unknown"
                    if error.delivery_unknown
                    else f"telegram_channel_preview_error_{error.http_status or error.error_code or 'unknown'}"
                )
                self.store.fail_education_poll_run(
                    run_key, status=outcome, failure_category=category
                )
                self._notify_admin(
                    f"The Education poll is live, but the channel preview failed "
                    f"({category}). The group poll will not be duplicated."
                )
                return
            channel_message_id = result.get("message_id")
            if not isinstance(channel_message_id, int):
                self.store.fail_education_poll_run(
                    run_key,
                    status="channel_delivery_unknown",
                    failure_category="channel_preview_confirmation_missing",
                )
                self._notify_admin(
                    "The channel preview may have been delivered, but Telegram "
                    "did not confirm its message ID. I will not retry automatically."
                )
                return
            if self.store.complete_education_poll_channel(
                run_key, channel_message_id
            ):
                logger.info("Education poll and channel preview published.")
                if run.get("source") == "manual":
                    self._notify_admin(
                        "The SMC poll is live in the Education group, and its channel "
                        "preview now links to the poll."
                    )
    def _notify_admin(self, text: str) -> None:
        if self.admin_id is None:
            return
        try:
            self.api.send_message(self.admin_id, text)
        except Exception:
            logger.warning("Could not deliver an Education poll status to the admin.")
