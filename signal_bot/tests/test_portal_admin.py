import io
import os
import sys
import unittest
from contextlib import redirect_stdout, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from smh import portal_admin


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, version=5, user_count=0):
        self.version = version
        self.user_count = user_count
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=None):
        self.commands.append((query, params))
        if "SELECT version FROM schema_version" in query:
            return FakeResult((self.version,))
        if "SELECT count(*) FROM portal_users" in query:
            return FakeResult((self.user_count,))
        return FakeResult()


class PortalAdminSetupTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_URL": "development-db-url",
                "SMH_DATABASE_URL": "production-db-url",
                "NODE_ENV": "development",
            },
            clear=True,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    @staticmethod
    def sequence(values):
        iterator = iter(values)
        return lambda _prompt="": next(iterator)

    def test_setup_dev_uses_database_url_and_never_prints_password(self):
        create = Mock()
        output = io.StringIO()
        password = "A-long-private-password-123"
        with redirect_stdout(output):
            result = portal_admin.setup_development(
                input_fn=self.sequence(
                    ["DEVELOPMENT", "Owner@Example.test", "Portal Owner"]),
                password_fn=self.sequence([password, password]),
                create_fn=create,
            )

        self.assertTrue(result)
        create.assert_called_once_with(
            "development-db-url",
            "owner@example.test",
            "Portal Owner",
            password,
            must_change_password=False,
        )
        self.assertNotIn(password, output.getvalue())
        self.assertIn("created in Development", output.getvalue())

    def test_setup_dev_requires_explicit_development_confirmation(self):
        create = Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            result = portal_admin.setup_development(
                input_fn=self.sequence(["PRODUCTION"]),
                password_fn=Mock(),
                create_fn=create,
            )

        self.assertFalse(result)
        create.assert_not_called()
        self.assertIn("No database changes were made", output.getvalue())

    def test_setup_dev_rejects_short_or_mismatched_password_before_database_write(self):
        create = Mock()
        with self.assertRaisesRegex(ValueError, "at least 12 characters"):
            portal_admin.setup_development(
                input_fn=self.sequence(
                    ["DEVELOPMENT", "owner@example.test", "Portal Owner"]),
                password_fn=self.sequence(["short", "short"]),
                create_fn=create,
            )
        create.assert_not_called()

    def test_setup_dev_rejects_password_mismatch_without_printing_either_value(self):
        create = Mock()
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaisesRegex(ValueError, "did not match"):
                portal_admin.setup_development(
                    input_fn=self.sequence(
                        ["DEVELOPMENT", "owner@example.test", "Portal Owner"]),
                    password_fn=self.sequence(
                        ["A-long-private-password-123", "different-private-password"]),
                    create_fn=create,
                )
        create.assert_not_called()
        self.assertNotIn("A-long-private-password-123", output.getvalue())
        self.assertNotIn("different-private-password", output.getvalue())

    def test_setup_dev_refuses_production_process(self):
        os.environ["NODE_ENV"] = "production"
        with self.assertRaisesRegex(ValueError, "not Production"):
            portal_admin.setup_development(
                input_fn=Mock(),
                password_fn=Mock(),
                create_fn=Mock(),
            )

    def test_setup_dev_refuses_isolated_test_instance(self):
        os.environ["SMH_ISOLATED_TEST_INSTANCE"] = "true"
        with self.assertRaisesRegex(ValueError, "not the isolated test bot"):
            portal_admin.setup_development(
                input_fn=Mock(),
                password_fn=Mock(),
                create_fn=Mock(),
            )

    def test_setup_dev_stops_if_terminal_cannot_hide_password(self):
        create = Mock()
        with patch.object(portal_admin.sys, "stdin", SimpleNamespace(isatty=lambda: False)):
            with patch.object(portal_admin.sys, "stderr", SimpleNamespace(isatty=lambda: True)):
                with patch.object(portal_admin.getpass, "getpass") as password_prompt:
                    with self.assertRaisesRegex(ValueError, "cannot securely hide"):
                        portal_admin.setup_development(
                            input_fn=self.sequence(
                                ["DEVELOPMENT", "owner@example.test", "Portal Owner"]),
                            create_fn=create,
                        )
        password_prompt.assert_not_called()
        create.assert_not_called()

    def test_setup_dev_command_dispatches_without_long_flags(self):
        with patch.object(sys, "argv", ["portal_admin", "setup-dev"]):
            with patch.object(portal_admin, "setup_development") as setup:
                portal_admin.main()
        setup.assert_called_once_with()

    def test_database_helper_creates_only_first_admin_and_stores_hash(self):
        conn = FakeConnection(version=5, user_count=0)
        password = "A-long-private-password-123"

        portal_admin.create_admin_account(
            "development-db-url",
            "owner@example.test",
            "Portal Owner",
            password,
            must_change_password=False,
            connect=lambda url: (self.assertEqual(url, "development-db-url") or conn),
        )

        insert = next(
            (query, params) for query, params in conn.commands
            if query.startswith("INSERT INTO portal_users")
        )
        self.assertTrue(insert[1][3].startswith("scrypt$16384$8$1$"))
        self.assertEqual(insert[1][4], False)
        self.assertNotIn(password, repr(insert[1]))
        self.assertTrue(any("INSERT INTO portal_audit" in query for query, _ in conn.commands))

    def test_database_helper_refuses_existing_accounts(self):
        conn = FakeConnection(version=5, user_count=1)
        with self.assertRaisesRegex(ValueError, "already exists"):
            portal_admin.create_admin_account(
                "development-db-url",
                "owner@example.test",
                "Portal Owner",
                "A-long-private-password-123",
                must_change_password=False,
                connect=lambda _url: conn,
            )
        self.assertFalse(
            any(query.startswith("INSERT INTO portal_users") for query, _ in conn.commands)
        )

    def test_database_helper_refuses_unmigrated_schema(self):
        conn = FakeConnection(version=3, user_count=0)
        with self.assertRaisesRegex(ValueError, "migration is not ready"):
            portal_admin.create_admin_account(
                "development-db-url",
                "owner@example.test",
                "Portal Owner",
                "A-long-private-password-123",
                must_change_password=False,
                connect=lambda _url: conn,
            )
        self.assertFalse(
            any(query.startswith("INSERT INTO portal_users") for query, _ in conn.commands)
        )


if __name__ == "__main__":
    unittest.main()
