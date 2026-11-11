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


def test_ocr_workspace_widget_constructs():
    """Catch Qt wiring/runtime errors that a plain import test cannot see."""
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from desktop_qt_ui.ui.main_page.pages.ocr_workspace_page import OCRWorkspacePanel

    class FakeState(QObject):
        is_translating_changed = pyqtSignal(bool)

    class FakeController(QObject):
        file_sources_changed = pyqtSignal()
        task_completed = pyqtSignal(list)

        def __init__(self):
            super().__init__()
            self.state_manager = FakeState()
            self.source_files = []

        def add_folder(self):
            pass

        def start_ocr_workspace_scan(self):
            pass

        def start_ocr_workspace_render(self):
            pass

        def add_files(self, _files):
            pass

        def get_last_open_dir(self):
            return "."

        def set_last_open_dir(self, _path):
            pass

    app = QApplication.instance() or QApplication([])
    controller = FakeController()
    panel = OCRWorkspacePanel(controller, t_func=lambda key, **k: key.format(**k))
    assert panel.splitter.count() == 2
    assert panel.table.columnCount() == 3
    assert panel.scan_button.isEnabled()
    panel.close()
    app.processEvents()



def test_workspace_scans_only_selected_folder(tmp_path):
    """Two registered folders must not be merged into one OCR scan."""
    from types import SimpleNamespace
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication

    first = tmp_path / "Chuong A"
    second = tmp_path / "Chuong B"
    first.mkdir()
    second.mkdir()
    (first / "001.jpg").write_bytes(b"image")
    (second / "002.jpg").write_bytes(b"image")

    class State(QObject):
        is_translating_changed = pyqtSignal(bool)
        def is_translating(self):
            return False

    class Controller(QObject):
        file_sources_changed = pyqtSignal()
        task_completed = pyqtSignal(list)

        def __init__(self):
            super().__init__()
            self.source_files = [str(first), str(second)]
            self.config_service = SimpleNamespace(root_dir=str(tmp_path / "app"))
            self.state_manager = State()
            self.scans = []

        def get_last_open_dir(self):
            return str(tmp_path)
        def set_last_open_dir(self, path):
            pass
        def start_ocr_workspace_scan(self, **kwargs):
            self.scans.append(kwargs)

    app = QApplication.instance() or QApplication([])
    controller = Controller()
    panel = OCRWorkspacePanel(controller, t_func=lambda key, **kwargs: key.format(**kwargs))
    panel._scan_project()
    assert controller.scans[-1]["project_root"] == str(second)
    assert controller.scans[-1]["project_images"] == [str(second / "002.jpg")]

    panel.projects.select(str(first))
    panel.refresh_sources()
    panel._scan_project()
    assert controller.scans[-1]["project_root"] == str(first)
    assert controller.scans[-1]["project_images"] == [str(first / "001.jpg")]
    panel.close()
    app.processEvents()


def test_workspace_render_cache_skips_unchanged_pages(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    import json
    from desktop_qt_ui.ui.main_page.pages import ocr_workspace_page as workspace

    root = tmp_path / "manga"
    root.mkdir()
    images = [root / "1.jpg", root / "2.jpg"]
    jsons = {}
    for image in images:
        image.write_bytes(b"image")
        sidecar = root / (image.stem + "_translations.json")
        sidecar.write_text(
            json.dumps({"page": {"regions": [{"text": "Hi", "translation": "Xin chào"}]}}),
            encoding="utf-8",
        )
        jsons[str(image)] = str(sidecar)
    monkeypatch.setattr(workspace, "find_json_path", lambda p: jsons.get(p))

    class State(QObject):
        is_translating_changed = pyqtSignal(bool)
        def is_translating(self):
            return False

    class Controller(QObject):
        file_sources_changed = pyqtSignal()
        task_completed = pyqtSignal(list)

        def __init__(self):
            super().__init__()
            self.source_files = [str(root)]
            self.state_manager = State()
            self.last_completed_workflow = "normal"
            self.config_service = SimpleNamespace(
                root_dir=str(tmp_path / "app"),
                get_config=lambda: SimpleNamespace(
                    model_dump=lambda: {
                        "render": {"font_size_offset": 0},
                        "translator": {"target_lang": "VIN"},
                        "cli": {"format": None, "save_quality": 100},
                    }
                ),
            )
            self.started = []
            self.saved_sources = {}

        def start_ocr_workspace_render(self, **kwargs):
            self.started.append(kwargs)
            self.last_completed_workflow = "ocr_workspace_render"
        def resolve_completed_source(self, path):
            return self.saved_sources[path]

    app = QApplication.instance() or QApplication([])
    controller = Controller()
    panel = OCRWorkspacePanel(controller, t_func=lambda key, **kwargs: key.format(**kwargs))
    panel._render_batch()
    assert len(controller.started) == 1
    assert len(controller.started[0]["project_images"]) == 2

    rendered = []
    for image in images:
        output = root / "manga_translator_work" / "ocr_workspace_output" / image.name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")
        controller.saved_sources[str(output)] = str(image)
        rendered.append(str(output))
    panel._on_task_completed(rendered)
    panel._render_batch()
    assert len(controller.started) == 1  # nothing changed

    sidecar = root / "1_translations.json"
    sidecar.write_text(
        json.dumps({"page": {"regions": [{"text": "Hi", "translation": "Chào bạn"}]}}),
        encoding="utf-8",
    )
    panel._render_batch()
    assert len(controller.started) == 2
    assert controller.started[-1]["project_images"] == [str(images[0])]
    panel.close()
    app.processEvents()
