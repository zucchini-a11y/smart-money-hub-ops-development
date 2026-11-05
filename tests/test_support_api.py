import json
import os
import unittest
from io import BytesIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from smart_money_hub_bot.support_api import SupportApiClient, SupportApiError


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self._body[:limit]


class SupportApiClientTests(unittest.TestCase):
    def test_client_stays_disabled_without_isolated_test_flags(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(SupportApiClient.from_environment())
        with patch.dict(
            os.environ,
            {
                "SMH_ISOLATED_TEST_INSTANCE": "true",
                "SMH_SUPPORT_API_ENABLED": "true",
                "SMH_SUPPORT_API_URL": "https://support.example.test",
                "SMH_SUPPORT_COACH_TOKEN": "t" * 40,
            },
            clear=True,
        ):
            self.assertIsNotNone(SupportApiClient.from_environment())

    def test_production_client_requires_explicit_flag_and_https(self) -> None:
        production = {
            "SMH_SUPPORT_API_ENABLED": "true",
            "SMH_SUPPORT_PRODUCTION_ENABLED": "true",
            "SMH_SUPPORT_API_URL": "https://support.example.test",
            "SMH_SUPPORT_COACH_TOKEN": "t" * 40,
        }
        with patch.dict(os.environ, production, clear=True):
            self.assertIsNotNone(SupportApiClient.from_environment())

        production["SMH_SUPPORT_API_URL"] = "http://support.example.test"
        with patch.dict(os.environ, production, clear=True):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                SupportApiClient.from_environment()

    def test_create_case_sends_bearer_token_and_stable_update_id(self) -> None:
        client = SupportApiClient("https://support.example.test/api", "t" * 40)
        response = _Response({"caseId": "case-12345678"})
        client._opener.open = Mock(return_value=response)

        result = client.create_case(12345, "Please help with my account.", 987)

        self.assertEqual(result["caseId"], "case-12345678")
        request = client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://support.example.test/api/support/bot/cases")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["authorization"], f"Bearer {'t' * 40}")
        self.assertEqual(
            json.loads(request.data),
            {
                "requestId": "telegram-update-987",
                "telegramUserId": 12345,
                "question": "Please help with my account.",
            },
        )

    def test_http_error_does_not_expose_response_body(self) -> None:
        client = SupportApiClient("https://support.example.test", "t" * 40)
        client._opener.open = Mock(
            side_effect=HTTPError(
                "https://support.example.test/api/support",
                401,
                "Unauthorized",
                {},
                BytesIO(b"password=private-value"),
            )
        )

        with self.assertRaises(SupportApiError) as raised:
            client.list_cases(12345)

        self.assertEqual(str(raised.exception), "http_401")
        self.assertNotIn("private-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
