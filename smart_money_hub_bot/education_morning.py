"""Persistent, non-repeating daily Education-group learning notes."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .education_polls import EXPECTED_EDUCATION_GROUP_ID
from .group_features import SCENARIO_POLLS
from .telegram_api import TelegramAPIError

logger = logging.getLogger(__name__)
MORNING_ZONE = ZoneInfo("Africa/Lagos")
MORNING_TIME = time(8, 0)
MORNING_LATE_GRACE = timedelta(minutes=5)
TELEGRAM_TEXT_LIMIT_UTF16 = 4096


@dataclass(frozen=True)
class MorningLesson:
    topic: str
    title: str
    lesson: str
    practice: str
    keywords: tuple[str, ...]
    checklist: tuple[str, ...] = ()
    takeaway: str | None = None


class MorningPublishingError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


# These evergreen notes deliberately avoid live-market claims, trade signals,
# promises about institutional intent, and fixed personal risk settings.
MORNING_LESSONS: tuple[MorningLesson, ...] = (
    MorningLesson(
        "liquidity", "A SWING HIGH IS A REFERENCE, NOT A SIGNAL",
        "A move above a visible high may be studied as a possible liquidity sweep. "
        "The wick alone does not confirm a reversal or reveal who placed orders.",
        "Write down what close-based confirmation your own plan requires.",
        ("liquidity", "swing high", "sweep"),
    ),
    MorningLesson(
        "structure", "DEFINE THE STRUCTURE YOU ARE READING",
        "A BOS or CHOCH label depends on the swing points and rules you chose. "
        "Mark the relevant high or low before interpreting a break.",
        "Name the timeframe and the exact swing that matters to your setup.",
        ("structure", "bos", "choch"),
    ),
    MorningLesson(
        "confirmation", "A WICK IS NOT A CLOSE",
        "A brief move beyond a level and a candle close beyond it are different "
        "observations. Decide in advance which one your setup requires.",
        "Review one chart and label the wick and candle close separately.",
        ("confirmation", "wick", "close"),
    ),
    MorningLesson(
        "poi", "A POINT OF INTEREST IS NOT AN ENTRY",
        "A POI can help organize a chart, but price reaching an area does not "
        "confirm that a trade is valid. A POI identifies where to pay attention, "
        "not when to enter.",
        "List the confirmation and invalidation conditions before considering entry.",
        ("poi", "entry", "confirmation"),
        checklist=(
            "Identify the POI and its relevance to market structure.",
            "Define the confirmation required by your trading plan.",
            "Establish invalidation conditions before entry.",
            "Wait for price to confirm the setup; do not enter simply because it reached the zone.",
        ),
        takeaway="A POI identifies where to pay attention, not when to enter.",
    ),
    MorningLesson(
        "fvg", "TREAT AN FVG AS A CHART CONCEPT",
        "A fair value gap is a charting concept. It does not have to fill, hold, "
        "or produce a reversal.",
        "Record what would disprove your idea if price returns to the area.",
        ("fvg", "fair value gap"),
    ),
    MorningLesson(
        "displacement", "DESCRIBE DISPLACEMENT WITH YOUR OWN RULES",
        "Traders use displacement to describe a forceful price move, but the term "
        "can be subjective unless your method defines it.",
        "Write the observable candle or structure conditions you use.",
        ("displacement", "momentum"),
    ),
    MorningLesson(
        "retest", "A RETEST DOES NOT GUARANTEE CONTINUATION",
        "Returning to a broken level can be useful context, but a retest alone "
        "does not guarantee that price will continue in the same direction.",
        "Check whether your plan requires a reaction or close after the retest.",
        ("retest", "continuation"),
    ),
    MorningLesson(
        "risk", "PLAN INVALIDATION BEFORE ENTRY",
        "A trade idea is easier to manage when the point that invalidates it is "
        "clear before entry, not chosen after price moves.",
        "Write the invalidation condition and position-size rule first.",
        ("risk", "invalidation", "position size"),
    ),
    MorningLesson(
        "patience", "WAITING IS A VALID DECISION",
        "If your confirmation is missing or the setup is unclear, standing aside "
        "is a disciplined decision—not a missed obligation.",
        "Identify one condition that would make you skip a setup today.",
        ("patience", "discipline", "stand aside"),
    ),
    MorningLesson(
        "journal", "SEPARATE THE PLAN FROM THE RESULT",
        "A profitable result does not prove every decision was sound, and a loss "
        "does not automatically mean the plan was wrong.",
        "Journal what you knew before entry and whether you followed your rules.",
        ("journal", "review", "results"),
    ),
    MorningLesson(
        "timeframe", "KEEP TIMEFRAMES IN THEIR ROLES",
        "A higher-timeframe idea and a lower-timeframe trigger answer different "
        "questions. One does not replace the other.",
        "Write the job of each timeframe in your setup before charting.",
        ("timeframe", "higher timeframe", "lower timeframe"),
    ),
    MorningLesson(
        "fomo", "DO NOT CHASE A MOVE YOU DID NOT PLAN",
        "A fast move can create pressure to act. Entering only because price has "
        "already moved can leave the original risk plan behind.",
        "If the setup has gone, wait for a new one that meets your rules.",
        ("fomo", "chasing", "plan"),
    ),
    MorningLesson(
        "bias", "BIAS IS A HYPOTHESIS",
        "A directional bias is a working idea, not proof. Keep track of the "
        "conditions that would weaken or invalidate it.",
        "Write one supporting observation and one invalidation condition.",
        ("bias", "hypothesis", "invalidation"),
    ),
    MorningLesson(
        "levels", "MARK LEVELS BEFORE PRICE REACHES THEM",
        "Planning reference levels in advance can reduce rushed decisions. A "
        "marked level still needs the confirmation required by your plan.",
        "Choose the level, the response you need, and what would cancel the idea.",
        ("levels", "planning", "confirmation"),
    ),
    MorningLesson(
        "order blocks", "KEEP ORDER-BLOCK LABELS PRECISE",
        "An order-block label is an interpretation of chart behavior, not proof "
        "of a specific institution's activity or intention.",
        "Record the observable price action separately from your interpretation.",
        ("order block", "institution", "interpretation"),
    ),
    MorningLesson(
        "market context", "CONTEXT DOES NOT REPLACE CONFIRMATION",
        "A chart narrative can help organize observations, but no narrative "
        "removes the need for your entry, invalidation, and risk rules.",
        "Check that each part of your setup is present before acting.",
        ("context", "confirmation", "risk"),
    ),
    MorningLesson(
        "risk", "SIZE THE POSITION FROM THE PLAN",
        "Position size should follow the account risk and invalidation distance "
        "you selected—not the confidence you feel in a setup.",
        "Recheck your sizing method before placing any order.",
        ("risk", "position size", "invalidation"),
    ),
    MorningLesson(
        "liquidity", "A LIQUIDITY POOL IS A POSSIBILITY",
        "A visible high or low may attract trader attention, but a chart does "
        "not show every resting order or identify who holds it.",
        "Describe the visible level without claiming to know participants' intent.",
        ("liquidity", "orders", "high", "low"),
    ),
    MorningLesson(
        "breakout", "CHECK WHAT COUNTS AS A VALID BREAK",
        "A move through a level may be temporary. Your written rules should "
        "define whether you need a close, follow-through, or another condition.",
        "Apply the same break criteria consistently during chart review.",
        ("breakout", "close", "follow-through"),
    ),
    MorningLesson(
        "psychology", "NOTICE THE URGE TO RECOVER A LOSS",
        "Trying to win back a loss quickly can lead to decisions outside the "
        "plan. A pause can protect decision quality.",
        "Step back and resume only when you can follow your normal checklist.",
        ("psychology", "loss", "discipline"),
    ),
    MorningLesson(
        "review", "REVIEW PROCESS, NOT JUST P&L",
        "A useful review asks whether the setup, confirmation, and risk plan "
        "were followed—not only whether the trade made money.",
        "Choose one decision to keep and one process to improve.",
        ("review", "journal", "process"),
    ),
    MorningLesson(
        "confirmation", "WAIT FOR THE SETUP YOU DEFINED",
        "Changing entry rules while a candle is moving makes it harder to assess "
        "whether the setup was actually present.",
        "Keep your confirmation criteria written and apply them consistently.",
        ("confirmation", "entry", "rules"),
    ),
    MorningLesson(
        "risk", "NO TRADE IS BETTER THAN UNDEFINED RISK",
        "If you cannot describe where the idea is wrong or how the risk is "
        "controlled, the plan is not ready.",
        "Clarify invalidation and risk before considering any entry.",
        ("risk", "invalidation", "plan"),
    ),
    MorningLesson(
        "learning", "MAKE ONE CONCEPT YOUR FOCUS",
        "Studying one concept at a time makes it easier to notice what you "
        "understand and what still needs practice.",
        "Pick one chart example and explain the concept in your own words.",
        ("learning", "practice", "education"),
    ),
)

def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def render_morning_post(
    lesson: MorningLesson,
    *,
    saturday_poll_reminder: bool = False,
) -> str:
    lines = [
        "📊 <b>SMART MONEY HUB | TRADING EDUCATION</b>",
        "",
        f"📚 <b>TODAY’S LESSON: {html.escape(lesson.title)}</b>",
        "",
        html.escape(lesson.lesson),
        "",
    ]
    if lesson.checklist:
        lines.extend(
            [
                "<b>BEFORE CONSIDERING ANY TRADE</b>",
                "",
                *(f"✅ {html.escape(item)}" for item in lesson.checklist),
            ]
        )
        if lesson.takeaway:
            lines.extend(
                [
                    "",
                    f"<b>REMEMBER:</b> {html.escape(lesson.takeaway)}",
                ]
            )
    else:
        lines.append(f"✅ <b>TRY THIS:</b> {html.escape(lesson.practice)}")
    if saturday_poll_reminder:
        lines.extend(
            [
                "",
                "🗳️ The weekly Education practice poll is scheduled for "
                "<b>9:00 PM WAT tonight</b>.",
            ]
        )
    lines.extend(
        [
            "",
            "🛡️ <b>NO CONFIRMATION, NO ENTRY.</b>",
        ]
    )
    result = "\n".join(lines)
    if _utf16_length(result) > TELEGRAM_TEXT_LIMIT_UTF16:
        raise ValueError("The morning message exceeds Telegram's text limit.")
    return result


class EducationMorningStore:
    """Small idempotency ledger; it does not share poll or channel state."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS education_morning_runs (
                    schedule_date TEXT PRIMARY KEY,
                    scheduled_at_utc TEXT NOT NULL,
                    topic TEXT,
                    content TEXT,
                    content_hash TEXT,
                    status TEXT NOT NULL CHECK (status IN (
                        'queued', 'sending', 'sent', 'failed',
                        'delivery_unknown', 'skipped'
                    )),
                    failure_category TEXT,
                    telegram_message_id INTEGER,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS education_morning_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO education_morning_settings (
                    setting_key, setting_value, updated_at_utc
                ) VALUES ('enabled', '0', '1970-01-01T00:00:00+00:00')
                """
            )

    def is_enabled(self) -> bool:
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT setting_value FROM education_morning_settings "
                "WHERE setting_key='enabled'"
            ).fetchone()
        return bool(row and str(row[0]) == "1")

    def set_enabled(self, enabled: bool, *, now: datetime | None = None) -> None:
        observed = _utc_text(now or datetime.now(timezone.utc))
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                INSERT INTO education_morning_settings (
                    setting_key, setting_value, updated_at_utc
                ) VALUES ('enabled', ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    updated_at_utc=excluded.updated_at_utc
                """,
                ("1" if enabled else "0", observed),
            )

    def get(self, schedule_date: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM education_morning_runs WHERE schedule_date=?",
                (schedule_date,),
            ).fetchone()
            return dict(row) if row else None

    def used_hashes(self) -> set[str]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            return {
                str(row[0])
                for row in connection.execute(
                    "SELECT content_hash FROM education_morning_runs "
                    "WHERE content_hash IS NOT NULL"
                ).fetchall()
            }

    def create(
        self,
        *,
        schedule_date: str,
        scheduled_at: datetime,
        topic: str | None,
        content: str | None,
        status: str,
        failure_category: str | None,
        now: datetime,
    ) -> bool:
        digest = _content_hash(content) if content else None
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO education_morning_runs (
                    schedule_date, scheduled_at_utc, topic, content, content_hash,
                    status, failure_category, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_date,
                    scheduled_at.astimezone(timezone.utc).isoformat(),
                    topic,
                    content,
                    digest,
                    status,
                    failure_category,
                    now.astimezone(timezone.utc).isoformat(),
                    now.astimezone(timezone.utc).isoformat(),
                ),
            )
            return cursor.rowcount == 1

    def reserve(self, schedule_date: str, now: datetime) -> bool:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE education_morning_runs
                SET status='sending', updated_at_utc=?
                WHERE schedule_date=? AND status='queued'
                """,
                (now.astimezone(timezone.utc).isoformat(), schedule_date),
            )
            return cursor.rowcount == 1

    def finish(
        self,
        schedule_date: str,
        *,
        status: str,
        now: datetime,
        failure_category: str | None = None,
        message_id: int | None = None,
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                UPDATE education_morning_runs
                SET status=?, failure_category=?, telegram_message_id=?,
                    updated_at_utc=?
                WHERE schedule_date=?
                """,
                (
                    status,
                    failure_category,
                    message_id,
                    now.astimezone(timezone.utc).isoformat(),
                    schedule_date,
                ),
            )


class EducationMorningPublisher:
    """Sends one professional, non-repeating morning note per WAT date."""

    def __init__(
        self,
        api: Any,
        database_path: str | Path,
        *,
        admin_id: int | None,
        education_group_id: int | None,
        group_history_store: Any | None = None,
    ) -> None:
        self.api = api
        self.store = EducationMorningStore(database_path)
        self.admin_id = admin_id
        self.education_group_id = education_group_id
        self.group_history_store = group_history_store

    def dispatch_due(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if not self.store.is_enabled():
            return
        local_now = current.astimezone(MORNING_ZONE)
        if local_now.time().replace(tzinfo=None) < MORNING_TIME:
            return

        schedule_date = local_now.date().isoformat()
        scheduled_at = datetime.combine(
            local_now.date(), MORNING_TIME, tzinfo=MORNING_ZONE
        )
        run = self.store.get(schedule_date)
        if run is None:
            if current.astimezone(timezone.utc) - scheduled_at.astimezone(
                timezone.utc
            ) > MORNING_LATE_GRACE:
                self.store.create(
                    schedule_date=schedule_date,
                    scheduled_at=scheduled_at,
                    topic=None,
                    content=None,
                    status="skipped",
                    failure_category="missed_morning_window",
                    now=current,
                )
                self._notify_admin(
                    "Today’s Education-group morning post was skipped because the "
                    "bot was unavailable more than five minutes after 8:00 AM WAT. "
                    "It was not sent late."
                )
                return
            selected = self._select_content(local_now.date())
            if selected is None:
                self.store.create(
                    schedule_date=schedule_date,
                    scheduled_at=scheduled_at,
                    topic=None,
                    content=None,
                    status="skipped",
                    failure_category="unique_content_pool_exhausted",
                    now=current,
                )
                self._notify_admin(
                    "Today’s Education-group morning post was held because all "
                    "approved message variations have already been used. Add new "
                    "learning notes before sending another unique post."
                )
                return
            lesson, content = selected
            if not self.store.create(
                schedule_date=schedule_date,
                scheduled_at=scheduled_at,
                topic=lesson.topic,
                content=content,
                status="queued",
                failure_category=None,
                now=current,
            ):
                return
            run = self.store.get(schedule_date)
        if run is None:
            return
        if run["status"] in {"sent", "failed", "delivery_unknown", "skipped"}:
            return
        if run["status"] == "sending":
            self.store.finish(
                schedule_date,
                status="delivery_unknown",
                failure_category="interrupted_during_send",
                now=current,
            )
            self._notify_admin(
                "The Education-group morning post has an uncertain delivery "
                "status after an interruption. I did not resend it."
            )
            return
        if current.astimezone(timezone.utc) - scheduled_at.astimezone(
            timezone.utc
        ) > MORNING_LATE_GRACE:
            self.store.finish(
                schedule_date,
                status="skipped",
                failure_category="missed_morning_window",
                now=current,
            )
            self._notify_admin(
                "Today’s Education-group morning post missed its five-minute "
                "delivery window and was not sent late."
            )
            return
        if not self.store.reserve(schedule_date, current):
            return
        try:
            self._verify_destination()
        except MorningPublishingError as error:
            self.store.finish(
                schedule_date,
                status="failed",
                failure_category=error.category,
                now=current,
            )
            self._notify_admin(
                "The Education-group morning post was held because destination "
                f"verification failed: {error.category}. No group message was sent."
            )
            return
        except Exception:
            self.store.finish(
                schedule_date,
                status="failed",
                failure_category="destination_verification_unavailable",
                now=current,
            )
            logger.warning("Education-group destination verification failed.")
            self._notify_admin(
                "The Education-group morning post was held because destination "
                "verification was unavailable. No group message was sent."
            )
            return
        try:
            result = self.api.send_message_with_result(
                int(self.education_group_id),
                str(run["content"]),
                parse_mode="HTML",
            )
            message_id = result.get("message_id") if isinstance(result, dict) else None
            if not isinstance(message_id, int) or message_id <= 0:
                self.store.finish(
                    schedule_date,
                    status="delivery_unknown",
                    failure_category="message_id_missing",
                    now=current,
                )
                self._notify_admin(
                    "Telegram accepted a morning-post request but returned no "
                    "message ID. Delivery is uncertain; I did not retry it."
                )
                return
            self.store.finish(
                schedule_date,
                status="sent",
                message_id=message_id,
                now=current,
            )
            self._archive_success(
                result,
                topic=str(run.get("topic") or "daily learning"),
                content=self._plain_text(str(run["content"])),
                now=current,
            )
            logger.info("Education-group morning post sent successfully.")
        except TelegramAPIError as error:
            category = (
                "telegram_delivery_unknown"
                if error.delivery_unknown
                else f"telegram_rejected_{error.error_code or error.http_status or 'error'}"
            )
            status = "delivery_unknown" if error.delivery_unknown else "failed"
            self.store.finish(
                schedule_date,
                status=status,
                failure_category=category,
                now=current,
            )
            self._notify_admin(
                "The Education-group morning post was not confirmed as delivered. "
                f"Failure category: {category}. It will not be retried automatically."
            )
        except Exception:
            self.store.finish(
                schedule_date,
                status="delivery_unknown",
                failure_category="unexpected_send_error",
                now=current,
            )
            logger.exception(
                "Education-group morning send has an uncertain delivery state."
            )
            self._notify_admin(
                "The Education-group morning post has an uncertain delivery "
                "status. It was not retried to prevent a duplicate."
            )

    def _select_content(
        self, scheduled_date: date
    ) -> tuple[MorningLesson, str] | None:
        used = self.store.used_hashes()
        recent_text = self._recent_group_text(scheduled_date)
        total = len(MORNING_LESSONS)
        offset = scheduled_date.toordinal() % max(total, 1)
        lessons = [
            MORNING_LESSONS[(offset + step) % total]
            for step in range(total)
        ]
        for lesson in lessons:
            if any(keyword.casefold() in recent_text for keyword in lesson.keywords):
                continue
            content = render_morning_post(
                lesson,
                saturday_poll_reminder=scheduled_date.weekday() == 5,
            )
            digest = _content_hash(content)
            if digest not in used:
                return lesson, content
        # Prefer a unique post over a duplicate if every topic was recently
        # covered; the per-run hash still prevents any exact repeated message.
        for lesson in lessons:
            content = render_morning_post(
                lesson,
                saturday_poll_reminder=scheduled_date.weekday() == 5,
            )
            if _content_hash(content) not in used:
                return lesson, content
        return None

    def _recent_group_text(self, scheduled_date: date) -> str:
        if self.group_history_store is None:
            return ""
        cutoff = datetime.combine(
            scheduled_date - timedelta(days=14), time.min, tzinfo=MORNING_ZONE
        ).astimezone(timezone.utc).isoformat()
        try:
            records = self.group_history_store.recent_education_group_posts(
                int(self.education_group_id),
                since=cutoff,
                limit=30,
            )
            polls = self.group_history_store.recent_education_poll_runs(
                since=cutoff,
                limit=12,
            )
        except Exception:
            logger.warning("Could not read the bounded Education-group archive.")
            return ""
        recent_content = [str(row.get("content") or "") for row in records]
        for poll in polls:
            try:
                scenario_index = int(poll["scenario_index"])
                recent_content.append(SCENARIO_POLLS[scenario_index].question)
            except (KeyError, TypeError, ValueError, IndexError):
                continue
        return " ".join(recent_content).casefold()

    def _verify_destination(self) -> None:
        if self.education_group_id != EXPECTED_EDUCATION_GROUP_ID:
            raise MorningPublishingError("destination_id_mismatch")
        try:
            bot = self.api.get_me()
        except TelegramAPIError:
            raise MorningPublishingError("bot_identity_unavailable") from None
        except Exception:
            raise MorningPublishingError("bot_identity_unavailable") from None
        bot_id = bot.get("id") if isinstance(bot, dict) else None
        if not isinstance(bot_id, int) or bot_id <= 0:
            raise MorningPublishingError("bot_identity_unavailable")
        try:
            group = self.api.get_chat(int(self.education_group_id))
        except TelegramAPIError:
            raise MorningPublishingError(
                "destination_verification_unavailable"
            ) from None
        except Exception:
            raise MorningPublishingError(
                "destination_verification_unavailable"
            ) from None
        if not isinstance(group, dict):
            raise MorningPublishingError("destination_not_verified")
        title = " ".join(str(group.get("title") or "").split()).casefold()
        if (
            group.get("id") != self.education_group_id
            or group.get("type") != "supergroup"
            or "pro signals" in title
            or re.search(r"\b(?:test|testing|sandbox)\b", title)
        ):
            raise MorningPublishingError("destination_not_verified")
        try:
            member = self.api.get_chat_member(
                int(self.education_group_id), bot_id
            )
        except TelegramAPIError:
            raise MorningPublishingError(
                "posting_permission_verification_unavailable"
            ) from None
        except Exception:
            raise MorningPublishingError(
                "posting_permission_verification_unavailable"
            ) from None
        if not isinstance(member, dict) or member.get("status") not in {
            "administrator", "creator"
        }:
            raise MorningPublishingError("posting_permission_missing")

    def _archive_success(
        self,
        result: dict[str, Any],
        *,
        topic: str,
        content: str,
        now: datetime,
    ) -> None:
        if self.group_history_store is None:
            return
        try:
            self.group_history_store.record_education_group_post(
                chat_id=int(self.education_group_id),
                message_id=int(result["message_id"]),
                thread_id=None,
                topic_name=topic,
                message_kind="text",
                content=content,
                source_status="bot_authored",
                posted_at=now.astimezone(timezone.utc).isoformat(),
            )
        except Exception:
            logger.warning("Could not archive the sent Education-group morning post.")

    @staticmethod
    def _plain_text(value: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", value))

    def _notify_admin(self, message: str) -> None:
        if self.admin_id is None:
            logger.error("Education-group morning post needs admin attention.")
            return
        try:
            self.api.send_message(self.admin_id, message)
        except Exception:
            logger.error("Could not notify admin about Education-group morning post.")
