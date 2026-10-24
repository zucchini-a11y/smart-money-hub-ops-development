from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from smart_money_hub_bot.telegram_api import TelegramAPI


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return b'{"ok":true,"result":[]}'


class TelegramUpdateSubscriptionTests(unittest.TestCase):
    def test_poll_subscription_includes_channel_posts_and_edits(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response()

        api = TelegramAPI("synthetic-test-token")
        with patch("smart_money_hub_bot.telegram_api.urlopen", side_effect=fake_urlopen):
            self.assertEqual(api.get_updates(), [])

        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertIn("channel_post", payload["allowed_updates"])
        self.assertIn("edited_channel_post", payload["allowed_updates"])
        self.assertIn("message", payload["allowed_updates"])
        self.assertIn("callback_query", payload["allowed_updates"])


if __name__ == "__main__":
    unittest.main()
