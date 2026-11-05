"""Owner-approved portal signal actions for the isolated Development bot."""
import asyncio
import json
import logging
import time
from uuid import uuid4

from .database import now
from .domain import safe_text, validate_analysis
from .publishing import clean_channel_text
from . import zones

log = logging.getLogger("smh")
_STATUS_KEY = "portal_signal_worker_status"
_PANEL_KEY = "portal_signal_panel"
_VERSION = "signal-controls-v1"
_HEARTBEAT_SECONDS = 20
_FINAL = ("completed", "failed", "uncertain", "stale", "cancelled")


def _worker_status(db, status, config, publisher):
    db.put(_STATUS_KEY, {
        "version": _VERSION,
        "status": status,
        "publishing_enabled": bool(config.allow_publishing),
        "destinations_verified": bool(publisher.verified),
        "updated": now(),
    })


def _write_panel(db, config, publisher):
    setup = db.get("active_setup")
    draft = db.draft(config.admin)
    panel = {
        "version": _VERSION,
        "worker_status": "ready",
        "publishing_enabled": bool(config.allow_publishing),
        "destinations_verified": bool(publisher.verified),
        "active_setup": None,
        "zone_draft": None,
        "updated": now(),
    }
    if setup:
        panel["active_setup"] = {
            "setup_id": setup.get("id"),
            "market": setup.get("market", ""),
            "zone": setup.get("zone", ""),
            "timeframe": setup.get("timeframe", ""),
            "condition": setup.get("condition", ""),
            "status": zones.public_status(setup),
            "expires": setup.get("expires"),
            "has_chart": bool(setup.get("image")),
            "has_message": bool(setup.get("setup_message_id")),
        }
    if draft and draft.get("kind") == "zone":
        setup_draft = draft.get("setup") or {}
        panel["zone_draft"] = {
            "revision": draft.get("revision"),
            "market": setup_draft.get("market", ""),
            "zone": setup_draft.get("zone", ""),
            "timeframe": setup_draft.get("timeframe", ""),
            "condition": setup_draft.get("condition", ""),
            "step": draft.get("step", ""),
            "has_chart": bool(draft.get("image")),
            "ready_to_publish": draft.get("step") == "ready" and bool(draft.get("image")),
        }
    db.put(_PANEL_KEY, panel)


def _command_event(db, command_id, event_type, detail):
    rows = db.rows(
        "SELECT actor_staff_id FROM portal_signal_commands WHERE id=?",
        (command_id,),
    )
    if not rows:
        return
    db.execute(
        "INSERT INTO portal_signal_command_events"
        "(id,command_id,actor_staff_id,event_type,detail,created) VALUES(?,?,?,?,?,?)",
        (uuid4().hex, command_id, rows[0]["actor_staff_id"], event_type, str(detail)[:500], now()),
    )


def _mark(db, command_id, status, message, operation_id=None):
    stamp = now()
    db.execute(
        "UPDATE portal_signal_commands SET command_status=?,safe_result=?,"
        "operation_id=COALESCE(?,operation_id),updated=?,"
        "completed_at=CASE WHEN ? IN ('completed','failed','uncertain','stale','cancelled') "
        "THEN ? ELSE completed_at END WHERE id=?",
        (status, str(message)[:500], operation_id, stamp, status, stamp, command_id),
    )
    _command_event(db, command_id, status, message)


def recover_interrupted_commands(db):
    """Quarantine any in-flight action; it may have reached Telegram."""
    for row in db.rows(
        "SELECT id FROM portal_signal_commands WHERE command_status='processing'",
    ):
        _mark(
            db,
            row["id"],
            "uncertain",
            "The signal worker stopped during this action. Check the relevant test channel before taking any further action; it will not retry automatically.",
        )


def _claim(db, command_id, expected_status):
    with db.transaction() as cursor:
        row = cursor.execute(
            "SELECT * FROM portal_signal_commands WHERE id=? AND command_status=?",
            (command_id, expected_status),
        ).fetchone()
        if not row:
            return None
        actor_sql = (
            "SELECT role,active FROM smh.portal_users WHERE id=?"
            if getattr(db, "postgres", False) and getattr(db, "schema", "") == "smh_test"
            else "SELECT role,active FROM portal_users WHERE id=?"
        )
        actor = cursor.execute(actor_sql, (row["actor_staff_id"],)).fetchone()
        if not actor or actor["role"] != "admin" or not actor["active"]:
            message = "The portal owner account is no longer authorized; no Telegram action was sent."
            stamp = now()
            cursor.execute(
                "UPDATE portal_signal_commands SET command_status='failed',safe_result=?,updated=?,completed_at=? "
                "WHERE id=? AND command_status=?",
                (message, stamp, stamp, command_id, expected_status),
            )
            cursor.execute(
                "INSERT INTO portal_signal_command_events"
                "(id,command_id,actor_staff_id,event_type,detail,created) VALUES(?,?,?,?,?,?)",
                (uuid4().hex, command_id, row["actor_staff_id"], "failed", message, stamp),
            )
            return None
        cursor.execute(
            "UPDATE portal_signal_commands SET command_status='processing',attempt_count=attempt_count+1,updated=? "
            "WHERE id=? AND command_status=?",
            (now(), command_id, expected_status),
        )
        cursor.execute(
            "INSERT INTO portal_signal_command_events"
            "(id,command_id,actor_staff_id,event_type,detail,created) VALUES(?,?,?,?,?,?)",
            (uuid4().hex, command_id, row["actor_staff_id"], "processing",
             "The owner-approved signal action is being processed.", now()),
        )
        return dict(row)


def _active_setup(db, setup_id):
    setup = zones.active(db, setup_id)
    if not setup.get("setup_message_id"):
        raise ValueError("The zone has no confirmed Telegram post to update or reply to.")
    return setup


def _prepare_publish(db, publisher, config, action, values):
    if action == "publish_zone":
        draft = db.draft(config.admin)
        if not draft or draft.get("kind") != "zone" or draft.get("step") != "ready" or not draft.get("image"):
            raise ValueError("Upload and review the matching chart in the private bot before publishing this zone.")
        expected_revision = values.get("draft_revision")
        if expected_revision and expected_revision != draft.get("revision"):
            raise ValueError("The zone draft changed. Refresh it and review the current chart.")
        setup = {**draft["setup"], "image": draft["image"], "original": draft.get("original", draft["image"])}
        replaces = draft.get("replaces")
        active = db.get("active_setup")
        if replaces and (not active or active.get("id") != replaces or active.get("status") != "active"):
            raise ValueError("The active zone changed. Review the replacement again.")
        payload = {
            "destination": "signals",
            "setup": setup,
            "replaces": replaces,
            "image": draft["image"],
            "original": draft.get("original", draft["image"]),
            "text": zones.setup_caption(setup),
        }
        op = publisher.prepare(config.admin, "setup", payload)
        return op, payload["text"], {"draft_revision": draft.get("revision")}

    if action == "publish_signal":
        setup = _active_setup(db, values.get("setup_id"))
        if not setup.get("confirmation"):
            raise ValueError("Record the confirmation you observed before preparing BUY or SELL.")
        direction = str(values.get("direction", "")).upper()
        entry_range = values.get("entry_range")
        stop_loss = values.get("stop_loss")
        take_profits = values.get("take_profits")
        if any(not isinstance(value, str) or not value.strip()
               for value in (entry_range, stop_loss, take_profits)):
            raise ValueError(
                "Set a valid Entry range, Stop Loss, and at least one Take Profit before preparing a signal.")
        levels = zones.validate_signal_levels(
            setup, direction, entry_range, stop_loss, take_profits,
        )
        payload = zones.signal_payload(setup, direction, config.admin, levels)
        op = publisher.prepare(config.admin, "signal", payload)
        review_summary = (
            f"Private signal review\nMarket: {setup['market']}\nDirection: {direction}\n"
            f"Entry range: {levels['entry']}\nStop Loss: {levels['sl']}\n"
            + "Take Profit: " + ", ".join(
                item["price"] for item in levels["targets"].values())
            + f"\nExact PRO Signals message: {payload['text']}"
        )
        return op, payload["text"], {
            "setup_id": setup["id"], "direction": direction,
            "entry_range": levels["entry"], "stop_loss": levels["sl"],
            "take_profits": take_profits,
            "review_summary": review_summary,
        }

    if action == "publish_analysis":
        text = validate_analysis(values.get("text", ""))
        payload = {"destination": "analysis", "text": text}
        op = publisher.prepare(config.admin, "analysis", payload)
        return op, text, {"text": text}

    raise ValueError("Choose a supported publishing action.")


def _prepare_command(db, publisher, config, command_id):
    command = _claim(db, command_id, "queued")
    if not command:
        return False
    action = command["action"]
    try:
        values = json.loads(command["input_json"])
        if action == "create_zone_draft":
            existing = db.draft(config.admin)
            if existing:
                raise ValueError("A draft is already open in the bot. Finish or cancel it before starting another setup.")
            market = safe_text(values.get("market", ""), 80)
            low = safe_text(values.get("low", ""), 40)
            high = safe_text(values.get("high", ""), 40)
            timeframe = safe_text(values.get("timeframe", ""), 30) or "-"
            condition = safe_text(values.get("condition", ""), 300) or "-"
            setup = zones.parse_zone(f"{market} | {low}-{high} | {timeframe} | manual | {condition}")
            old = db.get("active_setup")
            if old and old.get("status") == "active" and not zones.is_expired(old):
                replaces = old.get("id")
            else:
                replaces = None
            draft = {"kind": "zone", "step": "chart", "setup": setup}
            if replaces:
                draft["replaces"] = replaces
            db.save_draft(config.admin, draft)
            _mark(db, command_id, "completed",
                  "Setup details saved. Attach the matching chart in the private bot before publishing.")
            _write_panel(db, config, publisher)
            return True

        if action in ("record_confirmation", "cancel_setup", "expire_setup"):
            setup = _active_setup(db, values.get("setup_id"))
            if action == "record_confirmation":
                confirmation = safe_text(values.get("confirmation", ""), 300)
                if not confirmation:
                    raise ValueError("Enter the confirmation you actually observed.")
                changed = dict(setup, confirmation=confirmation)
                preview_status = "Confirmation Recorded"
            else:
                expired = action == "expire_setup"
                changed = dict(
                    setup,
                    status="expired" if expired else "cancelled",
                    expires=None if expired else setup.get("expires"),
                )
                preview_status = "Expired" if expired else "Cancelled"
            preview = zones.setup_caption(changed, preview_status)
            expected = json.dumps(setup, sort_keys=True)
            values["expected_setup"] = expected
            db.execute(
                "UPDATE portal_signal_commands SET input_json=?,preview_text=?,command_status='preview_ready',"
                "safe_result=?,updated=? WHERE id=? AND command_status='processing'",
                (json.dumps(values), clean_channel_text(preview, [setup.get("id")]),
                 "Preview ready. Nothing has been sent or edited.", now(), command_id),
            )
            _command_event(db, command_id, "preview_ready", "The zone update preview is ready. Nothing has been sent.")
            _write_panel(db, config, publisher)
            return True

        op, preview, prepared_values = _prepare_publish(db, publisher, config, action, values)
        values.update(prepared_values)
        review_summary = values.pop("review_summary", None)
        db.execute(
            "UPDATE portal_signal_commands SET input_json=?,operation_id=?,preview_text=?,command_status='preview_ready',"
            "safe_result=?,updated=? WHERE id=? AND command_status='processing'",
            (json.dumps(values), op, clean_channel_text(preview),
             review_summary or "Preview ready. Nothing has been sent.", now(), command_id),
        )
        _command_event(db, command_id, "preview_ready", "The owner review preview is ready. Nothing has been sent.")
        _write_panel(db, config, publisher)
        return True
    except ValueError as exc:
        _mark(db, command_id, "failed", str(exc))
        _write_panel(db, config, publisher)
        return False
    except Exception:
        _mark(db, command_id, "failed", "The action could not be prepared. No Telegram message was sent.")
        log.warning("portal_signal_prepare_failed")
        return False


async def _publish_command(db, publisher, config, bot, command_id):
    command = _claim(db, command_id, "approved")
    if not command:
        return False
    operation_id = command.get("operation_id")
    try:
        if not config.allow_publishing or not publisher.verified:
            _mark(db, command_id, "failed", "Publishing is locked or the destinations are not verified. Nothing was sent.")
            return False
        values = json.loads(command["input_json"])
        action = command["action"]
        if action in ("record_confirmation", "cancel_setup", "expire_setup"):
            setup = _active_setup(db, values.get("setup_id"))
            if json.dumps(setup, sort_keys=True) != values.get("expected_setup"):
                _mark(db, command_id, "stale", "The active zone changed after preview. Nothing was edited.")
                return False
            if action == "record_confirmation":
                changed = dict(setup, confirmation=safe_text(values.get("confirmation", ""), 300))
                status = "Confirmation Recorded"
            else:
                expired = action == "expire_setup"
                changed = dict(
                    setup,
                    status="expired" if expired else "cancelled",
                    expires=None if expired else setup.get("expires"),
                )
                status = "Expired" if expired else "Cancelled"
            caption = clean_channel_text(
                zones.setup_caption(changed, status),
                [changed.get("id"), changed.get("post_operation")],
            )
            try:
                await bot.edit_message_caption(
                    chat_id=config.signals,
                    message_id=setup["setup_message_id"],
                    caption=caption,
                    parse_mode="HTML",
                )
            except Exception as exc:
                if "message is not modified" not in str(exc).lower():
                    _mark(
                        db, command_id, "uncertain",
                        "Telegram edit outcome is uncertain. Check the private test channel before trying again.",
                    )
                    log.warning("portal_signal_zone_edit_uncertain")
                    return False
            with db.transaction() as cursor:
                current = db.get("active_setup")
                if current and current.get("id") == changed.get("id"):
                    zones.save_in(cursor, changed)
                else:
                    zones.save_record_in(cursor, changed)
            _mark(db, command_id, "completed", "The zone post was updated and its status was saved.")
            _write_panel(db, config, publisher)
            return True

        if not operation_id:
            _mark(db, command_id, "failed", "The publishing operation is missing. Nothing was sent.")
            return False
        if action == "publish_zone":
            draft = db.draft(config.admin)
            if not draft or draft.get("revision") != values.get("draft_revision"):
                # Keep compatibility with a draft whose revision was captured in
                # the publisher payload when the command was prepared.
                operation, payload = publisher.operation(operation_id)
                expected_draft = payload.get("draft_revision")
                if not draft or (expected_draft and draft.get("revision") != expected_draft):
                    _mark(db, command_id, "stale", "The zone draft changed after preview. Nothing was sent.", operation_id)
                    return False
        elif action == "publish_signal":
            setup = _active_setup(db, values.get("setup_id"))
            if not setup.get("confirmation"):
                _mark(db, command_id, "stale", "The setup confirmation changed. Prepare a fresh signal preview.", operation_id)
                return False
        operation, _ = publisher.operation(operation_id)
        if operation["status"] not in ("prepared", "retryable"):
            if operation["status"] == "done":
                _mark(db, command_id, "completed", "Telegram already confirmed this operation; it was not sent again.", operation_id)
                return True
            _mark(db, command_id, "uncertain",
                  "The Telegram operation needs reconciliation. It will not be resent automatically.", operation_id)
            return False
        await publisher.send(config.admin, operation_id)
        operation, payload = publisher.operation(operation_id)
        if operation["status"] == "done":
            if action == "publish_zone":
                draft = db.draft(config.admin)
                if draft and draft.get("image"):
                    db.clear_draft(config.admin)
            result = "The post was published to the configured private test destination."
            if action == "publish_signal":
                result = "The signal was published to private test PRO Signals and linked to its setup post."
                setup = db.get("setup:" + str(values.get("setup_id")))
                if setup:
                    try:
                        await bot.edit_message_caption(
                            chat_id=config.signals,
                            message_id=setup["setup_message_id"],
                            caption=clean_channel_text(
                                zones.setup_caption(setup, zones.public_status(setup, "done")),
                                [setup.get("id"), setup.get("post_operation")],
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        log.warning("portal_signal_setup_status_edit_failed")
            _mark(db, command_id, "completed", result, operation_id)
            _write_panel(db, config, publisher)
            return True
        if operation["status"] in ("uncertain", "sending"):
            _mark(db, command_id, "uncertain",
                  "Telegram delivery is uncertain. Check the private test channel and reconcile; there is no automatic retry.",
                  operation_id)
        else:
            _mark(db, command_id, "failed", "The post was not published. Review the operation before continuing.", operation_id)
        return False
    except Exception as exc:
        if operation_id:
            try:
                operation, _ = publisher.operation(operation_id)
                if operation["status"] in ("uncertain", "sending"):
                    _mark(db, command_id, "uncertain",
                          "Telegram delivery is uncertain. Check the private test channel before any retry.",
                          operation_id)
                    log.warning("portal_signal_publish_uncertain")
                    return False
            except Exception:
                pass
        if isinstance(exc, ValueError):
            safe_result = str(exc)
        else:
            safe_result = "The action could not be completed. Check its status before trying again."
        _mark(db, command_id, "failed", safe_result, operation_id)
        log.warning("portal_signal_publish_failed")
        return False


async def process_signal_command(db, publisher, config, bot, command_id, status):
    if status == "queued":
        return _prepare_command(db, publisher, config, command_id)
    if status == "approved":
        return await _publish_command(db, publisher, config, bot, command_id)
    return False


async def run_portal_signal_command_worker(db, publisher, config, bot, stop):
    """Process Development-only signal commands with explicit approval and no blind replay."""
    if not getattr(config, "isolated_test", False) or getattr(db, "schema", "") != "smh_test":
        _worker_status(db, "disabled", config, publisher)
        return
    try:
        db.execute("SELECT 1 FROM portal_signal_commands LIMIT 1")
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
                db.execute("SELECT 1 FROM portal_signal_commands LIMIT 1")
            except Exception:
                _worker_status(db, "migration_required", config, publisher)
                continue
            break

    recover_interrupted_commands(db)
    last_heartbeat = 0.0
    _worker_status(db, "ready", config, publisher)
    _write_panel(db, config, publisher)
    while not stop.is_set():
        try:
            rows = db.rows(
                "SELECT id,command_status FROM portal_signal_commands "
                "WHERE command_status IN ('queued','approved') ORDER BY created LIMIT 1"
            )
            if rows:
                await process_signal_command(
                    db, publisher, config, bot, rows[0]["id"], rows[0]["command_status"])
                continue
            if time.monotonic() - last_heartbeat >= _HEARTBEAT_SECONDS:
                _worker_status(db, "ready", config, publisher)
                _write_panel(db, config, publisher)
                last_heartbeat = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("portal_signal_worker_error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass
