import asyncio
import json
import re
import time
from html import escape
from urllib.parse import urlsplit
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .database import now, uid
from .domain import safe_text
from .applicant_followups import (
    followup_schema_available,
    mark_notice_shown,
    record_applicant_activity,
    set_followup_status,
)

MEMBER_WELCOME_TEXT = """👋 <b>WELCOME TO VAYDA SMART MONEY HUB</b>

Welcome! Choose an option from the menu or type your question to get guidance on member access and application updates.

📚 <b>EDUCATION</b> — Self-service access
📊 <b>MARKET ANALYSIS</b> — Separate application and review
💎 <b>PRO SIGNALS</b> — Separate application and eligibility review

🔐 <b>MEMBER ACCESS</b>
Open Member Access to select your preferred destination and follow the relevant application process.

ℹ️ <b>APPLICATION NOTICE</b>
If you have a previous general application on file, it does not automatically grant access to a specific destination. Each destination has its own access requirements and review process.

⚠️ <b>TRADING RISK DISCLOSURE</b>
This bot provides information and access guidance only. It does not place trades or guarantee profits. Trading involves risk, and you may lose some or all of your trading capital.

━━━━━━━━━━━━━━━━━━

💰 <b>PRO SIGNALS — PROFITS &amp; FUNDING POLICY</b>

✅ <b>Your profits belong to you.</b>
VAYDA Smart Money Hub does not take a share of your trading profits.

🏦 <b>Withdrawals</b>
You may request withdrawals through Exness at any time, subject to Exness policies, account conditions, and applicable processing requirements.

📊 <b>Maintaining Eligibility</b>
• Keep sufficient funds available for your own trading activities and financial circumstances.
• There is no fixed account-balance threshold automatically applied by the bot.
• An administrator reviews updated balance evidence on a case-by-case basis.
• Additional evidence may be requested during the review process.

🔎 <b>IMPORTANT REVIEW GUIDELINES</b>
• Submitting a screenshot does not guarantee approval or automatic removal of access restrictions.
• PRO Signals access may be declined or withdrawn following an administrator’s eligibility review.
• Never share your account password, OTP, recovery codes, or other login credentials.
• Never deposit money solely to qualify for PRO Signals. Only fund or trade an account when it is appropriate for your financial situation and risk tolerance.

🔒 <b>FINAL NOTICE</b>
All access decisions remain subject to the applicable review process. Please ensure that any information submitted is accurate and up to date.

<b>VAYDA SMART MONEY HUB</b>
Trade with discipline. Manage risk. No confirmation, no entry."""

EDUCATION_WELCOME_TEXT = """🎉 Welcome to the Educational Group!

Your Educational Group invite is ready. Joining is optional. We’re glad to have you here.

📚 Learn with our education community

Explore market structure, liquidity, order blocks, fair value gaps, BOS/CHoCH, risk management, and how to wait for confirmation before entry. Learn through educational materials, chart breakdowns, video lessons, and practice.

Joining is optional. Education supports learning; it does not guarantee profits or trading success.

Remember: NO CONFIRMATION, NO ENTRY.

👇 Tap below if you’d like to join."""

PRO_ACCESS_GUIDE = """🔐 <b>PRO SIGNALS ACCESS</b> 🎯

Welcome to the next level of your trading journey! 📈

Access to <b>PRO Signals</b> is subject to a separate review. Please follow the steps below carefully.

📝 <b>HOW TO APPLY</b>

1️⃣ Register using the official Exness button provided by the bot.

2️⃣ Submit your registration for review.

3️⃣ Privately provide evidence of your initial funding, or updated funding evidence if requested.

4️⃣ An administrator will review your submission and make the final decision on PRO access.

⚠️ <b>SECURITY FIRST</b>
Never share your trading password, OTP, recovery codes, or other sensitive login credentials. Your evidence should be shared privately through the approved process.

💰 <b>PRO PROFITS &amp; FUNDING — IMPORTANT</b>

✅ <b>Your profits belong to you.</b> We do not take a share of your trading profits.

🏦 <b>Withdrawals:</b> You may request withdrawals through Exness at any time, subject to Exness policies, account conditions, and processing requirements.

📊 <b>Maintaining eligibility:</b> Keep sufficient funds available for your trading activity. There is no fixed balance threshold applied by the bot. An administrator reviews updated balance evidence on a case-by-case basis.

🔎 <b>Please note:</b>

• Updated evidence may be requested during a review.
• Submitting a screenshot does not automatically remove or approve anyone.
• PRO access may be declined if the administrator determines that eligibility requirements are no longer met.
• <b>Never deposit money solely to qualify for PRO Signals.</b> Only trade or fund an account according to your financial situation and risk tolerance.

🎯 <b>OUR STANDARD</b>

We value transparency, responsible trading, account security, and disciplined execution.

Learn • Confirm • Execute • Grow 🚀"""

PRO_ACCESS_REMINDER = (
    "💰 <b>PRO PROFITS &amp; FUNDING — IMPORTANT</b>\n\n"
    "✅ <b>Your profits belong to you.</b> We do not take a share of your trading profits.\n\n"
    "🏦 <b>Withdrawals:</b> You may request withdrawals through Exness at any time, subject to Exness policies, "
    "account conditions, and processing requirements.\n\n"
    "📊 <b>Maintaining eligibility:</b> Keep sufficient funds available for your trading activity. There is no fixed "
    "balance threshold applied by the bot. An administrator reviews updated balance evidence case by case.\n\n"
    "🔎 <b>Please note:</b>\n"
    "• Updated evidence may be requested during a review.\n"
    "• Submitting a screenshot does not automatically remove or approve anyone.\n"
    "• PRO access may be declined if the administrator determines that eligibility requirements are no longer met.\n"
    "• <b>Never deposit money solely to qualify for PRO Signals.</b> Only trade or fund an account according to your "
    "financial situation and risk tolerance."
)


QUESTIONS = [
    "What is your trading experience? Beginners are welcome.",
    "Which markets are you interested in?",
    "How do you approach the risk of losing money when trading?",
    "How do you decide when confirmation is strong enough to enter?",
    "How will you manage risk and avoid revenge trading?",
]

PRO_SCREENING_QUESTIONS = [
    "Do you understand that PRO Signals access is subject to eligibility checks and admin approval?",
    "Are you committed to following our trading guidelines, including proper risk management?",
    "Are you prepared to complete the required verification process before access can be granted?",
]
PRO_SCREENING_ANSWER_LABELS = (
    ("✅ Yes, I understand.", "❌ No."),
    ("✅ Yes, I agree.", "❌ No."),
    ("✅ Yes, I’m ready.", "⏳ Not yet."),
)
PRO_SUBMISSION_NOTICE = (
    "⚠️ Submitting this application does not guarantee approval. PRO Signals access is granted only after "
    "the required verification and admin review are completed. Trading involves risk, and profits are not guaranteed."
)

DESTINATION_LABELS = {
    "education": "Educational Group",
    "analysis": "Market Analysis",
    "pro": "PRO Signals",
}
_CREDENTIAL_FIELD = re.compile(
    r"(?i)\b(password|passcode|one[- ]time code|otp|recovery code|seed phrase|private key|login credentials)"
    r"\s*(?:[:=]|\bis\b)\s*\S+"
)


def safe_application_answer(value, limit=700):
    text = safe_text(value, limit)
    if _CREDENTIAL_FIELD.search(text):
        raise ValueError("Please remove passwords, OTPs, recovery codes, and login details. The bot will not store them.")
    return text


def application_prompt(index):
    return f"📝 Access application · {index + 1}/{len(QUESTIONS)}\n\n{QUESTIONS[index]}"


def application_status_label(status):
    return {"pending": "older general application awaiting review",
            "approved": "older general application on file; it does not approve a specific destination",
            "rejected": "older general application was not approved",
            "destination_applicant": "destination requests on file"}.get(
        status, status.replace("_", " "))


def pro_status_label(request):
    status = request.get("status")
    if status == "approved" and request.get("funding_status") == "pending_review":
        return "APPROVED — UPDATED BALANCE UNDER REVIEW"
    return {
        "approved": "APPROVED",
        "revoked": "REVOKED",
        "information_requested": "MORE_INFORMATION_REQUIRED",
        "not_yet_eligible": "NOT_YET_ELIGIBLE",
        "rejected": "REJECTED",
        "awaiting_registration": "NOT_YET_ELIGIBLE",
        "pending_review": "PENDING_REVIEW",
        "legacy_review": "PENDING_REVIEW",
    }.get(status, str(status or "PENDING_REVIEW").upper())


def pro_registration_approved(value):
    return value in ("approved", "verified")


def pro_education_entitled(request):
    return (request.get("destination") == "pro"
            and request.get("status") not in ("rejected", "revoked")
            and pro_registration_approved(request.get("registration_status")))


class MemberFlows:
    def ensure_legacy_pro_review(self):
        """Flag existing PRO access for review without revoking membership or invites."""
        if not self.config.admin or not self.config.signals:
            return
        rows = self.db.rows(
            "SELECT a.user_id,app.answers FROM access a LEFT JOIN applications app ON app.user_id=a.user_id "
            "WHERE a.channel=? AND a.status IN "
            "('invite_pending','invite_issued','invite_uncertain','joined','member','administrator','creator')",
            (self.config.signals,))
        for row in rows:
            request_id = f"legacy-pro-{row['user_id']}"
            exists = self.db.rows("SELECT id FROM member_requests WHERE id=?", (request_id,))
            if exists:
                continue
            answers = row.get("answers") or "[]"
            self.db.execute(
                "INSERT INTO member_requests "
                "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (request_id, row["user_id"], "pro", answers, "legacy_review",
                 "unverified", "unverified", "legacy", now(), now()))
            self.db.execute(
                "INSERT INTO member_request_events(request_id,actor,action,detail,created) VALUES (?,?,?,?,?)",
                (request_id, self.config.admin, "legacy_access_flagged",
                 "Existing PRO access flagged for manual eligibility review; no access was revoked.", now()))

    def member_request_event(self, request_id, actor, action, detail=""):
        self.db.execute(
            "INSERT INTO member_request_events(request_id,actor,action,detail,created) VALUES (?,?,?,?,?)",
            (request_id, actor, action, detail[:400], now()))
        request_rows = self.db.rows(
            "SELECT user_id,destination FROM member_requests WHERE id=?", (request_id,))
        if not request_rows:
            return
        request = request_rows[0]
        if action == "more_information_requested":
            record_applicant_activity(
                self.db, self.config, request["user_id"], "information_requested",
                request["destination"], source="administrator_decision")
        elif action in ("destination_approved", "pro_final_approval",
                        "pro_two_stage_access_granted",
                        "self_service_access_granted", "self_service_invite_requested"):
            record_applicant_activity(
                self.db, self.config, request["user_id"], "membership_check",
                request["destination"], source="access_progress")
        elif action in ("request_rejected", "pro_not_yet_eligible", "access_disapproved"):
            if followup_schema_available(self.db):
                rows = self.db.rows(
                    "SELECT user_id FROM applicant_followup_state WHERE user_id=?",
                    (request["user_id"],))
                if rows:
                    set_followup_status(
                        self.db, request["user_id"], "completed", "application_decision_closed")

    def pro_requirement_guidance(self, request):
        registration = request.get("registration_status")
        funding = request.get("funding_status")
        evidence = bool(request.get("evidence_file_id"))
        lines = []
        if pro_registration_approved(registration):
            lines.append("• <b>PRO registration:</b> APPROVED by the administrator.")
            lines.append("• <b>PRO education:</b> unlocked by registration approval only.")
        elif registration == "pending_review":
            lines.append("• <b>Registration:</b> awaiting administrator review. A pending check is not a rejection.")
        elif registration == "rejected":
            lines.append("• <b>Registration:</b> REJECTED by the administrator.")
        elif registration == "unverified":
            lines.append("• <b>Registration:</b> not verified yet. If your circumstances have changed, submit it for another review.")
        else:
            lines.append("• <b>Registration:</b> not submitted. If you choose to continue, use the registration button and then request verification.")

        if funding == "verified":
            lines.append("• <b>Funded-account verification:</b> VERIFIED by the administrator.")
        elif funding == "pending_review":
            pending = "• <b>Funded-account verification:</b> PENDING administrator review. A pending check is not a rejection."
            if request.get("status") == "approved":
                pending += " Your existing PRO access remains unchanged during this review."
            lines.append(pending)
        elif funding == "rejected":
            lines.append("• <b>Funded-account verification:</b> REJECTED. You may submit updated evidence for review.")
        elif evidence or funding == "unverified":
            lines.append("• <b>Funded-account verification:</b> not verified yet. Submit evidence privately for administrator review.")
        else:
            lines.append("• <b>Funded-account verification:</b> NOT_SUBMITTED. Registration approval alone does not grant PRO Signals access.")

        if pro_education_entitled(request):
            lines.append("• <b>PRO Signals access:</b> remains locked until funded-account verification is VERIFIED.")
        elif request.get("status") == "approved" and funding == "pending_review":
            lines.append("• <b>PRO Signals access:</b> existing access is preserved during an update review.")
        lines.append("<b>Security:</b> Never send passwords, OTPs, recovery codes, or account login details.")
        return "\n".join(lines)

    def pro_alternative_specs(self, request_id):
        return [
            ("Request Educational Group access", "member_pro_alternative",
             {"request_id": request_id, "choice": "education"}),
            ("Request Market Analysis access", "member_pro_alternative",
             {"request_id": request_id, "choice": "analysis"}),
            ("Request both", "member_pro_alternative", {"request_id": request_id, "choice": "both"}),
            ("Check PRO eligibility again", "member_pro_recheck", {"request_id": request_id}),
        ]

    def pro_outcome_text(self, request, status=None, decision_note=None):
        display_status = status or pro_status_label(request)
        note = (f"\n\n<b>Administrator's note:</b> {escape(str(decision_note).strip())}"
                if decision_note and str(decision_note).strip() else "")
        return (
            "🔐 <b>PRO SIGNALS APPLICATION UPDATE</b>\n\n"
            f"<b>Status:</b> {escape(display_status)}\n\n"
            f"{self.pro_requirement_guidance(request)}\n\n"
            "Need a different destination? Open <b>Member Access</b> from the main menu to join the "
            "Educational Group or apply for Market Analysis. Each destination follows its own access rules. "
            "There is no pressure to make a deposit."
            f"{note}\n\n"
            f"{PRO_ACCESS_REMINDER}"
        )

    def pro_outcome_specs(self, request):
        request_id = request["id"]
        if request.get("status") in ("rejected", "not_yet_eligible"):
            return self.pro_alternative_specs(request_id)
        if request.get("registration_status") == "pending_review" or \
                request.get("funding_status") == "pending_review":
            return [("View application status", "member_status", {})]
        if not pro_registration_approved(request.get("registration_status")):
            return [("Continue PRO registration", "member_pro_registration",
                     {"request_id": request_id})]
        elif request.get("funding_status") != "verified":
            return [("Submit funding evidence", "member_funding_evidence",
                     {"request_id": request_id})]
        return [("Request another PRO review", "member_pro_recheck",
                 {"request_id": request_id})]

    def pro_outcome_buttons(self, user, request):
        return InlineKeyboardMarkup([[self.button(user, label, action, data)]
                                     for label, action, data in self.pro_outcome_specs(request)])

    async def send_pro_outcome(self, request, status=None, decision_note=None):
        user = request["user_id"]
        text = self.pro_outcome_text(request, status, decision_note)
        try:
            await self.bot.send_message(
                user, text, reply_markup=self.pro_outcome_buttons(user, request), parse_mode="HTML")
            return True
        except Exception:
            try:
                self.db.error("pro_outcome_notification",
                              "A PRO application outcome was saved, but its private notification could not be confirmed.")
            except Exception:
                pass
            return False

    async def send_portal_funding_evidence_request(self, request, reason):
        user = request["user_id"]
        text = (
            "🔎 <b>UPDATED FUNDING EVIDENCE REQUESTED</b>\n\n"
            "An administrator has requested updated funding evidence for your PRO Signals review. "
            "Please submit one current screenshot privately using the button below."
        )
        if request.get("status") == "approved":
            text += "\n\nYour existing PRO access remains unchanged while this review is pending."
        if reason and str(reason).strip():
            text += f"\n\n<b>Administrator's note:</b> {escape(str(reason).strip())}"
        text += "\n\nNever send passwords, OTPs, recovery codes, or account login details."
        try:
            await self.bot.send_message(
                user,
                text,
                reply_markup=InlineKeyboardMarkup([[
                    self.button(user, "Submit updated funding evidence", "member_funding_evidence",
                                {"request_id": request["id"]})
                ]]),
                parse_mode="HTML",
            )
            return True
        except Exception:
            try:
                self.db.error(
                    "pro_evidence_request_notification",
                    "An updated funding evidence request was saved, but private delivery could not be confirmed.",
                )
            except Exception:
                pass
            return False

    async def send_portal_pro_registration_notice(self, user, reason="", request_id=None):
        text = (
            "✅ <b>PRO REGISTRATION APPROVED</b>\n\n"
            "Your registration approval unlocks PRO education only. It does not grant PRO Signals channel access. "
            "That requires a separate administrator-verified funded-account status.\n\n"
        )
        text += (
            "Your PRO education entitlement is saved. Lesson delivery remains turned off until onboarding is ready. "
            "No PRO Signals invite was created."
        )
        buttons = [[self.button(user, "Submit Funded-Account Evidence", "member_funding_evidence",
                                {"request_id": request_id})]] if request_id else None
        if reason and str(reason).strip():
            text += f"\n\n<b>Administrator note:</b> {escape(str(reason).strip())}"
        try:
            await self.bot.send_message(
                user, text, reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                parse_mode="HTML")
            return True
        except Exception:
            try:
                self.db.error(
                    "pro_registration_notification",
                    "PRO education eligibility was saved, but its private notification could not be confirmed.",
                )
            except Exception:
                pass
            return False

    async def send_portal_funding_verified_notice(self, user, *, registration_approved, reason=""):
        if registration_approved:
            text = (
                "✅ <b>FUNDED-ACCOUNT VERIFICATION RECORDED</b>\n\n"
                "Your funded-account status is verified. Existing PRO Signals access was not changed by this update."
            )
        else:
            text = (
                "✅ <b>FUNDED-ACCOUNT VERIFICATION RECORDED</b>\n\n"
                "Your funded-account status is verified. Registration approval is still required before PRO education "
                "or PRO Signals access can be unlocked."
            )
        if reason and str(reason).strip():
            text += f"\n\n<b>Administrator note:</b> {escape(str(reason).strip())}"
        try:
            await self.bot.send_message(user, text, parse_mode="HTML")
            return True
        except Exception:
            try:
                self.db.error(
                    "pro_funding_notification",
                    "Funding verification was saved, but its private notification could not be confirmed.",
                )
            except Exception:
                pass
            return False

    async def send_portal_funding_rejected_notice(self, user, reason=""):
        text = (
            "⚠️ <b>FUNDED-ACCOUNT EVIDENCE NOT VERIFIED</b>\n\n"
            "The administrator could not verify the submitted evidence. PRO Signals access remains locked. "
            "Registration-approved education access, if already granted, remains separate."
        )
        if reason and str(reason).strip():
            text += f"\n\n<b>Administrator note:</b> {escape(str(reason).strip())}"
        try:
            await self.bot.send_message(user, text, parse_mode="HTML")
            return True
        except Exception:
            try:
                self.db.error(
                    "pro_funding_notification",
                    "Funding evidence rejection was saved, but its private notification could not be confirmed.",
                )
            except Exception:
                pass
            return False

    async def send_portal_pro_registration_rejected_notice(self, user, reason=""):
        text = (
            "⚠️ <b>PRO REGISTRATION NOT APPROVED</b>\n\n"
            "Your registration was not approved. PRO education eligibility remains locked. "
            "Any existing channel membership is handled separately and was not automatically removed."
        )
        if reason and str(reason).strip():
            text += f"\n\n<b>Administrator note:</b> {escape(str(reason).strip())}"
        try:
            await self.bot.send_message(user, text, parse_mode="HTML")
            return True
        except Exception:
            try:
                self.db.error(
                    "pro_registration_notification",
                    "Registration rejection was saved, but its private notification could not be confirmed.",
                )
            except Exception:
                pass
            return False

    async def send_portal_pro_approval_notice(self, user, invite_link=None):
        if invite_link:
            text = (
                "✅ <b>PRO SIGNALS ACCESS APPROVED</b>\n\n"
                "Your application has been approved. Use the secure button below to open your invite. "
                "The invite expires after 24 hours and must not be forwarded.\n\n"
                "Never share passwords, OTPs, or recovery codes."
            )
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("Join PRO Signals", url=invite_link)
            ]])
        else:
            text = (
                "✅ <b>PRO SIGNALS ACCESS APPROVED</b>\n\n"
                "Your PRO Signals access is already active. No duplicate invite was created."
            )
            markup = None
        try:
            await self.bot.send_message(user, text, reply_markup=markup, parse_mode="HTML")
            return True
        except Exception:
            try:
                self.db.error(
                    "pro_approval_notification",
                    "PRO access was approved, but private invite delivery could not be confirmed.",
                )
            except Exception:
                pass
            return False

    async def show_pro_outcome(self, update, request):
        return await self.say(update, self.pro_outcome_text(request),
                              self.pro_outcome_specs(request), parse_mode="HTML")

    def _pro_request_for_user(self, user, request_id):
        request = self.member_request(request_id)
        if not request or request["user_id"] != user or request["destination"] != "pro":
            raise PermissionError("This PRO application is not available.")
        return request

    async def member_pro_alternative(self, update, request_id, choice):
        user = update.effective_user.id
        request = self._pro_request_for_user(user, request_id)
        if request["status"] not in ("rejected", "not_yet_eligible", "awaiting_registration"):
            return await self.say(
                update, "🔐 <b>PRO SIGNALS APPLICATION STATUS</b>\n\n"
                f"<b>Status:</b> {escape(pro_status_label(request))}\n\n"
                "A pending review is not a rejection. Check My Access / Applications for updates.",
                parse_mode="HTML")
        if choice not in ("education", "analysis", "both"):
            raise ValueError("Choose a listed alternative access option.")
        if self.db.draft(user):
            return await self.say(update, "Finish or cancel your current application step before starting another.")

        if choice != "both":
            if choice == "education":
                button, note = await self.education_join_button(update)
                if not button:
                    return await self.say(update, note)
            existing = self.latest_member_request(user, choice) if choice != "education" else None
            if existing and existing["status"] not in ("rejected",):
                return await self.say(update, f"You already have a {DESTINATION_LABELS[choice]} request "
                                              f"({existing['status'].replace('_', ' ')}). "
                                              "No duplicate application or invite was created.")
            self.member_request_event(request_id, user, "alternative_access_requested", choice)
            return await self.begin_destination_application(update, choice)

        destinations = ["education", "analysis"]
        queued, unavailable = [], []
        for destination in destinations:
            if destination == "education":
                education_button, education_note = await self.education_join_button(update)
                if not education_button:
                    unavailable.append(education_note)
                    continue
            existing = self.latest_member_request(user, destination)
            if existing and existing["status"] != "rejected":
                unavailable.append(
                    f"{DESTINATION_LABELS[destination]} already has a request ({existing['status'].replace('_', ' ')}).")
                continue
            queued.append(destination)
        if not queued:
            return await self.say(update, "No new access application was started. " +
                                  " ".join(unavailable or ["Both requests are already on file."]))
        self.member_request_event(request_id, user, "alternative_access_requested", "both")
        self.db.put(f"member:alternative_queue:{user}", {
            "pro_request_id": request_id,
            "remaining": queued,
            "unavailable": unavailable,
        })
        await self.member_pro_alternative_next(update, request_id)
        if unavailable:
            await self.say(update, "These destinations still require separate applications and reviews. " +
                           " ".join(unavailable))

    async def member_pro_alternative_next(self, update, request_id):
        user = update.effective_user.id
        self._pro_request_for_user(user, request_id)
        key = f"member:alternative_queue:{user}"
        queue = self.db.get(key)
        if not isinstance(queue, dict) or queue.get("pro_request_id") != request_id:
            return await self.say(update, "There is no combined access request waiting. Use the PRO outcome buttons again.")
        if self.db.draft(user):
            return await self.say(update, "Finish or cancel the current application step before continuing.")
        remaining = list(queue.get("remaining", []))
        while remaining:
            destination = remaining[0]
            existing = self.latest_member_request(user, destination)
            if existing and existing["status"] != "rejected":
                remaining.pop(0)
                queue["remaining"] = remaining
                self.db.put(key, queue)
                continue
            await self.begin_destination_application(update, destination)
            remaining.pop(0)
            queue["remaining"] = remaining
            self.db.put(key, queue)
            if destination == "education":
                continue
            return
        self.db.execute("DELETE FROM kv WHERE key=?", (key,))
        return await self.say(update, "Both destination requests are already on file or unavailable. "
                                      "No extra access was granted.")

    async def member_pro_alternative_cancel(self, update):
        user = update.effective_user.id
        self.db.execute("DELETE FROM kv WHERE key=?", (f"member:alternative_queue:{user}",))
        self.db.clear_draft(user)
        return await self.say(update, "The alternative-access sequence was cancelled. "
                                      "No access was granted.")

    async def member_pro_recheck(self, update, request_id):
        user = update.effective_user.id
        request = self._pro_request_for_user(user, request_id)
        status = request["status"]
        if status == "approved":
            update_note = (" Your existing PRO access remains unchanged while the updated balance is reviewed."
                           if request["funding_status"] == "pending_review" else
                           " Your PRO Signals access decision is already recorded.")
            return await self.say(
                update, f"🔐 <b>PRO SIGNALS APPLICATION STATUS</b>\n\n"
                f"<b>Status:</b> {escape(pro_status_label(request))}.{update_note}\n\n{PRO_ACCESS_REMINDER}",
                parse_mode="HTML")
        if status == "information_requested":
            return await self.say(update, "🔐 <b>PRO SIGNALS APPLICATION STATUS</b>\n\n"
                                          "<b>Status:</b> MORE_INFORMATION_REQUIRED\n\n"
                                          "Please use the Reply to administrator button and send the requested "
                                          "information privately.",
                                  [("Reply to administrator", "member_more_info", {"request_id": request_id})],
                                  parse_mode="HTML")
        if status in ("pending_review", "legacy_review"):
            return await self.say(update, "🔐 <b>PRO SIGNALS APPLICATION STATUS</b>\n\n"
                                          "<b>Status:</b> PENDING_REVIEW\n\n"
                                          "The administrator is still reviewing your application. A pending "
                                          "verification is not a rejection.", parse_mode="HTML")
        if status not in ("rejected", "not_yet_eligible", "awaiting_registration"):
            raise ValueError("This PRO application cannot be checked again yet.")
        if request["registration_status"] == "pending_review" or request["funding_status"] == "pending_review":
            stamp = now()
            with self.db.transaction() as c:
                result = c.execute(
                    "UPDATE member_requests SET status='pending_review',admin_decision_by=NULL,"
                    "admin_decision_at=NULL,updated=? WHERE id=? AND status IN "
                    "('rejected','not_yet_eligible','awaiting_registration')",
                    (stamp, request_id))
                if result.rowcount != 1:
                    raise ValueError("This PRO application changed. Check its current status.")
            self.member_request_event(request_id, user, "pro_recheck_pending",
                                      "Applicant asked for a status check while verification remained pending.")
            return await self.say(update, "🔐 <b>PRO SIGNALS APPLICATION STATUS</b>\n\n"
                                          "<b>Status:</b> PENDING_REVIEW\n\n"
                                          "Verification is still in progress; this is not a rejection.",
                                  parse_mode="HTML")
        if not pro_registration_approved(request["registration_status"]):
            stamp = now()
            with self.db.transaction() as c:
                result = c.execute(
                    "UPDATE member_requests SET status='awaiting_registration',admin_decision_by=NULL,"
                    "admin_decision_at=NULL,updated=? WHERE id=? AND status IN "
                    "('rejected','not_yet_eligible','awaiting_registration')",
                    (stamp, request_id))
                if result.rowcount != 1:
                    raise ValueError("This PRO application changed. Check its current status.")
            self.member_request_event(request_id, user, "pro_recheck_registration",
                                      "Applicant requested another registration review.")
            refreshed = self.member_request(request_id)
            await self.send_pro_outcome(refreshed, "NOT_YET_ELIGIBLE")
            return
        if request["funding_status"] != "verified":
            stamp = now()
            with self.db.transaction() as c:
                result = c.execute(
                    "UPDATE member_requests SET status='not_yet_eligible',admin_decision_by=NULL,"
                    "admin_decision_at=NULL,updated=? WHERE id=? AND status IN "
                    "('rejected','not_yet_eligible','awaiting_registration')",
                    (stamp, request_id))
                if result.rowcount != 1:
                    raise ValueError("This PRO application changed. Check its current status.")
            self.member_request_event(request_id, user, "pro_recheck_funding",
                                      "Applicant requested another funding-evidence review.")
            refreshed = self.member_request(request_id)
            return await self.send_pro_outcome(refreshed, "NOT_YET_ELIGIBLE")
        stamp = now()
        with self.db.transaction() as c:
            result = c.execute(
                "UPDATE member_requests SET status='pending_review',admin_decision_by=NULL,"
                "admin_decision_at=NULL,updated=? WHERE id=? AND status IN "
                "('rejected','not_yet_eligible','awaiting_registration')",
                (stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("This PRO application changed. Check its current status.")
        self.member_request_event(request_id, user, "pro_recheck_requested",
                                  "Applicant requested a new administrator review.")
        await self.notify_member_request(
            request_id, "🔎 <b>PRO REVIEW REQUESTED</b>\n\n"
            "Applicant requested another PRO eligibility review.", parse_mode="HTML")
        return await self.say(update, "🔐 <b>PRO SIGNALS APPLICATION STATUS</b>\n\n"
                                      "<b>Status:</b> PENDING_REVIEW\n\n"
                                      "Your request for another administrator review was recorded. Access is not "
                                      "granted until the administrator confirms approval.", parse_mode="HTML")

    def _pro_has_pending_verification(self, request):
        return (request["destination"] == "pro" and
                (request["registration_status"] == "pending_review" or
                 request["funding_status"] == "pending_review"))

    async def member_pro_not_eligible_prompt(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["destination"] != "pro" or request["status"] != "pending_review":
            raise ValueError("This PRO application is not ready for an eligibility decision.")
        if self._pro_has_pending_verification(request):
            raise ValueError("Verification is pending. Keep the status as PENDING_REVIEW; do not mark it ineligible.")
        if pro_registration_approved(request["registration_status"]) and request["funding_status"] == "verified":
            raise ValueError("Both PRO requirements are verified. Use the separate final approval review.")
        return await self.say(
            update,
            "⚠️ <b>PRO ELIGIBILITY REVIEW</b>\n\n"
            "Confirm marking this application <b>NOT_YET_ELIGIBLE</b>? This is not a rejection. "
            "The applicant will see the unmet steps and may request another review later.\n\n" +
            self.pro_requirement_guidance(request),
            [("Confirm Not Yet Eligible", "member_pro_not_eligible_confirm", {"request_id": request_id}),
             ("Back to Request", "member_request", {"request_id": request_id})],
            parse_mode="HTML")

    async def member_pro_not_eligible_confirm(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["destination"] != "pro" or request["status"] != "pending_review":
            raise ValueError("This PRO application changed. Review its current status.")
        if self._pro_has_pending_verification(request):
            raise ValueError("Verification is pending. Keep the status as PENDING_REVIEW.")
        if pro_registration_approved(request["registration_status"]) and request["funding_status"] == "verified":
            raise ValueError("Both requirements are met; use the existing PRO access workflow.")
        stamp = now()
        with self.db.transaction() as c:
            result = c.execute(
                "UPDATE member_requests SET status='not_yet_eligible',admin_decision_by=?,"
                "admin_decision_at=?,updated=? WHERE id=? AND destination='pro' AND status='pending_review' "
                "AND registration_status!='pending_review' AND funding_status!='pending_review' "
                "AND NOT (registration_status IN ('approved','verified') AND funding_status='verified')",
                (self.config.admin, stamp, stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("This PRO application changed. Review its current status.")
        current = self.member_request(request_id)
        self.member_request_event(request_id, self.config.admin, "pro_not_yet_eligible",
                                  "Administrator marked the application not yet eligible; unmet requirements remain.")
        delivered = await self.send_pro_outcome(current, "NOT_YET_ELIGIBLE")
        return await self.say(update, "✅ <b>NOT_YET_ELIGIBLE RECORDED</b>\n\n" +
                              ("The applicant was notified privately." if delivered else
                               "The private notification could not be confirmed; check Recent Errors."),
                              parse_mode="HTML")

    def member_request(self, request_id):
        rows = self.db.rows("SELECT * FROM member_requests WHERE id=?", (request_id,))
        return rows[0] if rows else None

    def latest_member_request(self, user, destination):
        rows = self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=? AND destination=? "
            "ORDER BY updated DESC,created DESC LIMIT 1", (user, destination))
        return rows[0] if rows else None

    async def notify_member_request(self, request_id, text, parse_mode=None):
        request = self.member_request(request_id)
        if not request:
            return
        try:
            await self.bot.send_message(
                self.config.admin, text, parse_mode=parse_mode,
                reply_markup=InlineKeyboardMarkup([[
                    self.button(self.config.admin, "Review request", "member_request",
                                {"request_id": request_id})
                ]]))
        except Exception:
            self.db.error("member_request_notification",
                          "An administrator could not be notified about a member request.")

    async def education_join_button(self, update):
        if self.config.education_group_id:
            access = self.db.rows(
                "SELECT status FROM access WHERE user_id=? AND channel=?",
                (update.effective_user.id, self.config.education_group_id))
            if access and access[0]["status"] in (
                    "disapproval_pending", "access_revoked", "kicked"):
                return None, "Educational Group access was removed. Contact the administrator for a review."
        link = (self.config.education_link or "").strip()
        if not link:
            return None, "The Educational Group link is not configured for this bot."
        try:
            parsed = urlsplit(link)
            valid = (parsed.scheme == "https" and bool(parsed.netloc) and
                     parsed.username is None and parsed.password is None)
        except ValueError:
            valid = False
        if not valid:
            self.db.error("education_link_invalid",
                          "Configured Education link is not a valid HTTPS URL.")
            return None, "The configured Educational Group link is invalid. Contact the administrator."
        if getattr(self.config, "education_onboarding_enabled", False):
            return ("Start Education", "education_onboarding_start", {}), ""
        return ("Join Educational Group", "assistant_url", {"url": link}), ""

    async def request_destination_selection(self, update):
        if update.effective_chat.type == "private":
            record_applicant_activity(
                self.db, self.config, update.effective_user.id,
                "choosing_destination", source="member_access_menu")
        buttons = []
        education_button, education_note = await self.education_join_button(update)
        if education_button:
            buttons.append(education_button)
        buttons.extend([
            ("Apply for Market Analysis", "member_apply_dest", {"destination": "analysis"}),
            ("Apply for PRO Signals", "member_apply_dest", {"destination": "pro"}),
        ])
        if education_button:
            education_action_text = (
                "Start Education below, then join the private group and verify membership. "
                if getattr(self.config, "education_onboarding_enabled", False) else
                "Join directly using the button below — no application or approval is needed. "
            )
            education_text = (
                "📚 <b>Educational Group</b>\n"
                "Trading lessons, chart breakdowns, and learning materials.\n"
                + education_action_text + "<i>Joining is optional.</i>"
            )
        else:
            education_text = "📚 <b>Educational Group</b>\n" + education_note
        text = (
            "🔐 <b>MEMBER ACCESS</b>\n"
            "Choose the space that best fits what you’re looking for.\n\n"
            f"{education_text}\n\n"
            "────────────\n\n"
            "📊 <b>Market Analysis</b>\n"
            "Apply separately. An administrator reviews each request.\n\n"
            "💹 <b>PRO Signals</b>\n"
            "Requires verified Exness registration, a private review of funding evidence, "
            "and final administrator approval.\n\n"
            "🗂 Already applied? Choose <b>My Access / Status</b> from the main menu."
        )
        notice = self.applicant_followup_notice_text(update.effective_user.id)
        if notice:
            text += "\n\n" + notice
            buttons.append(("Stop Reminders", "applicant_followup_stop", {}))
        result = await self.say(update, text, buttons, parse_mode="HTML")
        if notice:
            mark_notice_shown(self.db, update.effective_user.id)
        return result

    def _pro_screening_draft(self, update, data):
        user = update.effective_user.id
        draft = self.db.draft(user)
        if (not draft or draft.get("kind") != "pro_screening" or
                draft.get("destination") != "pro"):
            raise ValueError("This PRO application step is no longer active. Start again from Member Access.")
        if data.get("revision") != draft.get("revision"):
            raise ValueError("This PRO application button is out of date. Reopen the current step.")
        return draft

    async def pro_screening_prompt(self, update, draft=None, notice=None):
        user = update.effective_user.id
        draft = draft or self.db.draft(user)
        if (not draft or draft.get("kind") != "pro_screening" or
                draft.get("destination") != "pro"):
            raise ValueError("This PRO application step is no longer active. Start again from Member Access.")

        step = draft.get("step")
        revision = draft.get("revision")
        buttons = []
        if isinstance(step, int) and 0 <= step < len(PRO_SCREENING_QUESTIONS):
            text = (
                f"🔐 <b>PRO SIGNALS APPLICATION · {step + 1}/3</b>\n\n"
                f"{PRO_SCREENING_QUESTIONS[step]}"
            )
            answer_values = ("yes", "no") if step < 2 else ("ready", "not_yet")
            buttons.extend(
                (label, "member_pro_screening_answer",
                 {"revision": revision, "step": step, "answer": answer})
                for label, answer in zip(PRO_SCREENING_ANSWER_LABELS[step], answer_values)
            )
            if step > 0:
                buttons.append(("⬅️ Back", "member_pro_screening_back",
                                {"revision": revision, "step": step}))
        elif step == "summary":
            answers = draft.get("screening_answers", [])
            if answers != ["yes", "yes", "ready"]:
                raise ValueError("Complete all three PRO application questions before submitting.")
            text = (
                "🔐 <b>PRO SIGNALS APPLICATION SUMMARY</b>\n\n"
                "• Eligibility checks and administrator approval: understood\n"
                "• Trading guidelines and risk management: accepted\n"
                "• Verification before access: ready\n\n"
                "Tap <b>Submit Application</b> to continue to the existing application questions. "
                "The existing Exness registration, funding review, and final administrator approval "
                "will still be required.\n\n"
                f"{PRO_SUBMISSION_NOTICE}"
            )
            buttons.extend([
                ("⬅️ Back", "member_pro_screening_back",
                 {"revision": revision, "step": "summary"}),
                ("✅ Submit Application", "member_pro_screening_submit",
                 {"revision": revision}),
            ])
        elif step == "declined":
            text = (
                "To continue with PRO Signals, you need to understand that access is subject to eligibility "
                "checks and administrator approval, and agree to follow the trading guidelines. "
                "You can review the requirements and start these questions again whenever you’re ready."
            )
            buttons.append(("Review requirements and start again", "member_pro_screening_restart",
                            {"revision": revision}))
        elif step == "not_ready":
            text = (
                "No problem. You can return to the PRO Signals application when you’re ready to complete "
                "the required verification. Your progress is saved; use <b>Continue my saved step</b> "
                "from the main menu to resume."
            )
            buttons.append(("Continue when ready", "member_pro_screening_resume",
                            {"revision": revision}))
        else:
            raise ValueError("This PRO application draft is invalid. Start again from Member Access.")

        buttons.append(("↩️ Return to Main Menu", "member_pro_screening_exit",
                        {"revision": revision}))
        if notice:
            text = escape(str(notice)) + "\n\n" + text
        return await self.say(update, text, buttons, parse_mode="HTML")

    async def member_pro_screening_answer(self, update, data):
        draft = self._pro_screening_draft(update, data)
        step = data.get("step")
        answer = data.get("answer")
        if not isinstance(step, int) or draft.get("step") != step or not 0 <= step < 3:
            raise ValueError("This PRO application answer is out of date. Reopen the current step.")
        allowed = ("yes", "no") if step < 2 else ("ready", "not_yet")
        if answer not in allowed:
            raise ValueError("Choose one of the answers shown for this question.")

        answers = list(draft.get("screening_answers", []))
        answers = answers[:step]
        answers.append(answer)
        draft["screening_answers"] = answers
        if answer == "no":
            draft["step"] = "declined"
        elif answer == "not_yet":
            draft["step"] = "not_ready"
        elif step == 2:
            draft["step"] = "summary"
        else:
            draft["step"] = step + 1
        self.db.save_draft(update.effective_user.id, draft)
        return await self.pro_screening_prompt(update, draft)

    async def member_pro_screening_back(self, update, data):
        draft = self._pro_screening_draft(update, data)
        if data.get("step") == "summary" and draft.get("step") == "summary":
            target = 2
        elif (isinstance(data.get("step"), int) and draft.get("step") == data.get("step") and
              data["step"] > 0):
            target = data["step"] - 1
        else:
            raise ValueError("This Back button is out of date. Reopen the current step.")
        draft["screening_answers"] = list(draft.get("screening_answers", []))[:target]
        draft["step"] = target
        self.db.save_draft(update.effective_user.id, draft)
        return await self.pro_screening_prompt(update, draft)

    async def member_pro_screening_restart(self, update, data):
        draft = self._pro_screening_draft(update, data)
        if draft.get("step") != "declined":
            raise ValueError("This restart button is no longer active.")
        draft["screening_answers"] = []
        draft["step"] = 0
        self.db.save_draft(update.effective_user.id, draft)
        return await self.pro_screening_prompt(update, draft)

    async def member_pro_screening_resume(self, update, data):
        draft = self._pro_screening_draft(update, data)
        if draft.get("step") != "not_ready":
            raise ValueError("This resume button is no longer active.")
        draft["screening_answers"] = list(draft.get("screening_answers", []))[:2]
        draft["step"] = 2
        self.db.save_draft(update.effective_user.id, draft)
        return await self.pro_screening_prompt(update, draft)

    async def member_pro_screening_exit(self, update, data):
        self._pro_screening_draft(update, data)
        return await self.member_start(update)

    async def member_pro_screening_submit(self, update, data):
        user = update.effective_user.id
        draft = self._pro_screening_draft(update, data)
        if draft.get("step") != "summary" or draft.get("screening_answers") != ["yes", "yes", "ready"]:
            raise ValueError("Complete and review the PRO application questions before submitting.")

        existing = self.db.rows(
            "SELECT id,status FROM member_requests WHERE user_id=? AND destination='pro' "
            "AND status NOT IN ('rejected','revoked') LIMIT 1", (user,))
        if existing:
            self.db.clear_draft(user)
            return await self.say(
                update,
                "You already have a PRO Signals application in progress. No duplicate application was created.",
                [("My Access / Status", "member_status", {})],
                parse_mode="HTML")

        application_answers = list(draft.get("application_answers", []))
        self.db.save_draft(user, {
            "kind": "destination_application",
            "destination": "pro",
            "answers": application_answers,
            "pro_screening_answers": ["yes", "yes", "ready"],
            "step": "answer",
        })
        text = (
            "✅ <b>PRO APPLICATION STARTED</b>\n\n"
            "Your responses are saved. Next, complete the existing application questions. "
            "After those are submitted, the existing Exness registration, funding-evidence review, "
            "and final administrator approval steps will continue. This does not guarantee access."
        )
        return await self.say(
            update, text + "\n\n" + application_prompt(len(application_answers)),
            parse_mode="HTML")

    async def self_service_education_access(self, update, link_only=False):
        lock = getattr(self, "_education_access_lock", None)
        if lock is None:
            lock = self._education_access_lock = asyncio.Lock()
        async with lock:
            return await self._self_service_education_access_locked(update, link_only)

    async def _self_service_education_access_locked(self, update, link_only=False):
        async def reply(text):
            return None if link_only else await self.say(update, text)

        user = update.effective_user.id
        if getattr(update.effective_chat, "type", None) != "private":
            if link_only:
                return None
            raise PermissionError("Open a private chat with the bot to get an Education Group invite.")

        group_id = self.config.education_group_id
        if not group_id:
            raise ValueError("Educational Group access is not configured.")

        access = self.db.rows(
            "SELECT status FROM access WHERE user_id=? AND channel=?", (user, group_id))
        status = access[0]["status"] if access else ""
        if status in ("disapproval_pending", "access_revoked", "kicked"):
            return await reply(
                "Education Group access was removed by an administrator. Contact the administrator "
                "if you want them to review it.")
        stamp = now()
        self.db.execute(
            "INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
            (user, "[]", "destination_applicant", stamp))

        try:
            member = await self.bot.get_chat_member(group_id, user)
        except Exception as exc:
            self.db.error(
                "education_self_service_membership_check",
                f"Telegram membership check failed ({type(exc).__name__}); no new invite was created.")
            return await reply(
                "I couldn't confirm your current Education Group membership, so I didn't create "
                "another invite. Check My Access or contact the administrator.")
        member_status = getattr(member, "status", "")
        is_member = (member_status in ("member", "administrator", "creator") or
                     (member_status == "restricted" and bool(getattr(member, "is_member", False))))
        if is_member:
            self.db.execute(
                "INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                (user, group_id, member_status, now()))
            if link_only:
                return ""
            return await self.say(update, "You are already in the Educational Group.")

        if status in ("invite_pending", "invite_uncertain"):
            return await reply(
                "An Education Group invite is already being processed or checked. I won't create "
                "another link automatically. Check My Access later or contact the administrator.")

        if status == "invite_issued":
            op = self.publisher.current_invite_operation(user, group_id)
            row = self.publisher.operation(op)[0] if op else None
            result = self.db.get(f"invite:{op}") if op else None
            if (row and row["status"] == "done" and isinstance(result, dict) and
                    result.get("invite_link") and result.get("direct_join") is True):
                from datetime import datetime, timezone
                try:
                    expires_at = datetime.fromisoformat(result.get("expires_at", ""))
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    if expires_at > datetime.now(timezone.utc):
                        if link_only:
                            return result["invite_link"]
                        return await self.member_action(update, "member_status", {})
                except (TypeError, ValueError):
                    return await reply(
                        "Your existing invite needs an administrator check. I won't create a duplicate.")
            elif (row and row["status"] == "done" and isinstance(result, dict) and
                  result.get("invite_link")):
                # Rotate legacy join-request invites into the new direct-join flow.
                pass
            else:
                return await reply(
                    "Your existing invite needs an administrator check. I won't create a duplicate.")

        latest = self.latest_member_request(user, "education")
        request_id = latest["id"] if latest and latest["status"] == "approved" else None
        if request_id is None and latest and latest["status"] not in (
                "rejected", "revoked", "not_yet_eligible"):
            request_id = latest["id"]
            self.db.execute(
                "UPDATE member_requests SET status='approved',source='self_service',"
                "admin_decision_by=NULL,admin_decision_at=NULL,updated=? WHERE id=?",
                (stamp, request_id))
            self.member_request_event(
                request_id, user, "self_service_access_granted",
                "Educational Group access is self-service; no administrator approval was required.")
        elif request_id is None:
            request_id = uid()
            self.db.execute(
                "INSERT INTO member_requests "
                "(id,user_id,username,destination,answers,status,registration_status,funding_status,"
                "source,created,updated) VALUES (?,?,?,?,?,'approved','not_required','not_required',"
                "'self_service',?,?)",
                (request_id, user, getattr(update.effective_user, "username", "") or "",
                 "education", json.dumps([], ensure_ascii=False), stamp, stamp))
            self.member_request_event(
                request_id, user, "self_service_access_granted",
                "Educational Group access is self-service; no administrator approval was required.")
        self.db.execute(
            "INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
            (user, group_id, "invite_pending", stamp))
        self.member_request_event(
            request_id, user, "self_service_invite_requested",
            "Requested a one-use direct-join Educational Group invite.")

        op = None
        try:
            op = self.publisher.prepare(
                user, "invite",
                {"user": user, "channel": group_id, "self_service_education": True})
            await self.publisher.send(user, op)
            operation, _ = self.publisher.operation(op)
        except Exception as exc:
            state = "failed"
            if op:
                try:
                    state = self.publisher.operation(op)[0]["status"]
                except Exception:
                    state = "uncertain"
            access_status = ("invite_uncertain" if state in ("sending", "uncertain", "retryable")
                             else "invite_failed")
            self.db.execute(
                "UPDATE access SET status=?,updated=? WHERE user_id=? AND channel=?",
                (access_status, now(), user, group_id))
            self.db.error(
                "education_self_service_invite",
                f"Telegram invite creation was not confirmed ({type(exc).__name__}); no automatic retry.")
            return await reply(
                "I couldn't confirm the Education Group invite, so I won't create another "
                "automatically. Check My Access or contact the administrator.")

        if operation["status"] != "done":
            access_status = "invite_uncertain" if operation["status"] in ("sending", "uncertain") else "invite_failed"
            self.db.execute(
                "UPDATE access SET status=?,updated=? WHERE user_id=? AND channel=?",
                (access_status, now(), user, group_id))
            return await reply(
                "I couldn't confirm the Education Group invite, so I won't create another "
                "automatically. Check My Access or contact the administrator.")
        result = self.db.get(f"invite:{op}")
        link = result.get("invite_link") if isinstance(result, dict) else None
        if not link:
            self.db.execute(
                "UPDATE access SET status='invite_uncertain',updated=? WHERE user_id=? AND channel=?",
                (now(), user, group_id))
            self.db.error("education_self_service_invite", "Completed invite operation has no saved invite link.")
            return await reply(
                "The invite was created but its link could not be retrieved safely. Contact the administrator.")
        if link_only:
            return link
        delivery = await self.send_education_welcome(user, link, update=update)
        if delivery == "failed":
            try:
                await self.bot.send_message(
                    self.config.admin,
                    "⚠️ The Educational Group welcome could not be delivered privately. "
                    "The one-use invite remains available in My Access; check Recent Errors.")
            except Exception:
                self.db.error(
                    "education_invitation_admin_alert",
                    "Administrator could not be notified that a self-service welcome delivery failed.")
        return delivery

    async def begin_destination_application(self, update, destination):
        if destination not in DESTINATION_LABELS:
            raise ValueError("Choose a valid access destination.")
        if update.effective_chat.type == "private":
            stage = "membership_check" if destination == "education" else "application_draft"
            record_applicant_activity(
                self.db, self.config, update.effective_user.id, stage,
                destination, source="destination_selected")
        if destination == "education":
            education_button, education_note = await self.education_join_button(update)
            if not education_button:
                return await self.say(update, education_note)
            return await self.say(
                update,
                ("Start Education below, then join and verify membership."
                 if getattr(self.config, "education_onboarding_enabled", False) else
                 "Educational Group access is self-service. Tap below to open the saved Education link."),
                [education_button])
        active = self.latest_member_request(update.effective_user.id, destination)
        if active and destination == "pro" and active["status"] in ("rejected", "not_yet_eligible"):
            return await self.show_pro_outcome(update, active)
        if active and active["status"] not in ("rejected", "revoked"):
            if destination == "pro" and active["status"] in ("awaiting_registration", "legacy_review"):
                return await self.pro_registration_prompt(update, active["id"])
            return await self.say(update, f"You already have a {DESTINATION_LABELS[destination]} application "
                                   f"({active['status'].replace('_', ' ')}). Check My Access / Applications.")
        draft = self.db.draft(update.effective_user.id)
        if destination == "pro":
            if draft and draft.get("kind") == "pro_screening":
                return await self.pro_screening_prompt(update, draft)
            if draft and draft.get("kind") == "destination_application" and draft.get("destination") == "pro":
                screening_answers = draft.get("pro_screening_answers", [])
                if screening_answers != ["yes", "yes", "ready"]:
                    valid_prefixes = ([], ["yes"], ["yes", "yes"])
                    screening_answers = (screening_answers
                                         if screening_answers in valid_prefixes
                                         else [])
                    self.db.save_draft(update.effective_user.id, {
                        "kind": "pro_screening",
                        "destination": "pro",
                        "screening_answers": screening_answers,
                        "application_answers": list(draft.get("answers", [])),
                        "step": len(screening_answers),
                    })
                    return await self.pro_screening_prompt(
                        update, self.db.draft(update.effective_user.id))
                return await self.say(
                    update, "Let's continue your saved PRO Signals application.\n\n" +
                    application_prompt(len(draft.get("answers", []))))
            if draft:
                raise ValueError("Finish or cancel your current draft before starting a PRO Signals application.")
            self.db.save_draft(update.effective_user.id, {
                "kind": "pro_screening",
                "destination": "pro",
                "screening_answers": [],
                "application_answers": [],
                "step": 0,
            })
            return await self.pro_screening_prompt(update, self.db.draft(update.effective_user.id))
        if draft and draft.get("kind") == "destination_application":
            if draft.get("destination") == destination:
                return await self.say(update, "Let's continue this application.\n\n" +
                                      application_prompt(len(draft.get("answers", []))))
            raise ValueError("Finish or cancel your current application draft before starting another.")
        if draft:
            raise ValueError("Finish or cancel your current draft before starting an access application.")
        self.db.save_draft(update.effective_user.id, {
            "kind": "destination_application", "destination": destination,
            "answers": [], "step": "answer",
        })
        await self.say(update, f"Applying for {DESTINATION_LABELS[destination]}.\n\n" + application_prompt(0))

    async def destination_application_answer(self, update, draft):
        user = update.effective_user.id
        destination = draft.get("destination")
        if destination not in DESTINATION_LABELS:
            self.db.clear_draft(user)
            raise ValueError("This application draft is invalid. Return to the main menu and start again.")
        record_applicant_activity(
            self.db, self.config, user, "application_draft", destination,
            source="application_answer")
        if destination == "pro" and draft.get("pro_screening_answers") != ["yes", "yes", "ready"]:
            self.db.save_draft(user, {
                "kind": "pro_screening",
                "destination": "pro",
                "screening_answers": [],
                "application_answers": list(draft.get("answers", [])),
                "step": 0,
            })
            return await self.pro_screening_prompt(
                update, self.db.draft(user))
        answers = list(draft.get("answers", []))
        answers.append(safe_application_answer(update.message.text))
        if len(answers) < len(QUESTIONS):
            draft["answers"] = answers
            self.db.save_draft(user, draft)
            return await self.say(update, application_prompt(len(answers)))
        existing = self.db.rows(
            "SELECT id FROM member_requests WHERE user_id=? AND destination=? "
            "AND status NOT IN ('rejected','revoked') LIMIT 1", (user, destination))
        if existing:
            self.db.clear_draft(user)
            raise ValueError("An application for this destination is already awaiting review.")
        request_id = uid()
        stamp = now()
        status = "awaiting_registration" if destination == "pro" else "pending_review"
        registration = "not_submitted" if destination == "pro" else "not_required"
        funding = "not_submitted" if destination == "pro" else "not_required"
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,username,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (request_id, user, getattr(update.effective_user, "username", "") or "", destination,
             json.dumps(answers, ensure_ascii=False), status, registration, funding, "new", stamp, stamp))
        self.member_request_event(request_id, user, "application_submitted",
                                  f"Submitted application for {DESTINATION_LABELS[destination]}.")
        if destination == "pro":
            self.member_request_event(
                request_id, user, "pro_screening_completed",
                json.dumps(draft["pro_screening_answers"], separators=(",", ":")))
        self.db.clear_draft(user)
        if destination == "pro":
            return await self.pro_registration_prompt(update, request_id)
        await self.notify_member_request(
            request_id, f"📨 New {DESTINATION_LABELS[destination]} application is ready for review.")
        queue_key = f"member:alternative_queue:{user}"
        queue = self.db.get(queue_key)
        if isinstance(queue, dict) and queue.get("remaining"):
            next_destination = DESTINATION_LABELS.get(queue["remaining"][0], "next destination")
            return await self.say(
                update,
                f"✅ Your {DESTINATION_LABELS[destination]} request was submitted for separate review. "
                f"No access has been granted yet.\n\nWhen you're ready, continue with {next_destination}.",
                [("Continue with next request", "member_pro_alternative_next",
                  {"request_id": queue["pro_request_id"]}),
                 ("Cancel remaining request", "member_pro_alternative_cancel", {})])
        if isinstance(queue, dict):
            self.db.execute("DELETE FROM kv WHERE key=?", (queue_key,))
            unavailable = " ".join(queue.get("unavailable", []))
            text = (f"✅ Your {DESTINATION_LABELS[destination]} request was submitted for separate review. "
                    "No access has been granted automatically.")
            if unavailable:
                text += "\n\n" + unavailable
            return await self.say(update, text)
        return await self.say(update, f"✅ Your {DESTINATION_LABELS[destination]} application was submitted. "
                               "It will be reviewed separately from your other access requests.",
                               [("My Access / Applications", "member_status", {})])

    async def pro_registration_prompt(self, update, request_id):
        request = self.member_request(request_id)
        if not request or request["destination"] != "pro":
            raise ValueError("PRO application not found.")
        rows = []
        registration_status = request["registration_status"]
        if registration_status == "pending_review":
            text = (
                "🔎 <b>EXNESS REGISTRATION REVIEW</b>\n\n"
                "Your registration has been submitted and is awaiting administrator verification. "
                "A pending review is not a rejection."
            )
        elif pro_registration_approved(registration_status):
            text = (
                "✅ <b>PRO REGISTRATION APPROVED</b>\n\n"
                "PRO education eligibility is approved, but lesson delivery remains turned off until onboarding is ready. "
                "PRO Signals access is separate and still requires administrator verification of your funded account."
            )
            if request["funding_status"] not in ("pending_review", "verified"):
                rows.append([self.button(
                    update.effective_user.id, "Submit Funding Evidence",
                    "member_funding_evidence", {"request_id": request_id})])
        elif self.config.exness_partner_link:
            text = (
                "🔐 <b>EXNESS REGISTRATION</b>\n\n"
                "To continue your PRO Signals application, register through the official Exness link below. "
                "After registering, tap the verification button below to submit your registration for "
                "administrator review. This submits a review request; it does not grant PRO access.\n\n"
                "⚠️ Never send passwords, OTPs, recovery codes, or account login details."
            )
            rows.append([InlineKeyboardButton("Register with Exness",
                                              url=self.config.exness_partner_link)])
            rows.append([self.button(
                update.effective_user.id, "I've Registered — Submit for Verification",
                "member_pro_registered", {"request_id": request_id})])
        else:
            text = (
                "🔐 <b>EXNESS REGISTRATION</b>\n\n"
                "Registration is temporarily unavailable because the official Exness link is not configured. "
                "Please contact the administrator."
            )
        await self.bot.send_message(update.effective_chat.id, text,
                                    reply_markup=InlineKeyboardMarkup(rows) if rows else None,
                                    parse_mode="HTML")

    async def submit_registration_for_review(self, update, request_id):
        user = update.effective_user.id
        request = self.member_request(request_id)
        if not request or request["user_id"] != user or request["destination"] != "pro":
            raise PermissionError("This PRO application is not available.")
        if request["status"] not in ("awaiting_registration", "legacy_review"):
            raise ValueError("This application has already been submitted for registration review.")
        if not self.config.exness_partner_link:
            raise ValueError("The Exness registration link is not configured. Contact the administrator.")
        with self.db.transaction() as c:
            c.execute("UPDATE member_requests SET status='pending_review',registration_status='pending_review',updated=? "
                      "WHERE id=? AND user_id=? AND status IN ('awaiting_registration','legacy_review')",
                      (now(), request_id, user))
        self.member_request_event(request_id, user, "registration_submitted",
                                  "Applicant asked the administrator to verify registration.")
        await self.notify_member_request(
            request_id, "🧾 <b>PRO REGISTRATION SUBMITTED</b>\n\nThe applicant requested manual verification.",
            parse_mode="HTML")
        return await self.say(
            update, "✅ <b>REGISTRATION SUBMITTED</b>\n\n"
            "An administrator will review it. <b>This does not grant access.</b>\n\n" + PRO_ACCESS_REMINDER,
            parse_mode="HTML")

    async def begin_funding_evidence(self, update, request_id):
        user = update.effective_user.id
        request = self.member_request(request_id)
        if not request or request["user_id"] != user or request["destination"] != "pro":
            raise PermissionError("This PRO application is not available.")
        if request["status"] == "revoked":
            raise ValueError("This PRO access was disapproved. Start a new PRO application to request review.")
        if not pro_registration_approved(request["registration_status"]):
            raise ValueError("Wait for administrator approval of your PRO registration before submitting funded-account evidence.")
        if request["status"] == "approved":
            if request["funding_status"] == "pending_review":
                raise ValueError("Your updated balance screenshot is already awaiting administrator review.")
            if not pro_registration_approved(request["registration_status"]) or request["funding_status"] not in (
                    "verified", "evidence_requested"):
                raise ValueError("This approved request needs administrator review before another screenshot can be submitted.")
        return await self.say(
            update,
            "📄 <b>PRIVATE FUNDING EVIDENCE</b>\n\n"
            "Send a clear screenshot showing your current trading balance and currency. Hide passwords, OTPs, "
            "recovery codes, login details, and unnecessary personal information. The bot will not scan the image; "
            "an administrator reviews it privately.\n\n" + PRO_ACCESS_REMINDER,
            [("I Removed Credentials — Continue", "member_evidence_confirm", {"request_id": request_id})],
            parse_mode="HTML")

    async def confirm_funding_evidence(self, update, request_id):
        user = update.effective_user.id
        request = self.member_request(request_id)
        if not request or request["user_id"] != user or request["destination"] != "pro":
            raise PermissionError("This PRO application is not available.")
        if request["status"] == "revoked":
            raise ValueError("This PRO access was disapproved. Start a new PRO application to request review.")
        if not pro_registration_approved(request["registration_status"]):
            raise ValueError("Wait for administrator approval of your PRO registration before submitting funded-account evidence.")
        if request["status"] == "approved":
            if request["funding_status"] == "pending_review":
                raise ValueError("Your updated balance screenshot is already awaiting administrator review.")
            if not pro_registration_approved(request["registration_status"]) or request["funding_status"] not in (
                    "verified", "evidence_requested"):
                raise ValueError("This approved request needs administrator review before another screenshot can be submitted.")
        self.db.save_draft(user, {"kind": "pro_evidence", "request_id": request_id, "step": "upload"})
        if request["status"] == "approved":
            prompt = ("📄 <b>UPDATED BALANCE EVIDENCE</b>\n\n"
                      "Send one updated balance screenshot or PDF privately. It will be sent only to the "
                      "administrator for manual review. Your existing PRO access will not change while the "
                      "review is pending. It will not be posted to either channel.")
        else:
            prompt = ("📄 <b>PRIVATE FUNDING EVIDENCE</b>\n\n"
                      "Submit one screenshot or PDF privately. It will be sent only to the administrator "
                      "for manual review and marked PENDING_REVIEW. It will not be posted to either channel.")
        await self.say(update, prompt + "\n\n" + PRO_ACCESS_REMINDER, parse_mode="HTML")

    async def save_funding_evidence(self, update):
        user = update.effective_user.id
        draft = self.db.draft(user)
        if not draft or draft.get("kind") != "pro_evidence":
            raise ValueError("Open Submit Funding Evidence from your PRO application first.")
        request = self.member_request(draft.get("request_id"))
        if not request or request["user_id"] != user or request["destination"] != "pro":
            self.db.clear_draft(user)
            raise PermissionError("This evidence submission is not available.")
        if request["status"] == "revoked":
            self.db.clear_draft(user)
            raise ValueError("This PRO access was disapproved. Start a new PRO application to request review.")
        is_balance_update = (request["status"] == "approved" and
                             pro_registration_approved(request["registration_status"]) and
                             request["funding_status"] in ("verified", "evidence_requested"))
        if request["status"] == "approved" and not is_balance_update:
            self.db.clear_draft(user)
            raise ValueError("A funding review is already active or this request changed. Check your access status.")
        message = update.message
        item = message.photo[-1] if message.photo else message.document
        if not item:
            raise ValueError("Send one screenshot or PDF.")
        if item.file_size and item.file_size > 10 * 1024 * 1024:
            raise ValueError("Evidence must be 10 MB or smaller.")
        mime = getattr(item, "mime_type", "") or ("image/jpeg" if message.photo else "")
        if mime not in ("image/jpeg", "image/png", "image/webp", "application/pdf"):
            raise ValueError("Send a JPEG, PNG, WEBP image, or PDF.")
        stamp = now()
        with self.db.transaction() as c:
            if is_balance_update:
                result = c.execute(
                    "UPDATE member_requests SET evidence_file_id=?,evidence_kind=?,evidence_submitted_at=?,"
                    "funding_status='pending_review',updated=? WHERE id=? AND user_id=? AND destination='pro' "
                    "AND status='approved' AND registration_status IN ('approved','verified') "
                    "AND funding_status IN ('verified','evidence_requested')",
                    (item.file_id, mime, stamp, stamp, request["id"], user))
            else:
                result = c.execute(
                    "UPDATE member_requests SET evidence_file_id=?,evidence_kind=?,evidence_submitted_at=?,"
                    "funding_status='pending_review',status='pending_review',updated=? "
                    "WHERE id=? AND user_id=? AND destination='pro' AND status!='revoked'",
                    (item.file_id, mime, stamp, stamp, request["id"], user))
            if result.rowcount == 1:
                action = "funding_balance_update_submitted" if is_balance_update else "funding_evidence_submitted"
                detail = (f"Private {'updated balance ' if is_balance_update else ''}evidence submitted; "
                          f"MIME type {mime}; marked PENDING_REVIEW.")
                if is_balance_update and request.get("evidence_file_id"):
                    detail += f" Previous evidence reference retained: {request['evidence_file_id']}."
                c.execute(
                    "INSERT INTO member_request_events(request_id,actor,action,detail,created) "
                    "VALUES (?,?,?,?,?)", (request["id"], user, action, detail[:400], stamp))
        if result.rowcount != 1:
            self.db.clear_draft(user)
            raise ValueError("This funding request changed. Check your current PRO status before trying again.")
        self.db.clear_draft(user)
        if is_balance_update:
            await self.notify_member_request(
                request["id"],
                "🔎 <b>PRO BALANCE UPDATE READY FOR REVIEW</b>\n\n"
                "Existing access remains unchanged while the review is pending.",
                parse_mode="HTML")
            text = ("✅ <b>BALANCE UPDATE SUBMITTED</b>\n\n"
                    "Your updated screenshot was sent privately for administrator review. "
                    "Your existing PRO access remains unchanged while the review is pending.")
        else:
            await self.notify_member_request(
                request["id"], "🔎 <b>PRO FUNDING EVIDENCE READY FOR REVIEW</b>",
                parse_mode="HTML")
            text = ("✅ <b>FUNDING EVIDENCE SUBMITTED</b>\n\n"
                    "Your evidence was submitted privately and marked <b>PENDING_REVIEW</b>. "
                    "It has not been treated as verification.")
        await self.say(update, text + "\n\n" + PRO_ACCESS_REMINDER, parse_mode="HTML")

    def access_destinations(self):
        destinations = [
            (self.config.signals, "PRO Signals"),
            (self.config.analysis, "Market Analysis"),
        ]
        if self.config.education_group_id:
            destinations.append((self.config.education_group_id, "Educational Group"))
        return [(chat_id, label) for chat_id, label in destinations if chat_id]

    async def member_start(self, update):
        user = update.effective_user.id
        record_applicant_activity(
            self.db, self.config, user, "welcome", source="start")
        _, buttons = self.assistant_start_info(user)
        notice = self.applicant_followup_notice_text(user)
        text = MEMBER_WELCOME_TEXT + ("\n\n" + notice if notice else "")
        if not self.assistant_enabled():
            text += "\n\n" + escape(self.assistant_inactive_text())
        if notice:
            buttons.append(("Stop Reminders", "applicant_followup_stop", {}))
        await self.say(update, text, buttons, parse_mode="HTML")
        if notice:
            mark_notice_shown(self.db, user)

    async def member_action(self, update, action, data):
        user = update.effective_user.id
        if user != self.config.admin and action not in ("member_apply", "member_cancel"):
            await self.applicant_followup_ensure_notice(update)
        if user != self.config.admin:
            if action == "member_apply":
                record_applicant_activity(
                    self.db, self.config, user, "choosing_destination",
                    source="member_access_button")
            elif action == "member_status":
                request_rows = self.db.rows(
                    "SELECT DISTINCT destination FROM member_requests WHERE user_id=? "
                    "AND status NOT IN ('rejected','revoked')", (user,))
                state = record_applicant_activity(
                    self.db, self.config, user, "membership_check",
                    source="member_status")
                for request in request_rows:
                    if request["destination"] in DESTINATION_LABELS:
                        state = record_applicant_activity(
                            self.db, self.config, user, "membership_check",
                            request["destination"], source="member_status")
            elif action == "member_pro_registration":
                request = self.member_request(data.get("request_id"))
                if request and request["user_id"] == user:
                    record_applicant_activity(
                        self.db, self.config, user, "registration_step", "pro",
                        source="pro_registration")
            elif action == "member_more_info":
                request = self.member_request(data.get("request_id"))
                if request and request["user_id"] == user:
                    record_applicant_activity(
                        self.db, self.config, user, "information_requested",
                        request["destination"], source="more_information")
            elif action == "member_cancel":
                if followup_schema_available(self.db):
                    rows = self.db.rows(
                        "SELECT user_id FROM applicant_followup_state WHERE user_id=?", (user,))
                    if rows:
                        set_followup_status(
                            self.db, user, "completed", "application_draft_cancelled")
        if action == "member_apply":
            return await self.request_destination_selection(update)
        elif action == "member_apply_dest":
            return await self.begin_destination_application(update, data.get("destination"))
        elif action == "member_pro_alternative":
            return await self.member_pro_alternative(
                update, data.get("request_id"), data.get("choice"))
        elif action == "member_pro_alternative_next":
            return await self.member_pro_alternative_next(update, data.get("request_id"))
        elif action == "member_pro_alternative_cancel":
            return await self.member_pro_alternative_cancel(update)
        elif action == "member_pro_recheck":
            return await self.member_pro_recheck(update, data.get("request_id"))
        elif action == "member_pro_screening_answer":
            return await self.member_pro_screening_answer(update, data)
        elif action == "member_pro_screening_back":
            return await self.member_pro_screening_back(update, data)
        elif action == "member_pro_screening_restart":
            return await self.member_pro_screening_restart(update, data)
        elif action == "member_pro_screening_resume":
            return await self.member_pro_screening_resume(update, data)
        elif action == "member_pro_screening_submit":
            return await self.member_pro_screening_submit(update, data)
        elif action == "member_pro_screening_exit":
            return await self.member_pro_screening_exit(update, data)
        elif action == "member_pro_registration":
            request = self.member_request(data.get("request_id"))
            if not request or request["user_id"] != user or request["destination"] != "pro":
                raise PermissionError("This PRO application is not available.")
            return await self.pro_registration_prompt(update, request["id"])
        elif action == "member_pro_registered":
            return await self.submit_registration_for_review(update, data.get("request_id"))
        elif action == "member_funding_evidence":
            return await self.begin_funding_evidence(update, data.get("request_id"))
        elif action == "member_evidence_confirm":
            return await self.confirm_funding_evidence(update, data.get("request_id"))
        elif action == "member_more_info":
            request = self.member_request(data.get("request_id"))
            if not request or request["user_id"] != user or request["status"] != "information_requested":
                raise PermissionError("This information request is no longer active.")
            self.db.save_draft(user, {"kind": "member_info_response", "request_id": request["id"]})
            await self.say(update, "Reply with the requested information in this private chat. "
                                   "Do not send account passwords, OTPs, or recovery codes.")
        elif action == "member_cancel":
            self.db.clear_draft(user)
            self.db.execute("DELETE FROM kv WHERE key=?", (f"member:alternative_queue:{user}",))
            await self.say(update, "Your application draft has been cancelled. You can start again whenever you're ready.")
        elif action == "member_status":
            r = self.db.rows("SELECT status FROM applications WHERE user_id=?", (user,))
            status = r[0]["status"] if r else "not applied"
            text = (f"📋 <b>YOUR ACCESS STATUS</b>\n\n<b>Previous application:</b> "
                    f"{escape(application_status_label(status))}")
            text += ("\n\nCurrent application decisions and access are shown separately for each "
                     "destination below.")
            labels = {
                "invite_pending": "invite being prepared",
                "invite_issued": "invite ready",
                "invite_uncertain": "invite needs administrator review",
                "invite_failed": "invite could not be created",
                "invite_revoked": "invite revoked",
                "disapproval_pending": "disapproval in progress; administrator review needed",
                "access_revoked": "access disapproved",
                "joined": "joined",
                "member": "member",
                "administrator": "administrator",
                "creator": "administrator",
            }
            names = dict(self.access_destinations())
            current_requests = {}
            for request in self.db.rows(
                    "SELECT * FROM member_requests WHERE user_id=? ORDER BY updated DESC,created DESC",
                    (user,)):
                current_requests.setdefault(request["destination"], request)
            request_buttons = []
            for destination, request in current_requests.items():
                label = DESTINATION_LABELS.get(destination, "Access")
                request_status = ("SELF-SERVICE ACCESS" if destination == "education" and
                                  request["source"] == "self_service" else
                                  "SELF-SERVICE ACCESS AVAILABLE" if destination == "education" and
                                  request["status"] == "pending_review" else
                                  pro_status_label(request) if destination == "pro" else
                                  "MORE_INFORMATION_REQUIRED" if request["status"] == "information_requested" else
                                  request["status"].replace("_", " ").upper())
                text += (f"\n\n<b>{escape(label)} application:</b> <b>{escape(request_status)}</b>")
                if destination == "pro":
                    text += "\n" + self.pro_requirement_guidance(request)
                    if request["status"] in ("awaiting_registration", "legacy_review"):
                        if self.config.exness_partner_link:
                            request_buttons.append(
                                ("I've Registered — Submit for Verification", "member_pro_registered",
                                 {"request_id": request["id"]}))
                        else:
                            text += "\nThe registration link is not configured for this bot."
                    if request["status"] == "approved":
                        if request["funding_status"] == "pending_review":
                            text += "\nYour existing PRO access remains unchanged while this balance update is reviewed."
                        elif (pro_registration_approved(request["registration_status"]) and
                              request["funding_status"] == "verified"):
                            request_buttons.append(("Update Funding Screenshot", "member_funding_evidence",
                                                    {"request_id": request["id"]}))
                    elif (request["status"] not in ("rejected", "not_yet_eligible") and
                          pro_registration_approved(request["registration_status"]) and
                          request["funding_status"] in ("not_submitted", "unverified", "rejected")):
                        request_buttons.append(("Submit Funding Evidence", "member_funding_evidence",
                                                {"request_id": request["id"]}))
                    if request["status"] in ("rejected", "not_yet_eligible"):
                        request_buttons.extend(self.pro_outcome_specs(request))
                if request["status"] == "information_requested":
                    request_buttons.append(("Reply to administrator", "member_more_info",
                                            {"request_id": request["id"]}))
            access_rows = self.db.rows("SELECT * FROM access WHERE user_id=?", (user,))
            has_pro_context = bool(current_requests.get("pro"))
            for access in access_rows:
                name = names.get(access["channel"], "Access destination")
                state = labels.get(access["status"], access["status"].replace("_", " "))
                text += f"\n<b>{escape(name)}:</b> {escape(state)}"
                if access["channel"] == self.config.signals:
                    has_pro_context = True
                pro_request = current_requests.get("pro") if access["channel"] == self.config.signals else None
                pro_eligible = bool(pro_request and pro_request["status"] == "approved" and
                                    pro_registration_approved(pro_request["registration_status"]) and
                                    pro_request["funding_status"] in ("verified", "pending_review"))
                if access["status"] == "invite_issued" and (
                        access["channel"] != self.config.signals or pro_eligible):
                    op = self.publisher.current_invite_operation(user, access["channel"])
                    result = self.db.get(f"invite:{op}") if op else None
                    if result and result.get("invite_link"):
                        invite_kind = ("direct-join invite (one use)"
                                       if access["channel"] == self.config.education_group_id
                                       else "join-request invite")
                        text += (f"\n{escape(name)} 24-hour {escape(invite_kind)}: "
                                 f"{escape(result['invite_link'])}")
            text += ("\n\nUse a current invite for each approved destination. Education Group links join directly. "
                     "PRO Signals and Market Analysis links require a join request. "
                     "Joining the Education Group is optional.")
            if has_pro_context:
                text += "\n\n" + PRO_ACCESS_REMINDER
            request_buttons.append(("🔐 Member Access", "member_apply", {}))
            await self.say(update, text[:3900], request_buttons, parse_mode="HTML")

    async def application_answer(self, update, draft):
        user = update.effective_user.id
        if not self.config.admin:
            return await self.say(update, "Applications are temporarily unavailable. Please try again later.")
        draft["answers"].append(safe_application_answer(update.message.text))
        if len(draft["answers"]) < len(QUESTIONS):
            self.db.save_draft(user, draft)
            return await self.say(update, application_prompt(len(draft["answers"])))
        self.db.execute("INSERT OR REPLACE INTO applications VALUES (?,?,?,?)",
                        (user, json.dumps(draft["answers"]), "pending", now()))
        self.db.clear_draft(user)
        await self.say(update, "✅ Application submitted\n\n"
                       "Thanks for your interest. Your request is now awaiting administrator review. "
                       "You can check its status with My Access / Invites.")
        await self.bot.send_message(self.config.admin, "📨 New member application is ready for review.",
                                    reply_markup=InlineKeyboardMarkup([[self.button(self.config.admin, "Review", "application", {"user": user})]]))

    async def applications(self, update, page=0):
        legacy = self.db.rows("SELECT user_id,status FROM applications WHERE status!='destination_applicant' "
                              "ORDER BY updated DESC LIMIT 8 OFFSET ?", (page * 8,))
        requests = self.db.rows("SELECT id,user_id,destination,status FROM member_requests "
                                "ORDER BY updated DESC LIMIT 12")
        buttons = [(f"Legacy {r['user_id']} · {r['status']}", "application",
                    {"user": r["user_id"]}) for r in legacy]
        buttons.extend((f"{r['user_id']} · {DESTINATION_LABELS.get(r['destination'], 'Access')} · "
                        f"{r['status'].replace('_', ' ')}", "member_request",
                        {"request_id": r["id"]}) for r in requests)
        nav = []
        if page:
            nav.append(("Previous", "applications", {"page": page - 1}))
        if len(legacy) == 8:
            nav.append(("Next", "applications", {"page": page + 1}))
        buttons.extend(nav)
        await self.say(update, "📨 Member applications\n\nNew destination requests and preserved legacy applications "
                       "are listed separately. Choose one to review.", buttons)

    async def member_request_screen(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request:
            raise ValueError("Member request not found.")
        label = DESTINATION_LABELS.get(request["destination"], "Access")
        answers = json.loads(request["answers"] or "[]")
        request_status = ("SELF-SERVICE ACCESS" if request["destination"] == "education" and
                          request["source"] == "self_service" else
                          "SELF-SERVICE ACCESS AVAILABLE" if request["destination"] == "education" and
                          request["status"] == "pending_review" else
                          pro_status_label(request) if request["destination"] == "pro" else
                          "MORE_INFORMATION_REQUIRED" if request["status"] == "information_requested" else
                          request["status"].replace("_", " ").upper())
        text = (f"📨 {label} request · {request_status}\n"
                f"Applicant Telegram ID: {request['user_id']}\n"
                f"Username: @{request['username']}" if request.get("username") else
                f"📨 {label} request · {request_status}\n"
                f"Applicant Telegram ID: {request['user_id']}\nUsername: not available")
        text += "\n\n" + "\n\n".join(f"{question}\n{answer}"
                                     for question, answer in zip(QUESTIONS, answers))
        destination_channel = {
            "pro": self.config.signals,
            "analysis": self.config.analysis,
            "education": self.config.education_group_id,
        }.get(request["destination"])
        access = (self.db.rows("SELECT status FROM access WHERE user_id=? AND channel=?",
                               (request["user_id"], destination_channel))
                  if destination_channel else [])
        access_status = access[0]["status"] if access else "not issued"
        text += f"\n\nDestination access: {access_status.replace('_', ' ')}"
        if request["destination"] == "pro":
            screening_events = self.db.rows(
                "SELECT detail FROM member_request_events WHERE request_id=? "
                "AND action='pro_screening_completed' ORDER BY id DESC LIMIT 1",
                (request_id,))
            if screening_events:
                try:
                    screening_answers = json.loads(screening_events[0]["detail"])
                except (TypeError, ValueError):
                    screening_answers = []
                if screening_answers == ["yes", "yes", "ready"]:
                    text += (
                        "\n\nPRO application questions:\n"
                        "• Eligibility checks and administrator approval: understood\n"
                        "• Trading guidelines and risk management: accepted\n"
                        "• Verification before access: ready"
                    )
            text += (f"\n\nRegistration verification: {request['registration_status']}"
                     f"\nPRO education entitlement: "
                     f"{'approved' if pro_education_entitled(request) else 'locked'}"
                     f"\nFunded-account verification: {request['funding_status']}"
                     f"\nPRO Signals access: {access_status.replace('_', ' ')}"
                     f"\nEvidence submitted: {request['evidence_submitted_at'] or 'not submitted'}")
            if request.get("followup_text"):
                text += "\n\nApplicant's latest reply:\n" + safe_text(request["followup_text"], 800)
            if request["source"] == "legacy":
                text += ("\n\nExisting PRO access is retained pending manual review. "
                         "No invite or membership was automatically revoked.")
        buttons = []
        if request.get("evidence_file_id"):
            buttons.append(("View Funding Evidence (admin only)", "member_request_evidence",
                            {"request_id": request_id}))
        if request["destination"] == "pro":
            if request["registration_status"] in ("pending_review", "unverified"):
                buttons.append(("Approve Registration (Education Only)", "member_verify_prompt",
                                {"request_id": request_id, "field": "registration"}))
            if request.get("evidence_file_id") and request["funding_status"] == "pending_review":
                buttons.append(("Verify Funded Account", "member_verify_prompt",
                                {"request_id": request_id, "field": "funding"}))
                buttons.append(("Reject Funding Evidence", "member_funding_reject",
                                {"request_id": request_id}))
            if request["registration_status"] in ("pending_review", "unverified"):
                buttons.append(("Reject PRO Registration", "member_registration_reject",
                                {"request_id": request_id}))
            if (pro_registration_approved(request["registration_status"]) and
                    request["funding_status"] == "verified" and
                    request["status"] in ("pending_review", "legacy_review")):
                buttons.append(("Review PRO Signals Invite", "member_pro_approve",
                                {"request_id": request_id}))
            elif (request["status"] == "pending_review" and
                  not self._pro_has_pending_verification(request)):
                buttons.append(("Mark Not Yet Eligible", "member_pro_not_eligible",
                                {"request_id": request_id}))
        elif request["status"] == "pending_review" and request["destination"] != "education":
            buttons.append(("Approve This Destination", "member_request_approve",
                            {"request_id": request_id}))
        if (request["status"] == "approved" and destination_channel and
                access_status in ("invite_pending", "invite_issued", "invite_uncertain", "invite_revoked",
                                  "invite_failed", "joined", "member", "administrator",
                                  "creator", "left", "kicked", "disapproval_pending")):
            buttons.append(("Disapprove this destination", "access_disapprove", {
                "user": request["user_id"], "channel": destination_channel,
                "request_id": request_id,
            }))
        elif (request["destination"] == "pro" and request["source"] == "legacy" and
              request["status"] == "legacy_review" and destination_channel and
              access_status in ("invite_pending", "invite_issued", "invite_uncertain", "invite_revoked",
                                "invite_failed", "joined", "member", "administrator",
                                "creator", "left", "kicked", "disapproval_pending")):
            buttons.append(("Disapprove existing PRO access", "access_disapprove", {
                "user": request["user_id"], "channel": destination_channel,
                "request_id": request_id,
            }))
        if (request["destination"] not in ("education", "pro") and
                request["status"] not in ("approved", "rejected", "not_yet_eligible", "revoked") and
                not self._pro_has_pending_verification(request)):
            buttons.extend([
                ("Reject Request", "member_request_reject", {"request_id": request_id}),
            ])
        if (request["destination"] != "education" and
                request["status"] not in ("approved", "rejected", "not_yet_eligible",
                                          "information_requested", "revoked")):
            buttons.append(("Request More Information", "member_request_more", {"request_id": request_id}))
        buttons.append(("Back to Applications", "applications", {}))
        return await self.say(update, text[:3900], buttons)

    async def member_request_evidence(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["destination"] != "pro" or not request.get("evidence_file_id"):
            raise ValueError("Funding evidence is unavailable.")
        caption = (f"Private funding evidence · applicant {request['user_id']} · "
                   f"{request['evidence_submitted_at'] or 'submission time unavailable'} · PENDING_REVIEW")
        if request["evidence_kind"] == "application/pdf":
            await self.bot.send_document(self.config.admin, request["evidence_file_id"], caption=caption)
        else:
            await self.bot.send_photo(self.config.admin, request["evidence_file_id"], caption=caption)
        return await self.member_request_screen(update, request_id)

    async def member_verify_prompt(self, update, request_id, field):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["destination"] != "pro" or field not in ("registration", "funding"):
            raise ValueError("Verification action is unavailable.")
        if field == "funding" and not request.get("evidence_file_id"):
            raise ValueError("Funding evidence must be privately reviewed before it can be marked verified.")
        current = request["registration_status" if field == "registration" else "funding_status"]
        if current not in ("pending_review", "unverified"):
            raise ValueError("This verification has already been reviewed.")
        field_label = ("updated balance screenshot"
                       if field == "funding" and request["status"] == "approved" else field)
        return await self.say(update,
                              "🔎 <b>MANUAL PRO VERIFICATION</b>\n\n"
                              f"Confirm you manually reviewed and verified the applicant's <b>{escape(field_label)}</b> "
                              "using your approved review process. The bot does not verify Exness accounts or infer "
                              "funding from a screenshot.",
                              [("Confirm Verified", "member_verify_confirm",
                                {"request_id": request_id, "field": field}),
                               ("Back to Request", "member_request", {"request_id": request_id})],
                              parse_mode="HTML")

    async def member_verify_confirm(self, update, request_id, field):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["destination"] != "pro" or field not in ("registration", "funding"):
            raise ValueError("Verification action is unavailable.")
        if field == "funding" and not request.get("evidence_file_id"):
            raise ValueError("Funding evidence must be reviewed before it can be marked verified.")
        column = "registration_status" if field == "registration" else "funding_status"
        current = request[column]
        if current not in ("pending_review", "unverified"):
            raise ValueError("This verification has already been reviewed.")
        stamp = now()
        new_status = "approved" if field == "registration" else "verified"
        self.db.execute(f"UPDATE member_requests SET {column}=?,updated=? WHERE id=? AND {column}=?",
                        (new_status, stamp, request_id, current))
        event_action = "registration_approved" if field == "registration" else "funding_verified"
        self.member_request_event(request_id, self.config.admin, event_action,
                                  "Administrator manually confirmed verification.")
        refreshed = self.member_request(request_id)
        if (field in ("registration", "funding")
                and pro_registration_approved(refreshed.get("registration_status"))
                and refreshed.get("funding_status") == "verified"
                and refreshed.get("status") in ("pending_review", "legacy_review")):
            return await self.member_pro_approve_confirm(update, request_id, automatic=True)
        if field == "registration":
            delivered = await self.send_portal_pro_registration_notice(
                request["user_id"], "Your education entitlement is separate from PRO Signals access.",
                request_id=request_id)
            if not delivered:
                self.db.error("member_notification", "Registration approval was saved; private notification failed.")
        elif request["status"] == "approved":
            message = ("✅ <b>FUNDED-ACCOUNT VERIFICATION RECORDED</b>\n\n"
                       "Your existing PRO Signals access remains unchanged during this update.")
            delivered = await self.bot.send_message(request["user_id"], message, parse_mode="HTML")
        else:
            delivered = await self.send_portal_funding_verified_notice(
                request["user_id"],
                registration_approved=pro_registration_approved(refreshed.get("registration_status")),
            )
        if delivered is False:
            self.db.error("member_notification", "Verification was saved; private notification could not be confirmed.")
        return await self.member_request_screen(update, request_id)

    async def member_request_approve_prompt(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if request and request["destination"] == "education":
            raise ValueError("Educational Group access is self-service and does not require administrator approval.")
        if not request or request["destination"] not in ("education", "analysis"):
            raise ValueError("This destination request cannot be approved through this action.")
        if request["status"] != "pending_review":
            raise ValueError("This request is no longer awaiting review.")
        label = DESTINATION_LABELS[request["destination"]]
        return await self.say(update, f"Confirm approval for {label} only? No other destination will be granted.",
                              [("Confirm Approval", "member_request_approve_confirm",
                                {"request_id": request_id}),
                               ("Back to Request", "member_request", {"request_id": request_id})])

    async def member_request_approve_confirm(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if request and request["destination"] == "education":
            raise ValueError("Educational Group access is self-service and does not require administrator approval.")
        if not request or request["destination"] not in ("education", "analysis") or request["status"] != "pending_review":
            raise ValueError("This request is no longer awaiting approval.")
        stamp = now()
        with self.db.transaction() as c:
            result = c.execute("UPDATE member_requests SET status='approved',admin_decision_by=?,"
                               "admin_decision_at=?,updated=? WHERE id=? AND status='pending_review'",
                               (self.config.admin, stamp, stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("This request was already reviewed.")
            c.execute("INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
                      (request["user_id"], "[]", "destination_applicant", stamp))
            channel = self.config.education_group_id if request["destination"] == "education" else self.config.analysis
            c.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                      (request["user_id"], channel, "invite_pending", stamp))
        self.member_request_event(request_id, self.config.admin, "destination_approved",
                                  f"Administrator approved {DESTINATION_LABELS[request['destination']]} only.")
        op = self.publisher.prepare(self.config.admin, "invite",
                                    {"user": request["user_id"], "channel": channel})
        result = await self.publisher.send(self.config.admin, op)
        if request["destination"] == "education" and self.publisher.operation(op)[0]["status"] == "done":
            invite = self.db.get(f"invite:{op}", {})
            delivery = await self.send_education_welcome(
                request["user_id"], invite.get("invite_link") if isinstance(invite, dict) else None)
            if delivery == "failed":
                try:
                    await self.bot.send_message(
                        self.config.admin,
                        "⚠️ The Educational Group welcome could not be delivered privately. "
                        "Check Recent Errors; the approval remains valid and the invite is still available.")
                except Exception:
                    pass
            elif delivery != "sent":
                try:
                    await self.bot.send_message(
                        self.config.admin,
                        "⚠️ The Educational Group welcome button was not sent because no valid group invite "
                        "was available. The approval remains valid; check the invite operation and group permissions.")
                except Exception:
                    pass
        return await self.operation_result(update, op, result)

    async def member_pro_approve_prompt(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if (not request or request["destination"] != "pro" or
                not pro_registration_approved(request["registration_status"]) or
                request["funding_status"] != "verified" or
                request["status"] not in ("pending_review", "legacy_review")):
            raise ValueError("PRO approval requires manually verified registration and funding.")
        return await self.say(
            update,
            "🔐 <b>PRO SIGNALS ACCESS RECOVERY</b>\n\n"
            f"<b>Applicant:</b> {request['user_id']}"
            f"\n<b>Registration:</b> approved by administrator"
            f"\n<b>Funded-account verification:</b> verified by administrator"
            f"\n<b>Funding evidence submitted:</b> "
            f"{escape(str(request['evidence_submitted_at'] or 'not required for legacy manual check'))}"
            "\n\nConfirm that you explicitly authorize the existing PRO Signals invite workflow.",
            [("Confirm PRO Signals Access", "member_pro_approve_confirm", {"request_id": request_id}),
             ("Back to Request", "member_request", {"request_id": request_id})],
            parse_mode="HTML")

    async def member_pro_approve_confirm(self, update, request_id, automatic=False):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if (not request or request["destination"] != "pro" or
                not pro_registration_approved(request["registration_status"]) or
                request["funding_status"] != "verified" or
                request["status"] not in ("pending_review", "legacy_review")):
            raise ValueError("PRO approval requires manually verified registration and funding.")
        stamp = now()
        existing_access = self.db.rows(
            "SELECT status FROM access WHERE user_id=? AND channel=?",
            (request["user_id"], self.config.signals))
        existing_access_status = existing_access[0]["status"] if existing_access else None
        if existing_access_status in ("invite_pending", "invite_uncertain", "disapproval_pending"):
            raise ValueError("An invite or access change is already pending or uncertain. Review it before continuing.")
        with self.db.transaction() as c:
            result = c.execute("UPDATE member_requests SET status='approved',admin_decision_by=?,"
                               "admin_decision_at=?,updated=? WHERE id=? AND status IN ('pending_review','legacy_review') "
                               "AND registration_status IN ('approved','verified') AND funding_status='verified'",
                               (self.config.admin, stamp, stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("This PRO request was already reviewed.")
            c.execute("INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
                      (request["user_id"], "[]", "destination_applicant", stamp))
            access = c.execute("SELECT status FROM access WHERE user_id=? AND channel=?",
                               (request["user_id"], self.config.signals)).fetchone()
            if not access or access[0] not in ("joined", "member", "administrator", "creator",
                                                "invite_issued", "invite_uncertain"):
                c.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                          (request["user_id"], self.config.signals, "invite_pending", stamp))
        self.member_request_event(
            request_id, self.config.admin,
            "pro_two_stage_access_granted" if automatic else "pro_final_approval",
                                  "PRO Signals access was granted only after registration approval and funded-account verification.")
        if access and access[0] in ("joined", "member", "administrator", "creator", "invite_issued"):
            await self.bot.send_message(request["user_id"],
                                        "✅ <b>PRO SIGNALS ACCESS APPROVED</b>\n\n"
                                        "Your existing access was retained.\n\n" + PRO_ACCESS_REMINDER,
                                        parse_mode="HTML")
            return await self.say(
                update,
                ("✅ <b>PRO SIGNALS ACCESS GRANTED</b>\n\n"
                 "Both registration and funded-account verification passed." if automatic else
                 "✅ <b>PRO SIGNALS ACCESS REVIEWED</b>\n\n"
                 "Existing access was retained; no duplicate invite was sent."),
                [("View Request", "member_request", {"request_id": request_id})],
                parse_mode="HTML")
        op = self.publisher.prepare(self.config.admin, "invite",
                                   {"user": request["user_id"], "channel": self.config.signals})
        result = await self.publisher.send(self.config.admin, op)
        return await self.operation_result(update, op, result)

    async def member_registration_reject_prompt(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if (not request or request["destination"] != "pro" or
                request["registration_status"] not in ("pending_review", "unverified") or
                request["status"] in ("approved", "rejected", "revoked")):
            raise ValueError("This PRO registration is not awaiting a decision.")
        return await self.say(
            update,
            "⚠️ <b>REJECT PRO REGISTRATION?</b>\n\n"
            "This records a registration rejection and blocks new PRO education eligibility. "
            "It does not automatically remove any existing channel membership.",
            [("Confirm Registration Rejection", "member_registration_reject_confirm",
              {"request_id": request_id}),
             ("Back to Request", "member_request", {"request_id": request_id})])

    async def member_registration_reject_confirm(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if (not request or request["destination"] != "pro" or
                request["registration_status"] not in ("pending_review", "unverified") or
                request["status"] in ("approved", "rejected", "revoked")):
            raise ValueError("This PRO registration changed. Review its current status.")
        stamp = now()
        with self.db.transaction() as c:
            result = c.execute(
                "UPDATE member_requests SET registration_status='rejected',status='rejected',"
                "admin_decision_by=?,admin_decision_at=?,updated=? WHERE id=? AND destination='pro' "
                "AND status NOT IN ('approved','rejected','revoked') "
                "AND registration_status IN ('pending_review','unverified')",
                (self.config.admin, stamp, stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("This registration was already reviewed.")
        self.member_request_event(request_id, self.config.admin, "registration_rejected",
                                  "Administrator rejected the PRO registration.")
        delivered = await self.send_pro_outcome(self.member_request(request_id), "REJECTED")
        if not delivered:
            self.db.error("member_notification", "Registration rejection was saved; applicant notification failed.")
        return await self.member_request_screen(update, request_id)

    async def member_funding_reject_prompt(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if (not request or request["destination"] != "pro" or
                request["status"] in ("approved", "rejected", "revoked") or
                request["funding_status"] != "pending_review" or not request.get("evidence_file_id")):
            raise ValueError("Funded-account evidence is not awaiting review.")
        return await self.say(
            update,
            "⚠️ <b>REJECT FUNDED-ACCOUNT EVIDENCE?</b>\n\n"
            "This keeps PRO Signals access locked. Any already-approved education entitlement stays separate.",
            [("Confirm Funding Rejection", "member_funding_reject_confirm", {"request_id": request_id}),
             ("Back to Request", "member_request", {"request_id": request_id})])

    async def member_funding_reject_confirm(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if (not request or request["destination"] != "pro" or
                request["status"] in ("approved", "rejected", "revoked") or
                request["funding_status"] != "pending_review" or not request.get("evidence_file_id")):
            raise ValueError("Funded-account evidence changed. Review its current status.")
        stamp = now()
        with self.db.transaction() as c:
            result = c.execute(
                "UPDATE member_requests SET funding_status='rejected',updated=? WHERE id=? "
                "AND destination='pro' AND status NOT IN ('approved','rejected','revoked') "
                "AND funding_status='pending_review'",
                (stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("Funded-account evidence was already reviewed.")
        self.member_request_event(request_id, self.config.admin, "funding_rejected",
                                  "Administrator rejected the submitted funded-account evidence.")
        delivered = await self.send_portal_funding_rejected_notice(
            request["user_id"], "You may submit new evidence after reviewing the submission requirements.")
        if not delivered:
            self.db.error("member_notification", "Funding rejection was saved; applicant notification failed.")
        return await self.member_request_screen(update, request_id)

    async def member_request_reject_prompt(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["status"] in ("approved", "rejected", "not_yet_eligible", "revoked"):
            raise ValueError("This request is already closed.")
        if self._pro_has_pending_verification(request):
            raise ValueError("Verification is pending. Keep the status as PENDING_REVIEW; do not reject it for waiting.")
        return await self.say(update, "Confirm rejecting this destination request? Existing access to other destinations "
                              "will not be changed.",
                              [("Confirm Rejection", "member_request_reject_confirm", {"request_id": request_id}),
                               ("Back to Request", "member_request", {"request_id": request_id})])

    async def member_request_reject_confirm(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["status"] in ("approved", "rejected", "not_yet_eligible", "revoked"):
            raise ValueError("This request is already closed.")
        if self._pro_has_pending_verification(request):
            raise ValueError("Verification is pending. Keep the status as PENDING_REVIEW; do not reject it for waiting.")
        stamp = now()
        with self.db.transaction() as c:
            result = c.execute(
                "UPDATE member_requests SET status='rejected',admin_decision_by=?,admin_decision_at=?,updated=? "
                "WHERE id=? AND status NOT IN ('approved','rejected','not_yet_eligible') "
                "AND registration_status!='pending_review' AND funding_status!='pending_review'",
                (self.config.admin, stamp, stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("This request changed or verification is still pending. Review its current status.")
        self.member_request_event(request_id, self.config.admin, "request_rejected",
                                  "Administrator rejected this destination request.")
        if request["destination"] == "pro":
            delivered = await self.send_pro_outcome(self.member_request(request_id), "REJECTED")
            if not delivered:
                self.db.error("member_notification", "Applicant could not be notified of the PRO decision.")
        else:
            try:
                await self.bot.send_message(request["user_id"],
                                            f"Thank you for applying for {DESTINATION_LABELS[request['destination']]}. "
                                            "The administrator was unable to approve this request.")
            except Exception:
                self.db.error("member_notification", "Applicant could not be notified of the decision.")
        return await self.member_request_screen(update, request_id)

    async def member_request_more(self, update, request_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        request = self.member_request(request_id)
        if not request or request["status"] in ("approved", "rejected", "not_yet_eligible", "revoked"):
            raise ValueError("This request is already closed.")
        if request["status"] == "information_requested":
            raise ValueError("More information has already been requested. Wait for the applicant's response.")
        stamp = now()
        with self.db.transaction() as c:
            result = c.execute("UPDATE member_requests SET status='information_requested',updated=? "
                               "WHERE id=? AND status NOT IN ('approved','rejected','not_yet_eligible',"
                               "'information_requested')", (stamp, request_id))
            if result.rowcount != 1:
                raise ValueError("This request changed. Review its current status.")
        self.member_request_event(request_id, self.config.admin, "more_information_requested",
                                  "Administrator requested additional information.")
        text = ("Status: MORE_INFORMATION_REQUIRED. The administrator needs more information to review your PRO "
                "application. A pending verification is not a rejection. Reply privately using the button below."
                if request["destination"] == "pro" else
                "The administrator needs more information to review your access request. "
                "Reply privately using the button below.")
        try:
            await self.bot.send_message(
                request["user_id"], text,
                reply_markup=InlineKeyboardMarkup([[
                    self.button(request["user_id"], "Reply to administrator", "member_more_info",
                                {"request_id": request_id})
                ]]))
        except Exception:
            self.db.error("member_notification", "Applicant could not be sent a request for more information.")
        return await self.member_request_screen(update, request_id)

    async def member_info_response(self, update, draft):
        user = update.effective_user.id
        request = self.member_request(draft.get("request_id"))
        if not request or request["user_id"] != user or request["status"] != "information_requested":
            self.db.clear_draft(user)
            raise PermissionError("This information request is no longer active.")
        value = safe_application_answer(update.message.text, 1200)
        stamp = now()
        self.db.execute("UPDATE member_requests SET followup_text=?,status='pending_review',updated=? WHERE id=?",
                        (value, stamp, request["id"]))
        self.member_request_event(request["id"], user, "more_information_received",
                                  "Applicant submitted a private text response.")
        self.db.clear_draft(user)
        await self.notify_member_request(request["id"], "📨 Applicant submitted requested information.")
        return await self.say(update, "✅ Your reply was sent privately to the administrator.")

    async def application(self, update, user):
        rows = self.db.rows("SELECT * FROM applications WHERE user_id=?", (user,))
        if not rows:
            raise ValueError("Application not found.")
        app = rows[0]
        text = f"📨 Applicant {user} · {app['status'].replace('_', ' ')}\n\n" + "\n\n".join(
            f"{q}\n{a}" for q, a in zip(QUESTIONS, json.loads(app["answers"])))
        buttons = []
        if app["status"] == "pending":
            buttons += [("Approve Application", "review", {"user": user, "status": "approved"}),
                        ("Reject Application", "review", {"user": user, "status": "rejected"})]
        if app["status"] == "approved":
            access_rows = {row["channel"]: row["status"]
                           for row in self.db.rows("SELECT * FROM access WHERE user_id=?", (user,))}
            for channel, label in self.access_destinations():
                state = access_rows.get(channel)
                if channel == self.config.signals:
                    pro_request = self.latest_member_request(user, "pro")
                    if pro_request:
                        buttons.append(("Review PRO eligibility", "member_request",
                                        {"request_id": pro_request["id"]}))
                        if ((pro_request["status"] == "approved" or
                             (pro_request["source"] == "legacy" and
                              pro_request["status"] == "legacy_review")) and
                                state in ("invite_pending", "invite_issued", "invite_uncertain", "invite_revoked",
                                          "invite_failed", "joined", "member", "administrator",
                                          "creator", "left", "kicked", "disapproval_pending")):
                            buttons.append(("Disapprove PRO Signals access", "access_disapprove", {
                                "user": user, "channel": channel, "request_id": pro_request["id"],
                            }))
                    if (state in ("invite_issued", "joined", "member", "administrator", "creator") and
                            self.publisher.current_invite_operation(user, channel)):
                        buttons.append(("Revoke PRO invite", "invite_revoke",
                                        {"user": user, "channel": channel}))
                    continue
                if state in ("access_revoked", "disapproval_pending"):
                    if state == "disapproval_pending":
                        buttons.append((f"Continue {label} disapproval", "access_disapprove", {
                            "user": user, "channel": channel,
                        }))
                elif state == "invite_uncertain":
                    buttons.append((f"Review {label} Invite", "operations", {}))
                    if self.publisher.current_invite_operation(user, channel):
                        buttons.append((f"Revoke {label} Invite", "invite_revoke",
                                        {"user": user, "channel": channel}))
                    buttons.append((f"Disapprove {label} access", "access_disapprove", {
                        "user": user, "channel": channel,
                    }))
                elif state == "invite_pending":
                    buttons.append((f"Review {label} Invite", "operations", {}))
                    buttons.append((f"Disapprove {label} access", "access_disapprove", {
                        "user": user, "channel": channel,
                    }))
                else:
                    verb = ("Reissue" if state in ("invite_issued", "joined", "member",
                                                   "administrator", "creator") else
                            "Retry" if state == "invite_failed" else "Issue")
                    buttons.append((f"{verb} {label} Invite", "invite",
                                    {"user": user, "channel": channel}))
                    if state in ("invite_issued", "invite_failed", "invite_revoked", "joined", "member",
                                 "administrator", "creator", "left", "kicked"):
                        buttons.append((f"Disapprove {label} access", "access_disapprove", {
                            "user": user, "channel": channel,
                        }))
                    current_op = self.publisher.current_invite_operation(user, channel)
                    if current_op and state in ("invite_issued", "joined", "member",
                                                "administrator", "creator"):
                        buttons.append((f"Revoke {label} Invite", "invite_revoke",
                                        {"user": user, "channel": channel}))
        for row in self.db.rows("SELECT * FROM access WHERE user_id=?", (user,)):
            name = dict(self.access_destinations()).get(row["channel"], "Access destination")
            text += f"\n{name}: {row['status']}"
        buttons.append(("Refresh Telegram membership", "membership", {"user": user}))
        buttons.append(("Back to Applications", "applications", {}))
        await self.say(update, text[:3900], buttons)

    async def approve(self, update, data):
        self.config.authorize(update.effective_user.id)
        status = data.get("status")
        user = data.get("user")
        channels = []
        if status == "approved":
            channels = data.get("channels")
            allowed = tuple(channel for channel, _ in self.access_destinations())
            if not self.config.ready or not isinstance(channels, list) or not channels:
                raise ValueError("Choose at least one configured destination before approving.")
            if any(channel not in allowed for channel in channels) or len(set(channels)) != len(channels):
                raise ValueError("Choose only configured access destinations.")
            if self.config.signals in channels:
                raise ValueError("PRO Signals access requires the separate registration, funding, and final-approval workflow.")
            if (self.db.postgres or self.config.isolated_test) and not self.publisher.verified:
                raise ValueError("Channel permissions are not verified; approval is paused so access can be issued safely.")
        elif status != "rejected":
            raise ValueError("Choose approve or reject.")
        with self.db.transaction() as c:
            result = c.execute("UPDATE applications SET status=?,updated=? WHERE user_id=? AND status='pending'",
                               (status, now(), user))
            if result.rowcount != 1:
                raise ValueError("Application already reviewed.")
            c.execute("INSERT INTO errors(category,detail,created) VALUES (?,?,?)",
                      ("application_review", f"Admin set application {user} to {status}.", now()))
            if status == "approved":
                for channel in channels:
                    c.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                              (user, channel, "invite_pending", now()))

        if status == "rejected":
            notified = True
            try:
                await self.bot.send_message(
                    user, "Thank you for applying. "
                    "We’re unable to approve your request at this time. "
                    "Please contact the administrator if you have questions.")
            except Exception:
                notified = False
                self.db.error("member_notification", "Applicant could not be notified of the review decision.")
            result = "✅ Application declined."
            if not notified:
                result += " The applicant could not be notified by private message."
            return await self.say(update, result,
                                  [("View application", "application", {"user": user})])

        links, issues, notified = await self.issue_approval_invites(user, channels)
        channel_names = dict(self.access_destinations())
        issued_names = [channel_names[channel] for channel in links]
        issue_names = [channel_names[channel] for channel in issues]
        education_delivery = None
        if self.config.education_group_id in channels:
            education_delivery = await self.send_education_welcome(
                user, links.get(self.config.education_group_id))
        summary = "✅ Application approved."
        if issued_names:
            summary += f" Join-request invite(s) issued for {', '.join(issued_names)}."
        if issue_names:
            summary += f" Invite issue needs attention for {', '.join(issue_names)}. Open Operations for details."
        if not notified and issued_names:
            summary += " The member may not have received the invite. They can open Member Access / Status from the main menu."
        if education_delivery == "missing":
            summary += " Education welcome was not delivered because no approved Education Group invite was available."
        elif education_delivery == "group_missing":
            summary += (" Education welcome button was not sent because the Education Group invite could not be "
                        "created or validated. Check the group ID and bot invite permissions.")
        elif education_delivery == "invalid":
            summary += " Education welcome not sent: configure a valid HTTPS SMH_EDUCATION_LINK."
        elif education_delivery == "failed":
            summary += " The education welcome could not be delivered privately. Check Recent Errors."
        buttons = [("View application", "application", {"user": user})]
        if issues:
            buttons.append(("View Operations", "operations", {}))
        return await self.say(update, summary, buttons)

    async def send_education_welcome(self, user, group_invite_link=None, update=None):
        configured_link = self.config.education_link.strip()
        configured_link_valid = False
        if configured_link:
            try:
                parsed = urlsplit(configured_link)
                configured_link_valid = (parsed.scheme == "https" and bool(parsed.netloc) and
                                         parsed.username is None and parsed.password is None)
            except ValueError:
                configured_link_valid = False
            if not configured_link_valid:
                self.db.error("education_link_invalid",
                              "Configured SMH_EDUCATION_LINK is not a valid HTTPS link.")

        group_link = (group_invite_link or "").strip()
        group_link_valid = False
        if group_link:
            try:
                parsed_group_link = urlsplit(group_link)
                group_host = (parsed_group_link.hostname or "").lower()
                group_link_valid = (
                    parsed_group_link.scheme == "https" and
                    group_host in ("t.me", "www.t.me", "telegram.me", "www.telegram.me") and
                    parsed_group_link.username is None and parsed_group_link.password is None and
                    bool(parsed_group_link.path)
                )
            except ValueError:
                group_link_valid = False
            if not group_link_valid:
                self.db.error("education_group_invite_invalid",
                              "The generated Education Group invite was not a valid HTTPS Telegram link.")

        if group_link_valid:
            link = group_link
        elif self.config.education_group_id:
            self.db.error("education_group_invite_missing",
                          "Education welcome was withheld because no valid generated group invite was available.")
            return "group_missing"
        elif configured_link_valid:
            link = configured_link
        elif configured_link:
            return "invalid"
        else:
            self.db.error("education_link_missing",
                          "Education welcome was not sent because no approved group invite or valid education site is available.")
            return "missing"
        if update is not None and (
                getattr(update.effective_user, "id", None) != user or
                getattr(update.effective_chat, "type", None) != "private"):
            return "invalid"
        try:
            if update is not None:
                await self.say(
                    update, EDUCATION_WELCOME_TEXT,
                    [("📚 Join the Education Community", "assistant_url", {"url": link})])
            else:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📚 Join the Education Community", url=link)
                ]])
                await self.bot.send_message(user, EDUCATION_WELCOME_TEXT, reply_markup=keyboard)
            return "sent"
        except Exception:
            self.db.error("education_invitation_delivery",
                          "Member could not receive the Educational Group welcome by private message.")
            return "failed"

    async def issue_approval_invites(self, user, channels):
        names = dict(self.access_destinations())
        links, issues = {}, []
        for channel in channels:
            op = None
            try:
                op = self.publisher.prepare(self.config.admin, "invite",
                                           {"user": user, "channel": channel})
                await self.publisher.send(self.config.admin, op)
                row, _ = self.publisher.operation(op)
                result = self.db.get(f"invite:{op}")
                if row["status"] == "done" and result and result.get("invite_link"):
                    links[channel] = result["invite_link"]
                    if result.get("previous_invite_revoked") is False:
                        issues.append(channel)
                    continue
                state = row["status"]
            except Exception:
                state = "failed"
                if op:
                    try:
                        state = self.publisher.operation(op)[0]["status"]
                    except Exception:
                        pass
            access_state = ("invite_uncertain" if state == "uncertain" else
                            "invite_failed" if state in ("failed", "abandoned") else "invite_pending")
            self.db.execute("UPDATE access SET status=?,updated=? WHERE user_id=? AND channel=?",
                            (access_state, now(), user, channel))
            if op:
                self.db.error("member_invite_issue", f"Invite for {names[channel]} was not delivered; operation {op} is {state}.")
            else:
                self.db.error("member_invite_issue", f"Invite for {names[channel]} could not be prepared.")
            issues.append(channel)

        parts = ["✅ Your access request is approved."]
        if links:
            parts.append("Your 24-hour access invite(s):")
            for channel, link in links.items():
                if channel == self.config.education_group_id:
                    parts.append(f"{names[channel]} — direct join, one use; do not forward: {link}")
                else:
                    parts.append(f"{names[channel]} — join-request invite: {link}")
            if self.config.education_group_id in links:
                parts.append("Tap the Educational Group link to join directly.")
            if any(channel != self.config.education_group_id for channel in links):
                parts.append("For the other destinations, open each link and request to join; "
                             "the bot will check the request.")
        if issues:
            parts.append("Some invites could not be issued yet. Open My Access / Status from the main menu later or contact the administrator.")
        notified = True
        try:
            await self.bot.send_message(user, "\n".join(parts))
        except Exception:
            notified = False
            self.db.error("member_notification", "Approved member could not be notified; issued links remain available through My Access / Status.")
        return links, issues, notified

    async def revoke_access_invite(self, update, user, channel):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        destinations = dict(self.access_destinations())
        if channel not in destinations:
            raise ValueError("Choose a configured access destination.")
        op = self.publisher.current_invite_operation(user, channel)
        invite = self.db.get(f"invite:{op}") if op else None
        link = invite.get("invite_link") if isinstance(invite, dict) else None
        if not op or not link:
            raise ValueError("No current invite is available to revoke.")
        try:
            await self.bot.revoke_chat_invite_link(chat_id=channel, invite_link=link)
        except Exception:
            self.db.error("member_invite_revoke",
                          "Telegram did not confirm revocation of the current member invite.")
            raise ValueError("Telegram did not confirm that the invite was revoked. Check its status before retrying.") from None
        self.db.put(f"current_invite:{user}:{channel}", "revoked")
        rows = self.db.rows("SELECT status FROM access WHERE user_id=? AND channel=?", (user, channel))
        if rows and rows[0]["status"] not in (
                "joined", "member", "administrator", "creator", "invite_pending", "invite_uncertain"):
            self.db.execute("UPDATE access SET status='invite_revoked',updated=? WHERE user_id=? AND channel=?",
                            (now(), user, channel))
        self.db.error("member_invite_revoked", f"Administrator revoked a {destinations[channel]} invite.")
        return await self.say(update, f"✅ The current {destinations[channel]} invite was revoked. "
                              "This does not remove a member who has already joined.",
                              [("View application", "application", {"user": user})])

    def access_disapproval_context(self, user, channel, request_id=None):
        destinations = dict(self.access_destinations())
        if channel not in destinations:
            raise ValueError("Choose a configured access destination.")
        rows = self.db.rows("SELECT status FROM access WHERE user_id=? AND channel=?",
                            (user, channel))
        if not rows:
            raise ValueError("No access record exists for this member and destination.")
        state = rows[0]["status"]
        if state == "access_revoked":
            raise ValueError("Access to this destination has already been disapproved.")
        if state not in ("invite_pending", "invite_issued", "invite_uncertain", "invite_revoked", "invite_failed",
                         "joined", "member", "administrator", "creator", "left", "kicked",
                         "disapproval_pending"):
            raise ValueError("This destination has no approved access to disapprove.")

        request = None
        if request_id:
            request = self.member_request(request_id)
            expected_destination = {
                self.config.signals: "pro",
                self.config.analysis: "analysis",
                self.config.education_group_id: "education",
            }.get(channel)
            if (not request or request["user_id"] != user or
                    request["destination"] != expected_destination or
                    (request["status"] != "approved" and not (
                        request["destination"] == "pro" and request["source"] == "legacy" and
                        request["status"] == "legacy_review"))):
                raise ValueError("This destination approval is no longer available.")
        else:
            if channel == self.config.signals:
                raise ValueError("PRO access requires its destination-specific approved request.")
            app = self.db.rows("SELECT status FROM applications WHERE user_id=?", (user,))
            if not app or app[0]["status"] != "approved":
                raise ValueError("A destination-specific approved request is required.")
            destination = {
                self.config.analysis: "analysis",
                self.config.education_group_id: "education",
            }.get(channel)
            matching = self.db.rows(
                "SELECT id FROM member_requests WHERE user_id=? AND destination=? "
                "AND status='approved' ORDER BY updated DESC LIMIT 1",
                (user, destination))
            if matching:
                request = self.member_request(matching[0]["id"])
        return destinations[channel], state, request

    async def access_disapprove_prompt(self, update, user, channel, request_id=None):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        label, state, _ = self.access_disapproval_context(user, channel, request_id)
        if state == "disapproval_pending":
            intro = ("A previous disapproval did not finish. New invite requests are blocked while "
                     "you check the Telegram membership state.\n\n")
            confirm_label = "Continue disapproval"
        else:
            intro = ""
            confirm_label = "Confirm disapproval"
        payload = {"user": user, "channel": channel}
        if request_id:
            payload["request_id"] = request_id
        back = (("Back to Request", "member_request", {"request_id": request_id})
                if request_id else ("Back to Application", "application", {"user": user}))
        return await self.say(
            update,
            intro + f"Disapprove {label} access for member {user}?\n\n"
            "The bot will revoke the current invite and remove them if they have joined. "
            "Only this destination is affected; other access stays unchanged. "
            "A temporary Telegram restriction is used to remove a joined member, not a permanent ban. "
            "If Telegram permissions or status checks prevent removal, access remains blocked "
            "pending administrator review.",
            [(confirm_label, "access_disapprove_confirm", payload), back])

    async def access_disapprove_confirm(self, update, user, channel, request_id=None):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        label, prior_state, request = self.access_disapproval_context(user, channel, request_id)
        direct_invite = channel == self.config.education_group_id
        pending_link_note = (
            "An existing one-use Education Group link may still work until used or expired if Telegram "
            "does not confirm revocation; check it in Telegram."
            if direct_invite else
            "New join requests are blocked pending administrator review."
        )

        # Claim first so a second action cannot issue a new invite during removal.
        if prior_state != "disapproval_pending":
            with self.db.transaction() as c:
                result = c.execute(
                    "UPDATE access SET status='disapproval_pending',updated=? "
                    "WHERE user_id=? AND channel=? AND status=?",
                    (now(), user, channel, prior_state))
                if result.rowcount != 1:
                    raise ValueError("Access changed while this action was open. Review the application again.")
            if request:
                self.member_request_event(
                    request_id, self.config.admin, "access_disapproval_started",
                    f"Administrator started disapproving {label} access.")

        invite_revocation_uncertain = False
        invite_op = self.publisher.current_invite_operation(user, channel)
        invite = self.db.get(f"invite:{invite_op}") if invite_op else None
        link = invite.get("invite_link") if isinstance(invite, dict) else None
        if link:
            try:
                await self.bot.revoke_chat_invite_link(chat_id=channel, invite_link=link)
                self.db.put(f"current_invite:{user}:{channel}", "revoked")
            except Exception as exc:
                # Don't blindly retry a revoke whose response is uncertain.
                invite_revocation_uncertain = True
                self.db.error(
                    "member_access_invite_revoke_uncertain",
                    f"Telegram did not confirm invite revocation ({type(exc).__name__}); "
                    f"{pending_link_note}")

        try:
            current_member = await self.bot.get_chat_member(channel, user)
        except Exception as exc:
            self.db.error(
                "member_access_status_uncertain",
                f"Telegram membership could not be checked ({type(exc).__name__}); "
                f"{pending_link_note}")
            return await self.say(
                update, f"⚠️ Telegram could not confirm {label} membership. Access remains pending. "
                f"{pending_link_note} Check the member in Telegram, then use Continue disapproval.",
                [("Continue disapproval", "access_disapprove", {
                    "user": user, "channel": channel,
                    **({"request_id": request_id} if request_id else {}),
                })])

        member_status = getattr(current_member, "status", "")
        is_present = (member_status in ("member", "administrator", "creator") or
                      (member_status == "restricted" and
                       bool(getattr(current_member, "is_member", False))))
        if member_status in ("administrator", "creator"):
            self.db.error(
                "member_access_removal_blocked",
                f"Member {user} is a {member_status} in {label}; access remains blocked pending manual role change.")
            return await self.say(
                update, f"⚠️ Member {user} is an administrator or owner in {label}. Telegram will not "
                "let the bot remove them in this state. Access is pending in the bot; demote them in "
                "Telegram, then continue disapproval.",
                [("Continue disapproval", "access_disapprove", {
                    "user": user, "channel": channel,
                    **({"request_id": request_id} if request_id else {}),
                })])

        if is_present:
            try:
                bot_user = await self.bot.get_me()
                bot_member = await self.bot.get_chat_member(channel, bot_user.id)
            except Exception as exc:
                self.db.error(
                    "member_access_permission_check",
                    f"Telegram could not verify bot removal permissions ({type(exc).__name__}).")
                return await self.say(
                    update, f"⚠️ The bot could not verify its removal permission in {label}. Access "
                    f"is pending. {pending_link_note} Check the bot's administrator permissions, then continue.",
                    [("Continue disapproval", "access_disapprove", {
                        "user": user, "channel": channel,
                        **({"request_id": request_id} if request_id else {}),
                    })])
            if (getattr(bot_member, "status", "") != "administrator" or
                    getattr(bot_member, "can_restrict_members", False) is not True):
                self.db.error(
                    "member_access_permission_missing",
                    f"Bot lacks member-removal permission in {label}; access remains blocked.")
                return await self.say(
                    update, f"⚠️ The bot needs administrator permission to restrict members in {label}. "
                    f"The member is still there. {pending_link_note} Fix permissions, "
                    "then continue disapproval.",
                    [("Continue disapproval", "access_disapprove", {
                        "user": user, "channel": channel,
                        **({"request_id": request_id} if request_id else {}),
                    })])
            try:
                result = await self.bot.ban_chat_member(
                    chat_id=channel, user_id=user, until_date=int(time.time()) + 60)
                if result is not True:
                    raise RuntimeError("Telegram did not confirm removal.")
            except Exception as exc:
                # A timeout may happen after Telegram applied the removal. Read the
                # status once; never blindly repeat the removal.
                try:
                    after = await self.bot.get_chat_member(channel, user)
                    removed = getattr(after, "status", "") in ("left", "kicked")
                except Exception:
                    removed = False
                if not removed:
                    self.db.error(
                        "member_access_removal_uncertain",
                        f"Telegram did not confirm member removal ({type(exc).__name__}); "
                        "access remains blocked pending review.")
                    return await self.say(
                        update, f"⚠️ Telegram did not confirm removal from {label}. Access is pending. "
                        f"{pending_link_note} Check membership in Telegram before continuing.",
                        [("Continue disapproval", "access_disapprove", {
                            "user": user, "channel": channel,
                            **({"request_id": request_id} if request_id else {}),
                        })])

        stamp = now()
        with self.db.transaction() as c:
            result = c.execute(
                "UPDATE access SET status='access_revoked',updated=? "
                "WHERE user_id=? AND channel=? AND status='disapproval_pending'",
                (stamp, user, channel))
            if result.rowcount != 1:
                raise ValueError("Access state changed before disapproval could be recorded.")
            if request:
                result = c.execute(
                    "UPDATE member_requests SET status='revoked',updated=? "
                    "WHERE id=? AND status=?",
                    (stamp, request_id, request["status"]))
                if result.rowcount != 1:
                    raise ValueError("The approved request changed before disapproval could be recorded.")

        if request:
            detail = ("Member was removed from Telegram." if is_present else
                      "Member was already absent from Telegram.")
            self.member_request_event(
                request_id, self.config.admin, "access_disapproved",
                f"Administrator disapproved {label} access. {detail}")
        else:
            self.db.error("member_access_disapproved",
                          f"Administrator disapproved {label} access for member {user}.")

        try:
            await self.bot.send_message(
                user, f"Your {label} access has been disapproved. This affects only {label}; "
                "your access to other destinations is unchanged. Message the administrator privately "
                "if you believe this was a mistake.")
            notified = True
        except Exception as exc:
            notified = False
            self.db.error(
                "member_access_notice_failed",
                f"Private disapproval notice could not be delivered ({type(exc).__name__}).")

        message = f"✅ {label} access was disapproved for member {user}."
        if invite_revocation_uncertain:
            message += f" Telegram did not confirm invite-link revocation. {pending_link_note}"
        if not notified:
            message += " The member could not be notified privately."
        return await self.say(update, message, [
            ("View application", "application", {"user": user}),
        ])

    async def join_request(self, update, context):
        req = update.chat_join_request
        allowed = {channel for channel, _ in self.access_destinations()}
        if req.chat.id not in allowed or not self.config.ready:
            return
        user = req.from_user.id
        issued = self.db.rows("SELECT status FROM access WHERE user_id=? AND channel=?", (user, req.chat.id))
        current_op = self.publisher.current_invite_operation(user, req.chat.id)
        current_invite = self.db.get(f"invite:{current_op}") if current_op else None
        invite_obj = getattr(req, "invite_link", None)
        presented_link = getattr(invite_obj, "invite_link", None)
        current_link = current_invite.get("invite_link") if isinstance(current_invite, dict) else None
        matches_current_invite = bool(current_op and presented_link and current_link == presented_link)
        if matches_current_invite:
            try:
                op_row, payload = self.publisher.operation(current_op)
                matches_current_invite = (
                    op_row["status"] == "done" and
                    payload.get("user") == user and
                    payload.get("channel") == req.chat.id
                )
            except ValueError:
                matches_current_invite = False
        if (self.publisher.invite_authorized(user, req.chat.id) and issued and
                issued[0]["status"] in ("invite_issued", "joined") and matches_current_invite):
            await req.approve()
            self.db.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)", (user, req.chat.id, "joined", now()))
        else:
            await req.decline()

    async def membership_event(self, update, context):
        event = update.chat_member
        if event.chat.id in {channel for channel, _ in self.access_destinations()}:
            user = event.new_chat_member.user.id
            is_education_group = event.chat.id == self.config.education_group_id
            has_application = bool(self.db.rows(
                "SELECT user_id FROM applications WHERE user_id=?", (user,)))
            if is_education_group or has_application:
                if is_education_group and not has_application:
                    self.db.execute(
                        "INSERT OR IGNORE INTO applications (user_id,answers,status,updated) "
                        "VALUES (?,?,?,?)",
                        (user, "[]", "destination_applicant", now()))
                current = self.db.rows(
                    "SELECT status FROM access WHERE user_id=? AND channel=?",
                    (user, event.chat.id))
                if current and current[0]["status"] in ("disapproval_pending", "access_revoked"):
                    return
                self.db.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                                (user, event.chat.id, event.new_chat_member.status, now()))
                if is_education_group:
                    await self.education_onboarding_membership_changed(
                        user, event.new_chat_member.status)
