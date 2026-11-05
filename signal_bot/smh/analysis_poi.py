"""Extract only explicitly labelled POI ranges from a Market Analysis caption."""
import re
from decimal import Decimal

from .domain import price, safe_text
from .zones import parse_zone


_NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w.])")
_DIRECTIONAL_POI = re.compile(r"\b(?P<direction>BUY|SELL)\s+POI(?:\s+ZONE)?\b", re.I)
_GENERIC_POI = re.compile(
    r"\b(?:POI(?:\s+ZONE)?|POINT OF INTEREST)\s*:\s*",
    re.I,
)
_POI_INTENT = re.compile(
    r"\b(?:BUY|SELL)\s+POI\b|\bPOI\s+ZONE\b|\bPOINT OF INTEREST\s*:",
    re.I,
)
_CURRENCIES = {
    "AUD", "BRL", "CAD", "CHF", "CNH", "CZK", "DKK", "EUR", "GBP",
    "HKD", "HUF", "ILS", "INR", "JPY", "MXN", "NOK", "NZD", "PLN",
    "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
}

DEFAULT_CONFIRMATION = (
    "Wait for liquidity behaviour, displacement, and M5 CHoCH/MSS after price "
    "reacts at the POI. A POI touch alone is not entry confirmation."
)


def _field(text, label):
    match = re.search(
        rf"(?im)^\s*.*?\b{label}\s*:\s*(.*?)\s*$",
        text,
    )
    return match.group(1).strip() if match else ""


def _market(value):
    value = safe_text(value, 80)
    if "|" in value or "\n" in value or "\r" in value:
        raise ValueError("The MARKET line must contain one market on one line.")
    upper = value.upper()
    gold = re.search(r"\bXAUUSD(?:\.[A-Z0-9]+)?\b", upper)
    if gold:
        return f"Gold/{gold.group(0)}"
    forex = re.search(r"\b([A-Z]{6})\b", upper)
    if forex:
        symbol = forex.group(1)
        if symbol[:3] in _CURRENCIES and symbol[3:] in _CURRENCIES:
            return f"Forex/{symbol}"
    return value


def _range(segment):
    matches = list(_NUMBER.finditer(segment))
    if len(matches) != 2:
        raise ValueError("Each POI must show exactly two readable prices as a range.")
    separator = segment[matches[0].end():matches[1].start()]
    if not re.search(r"(?:-|–|—|\bto\b)", separator, re.I):
        raise ValueError("Each POI needs two prices separated by a range marker.")
    values = [
        Decimal(price(match.group(0).replace(",", "")))
        for match in matches
    ]
    if values[0] == values[1]:
        raise ValueError("A POI range needs two different prices.")
    low, high = sorted(values)
    normalized = (price(format(low, "f")), price(format(high, "f")))
    approximate = bool(re.search(r"\b(?:approx(?:imately)?|around|about)\b|~", segment, re.I))
    return normalized, approximate


def extract_poi_setups(caption):
    """Build validated PRO setup drafts from explicit MARKET/TIMEFRAME/POI labels.

    A caption without an explicit POI range returns an empty list. Once a POI
    label is present, missing fields or ambiguous prices fail closed.
    """
    text = str(caption or "")
    labelled_zones = []
    for line in text.splitlines():
        directional = list(_DIRECTIONAL_POI.finditer(line))
        if directional:
            for index, match in enumerate(directional):
                end = directional[index + 1].start() if index + 1 < len(directional) else len(line)
                labelled_zones.append((line[match.end():end], match.group("direction").upper()))
            continue
        for match in _GENERIC_POI.finditer(line):
            labelled_zones.append((line[match.end():], None))

    if not labelled_zones:
        if _POI_INTENT.search(text):
            raise ValueError(
                "Label the exact POI range as POI ZONE: lower price – upper price."
            )
        return []

    market_value = _field(text, "MARKET")
    timeframe = _field(text, "TIMEFRAME")
    if not market_value:
        raise ValueError("Add a MARKET: line before publishing this POI to PRO Signals.")
    if not timeframe:
        raise ValueError("Add a TIMEFRAME: line before publishing this POI to PRO Signals.")

    market = _market(market_value)
    timeframe = safe_text(timeframe, 30)
    if "|" in timeframe or "\n" in timeframe or "\r" in timeframe:
        raise ValueError("The TIMEFRAME line must contain one timeframe on one line.")

    setups = []
    for segment, direction in labelled_zones:
        (low, high), approximate = _range(segment)
        setup = parse_zone(
            f"{market} | {low}-{high} | {timeframe} | manual | {DEFAULT_CONFIRMATION}"
        )
        if direction:
            setup["poi_direction"] = direction
        if approximate:
            setup["approximate_zone"] = True
        setups.append(setup)
    return setups
