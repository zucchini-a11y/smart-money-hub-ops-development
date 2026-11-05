"""Conservative local price reading for administrator-reviewed TP1 screenshots."""
import csv
import io
import re
import shutil
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .domain import price
from .zones import automatic_tp1_pip_size

_PRICE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,8}(?:[.,]\d{1,8})?)(?![\w.])")
_ENTRY_LABEL = re.compile(r"\b(?:entry|open(?:ing)?(?:\s+price)?)\b", re.I)
_EXIT_LABEL = re.compile(r"\b(?:exit|clos(?:e|ed|ing)(?:\s+price)?)\b", re.I)
_TRADE_ROW = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9._-]{2,}),?\s+(BUY|SELL)\b"
    r"(?:\s+\d+(?:[.,]\d+)?){0,2}\s*$", re.I)
_PRICE_ARROW_ROW = re.compile(
    r"^\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,8}(?:[.,]\d{1,8})?)\s*"
    r"(?:→|->|—|–|−)\s*"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,8}(?:[.,]\d{1,8})?)\s*$")


def _text_lines(tsv):
    grouped = {}
    for row in csv.DictReader(io.StringIO(tsv or ""), delimiter="\t"):
        try:
            confidence = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            continue
        word = (row.get("text") or "").strip()
        if not word or confidence < 60:
            continue
        key = tuple(row.get(name, "") for name in (
            "page_num", "block_num", "par_num", "line_num"))
        grouped.setdefault(key, []).append(word)
    return [" ".join(words) for words in grouped.values()]


def _normalize_price(raw):
    # A lone comma could be either a decimal or thousands separator. Do not infer.
    if "," in raw and "." not in raw and not re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw):
        return None
    try:
        return price(raw.replace(",", ""))
    except ValueError:
        return None


def extract_labeled_prices(tsv):
    """Return one clearly labeled entry/open and exit/close price, or no result."""
    values = {"entry": [], "exit": []}
    for line in _text_lines(tsv):
        labels = [
            ("entry", match) for match in _ENTRY_LABEL.finditer(line)
        ] + [
            ("exit", match) for match in _EXIT_LABEL.finditer(line)
        ]
        labels.sort(key=lambda item: item[1].start())
        for index, (kind, label) in enumerate(labels):
            end = labels[index + 1][1].start() if index + 1 < len(labels) else len(line)
            match = _PRICE.search(line, label.end(), end)
            if not match:
                continue
            normalized = _normalize_price(match.group(1))
            if normalized is not None:
                values[kind].append(normalized)

    if len(values["entry"]) != 1 or len(values["exit"]) != 1:
        return None
    if values["entry"][0] == values["exit"][0]:
        return None
    return {"entry": values["entry"][0], "exit": values["exit"][0]}


def extract_position_rows(tsv):
    """Read explicit trade rows followed by a left-to-right arrow-separated price pair."""
    lines = _text_lines(tsv)
    candidates = []
    for index, line in enumerate(lines):
        header = _TRADE_ROW.fullmatch(line)
        if not header:
            continue
        if index + 1 >= len(lines):
            return None
        prices = _PRICE_ARROW_ROW.fullmatch(lines[index + 1])
        if not prices:
            return None
        entry, exit_price = (
            _normalize_price(prices.group(1)),
            _normalize_price(prices.group(2)),
        )
        if not entry or not exit_price or entry == exit_price:
            return None
        candidates.append({
            "symbol": header.group(1),
            "direction": header.group(2).upper(),
            "entry": entry,
            "exit": exit_price,
        })
    return candidates or None


def read_screenshot_prices(image_path):
    """Run local Tesseract TSV OCR. No image or OCR text is sent to a remote service."""
    executable = shutil.which("tesseract")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, str(Path(image_path)), "stdout", "tsv"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    labeled = extract_labeled_prices(result.stdout)
    if labeled:
        return labeled
    rows = extract_position_rows(result.stdout)
    return {"candidates": rows} if rows else None


def calculate_pips(market, direction, entry_price, exit_price):
    """Calculate signed pips only for the configured Forex and XAUUSD pip sizes."""
    pip_size = profit_pip_size(market)
    if pip_size is None:
        raise ValueError("Pip calculation is supported only for configured Forex pairs and XAUUSD.")
    return calculate_trade_result(market, direction, entry_price, exit_price)["pips"]


def profit_pip_size(market):
    """Pip size for realized-profit screenshots and statistics (not TP ladder math)."""
    normalized = re.sub(r"[^A-Z]", "", str(market or "").upper())
    if "XAUUSD" in normalized:
        return Decimal("0.1")
    return automatic_tp1_pip_size(market)


def signed_trade_pips(market, direction, entry_price, exit_price):
    """Return signed realized pips, or None if the market/value is unsupported."""
    pip_size = profit_pip_size(market)
    if pip_size is None or direction not in ("BUY", "SELL"):
        return None
    try:
        entry_value = Decimal(price(str(entry_price)))
        exit_value = Decimal(price(str(exit_price)))
    except (TypeError, ValueError):
        return None
    movement = exit_value - entry_value if direction == "BUY" else entry_value - exit_value
    pips = movement / pip_size
    if "XAUUSD" in re.sub(r"[^A-Z]", "", str(market or "").upper()):
        pips = pips.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return pips


def calculate_trade_result(market, direction, entry_price, exit_price):
    """Calculate pips where defined; otherwise return a transparent price movement."""
    entry_value = Decimal(price(str(entry_price)))
    exit_value = Decimal(price(str(exit_price)))
    if direction == "BUY":
        movement = exit_value - entry_value
    elif direction == "SELL":
        movement = entry_value - exit_value
    else:
        raise ValueError("The trade direction is unavailable; pips cannot be calculated.")
    if movement <= 0:
        raise ValueError("The detected exit price is not profitable for this trade direction. Review or correct the prices.")
    pip_size = profit_pip_size(market)
    result = {
        "price_movement": format(movement.normalize(), "f"),
        "pips": None,
    }
    if pip_size is not None:
        pips = movement / pip_size
        if "XAUUSD" in re.sub(r"[^A-Z]", "", str(market or "").upper()):
            pips = pips.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        result["pips"] = format(pips.normalize(), "f")
    return result


def saved_screenshot_pips(trade, record):
    """Recalculate persisted screenshot pips with the current display convention."""
    entry_value = record.get("observed_entry") or trade.get("entry")
    exit_value = record.get("observed_exit")
    if entry_value and exit_value:
        try:
            return calculate_trade_result(
                trade.get("market") or trade.get("symbol"),
                str(trade.get("direction", "")).upper(),
                entry_value,
                exit_value,
            ).get("pips")
        except ValueError:
            pass
    return record.get("pips")


def target_profit_screenshots(trade):
    """Return target screenshot history, including the legacy TP1 record."""
    saved = trade.get("target_profit_screenshots")
    records = dict(saved) if isinstance(saved, dict) else {}
    legacy_tp1 = trade.get("tp1_profit_screenshot")
    if legacy_tp1 and "1" not in records:
        records["1"] = legacy_tp1
    return records


def next_target_profit_screenshot(trade, max_targets=4):
    """Return the next available target number, preserving strict sequence."""
    records = target_profit_screenshots(trade)
    targets = trade.get("targets") or {}
    for number in range(1, max_targets + 1):
        key = str(number)
        if key not in records:
            return number if key in targets else None
    return None


def validate_target_exit(direction, target_price, exit_price):
    """Require the confirmed screenshot exit to have reached its named TP."""
    target = Decimal(price(str(target_price)))
    exit_value = Decimal(price(str(exit_price)))
    if direction == "BUY" and exit_value < target:
        raise ValueError(
            f"The screenshot exit price has not reached TP at {target_price}. Check the prices."
        )
    if direction == "SELL" and exit_value > target:
        raise ValueError(
            f"The screenshot exit price has not reached TP at {target_price}. Check the prices."
        )
