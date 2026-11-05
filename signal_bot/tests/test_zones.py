import time
import tempfile
import unittest
from decimal import Decimal

from smh.database import Database
from smh.zones import (
    automatic_tp1_pip_size,
    automatic_tp1_price,
    automatic_tp_ladder,
    activate,
    make_active_expiry_manual,
    next_automatic_tp,
    parse_zone,
    is_expired,
    public_status,
    setup_caption,
    signal_payload,
    zone_tapped_update_text,
)


class ZoneCaptionTests(unittest.TestCase):
    def setUp(self):
        self.setup = parse_zone(
            "Gold/XAUUSD | 2650-2655 | M15 | 60 | M15 bullish close"
        )

    def test_active_caption_uses_saved_values_and_supported_html(self):
        caption = setup_caption(self.setup)
        self.assertIn("<b>📍 ACTIVE SETUP ZONE | XAUUSD</b>", caption)
        self.assertIn("📊 <b>Market:</b> XAUUSD (GOLD)", caption)
        self.assertIn("🎯 <b>Zone:</b> 2650–2655", caption)
        self.assertIn("⏱️ <b>Zone Timeframe:</b> M15", caption)
        self.assertIn("✅ <b>Required Confirmation:</b> M15 bullish close", caption)
        self.assertIn("Expiry:</b> Manual — remains active until marked expired", caption)
        self.assertIn("⌛ <b>Status:</b> <b>Awaiting Confirmation</b>", caption)
        self.assertNotIn("Setup ID", caption)
        self.assertNotIn(self.setup["id"], caption)
        self.assertIn("⚠️ <b>WAIT FOR CONFIRMATION</b>", caption)
        self.assertIn(
            "Price entering the zone does not automatically mean an entry is valid. "
            "Wait for the required confirmation before considering a trade.",
            caption,
        )
        self.assertIn("🛡️ <b>NO CONFIRMATION, NO ENTRY.</b>", caption)

    def test_new_zone_is_manual_expiry_and_explicitly_expired_zone_is_closed(self):
        self.assertIsNone(self.setup["expires"])
        self.assertFalse(is_expired(self.setup))
        self.assertTrue(is_expired({**self.setup, "status": "expired"}))
        self.assertTrue(is_expired({**self.setup, "expires": 0}))

    def test_dynamic_values_are_html_escaped(self):
        self.setup["market"] = "Gold <urgent>&"
        self.setup["condition"] = "M15 close < 2655 & hold"
        caption = setup_caption(self.setup)
        self.assertIn("Gold &lt;urgent&gt;&amp;", caption)
        self.assertIn("M15 close &lt; 2655 &amp; hold", caption)
        self.assertNotIn("<urgent>", caption)

    def test_zone_tapped_copy_is_factual_and_preserves_no_entry_rule(self):
        text = zone_tapped_update_text(self.setup)
        self.assertIn("<b>📍 POI ZONE TAPPED | Gold/XAUUSD</b>", text)
        self.assertIn("<b>2650–2655</b>", text)
        self.assertIn("A POI touch is not an entry signal.", text)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", text)
        self.assertNotIn("BUY NOW", text)
        self.assertNotIn("SELL NOW", text)

        unsafe = {**self.setup, "market": "Gold <urgent>&"}
        self.assertIn("Gold &lt;urgent&gt;&amp;", zone_tapped_update_text(unsafe))

    def test_missing_optional_values_are_not_invented(self):
        incomplete = {
            "market": "",
            "zone": "",
            "timeframe": "",
            "condition": "",
            "status": "active",
            "expires": time.time() + 60,
        }
        caption = setup_caption(incomplete)
        self.assertIn("Market:</b> Not specified", caption)
        self.assertIn("Zone:</b> Not specified–Not specified", caption)
        self.assertIn("Zone Timeframe:</b> Not specified", caption)
        self.assertIn("Required Confirmation:</b> Not specified", caption)
        self.assertNotIn("Setup ID", caption)

    def test_signal_keeps_internal_setup_link_but_does_not_publish_the_id(self):
        self.setup.update(confirmation="Observed M15 bullish close", setup_message_id=901)
        payload = signal_payload(self.setup, "SELL", 42, {
            "entry": "2652–2654", "sl": "2660",
            "targets": {"1": {"price": "2635"}, "2": {"price": "2620"}},
        })
        self.assertEqual(payload["setup_id"], self.setup["id"])
        self.assertEqual(payload["trade"]["setup_id"], self.setup["id"])
        self.assertEqual(payload["trade"]["setup_message_id"], 901)
        self.assertEqual(payload["text"], "<b>🔴 SELL NOW</b>")
        self.assertEqual(payload["trade"]["entry"], "2652–2654")
        self.assertNotIn(self.setup["id"], payload["text"])
        self.assertNotIn("Setup #", payload["text"])
        self.assertNotIn("XAUUSD", payload["text"])
        self.assertNotIn("2660", payload["text"])

    def test_signal_payload_requires_stop_loss_and_take_profit(self):
        self.setup.update(confirmation="Observed M15 bullish close", setup_message_id=901)
        with self.assertRaisesRegex(ValueError, "Entry range, Stop Loss"):
            signal_payload(self.setup, "BUY", 42)

    def test_automatic_tp1_uses_20_pips_for_gold_and_forex(self):
        self.assertEqual(automatic_tp1_pip_size("Gold/XAUUSD"), Decimal("0.01"))
        self.assertEqual(automatic_tp1_price("Gold/XAUUSD", "BUY", "2653.00"), "2653.20")
        self.assertEqual(automatic_tp1_price("Gold/XAUUSD", "SELL", "2653.00"), "2652.80")
        self.assertEqual(automatic_tp1_price("Forex/EURUSD", "BUY", "1.08250"), "1.08450")
        self.assertEqual(automatic_tp1_price("Forex/EURUSD", "SELL", "1.08250"), "1.08050")
        self.assertEqual(automatic_tp1_price("Forex/USDJPY", "BUY", "150.00"), "150.20")

    def test_automatic_tp1_requires_exact_entry_and_only_known_pip_scopes(self):
        with self.assertRaisesRegex(ValueError, "exact entry"):
            automatic_tp1_price("Gold/XAUUSD", "BUY", "2650-2655")
        self.assertIsNone(automatic_tp1_price("Bitcoin/BTC", "BUY", "65000"))
        self.assertIsNone(automatic_tp1_price("Forex/ABCXYZ", "BUY", "1.2000"))

    def test_automatic_tp_ladder_calculates_four_20_pip_steps_for_buy_and_sell(self):
        buy = automatic_tp_ladder("Gold/XAUUSD", "BUY", "2653.00")
        self.assertEqual(
            [buy[str(number)] for number in range(1, 5)],
            [
                {"price": "2653.20", "pips": 20},
                {"price": "2653.40", "pips": 40},
                {"price": "2653.60", "pips": 60},
                {"price": "2653.80", "pips": 80},
            ],
        )
        sell = automatic_tp_ladder("Forex/EURUSD", "SELL", "1.08250")
        self.assertEqual(
            [sell[str(number)] for number in range(1, 5)],
            [
                {"price": "1.08050", "pips": 20},
                {"price": "1.07850", "pips": 40},
                {"price": "1.07650", "pips": 60},
                {"price": "1.07450", "pips": 80},
            ],
        )
        self.assertIsNone(automatic_tp_ladder("Bitcoin/BTC", "BUY", "65000"))

    def test_next_automatic_target_is_private_20_pip_increment_and_requires_auto_ladder(self):
        targets = {"1": {"price": "2652.80", "hit": False}}
        self.assertEqual(
            next_automatic_tp("Gold/XAUUSD", "SELL", "2653.00", targets),
            {"number": 2, "price": "2652.60", "pips": 40},
        )
        targets["2"] = {"price": "2652.60", "hit": False}
        self.assertEqual(
            next_automatic_tp("Gold/XAUUSD", "SELL", "2653.00", targets),
            {"number": 3, "price": "2652.40", "pips": 60},
        )
        targets["1"]["price"] = "2640.00"
        self.assertIsNone(
            next_automatic_tp("Gold/XAUUSD", "SELL", "2653.00", targets))

    def test_confirmation_status_requires_saved_confirmation(self):
        self.assertEqual(public_status(self.setup), "Awaiting Confirmation")
        self.setup["confirmation"] = "Observed M15 bullish close"
        self.assertEqual(public_status(self.setup), "Confirmation Recorded")
        self.assertIn("Status:</b> <b>Confirmation Recorded</b>", setup_caption(self.setup))

    def test_expired_cancelled_and_signal_statuses_are_not_active(self):
        expired = {**self.setup, "expires": 0}
        self.assertEqual(public_status(expired), "Expired")
        self.assertIn("<b>📍 SETUP EXPIRED |", setup_caption(expired))

        cancelled = {**self.setup, "status": "cancelled"}
        self.assertEqual(public_status(cancelled), "Cancelled")
        self.assertIn("<b>📍 SETUP CANCELLED |", setup_caption(cancelled))

        used = {**self.setup, "status": "used"}
        self.assertEqual(public_status(used, "uncertain"), "Signal Result Uncertain")
        self.assertIn("<b>📍 SETUP NOT ACTIVE |", setup_caption(used, "Signal Result Uncertain"))
        self.assertEqual(public_status(used), "Signal Status Unavailable")


class ZoneExpiryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(self.tempdir.name)

    def tearDown(self):
        self.db.conn.close()
        self.tempdir.cleanup()

    def test_active_zone_with_past_legacy_deadline_stays_active(self):
        from smh.zones import active, is_expired

        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | manual | M15 close")
        setup["setup_message_id"] = 777
        activate(self.db, setup, None)
        setup["expires"] = time.time() - 60
        with self.db.transaction() as connection:
            from smh.zones import save_in
            save_in(connection, setup)
        self.assertTrue(is_expired(self.db.get("setup:" + setup["id"])))

        migrated = make_active_expiry_manual(self.db)

        self.assertEqual(migrated, [setup["id"]])
        current = active(self.db, setup["id"])
        self.assertEqual(current["status"], "active")
        self.assertIsNone(current["expires"])


if __name__ == "__main__":
    unittest.main()
