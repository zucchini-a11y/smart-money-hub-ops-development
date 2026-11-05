import unittest

from smh.analysis_poi import extract_poi_setups


class AnalysisPoiTests(unittest.TestCase):
    def test_single_labeled_poi_uses_exact_caption_values(self):
        setups = extract_poi_setups(
            "📊 SMART MONEY HUB | MARKET ANALYSIS\n"
            "📍 MARKET: XAUUSD\n"
            "⏱️ TIMEFRAME: M15\n"
            "🩷 POI ZONE: 4,124.00 – 4,132.00\n"
            "➖ REFERENCE LEVEL: 4,113.30"
        )
        self.assertEqual(len(setups), 1)
        setup = setups[0]
        self.assertEqual(setup["market"], "Gold/XAUUSD")
        self.assertEqual(setup["zone"], "4124.00–4132.00")
        self.assertEqual(setup["timeframe"], "M15")
        self.assertNotIn("poi_direction", setup)
        self.assertIn("POI touch alone is not entry confirmation", setup["condition"])

    def test_buy_and_sell_pois_are_extracted_as_independent_ranges(self):
        setups = extract_poi_setups(
            "📍 MARKET: Gold Spot / U.S. Dollar (XAUUSD)\n"
            "⏱️ TIMEFRAME: 1h\n"
            "🎯 POI ZONE: BUY POI (approx 3,989.21 - 4,007.00) and "
            "SELL POI (approx 4,107.96 - 4,087.28)"
        )
        self.assertEqual(len(setups), 2)
        self.assertEqual(
            [(setup["poi_direction"], setup["zone"], setup["approximate_zone"])
             for setup in setups],
            [
                ("BUY", "3989.21–4007.00", True),
                ("SELL", "4087.28–4107.96", True),
            ],
        )
        self.assertTrue(all(setup["market"] == "Gold/XAUUSD" for setup in setups))
        self.assertTrue(all(setup["timeframe"] == "1h" for setup in setups))

    def test_does_not_use_reference_level_as_a_poi_or_guess_from_chart_text(self):
        self.assertEqual(
            extract_poi_setups(
                "MARKET: XAUUSD\nTIMEFRAME: M15\n"
                "REFERENCE LEVEL: 4113.30"
            ),
            [],
        )

    def test_incomplete_poi_or_missing_metadata_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly two readable prices"):
            extract_poi_setups(
                "MARKET: XAUUSD\nTIMEFRAME: M15\nPOI ZONE: 4124.00"
            )
        with self.assertRaisesRegex(ValueError, "Add a MARKET"):
            extract_poi_setups("TIMEFRAME: M15\nPOI ZONE: 4124 - 4132")
        with self.assertRaisesRegex(ValueError, "Add a TIMEFRAME"):
            extract_poi_setups("MARKET: XAUUSD\nPOI ZONE: 4124 - 4132")
        with self.assertRaisesRegex(ValueError, "Label the exact POI range"):
            extract_poi_setups("MARKET: XAUUSD\nTIMEFRAME: M15\nPOI ZONE soon")


if __name__ == "__main__":
    unittest.main()
