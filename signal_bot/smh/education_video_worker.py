"""One-shot-safe publisher for owner-approved Educational Group video posts."""
import asyncio
import html
import logging
import re
import uuid

from telegram.error import NetworkError

from .config import _private_forum_message_target
from .database import now


_STORAGE_NAME = re.compile(r"^[a-f0-9]{32}\.mp4$")


def recover_education_video_posts(db):
    """Quarantine in-flight posts after restart; never replay an uncertain send."""
    stamp = now()
    with db.transaction() as conn:
        cursor = conn.execute(
            "UPDATE education_video_posts SET status='uncertain',updated=?,safe_result=? "
            "WHERE status='sending' RETURNING id",
            (stamp, "The bot restarted while delivery was in progress. Check the topic before posting again."),
        )
        recovered = cursor.fetchall()
        for row in recovered:
            conn.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "VALUES(?,NULL,'education_video_uncertain',?,?,?)",
                ("video-recovery-" + uuid.uuid4().hex, row["id"], stamp,
                 "In-flight video send was quarantined after restart; it was not retried."),
            )
    return len(recovered)


def _finish(db, video_id, status, safe_result, *, message_id=None):
    stamp = now()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE education_video_posts SET status=?,safe_result=?,telegram_message_id=?,"
            "published_at=?,updated=? WHERE id=? AND status='sending'",
            (status, safe_result, message_id,
             stamp if status == "published" else None, stamp, video_id),
        )
        conn.execute(
            "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
            "VALUES(?,?,?,?,?,?)",
            ("video-" + video_id, None, "education_video_" + status, video_id, stamp, safe_result),
        )


def _allowed_target(row, config):
    target_chat = getattr(config, "education_video_group_id", 0)
    target_thread = getattr(config, "education_video_topic_id", 0)
    if not config.allow_publishing:
        return False, "Publishing is locked; no Telegram request was sent."
    if not target_chat or not target_thread:
        return False, "The Video tutorials destination and topic are not configured."
    if target_chat in (config.signals, config.analysis):
        return False, "The video destination must be separate from PRO Signals and Market Analysis."
    if target_chat == getattr(config, "education_group_id", 0):
        if not getattr(config, "isolated_test", False):
            return False, "Only the isolated test environment may use a separate Video tutorials topic in the Education forum."
        protected_topics = {
            parsed[1]
            for url in (
                getattr(config, "education_announcement_url", ""),
                getattr(config, "education_episode_01_url", ""),
            )
            if (parsed := _private_forum_message_target(url))
            and parsed[0] == target_chat
        }
        if len(protected_topics) < 2 or target_thread in protected_topics:
            return False, "The Video tutorials topic must be distinct from the Education lesson and announcement topics."
    if (int(row["target_chat_id"] or 0) != target_chat or
            int(row["target_thread_id"] or 0) != target_thread):
        return False, "The saved destination does not match the configured Video tutorials topic."
    return True, ""


async def process_education_video_once(db, bot, config):
    rows = db.rows(
        "SELECT * FROM education_video_posts WHERE status='queued' ORDER BY created,id LIMIT 1"
    )
    if not rows:
        return False
    row = rows[0]
    video_id = row["id"]
    with db.transaction() as conn:
        claimed = conn.execute(
            "UPDATE education_video_posts SET status='sending',attempt_count=attempt_count+1,updated=? "
            "WHERE id=? AND status='queued'",
            (now(), video_id),
        )
        if claimed.rowcount != 1:
            return False

    permitted, reason = _allowed_target(row, config)
    if not permitted:
        _finish(db, video_id, "blocked", reason)
        return True

    storage_name = str(row["storage_name"])
    if not _STORAGE_NAME.fullmatch(storage_name):
        _finish(db, video_id, "failed", "The saved video file reference is invalid.")
        return True
    path = (config.education_video_data_dir / storage_name).resolve()
    root = config.education_video_data_dir.resolve()
    if path.parent != root or not path.is_file() or path.stat().st_size != int(row["byte_size"]):
        _finish(db, video_id, "failed", "The saved video file is missing or failed its size check.")
        return True

    # Preflight reads destination metadata only; it never sends a Telegram message.
    try:
        chat = await bot.get_chat(config.education_video_group_id)
        if (chat.id != config.education_video_group_id or
                getattr(chat, "type", "") not in ("group", "supergroup") or
                not getattr(chat, "is_forum", False)):
            _finish(db, video_id, "blocked", "The configured video destination is not the expected forum.")
            return True
        if config.isolated_test and getattr(chat, "username", None):
            _finish(db, video_id, "blocked", "The isolated test video destination must be private.")
            return True
        bot_member = await bot.get_chat_member(config.education_video_group_id, bot.id)
        if getattr(bot_member, "status", "") not in ("administrator", "creator"):
            _finish(db, video_id, "blocked", "The bot is not an administrator in the configured video destination.")
            return True
    except Exception:
        _finish(db, video_id, "blocked", "The video destination could not be verified. No video was sent.")
        return True

    caption = f"<b>{html.escape(row['title'])}</b>\n\n{html.escape(row['caption'])}"
    try:
        with path.open("rb") as video_file:
            message = await bot.send_video(
                chat_id=config.education_video_group_id,
                message_thread_id=config.education_video_topic_id,
                video=video_file,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
            )
    except (NetworkError, asyncio.TimeoutError, TimeoutError):
        _finish(
            db, video_id, "uncertain",
            "Telegram delivery is uncertain. Check the Video tutorials topic before taking any further action.",
        )
        db.error("education_video_uncertain",
                 "Telegram may have received the video; automatic retries are disabled.")
        return True
    except Exception:
        _finish(db, video_id, "failed", "Telegram rejected the video. No automatic retry was made.")
        db.error("education_video_failed", "Telegram did not accept the video post.")
        return True

    _finish(
        db, video_id, "published", f"Published to {row['target_topic_name']}.",
        message_id=getattr(message, "message_id", None),
    )
    return True


async def run_education_video_worker(db, bot, config, stop_event, interval=5):
    while not stop_event.is_set():
        try:
            worked = await process_education_video_once(db, bot, config)
        except Exception:
            logging.getLogger("smh").error("education_video_worker_failed")
            try:
                db.error("education_video_worker", "The video worker failed safely; inspect its status before retrying.")
            except Exception:
                pass
            worked = False
        if worked:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
