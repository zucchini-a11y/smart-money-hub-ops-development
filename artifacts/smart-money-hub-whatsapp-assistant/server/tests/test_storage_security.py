import hashlib
import hmac
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant import providers, storage


class StorageAndSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = storage.DB_PATH
        storage.DB_PATH = Path(self.temp_dir.name) / "test.sqlite3"
        storage.init_db()

    def tearDown(self) -> None:
        storage.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_duplicate_provider_message_is_ignored(self) -> None:
        first = storage.record_inbound("wamid.test-1", "15550001111", "Test User", "Hi")
        duplicate = storage.record_inbound("wamid.test-1", "15550001111", "Test User", "Hi again")
        self.assertIsNotNone(first)
        self.assertTrue(first[1])
        self.assertIsNone(duplicate)
        conversations = storage.list_conversations()
        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["unreadCount"], 1)

    def test_signature_requires_configured_secret_and_matches_raw_body(self) -> None:
        body = b'{"entry":[]}'
        secret = "test-signature-secret"
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {"WHATSAPP_APP_SECRET": secret}):
            self.assertTrue(providers.verify_meta_signature(body, signature))
            self.assertFalse(providers.verify_meta_signature(body + b" ", signature))
            self.assertFalse(providers.verify_meta_signature(body, None))
        with patch.dict(os.environ, {"WHATSAPP_APP_SECRET": ""}):
            self.assertFalse(providers.verify_meta_signature(body, signature))

    def test_send_is_blocked_for_unapproved_test_recipient(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_ACCESS_TOKEN": "test-token",
                "WHATSAPP_PHONE_NUMBER_ID": "123456",
                "WHATSAPP_TEST_RECIPIENTS": "15550002222",
            },
        ):
            with self.assertRaises(providers.ProviderError):
                import asyncio

                asyncio.run(providers.send_text("15550003333", "Test"))


if __name__ == "__main__":
    unittest.main()
