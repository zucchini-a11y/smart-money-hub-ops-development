"""Administrator review and member opt-out controls for applicant follow-ups."""
import json
import re

from .applicant_followups import (
    ALLOWED_CATEGORIES,
    ApplicantFollowupService,
    DESTINATION_LABELS,
    followup_schema_available,
    get_settings,
    mark_notice_shown,
    record_applicant_activity,
    set_followup_status,
    sending_is_enabled,
)
from .database import now

PENDING_KEY_PREFIX = "applicant_followup_admin_pending:"


class ApplicantFollowupFlows:
    def _applicant_followup_service(self):
        return ApplicantFollowupService(self.db, self.config, self.bot)

    def _followup_pending_key(self, user):
        return f"{PENDING_KEY_PREFIX}{int(user)}"

    def applicant_followup_notice_text(self, user):
        if (not getattr(self.config, "applicant_followups_enabled", False)
                or not followup_schema_available(self.db)):
            return ""
        service = self._applicant_followup_service()
        settings = service.settings()
        state = service.state(user)
        if (not sending_is_enabled(self.config, settings) or not settings["categories"] or
                (state and state.get("consent_notice_at"))):
            return ""
        intervals = ", ".join(str(day) for day in settings["interval_days"])
        return (
            "🔔 <b>PRIVATE FOLLOW-UP NOTICE</b>\n\n"
            f"If you continue an access step, you may receive up to {settings['max_reminders']} "
            f"private progress reminders, scheduled around days {intervals}. "
            "They do not change your application or access decision. "
            "Use the <b>Stop Reminders</b> button at any time."
        )

    async def applicant_followup_ensure_notice(self, update):
        if (update.effective_user.id == self.config.admin
                or not getattr(self.config, "applicant_followups_enabled", False)
                or not followup_schema_available(self.db)):
            return False
        user = update.effective_user.id
        state = self._applicant_followup_service().state(user)
        if not state:
            record_applicant_activity(
                self.db, self.config, user, "welcome", source="member_flow")
        notice = self.applicant_followup_notice_text(user)
        if not notice:
            return False
        await self.say(
            update, notice, [("Stop Reminders", "applicant_followup_stop", {})],
            parse_mode="HTML", admin_chrome=False,
        )
        mark_notice_shown(self.db, user)
        return True

    async def applicant_followup_handle_action(self, update, action, data):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        service = self._applicant_followup_service()
        user = update.effective_user.id

        if not service.schema_available():
            return await self.say(
                update,
                "Applicant follow-up controls are not available in this bot database yet. "
                "No reminders can be sent.",
                admin_chrome=False,
            )
        if action == "applicant_followup_admin":
            return await self.applicant_followup_admin_screen(update)
        if action == "applicant_followup_review":
            return await self.applicant_followup_review_screen(update)
        if action == "applicant_followup_set_schedule":
            self.db.put(self._followup_pending_key(user), {"kind": "schedule"})
            return await self.say(
                update,
                "Send the reminder intervals and maximum count in this format:\n"
                "2,5,9 | 3\n\n"
                "Intervals must be ascending whole days (1–90), with at most five intervals. "
                "The maximum count can be 1–10. This changes the Development/Production app setting "
                "only when you later configure that environment; it does not enable sending.",
                [("Cancel", "applicant_followup_review", {})],
                admin_chrome=False,
            )
        if action == "applicant_followup_toggle_category":
            category = data.get("category")
            if category not in ALLOWED_CATEGORIES:
                raise ValueError("Unknown follow-up category.")
            settings = service.settings()
            enabled = set(settings["categories"])
            enabled.symmetric_difference_update({category})
            service.save_settings({"categories": sorted(enabled), "reviewed": False,
                                   "sample_reviewed": False, "enabled": False})
            return await self.applicant_followup_review_screen(update)
        if action == "applicant_followup_mark_reviewed":
            service.save_settings({"reviewed": True, "enabled": False})
            return await self.applicant_followup_review_screen(
                update, notice="Schedule and category review recorded. Sending is still OFF.")
        if action == "applicant_followup_sample":
            context = {
                "category": "welcome",
                "stage": "welcome",
                "destinations": [],
                "next_action": "Invite the person to open Member Access and choose a destination.",
            }
            try:
                sample = service._validate_message(await service.generate_message(context))
            except Exception:
                return await self.say(
                    update,
                    "Gemini could not produce a safe sample. No applicant was contacted. "
                    "Check the Gemini configuration or try again.",
                    [("Back to Follow-up Review", "applicant_followup_review", {})],
                    admin_chrome=False,
                )
            settings = service.settings()
            settings.update({"sample_previewed": True, "sample_text": sample,
                            "sample_reviewed": False, "enabled": False})
            service.save_settings(settings)
            buttons = [
                ("Approve this sample wording", "applicant_followup_sample_approve", {}),
                ("Generate another sample", "applicant_followup_sample", {}),
                ("Back to Follow-up Review", "applicant_followup_review", {}),
            ]
            return await self.say(
                update, "SAMPLE ONLY — no applicant will receive this message.\n\n" + sample,
                buttons, admin_chrome=False,
            )
        if action == "applicant_followup_sample_approve":
            settings = service.settings()
            if not settings.get("sample_previewed"):
                raise ValueError("Preview a sample before approving it.")
            service.save_settings({"sample_reviewed": True, "enabled": False})
            return await self.applicant_followup_review_screen(
                update, notice="Sample wording approved. Sending remains OFF.")
        if action == "applicant_followup_toggle_enabled":
            settings = service.settings()
            desired = not settings["enabled"]
            if desired:
                if not getattr(self.config, "applicant_followups_enabled", False):
                    return await self.say(
                        update,
                        "Sending remains OFF. The environment-level follow-up flag is OFF; "
                        "this control cannot change it.",
                        [("Back to Follow-up Controls", "applicant_followup_admin", {})],
                        admin_chrome=False,
                    )
                if not settings["reviewed"] or not settings["sample_reviewed"]:
                    return await self.say(
                        update,
                        "Sending remains OFF. Review the schedule and categories, then preview and approve "
                        "the sample wording first.",
                        [("Review Setup", "applicant_followup_review", {})],
                        admin_chrome=False,
                    )
            service.save_settings({"enabled": desired})
            return await self.applicant_followup_admin_screen(
                update, notice=("Follow-ups enabled. Both send gates are active."
                                if desired else "Follow-up sending paused."))
        if action == "applicant_followup_list":
            return await self.applicant_followup_list_screen(update)
        if action == "applicant_followup_open":
            return await self.applicant_followup_detail_screen(update, int(data.get("user_id", 0)))
        if action == "applicant_followup_pause":
            state = service.state(int(data.get("user_id", 0)))
            if not state:
                raise ValueError("Applicant follow-up record not found.")
            if state["status"] == "paused":
                if state["pause_reason"] == "awaiting_admin_review":
                    return await self.say(
                        update, "This applicant is waiting for an administrator review. "
                        "The follow-up scheduler will not send a reminder while that decision is pending.",
                        [("Back", "applicant_followup_open", {"user_id": state["user_id"]})],
                        admin_chrome=False,
                    )
                if state["pause_reason"] == "notice_not_seen":
                    return await self.say(
                        update, "This person must return to a private member flow and see the reminder notice "
                        "before follow-ups can resume.",
                        [("Back", "applicant_followup_open", {"user_id": state["user_id"]})],
                        admin_chrome=False,
                    )
                set_followup_status(self.db, state["user_id"], "active", "administrator_resumed")
            elif state["status"] in ("active", "unable_to_contact"):
                set_followup_status(self.db, state["user_id"], "paused", "administrator_paused")
            else:
                return await self.say(
                    update, f"Current status is {state['status']}; it was not changed.",
                    [("Back", "applicant_followup_open", {"user_id": state["user_id"]})],
                    admin_chrome=False,
                )
            return await self.applicant_followup_detail_screen(update, state["user_id"])
        if action == "applicant_followup_generate":
            return await self.applicant_followup_generate_draft(
                update, service, int(data.get("user_id", 0)))
        if action == "applicant_followup_edit":
            delivery = self.db.rows(
                "SELECT id,status FROM applicant_followup_deliveries WHERE id=?",
                (data.get("delivery_id"),))
            if not delivery or delivery[0]["status"] != "draft":
                raise ValueError("This follow-up draft is no longer editable.")
            self.db.put(self._followup_pending_key(user), {
                "kind": "edit_message", "delivery_id": delivery[0]["id"],
            })
            return await self.say(
                update, "Send the replacement message text. Keep it short and do not add a URL; "
                "configured buttons handle access links. Select Cancel below to stop editing.",
                admin_chrome=False,
            )
        if action == "applicant_followup_send":
            try:
                result = await service.send_delivery(data.get("delivery_id"), manual=True)
            except ValueError as exc:
                return await self.say(
                    update, str(exc),
                    [("Back to Follow-up Controls", "applicant_followup_admin", {})],
                    admin_chrome=False,
                )
            return await self.say(
                update, f"Private follow-up result: {result}.",
                [("Applicant Follow-ups", "applicant_followup_admin", {})],
                admin_chrome=False,
            )
        if action == "applicant_followup_cancel":
            service.cancel_draft(data.get("delivery_id"))
            return await self.say(update, "Draft cancelled; no applicant message was sent.",
                                  [("Applicant Follow-ups", "applicant_followup_admin", {})],
                                  admin_chrome=False)
        if action == "applicant_followup_retry":
            try:
                result = await service.send_delivery(data.get("delivery_id"), manual=False)
            except ValueError as exc:
                return await self.say(update, str(exc),
                                      [("Recent History", "applicant_followup_history", {})],
                                      admin_chrome=False)
            return await self.say(
                update, f"Retry result: {result}. An uncertain delivery is never retried automatically.",
                [("Recent History", "applicant_followup_history", {})],
                admin_chrome=False,
            )
        if action == "applicant_followup_history":
            return await self.applicant_followup_history_screen(
                update, data.get("user_id"))
        raise ValueError("Unknown applicant follow-up action.")

    async def applicant_followup_admin_screen(self, update, notice=""):
        service = self._applicant_followup_service()
        if not service.schema_available():
            return await self.say(
                update,
                "Applicant follow-up controls are not available in this bot database yet. "
                "No reminders can be sent.",
                admin_chrome=False,
            )
        settings = service.settings()
        states = service.states(100)
        due = sum(1 for row in states if row["status"] == "active" and row["next_followup"]
                  and row["next_followup"] <= now())
        failed = len([row for row in service.deliveries(limit=100)
                      if row["status"] in ("failed", "uncertain")])
        env_gate = bool(getattr(self.config, "applicant_followups_enabled", False))
        text = (
            "👥 APPLICANT FOLLOW-UPS\n\n"
            f"Environment send gate: {'ON' if env_gate else 'OFF'}\n"
            f"Administrator control: {'ON' if settings['enabled'] else 'OFF'}\n"
            f"Effective sending: {'ON' if sending_is_enabled(self.config, settings) else 'OFF'}\n"
            f"Schedule: {', '.join(str(day) for day in settings['interval_days'])} days; "
            f"maximum {settings['max_reminders']} reminders\n"
            f"Active records: {sum(row['status'] == 'active' for row in states)}\n"
            f"Due now: {due} (one send maximum per worker cycle)\n"
            f"Failed or uncertain: {failed}\n\n"
            "Messages are private, tied to a user-started access flow, rechecked before sending, "
            "and include Stop Reminders. Uncertain deliveries are never replayed automatically.\n"
            "No applicant message is sent while either send gate is OFF."
        )
        if notice:
            text = notice + "\n\n" + text
        buttons = [
            ("Review Schedule, Categories & Sample", "applicant_followup_review", {}),
            ("Applicants / Upcoming", "applicant_followup_list", {}),
            ("Recent History & Errors", "applicant_followup_history", {}),
        ]
        if settings["enabled"]:
            buttons.insert(0, ("⏸ Pause All Follow-ups", "applicant_followup_toggle_enabled", {}))
        elif env_gate and settings["reviewed"] and settings["sample_reviewed"]:
            buttons.insert(0, ("Enable Follow-ups", "applicant_followup_toggle_enabled", {}))
        return await self.say(update, text, buttons, admin_chrome=False)

    async def applicant_followup_review_screen(self, update, notice=""):
        service = self._applicant_followup_service()
        settings = service.settings()
        text = (
            "FOLLOW-UP REVIEW — SENDING OFF\n\n"
            f"Intervals: {', '.join(str(day) for day in settings['interval_days'])} elapsed days\n"
            f"Maximum reminders: {settings['max_reminders']}\n"
            "Configured destinations (optional and reviewed separately):\n"
            f"• Educational Group: "
            f"{'configured' if self.config.education_group_id and self.config.education_link else 'not configured'}\n"
            f"• Market Analysis: {'configured' if self.config.analysis else 'not configured'}\n"
            f"• PRO Signals: {'configured' if self.config.signals else 'not configured'}\n"
            "Enabled categories:\n"
            + "\n".join(f"• {'ON' if item in settings['categories'] else 'OFF'} — {item}"
                        for item in sorted(ALLOWED_CATEGORIES))
            + "\n\nConfiguration reviewed: "
            + ("yes" if settings["reviewed"] else "no")
            + "\nSample wording approved: "
            + ("yes" if settings["sample_reviewed"] else "no")
            + "\nEnvironment gate: "
            + ("ON" if getattr(self.config, "applicant_followups_enabled", False) else "OFF")
            + "\n\nEducation is optional; PRO Signals and Market Analysis remain separate. "
            "No destination is treated as required unless the applicant selected it."
        )
        if notice:
            text = notice + "\n\n" + text
        buttons = [
            ("Edit reminder intervals", "applicant_followup_set_schedule", {}),
            ("Preview sample wording", "applicant_followup_sample", {}),
        ]
        buttons.extend([
            (f"{'✅' if item in settings['categories'] else '⬜'} {item}",
             "applicant_followup_toggle_category", {"category": item})
            for item in sorted(ALLOWED_CATEGORIES)
        ])
        buttons.extend([
            ("Mark schedule/categories reviewed", "applicant_followup_mark_reviewed", {}),
            ("Back to Follow-up Controls", "applicant_followup_admin", {}),
        ])
        return await self.say(update, text, buttons, admin_chrome=False)

    async def applicant_followup_list_screen(self, update):
        service = self._applicant_followup_service()
        states = service.states(30)
        if not states:
            return await self.say(
                update, "No follow-up records exist yet. Records are created only after a person starts "
                "the private bot or chooses an access step. No existing applicants were backfilled.",
                [("Back", "applicant_followup_admin", {})], admin_chrome=False)
        lines = ["APPLICANTS / UPCOMING FOLLOW-UPS", ""]
        buttons = []
        for state in states:
            destinations = ", ".join(
                DESTINATION_LABELS[item]
                for item in json_list(state.get("destinations"))
                if item in DESTINATION_LABELS
            ) or "not selected"
            lines.append(
                f"ID {state['user_id']} — {state['status']} — {state['stage']} — "
                f"{destinations} — next: {state['next_followup'] or 'none'}")
            buttons.append((f"Open applicant {state['user_id']}", "applicant_followup_open",
                            {"user_id": state["user_id"]}))
        buttons.append(("Back", "applicant_followup_admin", {}))
        return await self.say(update, "\n".join(lines)[:3800], buttons,
                              admin_chrome=False)

    async def applicant_followup_detail_screen(self, update, user_id):
        service = self._applicant_followup_service()
        state = service.state(user_id)
        if not state:
            raise ValueError("Applicant follow-up record not found.")
        destinations = ", ".join(
            DESTINATION_LABELS[item] for item in json_list(state["destinations"])
            if item in DESTINATION_LABELS
        ) or "not selected"
        recent = service.deliveries(user_id, 10)
        text = (
            f"APPLICANT FOLLOW-UP — ID {state['user_id']}\n\n"
            f"Status: {state['status']} ({state['pause_reason'] or 'no pause reason'})\n"
            f"Stage: {state['stage']}\nSelected destinations: {destinations}\n"
            f"Started: {state['first_interaction']}\nLast activity: {state['last_activity']}\n"
            f"Reminders sent: {state['reminders_sent']}\n"
            f"Last reminder: {state['last_followup'] or 'none'}\n"
            f"Next reminder: {state['next_followup'] or 'none'}\n"
            f"Last error: {state['last_error'] or 'none'}\n"
            f"Recent deliveries: {', '.join(row['status'] for row in recent) or 'none'}"
        )
        buttons = [
            (("▶️ Resume" if state["status"] == "paused" else "⏸ Pause"),
             "applicant_followup_pause", {"user_id": state["user_id"]}),
            ("Generate private draft", "applicant_followup_generate",
             {"user_id": state["user_id"]}),
            ("Applicant history", "applicant_followup_history",
             {"user_id": state["user_id"]}),
        ]
        buttons.extend([
            (f"Retry failed delivery {row['id'][:8]}", "applicant_followup_retry",
             {"delivery_id": row["id"]})
            for row in recent if row["status"] == "failed"
        ])
        buttons.append(("Back to applicants", "applicant_followup_list", {}))
        return await self.say(update, text[:3800], buttons, admin_chrome=False)

    async def applicant_followup_history_screen(self, update, user_id=None):
        service = self._applicant_followup_service()
        if user_id is not None:
            rows = service.events(int(user_id), 25)
            deliveries = service.deliveries(int(user_id), 25)
        else:
            rows = self.db.rows(
                "SELECT * FROM applicant_followup_events ORDER BY created DESC LIMIT 25")
            deliveries = service.deliveries(limit=25)
        if not rows and not deliveries:
            text = "No follow-up events or delivery attempts have been recorded."
        else:
            text = "RECENT FOLLOW-UP HISTORY / ERRORS\n\n"
            for item in rows[:20]:
                text += f"{item['created']} — user {item['user_id']} — {item['action']}: {item['detail']}\n"
            text += "\nDeliveries:\n"
            for item in deliveries[:15]:
                text += (f"{item['created']} — user {item['user_id']} — {item['status']} — "
                         f"{item['category']} — {item['error_category'] or 'no error'}\n")
        return await self.say(
            update, text[:3900],
            [("Back to Follow-up Controls", "applicant_followup_admin", {})],
            admin_chrome=False,
        )

    async def applicant_followup_generate_draft(self, update, service, user_id):
        state = service.state(user_id)
        if not state:
            raise ValueError("Applicant follow-up record not found.")
        if not state.get("consent_notice_at"):
            return await self.say(
                update,
                "No draft was generated. The person has not yet seen the follow-up notice in a private flow.",
                [("Back", "applicant_followup_open", {"user_id": user_id})],
                admin_chrome=False,
            )
        context = await service.resolve_context(state)
        if context.get("skip") or context.get("complete"):
            return await self.say(
                update,
                "No draft was generated. " + str(context.get("detail") or context.get("skip") or
                                                    "The access flow is already complete."),
                [("Back", "applicant_followup_open", {"user_id": user_id})],
                admin_chrome=False,
            )
        context["user_id"] = user_id
        settings = service.settings()
        if context["category"] not in settings["categories"]:
            return await self.say(
                update, "That follow-up category is disabled in the administrator settings.",
                [("Review categories", "applicant_followup_review", {}),
                 ("Back", "applicant_followup_open", {"user_id": user_id})],
                admin_chrome=False,
            )
        try:
            message = service._validate_message(await service.generate_message(context))
        except Exception:
            return await self.say(
                update, "Gemini could not create a safe draft. No applicant was contacted.",
                [("Back", "applicant_followup_open", {"user_id": user_id})],
                admin_chrome=False,
            )
        delivery = service.create_manual_draft(
            user_id, context["category"], message, update.effective_user.id)
        preview = (
            f"PRIVATE DRAFT PREVIEW — applicant {user_id}\n"
            "This text has not been sent.\n\n" + message)
        buttons = [
            ("Edit text", "applicant_followup_edit", {"delivery_id": delivery["id"]}),
            ("Confirm & Send privately", "applicant_followup_send", {"delivery_id": delivery["id"]}),
            ("Cancel draft", "applicant_followup_cancel", {"delivery_id": delivery["id"]}),
        ]
        return await self.say(update, preview, buttons, admin_chrome=False)

    async def applicant_followup_pending_text(self, update, text):
        user = update.effective_user.id
        if user != self.config.admin or update.effective_chat.type != "private":
            return False
        key = self._followup_pending_key(user)
        pending = self.db.get(key)
        if not pending:
            return False
        if (text or "").strip().casefold() in ("/cancel", "cancel"):
            self.db.execute("DELETE FROM kv WHERE key=?", (key,))
            await self.say(update, "Follow-up setup input cancelled.", admin_chrome=False)
            return True
        service = self._applicant_followup_service()
        if pending.get("kind") == "schedule":
            match = re.fullmatch(
                r"\s*(\d{1,2}(?:\s*,\s*\d{1,2}){0,4})\s*\|\s*(\d{1,2})\s*",
                text or "",
            )
            if not match:
                await self.say(update, "Use the format 2,5,9 | 3, or select Cancel below.",
                               admin_chrome=False)
                return True
            days = [int(value.strip()) for value in match.group(1).split(",")]
            maximum = int(match.group(2))
            if (any(day < 1 or day > 90 for day in days) or
                    days != sorted(set(days)) or not 1 <= maximum <= 10):
                await self.say(
                    update, "Intervals must be ascending, unique, and 1–90 days; maximum must be 1–10.",
                    admin_chrome=False)
                return True
            settings = service.settings()
            settings.update({
                "interval_days": days,
                "max_reminders": maximum,
                "reviewed": False,
                "sample_reviewed": False,
                "enabled": False,
            })
            service.save_settings(settings)
            self.db.execute("DELETE FROM kv WHERE key=?", (key,))
            await self.applicant_followup_review_screen(
                update, notice="Schedule saved. Sending remains OFF until review.")
            return True
        if pending.get("kind") == "edit_message":
            try:
                message = service._validate_message(text)
                service.update_draft(pending["delivery_id"], message)
            except ValueError as exc:
                await self.say(update, str(exc), admin_chrome=False)
                return True
            self.db.execute("DELETE FROM kv WHERE key=?", (key,))
            row = self.db.rows(
                "SELECT user_id,message FROM applicant_followup_deliveries WHERE id=?",
                (pending["delivery_id"],))
            if row:
                await self.say(
                    update,
                    f"UPDATED PRIVATE DRAFT — applicant {row[0]['user_id']}\n\n{row[0]['message']}\n\n"
                    "This has not been sent.",
                    [("Confirm & Send privately", "applicant_followup_send",
                      {"delivery_id": pending["delivery_id"]}),
                     ("Cancel draft", "applicant_followup_cancel",
                      {"delivery_id": pending["delivery_id"]})],
                    admin_chrome=False,
                )
            return True
        self.db.execute("DELETE FROM kv WHERE key=?", (key,))
        return False

    async def applicant_followup_stop(self, update):
        user = update.effective_user.id
        if update.effective_chat.type != "private":
            return
        if not followup_schema_available(self.db):
            return await self.say(update, "No follow-up reminders are active for this account.")
        state = self._applicant_followup_service().state(user)
        if not state:
            return await self.say(update, "There are no active follow-up reminders for this account.")
        set_followup_status(self.db, user, "opted_out", "member_requested_stop")
        await self.say(
            update, "Follow-up reminders are stopped. This does not change your access or application status.")


def json_list(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []
