import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from smh.trade_statistics import format_trade_statistics


class TradeStatisticsTests(unittest.TestCase):
    def test_year_to_date_and_weekly_summary_use_closed_outcomes_and_no_double_counting(self):
        rows = [
            {
                "id": "win-1",
                "state": "CLOSED",
                "created": "2026-10-21T08:00:00+00:00",
                "updated": "2026-10-21T09:00:00+00:00",
                "data": json.dumps({
                    "symbol": "XAUUSD.s", "market": "XAUUSD.s", "direction": "BUY",
                    "entry": "4000.00", "exit": "4004.16", "outcome": "Win",
                    "targets": {},
                }),
            },
            {
                "id": "loss-1",
                "state": "CLOSED",
                "created": "2026-10-22T08:00:00+00:00",
                "updated": "2026-10-22T09:00:00+00:00",
                "data": json.dumps({
                    "symbol": "XAUUSD.s", "market": "XAUUSD.s", "direction": "SELL",
                    "entry": "4000.00", "exit": "4006.16", "sl": "4006.16",
                    "outcome": "Loss", "targets": {},
                }),
            },
            {
                "id": "active-1",
                "state": "ACTIVE",
                "created": "2026-10-22T08:00:00+00:00",
                "updated": "2026-10-22T08:00:00+00:00",
                "data": json.dumps({
                    "symbol": "XAUUSD.s", "market": "XAUUSD.s", "direction": "BUY",
                    "entry": "4000.00", "outcome": "", "targets": {},
                    "target_profit_screenshots": {
                        "1": {
                            "observed_entry": "4000.00",
                            "observed_exit": "4004.16",
                            "pips": "416",
                            "posted_at": "2026-10-23T10:00:00+01:00",
                        },
                    },
                }),
            },
        ]
        report = format_trade_statistics(
            rows, datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("Africa/Lagos")))

        self.assertIn("2026 STATISTICS · YEAR TO DATE", report)
        self.assertIn("Wins: 1", report)
        self.assertIn("Losses: 1", report)
        self.assertIn("Win rate: 50%", report)
        self.assertIn("Total pips: -20 pips", report)
        self.assertIn("TP1 screenshot", report)
        self.assertIn("+42 pips", report)
        self.assertIn("Closed-trade total: -20 pips", report)
        self.assertIn("TP screenshot pips are milestones", report)
        self.assertIn("old channel posts are not imported", report)

    def test_empty_history_does_not_invent_results(self):
        report = format_trade_statistics(
            [], datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("Africa/Lagos")))
        self.assertIn("Wins: 0", report)
        self.assertIn("Losses: 0", report)
        self.assertIn("Win rate: 0%", report)
        self.assertIn("No closed trades or TP screenshots recorded this week.", report)
