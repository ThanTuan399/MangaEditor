import unittest

from manga_editor.application.session import ProjectSession
from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import MangaProject


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.session = ProjectSession(MangaProject.create("Kiểm thử"))
        self.page_id = self.session.add_page("page.png", b"raw-image-bytes", 1000, 1600)

    def test_region_id_is_stable_and_not_based_on_order_or_name(self):
        first = self.session.add_region(self.page_id)
        second = self.session.add_region(self.page_id)
        self.session.rename_region(self.page_id, first, "Lời thoại chính")
        page = self.session.project.page(self.page_id)
        page.region(first).order = 99
        self.assertEqual(page.region(first).id, first)
        self.assertNotEqual(first, second)

    def test_three_areas_are_independent(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(self.page_id, region_id, "ocr_area", Rect(10, 20, 200, 300))
        self.session.set_region_area(self.page_id, region_id, "cleanup_area", Rect(30, 50, 80, 120))
        self.session.set_region_area(self.page_id, region_id, "text_frame", Rect(5, 10, 250, 330))
        region = self.session.project.page(self.page_id).region(region_id)
        self.assertNotEqual(region.ocr_area, region.cleanup_area)
        self.assertNotEqual(region.cleanup_area, region.text_frame)
        self.assertEqual(region.ocr_area, Rect(10, 20, 200, 300))

    def test_area_is_clamped_to_original_image_coordinates(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(self.page_id, region_id, "ocr_area", Rect(-20, -10, 1200, 1800))
        region = self.session.project.page(self.page_id).region(region_id)
        self.assertEqual(region.ocr_area, Rect(0, 0, 1000, 1600))

    def test_undo_and_redo_use_one_session_history(self):
        region_id = self.session.add_region(self.page_id)
        self.assertIsNotNone(self.session.project.page(self.page_id).region(region_id))
        self.assertTrue(self.session.undo())
        self.assertEqual(self.session.project.page(self.page_id).regions, [])
        self.assertTrue(self.session.redo())
        self.assertEqual(self.session.project.page(self.page_id).regions[0].id, region_id)


if __name__ == "__main__":
    unittest.main()
