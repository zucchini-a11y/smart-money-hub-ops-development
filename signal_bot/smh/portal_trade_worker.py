"""Owner-approved portal trade actions, processed through the normal publisher."""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from .database import now
from .domain import change, safe_text
from .publishing import clean_channel_text

log = logging.getLogger("smh")
_WORKER_STATUS_KEY = "portal_trade_worker_status"
_WORKER_VERSION = "trade-management-v1"
_HEARTBEAT_SECONDS = 20


def _worker_status(db, status, config, publisher):
    db.put(_WORKER_STATUS_KEY, {
        "version": _WORKER_VERSION,
        "status": status,
        "publishing_enabled": bool(config.allow_publishing),
        "destinations_verified": bool(publisher.verified),
        "updated": now(),
    })


def recover_interrupted_commands(db):
    """Quarantine claimed commands after a crash; never replay a possibly sent post."""
    interrupted = db.rows(
        "SELECT id FROM portal_trade_commands WHERE command_status='processing'",
    )
    for command in interrupted:
        _mark(
            db,
            command["id"],
            "uncertain",
            "The worker stopped during this action. No automatic retry will occur. Check the trade history and Telegram post before continuing.",
        )


def _command_event(db, command_id, event_type, detail):
    rows = db.rows(
        "SELECT actor_staff_id FROM portal_trade_commands WHERE id=?",
        (command_id,),
    )
    if not rows:
        return
    db.execute(
        "INSERT INTO portal_trade_command_events"
        "(id,command_id,actor_staff_id,event_type,detail,created) VALUES(?,?,?,?,?,?)",
        (uuid4().hex, command_id, rows[0]["actor_staff_id"], event_type, str(detail)[:500], now()),
    )


def _input_for_change(action, values):
    def required(name):
        value = values.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Enter the confirmed {name.replace('_', ' ')}.")
        return value.strip()

    if action == "entry_bundle":
        entry = required("entry")
        stop = required("stop_loss")
        target_number = required("target_number")
        target_price = required("target_price")
        trade, _ = change(values["_trade"], "entry", entry)
        trade, _ = change(trade, "sl", stop)
        trade, _ = change(trade, "tp", f"{target_number} {target_price}")
        targets = ", ".join(
            f"TP{key}: {target['price']}"
            for key, target in sorted(trade.get("targets", {}).items(), key=lambda pair: int(pair[0]))
        )
        symbol = trade.get("symbol") or trade.get("market") or "Not supplied"
        text = (
            "📌 VAYDA SMART MONEY HUB\n\n🔄 TRADE DETAILS UPDATED\n\n"
            f"📊 Pair: {symbol}\n📌 Direction: {trade.get('direction', 'Not supplied')}\n"
            f"📍 Entry: {trade['entry']}\n🛑 Stop Loss: {trade.get('sl') or 'Not supplied'}\n"
            f"🎯 Targets: {targets or 'Not supplied'}"
        )
        return trade, text
    if action == "sl_tp":
        value = f"SL {required('stop_loss')} | TP{required('target_number')} {required('target_price')}"
    elif action == "tp":
        value = f"{required('target_number')} {required('target_price')}"
    elif action == "hit":
        value = f"{required('target_number')}|{required('target_status')}"
    elif action == "partial":
        if values.get("mode") != "reported":
            raise ValueError("Select a confirmed partial profit, not a recommendation.")
        value = (
            f"{required('percentage')}|reported|{required('target_price')}|"
            f"{str(values.get('remaining', '')).strip()}"
        )
    elif action == "be":
        if values.get("stop_moved") is not True:
            raise ValueError("Confirm that the stop loss was actually moved to entry.")
        value = "confirmed"
    elif action == "close":
        if values.get("outcome_confirmed") is not True:
            raise ValueError("Confirm the recorded trade outcome before continuing.")
        value = (
            f"{required('outcome')}|{str(values.get('exit_price', '')).strip()}|"
            f"{str(values.get('note', '')).strip()}"
        )
    elif action in ("cancel", "invalidate"):
        value = required("reason")
    elif action in ("custom", "edit"):
        value = safe_text(required("text"))
    elif action in ("sl", "trail"):
        value = required("stop_loss")
    else:
        raise ValueError("Choose a supported trade action.")
    if action == "edit":
        return values["_trade"], value
    return change(values["_trade"], action, value)


def _build_preview(trade, action, values):
    entered = bool(trade.get("entry")) or trade.get("state") == "ACTIVE"
    if action == "cancel" and entered:
        raise ValueError("This trade has an entry. Use Invalidate Trade instead.")
    if action == "invalidate" and not entered:
        raise ValueError("This setup has no recorded entry. Use Cancel Setup instead.")
    working_values = {**values, "_trade": trade}
    changed_trade, text = _input_for_change(action, working_values)
    reference_ids = [
        trade.get("id"),
        trade.get("message_id"),
        trade.get("setup_message_id"),
    ]
    return changed_trade, clean_channel_text(text, reference_ids)


def _mark(db, command_id, status, message, operation_id=None):
    stamp = now()
    db.execute(
        "UPDATE portal_trade_commands SET command_status=?,safe_result=?,operation_id=COALESCE(?,operation_id),"
        "updated=?,completed_at=CASE WHEN ? IN ('completed','failed','uncertain','stale','cancelled') "
        "THEN ? ELSE completed_at END WHERE id=?",
        (status, str(message)[:500], operation_id, stamp, status, stamp, command_id),
    )
    _command_event(db, command_id, status, message)


def _claim(db, command_id, expected_status):
    with db.transaction() as cursor:
        row = cursor.execute(
            "SELECT * FROM portal_trade_commands WHERE id=? AND command_status=?",
            (command_id, expected_status),
        ).fetchone()
        if not row:
            return None
        # Portal authentication lives in the Development database's smh
        # schema, while isolated bot records live in smh_test. Production's
        # portal and bot share smh in their separate Production database.
        # SQLite tests intentionally use their own unqualified portal_users.
        actor_sql = (
            "SELECT role,active FROM smh.portal_users WHERE id=?"
            if getattr(db, "postgres", False) and getattr(db, "schema", "") == "smh_test"
            else "SELECT role,active FROM portal_users WHERE id=?"
        )
        actor = cursor.execute(actor_sql, (row["actor_staff_id"],)).fetchone()
        if not actor or actor["role"] != "admin" or not actor["active"]:
            stamp = now()
            cursor.execute(
                "UPDATE portal_trade_commands SET command_status='failed',safe_result=?,updated=?,completed_at=? "
                "WHERE id=? AND command_status=?",
                ("The portal owner account is no longer authorized; no Telegram action was sent.",
                 stamp, stamp, command_id, expected_status),
            )
            cursor.execute(
                "INSERT INTO portal_trade_command_events"
                "(id,command_id,actor_staff_id,event_type,detail,created) VALUES(?,?,?,?,?,?)",
                (uuid4().hex, command_id, row["actor_staff_id"], "failed",
                 "The owner authorization check failed; no Telegram action was sent.", stamp),
            )
            return None
        changed = cursor.execute(
            "UPDATE portal_trade_commands SET command_status='processing',attempt_count=attempt_count+1,updated=? "
            "WHERE id=? AND command_status=?",
            (now(), command_id, expected_status),
        )
        if changed.rowcount != 1:
            return None
        cursor.execute(
            "INSERT INTO portal_trade_command_events"
            "(id,command_id,actor_staff_id,event_type,detail,created) VALUES(?,?,?,?,?,?)",
            (uuid4().hex, command_id, row["actor_staff_id"], "processing",
             "The approved owner action is being processed.", now()),
        )
        return dict(row)


def _prepare_command(db, command_id):
    command = _claim(db, command_id, "queued")
    if not command:
        return False
    try:
        trade = db.trade(command["trade_id"])
        if int(trade["version"]) != int(command["expected_version"]):
            _mark(db, command_id, "stale", "The trade changed. Reopen it and prepare a new review.")
            return False
        if trade.get("state") not in ("ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL"):
            _mark(db, command_id, "stale", "This trade is no longer open.")
            return False
        if not trade.get("message_id") and not trade.get("setup_message_id"):
            _mark(db, command_id, "failed", "This trade has no linked Telegram post, so an update cannot be safely attached.")
            return False
        values = json.loads(command["input_json"])
        changed_trade, preview = _build_preview(trade, command["action"], values)
        if not preview:
            raise ValueError("The message preview is empty.")
        db.execute(
            "UPDATE portal_trade_commands SET command_status='preview_ready',preview_text=?,prepared_trade=?,"
            "safe_result=?,updated=? WHERE id=? AND command_status='processing'",
            (preview, json.dumps(changed_trade), "Preview ready. Nothing has been sent.", now(), command_id),
        )
        _command_event(db, command_id, "preview_ready", "A private review preview is ready. Nothing has been sent.")
        return True
    except ValueError as exc:
        _mark(db, command_id, "failed", str(exc))
        return False
    except Exception:
        _mark(db, command_id, "failed", "The trade could not be prepared. No Telegram message was sent.")
        log.warning("portal_trade_prepare_failed")
        return False


async def _publish_command(db, publisher, config, command_id):
    command = _claim(db, command_id, "approved")
    if not command:
        return False
    try:
        updated = command["updated"]
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - updated).total_seconds() > 300:
            _mark(db, command_id, "stale", "This confirmation expired. Review the current trade and create a new preview.")
            return False
        trade = db.trade(command["trade_id"])
        if int(trade["version"]) != int(command["expected_version"]):
            _mark(db, command_id, "stale", "The trade changed after preview. Nothing was sent.")
            return False
        values = json.loads(command["input_json"])
        changed_trade, preview = _build_preview(trade, command["action"], values)
        if preview != command["preview_text"]:
            _mark(db, command_id, "stale", "The preview no longer matches the current trade. Nothing was sent.")
            return False
        # For an update, reply to the confirmed signal or, before entry, the
        # original setup-zone post. The IDs stay internal and out of the text.
        linked_trade = dict(changed_trade)
        linked_trade["message_id"] = trade.get("message_id") or trade.get("setup_message_id")
        kind = "edit" if command["action"] == "edit" else "update"
        operation_id = publisher.prepare(
            config.admin,
            kind,
            {
                "destination": "signals",
                "trade": linked_trade,
                "expected_version": command["expected_version"],
                "text": preview,
            },
        )
        db.execute(
            "UPDATE portal_trade_commands SET operation_id=?,updated=? "
            "WHERE id=? AND command_status='processing'",
            (operation_id, now(), command_id),
        )
        command["operation_id"] = operation_id
        await publisher.send(config.admin, operation_id)
        operation, _ = publisher.operation(operation_id)
        if operation["status"] == "done":
            _mark(db, command_id, "completed", "Update published and linked to the original trade message.", operation_id)
            _command_event(
                db, command_id, "completed",
                "Telegram delivery confirmed and trade history updated.",
            )
            return True
        if operation["status"] in ("uncertain", "sending"):
            _mark(db, command_id, "uncertain",
                  "Telegram delivery is uncertain. Check Operations and the channel; it will not be resent automatically.",
                  operation_id)
        else:
            _mark(db, command_id, "failed", "The update was not published. Review the operation before retrying.", operation_id)
        return False
    except Exception as exc:
        # Publisher records ambiguous Telegram sends on its operation row.
        operation_id = command.get("operation_id")
        if operation_id:
            try:
                operation, _ = publisher.operation(operation_id)
                if operation["status"] in ("uncertain", "sending"):
                    _mark(db, command_id, "uncertain",
                          "Telegram delivery is uncertain. Check Operations and the channel; do not retry blindly.",
                          operation_id)
                    return False
            except Exception:
                pass
        safe_result = str(exc) if isinstance(exc, ValueError) else "The update could not be published."
        _mark(db, command_id, "failed", safe_result, operation_id)
        log.warning("portal_trade_publish_failed")
        return False


async def process_trade_command(db, publisher, config, command_id, status):
    if status == "queued":
        return _prepare_command(db, command_id)
    if status == "approved":
        return await _publish_command(db, publisher, config, command_id)
    return False


async def run_portal_trade_command_worker(db, publisher, config, stop):
    """Poll queued previews and explicitly approved sends; no blind replay."""
    try:
        db.execute("SELECT 1 FROM portal_trade_commands LIMIT 1")
    except Exception:
        _worker_status(db, "migration_required", config, publisher)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                pass
            if stop.is_set():
                break
            try:
                db.execute("SELECT 1 FROM portal_trade_commands LIMIT 1")
            except Exception:
                _worker_status(db, "migration_required", config, publisher)
                continue
            break

    recover_interrupted_commands(db)
    last_heartbeat = 0.0
    _worker_status(db, "ready", config, publisher)
    while not stop.is_set():
        try:
            command = db.rows(
                "SELECT id,command_status FROM portal_trade_commands "
                "WHERE command_status IN ('queued','approved') ORDER BY created LIMIT 1"
            )
            if command:
                await process_trade_command(
                    db, publisher, config, command[0]["id"], command[0]["command_status"])
                continue
            if time.monotonic() - last_heartbeat >= _HEARTBEAT_SECONDS:
                _worker_status(db, "ready", config, publisher)
                last_heartbeat = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("portal_trade_worker_error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass
