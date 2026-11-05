"""Offline fixture-safety checks; no live Telegram calls are made."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from smh.config import Config
from smh.database import Database
from smh.publishing import Publisher
from smh.zones import active, setup_caption, signal_payload
from tests.fixture_support import FIXTURE_DIR, load_zone_fixture, validate_fixture_chart


class IsolatedFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_zone_fixture()
        self.setup = dict(self.fixture["setup"])

    def test_synthetic_chart_matches_fixture_and_setup_is_unconfirmed(self):
        chart = FIXTURE_DIR / self.fixture["chart_file"]
        manifest = validate_fixture_chart(self.setup, chart)
        self.assertEqual(manifest["label"], "TEST ONLY / DO NOT TRADE")
        self.assertNotIn("confirmation", self.setup)
        caption = setup_caption(self.setup)
        self.assertIn("<b>📍 ACTIVE SETUP ZONE | TEST ONLY - DO NOT TRADE</b>", caption)
        self.assertIn("🎯 <b>Zone:</b> 100–101", caption)
        self.assertIn("<b>Awaiting Confirmation</b>", caption)

    def test_chart_setup_mismatch_is_rejected(self):
        chart = FIXTURE_DIR / self.fixture["chart_file"]
        mismatched = {**self.setup, "zone": "102–103"}
        with self.assertRaisesRegex(ValueError, "Chart/setup mismatch: zone"):
            validate_fixture_chart(mismatched, chart)

    def test_used_setup_is_rejected_without_creating_an_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(directory)
            try:
                used = {
                    **self.setup,
                    "status": "used",
                    "confirmation": self.fixture["preview_confirmation"],
                    "setup_message_id": 9001,
                }
                db.put("active_setup", used)
                db.put("setup:" + used["id"], used)
                config = Config("456:TEST_ONLY", 42, -3001, -3002, Path(directory),
                                allow_publishing=True, isolated_test=True)
                bot = SimpleNamespace(send_message=AsyncMock())
                publisher = Publisher(db, config, bot)
                payload = signal_payload(used, "BUY", 42, {
                    "entry": "100.50", "sl": "99", "targets": {"1": {"price": "102"}},
                })
                with self.assertRaisesRegex(ValueError, "already used"):
                    publisher.prepare(42, "signal", payload)
                self.assertEqual(db.rows("SELECT COUNT(*) AS n FROM operations")[0]["n"], 0)
                self.assertEqual(db.rows("SELECT COUNT(*) AS n FROM trades")[0]["n"], 0)
                bot.send_message.assert_not_called()
            finally:
                db.conn.close()

    def test_isolated_signal_routes_to_test_channel_not_production_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(directory)
            try:
                config = Config("456:TEST_ONLY", 42, -3001, -3002, Path(directory),
                                allow_publishing=True, isolated_test=True)
                setup = {
                    **self.setup,
                    "confirmation": self.fixture["preview_confirmation"],
                    "setup_message_id": 9001,
                }
                from smh.zones import activate
                activate(db, setup, None)
                bot = SimpleNamespace(send_message=AsyncMock())
                publisher = Publisher(db, config, bot)
                payload = signal_payload(setup, "BUY", 42, {
                    "entry": "100.50", "sl": "99", "targets": {"1": {"price": "102"}},
                })
                op = publisher.prepare(42, "signal", payload)
                _, stored = publisher.operation(op)
                self.assertEqual(stored["channel"], -3001)
                self.assertNotIn(stored["channel"], (-1001, -1002))
                self.assertEqual(stored["destination"], "signals")
                bot.send_message.assert_not_called()
            finally:
                db.conn.close()

    def test_buy_and_sell_previews_are_synthetic_and_do_not_mutate_fixture(self):
        preview_setup = {
            **self.setup,
            "confirmation": self.fixture["preview_confirmation"],
            # This local-only placeholder models the link assigned after a future
            # zone post; it is never saved or sent to Telegram.
            "setup_message_id": 9001,
        }
        previews = {
            "BUY": signal_payload(preview_setup, "BUY", 42, {
                "entry": "100.50", "sl": "99", "targets": {"1": {"price": "102"}},
            })["text"],
            "SELL": signal_payload(preview_setup, "SELL", 42, {
                "entry": "100.50", "sl": "102", "targets": {"1": {"price": "99"}},
            })["text"],
        }
        self.assertEqual(previews["BUY"], "<b>🟢 BUY NOW</b>")
        self.assertEqual(previews["SELL"], "<b>🔴 SELL NOW</b>")
        self.assertNotIn("confirmation", self.setup)


if __name__ == "__main__":
    unittest.main()
