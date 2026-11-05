"""Telegram-native text emphasis for bot messages and media captions."""
import inspect
import re

from telegram import MessageEntity
from telegram.ext import ExtBot


def telegram_text_entities(text):
    """Bold the first heading and short field labels without changing visible text."""
    if not text:
        return []
    entities = []

    def add_bold(start, end):
        if end <= start:
            return
        offset = len(text[:start].encode("utf-16-le")) // 2
        length = len(text[start:end].encode("utf-16-le")) // 2
        entities.append(MessageEntity(MessageEntity.BOLD, offset, length))

    lines = text.splitlines(keepends=True)
    cursor = 0
    first_content_line = None
    for line in lines:
        visible = line.rstrip("\r\n")
        if visible.strip():
            first_content_line = (cursor, cursor + len(visible))
            break
        cursor += len(line)
    if first_content_line:
        start, end = first_content_line
        if end - start <= 160:
            add_bold(start, end)

    cursor = 0
    for line in lines:
        visible = line.rstrip("\r\n")
        if visible.strip() and (not first_content_line or cursor != first_content_line[0]):
            match = re.match(r"^(\s*[^:\n]{1,48}):", visible)
            if match and "://" not in match.group(1):
                add_bold(cursor + match.start(1), cursor + match.end(1))
        cursor += len(line)
    return entities


def styled_call_arguments(method, args, kwargs, text_parameter, entities_parameter):
    """Add safe native emphasis to a plain-text Telegram method call."""
    bound = inspect.signature(method).bind_partial(*args, **kwargs)
    text = bound.arguments.get(text_parameter)
    parse_mode = bound.arguments.get("parse_mode")
    if (isinstance(text, str) and parse_mode is None
            and not bound.arguments.get(entities_parameter)):
        entities = telegram_text_entities(text)
        if entities:
            bound.arguments[entities_parameter] = entities
    return bound.args, bound.kwargs


class StyledExtBot(ExtBot):
    """ExtBot that adds Telegram bold entities to plain text and captions."""

    async def _send_styled(self, method_name, text_parameter, entities_parameter, *args, **kwargs):
        method = getattr(super(), method_name)
        args, kwargs = styled_call_arguments(
            method, args, kwargs, text_parameter, entities_parameter)
        return await method(*args, **kwargs)

    async def send_message(self, *args, **kwargs):
        return await self._send_styled("send_message", "text", "entities", *args, **kwargs)

    async def edit_message_text(self, *args, **kwargs):
        return await self._send_styled("edit_message_text", "text", "entities", *args, **kwargs)

    async def send_photo(self, *args, **kwargs):
        return await self._send_styled("send_photo", "caption", "caption_entities", *args, **kwargs)

    async def send_video(self, *args, **kwargs):
        return await self._send_styled("send_video", "caption", "caption_entities", *args, **kwargs)

    async def send_document(self, *args, **kwargs):
        return await self._send_styled("send_document", "caption", "caption_entities", *args, **kwargs)

    async def edit_message_caption(self, *args, **kwargs):
        return await self._send_styled("edit_message_caption", "caption", "caption_entities", *args, **kwargs)
