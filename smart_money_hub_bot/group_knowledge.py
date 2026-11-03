"""Privacy-conscious helpers for archiving and retrieving education-group posts."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

_COMMAND_START = re.compile(r"^/[a-z0-9_]+(?:@[a-z0-9_]+)?(?:\s|$)", re.I)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_'-]{1,}", re.I)
_QUESTION_REDACTIONS = (
    (re.compile(r"@[A-Za-z0-9_]{3,}"), "[mention]"),
    (re.compile(r"https?://\S+|t\.me/\S+", re.I), "[link]"),
    (re.compile(r"\b\d{7,}\b"), "[number]"),
)
_ARCHIVE_REDACTIONS = (
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    (re.compile(r"@[A-Za-z0-9_]{3,}"), "[mention]"),
    (re.compile(r"https?://t\.me/\S+|t\.me/\S+", re.I), "[Telegram link]"),
    (re.compile(r"\b\d{7,}\b"), "[number]"),
)


def topic_update_from_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Extract topic names only from Telegram's explicit forum-topic service fields."""
    topic_event = message.get("forum_topic_created") or message.get("forum_topic_edited")
    if not isinstance(topic_event, dict):
        return None
    name = topic_event.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    thread_id = message.get("message_thread_id")
    if not isinstance(thread_id, int) or isinstance(thread_id, bool):
        thread_id = message.get("message_id")
    if not isinstance(thread_id, int) or isinstance(thread_id, bool):
        return None
    return {"thread_id": thread_id, "topic_name": " ".join(name.split())[:120]}


def archived_group_post(
    message: dict[str, Any],
    *,
    configured_admin_id: int | None,
    bot_username: str = "SmartMoneyHubSignalsBot",
) -> dict[str, Any] | None:
    """Return a bounded post record without storing sender IDs or usernames."""
    sender = message.get("from")
    sender = sender if isinstance(sender, dict) else {}
    if sender.get("is_bot") is True:
        return None

    poll = message.get("poll")
    if isinstance(poll, dict):
        content, kind = _format_poll(poll), "poll"
    else:
        text = message.get("text") or message.get("caption")
        if not isinstance(text, str) or not text.strip():
            return None
        if _COMMAND_START.match(text.strip()):
            return None
        content = text.strip()
        kind = "caption" if message.get("caption") else "text"
        if addressed_group_question(message, bot_username=bot_username):
            return None

    message_id = message.get("message_id")
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        return None
    thread_id = message.get("message_thread_id")
    if not isinstance(thread_id, int) or isinstance(thread_id, bool):
        thread_id = None
    timestamp = message.get("date")
    try:
        posted_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        posted_at = ""

    sender_id = sender.get("id")
    source_status = (
        "configured_admin"
        if configured_admin_id is not None and sender_id == configured_admin_id
        else "unverified"
    )
    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "message_kind": kind,
        "content": sanitize_archive_content(content)[:6000],
        "source_status": source_status,
        "posted_at": posted_at,
        "poll_id": str(poll.get("id")) if isinstance(poll, dict) and poll.get("id") else None,
    }


def education_resource_from_message(
    message: dict[str, Any], *, configured_admin_id: int | None
) -> dict[str, Any] | None:
    """Index only admin-posted PDF/video metadata and a safe Telegram message link."""
    sender = message.get("from")
    sender = sender if isinstance(sender, dict) else {}
    if (
        configured_admin_id is None
        or sender.get("is_bot") is True
        or sender.get("id") != configured_admin_id
    ):
        return None

    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("type") not in {"group", "supergroup"}:
        return None
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if (
        not isinstance(chat_id, int)
        or isinstance(chat_id, bool)
        or not isinstance(message_id, int)
        or isinstance(message_id, bool)
        or message_id <= 0
    ):
        return None

    document = message.get("document")
    video = message.get("video")
    if not isinstance(document, dict):
        document = None
    if not isinstance(video, dict):
        video = None

    file_data = document or video
    if file_data is None:
        return None
    filename = " ".join(str(file_data.get("file_name") or "").split())[:200]
    mime_type = str(file_data.get("mime_type") or "").casefold()
    suffix = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if video is not None or mime_type.startswith("video/") or suffix in {
        "mp4",
        "mov",
        "m4v",
        "webm",
        "mkv",
    }:
        resource_type = "video"
    elif mime_type == "application/pdf" or suffix == "pdf":
        resource_type = "pdf"
    else:
        return None

    caption = message.get("caption")
    caption = sanitize_archive_content(caption)[:1200] if isinstance(caption, str) else ""
    safe_filename = sanitize_archive_content(filename)[:200]
    title = (caption.splitlines()[0].strip() if caption else "") or safe_filename
    if not title:
        title = f"Education group {resource_type.upper()}"
    title = " ".join(title.split())[:180]
    description_parts = [safe_filename, caption]
    description = " ".join(part for part in description_parts if part).strip()[:1800]

    thread_id = message.get("message_thread_id")
    if not isinstance(thread_id, int) or isinstance(thread_id, bool) or thread_id <= 0:
        thread_id = None
    username = chat.get("username")
    if isinstance(username, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        base_link = f"https://t.me/{username}"
    else:
        chat_text = str(chat_id)
        if not chat_text.startswith("-100") or not chat_text[4:].isdigit():
            return None
        base_link = f"https://t.me/c/{chat_text[4:]}"
    message_link = (
        f"{base_link}/{thread_id}/{message_id}"
        if thread_id is not None
        else f"{base_link}/{message_id}"
    )

    timestamp = message.get("date")
    try:
        posted_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        posted_at = ""

    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "thread_id": thread_id,
        "resource_type": resource_type,
        "title": title,
        "description": description,
        "message_link": message_link,
        "posted_at": posted_at,
        "source_status": "configured_admin",
    }


def format_group_context(
    records: list[dict[str, Any]], *, max_items: int = 4, max_chars: int = 900
) -> list[dict[str, str]]:
    """Bound archive excerpts before they are passed to the Coach provider."""
    result: list[dict[str, str]] = []
    total_chars = 0
    for record in records[:max_items]:
        content = " ".join(str(record.get("content") or "").split())
        if not content:
            continue
        content = content[:max_chars]
        if total_chars + len(content) > 3200:
            break
        result.append(
            {
                "topic": str(record.get("topic_name") or "Topic not identified")[:120],
                "source_status": str(record.get("source_status") or "unverified"),
                "posted_at": str(record.get("posted_at") or "")[:40],
                "content": content,
            }
        )
        total_chars += len(content)
    return result


def addressed_group_question(
    message: dict[str, Any], *, bot_username: str
) -> str | None:
    """Return text only when a group message explicitly mentions or replies to this bot."""
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    username = bot_username.lstrip("@")
    mention = re.compile(rf"(?<!\w)@{re.escape(username)}\b", re.I)
    reply = message.get("reply_to_message")
    reply_from = reply.get("from") if isinstance(reply, dict) else None
    is_reply_to_bot = (
        isinstance(reply_from, dict)
        and reply_from.get("is_bot") is True
        and str(reply_from.get("username") or "").casefold() == username.casefold()
    )
    if not mention.search(text) and not is_reply_to_bot:
        return None
    cleaned = mention.sub("", text)
    cleaned = re.sub(r"^\s*[,;:—–-]+\s*", "", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def question_fingerprint(question: str) -> tuple[str, str]:
    """Create a dedupe key and a review-safe preview without Telegram identifiers."""
    cleaned = " ".join(question.split()).strip()
    for pattern, replacement in _QUESTION_REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    preview = cleaned[:500]
    normalized = re.sub(r"[^a-z0-9]+", " ", preview.casefold()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), preview


def sanitize_archive_content(content: str) -> str:
    """Remove common personal identifiers while preserving educational text."""
    sanitized = content
    for pattern, replacement in _ARCHIVE_REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized.strip()


def fts_query_terms(query: str, *, limit: int = 12) -> str:
    """Build a safely quoted FTS5 query from plain message text."""
    stop_words = {
        "am", "an", "as", "at", "be", "by", "do", "he", "if", "in", "it",
        "me", "my", "of", "on", "or", "so", "to", "up", "us", "we",
        "what", "when", "where", "which", "would", "could", "should", "does",
        "this", "that", "with", "from", "have", "your", "about", "explain",
        "tell", "please", "into", "were", "been", "will", "than", "then",
    }
    short_smc_terms = {"m5", "h1", "rr", "sl", "tp"}
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.finditer(query.casefold()):
        token = match.group(0)
        if token in stop_words or token in seen:
            continue
        if len(token) < 3 and token not in short_smc_terms:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return " OR ".join(f'"{token}"' for token in tokens)


def _format_poll(poll: dict[str, Any]) -> str:
    question = str(poll.get("question") or "Quiz poll").strip()
    options = poll.get("options")
    option_lines: list[str] = []
    if isinstance(options, list):
        for index, option in enumerate(options[:12]):
            if isinstance(option, dict):
                option_lines.append(f"{index + 1}. {str(option.get('text') or '')[:200]}")
    content = question
    if option_lines:
        content += "\nOptions:\n" + "\n".join(option_lines)
    correct = poll.get("correct_option_id")
    if isinstance(correct, int) and 0 <= correct < len(option_lines):
        content += f"\nCorrect option: {option_lines[correct].split('. ', 1)[-1]}"
    explanation = poll.get("explanation")
    if isinstance(explanation, str) and explanation.strip():
        content += f"\nExplanation: {explanation.strip()[:1200]}"
    return content[:6000]
