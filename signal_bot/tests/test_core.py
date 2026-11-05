import asyncio
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from PIL import Image
from telegram.error import BadRequest, Conflict, InvalidToken, NetworkError, RetryAfter
from smh.config import Config
from smh.database import Database
from smh.domain import change, confirmation, entry, price, validate_analysis
from smh.images import import_chart, render
from smh.publishing import Publisher, clean_channel_text
from smh.runtime import build, poll, lock_process, friendly_error, initialize_app
from smh.handlers import ACTIONS


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.db = Database(self.path)
        self.config = Config("123456789:TEST_TOKEN_NOT_REAL", 42, -1001, -1002, self.path)

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()


def trade():
    return {"id": "trade1", "symbol": "XAUUSD", "market": "Gold/XAUUSD",
            "direction": "BUY", "state": "CONFIRMED_BUY", "targets": {}, "version": 1, "message_id": 90}


class ConfigTests(unittest.TestCase):
    def test_missing_token(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            Config.load()

    def test_discovery_mode(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:dummy", "SMH_TEST_MODE": "1"}, clear=True):
            self.assertFalse(Config.load().ready)

    def test_duplicate_channels_rejected(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:dummy", "PRO_SIGNALS_CHANNEL_ID": "-1", "MARKET_ANALYSIS_CHANNEL_ID": "-1"}, clear=True):
            with self.assertRaises(ValueError):
                Config.load()

    def test_bad_id(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:dummy", "ADMIN_TELEGRAM_ID": "bad"}, clear=True):
            with self.assertRaises(ValueError):
                Config.load()

    def test_ephemeral_deployment_blocked(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:dummy", "REPLIT_DEPLOYMENT": "1"}, clear=True):
            with self.assertRaises(ValueError):
                Config.load()

    def test_isolated_instance_uses_only_test_credentials_channels_and_database(self):
        env = {"SMH_ISOLATED_TEST_INSTANCE": "true",
               "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
               "SMH_TEST_ADMIN_TELEGRAM_ID": "42",
               "SMH_TEST_PRO_SIGNALS_CHANNEL_ID": "-1001",
               "SMH_TEST_MARKET_ANALYSIS_CHANNEL_ID": "-1002",
                "SMH_TEST_EDUCATION_GROUP_ID": "-1003",
                "SMH_TEST_EDUCATION_LINK": "https://t.me/+test-education",
               "SMH_TEST_DATABASE_URL": "postgresql://test.invalid/database",
               "SMH_TEST_DATA_DIR": "isolated-test-data",
               "TELEGRAM_BOT_TOKEN": "123:production-token",
               "ADMIN_TELEGRAM_ID": "99", "PRO_SIGNALS_CHANNEL_ID": "-2001",
               "MARKET_ANALYSIS_CHANNEL_ID": "-2002",
                "EDUCATION_GROUP_ID": "-2003",
               "DATABASE_URL": "postgresql://production.invalid/database",
                "SMH_EDUCATION_LINK": "https://t.me/+production-education",
               "SMH_ALLOW_PUBLISHING": "true"}
        with patch.dict(os.environ, env, clear=True):
            c = Config.load()
        self.assertEqual(c.admin, 42)
        self.assertEqual(c.signals, -1001)
        self.assertEqual(c.analysis, -1002)
        self.assertEqual(c.token, "456:test-token")
        self.assertEqual(c.database_url, env["SMH_TEST_DATABASE_URL"])
        self.assertEqual(c.database_schema, "smh_test")
        self.assertEqual(c.data.name, "isolated-test-data")
        self.assertTrue(c.isolated_test)
        self.assertFalse(c.allow_publishing)
        self.assertEqual(c.education_link, env["SMH_TEST_EDUCATION_LINK"])
        self.assertEqual(c.education_group_id, -1003)
        self.assertNotIn("-1003", repr(c))
        self.assertNotIn(env["SMH_TEST_EDUCATION_LINK"], repr(c))

    def test_education_group_id_must_be_negative_and_separate_from_channels(self):
        for group_id in ("1003", "-1001"):
            env = {
                "TELEGRAM_BOT_TOKEN": "123:dummy",
                "SMH_TEST_MODE": "1",
                "PRO_SIGNALS_CHANNEL_ID": "-1001",
                "MARKET_ANALYSIS_CHANNEL_ID": "-1002",
                "EDUCATION_GROUP_ID": group_id,
            }
            with patch.dict(os.environ, env, clear=True), self.subTest(group_id=group_id):
                with self.assertRaises(ValueError):
                    Config.load()

    def test_optional_education_link_is_loaded_without_appearing_in_repr(self):
        link = "javascript:alert(1)"
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:dummy",
            "SMH_TEST_MODE": "1",
            "SMH_EDUCATION_LINK": link,
        }, clear=True):
            config = Config.load()
        self.assertEqual(config.education_link, link)
        self.assertNotIn(link, repr(config))

    def test_isolated_instance_never_falls_back_to_production_database(self):
        env = {"SMH_ISOLATED_TEST_INSTANCE": "true",
               "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
               "SMH_TEST_ADMIN_TELEGRAM_ID": "42",
               "SMH_TEST_PRO_SIGNALS_CHANNEL_ID": "-1001",
               "SMH_TEST_MARKET_ANALYSIS_CHANNEL_ID": "-1002",
               "DATABASE_URL": "postgresql://production.invalid/database"}
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, "SMH_TEST_DATABASE_URL"):
            Config.load()

    def test_isolated_instance_rejects_unapproved_database_schema(self):
        env = {"SMH_ISOLATED_TEST_INSTANCE": "true",
               "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
               "SMH_TEST_DATABASE_SCHEMA": "smh"}
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, "smh_test schema"):
            Config.load()

    def test_isolated_discovery_mode_can_use_local_sqlite_without_publishing(self):
        env = {"SMH_ISOLATED_TEST_INSTANCE": "true", "SMH_TEST_MODE": "1",
               "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
               "SMH_TEST_DATA_DIR": "isolated-test-data",
               "DATABASE_URL": "postgresql://production.invalid/database",
               "SMH_ALLOW_PUBLISHING": "true"}
        with patch.dict(os.environ, env, clear=True):
            c = Config.load()
        self.assertEqual(c.database_url, "")
        self.assertEqual(c.database_schema, "smh_test")
        self.assertTrue(c.isolated_test)
        self.assertFalse(c.allow_publishing)

    def test_video_destination_and_storage_are_separate_in_isolated_mode(self):
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
            "SMH_TEST_ADMIN_TELEGRAM_ID": "42",
            "SMH_TEST_PRO_SIGNALS_CHANNEL_ID": "-1000000001",
            "SMH_TEST_MARKET_ANALYSIS_CHANNEL_ID": "-1000000002",
            "SMH_TEST_EDUCATION_GROUP_ID": "-1000000003",
            "SMH_TEST_EDUCATION_VIDEO_GROUP_ID": "-1000000004",
            "SMH_TEST_EDUCATION_VIDEO_TOPIC_ID": "8",
            "SMH_TEST_DATA_DIR": "test-bot-data",
            "SMH_TEST_DATABASE_URL": "postgresql://test.invalid/test_db",
            "SMH_TEST_ALLOW_PUBLISHING": "false",
            "TELEGRAM_BOT_TOKEN": "123:production-token",
            "SMH_EDUCATION_VIDEO_GROUP_ID": "-1000000005",
            "SMH_EDUCATION_VIDEO_TOPIC_ID": "9",
            "SMH_ALLOW_PUBLISHING": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config.load()
        self.assertEqual(config.education_video_group_id, -1000000004)
        self.assertEqual(config.education_video_topic_id, 8)
        self.assertEqual(config.education_video_topic_name, "Video tutorials")
        self.assertEqual(config.education_video_data_dir, Path("test-bot-data/education-videos").resolve())
        self.assertFalse(config.allow_publishing)
        self.assertNotIn("-1000000004", repr(config))

    def test_production_video_destination_uses_its_own_smh_settings(self):
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:dummy",
            "ADMIN_TELEGRAM_ID": "42",
            "PRO_SIGNALS_CHANNEL_ID": "-1000000001",
            "MARKET_ANALYSIS_CHANNEL_ID": "-1000000002",
            "EDUCATION_GROUP_ID": "-1000000003",
            "SMH_EDUCATION_VIDEO_GROUP_ID": "-1004000000004",
            "SMH_EDUCATION_VIDEO_TOPIC_ID": "8",
            "EDUCATION_MARKET_STRUCTURE_VIDEO_URL": "https://t.me/c/4000000004/8/125",
            "SMH_DATABASE_URL": "postgresql://test.invalid/prod_config_test",
            "SMH_DATA_DIR": "bot-data",
            "SMH_ALLOW_PUBLISHING": "false",
        }, clear=True):
            config = Config.load()
        self.assertEqual(config.education_video_group_id, -1004000000004)
        self.assertEqual(config.education_video_topic_id, 8)
        self.assertEqual(config.education_video_data_dir, Path("bot-data/education-videos").resolve())
        self.assertEqual(
            config.education_market_structure_video_url,
            "https://t.me/c/4000000004/8/125",
        )

    def test_video_destination_must_not_overlap_member_or_trading_channels(self):
        common = {
            "TELEGRAM_BOT_TOKEN": "123:dummy",
            "SMH_TEST_MODE": "1",
            "PRO_SIGNALS_CHANNEL_ID": "-1000000001",
            "MARKET_ANALYSIS_CHANNEL_ID": "-1000000002",
            "EDUCATION_GROUP_ID": "-1000000003",
            "SMH_EDUCATION_VIDEO_TOPIC_ID": "8",
        }
        for group_id in ("-1000000001", "-1000000002", "-1000000003", "-10"):
            env = {**common, "SMH_EDUCATION_VIDEO_GROUP_ID": group_id}
            with patch.dict(os.environ, env, clear=True), self.subTest(group_id=group_id):
                with self.assertRaises(ValueError):
                    Config.load()

    def test_shared_education_forum_is_allowed_only_with_distinct_topics(self):
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
            "SMH_TEST_ADMIN_TELEGRAM_ID": "42",
            "SMH_TEST_PRO_SIGNALS_CHANNEL_ID": "-1000000001",
            "SMH_TEST_MARKET_ANALYSIS_CHANNEL_ID": "-1000000002",
            "SMH_TEST_EDUCATION_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_LINK": "https://t.me/+education-test",
            "SMH_TEST_EDUCATION_ANNOUNCEMENT_URL": "https://t.me/c/3916437804/3",
            "SMH_TEST_EDUCATION_DEMO_ACCOUNT_URL": "https://t.me/c/3916437804/2/57",
            "SMH_TEST_EDUCATION_EPISODE_01_URL": "https://t.me/c/3916437804/6/23",
            "SMH_TEST_EDUCATION_EPISODE_02_VIDEO_URL": "https://t.me/c/3916437804/8/143",
            "SMH_TEST_EDUCATION_EPISODE_02_PDF_URL": "https://t.me/c/3916437804/6/24",
            "SMH_TEST_EDUCATION_MARKET_STRUCTURE_VIDEO_URL": "https://t.me/c/3916437804/8/125",
            "SMH_TEST_COACH_BOT_URL": "https://t.me/smh_coach_test_bot",
            "SMH_TEST_EDUCATION_ONBOARDING_ENABLED": "true",
            "SMH_TEST_EDUCATION_DAY2_MODE": "online",
            "SMH_TEST_EDUCATION_VIDEO_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_VIDEO_TOPIC_ID": "8",
            "SMH_TEST_DATA_DIR": "test-bot-data",
            "SMH_TEST_DATABASE_URL": "postgresql://test.invalid/test_db",
            "SMH_TEST_ALLOW_PUBLISHING": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config.load()
        self.assertEqual(config.education_group_id, config.education_video_group_id)
        self.assertEqual(config.education_video_topic_id, 8)
        self.assertTrue(config.education_onboarding_enabled)
        self.assertEqual(config.education_announcement_url, "https://t.me/c/3916437804/3")
        self.assertEqual(
            config.education_market_structure_video_url,
            "https://t.me/c/3916437804/8/125",
        )
        self.assertEqual(
            config.education_episode_02_video_url,
            "https://t.me/c/3916437804/8/143",
        )
        self.assertEqual(
            config.education_episode_02_pdf_url,
            "https://t.me/c/3916437804/6/24",
        )
        self.assertEqual(config.education_demo_account_url, "https://t.me/c/3916437804/2/57")
        self.assertEqual(config.education_coach_bot_url, "https://t.me/smh_coach_test_bot")
        self.assertEqual(config.education_day2_mode, "online")
        self.assertFalse(config.allow_publishing)
        self.assertNotIn("3916437804", repr(config))

    def test_onboarding_fails_closed_without_coach_link(self):
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
            "SMH_TEST_EDUCATION_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_LINK": "https://t.me/+education-test",
            "SMH_TEST_EDUCATION_ANNOUNCEMENT_URL": "https://t.me/c/3916437804/3",
            "SMH_TEST_EDUCATION_EPISODE_01_URL": "https://t.me/c/3916437804/6/23",
            "SMH_TEST_EDUCATION_ONBOARDING_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "Coach bot links"):
                Config.load()

    def test_episode_02_video_must_use_configured_video_topic(self):
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
            "SMH_TEST_EDUCATION_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_VIDEO_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_VIDEO_TOPIC_ID": "8",
            "SMH_TEST_EDUCATION_EPISODE_02_VIDEO_URL": "https://t.me/c/3916437804/9/143",
        }
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(
                ValueError, "SMH_TEST_EDUCATION_EPISODE_02_VIDEO_URL must point to the configured Education video topic"):
            Config.load()

    def test_episode_02_pdf_must_point_to_education_group(self):
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
            "SMH_TEST_EDUCATION_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_EPISODE_02_PDF_URL": "https://t.me/c/3916437805/6/24",
        }
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(
                ValueError, "SMH_TEST_EDUCATION_EPISODE_02_PDF_URL must point to EDUCATION_GROUP_ID"):
            Config.load()

    def test_production_does_not_read_isolated_episode_02_video_link(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "123:dummy",
            "DATABASE_URL": "postgresql://test.invalid/prod_db",
            "SMH_TEST_EDUCATION_EPISODE_02_VIDEO_URL": "https://t.me/c/3916437804/8/143",
            "SMH_TEST_EDUCATION_EPISODE_02_PDF_URL": "https://t.me/c/3916437804/6/24",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config.load()
        self.assertFalse(config.isolated_test)
        self.assertEqual(config.education_episode_02_video_url, "")
        self.assertEqual(config.education_episode_02_pdf_url, "")

    def test_coach_bot_link_must_be_an_https_t_me_link(self):
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
            "SMH_TEST_COACH_BOT_URL": "https://example.com/not-a-bot",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "SMH_TEST_COACH_BOT_URL"):
                Config.load()

    def test_shared_education_forum_rejects_video_topic_collision(self):
        env = {
            "SMH_ISOLATED_TEST_INSTANCE": "true",
            "SMH_TEST_TELEGRAM_BOT_TOKEN": "456:test-token",
            "SMH_TEST_ADMIN_TELEGRAM_ID": "42",
            "SMH_TEST_PRO_SIGNALS_CHANNEL_ID": "-1000000001",
            "SMH_TEST_MARKET_ANALYSIS_CHANNEL_ID": "-1000000002",
            "SMH_TEST_EDUCATION_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_LINK": "https://t.me/+education-test",
            "SMH_TEST_EDUCATION_ANNOUNCEMENT_URL": "https://t.me/c/3916437804/7/35",
            "SMH_TEST_EDUCATION_EPISODE_01_URL": "https://t.me/c/3916437804/6/23",
            "SMH_TEST_EDUCATION_VIDEO_GROUP_ID": "-1003916437804",
            "SMH_TEST_EDUCATION_VIDEO_TOPIC_ID": "6",
            "SMH_TEST_DATA_DIR": "test-bot-data",
            "SMH_TEST_DATABASE_URL": "postgresql://test.invalid/test_db",
            "SMH_TEST_ALLOW_PUBLISHING": "false",
        }
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(
                ValueError, "Video tutorials topic must differ"):
            Config.load()

    def test_production_cannot_share_member_access_and_video_group(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "123:dummy",
            "ADMIN_TELEGRAM_ID": "42",
            "PRO_SIGNALS_CHANNEL_ID": "-1000000001",
            "MARKET_ANALYSIS_CHANNEL_ID": "-1000000002",
            "EDUCATION_GROUP_ID": "-1003916437804",
            "EDUCATION_ANNOUNCEMENT_URL": "https://t.me/c/3916437804/7/35",
            "EDUCATION_EPISODE_01_URL": "https://t.me/c/3916437804/6/23",
            "SMH_EDUCATION_VIDEO_GROUP_ID": "-1003916437804",
            "SMH_EDUCATION_VIDEO_TOPIC_ID": "8",
            "SMH_TEST_MODE": "1",
        }
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(
                ValueError, "Production must keep"):
            Config.load()


class RuntimeMessageTests(unittest.TestCase):
    def test_permission_error_explains_member_next_step(self):
        message = friendly_error(PermissionError("internal permission detail"))
        self.assertIn("administrator only", message)
        self.assertIn("main menu", message)
        self.assertNotIn("/", message)
        self.assertNotIn("internal permission detail", message)

    def test_unexpected_error_is_friendly_and_does_not_leak_exception(self):
        message = friendly_error(RuntimeError("token=private-value database traceback"))
        self.assertIn("try again shortly", message)
        self.assertIn("contact an administrator", message)
        self.assertNotIn("private-value", message)
        self.assertNotIn("traceback", message)

    def test_input_error_keeps_the_expected_format(self):
        message = friendly_error(ValueError("Enter a price such as 2650.50."))
        self.assertIn("2650.50", message)
        self.assertIn("⚠️", message)


class DomainTests(unittest.TestCase):
    def test_instant_confirmation_no_levels(self):
        for direction in ("BUY", "SELL"):
            text = confirmation(direction, "XAUUSD")
            self.assertIn(f"{direction} NOW", text)
            self.assertNotIn("SL", text)

    def test_price_validation(self):
        for text in ("NaN", "Infinity", "-1", "0", "abc", "1e999"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                price(text)
        self.assertEqual(price("2650.50"), "2650.50")

    def test_entry_zone(self):
        self.assertEqual(entry("20-25"), "20–25")
        with self.assertRaises(ValueError):
            entry("30-20")

    def test_entry_activates(self):
        t, _ = change(trade(), "entry", "2650-2655")
        self.assertEqual(t["state"], "ACTIVE")

    def test_stop_and_trail(self):
        t, sl_text = change(trade(), "sl", "2600")
        self.assertIn("Stop Loss Updated", sl_text)
        self.assertIn("Pair: XAUUSD", sl_text)
        self.assertIn("Direction: BUY", sl_text)
        self.assertIn("New SL: 2600", sl_text)
        self.assertIn("Follow your risk-management plan", sl_text)
        t, text = change(t, "trail", "2630")
        self.assertEqual(t["sl"], "2630")
        self.assertIn("Trailing Stop Updated", text)
        self.assertIn("New SL: 2630", text)

    def test_stop_loss_and_take_profit_can_be_updated_together(self):
        t, text = change(trade(), "sl_tp", "SL 2580 | TP1 2700")
        self.assertEqual(t["sl"], "2580")
        self.assertEqual(t["targets"]["1"], {"price": "2700", "hit": False})
        self.assertIn("Stop Loss: 2580", text)
        self.assertIn("TP1: 2700", text)
        self.assertIn("risk-management plan", text)

        for value in (
            "2580 | 1 2700",
            "SL NaN | TP1 2700",
            "SL 2580 | TP0 2700",
            "SL 2580 | TP101 2700",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                change(trade(), "sl_tp", value)

        hit_trade, _ = change(trade(), "tp", "1 2700")
        hit_trade, _ = change(hit_trade, "hit", "1|final")
        with self.assertRaisesRegex(ValueError, "already recorded as hit"):
            change(hit_trade, "sl_tp", "SL 2580 | TP1 2710")

    def test_targets_add_correct_hit(self):
        t, _ = change(trade(), "tp", "4 2800")
        t, _ = change(t, "tp", "5 2900")
        with self.assertRaisesRegex(ValueError, "Partial or Final"):
            change(t, "hit", "4")
        t, text = change(t, "hit", "4|partial")
        self.assertTrue(t["targets"]["4"]["hit"])
        self.assertIn("Status: PARTIAL", text)
        t, text = change(t, "hit", "5|final")
        self.assertIn("Status: FINAL TARGET", text)
        self.assertEqual(t["targets"]["5"]["hit_status"], "final")
        with self.assertRaises(ValueError):
            change(t, "hit", "5|final")

    def test_invalid_target(self):
        for value in ("0 25", "101 25", "abc", "1 NaN"):
            with self.assertRaises(ValueError):
                change(trade(), "tp", value)
        t, text = change(trade(), "tp", "100 5000")
        self.assertEqual(t["targets"]["100"]["price"], "5000")
        self.assertIn("TP100: 5000", text)

    def test_partial_reports_are_explicit(self):
        _, text = change(trade(), "partial", "25|recommendation")
        self.assertNotIn("secured", text)
        self.assertNotIn("RISK MANAGEMENT UPDATE", text)
        _, text = change(trade(), "partial", "50|reported|2800|remaining runner")
        self.assertIn("Partial Profits Secured", text)
        self.assertIn("Target: 2800", text)
        self.assertIn("Closed: 50%", text)
        self.assertIn("RISK MANAGEMENT UPDATE", text)
        self.assertIn("move your SL to BREAKEVEN", text)
        self.assertNotIn("RISK-FREE UPDATE", text)
        self.assertIn("Remaining position: remaining runner", text)
        with self.assertRaisesRegex(ValueError, "confirmed take-profit"):
            change(trade(), "partial", "50|reported")
        with self.assertRaises(ValueError):
            change(trade(), "partial", "50|reported|not-a-price")
        with self.assertRaises(ValueError):
            change(trade(), "partial", "101|reported|2800")

    def test_generated_trade_update_templates_never_show_internal_trade_ids(self):
        pending = trade()
        active = {**trade(), "state": "ACTIVE", "entry": "2600",
                  "targets": {"1": {"price": "2700", "hit": False}}}
        messages = [
            change(pending, "entry", "2650")[1],
            change(pending, "sl", "2580")[1],
            change(pending, "sl_tp", "SL 2580 | TP1 2700")[1],
            change(pending, "tp", "1 2700")[1],
            change(pending, "partial", "25|reported|2700")[1],
            change(active, "be", "confirmed")[1],
            change(active, "trail", "2580")[1],
            change(active, "hit", "1|partial")[1],
            change(pending, "cancel", "confirmation withdrawn")[1],
            change(active, "invalidate", "setup conditions changed")[1],
            change(active, "close", "Win")[1],
            change(pending, "custom", "Session update.")[1],
        ]
        for text in messages:
            with self.subTest(text=text):
                self.assertNotIn("trade1", text)
                self.assertNotRegex(text, r"(?i)\bTrade\s*(?:ID|#)")
                self.assertNotRegex(text, r"(?<!\w)#[A-Za-z0-9_-]+")

    def test_public_text_removes_internal_references_but_not_market_values(self):
        text = (
            "🔴 SELL NOW — XAUUSD\n"
            "Trading zone: 2650–2655\n"
            "Trade ID: trade-id-123456\n"
            "Operation: 847291\n"
            "Database ID: db-000023\n"
            "Message ID: 111222\n"
            "Channel ID: -10012345678\n"
            "Original channel post #90210\n"
            "Reference: #SMH-2026-001\n"
            "Ref no. 763355\n\n"
            "Confirmation received. Follow your trading plan."
        )
        cleaned = clean_channel_text(text, ["trade-id-123456"])
        self.assertIn("SELL NOW — XAUUSD", cleaned)
        self.assertIn("2650–2655", cleaned)
        self.assertIn("Confirmation received.", cleaned)
        for internal in (
            "trade-id-123456", "847291", "db-000023", "111222", "-10012345678",
            "90210", "#SMH-2026-001", "763355", "Trade ID", "Database ID",
            "Message ID", "Channel ID", "Reference:", "Ref no.",
        ):
            self.assertNotIn(internal, cleaned)

    def test_second_partial_message_requires_confirmed_breakeven(self):
        first, _ = change(trade(), "partial", "25|reported|2700")
        self.assertEqual(first["partial_count"], 1)

        recommendation, _ = change(first, "partial", "25|recommendation")
        self.assertEqual(recommendation["partial_count"], 1)

        second, text_without_be = change(first, "partial", "25|reported|2750")
        self.assertEqual(second["partial_count"], 2)
        self.assertNotIn("SECOND PARTIAL UPDATE", text_without_be)
        self.assertNotIn("Keep your SL at breakeven", text_without_be)

        trade_with_entry = {**first, "entry": "2600"}
        breakeven, be_text = change(trade_with_entry, "be", "confirmed")
        self.assertTrue(breakeven["breakeven_confirmed"])
        self.assertIn("Market risk is not eliminated", be_text)
        second_after_be, second_text = change(breakeven, "partial", "25|reported|2750")
        self.assertEqual(second_after_be["partial_count"], 2)
        self.assertIn("SECOND PARTIAL UPDATE", second_text)
        self.assertIn("Keep your SL at breakeven", second_text)

        changed_sl, _ = change(breakeven, "sl", "2580")
        self.assertFalse(changed_sl["breakeven_confirmed"])
        _, text_after_sl_change = change(changed_sl, "partial", "25|reported|2750")
        self.assertNotIn("SECOND PARTIAL UPDATE", text_after_sl_change)

    def test_breakeven_requires_manual_confirmation(self):
        with self.assertRaisesRegex(ValueError, "Confirm"):
            change(trade(), "be", "")
        active = {**trade(), "state": "ACTIVE", "entry": "2600"}
        updated, text = change(active, "be", "confirmed")
        self.assertEqual(updated["sl"], "2600")
        self.assertIn("Stop Loss Moved to Breakeven", text)
        self.assertIn("Market risk is not eliminated", text)
        self.assertNotIn("risk-free", text.lower())

    def test_cancel_only_before_active(self):
        t, text = change(trade(), "cancel", "confirmation was withdrawn")
        self.assertEqual(t["state"], "CANCELLED")
        self.assertIn("Unentered Setup Cancelled", text)
        self.assertIn("No entry was recorded", text)
        self.assertIn("Reason: confirmation was withdrawn", text)
        with self.assertRaises(ValueError):
            change({**trade(), "state": "ACTIVE"}, "cancel", "reason")
        with self.assertRaises(ValueError):
            change(trade(), "cancel", "")
        t, text = change({**trade(), "state": "ACTIVE", "entry": "2600"},
                         "invalidate", "structure invalidated")
        self.assertEqual(t["state"], "INVALIDATED")
        self.assertIn("Trade Invalidated", text)
        self.assertIn("Reason: structure invalidated", text)

    def test_close_outcomes_and_custom(self):
        for outcome in ("Win", "Breakeven", "Loss", "Unrecorded"):
            t, text = change(trade(), "close", f"{outcome}|2700|My note")
            self.assertEqual(t["state"], "CLOSED")
            self.assertEqual(t["exit"], "2700")
            self.assertIn("My note", text)
            self.assertIn(f"Result: {outcome.upper()}", text)
        _, text = change(trade(), "close", "Unrecorded||")
        self.assertIn("Exit: Not provided", text)
        _, text = change(trade(), "custom", "Spread is widening.")
        self.assertIn("Spread is widening.", text)

    def test_closed_trade_rejects_changes(self):
        with self.assertRaises(ValueError):
            change({**trade(), "state": "CLOSED"}, "sl", "10")

    def test_analysis_rejects_specific_trade_instructions(self):
        for text in (
                "BUY NOW",
                "SELL NOW",
                "Entry price: 2500",
                "Entry zone 2500-2505",
                "Stop loss: 2490",
                "Take profit at 2600",
                "SL: 2490",
                "TP1: 2600",
                "Target 1: 2600",
                "Move SL to breakeven",
                "Trail the stop-loss",
                "TP1 hit",
                "Close the trade",
                "Take 25% partial",
                "Go long",
                "buy gold at 2600",
                "BUY EURUSD"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_analysis(text)

    def test_analysis_allows_educational_discussion_of_trade_concepts(self):
        examples = (
            "A stop-loss helps define risk, while take-profit planning depends on market structure.",
            "Entry zones are areas for study, not instructions to enter a trade.",
            "Traders can compare risk and reward without treating this analysis as a signal.",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(validate_analysis(text), text)
        self.assertEqual(validate_analysis("H4 bullish bias; liquidity observed above recent highs."),
                         "H4 bullish bias; liquidity observed above recent highs.")

    def test_placeholder_rejected(self):
        with self.assertRaises(ValueError):
            validate_analysis("Bias: [your observation]")


class DatabaseTests(Base):
    def test_persisted_jpeg_extension_can_be_loaded(self):
        source = self.path / "chart.jpeg"
        source.write_bytes(b"jpeg chart fixture")
        image = {"image": str(source)}

        self.db.persist_images(image)

        restored = Path(self.db.image_path(image["image"]))
        self.assertEqual(restored.suffix, ".jpeg")
        self.assertEqual(restored.read_bytes(), source.read_bytes())

    def test_admin_and_private_only(self):
        self.config.authorize(42)
        for user, chat in ((8, "private"), (42, "group")):
            with self.assertRaises(PermissionError):
                self.config.authorize(user, chat)

    def test_strict_destinations(self):
        for kind in ("signal", "update", "edit"):
            self.assertEqual(self.config.destination(kind, "signals"), -1001)
            with self.assertRaises(ValueError):
                self.config.destination(kind, "analysis")
        self.assertEqual(self.config.destination("analysis", "analysis"), -1002)
        with self.assertRaises(ValueError):
            self.config.destination("analysis", "signals")

    def test_buttons_single_use_owner_expiry(self):
        key = self.db.button(42, "publish")
        with self.assertRaises(ValueError):
            self.db.consume(key, 5)
        self.assertEqual(self.db.consume(key, 42)[0], "publish")
        with self.assertRaises(ValueError):
            self.db.consume(key, 42)
        key = self.db.button(42, "menu")
        self.db.execute("UPDATE buttons SET expires=0 WHERE id=?", (key,))
        with self.assertRaises(ValueError):
            self.db.consume(key, 42)

    def test_draft_restart_and_revision(self):
        d = {"kind": "analysis", "text": "H4 bias"}
        self.db.save_draft(42, d)
        first = d["revision"]
        self.db.save_draft(42, d)
        self.assertNotEqual(first, d["revision"])
        self.db.conn.close()
        self.db = Database(self.path)
        self.assertEqual(self.db.draft(42)["text"], "H4 bias")

    def test_backup_restore_retention(self):
        self.db.put("test", 123)
        for _ in range(3):
            path = self.db.backup(2)
        self.assertEqual(len(list((self.path / "backups").glob("*.sqlite3"))), 2)
        with sqlite3.connect(path) as restored:
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(restored.execute("SELECT value FROM kv WHERE key='test'").fetchone()[0], "123")

    def test_foreign_keys_and_transaction_rollback(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO access VALUES (99,-1001,'joined','now')")
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO kv VALUES ('rollback','1')")
                raise RuntimeError()
        self.assertIsNone(self.db.get("rollback"))

    def test_single_host_poll_lock(self):
        lock = lock_process(self.config)
        try:
            with self.assertRaises(RuntimeError):
                lock_process(self.config)
        finally:
            lock.close()

    def test_images_annotations_and_original_preserved(self):
        raw = self.path / "chart.jpg"
        Image.new("RGB", (600, 400), "black").save(raw)
        original = import_chart(raw, self.path / "images")
        self.assertEqual(Path(original).read_bytes(), raw.read_bytes())
        before = Path(original).read_bytes()
        output = render(original, ["line 40 2650", "zone 20 30 80 60 FVG",
                                   "arrow 10 10 70 50 BOS", "label 5 5 CHoCH",
                                   "crop 5 5 95 95", "resize 1000 600"], self.path / "images")
        self.assertEqual(Path(original).read_bytes(), before)
        with Image.open(output) as image:
            self.assertEqual(image.width, 1000)
            self.assertGreater(image.height, 600)
        for command in ("line 101", "zone 90 90 10 10", "resize 1 1", "arrow nan 0 1 2", "shell rm"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                render(original, [command], self.path / "images")


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name)
        self.config = Config("123456789:TEST_TOKEN_NOT_REAL", 42, -1001, -1002, Path(self.tmp.name))
        self.bot = NS(send_message=AsyncMock(return_value=NS(message_id=90)),
                      send_photo=AsyncMock(return_value=NS(message_id=91)),
                      edit_message_text=AsyncMock(return_value=NS(message_id=90)),
                      create_chat_invite_link=AsyncMock(return_value=NS(invite_link="https://t.me/+example")),
                      get_me=AsyncMock(return_value=NS(id=1)))
        self.pub = Publisher(self.db, self.config, self.bot)

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def signal(self, direction="BUY"):
        from smh.zones import activate, parse_zone, signal_payload, validate_signal_levels
        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        setup["confirmation"] = "Mock observed M15 confirmation"
        setup["setup_message_id"] = 89
        activate(self.db, setup, None)
        levels = validate_signal_levels(
            setup, direction, "2653",
            "2640" if direction == "BUY" else "2660",
            "2670" if direction == "BUY" else "2635",
        )
        payload = signal_payload(setup, direction, 42, levels)
        payload["trade"]["id"] = "trade1"
        return self.pub.prepare(42, "signal", payload)

    def update_obj(self, user=42, text=""):
        return NS(effective_user=NS(id=user), effective_chat=NS(id=user, type="private"),
                  message=NS(text=text, forward_origin=None), callback_query=NS(answer=AsyncMock()))

    def ui(self):
        from smh.handlers import Handlers
        from smh.health import Health
        return Handlers(self.db, self.config, self.bot, self.pub, Health(self.db, self.config, self.bot))

    async def test_signal_and_duplicate_tap(self):
        op = self.signal()
        await self.pub.send(42, op)
        await self.pub.send(42, op)
        self.assertEqual(self.bot.send_message.await_count, 1)
        self.assertEqual(self.db.trade("trade1")["state"], "CONFIRMED_BUY")
        self.assertEqual(self.db.trade("trade1")["message_id"], 90)

    async def test_sell_confirmation(self):
        op = self.signal("SELL")
        await self.pub.send(42, op)
        self.assertEqual(self.db.trade("trade1")["state"], "CONFIRMED_SELL")

    async def test_publisher_authorization(self):
        op = self.signal()
        with self.assertRaises(PermissionError):
            await self.pub.send(7, op)
        self.bot.send_message.assert_not_called()

    async def test_zone_tapped_posts_to_both_channels_once_and_replies_to_zone(self):
        from dataclasses import replace
        from smh.zones import activate, parse_zone

        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | M15 bullish close")
        setup["setup_message_id"] = 89
        activate(self.db, setup, None)
        config = replace(self.config, allow_publishing=True)
        publisher = Publisher(self.db, config, self.bot)
        publisher.verify_destinations = AsyncMock()

        operations = publisher.prepare_zone_tapped(42, setup["id"])
        self.assertEqual(set(operations), {"signals", "analysis"})
        for destination in ("signals", "analysis"):
            await publisher.send(42, operations[destination])

        sent_calls = list(self.bot.send_message.await_args_list)
        self.assertEqual([call.args[0] for call in sent_calls], [-1001, -1002])
        self.assertIn("NO CONFIRMATION, NO ENTRY", sent_calls[0].args[1])
        self.assertNotIn("BUY NOW", sent_calls[0].args[1])
        self.assertEqual(
            sent_calls[0].kwargs["reply_parameters"].message_id, 89)
        self.assertIsNone(sent_calls[1].kwargs["reply_parameters"])

        repeated = publisher.prepare_zone_tapped(42, setup["id"])
        self.assertEqual(repeated, operations)
        for destination in ("signals", "analysis"):
            await publisher.send(42, repeated[destination])
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_linked_market_analysis_post_receives_zone_tapped_reply(self):
        from dataclasses import replace
        from smh.zones import activate, parse_zone, public_status

        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        setup["setup_message_id"] = 89
        setup["caption_status"] = public_status(setup)
        activate(self.db, setup, None)
        analysis_operation = self.pub.prepare(42, "analysis", {
            "destination": "analysis",
            "text": "Gold market structure and the marked point of interest.",
        })
        self.db.execute(
            "UPDATE operations SET status='done',message_id=321 WHERE id=?",
            (analysis_operation,),
        )

        ui = self.ui()
        await ui.zone_analysis_link_list(self.update_obj(), setup["id"])
        link_actions = [
            row["action"] for row in self.db.rows(
                "SELECT action FROM buttons WHERE owner=?", (42,))
        ]
        self.assertIn("zone_analysis_link", link_actions)
        await ui.zone_analysis_link(self.update_obj(), setup["id"], analysis_operation)
        linked_setup = self.db.get("active_setup")
        self.assertEqual(linked_setup["market_analysis_message_id"], 321)
        self.bot.send_message.reset_mock()

        publisher = Publisher(
            self.db, replace(self.config, allow_publishing=True), self.bot)
        publisher.verify_destinations = AsyncMock()
        operations = publisher.prepare_zone_tapped(42, setup["id"])
        analysis_payload = publisher.operation(operations["analysis"])[1]
        self.assertEqual(analysis_payload["analysis_message_id"], 321)
        await publisher.send(42, operations["signals"])
        await publisher.send(42, operations["analysis"])
        self.assertEqual(self.bot.send_message.await_args_list[0].kwargs[
            "reply_parameters"].message_id, 89)
        self.assertEqual(self.bot.send_message.await_args_list[1].kwargs[
            "reply_parameters"].message_id, 321)

        with self.assertRaisesRegex(ValueError, "already prepared"):
            await ui.zone_analysis_unlink(self.update_obj(), setup["id"])

    async def test_zone_tapped_publishing_off_and_expired_zone_make_no_telegram_calls(self):
        from dataclasses import replace
        from smh.zones import activate, parse_zone

        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | -")
        setup["setup_message_id"] = 89
        activate(self.db, setup, None)
        disabled = Publisher(self.db, replace(self.config, allow_publishing=False), self.bot)
        with self.assertRaisesRegex(ValueError, "Publishing is OFF"):
            disabled.prepare_zone_tapped(42, setup["id"])
        self.bot.send_message.assert_not_called()

        expired = {**setup, "expires": time.time() - 1}
        with self.db.transaction() as connection:
            from smh.zones import save_in
            save_in(connection, expired)
        enabled = Publisher(
            self.db, replace(self.config, allow_publishing=True), self.bot)
        with self.assertRaisesRegex(ValueError, "expired"):
            enabled.prepare_zone_tapped(42, setup["id"])
        self.bot.send_message.assert_not_called()

    async def test_zone_category_exposes_zone_tapped_control_for_active_setup(self):
        from smh.zones import activate, parse_zone, public_status

        setup = parse_zone("Gold/XAUUSD | 2650-2655 | M15 | 60 | M15 bullish close")
        setup["setup_message_id"] = 89
        setup["caption_status"] = public_status(setup)
        activate(self.db, setup, None)

        await self.ui().admin_category(self.update_obj(), "zone")

        actions = {
            row["action"] for row in self.db.rows(
                "SELECT action FROM buttons WHERE owner=?", (42,))
        }
        self.assertIn("zone_tapped", actions)
        self.assertIn("zone_analysis_link_list", actions)
        self.assertIn("A POI touch is not confirmation",
                      self.bot.send_message.await_args.args[1])

    async def test_publisher_rejects_wrong_destination(self):
        with self.assertRaises(ValueError):
            self.pub.prepare(42, "analysis", {"destination": "signals", "text": "Bullish structure"})
        with self.assertRaises(ValueError):
            self.pub.prepare(42, "analysis", {"destination": "analysis", "text": "BUY NOW"})

    async def test_publisher_accepts_educational_trade_concepts_without_posting(self):
        text = ("A stop-loss helps define risk, while take-profit planning and entry selection "
                "should be considered in the context of market structure.")
        operation = self.pub.prepare(42, "analysis", {"destination": "analysis", "text": text})
        self.assertTrue(operation)
        self.bot.send_message.assert_not_awaited()

    async def test_network_uncertainty_never_retried(self):
        op = self.signal()
        self.bot.send_message.side_effect = NetworkError("timeout")
        with self.assertRaises(ValueError):
            await self.pub.send(42, op)
        with self.assertRaises(ValueError):
            await self.pub.send(42, op)
        self.assertEqual(self.pub.operation(op)[0]["status"], "uncertain")
        self.assertEqual(self.bot.send_message.await_count, 1)

    async def test_rate_limit_safe_retry(self):
        op = self.signal()
        self.bot.send_message.side_effect = [RetryAfter(0), NS(message_id=90)]
        with patch("smh.publishing.asyncio.sleep", new=AsyncMock()):
            await self.pub.send(42, op)
        self.assertEqual(self.pub.operation(op)[0]["status"], "done")

    async def test_long_rate_limit_honored(self):
        op = self.signal()
        self.bot.send_message.side_effect = RetryAfter(120)
        await self.pub.send(42, op)
        self.assertEqual(self.pub.operation(op)[0]["status"], "retryable")
        with self.assertRaises(ValueError):
            await self.pub.send(42, op)

    async def test_telegram_rejection(self):
        op = self.signal()
        self.bot.send_message.side_effect = BadRequest("no access")
        with self.assertRaises(ValueError):
            await self.pub.send(42, op)
        self.assertEqual(self.pub.operation(op)[0]["status"], "failed")

    async def test_success_sql_failure_receipt_reconciles(self):
        op = self.signal()
        with patch.object(self.pub, "finalize", side_effect=sqlite3.OperationalError("disk")):
            with self.assertRaises(ValueError):
                await self.pub.send(42, op)
        self.pub.recover()
        self.assertEqual(self.pub.operation(op)[0]["status"], "done")
        self.assertEqual(self.bot.send_message.await_count, 1)

    async def test_restart_quarantines_sending(self):
        op = self.signal()
        self.db.execute("UPDATE operations SET status='sending' WHERE id=?", (op,))
        self.pub.recover()
        self.assertEqual(self.pub.operation(op)[0]["status"], "uncertain")

    async def test_manual_reconciliation(self):
        op = self.signal()
        self.db.execute("UPDATE operations SET status='uncertain' WHERE id=?", (op,))
        await self.pub.reconcile(42, op, 95)
        self.assertEqual(self.db.trade("trade1")["message_id"], 95)
        self.bot.send_message.assert_not_called()

    async def test_update_versions_and_reply(self):
        await self.pub.send(42, self.signal())
        t = self.db.trade("trade1")
        changed, text = change(t, "entry", "2600")
        self.assertNotIn("trade1", text)
        self.assertNotIn("Trade #", text)
        payload = {"destination": "signals", "trade": changed, "text": text, "expected_version": t["version"]}
        op = self.pub.prepare(42, "update", payload)
        with self.assertRaises(ValueError):
            self.pub.prepare(42, "update", payload)
        await self.pub.send(42, op)
        self.assertEqual(self.db.trade("trade1")["state"], "ACTIVE")
        self.assertEqual(self.bot.send_message.call_args.kwargs["reply_parameters"].message_id, 90)
        self.assertTrue(self.bot.send_message.call_args.kwargs["reply_parameters"].allow_sending_without_reply)
        self.assertNotIn("trade1", self.bot.send_message.call_args.args[1])
        self.assertNotIn("90", self.bot.send_message.call_args.args[1])
        self.assertNotIn("Original channel post", self.bot.send_message.call_args.args[1])
        with self.assertRaises(ValueError):
            self.pub.prepare(42, "update", payload)

    async def test_publisher_cleans_freeform_references_and_keeps_internal_records(self):
        await self.pub.send(42, self.signal())
        source = self.db.trade("trade1")
        changed, text = change(
            source,
            "custom",
            "Trend remains intact.\nTrade ID: trade1\nOperation: 847291\nOriginal channel post #90",
        )
        op = self.pub.prepare(42, "update", {
            "destination": "signals",
            "trade": changed,
            "text": text,
            "expected_version": source["version"],
        })
        row, payload = self.pub.operation(op)
        self.assertEqual(row["id"], op)
        self.assertEqual(payload["trade"]["id"], "trade1")
        self.assertNotIn("trade1", payload["text"])
        self.assertNotIn("847291", payload["text"])
        self.assertNotIn("90", payload["text"])
        self.assertNotIn(op, payload["text"])

        await self.pub.send(42, op)
        sent_text = self.bot.send_message.await_args_list[-1].args[1]
        self.assertIn("Trend remains intact.", sent_text)
        self.assertNotIn("trade1", sent_text)
        self.assertNotIn("847291", sent_text)
        self.assertNotIn("Original channel post", sent_text)
        self.assertEqual(self.db.trade("trade1")["id"], "trade1")
        self.assertEqual(self.pub.operation(op)[0]["id"], op)

    async def test_legacy_prepared_send_is_cleaned_and_requires_fresh_review(self):
        op = self.signal()
        _, payload = self.pub.operation(op)
        payload["text"] += "\nTrade ID: trade1\nOperation: 847291\nOriginal channel post #90"
        self.db.execute("UPDATE operations SET payload=? WHERE id=?", (json.dumps(payload), op))

        with self.assertRaisesRegex(ValueError, "Review the clean message"):
            await self.pub.send(42, op)
        self.bot.send_message.assert_not_called()
        cleaned_payload = self.pub.operation(op)[1]
        self.assertNotIn("trade1", cleaned_payload["text"])
        self.assertNotIn("847291", cleaned_payload["text"])
        self.assertNotIn("90", cleaned_payload["text"])
        self.assertEqual(self.pub.operation(op)[0]["id"], op)
        self.assertEqual(self.db.rows("SELECT id FROM operations WHERE id=?", (op,))[0]["id"], op)

        await self.ui().operation_screen(self.update_obj(), op)
        operation_preview = self.bot.send_message.await_args.args[1]
        self.assertIn(op, operation_preview)  # Internal operation ID is visible only in the admin UI.
        for reference in ("trade1", "847291", "#90", "Trade ID", "Original channel post"):
            self.assertNotIn(reference, operation_preview)

        await self.pub.send(42, op)
        sent_text = self.bot.send_message.await_args.args[1]
        self.assertNotIn("trade1", sent_text)
        self.assertNotIn("847291", sent_text)
        self.assertNotIn("Original channel post", sent_text)
        self.assertEqual(self.db.trade("trade1")["id"], "trade1")

    async def test_edit_signal(self):
        await self.pub.send(42, self.signal())
        t = self.db.trade("trade1")
        op = self.pub.prepare(42, "edit", {"destination": "signals", "trade": t,
                                           "expected_version": t["version"],
                                           "text": "Revised BUY confirmation.\nTrade ID: trade1\nOperation: 847291"})
        await self.pub.send(42, op)
        self.bot.edit_message_text.assert_awaited_once()
        self.assertEqual(self.db.trade("trade1")["original_text"], "Revised BUY confirmation.")
        self.assertNotIn("trade1", self.bot.edit_message_text.call_args.args[0])
        self.assertNotIn("847291", self.bot.edit_message_text.call_args.args[0])

    async def test_photo_analysis_destination(self):
        path = Path(self.tmp.name) / "images" / "chart.png"
        Image.new("RGB", (300, 300)).save(path)
        op = self.pub.prepare(42, "analysis", {
            "destination": "analysis",
            "text": "H4 bullish bias.\nTrade ID: trade1\nOperation: 847291",
            "image": str(path),
        })
        self.assertEqual(self.pub.operation(op)[1]["text"], "H4 bullish bias.")
        await self.pub.send(42, op)
        self.assertEqual(self.bot.send_photo.call_args.args[0], -1002)
        self.assertEqual(self.bot.send_photo.call_args.kwargs["caption"], "H4 bullish bias.")
        self.bot.send_message.assert_not_called()

    async def test_approved_invite_only_and_repeated_tap(self):
        with self.assertRaises(ValueError):
            self.pub.prepare(42, "invite", {"user": 77, "channel": -1001})
        self.db.execute("INSERT INTO applications VALUES (77,'[]','approved','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('verified-pro-77',77,'pro','[]','approved','verified','verified','new','now','now')")
        op = self.pub.prepare(42, "invite", {"user": 77, "channel": -1001})
        with self.assertRaisesRegex(ValueError, "existing invite operation"):
            self.pub.prepare(42, "invite", {"user": 77, "channel": -1001})
        await self.pub.send(42, op)
        await self.pub.send(42, op)
        self.bot.create_chat_invite_link.assert_awaited_once()
        self.assertTrue(self.bot.create_chat_invite_link.call_args.kwargs["creates_join_request"])
        self.assertIn("expires_at", self.db.get(f"invite:{op}"))
        expiry = datetime.fromisoformat(self.db.get(f"invite:{op}")["expires_at"])
        remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(remaining, 23 * 60 * 60)
        self.assertLessEqual(remaining, 24 * 60 * 60)
        self.assertEqual(self.pub.current_invite_operation(77, -1001), op)

    async def test_reissuing_invite_revokes_previous_link_and_tracks_latest(self):
        self.db.execute("INSERT INTO applications VALUES (77,'[]','approved','now')")
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
            "VALUES ('verified-pro-77',77,'pro','[]','approved','verified','verified','new','now','now')")
        self.bot.create_chat_invite_link.side_effect = [
            NS(invite_link="https://t.me/+old"),
            NS(invite_link="https://t.me/+new"),
        ]
        self.bot.revoke_chat_invite_link = AsyncMock(return_value=True)
        first = self.pub.prepare(42, "invite", {"user": 77, "channel": -1001})
        await self.pub.send(42, first)
        self.db.execute("UPDATE access SET status='joined' WHERE user_id=77 AND channel=-1001")
        second = self.pub.prepare(42, "invite", {"user": 77, "channel": -1001})
        await self.pub.send(42, second)
        self.bot.revoke_chat_invite_link.assert_awaited_once_with(
            chat_id=-1001, invite_link="https://t.me/+old")
        self.assertEqual(self.pub.current_invite_operation(77, -1001), second)
        self.assertEqual(self.db.get(f"invite:{second}")["invite_link"], "https://t.me/+new")
        self.assertEqual(self.db.rows("SELECT status FROM access WHERE user_id=77 AND channel=-1001")[0]["status"],
                         "joined")
        ui = self.ui()
        stale_request = NS(
            chat=NS(id=-1001), from_user=NS(id=77),
            invite_link=NS(invite_link="https://t.me/+old"),
            approve=AsyncMock(), decline=AsyncMock())
        await ui.join_request(NS(chat_join_request=stale_request), None)
        stale_request.decline.assert_awaited_once()
        current_request = NS(
            chat=NS(id=-1001), from_user=NS(id=77),
            invite_link=NS(invite_link="https://t.me/+new"),
            approve=AsyncMock(), decline=AsyncMock())
        await ui.join_request(NS(chat_join_request=current_request), None)
        current_request.approve.assert_awaited_once()
        self.db.execute("INSERT INTO applications VALUES (78,'[]','approved','now')")
        self.db.execute("INSERT INTO access VALUES (78,-1001,'invite_issued','now')")
        forwarded_request = NS(
            chat=NS(id=-1001), from_user=NS(id=78),
            invite_link=NS(invite_link="https://t.me/+new"),
            approve=AsyncMock(), decline=AsyncMock())
        await ui.join_request(NS(chat_join_request=forwarded_request), None)
        forwarded_request.decline.assert_awaited_once()

    async def test_education_group_permission_check_requires_invite_right(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003)
        self.pub.config = self.config
        self.bot.get_chat = AsyncMock(return_value=NS(id=-1003, type="supergroup", username=None))
        self.bot.get_me = AsyncMock(return_value=NS(id=999))
        self.bot.get_chat_member = AsyncMock(side_effect=[
            NS(status="administrator"),
            NS(status="administrator", can_invite_users=True),
        ])
        await self.pub.verify_education_group()
        self.assertEqual(self.bot.get_chat_member.await_count, 2)
        self.bot.get_chat_member = AsyncMock(side_effect=[
            NS(status="administrator"),
            NS(status="administrator", can_invite_users=False),
        ])
        with self.assertRaisesRegex(ValueError, "Invite Users permission"):
            await self.pub.verify_education_group()

    async def test_education_invite_is_blocked_before_creation_without_bot_permission(self):
        from dataclasses import replace
        self.config = replace(self.config, education_group_id=-1003, isolated_test=True)
        self.pub.config = self.config
        self.pub.verified = True
        self.bot.get_chat = AsyncMock(side_effect=[
            NS(id=self.config.admin, type="private"),
            NS(id=self.config.signals, type="channel", username=None),
            NS(id=self.config.analysis, type="channel", username=None),
            NS(id=-1003, type="supergroup", username=None),
        ])
        good_channel_admin = NS(status="administrator", can_post_messages=True,
                                can_edit_messages=True, can_invite_users=True)
        self.bot.get_chat_member = AsyncMock(side_effect=[
            good_channel_admin, good_channel_admin, good_channel_admin, good_channel_admin,
            NS(status="administrator"),
            NS(status="administrator", can_invite_users=False),
        ])
        self.db.execute("INSERT INTO applications VALUES (77,'[]','approved','now')")
        op = self.pub.prepare(42, "invite", {"user": 77, "channel": -1003})
        with self.assertRaisesRegex(ValueError, "Invite Users permission"):
            await self.pub.send(42, op)
        self.bot.create_chat_invite_link.assert_not_awaited()
        self.assertEqual(self.pub.operation(op)[0]["status"], "prepared")

    async def test_member_application_flow(self):
        ui = self.ui()
        u = self.update_obj(77, "I understand risk.")
        await ui.member_action(u, "member_apply", {})
        await ui.member_action(u, "member_apply_dest", {"destination": "analysis"})
        for _ in range(5):
            await ui.destination_application_answer(u, self.db.draft(77))
        request = self.db.rows("SELECT * FROM member_requests WHERE user_id=77 AND destination='analysis'")[0]
        self.assertEqual(request["status"], "pending_review")
        self.assertEqual(len(json.loads(request["answers"])), 5)
        self.assertIsNone(self.db.draft(77))

    async def test_approve_and_reject_confirmation(self):
        from dataclasses import replace
        self.config = replace(self.config, allow_publishing=False, isolated_test=True)
        self.pub.config = self.config
        self.pub.verified = True
        self.bot.get_chat = AsyncMock(side_effect=[
            NS(id=self.config.admin, type="private"),
            NS(id=self.config.signals, type="channel"),
            NS(id=self.config.analysis, type="channel")])
        self.bot.get_chat_member = AsyncMock(return_value=NS(
            status="administrator", can_post_messages=True, can_edit_messages=True, can_invite_users=True))
        ui = self.ui()
        for user, decision in ((77, "approved"), (78, "rejected")):
            self.db.execute("INSERT INTO applications VALUES (?,'[]','pending','now')", (user,))
            data = {"user": user, "status": decision}
            if decision == "approved":
                data["channels"] = [self.config.analysis]
            await ui.approve(self.update_obj(), data)
            self.assertEqual(self.db.rows("SELECT status FROM applications WHERE user_id=?", (user,))[0]["status"], decision)
            with self.assertRaises(ValueError):
                await ui.approve(self.update_obj(), data)
        self.assertEqual(self.bot.create_chat_invite_link.await_count, 1)

    async def test_approval_uncertain_invite_is_not_retried(self):
        from dataclasses import replace
        self.config = replace(self.config, allow_publishing=False, isolated_test=True)
        self.pub.config = self.config
        self.pub.verified = True
        self.bot.get_chat = AsyncMock(side_effect=[
            NS(id=self.config.admin, type="private"),
            NS(id=self.config.signals, type="channel"),
            NS(id=self.config.analysis, type="channel")])
        self.bot.get_chat_member = AsyncMock(return_value=NS(
            status="administrator", can_post_messages=True, can_edit_messages=True, can_invite_users=True))
        self.bot.create_chat_invite_link.side_effect = NetworkError("timeout")
        self.db.execute("INSERT INTO member_requests "
                        "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
                        "VALUES ('pro-77',77,'pro','[]','pending_review','verified','verified','new','now','now')")
        ui = self.ui()
        await ui.member_pro_approve_prompt(self.update_obj(), "pro-77")
        with self.assertRaisesRegex(ValueError, "uncertain result"):
            await ui.member_pro_approve_confirm(self.update_obj(), "pro-77")
        op = self.db.rows("SELECT id,status FROM operations WHERE kind='invite'")[0]
        self.assertEqual(op["status"], "uncertain")
        self.assertEqual(self.bot.create_chat_invite_link.await_count, 1)
        self.assertEqual(self.db.rows(
            "SELECT status FROM access WHERE user_id=77 AND channel=?",
            (self.config.signals,))[0]["status"], "invite_uncertain")
        self.assertEqual(self.db.rows("SELECT status FROM member_requests WHERE id='pro-77'")[0]["status"],
                         "approved")
        with self.assertRaisesRegex(ValueError, "existing invite operation"):
            self.pub.prepare(42, "invite", {"user": 77, "channel": self.config.signals})

    async def test_join_request_identity_gate(self):
        ui = self.ui()
        req = NS(chat=NS(id=-1001), from_user=NS(id=77), approve=AsyncMock(), decline=AsyncMock())
        await ui.join_request(NS(chat_join_request=req), None)
        req.decline.assert_awaited_once()
        self.db.execute("INSERT INTO applications VALUES (77,'[]','approved','now')")
        self.db.execute("INSERT INTO member_requests "
                        "(id,user_id,destination,answers,status,registration_status,funding_status,source,created,updated) "
                        "VALUES ('pro-join-77',77,'pro','[]','approved','verified','verified','new','now','now')")
        op = self.pub.prepare(42, "invite", {"user": 77, "channel": -1001})
        await self.pub.send(42, op)
        req.invite_link = NS(invite_link="https://t.me/+wrong")
        await ui.join_request(NS(chat_join_request=req), None)
        self.assertEqual(req.decline.await_count, 2)
        req.invite_link = NS(invite_link=self.db.get(f"invite:{op}")["invite_link"])
        await ui.join_request(NS(chat_join_request=req), None)
        req.approve.assert_awaited_once()

    async def test_admin_callback_member_blocked(self):
        ui = self.ui()
        u = self.update_obj(77)
        u.callback_query.data = self.db.button(77, "menu")
        with self.assertRaises(PermissionError):
            await ui.callback(u, None)

    async def test_stale_preview_rejected(self):
        ui = self.ui()
        d = {"kind": "signal"}
        self.db.save_draft(42, d)
        old = d["revision"]
        self.db.save_draft(42, d)
        with self.assertRaises(ValueError):
            ui.require_revision(42, {"revision": old})

    async def test_health_database_and_connectivity(self):
        health = self.ui().health
        report = await health.check()
        self.assertEqual(report["database"], "ok")
        self.assertEqual(report["telegram"], "reachable")
        self.bot.get_me.side_effect = NetworkError("offline")
        self.assertEqual((await health.check())["status"], "degraded")

    def test_command_center_health_is_persisted_only_for_isolated_test(self):
        from dataclasses import replace
        health = self.ui().health
        report = {
            "status": "healthy",
            "database": "ok",
            "telegram": "reachable",
            "seconds_since_poll": 3,
            "publishing_requested": True,
        }

        health.persist_command_center_health(report)
        self.assertIsNone(self.db.get("command_center_health"))

        health.config = replace(self.config, isolated_test=True)
        health.persist_command_center_health(report)
        snapshot = self.db.get("command_center_health")
        self.assertEqual(snapshot["status"], "healthy")
        self.assertEqual(snapshot["database"], "ok")
        self.assertEqual(snapshot["telegram"], "reachable")
        self.assertEqual(snapshot["seconds_since_poll"], 3)
        self.assertTrue(snapshot["publishing_requested"])
        self.assertTrue(snapshot["checked_at"])
        self.assertNotIn("token", snapshot)
        self.assertNotIn("admin", snapshot)

    async def test_poll_persists_offset_after_dispatch(self):
        health = self.ui().health
        stop = asyncio.Event()
        async def dispatch(update):
            self.assertEqual(self.db.get("telegram_offset", 0), 0)
            stop.set()
        app = NS(bot=NS(get_updates=AsyncMock(return_value=[NS(update_id=25)])),
                 process_update=AsyncMock(side_effect=dispatch))
        await poll(app, self.db, health, stop)
        self.assertEqual(self.db.get("telegram_offset"), 26)

    async def test_invalid_token_during_startup_is_classified_without_leak(self):
        secret_marker = "TEST_TOKEN_SECRET_MARKER"
        app = NS(initialize=AsyncMock(side_effect=InvalidToken(secret_marker)))
        stop = asyncio.Event()
        with self.assertLogs("smh", level="CRITICAL") as captured:
            with self.assertRaisesRegex(RuntimeError, "configured bot token") as raised:
                await initialize_app(app, self.db, stop)
        row = self.db.rows("SELECT category,detail FROM errors")[0]
        category, detail = row["category"], row["detail"]
        self.assertEqual(category, "polling_invalid_token")
        self.assertTrue(stop.is_set())
        self.assertEqual(app.initialize.await_count, 1)
        self.assertNotIn(secret_marker, str(raised.exception) + detail + repr(captured.output))

    async def test_poll_invalid_token_is_classified_without_leak_or_retry(self):
        secret_marker = "TEST_TOKEN_SECRET_MARKER"
        bot = NS(get_updates=AsyncMock(side_effect=InvalidToken(secret_marker)))
        app = NS(bot=bot)
        stop = asyncio.Event()
        with self.assertLogs("smh", level="CRITICAL") as captured:
            with self.assertRaisesRegex(RuntimeError, "configured bot token") as raised:
                await poll(app, self.db, self.ui().health, stop)
        row = self.db.rows("SELECT category,detail FROM errors")[0]
        category, detail = row["category"], row["detail"]
        self.assertEqual(category, "polling_invalid_token")
        self.assertTrue(stop.is_set())
        self.assertEqual(bot.get_updates.await_count, 1)
        self.assertNotIn(secret_marker, str(raised.exception) + detail + repr(captured.output))

    async def test_poll_webhook_conflict_is_classified_without_logging_webhook_url(self):
        secret_marker = "WEBHOOK_URL_SECRET_MARKER"
        conflict_marker = "BOT_TOKEN_SECRET_MARKER"
        bot = NS(
            get_updates=AsyncMock(side_effect=Conflict(conflict_marker)),
            get_webhook_info=AsyncMock(return_value=NS(url=f"https://example.invalid/{secret_marker}")),
        )
        stop = asyncio.Event()
        with self.assertLogs("smh", level="CRITICAL") as captured:
            with self.assertRaisesRegex(RuntimeError, "polling conflict"):
                await poll(NS(bot=bot), self.db, self.ui().health, stop)
        row = self.db.rows("SELECT category,detail FROM errors")[0]
        category, detail = row["category"], row["detail"]
        self.assertEqual(category, "polling_webhook_conflict")
        self.assertTrue(stop.is_set())
        self.assertEqual(bot.get_updates.await_count, 1)
        self.assertEqual(bot.get_webhook_info.await_count, 1)
        self.assertNotIn(secret_marker, detail + repr(captured.output))
        self.assertNotIn(conflict_marker, detail + repr(captured.output))

    async def test_poll_session_conflict_is_classified_without_provider_text(self):
        conflict_marker = "BOT_TOKEN_SECRET_MARKER"
        bot = NS(
            get_updates=AsyncMock(side_effect=Conflict(conflict_marker)),
            get_webhook_info=AsyncMock(return_value=NS(url="")),
        )
        stop = asyncio.Event()
        with self.assertLogs("smh", level="CRITICAL") as captured:
            with self.assertRaisesRegex(RuntimeError, "polling conflict") as raised:
                await poll(NS(bot=bot), self.db, self.ui().health, stop)
        row = self.db.rows("SELECT category,detail FROM errors")[0]
        category, detail = row["category"], row["detail"]
        self.assertEqual(category, "polling_session_conflict")
        self.assertTrue(stop.is_set())
        self.assertEqual(bot.get_updates.await_count, 1)
        self.assertNotIn(conflict_marker, str(raised.exception) + detail + repr(captured.output))

    async def test_real_handler_registration(self):
        app, *_ = build(self.config, self.db)
        self.assertGreaterEqual(len(app.handlers[0]), 7)

    async def test_all_management_actions_have_ui(self):
        signal = self.signal("BUY")
        await self.pub.send(42, signal)
        ui = self.ui()
        for label, action in ACTIONS:
            with self.subTest(action=action):
                await ui.manage(self.update_obj(), "trade1", action)
                self.assertIsNotNone(self.db.draft(42))


if __name__ == "__main__":
    unittest.main()
