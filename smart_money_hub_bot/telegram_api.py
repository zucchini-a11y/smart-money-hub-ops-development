"""Small standard-library client for the Telegram Bot HTTP API."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramAPIError(RuntimeError):
    """A Telegram API request failed without exposing the bot token."""


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
            try:
                error_body = error.read()
                parsed = json.loads(error_body.decode("utf-8"))
                description = parsed.get("description", f"HTTP {error.code}")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                description = f"HTTP {error.code}"
            raise TelegramAPIError(str(description)) from None
        except (URLError, TimeoutError, OSError) as error:
            # Do not echo the request URL: it contains the private bot token.
            reason = getattr(error, "reason", None)
            safe_reason = str(reason or "network request failed")
            raise TelegramAPIError(f"Telegram connection failed: {safe_reason}") from None

        try:
            parsed_response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramAPIError("Telegram returned an unreadable response.") from None

        if not isinstance(parsed_response, dict) or not parsed_response.get("ok"):
            description = (
                parsed_response.get("description", "Telegram request was not successful.")
                if isinstance(parsed_response, dict)
                else "Telegram returned an unexpected response."
            )
            raise TelegramAPIError(str(description))

        return parsed_response.get("result")

    def get_me(self) -> dict[str, Any]:
        return self._request("getMe")

    def get_webhook_info(self) -> dict[str, Any]:
        result = self._request("getWebhookInfo")
        return result if isinstance(result, dict) else {}

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
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
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self._request("sendMessage", payload)

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self._request(
            "sendChatAction",
            {"chat_id": chat_id, "action": action},
            timeout=3,
        )

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