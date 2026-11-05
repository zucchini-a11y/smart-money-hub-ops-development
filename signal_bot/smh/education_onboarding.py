"""Persisted, membership-gated Education orientation and lesson progression."""
import asyncio
import json
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .database import now


_KEY_PREFIX = "education:onboarding:"
_LAGOS = ZoneInfo("Africa/Lagos")
_DAY1_HEADING = "📚 <b>SMART MONEY HUB | DAY 1: EDUCATION ORIENTATION</b>\n\n"
_EPISODE_01_ASSIGNMENT = (
    "Open your Gold (XAUUSD) chart and:\n"
    "1. Choose one timeframe.\n"
    "2. Identify whether the market is bullish, bearish or ranging.\n"
    "3. Mark at least two significant swing highs.\n"
    "4. Mark at least two significant swing lows.\n"
    "5. Explain how the sequence of these swings supports your conclusion.\n\n"
    "Submit your completed assignment privately."
)

def _day2_schedule_text(mode):
    if mode == "online":
        return "Episode 01 will be delivered when Bot 1 is online."
    return f"Episode 01 is scheduled for {mode} Africa/Lagos time."


def _day1_text(demo_account_url, coach_bot_url="", day2_mode="online"):
    return (
        _DAY1_HEADING +
        "Welcome to Smart Money Hub! 🚀\n\n"
        "You’re beginning a structured learning journey designed to help you understand the financial markets, "
        "develop your analysis skills and become an independent trader.\n\n"
        "📍 <b>WHERE LEARNING HAPPENS</b>\n\n"
        "• <b>Education Group:</b> Your learning space for lessons and educational resources. "
        "Follow the lessons in the correct order.\n\n"
        "• <b>Education Announcements:</b> Stay updated with official course announcements and important information.\n\n"
        "• <b>Demo Account Guide:</b> Use the guide if you need help setting up a demo account for practice.\n\n"
        "🎯 <b>HOW TO LEARN</b>\n\n"
        "• Study each lesson and its provided resources before moving forward.\n"
        "• Complete assignments whenever they are given.\n"
        "• Take quizzes when they are included in a lesson.\n"
        "• Ask questions whenever something is unclear.\n"
        "• Practise what you learn without rushing the process.\n\n"
        "🛡️ <b>RISK &amp; TRADING PRINCIPLES</b>\n\n"
        "Always protect your capital. No trading setup is guaranteed to make a profit.\n\n"
        "<b>Remember:</b>\n"
        "• A Point of Interest (POI) is an area of interest, not an automatic entry.\n"
        "• Never chase price or force a trade.\n"
        "• Patience and risk management are essential.\n\n"
        "❌ <b>NO CONFIRMATION, NO ENTRY.</b>\n\n"
        "📅 <b>WHAT HAPPENS NEXT?</b>\n\n"
        "Today is strictly for orientation. There is no technical trading lesson today.\n\n"
        "<b>Tomorrow — Day 2: Episode 01 | Understanding Market Structure</b>\n\n"
        "You’ll learn to identify whether the market is bullish, bearish or ranging by studying swing highs and swing lows.\n"
        f"{_day2_schedule_text(day2_mode)}\n\n"
        "Your learning progress matters. Take your time, understand each topic and complete the tasks provided.\n\n"
        "Welcome aboard! Let’s build independent traders, one lesson at a time. 🚀\n\n"
        "<b>SMART MONEY HUB — Learn. Understand. Execute with discipline.</b>"
    )


def _episode_01_text(coach_bot_url="", video_url=""):
    study_video = (
        "Watch the Market Structure video carefully and study the examples before attempting the assignment.\n\n"
        if video_url else ""
    )
    return (
        "📘 <b>SMART MONEY HUB | DAY 2: EPISODE 01</b>\n\n"
        "<b>UNDERSTANDING MARKET STRUCTURE</b>\n\n"
        "🎯 <b>LEARNING OBJECTIVE</b>\n\n"
        "Learn to identify whether the market is bullish, bearish or ranging by studying significant swing highs and swing lows.\n\n"
        "📖 <b>LESSON INTRODUCTION</b>\n\n"
        "Market structure describes how price moves by forming swing highs and swing lows over time.\n\n"
        "To understand market direction, you must study the sequence of these swings rather than relying on individual candles.\n\n"
        "A single green or red candle does not determine the market’s direction. What matters is how price develops its structure over time.\n\n"
        "🎥 <b>STUDY MATERIAL</b>\n\n"
        "Open the existing Episode 01: Understanding Market Structure lesson in the Education Group.\n\n"
        f"{study_video}"
        "📝 <b>PRACTICAL ASSIGNMENT</b>\n\n"
        f"{_EPISODE_01_ASSIGNMENT}\n\n"
        "IMPORTANT: Don’t rush into finding trade entries. Before learning when to enter, you must first understand how to read the chart.\n\n"
        "❌ <b>NO CONFIRMATION, NO ENTRY.</b>\n\n"
        "Take your time. Focus on understanding the structure, not just completing the assignment.\n\n"
        "🚀 <b>SMART MONEY HUB — Building independent traders, one lesson at a time.</b>"
    )


def _episode_02_text():
    return (
        "📘 <b>SMART MONEY HUB | DAY 3: EPISODE 02</b>\n\n"
        "<b>BREAK OF STRUCTURE (BOS) &amp; CHANGE OF CHARACTER (CHoCH)</b>\n\n"
        "🎯 <b>LEARNING OBJECTIVE</b>\n\n"
        "Learn to describe a break with the existing market structure and a possible break against it.\n\n"
        "🎥 <b>STUDY MATERIAL</b>\n\n"
        "Study the Episode 02 PDF and watch the lesson video. Complete the practice explained in the lesson.\n\n"
        "BOS and CHoCH describe price structure; neither guarantees what price will do next or gives "
        "permission to enter a trade.\n\n"
        "❌ <b>NO CONFIRMATION, NO ENTRY.</b>"
    )


def _key(user_id):
    return _KEY_PREFIX + str(int(user_id))


def _read(db, user_id):
    value = db.get(_key(user_id))
    return value if isinstance(value, dict) else None


def _write(db, user_id, progress):
    db.put(_key(user_id), progress)


def _atomic_update(db, user_id, update):
    """Compare-and-swap learner state so concurrent taps/workers cannot clobber progress."""
    key = _key(user_id)
    with db.transaction() as conn:
        for _ in range(3):
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            if not row:
                return None
            previous = row["value"]
            progress = json.loads(previous)
            if update(progress) is False:
                return progress
            progress["updated_at"] = now()
            result = conn.execute(
                "UPDATE kv SET value=? WHERE key=? AND value=?",
                (json.dumps(progress, ensure_ascii=False), key, previous),
            )
            if result.rowcount == 1:
                return progress
    return _read(db, user_id)


def _next_day2_due(day1_sent_at, mode):
    sent_at = datetime.fromisoformat(day1_sent_at)
    local = sent_at.astimezone(_LAGOS)
    if mode == "online":
        scheduled_time = time.min
    else:
        hour, minute = (int(piece) for piece in mode.split(":"))
        scheduled_time = time(hour, minute)
    next_local_day = datetime.combine(local.date() + timedelta(days=1), scheduled_time, _LAGOS)
    return next_local_day.astimezone(timezone.utc).isoformat(timespec="seconds")


def _eligible_member(member):
    status = getattr(member, "status", "")
    return status in ("member", "administrator", "creator") or (
        status == "restricted" and bool(getattr(member, "is_member", False))
    )


class EducationOnboardingFlows:
    def _education_enabled(self):
        return bool(getattr(self.config, "education_onboarding_enabled", False))

    def _authorize_education_preview(self, update):
        if (update.effective_chat.type != "private"
                or update.effective_user.id != getattr(self.config, "admin", None)):
            raise PermissionError("This preview is available to the administrator in a private chat only.")
        if not getattr(self.config, "isolated_test", False):
            raise PermissionError("Education message previews are available only in the isolated test bot.")

    async def education_onboarding_preview(self, update):
        self._authorize_education_preview(update)
        chat_id = update.effective_chat.id
        if not self.config.education_episode_01_url:
            return await self._education_reply(chat_id, "The Episode 01 lesson link is not configured.")

        await self._education_reply(
            chat_id,
            _day1_text(
                self.config.education_demo_account_url,
                getattr(self.config, "education_coach_bot_url", ""),
                getattr(self.config, "education_day2_mode", "online"),
            ),
            self._day1_buttons(),
        )
        await self._education_reply(
            chat_id,
            _episode_01_text(
                getattr(self.config, "education_coach_bot_url", ""),
                getattr(self.config, "education_market_structure_video_url", ""),
            ),
            self._day2_preview_buttons(),
        )
        if (getattr(self.config, "education_episode_02_video_url", "")
                or getattr(self.config, "education_episode_02_pdf_url", "")):
            await self._education_reply(
                chat_id,
                _episode_02_text(),
                self._day3_buttons(),
            )

    def _day1_buttons(self):
        buttons = []
        education_link = getattr(self.config, "education_link", "")
        if education_link:
            buttons.append([("Education access link", "url", education_link)])
        if self.config.education_demo_account_url:
            buttons.append(
                [("How to open a demo account", "url", self.config.education_demo_account_url)]
            )
        if self.config.education_announcement_url:
            buttons.append(
                [("Open Education announcements", "url", self.config.education_announcement_url)]
            )
        coach_url = getattr(self.config, "education_coach_bot_url", "")
        if coach_url:
            buttons.append([("Open Smart Money Hub Coach", "url", coach_url)])
        return buttons or None

    def _day2_preview_buttons(self):
        buttons = [[("Open Episode 01", "url", self.config.education_episode_01_url)]]
        video_url = getattr(self.config, "education_market_structure_video_url", "")
        if video_url:
            buttons.append([("Watch Market Structure video", "url", video_url)])
        coach_url = getattr(self.config, "education_coach_bot_url", "")
        if coach_url:
            buttons.append([("Open Smart Money Hub Coach", "url", coach_url)])
        buttons.append([("Submit Episode 01 assignment", "admin_education_preview_assignment", {})])
        return buttons

    def _day3_buttons(self):
        buttons = []
        video_url = getattr(self.config, "education_episode_02_video_url", "")
        if video_url:
            buttons.append([("Watch Episode 02 video", "url", video_url)])
        pdf_url = getattr(self.config, "education_episode_02_pdf_url", "")
        if pdf_url:
            buttons.append([("Open Episode 02 PDF", "url", pdf_url)])
        coach_url = getattr(self.config, "education_coach_bot_url", "")
        if coach_url:
            buttons.append([("Open Smart Money Hub Coach", "url", coach_url)])
        return buttons or None

    async def education_onboarding_preview_assignment(self, update):
        self._authorize_education_preview(update)
        await self._education_reply(
            update.effective_chat.id,
            "Send your Episode 01 assignment as a text message in this private chat. "
            "In the learner flow, this prompt appears after the lesson is delivered and "
            "Education Group membership is verified."
        )

    async def _education_member_verified(self, user_id):
        if not self.config.education_group_id:
            return False
        member = await self.bot.get_chat_member(self.config.education_group_id, user_id)
        return _eligible_member(member)

    async def _education_reply(self, chat_id, text, buttons=None):
        rows = [[InlineKeyboardButton(label, url=data) if action == "url"
                 else self.button(chat_id, label, action, data)
                 for label, action, data in row] for row in (buttons or [])]
        # A learner's Telegram ID is also the private-chat ID, and actions remain recipient-bound.
        markup = InlineKeyboardMarkup(rows) if rows else None
        await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup)

    def _education_begin_state(self, user_id):
        key = _key(user_id)
        progress = _read(self.db, user_id)
        if progress:
            updated = _atomic_update(self.db, user_id, lambda state: state.update({"initiated": True}))
            return updated or progress
        stamp = now()
        progress = {
            "version": 1,
            "user_id": int(user_id),
            "initiated": True,
            "started_at": stamp,
            "updated_at": stamp,
            "member_verified_at": None,
            "day1_status": "pending",
            "day2_status": "waiting_for_day1",
            "day2_due_at": None,
            "episode1_status": "locked",
            "assignment_status": "not_started",
            "assignment_text": None,
            "assignment_submitted_at": None,
            "day3_status": "locked",
            "day3_due_at": None,
            "episode2_status": "locked",
        }
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO kv (key,value) VALUES (?,?)",
                (key, json.dumps(progress, ensure_ascii=False)),
            )
        return _read(self.db, user_id) or progress

    def _education_mark_verified(self, user_id):
        def update(progress):
            progress["member_verified_at"] = now()
            if progress.get("day2_status") == "awaiting_membership":
                progress["day2_status"] = "pending"
            if progress.get("day3_status") == "awaiting_membership":
                progress["day3_status"] = "pending"
            return True
        return _atomic_update(self.db, user_id, update)

    async def education_onboarding_action(self, update, action):
        if update.effective_chat.type != "private":
            return
        user_id = update.effective_user.id
        if not self._education_enabled():
            return await self._education_reply(
                update.effective_chat.id,
                "Education onboarding is not enabled in this environment.",
            )
        if not self.config.education_group_id or not self.config.education_link:
            return await self._education_reply(
                update.effective_chat.id,
                "Education access is not fully configured. Please contact an administrator.",
            )

        if action == "education_onboarding_start":
            self._education_begin_state(user_id)
        elif not (_read(self.db, user_id) or {}).get("initiated"):
            return await self._education_reply(
                update.effective_chat.id,
                "Start Education from the member access menu before checking membership or submitting work.",
            )

        if action == "education_onboarding_assignment":
            return await self._education_begin_assignment(update, user_id)

        try:
            verified = await self._education_member_verified(user_id)
        except Exception:
            return await self._education_reply(
                update.effective_chat.id,
                "I couldn’t verify your Education Group membership right now. Please try again shortly.",
            )
        if not verified:
            return await self._education_reply(
                update.effective_chat.id,
                "Join the private Education Group, then tap <b>Check membership</b> here to begin.",
                [[("Join Educational Group", "url", self.config.education_link)],
                 [("Check membership", "education_onboarding_check", {})]],
            )

        progress = self._education_mark_verified(user_id)
        if progress and progress.get("day1_status") == "sent":
            if progress.get("day3_status") == "sent":
                status_text = "Your Education progress is saved. Day 3: Episode 02 is open."
            elif progress.get("day3_status") == "uncertain":
                status_text = "Your progress is saved, but Episode 02 delivery could not be confirmed. It was not automatically retried."
            elif progress.get("day3_status") == "awaiting_membership":
                status_text = "Your progress is saved. Episode 02 is paused until Education Group membership is verified again."
            elif progress.get("day3_status") == "pending":
                status_text = "Your Episode 01 assignment is received. Day 3: Episode 02 is scheduled for the next Lagos day."
            elif progress.get("day2_status") == "sent":
                status_text = "Your Education progress is saved. Episode 01 is open; submit its assignment here when ready."
            elif progress.get("day2_status") == "uncertain":
                status_text = "Your progress is saved, but Episode 01 delivery could not be confirmed. It was not automatically retried."
            elif progress.get("day2_status") == "awaiting_membership":
                status_text = "Your progress is saved. Episode 01 is paused until Education Group membership is verified again."
            else:
                status_text = "Your Education progress is saved. Episode 01 is scheduled for Day 2."
            return await self._education_reply(
                update.effective_chat.id,
                status_text,
                [[("Open Education announcements", "url", self.config.education_announcement_url)]]
                if self.config.education_announcement_url else None,
            )
        await self._education_send_day1(user_id)

    async def _education_send_day1(self, user_id):
        def claim(progress):
            if not progress.get("initiated") or progress.get("day1_status") != "pending":
                return False
            progress["day1_status"] = "sending"
            return True
        claimed = _atomic_update(self.db, user_id, claim)
        if not claimed or claimed.get("day1_status") != "sending":
            return False
        try:
            await self._education_reply(
                user_id,
                _day1_text(
                    self.config.education_demo_account_url,
                    getattr(self.config, "education_coach_bot_url", ""),
                    getattr(self.config, "education_day2_mode", "online"),
                ),
                self._day1_buttons(),
            )
        except Exception:
            _atomic_update(self.db, user_id, lambda p: p.update({"day1_status": "uncertain"}))
            self.db.error("education_onboarding_day1_uncertain",
                          "Education orientation delivery is uncertain; it was not automatically retried.")
            return False
        sent_at = now()
        def mark_sent(progress):
            if progress.get("day1_status") != "sending":
                return False
            progress["day1_status"] = "sent"
            progress["day1_sent_at"] = sent_at
            progress["day2_due_at"] = _next_day2_due(
                sent_at, getattr(self.config, "education_day2_mode", "online"))
            progress["day2_status"] = "pending"
            progress["episode1_status"] = "scheduled"
            return True
        _atomic_update(self.db, user_id, mark_sent)
        return True

    async def _education_begin_assignment(self, update, user_id):
        progress = _read(self.db, user_id) or {}
        if progress.get("assignment_status") in ("submitted", "complete"):
            return await self._education_reply(
                update.effective_chat.id,
                "Your Episode 01 assignment has already been received. Your progress is saved.",
            )
        if progress.get("day2_status") != "sent" or progress.get("episode1_status") != "in_progress":
            return await self._education_reply(
                update.effective_chat.id,
                "Episode 01 is not ready for assignment submission yet.",
            )
        try:
            if not await self._education_member_verified(user_id):
                return await self._education_reply(
                    update.effective_chat.id,
                    "Your Education Group membership could not be confirmed. Rejoin before submitting the assignment.",
                )
        except Exception:
            return await self._education_reply(
                update.effective_chat.id,
                "I couldn’t verify your Education Group membership. Please try again shortly.",
            )
        def awaiting(progress):
            if progress.get("assignment_status") in ("submitted", "complete"):
                return False
            progress["assignment_status"] = "awaiting_submission"
            return True
        updated = _atomic_update(self.db, user_id, awaiting)
        if not updated or updated.get("assignment_status") != "awaiting_submission":
            return await self._education_reply(
                update.effective_chat.id,
                "Your Episode 01 assignment has already been received. Your progress is saved.",
            )
        return await self._education_reply(
            update.effective_chat.id,
            "Send your Episode 01 assignment as a text message in this private chat.",
        )

    async def education_onboarding_handle_text(self, update, text):
        if not self._education_enabled() or update.effective_chat.type != "private":
            return False
        user_id = update.effective_user.id
        progress = _read(self.db, user_id)
        if not progress or progress.get("assignment_status") != "awaiting_submission":
            return False
        answer = (text or "").strip()
        if not answer:
            await self._education_reply(update.effective_chat.id, "Please send your assignment as text.")
            return True
        if len(answer) > 4000:
            await self._education_reply(update.effective_chat.id, "Please keep the assignment under 4,000 characters.")
            return True
        try:
            verified = await self._education_member_verified(user_id)
        except Exception:
            await self._education_reply(
                update.effective_chat.id,
                "I couldn’t verify your Education Group membership. Please try again shortly.",
            )
            return True
        if not verified:
            _atomic_update(self.db, user_id, lambda p: p.update({"day2_status": "awaiting_membership"}))
            await self._education_reply(
                update.effective_chat.id,
                "Your Education Group membership is not active. Rejoin, then check membership before submitting.",
            )
            return True

        def submit(progress):
            if progress.get("assignment_status") != "awaiting_submission":
                return False
            progress["assignment_text"] = answer
            progress["assignment_status"] = "submitted"
            progress["assignment_submitted_at"] = now()
            progress["episode1_status"] = "assignment_submitted"
            if getattr(self.config, "education_episode_02_video_url", ""):
                progress["day3_status"] = "pending"
                progress["day3_due_at"] = _next_day2_due(
                    progress["assignment_submitted_at"],
                    getattr(self.config, "education_day2_mode", "online"),
                )
                progress["episode2_status"] = "scheduled"
            return True
        updated = _atomic_update(self.db, user_id, submit)
        if updated and updated.get("assignment_status") == "submitted":
            if updated.get("day3_status") == "pending":
                confirmation = (
                    "✅ Episode 01 assignment received. Your progress is saved. "
                    "Day 3: Episode 02 is scheduled for the next Lagos day."
                )
            else:
                confirmation = (
                    "✅ Episode 01 assignment received. Your progress is saved. "
                    "Episode 02 is not configured yet, so I haven’t sent or invented another lesson."
                )
            await self._education_reply(
                update.effective_chat.id,
                confirmation,
            )
        else:
            await self._education_reply(update.effective_chat.id, "Your assignment was already received.")
        return True

    async def education_onboarding_membership_changed(self, user_id, status):
        if not self._education_enabled():
            return
        progress = _read(self.db, user_id)
        if not progress or not progress.get("initiated"):
            return
        if status not in ("member", "administrator", "creator") and status != "restricted":
            def pause(state):
                state["member_verified_at"] = None
                if state.get("day2_status") == "pending":
                    state["day2_status"] = "awaiting_membership"
                if state.get("day3_status") == "pending":
                    state["day3_status"] = "awaiting_membership"
                return True
            _atomic_update(self.db, user_id, pause)
            return
        try:
            verified = await self._education_member_verified(user_id)
        except Exception:
            return
        if not verified:
            return
        self._education_mark_verified(user_id)
        if progress.get("day1_status") == "pending":
            await self._education_send_day1(user_id)


def recover_education_onboarding(db):
    """Quarantine deliveries interrupted by a process restart; never replay uncertain DMs."""
    rows = db.rows("SELECT key,value FROM kv WHERE key LIKE ?", (_KEY_PREFIX + "%",))
    recovered = 0
    for row in rows:
        progress = json.loads(row["value"])
        changed = False
        for field in ("day1_status", "day2_status", "day3_status"):
            if progress.get(field) == "sending":
                progress[field] = "uncertain"
                changed = True
        if changed:
            progress["updated_at"] = now()
            db.put(row["key"], progress)
            recovered += 1
    if recovered:
        db.error(
            "education_onboarding_uncertain",
            f"Quarantined {recovered} interrupted Education delivery record(s); none were retried.",
        )
    return recovered


async def process_education_onboarding_once(db, bot, config, *, now_override=None):
    if not getattr(config, "education_onboarding_enabled", False) or not config.education_group_id:
        return False
    current = datetime.fromisoformat(now_override) if now_override else datetime.now(timezone.utc)
    rows = db.rows("SELECT key,value FROM kv WHERE key LIKE ?", (_KEY_PREFIX + "%",))
    for row in rows:
        progress = json.loads(row["value"])
        due = progress.get("day2_due_at")
        if (progress.get("initiated") and progress.get("day1_status") == "sent"
                and progress.get("day2_status") == "pending" and due
                and datetime.fromisoformat(due) <= current):
            user_id = int(progress["user_id"])
            try:
                member = await bot.get_chat_member(config.education_group_id, user_id)
            except Exception:
                db.error("education_onboarding_membership_check",
                         "Education membership could not be verified; Day 2 was not sent.")
                continue
            if not _eligible_member(member):
                _atomic_update(db, user_id, lambda state: state.update({"day2_status": "awaiting_membership"}))
                continue

            def claim_day2(state):
                if state.get("day2_status") != "pending" or state.get("day1_status") != "sent":
                    return False
                state["day2_status"] = "sending"
                return True
            claimed = _atomic_update(db, user_id, claim_day2)
            if not claimed or claimed.get("day2_status") != "sending":
                continue
            keyboard = [[InlineKeyboardButton("Open Episode 01", url=config.education_episode_01_url)]]
            video_url = getattr(config, "education_market_structure_video_url", "")
            if video_url:
                keyboard.append([InlineKeyboardButton("Watch Market Structure video", url=video_url)])
            coach_url = getattr(config, "education_coach_bot_url", "")
            if coach_url:
                keyboard.append([InlineKeyboardButton("Open Smart Money Hub Coach", url=coach_url)])
            keyboard.append([InlineKeyboardButton("Submit Episode 01 assignment",
                                                  callback_data=bot_data_button(db, user_id))])
            markup = InlineKeyboardMarkup(keyboard)
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=_episode_01_text(coach_url, video_url),
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            except Exception:
                _atomic_update(db, user_id, lambda state: state.update({"day2_status": "uncertain"}))
                db.error("education_onboarding_day2_uncertain",
                         "Episode 01 delivery is uncertain; it was not automatically retried.")
                return True
            def sent_day2(state):
                if state.get("day2_status") != "sending":
                    return False
                state["day2_status"] = "sent"
                state["day2_sent_at"] = now()
                state["episode1_status"] = "in_progress"
                return True
            _atomic_update(db, user_id, sent_day2)
            return True

        due_day3 = progress.get("day3_due_at")
        if (not progress.get("initiated") or progress.get("assignment_status") != "submitted"
                or progress.get("day3_status") != "pending" or not due_day3
                or datetime.fromisoformat(due_day3) > current
                or not getattr(config, "education_episode_02_video_url", "")
                or not getattr(config, "education_episode_02_pdf_url", "")):
            continue
        user_id = int(progress["user_id"])
        try:
            member = await bot.get_chat_member(config.education_group_id, user_id)
        except Exception:
            db.error("education_onboarding_membership_check",
                     "Education membership could not be verified; Day 3 was not sent.")
            continue
        if not _eligible_member(member):
            _atomic_update(db, user_id, lambda state: state.update({"day3_status": "awaiting_membership"}))
            continue

        def claim_day3(state):
            if (state.get("day3_status") != "pending"
                    or state.get("assignment_status") != "submitted"):
                return False
            state["day3_status"] = "sending"
            return True
        claimed = _atomic_update(db, user_id, claim_day3)
        if not claimed or claimed.get("day3_status") != "sending":
            continue
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Watch Episode 02 video",
                url=config.education_episode_02_video_url,
            )],
            [InlineKeyboardButton(
                "Open Episode 02 PDF",
                url=config.education_episode_02_pdf_url,
            )],
        ])
        try:
            await bot.send_message(
                chat_id=user_id,
                text=_episode_02_text(),
                parse_mode="HTML",
                reply_markup=markup,
            )
        except Exception:
            _atomic_update(db, user_id, lambda state: state.update({"day3_status": "uncertain"}))
            db.error("education_onboarding_day3_uncertain",
                     "Episode 02 delivery is uncertain; it was not automatically retried.")
            return True
        def sent_day3(state):
            if state.get("day3_status") != "sending":
                return False
            state["day3_status"] = "sent"
            state["day3_sent_at"] = now()
            state["episode2_status"] = "in_progress"
            return True
        _atomic_update(db, user_id, sent_day3)
        return True
    return False


def bot_data_button(db, user_id):
    # Callback data remains short, opaque, expiring, and bound to this learner.
    return db.button(user_id, "education_onboarding_assignment", {})


async def run_education_onboarding_worker(db, bot, config, stop_event, interval=30):
    while not stop_event.is_set():
        try:
            worked = await process_education_onboarding_once(db, bot, config)
        except Exception:
            logging.getLogger("smh").error("education_onboarding_worker_failed")
            try:
                db.error("education_onboarding_worker",
                         "The Education worker failed safely; learner delivery state was preserved.")
            except Exception:
                pass
            worked = False
        if worked:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
