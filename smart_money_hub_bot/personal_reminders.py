"""Small, deterministic parser for one-time member reminders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


_REQUEST_PREFIX = re.compile(
    r"^\s*(?:please\s+)?(?:remind\s+me(?:\s+to)?|"
    r"set\s+(?:a\s+)?reminder(?:\s+to)?|/remind(?:@\w+)?)\b\s*",
    re.IGNORECASE,
)
_RELATIVE = re.compile(
    r"\bin\s+(?P<count>\d{1,4})\s+"
    r"(?P<unit>minutes?|mins?|hours?|hrs?|days?)\s*$",
    re.IGNORECASE,
)
_DATE = re.compile(r"\b(?P<date>today|tomorrow|on\s+\d{4}-\d{2}-\d{2})\b", re.I)
_TIME = re.compile(
    r"\b(?P<time>(?:\d{1,2}(?::\d{2})?\s*[ap]m)|"
    r"(?:[01]\d|2[0-3]):[0-5]\d)\b",
    re.IGNORECASE,
)
_AT_TIME = re.compile(r"\bat\s+(?P<time>.+?)\s*$", re.IGNORECASE)
_TIME_TOKEN = re.compile(
    r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReminderTiming:
    due_at: datetime | None
    start: int
    needs: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ReminderRequest:
    task: str
    due_at: datetime | None
    needs: str | None = None
    error: str | None = None


def parse_reminder_timing(
    text: str, now: datetime, zone: Any
) -> ReminderTiming | None:
    """Parse an unambiguous relative or calendar time, requiring no guesses."""
    relative = _RELATIVE.search(text)
    if relative:
        count = int(relative.group("count"))
        if count <= 0:
            return ReminderTiming(None, relative.start(), error="invalid_time")
        unit = relative.group("unit").casefold()
        if unit.startswith(("min",)):
            delta = timedelta(minutes=count)
        elif unit.startswith(("hour", "hr")):
            delta = timedelta(hours=count)
        else:
            delta = timedelta(days=count)
        if delta > timedelta(days=365):
            return ReminderTiming(None, relative.start(), error="too_far")
        due_at = now.astimezone(zone) + delta
        return _validate_due(due_at, relative.start(), now, zone)

    date_match = _DATE.search(text)
    at_time = _AT_TIME.search(text)
    time_match = _TIME.search(at_time.group("time")) if at_time else None
    time_phrase_start = None
    if at_time and time_match:
        time_offset = at_time.start("time") + time_match.start()
        at_markers = list(re.finditer(r"\bat\s+", text[:time_offset], re.IGNORECASE))
        if at_markers:
            time_phrase_start = at_markers[-1].start()

    if date_match:
        if not at_time:
            return ReminderTiming(None, date_match.start(), needs="time")
        if not time_match or not _valid_time(time_match.group("time")):
            return ReminderTiming(None, date_match.start(), error="invalid_time")
        timing_start = min(
            date_match.start(),
            time_phrase_start if time_phrase_start is not None else date_match.start(),
        )
        date_text = date_match.group("date").casefold()
        local_now = now.astimezone(zone)
        if date_text == "today":
            reminder_date = local_now.date()
        elif date_text == "tomorrow":
            reminder_date = local_now.date() + timedelta(days=1)
        else:
            try:
                reminder_date = datetime.strptime(date_text[3:].strip(), "%Y-%m-%d").date()
            except ValueError:
                return ReminderTiming(None, date_match.start(), error="invalid_date")
        parsed_time = _parse_clock_time(time_match.group("time"))
        if parsed_time is None:
            return ReminderTiming(None, date_match.start(), error="invalid_time")
        due_at = datetime.combine(reminder_date, parsed_time, tzinfo=zone)
        return _validate_due(due_at, timing_start, now, zone)

    if at_time:
        if not time_match or not _valid_time(time_match.group("time")):
            return ReminderTiming(
                None,
                time_phrase_start if time_phrase_start is not None else at_time.start(),
                needs="date",
            )
        return ReminderTiming(
            None,
            time_phrase_start if time_phrase_start is not None else at_time.start(),
            needs="date",
        )
    return None


def parse_personal_reminder_request(
    text: str, now: datetime, zone: Any
) -> ReminderRequest | None:
    """Recognize a reminder request; return None for ordinary chat."""
    prefix = _REQUEST_PREFIX.match(text)
    if not prefix:
        return None
    body = text[prefix.end() :].strip()
    timing = parse_reminder_timing(body, now, zone)
    if timing is None:
        task = _clean_task(body)
        return ReminderRequest(task=task, due_at=None, needs="time")
    task = _clean_task(body[: timing.start])
    return ReminderRequest(
        task=task,
        due_at=timing.due_at,
        needs=timing.needs,
        error=timing.error,
    )


def _clean_task(task: str) -> str:
    cleaned = task.strip().strip(" ,.!—-")
    if cleaned.casefold().startswith("to "):
        cleaned = cleaned[3:].strip()
    return cleaned


def _validate_due(
    due_at: datetime, start: int, now: datetime, zone: Any
) -> ReminderTiming:
    local_due = due_at.astimezone(zone)
    local_now = now.astimezone(zone)
    if local_due <= local_now + timedelta(minutes=1):
        return ReminderTiming(None, start, error="not_future")
    if local_due > local_now + timedelta(days=365):
        return ReminderTiming(None, start, error="too_far")
    return ReminderTiming(local_due, start)


def _valid_time(value: str) -> bool:
    return _parse_clock_time(value) is not None


def _parse_clock_time(value: str):
    match = _TIME_TOKEN.fullmatch(value.strip())
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").casefold()
    if minute > 59:
        return None
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif not (":" in value and 0 <= hour <= 23):
        return None
    from datetime import time

    return time(hour, minute)
