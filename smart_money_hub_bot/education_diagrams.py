"""Admin-managed SMC diagram images for private Coach replies."""

from __future__ import annotations

import re
from typing import Any

from .storage import Repository
from .telegram_api import TelegramAPI


class EducationDiagramManager:
    def __init__(
        self,
        api: TelegramAPI,
        store: Repository,
        admin_id: int | None,
    ) -> None:
        self.api = api
        self.store = store
        self.admin_id = admin_id
        self._upload_pending: set[int] = set()

    def is_upload_pending(self, telegram_id: int) -> bool:
        return telegram_id in self._upload_pending

    def cancel_upload(self, telegram_id: int) -> None:
        self._upload_pending.discard(telegram_id)

    def handle_callback(
        self, chat_id: int, telegram_id: int, is_private: bool, data: str
    ) -> None:
        if not self._authorized(chat_id, telegram_id, is_private):
            return
        if data in {"admin:education_diagrams", "admin:education_diagrams:list"}:
            self._show_library(chat_id)
            return
        if data == "admin:education_diagrams:add":
            self._upload_pending.add(telegram_id)
            self.api.send_message(
                chat_id,
                "Send a diagram image with this caption format:\n"
                "TITLE | TAGS | optional short explanation\n\n"
                "Example: BOS | BOS, break of structure, market structure | "
                "A close beyond a relevant swing.\n\n"
                "The image will be offered in private Coach chats when the "
                "matching concept is asked about. It will not be posted to a "
                "channel or group. Send /cancel to stop.",
            )
            return
        if data == "admin:education_diagrams:cancel":
            self.cancel_upload(telegram_id)
            self._show_library(chat_id, notice="Diagram upload cancelled.")
            return
        match = re.fullmatch(r"admin:education_diagrams:hide:(\d{1,8})", data)
        if match:
            hidden = self.store.deactivate_education_diagram(int(match.group(1)))
            self._show_library(
                chat_id,
                notice=(
                    "That diagram is hidden from Coach replies; its stored record "
                    "was retained."
                    if hidden
                    else "That diagram is already hidden or was not found."
                ),
            )

    def handle_admin_photo(
        self,
        chat_id: int,
        telegram_id: int,
        photos: list[Any],
        *,
        caption: str,
        is_private: bool,
    ) -> bool:
        if not self.is_upload_pending(telegram_id):
            return False
        if not self._authorized(chat_id, telegram_id, is_private):
            self.cancel_upload(telegram_id)
            return True
        photo_id = self._largest_photo_file_id(photos)
        parts = [part.strip() for part in caption.split("|", maxsplit=2)]
        if not photo_id or len(parts) < 2 or not parts[0] or not parts[1]:
            self.api.send_message(
                chat_id,
                "I didn’t save that image. Add a caption with a title and tags, "
                "for example: BOS | break of structure, BOS. Send the image again "
                "with its caption, or /cancel.",
            )
            return True
        title, tags = parts[0], parts[1]
        description = parts[2] if len(parts) == 3 else ""
        try:
            diagram_id = self.store.add_education_diagram(
                title=title,
                tags=tags,
                description=description,
                photo_file_id=photo_id,
                admin_telegram_id=telegram_id,
            )
        except ValueError:
            self.api.send_message(
                chat_id,
                "I couldn’t save that diagram. Check the title and tags, then send "
                "the image again with its caption.",
            )
            return True
        self.cancel_upload(telegram_id)
        self._show_library(
            chat_id,
            notice=f"Saved “{title[:120]}” as diagram {diagram_id}.",
        )
        return True

    def diagram_for_question(self, question: str) -> dict[str, Any] | None:
        return self.store.matching_education_diagram(question)

    def _show_library(self, chat_id: int, *, notice: str | None = None) -> None:
        diagrams = self.store.education_diagrams()
        lines = [
            "📊 LEARNING DIAGRAMS",
            "Saved images are sent only in private Coach chats when a matching "
            "concept is asked about. They are never posted to a channel or group.",
            "",
        ]
        if notice:
            lines.extend([notice, ""])
        if diagrams:
            lines.append("Active diagrams:")
            rows: list[list[dict[str, str]]] = []
            for item in diagrams[:20]:
                title = " ".join(str(item.get("title") or "").split())[:55]
                tags = " ".join(str(item.get("tags") or "").split())[:90]
                lines.append(f"• {title} — {tags}")
                rows.append(
                    [
                        {
                            "text": f"Hide: {title[:35]}",
                            "callback_data": (
                                f"admin:education_diagrams:hide:{int(item['id'])}"
                            ),
                        }
                    ]
                )
        else:
            lines.append("No diagrams have been added yet.")
            rows = []
        rows.extend(
            [
                [
                    {
                        "text": "➕ Add diagram",
                        "callback_data": "admin:education_diagrams:add",
                    },
                    {
                        "text": "🔄 Refresh",
                        "callback_data": "admin:education_diagrams:list",
                    },
                ],
                [{"text": "Admin menu", "callback_data": "admin:home"}],
            ]
        )
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            {"inline_keyboard": rows},
        )

    def _authorized(
        self, chat_id: int, telegram_id: int, is_private: bool
    ) -> bool:
        return (
            is_private
            and self.admin_id is not None
            and telegram_id == self.admin_id
            and chat_id == telegram_id
        )

    @staticmethod
    def _largest_photo_file_id(photos: list[Any]) -> str | None:
        if not isinstance(photos, list):
            return None
        for photo in reversed(photos):
            if not isinstance(photo, dict):
                continue
            file_id = photo.get("file_id")
            if isinstance(file_id, str) and file_id.strip():
                return file_id.strip()
        return None
