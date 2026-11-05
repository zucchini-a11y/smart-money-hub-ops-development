"""Gated, private applicant follow-ups for the main Smart Money Hub bot."""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden

from .database import now, uid
from .gemini_analysis import GeminiAnalysisError, generate_applicant_followup

logger = logging.getLogger("smh.applicant_followups")

DEFAULT_SETTINGS = {
    "enabled": False,
    "reviewed": False,
    "sample_reviewed": False,
    "interval_days": [2, 5, 9],
    "max_reminders": 3,
    "categories": [
        "application_draft",
        "information_requested",
        "registration_step",
        "missing_membership",
    ],
}
ALLOWED_CATEGORIES = frozenset((*DEFAULT_SETTINGS["categories"], "welcome"))
DESTINATION_LABELS = {
    "education": "Educational Group",
    "analysis": "Market Analysis",
    "pro": "PRO Signals",
}
MEMBER_STATUSES = frozenset(("member", "administrator", "creator"))
UNKNOWN_STATUSES = frozenset((
    "pending_review", "legacy_review", "information_requested",
    "awaiting_registration", "not_yet_eligible",
))


def _stamp(value=None):
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(
        timespec="seconds")


def _parse_stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _destinations(value):
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return list(dict.fromkeys(
        item for item in decoded if isinstance(item, str) and item in DESTINATION_LABELS
    ))


def get_settings(db):
    stored = db.get("applicant_followup_settings", {})
    if not isinstance(stored, dict):
        stored = {}
    settings = {**DEFAULT_SETTINGS, **stored}
    days = settings.get("interval_days")
    if (not isinstance(days, list) or not 1 <= len(days) <= 5 or
            any(type(day) is not int or not 1 <= day <= 90 for day in days) or
            days != sorted(set(days))):
        settings["interval_days"] = list(DEFAULT_SETTINGS["interval_days"])
    maximum = settings.get("max_reminders")
    if type(maximum) is not int or not 1 <= maximum <= 10:
        settings["max_reminders"] = DEFAULT_SETTINGS["max_reminders"]
    categories = settings.get("categories")
    if not isinstance(categories, list):
        categories = list(DEFAULT_SETTINGS["categories"])
    settings["categories"] = sorted(
        set(category for category in categories if category in ALLOWED_CATEGORIES))
    for key in ("enabled", "reviewed", "sample_reviewed"):
        settings[key] = settings.get(key) is True
    return settings


def followup_schema_available(db):
    """Return whether the connected bot schema has the additive v9 tables."""
    cached = getattr(db, "_applicant_followup_schema_available", None)
    if cached is not None:
        return cached
    if getattr(db, "postgres", False):
        row = db.conn.execute("SELECT version FROM schema_version").fetchone()
        version = int(row[0]) if row else 0
    else:
        version = int(db.conn.execute("PRAGMA user_version").fetchone()[0])
    available = version >= 9
    db._applicant_followup_schema_available = available
    return available


def sending_is_enabled(config, settings):
    return bool(
        getattr(config, "applicant_followups_enabled", False)
        and settings.get("enabled")
        and settings.get("reviewed")
        and settings.get("sample_reviewed")
    )


def mark_notice_shown(db, user_id):
    if not followup_schema_available(db):
        return
    rows = db.rows(
        "SELECT status,pause_reason FROM applicant_followup_state WHERE user_id=?",
        (int(user_id),))
    if not rows:
        return
    timestamp = now()
    status, reason, next_due = rows[0]["status"], rows[0]["pause_reason"], None
    settings = get_settings(db)
    next_due = _stamp(
        datetime.now(timezone.utc) + timedelta(days=settings["interval_days"][0]))
    if status == "paused" and reason == "notice_not_seen":
        status, reason = "active", ""
    db.execute(
        "UPDATE applicant_followup_state SET consent_notice_at=COALESCE(consent_notice_at,?),"
        "status=?,pause_reason=?,schedule_anchor=?,stage_reminders=0,"
        "next_followup=?,updated=? WHERE user_id=?",
        (timestamp, status, reason, timestamp, next_due, timestamp, int(user_id)),
    )
    _event(db, user_id, "reminder_notice_shown", "Private follow-up terms shown in a user-initiated flow.")


def _event(db, user_id, action, detail="", delivery_id=None):
    db.execute(
        "INSERT INTO applicant_followup_events(id,user_id,delivery_id,action,detail,created) "
        "VALUES (?,?,?,?,?,?)",
        (uid(), int(user_id), delivery_id, str(action)[:60], str(detail)[:500], now()),
    )


def record_applicant_activity(db, config, user_id, stage="welcome", destination=None,
                              *, source="member", allow_create=True):
    """Persist only onboarding milestones, never arbitrary/private message text."""
    if not isinstance(user_id, int) or user_id <= 0 or user_id == config.admin:
        return None
    if not followup_schema_available(db):
        return None
    if stage not in {
        "welcome", "choosing_destination", "application_draft", "information_requested",
        "registration_step", "approved_access", "membership_check", "completed",
    }:
        raise ValueError("Invalid applicant follow-up stage.")
    old_rows = db.rows(
        "SELECT * FROM applicant_followup_state WHERE user_id=?", (user_id,))
    if not old_rows and not allow_create:
        return None
    old = old_rows[0] if old_rows else None
    selected = _destinations(old["destinations"]) if old else []
    had_destination = destination in selected
    if destination in DESTINATION_LABELS and destination not in selected:
        selected.append(destination)
    timestamp = now()
    settings = get_settings(db)
    anchor = _parse_stamp(timestamp)
    stage_changed = old is None or stage != old["stage"] or (
        destination in DESTINATION_LABELS and not had_destination)
    schedule_anchor = timestamp if stage_changed else old["schedule_anchor"]
    stage_reminders = 0 if stage_changed else int(old["stage_reminders"])
    next_due = (
        _stamp(anchor + timedelta(days=settings["interval_days"][0]))
        if stage_changed else old["next_followup"]
    )
    status = old["status"] if old else "active"
    pause_reason = old["pause_reason"] if old else ""
    if status == "unable_to_contact":
        status, pause_reason = "active", ""
    if status == "completed" and stage_changed:
        status, pause_reason = "active", ""
    if status in ("paused", "opted_out"):
        next_due = None
    if (old and old["status"] == "paused" and
            old["pause_reason"] == "awaiting_admin_review" and
            source in ("administrator_decision", "access_progress")):
        status, pause_reason = "active", ""
        next_due = _stamp(anchor + timedelta(days=settings["interval_days"][0]))
        schedule_anchor, stage_reminders = timestamp, 0
    if old and old["status"] == "unable_to_contact":
        schedule_anchor, stage_reminders = timestamp, 0
        next_due = _stamp(anchor + timedelta(days=settings["interval_days"][0]))
    if old:
        db.execute(
            "UPDATE applicant_followup_state SET private_status='available',last_activity=?,"
            "stage=?,destinations=?,status=?,pause_reason=?,stage_reminders=?,"
            "schedule_anchor=?,next_followup=?,last_error='',updated=? WHERE user_id=?",
            (timestamp, stage, json.dumps(selected), status, pause_reason,
             stage_reminders, schedule_anchor, next_due, timestamp, user_id),
        )
    else:
        db.execute(
            "INSERT INTO applicant_followup_state "
            "(user_id,private_status,first_interaction,last_activity,stage,destinations,status,"
            "schedule_anchor,next_followup,created,updated) "
            "VALUES (?,'available',?,?,?,?, 'active',?,?,?,?)",
            (user_id, timestamp, timestamp, stage, json.dumps(selected), timestamp,
             next_due, timestamp, timestamp),
        )
    _event(
        db, user_id, "activity_recorded",
        json.dumps({"stage": stage, "destination": destination, "source": source},
                   separators=(",", ":")),
    )
    return db.rows("SELECT * FROM applicant_followup_state WHERE user_id=?", (user_id,))[0]


def set_followup_status(db, user_id, status, reason=""):
    if status not in ("active", "completed", "paused", "opted_out", "unable_to_contact"):
        raise ValueError("Invalid applicant follow-up status.")
    if not followup_schema_available(db):
        return None
    timestamp = now()
    next_due = None
    if status == "active":
        settings = get_settings(db)
        next_due = _stamp(
            datetime.now(timezone.utc) + timedelta(days=settings["interval_days"][0]))
    db.execute(
        "UPDATE applicant_followup_state SET status=?,pause_reason=?,next_followup=?,"
        "updated=? WHERE user_id=?",
        (status, str(reason)[:200], next_due, timestamp, int(user_id)),
    )
    _event(db, user_id, "status_changed", f"{status}:{reason[:160]}")


def _action_context(db, config, state, requests):
    user_id = int(state["user_id"])
    draft = db.draft(user_id)
    selected = _destinations(state["destinations"])
    by_destination = {}
    for request in requests:
        by_destination.setdefault(request["destination"], request)

    if draft:
        kind = draft.get("kind")
        if kind in ("destination_application", "application", "pro_screening"):
            dest = draft.get("destination")
            return {
                "category": "application_draft",
                "stage": state["stage"],
                "destinations": [DESTINATION_LABELS[dest]] if dest in DESTINATION_LABELS else [],
                "next_action": "Resume the saved access application step in this private chat.",
                "button_action": "assistant_resume",
            }
        if kind == "member_info_response":
            request_id = draft.get("request_id")
            request = next((item for item in requests if item["id"] == request_id), None)
            dest = request.get("destination") if request else None
            return {
                "category": "information_requested",
                "stage": "information_requested",
                "destinations": [DESTINATION_LABELS[dest]] if dest in DESTINATION_LABELS else [],
                "next_action": "Reply to the administrator's information request in the saved private step.",
                "button_action": "assistant_resume",
                "request_id": request_id,
            }
        if kind == "pro_evidence":
            return {
                "category": "application_draft",
                "stage": "application_draft",
                "destinations": ["PRO Signals"],
                "next_action": "Continue the saved private funding-evidence step if you still want to proceed.",
                "button_action": "assistant_resume",
            }

    if not selected:
        return {
            "category": "welcome",
            "stage": state["stage"],
            "destinations": [],
            "next_action": "Open Member Access and choose the destination that suits you.",
            "button_action": "member_apply",
        }

    actionable = []
    joined = []
    for destination in selected:
        request = by_destination.get(destination)
        if request:
            status = str(request.get("status") or "")
            if status in ("pending_review", "legacy_review"):
                return {
                    "skip": "awaiting_admin_review",
                    "detail": f"{destination}:application_pending_review",
                }
            if destination == "pro" and (
                    request.get("registration_status") == "pending_review" or
                    request.get("funding_status") == "pending_review"):
                return {
                    "skip": "awaiting_admin_review",
                    "detail": "pro:registration_or_funding_pending_review",
                }
            if status in ("rejected", "revoked", "not_yet_eligible"):
                continue
            if status == "information_requested":
                return {
                    "category": "information_requested",
                    "stage": "information_requested",
                    "destinations": [DESTINATION_LABELS[destination]],
                    "next_action": "Reply to the administrator's request using the saved private application step.",
                    "button_action": "assistant_resume",
                    "request_id": request["id"],
                }
            if destination == "pro" and status == "awaiting_registration":
                return {
                    "category": "registration_step",
                    "stage": "registration_step",
                    "destinations": ["PRO Signals"],
                    "next_action": "Continue the separate PRO registration and verification steps if you still want to apply.",
                    "button_action": "member_pro_registration",
                    "request_id": request["id"],
                }
        chat_id = {
            "education": config.education_group_id,
            "analysis": config.analysis,
            "pro": config.signals,
        }.get(destination)
        if not chat_id:
            return {"skip": "destination_not_configured", "detail": destination}
        actionable.append((destination, chat_id, request))

    if not actionable and not joined:
        return {"skip": "no_open_applicant_step", "detail": "No actionable destination remains."}

    names = [DESTINATION_LABELS[item[0]] for item in actionable]
    return {
        "category": "missing_membership",
        "stage": "membership_check",
        "destinations": names,
        "missing": actionable,
        "joined": joined,
        "next_action": "Open My Access / Status to continue only the destination steps you selected.",
        "button_action": "member_status",
    }


class ApplicantFollowupService:
    def __init__(self, db, config, bot):
        self.db, self.config, self.bot = db, config, bot

    def schema_available(self):
        return followup_schema_available(self.db)

    def settings(self):
        return get_settings(self.db)

    def save_settings(self, settings):
        current = get_settings(self.db)
        current.update(settings)
        self.db.put("applicant_followup_settings", current)
        _event(self.db, self.config.admin, "settings_updated", "Applicant follow-up settings changed.")
        return get_settings(self.db)

    def states(self, limit=20):
        limit = max(1, min(int(limit), 100))
        return self.db.rows(
            "SELECT * FROM applicant_followup_state ORDER BY updated DESC LIMIT ?", (limit,))

    def state(self, user_id):
        rows = self.db.rows(
            "SELECT * FROM applicant_followup_state WHERE user_id=?", (int(user_id),))
        return rows[0] if rows else None

    def events(self, user_id, limit=25):
        return self.db.rows(
            "SELECT * FROM applicant_followup_events WHERE user_id=? "
            "ORDER BY created DESC LIMIT ?", (int(user_id), max(1, min(int(limit), 100))))

    def deliveries(self, user_id=None, limit=25):
        if user_id is None:
            return self.db.rows(
                "SELECT * FROM applicant_followup_deliveries ORDER BY created DESC LIMIT ?",
                (max(1, min(int(limit), 100)),))
        return self.db.rows(
            "SELECT * FROM applicant_followup_deliveries WHERE user_id=? "
            "ORDER BY created DESC LIMIT ?", (int(user_id), max(1, min(int(limit), 100))))

    async def resolve_context(self, state):
        user_id = int(state["user_id"])
        requests = self.db.rows(
            "SELECT * FROM member_requests WHERE user_id=? ORDER BY updated DESC,created DESC",
            (user_id,),
        )
        context = _action_context(self.db, self.config, state, requests)
        if context.get("skip"):
            return context
        if context["category"] in ("application_draft", "registration_step"):
            known_names = set(context.get("destinations", []))
            selected = _destinations(state["destinations"])
            for destination in selected:
                if DESTINATION_LABELS[destination] not in known_names:
                    continue
                channel_id = {
                    "education": self.config.education_group_id,
                    "analysis": self.config.analysis,
                    "pro": self.config.signals,
                }.get(destination)
                if not channel_id:
                    return {
                        "skip": "destination_not_configured",
                        "detail": destination,
                    }
                try:
                    member = await self.bot.get_chat_member(channel_id, user_id)
                except Exception as exc:
                    return {
                        "skip": "membership_unverifiable",
                        "detail": f"{destination}:{type(exc).__name__}",
                    }
                status = str(getattr(member, "status", ""))
                if status in MEMBER_STATUSES or (
                        status == "restricted" and bool(getattr(member, "is_member", False))):
                    return {
                        "complete": True,
                        "detail": f"{destination}: membership verified.",
                    }

        missing = context.get("missing", [])
        if not missing:
            return context
        refreshed = []
        for destination, channel_id, request in missing:
            try:
                member = await self.bot.get_chat_member(channel_id, user_id)
            except Exception as exc:
                return {
                    "skip": "membership_unverifiable",
                    "detail": f"{destination}:{type(exc).__name__}",
                }
            status = str(getattr(member, "status", ""))
            is_member = status in MEMBER_STATUSES or (
                status == "restricted" and bool(getattr(member, "is_member", False)))
            if is_member:
                continue
            refreshed.append((destination, channel_id, request))
        if not refreshed:
            return {"complete": True, "detail": "All selected destinations were verified."}
        context["missing"] = refreshed
        context["destinations"] = [DESTINATION_LABELS[item[0]] for item in refreshed]
        return context

    def defer(self, user_id, reason, seconds=6 * 3600):
        timestamp = now()
        next_due = _stamp(datetime.now(timezone.utc) + timedelta(seconds=seconds))
        self.db.execute(
            "UPDATE applicant_followup_state SET next_followup=?,last_error=?,updated=? "
            "WHERE user_id=? AND status='active'",
            (next_due, str(reason)[:200], timestamp, int(user_id)),
        )
        _event(self.db, user_id, "followup_deferred", str(reason)[:200])

    def skip_due(self, user_id, category, detail=""):
        timestamp = now()
        if category == "awaiting_admin_review":
            self.db.execute(
                "UPDATE applicant_followup_state SET status='paused',pause_reason=?,"
                "next_followup=NULL,last_error='',updated=? WHERE user_id=? AND status='active'",
                (category, timestamp, int(user_id)),
            )
        elif category == "complete":
            self.db.execute(
                "UPDATE applicant_followup_state SET status='completed',pause_reason=?,"
                "next_followup=NULL,last_error='',updated=? WHERE user_id=?",
                (category, timestamp, int(user_id)),
            )
        elif category == "destination_not_configured":
            self.db.execute(
                "UPDATE applicant_followup_state SET status='paused',pause_reason=?,"
                "next_followup=NULL,last_error=?,updated=? WHERE user_id=?",
                (category, str(detail)[:200], timestamp, int(user_id)),
            )
        else:
            self.defer(user_id, f"{category}:{detail}", seconds=24 * 3600)
        _event(self.db, user_id, "followup_skipped", f"{category}:{detail}"[:400])

    def record_approved_progress(self, user_id, destination, stage):
        record_applicant_activity(
            self.db, self.config, int(user_id), stage=stage, destination=destination,
            source="admin_or_application_event", allow_create=True)

    def refresh_paused_reviews(self):
        """Notice decisions made through the Support Portal without duplicating its writes."""
        rows = self.db.rows(
            "SELECT * FROM applicant_followup_state WHERE status='paused' "
            "AND pause_reason='awaiting_admin_review'")
        for state in rows:
            requests = self.db.rows(
                "SELECT * FROM member_requests WHERE user_id=? ORDER BY updated DESC,created DESC",
                (state["user_id"],),
            )
            latest = {}
            for request in requests:
                latest.setdefault(request["destination"], request)
            pending = False
            actionable = None
            for destination, request in latest.items():
                status = request.get("status")
                if (status in ("pending_review", "legacy_review") or
                        request.get("registration_status") == "pending_review" or
                        request.get("funding_status") == "pending_review"):
                    pending = True
                    break
                if status == "information_requested":
                    actionable = (destination, "information_requested")
                    break
                if status == "awaiting_registration":
                    actionable = (destination, "registration_step")
                    break
                if status == "approved":
                    actionable = (destination, "membership_check")
                    break
            if pending or not requests:
                continue
            if actionable:
                record_applicant_activity(
                    self.db, self.config, int(state["user_id"]), actionable[1],
                    actionable[0], source="access_progress")
                continue
            if all(request.get("status") in
                   ("rejected", "revoked", "not_yet_eligible")
                   for request in latest.values()):
                set_followup_status(
                    self.db, state["user_id"], "completed", "application_decision_closed")

    def _keyboard(self, user_id, context):
        rows = []
        action = context.get("button_action")
        if action == "member_apply":
            rows.append([InlineKeyboardButton(
                "🔐 Member Access",
                callback_data=self.db.button(user_id, "member_apply", {}))])
        elif action == "assistant_resume":
            rows.append([InlineKeyboardButton(
                "▶️ Resume Application",
                callback_data=self.db.button(user_id, "assistant_resume", {}))])
        elif action == "member_pro_registration":
            rows.append([InlineKeyboardButton(
                "Continue PRO Application",
                callback_data=self.db.button(
                    user_id, action, {"request_id": context.get("request_id", "")}))])
        else:
            rows.append([InlineKeyboardButton(
                "📋 Check My Access",
                callback_data=self.db.button(user_id, "member_status", {}))])
            if ("education" in _destinations(
                    self.state(user_id).get("destinations") if self.state(user_id) else "[]")
                    and self.config.education_link):
                rows.append([InlineKeyboardButton(
                    "📚 Open Educational Group", url=self.config.education_link)])
        rows.extend([
            [InlineKeyboardButton(
                "💬 Get Help",
                callback_data=self.db.button(user_id, "assistant_contact", {}))],
            [InlineKeyboardButton(
                "Stop Reminders",
                callback_data=self.db.button(user_id, "applicant_followup_stop", {}))],
        ])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def _validate_message(message):
        message = " ".join(str(message or "").split())
        if not message or len(message) > 900:
            raise GeminiAnalysisError("Gemini returned an empty or oversized follow-up message.")
        lowered = message.casefold()
        forbidden = (
            "http://", "https://", "t.me/", "profit", "guarantee", "earnings",
            "deposit now", "limited offer", "deadline", "urgent", "approved",
            "you have joined", "you have not joined",
        )
        if any(token in lowered for token in forbidden):
            raise GeminiAnalysisError("The generated follow-up failed the safety check.")
        return message

    async def generate_message(self, context):
        allowed_context = {
            key: context.get(key)
            for key in ("category", "stage", "destinations", "next_action")
        }
        # Never send IDs, application answers, evidence, credentials, or private invite URLs to Gemini.
        allowed_context["approved_destination_names"] = [
            DESTINATION_LABELS[d]
            for d in _destinations(
                self.state(context.get("user_id", 0)).get("destinations")
                if context.get("user_id") and self.state(context["user_id"]) else "[]")
        ]
        return await asyncio.to_thread(
            generate_applicant_followup,
            allowed_context,
            api_key=os.getenv("GEMINI_API_KEY", ""),
        )

    def _insert_delivery(self, user_id, request_key, category, status, message="", created_by=None):
        row_id = uid()
        timestamp = now()
        with self.db.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM applicant_followup_deliveries WHERE request_key=?",
                (request_key,),
            ).fetchone()
            if existing:
                return dict(existing), False
            connection.execute(
                "INSERT INTO applicant_followup_deliveries "
                "(id,user_id,request_key,category,reminder_number,status,message,created_by,created,updated) "
                "VALUES (?,?,?,?,0,?,?,?,?,?)",
                (row_id, int(user_id), request_key, category, status,
                 message, created_by, timestamp, timestamp),
            )
        return self.db.rows(
            "SELECT * FROM applicant_followup_deliveries WHERE id=?", (row_id,))[0], True

    def create_manual_draft(self, user_id, category, message, created_by):
        key = f"manual:{int(user_id)}:{uid()}"
        row, created = self._insert_delivery(
            user_id, key, category, "draft", message=message, created_by=created_by)
        if created:
            _event(self.db, user_id, "manual_draft_created", category, row["id"])
        return row

    def update_draft(self, delivery_id, message):
        with self.db.transaction() as connection:
            result = connection.execute(
                "UPDATE applicant_followup_deliveries SET message=?,updated=? "
                "WHERE id=? AND status='draft'",
                (message, now(), delivery_id),
            )
            if not result.rowcount:
                raise ValueError("This follow-up draft is no longer editable.")

    def cancel_draft(self, delivery_id):
        rows = self.db.rows(
            "SELECT user_id FROM applicant_followup_deliveries WHERE id=? AND status='draft'",
            (delivery_id,))
        if not rows:
            raise ValueError("This follow-up draft is no longer available.")
        self.db.execute(
            "UPDATE applicant_followup_deliveries SET status='cancelled',updated=? "
            "WHERE id=? AND status='draft'", (now(), delivery_id))
        _event(self.db, rows[0]["user_id"], "draft_cancelled", "Administrator cancelled the draft.", delivery_id)

    async def send_delivery(self, delivery_id, *, manual=False):
        settings = self.settings()
        if not sending_is_enabled(self.config, settings):
            raise ValueError(
                "Follow-up sending is locked. Review the configuration and sample, then enable the environment gate.")
        delivery_rows = self.db.rows(
            "SELECT * FROM applicant_followup_deliveries WHERE id=?", (delivery_id,))
        if not delivery_rows:
            raise ValueError("Follow-up delivery not found.")
        delivery = delivery_rows[0]
        allowed_statuses = ("draft",) if manual else ("failed",)
        if delivery["status"] not in allowed_statuses:
            raise ValueError(
                "This delivery is not safely retryable. Uncertain sends must be checked before any new message.")
        state = self.state(delivery["user_id"])
        if not state or state["status"] != "active":
            raise ValueError("The applicant is not currently eligible for a follow-up send.")
        if state["private_status"] != "available":
            raise ValueError("The private chat is not currently available for follow-up.")
        if not state.get("consent_notice_at"):
            raise ValueError("The applicant has not yet seen the follow-up notice. No message was sent.")
        context = await self.resolve_context(state)
        if context.get("skip") or context.get("complete"):
            raise ValueError(
                "The applicant's current access status no longer supports this message. "
                "No Telegram message was sent.")
        if context.get("category") != delivery["category"]:
            raise ValueError("The applicant's stage changed. Generate a fresh draft before sending.")
        if delivery["category"] not in settings["categories"]:
            raise ValueError("This follow-up category is disabled.")
        if manual:
            if int(state["reminders_sent"]) >= settings["max_reminders"]:
                raise ValueError("The configured maximum number of applicant reminders has been reached.")
            sent_rows = self.db.rows(
                "SELECT MAX(sent_at) AS last_sent FROM applicant_followup_deliveries "
                "WHERE user_id=? AND status='sent'", (delivery["user_id"],))
            last_sent = _parse_stamp(sent_rows[0]["last_sent"]) if sent_rows else None
            if last_sent and datetime.now(timezone.utc) - last_sent < timedelta(hours=24):
                raise ValueError("Only one applicant reminder may be sent to this person in 24 hours.")
        timestamp = now()
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT d.status,s.status AS applicant_status,s.private_status "
                "FROM applicant_followup_deliveries d JOIN applicant_followup_state s "
                "ON s.user_id=d.user_id WHERE d.id=?",
                (delivery_id,)).fetchone()
            if (not row or row["status"] not in allowed_statuses or
                    row["applicant_status"] != "active" or
                    row["private_status"] != "available"):
                raise ValueError("This delivery changed or was already handled.")
            connection.execute(
                "UPDATE applicant_followup_deliveries SET status='sending',updated=? WHERE id=?",
                (timestamp, delivery_id))
        current_state = self.state(delivery["user_id"])
        if not current_state or current_state["status"] != "active":
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='cancelled',"
                "error_category='applicant_status_changed',updated=? WHERE id=? AND status='sending'",
                (now(), delivery_id),
            )
            raise ValueError("The applicant status changed before sending; no message was sent.")
        try:
            await self.bot.send_message(
                chat_id=delivery["user_id"],
                text=delivery["message"],
                reply_markup=self._keyboard(delivery["user_id"], {
                    "category": delivery["category"],
                    "button_action": "member_status",
                }),
            )
        except (Forbidden, BadRequest) as exc:
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='failed',error_category=?,updated=? "
                "WHERE id=? AND status='sending'",
                (type(exc).__name__, now(), delivery_id),
            )
            self.db.execute(
                "UPDATE applicant_followup_state SET private_status='blocked',status='unable_to_contact',"
                "pause_reason='telegram_delivery_denied',next_followup=NULL,last_error=?,updated=? "
                "WHERE user_id=?",
                (type(exc).__name__, now(), delivery["user_id"]),
            )
            _event(self.db, delivery["user_id"], "delivery_failed",
                   type(exc).__name__, delivery_id)
            return "failed"
        except Exception as exc:
            # A network exception can occur after Telegram accepted the message.
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='uncertain',error_category=?,updated=? "
                "WHERE id=? AND status='sending'",
                (type(exc).__name__, now(), delivery_id),
            )
            self.db.execute(
                "UPDATE applicant_followup_state SET status='paused',pause_reason='uncertain_delivery',"
                "next_followup=NULL,last_error=?,updated=? WHERE user_id=?",
                (type(exc).__name__, now(), delivery["user_id"]),
            )
            _event(self.db, delivery["user_id"], "delivery_uncertain",
                   "Telegram delivery could not be confirmed; automatic retry disabled.", delivery_id)
            return "uncertain"
        timestamp = now()
        self.db.execute(
            "UPDATE applicant_followup_deliveries SET status='sent',sent_at=?,updated=? "
            "WHERE id=? AND status='sending'",
            (timestamp, timestamp, delivery_id),
        )
        state_rows = self.db.rows(
            "SELECT * FROM applicant_followup_state WHERE user_id=?",
            (delivery["user_id"],))
        if state_rows:
            state = state_rows[0]
            updated_settings = self.settings()
            total_sent = int(state["reminders_sent"]) + 1
            stage_sent = int(state["stage_reminders"]) + (0 if manual else 1)
            days = updated_settings["interval_days"]
            if manual:
                if total_sent >= updated_settings["max_reminders"]:
                    next_due, status, reason = None, "paused", "maximum_reminders_reached"
                else:
                    next_due = state["next_followup"]
                    status, reason = state["status"], state["pause_reason"]
            elif total_sent >= updated_settings["max_reminders"] or stage_sent >= len(days):
                next_due = None
                status, reason = "paused", "maximum_reminders_reached"
            else:
                anchor = _parse_stamp(state["schedule_anchor"]) or datetime.now(timezone.utc)
                next_index = min(stage_sent, len(days) - 1)
                target = anchor + timedelta(days=days[next_index])
                if target <= datetime.now(timezone.utc):
                    previous = days[max(0, next_index - 1)]
                    gap = max(1, days[next_index] - previous)
                    target = datetime.now(timezone.utc) + timedelta(days=gap)
                next_due = _stamp(target)
                status, reason = "active", ""
            self.db.execute(
                "UPDATE applicant_followup_state SET reminders_sent=?,stage_reminders=?,"
                "last_followup=?,next_followup=?,status=?,pause_reason=?,last_error='',updated=? "
                "WHERE user_id=?",
                (total_sent, stage_sent, timestamp, next_due, status, reason,
                 timestamp, delivery["user_id"]),
            )
        _event(self.db, delivery["user_id"], "delivery_sent",
               "Private follow-up confirmed sent.", delivery_id)
        return "sent"

    def recover_inflight(self):
        rows = self.db.rows(
            "SELECT id,user_id FROM applicant_followup_deliveries WHERE status='sending'")
        for row in rows:
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='uncertain',"
                "error_category='process_restarted',updated=? WHERE id=? AND status='sending'",
                (now(), row["id"]),
            )
            self.db.execute(
                "UPDATE applicant_followup_state SET status='paused',pause_reason='uncertain_delivery',"
                "next_followup=NULL,last_error='process_restarted',updated=? WHERE user_id=?",
                (now(), row["user_id"]),
            )
            _event(self.db, row["user_id"], "delivery_uncertain",
                   "Process restarted during send; automatic retry disabled.", row["id"])

    def due(self):
        rows = self.db.rows(
            "SELECT * FROM applicant_followup_state WHERE status='active' AND next_followup IS NOT NULL "
            "AND next_followup<=? ORDER BY next_followup,user_id LIMIT 1", (now(),))
        return rows[0] if rows else None

    async def process_due(self, state):
        current = self.state(state["user_id"])
        settings = self.settings()
        if not current or current["status"] != "active" or not sending_is_enabled(self.config, settings):
            return
        if not current.get("consent_notice_at"):
            self.db.execute(
                "UPDATE applicant_followup_state SET status='paused',pause_reason='notice_not_seen',"
                "next_followup=NULL,updated=? WHERE user_id=? AND status='active'",
                (now(), current["user_id"]),
            )
            _event(self.db, current["user_id"], "followup_skipped",
                   "Reminder notice was not shown; wait for the person to return to a private flow.")
            return
        if current["reminders_sent"] >= settings["max_reminders"]:
            set_followup_status(self.db, current["user_id"], "paused", "maximum_reminders_reached")
            return
        due_at = _parse_stamp(current["next_followup"])
        if not due_at:
            self.defer(current["user_id"], "invalid_schedule", 24 * 3600)
            return
        now_dt = datetime.now(timezone.utc)
        # Do not send a backlog of stale reminders after downtime or enablement.
        if now_dt - due_at > timedelta(days=2):
            self.db.execute(
                "UPDATE applicant_followup_state SET schedule_anchor=?,stage_reminders=0,"
                "next_followup=?,updated=? WHERE user_id=? AND status='active'",
                (_stamp(now_dt), _stamp(now_dt + timedelta(days=settings["interval_days"][0])),
                 now(), current["user_id"]),
            )
            _event(self.db, current["user_id"], "stale_reminder_skipped",
                   "Overdue by more than two days; schedule reset to prevent a catch-up burst.")
            return

        context = await self.resolve_context(current)
        if context.get("skip"):
            self.skip_due(
                current["user_id"], context["skip"], context.get("detail", ""))
            return
        if context.get("complete"):
            self.skip_due(current["user_id"], "complete", context.get("detail", ""))
            return
        if context["category"] not in settings["categories"]:
            self.db.execute(
                "UPDATE applicant_followup_state SET status='paused',pause_reason='category_disabled',"
                "next_followup=NULL,updated=? WHERE user_id=? AND status='active'",
                (now(), current["user_id"]),
            )
            _event(self.db, current["user_id"], "followup_skipped",
                   f"Category disabled: {context['category']}")
            return

        context["user_id"] = current["user_id"]
        try:
            message = await self.generate_message(context)
            message = self._validate_message(message)
        except Exception as exc:
            category = type(exc).__name__
            self.defer(current["user_id"], f"gemini_{category}", 6 * 3600)
            logger.warning("applicant_followup_generation_failed category=%s", category)
            return
        latest = self.state(current["user_id"])
        if (not latest or latest["status"] != "active" or
                not latest.get("consent_notice_at") or
                not sending_is_enabled(self.config, self.settings())):
            return
        refreshed = await self.resolve_context(latest)
        if refreshed.get("skip"):
            self.skip_due(current["user_id"], refreshed["skip"], refreshed.get("detail", ""))
            return
        if refreshed.get("complete"):
            self.skip_due(current["user_id"], "complete", refreshed.get("detail", ""))
            return
        if any(refreshed.get(key) != context.get(key) for key in
               ("category", "destinations", "next_action")):
            self.defer(current["user_id"], "applicant_progress_changed_during_generation", 24 * 3600)
            return
        request_key = (
            f"scheduled:{current['user_id']}:{current['schedule_anchor']}:"
            f"{current['stage_reminders']}"
        )
        delivery, created = self._insert_delivery(
            current["user_id"], request_key, context["category"], "sending", message=message)
        if not created:
            if delivery["status"] in ("sent", "sending", "uncertain"):
                self.defer(current["user_id"], "duplicate_delivery_prevented", 24 * 3600)
                return
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='sending',message=?,updated=? "
                "WHERE id=? AND status IN ('failed','skipped')",
                (message, now(), delivery["id"]),
            )
        latest = self.state(current["user_id"])
        if not latest or latest["status"] != "active":
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='cancelled',"
                "error_category='applicant_status_changed',updated=? "
                "WHERE id=? AND status='sending'",
                (now(), delivery["id"]),
            )
            return
        try:
            await self.bot.send_message(
                chat_id=current["user_id"],
                text=message,
                reply_markup=self._keyboard(current["user_id"], context),
            )
        except (Forbidden, BadRequest) as exc:
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='failed',error_category=?,updated=? "
                "WHERE id=? AND status='sending'",
                (type(exc).__name__, now(), delivery["id"]),
            )
            self.db.execute(
                "UPDATE applicant_followup_state SET private_status='blocked',"
                "status='unable_to_contact',pause_reason='telegram_delivery_denied',"
                "next_followup=NULL,last_error=?,updated=? WHERE user_id=?",
                (type(exc).__name__, now(), current["user_id"]),
            )
            _event(self.db, current["user_id"], "delivery_failed",
                   type(exc).__name__, delivery["id"])
            return
        except Exception as exc:
            self.db.execute(
                "UPDATE applicant_followup_deliveries SET status='uncertain',error_category=?,updated=? "
                "WHERE id=? AND status='sending'",
                (type(exc).__name__, now(), delivery["id"]),
            )
            self.db.execute(
                "UPDATE applicant_followup_state SET status='paused',pause_reason='uncertain_delivery',"
                "next_followup=NULL,last_error=?,updated=? WHERE user_id=?",
                (type(exc).__name__, now(), current["user_id"]),
            )
            _event(self.db, current["user_id"], "delivery_uncertain",
                   "Telegram delivery could not be confirmed; automatic retry disabled.", delivery["id"])
            return
        self.db.execute(
            "UPDATE applicant_followup_deliveries SET status='sent',sent_at=?,updated=? "
            "WHERE id=? AND status='sending'",
            (now(), now(), delivery["id"]),
        )
        latest = self.state(current["user_id"])
        total_sent = int(latest["reminders_sent"]) + 1
        stage_sent = int(latest["stage_reminders"]) + 1
        days = settings["interval_days"]
        if total_sent >= settings["max_reminders"] or stage_sent >= len(days):
            next_due, status, reason = None, "paused", "maximum_reminders_reached"
        else:
            anchor = _parse_stamp(latest["schedule_anchor"]) or now_dt
            index = min(stage_sent, len(days) - 1)
            target = anchor + timedelta(days=days[index])
            if target <= datetime.now(timezone.utc):
                gap = max(1, days[index] - days[max(0, index - 1)])
                target = datetime.now(timezone.utc) + timedelta(days=gap)
            next_due, status, reason = _stamp(target), "active", ""
        self.db.execute(
            "UPDATE applicant_followup_state SET reminders_sent=?,stage_reminders=?,"
            "last_followup=?,next_followup=?,status=?,pause_reason=?,last_error='',updated=? "
            "WHERE user_id=?",
            (total_sent, stage_sent, now(), next_due, status, reason, now(), current["user_id"]),
        )
        _event(self.db, current["user_id"], "delivery_sent",
               "Scheduled private follow-up confirmed sent.", delivery["id"])


async def run_applicant_followup_worker(db, config, bot, stop):
    service = ApplicantFollowupService(db, config, bot)
    if not service.schema_available():
        # Keep the long-lived task parked until shutdown instead of returning.
        # The runtime watchdog treats an exited worker as a crash and would
        # otherwise restart it continuously while this optional migration is absent.
        await stop.wait()
        return
    service.recover_inflight()
    while not stop.is_set():
        try:
            if getattr(config, "applicant_followups_enabled", False):
                settings = service.settings()
                if sending_is_enabled(config, settings):
                    service.refresh_paused_reviews()
                    candidate = service.due()
                    if candidate:
                        await service.process_due(candidate)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("applicant_followup_worker_error category=%s", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
