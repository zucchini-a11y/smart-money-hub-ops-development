"""Private, Telegram-ID-gated admin dashboard for member reporting."""

from datetime import date, datetime, timedelta, timezone
import html
import shlex
from typing import Any
from zoneinfo import ZoneInfo

from .channel_posting import ChannelPostManager
from .channel_gemini import GeminiChannelContentService
from .session_open_posts import SessionOpenPostManager
from .daily_calendar_brief import DailyCalendarBriefStore
from .community_content import (
    CONTENT_CATEGORIES,
    CommunityContentError,
    CommunityContentManager,
    render_telegram_html,
)
from .economic_calendar_phase1 import (
    CALENDAR_REVIEW_PAGE_SIZE,
    OfficialCalendarReadRepository,
    fetch_and_store_official_schedules,
    format_calendar_admin_review,
)
from .economic_calendar_admin import (
    CalendarManagementError,
    OfficialCalendarManagementRepository,
    build_weekly_calendar_preview,
)
from .education_morning import EducationMorningStore
from .trade_ledger import TradeLedger, TradeLedgerError
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
    "🚀 <b>WELCOME TO SMART MONEY HUB</b>\n\n"
    "📚 <b>Learn smarter. Trade with discipline. Keep improving.</b>\n\n"
    "Want to understand Smart Money Concepts (SMC) and make more disciplined "
    "trading decisions? Smart Money Hub brings educational tools together in one place.\n\n"
    "🔥 <b>WHAT YOU CAN EXPLORE</b>\n\n"
    "📖 <b>SMC Lessons</b> — Learn key trading concepts.\n\n"
    "🎯 <b>Assessments &amp; Challenges</b> — Test your understanding and see which "
    "topics to revisit.\n\n"
    "📝 <b>Trade Journal</b> — Record trade reviews, reflect on decisions, and learn "
    "from mistakes.\n\n"
    "🧠 <b>Private Coach</b> — Ask educational questions about SMC concepts and "
    "trade-review scenarios.\n\n"
    "📈 <b>Learning Progress</b> — Review assessment and journal progress, and choose "
    "a weekly focus in check-ins or Sunday Preparation.\n\n"
    "🎓 <b>Class Reminders</b> — Get Monday and Thursday Zoom class reminders at the "
    "configured times.\n\n"
    "━━━━━━━━━━━━━━\n\n"
    "🛡️ <b>OUR PRINCIPLE</b>\n\n"
    "<b>NO CONFIRMATION, NO ENTRY.</b>\n\n"
    "Patience, structured analysis, and responsible risk management come first.\n\n"
    "👇 <b>READY TO GET STARTED?</b>\n\n"
    "Tap the Coach button below to open the Smart Money Hub bot, then send /start "
    "if prompted.\n\n"
    "📌 For educational purposes only. Trading involves risk, and profits are not guaranteed.\n\n"
    "— VAYDA | Smart Money Hub"
)
CHANNEL_PROMO_URL = "https://t.me/SmartMoneyHubSignalsBot"


class AdminDashboard:
    def __init__(
        self,
        api: TelegramAPI,
        store: Repository,
        admin_id: int | None,
        main_channel_id: int | None = None,
        channel_writer: GeminiChannelContentService | None = None,
        calendar_review: OfficialCalendarReadRepository | None = None,
        education_group_id: int | None = None,
        daily_brief_enabled: bool = False,
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self.main_channel_id = main_channel_id
        self.education_group_id = education_group_id
        self.calendar_review = calendar_review or OfficialCalendarReadRepository(
            store.database_path
        )
        self.calendar_manager = OfficialCalendarManagementRepository(
            store.database_path
        )
        self.education_morning_store = EducationMorningStore(store.database_path)
        allowed_destinations: dict[int, str] = {}
        if main_channel_id is not None:
            allowed_destinations[int(main_channel_id)] = "channel"
        if education_group_id is not None:
            allowed_destinations[int(education_group_id)] = "supergroup"
        self.trade_ledger = TradeLedger(store.database_path)
        self.community_content = CommunityContentManager(
            store.database_path,
            writer=channel_writer,
            trade_ledger=self.trade_ledger,
            allowed_destinations=allowed_destinations,
        )
        self.channel_posts = ChannelPostManager(
            api,
            store,
            admin_id,
            main_channel_id,
            channel_writer=channel_writer,
            daily_brief_store=DailyCalendarBriefStore(store.database_path),
            daily_brief_enabled=daily_brief_enabled,
        )
        self.session_open_posts = SessionOpenPostManager(
            api,
            store.database_path,
            admin_id=admin_id,
            destination_chat_id=main_channel_id,
            writer=channel_writer,
            history_store=store,
            channel_post_manager=self.channel_posts,
        )
        self._search_pending: set[int] = set()
        self._broadcast_pending: set[int] = set()
        self._broadcast_drafts: dict[int, str] = {}
        self._channel_promo_pending: set[int] = set()
        self._knowledge_pending: dict[int, tuple[str, int]] = {}
        self._calendar_pending: dict[int, tuple[str, str | None]] = {}
        self._calendar_filters: dict[int, dict[str, str]] = {}
        self._content_edit_pending: dict[int, str] = {}

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

    def has_channel_post_edit_pending(self, telegram_id: int) -> bool:
        if self.admin_id is None or telegram_id != self.admin_id:
            return False
        return self.channel_posts.has_edit_pending(telegram_id)

    def cancel_channel_post_edit(self, telegram_id: int) -> None:
        self.channel_posts.cancel_edit(telegram_id)

    def handle_channel_post_edit_message(
        self, chat_id: int, telegram_id: int, is_private: bool, text: str
    ) -> bool:
        if not self._authorize(chat_id, telegram_id, is_private):
            self.cancel_channel_post_edit(telegram_id)
            return True
        return self.channel_posts.handle_edit_message(
            chat_id, telegram_id, text, is_private
        )

    def knowledge_is_pending(self, telegram_id: int) -> bool:
        return telegram_id in self._knowledge_pending

    def cancel_knowledge_action(self, telegram_id: int) -> None:
        self._knowledge_pending.pop(telegram_id, None)

    def has_knowledge_state(self, telegram_id: int) -> bool:
        return telegram_id in self._knowledge_pending

    def calendar_is_pending(self, telegram_id: int) -> bool:
        return self.admin_id is not None and telegram_id == self.admin_id and (
            telegram_id in self._calendar_pending
        )

    def cancel_calendar_action(self, telegram_id: int) -> None:
        self._calendar_pending.pop(telegram_id, None)

    def has_calendar_state(self, telegram_id: int) -> bool:
        return telegram_id in self._calendar_pending

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

    def handle_calendar_message(
        self, chat_id: int, telegram_id: int, is_private: bool, text: str
    ) -> None:
        if not self._authorize(chat_id, telegram_id, is_private):
            self.cancel_calendar_action(telegram_id)
            return
        pending = self._calendar_pending.get(telegram_id)
        if pending is None:
            return
        action, field = pending
        try:
            if action == "filter":
                assert field is not None
                value = text.strip()
                filters = self._calendar_filters.setdefault(telegram_id, {})
                if value.casefold() in {"all", "clear", "none"}:
                    filters.pop(field, None)
                    notice = f"Filter cleared: {field}."
                else:
                    filters[field] = value[:100]
                    notice = f"Filter applied: {field}."
                self.cancel_calendar_action(telegram_id)
                self._show_market_awareness_review(chat_id, page=0, notice=notice)
                return
            if action == "add":
                parts = [part.strip() for part in text.split("|", maxsplit=4)]
                if len(parts) != 5:
                    raise CalendarManagementError(
                        "Use: SOURCE | EVENT | YYYY-MM-DD | ISO time with offset "
                        "(or blank) | official HTTPS source URL."
                    )
                external_id = self.calendar_manager.add_manual_record(
                    source_name=parts[0],
                    title=parts[1],
                    release_date=parts[2],
                    release_time=parts[3],
                    source_url=parts[4],
                    now=datetime.now(timezone.utc),
                )
                self.cancel_calendar_action(telegram_id)
                self.api.send_message(
                    chat_id,
                    "Manual event saved as HELD / UNVERIFIED. It is not eligible "
                    "for a weekly preview until each required field is checked. "
                    f"Record: <code>{external_id}</code>",
                    parse_mode="HTML",
                )
                self._show_market_awareness_review(chat_id, page=0)
                return
            if action in {"edit", "verify"}:
                parts = [part.strip() for part in text.split("|", maxsplit=2)]
                if len(parts) != 3:
                    raise CalendarManagementError(
                        "Use: FIELD | VALUE | official HTTPS evidence URL. "
                        "Fields: title, date, time, previous, forecast, actual, impact."
                    )
                self.calendar_manager.set_field(
                    str(field),
                    parts[0].casefold(),
                    parts[1],
                    parts[2],
                    verified=action == "verify",
                    now=datetime.now(timezone.utc),
                )
                self.cancel_calendar_action(telegram_id)
                message = (
                    "Field verification recorded from the linked official source."
                    if action == "verify"
                    else "Edit saved, verification cleared, and the entry returned to HELD."
                )
                self.api.send_message(chat_id, message)
                self._show_market_awareness_review(chat_id, page=0)
                return
            raise CalendarManagementError("That calendar action is no longer active.")
        except CalendarManagementError as error:
            self.api.send_message(
                chat_id,
                f"{error}\n\nSend /cancel to stop this action.",
            )

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
            "<b>CHANNEL PROMO PREVIEW — NOT PUBLISHED</b>\n"
            f"Destination channel ID: <code>{self.main_channel_id}</code>\n\n"
            f"{CHANNEL_PROMO_TEXT}\n\n"
            "<b>Nothing has been posted yet.</b> Confirm below to publish this one-time message.",
            self._admin_navigation(
                [
                    [{"text": "Coach", "url": CHANNEL_PROMO_URL}],
                    [
                        {
                            "text": "Publish to Channel",
                            "callback_data": "admin:channel_promo:confirm",
                        },
                        {
                            "text": "Cancel",
                            "callback_data": "admin:channel_promo:cancel",
                        },
                    ]
                ]
            ),
            parse_mode="HTML",
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
                        [{"text": "Coach", "url": CHANNEL_PROMO_URL}]
                    ]
                },
                parse_mode="HTML",
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
        if not data.startswith("admin:market_awareness"):
            self.cancel_calendar_action(telegram_id)
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
        channel_post_actions = (
            data == "admin:channel_posts"
            or data.startswith("admin:channel_posts:")
        )
        if not channel_post_actions:
            self.cancel_channel_post_edit(telegram_id)
        session_open_actions = (
            data == "admin:session_open:view"
            or data.startswith("admin:session_open:")
        )
        if not session_open_actions:
            self.session_open_posts.cancel_edit(telegram_id)
        if data != "admin:search":
            self.cancel_search(telegram_id)

        if session_open_actions:
            self.channel_posts.cancel_edit(telegram_id)
            self.session_open_posts.handle_callback(chat_id, telegram_id, data)
            return
        if channel_post_actions:
            self.channel_posts.handle_callback(chat_id, telegram_id, data)
            return

        if data in {"admin:open", "admin:home"}:
            self._show_dashboard(chat_id)
        elif data == "admin:market_awareness":
            self._show_market_awareness_review(chat_id, page=0)
        elif data == "admin:group_morning":
            self._show_education_morning(chat_id)
        elif data == "admin:content":
            self._show_content_overview(chat_id)
        elif data in {
            "admin:group_morning:pause",
            "admin:group_morning:resume",
        }:
            enabled = data.endswith(":resume")
            self.education_morning_store.set_enabled(enabled)
            self._show_education_morning(
                chat_id,
                notice=(
                    "Daily morning posts enabled for 08:00 WAT."
                    if enabled
                    else "Daily morning posts paused. No scheduled post was sent."
                ),
            )
        elif data.startswith("admin:market_awareness:page:"):
            self._show_market_awareness_review(
                chat_id, page=self._calendar_review_page(data)
            )
        elif data == "admin:market_awareness:filters":
            self._show_market_awareness_filters(chat_id, telegram_id)
        elif data == "admin:market_awareness:filters:clear":
            self._calendar_filters.pop(telegram_id, None)
            self._show_market_awareness_review(
                chat_id, page=0, notice="All calendar filters cleared."
            )
        elif data.startswith("admin:market_awareness:filter:"):
            field = data.rsplit(":", maxsplit=1)[1]
            if field not in {"date", "event", "source", "impact", "status", "verification"}:
                self._show_market_awareness_review(chat_id, page=0)
            else:
                self._calendar_pending[telegram_id] = ("filter", field)
                self.api.send_message(
                    chat_id,
                    f"Send a value for the {field} filter. Send “all” to clear just this filter, or /cancel.",
                )
        elif data == "admin:market_awareness:add":
            self._calendar_pending[telegram_id] = ("add", None)
            self.api.send_message(
                chat_id,
                "Add a manual event. It will remain HELD and UNVERIFIED until you "
                "independently verify its fields.\n\n"
                "Send: SOURCE | EVENT | YYYY-MM-DD | ISO time with explicit offset "
                "(or blank) | official HTTPS source URL\n"
                "Sources: BEA, Census, BLS, DOL, Federal Reserve.\n"
                "Example: BEA | GDP release | 2026-10-29 | 2026-10-29T12:30:00Z | "
                "https://www.bea.gov/news/schedule",
            )
        elif data == "admin:market_awareness:refresh":
            try:
                result = fetch_and_store_official_schedules(
                    self.store.database_path,
                    now=datetime.now(timezone.utc),
                )
            except Exception:
                # The source adapter records sanitized failure categories in
                # SQLite. Do not include provider response bodies in Telegram.
                self.api.send_message(
                    chat_id,
                    "Official-source refresh did not complete. Check the source "
                    "health and failure category in Market Awareness Review.",
                )
            else:
                summary = "\n".join(
                    f"{html.escape(str(source))}: {html.escape(str(status))}"
                    for source, status in sorted(result.items())
                )
                self.api.send_message(
                    chat_id,
                    "Official-source refresh finished. These are source-ingestion "
                    "results only; nothing was published.\n\n" + summary,
                )
            self._show_market_awareness_review(chat_id, page=0)
        elif data == "admin:market_awareness:preview":
            self._show_calendar_weekly_preview(chat_id, telegram_id)
        elif data.startswith("admin:market_awareness:status:"):
            payload = data[len("admin:market_awareness:status:"):]
            try:
                status, reference = payload.split(":", maxsplit=1)
                external_id = self.calendar_manager.resolve_reference(reference)
                self.calendar_manager.set_review_status(
                    external_id, status, now=datetime.now(timezone.utc)
                )
            except CalendarManagementError as error:
                self.api.send_message(chat_id, str(error))
            else:
                self._show_market_awareness_review(
                    chat_id, page=0, notice=f"Review status saved: {status}."
                )
        elif data.startswith("admin:market_awareness:edit:"):
            reference = data[len("admin:market_awareness:edit:"):]
            try:
                external_id = self.calendar_manager.resolve_reference(reference)
            except CalendarManagementError as error:
                self.api.send_message(chat_id, str(error))
                return
            self._calendar_pending[telegram_id] = ("edit", external_id)
            self.api.send_message(
                chat_id,
                "Send: FIELD | VALUE | official HTTPS evidence URL.\n"
                "Fields: title, date, time, previous, forecast, actual, impact. "
                "An edit clears that field’s verification and returns the entry to HELD. "
                "Send /cancel to stop.",
            )
        elif data.startswith("admin:market_awareness:verify:"):
            reference = data[len("admin:market_awareness:verify:"):]
            try:
                external_id = self.calendar_manager.resolve_reference(reference)
            except CalendarManagementError as error:
                self.api.send_message(chat_id, str(error))
                return
            self._calendar_pending[telegram_id] = ("verify", external_id)
            self.api.send_message(
                chat_id,
                "Independently check the official page, then send: "
                "FIELD | VERIFIED VALUE | official HTTPS evidence URL.\n"
                "Fields: date, time, previous, forecast, actual, impact. "
                "Time must include its explicit UTC offset. Verification is an "
                "admin attestation and is recorded in the audit history. /cancel stops.",
            )
        elif data.startswith("admin:market_awareness:audit:"):
            reference = data[len("admin:market_awareness:audit:"):]
            try:
                external_id = self.calendar_manager.resolve_reference(reference)
            except CalendarManagementError as error:
                self.api.send_message(chat_id, str(error))
                return
            self._show_calendar_audit(chat_id, external_id)
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
                [
                    {
                        "text": "🌍 Market Awareness Review",
                        "callback_data": "admin:market_awareness",
                    }
                ],
                [{"text": "🗓️ Channel Content", "callback_data": "admin:channel_posts"}],
                [{"text": "🌅 Education Morning Posts", "callback_data": "admin:group_morning"}],
                [{"text": "🧾 Content & Trade Records", "callback_data": "admin:content"}],
                [{"text": "📨 Send One-Time DM", "callback_data": "admin:dm_broadcast"}],
                [{"text": "📣 Promote Bot in Channel", "callback_data": "admin:channel_promo"}],
                [{"text": "🏠 Main Menu", "callback_data": "nav:home"}],
            ]
        }

    def handle_group_morning_command(
        self,
        chat_id: int,
        telegram_id: int,
        is_private: bool,
        command: str,
    ) -> bool:
        if command not in {"/content", "/contentpause", "/contentresume"}:
            return False
        if not self._authorize(chat_id, telegram_id, is_private):
            return True
        if command == "/contentpause":
            self.community_content.repository.set_enabled(False)
            self.education_morning_store.set_enabled(False)
            self._show_education_morning(
                chat_id,
                notice="Daily Education-group morning posts are paused.",
            )
        elif command == "/contentresume":
            self.community_content.repository.set_enabled(True)
            self.education_morning_store.set_enabled(True)
            self._show_education_morning(
                chat_id,
                notice="Daily Education-group morning posts are enabled for 08:00 WAT.",
            )
        else:
            self._show_content_overview(chat_id)
        return True

    def _show_education_morning(
        self, chat_id: int, *, notice: str | None = None
    ) -> None:
        enabled = self.education_morning_store.is_enabled()
        lines = [
            "🌅 <b>EDUCATION-GROUP MORNING POSTS</b>",
            "Schedule: daily at 08:00 WAT (Africa/Lagos)",
            f"Status: {'ENABLED' if enabled else 'PAUSED'}",
            "Destination: configured Education group only",
            "Delivery: one post per WAT date; missed windows are skipped.",
            "Recent archived group posts and poll topics help avoid repetition.",
            "Auto-publication of other content remains off unless separately configured.",
        ]
        if notice:
            lines.insert(0, html.escape(notice))
        keyboard = {
            "inline_keyboard": [[
                {
                    "text": "Pause" if enabled else "Enable daily posts",
                    "callback_data": (
                        "admin:group_morning:pause"
                        if enabled else "admin:group_morning:resume"
                    ),
                },
                {"text": "Admin menu", "callback_data": "admin:home"},
            ]]
        }
        self.api.send_message(chat_id, "\n".join(lines), keyboard, parse_mode="HTML")

    @staticmethod
    def _content_command_parts(text: str) -> tuple[str, list[str], dict[str, str]]:
        parts = shlex.split(text)
        if not parts:
            return "", [], {}
        command = parts[0].split("@", 1)[0].casefold()
        positional: list[str] = []
        values: dict[str, str] = {}
        for item in parts[1:]:
            if "=" in item:
                key, value = item.split("=", 1)
                values[key.strip().casefold()] = value.strip()
            else:
                positional.append(item)
        return command, positional, values

    def content_edit_is_pending(self, telegram_id: int) -> bool:
        return telegram_id in self._content_edit_pending

    def handle_content_edit_message(
        self,
        chat_id: int,
        telegram_id: int,
        is_private: bool,
        text: str,
    ) -> bool:
        if telegram_id not in self._content_edit_pending:
            return False
        if not self._authorize(chat_id, telegram_id, is_private):
            self._content_edit_pending.pop(telegram_id, None)
            return True
        if text.strip().casefold() == "/cancel":
            self._content_edit_pending.pop(telegram_id, None)
            self.api.send_message(chat_id, "Draft edit cancelled; saved draft is unchanged.")
            return True
        if text.lstrip().startswith("/"):
            self.api.send_message(
                chat_id,
                "A draft replacement is still pending. Send the complete replacement "
                "message, or use /cancel to leave the saved draft unchanged.",
            )
            return True
        draft_id = self._content_edit_pending.pop(telegram_id)
        try:
            self.community_content.repository.edit_draft(draft_id, text)
            self.api.send_message(
                chat_id,
                f"Draft {html.escape(draft_id)} updated and returned to review. "
                "It was not published.",
            )
        except CommunityContentError as error:
            self.api.send_message(chat_id, html.escape(str(error)))
        return True

    def handle_community_content_command(
        self,
        chat_id: int,
        telegram_id: int,
        is_private: bool,
        text: str,
    ) -> bool:
        try:
            command, positional, values = self._content_command_parts(text)
        except ValueError:
            return False
        commands = {
            "/content",
            "/contenthelp",
            "/contenthistory",
            "/contentfeedback",
            "/draftversions",
            "/contentautopublish",
            "/contentpause",
            "/contentresume",
            "/draft",
            "/weeklyreport",
            "/preview",
            "/editdraft",
            "/approve",
            "/reject",
            "/publishcontent",
            "/schedule",
            "/stats",
            "/recordtrade",
            "/closetrade",
            "/correcttrade",
            "/verifytrade",
            "/addpartialtp",
            "/trades",
            "/tradeaudit",
            "/exportstats",
        }
        if command not in commands:
            return False
        if not self._authorize(chat_id, telegram_id, is_private):
            return True
        try:
            if command in {"/content", "/contenthelp"}:
                self._show_content_overview(chat_id)
            elif command == "/contenthistory":
                self._show_content_history(chat_id)
            elif command == "/contentfeedback":
                self._show_content_feedback(chat_id)
            elif command == "/draftversions":
                self._show_draft_versions(chat_id, positional)
            elif command == "/contentpause":
                self.community_content.repository.set_enabled(False)
                self.education_morning_store.set_enabled(False)
                self.api.send_message(
                    chat_id,
                    "Scheduled content is paused. Existing drafts and schedules were preserved; "
                    "nothing was sent.",
                )
            elif command == "/contentresume":
                self.community_content.repository.set_enabled(True)
                self.education_morning_store.set_enabled(True)
                self.api.send_message(
                    chat_id,
                    "Scheduled content is enabled. The daily Education-group morning post "
                    "is set for 08:00 WAT. Other configured schedules create review drafts "
                    "only. Automatic publishing remains disabled.",
                )
            elif command == "/contentautopublish":
                if not positional:
                    enabled = (
                        self.community_content.repository.setting(
                            "auto_publish_enabled"
                        )
                        == "1"
                    )
                    self.api.send_message(
                        chat_id,
                        "Routine auto-publishing is "
                        f"{'ENABLED' if enabled else 'DISABLED'}. "
                        "Use /contentautopublish enable or disable. "
                        "Only schedules marked approval=auto for routine categories "
                        "are eligible; trade-result and promotional categories stay "
                        "in administrator review.",
                    )
                elif positional[0].casefold() in {"enable", "on"}:
                    self.community_content.repository.set_setting(
                        "auto_publish_enabled", "1"
                    )
                    self.api.send_message(
                        chat_id,
                        "Routine auto-publishing is enabled. Only explicitly enabled "
                        "routine schedules marked approval=auto can publish, after "
                        "content and Telegram destination checks. Trade results and "
                        "promotions remain in administrator review.",
                    )
                elif positional[0].casefold() in {"disable", "off"}:
                    self.community_content.repository.set_setting(
                        "auto_publish_enabled", "0"
                    )
                    self.api.send_message(
                        chat_id,
                        "Routine auto-publishing is disabled. Existing schedules and "
                        "drafts remain saved.",
                    )
                else:
                    raise CommunityContentError(
                        "Usage: /contentautopublish enable|disable"
                    )
            elif command == "/draft":
                self._create_content_draft(chat_id, positional, values)
            elif command == "/weeklyreport":
                self._create_weekly_report(chat_id, values)
            elif command == "/preview":
                self._preview_content_draft(chat_id, positional)
            elif command == "/editdraft":
                if not positional:
                    raise CommunityContentError("Usage: /editdraft DRAFT_ID")
                draft = self.community_content.repository.get_draft(positional[0])
                if not draft or draft["status"] not in {"draft", "approved"}:
                    raise CommunityContentError("That unpublished draft cannot be edited.")
                self._content_edit_pending[telegram_id] = draft["draft_id"]
                self.api.send_message(
                    chat_id,
                    "Send the complete replacement message now. Use /cancel to stop. "
                    "This edits the saved draft only; it does not publish.",
                )
            elif command == "/approve":
                if not positional:
                    raise CommunityContentError("Usage: /approve DRAFT_ID")
                self.community_content.repository.decide(
                    positional[0], "approved", admin_id=telegram_id
                )
                self.api.send_message(
                    chat_id,
                    f"Draft {html.escape(positional[0].upper())} approved. "
                    "It will not publish automatically; use /publishcontent only after "
                    "reviewing the destination.",
                )
            elif command == "/reject":
                if not positional or not values.get("reason"):
                    raise CommunityContentError(
                        'Usage: /reject DRAFT_ID reason="why it was rejected"'
                    )
                self.community_content.repository.decide(
                    positional[0],
                    "rejected",
                    admin_id=telegram_id,
                    reason=values["reason"],
                )
                self.api.send_message(
                    chat_id, f"Draft {html.escape(positional[0].upper())} rejected and retained."
                )
            elif command == "/publishcontent":
                if not positional:
                    raise CommunityContentError("Usage: /publishcontent DRAFT_ID")
                result = self.community_content.publish_approved(
                    positional[0], admin_id=telegram_id, api=self.api
                )
                self.api.send_message(
                    chat_id,
                    "Published after destination and permission checks. "
                    f"Draft {html.escape(result['draft_id'])}; "
                    f"message ID {result['telegram_message_id']}.",
                )
            elif command == "/schedule":
                self._handle_content_schedule(chat_id, positional, values)
            elif command == "/stats":
                self._show_trade_statistics(chat_id, positional, values)
            elif command == "/recordtrade":
                self._record_trade(chat_id, values)
            elif command == "/closetrade":
                self._close_trade(chat_id, values)
            elif command == "/correcttrade":
                self._correct_trade(chat_id, values)
            elif command == "/verifytrade":
                self._verify_trade(chat_id, values)
            elif command == "/addpartialtp":
                self._add_partial_tp(chat_id, values)
            elif command == "/trades":
                self._list_trades(chat_id, values)
            elif command == "/tradeaudit":
                self._show_trade_audit(chat_id, positional)
            elif command == "/exportstats":
                self._export_trade_ledger(chat_id)
        except (
            CommunityContentError,
            TradeLedgerError,
            ValueError,
            KeyError,
        ) as error:
            self.api.send_message(chat_id, html.escape(str(error)))
        return True

    def _show_content_overview(self, chat_id: int) -> None:
        schedules = self.community_content.repository.list_schedules()
        drafts = self.community_content.repository.list_drafts(limit=5)
        lines = [
            "<b>SMART MONEY HUB CONTENT &amp; VERIFIED TRADE RECORDS</b>",
            f"Scheduled draft generation: "
            f"{'ENABLED' if self.community_content.repository.enabled() else 'PAUSED'}",
            "Automatic publishing: "
            f"{'ENABLED' if self.community_content.repository.setting('auto_publish_enabled') == '1' else 'DISABLED'}",
            "Morning Education-group post: "
            f"{'ENABLED' if self.education_morning_store.is_enabled() else 'PAUSED'} "
            "(daily, 08:00 WAT)",
            "",
            "Commands: /draft CATEGORY destination=education|market",
            "/weeklyreport destination=education|market",
            "/preview ID · /editdraft ID · /approve ID · /reject ID reason=...",
            "/publishcontent ID (explicit send after destination checks)",
            "/contenthistory · /contentfeedback · /draftversions ID",
            "/contentautopublish enable|disable (off by default; routine posts only)",
            "/schedule to view; use id=... category=... destination=... time=HH:MM "
            "timezone=Africa/Lagos frequency=daily|weekly enabled=true",
            "/recordtrade · /closetrade · /correcttrade · /verifytrade · /addpartialtp",
            "/stats · /trades · /tradeaudit ID · /exportstats",
            "",
            f"Content categories: {', '.join(CONTENT_CATEGORIES)}",
            "Trade results use the separate ledger only. Unverified records are excluded "
            "from performance claims.",
            "",
            "<b>Recent drafts</b>",
        ]
        if drafts:
            lines.extend(
                f"• {html.escape(draft['draft_id'])} — "
                f"{html.escape(draft['category'])} — {html.escape(draft['status'])}"
                for draft in drafts
            )
        else:
            lines.append("• No saved drafts")
        lines.append(
            f"\nConfigured schedules: {len(schedules)} "
            f"(routine auto-publish "
            f"{'enabled' if self.community_content.repository.setting('auto_publish_enabled') == '1' else 'disabled'})"
        )
        self.api.send_message(
            chat_id, "\n".join(lines), self._dashboard_keyboard(), parse_mode="HTML"
        )

    def _show_content_history(self, chat_id: int) -> None:
        drafts = self.community_content.repository.list_drafts(limit=30)
        if not drafts:
            self.api.send_message(chat_id, "No content history is saved yet.")
            return
        lines = ["<b>CONTENT ARCHIVE</b>"]
        lines.extend(
            f"• <code>{html.escape(row['draft_id'])}</code> — "
            f"{html.escape(row['category'])} — {html.escape(row['status'])} — "
            f"rev {row['revision']} — {html.escape(row['created_at_utc'][:16])} UTC"
            for row in drafts
        )
        self.api.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

    def _show_content_feedback(self, chat_id: int) -> None:
        feedback = self.community_content.repository.recent_feedback(limit=10)
        if not feedback:
            self.api.send_message(chat_id, "No administrator feedback is saved yet.")
            return
        lines = ["<b>RECENT CONTENT FEEDBACK</b>"]
        lines.extend(
            f"• {html.escape(row['decision'])} on "
            f"<code>{html.escape(row['category'])}</code>: "
            f"{html.escape(row['details'] or 'No written note')}"
            for row in feedback
        )
        self.api.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

    def _show_draft_versions(self, chat_id: int, positional: list[str]) -> None:
        if not positional:
            raise CommunityContentError("Usage: /draftversions DRAFT_ID")
        versions = self.community_content.repository.draft_versions(positional[0])
        if not versions:
            self.api.send_message(chat_id, "No earlier version is saved for that draft.")
            return
        lines = [f"<b>EARLIER VERSIONS — {html.escape(positional[0].upper())}</b>"]
        for version in versions:
            lines.append(
                f"\n<b>Revision {version['revision']} · "
                f"{html.escape(version['saved_at_utc'][:16])} UTC</b>"
            )
            lines.append(render_telegram_html(version["content"]))
        self.api.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

    def _destination_id(self, label: str | None) -> int:
        if not label:
            raise CommunityContentError(
                "Choose destination=education or destination=market."
            )
        normalized = label.strip().casefold()
        if normalized in {"education", "group"} and self.education_group_id:
            return int(self.education_group_id)
        if normalized in {"market", "market_analysis", "channel"} and self.main_channel_id:
            return int(self.main_channel_id)
        try:
            candidate = int(normalized)
        except ValueError:
            raise CommunityContentError("That destination is not configured.") from None
        if candidate not in self.community_content.allowed_destinations:
            raise CommunityContentError("That destination is not configured.")
        return candidate

    def _create_content_draft(
        self, chat_id: int, positional: list[str], values: dict[str, str]
    ) -> None:
        if not positional:
            raise CommunityContentError(
                "Usage: /draft CATEGORY destination=education|market"
            )
        destination = self._destination_id(values.get("destination"))
        draft_id = self.community_content.generate_draft(
            positional[0].strip().casefold(),
            destination,
            trade_id=values.get("trade_id"),
            stats_start=date.fromisoformat(values["start"]) if values.get("start") else None,
            stats_end=date.fromisoformat(values["end"]) if values.get("end") else None,
        )
        self._preview_content_draft(chat_id, [draft_id])

    def _create_weekly_report(
        self, chat_id: int, values: dict[str, str]
    ) -> None:
        destination = self._destination_id(values.get("destination"))
        end = date.fromisoformat(values["end"]) if values.get("end") else datetime.now(
            ZoneInfo("Africa/Lagos")
        ).date()
        start = date.fromisoformat(values["start"]) if values.get("start") else end - timedelta(days=6)
        draft_id = self.community_content.generate_draft(
            "weekly_results",
            destination,
            stats_start=start,
            stats_end=end,
        )
        self._preview_content_draft(chat_id, [draft_id])

    def _preview_content_draft(self, chat_id: int, positional: list[str]) -> None:
        if not positional:
            drafts = self.community_content.repository.list_drafts(limit=1)
            if not drafts:
                raise CommunityContentError("There is no saved draft to preview.")
            draft = drafts[0]
        else:
            draft = self.community_content.repository.get_draft(positional[0])
        if not draft:
            raise CommunityContentError("Draft not found.")
        self.api.send_message(
            chat_id,
            f"<b>Draft {html.escape(draft['draft_id'])}</b> · "
            f"{html.escape(draft['status'])} · not published",
            parse_mode="HTML",
        )
        self.api.send_message(
            chat_id,
            render_telegram_html(draft["content"]),
            parse_mode="HTML",
        )

    def _handle_content_schedule(
        self, chat_id: int, positional: list[str], values: dict[str, str]
    ) -> None:
        if not values:
            schedules = self.community_content.repository.list_schedules()
            if not schedules:
                self.api.send_message(chat_id, "No content schedules are configured.")
                return
            lines = ["Saved schedules (all require manual review):"]
            lines.extend(
                f"• {row['schedule_id']}: {row['category']} at {row['local_time']} "
                f"{row['timezone_name']} ({row['frequency']}); "
                f"{'enabled' if row['enabled'] else 'paused'}; destination "
                f"{row['destination_chat_id']}; approval={row['approval_mode']}"
                for row in schedules
            )
            self.api.send_message(chat_id, "\n".join(lines))
            return
        destination = self._destination_id(values.get("destination"))
        enabled = values.get("enabled", "false").casefold() in {"true", "yes", "1", "on"}
        weekday = int(values["weekday"]) if values.get("weekday") else None
        self.community_content.save_schedule(
            schedule_id=values.get("id", positional[0] if positional else ""),
            category=values.get("category", ""),
            destination_chat_id=destination,
            timezone_name=values.get("timezone", "Africa/Lagos"),
            local_time=values.get("time", ""),
            frequency=values.get("frequency", ""),
            weekday=weekday,
            enabled=enabled,
            approval_mode=values.get("approval", "manual").casefold(),
        )
        self.api.send_message(
            chat_id,
            "Schedule saved. It can create drafts after /contentresume; "
            "every draft still requires manual review and publishing remains off.",
        )

    def _show_trade_statistics(
        self, chat_id: int, positional: list[str], values: dict[str, str]
    ) -> None:
        start = date.fromisoformat(values["start"]) if values.get("start") else None
        end = date.fromisoformat(values["end"]) if values.get("end") else None
        instrument = values.get("instrument")
        if positional and positional[0].casefold() in {
            "daily", "weekly", "monthly", "yearly"
        }:
            today = datetime.now(ZoneInfo("Africa/Lagos")).date()
            period = positional[0].casefold()
            if period == "daily":
                start = end = today
            elif period == "weekly":
                start, end = today - timedelta(days=6), today
            elif period == "monthly":
                start, end = today.replace(day=1), today
            else:
                start, end = today.replace(month=1, day=1), today
        stats = self.trade_ledger.calculate_statistics(
            start=start, end=end, instrument=instrument
        )
        lines = [
            "VERIFIED TRADE LEDGER STATISTICS",
            f"Period: {stats['period_start'] or 'all'} to {stats['period_end'] or 'all'}",
            f"Verified closed sample: {stats['verified_closed_sample']}",
            f"Excluded unverified closed records: {stats['unverified_closed_excluded']}",
            f"Wins / losses / breakeven: {stats['wins']} / {stats['losses']} / {stats['breakeven']}",
            f"Win rate: {stats['win_rate'] or 'Unavailable'} "
            f"({stats['win_rate_denominator']})",
            f"Full TP hits: {stats['full_tp_hits']} · Partial TPs: {stats['partial_tp_records']}",
        ]
        if stats["net_pips_by_instrument_and_convention"]:
            lines.append("Recorded pips by instrument and pip-size convention:")
            for summary in stats["net_pips_by_instrument_and_convention"].values():
                lines.append(
                    f"• {summary['instrument']} / {summary['pip_size']}: "
                    f"net {summary['net']} pips; average win "
                    f"{summary['average_win'] or 'Unavailable'}; average loss "
                    f"{summary['average_loss'] or 'Unavailable'} "
                    f"(n={summary['sample_size']})"
                )
        else:
            lines.append("Recorded pips: Unavailable")
        if stats["realized_pl_by_currency"]:
            lines.append("Recorded monetary P/L by currency:")
            for currency, item in stats["realized_pl_by_currency"].items():
                lines.append(
                    f"• {currency}: {item['net']} net; profit factor "
                    f"{item['profit_factor'] or 'Unavailable'} (n={item['sample_size']})"
                )
        lines.append("Member journals are not included in these results.")
        self.api.send_message(chat_id, "\n".join(lines))

    def _record_trade(self, chat_id: int, values: dict[str, str]) -> None:
        if not all(key in values for key in ("instrument", "direction", "opened_at", "entry")):
            raise CommunityContentError(
                "Usage: /recordtrade instrument=XAUUSD direction=BUY "
                "opened_at=ISO_WITH_OFFSET entry=... stop=... targets=..."
            )
        trade_id = self.trade_ledger.record_trade(
            instrument=values["instrument"],
            direction=values["direction"],
            opened_at=values["opened_at"],
            entry_price=values["entry"],
            stop_loss=values.get("stop"),
            planned_targets=values.get("targets", "").split(",")
            if values.get("targets") else [],
            source_evidence=values.get("evidence", ""),
            notes=values.get("notes", ""),
        )
        self.api.send_message(
            chat_id,
            f"Trade {html.escape(trade_id)} saved as OPEN and UNVERIFIED. "
            "No results claim will include it until you verify evidence.",
        )

    def _close_trade(self, chat_id: int, values: dict[str, str]) -> None:
        required = {"id", "outcome", "closed_at"}
        if not required.issubset(values):
            raise CommunityContentError(
                "Usage: /closetrade id=... outcome=win|loss|breakeven|partial "
                "closed_at=ISO_WITH_OFFSET exit=... net_pips=... pip_size=... "
                "pl=... currency=USD"
            )
        self.trade_ledger.close_trade(
            values["id"],
            outcome=values["outcome"],
            closed_at=values["closed_at"],
            exit_price=values.get("exit"),
            net_pips=values.get("net_pips"),
            pip_size=values.get("pip_size"),
            realized_pl=values.get("pl"),
            currency=values.get("currency"),
            full_tp_hit=values.get("full_tp", "false").casefold()
            in {"true", "yes", "1"},
        )
        self.api.send_message(
            chat_id,
            "Trade closed. It remains unverified until /verifytrade is completed.",
        )

    def _correct_trade(self, chat_id: int, values: dict[str, str]) -> None:
        if "id" not in values or "reason" not in values:
            raise CommunityContentError(
                'Usage: /correcttrade id=... reason="..." field=value'
            )
        aliases = {
            "entry": "entry_price",
            "exit": "exit_price",
            "net_pips": "net_pips",
            "pip_size": "pip_size",
            "pl": "realized_pl",
            "currency": "currency",
            "outcome": "outcome",
            "opened_at": "opened_at_utc",
            "closed_at": "closed_at_utc",
            "notes": "notes",
            "evidence": "source_evidence",
            "stop": "stop_loss",
            "targets": "planned_targets_json",
        }
        changes = {
            aliases[key]: (
                value.split(",") if key == "targets" else value
            )
            for key, value in values.items()
            if key in aliases
        }
        if not changes:
            raise CommunityContentError("Provide at least one supported correction field.")
        self.trade_ledger.correct_trade(
            values["id"], changes, reason=values["reason"]
        )
        self.api.send_message(chat_id, "Correction saved with an audit record.")

    def _verify_trade(self, chat_id: int, values: dict[str, str]) -> None:
        if not {"id", "verified", "evidence"}.issubset(values):
            raise CommunityContentError(
                'Usage: /verifytrade id=... verified=true|false evidence="source checked"'
            )
        verified = values["verified"].casefold() in {"true", "yes", "1"}
        self.trade_ledger.set_verification(
            values["id"], verified=verified, evidence=values["evidence"]
        )
        self.api.send_message(
            chat_id,
            "Verification status updated. Verified records may be used in ledger summaries.",
        )

    def _add_partial_tp(self, chat_id: int, values: dict[str, str]) -> None:
        if not {"id", "price", "closed_at"}.issubset(values):
            raise CommunityContentError(
                "Usage: /addpartialtp id=... price=... closed_at=ISO_WITH_OFFSET percent=..."
            )
        self.trade_ledger.add_partial_take_profit(
            values["id"],
            price=values["price"],
            closed_at=values["closed_at"],
            percent_closed=values.get("percent"),
        )
        self.api.send_message(chat_id, "Partial take-profit saved in the existing trade record.")

    def _list_trades(self, chat_id: int, values: dict[str, str]) -> None:
        records = self.trade_ledger.list_trades(
            instrument=values.get("instrument"), limit=25
        )
        if not records:
            self.api.send_message(chat_id, "No trade-ledger records found.")
            return
        lines = ["Trade ledger (most recent 25):"]
        lines.extend(
            f"• {row['trade_id']} · {row['instrument']} {row['direction']} · "
            f"{row['status']}/{row['outcome']} · {row['verification_status']} · "
            f"{row['opened_at_utc'][:10]}"
            for row in records
        )
        self.api.send_message(chat_id, "\n".join(lines))

    def _show_trade_audit(self, chat_id: int, positional: list[str]) -> None:
        if not positional:
            raise CommunityContentError("Usage: /tradeaudit TRADE_ID")
        audit = self.trade_ledger.audit_history(positional[0])
        if not audit:
            raise CommunityContentError("No audit entries found for that trade.")
        lines = [f"Audit history for {html.escape(positional[0].upper())}:"]
        lines.extend(
            f"• {html.escape(row['occurred_at_utc'])} — "
            f"{html.escape(row['action'])}"
            + (f": {html.escape(row['reason'])}" if row["reason"] else "")
            for row in audit
        )
        self.api.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

    def _export_trade_ledger(self, chat_id: int) -> None:
        content = self.trade_ledger.export_csv().encode("utf-8")
        try:
            result = self.api.send_document(
                chat_id,
                "smart-money-hub-trade-ledger.csv",
                content,
                caption=(
                    "Administrator export. Includes verification state; "
                    "unverified rows are not used in performance claims."
                ),
            )
        except TelegramAPIError as error:
            category = (
                f"telegram_http_{error.http_status}"
                if error.http_status
                else "telegram_document_error"
            )
            raise CommunityContentError(
                f"CSV export could not be sent ({category})."
            ) from None
        if not isinstance(result, dict) or not result.get("message_id"):
            raise CommunityContentError("Telegram did not confirm the CSV document message.")

    def _show_market_awareness_review(
        self, chat_id: int, *, page: int, notice: str | None = None
    ) -> None:
        filters = self._calendar_filters.get(self.admin_id or -1, {})
        records = self.calendar_manager.list_records(filters)
        statuses = self.calendar_review.list_source_status()
        page_count = max(
            1,
            (len(records) + CALENDAR_REVIEW_PAGE_SIZE - 1)
            // CALENDAR_REVIEW_PAGE_SIZE,
        )
        page = min(max(page, 0), page_count - 1)
        text, page_count = format_calendar_admin_review(
            records,
            statuses,
            page=page,
            page_size=CALENDAR_REVIEW_PAGE_SIZE,
        )
        keyboard_rows: list[list[dict[str, str]]] = [
            [
                {"text": "➕ Add Manual Event", "callback_data": "admin:market_awareness:add"},
                {"text": "🔄 Refresh Official Sources", "callback_data": "admin:market_awareness:refresh"},
                {"text": "🔎 Filters", "callback_data": "admin:market_awareness:filters"},
            ],
            [
                {
                    "text": "🗓️ Weekly Preview",
                    "callback_data": "admin:market_awareness:preview",
                }
            ],
            [
                {
                    "text": "🧾 Review Held Daily Brief",
                    "callback_data": "dailybrief:review",
                }
            ],
        ]
        if selected := records[page * CALENDAR_REVIEW_PAGE_SIZE : (page + 1) * CALENDAR_REVIEW_PAGE_SIZE]:
            for item in selected:
                external_id = str(item.get("external_id") or "")
                reference = self.calendar_manager.reference_for(external_id)
                keyboard_rows.extend(
                    [
                        [
                            {
                                "text": f"✅ Approve {item.get('title', 'event')[:18]}",
                                "callback_data": f"admin:market_awareness:status:approved:{reference}",
                            },
                            {
                                "text": "⏸ Hold",
                                "callback_data": f"admin:market_awareness:status:held:{reference}",
                            },
                            {
                                "text": "❌ Reject",
                                "callback_data": f"admin:market_awareness:status:rejected:{reference}",
                            },
                        ],
                        [
                            {
                                "text": "✏️ Edit field",
                                "callback_data": f"admin:market_awareness:edit:{reference}",
                            },
                            {
                                "text": "🔐 Verify field",
                                "callback_data": f"admin:market_awareness:verify:{reference}",
                            },
                            {
                                "text": "🧾 Audit",
                                "callback_data": f"admin:market_awareness:audit:{reference}",
                            },
                        ],
                    ]
                )
        if page_count > 1:
            navigation: list[dict[str, str]] = []
            if page > 0:
                navigation.append(
                    {
                        "text": "⬅️ Previous",
                        "callback_data": f"admin:market_awareness:page:{page - 1}",
                    }
                )
            if page + 1 < page_count:
                navigation.append(
                    {
                        "text": "Next ➡️",
                        "callback_data": f"admin:market_awareness:page:{page + 1}",
                    }
                )
            if navigation:
                keyboard_rows.append(navigation)
        keyboard_rows.extend(
            [
                [
                    {
                        "text": "🔄 Refresh View",
                        "callback_data": f"admin:market_awareness:page:{page}",
                    }
                ],
                [{"text": "⬅️ Admin Dashboard", "callback_data": "admin:home"}],
            ]
        )
        self.api.send_message(
            chat_id,
            (f"<b>{html.escape(notice)}</b>\n\n" if notice else "") + text,
            {"inline_keyboard": keyboard_rows},
            parse_mode="HTML",
        )

    def _show_market_awareness_filters(
        self, chat_id: int, telegram_id: int
    ) -> None:
        filters = self._calendar_filters.get(telegram_id, {})
        lines = ["<b>CALENDAR FILTERS</b>"]
        lines.extend(
            f"{key.title()}: {html.escape(value)}"
            for key, value in sorted(filters.items())
        )
        if not filters:
            lines.append("No filters are active.")
        rows = [
            [
                {"text": "Date", "callback_data": "admin:market_awareness:filter:date"},
                {"text": "Event", "callback_data": "admin:market_awareness:filter:event"},
                {"text": "Source", "callback_data": "admin:market_awareness:filter:source"},
            ],
            [
                {"text": "Impact", "callback_data": "admin:market_awareness:filter:impact"},
                {"text": "Review status", "callback_data": "admin:market_awareness:filter:status"},
                {"text": "Verification", "callback_data": "admin:market_awareness:filter:verification"},
            ],
            [
                {"text": "Clear all", "callback_data": "admin:market_awareness:filters:clear"},
                {"text": "Back", "callback_data": "admin:market_awareness"},
            ],
        ]
        self.api.send_message(
            chat_id, "\n".join(lines), {"inline_keyboard": rows}, parse_mode="HTML"
        )

    def _show_calendar_weekly_preview(
        self, chat_id: int, telegram_id: int
    ) -> None:
        now = datetime.now(timezone.utc)
        local_today = now.astimezone(ZoneInfo("Africa/Lagos")).date()
        week_start = local_today - timedelta(days=local_today.weekday())
        report = build_weekly_calendar_preview(
            self.calendar_manager.list_records(now=now),
            week_start=week_start,
            now=now,
            source_statuses=self.calendar_review.list_source_status(),
        )
        self.api.send_message(
            chat_id,
            report,
            self._admin_navigation(
                [[{"text": "Back to Calendar Review", "callback_data": "admin:market_awareness"}]]
            ),
            parse_mode="HTML",
        )

    def _show_calendar_audit(self, chat_id: int, external_id: str) -> None:
        entries = self.calendar_manager.list_audit(external_id)
        lines = [
            "<b>CALENDAR AUDIT HISTORY</b>",
            f"Record: <code>{html.escape(external_id)}</code>",
            "",
        ]
        if not entries:
            lines.append("No admin changes are recorded.")
        for entry in entries:
            timestamp = html.escape(str(entry.get("occurred_at_utc") or "unknown"))
            action = html.escape(str(entry.get("action") or "unknown"))
            field = html.escape(str(entry.get("field_name") or "record"))
            new_value = html.escape(str(entry.get("new_value") or "—")[:100])
            evidence = str(entry.get("evidence_url") or "")
            lines.append(f"{timestamp} · {action} · {field}: {new_value}")
            if evidence.startswith("https://"):
                lines.append(
                    f'Source: <a href="{html.escape(evidence, quote=True)}">official evidence</a>'
                )
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            self._admin_navigation(
                [[{"text": "Back to Calendar Review", "callback_data": "admin:market_awareness"}]]
            ),
            parse_mode="HTML",
        )

    @staticmethod
    def _calendar_review_page(data: str) -> int:
        try:
            page = int(data.rsplit(":", maxsplit=1)[1])
        except (IndexError, ValueError):
            return 0
        return max(page, 0)

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