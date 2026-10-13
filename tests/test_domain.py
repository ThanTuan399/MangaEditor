import unittest

from manga_editor.application.session import ProjectSession
from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import LayerKind, MangaProject, WorkState


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.session = ProjectSession(MangaProject.create("Kiểm thử"))
        self.page_id = self.session.add_page(
            "page.png", b"raw-image-bytes", 1000, 1600
        )

    def test_region_id_is_stable_and_not_based_on_order_or_name(self):
        first = self.session.add_region(self.page_id)
        second = self.session.add_region(self.page_id)
        self.session.rename_region(
            self.page_id, first, "Lời thoại chính"
        )
        self.session.move_region(self.page_id, second, -1)
        page = self.session.project.page(self.page_id)
        self.assertEqual(page.region(first).id, first)
        self.assertEqual(page.region(second).id, second)
        self.assertNotEqual(first, second)

    def test_three_areas_are_independent(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, region_id, "ocr_area",
            Rect(10, 20, 200, 300),
        )
        self.session.set_region_area(
            self.page_id, region_id, "cleanup_area",
            Rect(30, 50, 80, 120),
        )
        self.session.set_region_area(
            self.page_id, region_id, "text_frame",
            Rect(5, 10, 250, 330),
        )
        region = self.session.project.page(self.page_id).region(region_id)
        self.assertNotEqual(region.ocr_area, region.cleanup_area)
        self.assertNotEqual(region.cleanup_area, region.text_frame)
        self.assertEqual(region.ocr_area, Rect(10, 20, 200, 300))

    def test_one_region_can_have_disconnected_cleanup_parts(self):
        region_id = self.session.add_region(self.page_id)
        first = Rect(10, 20, 30, 40)
        second = Rect(400, 500, 60, 70)
        self.session.add_cleanup_part(
            self.page_id, region_id, first
        )
        self.session.add_cleanup_part(
            self.page_id, region_id, second
        )
        region = self.session.project.page(self.page_id).region(region_id)
        self.assertEqual(region.cleanup_parts, [first, second])
        self.assertEqual(
            region.cleanup_area,
            Rect(10, 20, 450, 550),
        )

    def test_adjacent_regions_never_merge_implicitly(self):
        first = self.session.create_region_with_cleanup_part(
            self.page_id, Rect(10, 10, 100, 100)
        )
        second = self.session.create_region_with_cleanup_part(
            self.page_id, Rect(110, 10, 100, 100)
        )
        page = self.session.project.page(self.page_id)
        self.assertEqual(len(page.regions), 2)
        self.assertNotEqual(first, second)

    def test_split_moves_only_selected_part_to_new_region(self):
        source = self.session.add_region(self.page_id)
        self.session.add_cleanup_part(
            self.page_id, source, Rect(10, 10, 50, 50)
        )
        moved = Rect(200, 200, 60, 60)
        self.session.add_cleanup_part(
            self.page_id, source, moved
        )
        self.session.set_background_patch(
            self.page_id, source, "#ffffff"
        )

        new_id = self.session.split_cleanup_part(
            self.page_id, source, 1
        )
        page = self.session.project.page(self.page_id)
        self.assertEqual(
            page.region(source).cleanup_parts,
            [Rect(10, 10, 50, 50)],
        )
        self.assertEqual(
            page.region(new_id).cleanup_parts,
            [moved],
        )
        self.assertNotEqual(source, new_id)
        self.assertIsNotNone(
            page.layer_for_region(
                new_id, LayerKind.BACKGROUND_PATCH
            )
        )

    def test_merge_keeps_target_id_and_explicit_text_policy(self):
        target = self.session.add_region(self.page_id)
        source = self.session.add_region(self.page_id)

        self.session.add_cleanup_part(
            self.page_id, target, Rect(10, 10, 50, 50)
        )
        self.session.add_cleanup_part(
            self.page_id, source, Rect(100, 10, 50, 50)
        )
        self.session.set_region_area(
            self.page_id, target, "text_frame",
            Rect(10, 100, 100, 80),
        )
        self.session.set_region_area(
            self.page_id, source, "text_frame",
            Rect(150, 100, 100, 80),
        )
        self.session.set_vietnamese_text(
            self.page_id, target, "A", "Arial", 20
        )
        self.session.set_vietnamese_text(
            self.page_id, source, "B", "Arial", 20
        )

        returned = self.session.merge_regions(
            self.page_id, target, source, "append"
        )
        page = self.session.project.page(self.page_id)
        self.assertEqual(returned, target)
        self.assertEqual(len(page.regions), 1)
        self.assertEqual(page.regions[0].id, target)
        text = page.layer_for_region(
            target, LayerKind.VIETNAMESE_TEXT
        )
        self.assertEqual(text.payload["content"], "A\nB")

    def test_region_states_are_independent(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_state(
            self.page_id, region_id, "cleanup",
            WorkState.REVIEWED,
        )
        region = self.session.project.page(self.page_id).region(region_id)
        self.assertEqual(
            region.cleanup_state, WorkState.REVIEWED
        )
        self.assertEqual(
            region.text_state, WorkState.NOT_STARTED
        )
        self.assertEqual(
            region.ocr_state, WorkState.NOT_STARTED
        )

    def test_area_is_clamped_to_original_image_coordinates(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, region_id, "ocr_area",
            Rect(-20, -10, 1200, 1800),
        )
        region = self.session.project.page(self.page_id).region(region_id)
        self.assertEqual(
            region.ocr_area, Rect(0, 0, 1000, 1600)
        )

    def test_undo_and_redo_use_one_session_history(self):
        region_id = self.session.add_region(self.page_id)
        self.assertIsNotNone(
            self.session.project.page(
                self.page_id
            ).region(region_id)
        )
        self.assertTrue(self.session.undo())
        self.assertEqual(
            self.session.project.page(self.page_id).regions,
            [],
        )
        self.assertTrue(self.session.redo())
        self.assertEqual(
            self.session.project.page(
                self.page_id
            ).regions[0].id,
            region_id,
        )

    def test_patch_and_text_are_separate_editable_layers(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, region_id, "cleanup_area",
            Rect(20, 30, 200, 120),
        )
        self.session.set_region_area(
            self.page_id, region_id, "text_frame",
            Rect(30, 40, 180, 100),
        )
        patch_id = self.session.set_background_patch(
            self.page_id, region_id, "#ffffff"
        )
        text_id = self.session.set_vietnamese_text(
            self.page_id,
            region_id,
            "Xin chào",
            "Arial",
            28,
            "center",
            "#000000",
        )

        page = self.session.project.page(self.page_id)
        patch = page.layer(patch_id)
        text = page.layer(text_id)
        self.assertEqual(
            patch.kind, LayerKind.BACKGROUND_PATCH
        )
        self.assertEqual(
            text.kind, LayerKind.VIETNAMESE_TEXT
        )
        self.assertEqual(
            text.payload["content"], "Xin chào"
        )
        self.assertEqual(patch.region_id, region_id)
        self.assertEqual(text.region_id, region_id)

    def test_layer_visibility_is_undoable(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, region_id, "cleanup_area",
            Rect(20, 30, 200, 120),
        )
        layer_id = self.session.set_background_patch(
            self.page_id, region_id, "#ffffff"
        )
        self.session.set_layer_visibility(
            self.page_id, layer_id, False
        )
        self.assertFalse(
            self.session.project.page(
                self.page_id
            ).layer(layer_id).visible
        )
        self.assertTrue(self.session.undo())
        self.assertTrue(
            self.session.project.page(
                self.page_id
            ).layer(layer_id).visible
        )

    def test_deleting_region_also_deletes_its_layers(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, region_id, "cleanup_area",
            Rect(20, 30, 200, 120),
        )
        self.session.set_background_patch(
            self.page_id, region_id
        )
        self.session.delete_region(
            self.page_id, region_id
        )
        page = self.session.project.page(self.page_id)
        self.assertFalse(
            any(
                layer.region_id == region_id
                for layer in page.layers
            )
        )


    def test_ocr_machine_and_edited_text_are_separate(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, region_id, "ocr_area", Rect(10, 20, 300, 120)
        )
        region = self.session.project.page(self.page_id).region(region_id)
        revision = region.ocr_input_revision

        self.assertTrue(
            self.session.apply_ocr_result(
                self.page_id,
                region_id,
                revision,
                "機械の結果",
                "fake",
                confidence=0.9,
            )
        )
        self.session.set_ocr_edited_text(
            self.page_id, region_id, "人が直した結果", reviewed=True
        )

        region = self.session.project.page(self.page_id).region(region_id)
        self.assertEqual(region.ocr_machine_text, "機械の結果")
        self.assertEqual(region.ocr_edited_text, "人が直した結果")
        self.assertEqual(region.source_text, "人が直した結果")
        self.assertEqual(region.ocr_state, WorkState.REVIEWED)

    def test_stale_ocr_result_is_rejected_after_input_changes(self):
        region_id = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, region_id, "ocr_area", Rect(10, 20, 300, 120)
        )
        region = self.session.project.page(self.page_id).region(region_id)
        old_revision = region.ocr_input_revision

        self.session.set_ocr_settings(
            self.page_id, region_id, "ja", "vertical"
        )
        self.assertNotEqual(
            self.session.project.page(self.page_id)
            .region(region_id)
            .ocr_input_revision,
            old_revision,
        )

        accepted = self.session.apply_ocr_result(
            self.page_id,
            region_id,
            old_revision,
            "Kết quả đã cũ",
            "fake",
        )
        self.assertFalse(accepted)
        self.assertEqual(
            self.session.project.page(self.page_id)
            .region(region_id)
            .ocr_machine_text,
            "",
        )

    def test_ocr_result_is_written_to_target_region_only(self):
        first = self.session.add_region(self.page_id)
        second = self.session.add_region(self.page_id)
        self.session.set_region_area(
            self.page_id, first, "ocr_area", Rect(10, 10, 100, 80)
        )
        self.session.set_region_area(
            self.page_id, second, "ocr_area", Rect(200, 10, 100, 80)
        )
        page = self.session.project.page(self.page_id)
        revision = page.region(first).ocr_input_revision

        self.assertTrue(
            self.session.apply_ocr_result(
                self.page_id, first, revision, "Vùng một", "fake"
            )
        )
        self.assertEqual(page.region(first).ocr_machine_text, "Vùng một")
        self.assertEqual(page.region(second).ocr_machine_text, "")


if __name__ == "__main__":
    unittest.main()
