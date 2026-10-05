"""Private, Telegram-ID-gated admin dashboard for member reporting."""

from datetime import datetime, timedelta, timezone
from typing import Any

from .storage import Repository
from .telegram_api import TelegramAPI

ADMIN_RECENT_CHECKIN_DAYS = 14
ADMIN_LOW_SCORE_THRESHOLD = 60
ADMIN_PAGE_SIZE = 8


class AdminDashboard:
    def __init__(
        self, api: TelegramAPI, store: Repository, admin_id: int | None
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self._search_pending: set[int] = set()

    def search_is_pending(self, telegram_id: int) -> bool:
        return telegram_id in self._search_pending

    def cancel_search(self, telegram_id: int) -> None:
        self._search_pending.discard(telegram_id)

    def open(self, chat_id: int, telegram_id: int, is_private: bool) -> None:
        if self._authorize(chat_id, telegram_id, is_private):
            self._show_dashboard(chat_id)

    def handle_search_message(
        self, chat_id: int, telegram_id: int, is_private: bool, query: str
    ) -> None:
        if not self._authorize(chat_id, telegram_id, is_private):
            self.cancel_search(telegram_id)
            return
        self.cancel_search(telegram_id)
        results = self.store.search_admin_members(query, limit=10)
        if not results:
            self.api.send_message(
                chat_id,
                "No member matched that ID, username, or first name.",
                self._admin_navigation(
                    [[{"text": "🔍 Search Member", "callback_data": "admin:search"}]]
                ),
            )
            return
        rows = [
            [
                {
                    "text": self._member_label(member),
                    "callback_data": f"admin:member:{member['telegram_id']}",
                }
            ]
            for member in results
        ]
        self.api.send_message(
            chat_id,
            f"Search results ({len(results)}). Select a member to view their progress.",
            self._admin_navigation(rows),
        )

    def handle_callback(
        self, chat_id: int, telegram_id: int, is_private: bool, data: str
    ) -> None:
        if not self._authorize(chat_id, telegram_id, is_private):
            return
        if data != "admin:search":
            self.cancel_search(telegram_id)

        if data in {"admin:open", "admin:home"}:
            self._show_dashboard(chat_id)
        elif data == "admin:members":
            self._show_members(chat_id, page=0, sort="joined")
        elif data.startswith("admin:members:"):
            self._show_members(chat_id, page=self._page(data), sort="joined")
        elif data == "admin:statistics":
            self._show_statistics(chat_id)
        elif data == "admin:dm_coach":
            self._show_dm_coach_stats(chat_id)
        elif data == "admin:weak_topics":
            self._show_weak_topics(chat_id)
        elif data == "admin:trade_journals":
            self._show_trade_journals(chat_id, page=0)
        elif data.startswith("admin:trade_journals:"):
            self._show_trade_journals(chat_id, page=self._page(data))
        elif data == "admin:search":
            self._search_pending.add(telegram_id)
            self.api.send_message(
                chat_id,
                "Send a member's Telegram ID, username, or first name. Send /cancel to return.",
                self._admin_navigation(),
            )
        elif data == "admin:progress":
            self._show_members(chat_id, page=0, sort="progress")
        elif data.startswith("admin:progress:page:"):
            self._show_members(
                chat_id, page=self._page(data), sort="progress"
            )
        elif data.startswith("admin:member_history:"):
            self._show_member_history(chat_id, data)
        elif data.startswith("admin:member_trades:"):
            self._show_member_trades(chat_id, data)
        elif data.startswith("admin:member:"):
            self._show_member_detail(chat_id, self._integer_suffix(data))
        elif data.startswith("admin:trade:"):
            self._show_trade_detail(chat_id, self._integer_suffix(data))
        else:
            self.api.send_message(
                chat_id,
                "That dashboard option is no longer active.",
                self._dashboard_keyboard(),
            )

    def _authorize(self, chat_id: int, telegram_id: int, is_private: bool) -> bool:
        if self.admin_id is None:
            self.api.send_message(
                chat_id,
                "Admin access is not configured. Send /myid and add your numeric ID "
                "as the Replit Secret ADMIN_TELEGRAM_ID.",
                self._basic_navigation(),
            )
            return False
        if telegram_id != self.admin_id:
            self.api.send_message(
                chat_id,
                "Admin access is restricted.",
                self._basic_navigation(),
            )
            return False
        if not is_private:
            self.api.send_message(
                chat_id,
                "For member privacy, open a private chat with this bot and send /admin there.",
                self._basic_navigation(),
            )
            return False
        return True

    def _dashboard_data(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return self.store.admin_dashboard_data(
            (now - timedelta(days=7)).isoformat(timespec="seconds"),
            (now - timedelta(days=ADMIN_RECENT_CHECKIN_DAYS)).isoformat(
                timespec="seconds"
            ),
            low_score_below=ADMIN_LOW_SCORE_THRESHOLD,
        )

    def _show_dashboard(self, chat_id: int) -> None:
        stats = self._dashboard_data()
        coach_stats = self.store.admin_dm_coach_stats()
        average = stats["average_score"]
        lines = [
            "SMART MONEY HUB — ADMIN DASHBOARD",
            f"Total registered members: {stats['total_members']}",
            f"Members active this week: {stats['active_this_week']}",
            f"Members who completed assessments: {stats['assessed_members']}",
            f"Average assessment score: {self._percentage(average)}",
            (
                f"Latest score below {ADMIN_LOW_SCORE_THRESHOLD}%: "
                f"{stats['low_score_members']} members"
            ),
            f"Trades journaled: {stats['trades_journaled']}",
            f"Members using DM Coach: {coach_stats['members_using_coach']}",
            (
                f"No check-in in the last {ADMIN_RECENT_CHECKIN_DAYS} days: "
                f"{stats['no_recent_checkin']} members"
            ),
            "\nTop-performing members (average score):",
        ]
        if stats["top_members"]:
            lines.extend(
                f"• {self._member_label(member)} — {member['average_score']}%"
                for member in stats["top_members"][:3]
            )
        else:
            lines.append("• No assessment data yet")
        lines.append("\nMost common weak topics:")
        if stats["weak_topics"]:
            lines.extend(
                f"• {topic['topic']} — {topic['accuracy']}% accuracy"
                for topic in stats["weak_topics"][:3]
            )
        else:
            lines.append("• No detailed assessment answers yet")
        lines.append("\nMost common trading mistakes:")
        if stats["common_mistakes"]:
            lines.extend(
                f"• {self._short(item['mistake'])} — {item['occurrences']}"
                for item in stats["common_mistakes"][:3]
            )
        else:
            lines.append("• No journaled mistakes yet")
        self.api.send_message(
            chat_id, "\n".join(lines), self._dashboard_keyboard()
        )

    @staticmethod
    def _dashboard_keyboard() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "👥 All Members", "callback_data": "admin:members"},
                    {"text": "📊 Statistics", "callback_data": "admin:statistics"},
                ],
                [
                    {"text": "📚 Weak Topics", "callback_data": "admin:weak_topics"},
                    {
                        "text": "📒 Trade Journals",
                        "callback_data": "admin:trade_journals",
                    },
                ],
                [
                    {"text": "🔍 Search Member", "callback_data": "admin:search"},
                    {"text": "📈 Member Progress", "callback_data": "admin:progress"},
                ],
                [{"text": "💬 DM Coach Stats", "callback_data": "admin:dm_coach"}],
                [{"text": "🏠 Main Menu", "callback_data": "nav:home"}],
            ]
        }

    def _show_statistics(self, chat_id: int) -> None:
        stats = self._dashboard_data()
        average = stats["average_score"]
        lines = [
            "ADMIN STATISTICS",
            f"Total registered members: {stats['total_members']}",
            f"Members active in the last 7 days: {stats['active_this_week']}",
            f"Members with an assessment: {stats['assessed_members']}",
            f"Average score across all attempts: {self._percentage(average)}",
            (
                f"Members whose latest score is below "
                f"{ADMIN_LOW_SCORE_THRESHOLD}%: {stats['low_score_members']}"
            ),
            f"Trades journaled: {stats['trades_journaled']}",
            (
                f"Members without a check-in in {ADMIN_RECENT_CHECKIN_DAYS}+ days "
                f"(or none): {stats['no_recent_checkin']}"
            ),
            "\nTop-performing members (average across attempts):",
        ]
        lines.extend(
            [
                f"• {self._member_label(member)} — {member['average_score']}% "
                f"({member['assessment_count']} tests)"
                for member in stats["top_members"]
            ]
            or ["• No assessment data yet"]
        )
        lines.append(
            f"\nLatest low scores (below {ADMIN_LOW_SCORE_THRESHOLD}%):"
        )
        lines.extend(
            [
                f"• {self._member_label(member)} — "
                f"{member['score']}/{member['total']} ({member['percentage']}%)"
                for member in stats["low_members"][:6]
            ]
            or ["• No members below the threshold"]
        )
        lines.append("\nMembers without a recent check-in:")
        lines.extend(
            f"• {self._member_label(member)}"
            for member in stats["no_checkin_members"][:5]
        )
        if not stats["no_checkin_members"]:
            lines.append("• Everyone has checked in recently")
        self.api.send_message(
            chat_id, "\n".join(lines), self._admin_navigation()
        )

    def _show_dm_coach_stats(self, chat_id: int) -> None:
        stats = self.store.admin_dm_coach_stats()
        lines = [
            "DM COACH STATISTICS",
            f"Members using coach: {stats['members_using_coach']}",
            f"Recorded interactions: {stats['total_interactions']}",
            "\nMost common questions:",
        ]
        lines.extend(
            f"• {self._short(item['question'], 90)} — {item['occurrences']}"
            for item in stats["common_questions"]
        )
        if not stats["common_questions"]:
            lines.append("• No coaching questions recorded")

        lines.append("\nMost common weak SMC topics:")
        lines.extend(
            f"• {item['topic']} — {item['occurrences']} flagged interactions"
            for item in stats["weak_topics"]
        )
        if not stats["weak_topics"]:
            lines.append("• No potential process gaps identified yet")

        lines.append("\nMost common trading mistakes:")
        lines.extend(
            f"• {item['mistake']} — {item['occurrences']}"
            for item in stats["common_mistakes"]
        )
        if not stats["common_mistakes"]:
            lines.append("• No mistakes identified yet")

        lines.append("\nRecent coaching activity:")
        for item in stats["recent_activity"]:
            lines.append(
                f"• {self._member_label(item)} — {item['detected_topic']} — "
                f"{str(item['created_at'])[:16]}"
            )
            lines.append(f"  {self._short(item['question'], 100)}")
            if item["mistakes_identified"]:
                lines.append(
                    f"  Review: {self._short(item['mistakes_identified'], 120)}"
                )
        if not stats["recent_activity"]:
            lines.append("• No recent coaching activity")

        self.api.send_message(
            chat_id, "\n".join(lines), self._admin_navigation()
        )

    def _show_weak_topics(self, chat_id: int) -> None:
        stats = self._dashboard_data()
        lines = ["WEAKEST SMC TOPICS", "Ranked by accuracy across recorded answers:"]
        if stats["weak_topics"]:
            lines.extend(
                f"• {item['topic']}: {item['accuracy']}% accuracy "
                f"({item['misses']} misses / {item['attempts']} answers)"
                for item in stats["weak_topics"]
            )
        else:
            lines.append(
                "No per-question assessment answers are available yet. "
                "Earlier quiz scores did not store topic-level answers."
            )
        self.api.send_message(
            chat_id, "\n".join(lines), self._admin_navigation()
        )

    def _show_members(self, chat_id: int, page: int, sort: str) -> None:
        total, members = self.store.admin_members_page(
            page, ADMIN_PAGE_SIZE, sort=sort
        )
        page_count = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
        if page >= page_count:
            page = page_count - 1
            total, members = self.store.admin_members_page(
                page, ADMIN_PAGE_SIZE, sort=sort
            )
        title = "MEMBER PROGRESS" if sort == "progress" else "ALL MEMBERS"
        lines = [f"{title} — page {page + 1}/{page_count} · {total} total"]
        rows = []
        for member in members:
            label = self._member_label(member)
            if sort == "progress":
                average = self._percentage(member["assessment_average"])
                label = f"{label} · avg {average}"
            rows.append(
                [
                    {
                        "text": label[:64],
                        "callback_data": f"admin:member:{member['telegram_id']}",
                    }
                ]
            )
        if not members:
            lines.append("No members have started the bot yet.")
        nav: list[dict[str, str]] = []
        prefix = "admin:progress:page" if sort == "progress" else "admin:members"
        if page > 0:
            nav.append(
                {
                    "text": "← Previous",
                    "callback_data": f"{prefix}:{page - 1}",
                }
            )
        if page + 1 < page_count:
            nav.append(
                {
                    "text": "Next →",
                    "callback_data": f"{prefix}:{page + 1}",
                }
            )
        if nav:
            rows.append(nav)
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            self._admin_navigation(rows),
        )

    def _show_member_detail(
        self, chat_id: int, telegram_id: int, assessment_page: int = 0
    ) -> None:
        detail = self.store.admin_member_detail(
            telegram_id, assessment_page, page_size=8
        )
        if not detail:
            self.api.send_message(
                chat_id,
                "Member not found.",
                self._admin_navigation(),
            )
            return
        user = detail["user"]
        username = f"@{user['username']}" if user["username"] else "Not set"
        average = self._percentage(detail["assessment_average"])
        lines = [
            f"MEMBER PROFILE — Telegram ID {telegram_id}",
            f"Username: {username}",
            f"First name: {user['first_name'] or 'Not set'}",
            f"Started: {str(user['started_at'])[:10]}",
            f"Last interaction: {user['last_interaction_at']}",
            f"Assessment attempts: {detail['assessment_count']}",
            f"Average score: {average}",
            f"Trades journaled: {detail['trade_total']}",
            f"Winning/loss records: {detail['wins']} wins, {detail['losses']} losses",
            "\nStrong topics:",
        ]
        if detail["strong_topics"]:
            lines.extend(
                f"• {item['topic']} — {item['accuracy']}%"
                for item in detail["strong_topics"]
            )
        else:
            lines.append("• No topic-level strengths recorded")
        lines.append("\nWeak topics:")
        if detail["weak_topics"]:
            lines.extend(
                f"• {item['topic']} — {item['accuracy']}%"
                for item in detail["weak_topics"]
            )
        else:
            lines.append(
                "• No topic-level weaknesses recorded"
                if detail["topics_available"]
                else "• Not available for earlier attempts without saved answers"
            )
        lines.append(
            f"\nAssessment history (page {assessment_page + 1}, newest first):"
        )
        lines.extend(
            f"• {item['completed_at'][:10]} — {item['score']}/{item['total']} "
            f"({item['percentage']}%)"
            for item in detail["assessment_history"]
        )
        if not detail["assessment_history"]:
            lines.append("• No assessments completed")
        lines.append("\nMost common mistakes:")
        lines.extend(
            f"• {self._short(item['mistake'])} — {item['occurrences']}"
            for item in detail["common_mistakes"]
        )
        if not detail["common_mistakes"]:
            lines.append("• No repeated mistakes recorded")
        lines.append("\nWeekly check-in history (latest 8):")
        lines.extend(
            f"• {item['completed_at'][:10]} — {item['trades_taken']} trades, "
            f"{item['winners']} wins, {item['losses']} losses; "
            f"focus: {self._short(item['next_focus'], 80)}"
            for item in detail["weekly_checkins"]
        )
        if not detail["weekly_checkins"]:
            lines.append("• No weekly check-ins recorded")

        buttons: list[list[dict[str, str]]] = []
        assessment_count = int(detail["assessment_count"])
        assessment_page_size = 8
        page_count = max(1, (assessment_count + assessment_page_size - 1) // assessment_page_size)
        history_controls = []
        if assessment_page > 0:
            history_controls.append(
                {
                    "text": "← Newer scores",
                    "callback_data": (
                        f"admin:member_history:{telegram_id}:{assessment_page - 1}"
                    ),
                }
            )
        if assessment_page + 1 < page_count:
            history_controls.append(
                {
                    "text": "Older scores →",
                    "callback_data": (
                        f"admin:member_history:{telegram_id}:{assessment_page + 1}"
                    ),
                }
            )
        if history_controls:
            buttons.append(history_controls)
        buttons.append(
            [
                {
                    "text": "📒 This Member’s Trade Journals",
                    "callback_data": f"admin:member_trades:{telegram_id}:0",
                }
            ]
        )
        self.api.send_message(
            chat_id, "\n".join(lines), self._admin_navigation(buttons)
        )

    def _show_member_history(self, chat_id: int, data: str) -> None:
        parts = data.split(":")
        try:
            telegram_id, page = int(parts[2]), max(0, int(parts[3]))
        except (IndexError, ValueError):
            self._show_dashboard(chat_id)
            return
        self._show_member_detail(chat_id, telegram_id, page)

    def _show_trade_journals(
        self, chat_id: int, page: int, telegram_id: int | None = None
    ) -> None:
        total, trades = self.store.admin_trade_page(
            page, ADMIN_PAGE_SIZE, telegram_id=telegram_id
        )
        page_count = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
        if page >= page_count:
            page = page_count - 1
            total, trades = self.store.admin_trade_page(
                page, ADMIN_PAGE_SIZE, telegram_id=telegram_id
            )
        heading = (
            f"MEMBER TRADE JOURNALS — ID {telegram_id}"
            if telegram_id is not None
            else "TRADE JOURNALS"
        )
        rows = []
        for trade in trades:
            owner = self._member_label(trade)
            text = (
                f"{trade['created_at'][:10]} · {trade['asset']} "
                f"{trade['direction']} · {trade['result']} · {owner}"
            )
            rows.append(
                [
                    {
                        "text": text[:64],
                        "callback_data": f"admin:trade:{trade['id']}",
                    }
                ]
            )
        lines = [f"{heading} — page {page + 1}/{page_count} · {total} entries"]
        if not trades:
            lines.append("No trade journal entries have been saved.")
        if page_count > 1:
            nav: list[dict[str, str]] = []
            if page > 0:
                nav.append(
                    {
                        "text": "← Previous",
                        "callback_data": self._trade_page_callback(
                            page - 1, telegram_id
                        ),
                    }
                )
            if page + 1 < page_count:
                nav.append(
                    {
                        "text": "Next →",
                        "callback_data": self._trade_page_callback(
                            page + 1, telegram_id
                        ),
                    }
                )
            rows.append(nav)
        if telegram_id is not None:
            back = [[
                {
                    "text": "← Member profile",
                    "callback_data": f"admin:member:{telegram_id}",
                }
            ]]
        else:
            back = []
        self.api.send_message(
            chat_id, "\n".join(lines), self._admin_navigation(rows, back)
        )

    def _show_member_trades(self, chat_id: int, data: str) -> None:
        parts = data.split(":")
        try:
            telegram_id, page = int(parts[2]), max(0, int(parts[3]))
        except (IndexError, ValueError):
            self._show_dashboard(chat_id)
            return
        self._show_trade_journals(chat_id, page, telegram_id)

    def _show_trade_detail(self, chat_id: int, trade_id: int) -> None:
        trade = self.store.admin_trade_detail(trade_id)
        if not trade:
            self.api.send_message(
                chat_id, "Trade journal entry not found.", self._admin_navigation()
            )
            return
        lines = [
            f"TRADE JOURNAL — {trade['created_at'][:10]}",
            f"Member: {self._member_label(trade)} · ID {trade['telegram_id']}",
            f"Asset: {trade['asset']}",
            f"Direction: {trade['direction']}",
            f"POI: {trade['poi']}",
            f"Timeframe: {trade['timeframe']}",
            f"Confirmation: {trade['confirmation']}",
            f"Liquidity swept: {self._yes_no(trade['liquidity_swept'])}",
            f"Retest: {self._yes_no(trade['waited_for_retest'])}",
            f"Stop loss: {trade['stop_loss']}",
            f"Take profit: {trade['take_profit']}",
            f"Partial profit: {self._yes_no(trade['partial_profit'])}",
            f"Moved SL to BE: {self._yes_no(trade['moved_sl_to_be'])}",
            f"Result: {trade['result']}",
            f"Followed plan: {self._yes_no(trade['followed_plan'])}",
            f"Mistake: {trade['mistake']}",
            f"Lesson: {trade['lesson']}",
        ]
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            self._admin_navigation(
                [[
                    {
                        "text": "📈 Member Progress",
                        "callback_data": f"admin:member:{trade['telegram_id']}",
                    }
                ]]
            ),
        )

    def _admin_navigation(
        self,
        rows: list[list[dict[str, str]]] | None = None,
        extra_rows: list[list[dict[str, str]]] | None = None,
    ) -> dict[str, Any]:
        keyboard = list(rows or [])
        if extra_rows:
            keyboard.extend(extra_rows)
        keyboard.append(
            [
                {"text": "⬅️ Dashboard", "callback_data": "admin:home"},
                {"text": "🏠 Main Menu", "callback_data": "nav:home"},
            ]
        )
        return {"inline_keyboard": keyboard}

    @staticmethod
    def _basic_navigation() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": "🏠 Main Menu", "callback_data": "nav:home"}]
            ]
        }

    def _member_label(self, member: dict[str, Any]) -> str:
        first_name = member.get("first_name") or ""
        username = member.get("username")
        if first_name and username:
            label = f"{first_name} (@{username})"
        elif first_name:
            label = first_name
        elif username:
            label = f"@{username}"
        else:
            label = "Member"
        return f"{label} · ID {member['telegram_id']}"

    @staticmethod
    def _percentage(value: float | int | None) -> str:
        return f"{round(value, 1)}%" if value is not None else "—"

    @staticmethod
    def _short(value: str | None, max_length: int = 100) -> str:
        clean_value = (value or "").replace("\n", " ").strip()
        if len(clean_value) <= max_length:
            return clean_value or "Not provided"
        return clean_value[: max_length - 1] + "…"

    @staticmethod
    def _yes_no(value: int | bool) -> str:
        return "Yes" if bool(value) else "No"

    @staticmethod
    def _integer_suffix(data: str) -> int:
        try:
            return int(data.rsplit(":", maxsplit=1)[1])
        except (IndexError, ValueError):
            return -1

    @staticmethod
    def _page(data: str) -> int:
        try:
            return max(0, int(data.rsplit(":", maxsplit=1)[1]))
        except (IndexError, ValueError):
            return 0

    @staticmethod
    def _trade_page_callback(page: int, telegram_id: int | None) -> str:
        if telegram_id is None:
            return f"admin:trade_journals:{page}"
        return f"admin:member_trades:{telegram_id}:{page}"