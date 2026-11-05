import asyncio
import json
import logging
import shutil
import time
from logging.handlers import RotatingFileHandler
from .database import now


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Application logs contain classification only, never provider messages/URLs.
        return json.dumps({"time": now(), "severity": record.levelname,
                           "event": record.getMessage()})


def setup_logging(directory):
    logger = logging.getLogger("smh")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    for handler in (logging.StreamHandler(),
                    RotatingFileHandler(directory / "logs" / "bot.log", maxBytes=1_000_000, backupCount=5)):
        handler.setFormatter(SafeFormatter())
        logger.addHandler(handler)
    # HTTP request URLs contain the bot token: never enable provider request logs.
    for name in ("httpx", "httpcore", "telegram"):
        lib = logging.getLogger(name)
        lib.handlers = [logging.NullHandler()]
        lib.propagate = False
        lib.setLevel(logging.CRITICAL)
    return logger


class Health:
    def __init__(self, db, config, bot):
        self.db, self.config, self.bot = db, config, bot
        self.poll_success = time.monotonic()
        self.heartbeat = time.monotonic()
        self.last_update = db.get("last_update", "none yet")
        self.last_alert = 0
        self.incident = False
        self.last_backup = 0
        self.report = {}

    async def check(self):
        report = {"status": "healthy", "configuration": "ready" if self.config.ready else "discovery only",
                  "publishing_requested": self.config.allow_publishing,
                  "last_successful_update": self.last_update,
                  "seconds_since_poll": int(time.monotonic() - self.poll_success)}
        try:
            report["database"] = self.db.integrity()
            report["free_disk_mb"] = shutil.disk_usage(self.db.directory).free // (1024*1024)
            report["unresolved_operations"] = self.db.conn.execute(
                "SELECT count(*) FROM operations WHERE status IN ('uncertain','failed','sending','retryable')").fetchone()[0]
            if report["database"] != "ok" or report["free_disk_mb"] < 100:
                report["status"] = "unavailable"
        except Exception:
            report["database"] = "unavailable"
            report["status"] = "unavailable"
        try:
            await asyncio.wait_for(self.bot.get_me(), 15)
            report["telegram"] = "reachable"
        except Exception:
            report["telegram"] = "unreachable"
            report["status"] = "degraded" if report["status"] != "unavailable" else "unavailable"
        if report["status"] == "healthy" and (not self.config.ready or report["seconds_since_poll"] > 120 or report.get("unresolved_operations")):
            report["status"] = "degraded"
        self.report = report
        return report

    def persist_command_center_health(self, report):
        """Publish an allowlisted health snapshot only to isolated-test storage."""
        if not self.config.isolated_test:
            return
        self.db.put("command_center_health", {
            "checked_at": now(),
            "status": report.get("status"),
            "database": report.get("database"),
            "telegram": report.get("telegram"),
            "seconds_since_poll": report.get("seconds_since_poll"),
            "publishing_requested": bool(report.get("publishing_requested")),
        })

    async def alert(self, text):
        if not self.config.admin or time.monotonic() - self.last_alert < 900:
            return
        self.last_alert = time.monotonic()
        try:
            await self.bot.send_message(self.config.admin, text)
        except Exception:
            logging.getLogger("smh").warning("admin_alert_unavailable")

    async def run(self):
        failures = 0
        while True:
            self.heartbeat = time.monotonic()
            stage = "check"
            try:
                report = await self.check()
                stage = "persist_health"
                self.persist_command_center_health(report)
                # Missing setup alone is not an outage.
                bad = report["telegram"] != "reachable" or report["database"] != "ok" or report.get("free_disk_mb", 0) < 100 or report["seconds_since_poll"] > 120
                failures = failures + 1 if bad else 0
                if failures >= 3:
                    self.incident = True
                    await self.alert("Smart Money Hub health degraded. Open Operations > Health and Recent Errors. "
                                     "Check network, disk space, and host status; uncertain posts must not be reposted.")
                elif self.incident and not bad:
                    self.incident = False
                    self.last_alert = 0
                    await self.alert("Smart Money Hub connectivity and storage checks recovered. "
                                     "Open Operations > Health for details.")
                if time.time() - self.last_backup > 86400:
                    stage = "backup"
                    self.db.backup(self.config.retention)
                    stage = "cleanup"
                    self.db.cleanup()
                    self.last_backup = time.time()
            except Exception as exc:
                logging.getLogger("smh").error(
                    f"health_check_failed:{stage}:{type(exc).__name__}")
                try:
                    self.db.error("health_failure", "Health check/backup failed. Inspect Operations > Health.")
                except Exception:
                    pass
            await asyncio.sleep(60)
