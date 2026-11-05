import unittest

from smh.profit_screenshot import (
    calculate_pips,
    calculate_trade_result,
    extract_labeled_prices,
    extract_position_rows,
)
from smh.zones import automatic_tp1_price


HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\t"
    "height\tconf\ttext\n"
)


def tsv_line(line_number, words, confidence=96):
    rows = []
    for word_number, word in enumerate(words.split(), start=1):
        rows.append(
            f"5\t1\t1\t1\t{line_number}\t{word_number}\t0\t0\t10\t10\t"
            f"{confidence}\t{word}\n"
        )
    return "".join(rows)


class ProfitScreenshotTests(unittest.TestCase):
    def test_reads_entry_and_exit_from_clear_labels(self):
        tsv = HEADER + tsv_line(1, "Entry Price 2653.00") + tsv_line(2, "Exit Price 2653.20")
        self.assertEqual(
            extract_labeled_prices(tsv),
            {"entry": "2653.00", "exit": "2653.20"},
        )

    def test_reads_two_labeled_prices_on_one_line(self):
        tsv = HEADER + tsv_line(1, "Open 1.08000 Close 1.08200")
        self.assertEqual(
            extract_labeled_prices(tsv),
            {"entry": "1.08000", "exit": "1.08200"},
        )

    def test_handles_thousands_separator_and_rejects_ambiguous_comma(self):
        tsv = HEADER + tsv_line(1, "Entry 2,653.00") + tsv_line(2, "Exit 2,653.20")
        self.assertEqual(
            extract_labeled_prices(tsv),
            {"entry": "2653.00", "exit": "2653.20"},
        )
        ambiguous = HEADER + tsv_line(1, "Entry 1,0800") + tsv_line(2, "Exit 1,0820")
        self.assertIsNone(extract_labeled_prices(ambiguous))

    def test_rejects_unlabeled_or_duplicate_prices_instead_of_guessing(self):
        self.assertIsNone(extract_labeled_prices(
            HEADER + tsv_line(1, "2653.00 2653.20")))
        self.assertIsNone(extract_labeled_prices(
            HEADER + tsv_line(1, "Entry 2653.00") +
            tsv_line(2, "Open 2653.00") +
            tsv_line(3, "Exit 2653.20")))
        self.assertIsNone(extract_labeled_prices(
            HEADER + tsv_line(1, "Entry 2653.00") +
            tsv_line(2, "Exit 2653.20", confidence=40)))

    def test_reads_multiple_broker_positions_as_separate_candidates(self):
        tsv = (
            HEADER
            + tsv_line(1, "XAUUSDm, sell 0.01 0.74")
            + tsv_line(2, "4051.944 — 4051.200")
            + tsv_line(3, "XAUUSDm sell 0.01 1.20")
            + tsv_line(4, "4052.402 — 4051.200")
        )
        self.assertEqual(
            extract_position_rows(tsv),
            [
                {
                    "symbol": "XAUUSDm",
                    "direction": "SELL",
                    "entry": "4051.944",
                    "exit": "4051.200",
                },
                {
                    "symbol": "XAUUSDm",
                    "direction": "SELL",
                    "entry": "4052.402",
                    "exit": "4051.200",
                },
            ],
        )

    def test_rejects_unpaired_or_ambiguous_broker_position_rows(self):
        unpaired = HEADER + tsv_line(1, "XAUUSDm sell 0.01") + tsv_line(2, "Balance 100")
        self.assertIsNone(extract_position_rows(unpaired))
        malformed = (
            HEADER
            + tsv_line(1, "XAUUSDm sell 0.01")
            + tsv_line(2, "4051.944 — 4051.200 extra")
        )
        self.assertIsNone(extract_position_rows(malformed))

    def test_calculates_directional_forex_and_selected_gold_display_pips(self):
        self.assertEqual(calculate_pips("Forex/EURUSD", "BUY", "1.0800", "1.0820"), "20")
        self.assertEqual(calculate_pips("Forex/USDJPY", "SELL", "150.20", "150.00"), "20")
        self.assertEqual(calculate_pips("Gold/XAUUSD", "BUY", "2653.00", "2653.20"), "2")

    def test_profit_screenshots_use_selected_xauusd_pip_size_and_round_to_whole_pips(self):
        self.assertEqual(
            calculate_trade_result("XAUUSD.s", "SELL", "4026.81", "4022.65"),
            {"pips": "42", "price_movement": "4.16"},
        )
        self.assertEqual(
            calculate_trade_result("Gold/XAUUSD.s", "SELL", "4026.81", "4022.65"),
            {"pips": "42", "price_movement": "4.16"},
        )
        self.assertEqual(
            calculate_trade_result("Gold/XAUUSD", "SELL", "4026.81", "4022.65"),
            {"pips": "42", "price_movement": "4.16"},
        )
        self.assertEqual(
            automatic_tp1_price("XAUUSD.s", "SELL", "4026.81"),
            "4024.81",
        )
        # Screenshot display units changed to 0.1; automatic TP ladder math stays configured separately.
        self.assertEqual(automatic_tp1_price("Gold/XAUUSD", "SELL", "4026.81"), "4026.61")

    def test_rejects_loss_side_unknown_direction_and_unsupported_market(self):
        with self.assertRaisesRegex(ValueError, "not profitable"):
            calculate_pips("Forex/EURUSD", "BUY", "1.0820", "1.0800")
        with self.assertRaisesRegex(ValueError, "direction"):
            calculate_pips("Forex/EURUSD", "HOLD", "1.0800", "1.0820")
        with self.assertRaisesRegex(ValueError, "supported only"):
            calculate_pips("BTCUSD", "BUY", "60000", "60100")
        self.assertEqual(
            calculate_trade_result("BTCUSD", "BUY", "60000", "60100"),
            {"pips": None, "price_movement": "100"},
        )


if __name__ == "__main__":
    unittest.main()
