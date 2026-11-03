"""Small standard-library client for the Telegram Bot HTTP API."""

import json
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class TelegramAPIError(RuntimeError):
    """A Telegram API request failed without exposing the bot token."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        error_code: int | None = None,
        retry_after: int | None = None,
        delivery_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.error_code = error_code
        self.retry_after = retry_after
        self.delivery_unknown = delivery_unknown


class TelegramAPI:
    def __init__(self, token: str) -> None:
        if not token.strip():
            raise ValueError("A Telegram bot token is required.")
        self._base_url = f"https://api.telegram.org/bot{token.strip()}/"

    def _request(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 20,
    ) -> Any:
        body = json.dumps(payload or {}).encode("utf-8")
        request = Request(
            self._base_url + method,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                raw_response = response.read()
        except HTTPError as error:
            parsed: dict[str, Any] = {}
            try:
                error_body = error.read()
                body = json.loads(error_body.decode("utf-8"))
                if isinstance(body, dict):
                    parsed = body
                description = parsed.get("description", f"HTTP {error.code}")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                description = f"HTTP {error.code}"
            parameters = parsed.get("parameters")
            retry_after = (
                parameters.get("retry_after")
                if isinstance(parameters, dict)
                else None
            )
            raise TelegramAPIError(
                str(description),
                http_status=error.code,
                error_code=parsed.get("error_code"),
                retry_after=retry_after if isinstance(retry_after, int) else None,
            ) from None
        except (URLError, TimeoutError, OSError) as error:
            # Do not echo the request URL: it contains the private bot token.
            raise TelegramAPIError(
                "Telegram network request failed.",
                delivery_unknown=True,
            ) from None

        try:
            parsed_response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramAPIError(
                "Telegram returned an unreadable response.",
                delivery_unknown=True,
            ) from None

        if not isinstance(parsed_response, dict) or not parsed_response.get("ok"):
            description = (
                parsed_response.get("description", "Telegram request was not successful.")
                if isinstance(parsed_response, dict)
                else "Telegram returned an unexpected response."
            )
            parameters = (
                parsed_response.get("parameters")
                if isinstance(parsed_response, dict)
                else None
            )
            retry_after = (
                parameters.get("retry_after")
                if isinstance(parameters, dict)
                else None
            )
            raise TelegramAPIError(
                str(description),
                error_code=(
                    parsed_response.get("error_code")
                    if isinstance(parsed_response, dict)
                    else None
                ),
                retry_after=retry_after if isinstance(retry_after, int) else None,
            )

        return parsed_response.get("result")

    def get_me(self) -> dict[str, Any]:
        return self._request("getMe")

    def get_webhook_info(self) -> dict[str, Any]:
        result = self._request("getWebhookInfo")
        return result if isinstance(result, dict) else {}

    def get_chat(self, chat_id: int) -> dict[str, Any]:
        result = self._request("getChat", {"chat_id": chat_id})
        return result if isinstance(result, dict) else {}

    def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        result = self._request(
            "getChatMember",
            {"chat_id": chat_id, "user_id": user_id},
        )
        return result if isinstance(result, dict) else {}

    def get_file(self, file_id: str) -> dict[str, Any]:
        if not isinstance(file_id, str) or not file_id or len(file_id) > 512:
            raise TelegramAPIError("Telegram file reference is invalid.")
        result = self._request("getFile", {"file_id": file_id}, timeout=15)
        return result if isinstance(result, dict) else {}

    def download_file(
        self,
        file_path: str,
        *,
        max_bytes: int = 4_000_000,
    ) -> tuple[bytes, str]:
        """Download a Telegram file with a strict size cap and sanitized errors."""
        if (
            not isinstance(file_path, str)
            or not file_path
            or len(file_path) > 1024
            or file_path.startswith("/")
            or ".." in file_path.split("/")
            or max_bytes < 1
        ):
            raise TelegramAPIError("Telegram file reference is invalid.")
        file_base = self._base_url.replace(
            "https://api.telegram.org/bot",
            "https://api.telegram.org/file/bot",
            1,
        )
        file_url = file_base + quote(file_path, safe="/")
        request = Request(file_url, method="GET")
        try:
            with urlopen(request, timeout=20) as response:
                declared_size = response.headers.get("Content-Length")
                if declared_size and int(declared_size) > max_bytes:
                    raise TelegramAPIError("Telegram image exceeds the size limit.")
                content = response.read(max_bytes + 1)
                content_type = str(
                    response.headers.get("Content-Type", "application/octet-stream")
                ).split(";", 1)[0].strip().lower()
        except HTTPError:
            raise TelegramAPIError("Telegram file download was rejected.") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise TelegramAPIError("Telegram file download failed.") from None
        if len(content) > max_bytes:
            raise TelegramAPIError("Telegram image exceeds the size limit.")
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise TelegramAPIError("Telegram file is not a supported image.")
        return content, content_type

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": [
                "message",
                "edited_message",
                "callback_query",
                "channel_post",
                "edited_channel_post",
                "poll",
            ],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._request("getUpdates", payload, timeout=timeout + 10)
        return result if isinstance(result, list) else []

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        *,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        if business_connection_id is not None:
            payload["business_connection_id"] = business_connection_id
        self._request("sendMessage", payload)

    def send_message_with_result(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        *,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        if business_connection_id is not None:
            payload["business_connection_id"] = business_connection_id
        result = self._request("sendMessage", payload)
        return result if isinstance(result, dict) else {}

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Delete one Telegram message and return Telegram's confirmation."""
        result = self._request(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": message_id},
        )
        return result is True

    def send_photo_with_result(
        self,
        chat_id: int,
        photo_file_id: str | Path,
        *,
        caption: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        """Send a Telegram-hosted photo ID or a local image with a caption."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id

        if isinstance(photo_file_id, Path):
            mime_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }
            content_type = mime_types.get(photo_file_id.suffix.lower())
            if content_type is None:
                raise TelegramAPIError("The configured photo format is not supported.")
            try:
                size = photo_file_id.stat().st_size
                if size < 1 or size > 10_000_000:
                    raise TelegramAPIError("The configured photo is outside Telegram's size limit.")
                image = photo_file_id.read_bytes()
            except TelegramAPIError:
                raise
            except OSError:
                raise TelegramAPIError("The configured photo asset is unavailable.") from None
            fields = {
                key: (
                    json.dumps(value, ensure_ascii=False)
                    if key == "reply_markup"
                    else str(value)
                )
                for key, value in payload.items()
            }
            result = self._multipart_request(
                "sendPhoto",
                fields,
                file_field="photo",
                filename=photo_file_id.name,
                content_type=content_type,
                content=image,
            )
            return result if isinstance(result, dict) else {}

        payload["photo"] = photo_file_id
        result = self._request("sendPhoto", payload)
        return result if isinstance(result, dict) else {}

    def _multipart_request(
        self,
        method: str,
        fields: dict[str, str],
        *,
        file_field: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> Any:
        boundary = "----smh-" + uuid.uuid4().hex
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        safe_name = Path(filename).name.replace('"', "").replace("\r", "").replace("\n", "")[:120]
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + content
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        request = Request(
            self._base_url + method,
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw_response = response.read()
        except HTTPError as error:
            parsed: dict[str, Any] = {}
            try:
                body = json.loads(error.read().decode("utf-8"))
                if isinstance(body, dict):
                    parsed = body
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            parameters = parsed.get("parameters")
            retry_after = (
                parameters.get("retry_after")
                if isinstance(parameters, dict)
                else None
            )
            raise TelegramAPIError(
                str(parsed.get("description", f"HTTP {error.code}")),
                http_status=error.code,
                error_code=parsed.get("error_code"),
                retry_after=retry_after if isinstance(retry_after, int) else None,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise TelegramAPIError(
                "Telegram photo request failed.",
                delivery_unknown=True,
            ) from None

        try:
            parsed_response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramAPIError(
                "Telegram returned an unreadable photo response.",
                delivery_unknown=True,
            ) from None
        if not isinstance(parsed_response, dict) or not parsed_response.get("ok"):
            description = (
                parsed_response.get("description", "Telegram photo request was not successful.")
                if isinstance(parsed_response, dict)
                else "Telegram returned an unexpected photo response."
            )
            parameters = (
                parsed_response.get("parameters")
                if isinstance(parsed_response, dict)
                else None
            )
            retry_after = (
                parameters.get("retry_after")
                if isinstance(parameters, dict)
                else None
            )
            raise TelegramAPIError(
                str(description),
                error_code=(
                    parsed_response.get("error_code")
                    if isinstance(parsed_response, dict)
                    else None
                ),
                retry_after=retry_after if isinstance(retry_after, int) else None,
            )
        return parsed_response.get("result")

    def send_document(
        self,
        chat_id: int,
        filename: str,
        content: bytes,
        *,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Send a generated document without exposing the token in errors."""
        safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")[:120]
        boundary = "----smh-" + uuid.uuid4().hex
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n"
            f"{int(chat_id)}\r\n".encode("utf-8")
        ]
        if caption:
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n"
                f"{caption}\r\n".encode("utf-8")
            )
        parts.append(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="document"; filename="{safe_name}"\r\n'
                "Content-Type: text/csv; charset=utf-8\r\n\r\n"
            ).encode("utf-8")
            + bytes(content)
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        request = Request(
            self._base_url + "sendDocument",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw_response = response.read()
        except HTTPError as error:
            parsed: dict[str, Any] = {}
            try:
                body = json.loads(error.read().decode("utf-8"))
                if isinstance(body, dict):
                    parsed = body
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            description = str(parsed.get("description", f"HTTP {error.code}"))
            parameters = parsed.get("parameters")
            retry_after = (
                parameters.get("retry_after")
                if isinstance(parameters, dict)
                else None
            )
            raise TelegramAPIError(
                description,
                http_status=error.code,
                error_code=parsed.get("error_code"),
                retry_after=retry_after if isinstance(retry_after, int) else None,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise TelegramAPIError(
                "Telegram document request failed.",
                delivery_unknown=True,
            ) from None
        try:
            parsed_response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramAPIError(
                "Telegram returned an unreadable document response.",
                delivery_unknown=True,
            ) from None
        if not isinstance(parsed_response, dict) or not parsed_response.get("ok"):
            description = (
                parsed_response.get("description", "Telegram request was not successful.")
                if isinstance(parsed_response, dict)
                else "Telegram returned an unexpected response."
            )
            raise TelegramAPIError(str(description))
        result = parsed_response.get("result")
        return result if isinstance(result, dict) else {}

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        *,
        parse_mode: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        return self._request("editMessageText", payload)

    def send_chat_action(
        self,
        chat_id: int,
        action: str = "typing",
        *,
        message_thread_id: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "action": action}
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        self._request(
            "sendChatAction",
            payload,
            timeout=3,
        )

    def send_poll(
        self,
        chat_id: int,
        question: str,
        options: list[str],
        correct_option_id: int,
        explanation: str,
        *,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "question": question,
            "options": options,
            "type": "quiz",
            "is_anonymous": True,
            "correct_option_id": correct_option_id,
            "explanation": explanation,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        result = self._request("sendPoll", payload)
        return result if isinstance(result, dict) else {}

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        self._request("answerCallbackQuery", payload)