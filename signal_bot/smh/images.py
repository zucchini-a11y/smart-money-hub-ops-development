"""Local annotations using administrator-supplied percent coordinates."""
import math
import re
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .database import uid

Image.MAX_IMAGE_PIXELS = 24_000_000
BRAND = "VAYDA SMART MONEY HUB"
_INTERNAL_CHART_STATUSES = (
    "manual review required",
    "not a signal verify all values",
    "ocr candidates only verify manually",
)


def _contains_internal_chart_status(text):
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip()
    return any(status in normalized for status in _INTERNAL_CHART_STATUSES)


def _brand_footer(image):
    """Add a consistent brand mark below the chart, without covering chart data."""
    width, height = image.size
    font_size = max(10, min(24, width // 70))
    font = ImageFont.load_default(size=font_size)
    probe = ImageDraw.Draw(image)
    bounds = probe.textbbox((0, 0), BRAND, font=font)
    while bounds[2] - bounds[0] > width - 24 and font_size > 8:
        font_size -= 1
        font = ImageFont.load_default(size=font_size)
        bounds = probe.textbbox((0, 0), BRAND, font=font)

    text_height = bounds[3] - bounds[1]
    footer_height = max(34, text_height + 16)
    branded = Image.new("RGB", (width, height + footer_height), "#14232c")
    branded.paste(image.convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(branded)
    draw.line((0, height, width, height), fill="#c9a35b", width=2)
    text_y = height + (footer_height - text_height) // 2 - bounds[1]
    draw.text((12, text_y), BRAND, font=font, fill="#f5f7f8")
    return branded


def import_chart(source, folder):
    with Image.open(source) as im:
        if im.width * im.height > Image.MAX_IMAGE_PIXELS:
            raise ValueError("Image is too large (maximum 24 megapixels).")
        suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(im.format)
        if not suffix:
            raise ValueError("Use a PNG, JPEG, or WebP image.")
        im.verify()
    path = Path(folder) / f"{uid()}{suffix}"
    shutil.copyfile(source, path)
    return str(path)


def render(original, commands, folder):
    """Commands: line y label; zone x1 y1 x2 y2 label; arrow ...;
    label x y text; crop x1 y1 x2 y2; resize width height.
    Percent coordinates are relative to current image, top-left = 0 0.
    """
    with Image.open(original) as source:
        im = ImageOps.exif_transpose(source).convert("RGB")
    for command in commands:
        words = command.strip().split()
        if not words:
            continue
        op = words[0].lower()
        if op not in ("line", "zone", "arrow", "label", "crop", "resize"):
            raise ValueError("Unknown tool. Use line, zone, arrow, label, crop, or resize.")
        count = {"line": 1, "zone": 4, "arrow": 4, "label": 2, "crop": 4, "resize": 2}[op]
        try:
            numbers = [float(w) for w in words[1:count+1]]
            if len(numbers) != count or not all(math.isfinite(v) for v in numbers):
                raise ValueError
            if op != "resize" and not all(0 <= v <= 100 for v in numbers):
                raise ValueError
        except ValueError:
            raise ValueError("Invalid coordinates. Use percentages from 0 to 100.") from None
        label = " ".join(words[count+1:])[:160]
        if _contains_internal_chart_status(label):
            raise ValueError("Internal verification notices cannot be added to a chart image.")
        w, h = im.size
        draw = ImageDraw.Draw(im)
        font = ImageFont.load_default(size=max(16, w // 65))
        color = "#f5b942"
        stroke = max(2, w // 500)
        def point(x, y):
            return (int(x * (w-1) / 100), int(y * (h-1) / 100))
        if op == "line":
            y = int(numbers[0] * (h-1) / 100)
            draw.line((0, y, w, y), fill=color, width=stroke)
            draw.text((8, max(0, y-25)), label, font=font, fill=color, stroke_width=1, stroke_fill="black")
        elif op in ("zone", "arrow", "crop"):
            x1, y1, x2, y2 = numbers
            a, b = point(x1, y1), point(x2, y2)
            if op != "arrow" and (x2 <= x1 or y2 <= y1):
                raise ValueError("Bottom-right must be below and right of top-left.")
            if op == "crop":
                im = im.crop((*a, *b))
            elif op == "zone":
                draw.rectangle((*a, *b), outline=color, width=stroke)
                draw.text(a, label, font=font, fill=color, stroke_width=1, stroke_fill="black")
            else:
                draw.line((*a, *b), fill=color, width=stroke)
                angle = math.atan2(b[1]-a[1], b[0]-a[0])
                size = max(12, w // 70)
                ends = [(b[0]-size*math.cos(angle+s), b[1]-size*math.sin(angle+s)) for s in (-.5, .5)]
                draw.polygon([b, *ends], fill=color)
                draw.text(a, label, font=font, fill=color, stroke_width=1, stroke_fill="black")
        elif op == "label":
            if not label:
                raise ValueError("Supply label text.")
            draw.text(point(*numbers), label, font=font, fill=color, stroke_width=1, stroke_fill="black")
        else:
            if not all(100 <= v <= 3000 and v.is_integer() for v in numbers):
                raise ValueError("Resize dimensions must be whole numbers from 100 to 3000 pixels.")
            im = im.resize(tuple(int(v) for v in numbers), Image.Resampling.LANCZOS)
        if min(im.size) < 50:
            raise ValueError("Crop is too small.")
    im = _brand_footer(im)
    out = Path(folder) / f"{uid()}.png"
    im.save(out)
    return str(out)


def render_review_copy(original, _report, folder):
    """Create a clean branded review image; verification status stays outside the image."""
    with Image.open(original) as source:
        im = ImageOps.exif_transpose(source).convert("RGB")
    review = _brand_footer(im)
    out = Path(folder) / f"{uid()}.png"
    review.save(out, format="PNG")
    return str(out)


def render_signal_capture(public_text, folder):
    """Render a clean screenshot-ready card using only the exact published signal text."""
    import html

    text = html.unescape(re.sub(r"<[^>]*>", "", str(public_text or ""))).strip()
    if text not in ("🟢 BUY NOW", "🔴 SELL NOW"):
        raise ValueError("The saved public signal text is not a supported BUY NOW or SELL NOW message.")
    direction = "BUY NOW" if text.startswith("🟢") else "SELL NOW"
    accent = "#27c58a" if direction == "BUY NOW" else "#ef6262"
    width, height = 1200, 660
    image = Image.new("RGB", (width, height), "#101922")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 42, width - 42, height - 42), radius=30,
                           fill="#17232d", outline="#c8a45c", width=3)
    def font(size):
        for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    brand_font = font(30)
    signal_font = font(104)
    eyebrow = font(24)
    draw.text((92, 100), BRAND, font=brand_font, fill="#f4f5f6")
    draw.line((92, 158, width - 92, 158), fill="#33434d", width=2)
    draw.text((92, 220), "PUBLISHED SIGNAL", font=eyebrow, fill="#b9c4ca")
    draw.rounded_rectangle((92, 300, width - 92, 500), radius=24,
                           fill="#101922", outline=accent, width=4)
    bounds = draw.textbbox((0, 0), direction, font=signal_font)
    text_width = bounds[2] - bounds[0]
    draw.text(((width - text_width) / 2, 350), direction, font=signal_font, fill=accent)
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    out = target / f"{uid()}.png"
    image.save(out, format="PNG")
    return str(out)


def as_document(path):
    """Telegram photo constraints; large/tall charts remain publishable as files."""
    with Image.open(path) as im:
        return (Path(path).stat().st_size > 9_500_000 or im.width + im.height > 10000
                or max(im.size) / min(im.size) > 20)
