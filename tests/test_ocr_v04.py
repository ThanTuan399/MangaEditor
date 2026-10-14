import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QBuffer, QIODevice, QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from manga_editor.infrastructure.benchmark_dataset import add_benchmark_sample
from manga_editor.ocr.base import OcrRequest, OcrResult
from manga_editor.ocr.benchmark import (
    character_error_rate,
    compact_character_error_rate,
    load_manifest,
    omitted_truth_lines,
    reading_order_score,
    run_benchmark,
)
from manga_editor.ocr.layout import segment_vertical_columns
from manga_editor.ocr.pipeline import OcrPipeline
from manga_editor.ocr.preprocess import prepare_image
from manga_editor.ocr.quality import analyze_suspicions

APP = QApplication.instance() or QApplication([])


def png_bytes(width=120, height=80):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class FakeEngine:
    def __init__(self, name, result=None, error=None, available=True):
        self.name = name
        self.result = result
        self.error = error
        self.available = available
        self.calls = 0

    def is_available(self):
        return self.available

    def recognize(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        if callable(self.result):
            return self.result(request)
        return self.result


class FakeRegistry:
    def __init__(self, tesseract, mangaocr):
        self.engines = {
            "tesseract": tesseract,
            "mangaocr": mangaocr,
        }

    def get(self, key):
        return self.engines[key]

    def availability(self):
        return {
            key: engine.is_available()
            for key, engine in self.engines.items()
        }


class FakeBenchmarkPipeline:
    def recognize(self, request):
        return OcrResult(
            text="本当",
            engine="fake",
            language=request.language,
            layout=request.layout,
            confidence=None,
            metadata={"suspicions": []},
        )


class OcrV04Tests(unittest.TestCase):
    def test_preprocess_profiles_keep_raw_separate(self):
        raw = png_bytes(20, 10)

        original = prepare_image(raw, "original")
        upscale = prepare_image(raw, "upscale2x")
        contrast = prepare_image(raw, "contrast")
        clean = prepare_image(raw, "manga_clean")

        self.assertEqual(
            (original.image.width(), original.image.height()),
            (20, 10),
        )
        self.assertEqual(
            (upscale.image.width(), upscale.image.height()),
            (40, 20),
        )
        self.assertEqual(
            (contrast.image.width(), contrast.image.height()),
            (20, 10),
        )
        self.assertEqual(
            (clean.image.width(), clean.image.height()),
            (72, 52),
        )
        self.assertEqual(
            QImage.fromData(raw).size(),
            QImage.fromData(original.png_bytes).size(),
        )

    def test_vertical_columns_are_returned_right_to_left(self):
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        try:
            painter.fillRect(QRect(18, 5, 16, 70), QColor("black"))
            painter.fillRect(QRect(82, 5, 16, 70), QColor("black"))
        finally:
            painter.end()

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        segments = segment_vertical_columns(bytes(buffer.data()))

        self.assertEqual(len(segments), 2)
        self.assertGreater(segments[0].x, segments[1].x)

    def test_quality_warns_when_japanese_expected_but_missing(self):
        result = OcrResult(
            text="ABC",
            engine="tesseract",
            language="ja",
            layout="vertical",
            confidence=0.3,
            metadata={},
        )
        issues = analyze_suspicions(
            result, language="ja", layout="vertical"
        )
        self.assertTrue(
            any("không có ký tự Nhật" in issue for issue in issues)
        )
        self.assertTrue(
            any("Confidence Tesseract thấp" in issue for issue in issues)
        )

    def test_auto_fallback_only_after_empty_primary_result(self):
        tesseract = FakeEngine(
            "tesseract",
            OcrResult(
                text="",
                engine="tesseract",
                language="ja",
                layout="auto",
            ),
        )
        mangaocr = FakeEngine(
            "mangaocr",
            OcrResult(
                text="本当？",
                engine="mangaocr",
                language="ja",
                layout="auto",
            ),
        )
        pipeline = OcrPipeline(FakeRegistry(tesseract, mangaocr))

        result = pipeline.recognize(
            OcrRequest(
                png_bytes(),
                "ja",
                "auto",
                {"engine": "auto", "preprocess": "original"},
            )
        )

        self.assertEqual(result.engine, "mangaocr")
        self.assertEqual(result.text, "本当？")
        self.assertEqual(tesseract.calls, 1)
        self.assertEqual(mangaocr.calls, 1)
        self.assertIn("Fallback", result.warning)

    def test_auto_does_not_replace_nonempty_result_by_cross_engine_confidence(self):
        tesseract = FakeEngine(
            "tesseract",
            OcrResult(
                text="A",
                engine="tesseract",
                language="ja",
                layout="auto",
                confidence=0.1,
            ),
        )
        mangaocr = FakeEngine(
            "mangaocr",
            OcrResult(
                text="本当？",
                engine="mangaocr",
                language="ja",
                layout="auto",
            ),
        )
        pipeline = OcrPipeline(FakeRegistry(tesseract, mangaocr))

        result = pipeline.recognize(
            OcrRequest(
                png_bytes(),
                "ja",
                "auto",
                {"engine": "auto", "preprocess": "original"},
            )
        )

        self.assertEqual(result.engine, "tesseract")
        self.assertEqual(mangaocr.calls, 0)
        self.assertTrue(result.metadata["suspicions"])

    def test_benchmark_metrics_measure_errors_and_omissions(self):
        self.assertAlmostEqual(
            character_error_rate("abc", "adc"), 1 / 3
        )
        self.assertEqual(
            compact_character_error_rate("a b\nc", "abc"), 0.0
        )
        self.assertEqual(
            omitted_truth_lines("一行目\n二行目", "一行目"), 1
        )
        self.assertEqual(
            reading_order_score("右\n左", "右左"), 1.0
        )
        self.assertEqual(
            reading_order_score("右\n左", "左右"), 0.0
        )

    def test_dataset_writer_and_benchmark_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            sample_id = add_benchmark_sample(
                directory,
                image_png=png_bytes(),
                truth="本当",
                language="ja",
                layout="vertical",
                tags=["vertical", "clean"],
                source={"region_id": "region_x"},
            )

            samples = load_manifest(directory)
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0].id, sample_id)
            self.assertEqual(samples[0].truth, "本当")

            report = run_benchmark(
                directory,
                engine="auto",
                preprocess="original",
                pipeline=FakeBenchmarkPipeline(),
            )

        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(report["success_count"], 1)
        self.assertEqual(report["mean_cer"], 0.0)
        self.assertEqual(report["mean_reading_order_score"], 1.0)
        self.assertEqual(report["failure_count"], 0)
        self.assertIn("language:ja", report["groups"])
        self.assertIn("layout:vertical", report["groups"])
        self.assertIn("tag:clean", report["groups"])
        self.assertEqual(report["results"][0]["engine"], "fake")


if __name__ == "__main__":
    unittest.main()
