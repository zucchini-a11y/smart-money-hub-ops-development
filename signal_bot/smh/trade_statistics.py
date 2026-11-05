"""Read-only summaries of saved, explicitly closed trades and TP milestones."""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .profit_screenshot import signed_trade_pips, target_profit_screenshots

LAGOS = ZoneInfo("Africa/Lagos")


def _as_local_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(LAGOS)


def _trade_from_row(row):
    raw = row.get("data")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Trade history contains an unreadable record; statistics were not calculated.") from exc
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        raise ValueError("Trade history contains an unreadable record; statistics were not calculated.")
    if not isinstance(data, dict):
        raise ValueError("Trade history contains an unreadable record; statistics were not calculated.")
    data["id"] = row.get("id", data.get("id"))
    data["state"] = row.get("state", data.get("state", ""))
    data["created"] = row.get("created", data.get("created"))
    data["updated"] = row.get("updated", data.get("updated"))
    return data


def _outcome(trade):
    value = str(trade.get("outcome", "")).strip().lower()
    return {
        "win": "win", "won": "win",
        "loss": "loss", "lost": "loss",
        "breakeven": "breakeven", "break even": "breakeven", "be": "breakeven",
        "unrecorded": "unrecorded",
    }.get(value, "")


def _trade_pips(trade):
    return signed_trade_pips(
        trade.get("market") or trade.get("symbol"),
        str(trade.get("direction", "")).upper(),
        trade.get("entry"),
        trade.get("exit"),
    )


def _usable_pips(trade, outcome):
    pips = _trade_pips(trade)
    if pips is None:
        return None
    if outcome == "win" and pips > 0:
        return pips
    if outcome == "loss" and pips < 0:
        return pips
    if outcome == "breakeven" and pips == 0:
        return pips
    return None


def _format_pips(value, signed=False):
    if value is None:
        return "pips not recorded"
    normalized = value.normalize()
    rendered = format(normalized, ",f")
    if signed and value > 0:
        rendered = "+" + rendered
    return f"{rendered} pips"


def _ordinal(day):
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _trade_label(trade, outcome):
    market = str(trade.get("symbol") or trade.get("market") or "Unknown market")
    market = " ".join(market.split())[:32]
    exit_value = str(trade.get("exit", "")).strip()
    if outcome == "loss" and exit_value and str(trade.get("sl", "")).strip() == exit_value:
        result = "SL"
    else:
        result = outcome.upper()
    color = "🟢" if outcome == "win" else "🔴" if outcome == "loss" else "⚪"
    return color, market, result


def _milestone_pips(trade, record):
    return _trade_pips({
        "market": trade.get("market") or trade.get("symbol"),
        "direction": trade.get("direction"),
        "entry": record.get("observed_entry") or trade.get("entry"),
        "exit": record.get("observed_exit"),
    })


def format_trade_statistics(rows, now=None):
    """Build current-year and current-week summaries from saved records only."""
    current = _as_local_datetime(now or datetime.now(LAGOS))
    if current is None:
        raise ValueError("A valid report date is required.")
    trades = [_trade_from_row(row) for row in rows]
    year_start = date(current.year, 1, 1)
    week_start = current.date() - timedelta(days=current.weekday())
    week_end = week_start + timedelta(days=6)

    closed = []
    for trade in trades:
        if str(trade.get("state", "")).upper() != "CLOSED":
            continue
        outcome = _outcome(trade)
        timestamp = _as_local_datetime(trade.get("updated") or trade.get("created"))
        if not outcome or timestamp is None:
            continue
        closed.append((trade, outcome, timestamp))

    annual = [
        (trade, outcome, timestamp)
        for trade, outcome, timestamp in closed
        if year_start <= timestamp.date() <= current.date()
    ]
    wins = sum(outcome == "win" for _, outcome, _ in annual)
    losses = sum(outcome == "loss" for _, outcome, _ in annual)
    decisive = wins + losses
    win_rate = round(wins / decisive * 100) if decisive else 0
    annual_pips = Decimal("0")
    pips_count = 0
    for trade, outcome, _ in annual:
        pips = _usable_pips(trade, outcome)
        if pips is not None and outcome in ("win", "loss"):
            annual_pips += pips
            pips_count += 1
    pips_missing = decisive - pips_count
    text = (
        f"📊 {current.year} STATISTICS · YEAR TO DATE\n\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Win rate: {win_rate}% (closed wins/losses only)\n"
        f"Total pips: {_format_pips(annual_pips, signed=True)}\n"
        f"Breakeven: {sum(outcome == 'breakeven' for _, outcome, _ in annual)}\n"
    )
    if pips_missing:
        text += f"Pip totals unavailable for {pips_missing} closed trade(s) with missing or inconsistent prices.\n"
    text += "\n"

    weekly_events = []
    for trade, outcome, timestamp in closed:
        if week_start <= timestamp.date() <= week_end:
            pips = _usable_pips(trade, outcome)
            color, market, label = _trade_label(trade, outcome)
            weekly_events.append((
                timestamp,
                f"{color} {market} {_format_pips(pips, signed=True)} ({label})",
                pips if outcome in ("win", "loss") else Decimal("0"),
            ))
    for trade in trades:
        records = target_profit_screenshots(trade)
        for number, record in records.items():
            timestamp = _as_local_datetime(record.get("posted_at"))
            if timestamp is None or not week_start <= timestamp.date() <= week_end:
                continue
            pips = _milestone_pips(trade, record)
            if pips is None or pips <= 0:
                continue
            market = " ".join(str(trade.get("symbol") or trade.get("market") or "Unknown market").split())[:32]
            try:
                target_label = f"TP{int(number)} screenshot"
            except (TypeError, ValueError):
                target_label = "TP screenshot"
            weekly_events.append((
                timestamp,
                f"🟢 {market} {_format_pips(pips, signed=True)} ({target_label})",
                Decimal("0"),
            ))
    weekly_events.sort(key=lambda item: item[0])
    week_total = sum((event[2] for event in weekly_events), Decimal("0"))
    text += (
        f"📅 WEEKLY TRADING SUMMARY {_ordinal(week_start.day)} – "
        f"{_ordinal(week_end.day)} {current:%B %Y}\n\n"
    )
    if weekly_events:
        text += "\n".join(event[1] for event in weekly_events[:45])
        if len(weekly_events) > 45:
            text += f"\n…plus {len(weekly_events) - 45} more entries in Trade History."
        text += f"\n\nClosed-trade total: {_format_pips(week_total, signed=True)}"
        text += "\nTP screenshot pips are milestones and are not added to closed-trade totals."
    else:
        text += "No closed trades or TP screenshots recorded this week."
    text += "\n\nUSD-per-lot is not shown because broker contract values are not configured here."
    text += "\nOnly trades recorded in this bot are included; old channel posts are not imported."
    return text
