"""Authenticated client for the shared Development Support Portal API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .domain import safe_text

logger = logging.getLogger("smh.support")
SECRET_LIKE = re.compile(
    r"\b(?:password|passcode|otp|one[- ]time code|recovery code|secret key|api key|access token|private key)\b",
    re.IGNORECASE,
)


class SupportApiError(RuntimeError):
    """Safe failure category; never includes response bodies or credentials."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SupportApiClient:
    def __init__(self, api_root: str, token: str, *, timeout: float = 6.0) -> None:
        parsed = urlsplit(api_root)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("A valid support API URL is required.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("The support API URL must not contain credentials or query parameters.")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Non-local support API connections must use HTTPS.")
        if not token or len(token) < 32:
            raise ValueError("A sufficiently long support API token is required.")
        path = parsed.path.rstrip("/")
        if not path.endswith("/api"):
            path = f"{path}/api" if path else "/api"
        self._api_root = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        self._token = token
        self._timeout = timeout
        self._opener = build_opener(_RejectRedirects())

    @classmethod
    def from_environment(
        cls,
        *,
        isolated_test: bool,
        database_schema: str,
        bot: str = "signals",
    ) -> SupportApiClient | None:
        enabled = os.getenv("SMH_SUPPORT_API_ENABLED", "").casefold() in {"1", "true", "yes"}
        if not enabled:
            return None
        if not isolated_test or database_schema != "smh_test":
            raise ValueError("The shared support API is allowed only for the isolated smh_test bot.")
        if bot != "signals":
            raise ValueError("This client is configured for the Signal bot only.")
        api_root = os.getenv("SMH_SUPPORT_API_URL", "").strip()
        token = os.getenv("SMH_SUPPORT_SIGNALS_TOKEN", "")
        if not api_root or not token:
            raise ValueError("The isolated support API URL and Signal bot token are required.")
        return cls(api_root, token)

    def _request(self, method: str, path: str, *, payload: dict | None = None) -> dict:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._api_root}/{path.lstrip('/')}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read(1_000_001)
        except HTTPError as error:
            raise SupportApiError(f"http_{error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise SupportApiError("network") from None
        if len(raw) > 1_000_000:
            raise SupportApiError("response_too_large")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SupportApiError("invalid_response") from None
        if not isinstance(data, dict):
            raise SupportApiError("invalid_response")
        return data

    @staticmethod
    def _request_id(update_id: int | None) -> str:
        if isinstance(update_id, int):
            return f"telegram-update-{update_id}"
        return f"telegram-{uuid4().hex}"

    def create_case(self, telegram_user_id: int, question: str, update_id: int | None) -> dict:
        response = self._request(
            "POST",
            "/support/bot/cases",
            payload={
                "requestId": self._request_id(update_id),
                "telegramUserId": telegram_user_id,
                "question": question,
            },
        )
        if not isinstance(response.get("caseId"), str):
            raise SupportApiError("invalid_response")
        return response

    def list_cases(self, telegram_user_id: int) -> dict:
        query = urlencode({"telegramUserId": telegram_user_id})
        return self._request("GET", f"/support/bot/cases?{query}")

    def get_case(self, case_id: str, telegram_user_id: int) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", case_id):
            raise ValueError("Invalid support case ID.")
        query = urlencode({"caseId": case_id, "telegramUserId": telegram_user_id})
        return self._request("GET", f"/support/bot/case?{query}")

    def reply_case(
        self,
        case_id: str,
        telegram_user_id: int,
        text: str,
        update_id: int | None,
    ) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", case_id):
            raise ValueError("Invalid support case ID.")
        return self._request(
            "POST",
            f"/support/bot/cases/{case_id}/messages",
            payload={
                "requestId": self._request_id(update_id),
                "telegramUserId": telegram_user_id,
                "text": text,
            },
        )

    def claim_replies(self) -> dict:
        return self._request("POST", "/support/bot/outbox/claim", payload={})

    def acknowledge_reply(self, reply_id: str, outcome: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", reply_id):
            raise ValueError("Invalid support reply ID.")
        if outcome not in {"sent", "failed", "uncertain"}:
            raise ValueError("Unsupported delivery outcome.")
        return self._request(
            "POST",
            f"/support/bot/outbox/{reply_id}/ack",
            payload={"outcome": outcome},
        )


async def process_shared_support_reply_once(support_api, bot, permanent_errors=()):
    """Deliver claimed replies once; callers provide Telegram's permanent-error types."""
    try:
        result = await asyncio.to_thread(support_api.claim_replies)
    except SupportApiError as exc:
        logger.warning("shared_support_reply_claim_failed:%s", exc.category)
        return False
    replies = result.get("replies")
    if not isinstance(replies, list):
        logger.warning("shared_support_reply_queue_invalid")
        return False
    if not replies:
        return False

    for reply in replies:
        if not isinstance(reply, dict):
            continue
        reply_id = str(reply.get("replyId") or "")
        raw_user_id = reply.get("telegramUserId")
        text = reply.get("text")
        if (
            not re.fullmatch(r"[A-Za-z0-9-]{8,64}", reply_id)
            or not isinstance(raw_user_id, str)
            or not raw_user_id.isdigit()
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 3000
            or SECRET_LIKE.search(text)
        ):
            if re.fullmatch(r"[A-Za-z0-9-]{8,64}", reply_id):
                try:
                    await asyncio.to_thread(support_api.acknowledge_reply, reply_id, "failed")
                except SupportApiError as exc:
                    logger.warning("shared_support_reply_ack_failed:%s", exc.category)
            continue

        try:
            safe_reply = safe_text(text, 3000)
        except ValueError:
            try:
                await asyncio.to_thread(support_api.acknowledge_reply, reply_id, "failed")
            except SupportApiError as exc:
                logger.warning("shared_support_reply_ack_failed:%s", exc.category)
            continue
        responder = reply.get("responderName")
        try:
            responder = safe_text(responder, 80) if isinstance(responder, str) and responder.strip() else "Support"
        except ValueError:
            responder = "Support"

        outcome = "sent"
        try:
            await asyncio.wait_for(
                bot.send_message(
                    chat_id=int(raw_user_id),
                    text=f"💬 VAYDA | Support · {responder}\n\n{safe_reply}",
                ),
                timeout=20,
            )
        except permanent_errors:
            outcome = "failed"
            logger.warning("shared_support_reply_rejected_by_telegram")
        except Exception:
            outcome = "uncertain"
            logger.warning("shared_support_reply_delivery_uncertain; automatic_retry_disabled")
        try:
            await asyncio.to_thread(support_api.acknowledge_reply, reply_id, outcome)
        except SupportApiError as exc:
            logger.warning("shared_support_reply_ack_failed:%s", exc.category)
    return True


async def run_shared_support_reply_worker(support_api, bot, stop_event, permanent_errors=()):
    """Poll the shared portal outbox, preserving uncertain-send quarantine."""
    while not stop_event.is_set():
        try:
            found = await process_shared_support_reply_once(
                support_api, bot, permanent_errors=permanent_errors)
            if not found:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("shared_support_reply_worker_failed")
            await asyncio.sleep(5)
