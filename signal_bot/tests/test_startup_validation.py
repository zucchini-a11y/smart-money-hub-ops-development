import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from telegram.error import InvalidToken

from smh.startup_validation import (
    check_database,
    check_telegram,
    format_report,
    validate_startup,
)
from smh.publishing import (
    DestinationVerificationError,
    verify_configured_destinations,
    verify_configured_destinations_detailed,
)


def test_config(directory, database_url=""):
    return NS(
        token="not-a-real-token",
        admin=42,
        signals=-1001,
        analysis=-1002,
        ready=True,
        database_url=database_url,
        database_schema="smh",
        data=Path(directory),
        isolated_test=False,
        allow_publishing=False,
    )


class FakeBot:
    def __init__(self, token):
        self.calls = []
        self.initialize = AsyncMock(side_effect=lambda: self.calls.append("initialize"))
        self.shutdown = AsyncMock(side_effect=lambda: self.calls.append("shutdown"))
        self.get_me = AsyncMock(side_effect=self._get_me)
        self.get_chat = AsyncMock(side_effect=self._get_chat)
        self.get_chat_member = AsyncMock(side_effect=self._get_chat_member)

    async def _get_me(self):
        self.calls.append("get_me")
        return NS(id=99)

    async def _get_chat(self, chat_id):
        self.calls.append(("get_chat", chat_id))
        return NS(id=chat_id, type="private" if chat_id == 42 else "channel")

    async def _get_chat_member(self, channel_id, user_id):
        self.calls.append(("get_chat_member", channel_id, user_id))
        return NS(
            status="administrator",
            can_post_messages=True,
            can_edit_messages=True,
            can_invite_users=True,
        )


class StartupValidationTests(unittest.IsolatedAsyncioTestCase):
    def make_database(self, directory, version=11):
        path = Path(directory) / "hub.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute(f"PRAGMA user_version={version}")
        connection.close()
        return path

    def test_database_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_database(directory)
            before = (path.stat().st_mtime_ns, path.stat().st_size)
            result = check_database(test_config(directory))
            after = (path.stat().st_mtime_ns, path.stat().st_size)
        self.assertEqual(result, {
            "ok": True, "database": "SQLite", "version": 11, "latest": True,
        })
        self.assertEqual(before, after)

    def test_missing_or_newer_schema_fails_closed_without_creating_database(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = check_database(test_config(directory))
            self.assertEqual(missing["category"], "database_file_missing")
            self.assertFalse((Path(directory) / "hub.sqlite3").exists())
            self.make_database(directory, version=12)
            newer = check_database(test_config(directory))
        self.assertEqual(newer["category"], "migration_not_ready")

    async def test_telegram_check_uses_only_read_only_api_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            config = test_config(directory)
            fake = FakeBot("unused")
            result = await check_telegram(config, lambda token: fake)
        self.assertTrue(result["ok"])
        self.assertIn("get_me", fake.calls)
        self.assertIn(("get_chat", -1001), fake.calls)
        self.assertIn(("get_chat", -1002), fake.calls)
        self.assertEqual(fake.calls[0], "initialize")
        self.assertEqual(fake.calls[-1], "shutdown")
        self.assertFalse(any(
            isinstance(call, str) and ("send" in call or "poll" in call or "updates" in call)
            for call in fake.calls
        ))

    async def test_detailed_destination_check_reports_each_channel_permission(self):
        async def membership(channel_id, user_id):
            if user_id == 42:
                return NS(status="administrator")
            return NS(
                status="administrator",
                can_post_messages=True,
                can_edit_messages=channel_id != -1002,
                can_invite_users=True,
            )

        with tempfile.TemporaryDirectory() as directory:
            config = test_config(directory)
            fake = FakeBot("unused")
            fake.get_chat_member = AsyncMock(side_effect=membership)
            result = await verify_configured_destinations_detailed(fake, config)

            self.assertTrue(result["administrator"]["ok"])
            self.assertTrue(result["signals"]["ok"])
            self.assertFalse(result["analysis"]["ok"])
            self.assertTrue(result["analysis"]["admin_ok"])
            self.assertFalse(result["analysis"]["bot_ok"])
            self.assertEqual(result["analysis"]["bot_category"], "bot_channel_permissions")
            with self.assertRaises(DestinationVerificationError) as failure:
                await verify_configured_destinations(fake, config)

        self.assertEqual(failure.exception.category, "bot_channel_permissions")

    async def test_invalid_token_is_reported_without_exception_details(self):
        class InvalidBot(FakeBot):
            def __init__(self, token):
                super().__init__(token)
                self.initialize = AsyncMock(side_effect=InvalidToken("never print this token"))

        with tempfile.TemporaryDirectory() as directory:
            result = await check_telegram(test_config(directory), InvalidBot)
            report = format_report({
                "ok": False,
                "dependencies": {"ok": True},
                "database": {"ok": False, "category": "database_file_missing"},
                "telegram": result,
                "publishing_enabled": False,
            })
        self.assertEqual(result["category"], "invalid_token")
        self.assertNotIn("never print this token", report)
        self.assertNotIn("not-a-real-token", report)

    async def test_safe_startup_keeps_publishing_locked_and_never_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_database(directory)
            fake = FakeBot("unused")
            result = await validate_startup(
                test_config(directory),
                bot_factory=lambda token: fake,
            )
            report = format_report(result)
        self.assertTrue(result["ok"])
        self.assertFalse(result["publishing_enabled"])
        self.assertIn("Publishing: LOCKED", report)
        self.assertIn("no polling started", report)


if __name__ == "__main__":
    unittest.main()
