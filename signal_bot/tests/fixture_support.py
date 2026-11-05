"""Helpers for isolated, synthetic setup fixtures used only by offline tests."""
import json
from pathlib import Path

from PIL import Image


FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_FILE = FIXTURE_DIR / "test_only_zone.json"


def load_zone_fixture():
    return json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))


def validate_fixture_chart(setup, image_path):
    """Reject a synthetic chart if its embedded setup manifest differs."""
    try:
        with Image.open(image_path) as image:
            if image.format != "PNG":
                raise ValueError("Fixture chart must be a PNG.")
            manifest_text = image.info.get("vayda_test_fixture")
            image.verify()
    except (OSError, ValueError) as exc:
        raise ValueError(f"Fixture chart is unreadable: {exc}") from None

    if not manifest_text:
        raise ValueError("Fixture chart has no test manifest.")
    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError:
        raise ValueError("Fixture chart test manifest is invalid.") from None

    if manifest.get("label") != "TEST ONLY / DO NOT TRADE":
        raise ValueError("Fixture chart is missing its TEST ONLY / DO NOT TRADE label.")
    if manifest.get("kind") != "synthetic-chart":
        raise ValueError("Fixture chart is not identified as synthetic.")

    for key in ("market", "zone", "timeframe", "condition"):
        if manifest.get(key) != setup.get(key):
            raise ValueError(f"Chart/setup mismatch: {key} does not match.")

    market = str(setup.get("market", "")).upper()
    if "TEST ONLY" not in market or "DO NOT TRADE" not in market:
        raise ValueError("Fixture setup must be labelled TEST ONLY / DO NOT TRADE.")
    return manifest
