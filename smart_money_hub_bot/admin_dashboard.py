"""Private, Telegram-ID-gated admin dashboard for member reporting."""

from datetime import date, datetime, timedelta, timezone
import html
import re
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
from .education_diagrams import EducationDiagramManager
from .education_topic_promotions import EducationTopicPromotionManager
from .curriculum_retrieval import curriculum_source_summary
from .trade_ledger import TradeLedger, TradeLedgerError
from .knowledge_approval import can_approve
from .knowledge_drafting import parse_research_material, validate_answer_draft
from .knowledge_research import UnavailableResearchProvider
from .questions import QUESTIONS
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
ADMIN_MENU_TEXT_ACTIONS = {
    "all members": "admin:members",
    "all the members": "admin:members",
    "members list": "admin:members",
    "member list": "admin:members",
    "list of members": "admin:members",
    "member directory": "admin:members",
    "everyone in the group": "admin:members",
    "active members": "admin:members",
    "members": "admin:members",
    "list members": "admin:members",
    "statistics": "admin:statistics",
    "stats": "admin:statistics",
    "member count": "admin:statistics",
    "how many members": "admin:statistics",
    "dashboard summary": "admin:statistics",
    "admin overview": "admin:statistics",
    "admin statistics": "admin:statistics",
    "member statistics": "admin:statistics",
    "weak topics": "admin:weak_topics",
    "learning gaps": "admin:weak_topics",
    "quiz gaps": "admin:weak_topics",
    "topics members struggle with": "admin:weak_topics",
    "who needs help with lessons": "admin:weak_topics",
    "trade journals": "admin:trade_journals",
    "member journals": "admin:trade_journals",
    "journal entries": "admin:trade_journals",
    "review member journals": "admin:trade_journals",
    "member trade journals": "admin:trade_journals",
    "search member": "admin:search",
    "search for a member": "admin:search",
    "look up a member": "admin:search",
    "find someone": "admin:search",
    "find member": "admin:search",
    "member progress": "admin:progress",
    "learning progress": "admin:progress",
    "progress reports": "admin:progress",
    "progress of members": "admin:progress",
    "dm coach stats": "admin:dm_coach",
    "coach usage": "admin:dm_coach",
    "coach usage stats": "admin:dm_coach",
    "knowledge improvement": "admin:knowledge",
    "knowledge queue": "admin:knowledge",
    "knowledge review": "admin:knowledge",
    "market awareness": "admin:market_awareness",
    "market awareness review": "admin:market_awareness",
    "calendar review": "admin:market_awareness",
    "economic calendar review": "admin:market_awareness",
    "channel content": "admin:channel_posts",
    "channel posts": "admin:channel_posts",
    "scheduled channel posts": "admin:channel_posts",
    "upcoming channel posts": "admin:channel_posts",
    "channel drafts": "admin:channel_posts",
    "scheduled posts": "admin:channel_posts",
    "what is scheduled": "admin:channel_posts",
    "what is the next post": "admin:channel_posts",
    "what is next post": "admin:channel_posts",
    "next post": "admin:channel_posts",
    "what will be posted next": "admin:channel_posts",
    "what is the next channel post": "admin:channel_posts",
    "held posts": "admin:held_posts",
    "held post": "admin:held_posts",
    "any held posts": "admin:held_posts",
    "any held post": "admin:held_posts",
    "any held post it says": "admin:held_posts",
    "are there any held posts": "admin:held_posts",
    "what posts are held": "admin:held_posts",
    "show held posts": "admin:held_posts",
    "check held posts": "admin:held_posts",
    "status everything": "admin:status:all",
    "full bot status": "admin:status:all",
    "check everything": "admin:status:all",
    "show all status": "admin:status:all",
    "give me feedback of everything": "admin:status:all",
    "feedback of everything": "admin:status:all",
    "any issues": "admin:status:all",
    "are there any issues": "admin:status:all",
    "what is wrong with the bot": "admin:status:all",
    "what is wrong with my bots": "admin:status:all",
    "check my bot": "admin:status:all",
    "check my bots": "admin:status:all",
    "check for other things": "admin:status:all",
    "check for issues": "admin:status:all",
    "list any issues": "admin:status:all",
    "anything broken": "admin:status:all",
    "how is everything": "admin:status:all",
    "education morning posts": "admin:group_morning",
    "education morning schedule": "admin:group_morning",
    "morning post schedule": "admin:group_morning",
    "group morning post": "admin:group_morning",
    "morning posts": "admin:group_morning",
    "education polls": "admin:education_polls",
    "education poll schedule": "admin:education_polls",
    "poll manager": "admin:education_polls",
    "poll management": "admin:education_polls",
    "open a poll": "admin:education_polls",
    "set up an education poll": "admin:education_polls",
    "poll schedule": "admin:education_polls",
    "poll controls": "admin:education_polls",
    "manage education polls": "admin:education_polls",
    "create an education poll": "admin:education_polls",
    "create education poll": "admin:education_polls",
    "next poll": "admin:education_polls",
    "polls": "admin:education_polls",
    "learning diagrams": "admin:education_diagrams",
    "education diagrams": "admin:education_diagrams",
    "smc diagrams": "admin:education_diagrams",
    "diagram library": "admin:education_diagrams",
    "add learning diagram": "admin:education_diagrams:add",
    "add diagram": "admin:education_diagrams:add",
    "content and trade records": "admin:content",
    "content records": "admin:content",
    "content history": "admin:content",
    "trade records": "admin:content",
    "trade ledger": "admin:content",
    "one time dm": "admin:dm_broadcast",
    "one time dm to all members": "admin:dm_broadcast",
    "send one time dm": "admin:dm_broadcast",
    "send one time dm to all members": "admin:dm_broadcast",
    "message all members": "admin:dm_broadcast",
    "send a message to all members": "admin:dm_broadcast",
    "send a message to everyone": "admin:dm_broadcast",
    "send a dm to everyone": "admin:dm_broadcast",
    "message everyone": "admin:dm_broadcast",
    "broadcast a message": "admin:dm_broadcast",
    "broadcast message": "admin:dm_broadcast",
    "announcement to members": "admin:dm_broadcast",
    "one time dm to one member": "admin:dm_member",
    "send one time dm to one member": "admin:dm_member",
    "message one member": "admin:dm_member",
    "send a message to one member": "admin:dm_member",
    "send a dm to one member": "admin:dm_member",
    "message a member": "admin:dm_member",
    "send someone a message": "admin:dm_member",
    "send a direct message to one member": "admin:dm_member",
    "private message a member": "admin:dm_member",
    "message a specific member": "admin:dm_member",
    "dm one member": "admin:dm_member",
    "promote bot in channel": "admin:channel_promo",
    "promote the bot": "admin:channel_promo",
    "channel promotion": "admin:channel_promo",
    "bot promotion": "admin:channel_promo",
    "share bot invitation": "admin:channel_promo",
    "promote in education market analysis": "admin:education_topic_promo",
    "promote the education group in market analysis": "admin:education_topic_promo",
    "education group promotion": "admin:education_topic_promo",
    "education group promo": "admin:education_topic_promo",
    "monday thursday promo": "admin:education_topic_promo",
    "education market analysis promotion": "admin:education_topic_promo",
}
ADMIN_MENU_HELP_ALIASES = {
    "admin commands",
    "show admin commands",
    "what can i ask you to do",
    "what admin actions can you do",
}


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
        weekly_brief_store: Any | None = None,
        weekly_brief_enabled: bool = False,
        education_market_analysis_topic_link: str | None = None,
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self.main_channel_id = main_channel_id
        self.education_group_id = education_group_id
        self.daily_brief_enabled = daily_brief_enabled
        self.weekly_brief_store = weekly_brief_store
        self.weekly_brief_enabled = weekly_brief_enabled
        self.calendar_review = calendar_review or OfficialCalendarReadRepository(
            store.database_path
        )
        self.calendar_manager = OfficialCalendarManagementRepository(
            store.database_path
        )
        self.education_morning_store = EducationMorningStore(store.database_path)
        self.education_diagrams = EducationDiagramManager(api, store, admin_id)
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
        self.education_topic_promotions = EducationTopicPromotionManager(
            api,
            store.database_path,
            admin_id=admin_id,
            education_group_id=education_group_id,
            market_channel_id=main_channel_id,
            topic_message_link=education_market_analysis_topic_link,
            writer=channel_writer,
        )
        self._search_pending: set[int] = set()
        self._broadcast_pending: set[int] = set()
        self._broadcast_drafts: dict[int, str] = {}
        self._single_member_dm_target_pending: set[int] = set()
        self._single_member_dm_message_pending: dict[int, dict[str, Any]] = {}
        self._single_member_dm_drafts: dict[int, dict[str, Any]] = {}
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

    def has_single_member_dm_state(self, telegram_id: int) -> bool:
        return (
            telegram_id in self._single_member_dm_target_pending
            or telegram_id in self._single_member_dm_message_pending
            or telegram_id in self._single_member_dm_drafts
        )

    def cancel_single_member_dm(self, telegram_id: int) -> None:
        self._single_member_dm_target_pending.discard(telegram_id)
        self._single_member_dm_message_pending.pop(telegram_id, None)
        self._single_member_dm_drafts.pop(telegram_id, None)

    def single_member_dm_is_pending(self, telegram_id: int) -> bool:
        return (
            telegram_id in self._single_member_dm_target_pending
            or telegram_id in self._single_member_dm_message_pending
        )

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

    def handle_admin_post_status_question(
        self, chat_id: int, telegram_id: int, is_private: bool, text: str
    ) -> bool:
        """Answer owner-only posting-status questions from saved admin state."""
        if (
            not is_private
            or self.admin_id is None
            or telegram_id != self.admin_id
            or chat_id != telegram_id
        ):
            return False

        normalized = " ".join(text.casefold().replace("&", "and").split())
        if normalized.startswith("/"):
            return False

        request_text = normalized
        for prefix in (
            "can you please ",
            "could you please ",
            "would you please ",
            "please ",
            "can you ",
            "could you ",
            "would you ",
            "tell me ",
            "show me ",
            "i want to know ",
            "i need to know ",
        ):
            if request_text.startswith(prefix):
                request_text = request_text[len(prefix):].strip()
                break

        if any(shortcut in request_text for shortcut in ADMIN_MENU_TEXT_ACTIONS):
            return False

        explicit_action = bool(
            re.match(
                r"^(?:create|write|draft|generate|make|edit|cancel|send|"
                r"publish now|post now|post\s+(?:a|this|the)\b|"
                r"schedule a post)\b",
                request_text,
            )
        )
        if explicit_action:
            return False

        mentions_posting = bool(
            re.search(
                r"\b(posts?|posted|posting|publish(?:ed|ing)?|auto[\s-]?post)\b",
                request_text,
            )
        )
        status_cue = bool(
            re.search(
                r"\b(auto(?:matic(?:ally)?)?|queue(?:d)?|schedul(?:e|ed|ing)|"
                r"upcoming|next|status|when|coming|today|tonight|tomorrow|"
                r"going on|happening|update|details|posted)\b",
                request_text,
            )
        )
        time_cue = bool(
            re.search(
                r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|wat)\b|"
                r"\b\d{1,2}:\d{2}\b",
                request_text,
            )
        )
        if not mentions_posting or not (status_cue or time_cue):
            return False

        broad_status = bool(
            re.search(
                r"\b(auto(?:matic(?:ally)?)?|everything|all|going on|happening)\b",
                request_text,
            )
        )
        if broad_status:
            self._show_full_status(chat_id)
        else:
            self.channel_posts.show_controls(chat_id)
        return True

    def handle_admin_menu_text(
        self, chat_id: int, telegram_id: int, is_private: bool, text: str
    ) -> bool:
        """Route admin text intents to existing dashboard callbacks safely."""
        if (
            not is_private
            or self.admin_id is None
            or telegram_id != self.admin_id
            or chat_id != telegram_id
        ):
            return False
        if self.handle_admin_post_status_question(
            chat_id, telegram_id, is_private, text
        ):
            return True

        normalized = " ".join(text.casefold().replace("&", "and").split())
        normalized = normalized.strip(" \t\r\n.!?")
        normalized = (
            normalized.replace("one-time", "one time")
            .replace("one–time", "one time")
            .replace("one—time", "one time")
            .replace("what’s", "what is")
            .replace("what's", "what is")
        )
        original_normalized = normalized
        if callback_data := ADMIN_MENU_TEXT_ACTIONS.get(original_normalized):
            self.handle_callback(chat_id, telegram_id, True, callback_data)
            return True
        prefixes = (
            "please ",
            "can you please ",
            "could you please ",
            "would you please ",
            "can you ",
            "could you ",
            "would you ",
            "can i ",
            "could i ",
            "how do i ",
            "i wanna ",
            "i want you to ",
            "i would like to ",
            "i'd like to ",
            "i need to know ",
            "i want to know ",
            "i want to see ",
            "i want to open ",
            "i want to ",
            "i need to ",
            "i need ",
            "show me ",
            "tell me ",
            "show ",
            "open ",
            "view ",
        )
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):].strip()
                    changed = True
                    if callback_data := ADMIN_MENU_TEXT_ACTIONS.get(normalized):
                        self.handle_callback(
                            chat_id, telegram_id, True, callback_data
                        )
                        return True
                    break
        for suffix in (" please", " for me", " right now", " now"):
            while normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()

        if (
            original_normalized in ADMIN_MENU_HELP_ALIASES
            or normalized in ADMIN_MENU_HELP_ALIASES
        ):
            self.api.send_message(
                chat_id,
                "ADMIN TEXT SHORTCUTS — PRIVATE CHAT\n\n"
                "Try: all members; statistics; weak topics; trade journals; "
                "search member; member progress; DM Coach stats; knowledge "
                "improvement; market awareness review; channel content; "
                "Education morning posts; Education polls; content and trade "
                "records; learning diagrams; send one-time DM; "
                "send one-time DM to one member; "
                "promote bot in channel; or promote in Education Market Analysis.\n\n"
                "These open the matching admin screen. Message and promotion "
                "flows still require their normal review and confirmation. "
                "“Post an SMC poll now” remains the direct poll request.",
                self._dashboard_keyboard(),
            )
            return True

        callback_data = (
            ADMIN_MENU_TEXT_ACTIONS.get(original_normalized)
            or ADMIN_MENU_TEXT_ACTIONS.get(normalized)
        )
        if callback_data is not None:
            self.handle_callback(chat_id, telegram_id, True, callback_data)
            return True

        # Allow natural wording around a clear action, but never let a keyword
        # mentioned in an ordinary Coach question open an admin screen.
        explicit_action = normalized != original_normalized or bool(
            re.match(
                r"^(show|open|list|find|search|view|check|review|manage|send|"
                r"message|dm|promote|create|schedule|post|how many|what is "
                r"scheduled)\b",
                normalized,
            )
        )
        if not explicit_action:
            return False

        matches = [
            (len(alias), alias, action)
            for alias, action in ADMIN_MENU_TEXT_ACTIONS.items()
            if len(alias.split()) >= 2
            and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized)
        ]
        if matches:
            # If the user clearly asked for two sections, ask which to open
            # instead of silently choosing one.
            actions = {action for _, _, action in matches}
            if len(actions) > 1 and re.search(r"\b(and|also|then)\b", normalized):
                labels = sorted(
                    action.removeprefix("admin:").replace("_", " ").title()
                    for action in actions
                )
                self.api.send_message(
                    chat_id,
                    "I found more than one admin action: "
                    + ", ".join(labels)
                    + ". Which one should I open? Send one action, or say "
                    "“admin commands” to see the list. Nothing was changed.",
                    self._dashboard_keyboard(),
                )
                return True
            best_length = max(length for length, _, _ in matches)
            best_actions = {
                action
                for length, _, action in matches
                if length == best_length
            }
            if len(best_actions) == 1:
                self.handle_callback(
                    chat_id, telegram_id, True, next(iter(best_actions))
                )
                return True
            labels = sorted(
                action.removeprefix("admin:").replace("_", " ").title()
                for action in best_actions
            )
            self.api.send_message(
                chat_id,
                "I’m not sure which admin action you mean: "
                + ", ".join(labels)
                + ". Send one action, or say “admin commands” to see the list. "
                "Nothing was changed.",
                self._dashboard_keyboard(),
            )
            return True

        admin_action_terms = (
            "member",
            "members",
            "weak topic",
            "journal",
            "coach stats",
            "knowledge",
            "market awareness",
            "calendar review",
            "channel",
            "morning post",
            "content record",
            "trade record",
            "one time dm",
            "direct message",
            "broadcast",
            "promotion",
            "progress report",
        )
        if any(term in normalized for term in admin_action_terms):
            self.api.send_message(
                chat_id,
                "I understand you want an admin action, but I couldn’t tell "
                "which one. Say “admin commands” to see the choices, or rephrase "
                "the request. Nothing was sent or published.",
                self._dashboard_keyboard(),
            )
            return True
        return False

    def handle_admin_post_text(
        self, chat_id: int, telegram_id: int, is_private: bool, text: str
    ) -> bool:
        """Turn an explicit admin post request into a saved, review-first draft."""
        request_text = text.strip()
        for prefix in (
            "can you please ",
            "could you please ",
            "please ",
            "can you ",
            "could you ",
            "i want you to ",
            "i want to ",
            "i'd like you to ",
            "help me ",
        ):
            if request_text.casefold().startswith(prefix):
                request_text = request_text[len(prefix):].lstrip()
                break
        request_head = re.split(r"[:\n]", request_text, maxsplit=1)[0]
        if re.search(r"\bpolls?\b", request_head, flags=re.IGNORECASE):
            return False
        if not re.match(r"^(post|publish|send)\b", request_text, flags=re.IGNORECASE):
            return False
        if not self._authorize(chat_id, telegram_id, is_private):
            return True
        previous_request = re.match(
            r"^(?:post|publish|send)\s+(?:the\s+)?(?:last|previous)\s+"
            r"(?:answer|lesson|post)\s+(?:to|in)\s+"
            r"(market analysis channel|market analysis|education group|education)\s*$",
            request_text,
            flags=re.IGNORECASE,
        )
        match = re.match(
            r"^(?:post|publish|send)\s+(?:(?:this|it|the post|the lesson)\s+)?"
            r"(?:to|in)\s+(market analysis channel|market analysis|"
            r"education group|education)\s*:\s*(.*)$",
            request_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match and not previous_request:
            self.api.send_message(
                chat_id,
                "I can prepare a private preview for the configured Market Analysis "
                "channel or Education group. Include the complete post and destination, "
                "or ask me to use your latest lesson. I’ll show you a private preview "
                "with buttons; nothing is sent until you choose to publish it.",
            )
            return True

        if previous_request:
            destination_name = previous_request.group(1)
            history = self.store.recent_dm_coaching_interactions(telegram_id, limit=1)
            content = str(history[0].get("coach_response") or "") if history else ""
            if not content:
                self.api.send_message(
                    chat_id, "I couldn't find a recent Coach answer to preview. Nothing was sent."
                )
                return True
        else:
            destination_name, content = match.groups()
        if destination_name.casefold() == "market analysis":
            self.api.send_message(
                chat_id,
                "Please specify “Market Analysis channel” or another configured "
                "destination. The Market Analysis topic inside Education is not "
                "supported by this shortcut.",
            )
            return True
        destination_key = (
            "market"
            if destination_name.casefold().startswith("market")
            else "education"
        )
        if destination_key == "market" and not self.main_channel_id:
            self.api.send_message(chat_id, "Market Analysis is not configured as a posting destination.")
            return True
        if destination_key == "education" and not self.education_group_id:
            self.api.send_message(chat_id, "The Education group is not configured as a posting destination.")
            return True

        body = content.strip()
        if not body:
            self.api.send_message(
                chat_id,
                "Include the complete post after the colon. Nothing was saved or sent.",
            )
            return True
        if not re.match(
            r"^(?:[\U0001f000-\U0001faff]\ufe0f?\s*)?SMART MONEY HUB\b",
            body,
            flags=re.IGNORECASE,
        ):
            body = f"📊 SMART MONEY HUB\n\n{body}"
        try:
            destination = self._destination_id(destination_key)
            draft_id = self.community_content.repository.create_draft(
                category="educational_reminder",
                content=body,
                destination_chat_id=destination,
                content_source="admin_text_request",
            )
            self._preview_content_draft(chat_id, [draft_id], show_actions=True)
        except CommunityContentError as error:
            self.api.send_message(chat_id, f"Post held; nothing was sent. {error}")
        return True

    def _handle_text_post_action(
        self, chat_id: int, telegram_id: int, action: str, draft_id: str
    ) -> None:
        draft = self.community_content.repository.get_draft(draft_id)
        if not draft:
            self.api.send_message(chat_id, "This preview is no longer available.")
            return
        if action == "approve":
            if draft["status"] == "draft":
                try:
                    self.community_content.repository.decide(
                        draft_id,
                        "approved",
                        admin_id=telegram_id,
                        reason="Approved from the private post preview.",
                    )
                except CommunityContentError:
                    self.api.send_message(
                        chat_id,
                        "This preview could not be approved. It has not been published.",
                    )
                    return
            elif draft["status"] != "approved":
                self.api.send_message(
                    chat_id,
                    "This preview has already been handled and cannot be approved again.",
                )
                return
            self.api.send_message(
                chat_id,
                "Approved. It is still not published. Tap Publish when you’re ready.",
                {
                    "inline_keyboard": [[
                        {
                            "text": "Publish now",
                            "callback_data": f"admin:content_draft:publish:{draft_id}",
                        }
                    ]]
                },
            )
            return
        try:
            self.community_content.publish_approved(
                draft_id, admin_id=telegram_id, api=self.api
            )
        except CommunityContentError:
            self.api.send_message(
                chat_id,
                "It was not published. Check the destination and bot permissions, "
                "then prepare a new preview if needed.",
            )
            return
        self.api.send_message(chat_id, "Published to the configured destination.")

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
        content_action = re.fullmatch(
            r"admin:content_draft:(approve|publish):([A-F0-9]{12})",
            data,
            flags=re.IGNORECASE,
        )
        if content_action:
            self._handle_text_post_action(
                chat_id,
                telegram_id,
                content_action.group(1).casefold(),
                content_action.group(2),
            )
            return
        if data.startswith("admin:education_topic_promo"):
            self.cancel_calendar_action(telegram_id)
            self.cancel_knowledge_action(telegram_id)
            self.cancel_broadcast(telegram_id)
            self.cancel_single_member_dm(telegram_id)
            self.cancel_channel_promo(telegram_id)
            self.cancel_channel_post_edit(telegram_id)
            self.session_open_posts.cancel_edit(telegram_id)
            self.cancel_search(telegram_id)
            self.education_topic_promotions.handle_callback(
                chat_id, telegram_id, is_private, data
            )
            return
        if data.startswith("admin:education_diagrams"):
            self.cancel_calendar_action(telegram_id)
            self.cancel_knowledge_action(telegram_id)
            self.cancel_broadcast(telegram_id)
            self.cancel_single_member_dm(telegram_id)
            self.cancel_channel_promo(telegram_id)
            self.cancel_channel_post_edit(telegram_id)
            self.session_open_posts.cancel_edit(telegram_id)
            self.cancel_search(telegram_id)
            self.education_diagrams.handle_callback(
                chat_id, telegram_id, is_private, data
            )
            return
        self.education_diagrams.cancel_upload(telegram_id)
        if not data.startswith("admin:market_awareness"):
            self.cancel_calendar_action(telegram_id)
        self.cancel_knowledge_action(telegram_id)
        broadcast_actions = {
            "admin:dm_broadcast",
            "admin:dm_broadcast:confirm",
            "admin:dm_broadcast:cancel",
        }
        single_member_dm_actions = {
            "admin:dm_member",
            "admin:dm_member:confirm",
            "admin:dm_member:cancel",
        }
        channel_promo_actions = {
            "admin:channel_promo",
            "admin:channel_promo:confirm",
            "admin:channel_promo:cancel",
        }
        if data not in broadcast_actions:
            self.cancel_broadcast(telegram_id)
        if (
            data not in single_member_dm_actions
            and not data.startswith("admin:dm_member:target:")
        ):
            self.cancel_single_member_dm(telegram_id)
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

        if data == "admin:held_posts":
            self._show_held_posts(chat_id)
            return
        if data == "admin:status:all":
            self._show_full_status(chat_id)
            return
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
        elif data in {"admin:education_polls", "admin:education_polls:open"}:
            self._show_education_polls(chat_id)
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
                    chat_id,
                    page=0,
                    notice=(
                        f"Admin review decision saved: {status}. Source verification "
                        "is separate; this does not verify unknown fields or publish "
                        "the record."
                    ),
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
        elif data == "admin:dm_member":
            self.cancel_single_member_dm(telegram_id)
            self._single_member_dm_target_pending.add(telegram_id)
            self.api.send_message(
                chat_id,
                "Who should receive the one-time DM? Send their numeric Telegram ID, "
                "username, or first name. They must have started this bot and not "
                "used /stop.\n\nNothing is sent until you review and confirm the "
                "message. You can also use /cancel to stop.",
                self._admin_navigation(
                    [[{"text": "Cancel", "callback_data": "admin:dm_member:cancel"}]]
                ),
            )
        elif data.startswith("admin:dm_member:target:"):
            self._start_single_member_dm_for_target(
                chat_id, telegram_id, self._integer_suffix(data)
            )
        elif data == "admin:dm_member:confirm":
            self._send_single_member_dm(chat_id, telegram_id)
        elif data == "admin:dm_member:cancel":
            self.cancel_single_member_dm(telegram_id)
            self.api.send_message(
                chat_id, "One-member DM cancelled. Nothing was sent.",
                self._dashboard_keyboard(),
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
                [{"text": "📊 Learning Diagrams", "callback_data": "admin:education_diagrams"}],
                [
                    {
                        "text": "🌍 Market Awareness Review",
                        "callback_data": "admin:market_awareness",
                    }
                ],
                [{"text": "🗓️ Channel Content", "callback_data": "admin:channel_posts"}],
                [{"text": "🌅 Education Morning Posts", "callback_data": "admin:group_morning"}],
                [{"text": "🗳️ Education Polls", "callback_data": "admin:education_polls"}],
                [{"text": "🧾 Content & Trade Records", "callback_data": "admin:content"}],
                [{"text": "📨 Send One-Time DM", "callback_data": "admin:dm_broadcast"}],
                [{"text": "✉️ Send One-Time DM to One Member", "callback_data": "admin:dm_member"}],
                [{"text": "📣 Promote Bot in Channel", "callback_data": "admin:channel_promo"}],
                [
                    {
                        "text": "📣 Promote in Education Market Analysis",
                        "callback_data": "admin:education_topic_promo",
                    }
                ],
                [{"text": "🏠 Main Menu", "callback_data": "nav:home"}],
            ]
        }

    def _show_education_polls(self, chat_id: int) -> None:
        group_status = (
            "configured Education group"
            if self.education_group_id is not None
            else "not configured"
        )
        channel_status = (
            "configured Market Analysis channel"
            if self.main_channel_id is not None
            else "not configured"
        )
        self.api.send_message(
            chat_id,
            "🗳️ EDUCATION POLLS\n\n"
            "Post a poll now to the "
            f"{group_status}. The bot also sends a poll preview with a vote button "
            f"to the {channel_status}.\n\n"
            "This manual action does not change the weekly Saturday 9:00 PM WAT poll.",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "Post Education Poll Now",
                            "callback_data": "admin:education_polls:post_now",
                        }
                    ],
                    [{"text": "⬅️ Admin Dashboard", "callback_data": "admin:home"}],
                ]
            },
        )

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
                self._preview_content_draft(chat_id, positional, show_actions=True)
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

    def handle_single_member_dm_command(
        self,
        chat_id: int,
        telegram_id: int,
        is_private: bool,
        text: str,
    ) -> bool:
        parts = text.strip().split(maxsplit=2)
        if not parts or parts[0].split("@", 1)[0].casefold() != "/memberdm":
            return False
        if not self._authorize(chat_id, telegram_id, is_private):
            return True
        self.cancel_search(telegram_id)
        self.cancel_broadcast(telegram_id)
        self.cancel_single_member_dm(telegram_id)
        if len(parts) == 1:
            self._single_member_dm_target_pending.add(telegram_id)
            self.api.send_message(
                chat_id,
                "Who should receive the one-time DM? Send their numeric Telegram ID, "
                "username, or first name. They must have started this bot and not "
                "used /stop.",
                self._admin_navigation(
                    [[{"text": "Cancel", "callback_data": "admin:dm_member:cancel"}]]
                ),
            )
            return True
        if len(parts) == 2:
            self.cancel_single_member_dm(telegram_id)
            self._set_single_member_dm_target(
                chat_id, telegram_id, parts[1]
            )
            return True
        target_query = parts[1]
        matches = self._eligible_private_dm_matches(target_query)
        if len(matches) != 1:
            self._send_single_dm_match_result(chat_id, matches, target_query)
            return True
        self._preview_single_member_dm(
            chat_id, telegram_id, matches[0], parts[2]
        )
        return True

    def handle_single_member_dm_message(
        self,
        chat_id: int,
        telegram_id: int,
        is_private: bool,
        text: str,
    ) -> bool:
        if not self.single_member_dm_is_pending(telegram_id):
            return False
        if not self._authorize(chat_id, telegram_id, is_private):
            self.cancel_single_member_dm(telegram_id)
            return True
        if text.lstrip().startswith("/"):
            return False
        if telegram_id in self._single_member_dm_target_pending:
            self._set_single_member_dm_target(chat_id, telegram_id, text)
            return True
        target = self._single_member_dm_message_pending.get(telegram_id)
        if target is None:
            return False
        self._preview_single_member_dm(chat_id, telegram_id, target, text)
        return True

    def _eligible_private_dm_matches(self, query: str) -> list[dict[str, Any]]:
        clean_query = query.strip()
        if not clean_query:
            return []
        eligible = {
            int(member["telegram_id"]): member
            for member in self._broadcast_recipients()
        }
        if clean_query.isdecimal():
            member = eligible.get(int(clean_query))
            return [member] if member is not None else []
        matching_ids = {
            int(member["telegram_id"])
            for member in self.store.search_admin_members(clean_query, limit=20)
        }
        return [
            member
            for member_id, member in eligible.items()
            if member_id in matching_ids
        ]

    def _send_single_dm_match_result(
        self, chat_id: int, matches: list[dict[str, Any]], query: str
    ) -> None:
        if matches:
            message = (
                f"More than one eligible member matched “{query}”. "
                "Send their exact username or numeric Telegram ID."
            )
        else:
            message = (
                "I couldn’t find an eligible private-chat member for that name or ID. "
                "They must have started the bot and must not have used /stop. "
                "Try their numeric ID, username, or first name."
            )
        self.api.send_message(
            chat_id,
            message,
            self._admin_navigation(
                [[{"text": "Cancel", "callback_data": "admin:dm_member:cancel"}]]
            ),
        )

    def _set_single_member_dm_target(
        self, chat_id: int, telegram_id: int, query: str
    ) -> None:
        matches = self._eligible_private_dm_matches(query)
        if len(matches) != 1:
            self._send_single_dm_match_result(chat_id, matches, query)
            return
        member = matches[0]
        self._single_member_dm_target_pending.discard(telegram_id)
        self._single_member_dm_message_pending[telegram_id] = {
            "telegram_id": int(member["telegram_id"]),
            "chat_id": int(member["chat_id"]),
            "first_name": str(member.get("first_name") or "Member"),
        }
        self.api.send_message(
            chat_id,
            f"Recipient selected: {member.get('first_name') or 'Member'} "
            f"(Telegram ID {int(member['telegram_id'])}).\n\n"
            "Now send the message text. It will be shown in a preview before "
            "anything is sent.",
            self._admin_navigation(
                [[{"text": "Cancel", "callback_data": "admin:dm_member:cancel"}]]
            ),
        )

    def _start_single_member_dm_for_target(
        self, chat_id: int, telegram_id: int, target_id: int
    ) -> None:
        self.cancel_single_member_dm(telegram_id)
        member = next(
            (
                item
                for item in self._broadcast_recipients()
                if int(item["telegram_id"]) == target_id
            ),
            None,
        )
        if member is None:
            self.api.send_message(
                chat_id,
                "This member can’t receive a private DM right now. They must have "
                "started the bot and not used /stop. Nothing was sent.",
                self._dashboard_keyboard(),
            )
            return
        self._single_member_dm_message_pending[telegram_id] = {
            "telegram_id": int(member["telegram_id"]),
            "chat_id": int(member["chat_id"]),
            "first_name": str(member.get("first_name") or "Member"),
        }
        self.api.send_message(
            chat_id,
            f"Recipient selected: {member.get('first_name') or 'Member'} "
            f"(Telegram ID {int(member['telegram_id'])}).\n\n"
            "Send the message text. I’ll show you a preview before anything is sent.",
            self._admin_navigation(
                [[{"text": "Cancel", "callback_data": "admin:dm_member:cancel"}]]
            ),
        )

    def _preview_single_member_dm(
        self,
        chat_id: int,
        telegram_id: int,
        member: dict[str, Any],
        text: str,
    ) -> None:
        message = text.strip()
        if (
            not message
            or len(message.encode("utf-16-le")) // 2
            > MAX_BROADCAST_MESSAGE_LENGTH
        ):
            self._single_member_dm_message_pending[telegram_id] = member
            self.api.send_message(
                chat_id,
                f"Send a non-empty message of at most "
                f"{MAX_BROADCAST_MESSAGE_LENGTH} Telegram characters.",
                self._admin_navigation(
                    [[{"text": "Cancel", "callback_data": "admin:dm_member:cancel"}]]
                ),
            )
            return
        self._single_member_dm_message_pending.pop(telegram_id, None)
        self._single_member_dm_target_pending.discard(telegram_id)
        self._single_member_dm_drafts[telegram_id] = {
            "telegram_id": int(member["telegram_id"]),
            "chat_id": int(member["chat_id"]),
            "first_name": str(member.get("first_name") or "Member"),
            "text": message,
        }
        self.api.send_message(
            chat_id,
            f"ONE-TIME MEMBER DM PREVIEW\n"
            f"To: {member.get('first_name') or 'Member'} "
            f"(Telegram ID {int(member['telegram_id'])})\n\n"
            f"{message}\n\n"
            "This will go only to this member after you confirm.",
            self._admin_navigation(
                [
                    [
                        {
                            "text": "Send to this member",
                            "callback_data": "admin:dm_member:confirm",
                        },
                        {
                            "text": "Cancel",
                            "callback_data": "admin:dm_member:cancel",
                        },
                    ]
                ]
            ),
        )
        return True

    def _send_single_member_dm(self, chat_id: int, telegram_id: int) -> None:
        draft = self._single_member_dm_drafts.pop(telegram_id, None)
        if draft is None:
            self.api.send_message(
                chat_id,
                "There is no pending one-member DM. Nothing was sent.",
                self._dashboard_keyboard(),
            )
            return
        member = next(
            (
                item
                for item in self._broadcast_recipients()
                if int(item["telegram_id"]) == int(draft["telegram_id"])
                and int(item["chat_id"]) == int(draft["chat_id"])
            ),
            None,
        )
        if member is None:
            self.api.send_message(
                chat_id,
                "That member is no longer eligible for a private message. "
                "Nothing was sent.",
                self._dashboard_keyboard(),
            )
            return
        try:
            self.api.send_message(int(member["chat_id"]), str(draft["text"]))
        except TelegramAPIError:
            self.api.send_message(
                chat_id,
                "Telegram could not confirm delivery. I did not retry, to avoid "
                "sending a duplicate. Check the member’s chat before starting "
                "another one-time DM.",
                self._dashboard_keyboard(),
            )
            return
        self.api.send_message(
            chat_id,
            f"One-time DM sent to {member.get('first_name') or 'the member'} "
            f"(Telegram ID {int(member['telegram_id'])}).",
            self._dashboard_keyboard(),
        )

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
            "For a one-off post, send: post to Market Analysis channel: [complete post] "
            "or post to Education group: [complete post]. A private preview comes first.",
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

    def _show_held_posts(self, chat_id: int) -> None:
        """Report saved unpublished failures from the Market Analysis queues."""
        channel_destination = self.channel_posts.destination_chat_id
        channel_holds = [
            post
            for post in self.store.list_channel_posts(limit=1000, pending_only=True)
            if (
                str(post.get("status") or "") in {"failed", "retry_wait"}
                or str(post.get("review_status") or "")
                in {"missed", "delivery_failed"}
            )
            and (
                channel_destination is None
                or int(post.get("destination_chat_id") or 0)
                == int(channel_destination)
            )
        ]

        session_store = self.session_open_posts.store
        session_holds = [
            post
            for post in session_store.list_recent(limit=100)
            if str(post.get("status") or "") == "failed"
            or str(post.get("review_status") or "")
            in {"missed", "delivery_failed"}
        ]
        today = datetime.now(ZoneInfo("Africa/Lagos")).date()
        retryable_sessions = session_store.list_retryable_gemini_failures(
            since_date=today - timedelta(days=30),
            limit=100,
        )
        session_by_id = {
            int(post["id"]): post for post in [*session_holds, *retryable_sessions]
        }
        session_holds = sorted(
            session_by_id.values(),
            key=lambda post: (
                str(post.get("schedule_at_utc") or ""),
                int(post.get("id") or 0),
            ),
            reverse=True,
        )

        lines = [
            "HELD POSTS — PRIVATE ADMIN VIEW",
            "These posts have not been published.",
        ]
        buttons: list[list[dict[str, str]]] = []
        if channel_holds:
            lines.extend(["", "Market Analysis channel:"])
            for post in channel_holds:
                failure = str(
                    post.get("failure_category")
                    or post.get("review_status")
                    or post.get("status")
                ).replace("_", " ")
                category = self.channel_posts._category_label(
                    str(post.get("category") or "post")
                )
                lines.append(
                    f"• {html.escape(str(post.get('schedule_date') or 'Date unavailable'))} "
                    f"— {html.escape(category)} — {html.escape(failure)}"
                )
                buttons.append(
                    [
                        {
                            "text": (
                                f"👁 Review Market post "
                                f"{post.get('schedule_date') or post.get('id')}"
                            )[:64],
                            "callback_data": (
                                f"admin:channel_posts:preview:{int(post['id'])}"
                            ),
                        }
                    ]
                )
        else:
            lines.extend(["", "Market Analysis channel: no held posts found."])

        if session_holds:
            lines.extend(["", "Session-open posts:"])
            for post in session_holds:
                failure = str(
                    post.get("failure_category")
                    or post.get("review_status")
                    or post.get("status")
                ).replace("_", " ")
                lines.append(
                    f"• {html.escape(str(post.get('schedule_date') or 'Date unavailable'))} "
                    f"— {html.escape(str(post.get('session_label') or 'Session post'))} "
                    f"— {html.escape(failure)}"
                )
                if post.get("content"):
                    buttons.append(
                        [
                            {
                                "text": (
                                    f"👁 Review {post.get('session_label') or 'session'} "
                                    f"{post.get('schedule_date') or post.get('id')}"
                                )[:64],
                                "callback_data": (
                                    f"admin:session_open:preview:{int(post['id'])}"
                                ),
                            }
                        ]
                    )
        else:
            lines.extend(["", "Session-open posts: no held posts found."])

        buttons.extend(
            [
                [{"text": "🗓️ Channel Content", "callback_data": "admin:channel_posts"}],
                [{"text": "🔙 Back to Admin Dashboard", "callback_data": "admin:home"}],
            ]
        )
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            {"inline_keyboard": buttons},
            parse_mode="HTML",
        )

    def _show_full_status(self, chat_id: int) -> None:
        """Provide a read-only operational summary from persisted bot state."""
        now_utc = datetime.now(timezone.utc)
        local_now = now_utc.astimezone(ZoneInfo("Africa/Lagos"))
        today = local_now.date()

        channel_settings = self.store.get_channel_posting_settings()
        channel_queue = [
            post
            for post in self.store.list_channel_posts(limit=1000, pending_only=True)
            if self.main_channel_id is None
            or int(post.get("destination_chat_id") or 0) == int(self.main_channel_id)
        ]
        held_channel = [
            post
            for post in channel_queue
            if str(post.get("status") or "") in {"failed", "retry_wait"}
            or str(post.get("review_status") or "")
            in {"missed", "delivery_failed"}
        ]

        session_upcoming = self.session_open_posts.store.list_upcoming(
            start_utc=now_utc, limit=5
        )
        session_recent = self.session_open_posts.store.list_recent(limit=30)
        session_held = [
            post
            for post in session_recent
            if str(post.get("status") or "") == "failed"
            or str(post.get("review_status") or "")
            in {"missed", "delivery_failed"}
        ]

        morning_run = self.education_morning_store.get(today.isoformat())
        poll_attempts = self.store.recent_education_poll_attempts(limit=3)
        pending_polls = self.store.pending_education_poll_runs(limit=20)
        promo_settings = self.education_topic_promotions.store.settings()
        recent_promos = self.education_topic_promotions.store.recent(limit=3)

        daily_run = (
            self.channel_posts.daily_brief_store.get(today)
            if self.daily_brief_enabled and self.channel_posts.daily_brief_store
            else None
        )
        week_start = today - timedelta(days=today.weekday())
        weekly_run = (
            self.weekly_brief_store.get(week_start)
            if self.weekly_brief_enabled and self.weekly_brief_store is not None
            else None
        )

        content_repository = self.community_content.repository
        schedules = content_repository.list_schedules()
        enabled_schedules = [
            schedule
            for schedule in schedules
            if str(schedule.get("enabled", "0")).casefold() in {"1", "true", "yes"}
        ]
        drafts = content_repository.list_drafts(limit=100)
        draft_counts: dict[str, int] = {}
        for draft in drafts:
            state = str(draft.get("status") or "unknown")
            draft_counts[state] = draft_counts.get(state, 0) + 1
        next_channel_posts = sorted(
            channel_queue,
            key=lambda post: (
                str(post.get("schedule_date") or ""),
                int(post.get("id") or 0),
            ),
        )[:5]
        channel_queue_lines: list[str] = []
        for post in next_channel_posts:
            schedule_date = str(post.get("schedule_date") or "")
            try:
                publish_time = self.channel_posts._publish_time(
                    date.fromisoformat(schedule_date)
                ).strftime("%H:%M")
            except ValueError:
                publish_time = "time unavailable"
            category = self.channel_posts._category_label(
                str(post.get("category") or "post")
            )
            status = self.channel_posts._status_label(post)
            channel_queue_lines.append(
                f"• {schedule_date or 'Date unavailable'} at {publish_time} WAT — "
                f"{category} — {status}"
            )
        if not channel_queue_lines:
            channel_queue_lines.append("• No saved channel posts in the queue.")

        source_statuses = self.calendar_review.list_source_status()
        if not source_statuses:
            source_summary = "No saved source checks"
            source_problems: list[str] = []
        else:
            source_problems = [
                str(item.get("source_name") or "Source")
                for item in source_statuses
                if str(item.get("status") or "").casefold()
                not in {"success", "ok", "healthy"}
            ]
            source_summary = (
                "Last checks: "
                + ", ".join(
                    f"{str(item.get('source_name') or 'source')}="
                    f"{str(item.get('status') or 'unknown')}"
                    for item in source_statuses
                )
            )

        lines = [
            "SMART MONEY HUB — FULL ADMIN STATUS",
            f"Read-only snapshot: {local_now.strftime('%Y-%m-%d %H:%M WAT')}",
            "",
            "MARKET ANALYSIS",
            (
                f"Scheduled channel posts: "
                f"{'PAUSED' if channel_settings.get('paused') else 'ACTIVE'}; "
                f"{len(channel_queue)} pending, {len(held_channel)} held/failed."
            ),
            "Saved Market Analysis queue (next 5):",
            *channel_queue_lines,
            "Routine slots: weekdays/Saturday 10:00 WAT; Sunday 18:00 WAT.",
            (
                f"Session opens: {len(session_upcoming)} upcoming; "
                f"{len(session_held)} recent held/failed."
            ),
            "",
            "EDUCATION GROUP",
            (
                "Morning lesson: "
                f"{'ENABLED' if self.education_morning_store.is_enabled() else 'PAUSED'} "
                f"daily at 08:00 WAT; today: "
                f"{self._run_status(morning_run)}."
            ),
            (
                "Weekly poll: Saturday 21:00 WAT; "
                f"{len(pending_polls)} pending run(s); latest: "
                f"{self._run_status(poll_attempts[0] if poll_attempts else None)}."
            ),
            (
                "Monday/Thursday topic promotion: "
                f"{'ENABLED' if promo_settings.get('scheduled_enabled') else 'PAUSED'} "
                "at 19:00 WAT; latest: "
                f"{self._run_status(recent_promos[0] if recent_promos else None)}."
            ),
            "",
            "USD & GOLD BRIEFS",
            (
                "Daily Market Analysis brief: "
                f"{'ENABLED' if self.daily_brief_enabled else 'DISABLED'} "
                f"at 00:00 WAT; today: {self._run_status(daily_run)}."
            ),
            (
                "Weekly Education announcements brief: "
                f"{'ENABLED' if self.weekly_brief_enabled else 'DISABLED'} "
                f"Monday 00:00 WAT; this week: {self._run_status(weekly_run)}."
            ),
            f"Official source checks: {source_summary}.",
            "",
            "CONTENT & TRADE RECORDS",
            (
                f"Scheduled draft generation: "
                f"{'ENABLED' if content_repository.enabled() else 'PAUSED'}; "
                f"{len(enabled_schedules)}/{len(schedules)} routine schedules enabled."
            ),
            (
                "Routine automatic publishing: "
                f"{'ENABLED' if content_repository.setting('auto_publish_enabled') == '1' else 'DISABLED'}; "
                "trade-result claims remain subject to the verified trade ledger."
            ),
            "Recent saved draft states: "
            + (
                ", ".join(
                    f"{state} {count}"
                    for state, count in sorted(draft_counts.items())
                )
                if draft_counts
                else "none"
            ),
        ]

        issues: list[str] = []
        for post in held_channel[:3]:
            issues.append(
                f"Market post {post.get('schedule_date')}: "
                f"{str(post.get('failure_category') or post.get('status')).replace('_', ' ')}"
            )
        for post in session_held[:2]:
            issues.append(
                f"{post.get('session_label') or 'Session post'} "
                f"{post.get('schedule_date')}: "
                f"{str(post.get('failure_category') or post.get('status')).replace('_', ' ')}"
            )
        if poll_attempts and str(poll_attempts[0].get("status") or "") in {
            "failed",
            "delivery_unknown",
            "channel_failed",
            "channel_delivery_unknown",
        }:
            latest_poll = poll_attempts[0]
            issues.append(
                f"Latest Education poll {latest_poll.get('scheduled_at')}: "
                f"{str(latest_poll.get('failure_category') or latest_poll.get('status')).replace('_', ' ')}"
            )
        if source_problems:
            issues.append("Calendar sources needing attention: " + ", ".join(source_problems))
        if issues:
            lines.extend(["", f"ISSUES ({min(len(issues), 6)} shown):"])
            lines.extend(f"• {line}" for line in issues[:6])
        else:
            lines.extend(["", "ISSUES: No saved held or failed items found in these queues."])

        lines.extend(
            [
                "",
                "This checks saved admin status only; it does not inspect private member "
                "messages, verify live market prices, or publish anything.",
            ]
        )
        self.api.send_message(chat_id, "\n".join(lines), self._dashboard_keyboard())

    @staticmethod
    def _run_status(run: dict[str, Any] | None) -> str:
        if not run:
            return "no run recorded"
        status = str(run.get("status") or "unknown")
        failure = str(run.get("failure_category") or "")
        return f"{status} ({failure.replace('_', ' ')})" if failure else status

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
        self._preview_content_draft(chat_id, [draft_id], show_actions=True)

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
        self._preview_content_draft(chat_id, [draft_id], show_actions=True)

    def _preview_content_draft(
        self, chat_id: int, positional: list[str], *, show_actions: bool = False
    ) -> None:
        if not positional:
            drafts = self.community_content.repository.list_drafts(limit=1)
            if not drafts:
                raise CommunityContentError("There is no saved draft to preview.")
            draft = drafts[0]
        else:
            draft = self.community_content.repository.get_draft(positional[0])
        if not draft:
            raise CommunityContentError("Draft not found.")
        destination_id = int(draft["destination_chat_id"])
        if destination_id == self.main_channel_id:
            destination_name = "Market Analysis channel"
        elif destination_id == self.education_group_id:
            destination_name = "Education group"
        else:
            destination_name = "configured destination"
        status = str(draft["status"])
        self.api.send_message(
            chat_id,
            (
                f"<b>Private preview</b> · {html.escape(destination_name)} · "
                f"{html.escape(status)} · not published"
                if show_actions
                else f"<b>Draft {html.escape(draft['draft_id'])}</b> · "
                f"{html.escape(status)} · not published"
            ),
            parse_mode="HTML",
        )
        keyboard = None
        if show_actions and status in {"draft", "approved"}:
            action = "approve" if status == "draft" else "publish"
            keyboard = {
                "inline_keyboard": [[
                    {
                        "text": "Approve preview" if action == "approve" else "Publish now",
                        "callback_data": (
                            f"admin:content_draft:{action}:{draft['draft_id']}"
                        ),
                    }
                ]]
            }
        self.api.send_message(
            chat_id,
            render_telegram_html(draft["content"]),
            keyboard,
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
        sources = curriculum_source_summary()
        archive_status = (
            self.store.education_group_archive_summary(self.education_group_id)
            if self.education_group_id is not None
            else {"post_count": 0, "latest_posted_at": None, "episode_numbers": []}
        )
        provider_health = self.store.coach_provider_health(days=7)
        latest_failure = provider_health["latest_failure"]
        failure_status = ""
        if latest_failure:
            status_parts = []
            if latest_failure.get("http_status") is not None:
                status_parts.append(f"HTTP {latest_failure['http_status']}")
            if latest_failure.get("provider_status"):
                status_parts.append(str(latest_failure["provider_status"]))
            if status_parts:
                failure_status = f" ({', '.join(status_parts)})"
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
            "Indexed learning sources:",
            f"• Built-in lesson cards: {sources['lesson_cards']}",
            f"• Assessment questions: {len(QUESTIONS)}",
            f"• Archived Education-group posts: {archive_status['post_count']}",
            "• Episode-tagged archived posts: "
            f"{len(archive_status['episode_numbers'])} "
            "(archive records, not verified transcripts)",
            f"• Uploaded course documents: {sources['uploaded_course_documents']}",
            f"• SMC diagrams: {len(self.store.education_diagrams())}",
            "• Episode transcripts: not configured",
            "• Separate Bot 1 progress interface: not connected",
            "",
            "Coach provider events (last 7 days; no message text stored here):",
            f"• Text: {provider_health['coach_text_success']} successful, "
            f"{provider_health['coach_text_failure']} failed",
            f"• Chart images: {provider_health['chart_image_success']} successful, "
            f"{provider_health['chart_image_failure']} failed",
            (
                "• Latest failure: "
                f"{latest_failure['feature']} / {latest_failure['failure_kind']}"
                f"{failure_status} at {latest_failure['created_at']}"
                if latest_failure
                else "• No provider failures recorded in this period"
            ),
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
                        "text": label[:52],
                        "callback_data": f"admin:member:{member['telegram_id']}",
                    },
                    {
                        "text": "✉️ DM",
                        "callback_data": (
                            f"admin:dm_member:target:{member['telegram_id']}"
                        ),
                    },
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
                    "text": "✉️ Send One-Time DM",
                    "callback_data": f"admin:dm_member:target:{telegram_id}",
                }
            ]
        )
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