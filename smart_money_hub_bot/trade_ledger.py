"""Separate, auditable administrator ledger for verified trading statistics.

Member journals remain private learning records and are never used as trade-result
evidence by this module.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class TradeLedgerError(ValueError):
    """Safe validation error suitable for an administrator reply."""


_OUTCOMES = {"open", "win", "loss", "breakeven", "partial"}
_VERIFICATION = {"verified", "unverified"}
_EDITABLE = {
    "instrument",
    "direction",
    "opened_at_utc",
    "entry_price",
    "stop_loss",
    "planned_targets_json",
    "exit_price",
    "closed_at_utc",
    "outcome",
    "net_pips",
    "pip_size",
    "realized_pl",
    "currency",
    "lot_size",
    "contract_size",
    "full_tp_hit",
    "notes",
    "source_evidence",
}


def _decimal_text(value: object, field: str, *, positive: bool = False) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise TradeLedgerError(f"{field} must be a valid number.") from None
    if not number.is_finite() or (positive and number <= 0):
        raise TradeLedgerError(
            f"{field} must be a finite number"
            + (" greater than zero." if positive else ".")
        )
    return format(number.normalize(), "f")


def _aware_utc(value: datetime | str, field: str) -> str:
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except ValueError:
        raise TradeLedgerError(f"{field} must be a valid ISO timestamp.") from None
    if parsed.tzinfo is None:
        raise TradeLedgerError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


class TradeLedger:
    """Persistent ledger, correction audit, and verified-only statistics."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS smh_trade_ledger (
                    trade_id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('BUY', 'SELL')),
                    opened_at_utc TEXT NOT NULL,
                    entry_price TEXT NOT NULL,
                    stop_loss TEXT,
                    planned_targets_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
                    outcome TEXT NOT NULL CHECK (
                        outcome IN ('open', 'win', 'loss', 'breakeven', 'partial')
                    ),
                    exit_price TEXT,
                    closed_at_utc TEXT,
                    net_pips TEXT,
                    pip_size TEXT,
                    realized_pl TEXT,
                    currency TEXT,
                    lot_size TEXT,
                    contract_size TEXT,
                    partial_tps_json TEXT NOT NULL DEFAULT '[]',
                    full_tp_hit INTEGER NOT NULL DEFAULT 0 CHECK (full_tp_hit IN (0, 1)),
                    source_evidence TEXT,
                    verification_status TEXT NOT NULL DEFAULT 'unverified'
                        CHECK (verification_status IN ('verified', 'unverified')),
                    notes TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS smh_trade_ledger_period
                    ON smh_trade_ledger(opened_at_utc, status, outcome);
                CREATE TABLE IF NOT EXISTS smh_trade_ledger_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT NOT NULL REFERENCES smh_trade_ledger(trade_id),
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    old_record_json TEXT NOT NULL,
                    new_record_json TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS smh_trade_ledger_audit_trade
                    ON smh_trade_ledger_audit(trade_id, audit_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def record_trade(
        self,
        *,
        instrument: str,
        direction: str,
        opened_at: datetime | str,
        entry_price: object,
        stop_loss: object | None = None,
        planned_targets: list[object] | None = None,
        source_evidence: str = "",
        notes: str = "",
        trade_id: str | None = None,
        now: datetime | None = None,
    ) -> str:
        symbol = str(instrument).strip().upper()
        side = str(direction).strip().upper()
        if not symbol or len(symbol) > 20 or not symbol.replace("/", "").isalnum():
            raise TradeLedgerError("Instrument must be a short symbol such as XAUUSD.")
        if side not in {"BUY", "SELL"}:
            raise TradeLedgerError("Direction must be BUY or SELL.")
        opened = _aware_utc(opened_at, "Opened time")
        entry = _decimal_text(entry_price, "Entry price", positive=True)
        stop = (
            _decimal_text(stop_loss, "Stop loss", positive=True)
            if stop_loss not in (None, "")
            else None
        )
        targets = [
            _decimal_text(target, "Planned target", positive=True)
            for target in (planned_targets or [])
        ]
        evidence = str(source_evidence or "").strip()[:500]
        note = str(notes or "").strip()[:1500]
        identifier = trade_id or f"SMH-{uuid.uuid4().hex[:12].upper()}"
        observed = _aware_utc(now or datetime.now(timezone.utc), "Record time")
        row = {
            "trade_id": identifier,
            "instrument": symbol,
            "direction": side,
            "opened_at_utc": opened,
            "entry_price": entry,
            "stop_loss": stop,
            "planned_targets_json": json.dumps(targets),
            "status": "open",
            "outcome": "open",
            "exit_price": None,
            "closed_at_utc": None,
            "net_pips": None,
            "pip_size": None,
            "realized_pl": None,
            "currency": None,
            "lot_size": None,
            "contract_size": None,
            "partial_tps_json": "[]",
            "full_tp_hit": 0,
            "source_evidence": evidence,
            "verification_status": "unverified",
            "notes": note,
            "revision": 1,
            "created_at_utc": observed,
            "updated_at_utc": observed,
        }
        with closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    """
                    INSERT INTO smh_trade_ledger (
                        trade_id, instrument, direction, opened_at_utc, entry_price,
                        stop_loss, planned_targets_json, status, outcome,
                        source_evidence, notes, created_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 'open', ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        symbol,
                        side,
                        opened,
                        entry,
                        stop,
                        json.dumps(targets),
                        evidence,
                        note,
                        observed,
                        observed,
                    ),
                )
            except sqlite3.IntegrityError:
                raise TradeLedgerError(
                    "That trade ID already exists; no second record was created."
                ) from None
            self._audit(connection, identifier, "recorded", "", {}, row, observed)
        return identifier

    def close_trade(
        self,
        trade_id: str,
        *,
        outcome: str,
        closed_at: datetime | str,
        exit_price: object | None = None,
        net_pips: object | None = None,
        pip_size: object | None = None,
        realized_pl: object | None = None,
        currency: str | None = None,
        full_tp_hit: bool = False,
        now: datetime | None = None,
    ) -> None:
        final_outcome = str(outcome).strip().casefold()
        if final_outcome not in {"win", "loss", "breakeven", "partial"}:
            raise TradeLedgerError(
                "Closed outcome must be win, loss, breakeven, or partial."
            )
        closed = _aware_utc(closed_at, "Closed time")
        exit_text = (
            _decimal_text(exit_price, "Exit price", positive=True)
            if exit_price not in (None, "")
            else None
        )
        pips_text = (
            _decimal_text(net_pips, "Net pips")
            if net_pips not in (None, "")
            else None
        )
        pip_size_text = (
            _decimal_text(pip_size, "Pip size", positive=True)
            if pip_size not in (None, "")
            else None
        )
        pl_text = (
            _decimal_text(realized_pl, "Realized P/L")
            if realized_pl not in (None, "")
            else None
        )
        currency_text = str(currency or "").strip().upper() or None
        if pl_text is not None and (
            currency_text is None or len(currency_text) != 3
            or not currency_text.isalpha()
        ):
            raise TradeLedgerError(
                "A realized monetary P/L requires a three-letter currency."
            )
        if pips_text is not None and pip_size_text is None:
            raise TradeLedgerError(
                "Record the pip-size convention whenever net pips are supplied."
            )
        observed = _aware_utc(now or datetime.now(timezone.utc), "Record time")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM smh_trade_ledger WHERE trade_id=?", (trade_id,)
            ).fetchone()
            if row is None:
                raise TradeLedgerError("Trade ID not found.")
            old = dict(row)
            if old["status"] == "closed":
                raise TradeLedgerError(
                    "This trade is already closed. Use /correcttrade with a reason "
                    "to amend it; it will not be counted as another trade."
                )
            if (
                pips_text is None
                and exit_text is not None
                and pip_size_text is not None
            ):
                signed_move = (
                    Decimal(exit_text) - Decimal(old["entry_price"])
                ) * (Decimal(1) if old["direction"] == "BUY" else Decimal(-1))
                pips_text = _decimal_text(
                    signed_move / Decimal(pip_size_text), "Calculated net pips"
                )
            new = dict(old)
            new.update(
                status="closed",
                outcome=final_outcome,
                exit_price=exit_text,
                closed_at_utc=closed,
                net_pips=pips_text,
                pip_size=pip_size_text,
                realized_pl=pl_text,
                currency=currency_text,
                full_tp_hit=int(bool(full_tp_hit)),
                revision=int(old["revision"]) + 1,
                updated_at_utc=observed,
            )
            self._write_record(connection, new)
            self._audit(connection, trade_id, "closed", "", old, new, observed)

    def update_trade(
        self,
        trade_id: str,
        changes: dict[str, object],
        *,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        self._apply_changes(
            trade_id, changes, reason=reason, now=now, allow_closed=False
        )

    def correct_trade(
        self,
        trade_id: str,
        changes: dict[str, object],
        *,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        if not str(reason).strip():
            raise TradeLedgerError("A correction reason is required.")
        self._apply_changes(
            trade_id, changes, reason=reason, now=now, allow_closed=True
        )

    def _apply_changes(
        self,
        trade_id: str,
        changes: dict[str, object],
        *,
        reason: str,
        now: datetime | None,
        allow_closed: bool,
    ) -> None:
        if not changes or set(changes) - _EDITABLE:
            raise TradeLedgerError("The update contains unsupported trade fields.")
        observed = _aware_utc(now or datetime.now(timezone.utc), "Record time")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM smh_trade_ledger WHERE trade_id=?", (trade_id,)
            ).fetchone()
            if row is None:
                raise TradeLedgerError("Trade ID not found.")
            old = dict(row)
            if old["status"] == "closed" and not allow_closed:
                raise TradeLedgerError(
                    "Closed trades require an audited /correcttrade change."
                )
            new = dict(old)
            for field, value in changes.items():
                new[field] = self._normalize_field(field, value)
            if new.get("outcome") not in _OUTCOMES:
                raise TradeLedgerError("Unsupported trade outcome.")
            if new["status"] == "closed" and new["outcome"] == "open":
                raise TradeLedgerError("A closed trade cannot have outcome=open.")
            if new["realized_pl"] is not None and (
                not new["currency"] or len(new["currency"]) != 3
            ):
                raise TradeLedgerError("Realized P/L requires a three-letter currency.")
            if new["net_pips"] is not None and new["pip_size"] is None:
                raise TradeLedgerError(
                    "Net pips require the documented pip-size convention."
                )
            new["revision"] = int(old["revision"]) + 1
            new["updated_at_utc"] = observed
            self._write_record(connection, new)
            self._audit(
                connection,
                trade_id,
                "corrected" if allow_closed else "updated",
                str(reason).strip()[:500],
                old,
                new,
                observed,
            )

    @staticmethod
    def _normalize_field(field: str, value: object) -> Any:
        if field == "instrument":
            text = str(value).strip().upper()
            if not text or len(text) > 20 or not text.replace("/", "").isalnum():
                raise TradeLedgerError("Instrument must be a short symbol.")
            return text
        if field == "direction":
            text = str(value).strip().upper()
            if text not in {"BUY", "SELL"}:
                raise TradeLedgerError("Direction must be BUY or SELL.")
            return text
        if field in {"opened_at_utc", "closed_at_utc"}:
            return _aware_utc(value, field.replace("_", " "))
        if field in {"entry_price", "stop_loss", "exit_price", "pip_size",
                     "lot_size", "contract_size"}:
            return (
                _decimal_text(value, field.replace("_", " "), positive=True)
                if value not in (None, "")
                else None
            )
        if field in {"net_pips", "realized_pl"}:
            return (
                _decimal_text(value, field.replace("_", " "))
                if value not in (None, "")
                else None
            )
        if field == "planned_targets_json":
            targets = json.loads(value) if isinstance(value, str) else value
            if not isinstance(targets, list):
                raise TradeLedgerError("Planned targets must be a list.")
            return json.dumps(
                [_decimal_text(item, "Planned target", positive=True) for item in targets]
            )
        if field == "outcome":
            text = str(value).strip().casefold()
            if text not in _OUTCOMES:
                raise TradeLedgerError("Unsupported trade outcome.")
            return text
        if field == "full_tp_hit":
            if not isinstance(value, bool):
                raise TradeLedgerError("Full-TP hit must be true or false.")
            return int(value)
        if field == "currency":
            text = str(value).strip().upper()
            if len(text) != 3 or not text.isalpha():
                raise TradeLedgerError("Currency must be a three-letter code.")
            return text
        if field in {"notes", "source_evidence"}:
            return str(value or "").strip()[:1500 if field == "notes" else 500]
        raise TradeLedgerError("Unsupported trade field.")

    def add_partial_take_profit(
        self,
        trade_id: str,
        *,
        price: object,
        closed_at: datetime | str,
        percent_closed: object | None = None,
        now: datetime | None = None,
    ) -> None:
        price_text = _decimal_text(price, "Partial target price", positive=True)
        closed = _aware_utc(closed_at, "Partial close time")
        percent = (
            _decimal_text(percent_closed, "Percent closed", positive=True)
            if percent_closed not in (None, "")
            else None
        )
        if percent is not None and Decimal(percent) > 100:
            raise TradeLedgerError("Percent closed cannot exceed 100.")
        observed = _aware_utc(now or datetime.now(timezone.utc), "Record time")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM smh_trade_ledger WHERE trade_id=?", (trade_id,)
            ).fetchone()
            if row is None:
                raise TradeLedgerError("Trade ID not found.")
            old = dict(row)
            if old["status"] == "closed":
                raise TradeLedgerError("A partial take-profit cannot be added after closure.")
            partials = json.loads(old["partial_tps_json"])
            partials.append(
                {
                    "price": price_text,
                    "closed_at_utc": closed,
                    "percent_closed": percent,
                }
            )
            new = dict(old)
            new.update(
                partial_tps_json=json.dumps(partials, sort_keys=True),
                status="open",
                outcome="open",
                revision=int(old["revision"]) + 1,
                updated_at_utc=observed,
            )
            self._write_record(connection, new)
            self._audit(
                connection, trade_id, "partial_take_profit", "", old, new, observed
            )

    def set_verification(
        self,
        trade_id: str,
        *,
        verified: bool,
        evidence: str,
        now: datetime | None = None,
    ) -> None:
        if verified and not str(evidence).strip():
            raise TradeLedgerError(
                "A source or evidence note is required before marking a trade verified."
            )
        observed = _aware_utc(now or datetime.now(timezone.utc), "Record time")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM smh_trade_ledger WHERE trade_id=?", (trade_id,)
            ).fetchone()
            if row is None:
                raise TradeLedgerError("Trade ID not found.")
            old = dict(row)
            new = dict(old)
            new.update(
                verification_status="verified" if verified else "unverified",
                source_evidence=str(evidence or "").strip()[:500],
                revision=int(old["revision"]) + 1,
                updated_at_utc=observed,
            )
            self._write_record(connection, new)
            self._audit(
                connection, trade_id, "verification_changed", "", old, new, observed
            )

    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM smh_trade_ledger WHERE trade_id=?", (trade_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_trades(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        instrument: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if start:
            clauses.append("opened_at_utc >= ?")
            start_local = datetime.combine(
                start, datetime.min.time(), ZoneInfo("Africa/Lagos")
            )
            params.append(start_local.astimezone(timezone.utc).isoformat())
        if end:
            clauses.append("opened_at_utc < ?")
            end_exclusive_local = datetime.combine(
                end + timedelta(days=1),
                datetime.min.time(),
                ZoneInfo("Africa/Lagos"),
            )
            params.append(end_exclusive_local.astimezone(timezone.utc).isoformat())
        if instrument:
            clauses.append("instrument = ?")
            params.append(instrument.strip().upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(int(limit), 500))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM smh_trade_ledger {where} "
                "ORDER BY opened_at_utc DESC, trade_id LIMIT ?",
                (*params, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def audit_history(self, trade_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM smh_trade_ledger_audit WHERE trade_id=? "
                "ORDER BY audit_id DESC LIMIT ?",
                (trade_id, min(max(int(limit), 1), 100)),
            ).fetchall()
        return [dict(row) for row in rows]

    def calculate_statistics(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        instrument: str | None = None,
    ) -> dict[str, Any]:
        rows = self.list_trades(
            start=start, end=end, instrument=instrument, limit=500
        )
        verified_closed = [
            row for row in rows
            if row["verification_status"] == "verified"
            and row["status"] == "closed"
            and row["outcome"] in {"win", "loss", "breakeven"}
        ]
        wins = sum(row["outcome"] == "win" for row in verified_closed)
        losses = sum(row["outcome"] == "loss" for row in verified_closed)
        breakeven = sum(row["outcome"] == "breakeven" for row in verified_closed)
        decisive = wins + losses
        pips_by_convention: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in verified_closed:
            if row["net_pips"] is not None and row["pip_size"] is not None:
                pips_by_convention.setdefault(
                    (row["instrument"], row["pip_size"]), []
                ).append(row)
        by_currency: dict[str, list[Decimal]] = {}
        for row in verified_closed:
            if row["realized_pl"] is not None and row["currency"]:
                by_currency.setdefault(row["currency"], []).append(
                    Decimal(row["realized_pl"])
                )
        monetary: dict[str, dict[str, Any]] = {}
        for currency, values in sorted(by_currency.items()):
            gross_profit = sum((value for value in values if value > 0), Decimal(0))
            gross_loss = abs(sum((value for value in values if value < 0), Decimal(0)))
            monetary[currency] = {
                "net": format(sum(values, Decimal(0)).normalize(), "f"),
                "gross_profit": format(gross_profit.normalize(), "f"),
                "gross_loss": format(gross_loss.normalize(), "f"),
                "profit_factor": (
                    format((gross_profit / gross_loss).normalize(), "f")
                    if gross_loss > 0
                    else None
                ),
                "sample_size": len(values),
            }
        all_closed = [
            row for row in rows
            if row["status"] == "closed"
            and row["outcome"] in {"win", "loss", "breakeven", "partial"}
        ]
        pips_summary: dict[str, dict[str, Any]] = {}
        for (symbol, pip_size), pips_rows in sorted(pips_by_convention.items()):
            values = [Decimal(row["net_pips"]) for row in pips_rows]
            wins_for_symbol = [
                Decimal(row["net_pips"])
                for row in pips_rows
                if row["outcome"] == "win"
            ]
            losses_for_symbol = [
                Decimal(row["net_pips"])
                for row in pips_rows
                if row["outcome"] == "loss"
            ]
            pips_summary[f"{symbol}|{pip_size}"] = {
                "instrument": symbol,
                "pip_size": pip_size,
                "net": format(sum(values, Decimal(0)).normalize(), "f"),
                "sample_size": len(values),
                "average_win": self._average(wins_for_symbol),
                "average_loss": self._average(losses_for_symbol),
                "largest_win": (
                    format(max(wins_for_symbol).normalize(), "f")
                    if wins_for_symbol else None
                ),
                "largest_loss": (
                    format(min(losses_for_symbol).normalize(), "f")
                    if losses_for_symbol else None
                ),
            }
        same_convention = (
            len(pips_summary) == 1
            and instrument is not None
            and next(iter(pips_summary.values()))["instrument"]
            == instrument.strip().upper()
        )
        return {
            "period_start": start.isoformat() if start else None,
            "period_end": end.isoformat() if end else None,
            "instrument": instrument.strip().upper() if instrument else None,
            "verified_closed_sample": len(verified_closed),
            "all_closed_including_unverified": len(all_closed),
            "unverified_closed_excluded": len(all_closed) - len(verified_closed),
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "partial_outcomes": sum(row["outcome"] == "partial" for row in all_closed),
            "win_rate": (
                format((Decimal(wins) * 100 / Decimal(decisive)).quantize(Decimal("0.1")), "f")
                if decisive
                else None
            ),
            "win_rate_denominator": "wins + losses; breakeven excluded",
            "known_net_pips": (
                next(iter(pips_summary.values()))["net"] if same_convention else None
            ),
            "pips_sample_size": (
                next(iter(pips_summary.values()))["sample_size"]
                if same_convention else 0
            ),
            "average_win_pips": (
                next(iter(pips_summary.values()))["average_win"]
                if same_convention else None
            ),
            "average_loss_pips": (
                next(iter(pips_summary.values()))["average_loss"]
                if same_convention else None
            ),
            "largest_win_pips": (
                next(iter(pips_summary.values()))["largest_win"]
                if same_convention else None
            ),
            "largest_loss_pips": (
                next(iter(pips_summary.values()))["largest_loss"]
                if same_convention else None
            ),
            "net_pips_by_instrument_and_convention": pips_summary,
            "full_tp_hits": sum(row["full_tp_hit"] for row in verified_closed),
            "partial_tp_records": sum(
                len(json.loads(row["partial_tps_json"])) for row in verified_closed
            ),
            "realized_pl_by_currency": monetary,
        }

    @staticmethod
    def _average(values: list[Decimal]) -> str | None:
        return (
            format((sum(values, Decimal(0)) / Decimal(len(values))).normalize(), "f")
            if values else None
        )

    def export_csv(self) -> str:
        rows = self.list_trades(limit=500)
        output = io.StringIO()
        fields = [
            "trade_id", "instrument", "direction", "opened_at_utc", "entry_price",
            "stop_loss", "planned_targets_json", "status", "outcome", "exit_price",
            "closed_at_utc", "net_pips", "pip_size", "realized_pl", "currency",
            "lot_size", "contract_size", "partial_tps_json", "full_tp_hit",
            "source_evidence", "verification_status", "notes", "revision",
        ]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    @staticmethod
    def _write_record(connection: sqlite3.Connection, record: dict[str, Any]) -> None:
        columns = [
            "instrument", "direction", "opened_at_utc", "entry_price", "stop_loss",
            "planned_targets_json", "status", "outcome", "exit_price", "closed_at_utc",
            "net_pips", "pip_size", "realized_pl", "currency", "lot_size",
            "contract_size", "partial_tps_json", "full_tp_hit", "source_evidence",
            "verification_status", "notes", "revision", "updated_at_utc",
        ]
        connection.execute(
            "UPDATE smh_trade_ledger SET "
            + ", ".join(f"{column}=?" for column in columns)
            + " WHERE trade_id=?",
            [record.get(column) for column in columns] + [record["trade_id"]],
        )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        trade_id: str,
        action: str,
        reason: str,
        old: dict[str, Any],
        new: dict[str, Any],
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO smh_trade_ledger_audit (
                trade_id, action, reason, old_record_json, new_record_json,
                occurred_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                action,
                reason[:500],
                json.dumps(old, ensure_ascii=False, sort_keys=True),
                json.dumps(new, ensure_ascii=False, sort_keys=True),
                timestamp,
            ),
        )
