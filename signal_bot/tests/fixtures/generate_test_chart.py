"""Regenerate the offline-only synthetic chart from test_only_zone.json."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


HERE = Path(__file__).parent
fixture = json.loads((HERE / "test_only_zone.json").read_text(encoding="utf-8"))
setup = fixture["setup"]
width, height = 1200, 760
image = Image.new("RGB", (width, height), "#f7f9fc")
draw = ImageDraw.Draw(image)


def font(size, bold=False):
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / filename
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=24, fill="white",
                       outline="#d8dee9", width=2)
draw.text((60, 52), fixture["label"], font=font(42, True), fill="#a12626")
draw.text((62, 112), f'Market: {setup["market"]}', font=font(24, True), fill="#1d2939")
draw.text((62, 150),
          f'Zone: {setup["zone"].replace("–", "-")}    Timeframe: {setup["timeframe"]}',
          font=font(24), fill="#1d2939")
draw.text((62, 188), "SYNTHETIC DATA ONLY - NOT A LIVE MARKET CHART",
          font=font(20, True), fill="#8b1e1e")

left, right, top, bottom = 145, 1040, 250, 635
low_axis, high_axis = 99.0, 102.0


def y_for(value):
    return round(bottom - (value - low_axis) * (bottom - top) / (high_axis - low_axis))


zone_low, zone_high = (float(part) for part in setup["zone"].replace("–", "-").split("-"))
draw.rectangle((left, y_for(zone_high), right, y_for(zone_low)),
               fill="#d9ecff", outline="#3677b9", width=3)
draw.text((left + 12, y_for(zone_high) + 8),
          f'TEST ZONE {zone_low:g}-{zone_high:g}', font=font(18, True), fill="#164e82")

for tick in (99, 99.5, 100, 100.5, 101, 101.5, 102):
    y = y_for(tick)
    draw.line((left, y, right, y), fill="#d9e0ea", width=1)
    draw.text((65, y - 12), f"{tick:.1f}", font=font(17), fill="#526174")

# Deliberately synthetic OHLC values, visibly contained around the test zone.
candles = [
    (99.25, 99.55, 99.10, 99.45),
    (99.45, 99.80, 99.35, 99.72),
    (99.72, 100.08, 99.60, 99.98),
    (99.98, 100.35, 99.90, 100.28),
    (100.28, 100.62, 100.20, 100.55),
    (100.55, 100.88, 100.48, 100.78),
    (100.78, 101.16, 100.69, 101.04),
    (101.04, 101.22, 100.82, 100.91),
    (100.91, 101.08, 100.72, 100.99),
    (100.99, 101.30, 100.90, 101.20),
    (101.20, 101.38, 101.00, 101.12),
    (101.12, 101.27, 100.86, 100.98),
]
slot = (right - left) / len(candles)
for index, (open_, high, low, close) in enumerate(candles):
    x = round(left + (index + 0.5) * slot)
    color = "#16845b" if close >= open_ else "#c43d4b"
    draw.line((x, y_for(high), x, y_for(low)), fill=color, width=3)
    y_open, y_close = y_for(open_), y_for(close)
    y1, y2 = sorted((y_open, y_close))
    if y2 - y1 < 5:
        y2 = y1 + 5
    draw.rectangle((x - 12, y1, x + 12, y2), fill=color)

draw.line((left, bottom, right, bottom), fill="#526174", width=2)
draw.line((left, top, left, bottom), fill="#526174", width=2)
draw.text((left, 665), "SYNTHETIC TEST FIXTURE - NO TRADING DATA",
          font=font(20, True), fill="#8b1e1e")

metadata = {
    "kind": "synthetic-chart",
    "label": fixture["label"],
    **{key: setup[key] for key in ("market", "zone", "timeframe", "condition")},
}
png_info = PngImagePlugin.PngInfo()
png_info.add_text("vayda_test_fixture", json.dumps(metadata, ensure_ascii=False))
image.save(HERE / fixture["chart_file"], format="PNG", pnginfo=png_info, optimize=True)
print(f"Generated offline fixture: {HERE / fixture['chart_file']}")
