from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["APP_ENV"] = "test"
os.environ["WHATSAPP_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["WHATSAPP_SESSION_SECRET"] = "test-session-secret"

from fastapi.testclient import TestClient

from assistant import storage
from main import API_PREFIX, WEBHOOK_PATH, app


class AdminAndWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {
                "APP_ENV": "test",
                "WHATSAPP_ADMIN_PASSWORD": "test-admin-password",
                "WHATSAPP_SESSION_SECRET": "test-session-secret",
                "WHATSAPP_APP_SECRET": "",
                "WHATSAPP_VERIFY_TOKEN": "",
                "WHATSAPP_TEST_RECIPIENTS": "",
                "WHATSAPP_ACCESS_TOKEN": "",
                "WHATSAPP_PHONE_NUMBER_ID": "",
            },
        )
        self.env_patch.start()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "api.sqlite3"
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.origin = {"Origin": "http://testserver"}

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        storage.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()
        self.env_patch.stop()

    def test_admin_login_protects_dashboard_and_pause_control(self) -> None:
        health = self.client.get(f"{API_PREFIX}/whatsapp/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})

        self.assertEqual(self.client.get(f"{API_PREFIX}/whatsapp/dashboard").status_code, 401)
        login = self.client.post(
            f"{API_PREFIX}/whatsapp/auth/login",
            json={"password": "test-admin-password"},
            headers=self.origin,
        )
        self.assertEqual(login.status_code, 200)
        dashboard = self.client.get(f"{API_PREFIX}/whatsapp/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertTrue(dashboard.json()["testMode"])
        self.assertFalse(dashboard.json()["paused"])

        pause = self.client.patch(
            f"{API_PREFIX}/whatsapp/settings",
            json={"paused": True},
            headers=self.origin,
        )
        self.assertEqual(pause.status_code, 200)
        self.assertTrue(pause.json()["paused"])

    def test_bad_origin_cannot_change_settings(self) -> None:
        self.client.post(
            f"{API_PREFIX}/whatsapp/auth/login",
            json={"password": "test-admin-password"},
            headers=self.origin,
        )
        response = self.client.patch(
            f"{API_PREFIX}/whatsapp/settings",
            json={"paused": True},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_signed_webhook_is_deduplicated_and_stays_test_only(self) -> None:
        secret = "test-meta-app-secret"
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": "15550001111", "profile": {"name": "Tester"}}],
                                "messages": [
                                    {
                                        "id": "wamid.webhook-test",
                                        "from": "15550001111",
                                        "type": "text",
                                        "text": {"body": "What is market structure?"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        raw = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_APP_SECRET": secret,
                "WHATSAPP_TEST_RECIPIENTS": "15550001111",
                "WHATSAPP_ACCESS_TOKEN": "",
                "WHATSAPP_PHONE_NUMBER_ID": "",
            },
        ):
            first = self.client.post(
                WEBHOOK_PATH,
                content=raw,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
            )
            duplicate = self.client.post(
                WEBHOOK_PATH,
                content=raw,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        conversations = storage.list_conversations()
        self.assertEqual(len(conversations), 1)
        detail = storage.get_conversation(conversations[0]["id"])
        self.assertEqual(len(detail["messages"]), 1)
        self.assertEqual(detail["messages"][0]["direction"], "inbound")

    def test_webhook_rejects_invalid_signature(self) -> None:
        response = self.client.post(
            WEBHOOK_PATH,
            content=b'{"entry":[]}',
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=bad"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
