"""Private Telegram UI. All actionable buttons are bound to their recipient."""
import asyncio
import json
import logging
import re
import time
from html import escape
from datetime import date
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .database import uid, now
from .domain import MARKETS, TEMPLATES, confirmation, change, price, safe_text, validate_analysis
from .images import import_chart, render, render_review_copy, as_document
from .chart_analysis import (
    analyze_chart,
    build_analysis_caption,
    format_review_report,
    manual_fields_prompt,
    parse_manual_fields,
)
from .gemini_analysis import (
    GeminiAnalysisError,
    analyze_chart_with_gemini,
    MODEL as GEMINI_ANALYSIS_MODEL,
)
from .profit_screenshot import (
    calculate_trade_result,
    next_target_profit_screenshot,
    read_screenshot_prices,
    saved_screenshot_pips,
    target_profit_screenshots,
    validate_target_exit,
)
from .trade_statistics import format_trade_statistics
from .analysis_poi import extract_poi_setups
from .members import MemberFlows, PRO_ACCESS_REMINDER
from .assistant import AssistantFlows
from .signal_result_flows import SignalResultFlows
from .applicant_followup_ui import ApplicantFollowupFlows
from .education_onboarding import EducationOnboardingFlows
from . import zones, zone_wizard
from .publishing import clean_channel_text, verify_configured_destinations_detailed
from .telegram_style import telegram_text_entities

ACTIONS = [
    ("Add Entry", "entry"), ("Set / Update SL", "sl"), ("Add / Update TP", "tp"),
    ("Take Partial", "partial"), ("Move SL to Breakeven", "be"), ("Trail SL", "trail"),
    ("TP Hit", "hit"), ("Cancel Setup", "cancel"), ("Close Trade", "close"),
    ("Custom Trade Update", "custom"), ("Edit Original Signal", "edit"),
]

logger = logging.getLogger("smh")


def format_targets(targets):
    if not targets:
        return "none recorded"
    labels = []
    for number, target in sorted(targets.items(), key=lambda item: int(item[0])):
        value = target.get("price") if isinstance(target, dict) else target
        if value is None:
            continue
        label = f"TP{number}: {value}"
        if isinstance(target, dict) and target.get("hit"):
            label += f" ({target.get('hit_status', 'hit')})"
        labels.append(label)
    return ", ".join(labels) or "none recorded"


class Handlers(MemberFlows, AssistantFlows, SignalResultFlows, ApplicantFollowupFlows, EducationOnboardingFlows):
    def __init__(self, db, config, bot, publisher, health, support_api=None):
        self.db, self.config, self.bot, self.publisher, self.health = db, config, bot, publisher, health
        self.support_api = support_api
        self._assistant_rate = {}
        self.ensure_legacy_pro_review()
        self.recover_assistant_actions()

    def button(self, user, label, action, data=None):
        return InlineKeyboardButton(label, callback_data=self.db.button(user, action, data))

    async def say(self, update, text, buttons=None, parse_mode=None, *, admin_chrome=True):
        user = update.effective_user.id
        buttons = list(buttons or [])
        if user == self.config.admin:
            if admin_chrome:
                actions = {item[1] for item in buttons}
                if not actions.intersection({"cancel", "zone_wizard_cancel"}):
                    buttons.append(("Cancel Draft", "cancel", {}))
                if "menu" not in actions:
                    buttons.append(("Main Menu", "menu", {}))
        elif self.db.draft(user) and not any(item[1] == "assistant_contact_cancel" for item in buttons):
            buttons += [("Cancel", "member_cancel", {})]
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(label, url=data["url"]) if action == "assistant_url"
            else self.button(user, label, action, data)
        ] for label, action, data in buttons]) if buttons else None
        safe_text = text[:4096]
        message_options = {"reply_markup": markup, "parse_mode": parse_mode}
        if parse_mode is None:
            message_options["entities"] = telegram_text_entities(safe_text)
        await self.bot.send_message(
            update.effective_chat.id, safe_text, **message_options)

    def zone_wizard_nav(self, draft, can_back=True):
        revision = draft["revision"]
        buttons = []
        if can_back:
            buttons.append(("⬅️ Back", "zone_wizard_back", {"revision": revision}))
        buttons.extend([
            ("Cancel", "zone_wizard_cancel", {"revision": revision}),
            ("↩️ Return to Main Menu", "menu", {}),
        ])
        return buttons

    def zone_wizard_choice(self, draft, label, field, value):
        return (label, "zone_wizard_select", {
            "revision": draft["revision"], "field": field, "value": value,
        })

    async def zone_wizard_prompt(self, update, draft, notice=None):
        original = draft
        draft = zone_wizard.normalize(draft)
        if draft is not original:
            self.db.save_draft(update.effective_user.id, draft)
            draft = self.db.draft(update.effective_user.id)
            notice = notice or "This zone will stay active until you mark it expired."
        if draft.get("wizard_version") != 1:
            draft = zone_wizard.new_draft()
            self.db.save_draft(update.effective_user.id, draft)
        step = draft.get("step")
        revision = draft["revision"]
        notice_text = (notice + "\n\n") if notice else ""

        if step == "edit":
            labels = {
                "market": "Market",
                "symbol": "Symbol",
                "low": "Lower zone price",
                "high": "Upper zone price",
                "timeframe": "Timeframe",
                "confirmation": "Required confirmation",
            }
            buttons = [
                (f"Edit {labels[field]}", "zone_wizard_edit_field",
                 {"revision": revision, "field": field})
                for field in zone_wizard.editable_fields(draft)
            ]
            buttons.extend(self.zone_wizard_nav(draft))
            return await self.say(update, notice_text + "✏️ Which setup detail would you like to edit?",
                                  buttons)

        if step == "preview":
            continuation = (
                "The Market Analysis chart will be reused. Confirming these details opens a private, "
                "formatted PRO Signals post preview. It does not publish anything."
                if draft.get("attached_to_analysis") else
                "Confirm saves these details as a draft and continues to the chart step. "
                "It does not publish a message."
            )
            buttons = [
                ("⬅️ Back", "zone_wizard_back", {"revision": revision}),
                ("✏️ Edit", "zone_wizard_edit", {"revision": revision}),
                ("✅ Confirm details", "zone_wizard_confirm", {"revision": revision}),
                ("Cancel", "zone_wizard_cancel", {"revision": revision}),
                ("↩️ Return to Main Menu", "menu", {}),
            ]
            return await self.say(
                update,
                notice_text + zone_wizard.preview_text(draft).replace(
                    "Confirm saves these details as a draft and continues to the chart step. "
                    "It does not publish a message.", continuation),
                buttons,
            )

        if step == "chart":
            buttons = [
                ("⬅️ Back to setup details", "zone_wizard_back", {"revision": revision}),
                ("Cancel", "zone_wizard_cancel", {"revision": revision}),
                ("↩️ Return to Main Menu", "menu", {}),
            ]
            return await self.say(
                update,
                notice_text + "✅ Setup details are saved as a draft.\n"
                "Step 1 of 2: upload the chart for this setup. Nothing has been published.",
                buttons,
            )

        if step == "choose_replacement":
            buttons = [
                (f"Replace {setup.get('poi_direction') or 'zone'} · "
                 f"{setup.get('market', 'Market')} · {setup.get('zone', '')}",
                 "zone_replace_choose", {
                     "revision": revision, "setup_id": setup["id"],
                 })
                for setup in zones.active_setups(self.db)
            ]
            buttons.extend([
                ("⬅️ Back to setup details", "zone_wizard_back", {"revision": revision}),
                ("Cancel", "zone_wizard_cancel", {"revision": revision}),
            ])
            return await self.say(
                update,
                notice_text + "More than one active zone exists. Choose exactly which zone this new post would replace, or go back and add an independent zone.",
                buttons,
            )

        if step == "replacement":
            old_id = draft.get("replaces", "unknown")
            market = draft.get("setup", {}).get("market", "the new market")
            buttons = [
                ("Confirm replacement", "zone_replace", {"revision": revision}),
                ("⬅️ Back to setup details", "zone_wizard_back", {"revision": revision}),
                ("Cancel", "zone_wizard_cancel", {"revision": revision}),
                ("↩️ Return to Main Menu", "menu", {}),
            ]
            return await self.say(
                update,
                notice_text + f"An active setup #{old_id} exists. Confirm replacing it with {market}?\n"
                "The current setup remains active until the new zone + chart is published.",
                buttons,
            )

        choices = []
        can_back = bool(draft.get("history") or draft.get("editing"))
        question = ""
        if step == "market":
            question = "Question 1 of 6 — Which market?"
            choices = [
                self.zone_wizard_choice(draft, "Gold (XAUUSD)", "market", "Gold"),
                self.zone_wizard_choice(draft, "Forex", "market", "Forex"),
                self.zone_wizard_choice(draft, "Bitcoin", "market", "Bitcoin"),
                self.zone_wizard_choice(draft, "Synthetic Indices", "market", "Synthetic Indices"),
                self.zone_wizard_choice(draft, "Other", "market", "Other"),
            ]
        elif step == "other_market":
            question = "Which other market should this setup use? Type its name."
        elif step == "symbol":
            question = "Question 2 of 6 — What is the symbol, if needed?"
            if draft.get("answers", {}).get("market_kind") == "Other":
                choices.append(self.zone_wizard_choice(draft, "Skip symbol", "symbol", zone_wizard.SKIP))
        elif step == "low":
            question = "Question 3 of 6 — What is the lower zone price? Enter a positive price."
        elif step == "high":
            question = "Question 4 of 6 — What is the upper zone price? It must be higher than the lower price."
        elif step == "timeframe":
            question = "Question 5 of 6 — Which timeframe?"
            choices.extend(self.zone_wizard_choice(draft, value, "timeframe", value)
                           for value in zone_wizard.TIMEFRAME_CHOICES)
            choices.extend([
                self.zone_wizard_choice(draft, "Other", "timeframe", zone_wizard.OTHER),
                self.zone_wizard_choice(draft, "Skip", "timeframe", zone_wizard.SKIP),
            ])
        elif step == "timeframe_other":
            question = "Question 5 of 6 — Type the timeframe, or choose Skip."
            choices.append(self.zone_wizard_choice(draft, "Skip", "timeframe_other", zone_wizard.SKIP))
        elif step == "confirmation":
            question = "Question 6 of 6 — What confirmation is required?"
            choices.append(self.zone_wizard_choice(draft, "Skip — not specified", "confirmation", zone_wizard.SKIP))
        else:
            raise ValueError("This setup wizard step is not available. Reopen the draft.")

        choices.extend(self.zone_wizard_nav(draft, can_back))
        return await self.say(update, notice_text + "📍 SETUP ZONE WIZARD\n\n" + question, choices)

    def setup_public_status(self, setup):
        operation_status = None
        if setup.get("status") == "used" and setup.get("operation"):
            rows = self.db.rows("SELECT status FROM operations WHERE id=?", (setup["operation"],))
            operation_status = rows[0]["status"] if rows else None
        return zones.public_status(setup, operation_status)

    async def update_setup_post(self, setup):
        """Edit the existing zone/chart caption; never create a replacement post."""
        if not setup or not setup.get("setup_message_id"):
            return True
        status = self.setup_public_status(setup)
        try:
            await self.bot.edit_message_caption(
                chat_id=self.config.signals,
                message_id=setup["setup_message_id"],
                caption=clean_channel_text(
                    zones.setup_caption(setup, status),
                    [setup.get("id"), setup.get("post_operation")],
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                pass
            else:
                try:
                    self.db.error(
                        "setup_caption_update_failed",
                        f"Setup {setup.get('id', 'unknown')} caption edit failed ({type(exc).__name__}).",
                    )
                except Exception:
                    pass
                return False
        setup["caption_status"] = status
        try:
            current = self.db.get("active_setup")
            with self.db.transaction() as c:
                if current and current.get("id") == setup.get("id"):
                    zones.save_in(c, setup)
                else:
                    zones.save_record_in(c, setup)
        except Exception as exc:
            try:
                self.db.error(
                    "setup_caption_status_persist_failed",
                    f"Setup {setup.get('id', 'unknown')} caption status save failed ({type(exc).__name__}).",
                )
            except Exception:
                pass
            return False
        return True

    async def refresh_expired_setup(self, setup=None):
        setup = setup or self.db.get("active_setup")
        if not setup:
            return True
        if setup.get("status") == "active" and zones.is_expired(setup):
            setup["status"] = "expired"
            try:
                with self.db.transaction() as c:
                    zones.save_in(c, setup)
            except Exception as exc:
                try:
                    self.db.error(
                        "setup_expiry_persist_failed",
                        f"Setup {setup.get('id', 'unknown')} expiry update failed ({type(exc).__name__}).",
                    )
                except Exception:
                    pass
                return False
        expected_status = self.setup_public_status(setup)
        if setup.get("setup_message_id") and setup.get("caption_status") != expected_status:
            return await self.update_setup_post(setup)
        return True

    async def say_rows(self, update, text, rows, parse_mode=None):
        user = update.effective_user.id
        self.config.authorize(user)
        keyboard = [[self.button(user, label, action, data) for label, action, data in row]
                    for row in rows if row]
        safe_text = text[:4096]
        options = {
            "reply_markup": InlineKeyboardMarkup(keyboard) if keyboard else None,
            "parse_mode": parse_mode,
        }
        if parse_mode is None:
            options["entities"] = telegram_text_entities(safe_text)
        await self.bot.send_message(update.effective_chat.id, safe_text, **options)

    async def command(self, update, context):
        if update.effective_chat.type != "private":
            return
        raw_command = update.message.text.strip()
        command = raw_command.split()[0].split("@")[0]
        argument = raw_command.partition(" ")[2].strip()
        user = update.effective_user.id
        if command == "/myid":
            return await self.say(update, f"Your Telegram user ID: {user}\n"
                                  "Share it only with the administrator if they need it for access setup.")
        if command == "/apply" and user != self.config.admin:
            if self.db.draft(user):
                return await self.assistant_resume(update)
            return await self.request_destination_selection(update)
        if command == "/status" and user != self.config.admin:
            return await self.member_action(update, "member_status", {})
        if command == "/stop" and user != self.config.admin:
            return await self.applicant_followup_stop(update)
        if command in ("/education", "/analysis", "/pro") and user != self.config.admin:
            return await self.assistant_topic(update, command[1:])
        if command == "/contact":
            if user == self.config.admin:
                return await self.assistant_admin_panel(update)
            return await self.assistant_begin_contact(update)
        if command == "/assistant":
            self.config.authorize(user, update.effective_chat.type)
            if argument.lower() in ("on", "off"):
                return await self.assistant_toggle(update, argument.lower() == "on")
            return await self.assistant_admin_panel(update)
        if command == "/faq":
            self.config.authorize(user, update.effective_chat.type)
            if argument.lower().startswith("set "):
                return await self.assistant_faq_set(update, argument)
            return await self.assistant_faq_screen(update)
        if command == "/reply":
            self.config.authorize(user, update.effective_chat.type)
            self.db.execute("DELETE FROM kv WHERE key=?",
                            (self.assistant_reply_pending_key(user),))
            case_id, separator, reply_text = argument.partition(" ")
            if not separator or not case_id or not reply_text.strip():
                return await self.say(update, "Send the case reference followed by the private reply text. "
                                      "Replies are never retried if delivery is uncertain.")
            return await self.assistant_reply_to_member(update, case_id, reply_text.strip())
        if command == "/help":
            if user == self.config.admin:
                help_text = ("ℹ️ Help\n\n"
                             "Open the administrator menu for bot and access controls.\n"
                              "Applications and Member Access let you review each destination separately.\n"
                             "Use the FAQ controls to manage rule-based answers and Operations to check service health.\n"
                             "The private reply fallback is available from the support case controls.\n\n"
                             "This bot does not connect to a broker or place orders. "
                             "Never send passwords or bot tokens here.")
            else:
                help_text = ("ℹ️ Help\n\n"
                             "Choose Member Access to begin or continue an access application.\n"
                              "Choose My Access Status to check your application and access.\n"
                             "Choose an individual destination to learn more, or Contact Administrator for help.\n"
                              "My Access and Invites show each approved destination separately. Educational Group access is optional.\n"
                             "For help, contact the administrator. This bot does not connect to a broker "
                             "or place orders. Trading involves risk.")
            return await self.say(update, help_text)
        if command == "/cancel":
            if self.db.get(f"assistant:contact_pending:{user}"):
                return await self.assistant_cancel_contact(update)
            if user == self.config.admin and self.db.get(self.assistant_reply_pending_key(user)):
                return await self.assistant_reply_cancel(update)
            self.db.clear_draft(user)
            return await self.say(update, "✅ Your current draft has been cancelled. Anything already posted remains unchanged.")
        if command == "/start" and user != self.config.admin:
            return await self.member_start(update)
        self.config.authorize(user, update.effective_chat.type)
        if command == "/health":
            return await self.health_screen(update)
        await self.menu(update)

    async def unknown_command(self, update, context):
        if update.effective_chat.type != "private":
            return
        if update.effective_user.id == self.config.admin:
            return await self.say(update, "I don’t recognize that command. Choose an option from the menu.")
        if not self.assistant_enabled():
            return await self.say(
                update, self.assistant_inactive_text(), self.assistant_inactive_buttons()
            )
        return await self.say(update, "I don’t recognize that command. Choose a button or send a question.",
                              [("📝 Apply for Access", "assistant_apply", {}),
                               ("🔎 Check My Access", "assistant_status", {}),
                               ("💬 Contact Administrator", "assistant_contact", {})])

    async def menu(self, update, notice=None):
        self.config.authorize(update.effective_user.id)
        expired_setups = zones.active_setups(self.db, include_expired=True)
        status_update_failed = False
        for candidate in expired_setups:
            if zones.is_expired(candidate):
                status_update_failed = (
                    not await self.refresh_expired_setup(candidate) or status_update_failed
                )
        active_setups = zones.active_setups(self.db)
        text = "📊 VAYDA SMART MONEY HUB\nAdministrator control panel\n\n"
        if notice:
            text += notice + "\n\n"
        if status_update_failed:
            text += "⚠️ The expired-zone status could not be fully refreshed; the zone remains ineligible for a signal. Check PRO Signals.\n\n"
        text += ("✅ Publishing is verified and enabled." if self.publisher.verified and self.config.allow_publishing else
                 "🔒 Publishing is locked. The administrator and both channels must be verified before it can be enabled.")
        if active_setups:
            from datetime import datetime, timezone
            text += f"\n\n{len(active_setups)} active zone{'s' if len(active_setups) != 1 else ''}:"
            for setup in active_setups:
                direction = setup.get("poi_direction")
                label = f"{direction} POI" if direction in ("BUY", "SELL") else "Zone"
                approximate = "Approx. " if setup.get("approximate_zone") else ""
                text += (
                    f"\n\nSetup #{setup['id']} · {label} · {setup['market']} · "
                    f"{approximate}{setup['zone']}"
                    f"\nTimeframe: {setup.get('timeframe') or 'not supplied'}"
                    f"\nChart: {'attached' if setup.get('image') else 'missing'}"
                    f"\nExpiry: {'Manual — mark expired in Zone & Signals' if setup.get('expires') is None else datetime.fromtimestamp(setup['expires'], timezone.utc).isoformat()}"
                    f"\nConfirmation: {'recorded' if setup.get('confirmation') else 'awaiting'}"
                )
        else:
            text += "\n\nNo active setup. Open Zone & Signals to create and publish a zone before recording confirmation."
            last_setup = self.db.get("active_setup")
            if last_setup and not self.config.isolated_test:
                text += (
                    f"\n\nLast Setup #{last_setup.get('id', 'unknown')} · "
                    f"{str(last_setup.get('status', 'unknown')).title()}"
                    f"\nMarket: {last_setup.get('market', 'not supplied')}"
                    f"\nZone: {last_setup.get('zone', 'not supplied')}"
                )
        buttons = [
            ("📍 Zone & Signals", "admin_category", {"category": "zone"}),
            ("💼 Trade Management", "admin_category", {"category": "trades"}),
            ("📊 Analysis & Drafts", "admin_category", {"category": "analysis"}),
            ("👥 Members & Access", "admin_category", {"category": "members"}),
            ("⚙️ System & Records", "admin_category", {"category": "system"}),
        ]
        if self.config.isolated_test and self.config.education_episode_01_url:
            buttons.append(("📚 Preview Education DMs", "admin_education_preview", {}))
        await self.say(update, text, buttons, admin_chrome=False)

    def recent_market_analysis_operations(self, limit=8):
        results = []
        rows = self.db.rows(
            "SELECT id,message_id,payload,created FROM operations "
            "WHERE kind='analysis' AND status='done' AND message_id IS NOT NULL "
            "ORDER BY created DESC LIMIT 40"
        )
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if (payload.get("destination") != "analysis" or
                    payload.get("channel") != self.config.analysis):
                continue
            results.append({**row, "payload": payload})
            if len(results) >= limit:
                break
        return results

    async def zone_analysis_link_list(self, update, setup_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        setup = zones.active(self.db, setup_id)
        if self.db.get(f"zone_tapped_operations:{setup_id}"):
            return await self.say(
                update,
                "The Zone Tapped update has already been prepared. Its Market Analysis link can no longer be changed.",
                [("↩️ Zone & Signals", "admin_category", {"category": "zone"})],
                admin_chrome=False,
            )

        posts = self.recent_market_analysis_operations()
        buttons = []
        current_operation = setup.get("market_analysis_operation_id")
        for row in posts:
            payload = row["payload"]
            snippet = re.sub(r"<[^>]*>", "", str(payload.get("text") or ""))
            snippet = " ".join(snippet.split())[:48] or "Market Analysis"
            prefix = "✅ " if row["id"] == current_operation else ""
            buttons.append((
                f"{prefix}{snippet}",
                "zone_analysis_link",
                {"setup_id": setup["id"], "operation_id": row["id"]},
            ))
        if current_operation:
            buttons.append(("Unlink Market Analysis Post", "zone_analysis_unlink",
                            {"setup_id": setup["id"]}))
        buttons.append(("↩️ Zone & Signals", "admin_category", {"category": "zone"}))
        text = (
            "🔗 LINK MARKET ANALYSIS\n\n"
            "Choose a completed post from the configured Market Analysis channel. "
            "The next Zone Tapped update will reply to the selected post and the original PRO Signals zone."
        )
        if not posts:
            text = (
                "No completed Market Analysis posts were found in the configured channel. "
                "Publish a Market Analysis post first, then return here to link it."
            )
        return await self.say(update, text, buttons, admin_chrome=False)

    async def zone_analysis_link(self, update, setup_id, operation_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        setup = zones.active(self.db, setup_id)
        if self.db.get(f"zone_tapped_operations:{setup_id}"):
            raise ValueError("The Zone Tapped update is already prepared; its link cannot be changed.")
        row, payload = self.publisher.operation(operation_id)
        if (row["kind"] != "analysis" or row["status"] != "done" or
                row["message_id"] is None or payload.get("destination") != "analysis" or
                payload.get("channel") != self.config.analysis):
            raise ValueError("Choose a completed Market Analysis post from the configured channel.")
        with self.db.transaction() as connection:
            current = zones.active(self.db, setup_id)
            if self.db.get(f"zone_tapped_operations:{setup_id}"):
                raise ValueError("The Zone Tapped update was prepared before this link was saved.")
            current.update(
                market_analysis_message_id=row["message_id"],
                market_analysis_operation_id=operation_id,
            )
            zones.save_in(connection, current)
        return await self.say(
            update,
            "✅ Market Analysis post linked. The next Zone Tapped update will reply to it and the original PRO Signals zone.",
            [("↩️ Zone & Signals", "admin_category", {"category": "zone"})],
            admin_chrome=False,
        )

    async def zone_analysis_unlink(self, update, setup_id):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        setup = zones.active(self.db, setup_id)
        if self.db.get(f"zone_tapped_operations:{setup_id}"):
            raise ValueError("The Zone Tapped update is already prepared; its link is locked.")
        setup.pop("market_analysis_message_id", None)
        setup.pop("market_analysis_operation_id", None)
        with self.db.transaction() as connection:
            zones.save_in(connection, setup)
        return await self.say(
            update, "✅ Market Analysis post unlinked from this zone.",
            [("↩️ Zone & Signals", "admin_category", {"category": "zone"})],
            admin_chrome=False,
        )

    async def admin_category(self, update, category):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        back = [("↩️ Admin Home", "menu", {})]
        if category == "zone":
            setups = zones.active_setups(self.db, include_expired=True)
            failed = False
            for candidate in setups:
                if zones.is_expired(candidate):
                    failed = not await self.refresh_expired_setup(candidate) or failed
            setups = zones.active_setups(self.db)
            setup = setups[0] if len(setups) == 1 else self.db.get("active_setup")
            buttons = []
            zone_update_notice = ""
            analysis_link_notice = ""
            if len(setups) > 1:
                lines = [
                    "📍 ZONE & SIGNALS",
                    "",
                    "Independent active POIs. Each zone has its own confirmation and controls.",
                    "A POI touch alone is never entry confirmation.",
                ]
                buttons.extend([
                    ("➕ Add independent BUY POI", "zone_new", {
                        "independent": True, "poi_direction": "BUY"}),
                    ("➕ Add independent SELL POI", "zone_new", {
                        "independent": True, "poi_direction": "SELL"}),
                ])
                for item in setups:
                    direction = item.get("poi_direction")
                    label = (
                        f"{'🟢 BUY' if direction == 'BUY' else '🔴 SELL' if direction == 'SELL' else '📍 ZONE'} "
                        f"· {item.get('market', 'Market')} · {item.get('zone', '')}"
                    )
                    if item.get("approximate_zone"):
                        label = "Approx. " + label
                    lines.extend([
                        "",
                        f"{label}",
                        f"Status: {'confirmation recorded' if item.get('confirmation') else 'awaiting confirmation'}",
                    ])
                    data = {"setup_id": item["id"]}
                    buttons.append((f"✏️ Replace {direction or 'zone'} POI", "zone_new", {
                        "replace_setup_id": item["id"],
                    }))
                    if not item.get("confirmation"):
                        buttons.append((
                            f"🧭 Record confirmation · {direction or item['market']}",
                            "zone_confirmation", data))
                    if not self.db.get(f"zone_tapped_operations:{item['id']}"):
                        buttons.append((
                            f"📍 Zone Tapped · {direction or item['market']}",
                            "zone_tapped", data))
                    if not self.db.get(f"zone_tapped_operations:{item['id']}"):
                        buttons.append((
                            f"🔗 Link Market Analysis · {direction or item['market']}",
                            "zone_analysis_link_list", data))
                    if item.get("confirmation"):
                        directions = [direction] if direction in ("BUY", "SELL") else ["BUY", "SELL"]
                        for signal_direction in directions:
                            buttons.append((
                                f"{'🟢' if signal_direction == 'BUY' else '🔴'} "
                                f"{signal_direction} NOW · {direction or item['market']}",
                                "new_signal", {**data, "direction": signal_direction}))
                    buttons.append((
                        f"Cancel {direction or 'zone'} POI",
                        "zone_cancel", data))
                    buttons.append((
                        f"🚫 Mark {direction or 'zone'} POI expired",
                        "zone_expire", data))
                if failed:
                    lines.append(
                        "\n⚠️ An expired-zone status could not be fully refreshed. Check PRO Signals.")
                text = "\n".join(lines)
            elif setup:
                try:
                    zones.active(self.db, setup["id"])
                    eligible = True
                except ValueError:
                    eligible = False
                buttons.append((
                    "📊 Market Analysis + PRO POI",
                    "new_analysis",
                    {"paired_pro_zone": True},
                ))
                buttons.extend([
                    ("➕ Add independent BUY POI", "zone_new", {
                        "independent": True, "poi_direction": "BUY"}),
                    ("➕ Add independent SELL POI", "zone_new", {
                        "independent": True, "poi_direction": "SELL"}),
                    ("📍 Replace Zone + Chart", "zone_new", {
                        "replace_setup_id": setup["id"]}),
                ])
                if eligible:
                    data = {"setup_id": setup["id"]}
                    tapped_operations = self.db.get(
                        f"zone_tapped_operations:{setup['id']}")
                    if not tapped_operations:
                        buttons.append((
                            "🔗 Change Market Analysis Link" if setup.get("market_analysis_message_id")
                            else "🔗 Link Market Analysis Post",
                            "zone_analysis_link_list", data))
                        analysis_link_notice = (
                            "\n\n🔗 A Market Analysis post is linked to this zone."
                            if setup.get("market_analysis_message_id") else
                            "\n\nNo Market Analysis post is linked to this zone yet.")
                    elif setup.get("market_analysis_message_id"):
                        analysis_link_notice = (
                            "\n\n🔗 Market Analysis link is locked because the Zone Tapped update "
                            "has already been prepared.")
                    if not tapped_operations:
                        buttons.append(("📍 Zone Tapped — Update Both Channels",
                                        "zone_tapped", data))
                    else:
                        operation_rows = {
                            destination: self.publisher.operation(operation_id)[0]
                            for destination, operation_id in tapped_operations.items()
                        }
                        if all(row["status"] == "done" for row in operation_rows.values()):
                            zone_update_notice = "\n\n✅ Zone Tapped update sent to both channels."
                        else:
                            zone_update_notice = (
                                "\n\nZone Tapped update status: "
                                f"PRO Signals — {operation_rows.get('signals', {}).get('status', 'unknown')}; "
                                f"Market Analysis — {operation_rows.get('analysis', {}).get('status', 'unknown')}."
                            )
                        if any(row["status"] in ("prepared", "retryable")
                               for row in operation_rows.values()):
                            buttons.append(("📍 Continue Zone Tapped Update",
                                            "zone_tapped", data))
                    buttons.append(
                        ("🧭 Record Observed Confirmation" if not setup.get("confirmation")
                         else "✏️ Update Confirmation", "zone_confirmation", data))
                    buttons.append(("Cancel Zone", "zone_cancel", data))
                    buttons.append(("🚫 Mark Zone Expired", "zone_expire", data))
                    if setup.get("confirmation"):
                        buttons.extend([
                            ("🟢 BUY NOW", "new_signal",
                             {**data, "direction": "BUY"}),
                            ("🔴 SELL NOW", "new_signal",
                             {**data, "direction": "SELL"}),
                        ])
                if not eligible:
                    text = ("📍 ZONE & SIGNALS\n\n"
                            "The saved setup is not eligible for a signal. Create a new zone and attach its matching chart.")
                elif not setup.get("confirmation"):
                    text = ("📍 ZONE & SIGNALS\n\n"
                            "The zone and chart are saved. Mark Zone Tapped only after observing price reach the POI. "
                            "A POI touch is not confirmation. Wait for the required confirmation, then record only what you observed. "
                            "BUY/SELL controls appear only after confirmation.")
                else:
                    publishing_status = (
                        "ON and verified" if self.config.allow_publishing and self.publisher.verified
                        else "OFF or not verified"
                    )
                    text = ("📍 ZONE & SIGNALS\n\n"
                            "You can mark when price reaches the POI using the Zone Tapped button; "
                            "that update is not an entry signal. "
                            "Confirmation is recorded. Choose BUY NOW or SELL NOW to set and review the trade details. "
                            "The channel post will show only the direction. "
                            f"Publishing is {publishing_status}; it is checked again before sending.")
                text += zone_update_notice
                text += analysis_link_notice
                if failed:
                    text += "\n\n⚠️ The expired-zone status could not be fully refreshed. Check PRO Signals."
            else:
                text = ("📍 ZONE & SIGNALS\n\n"
                        "Step 1: enter the zone details and attach its chart.\n"
                        "Step 2: review and publish the zone + chart to PRO Signals.\n"
                        "Step 3: after observing the required confirmation, record it here; then choose BUY or SELL.")
                buttons.append((
                    "📊 Market Analysis + PRO POI",
                    "new_analysis",
                    {"paired_pro_zone": True},
                ))
                buttons.append((
                    "📍 Start Zone Setup", "zone_new", {"choose_direction": True}))
        else:
            categories = {
                "trades": (
                    "💼 TRADE MANAGEMENT",
                    "Manage open trades, review signal controls, and browse completed trade history.",
                    [
                        ("📋 Active Trades", "trades", {}),
                        ("📤 Pending Result Posts", "signal_results_list", {}),
                        ("🎛️ Signal Management Controls", "controls", {}),
                        ("📚 Trade History", "history", {}),
                        ("📊 Trade Statistics", "trade_stats", {}),
                    ],
                ),
                "analysis": (
                    "📊 ANALYSIS & DRAFTS",
                    "Prepare educational Market Analysis and review drafts before publishing.",
                    [
                        ("📊 Prepare Market Analysis", "new_analysis", {}),
                        ("📤 Send posted POI to PRO", "pro_import_start", {}),
                        ("📸 Upload Chart", "upload", {}),
                        ("🖍️ Annotate a Chart", "annotate", {}),
                        ("✍️ Edit Caption", "caption", {}),
                        ("👁️ Preview Draft / Resume", "preview", {}),
                        ("📢 Publish Analysis", "analysis_publish", {}),
                    ],
                ),
                "members": (
                    "👥 MEMBERS & ACCESS",
                    "Review access requests, support conversations, and applicant follow-ups.",
                    [
                        ("📨 Applications / Member Access", "applications", {}),
                        ("🤝 Member Support & FAQs", "assistant_admin", {}),
                        ("⏰ Applicant Follow-ups", "applicant_followup_admin", {}),
                    ],
                ),
                "system": (
                    "⚙️ SYSTEM & RECORDS",
                    "Review bot health, backups, settings, and publishing operations.",
                    [
                        ("🔎 Verify Administrator", "publishing_verify", {"scope": "administrator"}),
                        ("🔎 Verify PRO Signals", "publishing_verify", {"scope": "signals"}),
                        ("🔎 Verify Market Analysis", "publishing_verify", {"scope": "analysis"}),
                        ("🔐 Check & Enable Publishing", "publishing_enable", {}),
                        ("🩺 Health Status", "health", {}),
                        ("📋 Recent Errors", "errors", {}),
                        ("💾 Backup Database", "backup", {}),
                        ("🔄 Retry / Reconcile Operations", "operations", {}),
                        ("⚙️ Settings / Channel Discovery", "settings", {}),
                    ],
                ),
            }
            if category not in categories:
                raise ValueError("Choose a category from the administrator menu.")
            title, description, buttons = categories[category]
            text = f"{title}\n\n{description}"
        return await self.say(update, text, buttons + back, admin_chrome=False)

    @staticmethod
    def publishing_verification_reason(category):
        return {
            "configuration_incomplete": "the required administrator or channel ID is not configured",
            "admin_identity_mismatch": "the configured administrator ID did not resolve to the expected private account",
            "destination_mismatch": "the configured ID did not resolve to the expected channel",
            "test_destination_not_private": "isolated test channels must be private",
            "admin_channel_permissions": "the configured administrator must be an administrator in both channels",
            "bot_channel_permissions": "the bot needs Post Messages, Edit Messages, and Invite Users in the channel",
            "invalid_token": "Telegram rejected the bot token",
            "telegram_forbidden": "Telegram denied access; check the bot and administrator membership",
            "telegram_bad_request": "Telegram rejected the request; check the configured channel ID",
            "telegram_network_error": "Telegram could not be reached; try the read-only check again later",
            "telegram_validation_error": "Telegram verification could not be completed",
        }.get(category, "verification could not be completed")

    async def publishing_verification(self, update, scope="all", enable=False):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        if scope not in ("all", "administrator", "signals", "analysis"):
            raise ValueError("Choose a supported verification check.")

        result = await verify_configured_destinations_detailed(self.bot, self.config)
        admin, signals, analysis = (
            result["administrator"], result["signals"], result["analysis"])
        verified = bool(admin["ok"] and signals["ok"] and analysis["ok"])
        if not verified:
            self.publisher.verified = False

        def mark(ok, category):
            return "✅ Verified" if ok else (
                "⚠️ Not verified — " + self.publishing_verification_reason(category))

        lines = [
            "🔐 PUBLISHING VERIFICATION",
            "",
            "Administrator: " + mark(admin["ok"], admin["category"]),
        ]
        for name, label, status in (
            ("signals", "PRO Signals", signals),
            ("analysis", "Market Analysis", analysis),
        ):
            destination_state = (
                "channel ID and type verified" if status["destination_ok"] else
                "channel not verified — " + self.publishing_verification_reason(
                    status["destination_category"])
            )
            admin_state = (
                "administrator role verified" if status["admin_ok"] else
                "administrator role not verified — " + self.publishing_verification_reason(
                    status["admin_category"])
            )
            bot_state = (
                "bot permissions verified" if status["bot_ok"] else
                "bot permissions not verified — " + self.publishing_verification_reason(
                    status["bot_category"])
            )
            channel_mark = "✅" if status["ok"] else "⚠️"
            lines.extend([
                f"{label}: {channel_mark}",
                f"  • {destination_state}",
                f"  • {admin_state}",
                f"  • {bot_state}",
            ])

        environment_on = bool(self.config.allow_publishing)
        if enable and verified and environment_on:
            self.publisher.verified = True
        lines.extend([
            "",
            "Environment publishing setting: " + ("ON" if environment_on else "OFF"),
        ])
        if enable and verified and environment_on:
            lines.append("Result: Publishing is enabled by the existing setting and all checks pass.")
        elif not verified:
            lines.append("Result: Publishing remains locked until every verification passes.")
        elif not environment_on:
            lines.append(
                "Result: Publishing remains locked. The explicit environment setting is OFF; "
                "this control does not change it."
            )
        else:
            lines.append("Result: All checks pass. Use “Check & Enable Publishing” for the explicit operator action.")
        lines.append("Read-only verification only; no channel messages were sent.")

        buttons = [
            ("🔎 Verify Administrator", "publishing_verify", {"scope": "administrator"}),
            ("🔎 Verify PRO Signals", "publishing_verify", {"scope": "signals"}),
            ("🔎 Verify Market Analysis", "publishing_verify", {"scope": "analysis"}),
            ("🔐 Check & Enable Publishing", "publishing_enable", {}),
            ("↩️ System & Records", "admin_category", {"category": "system"}),
        ]
        return await self.say(update, "\n".join(lines), buttons, admin_chrome=False)

    def current(self, user, kind=None):
        d = self.db.draft(user)
        if not d or (kind and d["kind"] != kind):
            raise ValueError(
                "This draft has been closed or replaced. No changes were made. "
                "Open the relevant category to start a fresh draft."
            )
        return d

    def require_revision(self, user, data):
        d = self.current(user)
        if data.get("revision") != d["revision"]:
            raise ValueError("This button is out of date. Reopen the current draft and review it again.")
        return d

    async def callback(self, update, context):
        q = update.callback_query
        await q.answer()
        if update.effective_chat.type != "private":
            return
        user = update.effective_user.id
        try:
            action, data = self.db.consume(q.data, user)
        except ValueError:
            logger.warning("callback_rejected:invalid_or_stale")
            raise
        safe_member_actions = {
            "member_pro_registration", "member_pro_screening_answer", "member_pro_screening_back",
            "member_pro_screening_restart", "member_pro_screening_resume",
            "member_pro_screening_submit", "member_pro_screening_exit",
            "applicant_followup_stop",
            "education_onboarding_start", "education_onboarding_check",
            "education_onboarding_assignment", "admin_education_preview",
            "admin_education_preview_assignment",
        }
        safe_action = action if action in safe_member_actions else "other"
        logger.info("callback_action:%s", safe_action)
        try:
            return await self.dispatch_callback_action(update, action, data, user)
        except Exception as exc:
            logger.warning("callback_action_error:%s:%s", safe_action, type(exc).__name__)
            raise

    async def dispatch_callback_action(self, update, action, data, user):
        if action in {
                "education_onboarding_start", "education_onboarding_check",
                "education_onboarding_assignment"}:
            return await self.education_onboarding_action(update, action)
        if action == "admin_education_preview":
            return await self.education_onboarding_preview(update)
        if action == "admin_education_preview_assignment":
            return await self.education_onboarding_preview_assignment(update)
        if action == "applicant_followup_stop":
            return await self.applicant_followup_stop(update)
        if action.startswith("applicant_followup_"):
            return await self.applicant_followup_handle_action(update, action, data)
        if action == "assistant_apply":
            return await self.request_destination_selection(update)
        if action == "assistant_status":
            return await self.member_action(update, "member_status", {})
        if action == "assistant_topic":
            return await self.assistant_topic(update, data.get("topic", "help"))
        if action == "assistant_resume":
            return await self.assistant_resume(update)
        if action == "assistant_contact":
            return await self.assistant_begin_contact(update)
        if action == "assistant_contact_cancel":
            return await self.assistant_cancel_contact(update)
        if action in {
                "member_apply", "member_apply_dest", "member_status", "member_cancel",
                "member_pro_registration", "member_pro_registered", "member_funding_evidence",
                "member_evidence_confirm", "member_more_info", "member_pro_alternative",
                "member_pro_alternative_next", "member_pro_alternative_cancel", "member_pro_recheck",
                "member_pro_screening_answer", "member_pro_screening_back",
                "member_pro_screening_restart", "member_pro_screening_resume",
                "member_pro_screening_submit", "member_pro_screening_exit"}:
            return await self.member_action(update, action, data)
        self.config.authorize(user, update.effective_chat.type)
        await self.admin_action(update, action, data)

    async def access_selection(self, u, user, selected):
        destinations = [(channel, label) for channel, label in self.access_destinations()
                        if channel != self.config.signals]
        valid_ids = {channel for channel, _ in destinations}
        if any(channel not in valid_ids for channel in selected):
            raise ValueError("Choose only configured access destinations.")
        buttons = [
            (("✅ " if channel in selected else "⬜ ") + label,
             "review_access_toggle",
             {"user": user, "channels": selected, "channel": channel})
            for channel, label in destinations
        ]
        if selected:
            buttons.append(("Continue with selected access", "review_access",
                            {"user": user, "channels": selected}))
        buttons.append(("Back to application", "application", {"user": user}))
        text = ("Choose each destination separately. Tap a destination to add or remove it, "
                "then continue. The applicant only receives access to the selected destinations.")
        text += "\n\nPRO Signals requires its separate registration and funding verification workflow."
        if not self.config.education_group_id:
            text += "\n\nEducational Group is unavailable until EDUCATION_GROUP_ID is configured."
        return await self.say(u, text, buttons)

    async def admin_action(self, u, action, p):
        user = u.effective_user.id
        self.config.authorize(user, u.effective_chat.type)
        if action == "admin_category":
            return await self.admin_category(u, p.get("category"))
        if action == "zone_analysis_link_list":
            return await self.zone_analysis_link_list(u, p.get("setup_id"))
        if action == "zone_analysis_link":
            return await self.zone_analysis_link(
                u, p.get("setup_id"), p.get("operation_id"))
        if action == "zone_analysis_unlink":
            return await self.zone_analysis_unlink(u, p.get("setup_id"))
        if action == "signal_results_list":
            return await self.signal_results_list(u)
        if action == "signal_result_open":
            return await self.signal_result_screen(u, p["trade_id"])
        if action == "signal_result_capture":
            return await self.signal_result_capture(u, p["trade_id"], p["updated"])
        if action == "signal_result_attach":
            return await self.signal_result_attach(u, p["trade_id"], p["updated"])
        if action == "signal_result_choose":
            return await self.signal_result_choose(u, p["trade_id"], p["updated"])
        if action == "signal_result_outcome":
            return await self.signal_result_set_outcome(
                u, p["trade_id"], p["updated"], p["outcome"])
        if action == "signal_result_edit_caption":
            return await self.signal_result_edit_caption(u, p["trade_id"], p["updated"])
        if action == "signal_result_preview":
            return await self.signal_result_preview(u, p["trade_id"], p["updated"])
        if action == "signal_result_confirm_screen":
            return await self.signal_result_confirm_screen(u, p["trade_id"], p["updated"])
        if action == "signal_result_publish_confirm":
            return await self.signal_result_publish_confirm(u, p["trade_id"], p["updated"])
        if action == "signal_result_save":
            return await self.signal_result_save(u, p["trade_id"], p["updated"])
        if action == "signal_result_cancel":
            return await self.signal_result_cancel(u, p["trade_id"], p["updated"])
        if action == "tp1_profit_screenshot_upload":
            return await self.tp1_profit_screenshot_upload(u, p)
        if action == "tp1_profit_screenshot_cancel":
            return await self.tp1_profit_screenshot_cancel(u, p)
        if action == "tp1_screenshot_values_confirm":
            return await self.tp1_screenshot_values_confirm(u, p)
        if action == "tp1_screenshot_values_edit":
            return await self.tp1_screenshot_values_edit(u, p)
        if action == "tp1_screenshot_candidate_choose":
            return await self.tp1_screenshot_candidate_choose(u, p)
        if action == "publishing_verify":
            return await self.publishing_verification(u, p.get("scope", "all"))
        if action == "publishing_enable":
            return await self.publishing_verification(u, enable=True)
        if action == "assistant_admin":
            return await self.assistant_admin_panel(u)
        if action == "assistant_faq":
            return await self.assistant_faq_screen(u)
        if action == "assistant_queue":
            return await self.assistant_queue(u)
        if action == "assistant_case":
            return await self.assistant_case(u, p.get("case_id"))
        if action == "assistant_reply_start":
            return await self.assistant_reply_start(u, p.get("case_id"))
        if action == "assistant_reply_cancel":
            return await self.assistant_reply_cancel(u)
        if action == "assistant_close_case":
            return await self.assistant_close_case(u, p.get("case_id"))
        if action == "assistant_toggle":
            return await self.assistant_toggle(u, p.get("enabled"))
        if action == "assistant_inactive_notice_prompt":
            return await self.assistant_inactive_notice_prompt(u)
        if action == "assistant_inactive_notice_cancel":
            return await self.assistant_inactive_notice_cancel(u)
        if action == "assistant_inactive_notice_reset":
            return await self.assistant_inactive_notice_reset(u)
        if action == "member_request":
            return await self.member_request_screen(u, p["request_id"])
        if action == "access_disapprove":
            return await self.access_disapprove_prompt(
                u, p["user"], p["channel"], p.get("request_id"))
        if action == "access_disapprove_confirm":
            return await self.access_disapprove_confirm(
                u, p["user"], p["channel"], p.get("request_id"))
        if action == "member_request_evidence":
            return await self.member_request_evidence(u, p["request_id"])
        if action == "member_verify_prompt":
            return await self.member_verify_prompt(u, p["request_id"], p["field"])
        if action == "member_verify_confirm":
            return await self.member_verify_confirm(u, p["request_id"], p["field"])
        if action == "member_registration_reject":
            return await self.member_registration_reject_prompt(u, p["request_id"])
        if action == "member_registration_reject_confirm":
            return await self.member_registration_reject_confirm(u, p["request_id"])
        if action == "member_funding_reject":
            return await self.member_funding_reject_prompt(u, p["request_id"])
        if action == "member_funding_reject_confirm":
            return await self.member_funding_reject_confirm(u, p["request_id"])
        if action == "member_request_approve":
            return await self.member_request_approve_prompt(u, p["request_id"])
        if action == "member_request_approve_confirm":
            return await self.member_request_approve_confirm(u, p["request_id"])
        if action == "member_pro_approve":
            return await self.member_pro_approve_prompt(u, p["request_id"])
        if action == "member_pro_approve_confirm":
            return await self.member_pro_approve_confirm(u, p["request_id"])
        if action == "member_pro_not_eligible":
            return await self.member_pro_not_eligible_prompt(u, p["request_id"])
        if action == "member_pro_not_eligible_confirm":
            return await self.member_pro_not_eligible_confirm(u, p["request_id"])
        if action == "member_request_reject":
            return await self.member_request_reject_prompt(u, p["request_id"])
        if action == "member_request_reject_confirm":
            return await self.member_request_reject_confirm(u, p["request_id"])
        if action == "member_request_more":
            return await self.member_request_more(u, p["request_id"])
        if action == "analysis_pro_zone_add":
            d = self.require_revision(user, p)
            return await self.analysis_pro_zone_add(u, d)
        if action == "analysis_pro_zone_edit":
            d = self.require_revision(user, p)
            return await self.analysis_pro_zone_edit(u, d)
        if action == "analysis_pro_zone_attach":
            d = self.require_revision(user, p)
            return await self.analysis_pro_zone_attach(u, d)
        if action == "pro_import_start":
            return await self.pro_import_start(u)
        if action == "pro_import_edit":
            d = self.require_revision(user, p)
            if d.get("kind") != "pro_import" or d.get("step") != "review":
                raise ValueError("This published POI review is no longer available.")
            d["step"] = "caption_edit"
            self.db.save_draft(user, d)
            return await self.say(
                u,
                "Paste the full corrected Market Analysis caption. The forwarded chart and source-post link will be kept.",
                [("Cancel", "cancel", {})],
                admin_chrome=False,
            )
        if action == "pro_import_publish":
            d = self.require_revision(user, p)
            return await self.publish_pro_import(u, d)
        if action == "pro_import_continue":
            d = self.current(user, "pro_import")
            return await self.continue_pro_import(u, d)
        if action == "pro_import_retry":
            d = self.current(user, "pro_import")
            return await self.retry_pro_import_operation(u, d, p.get("index"))
        if action == "pro_import_finish":
            d = self.current(user, "pro_import")
            return await self.finish_pro_import(u, d)
        if action == "analysis_zone_publish":
            d = self.current(user, "analysis")
            return await self.publish_analysis_zone_bundle(u, d)
        if action == "analysis_zone_retry":
            d = self.current(user, "analysis")
            return await self.retry_analysis_zone_operation(u, d, p.get("operation_kind"))
        if action == "analysis_zone_finish":
            d = self.current(user, "analysis")
            return await self.finish_analysis_zone_bundle(u, d)
        if action == "zone_wizard_select":
            d = self.require_revision(user, p)
            try:
                zone_wizard.answer(d, p.get("field"), p.get("value"))
            except ValueError as exc:
                return await self.zone_wizard_prompt(u, d, str(exc))
            self.db.save_draft(user, d)
            return await self.zone_wizard_prompt(u, d)
        if action == "zone_wizard_back":
            d = self.require_revision(user, p)
            if d.get("step") in ("replacement", "choose_replacement", "chart"):
                d["step"] = "preview"
                d.pop("replaces", None)
                d.pop("replaces_setup_id", None)
            else:
                zone_wizard.back(d)
            self.db.save_draft(user, d)
            return await self.zone_wizard_prompt(u, d)
        if action == "zone_wizard_edit":
            d = self.require_revision(user, p)
            if d.get("attached_to_analysis") and d.get("step") == "ready":
                d["step"] = "preview"
            zone_wizard.begin_edit(d)
            self.db.save_draft(user, d)
            return await self.zone_wizard_prompt(u, d)
        if action == "zone_wizard_edit_field":
            d = self.require_revision(user, p)
            zone_wizard.choose_edit(d, p.get("field"))
            self.db.save_draft(user, d)
            return await self.zone_wizard_prompt(u, d)
        if action == "zone_wizard_cancel":
            d = self.require_revision(user, p)
            if d.get("attached_to_analysis"):
                analysis_draft = d.get("resume_analysis")
                if not analysis_draft:
                    raise ValueError("The saved Market Analysis draft is unavailable.")
                self.db.save_draft(user, analysis_draft)
                return await self.preview(u)
            self.db.clear_draft(user)
            return await self.menu(u, "✅ Setup draft cancelled. No setup was saved or posted.")
        if action == "zone_wizard_confirm":
            d = self.require_revision(user, p)
            if d.get("step") != "preview":
                raise ValueError("Review the complete setup preview before confirming.")
            try:
                d["setup"] = zone_wizard.build_setup(d)
            except ValueError as exc:
                return await self.zone_wizard_prompt(u, d, str(exc))
            replace_id = d.get("replaces_setup_id")
            old = zones.active(self.db, replace_id) if replace_id else None
            active_zones = zones.active_setups(self.db)
            if old:
                d["replaces"] = old["id"]
                d["step"] = "replacement"
            elif d.get("independent"):
                d.pop("replaces", None)
                d["step"] = "ready" if d.get("attached_to_analysis") and d.get("image") else "chart"
            elif d.get("attached_to_analysis") and d.get("image"):
                d.pop("replaces", None)
                d["step"] = "ready"
            elif len(active_zones) == 1:
                d["replaces_setup_id"] = active_zones[0]["id"]
                d["replaces"] = active_zones[0]["id"]
                d["step"] = "replacement"
            elif len(active_zones) > 1:
                d["step"] = "choose_replacement"
            else:
                d.pop("replaces", None)
                d["step"] = "chart"
            self.db.save_draft(user, d)
            if d.get("attached_to_analysis") and d.get("step") == "ready":
                return await self.zone_preview(u, d)
            return await self.zone_wizard_prompt(u, d)
        if action == "zone_new":
            existing = self.db.draft(user)
            if existing:
                if existing.get("kind") == "zone":
                    if existing.get("step") == "input" and not existing.get("wizard_version"):
                        existing = zone_wizard.normalize(existing)
                        self.db.save_draft(user, existing)
                    return await self.preview(u)
                return await self.say(
                    u, "Finish, resume, or cancel the current draft before starting a setup zone."
                )
            if p.get("choose_direction") and p.get("poi_direction") not in ("BUY", "SELL"):
                return await self.say(
                    u,
                    "Choose which independent POI to create. Creating the second POI will not replace the first.",
                    [
                        ("🟢 Create independent BUY POI", "zone_new", {
                            "independent": True, "poi_direction": "BUY",
                            "approximate_zone": True,
                        }),
                        ("🔴 Create independent SELL POI", "zone_new", {
                            "independent": True, "poi_direction": "SELL",
                            "approximate_zone": True,
                        }),
                        ("↩️ Zone & Signals", "admin_category", {"category": "zone"}),
                    ],
                )
            replace_setup_id = p.get("replace_setup_id")
            if replace_setup_id:
                zones.active(self.db, replace_setup_id)
            d = zone_wizard.new_draft(
                independent=p.get("independent", False),
                poi_direction=p.get("poi_direction"),
                replaces_setup_id=replace_setup_id,
                approximate_zone=p.get("approximate_zone", False),
            )
            self.db.save_draft(user, d)
            return await self.zone_wizard_prompt(u, d)
        if action == "zone_replace_choose":
            d = self.require_revision(user, p)
            if d.get("kind") != "zone" or d.get("step") != "choose_replacement":
                raise ValueError("Choose a replacement target from the current setup preview.")
            target = zones.active(self.db, p.get("setup_id"))
            d["replaces_setup_id"] = target["id"]
            d["replaces"] = target["id"]
            d["step"] = "replacement"
            self.db.save_draft(user, d)
            return await self.zone_wizard_prompt(u, d)
        if action == "zone_replace":
            d = self.require_revision(user, p)
            if d["kind"] != "zone" or d["step"] != "replacement":
                raise ValueError("Submit a replacement zone first.")
            zones.active(self.db, d.get("replaces"))
            d["step"] = (
                "ready" if d.get("attached_to_analysis") and d.get("image")
                else "chart"
            )
            self.db.save_draft(user, d)
            if d.get("attached_to_analysis"):
                return await self.zone_preview(u, d)
            if d.get("wizard_version") == 1:
                return await self.zone_wizard_prompt(u, d)
            return await self.say(u, "Replacement confirmed. Step 1 of 3: send the chart image for this zone.")
        if action == "zone_preview":
            d = self.require_revision(user, p)
            if d["kind"] != "zone" or d["step"] != "ready" or not d.get("image"):
                raise ValueError("Upload the chart and review the zone first.")
            return await self.zone_preview(u, d)
        if action == "zone_publish":
            d = self.require_revision(user, p)
            if d["kind"] != "zone" or d["step"] != "ready" or not d.get("image"):
                raise ValueError("Upload and review the chart before posting the zone.")
            setup = {**d["setup"], "image": d["image"], "original": d.get("original", d["image"])}
            replaces = d.get("replaces")
            payload = {"destination": "signals", "setup": setup, "replaces": d.get("replaces"),
                       "image": d["image"], "original": d.get("original", d["image"]),
                       "text": zones.setup_caption(setup)}
            op = self.publisher.prepare(user, "setup", payload)
            d.update(step="operation", operation=op)
            self.db.save_draft(user, d)
            try:
                result = await self.publisher.send(user, op)
            except ValueError as e:
                return await self.say(u, str(e), [("Review / Reconcile Operations", "operations", {})])
            row, _ = self.publisher.operation(op)
            if row["status"] == "done":
                self.db.clear_draft(user)
                replacement_notice = ""
                if replaces:
                    old_setup = self.db.get("setup:" + str(replaces))
                    if old_setup and not await self.update_setup_post(old_setup):
                        replacement_notice = " The previous zone was replaced, but its post status could not be updated."
                return await self.menu(
                    u, "✅ Zone + chart posted to PRO Signals. No signal was sent yet. "
                    "Next: wait for the stated confirmation, then record what you observed."
                    + replacement_notice)
            return await self.operation_result(u, op, result)
        if action == "zone_tapped":
            if not p.get("setup_id"):
                raise ValueError("Open the current active zone before marking it tapped.")
            try:
                operation_ids = self.publisher.prepare_zone_tapped(user, p["setup_id"])
            except ValueError as exc:
                return await self.say(u, f"⚠️ {exc}", [
                    ("↩️ Zone & Signals", "admin_category", {"category": "zone"}),
                ])

            labels = {"signals": "PRO Signals", "analysis": "Market Analysis"}
            outcomes = []
            for destination in ("signals", "analysis"):
                operation_id = operation_ids[destination]
                row, _payload = self.publisher.operation(operation_id)
                if row["status"] == "done":
                    outcomes.append(f"✅ {labels[destination]} — already sent")
                    continue
                if row["status"] in ("uncertain", "sending"):
                    outcomes.append(
                        f"⚠️ {labels[destination]} — result uncertain; check the channel before retrying")
                    continue
                if row["status"] == "failed":
                    outcomes.append(
                        f"❌ {labels[destination]} — Telegram rejected it; check permissions/content")
                    continue
                try:
                    await self.publisher.send(user, operation_id)
                    outcomes.append(f"✅ {labels[destination]} — sent")
                except ValueError as exc:
                    outcomes.append(f"⚠️ {labels[destination]} — {exc}")
                except Exception as exc:
                    logger.warning("zone_tapped_send_failed:%s:%s",
                                   destination, type(exc).__name__)
                    outcomes.append(f"⚠️ {labels[destination]} — send failed; check its status before retrying")
            text = "📍 Zone Tapped update\n\n" + "\n".join(outcomes)
            text += "\n\nA POI touch is not an entry confirmation."
            return await self.say(u, text, [
                ("↩️ Zone & Signals", "admin_category", {"category": "zone"}),
            ])
        if action in ("zone_cancel", "zone_expire", "zone_confirmation"):
            with self.db.transaction() as c:
                setup = zones.active(self.db, p.get("setup_id"))
                if action == "zone_cancel":
                    setup["status"] = "cancelled"
                    zones.save_in(c, setup)
                elif action == "zone_expire":
                    setup["status"] = "expired"
                    setup["expires"] = None
                    zones.save_in(c, setup)
            if action == "zone_cancel":
                updated = await self.update_setup_post(setup)
                notice = "✅ The setup zone was cancelled. No signal was sent."
                if not updated:
                    notice += " Its Telegram post could not be updated; check PRO Signals."
                return await self.say(u, notice, [("Main Menu", "menu", {})])
            if action == "zone_expire":
                updated = await self.update_setup_post(setup)
                notice = "✅ The zone was marked expired. It can no longer be used for a signal."
                if not updated:
                    notice += " Its Telegram post could not be updated; check PRO Signals."
                return await self.say(
                    u, notice, [("↩️ Zone & Signals", "admin_category", {"category": "zone"})])
            self.db.save_draft(user, {"kind": "zone_confirmation", "setup_id": setup["id"]})
            return await self.say(u, "🧭 Step 2 of 3 — record the confirmation you actually observed.\n\n"
                                  "Required: " + (setup["condition"] or "your own observation") +
                                  "\nDo not record a confirmation until you have observed it.")
        if action == "menu":
            return await self.menu(u)
        if action == "cancel":
            draft = self.db.draft(user)
            if draft and draft.get("kind") == "pro_import_wait":
                self.db.clear_draft(user)
                return await self.say(u, "✅ Cancelled. No post was sent.",
                                      [("↩️ Analysis & Drafts", "admin_category", {"category": "analysis"})],
                                      admin_chrome=False)
            if draft and draft.get("kind") == "pro_import":
                if draft.get("pro_import_bundle"):
                    return await self.pro_import_screen(
                        u, draft, "A PRO post may already be live. Resolve the saved operations before leaving.")
                source_key = self.pro_import_source_key(
                    draft.get("source_channel"), draft.get("source_message_id"))
                if source_key:
                    self.db.put(source_key, {"status": "cancelled"})
                self.db.clear_draft(user)
                return await self.say(u, "✅ PRO review cancelled. Nothing was sent.",
                                      [("↩️ Analysis & Drafts", "admin_category", {"category": "analysis"})],
                                      admin_chrome=False)
            if draft and draft.get("resume_analysis_bundle"):
                saved_bundle = draft["resume_analysis_bundle"]
                self.db.save_draft(user, saved_bundle)
                return await self.analysis_zone_bundle_screen(
                    u, saved_bundle, "Reconciliation was cancelled. No post was resent.")
            if draft and draft.get("publish_bundle"):
                return await self.analysis_zone_bundle_screen(
                    u, draft, "A post in this two-channel review may already be live. Resolve it from this screen before leaving.")
            if draft and draft.get("attached_to_analysis"):
                analysis_draft = draft.get("resume_analysis")
                if not analysis_draft:
                    raise ValueError("The saved Market Analysis draft is unavailable.")
                self.db.save_draft(user, analysis_draft)
                return await self.preview(u)
            self.db.clear_draft(user)
            return await self.say(u, "✅ Draft cancelled. Published posts and pending operations were not changed.")
        if action == "new_signal":
            if p.get("direction") not in ("BUY", "SELL"):
                raise ValueError("Choose BUY or SELL.")
            setup_record = self.db.get("setup:" + str(p.get("setup_id")))
            if setup_record and setup_record.get("status") == "used":
                row = self.db.rows(
                    "SELECT status FROM operations WHERE id=?",
                    (setup_record.get("operation"),),
                ) if setup_record.get("operation") else []
                if row and row[0]["status"] == "done":
                    await self.update_setup_post(setup_record)
                    return await self.say(
                        u, "✅ This setup was already published, so it was not sent again.")
                return await self.say(
                    u, "⚠️ The result is uncertain. Check PRO Signals and reconcile this post before creating another setup.",
                    [("Review / Reconcile Operations", "operations", {})],
                )
            setup = zones.active(self.db, p.get("setup_id"))
            if not setup.get("confirmation"):
                return await self.say(u, "⚠️ Confirmation is still missing: " +
                                      (setup["condition"] or "your observed setup confirmation") +
                                      "\nRecord what you observed before sending a signal.",
                                      [("Record confirmation details", "zone_confirmation", {"setup_id": setup["id"]})])
            existing = self.db.draft(user)
            if existing:
                if (existing.get("kind") == "zone_signal" and
                        existing.get("setup_id") == setup["id"] and
                        existing.get("direction") == p["direction"]):
                    return await self.zone_signal_prompt(u, existing)
                raise ValueError("Finish or cancel the current draft before preparing a signal.")
            direction_first = True
            draft = {"kind": "zone_signal", "setup_id": setup["id"],
                     "direction": p["direction"], "direction_first": direction_first,
                     "step": "direction_preview" if direction_first else "controls"}
            self.db.save_draft(user, draft)
            if p["direction"] == "SELL":
                saved = self.db.draft(user)
                return await self.confirm_zone_signal(
                    u, user, {"revision": saved["revision"]})
            return await self.zone_signal_prompt(u, draft)
        if action == "zone_signal_field":
            d = self.require_revision(user, p)
            if d.get("kind") != "zone_signal":
                raise ValueError("This signal draft is no longer available.")
            if (d.get("step") not in ("controls", "preview") or
                    p.get("field") not in ("entry", "sl", "targets")):
                raise ValueError("Reopen the current signal controls and choose a valid field.")
            d["step"] = p["field"]
            self.db.save_draft(user, d)
            return await self.zone_signal_prompt(u, d)
        if action == "zone_signal_review":
            d = self.require_revision(user, p)
            if d.get("kind") != "zone_signal" or d.get("step") != "controls":
                raise ValueError("Open the current signal controls before reviewing.")
            d["step"] = "preview"
            self.db.save_draft(user, d)
            return await self.zone_signal_prompt(u, d)
        if action == "zone_signal_controls":
            d = self.require_revision(user, p)
            if d.get("kind") != "zone_signal":
                raise ValueError("This signal draft is no longer available.")
            d["step"] = "controls"
            self.db.save_draft(user, d)
            return await self.zone_signal_prompt(u, d)
        if action == "zone_signal_cancel":
            d = self.require_revision(user, p)
            if d.get("kind") != "zone_signal":
                raise ValueError("This signal draft is no longer available.")
            if d.get("step") in ("submitting", "operation"):
                raise ValueError("A publishing operation already exists. Review its status; do not cancel or resend it.")
            self.db.clear_draft(user)
            return await self.say(u, "✅ Signal draft cancelled. No signal was published.",
                                  [("↩️ Zone & Signals", "admin_category", {"category": "zone"}),
                                   ("↩️ Admin Home", "menu", {})],
                                  admin_chrome=False)
        if action == "zone_signal_confirm":
            return await self.confirm_zone_signal(u, user, p)
        if action == "market":
            d = self.current(user, "signal")
            if d["step"] != "market" or p["market"] not in MARKETS:
                raise ValueError("Choose a market from a fresh menu.")
            d.update(market=p["market"], symbol=p["market"], step="symbol")
            self.db.save_draft(user, d)
            return await self.say(u, "Optional: type a symbol or short note, or skip.", [("Skip", "signal_skip", {"revision": d["revision"]})])
        if action == "signal_skip":
            d = self.require_revision(user, p)
            d["text"] = confirmation(d["direction"], d["symbol"])
            d["step"] = "ready"
            self.db.save_draft(user, d)
            return await self.preview(u)
        if action in ("preview", "analysis_publish"):
            if action == "analysis_publish":
                self.current(user, "analysis")
            return await self.preview(u)
        if action == "destination":
            d = self.require_revision(user, p)
            if d.get("publish_bundle"):
                return await self.analysis_zone_bundle_screen(
                    u, d, "The publishing bundle is already in progress; its destinations cannot be changed.")
            if d.get("pro_zone") and p.get("destination") != "analysis":
                raise ValueError("A separate PRO zone can only be paired with the Market Analysis destination.")
            self.config.destination(d["kind"], p["destination"])
            d["destination"] = p["destination"]
            self.db.save_draft(user, d)
            return await self.preview(u)
        if action == "wording":
            d = self.require_revision(user, p)
            d["step"] = "wording"
            self.db.save_draft(user, d)
            return await self.say(u, "Type the complete replacement message. It will be previewed before publishing.")
        if action == "entry_bundle_edit":
            d = self.require_revision(user, p)
            if (d.get("kind") != "update" or d.get("action") != "entry_bundle" or
                    not d.get("source", {}).get("levels_pending") or
                    d.get("step") != "ready"):
                raise ValueError("This trade-details review is no longer available.")
            field = p.get("field")
            if field not in ("entry", "sl", "targets"):
                raise ValueError("Choose a valid trade-details field to edit.")
            if field in ("sl", "targets") and not d.get("entry_value"):
                raise ValueError("Set the Buy Range before editing Stop Loss or Take Profit.")
            if field == "targets" and not d.get("sl_value"):
                raise ValueError("Set the Stop Loss before editing Take Profit.")
            d["step"] = "tp" if field == "targets" else field
            if field == "entry":
                d.pop("sl_value", None)
                d.pop("targets_text", None)
                d.pop("targets_auto", None)
            elif field == "sl":
                d.pop("sl_value", None)
            else:
                d.pop("targets_text", None)
                d.pop("targets_auto", None)
            d.pop("trade", None)
            d.pop("text", None)
            self.db.save_draft(user, d)
            if field == "entry":
                market = d.get("source", {}).get("market") or d.get("source", {}).get("symbol")
                direction = d.get("source", {}).get("direction", "BUY")
                prompt = (
                    f"Enter one exact {direction.title()} entry price inside the original active zone."
                    if zones.automatic_tp1_pip_size(market) is not None else
                    f"Enter a {direction.title()} Range inside the original active zone, such as 2651–2654."
                )
            elif field == "sl":
                direction = d.get("source", {}).get("direction", "BUY")
                relation = "below" if direction == "BUY" else "above"
                prompt = f"Enter a Stop Loss {relation} the full {direction.title()} Range."
            else:
                direction = d.get("source", {}).get("direction", "BUY")
                relation = "above" if direction == "BUY" else "below"
                prompt = (f"Enter one or more Take Profit prices {relation} the full "
                          f"{direction.title()} Range, separated by commas.")
            return await self.say(u, prompt, admin_chrome=False)
        if action == "publish":
            d = self.require_revision(user, p)
            if d["kind"] == "signal":
                raise ValueError("Legacy signal preview retired. Submit a zone and use the current instant buttons.")
            if not d.get("destination") or d.get("step") != "ready":
                raise ValueError("Choose a destination and review the complete draft first.")
            if d["kind"] == "analysis" and (d.get("pro_zones") or d.get("pro_zone")):
                return await self.publish_analysis_zone_bundle(u, d)
            payload = dict(d)
            if d["kind"] == "signal":
                payload["trade"] = {"id": uid(), "direction": d["direction"], "market": d["market"],
                                    "symbol": d["symbol"], "targets": {}, "state": "WAITING_FOR_CONFIRMATION",
                                    "admin": user}
            op = self.publisher.prepare(user, d["kind"], payload)
            # Persist operation reference BEFORE any Telegram side effect.
            d.update(step="operation", operation=op)
            self.db.save_draft(user, d)
            text = await self.publisher.send(user, op)
            return await self.operation_result(u, op, text)
        if action == "controls":
            return await self.say(u, "Choose an action, then select the trade to update.",
                                  [(label, "trades", {"action": key}) for label, key in ACTIONS])
        if action == "trades":
            return await self.trades(u, p)
        if action == "trade":
            return await self.trade_screen(u, p["id"])
        if action == "trade_details":
            return await self.trade_details(u, p["id"])
        if action == "trade_stats":
            return await self.trade_statistics(u)
        if action == "manage":
            return await self.manage(
                u, p["id"], p["action"], target_number=p.get("target_number"))
        if action == "auto_tp_next":
            return await self.add_automatic_tp_next(u, p)
        if action == "choose_value":
            d = self.require_revision(user, p)
            if d["action"] == "partial":
                d["percent"] = p["value"]
                d["step"] = "partial_mode"
                self.db.save_draft(user, d)
                return await self.partial_mode(u, d)
            if d["action"] == "hit":
                return await self.select_hit_target(u, d, p["value"])
            if d["action"] == "close":
                d.update(outcome=p["value"], step="close_details")
                self.db.save_draft(user, d)
                return await self.say(
                    u, "Optional: enter the confirmed exit price and note as price | note, or skip both.",
                    [("Skip exit and note", "close_skip", {"revision": d["revision"]})])
            return await self.finish_update(u, d, p["value"])
        if action == "hit_target_choice":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "hit" or d.get("step") != "hit_target":
                raise ValueError("Choose a target from an open TP Hit draft.")
            return await self.select_hit_target(u, d, p.get("target"))
        if action == "hit_status":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "hit" or d.get("step") != "hit_status":
                raise ValueError("Select a TP number first, then choose whether it was partial or final.")
            status = p.get("status")
            if status not in ("partial", "final"):
                raise ValueError("Choose either Partial target or Final target.")
            key = str(d.get("hit_target", ""))
            target = d.get("source", {}).get("targets", {}).get(key)
            if not target or target.get("hit"):
                raise ValueError("That TP target is no longer available; reopen the trade.")
            return await self.finish_update(u, d, f"{key}|{status}")
        if action == "partial_custom":
            d = self.require_revision(user, p)
            d["step"] = "partial_percent"
            self.db.save_draft(user, d)
            return await self.say(u, "Enter the percentage closed (more than 0% and no more than 100%).")
        if action == "partial_mode":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "partial":
                raise ValueError("Open Take Partial before choosing a posting status.")
            if p.get("mode") == "reported":
                return await self.partial_target_prompt(u, d)
            if p.get("mode") != "recommendation":
                raise ValueError("Choose reported profit or recommendation.")
            return await self.finish_update(u, d, f"{d['percent']}|recommendation")
        if action == "partial_choice":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "partial":
                raise ValueError("Open Take Partial before choosing an amount.")
            if p.get("mode") not in ("reported", "recommendation"):
                raise ValueError("Choose reported profit or recommendation.")
            d["percent"] = p["percent"]
            if p["mode"] == "reported":
                return await self.partial_target_prompt(u, d)
            return await self.finish_update(u, d, f"{p['percent']}|recommendation")
        if action == "partial_target_choice":
            d = self.require_revision(user, p)
            target = p.get("target")
            if d["kind"] != "update" or d.get("action") != "partial" or d.get("step") != "partial_target":
                raise ValueError("Choose a target from a Take Partial draft.")
            if target not in {item["price"] for item in d["source"].get("targets", {}).values()}:
                raise ValueError("Choose a listed take-profit target or enter the confirmed price you observed.")
            d["partial_target"] = price(target)
            d["step"] = "partial_remaining"
            self.db.save_draft(user, d)
            return await self.say(u, "Optional: enter the confirmed remaining-position status, or skip.",
                                  [("Skip remaining status", "partial_remaining_skip",
                                    {"revision": d["revision"]})])
        if action == "partial_target_manual":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "partial" or d.get("step") != "partial_target":
                raise ValueError("Choose a target from a Take Partial draft.")
            d["step"] = "partial_target_value"
            self.db.save_draft(user, d)
            return await self.say(u, "Enter the confirmed take-profit price, for example 2700.")
        if action == "partial_remaining_skip":
            d = self.require_revision(user, p)
            if d.get("step") != "partial_remaining":
                raise ValueError("No remaining-position status is being requested.")
            return await self.finish_update(u, d, f"{d['percent']}|reported|{d['partial_target']}|")
        if action == "be_confirm":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "be" or d.get("step") != "be_confirm":
                raise ValueError("Open Move to BE and confirm the actual SL move first.")
            return await self.finish_update(u, d, "confirmed")
        if action == "partial_chart":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "partial" or d.get("step") != "ready":
                raise ValueError("Finish the partial update before attaching a chart.")
            d["step"] = "chart"
            self.db.save_draft(user, d)
            return await self.say(u, "Send a chart image to attach, or continue without a chart.",
                                  [("Continue without chart", "partial_chart_skip",
                                    {"revision": d["revision"]})])
        if action == "partial_chart_skip":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "partial" or d.get("step") != "chart":
                raise ValueError("No chart is being added to a partial update.")
            d["step"] = "ready"
            self.db.save_draft(user, d)
            return await self.preview(u)
        if action == "close_skip":
            d = self.require_revision(user, p)
            if d["kind"] != "update" or d.get("action") != "close" or d.get("step") != "close_details":
                raise ValueError("No trade-closure details are being requested.")
            return await self.finish_update(u, d, f"{d['outcome']}||")
        if action == "history":
            return await self.history(u, p)
        if action == "history_filter":
            self.db.save_draft(user, {"kind": "filter", "step": "filter"})
            return await self.say(u, "🔎 Filter trade history\n\nEnter filters separated by semicolons:\n"
                                  "market=Gold/XAUUSD; direction=BUY; status=CLOSED; from=2026-01-01; to=2026-12-31\n"
                                  "Leave out unused filters. Send all to clear the filters.")
        if action == "timeline":
            return await self.timeline(u, p["id"], p.get("page", 0))
        if action == "new_analysis":
            existing = self.db.draft(user)
            if existing:
                if existing.get("kind") == "analysis":
                    return await self.say(
                        u, "You already have a Market Analysis draft. Resume it to add the PRO zone, or cancel it before starting another.",
                        [("Resume Market Analysis Draft", "preview", {}),
                         ("Cancel Current Draft", "cancel", {}),
                         ("↩️ Admin Home", "menu", {})],
                    )
                return await self.say(
                    u, "You already have another draft in progress. Resume or cancel it before starting Market Analysis.",
                    [("Resume Current Draft", "preview", {}),
                     ("Cancel Current Draft", "cancel", {}),
                     ("↩️ Admin Home", "menu", {})],
                )
            paired_pro_zone = bool(p.get("paired_pro_zone"))
            self.db.save_draft(user, {
                "kind": "analysis", "step": "caption", "commands": [], "text": "",
                "paired_pro_zone_requested": paired_pro_zone,
            })
            pairing_hint = (
                " Label each POI range in the caption; matching PRO posts will be prepared from those details and the same chart."
                if paired_pro_zone else ""
            )
            return await self.say(u, "📊 Prepare market analysis\n\nChoose a chart-review mode or write your own observations."
                + pairing_hint + "\n\n"
                "Analysis posts cannot contain trade instructions.",
                                  [("⚡ Quick Chart Review", "analysis_ai", {}),
                                   *[(name, "template", {"name": name}) for name in TEMPLATES]])
        if action == "analysis_ai":
            d = self.current(user, "analysis")
            d.update(ai_mode=True, step="ai_focus", watch_note="")
            self.db.save_draft(user, d)
            return await self.say(
                u,
                "📊 Review chart\n\n"
                "Quick Chart Review is the fast review mode.\n\n"
                "Optionally say which marked area is your POI or what price action you are watching. "
                "Gemini will receive this note and the chart image using your API key. "
                "Google's quota and billing rules apply. The review stays private until you "
                "choose to publish it; it will not create a zone or signal.",
                [("Skip note and upload chart", "analysis_ai_skip",
                  {"revision": d["revision"]}),
                 ("Cancel Draft", "cancel", {})],
                admin_chrome=False,
            )
        if action == "analysis_ai_skip":
            d = self.require_revision(user, p)
            if d.get("kind") != "analysis" or d.get("step") != "ai_focus":
                raise ValueError("Start Gemini chart analysis before skipping the note.")
            d["watch_note"] = ""
            d["step"] = "ai_upload"
            self.db.save_draft(user, d)
            return await self.say(
                u, "Upload one chart for Gemini to review. The image will be sent to Google "
                   "for this private analysis draft; no post is made until you approve the preview.",
                [("Cancel Draft", "cancel", {})],
                admin_chrome=False,
            )
        if action == "analysis_ai_manual":
            d = self.current(user, "analysis")
            if not d.get("original"):
                raise ValueError("Upload a chart before continuing with manual review.")
            d.pop("ai_mode", None)
            d.pop("ai_analysis", None)
            d.pop("watch_note", None)
            original_path = self.db.image_path(d["original"])
            d["recognition"] = await asyncio.to_thread(
                analyze_chart, original_path, allow_ocr=self.config.isolated_test)
            d["image"] = await asyncio.to_thread(
                render_review_copy, original_path, d["recognition"], self.db.directory / "images")
            d["text"] = build_analysis_caption(d["recognition"]["fields"])
            d["step"] = "ready"
            self.db.save_draft(user, d)
            return await self.preview(u)
        if action == "template":
            d = self.current(user, "analysis")
            d["step"] = "caption"
            self.db.save_draft(user, d)
            return await self.say(u, "Replace the bracketed prompts with your own observations, then send the caption:\n\n" + TEMPLATES[p["name"]])
        if action in ("upload", "caption", "annotate"):
            d = self.db.draft(user)
            if d and d.get("kind") != "analysis":
                return await self.say(
                    u, "You already have another draft in progress. Resume or cancel it before opening an analysis chart.",
                    [("Resume Current Draft", "preview", {}),
                     ("Cancel Current Draft", "cancel", {}),
                     ("↩️ Admin Home", "menu", {})],
                )
            if not d:
                d = {"kind": "analysis", "commands": [], "text": ""}
            d.setdefault("commands", [])
            d.setdefault("text", "")
            if action == "annotate" and not d.get("original"):
                d["step"] = "upload"
                self.db.save_draft(user, d)
                return await self.say(
                    u, "🖍️ Annotate a chart\n\n"
                       "Annotations let you add your own labels, lines, arrows, and marked zones to a chart copy. "
                       "The original image is kept unchanged, and the bot does not infer prices or trading instructions.\n\n"
                       "First, upload the chart you want to mark.",
                    [("📸 Upload Chart Now", "upload", {}),
                     ("Cancel Draft", "cancel", {}),
                     ("↩️ Analysis & Drafts", "admin_category", {"category": "analysis"})],
                    admin_chrome=False,
                )
            d["step"] = action
            self.db.save_draft(user, d)
            if action == "upload":
                prompt = (
                    "Send a chart as a photo or PNG/JPEG file (maximum 10 MB). "
                    "Gemini will receive it for a private draft; Google API quota/billing applies."
                    if d.get("ai_mode") else
                    "Send a chart as a photo or PNG/JPEG file (maximum 10 MB)."
                )
                return await self.say(u, prompt)
            if action == "caption":
                return await self.say(u, "Write your analysis caption (up to 900 characters). Current caption:\n\n" + d.get("text", ""))
            return await self.say(u, "Send one or more annotation commands, one per line.\n"
                                  "The original stays unchanged; the marked copy appears in the review preview.\n"
                                  "Coordinates are percentages; top-left is 0 0.\n\n"
                                  "line 40 2650.50\nzone 20 30 70 55 FVG\narrow 20 20 60 50 BOS\n"
                                  "label 10 15 CHoCH\ncrop 5 5 95 95\nresize 1600 900\n\n"
                                  "Labels/levels are yours; the bot does not infer prices.",
                                  [("Undo last annotation", "undo", {"revision": d["revision"]}),
                                   ("Original + edited preview", "preview", {})])
        if action == "chart_fields":
            d = self.require_revision(user, p)
            if d["kind"] != "analysis" or not d.get("recognition"):
                raise ValueError("Upload a chart first to review its extracted fields.")
            d["step"] = "fields"
            self.db.save_draft(user, d)
            return await self.say(
                u,
                manual_fields_prompt(d["recognition"].get("fields")),
            )
        if action == "undo":
            d = self.require_revision(user, p)
            if d.get("commands"):
                d["commands"].pop()
            d["image"] = await asyncio.to_thread(render, self.db.image_path(d["original"]), d["commands"], self.db.directory / "images")
            d["step"] = "ready"
            self.db.save_draft(user, d)
            return await self.preview(u)
        if action == "applications":
            return await self.applications(u, p.get("page", 0))
        if action == "application":
            return await self.application(u, p["user"])
        if action == "review":
            if p.get("status") == "approved":
                if not self.config.ready:
                    raise ValueError("Configure the administrator and both channel IDs before approving members.")
                return await self.access_selection(u, p["user"], [])
            decision = "decline" if p["status"] == "rejected" else "approve"
            return await self.say(u, f"Confirm that you want to {decision} this application?",
                                  [("Confirm decision", "review_confirm", p)])
        if action == "review_access_toggle":
            channels = p.get("channels", [])
            channel = p.get("channel")
            allowed = {destination for destination, _ in self.access_destinations()}
            if (not isinstance(channels, list) or
                    any(item not in allowed for item in channels) or channel not in allowed):
                raise ValueError("Choose only configured access destinations.")
            selected = list(dict.fromkeys(channels))
            if channel in selected:
                selected.remove(channel)
            else:
                selected.append(channel)
            return await self.access_selection(u, p["user"], selected)
        if action == "review_access":
            channels = p.get("channels")
            allowed = {destination for destination, _ in self.access_destinations()}
            if (not isinstance(channels, list) or not channels or
                    any(c not in allowed for c in channels) or len(set(channels)) != len(channels)):
                raise ValueError("Choose one or more configured access destinations.")
            channels = list(dict.fromkeys(channels))
            names = dict(self.access_destinations())
            labels = [names[c] for c in channels]
            invite_modes = [
                f"{names[c]}: direct join" if c == self.config.education_group_id
                else f"{names[c]}: request to join"
                for c in channels
            ]
            return await self.say(
                u, f"Approve applicant {p['user']} and issue a time-limited invite for "
                   f"{' and '.join(labels)}? Invite behavior: {'; '.join(invite_modes)}. "
                   "The member chooses whether to use each invite.",
                [("Approve and issue invite", "review_confirm",
                  {"user": p["user"], "status": "approved", "channels": channels}),
                  ("Change access", "review", {"user": p["user"], "status": "approved"})])
        if action == "review_confirm":
            return await self.approve(u, p)
        if action == "invite":
            names = dict(self.access_destinations())
            destination = names.get(p.get("channel"))
            if not destination:
                raise ValueError("Choose a configured access destination.")
            is_education = p.get("channel") == self.config.education_group_id
            invite_instructions = (
                "They can join directly with this one-use link; do not forward it."
                if is_education else
                "They must request to join; the bot checks the member and current invite."
            )
            return await self.say(u, f"Create a 24-hour "
                                  f"{'direct-join' if is_education else 'join-request'} invite "
                                  f"for this approved member in {destination}?\n{invite_instructions}",
                                  [("Create invite", "invite_confirm", p)])
        if action == "invite_confirm":
            op = self.publisher.prepare(user, "invite", p)
            result = await self.publisher.send(user, op)
            return await self.operation_result(u, op, result)
        if action == "invite_revoke":
            return await self.revoke_access_invite(u, p["user"], p["channel"])
        if action == "membership":
            access_rows = self.db.rows("SELECT channel FROM access WHERE user_id=?", (p["user"],))
            for row in access_rows:
                channel = row["channel"]
                member = await self.bot.get_chat_member(channel, p["user"])
                self.db.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                                (p["user"], channel, member.status, now()))
            return await self.application(u, p["user"])
        if action == "health":
            return await self.health_screen(u)
        if action == "errors":
            rows = self.db.rows("SELECT * FROM errors ORDER BY id DESC LIMIT 12")
            return await self.say(u, "🩺 Recent administrator-only diagnostics\n\n" +
                                  ("\n".join(f"{r['created']} {r['category']}: {r['detail']}" for r in rows)
                                   or "No diagnostic records yet."))
        if action == "backup":
            path = self.db.backup(self.config.retention)
            with open(path, "rb") as f:
                await self.bot.send_document(user, f, caption="Private backup. PostgreSQL exports include chart files and manifest. Store securely off-host.")
            return await self.say(u, "✅ Backup created. Keep an encrypted copy off-host. "
                                  "Restore it into an empty database with publishing disabled.")
        if action == "cleanup":
            return await self.say(u, f"Removed {self.db.cleanup()} unreferenced images older than 7 days.")
        if action == "settings":
            return await self.say(u, f"Admin configured: {bool(self.config.admin)}\n"
                                  f"PRO Signals: {self.config.signals or 'missing'}\nAnalysis: {self.config.analysis or 'missing'}\n"
                                  f"Backup retention: {self.config.retention}\n"
                                  "Add the bot as channel administrator with Post Messages, Edit Messages, and Invite Users permissions.\n"
                                  "Forward a channel post here to discover its ID (forwarding must not be protected).\n"
                                  "Alternatively send a message in the channel after adding this bot; the ID will be sent privately to you.\n"
                                  "Only configure IDs in Secrets, then restart the bot.\n\n"
                                  "Recently discovered channels:\n" + "\n".join(str(x) for x in self.db.get("channels", [])),
                                  [("Clean old unreferenced images", "cleanup", {})])
        if action == "operations":
            return await self.operations(u, p.get("page", 0))
        if action == "operation":
            return await self.operation_screen(u, p["id"])
        if action == "retry":
            not_before = self.db.get(f"retry_after:{p['id']}", 0)
            if time.time() < not_before:
                raise ValueError(f"Please wait {int(not_before-time.time())+1} seconds before trying again.")
            result = await self.publisher.send(user, p["id"])
            return await self.operation_result(u, p["id"], result)
        if action == "reconcile":
            draft = self.db.draft(user)
            saved_bundle = (
                draft if draft and draft.get("kind") == "analysis"
                and draft.get("publish_bundle") else None
            )
            saved_pro_import = (
                draft if draft and draft.get("kind") == "pro_import"
                and draft.get("pro_import_bundle") else None
            )
            self.db.save_draft(user, {
                "kind": "reconcile", "step": "message_id", "operation": p["id"],
                "resume_analysis_bundle": saved_bundle,
                "resume_pro_import_bundle": saved_pro_import,
            })
            return await self.say(u, "🔎 Check the destination channel first. If the exact post is there, enter its numeric message ID.\n\n"
                                  "This records your confirmation; Telegram cannot verify it automatically. Do not guess.")
        if action == "reconcile_confirm":
            d = self.require_revision(user, p)
            await self.publisher.reconcile(user, d["operation"], d["message_id"])
            saved_bundle = d.get("resume_analysis_bundle")
            if saved_bundle:
                self.db.save_draft(user, saved_bundle)
                return await self.analysis_zone_bundle_screen(
                    u, saved_bundle,
                    "The uncertain post was reconciled from your confirmation. No post was resent.")
            saved_pro_import = d.get("resume_pro_import_bundle")
            if saved_pro_import:
                self.db.save_draft(user, saved_pro_import)
                return await self.pro_import_screen(
                    u, saved_pro_import,
                    "The uncertain PRO post was reconciled. No post was resent.")
            self.db.clear_draft(user)
            return await self.say(u, "✅ Reconciliation recorded from your confirmation. Nothing was reposted.")
        if action == "abandon":
            return await self.say(u, "Abandon this operation without sending again? Any post already in Telegram will remain.\n"
                                  "If it was sent, reconcile the existing message instead.",
                                  [("Confirm abandonment", "abandon_confirm", p)])
        if action == "abandon_confirm":
            self.publisher.abandon(user, p["id"])
            return await self.say(u, "✅ Operation abandoned. No Telegram post was deleted or resent.")
        raise ValueError("This action is no longer available. Open the main menu and try again.")

    async def preview(self, u):
        d = self.current(u.effective_user.id)
        if d.get("kind") == "analysis" and d.get("publish_bundle"):
            return await self.analysis_zone_bundle_screen(u, d)
        if d.get("kind") == "pro_import_wait":
            return await self.say(
                u, "Forward the original Market Analysis chart post here, including its caption and image.",
                [("Cancel", "cancel", {})], admin_chrome=False,
            )
        if d.get("kind") == "pro_import":
            return await self.pro_import_screen(u, d)
        if (d.get("kind") == "analysis" and d.get("step") == "ready"
                and d.get("destination") == "analysis" and d.get("image")
                and d.get("text") and not d.get("pro_zone")):
            source = {"text": d["text"], "image": d["image"]}
            if d.get("pro_poi_source") != source:
                try:
                    setups = extract_poi_setups(d["text"])
                except ValueError as exc:
                    d.pop("pro_zones", None)
                    d["pro_poi_source"] = source
                    d["pro_poi_error"] = str(exc)
                    self.db.save_draft(u.effective_user.id, d)
                    return await self.say(
                        u,
                        "⚠️ I found a POI label but cannot prepare its PRO post safely.\n\n"
                        f"{exc}\n\n"
                        "Add the exact MARKET, TIMEFRAME, and clearly labelled POI price range(s) "
                        "to the Market Analysis caption. No channel post has been sent.",
                        [("✏️ Edit Market Analysis", "caption", {}),
                         ("❌ Cancel Draft", "cancel", {})],
                        admin_chrome=False,
                    )
                image = d["image"]
                original = d.get("original") or image
                d["pro_zones"] = [
                    {
                        "setup": setup,
                        "image": image,
                        "original": original,
                        "replaces": None,
                        "independent": True,
                    }
                    for setup in setups
                ]
                d["pro_poi_source"] = source
                d.pop("pro_poi_error", None)
                self.db.save_draft(u.effective_user.id, d)
        if d.get("operation") and d["step"] == "operation":
            return await self.operation_screen(u, d["operation"])
        if d.get("kind") == "zone_signal":
            return await self.zone_signal_prompt(u, d)
        if d.get("kind") == "zone" and d.get("step") == "ready":
            return await self.zone_preview(u, d)
        if d.get("kind") == "zone" and zone_wizard.is_wizard(d):
            upgraded = zone_wizard.normalize(d)
            if upgraded is not d or upgraded.get("wizard_version") != 1:
                d = upgraded
                self.db.save_draft(u.effective_user.id, d)
            return await self.zone_wizard_prompt(u, d)
        if d["kind"] == "zone":
            if d["step"] == "replacement":
                return await self.say(u, f"Replace active setup #{d['replaces']} with {d['setup']['market']} · {d['setup']['zone']}?",
                                      [("Confirm replacement", "zone_replace", {"revision": d["revision"]})])
            if d["step"] == "chart":
                return await self.say(u, "Resume: send the chart image for this zone setup.")
            if d["step"] == "ready":
                return await self.zone_preview(u, d)
        # Persisted conversations can be resumed after restart, not just completed previews.
        step = d.get("step")
        rev = {"revision": d["revision"]}
        if step == "market":
            return await self.say(u, "Continue your signal draft by choosing a market.",
                                  [(m, "market", {"market": m}) for m in MARKETS])
        if step == "symbol":
            return await self.say(u, "Add a symbol or short note, or skip this step.",
                                  [("Skip", "signal_skip", rev)])
        if step in ("wording", "close_note", "close_details", "partial_percent", "filter", "message_id"):
            prompts = {"wording": "Send the full replacement wording.", "close_note": "Send an optional closure note.",
                       "close_details": "Send confirmed exit price and note as `price | note`, or skip both.",
                       "partial_percent": "Enter a percentage greater than 0 and at most 100.",
                       "filter": "Send filters, e.g. status=CLOSED; direction=BUY, or all.",
                       "message_id": "Inspect the channel and enter the exact existing message ID."}
            choices = [("Skip exit and note", "close_skip", rev)] if step in ("close_note", "close_details") else []
            return await self.say(u, "Continue your draft: " + prompts[step], choices)
        if step == "partial_mode":
            return await self.partial_mode(u, d)
        if step == "partial_target":
            return await self.partial_target_prompt(u, d)
        if step == "partial_target_value":
            return await self.say(u, "Continue: enter the confirmed take-profit price.")
        if step == "partial_remaining":
            return await self.say(u, "Optional: enter the confirmed remaining-position status, or skip.",
                                  [("Skip remaining status", "partial_remaining_skip", rev)])
        if (d.get("kind") == "update" and d.get("action") == "tp1_profit_screenshot"
                and step == "chart"):
            return await self.say(
                u,
                f"Resume: upload the TP{d.get('target_number', 1)} profit screenshot. "
                "It will stay private until you review and publish it.",
                [("❌ Cancel Screenshot", "tp1_profit_screenshot_cancel", rev)],
            )
        if (d.get("kind") == "update" and d.get("action") == "tp1_profit_screenshot"
                and step == "prices_manual_input"):
            image_ref = d.get("image") or d.get("original")
            if image_ref:
                image_path = self.db.image_path(image_ref)
                with open(image_path, "rb") as screenshot:
                    if as_document(image_path):
                        await self.bot.send_document(
                            u.effective_chat.id, screenshot,
                            caption=f"Private TP{d.get('target_number', 1)} screenshot — "
                                    "enter or correct its prices below.")
                    else:
                        await self.bot.send_photo(
                            u.effective_chat.id, screenshot,
                            caption=f"Private TP{d.get('target_number', 1)} screenshot — "
                                    "enter or correct its prices below.")
            return await self.say(
                u,
                (d.get("ocr_issue", "Please confirm the prices shown in the screenshot.")
                 + "\n\nEnter them as: entry price | exit price\n"
                 "Example: 1.0800 | 1.0820. Nothing will be posted until you review it."),
                [("❌ Cancel Screenshot", "tp1_profit_screenshot_cancel", rev)],
            )
        if step == "be_confirm":
            entry_value = d["source"].get("entry", "not set")
            return await self.say(
                u, f"Has the stop loss actually been moved to entry {entry_value}? Only confirm after the change is made.",
                [("Confirm SL moved to entry", "be_confirm", rev)])
        if step == "hit_target":
            return await self.hit_target_prompt(u, d)
        if step == "hit_status":
            return await self.hit_status_prompt(u, d)
        if step == "value":
            action = d["action"]
            if action == "partial":
                choices = []
                for n in (25, 50, 75):
                    choices.extend([
                        (f"{n}% — profit secured", "partial_choice",
                         {**rev, "percent": str(n), "mode": "reported"}),
                        (f"{n}% — recommendation only", "partial_choice",
                         {**rev, "percent": str(n), "mode": "recommendation"}),
                    ])
                choices.append(("Custom Percentage", "partial_custom", rev))
                return await self.say(u, "Choose the percentage and whether it was secured profit or a recommendation.",
                                      choices)
            if action == "close":
                return await self.say(u, "Choose the outcome to record.",
                                      [(s, "choose_value", {**rev, "value": s})
                                       for s in ("Win", "Breakeven", "Loss", "Unrecorded")])
            if action == "hit":
                return await self.hit_target_prompt(u, d)
            return await self.say(u, f"Continue the {action} update by sending the confirmed value or message."
                                  + (" Format: target number and price, e.g. 1 2700." if action == "tp" else ""))
        if d["kind"] == "analysis" and step in ("caption", "upload"):
            return await self.say(u, "Continue by sending your analysis caption (up to 900 characters)." if step == "caption"
                                  else "Continue by sending your chart as a photo or PNG/JPEG file.")
        if d["kind"] not in ("signal", "analysis", "update", "edit"):
            raise ValueError("Finish the current input first.")
        if d["kind"] == "analysis" and d.get("original"):
            sent_images = set()
            for field, label in (("original", "Original chart"), ("image", "Annotated preview")):
                if d.get(field):
                    image_path = self.db.image_path(d[field])
                    if str(image_path) in sent_images:
                        continue
                    sent_images.add(str(image_path))
                    with open(image_path, "rb") as f:
                        if as_document(image_path):
                            await self.bot.send_document(u.effective_chat.id, f, caption=label)
                        else:
                            await self.bot.send_photo(u.effective_chat.id, f, caption=label)
            pro_zones = d.get("pro_zones") or ([d["pro_zone"]] if d.get("pro_zone") else [])
            for index, zone in enumerate(pro_zones, start=1):
                preview_path = self.db.image_path(zone["image"])
                with open(preview_path, "rb") as chart:
                    caption = zones.setup_caption(
                        {**zone["setup"], "image": zone["image"]})
                    preview_caption = (
                        f"📍 PRO SIGNALS — POI {index} PRIVATE PREVIEW\n\n" + caption
                    )
                    if as_document(preview_path):
                        await self.bot.send_document(
                            u.effective_chat.id, chart,
                            caption=preview_caption,
                            parse_mode="HTML",
                        )
                    else:
                        await self.bot.send_photo(
                            u.effective_chat.id, chart,
                            caption=preview_caption,
                            parse_mode="HTML",
                        )
        elif (d["kind"] == "update" and
              d.get("action") in ("partial", "tp1_profit_screenshot") and d.get("image")):
            image_path = self.db.image_path(d["image"])
            with open(image_path, "rb") as f:
                if as_document(image_path):
                    await self.bot.send_document(
                        u.effective_chat.id, f, caption="Screenshot attached to trade update")
                else:
                    await self.bot.send_photo(
                        u.effective_chat.id, f, caption="Screenshot attached to trade update")
        text = d.get("text", "")
        internal_ids = [d.get("setup_id"), d.get("operation")]
        for key in ("trade", "source", "setup"):
            record = d.get(key)
            if isinstance(record, dict):
                internal_ids.append(record.get("id"))
                internal_ids.extend(record.get(field) for field in ("message_id", "setup_message_id"))
        if d.get("kind") != "invite":
            try:
                internal_ids.append(self.config.destination(d.get("kind"), d.get("destination")))
            except ValueError:
                pass
        cleaned_text = clean_channel_text(text, internal_ids)
        if cleaned_text != text:
            d["text"] = cleaned_text
            d["public_references_removed"] = True
            self.db.save_draft(u.effective_user.id, d)
            text = cleaned_text
        buttons = []
        destination = d.get("destination")
        if not destination:
            expected = "analysis" if d["kind"] == "analysis" else "signals"
            buttons.append((f"Choose destination: {'Market Analysis' if expected == 'analysis' else 'PRO Signals'}",
                            "destination", {"destination": expected, "revision": d["revision"]}))
        if d["kind"] == "update" and d.get("action") == "partial" and d.get("step") == "ready":
            buttons.append(("Replace chart" if d.get("image") else "Attach chart (optional)",
                            "partial_chart", {"revision": d["revision"]}))
        if (d["kind"] == "update" and d.get("action") == "tp1_profit_screenshot"
                and d.get("step") == "ready"):
            buttons.extend([
                (f"Replace TP{d.get('target_number', 1)} screenshot",
                 "tp1_profit_screenshot_upload",
                 {"revision": d["revision"]}),
                ("❌ Cancel Screenshot", "tp1_profit_screenshot_cancel",
                 {"revision": d["revision"]}),
            ])
        if (d["kind"] == "update" and d.get("action") == "tp1_profit_screenshot"
                and d.get("step") == "prices_review"):
            buttons.extend([
                ("✅ Confirm detected prices", "tp1_screenshot_values_confirm",
                 {"revision": d["revision"]}),
                ("✏️ Edit prices", "tp1_screenshot_values_edit",
                 {"revision": d["revision"]}),
                ("❌ Cancel Screenshot", "tp1_profit_screenshot_cancel",
                 {"revision": d["revision"]}),
            ])
        if (d["kind"] == "update" and d.get("action") == "tp1_profit_screenshot"
                and d.get("step") == "candidate_choice"):
            trade = d.get("trade") or {}
            for index, candidate in enumerate(d.get("ocr_candidates", [])):
                result = calculate_trade_result(
                    candidate.get("symbol") or trade.get("market") or trade.get("symbol"),
                    trade.get("direction"),
                    candidate.get("entry"),
                    candidate.get("exit"),
                )
                value = (f"+{result['pips']} pips" if result["pips"] is not None
                         else f"+{result['price_movement']} price units")
                buttons.append((
                    f"Use {candidate['symbol']} {candidate['direction']}: "
                    f"{candidate['entry']} → {candidate['exit']} ({value})",
                    "tp1_screenshot_candidate_choose",
                    {"revision": d["revision"], "index": index},
                ))
            buttons.append(("❌ Cancel Screenshot", "tp1_profit_screenshot_cancel",
                            {"revision": d["revision"]}))
        if d["kind"] in ("signal", "edit"):
            buttons.append(("Edit wording", "wording", {"revision": d["revision"]}))
        if (d["kind"] == "update" and d.get("action") == "entry_bundle" and
                d.get("source", {}).get("levels_pending") and d.get("step") == "ready"):
            market = d.get("source", {}).get("market") or d.get("source", {}).get("symbol")
            entry_button = (
                "Edit Entry Price" if zones.automatic_tp1_pip_size(market) is not None
                else "Edit Buy Range"
            )
            buttons.extend([
                (entry_button, "entry_bundle_edit",
                 {"revision": d["revision"], "field": "entry"}),
                ("Edit Stop Loss", "entry_bundle_edit",
                 {"revision": d["revision"], "field": "sl"}),
                ("Edit Take Profit", "entry_bundle_edit",
                 {"revision": d["revision"], "field": "targets"}),
            ])
        if d["kind"] == "analysis":
            upload_label = (
                "Upload Chart & Analyze with Gemini" if d.get("ai_mode") else "Upload Chart")
            buttons += [
                ("Edit Caption", "caption", {}),
                (upload_label, "upload", {}),
                ("Annotate", "annotate", {}),
            ]
            if d.get("recognition"):
                buttons.append(("✏️ Correct chart fields", "chart_fields",
                                {"revision": d["revision"]}))
            if d.get("ai_mode"):
                buttons.append(("Continue with manual chart review", "analysis_ai_manual", {}))
            if d.get("pro_zones") and not d.get("publish_bundle"):
                buttons.append(("✏️ Edit POIs in Market Analysis", "caption", {}))
            elif d.get("pro_zone") and not d.get("publish_bundle"):
                buttons.append((
                    "✏️ Edit PRO POI details",
                    "analysis_pro_zone_edit",
                    {"revision": d["revision"]},
                ))
        if text and d.get("step") == "ready" and destination:
            label = ("Approve & Publish Analysis" if d["kind"] == "analysis" else
                     f"📤 Publish TP{d.get('target_number', 1)} Profit Screenshot"
                     if d["kind"] == "update"
                     and d.get("action") == "tp1_profit_screenshot" else
                     "Publish partial update" if d["kind"] == "update" and d.get("action") == "partial" else
                     "Publish reviewed message" if d["kind"] != "edit" else "Apply reviewed edit")
            if d["kind"] == "analysis" and d.get("pro_zone"):
                buttons.append(("📤 Publish Analysis + PRO POI", "publish",
                                {"revision": d["revision"]}))
            else:
                buttons.append((label, "publish", {"revision": d["revision"]}))
        if (d.get("kind") == "update" and d.get("action") == "tp1_profit_screenshot"
                and d.get("step") == "prices_review"):
            detected = d.get("detected_position")
            detected_line = (
                f"Detected position: {detected['symbol']} {detected['direction']}\n"
                if detected else ""
            )
            return await self.say(
                u,
                f"🔎 TP{d.get('target_number', 1)} SCREENSHOT — PRICE REVIEW\n\n"
                f"Reading source: {d.get('price_source', 'screenshot OCR')}\n"
                f"{detected_line}"
                f"Entry price: {d['observed_entry']}\n"
                f"Exit price: {d['observed_exit']}\n"
                f"{d['result_summary']}\n\n"
                "Check these values against the screenshot. Nothing has been posted.",
                buttons,
            )
        if (d.get("kind") == "update" and d.get("action") == "tp1_profit_screenshot"
                and d.get("step") == "candidate_choice"):
            return await self.say(
                u,
                "🔎 MULTIPLE POSITIONS FOUND\n\n"
                "The screenshot contains more than one matching position. Choose the row "
                "that belongs to this active trade. Each option shows the detected symbol, "
                "direction, and left-to-right price pair. You will review and confirm the "
                "selected values before publication.",
                buttons,
            )
        report_text = ""
        if d["kind"] == "analysis" and d.get("ai_analysis"):
            note = d.get("ai_analysis", {}).get("watch_note") or "None supplied."
            report_text = (
                "📊 PRIVATE CHART REVIEW\n"
                "Check the marked POI and confirmation before publishing.\n\n"
                f"Your POI/watchpoint note: {note}\n\n"
            )
        elif d["kind"] == "analysis" and d.get("recognition"):
            report_text = format_review_report(d["recognition"]) + "\n\n"
        reference_notice = ("ℹ️ Internal references are kept in the bot’s records and omitted from the channel copy.\n\n"
                            if d.get("public_references_removed") else "")
        pro_zones = d.get("pro_zones") or ([d["pro_zone"]] if d.get("pro_zone") else [])
        pro_zone_notice = ""
        if pro_zones:
            entries = []
            for index, zone in enumerate(pro_zones, start=1):
                setup = zone["setup"]
                direction = setup.get("poi_direction")
                direction_label = f" ({direction} POI)" if direction else ""
                entries.append(
                    f"POI {index}{direction_label}: {setup.get('market', 'Not set')} · "
                    f"{setup.get('zone', 'Not set')} · {setup.get('timeframe') or 'Not specified'}"
                )
            pro_zone_notice = (
                "📍 PRO SIGNALS POSTS — PRIVATE REVIEW\n"
                + "\n".join(entries)
                + "\nThe same chart will be included with each formatted PRO post. "
                "Market Analysis is posted first; the matching PRO POI posts follow after it is recorded. "
                "Your final confirmation publishes the reviewed set.\n\n"
            )
        auto_tp1_notice = (
            "ℹ️ TP1–TP4 were calculated in 20-pip steps from the exact entry. "
            "Review every price below before publishing.\n\n"
            if d.get("targets_auto") else ""
        )
        review_label = "📝 Review analysis" if d.get("ai_analysis") else "📝 Review draft"
        await self.say(u, report_text + pro_zone_notice + reference_notice + auto_tp1_notice
                          + f"{review_label} — {destination or 'choose a destination'}\n\n"
                          f"{text or 'Add a caption or message before continuing.'}", buttons)

    async def manage(self, u, trade_id, action, target_number=None, notice=None):
        t = self.db.trade(trade_id)
        if t["state"] not in ("ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL"):
            raise ValueError("Only open trades can be managed.")
        if action == "tp1_profit_screenshot":
            return await self.start_tp1_profit_screenshot(
                u, t, target_number=target_number or 1)
        if action == "cancel" and t.get("entry"):
            action = "invalidate"
        if action == "be" and not t.get("entry"):
            raise ValueError("Add the confirmed entry price before moving the stop loss to breakeven.")
        if action == "hit" and not any(not target.get("hit") for target in t.get("targets", {}).values()):
            return await self.say(u, "No available take-profit target is recorded. Add or update a target before reporting one hit.",
                                  [("Trade Details", "trade_details", {"id": trade_id})])
        bundled_entry = action == "entry"
        d = {"kind": "edit" if action == "edit" else "update",
             "action": "entry_bundle" if bundled_entry else action, "source": t,
             "expected_version": t["version"], "step": "entry" if bundled_entry else "value"}
        if d["kind"] == "update":
            d["destination"] = "signals"
        self.db.save_draft(u.effective_user.id, d)
        rev = {"revision": d["revision"]}
        if bundled_entry:
            market = t.get("market") or t.get("symbol")
            auto_tp1_supported = zones.automatic_tp1_pip_size(market) is not None
            if d["source"].get("levels_pending"):
                direction = d["source"].get("direction", "BUY")
                entry_name = (f"exact {direction.title()} Entry" if auto_tp1_supported
                              else f"{direction.title()} Range")
                tp_note = (
                    " TP1–TP4 will be calculated automatically in 20-pip steps from that entry."
                    if auto_tp1_supported else ""
                )
                return await self.say(
                    u, (f"{notice}\n\n" if notice else "") +
                       f"📍 Enter the {entry_name} for the published {direction} NOW signal.\n\n"
                       "The entry must stay inside the original zone. "
                       f"{tp_note} Stop Loss is required next. "
                       "The trade details will be previewed before posting.")
            if auto_tp1_supported:
                ladder_note = (
                    "TP1–TP4 will be calculated automatically in 20-pip steps from this entry."
                    if t.get("levels_pending") else
                    "TP1 will be recalculated automatically as 20 pips from this entry."
                )
                entry_prompt = f"Enter one exact entry price. {ladder_note}"
            else:
                entry_prompt = f"Enter the actual {t['direction'].title()} entry price or range."
            return await self.say(
                u, (f"{notice}\n\n" if notice else "") + "📍 Add entry\n\n" + entry_prompt +
                " I’ll then ask for the Stop Loss. Nothing is published until you review it.")
        if action == "partial":
            choices = []
            for n in (25, 50, 75):
                choices.extend([
                    (f"{n}% — profit secured", "partial_choice",
                     {**rev, "percent": str(n), "mode": "reported"}),
                    (f"{n}% — recommendation only", "partial_choice",
                     {**rev, "percent": str(n), "mode": "recommendation"}),
                ])
            choices.append(("Custom Percentage", "partial_custom", rev))
            return await self.say(u, "Choose the percentage and confirm whether it was secured profit or a recommendation.",
                                  choices)
        if action == "hit":
            return await self.hit_target_prompt(u, d)
        if action == "close":
            return await self.say(u, "Choose the outcome you want recorded. You’ll confirm it before anything is published.",
                                  [(s, "choose_value", {**rev, "value": s})
                                   for s in ("Win", "Loss", "Breakeven", "Unrecorded")])
        if action == "be":
            d["step"] = "be_confirm"
            self.db.save_draft(u.effective_user.id, d)
            return await self.say(
                u, f"Has the stop loss actually been moved to entry {t['entry']}? "
                   "Only confirm after the change is made.",
                [("Confirm SL moved to entry", "be_confirm", {"revision": d["revision"]})])
        if action in ("cancel", "invalidate"):
            if action == "cancel":
                return await self.say(u, "This setup has no recorded entry. Enter the confirmed reason for cancelling it.")
            return await self.say(u, "This trade has an entry. Enter the confirmed reason for invalidating it.")
        prompts = {"entry": (
                       "Enter the exact entry price. TP1–TP4 will be calculated automatically "
                       "in 20-pip steps for supported Forex pairs and XAUUSD."
                       if zones.automatic_tp1_pip_size(t.get("market") or t.get("symbol")) is not None
                       else "Enter the actual entry price or zone, for example 2650-2655."),
                   "sl": f"Current stop loss: {t.get('sl', 'not set')}\nEnter the new stop-loss price after you have changed it.",
                   "sl_tp": f"Current stop loss: {t.get('sl', 'not set')}\n"
                            f"Current take-profit targets: {format_targets(t.get('targets', {}))}\n"
                            "Enter both confirmed values in one message, using this format:\n"
                            "SL 2580 | TP1 2700",
                   "trail": f"Current stop loss: {t.get('sl', 'not set')}\nEnter the confirmed new trailing stop price.",
                   "tp": "Enter the target number and price, for example 1 2700. Current targets:\n" +
                   format_targets(t.get("targets", {})),
                   "custom": "Write the trade-specific update you want to publish.",
                   "edit": "Send the complete replacement text for the original signal. It will be previewed first."}
        await self.say(u, prompts[action])

    def next_automatic_tp(self, trade):
        if not trade.get("targets_auto") or trade.get("levels_pending"):
            return None
        return zones.next_automatic_tp(
            trade.get("market") or trade.get("symbol"),
            trade.get("direction"),
            trade.get("entry"),
            trade.get("targets", {}),
        )

    async def add_automatic_tp_next(self, u, payload):
        user = u.effective_user.id
        self.config.authorize(user, u.effective_chat.type)
        trade = self.db.trade(payload.get("id"))
        if trade.get("version") != payload.get("version"):
            raise ValueError("The trade changed. Reopen Active Trade and review the next target.")
        if trade["state"] not in ("ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL"):
            raise ValueError("Only an active trade can receive another take-profit target.")
        next_target = self.next_automatic_tp(trade)
        if not next_target:
            raise ValueError("An automatic next target is not available for this trade.")
        if self.db.draft(user):
            return await self.say(
                u, "Finish or cancel the current draft before adding the next target.",
                [("Resume Current Draft", "preview", {}),
                 ("Cancel Current Draft", "cancel", {})],
            )
        target_values = [
            target["price"]
            for _, target in sorted(
                trade.get("targets", {}).items(),
                key=lambda item: int(item[0]),
            )
        ]
        target_values.append(next_target["price"])
        zones.validate_signal_targets(
            trade["direction"], trade.get("entry"), ", ".join(target_values))
        draft = {
            "kind": "update",
            "action": "tp",
            "auto_tp_next": True,
            "source": trade,
            "expected_version": trade["version"],
            "destination": "signals",
            "step": "value",
        }
        self.db.save_draft(user, draft)
        draft = self.db.draft(user)
        return await self.finish_update(
            u, draft, f"{next_target['number']} {next_target['price']}")

    def validate_tp1_profit_screenshot_trade(self, trade, target_number=1):
        try:
            target_number = int(target_number)
        except (TypeError, ValueError):
            raise ValueError("Choose a TP1–TP4 target for the screenshot.") from None
        if not 1 <= target_number <= zones.AUTOMATIC_TP_MAX_TARGETS:
            raise ValueError("Profit screenshots are available for TP1–TP4 only.")
        current = self.db.trade(trade["id"])
        if current["version"] != trade.get("version"):
            raise ValueError("Trade changed. Reopen Active Trade and review it again.")
        if current["state"] not in ("ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL"):
            raise ValueError("Profit screenshots are available only while the trade is active.")
        if current.get("levels_pending") or not current.get("message_id"):
            raise ValueError("Publish and complete the trade details before adding a TP screenshot.")
        target = current.get("targets", {}).get(str(target_number))
        if not target:
            raise ValueError(f"TP{target_number} is not set on this trade.")
        records = target_profit_screenshots(current)
        key = str(target_number)
        if key in records:
            raise ValueError(f"A TP{target_number} profit screenshot has already been published.")
        expected = next_target_profit_screenshot(
            current, max_targets=zones.AUTOMATIC_TP_MAX_TARGETS)
        if expected is None:
            raise ValueError("All available TP1–TP4 profit screenshots have already been posted.")
        if expected != target_number:
            raise ValueError(f"Post the TP{expected} profit screenshot first.")
        return current, target

    async def start_tp1_profit_screenshot(self, u, trade, target_number=1):
        current, target = self.validate_tp1_profit_screenshot_trade(
            trade, target_number=target_number)
        target_number = int(target_number)
        draft = {
            "kind": "update",
            "action": "tp1_profit_screenshot",
            "source": current,
            "expected_version": current["version"],
            "destination": "signals",
            "target_number": target_number,
            "target_price": target["price"],
            "tp1_price": target["price"],
            "step": "chart",
        }
        self.db.save_draft(u.effective_user.id, draft)
        draft = self.db.draft(u.effective_user.id)
        return await self.say(
            u,
            f"📸 Upload the TP{target_number} profit screenshot.\n\n"
            "It will be shown to you for review and posted to PRO Signals only after you confirm. "
            "Please hide account numbers, login details, and other private information.",
            [("❌ Cancel Screenshot", "tp1_profit_screenshot_cancel",
              {"revision": draft["revision"]})],
        )

    async def tp1_profit_screenshot_upload(self, u, p):
        draft = self.require_revision(u.effective_user.id, p)
        if (draft.get("kind") != "update" or
                draft.get("action") != "tp1_profit_screenshot" or
                draft.get("step") != "ready"):
            raise ValueError("Open a ready TP screenshot preview before replacing its image.")
        target_number = draft.get("target_number", 1)
        trade, _target = self.validate_tp1_profit_screenshot_trade(
            draft["source"], target_number=target_number)
        draft["trade"] = trade
        draft["step"] = "chart"
        self.db.save_draft(u.effective_user.id, draft)
        draft = self.db.draft(u.effective_user.id)
        return await self.say(
            u, f"Send the replacement TP{target_number} screenshot. "
               "It will remain private until you publish the reviewed update.",
            [("❌ Cancel Screenshot", "tp1_profit_screenshot_cancel",
              {"revision": draft["revision"]})],
        )

    async def tp1_profit_screenshot_cancel(self, u, p):
        draft = self.require_revision(u.effective_user.id, p)
        if (draft.get("kind") != "update" or
                draft.get("action") != "tp1_profit_screenshot"):
            raise ValueError("There is no TP1 screenshot draft to cancel.")
        trade_id = draft["source"]["id"]
        self.db.clear_draft(u.effective_user.id)
        return await self.trade_screen(
            u, trade_id, notice="Screenshot draft cancelled. Nothing was published.")

    async def set_tp1_screenshot_prices(
            self, u, draft, entry_value, exit_value, *, source, detected_position=None):
        target_number = int(draft.get("target_number", 1))
        trade, target = self.validate_tp1_profit_screenshot_trade(
            draft["source"], target_number=target_number)
        entry_value = price(str(entry_value))
        exit_value = price(str(exit_value))
        validate_target_exit(trade["direction"], target["price"], exit_value)
        calculation_market = (
            detected_position.get("symbol") if detected_position else
            trade.get("market") or trade.get("symbol")
        )
        result = calculate_trade_result(
            calculation_market, trade["direction"],
            entry_value, exit_value)
        draft["trade"] = trade
        draft["target_number"] = target_number
        draft["target_price"] = target["price"]
        if target_number == 1:
            draft["tp1_price"] = target["price"]
        draft["observed_entry"] = entry_value
        draft["observed_exit"] = exit_value
        draft["pips"] = result["pips"]
        draft["price_movement"] = result["price_movement"]
        draft["result_summary"] = (
            f"Calculated result: +{result['pips']} pips"
            if result["pips"] is not None else
            "Pip result: unavailable (pip size not configured for this market)\n"
            f"Price movement: +{result['price_movement']} price units"
        )
        draft["price_source"] = source
        if detected_position:
            draft["detected_position"] = {
                "symbol": detected_position["symbol"],
                "direction": detected_position["direction"],
            }
        else:
            draft.pop("detected_position", None)
        draft.pop("ocr_candidates", None)
        emoji = "🟢" if trade["direction"] == "BUY" else "🔴"
        draft["text"] = (
            f"🎯 TP{target_number} HIT — PROFIT SCREENSHOT\n\n"
            f"📊 {trade.get('symbol') or trade.get('market')} · "
            f"{emoji} {trade['direction']}\n"
            f"📍 Entry: {entry_value}\n"
            f"🏁 Exit: {exit_value}\n"
            f"📈 {draft['result_summary']}\n"
            f"🎯 Take Profit {target_number}: {target['price']}\n\n"
            "📸 Profit screenshot attached for reference."
        )
        draft["step"] = "prices_review"
        draft.pop("prices_confirmed", None)
        self.db.save_draft(u.effective_user.id, draft)
        return await self.preview(u)

    async def tp1_screenshot_values_confirm(self, u, p):
        draft = self.require_revision(u.effective_user.id, p)
        if (draft.get("kind") != "update" or
                draft.get("action") != "tp1_profit_screenshot" or
                draft.get("step") != "prices_review"):
            raise ValueError("Open the current TP1 price review before confirming.")
        trade, target = self.validate_tp1_profit_screenshot_trade(
            draft["source"], target_number=draft.get("target_number", 1))
        detected_position = draft.get("detected_position")
        calculation_market = (
            detected_position.get("symbol") if detected_position else
            trade.get("market") or trade.get("symbol")
        )
        result = calculate_trade_result(
            calculation_market, trade["direction"],
            draft.get("observed_entry"), draft.get("observed_exit"))
        validate_target_exit(
            trade["direction"], target["price"], draft.get("observed_exit"))
        draft["pips"] = result["pips"]
        draft["price_movement"] = result["price_movement"]
        draft["result_summary"] = (
            f"Calculated result: +{result['pips']} pips"
            if result["pips"] is not None else
            "Pip result: unavailable (pip size not configured for this market)\n"
            f"Price movement: +{result['price_movement']} price units"
        )
        draft["prices_confirmed"] = True
        draft["step"] = "ready"
        self.db.save_draft(u.effective_user.id, draft)
        return await self.preview(u)

    async def tp1_screenshot_values_edit(self, u, p):
        draft = self.require_revision(u.effective_user.id, p)
        if (draft.get("kind") != "update" or
                draft.get("action") != "tp1_profit_screenshot" or
                draft.get("step") != "prices_review"):
            raise ValueError("Open the current TP1 price review before editing.")
        draft["step"] = "prices_manual_input"
        draft["prices_confirmed"] = False
        self.db.save_draft(u.effective_user.id, draft)
        return await self.preview(u)

    async def tp1_screenshot_candidate_choose(self, u, p):
        draft = self.require_revision(u.effective_user.id, p)
        if (draft.get("kind") != "update" or
                draft.get("action") != "tp1_profit_screenshot" or
                draft.get("step") != "candidate_choice"):
            raise ValueError("Open the current position choices before selecting a row.")
        candidates = draft.get("ocr_candidates") or []
        try:
            index = int(p.get("index"))
        except (TypeError, ValueError):
            raise ValueError("That screenshot row selection is invalid.") from None
        if index < 0 or index >= len(candidates):
            raise ValueError("That screenshot row is no longer available. Upload the image again.")
        candidate = candidates[index]
        trade, _target = self.validate_tp1_profit_screenshot_trade(
            draft["source"], target_number=draft.get("target_number", 1))
        if candidate.get("direction") != trade.get("direction"):
            raise ValueError("That screenshot row direction does not match the active trade.")
        return await self.set_tp1_screenshot_prices(
            u, draft, candidate["entry"], candidate["exit"],
            source="screenshot OCR",
            detected_position=candidate,
        )

    async def partial_target_prompt(self, u, d):
        d["step"] = "partial_target"
        self.db.save_draft(u.effective_user.id, d)
        rev = {"revision": d["revision"]}
        targets = d["source"].get("targets", {})
        buttons = [(f"TP{key} · {target['price']}", "partial_target_choice",
                    {**rev, "target": target["price"]})
                   for key, target in sorted(targets.items(), key=lambda item: int(item[0]))]
        buttons.append(("Enter another confirmed TP level", "partial_target_manual", rev))
        return await self.say(u, "Select the TP level actually reached, or enter its confirmed price.",
                              buttons)

    async def hit_target_prompt(self, u, d):
        targets = d.get("source", {}).get("targets", {})
        available = [(key, target) for key, target in targets.items() if not target.get("hit")]
        if not available:
            return await self.say(u, "No unhit TP targets are recorded. Add or update a TP first.")
        d["step"] = "hit_target"
        self.db.save_draft(u.effective_user.id, d)
        rev = {"revision": d["revision"]}
        buttons = [(f"TP{key} · {target['price']}", "hit_target_choice",
                    {**rev, "target": key})
                   for key, target in sorted(available, key=lambda item: int(item[0]))]
        return await self.say(u, "Select the TP number you observed hitting.", buttons)

    async def select_hit_target(self, u, d, target_number):
        if not str(target_number).isdigit():
            raise ValueError("Choose an existing TP number.")
        key = str(int(target_number))
        target = d.get("source", {}).get("targets", {}).get(key)
        if not target or target.get("hit"):
            raise ValueError("That TP target is not available; reopen the trade.")
        d["hit_target"] = key
        d["step"] = "hit_status"
        self.db.save_draft(u.effective_user.id, d)
        return await self.hit_status_prompt(u, d)

    async def hit_status_prompt(self, u, d):
        key = str(d.get("hit_target", ""))
        target = d.get("source", {}).get("targets", {}).get(key)
        if not target or target.get("hit"):
            raise ValueError("Select an available TP number first.")
        rev = {"revision": d["revision"]}
        return await self.say(
            u, f"TP{key} at {target['price']} was observed hitting. Was it a partial or final target?",
            [("Partial target", "hit_status", {**rev, "status": "partial"}),
             ("Final target", "hit_status", {**rev, "status": "final"})])

    async def entry_bundle_text(self, u, d, value):
        skip = value.strip().lower() == "skip"
        levels_pending = bool(d.get("source", {}).get("levels_pending"))
        if d["step"] == "entry":
            market = d.get("source", {}).get("market") or d.get("source", {}).get("symbol")
            direction = d.get("source", {}).get("direction")
            if levels_pending:
                setup = self.db.get("setup:" + str(d["source"].get("setup_id")))
                if not setup:
                    return await self.say(
                        u, "The original setup details are unavailable. Do not guess the range.")
                try:
                    d["entry_value"] = zones.validate_signal_entry(
                        setup, direction, value)
                except ValueError as exc:
                    return await self.say(
                        u, f"{exc}\nEnter an exact entry price inside the active setup zone.")
            else:
                try:
                    parsed, _ = change(d["source"], "entry", value)
                    d["entry_value"] = parsed["entry"]
                except ValueError as exc:
                    return await self.say(u, str(exc))
            target_one = d.get("source", {}).get("targets", {}).get("1", {})
            auto_ladder = None
            if not target_one.get("hit"):
                try:
                    auto_ladder = zones.automatic_tp_ladder(
                        market, direction, d["entry_value"])
                except ValueError as exc:
                    return await self.say(
                        u, f"{exc}\nEnter one exact entry price to calculate the targets.")
            if auto_ladder:
                d["targets_text"] = ", ".join(
                    item["price"] for item in auto_ladder.values())
                d["targets_auto"] = True
            else:
                d.pop("targets_text", None)
                d.pop("targets_auto", None)
            d["step"] = "sl"
            self.db.save_draft(u.effective_user.id, d)
            entry_name = (
                "Exact entry" if zones.automatic_tp1_pip_size(market) is not None
                else "Entry"
            )
            tp_note = (
                "\nAutomatically calculated from this exact entry:\n" +
                "\n".join(
                    f"TP{number}: {item['price']} ({item['pips']} pips)"
                    for number, item in auto_ladder.items()
                )
                if auto_ladder else ""
            )
            if levels_pending:
                relation = "below" if direction == "BUY" else "above"
                return await self.say(
                    u, f"{entry_name} saved: {d['entry_value']}.{tp_note}\n"
                       f"Enter the Stop Loss {relation} the entry.")
            return await self.say(
                u, f"{entry_name} saved in this draft: {d['entry_value']}.{tp_note}\n"
                   f"Existing SL: {d['source'].get('sl', 'not set')}.\n"
                   "Enter the Stop Loss, or send `skip` to leave the existing SL unchanged.")
        if d["step"] == "sl":
            try:
                if levels_pending:
                    if skip:
                        raise ValueError("Stop Loss is required before publishing the trade-details update.")
                    d["sl_value"] = zones.validate_signal_stop_loss(
                        d["source"].get("direction"), d.get("entry_value"), value)
                elif not skip:
                    trade, _ = change(d["source"], "entry", d["entry_value"])
                    trade, _ = change(trade, "sl", value)
                    d["sl_value"] = trade["sl"]
            except ValueError as exc:
                return await self.say(u, f"{exc}\nEnter a valid Stop Loss to continue.")
            d["step"] = "tp"
            self.db.save_draft(u.effective_user.id, d)
            if levels_pending and d.get("targets_auto"):
                return await self.finish_pending_entry_bundle(u, d)
            if levels_pending:
                relation = "above" if d["source"].get("direction") == "BUY" else "below"
                return await self.say(
                    u, f"Stop Loss saved: {d['sl_value']}.\n"
                       f"Enter one or more Take Profit prices {relation} the full range, "
                       "separated by commas.")
            existing = format_targets(d["source"].get("targets", {}))
            if d.get("targets_auto"):
                return await self.say(
                    u, f"Stop Loss saved: {d.get('sl_value', d['source'].get('sl', 'unchanged'))}.\n"
                       f"TP1–TP4 are calculated in 20-pip steps: {d['targets_text']}.\n"
                       "Send `skip` to use these targets, or enter target prices to override them.")
            return await self.say(
                u, f"Existing take-profit targets: {existing}.\n"
                   "Enter a target number and price, for example 1 2700, or send skip to leave targets unchanged.")
        if d["step"] != "tp":
            raise ValueError("This Add Entry draft is out of sequence. Reopen the trade controls.")

        if levels_pending:
            if skip and not d.get("targets_auto"):
                return await self.say(
                    u, "At least one Take Profit is required before publishing the trade-details update.")
            if not skip:
                d["targets_text"] = safe_text(value, 1000)
                d["targets_auto"] = False
            try:
                return await self.finish_pending_entry_bundle(u, d)
            except ValueError as exc:
                return await self.say(u, f"{exc}\nEnter valid Take Profit prices to continue.")

        trade = d["source"]
        try:
            trade, _ = change(trade, "entry", d["entry_value"])
            if d.get("sl_value"):
                trade, _ = change(trade, "sl", d["sl_value"])

            if not skip:
                trade, _ = change(trade, "tp", value)
                d["targets_auto"] = False
            elif d.get("targets_auto"):
                trade["targets"] = zones.validate_signal_targets(
                    trade["direction"], trade["entry"], d["targets_text"])
        except ValueError as exc:
            return await self.say(u, f"{exc}\nReview the price and try again.")
        trade["targets_auto"] = bool(d.get("targets_auto"))
        targets = ", ".join(
            f"TP{key}: {target['price']}"
            for key, target in sorted(trade.get("targets", {}).items(), key=lambda item: int(item[0])))
        d["text"] = (
            "📌 VAYDA SMART MONEY HUB\n\n🔄 TRADE DETAILS UPDATED\n\n"
            f"📊 Pair: {trade['symbol']}\n📌 Direction: {trade['direction']}\n"
            f"📍 Entry: {trade['entry']}\n🛑 Stop Loss: {trade.get('sl') or 'Not supplied'}\n"
            f"🎯 Targets: {targets or 'Not supplied'}")
        d["trade"] = trade
        d["step"] = "ready"
        self.db.save_draft(u.effective_user.id, d)
        return await self.preview(u)

    async def finish_pending_entry_bundle(self, u, d):
        setup = self.db.get("setup:" + str(d["source"].get("setup_id")))
        if not setup:
            raise ValueError("The original setup details are unavailable. Do not guess Take Profit prices.")
        levels = zones.validate_signal_levels(
            setup, d["source"].get("direction"), d.get("entry_value"),
            d.get("sl_value"), d.get("targets_text"))
        trade = {
            **d["source"],
            "entry": levels["entry"],
            "sl": levels["sl"],
            "targets": levels["targets"],
            "levels_pending": False,
            "targets_auto": bool(d.get("targets_auto")),
        }
        target_lines = "\n".join(
            f"🎯 TP{number}: {target['price']}"
            for number, target in levels["targets"].items()
        )
        entry_name = (
            "Entry" if zones.automatic_tp1_pip_size(setup.get("market")) is not None
            else ("Buy Range" if trade["direction"] == "BUY" else "Sell Range")
        )
        d["trade"] = trade
        d["text"] = (
            "📍 TRADE DETAILS UPDATE\n\n"
            f"📌 Direction: {trade['direction']}\n"
            f"📍 {entry_name}: {levels['entry']}\n"
            f"🛡️ Stop Loss: {levels['sl']}\n"
            f"{target_lines}"
        )
        d["step"] = "ready"
        self.db.save_draft(u.effective_user.id, d)
        return await self.preview(u)

    async def finish_update(self, u, d, value):
        if d["kind"] == "edit":
            d["trade"], d["text"] = d["source"], safe_text(value)
        else:
            d["trade"], d["text"] = change(d["source"], d["action"], value)
            if d.get("auto_tp_next"):
                d["trade"]["targets_auto"] = True
        d["step"] = "ready"
        self.db.save_draft(u.effective_user.id, d)
        await self.preview(u)

    async def partial_mode(self, u, d):
        await self.say(u, f"{d['percent']}% partial: what are you publishing?",
                       [("I confirm profit was actually secured", "partial_mode", {"revision": d["revision"], "mode": "reported"}),
                        ("Recommendation only", "partial_mode", {"revision": d["revision"], "mode": "recommendation"})])

    async def text(self, u, context):
        if u.effective_chat.type != "private":
            return
        user = u.effective_user.id
        if await self.applicant_followup_pending_text(u, u.message.text or ""):
            return
        if await self.education_onboarding_handle_text(u, u.message.text or ""):
            return
        origin = u.message.forward_origin
        if origin and user == self.config.admin and getattr(origin, "chat", None):
            pending = self.db.draft(user)
            if pending and pending.get("kind") == "pro_import_wait":
                return await self.say(
                    u,
                    "I received a text-only forward. Please forward the original Market Analysis chart post with its caption and image.",
                    admin_chrome=False,
                )
            return await self.say(u, f"Forwarded channel ID: {origin.chat.id}\n{origin.chat.title}\nConfigure the matching channel Secret; restart afterward.")
        if user == self.config.admin:
            if self.db.get(self.assistant_inactive_notice_pending_key(user)):
                return await self.assistant_inactive_notice_save(u, u.message.text or "")
            reply_case = self.db.get(self.assistant_reply_pending_key(user))
            if reply_case:
                return await self.assistant_submit_admin_reply(
                    u, reply_case, u.message.text or "")
        if user != self.config.admin and self.db.get(f"assistant:contact_pending:{user}"):
            return await self.assistant_submit_contact(u, u.message.text or "")
        d = self.db.draft(user)
        if not d:
            if user == self.config.admin:
                return await self.say(u, "You’re not in an active setup. Open the administrator menu for available options.")
            return await self.assistant_respond(u, u.message.text or "")
        if user != self.config.admin and d.get("kind") in (
                "application", "destination_application", "pro_screening",
                "member_info_response", "pro_evidence"):
            await self.applicant_followup_ensure_notice(u)
        if d["kind"] == "application":
            return await self.application_answer(u, d)
        if d["kind"] == "destination_application":
            return await self.destination_application_answer(u, d)
        if d["kind"] == "pro_screening":
            return await self.pro_screening_prompt(
                u, d, notice="Use the buttons to answer each PRO Signals application question.")
        if d["kind"] == "member_info_response":
            return await self.member_info_response(u, d)
        if d["kind"] == "pro_evidence":
            return await self.say(u, "Please upload a JPEG, PNG, WEBP screenshot or PDF for this evidence request.")
        self.config.authorize(user)
        text = safe_text(u.message.text)
        if d.get("kind") == "pro_import_wait":
            return await self.say(
                u, "Forward the original Market Analysis chart post here, including its caption and image.",
                admin_chrome=False,
            )
        if d.get("kind") == "pro_import" and d.get("step") == "caption_edit":
            return await self.update_pro_import_caption(u, d, u.message.text or "")
        if d.get("kind") == "signal_result_caption":
            return await self.signal_result_caption_text(u, d, u.message.text or "")
        if d["kind"] == "zone" and zone_wizard.is_wizard(d):
            upgraded = zone_wizard.normalize(d)
            if upgraded is not d:
                d = upgraded
                self.db.save_draft(user, d)
                return await self.zone_wizard_prompt(
                    u, d, "This older draft has been reopened in the step-by-step setup wizard."
                )
            d = upgraded
            if d.get("step") in ("market", "timeframe", "expiry", "edit", "preview"):
                return await self.zone_wizard_prompt(u, d, "Choose an option using the buttons below.")
            try:
                zone_wizard.answer(d, d.get("step"), text)
            except ValueError as exc:
                return await self.zone_wizard_prompt(u, d, str(exc))
            self.db.save_draft(user, d)
            return await self.zone_wizard_prompt(u, d)
        if d["kind"] == "zone":
            raise ValueError("This setup is waiting for a chart or preview action. Use Preview Draft / Resume.")
        if d["kind"] == "zone_confirmation":
            with self.db.transaction() as c:
                setup = zones.active(self.db, d["setup_id"])
                setup["confirmation"] = safe_text(text, 300)
                zones.save_in(c, setup)
            self.db.clear_draft(user)
            notice = ("✅ Confirmation recorded. Choose Publish BUY Signal Now or Publish SELL Signal Now "
                      "only when you are ready to post the signal.")
            if not await self.update_setup_post(setup):
                notice += " The confirmation is saved, but the original zone post could not be updated; check PRO Signals."
            return await self.menu(u, notice)
        if d["kind"] == "zone_signal":
            return await self.zone_signal_answer(u, d, text)
        if d["kind"] == "update" and d.get("action") == "entry_bundle":
            return await self.entry_bundle_text(u, d, text)
        if (d["kind"] == "update" and
                d.get("action") == "tp1_profit_screenshot" and
                d.get("step") == "prices_manual_input"):
            entry_value, separator, exit_value = text.partition("|")
            if not separator:
                raise ValueError("Enter both values as entry price | exit price.")
            return await self.set_tp1_screenshot_prices(
                u, d, entry_value.strip(), exit_value.strip(),
                source="administrator entry")
        if d["kind"] == "filter":
            filters = {}
            if text.lower() != "all":
                for part in text.split(";"):
                    key, sep, value = part.strip().partition("=")
                    if not sep or key not in ("market", "direction", "status", "from", "to"):
                        raise ValueError("Use filters like market=Gold/XAUUSD; direction=BUY; status=CLOSED.")
                    if key in ("from", "to"):
                        try:
                            date.fromisoformat(value)
                        except ValueError:
                            raise ValueError("Enter filter dates as YYYY-MM-DD, for example 2026-01-31.") from None
                    if key == "direction" and value not in ("BUY", "SELL"):
                        raise ValueError("Direction must be BUY or SELL.")
                    filters[key] = value
            self.db.clear_draft(user)
            return await self.history(u, {"filters": filters})
        if d["kind"] == "reconcile":
            if not text.isdigit() or int(text) < 1:
                raise ValueError("Enter a positive numeric message ID.")
            d["message_id"] = int(text)
            self.db.save_draft(user, d)
            return await self.say(u, f"Confirm that operation {d['operation']} matches channel message {text}?",
                                  [("Confirm exact match", "reconcile_confirm", {"revision": d["revision"]})])
        if d["kind"] == "signal" and d["step"] == "symbol":
            d["symbol"] = safe_text(text, 100)
            d["text"] = confirmation(d["direction"], d["symbol"])
        elif d["step"] == "wording":
            d["text"] = safe_text(text)
        elif d["kind"] in ("update", "edit") and d["step"] == "value":
            return await self.finish_update(u, d, text)
        elif d["step"] == "partial_percent":
            from decimal import Decimal
            try:
                d["percent"] = price(text)
            except ValueError:
                raise ValueError("Enter a numeric percentage greater than 0 and no more than 100.") from None
            if Decimal(d["percent"]) > 100:
                raise ValueError("The percentage cannot exceed 100%.")
            d["step"] = "partial_mode"
            self.db.save_draft(user, d)
            return await self.partial_mode(u, d)
        elif d["kind"] == "update" and d.get("action") == "partial" and d["step"] == "partial_target_value":
            d["partial_target"] = price(text)
            d["step"] = "partial_remaining"
            self.db.save_draft(user, d)
            return await self.say(u, "Optional: enter the confirmed remaining-position status, or skip.",
                                  [("Skip remaining status", "partial_remaining_skip",
                                    {"revision": d["revision"]})])
        elif d["kind"] == "update" and d.get("action") == "partial" and d["step"] == "partial_remaining":
            remaining = "" if text.lower() == "skip" else safe_text(text, 200)
            return await self.finish_update(
                u, d, f"{d['percent']}|reported|{d['partial_target']}|{remaining}")
        elif d["kind"] == "update" and d.get("action") == "close" and d["step"] == "close_details":
            if text.lower() == "skip":
                return await self.finish_update(u, d, f"{d['outcome']}||")
            exit_value, sep, note = text.partition("|")
            exit_value = price(exit_value) if exit_value.strip() else ""
            note = safe_text(note, 500) if sep and note.strip() else ""
            return await self.finish_update(u, d, f"{d['outcome']}|{exit_value}|{note}")
        elif d["kind"] == "update" and d.get("action") == "close" and d["step"] == "close_note":
            return await self.finish_update(u, d, f"{d['outcome']}|{safe_text(text, 500)}")
        elif d["kind"] == "analysis" and d["step"] == "fields":
            report = d.get("recognition")
            if not report:
                raise ValueError("Upload a chart before correcting extracted fields.")
            report["fields"] = parse_manual_fields(text, report.get("fields"))
            d["recognition"] = report
            d["text"] = build_analysis_caption(report["fields"])
        elif d["kind"] == "analysis" and d["step"] == "ai_focus":
            d["watch_note"] = "" if text.strip().casefold() == "skip" else safe_text(text, 300)
            d["step"] = "ai_upload"
            self.db.save_draft(user, d)
            return await self.say(
                u, "Upload one chart for Gemini to review. The image will be sent to Google "
                   "for this private analysis draft; no post is made until you approve the preview.",
                [("Cancel Draft", "cancel", {})],
                admin_chrome=False,
            )
        elif d["kind"] == "analysis" and d["step"] == "annotate":
            commands = [clean_channel_text(command)
                        for command in d.get("commands", []) + text.splitlines()]
            if len(commands) > 50:
                raise ValueError("Maximum 50 annotations per chart.")
            d["image"] = await asyncio.to_thread(render, self.db.image_path(d["original"]), commands, self.db.directory / "images")
            d["commands"] = commands
        elif d["kind"] == "analysis" and d["step"] in ("caption", "ready"):
            d["text"] = validate_analysis(text)
        else:
            raise ValueError("Use the current buttons; this draft is not awaiting text.")
        d["step"] = "ready"
        self.db.save_draft(user, d)
        await self.preview(u)

    async def photo(self, u, context):
        user = u.effective_user.id
        saved = self.db.draft(user)
        if saved and saved.get("kind") == "pro_evidence":
            return await self.save_funding_evidence(u)
        if user != self.config.admin:
            if saved and saved.get("kind") in ("destination_application", "application", "member_info_response"):
                return await self.say(u, "Please answer the current application question with a text message. "
                                        "You can send evidence only when the bot asks for it privately.")
        self.config.authorize(user, u.effective_chat.type)
        if saved and saved.get("kind") == "signal_result_upload":
            return await self.save_signal_result_screenshot(u)
        if saved and saved.get("kind") == "pro_import_wait":
            return await self.accept_pro_import_forward(u)
        d = self.current(user)
        if d["kind"] == "analysis" and d.get("ai_mode") and d.get("step") not in (
                "ai_upload", "ai_error", "upload"):
            raise ValueError("Open Gemini chart analysis and choose Upload Chart before sending an image.")
        chart_update = (d["kind"] == "update" and
                        d.get("action") in ("partial", "tp1_profit_screenshot") and
                        d.get("step") == "chart")
        if d["kind"] not in ("analysis", "zone") and not chart_update:
            raise ValueError(
                "Open an active TP1 screenshot, partial update, analysis, or zone setup before uploading an image.")
        if d["kind"] == "zone" and d.get("step") != "chart":
            raise ValueError("Open a zone setup and confirm any replacement before uploading its chart.")
        photo = getattr(u.message, "photo", None)
        document = getattr(u.message, "document", None)
        item = photo[-1] if photo else document
        if not item:
            raise ValueError("Send one chart image.")
        if document and getattr(item, "mime_type", "") not in (
                "image/jpeg", "image/png", "image/webp"):
            raise ValueError("For charts, send a JPEG, PNG, or WEBP image. PDFs are accepted only as private funding evidence.")
        if item.file_size and item.file_size > 10 * 1024 * 1024:
            raise ValueError("Maximum upload size is 10 MB.")
        file = await item.get_file()
        raw = self.db.directory / "images" / f"{uid()}.upload"
        try:
            await file.download_to_drive(raw)
            d["original"] = await asyncio.to_thread(import_chart, raw, self.db.directory / "images")
            if d["kind"] == "zone":
                d["image"] = d["original"]
                d["step"] = "ready"
                self.db.save_draft(u.effective_user.id, d)
                return await self.zone_preview(u, d)
            if chart_update:
                d["image"] = d["original"]
                if d.get("action") == "tp1_profit_screenshot":
                    target_number = d.get("target_number", 1)
                    trade, target = self.validate_tp1_profit_screenshot_trade(
                        d["source"], target_number=target_number)
                    d["trade"] = trade
                    d["target_number"] = int(target_number)
                    d["target_price"] = target["price"]
                    if int(target_number) == 1:
                        d["tp1_price"] = target["price"]
                    observed = await asyncio.to_thread(
                        read_screenshot_prices, d["original"])
                    if observed:
                        if observed.get("candidates"):
                            matching = []
                            for candidate in observed["candidates"]:
                                if candidate.get("direction") != trade.get("direction"):
                                    continue
                                try:
                                    validate_target_exit(
                                        trade["direction"], target["price"],
                                        candidate["exit"])
                                    calculate_trade_result(
                                        candidate.get("symbol") or
                                        trade.get("market") or trade.get("symbol"),
                                        trade["direction"],
                                        candidate["entry"],
                                        candidate["exit"],
                                    )
                                except (KeyError, ValueError):
                                    continue
                                matching.append(candidate)
                            if len(matching) == 1:
                                selected = matching[0]
                                try:
                                    return await self.set_tp1_screenshot_prices(
                                        u, d, selected["entry"], selected["exit"],
                                        source="screenshot OCR",
                                        detected_position=selected,
                                    )
                                except ValueError as exc:
                                    d["ocr_issue"] = str(exc)
                            elif len(matching) > 1:
                                d["ocr_candidates"] = matching
                                d["step"] = "candidate_choice"
                                self.db.save_draft(u.effective_user.id, d)
                                return await self.preview(u)
                            else:
                                d["ocr_issue"] = (
                                    "No screenshot row matched the active trade direction "
                                    "with a profitable price movement. Enter the exact values manually."
                                )
                        else:
                            try:
                                return await self.set_tp1_screenshot_prices(
                                    u, d, observed["entry"], observed["exit"],
                                    source="screenshot OCR")
                            except ValueError as exc:
                                d["ocr_issue"] = str(exc)
                    else:
                        d["ocr_issue"] = (
                            "Entry and exit prices could not be safely paired from the screenshot. "
                            "No values were guessed."
                        )
                    d["step"] = "prices_manual_input"
                    self.db.save_draft(u.effective_user.id, d)
                    return await self.preview(u)
                d["step"] = "ready"
                self.db.save_draft(u.effective_user.id, d)
                return await self.preview(u)
            d["commands"] = []
            if d["kind"] == "analysis" and d.get("ai_mode"):
                try:
                    analysis = await asyncio.to_thread(
                        analyze_chart_with_gemini, d["original"], d.get("watch_note", ""))
                    d["text"] = validate_analysis(
                        "📊 SMART MONEY HUB | MARKET ANALYSIS 🥇\n\n" + analysis
                    )
                except GeminiAnalysisError as exc:
                    d["step"] = "ai_error"
                    d["image"] = d["original"]
                    self.db.save_draft(u.effective_user.id, d)
                    return await self.say(
                        u, f"⚠️ Gemini could not complete this chart review.\n\n{exc}\n\n"
                           "No analysis was posted. Retry by uploading the chart again, "
                           "or continue with manual chart review.",
                        [("Upload Chart", "upload", {}),
                         ("Continue with manual review", "analysis_ai_manual", {}),
                         ("Cancel Draft", "cancel", {})],
                        admin_chrome=False,
                    )
                d["ai_analysis"] = {
                    "provider": "Gemini",
                    "model": GEMINI_ANALYSIS_MODEL,
                    "mode": "quick",
                    "watch_note": d.get("watch_note", ""),
                }
                d["image"] = d["original"]
                d["step"] = "ready"
                self.db.save_draft(u.effective_user.id, d)
                return await self.preview(u)
            d["recognition"] = await asyncio.to_thread(
                analyze_chart, d["original"], allow_ocr=self.config.isolated_test)
            d["image"] = await asyncio.to_thread(
                render_review_copy, d["original"], d["recognition"], self.db.directory / "images")
            if not d.get("text"):
                d["text"] = build_analysis_caption(d["recognition"]["fields"])
        finally:
            raw.unlink(missing_ok=True)
        if u.message.caption:
            d["text"] = validate_analysis(u.message.caption)
        d["step"] = "ready"
        self.db.save_draft(u.effective_user.id, d)
        await self.preview(u)

    async def unsupported_message(self, update, context):
        if update.effective_chat.type != "private":
            return
        if update.effective_user.id == self.config.admin:
            return await self.say(update, "I can’t use that message type here. Open the administrator menu for controls.")
        return await self.assistant_unexpected_media(update)

    async def zone_signal_prompt(self, u, draft, notice=None):
        if draft.get("kind") != "zone_signal":
            raise ValueError("This signal draft is no longer available.")
        if draft.get("step") in ("submitting", "operation"):
            setup_record = self.db.get("setup:" + str(draft.get("setup_id")), {})
            operation = draft.get("operation") or setup_record.get("operation")
            if operation:
                draft.update(step="operation", operation=operation)
                self.db.save_draft(u.effective_user.id, draft)
                return await self.operation_screen(u, operation)
            if setup_record.get("status") == "used":
                self.db.clear_draft(u.effective_user.id)
                return await self.say(
                    u, "⚠️ This setup has already been consumed. No second signal was created.",
                    [("↩️ Zone & Signals", "admin_category", {"category": "zone"})],
                )
            draft["step"] = "preview"
            self.db.save_draft(u.effective_user.id, draft)

        try:
            setup = zones.active(self.db, draft.get("setup_id"))
        except ValueError as exc:
            self.db.clear_draft(u.effective_user.id)
            return await self.say(
                u, f"⚠️ This signal draft is no longer valid: {exc} No signal was published.",
                [("↩️ Zone & Signals", "admin_category", {"category": "zone"})],
                admin_chrome=False,
            )
        if not setup.get("confirmation"):
            self.db.clear_draft(u.effective_user.id)
            return await self.say(
                u, "⚠️ The active zone no longer has a recorded confirmation. No signal was published.",
                [("Record observed confirmation", "zone_confirmation",
                  {"setup_id": setup["id"]})],
                admin_chrome=False,
            )

        step = draft.get("step")
        revision = {"revision": draft["revision"]}
        auto_tp1_supported = zones.automatic_tp1_pip_size(setup.get("market")) is not None
        entry_label = "Entry Price" if auto_tp1_supported else (
            "Buy Range" if draft["direction"] == "BUY" else "Sell Range")
        field_buttons = [
            (f"Set {entry_label}",
             "zone_signal_field", {**revision, "field": "entry"}),
            ("Set Stop Loss", "zone_signal_field", {**revision, "field": "sl"}),
            ("Set Take Profit", "zone_signal_field", {**revision, "field": "targets"}),
        ]
        if step == "direction_preview":
            direction = draft["direction"]
            details_text = (
                "the exact Entry Price, Stop Loss, and auto-calculated TP1–TP4 "
                "(20-pip steps from entry)"
                if auto_tp1_supported else
                f"the {direction.title()} Range, Stop Loss, and Take Profit"
            )
            publishing_status = (
                "<b>READY</b>" if self.config.allow_publishing and self.publisher.verified
                else "<b>LOCKED</b> — publishing is OFF or verification is incomplete"
            )
            text = (
                f"<b>🔎 PRIVATE {direction} NOW PREVIEW</b>\n\n"
                "The first PRO Signals post will contain only:\n\n"
                f"{zones.signal_public_text(direction)}\n\n"
                f"After it is published, you can add {details_text} "
                "in a separate reviewed update. They will not be added to this first post.\n\n"
                f"🔐 <b>Publishing status:</b> {publishing_status}"
            )
            if notice:
                text = f"<b>{escape(str(notice))}</b>\n\n" + text
            return await self.say(
                u, text,
                [(f"✅ Confirm & Publish {direction} NOW", "zone_signal_confirm", revision),
                 ("Cancel", "zone_signal_cancel", revision)],
                parse_mode="HTML", admin_chrome=False,
            )
        if step == "controls":
            entry_value = draft.get("entry_value") or "Not set"
            stop_loss = draft.get("stop_loss") or "Not set"
            take_profits = draft.get("targets_text") or "Not set"
            if draft.get("targets_auto"):
                take_profits += " (TP1–TP4 auto-calculated in 20-pip steps)"
            safe_market = escape(str(setup["market"]))
            safe_zone = escape(str(setup["zone"]))
            safe_timeframe = escape(str(setup.get("timeframe") or ""))
            publishing_status = (
                "<b>READY</b>" if self.config.allow_publishing and self.publisher.verified
                else "<b>LOCKED</b> — publishing is OFF or verification is incomplete"
            )
            text = (
                f"<b>🛠️ PRIVATE {draft['direction']} SIGNAL CONTROLS</b>\n\n"
                f"📊 <b>Market:</b> {safe_market}\n"
                f"🎯 <b>Active zone:</b> {safe_zone}"
                + (f" · {safe_timeframe}" if safe_timeframe else "")
                + f"\n📍 <b>{entry_label}:</b> {escape(str(entry_value))}\n"
                f"🛡️ <b>Stop Loss:</b> {escape(str(stop_loss))}\n"
                f"🎯 <b>Take Profit:</b> {escape(str(take_profits))}\n\n"
                "Set or edit each value, then choose Review & Publish. "
                "These details stay in the private admin review; the channel post will contain only the direction.\n"
                f"🔐 <b>Publishing status:</b> {publishing_status}"
            )
            if notice:
                text = f"<b>{escape(str(notice))}</b>\n\n" + text
            return await self.say(
                u, text,
                [*field_buttons,
                 ("Review & Publish", "zone_signal_review", revision),
                 ("Cancel", "zone_signal_cancel", revision)],
                parse_mode="HTML", admin_chrome=False,
            )

        if step == "entry":
            if auto_tp1_supported:
                prompt = (f"<b>📍 SET EXACT {draft['direction']} ENTRY</b>\n\n"
                          "Enter one price within the active zone. TP1–TP4 will be calculated "
                          "automatically in 20-pip steps from this exact entry.")
            else:
                prompt = (f"<b>📍 SET {draft['direction']} RANGE</b>\n\n"
                          "Enter a price or range within the active zone, such as 2651–2654. "
                          "The complete range must remain inside the zone.")
        elif step == "sl":
            relation = "below" if draft.get("direction") == "BUY" else "above"
            entry_reference = (
                "the exact entry" if auto_tp1_supported else "the full Entry range"
            )
            prompt = (f"<b>🛡️ SET STOP LOSS</b>\n\nFor this {draft.get('direction')} signal, "
                      f"it must be {relation} {entry_reference}.")
        elif step == "targets":
            prompt = (
                "<b>🎯 SET TAKE PROFIT</b>\n\n"
                + ("Enter one or more prices separated by commas to replace the auto-calculated TP1–TP4."
                   if draft.get("targets_auto") else
                   "Enter one or more prices separated by commas, for example: 2670, 2680.")
            )
        elif step == "preview":
            edit_entry_label = "Edit Entry Price" if auto_tp1_supported else "Edit Entry"
            try:
                levels = zones.validate_signal_levels(
                    setup, draft.get("direction"), draft.get("entry_value"),
                    draft.get("stop_loss"), draft.get("targets_text"),
                )
            except ValueError as exc:
                return await self.say(
                    u, f"⚠️ The signal preview needs correction: {exc}",
                    [(edit_entry_label, "zone_signal_field",
                      {"revision": draft["revision"], "field": "entry"}),
                     ("Edit Stop Loss", "zone_signal_field",
                      {"revision": draft["revision"], "field": "sl"}),
                     ("Edit Take Profit", "zone_signal_field",
                      {"revision": draft["revision"], "field": "targets"}),
                     ("Back to Signal Controls", "zone_signal_controls",
                      {"revision": draft["revision"]}),
                     ("Cancel Signal", "zone_signal_cancel", {"revision": draft["revision"]})],
                    admin_chrome=False,
                )
            target_lines = "\n".join(
                f"  • TP{number}: {target['price']}"
                for number, target in levels["targets"].items()
            )
            state = ("ON" if self.config.allow_publishing and self.publisher.verified
                     else "OFF / not verified")
            target_lines = "\n".join(
                f"  • <b>TP{number}:</b> {escape(str(target['price']))}"
                + (" <i>(auto · 20 pips)</i>"
                   if draft.get("targets_auto") and number == "1" else "")
                for number, target in levels["targets"].items()
            )
            preview = (
                "<b>🔎 PRIVATE ADMIN REVIEW — PRO SIGNALS</b>\n\n"
                f"📊 <b>Market:</b> {escape(str(setup['market']))}\n"
                f"🧭 <b>Direction:</b> {draft['direction']}\n"
                f"📍 <b>{entry_label}:</b> "
                f"{escape(str(levels['entry']))}\n"
                f"🛡️ <b>Stop Loss:</b> {escape(str(levels['sl']))}\n"
                f"🎯 <b>Take Profit:</b>\n{target_lines}\n\n"
                f"📌 <b>Source zone:</b> {escape(str(setup['zone']))}"
                + (f" · {escape(str(setup['timeframe']))}" if setup.get("timeframe") else "")
                + f"\n✅ <b>Observed confirmation:</b> {escape(str(setup['confirmation']))}\n"
                f"🔐 <b>Publishing:</b> {state}\n\n"
                f"📨 <b>Exact public channel message:</b>\n"
                f"{zones.signal_public_text(draft['direction'])}\n\n"
                "The market, range, Stop Loss, Take Profit, timeframe, and confirmation will not appear "
                "in the public signal message. Confirm only after reviewing these private details."
            )
            if notice:
                preview = f"<b>{escape(str(notice))}</b>\n\n" + preview
            return await self.say(
                u, preview,
                [(edit_entry_label, "zone_signal_field",
                  {"revision": draft["revision"], "field": "entry"}),
                 ("Edit Stop Loss", "zone_signal_field",
                  {"revision": draft["revision"], "field": "sl"}),
                 ("Edit Take Profit", "zone_signal_field",
                  {"revision": draft["revision"], "field": "targets"}),
                 ("Back to Signal Controls", "zone_signal_controls",
                  {"revision": draft["revision"]}),
                 ("✅ Confirm & Publish", "zone_signal_confirm",
                  {"revision": draft["revision"]}),
                 ("Cancel", "zone_signal_cancel",
                  {"revision": draft["revision"]})],
                parse_mode="HTML", admin_chrome=False,
            )
        elif step not in ("entry", "sl", "targets"):
            self.db.clear_draft(u.effective_user.id)
            return await self.say(
                u, "⚠️ This signal draft is no longer in a valid step. No signal was published.",
                [("↩️ Zone & Signals", "admin_category", {"category": "zone"})],
                admin_chrome=False,
            )
        return await self.say(
            u, (f"<b>{escape(str(notice))}</b>\n\n" if notice else "") + prompt,
            [("Back to Signal Controls", "zone_signal_controls", revision),
             ("Cancel", "zone_signal_cancel", revision)],
            parse_mode="HTML", admin_chrome=False,
        )

    async def zone_signal_answer(self, u, draft, value):
        try:
            setup = zones.active(self.db, draft.get("setup_id"))
            if not setup.get("confirmation"):
                raise ValueError("Record the observed setup confirmation before preparing a signal.")
            step = draft.get("step")
            if step == "entry":
                draft["entry_value"] = zones.validate_signal_entry(
                    setup, draft.get("direction"), value)
                draft.pop("stop_loss", None)
                draft.pop("targets_text", None)
                draft.pop("targets_auto", None)
                auto_ladder = zones.automatic_tp_ladder(
                    setup.get("market"), draft.get("direction"), draft["entry_value"])
                if auto_ladder:
                    draft["targets_text"] = ", ".join(
                        target["price"] for target in auto_ladder.values())
                    draft["targets_auto"] = True
                draft["step"] = "controls"
            elif step == "sl":
                if not draft.get("entry_value"):
                    raise ValueError("Set the exact entry or entry range before entering Stop Loss.")
                draft["stop_loss"] = zones.validate_signal_stop_loss(
                    draft.get("direction"), draft.get("entry_value"), value)
                draft["step"] = "controls"
            elif step == "targets":
                if not draft.get("entry_value"):
                    raise ValueError("Set the Buy or Sell Range before entering Take Profit.")
                zones.validate_signal_targets(
                    draft.get("direction"), draft.get("entry_value"), value)
                draft["targets_text"] = safe_text(value, 1000)
                draft["targets_auto"] = False
                draft["step"] = "controls"
            else:
                raise ValueError("This signal draft is out of sequence. Reopen Zone & Signals.")
        except ValueError as exc:
            return await self.zone_signal_prompt(u, draft, "⚠️ " + str(exc))
        self.db.save_draft(u.effective_user.id, draft)
        return await self.zone_signal_prompt(u, draft)

    async def confirm_zone_signal(self, u, user, payload):
        draft = self.require_revision(user, payload)
        direction_first = (
            draft.get("kind") == "zone_signal" and
            draft.get("direction") in ("BUY", "SELL") and
            draft.get("direction_first") is True and
            draft.get("step") == "direction_preview"
        )
        if (draft.get("kind") != "zone_signal" or
                (draft.get("step") != "preview" and not direction_first)):
            raise ValueError("Review the signal preview before confirming.")

        setup_record = self.db.get("setup:" + str(draft.get("setup_id")), {})
        if setup_record.get("status") == "used":
            operation = setup_record.get("operation")
            if operation:
                draft.update(step="operation", operation=operation)
                self.db.save_draft(user, draft)
                return await self.operation_screen(u, operation)
            self.db.clear_draft(user)
            return await self.say(u, "⚠️ This setup has already been used. No duplicate signal was created.")

        try:
            setup = zones.active(self.db, draft.get("setup_id"))
            if not setup.get("confirmation"):
                raise ValueError("The active setup confirmation is missing.")
            levels = None if direction_first else zones.validate_signal_levels(
                setup, draft.get("direction"), draft.get("entry_value"),
                draft.get("stop_loss"), draft.get("targets_text"),
            )
        except ValueError as exc:
            return await self.zone_signal_prompt(u, draft, "⚠️ " + str(exc))

        if not self.config.allow_publishing:
            return await self.zone_signal_prompt(
                u, draft, "🔒 Publishing is OFF. The signal was not prepared or sent."
            )
        if not self.publisher.verified:
            return await self.zone_signal_prompt(
                u, draft, "🔒 Publishing verification is incomplete. The signal was not prepared or sent."
            )

        draft["step"] = "submitting"
        self.db.save_draft(user, draft)
        try:
            signal = zones.signal_payload(
                setup, draft["direction"], user, levels=levels,
                direction_first=direction_first)
            operation = self.publisher.prepare(user, "signal", signal)
            # Reserve a durable per-signal result record before Telegram can
            # receive the signal. It becomes available only after delivery.
            self.db.create_signal_result(signal["trade"]["id"], user)
        except ValueError as exc:
            draft["step"] = "preview"
            self.db.save_draft(user, draft)
            return await self.zone_signal_prompt(u, draft, "⚠️ " + str(exc))

        draft.update(step="operation", operation=operation)
        self.db.save_draft(user, draft)
        try:
            result = await self.publisher.send(user, operation)
        except ValueError as exc:
            row, _ = self.publisher.operation(operation)
            if row["status"] == "uncertain":
                return await self.say(
                    u,
                    "⚠️ The send result is uncertain: Telegram may or may not have received this signal. "
                    "Check PRO Signals first; "
                    "the bot will not repost it automatically.",
                    [("Review / Reconcile", "operation", {"id": operation})],
                    admin_chrome=False,
                )
            raise
        row, signal_payload = self.publisher.operation(operation)
        if row["status"] == "done":
            setup = self.db.get("setup:" + str(signal_payload.get("setup_id")))
            updated = await self.update_setup_post(setup)
            self.db.clear_draft(user)
            notice = f"✅ {draft['direction']} signal published to PRO Signals and linked to this trade."
            if not updated:
                notice += " The original zone post could not be updated; check PRO Signals."
            if direction_first and draft["direction"] == "SELL":
                return await self.manage(
                    u, signal_payload["trade"]["id"], "entry", notice=notice)
            return await self.trade_screen(
                u, signal_payload["trade"]["id"], notice=notice)
        return await self.operation_result(u, operation, result)

    async def zone_preview(self, u, d):
        if not d.get("image"):
            raise ValueError("A chart image is required for a zone setup post.")
        setup = {**d["setup"], "image": d["image"]}
        path = self.db.image_path(d["image"])
        with open(path, "rb") as f:
            if as_document(path):
                await self.bot.send_document(u.effective_chat.id, f, caption="Zone setup chart preview")
            else:
                await self.bot.send_photo(u.effective_chat.id, f, caption="Zone setup chart preview")
        caption = clean_channel_text(zones.setup_caption(setup), [setup.get("id")])
        if d.get("attached_to_analysis"):
            return await self.say(
                u,
                "📍 Review the separate PRO Signals zone post\n\n" + caption +
                "\n\nThis uses the chart attached to your Market Analysis draft. "
                "Nothing has been posted. You will review both channel posts before the final publish.",
                [
                    ("⬅️ Edit zone details", "zone_wizard_edit",
                     {"revision": d["revision"]}),
                    ("Attach zone to Market Analysis", "analysis_pro_zone_attach",
                     {"revision": d["revision"]}),
                    ("Cancel zone details", "zone_wizard_cancel",
                     {"revision": d["revision"]}),
                ],
                parse_mode="HTML",
            )
        await self.say(u, "📍 Review zone and chart — PRO Signals\n\n" + caption +
                       "\n\nBefore posting, check the market, zone prices, timeframe, and confirmation "
                       "condition. You will choose BUY or SELL only after recording an observed confirmation.\n"
                       "Publishing this posts only the zone + chart. It does not publish a BUY/SELL signal.",
                       [("📍 Publish Zone + Chart to PRO Signals", "zone_publish",
                         {"revision": d["revision"]})], parse_mode="HTML")

    async def analysis_pro_zone_add(self, u, analysis_draft):
        user = u.effective_user.id
        if (analysis_draft.get("kind") != "analysis" or
                analysis_draft.get("step") != "ready" or
                not analysis_draft.get("text") or
                not (analysis_draft.get("image") or analysis_draft.get("original"))):
            raise ValueError("Finish the Market Analysis caption and upload its chart before adding a PRO zone.")
        if analysis_draft.get("pro_zone") or analysis_draft.get("publish_bundle"):
            raise ValueError("This analysis already has PRO zone details. Choose Edit PRO Zone instead.")
        self.config.destination("analysis", "analysis")
        analysis_draft["destination"] = "analysis"
        image = analysis_draft.get("image") or analysis_draft.get("original")
        zone_draft = zone_wizard.new_draft()
        zone_draft.update(
            attached_to_analysis=True,
            resume_analysis=analysis_draft,
            image=image,
            original=analysis_draft.get("original") or image,
        )
        self.db.save_draft(user, zone_draft)
        return await self.zone_wizard_prompt(
            u, zone_draft,
            "Add the exact POI details for the PRO Signals post. "
            "The chart from this Market Analysis draft will be reused.",
        )

    async def analysis_pro_zone_edit(self, u, analysis_draft):
        user = u.effective_user.id
        pro_zone = analysis_draft.get("pro_zone")
        if (analysis_draft.get("kind") != "analysis" or not pro_zone or
                analysis_draft.get("publish_bundle")):
            raise ValueError("There are no editable PRO zone details in this draft.")
        zone_draft = zone_wizard.new_draft()
        zone_draft.update(
            attached_to_analysis=True,
            resume_analysis={
                key: value for key, value in analysis_draft.items()
                if key != "pro_zone"
            },
            image=pro_zone["image"],
            original=pro_zone.get("original") or pro_zone["image"],
            replaces=pro_zone.get("replaces"),
        )
        zone_draft["answers"] = dict(pro_zone["answers"])
        zone_draft["step"] = "preview"
        zone_draft["setup"] = pro_zone["setup"]
        self.db.save_draft(user, zone_draft)
        return await self.zone_wizard_prompt(
            u, zone_draft, "Edit the separate PRO Signals zone details.")

    async def analysis_pro_zone_attach(self, u, zone_draft):
        user = u.effective_user.id
        if (zone_draft.get("kind") != "zone" or
                not zone_draft.get("attached_to_analysis") or
                zone_draft.get("step") != "ready" or
                not zone_draft.get("image") or not zone_draft.get("setup")):
            raise ValueError("Review and confirm the complete PRO zone before attaching it.")
        analysis_draft = zone_draft.get("resume_analysis")
        if not analysis_draft or analysis_draft.get("kind") != "analysis":
            raise ValueError("The saved Market Analysis draft is unavailable.")
        analysis_draft["pro_zone"] = {
            "setup": zone_draft["setup"],
            "answers": dict(zone_draft.get("answers", {})),
            "image": zone_draft["image"],
            "original": zone_draft.get("original") or zone_draft["image"],
            "replaces": zone_draft.get("replaces"),
        }
        analysis_draft["destination"] = "analysis"
        analysis_draft["step"] = "ready"
        self.db.save_draft(user, analysis_draft)
        return await self.preview(u)

    @staticmethod
    def pro_import_source_key(channel_id, message_id):
        if not channel_id or not message_id:
            return None
        return f"pro_import_source:{channel_id}:{message_id}"

    async def pro_import_start(self, u):
        user = u.effective_user.id
        self.config.authorize(user, u.effective_chat.type)
        existing = self.db.draft(user)
        if existing:
            return await self.say(
                u,
                "Finish or cancel the current draft before forwarding a published Market Analysis post.",
                [("Resume Current Draft", "preview", {}),
                 ("Cancel Current Draft", "cancel", {})],
                admin_chrome=False,
            )
        self.db.save_draft(user, {"kind": "pro_import_wait", "step": "source"})
        return await self.say(
            u,
            "Forward the original chart post from the configured Market Analysis channel here. "
            "It must include its caption and image, and must be a Telegram forward so I can verify its source. "
            "I’ll prepare only a private PRO preview; the Market Analysis post will not be sent again.",
            [("Cancel", "cancel", {})],
            admin_chrome=False,
        )

    async def accept_pro_import_forward(self, u):
        user = u.effective_user.id
        message = getattr(u, "effective_message", None) or getattr(u, "message", None)
        origin = getattr(message, "forward_origin", None)
        source_chat = getattr(origin, "chat", None)
        source_message_id = getattr(origin, "message_id", None)
        try:
            source_channel_id = int(getattr(source_chat, "id", 0))
            configured_channel_id = int(self.config.analysis or 0)
            source_message_id = int(source_message_id or 0)
        except (TypeError, ValueError):
            source_channel_id = configured_channel_id = source_message_id = 0
        if (not origin or not source_chat or source_channel_id != configured_channel_id
                or source_message_id <= 0):
            return await self.say(
                u,
                "⚠️ This is not a verifiable forward from the configured Market Analysis channel. "
                "Nothing was prepared or sent. Forward the original, unprotected chart post.",
                admin_chrome=False,
            )

        draft = self.db.draft(user)
        if not draft or draft.get("kind") != "pro_import_wait":
            raise ValueError("Start “Send posted POI to PRO” before forwarding a chart post.")
        source_key = self.pro_import_source_key(configured_channel_id, source_message_id)
        previous = self.db.get(source_key)
        if previous and previous.get("status") != "cancelled":
            if previous.get("status") == "done":
                return await self.say(
                    u,
                    "✅ This Market Analysis post has already been processed for PRO. "
                    "It was not posted again.",
                    [("↩️ Analysis & Drafts", "admin_category", {"category": "analysis"})],
                    admin_chrome=False,
                )
            if (draft.get("kind") == "pro_import" and
                    draft.get("source_message_id") == source_message_id):
                return await self.pro_import_screen(u, draft)
            return await self.say(
                u,
                "A PRO review or publishing operation already exists for this Market Analysis post. "
                "Resume that draft or resolve its Operations record; it was not duplicated.",
                [("Resume Current Draft", "preview", {}),
                 ("Review Operations", "operations", {})],
                admin_chrome=False,
            )

        caption = (getattr(message, "caption", None) or "").strip()
        if not caption:
            return await self.say(
                u,
                "⚠️ The forwarded chart post has no caption. Forward the original Market Analysis post "
                "with its MARKET, TIMEFRAME, and labelled POI price range.",
                admin_chrome=False,
            )
        try:
            setups = extract_poi_setups(caption)
        except ValueError as exc:
            return await self.say(
                u, f"⚠️ I could not prepare the PRO post safely.\n\n{exc}\n\n"
                "No channel post was sent. Add clearly labelled POI prices to the source caption, then forward the updated post again.",
                admin_chrome=False,
            )
        if not setups:
            return await self.say(
                u,
                "⚠️ No clearly labelled POI range was found in that caption. "
                "Add a MARKET, TIMEFRAME, and POI ZONE with two exact prices, then forward it again.",
                admin_chrome=False,
            )

        photo = getattr(message, "photo", None)
        document = getattr(message, "document", None)
        item = photo[-1] if photo else document
        if not item:
            return await self.say(
                u, "⚠️ The forwarded post does not include a chart image. No post was sent.",
                admin_chrome=False,
            )
        if document and getattr(item, "mime_type", "") not in (
                "image/jpeg", "image/png", "image/webp"):
            return await self.say(
                u, "⚠️ The forwarded chart must be a JPEG, PNG, or WEBP image. No post was sent.",
                admin_chrome=False,
            )
        if item.file_size and item.file_size > 10 * 1024 * 1024:
            return await self.say(u, "⚠️ The forwarded image is over the 10 MB limit. No post was sent.",
                                  admin_chrome=False)

        raw = self.db.directory / "images" / f"{uid()}.upload"
        try:
            telegram_file = await item.get_file()
            await telegram_file.download_to_drive(raw)
            image_ref = await asyncio.to_thread(
                import_chart, raw, self.db.directory / "images")
        finally:
            raw.unlink(missing_ok=True)

        pro_zones = []
        for setup in setups:
            setup["market_analysis_message_id"] = source_message_id
            pro_zones.append({
                "setup": setup,
                "image": image_ref,
                "original": image_ref,
                "replaces": None,
                "independent": True,
            })
        draft = {
            "kind": "pro_import",
            "step": "review",
            "text": caption,
            "image": image_ref,
            "original": image_ref,
            "source_channel": configured_channel_id,
            "source_message_id": source_message_id,
            "pro_zones": pro_zones,
        }
        self.db.save_draft(user, draft)
        draft = self.db.draft(user)
        # save_draft persists the top-level chart reference as an asset; mirror
        # that durable reference into every nested POI payload before review.
        for item in draft.get("pro_zones") or []:
            item["image"] = draft["image"]
            item["original"] = draft.get("original") or draft["image"]
        self.db.save_draft(user, draft)
        draft = self.db.draft(user)
        self.db.put(source_key, {
            "status": "review",
            "message_id": source_message_id,
        })
        return await self.pro_import_screen(
            u, draft,
            "The source is verified. The Market Analysis post will not be reposted.",
        )

    async def update_pro_import_caption(self, u, draft, caption):
        if draft.get("step") != "caption_edit":
            raise ValueError("Open the current POI caption editor before sending text.")
        caption = (caption or "").strip()
        try:
            setups = extract_poi_setups(caption)
        except ValueError as exc:
            return await self.say(
                u, f"⚠️ {exc}\n\nPaste the full corrected caption. No channel post was sent.",
                admin_chrome=False,
            )
        if not setups:
            return await self.say(
                u, "⚠️ No clearly labelled POI range was found. Add the MARKET, TIMEFRAME, "
                "and POI ZONE price range, then send the full caption again.",
                admin_chrome=False,
            )
        pro_zones = []
        for setup in setups:
            setup["market_analysis_message_id"] = draft["source_message_id"]
            pro_zones.append({
                "setup": setup,
                "image": draft["image"],
                "original": draft.get("original") or draft["image"],
                "replaces": None,
                "independent": True,
            })
        draft.update(text=caption, pro_zones=pro_zones, step="review")
        draft.pop("pro_import_bundle", None)
        self.db.save_draft(u.effective_user.id, draft)
        return await self.pro_import_screen(
            u, self.db.draft(u.effective_user.id),
            "Caption updated. Review every POI before publishing to PRO.",
        )

    async def pro_import_screen(self, u, draft, notice=None):
        if draft.get("kind") != "pro_import":
            raise ValueError("This PRO review is no longer available.")
        bundle = draft.get("pro_import_bundle") or {}
        operations = bundle.get("setups") or []
        if not draft.get("pro_import_bundle"):
            previews = []
            for index, item in enumerate(draft.get("pro_zones") or [], 1):
                setup = {**item["setup"], "image": item["image"]}
                caption = clean_channel_text(zones.setup_caption(setup), [setup.get("id")])
                previews.append(f"POI {index}: {setup.get('market')} · {setup.get('zone')} · {setup.get('timeframe')}")
                path = self.db.image_path(item["image"])
                with open(path, "rb") as chart:
                    await self.bot.send_photo(
                        u.effective_chat.id, chart,
                        caption=f"📍 PRO POI {index} — PRIVATE PREVIEW\n\n{caption}",
                        parse_mode="HTML",
                    )
            buttons = [
                ("✏️ Edit POI details", "pro_import_edit", {"revision": draft["revision"]}),
                ("📤 Publish POI(s) to PRO Signals", "pro_import_publish", {"revision": draft["revision"]}),
                ("Cancel", "cancel", {}),
            ]
            text = (
                "📤 EXISTING MARKET ANALYSIS → PRO SIGNALS\n\n"
                "The forwarded Market Analysis post is already live. It will not be sent again. "
                "The chart will be reused, and each clearly labelled POI will be posted separately to PRO Signals.\n\n"
                + "\n".join(previews) +
                "\n\nReview the private previews. Publishing requires the normal verified, enabled controls."
            )
            if notice:
                text = notice + "\n\n" + text
            return await self.say(u, text, buttons, admin_chrome=False)

        lines = ["📤 EXISTING MARKET ANALYSIS → PRO SIGNALS", ""]
        buttons = []
        all_done = len(operations) == len(draft.get("pro_zones") or [])
        has_blocker = not all_done
        for index, operation in enumerate(operations):
            row, payload = self.publisher.operation(operation)
            setup = payload.get("setup") or {}
            label = f"PRO POI {index + 1}"
            lines.append(
                f"{label}: {row['status'].replace('_', ' ').title()} · "
                f"{setup.get('market', 'Market')} · {setup.get('zone', '')}"
            )
            if row["status"] != "done":
                all_done = False
            if row["status"] in ("uncertain", "sending"):
                has_blocker = True
                buttons.append((f"Review {label} operation", "operation", {"id": operation}))
            elif row["status"] in ("failed", "abandoned"):
                has_blocker = True
                buttons.append((
                    f"Retry rejected {label}", "pro_import_retry", {"index": index}))
        if len(operations) < len(draft.get("pro_zones") or []):
            has_blocker = False
        if all_done:
            buttons.append(("Finish and link to Market Analysis", "pro_import_finish", {}))
        elif not has_blocker:
            buttons.append(("Continue PRO publishing", "pro_import_continue", {}))
        buttons.append(("↩️ Admin Menu", "menu", {}))
        lines.extend([
            "",
            "Only PRO Signals is being sent. The original Market Analysis post is not changed or reposted.",
        ])
        if notice:
            lines.extend(["", notice])
        return await self.say(u, "\n".join(lines), buttons, admin_chrome=False)

    async def publish_pro_import(self, u, draft):
        if draft.get("kind") != "pro_import" or draft.get("step") != "review":
            raise ValueError("Review the existing POI before publishing.")
        if not self.config.allow_publishing:
            return await self.pro_import_screen(
                u, draft, "Publishing is OFF. No PRO channel post was sent.")
        source_key = self.pro_import_source_key(
            draft.get("source_channel"), draft.get("source_message_id"))
        marker = self.db.get(source_key, {}) if source_key else {}
        if marker.get("status") == "done":
            raise ValueError("This Market Analysis post was already cross-posted to PRO.")
        if marker.get("status") not in ("review", "publishing"):
            raise ValueError("The forwarded Market Analysis source is no longer available for this review.")

        draft["pro_import_bundle"] = {"setups": []}
        draft["step"] = "bundle"
        self.db.save_draft(u.effective_user.id, draft)
        draft = self.db.draft(u.effective_user.id)
        self.db.put(source_key, {
            "status": "publishing",
            "message_id": draft["source_message_id"],
            "operations": [],
        })
        return await self.continue_pro_import(u, self.db.draft(u.effective_user.id))

    async def continue_pro_import(self, u, draft):
        if draft.get("kind") != "pro_import" or not draft.get("pro_import_bundle"):
            raise ValueError("No saved PRO publishing operations are available.")
        operations = draft["pro_import_bundle"].get("setups") or []
        pro_zones = draft.get("pro_zones") or []
        if len(operations) > len(pro_zones):
            return await self.pro_import_screen(
                u, draft, "The saved PRO operation list does not match this review. Check Operations before continuing.")
        source_key = self.pro_import_source_key(
            draft.get("source_channel"), draft.get("source_message_id"))
        for item in pro_zones[len(operations):]:
            setup = {
                **item["setup"],
                "market_analysis_message_id": draft["source_message_id"],
                "market_analysis_source_channel_id": draft["source_channel"],
                "market_analysis_source_verified": True,
            }
            payload = {
                "destination": "signals",
                "setup": setup,
                "replaces": None,
                "independent": True,
                "image": item["image"],
                "original": item.get("original") or item["image"],
                "text": zones.setup_caption(setup),
                "source_analysis_message_id": draft["source_message_id"],
            }
            try:
                operation = self.publisher.prepare(u.effective_user.id, "setup", payload)
            except ValueError as exc:
                return await self.pro_import_screen(u, draft, str(exc))
            operations.append(operation)
            draft["pro_import_bundle"]["setups"] = list(operations)
            self.db.save_draft(u.effective_user.id, draft)
            self.db.put(source_key, {
                "status": "publishing",
                "message_id": draft["source_message_id"],
                "operations": list(operations),
            })
        draft = self.db.draft(u.effective_user.id)
        operations = draft["pro_import_bundle"]["setups"]
        for operation in operations:
            row, _payload = self.publisher.operation(operation)
            if row["status"] == "done":
                continue
            if row["status"] not in ("prepared", "retryable"):
                return await self.pro_import_screen(
                    u, draft, "A PRO post needs review before the next one can continue.")
            try:
                await self.publisher.send(u.effective_user.id, operation)
            except ValueError as exc:
                return await self.pro_import_screen(u, draft, str(exc))
            row, _payload = self.publisher.operation(operation)
            if row["status"] != "done":
                return await self.pro_import_screen(
                    u, draft, "A PRO post did not complete. Review its saved operation before continuing.")
        return await self.finish_pro_import(u, self.db.draft(u.effective_user.id))

    async def retry_pro_import_operation(self, u, draft, index):
        operations = (draft.get("pro_import_bundle") or {}).get("setups") or []
        try:
            index = int(index)
            operation = operations[index]
        except (TypeError, ValueError, IndexError):
            raise ValueError("Choose a valid PRO POI operation to retry.") from None
        row, payload = self.publisher.operation(operation)
        if row["status"] not in ("failed", "abandoned"):
            raise ValueError("Only a rejected or abandoned PRO post can be retried.")
        replacement = self.publisher.prepare(u.effective_user.id, "setup", payload)
        operations[index] = replacement
        draft["pro_import_bundle"]["setups"] = operations
        self.db.save_draft(u.effective_user.id, draft)
        source_key = self.pro_import_source_key(
            draft.get("source_channel"), draft.get("source_message_id"))
        self.db.put(source_key, {
            "status": "publishing",
            "message_id": draft["source_message_id"],
            "operations": operations,
        })
        return await self.continue_pro_import(u, self.db.draft(u.effective_user.id))

    async def finish_pro_import(self, u, draft):
        operations = (draft.get("pro_import_bundle") or {}).get("setups") or []
        if not operations or len(operations) != len(draft.get("pro_zones") or []):
            return await self.pro_import_screen(
                u, draft, "Every PRO POI must be recorded before finishing.")
        linked_setups = []
        for operation in operations:
            row, payload = self.publisher.operation(operation)
            if row["status"] != "done":
                return await self.pro_import_screen(
                    u, draft, "Every PRO POI must be recorded before linking.")
            setup_data = payload.get("setup") or {}
            setup = self.db.get("setup:" + str(setup_data.get("id")))
            if (not setup or setup.get("status") != "active" or
                    setup.get("setup_message_id") != row["message_id"] or
                    setup.get("market_analysis_message_id") != draft.get("source_message_id")):
                return await self.pro_import_screen(
                    u, draft, "A PRO POI could not be verified as linked to its source post.")
            linked_setups.append(setup)

        source_key = self.pro_import_source_key(
            draft.get("source_channel"), draft.get("source_message_id"))
        self.db.put(source_key, {
            "status": "done",
            "message_id": draft["source_message_id"],
            "operations": operations,
        })
        self.db.clear_draft(u.effective_user.id)
        return await self.say(
            u,
            f"✅ {len(linked_setups)} PRO POI post(s) published using the existing Market Analysis chart. "
            "The Market Analysis post was not reposted. Each PRO zone is linked for future Zone Tapped replies.",
            [("📍 Zone & Signals", "admin_category", {"category": "zone"}),
             ("↩️ Analysis & Drafts", "admin_category", {"category": "analysis"})],
            admin_chrome=False,
        )

    @staticmethod
    def analysis_bundle_setup_operations(bundle):
        operations = bundle.get("setups")
        if isinstance(operations, list):
            return operations
        legacy = bundle.get("setup")
        return [legacy] if legacy else []

    def analysis_zone_payloads(self, actor, draft):
        if (draft.get("kind") != "analysis" or draft.get("step") not in
                ("ready", "bundle") or draft.get("destination") != "analysis"):
            raise ValueError("Review the Market Analysis and PRO POI before publishing.")
        if not draft.get("text") or not draft.get("image"):
            raise ValueError("The Market Analysis needs its caption and chart.")
        pro_zones = draft.get("pro_zones") or (
            [draft["pro_zone"]] if draft.get("pro_zone") else []
        )
        if not pro_zones:
            raise ValueError("No complete POI was found for the paired PRO post.")
        setup_payloads = []
        for pro_zone in pro_zones:
            if not pro_zone.get("setup") or not pro_zone.get("image"):
                raise ValueError("A PRO POI is missing its setup details or chart.")
            setup = {**pro_zone["setup"], "image": pro_zone["image"]}
            setup_payloads.append({
                "destination": "signals",
                "setup": setup,
                "replaces": pro_zone.get("replaces"),
                "independent": bool(pro_zone.get("independent")),
                "image": pro_zone["image"],
                "original": pro_zone.get("original") or pro_zone["image"],
                "text": zones.setup_caption(setup),
            })
        analysis_payload = {
            key: value for key, value in draft.items()
            if key not in (
                "revision", "pro_zone", "pro_zones", "pro_poi_source",
                "pro_poi_error", "publish_bundle", "step",
            )
        }
        analysis_payload.update(destination="analysis", actor=actor)
        return setup_payloads, analysis_payload

    async def publish_analysis_zone_bundle(self, u, draft):
        if not self.config.allow_publishing:
            if draft.get("publish_bundle"):
                return await self.analysis_zone_bundle_screen(
                    u, draft, "Publishing is OFF. No additional post was sent.")
            return await self.say(
                u, "Publishing is OFF. Neither the Market Analysis nor PRO zone was sent.",
                [("Review Draft", "preview", {}),
                 ("↩️ Analysis & Drafts", "admin_category", {"category": "analysis"})],
                admin_chrome=False,
            )
        user = u.effective_user.id
        draft = self.current(user, "analysis")
        setup_payloads, analysis_payload = self.analysis_zone_payloads(user, draft)
        if not draft.get("publish_bundle"):
            draft["publish_bundle"] = {"setups": []}
            draft["step"] = "bundle"
            self.db.save_draft(user, draft)
        try:
            bundle = draft["publish_bundle"]
            setup_operations = self.analysis_bundle_setup_operations(bundle)
            if len(setup_operations) > len(setup_payloads):
                raise ValueError("The saved POI bundle does not match this review. Reopen the analysis draft.")
            for index in range(len(setup_operations), len(setup_payloads)):
                setup_operation = self.publisher.prepare(
                    user, "setup", setup_payloads[index])
                setup_operations.append(setup_operation)
                bundle["setups"] = setup_operations
                # Keep the first-operation key for resuming older one-zone bundles.
                bundle["setup"] = setup_operations[0]
                self.db.save_draft(user, draft)
            if not bundle.get("analysis"):
                analysis_operation = self.publisher.prepare(
                    user, "analysis", analysis_payload)
                bundle["analysis"] = analysis_operation
                self.db.save_draft(user, draft)
        except ValueError as exc:
            # Preparing an outbox entry has no Telegram side effect. If its pair
            # cannot be prepared, abandon only an unsent prepared entry.
            for setup_operation in self.analysis_bundle_setup_operations(
                    draft.get("publish_bundle") or {}):
                row, _ = self.publisher.operation(setup_operation)
                if row["status"] == "prepared":
                    self.db.execute(
                        "UPDATE operations SET status='abandoned',updated=? WHERE id=?",
                        (now(), setup_operation),
                    )
            draft.pop("publish_bundle", None)
            draft["step"] = "ready"
            self.db.save_draft(user, draft)
            return await self.say(
                u, f"Neither post was sent. The combined review could not be prepared: {exc}",
                [("Review Draft", "preview", {})], admin_chrome=False)
        return await self.continue_analysis_zone_bundle(u, draft)

    async def continue_analysis_zone_bundle(self, u, draft, notice=None):
        bundle = draft.get("publish_bundle") or {}
        setup_operations = self.analysis_bundle_setup_operations(bundle)
        if not setup_operations or not bundle.get("analysis"):
            return await self.analysis_zone_bundle_screen(
                u, draft, notice or "Both post records are not ready; no automatic send was attempted.")
        # Publish the Market Analysis post first. Only after its receipt is
        # recorded do the matching, privately reviewed PRO POI posts follow.
        for operation in [bundle["analysis"], *setup_operations]:
            row, _payload = self.publisher.operation(operation)
            if row["status"] == "done":
                continue
            if row["status"] not in ("prepared", "retryable"):
                return await self.analysis_zone_bundle_screen(
                    u, draft, notice or "A post needs review before the other one can continue.")
            try:
                await self.publisher.send(u.effective_user.id, operation)
            except ValueError as exc:
                return await self.analysis_zone_bundle_screen(u, draft, str(exc))
            row, _payload = self.publisher.operation(operation)
            if row["status"] != "done":
                return await self.analysis_zone_bundle_screen(
                    u, draft, "One post did not complete. Check its operation status before continuing.")
        return await self.finish_analysis_zone_bundle(u, draft)

    async def analysis_zone_bundle_screen(self, u, draft, notice=None):
        bundle = draft.get("publish_bundle") or {}
        setup_operations = self.analysis_bundle_setup_operations(bundle)
        multiple = len(setup_operations) > 1
        lines = ["📤 MARKET ANALYSIS + PRO POI\n"]
        buttons = []
        all_done = bool(setup_operations and bundle.get("analysis"))
        has_failed = False
        has_uncertain = False
        has_resumable = False
        for index, operation in enumerate(setup_operations):
            label = f"PRO POI {index + 1}" if multiple else "PRO Signals POI"
            row, payload = self.publisher.operation(operation)
            setup = payload.get("setup") or {}
            direction = setup.get("poi_direction")
            suffix = f" ({direction})" if direction in ("BUY", "SELL") else ""
            lines.append(
                f"{label}{suffix}: {row['status'].replace('_', ' ').title()}"
            )
            if row["status"] != "done":
                all_done = False
            if row["status"] == "failed":
                has_failed = True
                buttons.append((
                    f"Retry rejected {label}",
                    "analysis_zone_retry",
                    {"operation_kind": f"setup:{index}"},
                ))
            elif row["status"] in ("uncertain", "sending"):
                has_uncertain = True
                buttons.append((f"Review {label} operation", "operation",
                                {"id": operation}))
            elif row["status"] in ("prepared", "retryable"):
                has_resumable = True
                buttons.append((f"Review {label} operation", "operation",
                                {"id": operation}))
            elif row["status"] == "abandoned":
                has_failed = True
                buttons.append((
                    f"Create new {label} operation",
                    "analysis_zone_retry",
                    {"operation_kind": f"setup:{index}"},
                ))
        analysis_operation = bundle.get("analysis")
        if analysis_operation:
            row, _payload = self.publisher.operation(analysis_operation)
            lines.append(
                f"Market Analysis: {row['status'].replace('_', ' ').title()}"
            )
            if row["status"] != "done":
                all_done = False
            if row["status"] == "failed":
                has_failed = True
                buttons.append((
                    "Retry rejected Market Analysis post",
                    "analysis_zone_retry",
                    {"operation_kind": "analysis"},
                ))
            elif row["status"] in ("uncertain", "sending"):
                has_uncertain = True
                buttons.append(("Review Market Analysis operation", "operation",
                                {"id": analysis_operation}))
            elif row["status"] in ("prepared", "retryable"):
                has_resumable = True
                buttons.append(("Review Market Analysis operation", "operation",
                                {"id": analysis_operation}))
            elif row["status"] == "abandoned":
                has_failed = True
                buttons.append((
                    "Create new Market Analysis operation",
                    "analysis_zone_retry",
                    {"operation_kind": "analysis"},
                ))
        else:
            lines.append("Market Analysis: not prepared")
            all_done = False

        if notice:
            lines.extend(["", notice])
        if all_done:
            buttons.append(("Finish and link all posts", "analysis_zone_finish", {}))
        elif not has_failed and not has_uncertain and has_resumable:
            buttons.append(("Continue publishing remaining posts", "analysis_zone_publish", {}))
        buttons.append(("↩️ Admin Menu", "menu", {}))
        return await self.say(
            u, "\n".join(lines) +
               "\n\nMarket Analysis is sent first. PRO POI posts follow only after it is recorded.",
            buttons, admin_chrome=False)

    async def retry_analysis_zone_operation(self, u, draft, operation_kind):
        if operation_kind == "analysis":
            target = "analysis"
        elif operation_kind == "setup":
            target = 0
        elif isinstance(operation_kind, str) and operation_kind.startswith("setup:"):
            try:
                target = int(operation_kind.split(":", 1)[1])
            except ValueError:
                raise ValueError("Choose a valid PRO POI post to retry.") from None
        else:
            raise ValueError("Choose the rejected post to retry.")
        bundle = draft.get("publish_bundle") or {}
        setup_operations = self.analysis_bundle_setup_operations(bundle)
        operation = bundle.get("analysis") if target == "analysis" else (
            setup_operations[target] if 0 <= target < len(setup_operations) else None
        )
        if not operation:
            raise ValueError("That publishing operation is not available.")
        row, payload = self.publisher.operation(operation)
        if row["status"] not in ("failed", "abandoned"):
            raise ValueError("Only a rejected or explicitly abandoned post can be replaced with a new operation.")
        new_operation = self.publisher.prepare(
            u.effective_user.id, row["kind"], payload)
        if target == "analysis":
            bundle["analysis"] = new_operation
        else:
            setup_operations[target] = new_operation
            bundle["setups"] = setup_operations
            bundle["setup"] = setup_operations[0]
        draft["publish_bundle"] = bundle
        draft["step"] = "bundle"
        self.db.save_draft(u.effective_user.id, draft)
        return await self.continue_analysis_zone_bundle(u, draft)

    async def finish_analysis_zone_bundle(self, u, draft):
        bundle = draft.get("publish_bundle") or {}
        setup_operations = self.analysis_bundle_setup_operations(bundle)
        if not setup_operations or not bundle.get("analysis"):
            raise ValueError("The PRO POI and Market Analysis operations are not all recorded.")
        analysis_row, _analysis_payload = self.publisher.operation(bundle["analysis"])
        setup_records = []
        for operation in setup_operations:
            setup_row, setup_payload = self.publisher.operation(operation)
            if setup_row["status"] != "done":
                return await self.analysis_zone_bundle_screen(
                    u, draft, "Every PRO POI and the Market Analysis post must be recorded before linking.")
            setup = setup_payload.get("setup") or {}
            stored = self.db.get("setup:" + str(setup.get("id")))
            if (not stored or stored.get("status") != "active" or
                    stored.get("setup_message_id") != setup_row["message_id"]):
                return await self.analysis_zone_bundle_screen(
                    u, draft, "A PRO POI setup changed before linking. Review its saved status.")
            setup_records.append((setup_row, setup_payload, stored))
        if analysis_row["status"] != "done":
            return await self.analysis_zone_bundle_screen(
                u, draft, "Every PRO POI and the Market Analysis post must be recorded before linking.")

        analysis_message_id = analysis_row["message_id"]
        with self.db.transaction() as connection:
            for _setup_row, setup_payload, setup in setup_records:
                setup.update(
                    market_analysis_message_id=analysis_message_id,
                    market_analysis_operation_id=bundle["analysis"],
                )
                zones.save_in(connection, setup)

        self.db.clear_draft(u.effective_user.id)
        notice = (
            f"✅ {len(setup_records)} PRO POI post(s) + the Market Analysis post published. "
            "The posts are linked for future Zone Tapped replies. No signal or trade entry was sent."
        )
        for _setup_row, setup_payload, _stored in setup_records:
            replaces = setup_payload.get("replaces")
            if not replaces:
                continue
            old_setup = self.db.get("setup:" + str(replaces))
            if old_setup and not await self.update_setup_post(old_setup):
                notice += " The previous zone post could not be refreshed; check PRO Signals."
        return await self.menu(u, notice)

    async def trades(self, u, p):
        page = p.get("page", 0)
        rows = self.db.rows("SELECT id FROM trades WHERE state IN ('ACTIVE','CONFIRMED_BUY','CONFIRMED_SELL') "
                            "ORDER BY created DESC LIMIT 9 OFFSET ?", (page*8,))
        buttons = []
        lines = []
        for row in rows[:8]:
            t = self.db.trade(row["id"])
            lines.append(f"#{t['id']} · {t['symbol']} {t['direction']} · {t['state'].replace('_', ' ').title()}\n"
                         f"Entry: {t.get('entry','not set')} · Stop loss: {t.get('sl','not set')}\n"
                         f"Targets: {format_targets(t.get('targets', {}))}")
            buttons.append((f"{t['symbol']} {t['direction']} #{t['id']}", "manage" if p.get("action") else "trade",
                            {"id": t["id"], "action": p.get("action")}))
        if page:
            buttons.append(("Previous", "trades", {**p, "page": page-1}))
        if len(rows) > 8:
            buttons.append(("Next", "trades", {**p, "page": page+1}))
        await self.say(u, "📋 Active trades\n\n" + ("\n\n".join(lines) or "There are no open trades yet."), buttons)

    async def trade_screen(self, u, trade_id, notice=None):
        t = self.db.trade(trade_id)
        text = (f"📊 Trade #{t['id']} · {t['symbol']} · {t['direction']}\n\n"
                f"Status: {t['state'].replace('_', ' ').title()}\n"
                f"Entry: {t.get('entry', 'not set')}\n"
                f"Stop loss: {t.get('sl', 'not set')}\n"
                f"Take-profit targets: {format_targets(t.get('targets', {}))}")
        if notice:
            text = notice + "\n\n" + text
        open_trade = t["state"] in ("ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL")
        next_target = self.next_automatic_tp(t) if open_trade else None
        if next_target:
            text += (
                f"\n\n🔐 Next automatic TP (private): TP{next_target['number']} · "
                f"{next_target['price']} ({next_target['pips']} pips from entry). "
                "It stays private until you add and review it."
            )
        screenshot_records = target_profit_screenshots(t)
        for number, screenshot_record in sorted(
                screenshot_records.items(), key=lambda item: int(item[0])):
            pips = saved_screenshot_pips(t, screenshot_record)
            result_label = (
                f"+{pips} pips"
                if pips is not None else
                f"+{screenshot_record.get('price_movement', 'unknown')} price units "
                "(pip size not configured)"
            )
            text += f"\n\n✅ TP{number} profit screenshot posted · {result_label}."
        next_screenshot_target = (
            next_target_profit_screenshot(
                t, max_targets=zones.AUTOMATIC_TP_MAX_TARGETS)
            if open_trade and t.get("message_id") and not t.get("levels_pending")
            else None
        )
        rows = []
        if open_trade:
            if t.get("levels_pending"):
                market = t.get("market") or t.get("symbol")
                label = (f"📍 Set {t['direction'].title()} Entry, SL & Auto TP1–TP4"
                         if zones.automatic_tp1_pip_size(market) is not None
                         else f"📍 Set {t['direction'].title()} Range, SL & TP")
                rows = [
                    [(label, "manage",
                      {"id": trade_id, "action": "entry"})],
                    [("🚫 Cancel / Invalidate Setup", "manage",
                      {"id": trade_id, "action": "cancel"})],
                ]
            else:
                rows = [
                    [("🛡️ Set SL + TP together", "manage", {"id": trade_id, "action": "sl_tp"})],
                    [("💰 Partial Profit", "manage", {"id": trade_id, "action": "partial"}),
                     ("🔒 Move to BE", "manage", {"id": trade_id, "action": "be"})],
                    *([[(f"📸 Post TP{next_screenshot_target} Profit Screenshot", "manage",
                          {"id": trade_id, "action": "tp1_profit_screenshot",
                           "target_number": next_screenshot_target})]]
                      if next_screenshot_target else []),
                    [("📈 Trailing SL", "manage", {"id": trade_id, "action": "trail"}),
                     ("🏁 Close Trade", "manage", {"id": trade_id, "action": "close"})],
                    [("🚫 Cancel / Invalidate Setup", "manage",
                      {"id": trade_id, "action": "invalidate" if t["state"] == "ACTIVE" else "cancel"})],
                ]
        if next_target:
            rows.insert(0, [(
                f"➕ Add TP{next_target['number']} · {next_target['price']}",
                "auto_tp_next",
                {"id": trade_id, "version": t["version"]},
            )])
        if t.get("message_id") and not t.get("levels_pending"):
            _trade, result_record = self._result_record(trade_id)
            if result_record.get("status") == "posted":
                rows.append([
                    ("📸 Capture Signal Screenshot", "signal_result_capture",
                     {"trade_id": trade_id, "updated": result_record["updated"]}),
                    ("✅ View Published Result", "signal_result_open", {"trade_id": trade_id}),
                ])
            else:
                rows.append([
                    ("📸 Capture Signal Screenshot", "signal_result_capture",
                     {"trade_id": trade_id, "updated": result_record["updated"]}),
                    ("📤 Post Result to Market Analysis Group", "signal_result_confirm_screen",
                     {"trade_id": trade_id, "updated": result_record["updated"]}),
                ])
        rows.append([("📋 Trade Details", "trade_details", {"id": trade_id}),
                     ("↩️ Back to Admin", "menu", {})])
        await self.say_rows(u, text, rows)

    async def trade_details(self, u, trade_id):
        t = self.db.trade(trade_id)
        text = (f"📋 Trade details · #{t['id']}\n{t['symbol']} · {t['market']} · {t['direction']}\n\n"
                f"Status: {t['state'].replace('_', ' ').title()}\nEntry: {t.get('entry', 'not set')}\n"
                f"Stop loss: {t.get('sl', 'not set')}\nTake-profit targets: {format_targets(t.get('targets', {}))}\n"
                f"Setup post: #{t.get('setup_message_id', 'not recorded')}\n"
                f"Signal post: #{t.get('message_id', 'not recorded')}\nCreated: {t['created']}")
        screenshot_records = target_profit_screenshots(t)
        if screenshot_records:
            text += "\n\nProfit screenshots:"
            for number, record in sorted(
                    screenshot_records.items(), key=lambda item: int(item[0])):
                pips = saved_screenshot_pips(t, record)
                result_label = (
                    f"+{pips} pips" if pips is not None else
                    f"+{record.get('price_movement', 'unknown')} price units"
                )
                text += f"\nTP{number}: {result_label}"
        next_target = self.next_automatic_tp(t)
        if next_target:
            text += (
                f"\n\n🔐 Next automatic TP (private): TP{next_target['number']} · "
                f"{next_target['price']} ({next_target['pips']} pips from entry)."
            )
        rows = []
        if t["state"] in ("ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL"):
            if t.get("levels_pending"):
                market = t.get("market") or t.get("symbol")
                label = (f"📍 Set {t['direction'].title()} Entry, SL & Auto TP1"
                         if zones.automatic_tp1_pip_size(market) is not None
                         else f"📍 Set {t['direction'].title()} Range, SL & TP")
                rows = [[(label, "manage",
                          {"id": trade_id, "action": "entry"})]]
            else:
                rows = [
                    [("🛡️ Update SL", "manage", {"id": trade_id, "action": "sl"}),
                     ("🎯 Update TP", "manage", {"id": trade_id, "action": "tp"})],
                    [("Add Entry", "manage", {"id": trade_id, "action": "entry"}),
                     ("TP Hit", "manage", {"id": trade_id, "action": "hit"})],
                    [("Custom Trade Update", "manage", {"id": trade_id, "action": "custom"}),
                     ("Edit Original Signal", "manage", {"id": trade_id, "action": "edit"})],
                ]
        if next_target and not t.get("levels_pending"):
            rows.insert(0, [(
                f"➕ Add TP{next_target['number']} · {next_target['price']}",
                "auto_tp_next",
                {"id": trade_id, "version": t["version"]},
            )])
        rows.extend([
            [("Full Timeline", "timeline", {"id": trade_id}),
             ("Back to Trade", "trade", {"id": trade_id})],
            [("↩️ Back to Admin", "menu", {})],
        ])
        await self.say_rows(u, text, rows)

    async def history(self, u, p):
        filters, page = p.get("filters", {}), p.get("page", 0)
        clauses, args = [], []
        for key, field in (("market", "json_extract(data,'$.market')"), ("direction", "json_extract(data,'$.direction')"), ("status", "state")):
            if key in filters:
                clauses.append(f"{field}=?")
                args.append(filters[key])
        for key, operator in (("from", ">="), ("to", "<=")):
            if key in filters:
                clauses.append(f"substr(created,1,10){operator}?")
                args.append(filters[key])
        sql = "SELECT id FROM trades" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        rows = self.db.rows(sql + " ORDER BY created DESC LIMIT 9 OFFSET ?", (*args, page*8))
        buttons = [("Set / Clear Filters", "history_filter", {})]
        for row in rows[:8]:
            t = self.db.trade(row["id"])
            buttons.append((f"{t['symbol']} {t['direction']} {t['state']} #{t['id']}", "trade", {"id": t["id"]}))
        if page:
            buttons.append(("Previous", "history", {**p, "page": page-1}))
        if len(rows) > 8:
            buttons.append(("Next", "history", {**p, "page": page+1}))
        active_filters = ", ".join(f"{key}={value}" for key, value in filters.items()) or "none"
        await self.say(u, "📚 Trade history\nFilters: " + active_filters +
                       ("\n\nNo trades match these filters." if not rows else ""), buttons)

    async def trade_statistics(self, u):
        rows = self.db.rows(
            "SELECT id,data,state,created,updated FROM trades ORDER BY created DESC")
        text = format_trade_statistics(rows)
        await self.say(u, text, [
            ("🔄 Refresh Statistics", "trade_stats", {}),
            ("📚 Trade History", "history", {}),
            ("↩️ Trade Management", "admin_category", {"category": "trades"}),
        ])

    async def timeline(self, u, trade_id, page=0):
        rows = self.db.rows("SELECT * FROM events WHERE trade_id=? ORDER BY id LIMIT 2 OFFSET ?", (trade_id, page))
        buttons = [("Back to Trade", "trade", {"id": trade_id})]
        if page:
            buttons.append(("Previous event", "timeline", {"id": trade_id, "page": page-1}))
        if len(rows) > 1:
            buttons.append(("Next event", "timeline", {"id": trade_id, "page": page+1}))
        r = rows[0] if rows else None
        await self.say(u, f"🧾 Trade timeline · #{trade_id}\n\n" +
                       (f"{r['created']} · administrator {r['actor']} · message {r['message_id']}\n\n{r['text']}"
                        if r else "No published events are recorded yet."), buttons)

    async def operations(self, u, page=0):
        rows = self.db.rows("SELECT id,status,kind FROM operations ORDER BY created DESC LIMIT 9 OFFSET ?", (page*8,))
        buttons = [(f"{r['kind']} · {r['status']} · {r['id']}", "operation", {"id": r["id"]}) for r in rows[:8]]
        if page:
            buttons.append(("Previous", "operations", {"page": page-1}))
        if len(rows) > 8:
            buttons.append(("Next", "operations", {"page": page+1}))
        await self.say(u, "🔄 Publishing operations\n\n"
                       "If a send result is uncertain, check the destination channel before reconciling. "
                       "The bot will not automatically repost it.", buttons)

    async def operation_screen(self, u, op):
        references_removed = self.publisher.sanitize_pending_operation(op)
        row, p = self.publisher.operation(op)
        text = (f"🔄 Operation {op}\nType: {row['kind'].replace('_', ' ').title()}\n"
                f"Status: {row['status'].replace('_', ' ').title()}\n\n"
                + ("Internal references were removed from this saved draft. Review the clean channel copy below before sending.\n\n"
                   if references_removed else "")
                + f"{p.get('text') or ('No public message content remains. Abandon this operation and create a new clean draft.' if row['kind'] != 'invite' else 'Member invite')}")
        buttons = []
        if row["status"] in ("prepared", "retryable") and (row["kind"] == "invite" or p.get("text")):
            buttons.append(("Confirm safe retry / send", "retry", {"id": op}))
        if row["status"] == "uncertain" and row["kind"] != "invite":
            buttons.append(("Reconcile existing channel message", "reconcile", {"id": op}))
        if row["status"] not in ("done", "sending", "abandoned"):
            buttons.append(("Abandon without reposting", "abandon", {"id": op}))
        await self.say(u, text, buttons)

    async def operation_result(self, u, op, text):
        row, p = self.publisher.operation(op)
        buttons = [("View operation", "operation", {"id": op})]
        setup_caption_updated = True
        if row["kind"] == "signal" and p.get("setup_id"):
            setup = self.db.get("setup:" + str(p["setup_id"]))
            setup_caption_updated = await self.update_setup_post(setup)
        if row["kind"] == "setup" and row["status"] == "done" and p.get("replaces"):
            replaced = self.db.get("setup:" + str(p["replaces"]))
            if replaced and not await self.update_setup_post(replaced):
                text += " The previous zone post status could not be updated; check PRO Signals."
        if row["status"] == "done":
            completed_labels = {
                "setup": "Zone and chart",
                "signal": "Signal",
                "analysis": "Market analysis",
                "update": "Trade update",
                "edit": "Original signal edit",
                "invite": "Member invite",
            }
            text = f"✅ {completed_labels.get(row['kind'], 'Action')} completed and recorded."
            draft = self.db.draft(u.effective_user.id)
            if draft and draft.get("operation") == op:
                self.db.clear_draft(u.effective_user.id)
            if row["kind"] == "invite":
                result = self.db.get(f"invite:{op}")
                destination = dict(self.access_destinations()).get(p.get("channel"), "access")
                if result and result.get("previous_invite_revoked") is False:
                    if p.get("channel") == self.config.education_group_id:
                        text += (" A previous direct-join invite could not be revoked and may still work until "
                                 "used or expired. Review it in Telegram.")
                    else:
                        text += (" A previous invite could not be revoked. Requests using older links will be "
                                 "rejected; review this destination in Telegram.")
                try:
                    if p.get("channel") == self.config.education_group_id:
                        invite_text = (f"🎟️ Your 24-hour {escape(destination)} direct-join invite "
                                       f"(one use):\n\n{escape(result['invite_link'])}\n\n"
                                       "Tap to join the group directly. This link works for one account, "
                                       "expires in 24 hours, and must not be forwarded.")
                    else:
                        invite_text = (f"🎟️ Your 24-hour {escape(destination)} join-request invite:\n\n"
                                       f"{escape(result['invite_link'])}\n\n"
                                       "Open it and request to join before it expires.")
                    if p.get("channel") == self.config.signals:
                        invite_text = "<b>🎟️ PRO SIGNALS INVITATION</b>\n\n" + invite_text
                        invite_text += "\n\n" + PRO_ACCESS_REMINDER
                        await self.bot.send_message(p["user"], invite_text, parse_mode="HTML")
                    else:
                        await self.bot.send_message(p["user"], invite_text)
                except Exception:
                    text += " Member delivery failed; they can retrieve their invite from My Access / Status."
            if p.get("trade"):
                buttons.append(("Manage Trade", "trade", {"id": p["trade"]["id"]}))
        elif row["status"] == "uncertain":
            text = ("⚠️ Telegram’s result is uncertain. Inspect the destination before reconciling. "
                    "Do not retry unless the Operations screen marks it safe.")
        elif row["status"] == "failed":
            text = "⚠️ Telegram rejected this action. Check channel permissions and content; it was not reposted."
        if row["kind"] == "signal" and not setup_caption_updated:
            text += " The original zone post status could not be updated; check PRO Signals."
        if (row["status"] == "done" and row["kind"] == "update" and
                p.get("action") == "tp1_profit_screenshot" and p.get("trade")):
            number = int(p.get("target_number", 1))
            result = (
                f"+{p['pips']} pips" if p.get("pips") is not None else
                f"+{p.get('price_movement', 'unknown')} price units"
            )
            return await self.trade_screen(
                u, p["trade"]["id"],
                notice=f"✅ TP{number} profit screenshot posted · {result}.")
        await self.say(u, text, buttons)

    async def health_screen(self, u):
        report = await self.health.check()
        await self.say(u, "🩺 Service health\n\n" + "\n".join(f"{k}: {v}" for k, v in report.items()))

    def _save_channel_history(self, update, message, destination, event_type):
        # History capture is deliberately isolated to the private test bot.
        # It stores message text/captions and attachment labels only—never files,
        # Telegram file IDs, private conversations, or member group traffic.
        if not self.config.isolated_test:
            return
        update_id = getattr(update, "update_id", None)
        chat = getattr(message, "chat", None)
        message_id = getattr(message, "message_id", None)
        if update_id is None or chat is None or message_id is None:
            return
        attachment_label = "No attachment"
        for field, label in (
            ("photo", "Photo attached"), ("video", "Video attached"),
            ("animation", "Animation attached"), ("document", "File attached"),
            ("audio", "Audio attached"), ("voice", "Voice message attached"),
            ("sticker", "Sticker attached"),
        ):
            if getattr(message, field, None):
                attachment_label = label
                break
        message_text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        created = getattr(message, "date", None)
        recorded_at = created.isoformat() if hasattr(created, "isoformat") else now()
        try:
            self.db.execute(
                "INSERT INTO channel_history "
                "(update_id,chat_id,message_id,destination,event_type,message_text,attachment_label,recorded_at) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(update_id) DO NOTHING",
                (int(update_id), int(chat.id), int(message_id), destination, event_type,
                 str(message_text), attachment_label, recorded_at),
            )
        except Exception:
            # Do not let an optional history write block Telegram update polling.
            try:
                self.db.error("channel_history_capture_failed",
                              "An isolated channel-history record could not be saved.")
            except Exception:
                logger.warning("channel_history_capture_failed")

    def record_education_topic_post(self, update, context):
        if not self.config.isolated_test:
            return
        message = getattr(update, "effective_message", None)
        chat = getattr(update, "effective_chat", None)
        if (message is None or chat is None or
                chat.id != self.config.education_video_group_id or
                getattr(message, "message_thread_id", None) != self.config.education_video_topic_id):
            return
        sender = getattr(message, "from_user", None)
        sender_chat = getattr(message, "sender_chat", None)
        if not ((sender and sender.id == self.config.admin) or
                (sender_chat and sender_chat.id == self.config.education_video_group_id)):
            return
        self._save_channel_history(
            update, message, "Educational Group · Video tutorials", "posted")

    async def discover_channel(self, u, context):
        message = getattr(u, "effective_message", None)
        chat = getattr(u, "effective_chat", None)
        if message and chat and chat.type == "channel":
            destination = ("PRO Signals" if chat.id == self.config.signals else
                           "Market Analysis" if chat.id == self.config.analysis else None)
            if destination:
                event_type = "edited" if getattr(u, "edited_channel_post", None) else "posted"
                self._save_channel_history(u, message, destination, event_type)
        chat = u.effective_chat
        if chat.type != "channel":
            return
        channels = self.db.get("channels", [])
        if chat.id not in channels:
            self.db.put("channels", (channels + [chat.id])[-20:])
        if self.config.admin and u.channel_post and u.channel_post.text == "/channelid":
            await self.bot.send_message(self.config.admin, f"Channel discovery:\n{chat.title}\nID: {chat.id}\n"
                                        "Configure the appropriate channel Secret, then restart.")
