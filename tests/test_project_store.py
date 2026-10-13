import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from manga_editor.application.session import ProjectSession
from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import MangaProject
from manga_editor.infrastructure.project_store import ProjectStore


class ProjectStoreTests(unittest.TestCase):
    def test_round_trip_preserves_raw_ids_and_geometry(self):
        session = ProjectSession(MangaProject.create("Round trip"))
        page_id = session.add_page("raw.png", b"immutable-raw", 800, 1200)
        region_id = session.add_region(page_id)
        session.set_region_area(page_id, region_id, "ocr_area", Rect(10, 20, 100, 200))
        session.set_region_area(page_id, region_id, "cleanup_area", Rect(30, 40, 50, 60))
        session.set_region_area(page_id, region_id, "text_frame", Rect(5, 6, 150, 240))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.mep"
            ProjectStore.save(path, session.project, session.assets)
            loaded, assets = ProjectStore.load(path)

        self.assertEqual(loaded.id, session.project.id)
        page = loaded.page(page_id)
        self.assertEqual(page.region(region_id).ocr_area, Rect(10, 20, 100, 200))
        self.assertEqual(page.region(region_id).cleanup_area, Rect(30, 40, 50, 60))
        self.assertEqual(page.region(region_id).text_frame, Rect(5, 6, 150, 240))
        self.assertEqual(assets[page.raw_asset], b"immutable-raw")

    def test_format_version_is_in_manifest(self):
        session = ProjectSession(MangaProject.create("Version"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.mep"
            ProjectStore.save(path, session.project, session.assets)
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("project.json"))
        self.assertEqual(manifest["format_version"], 1)

    def test_raw_tampering_is_detected(self):
        session = ProjectSession(MangaProject.create("Checksum"))
        page_id = session.add_page("raw.png", b"original", 10, 10)
        page = session.project.page(page_id)
        session.assets[page.raw_asset] = b"changed"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.mep"
            with self.assertRaisesRegex(ValueError, "checksum"):
                ProjectStore.save(path, session.project, session.assets)


if __name__ == "__main__":
    unittest.main()
