"""Offline checks for conservative chart OCR and review-copy generation."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from smh.chart_analysis import (
    FIELD_LABELS,
    UNKNOWN,
    analyze_chart,
    build_analysis_caption,
    parse_manual_fields,
)
from smh.domain import validate_analysis
from smh.images import BRAND, render, render_review_copy


CHART = Path(__file__).parent / "fixtures" / "test_only_zone_chart.png"


def tsv_row(word, confidence, line=1, index=1):
    return f"5\t1\t1\t1\t{line}\t{index}\t10\t10\t50\t20\t{confidence}\t{word}"


def recording_draw_factory():
    recorded = []
    real_draw = ImageDraw.Draw

    def factory(image, *args, **kwargs):
        draw = real_draw(image, *args, **kwargs)

        class RecordingDraw:
            def text(self, xy, text, *draw_args, **draw_kwargs):
                recorded.append(str(text))
                return draw.text(xy, text, *draw_args, **draw_kwargs)

            def __getattr__(self, name):
                return getattr(draw, name)

        return RecordingDraw()

    return recorded, factory


class LocalChartAnalysisTests(unittest.TestCase):
    def test_unavailable_ocr_returns_unknowns_without_guessing(self):
        with patch("smh.chart_analysis.shutil.which", return_value=None):
            report = analyze_chart(CHART)
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["engine"], "Unavailable")
        self.assertTrue(all(value == UNKNOWN for value in report["fields"].values()))
        self.assertFalse(any(report["candidates"].values()))
        self.assertIn("No chart values were inferred", report["uncertainty"])

    def test_ocr_is_disabled_outside_isolated_test_mode(self):
        with patch("smh.chart_analysis._run_local_ocr") as run_ocr:
            report = analyze_chart(CHART, allow_ocr=False)
        run_ocr.assert_not_called()
        self.assertEqual(report["status"], "disabled")
        self.assertEqual(report["engine"], "Disabled outside isolated test")
        self.assertTrue(all(value == UNKNOWN for value in report["fields"].values()))
        self.assertFalse(any(report["candidates"].values()))

    def test_ocr_text_is_only_an_unverified_candidate(self):
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
        rows = [
            tsv_row("XAUUSD", 96, 1, 1),
            tsv_row("M15", 94, 1, 2),
            tsv_row("ZONE", 93, 2, 1),
            tsv_row("4150-4155", 91, 2, 2),
            tsv_row("BOS", 92, 3, 1),
            tsv_row("FVG", 92, 3, 2),
            tsv_row("SELL", 70, 4, 1),
        ]
        report = analyze_chart(CHART, ocr_tsv=header + "\n" + "\n".join(rows))
        self.assertEqual(report["status"], "candidates")
        self.assertEqual(report["candidates"]["markets"], ["XAUUSD"])
        self.assertEqual(report["candidates"]["timeframes"], ["M15"])
        self.assertEqual(report["candidates"]["zones"][0]["value"], "4150–4155")
        self.assertEqual(report["candidates"]["concept_labels"], ["BOS", "FVG"])
        self.assertTrue(all(value == UNKNOWN for value in report["fields"].values()))
        self.assertIn("not calibrated", report["uncertainty"])
        self.assertNotIn("SELL", report["uncertainty"])

    def test_manual_fields_preserve_unknowns_and_build_review_caption(self):
        fields = parse_manual_fields(
            "Market: XAUUSD\nTimeframe: M15\nProposed zones: 4150–4155\nDirectional bias: Unknown",
            {},
        )
        self.assertEqual(fields["market"], "XAUUSD")
        self.assertEqual(fields["timeframe"], "M15")
        self.assertEqual(fields["proposed_zones"], "4150–4155")
        self.assertEqual(fields["order_blocks"], UNKNOWN)
        caption = build_analysis_caption(fields)
        self.assertIn("Visual observations only; not verified market facts.", caption)
        self.assertIn("Proposed zones: 4150–4155", caption)
        self.assertIn("This analysis draft is not a trading signal.", caption)
        self.assertEqual(len(FIELD_LABELS), 11)

    def test_manual_fields_reject_unknown_labels_empty_values_and_trade_instructions(self):
        with self.assertRaisesRegex(ValueError, "listed field labels"):
            parse_manual_fields("Price: 4150", {})
        with self.assertRaisesRegex(ValueError, "Enter a value"):
            parse_manual_fields("Market:", {})
        fields = parse_manual_fields("Directional bias: BUY NOW", {})
        with self.assertRaisesRegex(ValueError, "specific trade instruction"):
            build_analysis_caption(fields)
        with self.assertRaisesRegex(ValueError, "specific trade instruction"):
            validate_analysis("SELL NOW — XAUUSD")

    def test_review_copy_is_separate_and_original_remains_byte_identical(self):
        original_hash = hashlib.sha256(CHART.read_bytes()).hexdigest()
        drawn_text = []
        with tempfile.TemporaryDirectory() as directory:
            report = analyze_chart(CHART, ocr_tsv="")
            report["candidates"] = {"concept_labels": ["BOS", "FVG"]}
            drawn_text, draw_factory = recording_draw_factory()
            with patch("smh.images.ImageDraw.Draw", side_effect=draw_factory):
                annotated = Path(render_review_copy(CHART, report, directory))
            self.assertNotEqual(annotated, CHART)
            self.assertTrue(annotated.exists())
            self.assertNotEqual(annotated.read_bytes(), CHART.read_bytes())
            self.assertEqual(drawn_text, [BRAND])
            self.assertFalse(any(
                "manual review required" in text.lower() or
                "not a signal" in text.lower() or
                "verify all values" in text.lower()
                for text in drawn_text
            ))
            with Image.open(annotated) as image:
                self.assertEqual(image.format, "PNG")
                with Image.open(CHART) as original:
                    self.assertEqual(image.width, original.width)
                    self.assertGreater(image.height, original.height)
        self.assertEqual(hashlib.sha256(CHART.read_bytes()).hexdigest(), original_hash)

    def test_annotated_copy_uses_only_supplied_labels_and_branding(self):
        original_hash = hashlib.sha256(CHART.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            drawn_text, draw_factory = recording_draw_factory()
            with patch("smh.images.ImageDraw.Draw", side_effect=draw_factory):
                annotated = Path(render(
                    CHART,
                    ["zone 10 20 40 45 FVG", "label 60 15 BOS"],
                    directory,
                ))
            self.assertEqual(drawn_text, ["FVG", "BOS", BRAND])
            self.assertFalse(any(
                "manual review required" in text.lower() or
                "not a signal" in text.lower() or
                "verify all values" in text.lower()
                for text in drawn_text
            ))
            self.assertNotEqual(annotated, CHART)
            self.assertTrue(annotated.exists())
        self.assertEqual(hashlib.sha256(CHART.read_bytes()).hexdigest(), original_hash)

    def test_internal_verification_notices_are_rejected_as_chart_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            for label in (
                "No verified zone — manual review required",
                "Not a signal — verify all values",
                "OCR candidates only — verify manually",
            ):
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError, "Internal verification notices"
                ):
                    render(CHART, [f"label 5 5 {label}"], directory)

    def test_unreadable_chart_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "not-a-chart.png"
            bad.write_text("not an image", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "could not be read safely"):
                analyze_chart(bad)


if __name__ == "__main__":
    unittest.main()
