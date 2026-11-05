"""Small authenticated client for the shared support portal API.

It stays off unless both the isolated-test flag and explicit enable flag are set.
"""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


class SupportApiError(RuntimeError):
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
            raise ValueError("A sufficiently long bot token is required.")
        path = parsed.path.rstrip("/")
        if not path.endswith("/api"):
            path = f"{path}/api" if path else "/api"
        self._api_root = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        self._token = token
        self._timeout = timeout
        self._opener = build_opener(_RejectRedirects())

    @classmethod
    def from_environment(cls, *, bot: str = "coach") -> SupportApiClient | None:
        if os.getenv("SMH_ISOLATED_TEST_INSTANCE", "").casefold() not in {"1", "true", "yes"}:
            return None
        if os.getenv("SMH_SUPPORT_API_ENABLED", "").casefold() not in {"1", "true", "yes"}:
            return None
        variable = "SMH_SUPPORT_COACH_TOKEN" if bot == "coach" else "SMH_SUPPORT_SIGNALS_TOKEN"
        base_url = os.getenv("SMH_SUPPORT_API_URL", "").strip()
        token = os.getenv(variable, "")
        if not base_url or not token:
            return None
        return cls(base_url, token)

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
        return f"telegram-update-{update_id}" if isinstance(update_id, int) else f"telegram-{uuid4().hex}"

    def create_case(self, telegram_user_id: int, question: str, update_id: int | None) -> dict:
        return self._request(
            "POST",
            "/support/bot/cases",
            payload={
                "requestId": self._request_id(update_id),
                "telegramUserId": telegram_user_id,
                "question": question,
            },
        )

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
