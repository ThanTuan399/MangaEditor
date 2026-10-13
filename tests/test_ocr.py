import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from manga_editor.domain.geometry import Rect
from manga_editor.infrastructure.ocr_crop import crop_raw_to_png
from manga_editor.ocr import OcrEngineError, OcrRequest, OcrResult, TesseractEngine
from manga_editor.presentation.ocr_task import OcrTarget, OcrTask

APP = QApplication.instance() or QApplication([])


class FakeEngine:
    name = "fake"

    def recognize(self, request):
        return OcrResult(
            text="テスト",
            engine="fake",
            language=request.language,
            layout=request.layout,
            confidence=0.75,
        )


class OcrTests(unittest.TestCase):
    def test_crop_uses_original_image_coordinates(self):
        image = QImage(100, 80, QImage.Format.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.png"
            image.save(str(path))
            crop = crop_raw_to_png(
                path.read_bytes(), Rect(10, 20, 30, 25)
            )
        self.assertEqual(crop.image.width(), 30)
        self.assertEqual(crop.image.height(), 25)
        self.assertTrue(crop.png_bytes.startswith(b"\x89PNG"))

    def test_background_task_returns_target_and_result(self):
        request = OcrRequest(
            image_bytes=b"fake",
            language="ja",
            layout="vertical",
        )
        target = OcrTarget("page_a", "region_b", 7)
        task = OcrTask(FakeEngine(), request, target)
        loop = QEventLoop()
        holder = {}

        def completed(received_target, result):
            holder["target"] = received_target
            holder["result"] = result
            loop.quit()

        def failed(received_target, message):
            holder["error"] = (received_target, message)
            loop.quit()

        task.completed.connect(completed)
        task.failed.connect(failed)
        task.start()
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        task.wait()

        self.assertNotIn("error", holder)
        self.assertEqual(holder["target"], target)
        self.assertEqual(holder["result"].text, "テスト")
        self.assertEqual(holder["result"].confidence, 0.75)

    def test_tesseract_missing_executable_has_clear_error(self):
        engine = TesseractEngine(
            executable="/definitely/missing/tesseract"
        )
        with self.assertRaisesRegex(
            OcrEngineError, "Không tìm thấy Tesseract"
        ):
            engine.recognize(
                OcrRequest(b"fake", "ja", "auto")
            )

    def test_tesseract_confidence_parser(self):
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
            "\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t80\tA\n"
            "5\t1\t1\t1\t1\t2\t10\t0\t10\t10\t60\tB\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.tsv"
            path.write_text(tsv, encoding="utf-8")
            confidence = TesseractEngine._confidence_from_tsv(path)
        self.assertAlmostEqual(confidence, 0.70, places=5)


if __name__ == "__main__":
    unittest.main()
