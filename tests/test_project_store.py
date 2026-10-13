import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from manga_editor.application.session import ProjectSession
from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import LayerKind, MangaProject, WorkState
from manga_editor.infrastructure.project_store import ProjectStore


class ProjectStoreTests(unittest.TestCase):
    def test_round_trip_preserves_regions_layers_and_multiple_parts(self):
        session = ProjectSession(MangaProject.create("Round trip"))
        page_id = session.add_page(
            "raw.png", b"immutable-raw", 800, 1200
        )
        region_id = session.add_region(page_id)
        session.set_region_area(
            page_id, region_id, "ocr_area",
            Rect(10, 20, 100, 200),
        )
        session.add_cleanup_part(
            page_id, region_id, Rect(30, 40, 50, 60)
        )
        session.add_cleanup_part(
            page_id, region_id, Rect(130, 140, 25, 30)
        )
        session.set_region_area(
            page_id, region_id, "text_frame",
            Rect(5, 6, 150, 240),
        )
        session.set_background_patch(
            page_id, region_id, "#fff4dc"
        )
        session.set_vietnamese_text(
            page_id,
            region_id,
            "Bản dịch tiếng Việt",
            "Arial",
            30,
            "center",
            "#111111",
        )
        session.set_region_state(
            page_id, region_id, "cleanup",
            WorkState.REVIEWED,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.mep"
            ProjectStore.save(
                path, session.project, session.assets
            )
            loaded, assets = ProjectStore.load(path)

        self.assertEqual(loaded.id, session.project.id)
        page = loaded.page(page_id)
        region = page.region(region_id)
        self.assertEqual(
            region.ocr_area, Rect(10, 20, 100, 200)
        )
        self.assertEqual(
            region.cleanup_parts,
            [
                Rect(30, 40, 50, 60),
                Rect(130, 140, 25, 30),
            ],
        )
        self.assertEqual(
            region.text_frame, Rect(5, 6, 150, 240)
        )
        self.assertEqual(
            region.cleanup_state, WorkState.REVIEWED
        )

        patch = page.layer_for_region(
            region_id, LayerKind.BACKGROUND_PATCH
        )
        text = page.layer_for_region(
            region_id, LayerKind.VIETNAMESE_TEXT
        )
        self.assertIsNotNone(patch)
        self.assertIsNotNone(text)
        self.assertEqual(
            len(patch.payload["parts"]), 2
        )
        self.assertTrue(
            all(
                part["color"] == "#fff4dc"
                for part in patch.payload["parts"]
            )
        )
        self.assertEqual(
            text.payload["content"],
            "Bản dịch tiếng Việt",
        )
        self.assertEqual(text.payload["size"], 30)
        self.assertEqual(
            assets[page.raw_asset],
            b"immutable-raw",
        )

    def test_format_version_is_in_manifest(self):
        session = ProjectSession(
            MangaProject.create("Version")
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.mep"
            ProjectStore.save(
                path, session.project, session.assets
            )
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(
                    archive.read("project.json")
                )
        self.assertEqual(manifest["format_version"], 2)

    def test_v1_project_is_migrated_to_v2(self):
        raw = b"legacy-raw"
        digest = hashlib.sha256(raw).hexdigest()
        manifest = {
            "format_version": 1,
            "id": "project_old",
            "name": "Legacy",
            "settings": {"default_language": "ja"},
            "pages": [
                {
                    "id": "page_old",
                    "name": "old.png",
                    "raw_asset": "assets/pages/page_old/original.png",
                    "raw_sha256": digest,
                    "width": 100,
                    "height": 200,
                    "regions": [
                        {
                            "id": "region_old",
                            "name": "Vùng 01",
                            "order": 0,
                            "content_type": "dialogue",
                            "ocr_area": None,
                            "cleanup_area": {
                                "x": 10,
                                "y": 20,
                                "width": 30,
                                "height": 40,
                            },
                            "text_frame": {
                                "x": 5,
                                "y": 6,
                                "width": 50,
                                "height": 60,
                            },
                            "revision": 0,
                        }
                    ],
                    "layers": [
                        {
                            "id": "source",
                            "kind": "source",
                            "name": "Ảnh gốc",
                            "visible": True,
                            "locked": True,
                            "region_id": None,
                            "payload": {},
                        },
                        {
                            "id": "patch",
                            "kind": "background_patch",
                            "name": "Bản vá nền",
                            "visible": True,
                            "locked": False,
                            "region_id": "region_old",
                            "payload": {
                                "rect": {
                                    "x": 10,
                                    "y": 20,
                                    "width": 30,
                                    "height": 40,
                                },
                                "color": "#ffffff",
                            },
                        },
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.mep"
            with zipfile.ZipFile(
                path, "w", zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr(
                    "project.json",
                    json.dumps(
                        manifest, ensure_ascii=False
                    ).encode("utf-8"),
                )
                archive.writestr(
                    "assets/pages/page_old/original.png",
                    raw,
                )

            loaded, _ = ProjectStore.load(path)

        self.assertEqual(loaded.format_version, 2)
        region = loaded.page("page_old").region(
            "region_old"
        )
        self.assertEqual(
            region.cleanup_parts,
            [Rect(10, 20, 30, 40)],
        )
        patch = loaded.page("page_old").layer(
            "patch"
        )
        self.assertEqual(
            patch.payload["parts"][0]["color"],
            "#ffffff",
        )

    def test_raw_tampering_is_detected(self):
        session = ProjectSession(
            MangaProject.create("Checksum")
        )
        page_id = session.add_page(
            "raw.png", b"original", 10, 10
        )
        page = session.project.page(page_id)
        session.assets[page.raw_asset] = b"changed"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.mep"
            with self.assertRaisesRegex(
                ValueError, "checksum"
            ):
                ProjectStore.save(
                    path, session.project, session.assets
                )


if __name__ == "__main__":
    unittest.main()
