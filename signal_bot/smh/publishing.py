"""Durable outbox. Ambiguous sends are NEVER automatically replayed."""
import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from telegram import ReplyParameters
from telegram.error import BadRequest, Forbidden, InvalidToken, NetworkError, RetryAfter
from .database import uid, now
from .domain import validate_analysis, safe_text, OPEN_STATES
from .images import as_document
from .profit_screenshot import (
    calculate_trade_result,
    next_target_profit_screenshot,
    target_profit_screenshots,
    validate_target_exit,
)
from . import zones


_PUBLIC_REFERENCE_PATTERNS = (
    re.compile(r"(?im)^\s*(?:trade|setup|operation|database|db|message|chat|channel)\s*[_ ]?ids?\s*[:=].*$"),
    re.compile(r"(?im)^\s*(?:trade|setup|operation|database|db)\s*#\s*\S+.*$"),
    re.compile(r"(?im)^\s*operation\s*[:=]\s*\S+.*$"),
    re.compile(r"(?im)^\s*(?:original\s+(?:channel\s+)?post|signal\s+post)\s*#\s*\S+.*$"),
    re.compile(r"(?im)^\s*(?:debug|internal)\b.*$"),
    re.compile(r"(?im)^\s*(?:trade|setup)\s+(?:[0-9a-f-]{8,}|[A-Za-z0-9_-]{12,})\s*$"),
    re.compile(r"(?im)^\s*operation(?:\s+id)?\s*[:#]?\s*(?:\d{3,}|[0-9a-f]{8,}(?:-[0-9a-f]{4,})*)\s*$"),
)
_PUBLIC_REFERENCE_INLINE_PATTERNS = (
    re.compile(r"\b(?:trade|setup|operation|database|db|message|chat|channel)\s*[_ ]?ids?\s*[:=]\s*#?[A-Za-z0-9_-]+\b", re.I),
    re.compile(r"\b(?:trade|setup|operation|database|db)\s*#\s*[A-Za-z0-9_-]+\b", re.I),
    re.compile(r"\boperation\s*[:=]\s*[A-Za-z0-9_-]{6,}\b", re.I),
    re.compile(r"\b(?:original\s+(?:channel\s+)?post|signal\s+post)\s*#\s*\S+", re.I),
    re.compile(r"\boperation(?:\s+id)?\s*[:#]?\s*(?:\d{3,}|[0-9a-f]{8,}(?:-[0-9a-f]{4,})*)\b", re.I),
    re.compile(r"\b(?:ref|reference)\s*(?:(?:id|no\.?|number)\s*)?(?:[:#]\s*|(?:id|no\.?|number)\s+)#?[A-Za-z0-9_-]+\b", re.I),
    re.compile(r"(?<!\w)#(?:SMH|VAYDA)[-_][A-Za-z0-9_-]{4,}", re.I),
    re.compile(r"(?<!\w)#\d{3,}\b"),
)


def clean_channel_text(text, internal_ids=()):
    """Remove bot-internal references from channel copy, retaining the IDs in storage."""
    cleaned = str(text or "")
    for pattern in _PUBLIC_REFERENCE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    for pattern in _PUBLIC_REFERENCE_INLINE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    for internal_id in internal_ids:
        value = str(internal_id or "").strip()
        if len(value) >= 6:
            cleaned = re.sub(
                rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9_-])",
                "",
                cleaned,
            )
    lines = [line.rstrip() for line in cleaned.splitlines()]
    result = re.sub(r"\n(?:[ \t]*\n){2,}", "\n\n", "\n".join(lines))
    return result.strip()


def _active_replacement_id(setup):
    """Return the setup ID only while that setup is active and still valid."""
    if not setup or setup.get("status") != "active":
        return None
    if not setup.get("id"):
        raise ValueError("The active setup ID is unavailable. Review its saved status first.")
    return setup["id"] if not zones.is_expired(setup) else None


def _validate_setup_publish_state(db, payload):
    """Keep replacement explicit while allowing separately keyed active zones."""
    replaces = payload.get("replaces")
    if replaces:
        try:
            zones.active(db, replaces)
        except ValueError as exc:
            raise ValueError(
                "Active setup changed. Review the replacement against the current zone."
            ) from exc
        return
    if payload.get("independent"):
        return
    if zones.active_setups(db):
        raise ValueError(
            "An active zone already exists. Choose an explicit replacement or add an independent zone."
        )


class DestinationVerificationError(ValueError):
    """A safe, stable category for a failed read-only destination check."""

    def __init__(self, category, message):
        self.category = category
        super().__init__(message)


async def verify_configured_destinations(bot, config):
    """Verify identities and channel permissions without sending or polling."""
    result = await verify_configured_destinations_detailed(bot, config)
    if not result["administrator"]["identity_ok"]:
        raise DestinationVerificationError(
            result["administrator"]["category"] or "admin_identity_mismatch",
            "Administrator identity is not the configured private Telegram user.",
        )
    for name in ("signals", "analysis"):
        channel = result[name]
        if channel["category"]:
            messages = {
                "configuration_incomplete": "Configure administrator and both channels.",
                "destination_mismatch": "Configured destination is not the expected channel.",
                "test_destination_not_private": "Isolated test destinations must be private Telegram channels.",
                "admin_channel_permissions": "Administrator must administer both channels.",
                "bot_channel_permissions": "Bot channel permissions are incomplete.",
            }
            raise DestinationVerificationError(channel["category"], messages.get(
                channel["category"], "Telegram destination verification failed."
            ))


def _verification_error_category(exc):
    if isinstance(exc, InvalidToken):
        return "invalid_token"
    if isinstance(exc, Forbidden):
        return "telegram_forbidden"
    if isinstance(exc, BadRequest):
        return "telegram_bad_request"
    if isinstance(exc, NetworkError):
        return "telegram_network_error"
    return "telegram_validation_error"


async def verify_configured_destinations_detailed(bot, config):
    """Return separate read-only verification results for admin and each channel."""
    result = {
        "administrator": {"ok": False, "identity_ok": False, "channel_admin_ok": False,
                          "category": None},
        "signals": {"ok": False, "destination_ok": False, "admin_ok": False, "bot_ok": False,
                    "destination_category": None, "admin_category": None, "bot_category": None,
                    "category": None},
        "analysis": {"ok": False, "destination_ok": False, "admin_ok": False, "bot_ok": False,
                     "destination_category": None, "admin_category": None, "bot_category": None,
                     "category": None},
    }

    if not config.admin:
        result["administrator"].update(category="configuration_incomplete")
    else:
        try:
            admin_chat = await bot.get_chat(config.admin)
            result["administrator"]["identity_ok"] = (
                admin_chat.id == config.admin and admin_chat.type == "private"
            )
            if not result["administrator"]["identity_ok"]:
                result["administrator"]["category"] = "admin_identity_mismatch"
        except Exception as exc:
            result["administrator"]["category"] = _verification_error_category(exc)

    bot_id = None
    try:
        bot_id = (await bot.get_me()).id
    except Exception as exc:
        bot_error = _verification_error_category(exc)
    else:
        bot_error = None

    for name, channel_id in (("signals", config.signals), ("analysis", config.analysis)):
        status = result[name]
        if not channel_id:
            status["destination_category"] = "configuration_incomplete"
            status["category"] = status["destination_category"]
            continue
        try:
            chat = await bot.get_chat(channel_id)
        except Exception as exc:
            status["destination_category"] = _verification_error_category(exc)
            status["category"] = status["destination_category"]
            continue
        if chat.id != channel_id or chat.type != "channel":
            status["destination_category"] = "destination_mismatch"
            status["category"] = status["destination_category"]
            continue
        if config.isolated_test and getattr(chat, "username", None):
            status["destination_category"] = "test_destination_not_private"
            status["category"] = status["destination_category"]
            continue
        status["destination_ok"] = True

        if result["administrator"]["identity_ok"]:
            try:
                admin_member = await bot.get_chat_member(channel_id, config.admin)
                status["admin_ok"] = admin_member.status in ("creator", "administrator")
            except Exception as exc:
                status["admin_category"] = _verification_error_category(exc)
        if not status["admin_ok"] and not status["admin_category"]:
            status["admin_category"] = (
                "admin_channel_permissions" if result["administrator"]["identity_ok"]
                else result["administrator"]["category"] or "admin_identity_mismatch"
            )

        if bot_id is None:
            status["bot_category"] = bot_error or "telegram_validation_error"
        else:
            try:
                bot_member = await bot.get_chat_member(channel_id, bot_id)
                status["bot_ok"] = (
                    bot_member.status == "creator" or
                    bot_member.status == "administrator" and all(
                        getattr(bot_member, key, False)
                        for key in ("can_post_messages", "can_edit_messages", "can_invite_users")
                    )
                )
            except Exception as exc:
                status["bot_category"] = _verification_error_category(exc)
        if not status["bot_ok"] and not status["bot_category"]:
            status["bot_category"] = "bot_channel_permissions"
        status["category"] = (
            status["destination_category"] or status["admin_category"] or status["bot_category"]
        )
        status["ok"] = (
            status["destination_ok"] and status["admin_ok"] and status["bot_ok"] and
            not status["category"]
        )

    admin_channel_ok = all(
        result[name]["admin_ok"] and not result[name]["destination_category"]
        for name in ("signals", "analysis")
    )
    result["administrator"]["channel_admin_ok"] = admin_channel_ok
    result["administrator"]["ok"] = (
        result["administrator"]["identity_ok"] and admin_channel_ok
    )
    if not result["administrator"]["category"] and not admin_channel_ok:
        result["administrator"]["category"] = "admin_channel_permissions"
    return result


class Publisher:
    def __init__(self, db, config, bot):
        self.db, self.config, self.bot = db, config, bot
        self.lock = asyncio.Lock()
        self.journal = db.directory / "receipts.jsonl"
        self.verified = False

    async def verify_destinations(self):
        self.verified = False
        await verify_configured_destinations(self.bot, self.config)
        self.verified = True

    async def verify_education_group(self):
        group_id = self.config.education_group_id
        if not group_id:
            raise ValueError("Configure EDUCATION_GROUP_ID before issuing Education Group access.")
        chat = await self.bot.get_chat(group_id)
        if chat.id != group_id or chat.type not in ("group", "supergroup"):
            raise ValueError("EDUCATION_GROUP_ID must identify a Telegram group.")
        if self.config.isolated_test and getattr(chat, "username", None):
            raise ValueError("The isolated test Education Group must be private.")
        me = await self.bot.get_me()
        admin = await self.bot.get_chat_member(group_id, self.config.admin)
        member = await self.bot.get_chat_member(group_id, me.id)
        if admin.status not in ("creator", "administrator"):
            raise ValueError("The configured administrator must administer the Education Group.")
        if (member.status != "creator" and
                (member.status != "administrator" or not getattr(member, "can_invite_users", False))):
            raise ValueError("The bot must be an administrator with Invite Users permission in the Education Group.")

    def invite_authorized(self, user_id, channel):
        destination = ("pro" if channel == self.config.signals else
                       "analysis" if channel == self.config.analysis else
                       "education" if channel == self.config.education_group_id else None)
        if destination is None:
            return False
        access = self.db.rows(
            "SELECT status FROM access WHERE user_id=? AND channel=?",
            (user_id, channel))
        if access and access[0]["status"] in ("disapproval_pending", "access_revoked"):
            return False
        if destination == "pro":
            return bool(self.db.rows(
                "SELECT id FROM member_requests WHERE user_id=? AND destination='pro' AND status='approved' "
                "AND registration_status IN ('approved','verified') AND funding_status='verified' LIMIT 1",
                (user_id,)))
        if destination not in ("analysis", "education"):
            return False
        legacy = self.db.rows("SELECT status FROM applications WHERE user_id=?", (user_id,))
        request = self.db.rows(
            "SELECT id FROM member_requests WHERE user_id=? AND destination=? AND status='approved' LIMIT 1",
            (user_id, destination))
        return bool((legacy and legacy[0]["status"] == "approved") or request)

    def is_self_service_education_operation(self, actor, kind, payload):
        return bool(
            kind == "invite" and
            payload.get("self_service_education") is True and
            actor == payload.get("user") and
            payload.get("actor", actor) == actor and
            self.config.education_group_id and
            payload.get("channel") == self.config.education_group_id
        )

    def prepare(self, actor, kind, payload):
        if not self.is_self_service_education_operation(actor, kind, payload):
            self.config.authorize(actor)
        payload = {**payload, "actor": actor}
        if kind not in ("signal", "setup", "update", "analysis", "edit", "invite"):
            raise ValueError("Unknown operation.")
        if kind != "invite":
            payload["channel"] = self.config.destination(kind, payload.get("destination"))
            internal_ids = [payload.get("setup_id"), payload.get("operation"), payload["channel"]]
            for key in ("trade", "setup", "source"):
                record = payload.get(key)
                if isinstance(record, dict):
                    internal_ids.append(record.get("id"))
                    internal_ids.extend(record.get(field) for field in ("message_id", "setup_message_id"))
            payload["text"] = clean_channel_text(payload.get("text", ""), internal_ids)
            if not payload["text"]:
                raise ValueError("Channel message must contain public content after internal references are removed.")
            if kind == "analysis":
                validate_analysis(payload["text"])
            elif kind == "signal":
                from .zones import active, signal_public_text, validate_signal_levels

                trade = payload.get("trade")
                if not isinstance(trade, dict) or not trade.get("id"):
                    raise ValueError("A signal must include its saved trade record.")
                setup_id = payload.get("setup_id") or trade.get("setup_id")
                setup = active(self.db, setup_id)
                if not setup.get("confirmation"):
                    raise ValueError("Record the observed setup confirmation before preparing a signal.")
                direction_first = trade.get("direction_first") is True
                if direction_first:
                    if (trade.get("direction") not in ("BUY", "SELL") or
                            trade.get("levels_pending") is not True or
                            trade.get("entry") or trade.get("sl") or trade.get("targets")):
                        raise ValueError("Only an empty, confirmed BUY or SELL draft can publish before its trade details.")
                    levels = {"entry": "", "sl": "", "targets": {}}
                else:
                    targets = trade.get("targets")
                    if not isinstance(targets, dict):
                        raise ValueError("At least one valid Take Profit is required before publishing.")
                    target_values = ", ".join(
                        str(target.get("price") if isinstance(target, dict) else target)
                        for _, target in sorted(targets.items(), key=lambda item: int(item[0]))
                    )
                    levels = validate_signal_levels(
                        setup, trade.get("direction"), trade.get("entry"),
                        trade.get("sl"), target_values,
                    )
                trade.update(
                    setup_id=setup["id"],
                    market=setup["market"],
                    symbol=setup["market"],
                    zone=setup["zone"],
                    timeframe=setup.get("timeframe", ""),
                    setup_message_id=setup["setup_message_id"],
                    entry=levels["entry"],
                    sl=levels["sl"],
                    targets=levels["targets"],
                )
                payload["setup_id"] = setup["id"]
                payload["text"] = signal_public_text(trade["direction"])
            elif kind == "setup":
                safe_text(payload["text"], 900)
                if not str(payload.get("image", "")).startswith("asset:"):
                    raise ValueError("Upload a chart before posting the setup zone.")
                _validate_setup_publish_state(self.db, payload)
                if zones.is_expired(payload.get("setup", {})):
                    raise ValueError("This setup expired before posting.")
            else:
                safe_text(payload["text"], 3900)
        else:
            allowed_destinations = tuple(
                chat_id for chat_id in
                (self.config.signals, self.config.analysis, self.config.education_group_id)
                if chat_id
            )
            if payload["channel"] not in allowed_destinations or not self.config.ready:
                raise ValueError("Choose a configured channel.")
            if not self.invite_authorized(payload["user"], payload["channel"]):
                if payload["channel"] == self.config.signals:
                    raise ValueError(
                        "PRO invite requires an approved application with registration APPROVED "
                        "and funded-account verification VERIFIED.")
                raise ValueError("Approve this destination request first.")
            for existing in self.db.rows(
                    "SELECT id,payload FROM operations WHERE kind='invite' "
                    "AND status IN ('prepared','sending','uncertain','retryable')"):
                try:
                    pending = json.loads(existing["payload"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if pending.get("user") == payload["user"] and pending.get("channel") == payload["channel"]:
                    raise ValueError("Resolve the existing invite operation before creating another link.")
        self.db.persist_images(payload)
        op = uid()
        with self.db.transaction() as c:
            if kind == "signal":
                if payload.get("setup_id"):
                    from .zones import active, save_in
                    setup = active(self.db, payload["setup_id"])
                    if not setup.get("confirmation"):
                        raise ValueError("Missing confirmation details: " + (setup["condition"] or "your observed setup confirmation"))
                    setup.update(status="used", operation=op, trade_id=payload["trade"]["id"])
                    save_in(c, setup)
                trade = payload["trade"]
                c.execute("INSERT INTO trades VALUES (?,?,?,?,?,0)",
                          (trade["id"], json.dumps(trade), "WAITING_FOR_CONFIRMATION", now(), now()))
            if kind == "setup":
                _validate_setup_publish_state(self.db, payload)
            if kind in ("update", "edit"):
                t = self.db.trade(payload["trade"]["id"])
                if t["version"] != payload["expected_version"] or t["state"] not in OPEN_STATES:
                    raise ValueError("Trade changed. Open it again and review a fresh update.")
                if kind == "update" and payload.get("action") == "tp1_profit_screenshot":
                    target = self._validate_tp1_profit_screenshot(payload, t)
                    payload["trade"] = t
                    number = int(payload.get("target_number", 1))
                    payload["target_number"] = number
                    payload["target_price"] = target["price"]
                    if number == 1:
                        payload["tp1_price"] = target["price"]
                # Only one unresolved mutation for this trade.
                for r in c.execute("SELECT payload FROM operations WHERE status IN ('prepared','sending','uncertain','retryable')"):
                    p = json.loads(r[0])
                    if p.get("trade", {}).get("id") == t["id"]:
                        raise ValueError("Resolve the existing pending operation for this trade first.")
            c.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                      (op, kind, json.dumps(payload), "prepared", None, now(), now()))
        return op

    def prepare_zone_tapped(self, actor, setup_id):
        """Create one idempotent outbox operation per configured channel."""
        self.config.authorize(actor)
        if not self.config.ready:
            raise ValueError("Configure both PRO Signals and Market Analysis before posting a zone update.")
        if not self.config.allow_publishing:
            raise ValueError("Publishing is OFF. No Telegram API call was made.")

        setup = zones.active(self.db, setup_id)
        text = zones.zone_tapped_update_text(setup)
        destinations = {"signals": self.config.signals, "analysis": self.config.analysis}
        key = f"zone_tapped_operations:{setup_id}"
        with self.db.transaction() as c:
            zones.active(self.db, setup_id)
            existing = self.db.get(key)
            if existing is not None:
                if (not isinstance(existing, dict) or set(existing) != set(destinations) or
                        any(not isinstance(existing.get(name), str) for name in destinations)):
                    raise ValueError("The saved Zone Tapped operation needs administrator review.")
                return existing

            operation_ids = {}
            for destination, channel in destinations.items():
                operation_id = uid()
                payload = {
                    "actor": actor,
                    "destination": destination,
                    "channel": channel,
                    "setup_id": setup_id,
                    "setup_message_id": setup["setup_message_id"],
                    "analysis_message_id": (
                        setup.get("market_analysis_message_id")
                        if destination == "analysis" else None),
                    "analysis_channel_id": (
                        setup.get("market_analysis_source_channel_id")
                        if destination == "analysis" else None),
                    "analysis_operation_id": (
                        setup.get("market_analysis_operation_id")
                        if destination == "analysis" else None),
                    "text": clean_channel_text(
                        text, [setup_id, setup.get("setup_message_id"), channel]),
                }
                c.execute(
                    "INSERT INTO operations VALUES (?,?,?,?,?,?,?)",
                    (operation_id, "zone_tapped", json.dumps(payload),
                     "prepared", None, now(), now()),
                )
                operation_ids[destination] = operation_id
            c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",
                      (key, json.dumps(operation_ids)))
        return operation_ids

    def _verify_linked_market_analysis_post(self, setup, payload):
        message_id = payload.get("analysis_message_id")
        if not message_id:
            return
        if message_id != setup.get("market_analysis_message_id"):
            raise ValueError("The linked Market Analysis post changed. Reopen Zone & Signals.")

        operation_id = payload.get("analysis_operation_id")
        if operation_id:
            try:
                row, linked_payload = self.operation(operation_id)
            except ValueError:
                raise ValueError("The linked Market Analysis post is no longer verified.") from None
            if (row["kind"] != "analysis" or row["status"] != "done" or
                    row["message_id"] != message_id or
                    linked_payload.get("destination") != "analysis" or
                    linked_payload.get("channel") != self.config.analysis):
                raise ValueError("The linked Market Analysis post is no longer verified.")
            return

        source_channel = (
            payload.get("analysis_channel_id") or
            setup.get("market_analysis_source_channel_id")
        )
        if (setup.get("market_analysis_source_verified") is True and
                source_channel is not None and
                str(source_channel) == str(self.config.analysis)):
            return

        # Backfill zones created before verified source metadata was persisted.
        # Their no-operation link must still be backed by the completed,
        # channel-keyed import record and its matching published PRO operation.
        try:
            channel_id = int(self.config.analysis)
            source_message_id = int(message_id)
        except (TypeError, ValueError):
            channel_id = source_message_id = 0
        source = self.db.get(
            f"pro_import_source:{channel_id}:{source_message_id}", {})
        if (not isinstance(source, dict) or source.get("status") != "done" or
                str(source.get("message_id")) != str(message_id) or
                not isinstance(source.get("operations"), list)):
            raise ValueError("The linked Market Analysis post is no longer verified.")
        setup_id = setup.get("id")
        for operation_id in source["operations"]:
            try:
                row, linked_payload = self.operation(operation_id)
            except ValueError:
                continue
            linked_setup = linked_payload.get("setup") or {}
            if (row["kind"] == "setup" and row["status"] == "done" and
                    row["message_id"] == setup.get("setup_message_id") and
                    linked_payload.get("destination") == "signals" and
                    linked_payload.get("channel") == self.config.signals and
                    linked_setup.get("id") == setup_id and
                    str(linked_setup.get("market_analysis_message_id")) == str(message_id)):
                return
        raise ValueError("The linked Market Analysis post is no longer verified.")

    def _validate_tp1_profit_screenshot(self, payload, trade=None):
        trade_data = payload.get("trade")
        if not isinstance(trade_data, dict) or not trade_data.get("id"):
            raise ValueError("Choose an active published trade before preparing a TP screenshot.")
        current = trade or self.db.trade(trade_data["id"])
        try:
            target_number = int(payload.get("target_number", 1))
        except (TypeError, ValueError):
            raise ValueError("Choose a TP1–TP4 target for the screenshot.") from None
        if not 1 <= target_number <= zones.AUTOMATIC_TP_MAX_TARGETS:
            raise ValueError("Profit screenshots are available for TP1–TP4 only.")
        target = current.get("targets", {}).get(str(target_number))
        if current["state"] not in OPEN_STATES:
            raise ValueError("Profit screenshots can be posted only while the trade is active.")
        if current.get("levels_pending") or not current.get("message_id"):
            raise ValueError("Complete the published trade details before posting a TP screenshot.")
        if not target:
            raise ValueError(f"TP{target_number} is not set on this trade.")
        records = target_profit_screenshots(current)
        if str(target_number) in records:
            raise ValueError(f"A TP{target_number} profit screenshot has already been published.")
        expected = next_target_profit_screenshot(
            current, max_targets=zones.AUTOMATIC_TP_MAX_TARGETS)
        if expected is None:
            raise ValueError("All available TP1–TP4 profit screenshots have already been posted.")
        if expected != target_number:
            raise ValueError(f"Post the TP{expected} profit screenshot first.")
        if payload.get("destination") != "signals" or payload.get("channel") != self.config.signals:
            raise ValueError("TP profit screenshots must reply in the configured PRO Signals channel.")
        if not str(payload.get("image", "")).startswith("asset:"):
            raise ValueError("Attach a screenshot before reviewing the TP update.")
        if (not payload.get("prices_confirmed") or
                not payload.get("observed_entry") or
                not payload.get("observed_exit") or
                not payload.get("price_movement")):
            raise ValueError("Confirm the screenshot’s entry, exit, and pip calculation before publishing.")
        validate_target_exit(
            current["direction"], target["price"], payload["observed_exit"])
        detected = payload.get("detected_position")
        calculation_market = (
            detected.get("symbol") if isinstance(detected, dict) else
            current.get("market") or current.get("symbol")
        )
        calculated = calculate_trade_result(
            calculation_market, current["direction"],
            payload["observed_entry"], payload["observed_exit"])
        if (calculated["pips"] != payload.get("pips") or
                calculated["price_movement"] != str(payload.get("price_movement"))):
            raise ValueError("The saved price movement does not match the confirmed screenshot prices.")
        return target

    def operation(self, op):
        rows = self.db.rows("SELECT * FROM operations WHERE id=?", (op,))
        if not rows:
            raise ValueError("Operation not found.")
        return rows[0], json.loads(rows[0]["payload"])

    def current_invite_operation(self, user, channel):
        key = f"current_invite:{user}:{channel}"
        current = self.db.get(key)
        if current == "revoked":
            return None
        if current:
            try:
                row, payload = self.operation(current)
                result = self.db.get(f"invite:{current}")
                if (row["kind"] == "invite" and row["status"] == "done" and
                        payload.get("user") == user and payload.get("channel") == channel and
                        isinstance(result, dict) and result.get("invite_link")):
                    return current
            except ValueError:
                pass
        # Adopt the most recent valid legacy invite once; older links are rejected
        # after this pointer is established and replaced links are revoked.
        for row in self.db.rows(
                "SELECT id,payload FROM operations WHERE kind='invite' AND status='done' "
                "ORDER BY created DESC LIMIT 500"):
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            result = self.db.get(f"invite:{row['id']}")
            if (payload.get("user") == user and payload.get("channel") == channel and
                    isinstance(result, dict) and result.get("invite_link")):
                self.db.put(key, row["id"])
                return row["id"]
        return None

    def record_invite_state(self, user, channel, state):
        rows = self.db.rows("SELECT status FROM access WHERE user_id=? AND channel=?", (user, channel))
        current = rows[0]["status"] if rows else None
        if current in ("joined", "member", "administrator", "creator"):
            return
        if (state in ("invite_failed", "invite_pending") and current == "invite_issued" and
                self.current_invite_operation(user, channel)):
            return
        self.db.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                        (user, channel, state, now()))

    def sanitize_pending_operation(self, op):
        """Clean legacy, not-yet-sent channel payloads and require a fresh review."""
        row, payload = self.operation(op)
        if row["kind"] == "invite" or row["status"] not in ("prepared", "retryable"):
            return False
        internal_ids = [op, payload.get("setup_id"), payload.get("operation"), payload.get("channel")]
        for key in ("trade", "setup", "source"):
            record = payload.get(key)
            if isinstance(record, dict):
                internal_ids.append(record.get("id"))
                internal_ids.extend(record.get(field) for field in ("message_id", "setup_message_id"))
        cleaned = clean_channel_text(payload.get("text", ""), internal_ids)
        if cleaned == payload.get("text", ""):
            return False
        payload["text"] = cleaned
        self.db.execute("UPDATE operations SET payload=?,updated=? WHERE id=? AND status IN ('prepared','retryable')",
                        (json.dumps(payload), now(), op))
        return True

    def receipt(self, op, result):
        self.db.execute("INSERT INTO receipts(id,result) VALUES (?,?) ON CONFLICT(id) DO NOTHING",
                        (op, json.dumps(result)))
        # Extra durable evidence if Telegram succeeded but the SQLite commit fails.
        if self.db.postgres:
            return
        with open(self.journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": op, "result": result, "time": now()}) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def finalize(self, op, result):
        row, p = self.operation(op)
        if row["status"] == "done":
            return
        message_id = result.get("message_id")
        with self.db.transaction() as c:
            if row["kind"] == "setup":
                from .zones import save_in
                setup = p["setup"]
                old = None
                if p.get("replaces"):
                    old = zones.active(self.db, p["replaces"])
                if old:
                    old["status"] = "replaced"
                    save_in(c, old)
                setup.update(status="active", setup_message_id=message_id, post_operation=op)
                save_in(c, setup)
            if row["kind"] in ("signal", "update", "edit"):
                t = p["trade"]
                if row["kind"] == "signal":
                    t["message_id"] = message_id
                    t["confirmation_time"] = now()
                    t["state"] = f"CONFIRMED_{t['direction']}"
                    t["original_text"] = p["text"]
                if row["kind"] == "edit":
                    t["original_text"] = p["text"]
                c.execute("UPDATE trades SET data=?,state=?,version=version+1,updated=? WHERE id=?",
                          (json.dumps(t), t["state"], now(), t["id"]))
                c.execute("INSERT OR IGNORE INTO events(trade_id,operation_id,actor,text,message_id,created) "
                          "VALUES (?,?,?,?,?,?)", (t["id"], op, p["actor"], p["text"], message_id, now()))
                if (row["kind"] == "update" and
                        p.get("source", {}).get("levels_pending") and
                        not t.get("levels_pending")):
                    result_key = self.db._signal_result_key(t["id"])
                    result_row = c.execute(
                        "SELECT value FROM kv WHERE key=?", (result_key,)
                    ).fetchone()
                    if result_row:
                        result_record = json.loads(result_row["value"])
                        result_record.update(
                            entry=t.get("entry", ""),
                            sl=t.get("sl", ""),
                            targets=t.get("targets", {}),
                            updated=now(),
                        )
                        c.execute(
                            "UPDATE kv SET value=? WHERE key=?",
                            (json.dumps(result_record), result_key),
                        )
                if (row["kind"] == "update" and
                        p.get("action") == "tp1_profit_screenshot"):
                    target_number = int(p.get("target_number", 1))
                    record = {
                        "image": p["image"],
                        "message_id": message_id,
                        "target": str(target_number),
                        "price": p.get("target_price", p.get("tp1_price")),
                        "entry": p["observed_entry"],
                        "exit": p["observed_exit"],
                        "pips": p["pips"],
                        "price_movement": p["price_movement"],
                        "posted_at": now(),
                    }
                    screenshots = target_profit_screenshots(t)
                    screenshots[str(target_number)] = record
                    t["target_profit_screenshots"] = screenshots
                    if target_number == 1:
                        t["tp1_profit_screenshot"] = record
                    c.execute("UPDATE trades SET data=?,updated=? WHERE id=?",
                              (json.dumps(t), now(), t["id"]))
            if row["kind"] == "invite":
                c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (f"invite:{op}", json.dumps(result)))
                access = c.execute("SELECT status FROM access WHERE user_id=? AND channel=?",
                                   (p["user"], p["channel"])).fetchone()
                current_status = access["status"] if access else "invite_pending"
                if current_status not in ("joined", "member", "administrator", "creator"):
                    current_status = "invite_issued"
                c.execute("INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                          (p["user"], p["channel"], current_status, now()))
                c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",
                          (f"current_invite:{p['user']}:{p['channel']}", json.dumps(op)))
            c.execute("UPDATE operations SET status='done',message_id=?,updated=? WHERE id=?",
                      (message_id, now(), op))

    async def send(self, actor, op):
        initial_row, initial_payload = self.operation(op)
        if not self.is_self_service_education_operation(
                actor, initial_row["kind"], initial_payload):
            self.config.authorize(actor)
        if initial_row["kind"] == "zone_tapped" and not self.config.allow_publishing:
            raise ValueError("Publishing is OFF. No Telegram API call was made.")
        if initial_row["kind"] == "zone_tapped":
            await self.verify_destinations()
        elif self.db.postgres or self.config.isolated_test:
            if not self.verified:
                raise ValueError("Live publishing is locked pending verification and operator enablement.")
            if initial_row["kind"] != "invite" and not self.config.allow_publishing:
                raise ValueError("Live publishing is locked pending verification and operator enablement.")
            await self.verify_destinations()
            if (initial_row["kind"] == "invite" and
                    initial_payload["channel"] == self.config.education_group_id):
                await self.verify_education_group()
        async with self.lock:
            row, p = self.operation(op)
            if row["status"] == "done":
                return "Already completed; nothing reposted."
            if row["status"] not in ("prepared", "retryable"):
                raise ValueError("Result is uncertain or not retryable. Reconcile it; do not blindly repost.")
            if self.sanitize_pending_operation(op):
                raise ValueError("Internal references were removed from this saved draft. Review the clean message before sending.")
            row, p = self.operation(op)
            if row["kind"] != "invite" and not p.get("text", "").strip():
                raise ValueError("This saved draft has no public message after internal references were removed. Abandon it and create a new draft.")
            if time.time() < self.db.get(f"retry_after:{op}", 0):
                raise ValueError("Telegram retry-after period has not elapsed.")
            if row["kind"] != "invite":
                if row["kind"] == "zone_tapped":
                    expected_channel = {
                        "signals": self.config.signals,
                        "analysis": self.config.analysis,
                    }.get(p.get("destination"))
                    if not expected_channel:
                        raise ValueError("This zone update has an invalid destination.")
                    current_setup = zones.active(self.db, p.get("setup_id"))
                    if p["destination"] == "analysis":
                        self._verify_linked_market_analysis_post(current_setup, p)
                else:
                    expected_channel = self.config.destination(row["kind"], p["destination"])
                if p["channel"] != expected_channel:
                    raise ValueError("Channel configuration changed. Discard this operation.")
                if row["kind"] == "analysis":
                    validate_analysis(p["text"])
                if row["kind"] == "setup":
                    _validate_setup_publish_state(self.db, p)
                    if zones.is_expired(p["setup"]):
                        raise ValueError("This setup expired before posting.")
            if row["kind"] in ("edit", "update"):
                current_trade = self.db.trade(p["trade"]["id"])
                if current_trade["version"] != p["expected_version"]:
                    raise ValueError("Trade changed; operation blocked.")
                if row["kind"] == "update" and p.get("action") == "tp1_profit_screenshot":
                    self._validate_tp1_profit_screenshot(p, current_trade)
            if row["kind"] == "invite" and not self.invite_authorized(p["user"], p["channel"]):
                raise ValueError("Membership approval or PRO eligibility is no longer valid.")
            self.db.execute("UPDATE operations SET status='sending',updated=? WHERE id=?", (now(), op))
            try:
                for attempt in range(3):
                    try:
                        if row["kind"] == "invite":
                            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
                            invite_options = {
                                "name": f"SMH {op}",
                                "expire_date": expires_at,
                                "creates_join_request": p["channel"] != self.config.education_group_id,
                            }
                            if p["channel"] == self.config.education_group_id:
                                invite_options["member_limit"] = 1
                            link = await self.bot.create_chat_invite_link(
                                p["channel"], **invite_options)
                            previous_revoked = True
                            previous_op = self.current_invite_operation(p["user"], p["channel"])
                            if previous_op and previous_op != op:
                                previous = self.db.get(f"invite:{previous_op}", {})
                                previous_link = previous.get("invite_link") if isinstance(previous, dict) else None
                                if previous_link:
                                    try:
                                        await self.bot.revoke_chat_invite_link(
                                            chat_id=p["channel"], invite_link=previous_link)
                                    except Exception:
                                        previous_revoked = False
                                        self.db.error(
                                            "member_invite_revoke",
                                            "A replaced invite could not be revoked; requests using it will be rejected.")
                            result = {
                                "invite_link": link.invite_link,
                                "expires_at": expires_at.isoformat(),
                                "direct_join": p["channel"] == self.config.education_group_id,
                                "previous_invite_revoked": previous_revoked,
                            }
                        elif row["kind"] == "edit":
                            msg = await self.bot.edit_message_text(p["text"], chat_id=p["channel"],
                                                                 message_id=p["trade"]["message_id"])
                            result = {"message_id": msg.message_id}
                        elif row["kind"] == "zone_tapped":
                            reply = None
                            if p["destination"] == "signals":
                                reply = ReplyParameters(
                                    p["setup_message_id"], allow_sending_without_reply=False)
                            elif p.get("analysis_message_id"):
                                reply = ReplyParameters(
                                    p["analysis_message_id"], allow_sending_without_reply=False)
                            msg = await self.bot.send_message(
                                p["channel"], p["text"], parse_mode="HTML",
                                reply_parameters=reply)
                            result = {"message_id": msg.message_id}
                        elif row["kind"] in ("setup", "analysis") and p.get("image"):
                            image_path = self.db.image_path(p["image"])
                            with open(image_path, "rb") as f:
                                caption_options = {"caption": p["text"]}
                                if row["kind"] == "setup":
                                    caption_options["parse_mode"] = "HTML"
                                if as_document(image_path):
                                    msg = await self.bot.send_document(p["channel"], f, **caption_options)
                                else:
                                    msg = await self.bot.send_photo(p["channel"], f, **caption_options)
                            result = {"message_id": msg.message_id}
                        elif row["kind"] == "update" and p.get("image"):
                            image_path = self.db.image_path(p["image"])
                            reply = ReplyParameters(p["trade"]["message_id"], allow_sending_without_reply=True)
                            with open(image_path, "rb") as f:
                                if as_document(image_path):
                                    msg = await self.bot.send_document(
                                        p["channel"], f, caption=p["text"], reply_parameters=reply)
                                else:
                                    msg = await self.bot.send_photo(
                                        p["channel"], f, caption=p["text"], reply_parameters=reply)
                            result = {"message_id": msg.message_id}
                        else:
                            reply = None
                            if row["kind"] == "update":
                                reply = ReplyParameters(p["trade"]["message_id"], allow_sending_without_reply=True)
                            elif row["kind"] == "signal" and p["trade"].get("setup_message_id"):
                                reply = ReplyParameters(p["trade"]["setup_message_id"], allow_sending_without_reply=False)
                            message_options = {"reply_parameters": reply}
                            if row["kind"] == "signal":
                                message_options["parse_mode"] = "HTML"
                            msg = await self.bot.send_message(
                                p["channel"], p["text"], **message_options)
                            result = {"message_id": msg.message_id}
                        break
                    except RetryAfter as e:
                        seconds = e.retry_after.total_seconds() if hasattr(e.retry_after, "total_seconds") else e.retry_after
                        if seconds > 30 or attempt == 2:
                            self.db.put(f"retry_after:{op}", datetime.now(timezone.utc).timestamp() + seconds)
                            self.db.execute("UPDATE operations SET status='retryable' WHERE id=?", (op,))
                            if row["kind"] == "invite":
                                self.record_invite_state(p["user"], p["channel"], "invite_pending")
                            return "Telegram rate-limited this action. Retry after the stated waiting period in Operations."
                        await asyncio.sleep(seconds + .1)
                self.receipt(op, result)
                self.finalize(op, result)
                return "Completed and recorded."
            except (BadRequest, Forbidden):
                self.db.execute("UPDATE operations SET status='failed',updated=? WHERE id=?", (now(), op))
                if row["kind"] == "invite":
                    self.record_invite_state(p["user"], p["channel"], "invite_failed")
                self.db.error("telegram_rejected", f"Operation {op}: check destination permissions and content.")
                raise ValueError("Telegram rejected this operation. Check destination permissions/content; it was not reposted.") from None
            except Exception:
                # Includes network timeouts and local commit errors after successful send.
                try:
                    self.db.execute("UPDATE operations SET status='uncertain',updated=? WHERE id=?", (now(), op))
                    if row["kind"] == "invite":
                        self.record_invite_state(p["user"], p["channel"], "invite_uncertain")
                    self.db.error("uncertain_operation", f"Operation {op}: inspect the channel before reconciliation.")
                except Exception:
                    pass
                raise ValueError(f"Operation {op} has an uncertain result. Inspect the channel; automatic reposting is blocked.") from None

    def recover(self):
        self.db.execute("UPDATE operations SET status='uncertain' WHERE status='sending'")
        for r in self.db.rows("SELECT * FROM receipts"):
            self.finalize(r["id"], json.loads(r["result"]))
        if not self.db.postgres and self.journal.exists():
            for line in self.journal.read_text().splitlines():
                try:
                    receipt = json.loads(line)
                    self.finalize(receipt["id"], receipt["result"])
                except (ValueError, KeyError):
                    self.db.error("receipt_invalid", "A receipt needs manual review; no send was repeated.")

    async def reconcile(self, actor, op, message_id):
        self.config.authorize(actor)
        row, p = self.operation(op)
        if row["status"] != "uncertain" or row["kind"] == "invite":
            raise ValueError("This operation cannot be reconciled with a message ID.")
        if message_id <= 0:
            raise ValueError("Use a positive original channel message ID.")
        # Telegram cannot fetch arbitrary historical posts. Admin attests exact match.
        self.receipt(op, {"message_id": message_id})
        self.finalize(op, {"message_id": message_id})
        self.db.error("manual_reconciliation", f"Administrator attested channel message for operation {op}.")

    def abandon(self, actor, op):
        self.config.authorize(actor)
        row, p = self.operation(op)
        if row["status"] in ("done", "sending"):
            raise ValueError("Cannot abandon this operation.")
        with self.db.transaction() as c:
            c.execute("UPDATE operations SET status='abandoned',updated=? WHERE id=?", (now(), op))
            if row["kind"] == "signal":
                c.execute("UPDATE trades SET state='CANCELLED',updated=? WHERE id=?", (now(), p["trade"]["id"]))
            c.execute("INSERT INTO errors(category,detail,created) VALUES (?,?,?)",
                      ("abandoned", f"Administrator abandoned operation {op}; no repost.", now()))
