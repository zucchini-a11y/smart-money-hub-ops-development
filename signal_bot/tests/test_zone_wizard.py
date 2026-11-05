import unittest

from smh import zone_wizard


class ZoneWizardValidationTests(unittest.TestCase):
    def test_forex_wizard_answers_build_only_from_entered_values(self):
        draft = zone_wizard.new_draft()
        self.assertEqual(draft["step"], "market")

        zone_wizard.answer(draft, "market", "Forex")
        self.assertEqual(draft["step"], "symbol")
        zone_wizard.answer(draft, "symbol", "EURUSD")
        zone_wizard.answer(draft, "low", "1.0800")
        zone_wizard.answer(draft, "high", "1.0850")
        zone_wizard.answer(draft, "timeframe", "M15")
        zone_wizard.answer(draft, "confirmation", "M15 bullish candle close")

        self.assertEqual(draft["step"], "preview")
        self.assertIn("Forex (EURUSD)", zone_wizard.preview_text(draft))
        setup = zone_wizard.build_setup(draft)
        self.assertEqual(setup["market"], "Forex/EURUSD")
        self.assertEqual(setup["zone"], "1.0800–1.0850")
        self.assertEqual(setup["timeframe"], "M15")
        self.assertEqual(setup["condition"], "M15 bullish candle close")
        self.assertIsNone(setup["expires"])

    def test_other_market_custom_steps_and_appropriate_skips(self):
        draft = zone_wizard.new_draft()
        zone_wizard.answer(draft, "market", "Other")
        self.assertEqual(draft["step"], "other_market")
        zone_wizard.answer(draft, "other_market", "Synthetic Test Market")
        self.assertEqual(draft["step"], "symbol")
        zone_wizard.answer(draft, "symbol", zone_wizard.SKIP)
        zone_wizard.answer(draft, "low", "100")
        zone_wizard.answer(draft, "high", "101")
        zone_wizard.answer(draft, "timeframe", zone_wizard.OTHER)
        zone_wizard.answer(draft, "timeframe_other", zone_wizard.SKIP)
        zone_wizard.answer(draft, "confirmation", zone_wizard.SKIP)

        setup = zone_wizard.build_setup(draft)
        self.assertEqual(setup["market"], "Synthetic Test Market")
        self.assertEqual(setup["timeframe"], "")
        self.assertEqual(setup["condition"], "")
        self.assertIsNone(setup["expires"])
        self.assertIn("mark it expired", zone_wizard.preview_text(draft))
        self.assertIn("Not specified", zone_wizard.preview_text(draft))

    def test_invalid_values_keep_the_current_question(self):
        draft = zone_wizard.new_draft()
        with self.assertRaisesRegex(ValueError, "Choose a market"):
            zone_wizard.answer(draft, "market", "Unknown")
        self.assertEqual(draft["step"], "market")

        zone_wizard.answer(draft, "market", "Forex")
        with self.assertRaisesRegex(ValueError, "Enter the symbol"):
            zone_wizard.answer(draft, "symbol", zone_wizard.SKIP)
        self.assertEqual(draft["step"], "symbol")

        zone_wizard.answer(draft, "symbol", "EURUSD")
        with self.assertRaisesRegex(ValueError, "positive price"):
            zone_wizard.answer(draft, "low", "0")
        self.assertEqual(draft["step"], "low")
        zone_wizard.answer(draft, "low", "10")
        with self.assertRaisesRegex(ValueError, "greater than the lower"):
            zone_wizard.answer(draft, "high", "10")
        self.assertEqual(draft["step"], "high")
        with self.assertRaisesRegex(ValueError, "greater than the lower"):
            zone_wizard.answer(draft, "high", "9")
        self.assertEqual(draft["step"], "high")

        zone_wizard.answer(draft, "high", "11")
        with self.assertRaisesRegex(ValueError, "Choose a timeframe"):
            zone_wizard.answer(draft, "timeframe", "M10")
        self.assertEqual(draft["step"], "timeframe")
        zone_wizard.answer(draft, "timeframe", zone_wizard.SKIP)
        zone_wizard.answer(draft, "confirmation", zone_wizard.SKIP)
        self.assertEqual(draft["step"], "preview")

    def test_invalid_custom_text_is_rejected(self):
        draft = zone_wizard.new_draft()
        zone_wizard.answer(draft, "market", "Other")
        with self.assertRaisesRegex(ValueError, "market name"):
            zone_wizard.answer(draft, "other_market", "")
        self.assertEqual(draft["step"], "other_market")
        with self.assertRaisesRegex(ValueError, "without /"):
            zone_wizard.answer(draft, "other_market", "Test/Market")
        self.assertEqual(draft["step"], "other_market")
        zone_wizard.answer(draft, "other_market", "Test market")
        with self.assertRaisesRegex(ValueError, "symbol"):
            zone_wizard.answer(draft, "symbol", "BTC|USD")
        self.assertEqual(draft["step"], "symbol")
        zone_wizard.answer(draft, "symbol", zone_wizard.SKIP)
        zone_wizard.answer(draft, "low", "100")
        zone_wizard.answer(draft, "high", "101")
        zone_wizard.answer(draft, "timeframe", zone_wizard.OTHER)
        with self.assertRaisesRegex(ValueError, "timeframe"):
            zone_wizard.answer(draft, "timeframe_other", "M15|H1")
        self.assertEqual(draft["step"], "timeframe_other")
        zone_wizard.answer(draft, "timeframe_other", "M15")
        zone_wizard.answer(draft, "confirmation", "M15 candle close")
        self.assertEqual(draft["step"], "preview")

    def test_back_and_edit_return_to_the_correct_step(self):
        draft = zone_wizard.new_draft()
        zone_wizard.answer(draft, "market", "Forex")
        zone_wizard.answer(draft, "symbol", "EURUSD")
        zone_wizard.answer(draft, "low", "1")
        zone_wizard.answer(draft, "high", "2")
        zone_wizard.answer(draft, "timeframe", "M15")
        zone_wizard.answer(draft, "confirmation", "M15 close")
        self.assertEqual(draft["step"], "preview")

        zone_wizard.back(draft)
        self.assertEqual(draft["step"], "confirmation")
        zone_wizard.answer(draft, "confirmation", "M15 close")
        zone_wizard.begin_edit(draft)
        zone_wizard.back(draft)
        self.assertEqual(draft["step"], "preview")
        zone_wizard.begin_edit(draft)
        zone_wizard.choose_edit(draft, "low")
        zone_wizard.answer(draft, "low", "1.5")
        self.assertEqual(draft["step"], "preview")
        self.assertEqual(draft["answers"]["low"], "1.5")

    def test_editing_market_reasks_symbol_when_required(self):
        draft = zone_wizard.new_draft()
        zone_wizard.answer(draft, "market", "Gold")
        zone_wizard.answer(draft, "low", "100")
        zone_wizard.answer(draft, "high", "101")
        zone_wizard.answer(draft, "timeframe", "M15")
        zone_wizard.answer(draft, "confirmation", "M15 close")
        zone_wizard.begin_edit(draft)
        zone_wizard.choose_edit(draft, "market")
        zone_wizard.answer(draft, "market", "Forex")
        self.assertEqual(draft["step"], "symbol")
        zone_wizard.answer(draft, "symbol", "EURUSD")
        self.assertEqual(draft["step"], "preview")
        self.assertEqual(zone_wizard.build_setup(draft)["market"], "Forex/EURUSD")

    def test_existing_timed_wizard_draft_migrates_to_manual_expiry(self):
        legacy = {
            "kind": "zone",
            "wizard_version": 1,
            "step": "expiry_other",
            "history": ["market", "symbol", "low", "high", "timeframe", "confirmation", "expiry"],
            "answers": {
                "market_kind": "Gold",
                "low": "2650",
                "high": "2655",
                "minutes": "60",
            },
            "revision": "legacy",
        }
        upgraded = zone_wizard.normalize(legacy)
        self.assertEqual(upgraded["step"], "preview")
        self.assertNotIn("minutes", upgraded["answers"])
        self.assertNotIn("expiry", upgraded["history"])
        self.assertIsNone(zone_wizard.build_setup(upgraded)["expires"])


if __name__ == "__main__":
    unittest.main()
