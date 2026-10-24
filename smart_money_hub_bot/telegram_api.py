"""Small standard-library client for the Telegram Bot HTTP API."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
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

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query", "channel_post"],
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

    def send_message_with_result(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = self._request("sendMessage", payload)
        return result if isinstance(result, dict) else {}

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