from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from smart_money_hub_bot.trade_ledger import TradeLedger, TradeLedgerError


NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


class TradeLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.ledger = TradeLedger(Path(self.temp_dir.name) / "bot.sqlite3")

    def _trade(self, **overrides) -> str:
        values = {
            "trade_id": "SMH-TEST-1",
            "instrument": "XAUUSD",
            "direction": "BUY",
            "opened_at": "2026-10-20T09:00:00+01:00",
            "entry_price": "2700.00",
            "stop_loss": "2690.00",
            "planned_targets": ["2710", "2720"],
            "source_evidence": "admin record; source not independently verified",
            "now": NOW,
        }
        values.update(overrides)
        return self.ledger.record_trade(**values)

    def _close(self, trade_id: str, outcome: str, **overrides) -> None:
        values = {
            "outcome": outcome,
            "closed_at": "2026-10-20T11:00:00+01:00",
            "now": NOW,
        }
        values.update(overrides)
        self.ledger.close_trade(trade_id, **values)

    def test_open_trades_and_unverified_records_are_excluded_from_claimed_results(self):
        open_id = self._trade()
        unverified_id = self._trade(trade_id="SMH-TEST-2", direction="SELL")
        self._close(unverified_id, "win", net_pips="10", pip_size="0.1")
        self.ledger.set_verification(
            open_id, verified=True, evidence="Admin-checked broker statement", now=NOW
        )
        stats = self.ledger.calculate_statistics()
        self.assertEqual(stats["verified_closed_sample"], 0)
        self.assertEqual(stats["all_closed_including_unverified"], 1)
        self.assertEqual(stats["unverified_closed_excluded"], 1)
        self.assertIsNone(stats["win_rate"])

    def test_win_rate_denominator_excludes_breakeven_and_open_trades(self):
        for index, outcome in enumerate(("win", "loss", "breakeven"), 1):
            trade_id = self._trade(trade_id=f"SMH-DENOM-{index}")
            self._close(
                trade_id,
                outcome,
                exit_price="2701" if outcome == "win" else "2699",
                net_pips="10" if outcome == "win" else "-10" if outcome == "loss" else "0",
                pip_size="0.1",
            )
            self.ledger.set_verification(
                trade_id, verified=True, evidence="Verified admin source", now=NOW
            )
        self._trade(trade_id="SMH-OPEN")
        stats = self.ledger.calculate_statistics()
        self.assertEqual(stats["verified_closed_sample"], 3)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["losses"], 1)
        self.assertEqual(stats["breakeven"], 1)
        self.assertEqual(stats["win_rate"], "50.0")
        self.assertEqual(stats["win_rate_denominator"], "wins + losses; breakeven excluded")
        self.assertEqual(stats["known_net_pips"], "0")

    def test_pips_are_calculated_only_with_explicit_pip_size(self):
        trade_id = self._trade()
        self._close(
            trade_id,
            "win",
            exit_price="2701.5",
            pip_size="0.1",
        )
        self.assertEqual(self.ledger.get_trade(trade_id)["net_pips"], "15")

    def test_supplied_pips_require_pip_size_and_money_requires_currency(self):
        trade_id = self._trade()
        with self.assertRaises(TradeLedgerError):
            self._close(trade_id, "win", net_pips="10")
        with self.assertRaises(TradeLedgerError):
            self._close(
                trade_id,
                "win",
                realized_pl="25",
            )

    def test_duplicate_trade_id_is_rejected_not_counted_twice(self):
        first_id = self._trade()
        with self.assertRaises(TradeLedgerError):
            self._trade()
        self.assertEqual(len(self.ledger.list_trades()), 1)
        self.assertEqual(first_id, "SMH-TEST-1")

    def test_closed_trade_cannot_be_overwritten_but_reasoned_correction_is_audited(self):
        trade_id = self._trade()
        self._close(trade_id, "win", net_pips="10", pip_size="0.1")
        with self.assertRaises(TradeLedgerError):
            self._close(trade_id, "loss", net_pips="-10", pip_size="0.1")
        with self.assertRaises(TradeLedgerError):
            self.ledger.update_trade(
                trade_id, {"net_pips": "8"}, reason="Edit closed trade", now=NOW
            )
        self.ledger.correct_trade(
            trade_id,
            {"net_pips": "8"},
            reason="Corrected from verified statement",
            now=NOW,
        )
        record = self.ledger.get_trade(trade_id)
        self.assertEqual(record["net_pips"], "8")
        self.assertEqual(record["revision"], 3)
        audit = self.ledger.audit_history(trade_id)
        self.assertEqual(audit[0]["action"], "corrected")
        self.assertEqual(audit[0]["reason"], "Corrected from verified statement")

    def test_partial_take_profit_and_full_target_are_counted_without_duplicate_trade(self):
        trade_id = self._trade()
        self.ledger.add_partial_take_profit(
            trade_id,
            price="2710",
            closed_at="2026-10-20T10:00:00+01:00",
            percent_closed="50",
            now=NOW,
        )
        self._close(
            trade_id, "win", full_tp_hit=True, net_pips="20", pip_size="0.1"
        )
        self.ledger.set_verification(
            trade_id, verified=True, evidence="Verified statement", now=NOW
        )
        stats = self.ledger.calculate_statistics()
        self.assertEqual(stats["verified_closed_sample"], 1)
        self.assertEqual(stats["partial_tp_records"], 1)
        self.assertEqual(stats["full_tp_hits"], 1)

    def test_money_is_aggregated_by_currency_and_profit_factor_requires_losses(self):
        values = [("win", "20", "USD"), ("loss", "-5", "USD")]
        for index, (outcome, amount, currency) in enumerate(values, 1):
            trade_id = self._trade(trade_id=f"SMH-PL-{index}")
            self._close(
                trade_id,
                outcome,
                realized_pl=amount,
                currency=currency,
            )
            self.ledger.set_verification(
                trade_id, verified=True, evidence="Verified source", now=NOW
            )
        stats = self.ledger.calculate_statistics()
        self.assertEqual(stats["realized_pl_by_currency"]["USD"]["net"], "15")
        self.assertEqual(
            stats["realized_pl_by_currency"]["USD"]["profit_factor"], "4"
        )

    def test_export_contains_verification_and_does_not_change_ledger(self):
        trade_id = self._trade(notes="Review carefully")
        before = self.ledger.get_trade(trade_id)
        exported = self.ledger.export_csv()
        self.assertIn("verification_status", exported)
        self.assertIn("unverified", exported)
        self.assertEqual(self.ledger.get_trade(trade_id), before)


if __name__ == "__main__":
    unittest.main()
