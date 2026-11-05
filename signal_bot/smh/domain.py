"""Pure validation and trade transitions, independent of Telegram."""
import re
from decimal import Decimal, InvalidOperation

MARKETS = ["Gold/XAUUSD", "Forex", "Bitcoin/BTC", "Synthetic Indices", "Other"]
OPEN_STATES = ("CONFIRMED_BUY", "CONFIRMED_SELL", "ACTIVE")
TEMPLATES = {
    "Higher-timeframe bias": "Higher-timeframe bias: [your observation]\nTimeframe: [timeframe]\nContext: [context]",
    "Market structure": "Market structure: [BOS / CHoCH / MSS]\nObservation: [your analysis]",
    "Liquidity": "Liquidity observation: [location and context]\nWhat I am watching: [observation]",
    "POI": "Point of interest: [your zone]\nReason for interest: [context]",
    "OB / FVG": "OB / FVG observation: [zone and timeframe]\nEducational context: [explanation]",
    "Commentary": "Market commentary: [your observations]\nContext: [timeframe and market]",
}

_ACTIONABLE_ANALYSIS_PATTERNS = (
    re.compile(
        r"\b(?:buy|sell)\s+(?:now|at|above|below|on|near|gold|xauusd|silver|xagusd|"
        r"bitcoin|btc(?:usd)?|ethereum|eth(?:usd)?)\b", re.I),
    re.compile(
        r"\b(?:buy|sell)\s+(?:(?:[A-Z]{3})(?:USD|EUR|GBP|JPY|CHF|AUD|CAD|NZD)|"
        r"(?:USD|EUR|GBP|JPY|CHF|AUD|CAD|NZD)[A-Z]{3}|US30|US100|NAS100|SPX500|GER40)\b", re.I),
    re.compile(r"\b(?:enter\s+(?:now|at|long|short)|go\s+(?:long|short))\b", re.I),
    re.compile(
        r"\bentry(?:\s+(?:price|zone))?\s*(?:(?:[:=@])|\b(?:at|is)\b)?"
        r"\s*[$€£]?\d+(?:[,.]\d+)?", re.I),
    re.compile(
        r"\b(?:stop[\s-]*loss|sl)\s*(?:price|level)?\s*(?:(?:[:=@])|\b(?:at|is)\b)?"
        r"\s*[$€£]?\d+(?:[,.]\d+)?", re.I),
    re.compile(
        r"\b(?:take[\s-]*profit|tp\s*\d*)\s*(?:price|target|level)?"
        r"\s*(?:(?:[:=@])|\b(?:at|is)\b)?\s*[$€£]?\d+(?:[,.]\d+)?", re.I),
    re.compile(
        r"\btarget\s*\d+\s*(?:(?:[:=@])|\b(?:at|is)\b)?\s*[$€£]?\d+(?:[,.]\d+)?", re.I),
    re.compile(
        r"\b(?:tp\s*\d+|target\s*\d+|stop[\s-]*loss|sl)\s+"
        r"(?:was\s+)?(?:hit|reached|filled|triggered|tagged|done)\b", re.I),
    re.compile(
        r"\b(?:close|exit)\s+(?:(?:the|this|your)\s+)?(?:trade|position)\b", re.I),
    re.compile(r"\bmove\s+(?:(?:the|your)\s+)?(?:sl|stop[\s-]*loss)\b", re.I),
    re.compile(r"\btrail(?:ing)?\s+(?:(?:the|your)\s+)?(?:sl|stop[\s-]*loss)\b", re.I),
    re.compile(
        r"\b(?:take|secure|close)\s+\d{1,3}\s*%\s+(?:partial|off|profit|position)\b", re.I),
)

FIRST_PARTIAL_FOLLOW_UP = (
    "🛡️ RISK MANAGEMENT UPDATE\n\n"
    "Price is moving in our favour. If you’re still in the trade, move your SL to "
    "BREAKEVEN (BE) according to your trade plan.\n\n"
    "💰 Consider securing partials.\n\n"
    "🔒 Protect your capital!\n\n"
    "Moving SL to breakeven does not eliminate all market risk.\n\n"
    "— VAYDA SMART MONEY HUB"
)

SECOND_PARTIAL_FOLLOW_UP = (
    "💰 SECOND PARTIAL UPDATE\n\n"
    "🎯 Take another partial and secure more profits. Keep your SL at breakeven "
    "and let the remaining position run!\n\n"
    "🔒 VAYDA SMART MONEY HUB"
)


def price(text):
    try:
        value = Decimal(text.strip())
        if not value.is_finite() or value <= 0 or value > Decimal("1e15"):
            raise ValueError
        return format(value, "f")
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a positive price using numbers, for example 2650.50.") from None


def entry(text):
    parts = re.split(r"\s*[-–]\s*", text.strip())
    if len(parts) not in (1, 2):
        raise ValueError("Enter one price or a zone in low-high order, for example 2650-2655.")
    values = [price(p) for p in parts]
    if len(values) == 2 and Decimal(values[0]) > Decimal(values[1]):
        raise ValueError("Enter the lower price first, for example 2650-2655.")
    return "–".join(values)


def safe_text(text, limit=3000):
    text = text.strip()
    if not text or len(text) > limit:
        raise ValueError(f"Enter a message between 1 and {limit} characters.")
    # Reject accidental credential pastes before they reach storage or Telegram.
    if re.search(r"\b\d{7,12}:[A-Za-z0-9_-]{25,}\b", text):
        raise ValueError("Do not send passwords or bot tokens to this chat.")
    return text


def validate_analysis(text):
    safe_text(text, 900)
    if re.search(r"\[[^\]]+\]", text):
        raise ValueError("Replace every bracketed prompt with your own market observations.")
    if any(pattern.search(text) for pattern in _ACTIONABLE_ANALYSIS_PATTERNS):
        raise ValueError(
            "This looks like a specific trade instruction. Keep Market Analysis educational; "
            "use the PRO Signals workflow for specific entries, levels, and trade updates.")
    return text


def confirmation(direction, symbol):
    return (f"{'🟢' if direction == 'BUY' else '🔴'} {direction} NOW — {symbol}\n\n"
            "Confirmation received. Execute according to your trading plan.\n— Smart Money Hub")


def change(trade, action, value):
    if trade["state"] not in OPEN_STATES:
        raise ValueError("This trade is closed. Open an active trade to make another update.")
    t = {**trade, "targets": dict(trade.get("targets", {}))}
    pair = t.get("symbol") or t.get("market") or "Not supplied"
    direction = t.get("direction", "Not supplied")

    def message(emoji, heading, *lines):
        return f"{emoji} VAYDA SMART MONEY HUB\n\n{heading}\n\n" + "\n".join(lines)

    if action == "entry":
        t["entry"] = entry(value)
        t["state"] = "ACTIVE"
        t["breakeven_confirmed"] = False
        text = message("📌", "Entry Updated", f"📊 Pair: {pair}",
                       f"📌 Direction: {direction}", f"📍 Entry: {t['entry']}")
    elif action == "sl":
        t["sl"] = price(value)
        t["breakeven_confirmed"] = False
        text = message("🛡️", "Stop Loss Updated", f"📊 Pair: {pair}",
                       f"📌 Direction: {direction}", f"🛑 New SL: {t['sl']}",
                       "⚠️ Follow your risk-management plan.")
    elif action == "trail":
        t["sl"] = price(value)
        t["breakeven_confirmed"] = False
        text = message("📈", "Trailing Stop Updated", f"📊 Pair: {pair}",
                       f"🛑 New SL: {t['sl']}")
    elif action == "tp":
        parts = value.split()
        if len(parts) != 2 or not parts[0].isdigit() or not 1 <= int(parts[0]) <= 100:
            raise ValueError("Enter the take-profit number and price separated by a space, for example: 1 2700.")
        key = str(int(parts[0]))
        t["targets"][key] = {"price": price(parts[1]), "hit": False}
        t["targets_auto"] = False
        text = message("🎯", "Take-Profit Updated", f"📊 Pair: {pair}",
                       f"📌 Direction: {direction}",
                       f"🎯 TP{key}: {t['targets'][key]['price']}")
    elif action == "sl_tp":
        parts = value.split("|")
        if len(parts) != 2:
            raise ValueError("Enter both values like this: SL 2580 | TP1 2700.")
        sl_match = re.fullmatch(r"\s*SL\s+(\S+)\s*", parts[0], re.I)
        tp_match = re.fullmatch(r"\s*TP\s*(\d+)\s+(\S+)\s*", parts[1], re.I)
        if not sl_match or not tp_match:
            raise ValueError("Enter both values like this: SL 2580 | TP1 2700.")
        target_number = int(tp_match.group(1))
        if not 1 <= target_number <= 100:
            raise ValueError("The TP number must be from 1 to 100.")
        key = str(target_number)
        if t["targets"].get(key, {}).get("hit"):
            raise ValueError(f"TP{key} is already recorded as hit. Choose another target number.")
        sl_value = price(sl_match.group(1))
        tp_value = price(tp_match.group(2))
        t["sl"] = sl_value
        t["breakeven_confirmed"] = False
        t["targets"][key] = {"price": tp_value, "hit": False}
        t["targets_auto"] = False
        text = message("🛡️", "Stop Loss and Take-Profit Updated",
                       f"📊 Pair: {pair}", f"📌 Direction: {direction}",
                       f"🛑 Stop Loss: {sl_value}", f"🎯 TP{key}: {tp_value}",
                       "⚠️ Review both levels and follow your risk-management plan.")
    elif action == "hit":
        parts = value.split("|", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            raise ValueError("Choose a take-profit number and mark it as Partial or Final.")
        key = str(int(parts[0]))
        status = parts[1].strip().lower()
        if not 1 <= int(key) <= 100 or status not in ("partial", "final"):
            raise ValueError("Choose a listed take-profit number and mark it Partial or Final.")
        if key not in t["targets"]:
            raise ValueError("That take-profit number is not on this trade. Reopen Trade Details and choose a listed target.")
        if t["targets"][key]["hit"]:
            raise ValueError("That target is already recorded as hit.")
        t["targets"][key] = {**t["targets"][key], "hit": True, "hit_status": status}
        status_label = "PARTIAL" if status == "partial" else "FINAL TARGET"
        text = message("🎯", f"TP{key} Hit", f"📊 Pair: {pair}",
                       f"💰 Target: {t['targets'][key]['price']}", f"📈 Status: {status_label}")
    elif action == "partial":
        parts = value.split("|", 3)
        if len(parts) < 2:
            raise ValueError("Choose a percentage and say whether profit was secured or this is only a recommendation.")
        percent, mode = parts[:2]
        p = Decimal(price(percent))
        if p > 100 or mode not in ("reported", "recommendation"):
            raise ValueError("The percentage must be more than 0% and no more than 100%.")
        target = parts[2].strip() if len(parts) > 2 else ""
        remaining = safe_text(parts[3], 200) if len(parts) > 3 and parts[3].strip() else ""
        if mode == "reported":
            if not target:
                raise ValueError("Choose or enter the confirmed take-profit level before reporting secured profit.")
            target = price(target)
            partial_count = int(t.get("partial_count") or (1 if t.get("partial_profit") else 0)) + 1
            t["partial_count"] = partial_count
            t["partial_profit"] = {"percent": format(p, "f"), "target": target, "remaining": remaining}
            lines = [f"📊 Pair: {pair}", f"🎯 Target: {target}",
                     f"📉 Closed: {format(p, 'f')}%"]
            if remaining:
                lines.append(f"Remaining position: {remaining}")
            text = message("💰", "Partial Profits Secured", *lines)
            if partial_count == 1:
                text += "\n\n" + FIRST_PARTIAL_FOLLOW_UP
            elif partial_count == 2 and t.get("breakeven_confirmed") is True:
                text += "\n\n" + SECOND_PARTIAL_FOLLOW_UP
        else:
            text = message("💰", "Partial Profit Recommendation",
                           f"📊 Pair: {pair}", f"📌 Direction: {direction}",
                           f"📉 Consider closing {format(p, 'f')}%. Execution not confirmed.")
    elif action == "be":
        if value != "confirmed" or not t.get("entry"):
            raise ValueError("Confirm that you moved the stop loss to the recorded entry price before publishing this update.")
        t["sl"] = t["entry"]
        t["breakeven_confirmed"] = True
        text = message("🔒", "Stop Loss Moved to Breakeven",
                       f"📊 Pair: {pair}", f"🛑 New SL: {t['entry']}",
                       "Administrator confirmed the move. Market risk is not eliminated.")
    elif action == "cancel":
        if t.get("entry") or t.get("state") == "ACTIVE":
            raise ValueError("This trade has an entry. Use Invalidate Trade or Close Trade instead of cancelling the setup.")
        reason = safe_text(value, 300)
        t["state"] = "CANCELLED"
        t["reason"] = reason
        text = message("🚫", "Unentered Setup Cancelled", f"📊 Pair: {pair}",
                       f"📝 Reason: {reason}",
                       "No entry was recorded for this setup. Do not enter it.")
    elif action == "invalidate":
        if not (t.get("entry") or t.get("state") == "ACTIVE"):
            raise ValueError("This setup has no recorded entry. Use Cancel Setup instead.")
        reason = safe_text(value, 300)
        t["state"] = "INVALIDATED"
        t["reason"] = reason
        text = message("🚫", "Trade Invalidated", f"📊 Pair: {pair}",
                       f"📝 Reason: {reason}",
                       "Anyone already in a position should manage it according to their own plan.")
    elif action == "close":
        parts = value.split("|", 2)
        result = parts[0].strip()
        if result == "Profit":
            result = "Win"
        elif result == "Other":
            result = "Unrecorded"
        if result not in ("Win", "Breakeven", "Loss", "Unrecorded"):
            raise ValueError("Choose Win, Breakeven, Loss, or Unrecorded.")
        exit_price, note = "", ""
        if len(parts) == 2:
            try:
                exit_price = price(parts[1]) if parts[1].strip() else ""
            except ValueError:
                note = safe_text(parts[1], 500)
        elif len(parts) == 3:
            exit_price = price(parts[1]) if parts[1].strip() else ""
            note = safe_text(parts[2], 500) if parts[2].strip() else ""
        if exit_price:
            t["exit"] = exit_price
        t["state"] = "CLOSED"
        t["outcome"] = result
        lines = [f"📊 Pair: {pair}", f"📌 Direction: {direction}",
                 f"📍 Exit: {exit_price or 'Not provided'}", f"📊 Result: {result.upper()}"]
        if note:
            lines.append(f"📝 Note: {note}")
        lines.append("📚 Trade recorded. Stay disciplined.")
        text = message("🏁", "Trade Closed", *lines)
    elif action == "custom":
        text = message("🛠️", "TRADE UPDATE", f"📊 Pair: {pair}",
                       f"📌 Direction: {direction}", safe_text(value))
    else:
        raise ValueError("Unknown trade action.")
    return t, text
