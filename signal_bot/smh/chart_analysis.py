"""Conservative local chart OCR and review helpers.

OCR text is only a visual candidate. It is never treated as a verified market fact,
and chart structure, bias, zones, and confirmation are never inferred from pixels.
"""
import csv
import io
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image


Image.MAX_IMAGE_PIXELS = 24_000_000

UNKNOWN = "Unknown — manual review required"
FIELD_LABELS = {
    "market": "Market",
    "timeframe": "Timeframe",
    "market_structure": "Market structure",
    "order_blocks": "Order Blocks",
    "fair_value_gaps": "Fair Value Gaps",
    "liquidity": "Liquidity",
    "bos": "BOS",
    "choch": "CHoCH",
    "proposed_zones": "Proposed zones",
    "directional_bias": "Directional bias",
    "confirmation_criteria": "Confirmation criteria",
}
FIELD_BY_LABEL = {label.casefold(): key for key, label in FIELD_LABELS.items()}
TIMEFRAMES = {
    "M1", "M2", "M3", "M5", "M10", "M15", "M20", "M30",
    "H1", "H2", "H3", "H4", "H6", "H8", "H12",
    "D1", "W1", "MN1",
}
MARKETS = {
    "XAUUSD", "GOLD", "BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD",
}
CONCEPTS = {"BOS", "CHOCH", "MSS", "OB", "FVG", "LIQUIDITY"}
_RANGE = re.compile(r"(?<![\w.])(\d{1,8}(?:\.\d+)?)\s*[-–]\s*(\d{1,8}(?:\.\d+)?)(?![\w.])")
_ZONE_LABEL = re.compile(r"\b(?:ZONE|OB|FVG|ORDER\s+BLOCK|FAIR\s+VALUE\s+GAP|SUPPLY|DEMAND|LIQUIDITY)\b", re.I)


def _unknown_fields():
    return {key: UNKNOWN for key in FIELD_LABELS}


def _run_local_ocr(image_path):
    executable = shutil.which("tesseract")
    if not executable:
        return None, "unavailable"
    try:
        result = subprocess.run(
            [executable, str(image_path), "stdout", "tsv"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "failed"
    if result.returncode != 0 or not result.stdout.strip():
        return None, "failed"
    return result.stdout, "available"


def _ocr_lines(tsv):
    """Return high-confidence OCR lines without retaining arbitrary low-confidence text."""
    grouped = {}
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        try:
            confidence = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            continue
        word = (row.get("text") or "").strip()
        if not word or confidence < 85:
            continue
        line_key = tuple(row.get(key, "") for key in ("page_num", "block_num", "par_num", "line_num"))
        grouped.setdefault(line_key, []).append((word, confidence))
    return [
        {
            "text": " ".join(word for word, _ in words),
            "min_confidence": min(conf for _, conf in words),
        }
        for words in grouped.values()
    ]


def _candidates(lines):
    markets, timeframes, zones, concepts = [], [], [], []
    for line in lines:
        words = re.findall(r"[A-Z0-9]+", line["text"].upper())
        for word in words:
            if word in MARKETS and word not in markets:
                markets.append(word)
            if word in TIMEFRAMES and word not in timeframes:
                timeframes.append(word)
            if word in CONCEPTS and word not in concepts:
                concepts.append(word)
        if _ZONE_LABEL.search(line["text"]):
            match = _RANGE.search(line["text"])
            if match:
                candidate = {
                    "value": f"{match.group(1)}–{match.group(2)}",
                    "label": line["text"][:100],
                    "ocr_word_confidence": round(line["min_confidence"]),
                }
                if candidate not in zones:
                    zones.append(candidate)
    return {
        "markets": markets,
        "timeframes": timeframes,
        "zones": zones,
        "concept_labels": concepts,
    }


def analyze_chart(image_path, ocr_tsv=None, *, allow_ocr=True):
    """Inspect a local image and surface only optional, unverified OCR candidates.

    Runtime callers must explicitly restrict OCR to the isolated test bot. Supplying
    ocr_tsv remains available for offline tests and never invokes a local executable.
    """
    image_path = Path(image_path)
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            image_format = image.format
            if width * height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("Image is too large for local chart review (maximum 24 megapixels).")
            image.verify()
    except (OSError, Image.DecompressionBombError, Image.UnidentifiedImageError):
        raise ValueError("The chart image could not be read safely.") from None

    if ocr_tsv is None and not allow_ocr:
        engine_state = "disabled"
    elif ocr_tsv is None:
        ocr_tsv, engine_state = _run_local_ocr(image_path)
    else:
        engine_state = "available"

    lines = _ocr_lines(ocr_tsv or "") if engine_state == "available" else []
    candidates = _candidates(lines)
    if engine_state == "disabled":
        note = "Local OCR is enabled only for the isolated test bot. No chart values were inferred."
        engine = "Disabled outside isolated test"
        status = "disabled"
    elif engine_state == "unavailable":
        note = "No local Tesseract OCR engine is installed. No chart values were inferred."
        engine = "Unavailable"
        status = "unavailable"
    elif engine_state == "failed":
        note = "Local OCR did not complete. No chart values were inferred."
        engine = "Tesseract OCR (local, failed)"
        status = "unavailable"
    else:
        note = (
            "OCR candidates are visible-text readings only; OCR word scores are not calibrated "
            "recognition confidence. Verify all values manually. No zones, bias, structure, or "
            "confirmation are inferred from chart geometry."
        )
        engine = "Tesseract OCR (local)" if ocr_tsv is not None else "Local OCR"
        status = "candidates" if any(candidates.values()) else "no_candidates"

    return {
        "engine": engine,
        "status": status,
        "image_width": width,
        "image_height": height,
        "image_format": image_format,
        "fields": _unknown_fields(),
        "candidates": candidates,
        "uncertainty": note,
    }


def format_review_report(report):
    fields = report.get("fields") or _unknown_fields()
    lines = [
        "🔎 LOCAL CHART REVIEW — DRAFT",
        f"Recognition: {report.get('engine', 'Unavailable')} · {report.get('status', 'unavailable')}",
        f"Image: {report.get('image_width', '?')} × {report.get('image_height', '?')} "
        f"{report.get('image_format', 'unknown')}",
    ]
    lines.extend(f"{FIELD_LABELS[key]}: {fields.get(key, UNKNOWN)}" for key in FIELD_LABELS)
    candidates = report.get("candidates") or {}
    candidate_lines = []
    for label, key in (
        ("Markets", "markets"),
        ("Timeframes", "timeframes"),
        ("Zones (labelled OCR text)", "zones"),
        ("Visible SMC text labels", "concept_labels"),
    ):
        values = candidates.get(key) or []
        if values:
            if key == "zones":
                values = [f"{item['value']} (OCR word score {item['ocr_word_confidence']}, unverified)"
                          for item in values]
            candidate_lines.append(f"{label}: " + ", ".join(map(str, values)))
    lines.append("OCR text candidates (unverified): " + ("; ".join(candidate_lines) if candidate_lines else "none"))
    lines.append("No automatic zones were drawn. Use manual field correction and annotation tools.")
    lines.append("Uncertainty: " + report.get("uncertainty", "Manual review required."))
    return "\n".join(lines)


def build_analysis_caption(fields):
    fields = fields or _unknown_fields()
    lines = [
        "📊 VAYDA SMART MONEY HUB — CHART REVIEW",
        "Visual observations only; not verified market facts.",
        "",
    ]
    lines.extend(f"{FIELD_LABELS[key]}: {fields.get(key) or UNKNOWN}" for key in FIELD_LABELS)
    lines.extend([
        "",
        "Verify all chart details manually. This analysis draft is not a trading signal.",
    ])
    text = "\n".join(lines)
    from .domain import validate_analysis
    return validate_analysis(text)


def manual_fields_prompt(fields):
    lines = [
        "Correct any fields you can verify from the screenshot. Send one field per line as Label: value.",
        "Keep Unknown for anything unreadable or unsupported. These are your observations, not verified market facts.",
        "",
    ]
    lines.extend(f"{FIELD_LABELS[key]}: {fields.get(key, UNKNOWN)}" for key in FIELD_LABELS)
    return "\n".join(lines)


def parse_manual_fields(text, existing=None):
    from .domain import safe_text

    if not isinstance(text, str) or not text.strip():
        raise ValueError("Enter at least one chart field as Label: value.")
    values = {**_unknown_fields(), **(existing or {})}
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        label, separator, value = line.partition(":")
        key = FIELD_BY_LABEL.get(label.strip().casefold())
        if not separator or key is None:
            raise ValueError("Use the listed field labels, one per line, followed by a colon.")
        if key in seen:
            raise ValueError(f"Enter {FIELD_LABELS[key]} only once.")
        value = value.strip()
        if not value:
            raise ValueError(f"Enter a value or Unknown for {FIELD_LABELS[key]}.")
        if value.casefold() in ("unknown", "?", "not supplied", "not readable"):
            value = UNKNOWN
        else:
            value = safe_text(value, 120)
        values[key] = value
        seen.add(key)
    if not seen:
        raise ValueError("Enter at least one chart field as Label: value.")
    return values
