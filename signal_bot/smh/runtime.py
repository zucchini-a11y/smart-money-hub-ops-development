"""Single-process polling with persisted offsets and supervised background tasks."""
import asyncio
import fcntl
import hashlib
import logging
import os
import random
import signal
import time
from pathlib import Path
from telegram import Update
from telegram.error import Conflict, InvalidToken, NetworkError, RetryAfter
from telegram.ext import (
    Application, CallbackQueryHandler, ChatJoinRequestHandler, ChatMemberHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.request import HTTPXRequest
from .config import Config
from .assistant import run_portal_reply_worker
from .support_api import SupportApiClient
from .pro_review_worker import run_portal_member_review_worker
from .portal_trade_worker import run_portal_trade_command_worker
from .portal_signal_worker import run_portal_signal_command_worker
from .education_video_worker import (
    recover_education_video_posts,
    run_education_video_worker,
)
from .education_onboarding import (
    recover_education_onboarding,
    run_education_onboarding_worker,
)
from .applicant_followups import run_applicant_followup_worker
from .database import Database, now
from .handlers import Handlers
from .health import Health, setup_logging
from .publishing import Publisher
from .telegram_style import StyledExtBot
from .zones import make_active_expiry_manual


def friendly_error(exc):
    if isinstance(exc, PermissionError):
        return "🔒 This section is available to the administrator only. Use the main menu to view member options."
    if isinstance(exc, ValueError):
        detail = str(exc).strip()
        if detail and detail not in ("Unknown action.", "Unknown trade action."):
            return f"⚠️ {detail}"
    return ("⚠️ I couldn't complete that request. Please try again shortly. "
            "If the problem continues, contact an administrator. "
            "If this involved a post, check Operations before trying again.")


def lock_process(config):
    # Same token cannot run twice on this host, even with different data directories.
    digest = hashlib.sha256(config.token.encode()).hexdigest()[:24]
    handle = open(f"/tmp/smh-{digest}.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another polling process is running on this host.") from None
    return handle


def _record_polling_failure(db, category, detail):
    """Persist a safe category without logging provider error text or credentials."""
    try:
        db.error(category, detail)
    except Exception:
        pass
    logging.getLogger("smh").critical(category)


def _invalid_token_failure(db):
    _record_polling_failure(
        db,
        "polling_invalid_token",
        "Telegram rejected the configured bot token. Check this bot's secret; token value was not logged.",
    )
    return RuntimeError("Telegram rejected the configured bot token. Check this bot's secret.")


async def initialize_app(app, db, stop):
    """Initialize Telegram with bounded network retries and fatal-token classification."""
    for attempt in range(5):
        try:
            await app.initialize()
            return
        except InvalidToken:
            stop.set()
            raise _invalid_token_failure(db) from None
        except NetworkError:
            await asyncio.sleep(min(60, 2**attempt) + random.random())
    raise RuntimeError("Telegram is unavailable; host restart may be required.")


def build(config, db):
    bot = StyledExtBot(
        token=config.token,
        request=HTTPXRequest(
            connect_timeout=10, read_timeout=25, write_timeout=25, pool_timeout=10),
        get_updates_request=HTTPXRequest(
            connect_timeout=10, read_timeout=35, write_timeout=25, pool_timeout=10),
    )
    app = Application.builder().bot(bot).concurrent_updates(False).build()
    health = Health(db, config, app.bot)
    publisher = Publisher(db, config, app.bot)
    support_api = SupportApiClient.from_environment(
        isolated_test=config.isolated_test,
        database_schema=db.schema,
        bot="signals",
    )
    ui = Handlers(db, config, app.bot, publisher, health, support_api=support_api)
    app.bot_data["smh_support_api"] = support_api
    app.bot_data["smh_ui"] = ui
    app.add_handler(CommandHandler(
        ["start", "myid", "admin", "health", "help", "cancel", "apply", "status",
         "education", "analysis", "pro", "contact", "assistant", "faq", "reply", "stop"],
        ui.command, filters.ChatType.PRIVATE,
    ))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.COMMAND, ui.unknown_command))
    app.add_handler(CallbackQueryHandler(ui.callback))
    app.add_handler(ChatJoinRequestHandler(ui.join_request))
    app.add_handler(ChatMemberHandler(ui.membership_event, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, ui.discover_channel))
    app.add_handler(MessageHandler(filters.ChatType.SUPERGROUP, ui.record_education_topic_post))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.ALL), ui.photo))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, ui.text))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.TEXT & ~filters.PHOTO & ~filters.Document.ALL,
        ui.unsupported_message,
    ))

    async def error(update, context):
        exc = context.error
        message = friendly_error(exc)
        # No raw provider exceptions, user content, or token-containing request URLs.
        logging.getLogger("smh").warning(f"handler_error:{type(exc).__name__}")
        try:
            db.error(type(exc).__name__, "Handler rejected input or encountered an error; review the affected operation.")
        except Exception:
            logging.getLogger("smh").error("error_record_unavailable")
        if update and update.effective_chat and update.effective_chat.type == "private":
            try:
                await app.bot.send_message(update.effective_chat.id, message)
            except Exception:
                logging.getLogger("smh").warning("error_reply_unavailable")
    app.add_error_handler(error)
    return app, ui, publisher, health


async def poll(app, db, health, stop):
    delay = 1
    while not stop.is_set():
        try:
            updates = await app.bot.get_updates(offset=db.get("telegram_offset", 0), timeout=25,
                                               allowed_updates=Update.ALL_TYPES)
            health.poll_success = time.monotonic()
            delay = 1
            ui = getattr(app, "bot_data", {}).get("smh_ui")
            if ui:
                await ui.refresh_expired_setup()
            for update in updates:
                # Serial dispatch; offset advances only after the update finishes.
                await app.process_update(update)
                db.put("telegram_offset", update.update_id+1)
                health.last_update = now()
                db.put("last_update", health.last_update)
                health.poll_success = time.monotonic()
        except RetryAfter as exc:
            seconds = exc.retry_after.total_seconds() if hasattr(exc.retry_after, "total_seconds") else exc.retry_after
            # Respect Telegram's requested delay, even above our network backoff cap.
            health.poll_success = time.monotonic() + seconds
            await asyncio.sleep(seconds + random.uniform(.1, 1))
        except InvalidToken:
            stop.set()
            raise _invalid_token_failure(db) from None
        except Conflict:
            try:
                webhook = await app.bot.get_webhook_info()
                if webhook.url:
                    category = "polling_webhook_conflict"
                    detail = ("A webhook is configured while this bot is attempting polling. "
                              "No webhook changes were made.")
                else:
                    category = "polling_session_conflict"
                    detail = ("Telegram reports another getUpdates polling session for this bot. "
                              "Stop the other process or host before polling here.")
            except Exception as probe_error:
                category = "polling_conflict_unclassified"
                detail = ("Telegram reported a polling conflict, but webhook status could not be checked "
                          f"({type(probe_error).__name__}). No webhook changes were made.")
            _record_polling_failure(db, category, detail)
            stop.set()
            raise RuntimeError("Telegram polling conflict. Check webhook status and whether another host is polling.") from None
        except Exception as exc:
            logging.getLogger("smh").warning(f"poll_retry:{type(exc).__name__}")
            try:
                db.error("poll_retry", f"Transient polling/storage failure ({type(exc).__name__}); retry scheduled.")
            except Exception:
                pass
            await asyncio.sleep(delay + random.uniform(0, 1))
            delay = min(60, delay * 2)


async def run(config):
    os.umask(0o077)
    lock = lock_process(config)
    db = Database(config.data, config.database_url or None, schema=config.database_schema)
    db.education_video_data_dir = config.education_video_data_dir
    config.education_video_data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if db.postgres and not db.conn.execute("SELECT pg_try_advisory_lock(hashtext(current_schema()),8219442)").fetchone()[0]:
        raise RuntimeError("Another worker is using this database.")
    log = setup_logging(config.data)
    if db.integrity() != "ok":
        raise RuntimeError("Database integrity failed. Restore a verified backup before starting.")
    manual_expiry_count = len(make_active_expiry_manual(db))
    if manual_expiry_count:
        logging.getLogger("smh").info("active_zones_set_to_manual_expiry:%s", manual_expiry_count)
    app, ui, publisher, health = build(config, db)
    publisher.recover()
    recover_education_video_posts(db)
    recover_education_onboarding(db)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await initialize_app(app, db, stop)
    await app.start()
    try:
        await publisher.verify_destinations()
        log.info("identities_and_channel_permissions_verified:publishing_" + ("enabled" if config.allow_publishing else "locked"))
    except Exception:
        log.warning("verification_failed:publishing_locked")
    if config.ready:
        for channel in (config.signals, config.analysis):
            try:
                member = await app.bot.get_chat_member(channel, app.bot.id)
                if member.status not in ("administrator", "creator") or (
                    member.status == "administrator" and not all(
                        getattr(member, key, False) for key in ("can_post_messages", "can_edit_messages", "can_invite_users"))):
                    db.error("channel_permissions", "Bot needs Post Messages, Edit Messages, and Invite Users in both channels.")
                    await health.alert("Channel permissions are incomplete. Grant Post Messages, Edit Messages, and Invite Users in both channels.")
            except Exception:
                db.error("channel_access", "A configured channel is inaccessible. Verify its ID and bot administrator permissions.")
    log.info("bot_ready" if config.ready else "discovery_mode_ready:use_/myid")
    polling = asyncio.create_task(poll(app, db, health, stop))
    monitor = asyncio.create_task(health.run())
    support_api = app.bot_data.get("smh_support_api")
    support_worker = asyncio.create_task(
        run_portal_reply_worker(db, app.bot, stop, support_api=support_api)
    )
    trade_worker = asyncio.create_task(
        run_portal_trade_command_worker(db, publisher, config, stop)
    )
    signal_worker = None
    if config.isolated_test and db.schema == "smh_test":
        signal_worker = asyncio.create_task(
            run_portal_signal_command_worker(db, publisher, config, app.bot, stop)
        )
    video_worker = asyncio.create_task(
        run_education_video_worker(db, app.bot, config, stop)
    )
    followup_worker = asyncio.create_task(
        run_applicant_followup_worker(db, config, app.bot, stop)
    )
    education_onboarding_worker = None
    if config.education_onboarding_enabled:
        education_onboarding_worker = asyncio.create_task(
            run_education_onboarding_worker(db, app.bot, config, stop)
        )
    review_worker = None
    if config.isolated_test and config.database_schema == "smh_test":
        review_worker = asyncio.create_task(
            run_portal_member_review_worker(db, ui, publisher, config, stop)
        )
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass
            if stop.is_set():
                break
            for name, task, heartbeat in (("poll", polling, health.poll_success), ("monitor", monitor, health.heartbeat)):
                if task.done() or time.monotonic() - heartbeat > 240:
                    log.warning(f"watchdog_restart:{name}")
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=10)
                    except (asyncio.CancelledError, Exception):
                        pass
                    db.error("watchdog_recovery", f"Restarted {name}; uncertain operations are quarantined.")
                    if name == "poll":
                        publisher.recover()
                        health.poll_success = time.monotonic()
                        polling = asyncio.create_task(poll(app, db, health, stop))
                    else:
                        health.heartbeat = time.monotonic()
                        monitor = asyncio.create_task(health.run())
                    await health.alert(f"Smart Money Hub restarted its {name} task. Inspect Operations > Health.")
            if support_worker.done() and not stop.is_set():
                log.warning("watchdog_restart:support_reply_worker")
                try:
                    await support_worker
                except Exception:
                    pass
                db.error("watchdog_recovery", "Restarted support reply worker; uncertain sends are not replayed.")
                support_worker = asyncio.create_task(
                    run_portal_reply_worker(db, app.bot, stop, support_api=support_api)
                )
                await health.alert("Smart Money Hub restarted its support reply worker. Check the support portal.")
            if trade_worker.done() and not stop.is_set():
                log.warning("watchdog_restart:portal_trade_worker")
                try:
                    await trade_worker
                except Exception:
                    pass
                db.error("watchdog_recovery", "Restarted portal trade worker; uncertain Telegram sends are not replayed.")
                trade_worker = asyncio.create_task(
                    run_portal_trade_command_worker(db, publisher, config, stop)
                )
            if signal_worker and signal_worker.done() and not stop.is_set():
                log.warning("watchdog_restart:portal_signal_worker")
                try:
                    await signal_worker
                except Exception:
                    pass
                db.error("watchdog_recovery", "Restarted isolated portal signal worker; uncertain sends are not replayed.")
                signal_worker = asyncio.create_task(
                    run_portal_signal_command_worker(db, publisher, config, app.bot, stop)
                )
            if video_worker.done() and not stop.is_set():
                log.warning("watchdog_restart:education_video_worker")
                try:
                    await video_worker
                except Exception:
                    pass
                db.error("watchdog_recovery", "Restarted the video worker; uncertain video sends are not replayed.")
                video_worker = asyncio.create_task(
                    run_education_video_worker(db, app.bot, config, stop)
                )
            if followup_worker.done() and not stop.is_set():
                log.warning("watchdog_restart:applicant_followup_worker")
                try:
                    await followup_worker
                except Exception:
                    pass
                db.error("watchdog_recovery", "Restarted applicant follow-up worker; uncertain sends are not replayed.")
                followup_worker = asyncio.create_task(
                    run_applicant_followup_worker(db, config, app.bot, stop)
                )
            if education_onboarding_worker and education_onboarding_worker.done() and not stop.is_set():
                log.warning("watchdog_restart:education_onboarding_worker")
                try:
                    await education_onboarding_worker
                except Exception:
                    pass
                db.error("watchdog_recovery", "Restarted Education onboarding worker; uncertain deliveries are not replayed.")
                education_onboarding_worker = asyncio.create_task(
                    run_education_onboarding_worker(db, app.bot, config, stop)
                )
            if review_worker and review_worker.done() and not stop.is_set():
                log.warning("watchdog_restart:portal_pro_review_worker")
                try:
                    await review_worker
                except Exception:
                    pass
                db.error("watchdog_recovery", "Restarted isolated portal PRO review worker; uncertain decisions are not replayed.")
                review_worker = asyncio.create_task(
                    run_portal_member_review_worker(db, ui, publisher, config, stop)
                )
    finally:
        background_tasks = [
            polling, monitor, support_worker, trade_worker, video_worker, followup_worker
        ]
        if education_onboarding_worker:
            background_tasks.append(education_onboarding_worker)
        if signal_worker:
            background_tasks.append(signal_worker)
        if review_worker:
            background_tasks.append(review_worker)
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        await app.stop()
        await app.shutdown()
        try:
            publisher.recover()
            db.backup(config.retention)
        finally:
            db.conn.close()
            lock.close()
        log.info("shutdown_complete")


def main():
    try:
        asyncio.run(run(Config.load()))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Do not print exception messages: network errors can contain the token.
        print(f"Bot stopped safely ({type(exc).__name__}). Check configuration, storage, and the private diagnostic log.")
        raise SystemExit(1) from None
