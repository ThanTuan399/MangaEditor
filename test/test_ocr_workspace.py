from desktop_qt_ui.ui.main_page.pages.ocr_workspace_page import (
    OCRWorkspacePanel,
    _region_rect,
)


def test_ocr_workspace_marker_paste_parser():
    parsed = OCRWorkspacePanel._parse_batch_translation(
        "[001] Xin chào\n[002] Dòng thứ hai\ntiếp tục"
    )
    assert parsed == {
        0: "Xin chào",
        1: "Dòng thứ hai tiếp tục",
    }


def test_ocr_workspace_plain_line_paste_parser():
    parsed = OCRWorkspacePanel._parse_batch_translation(
        "Xin chào\nTạm biệt"
    )
    assert parsed == ["Xin chào", "Tạm biệt"]


def test_ocr_workspace_region_rect_from_saved_lines():
    region = {
        "lines": [
            [[10.0, 20.0], [40.0, 20.0], [40.0, 35.0], [10.0, 35.0]],
            [[12.0, 38.0], [55.0, 38.0], [55.0, 52.0], [12.0, 52.0]],
        ]
    }
    rect = _region_rect(region)
    assert rect is not None
    assert rect.x() == 10.0
    assert rect.y() == 20.0
    assert rect.width() == 45.0
    assert rect.height() == 32.0
