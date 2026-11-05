"""Persistent, single-use setups; no market data or inferred confirmation."""
import html
import json
import re
import time
from decimal import Decimal
from .database import uid, now
from .domain import entry, price, safe_text

_FOREX_CURRENCIES = {
    "AUD", "BRL", "CAD", "CHF", "CNH", "CZK", "DKK", "EUR", "GBP",
    "HKD", "HUF", "ILS", "INR", "JPY", "MXN", "NOK", "NZD", "PLN",
    "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
}
AUTOMATIC_TP_STEP_PIPS = 20
AUTOMATIC_TP_MAX_TARGETS = 4


def parse_zone(text):
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 5:
        raise ValueError("Use market | low-high | timeframe or - | manual | required confirmation or -")
    market, zone, timeframe, minutes, condition = parts
    zone = entry(zone)
    if "–" not in zone or zone.split("–")[0] == zone.split("–")[1]:
        raise ValueError("Supply a zone with distinct lower and upper prices.")
    if minutes.lower() != "manual" and (
            not minutes.isdigit() or not 1 <= int(minutes) <= 1440):
        raise ValueError("Validity must be 1–1440 minutes.")
    return {"id": uid(), "market": safe_text(market, 80), "zone": zone,
            "timeframe": "" if timeframe == "-" else safe_text(timeframe, 30),
            "condition": "" if condition == "-" else safe_text(condition, 300),
            "expires": None, "status": "active", "created": now()}


def is_expired(setup, now_epoch=None):
    """Expiry is manual for new setups; preserve legacy deadlines until migration."""
    if not isinstance(setup, dict):
        return False
    if setup.get("status") == "expired":
        return True
    expires = setup.get("expires")
    if (setup.get("status") == "active"
            and isinstance(expires, (int, float))
            and not isinstance(expires, bool)):
        return expires <= (time.time() if now_epoch is None else now_epoch)
    return False


def make_active_expiry_manual(db):
    """Remove automatic deadlines from every still-active setup, even past deadlines."""
    records = active_setups(db, include_expired=True)
    changed = []
    with db.transaction() as connection:
        for setup in records:
            if (setup.get("status") == "active"
                    and setup.get("expires") is not None):
                setup["expires"] = None
                save_in(connection, setup)
                changed.append(setup["id"])
    return changed


def automatic_tp1_pip_size(market):
    """Return the agreed pip size for supported instruments, otherwise None."""
    raw = str(market or "").strip().upper()
    alias_match = re.fullmatch(r"(FOREX|GOLD)\s*\(([^)]+)\)", raw)
    if alias_match:
        category, symbol = alias_match.group(1), alias_match.group(2).replace("/", "")
    elif "/" in raw:
        category, symbol = (part.strip() for part in raw.split("/", 1))
        symbol = symbol.replace("/", "")
    else:
        category, symbol = raw, ""

    # This broker's XAUUSD.s quote uses 0.10 price units per pip. Keep the
    # existing 0.01 convention for unsuffixed XAUUSD unchanged.
    if raw == "XAUUSD.S" or (
            category in ("GOLD", "GOLD/XAUUSD") and symbol == "XAUUSD.S"):
        return Decimal("0.1")
    if raw == "XAUUSD" or (
            category in ("GOLD", "GOLD/XAUUSD") and symbol in ("", "XAUUSD")):
        return Decimal("0.01")
    if category != "FOREX":
        return None

    symbol = re.sub(r"[^A-Z]", "", symbol)
    if len(symbol) != 6:
        return None
    base, quote = symbol[:3], symbol[3:]
    if base not in _FOREX_CURRENCIES or quote not in _FOREX_CURRENCIES:
        return None
    return Decimal("0.01") if quote == "JPY" else Decimal("0.0001")


def automatic_tp_price(market, direction, entry_value, target_number):
    """Calculate a 20-pip-step target from one exact entry."""
    pip_size = automatic_tp1_pip_size(market)
    if pip_size is None:
        return None
    if direction not in ("BUY", "SELL"):
        raise ValueError("Choose BUY or SELL before calculating TP1.")
    if isinstance(target_number, bool) or not isinstance(target_number, int) or not 1 <= target_number <= 100:
        raise ValueError("Take-profit number must be between 1 and 100.")
    normalized_entry = entry(entry_value)
    if "–" in normalized_entry:
        raise ValueError("Automatic TP1 needs one exact entry price, not an entry range.")
    entry_price = Decimal(normalized_entry)
    adjustment = pip_size * Decimal(AUTOMATIC_TP_STEP_PIPS * target_number)
    target = entry_price + adjustment if direction == "BUY" else entry_price - adjustment
    if target <= 0:
        raise ValueError("The calculated TP1 is not a valid positive price.")
    return price(format(target, "f"))


def automatic_tp1_price(market, direction, entry_value):
    """Calculate the agreed 20-pip TP1 only for Forex pairs and XAUUSD."""
    return automatic_tp_price(market, direction, entry_value, 1)


def automatic_tp_ladder(market, direction, entry_value):
    """Return the four approved 20-pip targets from one exact entry."""
    if automatic_tp1_pip_size(market) is None:
        return None
    return {
        str(number): {
            "price": automatic_tp_price(market, direction, entry_value, number),
            "pips": AUTOMATIC_TP_STEP_PIPS * number,
        }
        for number in range(1, AUTOMATIC_TP_MAX_TARGETS + 1)
    }


def next_automatic_tp(market, direction, entry_value, targets):
    """Return the next 20-pip target only when existing levels follow the auto ladder."""
    if (not isinstance(targets, dict) or not targets or
            len(targets) >= AUTOMATIC_TP_MAX_TARGETS):
        return None
    try:
        numbered = {int(key): value for key, value in targets.items()}
        if (len(numbered) != len(targets) or
                set(numbered) != set(range(1, len(numbered) + 1)) or
                any(not isinstance(value, dict) or
                    value.get("price") != automatic_tp_price(
                        market, direction, entry_value, number)
                    for number, value in numbered.items())):
            return None
        number = len(numbered) + 1
        return {
            "number": number,
            "price": automatic_tp_price(market, direction, entry_value, number),
            "pips": AUTOMATIC_TP_STEP_PIPS * number,
        }
    except (TypeError, ValueError):
        return None


def active(db, ident):
    legacy = db.get("active_setup")
    setup = legacy if legacy and legacy.get("id") == ident else db.get("setup:" + str(ident))
    if not setup or setup.get("id") != ident:
        raise ValueError("This setup is stale. Open the administrator menu for the active zone.")
    if setup["status"] != "active" or is_expired(setup):
        raise ValueError("Setup expired, cancelled or already used. Submit a new zone.")
    if not setup.get("setup_message_id"):
        raise ValueError("The zone setup post is not confirmed yet.")
    return setup


def active_setups(db, include_expired=False):
    """Return all active zone records, with legacy single-zone compatibility."""
    records = {}
    for row in db.rows("SELECT key,value FROM kv WHERE substr(key,1,6)='setup:'"):
        try:
            record = json.loads(row["value"])
            if isinstance(record, dict) and record.get("id"):
                records[str(record["id"])] = record
        except (TypeError, json.JSONDecodeError):
            continue
    legacy = db.get("active_setup")
    if legacy and legacy.get("id"):
        records[str(legacy["id"])] = legacy
    setups = [
        setup for setup in records.values()
        if setup.get("status") == "active"
        and (include_expired or not is_expired(setup))
    ]
    return sorted(setups, key=lambda setup: (str(setup.get("created", "")), str(setup["id"])))


def save_in(c, setup):
    save_record_in(c, setup)
    current = c.execute("SELECT value FROM kv WHERE key='active_setup'").fetchone()
    current_setup = json.loads(current[0]) if current else None
    if setup.get("status") == "active":
        c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", ("active_setup", json.dumps(setup)))
    elif not current_setup:
        c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", ("active_setup", json.dumps(setup)))
    elif current_setup and current_setup.get("id") == setup.get("id"):
        alternatives = []
        for row in c.execute(
                "SELECT value FROM kv WHERE substr(key,1,6)='setup:'").fetchall():
            try:
                record = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                continue
            if (record.get("id") != setup.get("id")
                    and record.get("status") == "active"
                    and not is_expired(record)):
                alternatives.append(record)
        replacement = max(
            alternatives,
            key=lambda record: (str(record.get("created", "")), str(record.get("id", ""))),
            default=setup,
        )
        c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)",
                  ("active_setup", json.dumps(replacement)))


def save_record_in(c, setup):
    c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", ("setup:" + setup["id"], json.dumps(setup)))


def activate(db, setup, expected):
    with db.transaction() as c:
        old = db.get("active_setup")
        if (old["id"] if old else None) != expected:
            raise ValueError("Active zone changed. Submit and confirm the replacement again.")
        if is_expired(setup):
            raise ValueError("Proposed zone expired. Submit it again.")
        if old:
            old["status"] = "replaced"
            save_in(c, old)
        save_in(c, setup)


def _entry_bounds(value):
    values = [Decimal(part) for part in value.split("–")]
    return values[0], values[-1]


def validate_signal_entry(setup, direction, value):
    if direction not in ("BUY", "SELL"):
        raise ValueError("Choose BUY or SELL.")
    poi_direction = setup.get("poi_direction")
    if poi_direction in ("BUY", "SELL") and poi_direction != direction:
        raise ValueError(f"This is a {poi_direction} POI. Create a matching {poi_direction} signal.")
    normalized = entry(value)
    zone_low, zone_high = _entry_bounds(entry(setup.get("zone", "")))
    entry_low, entry_high = _entry_bounds(normalized)
    if entry_low < zone_low or entry_high > zone_high:
        raise ValueError("The entry price must be within the active setup zone.")
    return normalized


def validate_signal_stop_loss(direction, entry_value, value):
    if direction not in ("BUY", "SELL"):
        raise ValueError("Choose BUY or SELL.")
    if not str(value or "").strip():
        raise ValueError("Stop Loss is required before a signal can be confirmed.")
    stop_loss = price(value)
    entry_low, entry_high = _entry_bounds(entry(entry_value))
    stop = Decimal(stop_loss)
    if direction == "BUY" and stop >= entry_low:
        raise ValueError("For a BUY signal, Stop Loss must be below the entry price.")
    if direction == "SELL" and stop <= entry_high:
        raise ValueError("For a SELL signal, Stop Loss must be above the entry price.")
    return stop_loss


def validate_signal_targets(direction, entry_value, value):
    if direction not in ("BUY", "SELL"):
        raise ValueError("Choose BUY or SELL.")
    parts = [part.strip() for part in str(value or "").replace("\n", ",").split(",")]
    if not parts or any(not part for part in parts):
        raise ValueError("Take Profit is required. Enter prices separated by commas.")
    if len(parts) > 100:
        raise ValueError("Enter no more than 100 Take Profit prices.")
    targets = [price(part) for part in parts]
    numbers = [Decimal(target) for target in targets]
    if len(set(numbers)) != len(numbers):
        raise ValueError("Take Profit prices must be different.")
    entry_low, entry_high = _entry_bounds(entry(entry_value))
    if direction == "BUY":
        if any(target <= entry_high for target in numbers):
            raise ValueError("For a BUY signal, every Take Profit must be above the entry price.")
        if any(left >= right for left, right in zip(numbers, numbers[1:])):
            raise ValueError("For a BUY signal, list Take Profit prices from lowest to highest.")
    else:
        if any(target >= entry_low for target in numbers):
            raise ValueError("For a SELL signal, every Take Profit must be below the entry price.")
        if any(left <= right for left, right in zip(numbers, numbers[1:])):
            raise ValueError("For a SELL signal, list Take Profit prices from highest to lowest.")
    return {str(index): {"price": target, "hit": False}
            for index, target in enumerate(targets, start=1)}


def validate_signal_levels(setup, direction, entry_value, stop_loss, target_values):
    normalized_entry = validate_signal_entry(setup, direction, entry_value)
    normalized_stop_loss = validate_signal_stop_loss(direction, normalized_entry, stop_loss)
    targets = validate_signal_targets(direction, normalized_entry, target_values)
    return {"entry": normalized_entry, "sl": normalized_stop_loss, "targets": targets}


def signal_public_text(direction):
    if direction not in ("BUY", "SELL"):
        raise ValueError("Choose BUY or SELL.")
    return f"<b>{'🟢' if direction == 'BUY' else '🔴'} {direction} NOW</b>"


def signal_payload(setup, direction, actor, levels=None, direction_first=False):
    if direction not in ("BUY", "SELL"):
        raise ValueError("Choose BUY or SELL.")
    poi_direction = setup.get("poi_direction")
    if poi_direction in ("BUY", "SELL") and poi_direction != direction:
        raise ValueError(f"This is a {poi_direction} POI. Only a matching signal can be prepared.")
    if not setup.get("confirmation"):
        raise ValueError("Missing confirmation details: " + (setup["condition"] or "your observed setup confirmation"))
    if direction_first:
        if levels:
            raise ValueError("A direction-first signal cannot include trade details.")
        normalized_levels = {"entry": "", "sl": "", "targets": {}}
    elif not levels:
        raise ValueError("Set a valid Entry range, Stop Loss, and at least one Take Profit before publishing.")
    else:
        target_values = ", ".join(
            str(value.get("price") if isinstance(value, dict) else value)
            for _, value in sorted(levels.get("targets", {}).items(),
                                   key=lambda item: int(item[0]))
        )
        normalized_levels = validate_signal_levels(
            setup, direction, levels.get("entry"), levels.get("sl"), target_values)
    trade = {"id": uid(), "setup_id": setup["id"], "direction": direction,
             "market": setup["market"], "symbol": setup["market"],
             "zone": setup["zone"], "timeframe": setup["timeframe"],
             "setup_message_id": setup["setup_message_id"],
             "entry": normalized_levels["entry"], "sl": normalized_levels["sl"],
             "targets": normalized_levels["targets"], "admin": actor}
    if direction_first:
        trade.update(direction_first=True, levels_pending=True)
    return {
        "destination": "signals",
        "setup_id": setup["id"],
        "text": signal_public_text(direction),
        "trade": trade,
    }


def public_status(setup, operation_status=None):
    state = setup.get("status")
    if state == "cancelled":
        return "Cancelled"
    if state == "replaced":
        return "Replaced"
    if state == "expired" or is_expired(setup):
        return "Expired"
    if state == "used":
        return {
            "done": "Signal Published",
            "uncertain": "Signal Result Uncertain",
            "abandoned": "Signal Result Uncertain",
            "retryable": "Signal Not Yet Published",
            "failed": "Signal Not Published",
            "prepared": "Signal Pending",
            "sending": "Signal Pending",
        }.get(operation_status, "Signal Status Unavailable")
    if state != "active":
        return "Status Unavailable"
    return "Confirmation Recorded" if setup.get("confirmation") else "Awaiting Confirmation"


def setup_caption(setup, status=None):
    """Render a Telegram HTML caption using only saved setup values."""
    status = status or public_status(setup)

    def shown(value, fallback="Not specified"):
        value = str(value).strip() if value is not None else ""
        return html.escape(value, quote=False) if value else fallback

    market = str(setup.get("market") or "").strip()
    market_title = market
    market_label = market
    if "/" in market:
        alias, symbol = (part.strip() for part in market.split("/", 1))
        if alias and symbol:
            market_title = symbol
            market_label = f"{symbol} ({alias.upper()})"
    elif market.endswith(")") and "(" in market:
        symbol, _, alias = market.rpartition("(")
        symbol, alias = symbol.strip(), alias[:-1].strip()
        if symbol and alias:
            market_title = symbol
            market_label = f"{symbol} ({alias.upper()})"

    zone = str(setup.get("zone") or "")
    low, sep, high = zone.partition("–")
    if not sep or not low.strip() or not high.strip():
        low = high = ""

    active = status in ("Awaiting Confirmation", "Confirmation Recorded")
    if active:
        title = "ACTIVE SETUP ZONE"
        guidance = (
            "⚠️ <b>WAIT FOR CONFIRMATION</b>\n\n"
            "Price entering the zone does not automatically mean an entry is valid. "
            "Wait for the required confirmation before considering a trade."
            if status == "Awaiting Confirmation" else
            "✅ <b>CONFIRMATION RECORDED</b>\n\n"
            "The administrator recorded an observed confirmation. Recording it does not place an order."
        )
    else:
        title = {
            "Expired": "SETUP EXPIRED",
            "Cancelled": "SETUP CANCELLED",
            "Replaced": "SETUP REPLACED",
            "Signal Published": "SETUP USED",
        }.get(status, "SETUP NOT ACTIVE")
        guidance = f"⚠️ <b>DO NOT TRADE THIS SETUP</b>\n\nStatus: {shown(status)}."

    poi_direction = setup.get("poi_direction")
    approximate = "Approx. " if setup.get("approximate_zone") else ""
    poi_label = (
        f"🟢 <b>BUY POI</b>\n" if poi_direction == "BUY" else
        "🔴 <b>SELL POI</b>\n" if poi_direction == "SELL" else
        ""
    )
    return (
        f"<b>📍 {title} | {shown(market_title)}</b>\n\n"
        f"📊 <b>Market:</b> {shown(market_label)}\n"
        f"{poi_label}"
        f"🎯 <b>{'Approx. POI' if approximate else 'Zone'}:</b> "
        f"{approximate}{shown(low)}–{shown(high)}\n"
        f"⏱️ <b>Zone Timeframe:</b> {shown(setup.get('timeframe'))}\n"
        f"✅ <b>Required Confirmation:</b> {shown(setup.get('condition'))}\n"
        "⌛ <b>Expiry:</b> Manual — remains active until marked expired.\n"
        f"⌛ <b>Status:</b> <b>{shown(status)}</b>\n\n"
        f"{guidance}\n\n"
        "🛡️ <b>NO CONFIRMATION, NO ENTRY.</b>\n\n"
        "<b>VAYDA SMART MONEY HUB</b>"
    )


def zone_tapped_update_text(setup):
    """Build a factual POI-touch update; a touch is never entry confirmation."""
    def shown(value, fallback="Not specified"):
        value = str(value or "").strip()
        return html.escape(value, quote=False) if value else fallback

    low, separator, high = str(setup.get("zone") or "").partition("–")
    if not separator or not low.strip() or not high.strip():
        raise ValueError("The active zone has no valid saved price range.")
    market = shown(setup.get("market"))
    direction = setup.get("poi_direction")
    poi_label = (
        "🟢 <b>BUY POI</b>\n\n" if direction == "BUY" else
        "🔴 <b>SELL POI</b>\n\n" if direction == "SELL" else
        ""
    )
    return (
        f"<b>📍 POI ZONE TAPPED | {market}</b>\n\n"
        f"{poi_label}"
        f"Price has reached the marked POI zone: <b>{shown(low)}–{shown(high)}</b>.\n\n"
        "A POI touch is not an entry signal. Watch for the required liquidity behaviour, "
        "displacement, CHoCH/BOS, FVG, retest, and confirmation.\n\n"
        "⚠️ <b>NO CONFIRMATION, NO ENTRY.</b>\n\n"
        "🛡️ Protect your capital and manage risk responsibly.\n\n"
        "<b>VAYDA SMART MONEY HUB</b>"
    )
