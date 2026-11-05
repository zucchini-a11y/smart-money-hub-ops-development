"""Read-only startup checks. This module never starts polling or sends messages."""
import importlib
import re
import sqlite3
from pathlib import Path

from .publishing import DestinationVerificationError, verify_configured_destinations


LATEST_SCHEMA_VERSION = 11
SUPPORTED_SCHEMA_VERSIONS = {5, 6, 7, 8, 9, 10, 11}


class _CheckFailure(Exception):
    def __init__(self, category):
        self.category = category


def check_dependencies():
    """Confirm the runtime libraries import without exposing dependency details."""
    for module in ("telegram", "PIL", "psycopg"):
        try:
            importlib.import_module(module)
        except Exception:
            return {"ok": False, "category": "dependency_missing"}
    return {"ok": True}


def check_database(config):
    """Check connectivity and schema metadata using read-only transactions only."""
    if config.database_url:
        return _check_postgres(config.database_url, config.database_schema)
    return _check_sqlite(Path(config.data) / "hub.sqlite3")


def _check_postgres(url, schema):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", str(schema or "")):
        return {"ok": False, "category": "database_schema_invalid"}
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=5) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute(f'SET LOCAL search_path TO "{schema}"')
                marker_row = connection.execute(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name='schema_version' "
                    "AND column_name='version'",
                    (schema,),
                ).fetchone()
                if not marker_row or not marker_row[0]:
                    raise _CheckFailure("migration_marker_missing")
                match = re.search(r"\d+", str(marker_row[0]))
                if not match:
                    raise _CheckFailure("migration_marker_invalid")
                marker = int(match.group())
                version_row = connection.execute(
                    "SELECT version FROM schema_version LIMIT 1"
                ).fetchone()
                if marker not in SUPPORTED_SCHEMA_VERSIONS:
                    raise _CheckFailure("migration_not_ready")
                if version_row and str(version_row[0]) != str(marker):
                    raise _CheckFailure("migration_version_mismatch")
                return {
                    "ok": True,
                    "database": "PostgreSQL",
                    "version": marker,
                    "latest": marker == LATEST_SCHEMA_VERSION,
                }
    except _CheckFailure as exc:
        return {"ok": False, "category": exc.category}
    except Exception:
        return {"ok": False, "category": "database_unavailable"}


def _check_sqlite(path):
    if not path.is_file():
        return {"ok": False, "category": "database_file_missing"}
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            return {"ok": False, "category": "migration_not_ready"}
        return {
            "ok": True,
            "database": "SQLite",
            "version": version,
            "latest": version == LATEST_SCHEMA_VERSION,
        }
    except Exception:
        return {"ok": False, "category": "database_unavailable"}


async def check_telegram(config, bot_factory=None):
    """Read-only identity and channel-permission verification; never polls."""
    if not config.ready:
        return {"ok": False, "category": "configuration_incomplete"}
    if bot_factory is None:
        from telegram import Bot
        bot_factory = Bot
    from telegram.error import BadRequest, Forbidden, InvalidToken, NetworkError

    bot = bot_factory(token=config.token)
    initialized = False
    try:
        await bot.initialize()
        initialized = True
        await verify_configured_destinations(bot, config)
        return {"ok": True}
    except DestinationVerificationError as exc:
        return {"ok": False, "category": exc.category}
    except InvalidToken:
        return {"ok": False, "category": "invalid_token"}
    except Forbidden:
        return {"ok": False, "category": "telegram_forbidden"}
    except BadRequest:
        return {"ok": False, "category": "telegram_bad_request"}
    except NetworkError:
        return {"ok": False, "category": "telegram_network_error"}
    except Exception:
        return {"ok": False, "category": "telegram_validation_error"}
    finally:
        if initialized:
            try:
                await bot.shutdown()
            except Exception:
                pass


async def validate_startup(config, bot_factory=None):
    dependencies = check_dependencies()
    database = check_database(config)
    telegram = await check_telegram(config, bot_factory) if dependencies["ok"] else {
        "ok": False,
        "category": "dependency_missing",
    }
    return {
        "ok": dependencies["ok"] and database["ok"] and telegram["ok"],
        "dependencies": dependencies,
        "database": database,
        "telegram": telegram,
        "publishing_enabled": bool(config.allow_publishing),
    }


def format_report(result):
    """Return a report containing statuses only—never values from secrets/errors."""
    lines = [
        f"Safe startup validation: {'PASS' if result['ok'] else 'FAIL'}",
        "Mode: read-only; no polling started and no Telegram messages sent.",
        f"Dependencies: {'PASS' if result['dependencies']['ok'] else 'FAIL (' + result['dependencies']['category'] + ')'}",
    ]
    database = result["database"]
    if database["ok"]:
        freshness = "latest bundled schema" if database["latest"] else "runtime-supported older schema"
        lines.append(
            f"Database: PASS ({database['database']} schema v{database['version']}; {freshness})."
        )
    else:
        lines.append(f"Database: FAIL ({database['category']}).")
    telegram = result["telegram"]
    lines.append(
        "Telegram: PASS (bot identity, destination IDs, and admin permissions verified read-only)."
        if telegram["ok"] else
        f"Telegram: FAIL ({telegram['category']})."
    )
    lines.append(
        "Publishing: ENABLED in this environment; validation remained read-only."
        if result["publishing_enabled"] else
        "Publishing: LOCKED in this environment."
    )
    return "\n".join(lines)
