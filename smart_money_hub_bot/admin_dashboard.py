"""Private, Telegram-ID-gated admin dashboard for member reporting."""

from datetime import datetime, timedelta, timezone
from typing import Any

from .knowledge_approval import can_approve
from .knowledge_drafting import parse_research_material, validate_answer_draft
from .knowledge_research import UnavailableResearchProvider
from .storage import Repository
from .telegram_api import TelegramAPI, TelegramAPIError

ADMIN_RECENT_CHECKIN_DAYS = 14
ADMIN_LOW_SCORE_THRESHOLD = 60
ADMIN_PAGE_SIZE = 8
MAX_BROADCAST_MESSAGE_LENGTH = 3500
UNAVAILABLE_CHAT_ERRORS = (
    "bot was blocked by the user",
    "chat not found",
    "bot can't initiate conversation",
    "bot cannot initiate conversation",
)
CHANNEL_PROMO_TEXT = (
    "SMART MONEY HUB\n\n"
    "Build a more disciplined approach to Smart Money Concepts (SMC) with our "
    "Telegram bot.\n\n"
    "• Learn key SMC concepts through short lessons\n"
    "• Take an SMC assessment and see which topics to review\n"
    "• Journal trades and reflect on your decision-making\n"
    "• Ask the private DM Coach about SMC concepts and trade reviews\n"
    "• Track progress, set a weekly focus, and prepare for the week\n"
    "• Get Monday and Thursday Zoom class reminders; the link is shared here\n\n"
    "Tap “Open Smart Money Hub” below and send /start to begin.\n\n"
    "For education and journaling only. This bot does not provide trade signals "
    "or guarantee profits."
)
CHANNEL_PROMO_URL = "https://t.me/SmartMoneyHubSignalsBot"


class AdminDashboard:
    def __init__(
        self,
        api: TelegramAPI,
        store: Repository,
        admin_id: int | None,
        main_channel_id: int | None = None,
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self.main_channel_id = main_channel_id
        self._search_pending: set[int] = set()
        self._broadcast_pending: set[int] = set()
        self._broadcast_drafts: dict[int, str] = {}
        self._channel_promo_pending: set[int] = set()
        self._knowledge_pending: dict[int, tuple[str, int]] = {}

    def search_is_pending(self, telegram_id: int) -> bool:
        return telegram_id in self._search_pending

    def cancel_search(self, telegram_id: int) -> None:
        self._search_pending.discard(telegram_id)

    def broadcast_is_pending(self, telegram_id: int) -> bool:
        return telegram_id in self._broadcast_pending

    def has_broadcast_state(self, telegram_id: int) -> bool:
        return (
            telegram_id in self._broadcast_pending
            or telegram_id in self._broadcast_drafts
        )

    def cancel_broadcast(self, telegram_id: int) -> None:
        self._broadcast_pending.discard(telegram_id)
        self._broadcast_drafts.pop(telegram_id, None)

    def has_channel_promo_state(self, telegram_id: int) -> bool:
        return telegram_id in self._channel_promo_pending

    def cancel_channel_promo(self, telegram_id: int) -> None:
        self._channel_promo_pending.discard(telegram_id)

    def knowledge_is_pending(self, telegram_id: int) -> bool:
        return telegram_id in self._knowledge_pending

    def cancel_knowledge_action(self, telegram_id: int) -> None:
        self._knowledge_pending.pop(telegram_id, None)

    def has_knowledge_state(self, telegram_id: int) -> bool:
        return telegram_id in self._knowledge_pending

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

    def handle_broadcast_message(
        self, chat_id: int, telegram_id: int, is_private: bool, text: str
    ) -> None:
        if not self._authorize(chat_id, telegram_id, is_private):
            self.cancel_broadcast(telegram_id)
            return

        draft = text.strip()
        if not draft:
            self._prompt_for_broadcast_text(chat_id, "Please send a non-empty message.")
            return
        if len(draft) > MAX_BROADCAST_MESSAGE_LENGTH:
            self._prompt_for_broadcast_text(
                chat_id,
                f"That message is too long. Keep it under "
                f"{MAX_BROADCAST_MESSAGE_LENGTH} characters.",
            )
            return

        recipients = self._broadcast_recipients()
        if not recipients:
            self.cancel_broadcast(telegram_id)
            self.api.send_message(
                chat_id,
                "There are no eligible private-chat recipients right now. "
                "Members must start the bot and must not have used /stop.",
                self._admin_navigation(),
            )
            return

        self._broadcast_pending.discard(telegram_id)
        self._broadcast_drafts[telegram_id] = draft
        self.api.send_message(
            chat_id,
            f"ONE-TIME DM PREVIEW\nRecipients: {len(recipients)}\n\n"
            f"{draft}\n\nSend this message now?",
            self._admin_navigation(
                [
                    [
                        {
                            "text": "Send DM",
                            "callback_data": "admin:dm_broadcast:confirm",
                        },
                        {
                            "text": "Cancel",
                            "callback_data": "admin:dm_broadcast:cancel",
                        },
                    ]
                ]
            ),
        )

    def handle_knowledge_message(
        self, chat_id: int, telegram_id: int, is_private: bool, text: str
    ) -> None:
        if not self._authorize(chat_id, telegram_id, is_private):
            self.cancel_knowledge_action(telegram_id)
            return
        pending = self._knowledge_pending.get(telegram_id)
        if not pending:
            return
        action, item_id = pending
        try:
            if action == "answer":
                answer = validate_answer_draft(text)
                if not self.store.set_knowledge_draft(item_id, answer):
                    raise ValueError("That knowledge question no longer exists.")
                notice = "Draft answer saved for review. It is not trusted or used by the Coach yet."
            elif action == "sources":
                research = parse_research_material(text)
                if not self.store.set_knowledge_research(item_id, **research):
                    raise ValueError("That knowledge question no longer exists.")
                notice = "Research notes saved. The source links are recorded; no live web research was performed by the bot."
            else:
                raise ValueError("That admin action is no longer active.")
        except ValueError as error:
            prompt = (
                "Send the proposed answer again."
                if action == "answer"
                else "Send HTTPS source URLs, one per line. Optional lines: NOTE: text, "
                "CONFLICT: text, REVIEW_BY: YYYY-MM-DD."
            )
            self.api.send_message(
                chat_id,
                f"{error}\n\n{prompt}\nSend /cancel to stop.",
                self._admin_navigation(),
            )
            return
        self.cancel_knowledge_action(telegram_id)
        self._show_knowledge_item(chat_id, item_id, notice=notice)

    def _prompt_for_broadcast_text(self, chat_id: int, notice: str | None = None) -> None:
        prefix = f"{notice}\n\n" if notice else ""
        self.api.send_message(
            chat_id,
            f"{prefix}Type the one-time DM to send to eligible members. "
            "Nothing is sent until you review and confirm it.",
            self._admin_navigation(
                [[{"text": "Cancel", "callback_data": "admin:dm_broadcast:cancel"}]]
            ),
        )

    def _broadcast_recipients(self) -> list[dict[str, Any]]:
        return [
            member
            for member in self.store.active_private_dm_recipients()
            if int(member["telegram_id"]) != self.admin_id
        ]

    def _send_broadcast(self, chat_id: int, telegram_id: int) -> None:
        draft = self._broadcast_drafts.pop(telegram_id, None)
        if draft is None:
            self.api.send_message(
                chat_id,
                "There is no pending DM to send. Start a new one from the dashboard.",
                self._dashboard_keyboard(),
            )
            return

        recipients = self._broadcast_recipients()
        if not recipients:
            self.api.send_message(
                chat_id,
                "There are no eligible private-chat recipients right now. "
                "Members must start the bot and must not have used /stop.",
                self._dashboard_keyboard(),
            )
            return

        sent = 0
        failed = 0
        for member in recipients:
            try:
                self.api.send_message(
                    int(member["chat_id"]),
                    draft,
                    {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Stop All Reminders",
                                    "callback_data": "reminders:off",
                                }
                            ]
                        ]
                    },
                )
            except TelegramAPIError as error:
                failed += 1
                if any(part in str(error).casefold() for part in UNAVAILABLE_CHAT_ERRORS):
                    self.store.set_reminders_stopped(int(member["telegram_id"]), True)
            else:
                sent += 1

        self.api.send_message(
            chat_id,
            f"One-time DM complete. Sent: {sent}. Failed: {failed}.",
            self._dashboard_keyboard(),
        )

    def _preview_channel_promo(self, chat_id: int, telegram_id: int) -> None:
        if self.main_channel_id is None:
            self.api.send_message(
                chat_id,
                "Channel posting is not configured. Add SMH_MAIN_CHANNEL_ID to the "
                "project environment and restart the bot.",
                self._dashboard_keyboard(),
            )
            return
        self._channel_promo_pending.add(telegram_id)
        self.api.send_message(
            chat_id,
            "CHANNEL PROMO PREVIEW\n"
            f"Destination channel ID: {self.main_channel_id}\n\n"
            f"{CHANNEL_PROMO_TEXT}\n\n"
            "Nothing has been posted yet. Post this one-time message now?",
            self._admin_navigation(
                [
                    [
                        {
                            "text": "Post to Channel",
                            "callback_data": "admin:channel_promo:confirm",
                        },
                        {
                            "text": "Cancel",
                            "callback_data": "admin:channel_promo:cancel",
                        },
                    ]
                ]
            ),
        )

    def _post_channel_promo(self, chat_id: int, telegram_id: int) -> None:
        if telegram_id not in self._channel_promo_pending:
            self.api.send_message(
                chat_id,
                "There is no pending channel post to confirm. Open the dashboard "
                "to preview it first.",
                self._dashboard_keyboard(),
            )
            return
        self._channel_promo_pending.discard(telegram_id)
        if self.main_channel_id is None:
            self.api.send_message(
                chat_id,
                "Channel posting is not configured. Add SMH_MAIN_CHANNEL_ID to the "
                "project environment and restart the bot.",
                self._dashboard_keyboard(),
            )
            return
        try:
            self.api.send_message(
                self.main_channel_id,
                CHANNEL_PROMO_TEXT,
                {
                    "inline_keyboard": [
                        [{"text": "Open Smart Money Hub", "url": CHANNEL_PROMO_URL}]
                    ]
                },
            )
        except TelegramAPIError:
            self.api.send_message(
                chat_id,
                "Telegram could not post to the channel. Check that the configured "
                "channel ID is correct and that the bot still has permission to post.",
                self._dashboard_keyboard(),
            )
            return
        self.api.send_message(
            chat_id, "The bot introduction was posted to the channel.",
            self._dashboard_keyboard(),
        )

    def handle_callback(
        self, chat_id: int, telegram_id: int, is_private: bool, data: str
    ) -> None:
        if not self._authorize(chat_id, telegram_id, is_private):
            return
        self.cancel_knowledge_action(telegram_id)
        broadcast_actions = {
            "admin:dm_broadcast",
            "admin:dm_broadcast:confirm",
            "admin:dm_broadcast:cancel",
        }
        channel_promo_actions = {
            "admin:channel_promo",
            "admin:channel_promo:confirm",
            "admin:channel_promo:cancel",
        }
        if data not in broadcast_actions:
            self.cancel_broadcast(telegram_id)
        if data not in channel_promo_actions:
            self.cancel_channel_promo(telegram_id)
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
        elif data in {"admin:knowledge", "admin:knowledge:home"}:
            self._show_knowledge_home(chat_id)
        elif data.startswith("admin:knowledge:list:"):
            view = data.rsplit(":", maxsplit=1)[1]
            self._show_knowledge_queue(chat_id, view, page=0)
        elif data.startswith("admin:knowledge:page:"):
            parts = data.split(":")
            if len(parts) == 5:
                self._show_knowledge_queue(chat_id, parts[3], self._integer_suffix(":" + parts[4]))
            else:
                self._show_knowledge_home(chat_id)
        elif data.startswith("admin:knowledge:item:"):
            self._show_knowledge_item(
                chat_id, self._integer_suffix(data)
            )
        elif data.startswith("admin:knowledge:research:"):
            self._request_knowledge_research(
                chat_id, self._integer_suffix(data)
            )
        elif data.startswith("admin:knowledge:draft:"):
            self._prompt_knowledge_input(
                chat_id,
                telegram_id,
                "answer",
                self._integer_suffix(data),
            )
        elif data.startswith("admin:knowledge:sources:"):
            self._prompt_knowledge_input(
                chat_id,
                telegram_id,
                "sources",
                self._integer_suffix(data),
            )
        elif data.startswith("admin:knowledge:approve:"):
            self._approve_knowledge_item(
                chat_id,
                telegram_id,
                self._integer_suffix(data),
            )
        elif data.startswith("admin:knowledge:reject:"):
            item_id = self._integer_suffix(data)
            self.store.reject_knowledge_draft(item_id)
            self._show_knowledge_item(
                chat_id,
                item_id,
                notice="Draft rejected. Any previously approved answer remains unchanged.",
            )
        elif data.startswith("admin:knowledge:retire:"):
            item_id = self._integer_suffix(data)
            self.store.set_knowledge_status(item_id, "retired")
            self.api.send_message(
                chat_id,
                "Knowledge entry disabled. The Coach will no longer retrieve it.",
                self._knowledge_item_keyboard(item_id),
            )
        elif data.startswith("admin:knowledge:enable:"):
            item_id = self._integer_suffix(data)
            if self.store.set_knowledge_status(item_id, "approved"):
                self.api.send_message(
                    chat_id,
                    "Approved knowledge entry re-enabled.",
                    self._knowledge_item_keyboard(item_id),
                )
            else:
                self._show_knowledge_item(chat_id, item_id)
        elif data.startswith("admin:knowledge:versions:"):
            self._show_knowledge_versions(
                chat_id, self._integer_suffix(data)
            )
        elif data == "admin:dm_broadcast":
            self._broadcast_pending.add(telegram_id)
            self._broadcast_drafts.pop(telegram_id, None)
            self._prompt_for_broadcast_text(chat_id)
        elif data == "admin:dm_broadcast:confirm":
            self._send_broadcast(chat_id, telegram_id)
        elif data == "admin:dm_broadcast:cancel":
            self.cancel_broadcast(telegram_id)
            self.api.send_message(
                chat_id, "One-time DM cancelled.", self._dashboard_keyboard()
            )
        elif data == "admin:channel_promo":
            self._preview_channel_promo(chat_id, telegram_id)
        elif data == "admin:channel_promo:confirm":
            self._post_channel_promo(chat_id, telegram_id)
        elif data == "admin:channel_promo:cancel":
            self.cancel_channel_promo(telegram_id)
            self.api.send_message(
                chat_id,
                "Channel promo cancelled. Nothing was posted.",
                self._dashboard_keyboard(),
            )
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
        if self.admin_id is None or telegram_id != self.admin_id:
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
                [{"text": "🧠 Knowledge Improvement", "callback_data": "admin:knowledge"}],
                [{"text": "📨 Send One-Time DM", "callback_data": "admin:dm_broadcast"}],
                [{"text": "📣 Promote Bot in Channel", "callback_data": "admin:channel_promo"}],
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

    def _show_knowledge_home(self, chat_id: int) -> None:
        counts = self.store.knowledge_admin_summary()
        lines = [
            "🧠 KNOWLEDGE IMPROVEMENT",
            "Member questions are grouped without usernames or Telegram IDs. "
            "Only approved answers are reusable by the Coach.",
            "",
            f"Awaiting research: {counts['awaiting_research']}",
            f"Awaiting approval: {counts['awaiting_approval']}",
            f"Member feedback needs review: {counts['unhelpful']}",
            f"Repeated questions: {counts['repeated']}",
            f"Resolved or covered: {counts['covered'] + counts['approved'] + counts['retired']}",
            f"Rejected drafts: {counts['rejected']}",
            "",
            "Research provider: unavailable in the bot runtime. Research manually, "
            "then add HTTPS source links and an answer for approval.",
        ]
        rows = [
            [
                {
                    "text": f"🔎 Awaiting research ({counts['awaiting_research']})",
                    "callback_data": "admin:knowledge:list:awaiting_research",
                }
            ],
            [
                {
                    "text": f"✅ Awaiting approval ({counts['awaiting_approval']})",
                    "callback_data": "admin:knowledge:list:awaiting_approval",
                }
            ],
            [
                {
                    "text": f"👎 Feedback review ({counts['unhelpful']})",
                    "callback_data": "admin:knowledge:list:unhelpful",
                },
                {
                    "text": f"🔁 Repeated ({counts['repeated']})",
                    "callback_data": "admin:knowledge:list:repeated",
                },
            ],
            [
                {
                    "text": "📚 Covered / resolved",
                    "callback_data": "admin:knowledge:list:resolved",
                },
                {
                    "text": "🗂 All active",
                    "callback_data": "admin:knowledge:list:all",
                },
            ],
            [
                {
                    "text": f"🚫 Rejected ({counts['rejected']})",
                    "callback_data": "admin:knowledge:list:rejected",
                }
            ],
        ]
        self.api.send_message(chat_id, "\n".join(lines), self._admin_navigation(rows))

    def _show_knowledge_queue(self, chat_id: int, view: str, page: int = 0) -> None:
        titles = {
            "awaiting_research": "AWAITING RESEARCH",
            "awaiting_approval": "AWAITING APPROVAL",
            "unhelpful": "MEMBER FEEDBACK REVIEW",
            "repeated": "REPEATED QUESTIONS",
            "resolved": "COVERED / RESOLVED",
            "rejected": "REJECTED DRAFTS",
            "all": "ALL ACTIVE KNOWLEDGE ITEMS",
        }
        if view not in titles:
            self._show_knowledge_home(chat_id)
            return
        total, items = self.store.knowledge_queue(view, page=page)
        lines = [titles[view], f"{total} item(s). Question text is shown without member identity."]
        rows: list[list[dict[str, str]]] = []
        for item in items:
            question = item.get("display_question") or "No member question retained"
            button_text = (
                f"{self._short(item['topic'], 17)} · "
                f"{self._short(question, 31)} · {item['occurrence_count']}×"
            )
            rows.append(
                [
                    {
                        "text": button_text[:64],
                        "callback_data": f"admin:knowledge:item:{item['id']}",
                    }
                ]
            )
            lines.append(
                f"• {item['topic']} — {item['status']} — "
                f"{item['occurrence_count']} question(s)"
            )
        if not items:
            lines.append("No items in this view.")
        page_count = max(1, (total + 7) // 8)
        if page > 0 or page + 1 < page_count:
            navigation: list[dict[str, str]] = []
            if page > 0:
                navigation.append(
                    {
                        "text": "⬅️ Previous",
                        "callback_data": f"admin:knowledge:page:{view}:{page - 1}",
                    }
                )
            if page + 1 < page_count:
                navigation.append(
                    {
                        "text": "Next ➡️",
                        "callback_data": f"admin:knowledge:page:{view}:{page + 1}",
                    }
                )
            rows.append(navigation)
        rows.append(
            [{"text": "🧠 Knowledge dashboard", "callback_data": "admin:knowledge:home"}]
        )
        self.api.send_message(
            chat_id, "\n".join(lines), self._admin_navigation(rows)
        )

    def _show_knowledge_item(
        self, chat_id: int, item_id: int, notice: str | None = None
    ) -> None:
        item = self.store.knowledge_item_detail(item_id)
        if not item:
            self.api.send_message(
                chat_id, "Knowledge item not found.", self._admin_navigation()
            )
            return
        lines = [
            f"KNOWLEDGE ITEM #{item['id']}",
            f"Category: {item['topic']}",
            f"Status: {item['status']} · confidence: {item['confidence']}",
            f"Occurrences: {item['occurrence_count']} · "
            f"Helpful: {item['helpful_count']} · Not helpful: {item['unhelpful_count']} · "
            f"Still unclear: {item['unclear_count']}",
            f"Review reason: {item['review_reason'] or '—'}",
            f"Last seen: {str(item['last_seen_at'])[:16]}",
        ]
        if notice:
            lines[0:0] = [notice, ""]
        if item["last_researched_at"]:
            lines.append(f"Research entered: {str(item['last_researched_at'])[:16]}")
        if item["review_after"]:
            lines.append(f"Review by: {item['review_after']}")
        if item["draft_review_after"]:
            lines.append(f"Proposed review date: {item['draft_review_after']}")
        lines.append("\nAnonymized question examples:")
        lines.extend(
            f"• {self._short(example['question'], 220)}"
            for example in item["examples"][:5]
        )
        if not item["examples"]:
            lines.append("• No member question text retained.")
        if item["proposed_answer"]:
            lines.extend(
                [
                    "\nPROPOSED ANSWER — not used by the Coach:",
                    self._short(item["proposed_answer"], 1500),
                ]
            )
        if item["approved_answer"]:
            lines.extend(
                [
                    "\nCURRENT APPROVED ANSWER:",
                    self._short(item["approved_answer"], 1500),
                ]
            )
        if item["source_urls"] and item["proposed_answer"]:
            lines.append("\nProposed answer source links:")
            lines.extend(
                f"• {url}"
                for url in item["source_urls"].splitlines()[:5]
            )
        elif item["versions"]:
            lines.append("\nCurrent approved answer source links:")
            lines.extend(
                f"• {url}"
                for url in item["versions"][0]["source_urls"].splitlines()[:5]
            )
        if item["research_notes"]:
            lines.append(f"\nResearch notes: {self._short(item['research_notes'], 500)}")
        if len("\n".join(lines)) > 3900:
            lines = [*lines[:12], "\nDetails are shortened to fit Telegram."]
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            self._knowledge_item_keyboard(item),
        )

    def _knowledge_item_keyboard(self, item_or_id: dict[str, Any] | int) -> dict[str, Any]:
        item = (
            item_or_id
            if isinstance(item_or_id, dict)
            else self.store.knowledge_item_detail(item_or_id)
        )
        if not item:
            return self._admin_navigation()
        item_id = int(item["id"])
        rows: list[list[dict[str, str]]] = [
            [
                {
                    "text": "✏️ Draft / edit answer",
                    "callback_data": f"admin:knowledge:draft:{item_id}",
                },
                {
                    "text": "🔗 Add research sources",
                    "callback_data": f"admin:knowledge:sources:{item_id}",
                },
            ],
            [
                {
                    "text": "🔎 Request more research",
                    "callback_data": f"admin:knowledge:research:{item_id}",
                },
                {
                    "text": "📜 Version history",
                    "callback_data": f"admin:knowledge:versions:{item_id}",
                },
            ],
        ]
        if (
            item.get("status") == "awaiting_approval"
            and can_approve(item.get("proposed_answer"), item.get("source_urls"))
        ):
            rows.append(
                [
                    {
                        "text": "✅ Approve answer",
                        "callback_data": f"admin:knowledge:approve:{item_id}",
                    }
                ]
            )
        if item.get("proposed_answer"):
            rows.append(
                [
                    {
                        "text": "❌ Reject proposed answer",
                        "callback_data": f"admin:knowledge:reject:{item_id}",
                    }
                ]
            )
        if item["status"] == "retired":
            rows.append(
                [
                    {
                        "text": "♻️ Re-enable approved entry",
                        "callback_data": f"admin:knowledge:enable:{item_id}",
                    }
                ]
            )
        elif item.get("approved_answer"):
            rows.append(
                [
                    {
                        "text": "⏸ Disable approved entry",
                        "callback_data": f"admin:knowledge:retire:{item_id}",
                    }
                ]
            )
        rows.append(
            [{"text": "🧠 Knowledge dashboard", "callback_data": "admin:knowledge:home"}]
        )
        return self._admin_navigation(rows)

    def _request_knowledge_research(self, chat_id: int, item_id: int) -> None:
        item = self.store.knowledge_item_detail(item_id)
        if not item:
            self.api.send_message(
                chat_id, "Knowledge item not found.", self._admin_navigation()
            )
            return
        question = item["examples"][0]["question"] if item["examples"] else item["topic"]
        result = UnavailableResearchProvider().research(question)
        self.store.set_knowledge_status(item_id, "awaiting_research")
        self.api.send_message(
            chat_id,
            result.message,
            self._knowledge_item_keyboard(item),
        )

    def _prompt_knowledge_input(
        self, chat_id: int, telegram_id: int, action: str, item_id: int
    ) -> None:
        item = self.store.knowledge_item_detail(item_id)
        if not item:
            self.api.send_message(
                chat_id, "Knowledge item not found.", self._admin_navigation()
            )
            return
        self._knowledge_pending[telegram_id] = (action, item_id)
        if action == "answer":
            prompt = (
                "Send a reviewed answer for this question. Keep it concise and factual; "
                "include relevant limitations or uncertainty. It will remain a draft "
                "until you add source links and approve it.\n\n"
                f"Category: {item['topic']}\n"
                f"Question: {self._short(item['examples'][0]['question'], 400) if item['examples'] else item['topic']}"
            )
        else:
            prompt = (
                "Send one HTTPS source URL per line. Optional lines:\n"
                "NOTE: research context or limitation\n"
                "CONFLICT: conflicting information to review\n"
                "REVIEW_BY: YYYY-MM-DD\n\n"
                "Add publication dates and source limitations in NOTE lines. "
                "The bot will store these links, not fetch or verify their contents. "
                "Send /cancel to stop."
            )
        self.api.send_message(
            chat_id, prompt + "\n\nSend /cancel to stop.", self._admin_navigation()
        )

    def _approve_knowledge_item(
        self, chat_id: int, telegram_id: int, item_id: int
    ) -> None:
        try:
            version = self.store.approve_knowledge_item(item_id, telegram_id)
        except ValueError as error:
            self.api.send_message(
                chat_id,
                str(error),
                self._knowledge_item_keyboard(item_id),
            )
            return
        self._show_knowledge_item(
            chat_id,
            item_id,
            notice=(
                f"Answer approved as version {version}. The Coach may now reuse "
                "it for matching questions."
            ),
        )

    def _show_knowledge_versions(self, chat_id: int, item_id: int) -> None:
        item = self.store.knowledge_item_detail(item_id)
        if not item:
            self.api.send_message(
                chat_id, "Knowledge item not found.", self._admin_navigation()
            )
            return
        lines = [f"VERSION HISTORY · {item['topic']}"]
        for version in item["versions"]:
            lines.extend(
                [
                    f"\nVersion {version['version']} · {str(version['created_at'])[:16]}",
                    self._short(version["answer"], 1000),
                    "Sources: " + (version["source_urls"].replace("\n", ", ")[:600] or "—"),
                ]
            )
            if version["review_after"]:
                lines.append(f"Review by: {version['review_after']}")
        if not item["versions"]:
            lines.append("No approved versions yet.")
        self.api.send_message(
            chat_id,
            "\n".join(lines)[:3900],
            self._knowledge_item_keyboard(item),
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