"""Offline, rule-based private-chat guidance and admin support cases."""
import asyncio
import hashlib
import logging
import re
import time

from .database import now, uid
from .domain import safe_text
from .members import PRO_ACCESS_GUIDE, PRO_ACCESS_REMINDER
from .support_api import SupportApiError, run_shared_support_reply_worker
from telegram.error import BadRequest, Forbidden

logger = logging.getLogger("smh.support")


FAQS = {
    "apply": "Educational Group access is self-service. PRO Signals and Market Analysis require separate applications. "
             "Open Member Access, choose the destination you want, and answer one question at a time. Approval for "
             "one destination does not grant access to another.",
    "education": "The Educational Group shares trading lessons, chart breakdowns, and learning materials. "
                 "Access is optional and requested separately through Member Access.",
    "analysis": "Market Analysis is a separate destination for market commentary and analysis. "
                "It is not the PRO Signals channel. Request access separately through Member Access.",
    "pro": PRO_ACCESS_GUIDE,
    "access": "After approval, the bot sends a private invitation for the approved destination. Open the invitation "
              "in your private chat and use its Join button. If you cannot see the invitation, open My Access / Status "
              "or contact the administrator.",
    "verification": "Registration and funding are reviewed by an administrator. The bot does not connect to "
                    "Exness and cannot verify an account automatically. Never send passwords, OTPs, or recovery codes.",
    "evidence": "Send a supported balance screenshot or PDF privately to this bot. Only administrators can "
                "review it. Do not post evidence in a channel, and never send passwords, OTPs, or recovery codes.\n\n"
                + PRO_ACCESS_REMINDER,
    "trading": "The bot shares educational material and published analysis; it does not place trades or provide "
               "personalized financial advice. Wait for the stated confirmation before considering any setup. "
               "Trading involves risk.",
    "community": "Please keep member information and private application evidence confidential, follow the "
                 "community rules, and do not share passwords or account credentials. Trading outcomes are not guaranteed.",
}

DESTINATION_LABELS = {
    "education": "Educational Group",
    "analysis": "Market Analysis",
    "pro": "PRO Signals",
}

DEFAULT_INACTIVE_REASON = (
    "The administrator has temporarily paused automated replies while updates are being completed."
)

SECRET_LIKE = re.compile(
    r"\b(?:password|passcode|otp|one[- ]time code|recovery code|secret key|api key)"
    r"\b(?:\s+(?:is|:|=)\s*|[:=]\s*)\S+|\b(?:otp|one[- ]time code|recovery code)\s+\d{4,10}\b",
    re.IGNORECASE,
)


def detect_intent(text):
    """Classify common help requests without an external model or network call."""
    value = " ".join((text or "").casefold().split())
    if not value:
        return "unknown"
    if any(term in value for term in ("talk to admin", "contact admin", "human help", "human support",
                                      "administrator", "speak to someone", "contact support")):
        return "contact"
    if any(term in value for term in ("my status", "application status", "pending application",
                                      "approved", "rejected", "my access", "check my application")):
        return "status"
    if any(term in value for term in ("after approval", "get access after", "where is my invite",
                                      "invitation link", "join after approval")):
        return "access"
    if any(term in value for term in ("pro signal", "pro access", "exness", "funded account",
                                      "funding", "registration", "broker account")):
        return "pro"
    if any(term in value for term in ("market analysis", "analysis access", "analysis channel")):
        return "analysis"
    if any(term in value for term in ("education", "lesson", "course", "bos", "choch", "liquidity",
                                      "chart breakdown", "homework", "learn to trade")):
        return "education"
    if any(term in value for term in ("apply", "application", "membership", "join", "access")):
        return "apply"
    if any(term in value for term in ("trade", "risk", "confirmation", "setup", "trading rules")):
        return "trading"
    if value in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
        return "greeting"
    if value in {"help", "what can you do", "commands"}:
        return "help"
    return "unknown"


class AssistantFlows:
    def recover_assistant_actions(self):
        with self.db.transaction() as c:
            c.execute("UPDATE assistant_escalations SET status='reply_uncertain',updated=? "
                      "WHERE status='reply_sending'", (now(),))

    def assistant_enabled(self):
        return self.db.get("assistant:enabled") is not False

    def assistant_inactive_reason(self):
        value = self.db.get("assistant:inactive_reason")
        if isinstance(value, str) and value.strip():
            try:
                return safe_text(value, 240)
            except ValueError:
                pass
        return DEFAULT_INACTIVE_REASON

    def assistant_inactive_text(self):
        return (
            "⚠️ Automated replies are temporarily paused.\n\n"
            f"Reason: {self.assistant_inactive_reason()}\n\n"
            "Member Access and My Access / Status are still available. "
            "Use the buttons below or contact the administrator for help."
        )

    def assistant_inactive_buttons(self):
        return [
            ("🔐 Member Access", "assistant_apply", {}),
            ("🔎 My Access / Status", "assistant_status", {}),
            ("💬 Contact Administrator", "assistant_contact", {}),
        ]

    def assistant_inactive_notice_pending_key(self, user):
        return f"assistant:inactive_notice_pending:{user}"

    async def assistant_inactive_notice_prompt(self, update):
        user = update.effective_user.id
        self.config.authorize(user, update.effective_chat.type)
        if self.db.draft(user) or self.db.get(self.assistant_reply_pending_key(user)):
            return await self.say(
                update,
                "Finish or cancel your current administrator draft or reply before editing the inactive notice.",
            )
        self.db.put(self.assistant_inactive_notice_pending_key(user), True)
        return await self.say(
            update,
            "Send the short reason members should see while automated replies are paused. "
            "Keep it general; do not include private member details, credentials, or tokens.",
            [("Cancel", "assistant_inactive_notice_cancel", {})],
        )

    async def assistant_inactive_notice_save(self, update, text):
        user = update.effective_user.id
        self.config.authorize(user, update.effective_chat.type)
        try:
            notice = safe_text(text, 240)
        except ValueError as exc:
            return await self.say(
                update, str(exc), [("Cancel", "assistant_inactive_notice_cancel", {})]
            )
        if SECRET_LIKE.search(notice):
            return await self.say(
                update,
                "I did not save that notice because it may contain credentials. Send a general reason instead.",
                [("Cancel", "assistant_inactive_notice_cancel", {})],
            )
        self.db.put("assistant:inactive_reason", notice)
        self.db.execute(
            "DELETE FROM kv WHERE key=?",
            (self.assistant_inactive_notice_pending_key(user),),
        )
        return await self.assistant_admin_panel(update)

    async def assistant_inactive_notice_cancel(self, update):
        user = update.effective_user.id
        self.config.authorize(user, update.effective_chat.type)
        self.db.execute(
            "DELETE FROM kv WHERE key=?",
            (self.assistant_inactive_notice_pending_key(user),),
        )
        return await self.assistant_admin_panel(update)

    async def assistant_inactive_notice_reset(self, update):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        self.db.execute("DELETE FROM kv WHERE key='assistant:inactive_reason'")
        return await self.assistant_admin_panel(update)

    def assistant_faqs(self):
        configured = self.db.get("assistant:faqs") or {}
        return {**FAQS, **{key: value for key, value in configured.items()
                          if key in FAQS and isinstance(value, str)}}

    def assistant_start_info(self, user):
        first_visit = not self.db.get(f"assistant:visited:{user}")
        self.db.put(f"assistant:visited:{user}", True)
        text = ("👋 <b>Welcome</b>\n\n"
                "Choose what you need, or type a question. I can guide you through access and application updates."
                if first_visit else
                "👋 <b>Welcome back</b>\n\nContinue your application or check your access.")
        draft = self.db.draft(user)
        buttons = []
        if draft and draft.get("kind") in ("destination_application", "pro_screening", "application",
                                            "pro_evidence", "member_info_response"):
            buttons.append(("▶️ Continue my saved step", "assistant_resume", {}))
            text += "\n\nYou have a saved application step. It is still here to continue."
        else:
            buttons.append(("🔐 Member Access", "assistant_apply", {}))
        buttons.extend([
            ("📋 My Access / Status", "assistant_status", {}),
            ("💬 Contact Administrator", "assistant_contact", {}),
        ])
        text += ("\n\nEducation is self-service. Market Analysis and PRO Signals are reviewed separately. "
                 "Trading involves risk; no outcome is guaranteed.")
        return text, buttons

    async def assistant_resume(self, update):
        await self.applicant_followup_ensure_notice(update)
        user = update.effective_user.id
        draft = self.db.draft(user)
        if not draft:
            return await self.request_destination_selection(update)
        kind = draft.get("kind")
        if kind == "destination_application":
            return await self.begin_destination_application(update, draft.get("destination"))
        if kind == "pro_screening":
            return await self.pro_screening_prompt(update, draft)
        if kind == "application":
            from .members import application_prompt
            return await self.say(update, application_prompt(len(draft.get("answers", []))))
        if kind == "pro_evidence":
            return await self.say(update, "Your private evidence step is saved. Upload the requested file here, "
                                          "or select Cancel to leave that step.")
        if kind == "member_info_response":
            return await self.say(update, "Your application needs more information. Reply to the administrator's "
                                          "request here, or select Cancel to leave the response step.")
        return await self.say(update, "No membership step is waiting. Choose Apply for Access or My Access.")

    async def assistant_topic(self, update, topic):
        if topic not in (*FAQS, "status", "help"):
            topic = "help"
        if topic == "status":
            return await self.member_action(update, "member_status", {})
        if not self.assistant_enabled():
            return await self.say(
                update, self.assistant_inactive_text(), self.assistant_inactive_buttons()
            )
        if topic == "help":
            text = ("I can help with access applications, application status, the three destinations, "
                    "education topics, and contacting the administrator.")
        else:
            text = self.assistant_faqs()[topic]
        buttons = []
        if topic == "access":
            buttons.append(("🔐 Member Access", "assistant_apply", {}))
            return await self.say(update, text, buttons)
        if topic in ("education", "analysis", "pro", "apply"):
            dest = {"education": "education", "analysis": "analysis", "pro": "pro"}.get(topic)
            if topic == "apply":
                buttons.append(("🔐 Member Access", "assistant_apply", {}))
            elif topic == "pro":
                buttons.append(("Apply for PRO Signals", "member_apply_dest", {"destination": "pro"}))
                if not self.config.exness_partner_link:
                    text += "\n\nThe registration link is not configured for this bot. Please contact the administrator."
            elif topic == "education":
                education_button, education_note = await self.education_join_button(update)
                if education_button:
                    buttons.append(education_button)
                elif education_note:
                    text += "\n\n" + education_note
            else:
                buttons.append(("📝 Apply for " + DESTINATION_LABELS[dest],
                                "member_apply_dest", {"destination": dest}))
        elif topic == "contact":
            buttons.append(("💬 Contact Administrator", "assistant_contact", {}))
        elif topic == "help":
            buttons.append(("🔐 Member Access", "assistant_apply", {}))
        return await self.say(update, text, buttons,
                              parse_mode="HTML" if topic in ("pro", "evidence") else None)

    def assistant_rate_limit(self, user, text):
        if not hasattr(self, "_assistant_rate"):
            self._assistant_rate = {}
        state = self._assistant_rate.get(user, {})
        stamp = time.time()
        digest = hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()
        recent = [t for t in state.get("times", []) if stamp - float(t) < 60]
        repeated = state.get("last_hash") == digest and stamp - float(state.get("last_at", 0)) < 5
        limited = repeated or len(recent) >= 8
        if not limited:
            recent.append(stamp)
        self._assistant_rate[user] = {"times": recent, "last_hash": digest, "last_at": stamp}
        if len(self._assistant_rate) > 1000:
            self._assistant_rate.pop(next(iter(self._assistant_rate)))
        return limited, repeated

    async def assistant_respond(self, update, text):
        user = update.effective_user.id
        limited, repeated = self.assistant_rate_limit(user, text)
        if limited:
            message = ("I’ve just received that same message. Please use one of the options below."
                       if repeated else "Please wait a little before sending another question.")
            return await self.say(update, message, [
                ("📝 Apply for Access", "assistant_apply", {}),
                ("🔎 My Access / Status", "assistant_status", {}),
                ("💬 Contact Administrator", "assistant_contact", {}),
            ])
        first = not self.db.get(f"assistant:visited:{user}")
        self.db.put(f"assistant:visited:{user}", True)
        if not self.assistant_enabled():
            return await self.say(
                update, self.assistant_inactive_text(), self.assistant_inactive_buttons()
            )
        intent = detect_intent(text)
        if intent == "contact":
            return await self.assistant_begin_contact(update)
        if intent == "status":
            return await self.member_action(update, "member_status", {})
        if intent == "greeting":
            reply = ("👋 Hi! I can guide you to access, education, "
                     "market analysis, or PRO Signals." if first else
                     "👋 Hello again. What would you like help with?")
            return await self.say(update, reply, [
                ("📝 Apply for Access", "assistant_apply", {}),
                ("📚 Education", "assistant_topic", {"topic": "education"}),
                ("📊 Market Analysis", "assistant_topic", {"topic": "analysis"}),
                ("⭐ PRO Signals", "assistant_topic", {"topic": "pro"}),
                ("💬 Contact Administrator", "assistant_contact", {}),
            ])
        if intent in ("apply", "education", "analysis", "pro", "trading", "access"):
            if intent == "trading":
                reply = self.assistant_faqs()["trading"]
                return await self.say(update, reply, [
                    ("📚 Education", "assistant_topic", {"topic": "education"}),
                    ("💬 Contact Administrator", "assistant_contact", {}),
                ])
            return await self.assistant_topic(update, intent)
        if intent == "help":
            return await self.assistant_topic(update, "help")
        prefix = ("👋 Welcome. " if first else "")
        return await self.say(
            update,
            prefix + "I’m not sure I understood yet. You can ask me about applications, access status, "
            "PRO eligibility, Market Analysis, or education. Try rephrasing, choose an option, or ask the administrator.",
            [
                ("📝 Apply for Access", "assistant_apply", {}),
                ("🔎 My Access / Status", "assistant_status", {}),
                ("📚 Education", "assistant_topic", {"topic": "education"}),
                ("📊 Market Analysis", "assistant_topic", {"topic": "analysis"}),
                ("⭐ PRO Signals", "assistant_topic", {"topic": "pro"}),
                ("💬 Ask the Administrator", "assistant_contact", {}),
            ],
        )

    async def assistant_unexpected_media(self, update):
        user = update.effective_user.id
        self.db.put(f"assistant:visited:{user}", True)
        if not self.assistant_enabled():
            return await self.say(
                update, self.assistant_inactive_text(), self.assistant_inactive_buttons()
            )
        return await self.say(update, "I can’t process that attachment here. To submit private PRO evidence, "
                                      "open your application first. For chart analysis, use the administrator "
                                      "controls, or contact the administrator from the menu.",
                              [("📝 Apply for Access", "assistant_apply", {}),
                               ("💬 Contact Administrator", "assistant_contact", {})])

    async def assistant_begin_contact(self, update):
        user = update.effective_user.id
        if self.db.get(f"assistant:contact_pending:{user}"):
            return await self.say(update, "I’m waiting for your one short question. Send it now, or cancel this request.")
        last_prompt = float(self.db.get(f"assistant:contact_prompt:{user}") or 0)
        if time.time() - last_prompt < 5:
            return await self.say(update, "Please wait a moment before starting another contact request.")
        self.db.put(f"assistant:contact_pending:{user}", True)
        self.db.put(f"assistant:contact_prompt:{user}", time.time())
        return await self.say(update, "Please send one short question for the administrator. Only this requested "
                                      "message will be saved and shared with the administrator. Never include "
                                      "passwords, OTPs, recovery codes, or account credentials.",
                              [("Cancel Contact Request", "assistant_contact_cancel", {})])

    async def assistant_cancel_contact(self, update):
        user = update.effective_user.id
        self.db.put(f"assistant:contact_pending:{user}", False)
        return await self.say(update, "Contact request cancelled. Your saved membership application is unchanged.")

    async def assistant_submit_contact(self, update, text):
        user = update.effective_user.id
        self.db.put(f"assistant:contact_pending:{user}", False)
        if SECRET_LIKE.search(text):
            return await self.say(update, "For your safety, I did not save or forward that message because it may "
                                          "contain account credentials. Please resend your question without "
                                          "passwords, OTPs, or recovery codes.")
        question = safe_text(text, 1000)
        if len(question.strip()) < 3:
            return await self.say(update, "Please send a little more detail, or choose Contact Administrator again.")
        support_api = getattr(self, "support_api", None)
        if support_api is not None:
            try:
                await asyncio.to_thread(
                    support_api.create_case,
                    user,
                    question,
                    getattr(update, "update_id", None),
                )
            except SupportApiError as exc:
                logger.warning("shared_support_case_submit_failed:%s", exc.category)
                return await self.say(
                    update,
                    "⚠️ I couldn’t send your message to the shared Support Portal, so it was not submitted. "
                    "Please start Contact Administrator again and retry later.",
                )
            return await self.say(
                update,
                "✅ Your message has been received by our shared support team. "
                "A team member will reply here.",
            )
        existing = self.db.rows(
            "SELECT id,status FROM assistant_escalations WHERE user_id=? "
            "AND status IN ('open','reply_sending','reply_uncertain') ORDER BY created DESC LIMIT 1",
            (user,),
        )
        if existing:
            return await self.say(
                update,
                "Your message is already in our support queue. "
                "An administrator or support team member will reply here.",
            )
        case_id = uid()
        stamp = now()
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
                "VALUES (?,?,?,'open',?,?)",
                (case_id, user, question, stamp, stamp),
            )
        return await self.say(
            update,
            "✅ Your message has been received by our support team.\n"
            "An administrator or support team member will review it in the Support Portal and reply here.",
        )

    async def assistant_admin_panel(self, update):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        enabled = self.assistant_enabled()
        return await self.say(update, f"🤝 Member Support & FAQs\n\n"
                                      "Member support requests are handled in the Support Portal only. "
                                      "This bot will not notify or display them in this chat.\n\n"
                                      f"Automated topic replies: {'on' if enabled else 'paused'}\n\n"
                                      "Reason shown to members while paused:\n"
                                      f"{self.assistant_inactive_reason()}\n\n"
                                      "This notice is sent only while the bot process is running. "
                                      "A stopped bot cannot receive or answer Telegram messages.",
                              [("📚 FAQ keys and editing", "assistant_faq", {}),
                               ("📋 Recent Errors", "errors", {}),
                               ("📝 Set inactive reason", "assistant_inactive_notice_prompt", {}),
                               ("↩️ Reset inactive reason", "assistant_inactive_notice_reset", {}),
                               (("⏸ Pause topic replies" if enabled else "▶️ Resume topic replies"),
                                "assistant_toggle", {"enabled": not enabled})])

    async def assistant_faq_screen(self, update):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        body = "\n".join(f"• {key}" for key in sorted(FAQS))
        return await self.say(
            update,
            "📚 FAQ responses\n\n" + body + "\n\n"
            "Only the administrator can change these approved responses. Use plain text and never add private "
            "member details or credentials.",
            [("Back to Member Support", "assistant_admin", {})],
        )

    async def assistant_faq_set(self, update, arg):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        match = re.match(r"set\s+([a-z_]+)\s*\|\s*(.+)$", arg, re.IGNORECASE | re.DOTALL)
        if not match:
            return await self.assistant_faq_screen(update)
        key, answer = match.group(1).lower(), safe_text(match.group(2), 1000)
        if key not in FAQS or len(answer.strip()) < 5:
            return await self.say(update, "That FAQ topic is unavailable or the answer is too short. "
                                          "Review the topic list and try again.")
        answers = self.db.get("assistant:faqs") or {}
        answers[key] = answer
        self.db.put("assistant:faqs", answers)
        return await self.say(update, f"✅ The “{key}” FAQ reply was updated.")

    async def assistant_queue(self, update):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        return await self.say(
            update,
            "Member support requests are available in the Support Portal. "
            "Request details are not shown in this Telegram chat.",
        )

    async def assistant_case(self, update, case_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        return await self.say(
            update,
            "Support requests are managed in the Support Portal. "
            "No member message or request details are displayed here.",
        )

    def assistant_reply_pending_key(self, user):
        return f"assistant:reply_pending:{user}"

    async def assistant_reply_start(self, update, case_id):
        user = update.effective_user.id
        self.config.authorize(user, update.effective_chat.type)
        case = self.db.rows(
            "SELECT id,status FROM assistant_escalations WHERE id=?", (case_id,))
        if not case or case[0]["status"] != "open":
            raise ValueError("That support request is not open for a reply.")
        if self.db.draft(user):
            raise ValueError("Finish or cancel your current draft before replying to a member.")
        key = self.assistant_reply_pending_key(user)
        pending = self.db.get(key)
        if pending and pending != case_id:
            return await self.say(
                update, "You already have a reply in progress. Send it or cancel that reply first.",
                [("Cancel Reply", "assistant_reply_cancel", {})], admin_chrome=False)
        self.db.put(key, case_id)
        return await self.say(
            update,
            f"✉️ Reply to support request #{case_id}\n\n"
            "Type one message to send privately to the member. "
            "Your reply will be recorded, and the request will close after successful delivery. "
            "Never include passwords, OTPs, or recovery codes.",
            [("Cancel Reply", "assistant_reply_cancel", {})],
            admin_chrome=False)

    async def assistant_reply_cancel(self, update):
        user = update.effective_user.id
        self.config.authorize(user, update.effective_chat.type)
        self.db.execute("DELETE FROM kv WHERE key=?",
                        (self.assistant_reply_pending_key(user),))
        return await self.say(update, "Reply cancelled. The member’s support request is unchanged.")

    async def assistant_submit_admin_reply(self, update, case_id, text):
        user = update.effective_user.id
        self.config.authorize(user, update.effective_chat.type)
        rows = self.db.rows(
            "SELECT id,status FROM assistant_escalations WHERE id=?", (case_id,))
        if not rows or rows[0]["status"] != "open":
            self.db.execute("DELETE FROM kv WHERE key=?",
                            (self.assistant_reply_pending_key(user),))
            return await self.say(update, "This support request is no longer open. No reply was sent.")
        text = (text or "").strip()
        if len(text) < 3:
            return await self.say(
                update, "Please type a little more detail, or cancel this reply.",
                [("Cancel Reply", "assistant_reply_cancel", {})], admin_chrome=False)
        if len(text) > 3000:
            return await self.say(
                update, "Please keep the reply under 3,000 characters, or cancel this reply.",
                [("Cancel Reply", "assistant_reply_cancel", {})], admin_chrome=False)
        if SECRET_LIKE.search(text):
            return await self.say(
                update, "For safety, remove any passwords, OTPs, or recovery codes before sending.",
                [("Cancel Reply", "assistant_reply_cancel", {})], admin_chrome=False)
        self.db.execute("DELETE FROM kv WHERE key=?",
                        (self.assistant_reply_pending_key(user),))
        return await self.assistant_reply_to_member(update, case_id, text)

    async def assistant_close_case(self, update, case_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        with self.db.transaction() as c:
            c.execute("UPDATE assistant_escalations SET status='closed',updated=? "
                      "WHERE id=? AND status IN ('open','reply_uncertain')", (now(), case_id))
        return await self.assistant_case(update, case_id)

    async def assistant_reply_to_member(self, update, case_id, text):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        rows = self.db.rows("SELECT * FROM assistant_escalations WHERE id=?", (case_id,))
        if not rows or rows[0]["status"] != "open":
            raise ValueError("That request is not open for a reply.")
        case = rows[0]
        profile_name = getattr(update.effective_user, "full_name", "") or " ".join(
            part for part in (
                getattr(update.effective_user, "first_name", ""),
                getattr(update.effective_user, "last_name", ""),
            ) if part
        )
        profile_name = str(profile_name or "").strip()
        responder_name = safe_text(profile_name[:80], 80).strip() if profile_name else "Administrator"
        with self.db.transaction() as c:
            c.execute("UPDATE assistant_escalations SET status='reply_sending',updated=? "
                      "WHERE id=? AND status IN ('open','reply_uncertain')",
                      (now(), case_id))
        try:
            await self.bot.send_message(
                case["user_id"],
                f"💬 VAYDA | Administrator · {responder_name}\n\n" + safe_text(text, 3000),
            )
        except Exception:
            with self.db.transaction() as c:
                c.execute("UPDATE assistant_escalations SET status='reply_uncertain',updated=? "
                          "WHERE id=? AND status='reply_sending'", (now(), case_id))
            return await self.say(update, "⚠️ Telegram did not confirm delivery. The reply is marked uncertain. "
                                          "Check with the member before attempting another reply.")
        with self.db.transaction() as c:
            c.execute("UPDATE assistant_escalations SET status='replied',reply=?,replied_by=?,"
                      "replied_by_name=?,replied_by_staff_id=NULL,updated=? "
                      "WHERE id=? AND status='reply_sending'",
                      (safe_text(text, 3000), update.effective_user.id, responder_name, now(), case_id))
        return await self.say(update, "✅ Your reply was sent privately and recorded.")

    async def assistant_toggle(self, update, enabled):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        self.db.put("assistant:enabled", bool(enabled))
        return await self.assistant_admin_panel(update)


def recover_portal_replies(db):
    """Quarantine sends interrupted by a process restart; never replay them."""
    rows = db.rows("SELECT id,case_id FROM assistant_support_replies WHERE status='sending'")
    if not rows:
        return 0
    stamp = now()
    with db.transaction() as c:
        for row in rows:
            c.execute(
                "UPDATE assistant_support_replies SET status='uncertain',updated=? "
                "WHERE id=? AND status='sending'",
                (stamp, row["id"]),
            )
            c.execute(
                "UPDATE assistant_escalations SET status='reply_uncertain',updated=? "
                "WHERE id=? AND status='reply_sending'",
                (stamp, row["case_id"]),
            )
            c.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "SELECT ?,staff_id,'reply_uncertain',case_id,?,? "
                "FROM assistant_support_replies WHERE id=?",
                (uid(), stamp, "Process restarted during delivery; reply was not replayed.", row["id"]),
            )
    return len(rows)


async def process_portal_reply_once(db, bot):
    """Send one queued staff response; uncertain Telegram results are never retried."""
    with db.transaction() as c:
        suffix = " FOR UPDATE OF r,p SKIP LOCKED" if db.postgres else ""
        rows = c.execute(
            "SELECT r.id,r.case_id,r.staff_id,r.responder_name,r.text,e.user_id,p.role AS responder_role "
            "FROM assistant_support_replies r "
            "JOIN assistant_escalations e ON e.id=r.case_id "
            "JOIN portal_users p ON p.id=r.staff_id "
            "WHERE r.status='queued' AND p.active=TRUE "
            "ORDER BY r.created LIMIT 1" + suffix
        ).fetchall()
        if not rows:
            return False
        reply = rows[0]
        stamp = now()
        if SECRET_LIKE.search(str(reply["text"])):
            c.execute(
                "UPDATE assistant_support_replies SET status='failed',updated=? "
                "WHERE id=? AND status='queued'",
                (stamp, reply["id"]),
            )
            c.execute(
                "UPDATE assistant_escalations SET status='open',updated=? "
                "WHERE id=? AND status='reply_sending'",
                (stamp, reply["case_id"]),
            )
            c.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "VALUES(?,?,?,?,?,?)",
                (uid(), reply["staff_id"], "reply_rejected", reply["case_id"], stamp,
                 "Reply safety validation failed; message was not sent."),
            )
            return True
        updated = c.execute(
            "UPDATE assistant_support_replies SET status='sending',updated=? "
            "WHERE id=? AND status='queued'",
            (stamp, reply["id"]),
        )
        if updated.rowcount != 1:
            return False
    role_label = "Administrator" if reply["responder_role"] == "admin" else "Support"
    responder_name = safe_text(reply["responder_name"], 80).strip()
    responder_label = f"{role_label} · {responder_name}" if responder_name else role_label
    try:
        await asyncio.wait_for(
            bot.send_message(
                chat_id=reply["user_id"],
                text=f"💬 VAYDA | {responder_label}\n\n"
                     f"{safe_text(reply['text'], 3000)}",
            ),
            timeout=20,
        )
    except (Forbidden, BadRequest):
        stamp = now()
        with db.transaction() as c:
            c.execute(
                "UPDATE assistant_support_replies SET status='failed',updated=? "
                "WHERE id=? AND status='sending'",
                (stamp, reply["id"]),
            )
            c.execute(
                "UPDATE assistant_escalations SET status='open',updated=? "
                "WHERE id=? AND status='reply_sending'",
                (stamp, reply["case_id"]),
            )
            c.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "VALUES(?,?,?,?,?,?)",
                (uid(), reply["staff_id"], "reply_failed", reply["case_id"], stamp,
                 "Telegram rejected the private message; it was not retried."),
            )
        return True
    except Exception:
        stamp = now()
        with db.transaction() as c:
            c.execute(
                "UPDATE assistant_support_replies SET status='uncertain',updated=? "
                "WHERE id=? AND status='sending'",
                (stamp, reply["id"]),
            )
            c.execute(
                "UPDATE assistant_escalations SET status='reply_uncertain',updated=? "
                "WHERE id=? AND status='reply_sending'",
                (stamp, reply["case_id"]),
            )
            c.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "VALUES(?,?,?,?,?,?)",
                (uid(), reply["staff_id"], "reply_uncertain", reply["case_id"], stamp,
                 "Telegram delivery was uncertain; automatic retry is disabled."),
            )
        db.error("portal_reply_uncertain",
                 "A staff reply may or may not have reached Telegram; no retry was attempted.")
        return True
    stamp = now()
    with db.transaction() as c:
        c.execute(
            "UPDATE assistant_support_replies SET status='sent',updated=? "
            "WHERE id=? AND status='sending'",
            (stamp, reply["id"]),
        )
        c.execute(
            "UPDATE assistant_escalations SET status='replied',reply=?,replied_by=NULL,"
            "replied_by_name=?,replied_by_staff_id=?,updated=? "
            "WHERE id=? AND status='reply_sending'",
            (safe_text(reply["text"], 3000), safe_text(reply["responder_name"], 80),
             reply["staff_id"], stamp, reply["case_id"]),
        )
        c.execute(
            "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
            "VALUES(?,?,?,?,?,?)",
            (uid(), reply["staff_id"], "reply_sent", reply["case_id"], stamp, reply["id"]),
        )
    return True


async def run_portal_reply_worker(db, bot, stop_event, support_api=None):
    """Outbox worker attached to the current bot instance and its isolated database."""
    if support_api is not None:
        await run_shared_support_reply_worker(
            support_api, bot, stop_event, permanent_errors=(Forbidden, BadRequest))
        return
    recover_portal_replies(db)
    while not stop_event.is_set():
        try:
            found = await process_portal_reply_once(db, bot)
            if not found:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                db.error("portal_reply_worker",
                         "The support reply worker failed; it will retry the queue check.")
            except Exception:
                pass
            await asyncio.sleep(5)
