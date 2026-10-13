import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from manga_editor.application.session import ProjectSession
from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import MangaProject
from manga_editor.infrastructure.renderer import render_page, save_rendered_page

APP = QApplication.instance() or QApplication([])


def png_bytes(width=120, height=80, color=0xFFFFFFFF):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(color)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class RendererTests(unittest.TestCase):
    def test_patch_is_rendered_without_mutating_raw(self):
        raw = png_bytes()
        session = ProjectSession(MangaProject.create("Render"))
        page_id = session.add_page("raw.png", raw, 120, 80)
        region_id = session.add_region(page_id)
        session.set_region_area(page_id, region_id, "cleanup_area", Rect(10, 10, 30, 20))
        session.set_background_patch(page_id, region_id, "#000000")

        page = session.project.page(page_id)
        rendered = render_page(page, session.assets[page.raw_asset])

        self.assertEqual(rendered.width(), 120)
        self.assertEqual(rendered.height(), 80)
        self.assertEqual(rendered.pixelColor(15, 15).name(), "#000000")
        self.assertEqual(session.assets[page.raw_asset], raw)

    def test_export_keeps_original_dimensions(self):
        raw = png_bytes(90, 140)
        session = ProjectSession(MangaProject.create("Export"))
        page_id = session.add_page("raw.png", raw, 90, 140)
        page = session.project.page(page_id)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.png"
            self.assertTrue(save_rendered_page(page, raw, str(path)))
            saved = QImage(str(path))

        self.assertEqual(saved.width(), 90)
        self.assertEqual(saved.height(), 140)


if __name__ == "__main__":
    unittest.main()
