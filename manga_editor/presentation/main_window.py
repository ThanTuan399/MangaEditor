from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from manga_editor import APP_VERSION
from manga_editor.application.session import ProjectSession
from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import LayerKind, WorkState
from manga_editor.infrastructure.image_io import load_raw_image
from manga_editor.infrastructure.ocr_crop import crop_raw_to_png
from manga_editor.infrastructure.project_store import ProjectStore
from manga_editor.infrastructure.renderer import render_page, save_rendered_page
from manga_editor.ocr import OcrRequest, TesseractEngine
from .canvas import CanvasView
from .ocr_task import OcrTarget, OcrTask


STATE_LABELS = {
    WorkState.NOT_STARTED: "Chưa làm",
    WorkState.IN_PROGRESS: "Đang làm",
    WorkState.REVIEWED: "Đã duyệt",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MangaEditor v0.3 — {APP_VERSION}")
        self.resize(1540, 930)

        self.session = ProjectSession()
        self.project_path: Path | None = None
        self.current_page_id: str | None = None
        self.current_region_id: str | None = None

        self.text_color = "#000000"
        self.pending_draw_action = "set_area"
        self.editor_region_id: str | None = None
        self.editor_dirty = False
        self.ocr_editor_region_id: str | None = None
        self.ocr_editor_dirty = False
        self.ocr_engine = TesseractEngine()
        self.ocr_task: OcrTask | None = None
        self._syncing_ui = False

        self.canvas = CanvasView()
        self.canvas.areaDrawn.connect(self._area_drawn)
        self.canvas.regionSelected.connect(self._select_region_by_id)
        self.canvas.regionsHit.connect(self._choose_overlapping_region)

        self._build_ui()
        self._refresh_all()

    def _build_ui(self) -> None:
        toolbar = self.addToolBar("Project")
        toolbar.setMovable(False)
        for title, shortcut, slot in [
            ("Dự án mới", "Ctrl+N", self.new_project),
            ("Mở dự án", "Ctrl+O", self.open_project),
            ("Lưu dự án", "Ctrl+S", self.save_project),
            ("Nhập trang raw", "Ctrl+I", self.import_page),
            ("Xuất ảnh", "Ctrl+Shift+S", self.export_image),
            ("Hoàn tác", "Ctrl+Z", self.undo),
            ("Làm lại", "Ctrl+Y", self.redo),
            ("Vừa trang", "Ctrl+0", self.canvas.fit_page),
        ]:
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            toolbar.addAction(action)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Trang trong dự án"))
        self.pages = QListWidget()
        self.pages.currentRowChanged.connect(self._page_changed)
        left_layout.addWidget(self.pages)

        import_button = QPushButton("Nhập trang raw")
        import_button.clicked.connect(self.import_page)
        left_layout.addWidget(import_button)

        left_layout.addWidget(QLabel("Nội dung các vùng"))
        self.contents = QListWidget()
        self.contents.currentRowChanged.connect(self._content_region_changed)
        left_layout.addWidget(self.contents)
        left.setMinimumWidth(270)

        right_content = QWidget()
        right_layout = QVBoxLayout(right_content)

        project_box = QGroupBox("v0.3 — OCR theo Region")
        project_layout = QVBoxLayout(project_box)
        self.project_name = QLabel()
        project_layout.addWidget(self.project_name)
        note = QLabel(
            "OCR chỉ đọc Region người dùng chọn trước. Kết quả máy và bản đã sửa "
            "được lưu riêng; task nền luôn trả về đúng region_id + revision."
        )
        note.setWordWrap(True)
        project_layout.addWidget(note)
        right_layout.addWidget(project_box)

        region_box = QGroupBox("1. Region độc lập")
        region_layout = QVBoxLayout(region_box)

        create_row = QHBoxLayout()
        add_empty = QPushButton("Tạo vùng rỗng")
        add_empty.clicked.connect(self.add_region)
        create_on_image = QPushButton("Tạo vùng mới trên ảnh")
        create_on_image.clicked.connect(self.begin_create_region_on_image)
        create_row.addWidget(add_empty)
        create_row.addWidget(create_on_image)
        region_layout.addLayout(create_row)

        order_row = QHBoxLayout()
        move_up = QPushButton("↑ Lên")
        move_up.clicked.connect(lambda: self.move_region(-1))
        move_down = QPushButton("↓ Xuống")
        move_down.clicked.connect(lambda: self.move_region(1))
        merge = QPushButton("Gộp vùng…")
        merge.clicked.connect(self.merge_region)
        delete_region = QPushButton("Xóa vùng")
        delete_region.clicked.connect(self.delete_region)
        order_row.addWidget(move_up)
        order_row.addWidget(move_down)
        order_row.addWidget(merge)
        order_row.addWidget(delete_region)
        region_layout.addLayout(order_row)

        self.regions = QListWidget()
        self.regions.setMaximumHeight(150)
        self.regions.currentRowChanged.connect(self._region_changed)
        region_layout.addWidget(self.regions)

        form = QFormLayout()
        self.region_id = QLabel("—")
        self.region_id.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow("ID cố định", self.region_id)

        self.region_name = QLineEdit()
        self.region_name.editingFinished.connect(self.rename_region)
        form.addRow("Tên hiển thị", self.region_name)

        self.cleanup_state = self._state_combo()
        self.cleanup_state.currentIndexChanged.connect(
            lambda: self._state_changed("cleanup", self.cleanup_state)
        )
        form.addRow("Trạng thái nền", self.cleanup_state)

        self.text_state = self._state_combo()
        self.text_state.currentIndexChanged.connect(
            lambda: self._state_changed("text", self.text_state)
        )
        form.addRow("Trạng thái chữ", self.text_state)

        self.ocr_state = self._state_combo()
        self.ocr_state.currentIndexChanged.connect(
            lambda: self._state_changed("ocr", self.ocr_state)
        )
        form.addRow("Trạng thái OCR", self.ocr_state)
        region_layout.addLayout(form)

        self.area_combo = QComboBox()
        self.area_combo.addItem("Khung đặt chữ Việt", "text_frame")
        self.area_combo.addItem("Vùng đọc OCR", "ocr_area")
        self.area_combo.addItem(
            "Thay toàn bộ phạm vi xóa bằng 1 mảng", "cleanup_area"
        )
        draw_area = QPushButton("Vẽ / cập nhật phạm vi")
        draw_area.clicked.connect(self.begin_draw_area)

        area_row = QHBoxLayout()
        area_row.addWidget(self.area_combo)
        area_row.addWidget(draw_area)
        region_layout.addLayout(area_row)

        self.ocr_rect = QLabel("—")
        self.cleanup_rect = QLabel("—")
        self.text_rect = QLabel("—")
        rect_form = QFormLayout()
        rect_form.addRow("Khung bao OCR", self.ocr_rect)
        rect_form.addRow("Khung bao các mảng xóa", self.cleanup_rect)
        rect_form.addRow("Khung chữ Việt", self.text_rect)
        region_layout.addLayout(rect_form)

        region_layout.addWidget(QLabel("Các mảng xóa riêng của Region"))
        self.cleanup_parts = QListWidget()
        self.cleanup_parts.setMaximumHeight(110)
        region_layout.addWidget(self.cleanup_parts)

        part_row = QHBoxLayout()
        add_part = QPushButton("Thêm mảng vào vùng")
        add_part.clicked.connect(self.begin_add_cleanup_part)
        remove_part = QPushButton("Xóa mảng")
        remove_part.clicked.connect(self.remove_cleanup_part)
        split_part = QPushButton("Tách mảng → vùng mới")
        split_part.clicked.connect(self.split_cleanup_part)
        part_row.addWidget(add_part)
        part_row.addWidget(remove_part)
        part_row.addWidget(split_part)
        region_layout.addLayout(part_row)

        right_layout.addWidget(region_box)

        ocr_box = QGroupBox("2. OCR vùng đang chọn")
        ocr_layout = QVBoxLayout(ocr_box)

        ocr_form = QFormLayout()
        self.ocr_language = QComboBox()
        self.ocr_language.addItem("Tiếng Nhật", "ja")
        self.ocr_language.addItem("Tiếng Anh", "en")
        self.ocr_language.addItem("Tiếng Trung giản thể", "zh-Hans")
        self.ocr_language.addItem("Tiếng Trung phồn thể", "zh-Hant")
        self.ocr_language.addItem("Tiếng Hàn", "ko")
        self.ocr_language.addItem("Tiếng Việt", "vi")
        self.ocr_language.currentIndexChanged.connect(self._ocr_settings_changed)
        ocr_form.addRow("Ngôn ngữ", self.ocr_language)

        self.ocr_layout = QComboBox()
        self.ocr_layout.addItem("Tự động / khối chữ", "auto")
        self.ocr_layout.addItem("Chữ ngang", "horizontal")
        self.ocr_layout.addItem("Chữ dọc", "vertical")
        self.ocr_layout.currentIndexChanged.connect(self._ocr_settings_changed)
        ocr_form.addRow("Bố cục", self.ocr_layout)

        self.ocr_engine_label = QLabel()
        ocr_form.addRow("Bộ đọc", self.ocr_engine_label)
        ocr_layout.addLayout(ocr_form)

        self.ocr_preview = QLabel("Chưa có vùng OCR")
        self.ocr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ocr_preview.setMinimumHeight(160)
        self.ocr_preview.setStyleSheet(
            "QLabel { background:#171b22; border:1px solid #3b4350; }"
        )
        ocr_layout.addWidget(self.ocr_preview)

        scan_row = QHBoxLayout()
        self.scan_ocr_button = QPushButton("Quét Region đang chọn")
        self.scan_ocr_button.clicked.connect(self.scan_current_region)
        scan_row.addWidget(self.scan_ocr_button)
        self.ocr_progress = QProgressBar()
        self.ocr_progress.setRange(0, 0)
        self.ocr_progress.setVisible(False)
        scan_row.addWidget(self.ocr_progress)
        ocr_layout.addLayout(scan_row)

        self.ocr_status = QLabel("Chưa quét.")
        self.ocr_status.setWordWrap(True)
        ocr_layout.addWidget(self.ocr_status)

        ocr_layout.addWidget(QLabel("Kết quả OCR gốc — máy trả về"))
        self.ocr_machine_text = QTextEdit()
        self.ocr_machine_text.setReadOnly(True)
        self.ocr_machine_text.setFixedHeight(90)
        ocr_layout.addWidget(self.ocr_machine_text)

        ocr_layout.addWidget(QLabel("Văn bản đã sửa / xác nhận"))
        self.ocr_edited_text = QTextEdit()
        self.ocr_edited_text.setFixedHeight(100)
        self.ocr_edited_text.textChanged.connect(self._mark_ocr_editor_dirty)
        ocr_layout.addWidget(self.ocr_edited_text)

        ocr_buttons = QHBoxLayout()
        save_ocr = QPushButton("Lưu bản đã sửa")
        save_ocr.clicked.connect(lambda: self.save_ocr_edited(False))
        review_ocr = QPushButton("Lưu + đánh dấu đã duyệt")
        review_ocr.clicked.connect(lambda: self.save_ocr_edited(True))
        use_machine = QPushButton("Dùng lại kết quả máy")
        use_machine.clicked.connect(self.replace_edited_with_machine)
        copy_source = QPushButton("Sao chép chữ gốc")
        copy_source.clicked.connect(self.copy_source_text)
        ocr_buttons.addWidget(save_ocr)
        ocr_buttons.addWidget(review_ocr)
        ocr_buttons.addWidget(use_machine)
        ocr_buttons.addWidget(copy_source)
        ocr_layout.addLayout(ocr_buttons)

        right_layout.addWidget(ocr_box)

        patch_box = QGroupBox("3. Nền của Region")
        patch_layout = QVBoxLayout(patch_box)
        patch_note = QLabel(
            "Patch vẫn là layer riêng. Khi Region có nhiều mảng xóa, "
            "patch có thể phủ từng mảng nhưng vẫn thuộc đúng region_id."
        )
        patch_note.setWordWrap(True)
        patch_layout.addWidget(patch_note)

        patch_buttons = QHBoxLayout()
        white_button = QPushButton("Tô trắng")
        white_button.clicked.connect(self.apply_white_patch)
        color_button = QPushButton("Chọn màu nền")
        color_button.clicked.connect(self.apply_color_patch)
        remove_patch = QPushButton("Bỏ patch")
        remove_patch.clicked.connect(self.remove_patch)
        patch_buttons.addWidget(white_button)
        patch_buttons.addWidget(color_button)
        patch_buttons.addWidget(remove_patch)
        patch_layout.addLayout(patch_buttons)
        right_layout.addWidget(patch_box)

        text_box = QGroupBox("4. Nội dung tiếng Việt của Region")
        text_layout = QVBoxLayout(text_box)
        self.vn_text = QTextEdit()
        self.vn_text.setPlaceholderText(
            "Nội dung này chỉ thuộc Region đang chọn…"
        )
        self.vn_text.setFixedHeight(105)
        self.vn_text.textChanged.connect(self._mark_editor_dirty)
        text_layout.addWidget(self.vn_text)

        text_form = QFormLayout()
        self.font_family = QFontComboBox()
        self.font_family.currentFontChanged.connect(
            lambda *_: self._mark_editor_dirty()
        )
        text_form.addRow("Phông", self.font_family)

        self.font_size = QSpinBox()
        self.font_size.setRange(6, 300)
        self.font_size.setValue(32)
        self.font_size.setSuffix(" px")
        self.font_size.valueChanged.connect(
            lambda *_: self._mark_editor_dirty()
        )
        text_form.addRow("Cỡ chữ", self.font_size)

        self.text_align = QComboBox()
        self.text_align.addItem("Căn trái", "left")
        self.text_align.addItem("Căn giữa", "center")
        self.text_align.addItem("Căn phải", "right")
        self.text_align.setCurrentIndex(1)
        self.text_align.currentIndexChanged.connect(
            lambda *_: self._mark_editor_dirty()
        )
        text_form.addRow("Căn chữ", self.text_align)
        text_layout.addLayout(text_form)

        text_buttons = QHBoxLayout()
        apply_text = QPushButton("Áp dụng / cập nhật")
        apply_text.clicked.connect(self.apply_vietnamese_text)
        text_color_button = QPushButton("Màu chữ")
        text_color_button.clicked.connect(self.choose_text_color)
        remove_text = QPushButton("Bỏ lớp chữ")
        remove_text.clicked.connect(self.remove_text_layer)
        text_buttons.addWidget(apply_text)
        text_buttons.addWidget(text_color_button)
        text_buttons.addWidget(remove_text)
        text_layout.addLayout(text_buttons)
        right_layout.addWidget(text_box)

        layer_box = QGroupBox("5. Layer của trang")
        layer_layout = QVBoxLayout(layer_box)
        layer_note = QLabel(
            "Bỏ dấu ✓ để ẩn patch hoặc chữ. Ảnh gốc luôn khóa."
        )
        layer_note.setWordWrap(True)
        layer_layout.addWidget(layer_note)
        self.layers = QListWidget()
        self.layers.setMaximumHeight(130)
        self.layers.itemChanged.connect(self._layer_visibility_changed)
        layer_layout.addWidget(self.layers)
        right_layout.addWidget(layer_box)

        export_button = QPushButton("Xuất ảnh hoàn chỉnh")
        export_button.clicked.connect(self.export_image)
        right_layout.addWidget(export_button)
        right_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(right_content)
        scroll.setMinimumWidth(430)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.canvas)
        splitter.addWidget(scroll)
        splitter.setSizes([270, 820, 450])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(
            "v0.3: OCR chạy nền theo Region, giữ riêng kết quả máy và bản đã sửa."
        )

    @staticmethod
    def _state_combo() -> QComboBox:
        combo = QComboBox()
        combo.addItem("Chưa làm", WorkState.NOT_STARTED.value)
        combo.addItem("Đang làm", WorkState.IN_PROGRESS.value)
        combo.addItem("Đã duyệt", WorkState.REVIEWED.value)
        return combo

    def new_project(self) -> None:
        if not self._confirm_editor_changes():
            return
        if not self._confirm_discard():
            return
        name, ok = QInputDialog.getText(
            self, "Dự án mới", "Tên dự án:"
        )
        if not ok:
            return
        from manga_editor.domain.models import MangaProject

        self.session = ProjectSession(MangaProject.create(name))
        self.project_path = None
        self.current_page_id = None
        self.current_region_id = None
        self.editor_region_id = None
        self.editor_dirty = False
        self.ocr_editor_region_id = None
        self.ocr_editor_dirty = False
        self._refresh_all()

    def import_page(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn ảnh raw",
            "",
            "Ảnh (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
        )
        if not path:
            return
        try:
            raw = load_raw_image(path)
            page_id = self.session.add_page(
                raw.name, raw.data, raw.width, raw.height
            )
        except Exception as exc:
            self._error("Không nhập được ảnh", str(exc))
            return
        self.current_page_id = page_id
        self.current_region_id = None
        self._refresh_all(select_page_id=page_id)
        self.canvas.fit_page()

    def save_project(self) -> None:
        if not self._confirm_editor_changes():
            return
        if self.project_path is None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Lưu dự án",
                "manga-project.mep",
                "MangaEditor Project (*.mep)",
            )
            if not path:
                return
            self.project_path = Path(
                path if path.lower().endswith(".mep") else path + ".mep"
            )
        try:
            ProjectStore.save(
                self.project_path,
                self.session.project,
                self.session.assets,
            )
            self.session.dirty = False
            self.statusBar().showMessage(
                f"Đã lưu: {self.project_path}"
            )
        except Exception as exc:
            self._error("Không lưu được dự án", str(exc))

    def open_project(self) -> None:
        if not self._confirm_editor_changes():
            return
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở dự án", "", "MangaEditor Project (*.mep)"
        )
        if not path:
            return
        try:
            project, assets = ProjectStore.load(path)
        except Exception as exc:
            self._error("Không mở được dự án", str(exc))
            return

        self.session = ProjectSession(project, assets)
        self.project_path = Path(path)
        self.current_page_id = (
            project.pages[0].id if project.pages else None
        )
        self.current_region_id = None
        self.editor_region_id = None
        self.editor_dirty = False
        self.ocr_editor_region_id = None
        self.ocr_editor_dirty = False
        self._refresh_all(select_page_id=self.current_page_id)
        self.canvas.fit_page()

    def export_image(self) -> None:
        if not self._confirm_editor_changes():
            return
        page = self._current_page()
        if page is None:
            self._error(
                "Chưa có trang",
                "Chọn hoặc nhập một trang trước khi xuất.",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Xuất ảnh hoàn chỉnh",
            f"{Path(page.name).stem}-vi.png",
            "PNG (*.png);;JPEG (*.jpg *.jpeg)",
        )
        if not path:
            return
        try:
            raw = self.session.assets[page.raw_asset]
            if not save_rendered_page(page, raw, path):
                raise ValueError("Qt không ghi được ảnh đầu ra.")
        except Exception as exc:
            self._error("Không xuất được ảnh", str(exc))
            return
        self.statusBar().showMessage(
            f"Đã xuất {path} đúng kích thước "
            f"{page.width}×{page.height}."
        )

    def add_region(self) -> None:
        if self.current_page_id is None:
            self._error("Chưa có trang", "Nhập một ảnh raw trước.")
            return
        if not self._confirm_editor_changes():
            return
        region_id = self.session.add_region(self.current_page_id)
        self._switch_region(region_id, ask_editor=False)

    def begin_create_region_on_image(self) -> None:
        if self.current_page_id is None:
            self._error("Chưa có trang", "Nhập một ảnh raw trước.")
            return
        if not self._confirm_editor_changes():
            return
        self.pending_draw_action = "new_region_cleanup"
        self.canvas.set_draw_mode("cleanup_area")
        self.statusBar().showMessage(
            "Kéo một mảng xóa trên ảnh. App sẽ tạo Region mới có ID riêng."
        )

    def delete_region(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        if not self._confirm_editor_changes():
            return
        region = self._current_region()
        answer = QMessageBox.question(
            self,
            "Xóa Region",
            f"Xóa '{region.name}' cùng patch và chữ thuộc Region này?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.session.delete_region(
            self.current_page_id, self.current_region_id
        )
        self.current_region_id = None
        self.editor_region_id = None
        self.editor_dirty = False
        self.ocr_editor_region_id = None
        self.ocr_editor_dirty = False
        self._refresh_all(select_page_id=self.current_page_id)

    def rename_region(self) -> None:
        if (
            self._syncing_ui
            or self.current_page_id is None
            or self.current_region_id is None
        ):
            return
        self.session.rename_region(
            self.current_page_id,
            self.current_region_id,
            self.region_name.text(),
        )
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def move_region(self, direction: int) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        if self.session.move_region(
            self.current_page_id,
            self.current_region_id,
            direction,
        ):
            self._refresh_all(
                select_page_id=self.current_page_id,
                select_region_id=self.current_region_id,
            )

    def merge_region(self) -> None:
        page = self._current_page()
        target = self._current_region()
        if page is None or target is None:
            return
        if not self._confirm_editor_changes():
            return

        others = [
            region
            for region in sorted(page.regions, key=lambda x: x.order)
            if region.id != target.id
        ]
        if not others:
            self._error(
                "Không có vùng để gộp",
                "Trang cần ít nhất hai Region.",
            )
            return

        labels = [
            f"{region.order + 1:02d}. {region.name}"
            for region in others
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Gộp Region",
            f"Chọn Region sẽ gộp VÀO '{target.name}'. "
            "ID của vùng đang chọn sẽ được giữ:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        source = others[labels.index(choice)]

        target_text = page.layer_for_region(
            target.id, LayerKind.VIETNAMESE_TEXT
        )
        source_text = page.layer_for_region(
            source.id, LayerKind.VIETNAMESE_TEXT
        )
        policy = "keep_target"

        if target_text is not None and source_text is not None:
            policy_labels = [
                "Giữ chữ của vùng đang chọn",
                "Giữ chữ của vùng gộp vào",
                "Nối hai nội dung",
            ]
            policy_choice, ok = QInputDialog.getItem(
                self,
                "Quy tắc gộp chữ",
                "Cả hai Region đều có chữ Việt. Chọn cách xử lý:",
                policy_labels,
                0,
                False,
            )
            if not ok:
                return
            policy = {
                policy_labels[0]: "keep_target",
                policy_labels[1]: "keep_source",
                policy_labels[2]: "append",
            }[policy_choice]

        answer = QMessageBox.question(
            self,
            "Xác nhận gộp",
            f"Gộp '{source.name}' vào '{target.name}'?\n"
            "Region đích giữ nguyên ID; Region nguồn sẽ bị xóa.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.session.merge_regions(
            page.id,
            target.id,
            source.id,
            policy,
        )
        self._switch_region(target.id, ask_editor=False)

    def begin_draw_area(self) -> None:
        if self.current_region_id is None:
            self._error(
                "Chưa chọn vùng",
                "Tạo hoặc chọn Region trước khi vẽ phạm vi.",
            )
            return
        self.pending_draw_action = "set_area"
        self.canvas.set_draw_mode(self.area_combo.currentData())
        self.statusBar().showMessage(
            "Kéo chuột trên ảnh. Thao tác này chỉ cập nhật Region đang chọn."
        )

    def begin_add_cleanup_part(self) -> None:
        if self.current_region_id is None:
            self._error(
                "Chưa chọn vùng",
                "Chọn Region trước khi thêm mảng xóa.",
            )
            return
        self.pending_draw_action = "add_cleanup_part"
        self.canvas.set_draw_mode("cleanup_area")
        self.statusBar().showMessage(
            "Kéo thêm một mảng xóa. Mảng mới vẫn thuộc đúng Region đang chọn."
        )

    def _area_drawn(self, area_kind: str, rect: Rect) -> None:
        if self.current_page_id is None:
            return
        try:
            if self.pending_draw_action == "new_region_cleanup":
                region_id = self.session.create_region_with_cleanup_part(
                    self.current_page_id, rect
                )
                self.pending_draw_action = "set_area"
                self._switch_region(region_id, ask_editor=False)
                return

            if self.current_region_id is None:
                return

            if self.pending_draw_action == "add_cleanup_part":
                self.session.add_cleanup_part(
                    self.current_page_id,
                    self.current_region_id,
                    rect,
                )
            else:
                self.session.set_region_area(
                    self.current_page_id,
                    self.current_region_id,
                    area_kind,
                    rect,
                )
        except Exception as exc:
            self._error("Không cập nhật được Region", str(exc))
            return
        finally:
            self.pending_draw_action = "set_area"

        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def remove_cleanup_part(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        row = self.cleanup_parts.currentRow()
        if row < 0:
            self._error("Chưa chọn mảng", "Chọn một mảng xóa trong danh sách.")
            return
        self.session.remove_cleanup_part(
            self.current_page_id,
            self.current_region_id,
            row,
        )
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def split_cleanup_part(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        if not self._confirm_editor_changes():
            return
        row = self.cleanup_parts.currentRow()
        if row < 0:
            self._error(
                "Chưa chọn mảng",
                "Chọn mảng muốn chuyển sang Region mới.",
            )
            return
        try:
            new_id = self.session.split_cleanup_part(
                self.current_page_id,
                self.current_region_id,
                row,
            )
        except Exception as exc:
            self._error("Không tách được mảng", str(exc))
            return
        self._switch_region(new_id, ask_editor=False)

    def _ocr_settings_changed(self) -> None:
        if (
            self._syncing_ui
            or self.current_page_id is None
            or self.current_region_id is None
        ):
            return
        self.session.set_ocr_settings(
            self.current_page_id,
            self.current_region_id,
            self.ocr_language.currentData(),
            self.ocr_layout.currentData(),
        )
        self._refresh_region_form()
        self._load_ocr_editor()

    def scan_current_region(self) -> None:
        page = self._current_page()
        region = self._current_region()
        if page is None or region is None:
            self._error("Chưa chọn Region", "Chọn Region trước khi OCR.")
            return
        if self.ocr_task is not None and self.ocr_task.isRunning():
            self._error("OCR đang chạy", "Chờ tác vụ OCR hiện tại hoàn thành.")
            return
        if region.ocr_area is None:
            self._error(
                "Chưa có vùng OCR",
                "Chọn 'Vùng đọc OCR' rồi kéo khung trên ảnh trước.",
            )
            return
        if not self._confirm_ocr_editor_changes():
            return

        self.session.set_ocr_settings(
            page.id,
            region.id,
            self.ocr_language.currentData(),
            self.ocr_layout.currentData(),
        )
        region = page.region(region.id)

        try:
            crop = crop_raw_to_png(
                self.session.assets[page.raw_asset],
                region.ocr_area,
            )
        except Exception as exc:
            self._error("Không cắt được ảnh OCR", str(exc))
            return

        request = OcrRequest(
            image_bytes=crop.png_bytes,
            language=region.ocr_language,
            layout=region.ocr_layout,
        )
        target = OcrTarget(
            page_id=page.id,
            region_id=region.id,
            input_revision=region.ocr_input_revision,
        )

        task = OcrTask(self.ocr_engine, request, target)
        task.progress.connect(self._ocr_progress_message)
        task.completed.connect(self._ocr_completed)
        task.failed.connect(self._ocr_failed)
        task.finished.connect(self._ocr_thread_finished)
        self.ocr_task = task
        self._set_ocr_busy(True)
        self.ocr_status.setText(
            f"Đang quét {region.name} bằng Tesseract…"
        )
        task.start()

    def _ocr_progress_message(self, message: str) -> None:
        self.ocr_status.setText(message)
        self.statusBar().showMessage(message)

    def _ocr_completed(self, target: OcrTarget, result) -> None:
        accepted = self.session.apply_ocr_result(
            page_id=target.page_id,
            region_id=target.region_id,
            expected_input_revision=target.input_revision,
            machine_text=result.text,
            engine=result.engine,
            warning=result.warning,
            confidence=result.confidence,
            replace_edited=False,
        )
        if not accepted:
            self.statusBar().showMessage(
                "Đã bỏ kết quả OCR cũ vì Region bị xóa hoặc cấu hình OCR đã đổi."
            )
            return

        try:
            page = self.session.project.page(target.page_id)
            name = page.region(target.region_id).name
        except KeyError:
            name = target.region_id

        self.statusBar().showMessage(
            f"OCR xong cho {name}. Kết quả máy đã lưu riêng."
        )
        if (
            self.current_page_id == target.page_id
            and self.current_region_id == target.region_id
        ):
            self._refresh_region_form()
            self._load_ocr_editor()
            self._refresh_contents()

    def _ocr_failed(self, target: OcrTarget, message: str) -> None:
        self.statusBar().showMessage(
            f"OCR thất bại cho {target.region_id}: {message}"
        )
        if (
            self.current_page_id == target.page_id
            and self.current_region_id == target.region_id
        ):
            self.ocr_status.setText(f"Lỗi OCR: {message}")
        QMessageBox.warning(self, "OCR chưa thành công", message)

    def _ocr_thread_finished(self) -> None:
        task = self.ocr_task
        self.ocr_task = None
        self._set_ocr_busy(False)
        if task is not None:
            task.deleteLater()

    def _set_ocr_busy(self, busy: bool) -> None:
        self.scan_ocr_button.setEnabled(not busy)
        self.ocr_progress.setVisible(busy)

    def save_ocr_edited(self, reviewed: bool = False) -> None:
        if self.current_region_id is None:
            return
        if self._save_ocr_editor_to_region(
            self.current_region_id, reviewed=reviewed
        ):
            self._refresh_region_form()
            self._refresh_contents()
            self._load_ocr_editor()

    def _save_ocr_editor_to_region(
        self, region_id: str, reviewed: bool = False
    ) -> bool:
        if self.current_page_id is None:
            return False
        try:
            self.session.set_ocr_edited_text(
                self.current_page_id,
                region_id,
                self.ocr_edited_text.toPlainText(),
                reviewed=reviewed,
            )
        except Exception as exc:
            self._error("Không lưu được chữ OCR", str(exc))
            return False
        self.ocr_editor_region_id = region_id
        self.ocr_editor_dirty = False
        return True

    def replace_edited_with_machine(self) -> None:
        region = self._current_region()
        if region is None or not region.ocr_machine_text:
            self._error(
                "Chưa có kết quả máy",
                "Quét OCR Region này trước.",
            )
            return
        if (
            region.ocr_edited_text.strip()
            and region.ocr_edited_text != region.ocr_machine_text
        ):
            answer = QMessageBox.question(
                self,
                "Thay bản đã sửa?",
                "Thao tác này sẽ thay văn bản đã sửa bằng kết quả OCR máy. Tiếp tục?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.ocr_edited_text.setPlainText(region.ocr_machine_text)
        self.ocr_editor_dirty = True
        self.save_ocr_edited(False)

    def copy_source_text(self) -> None:
        region = self._current_region()
        if region is None:
            return
        text = region.source_text
        if not text:
            self._error(
                "Chưa có chữ gốc",
                "Region này chưa có kết quả OCR hoặc văn bản đã sửa.",
            )
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(
            f"Đã sao chép chữ gốc của {region.name}."
        )

    def _mark_ocr_editor_dirty(self) -> None:
        if self._syncing_ui or self.current_region_id is None:
            return
        self.ocr_editor_dirty = True

    def _load_ocr_editor(self) -> None:
        page = self._current_page()
        region = self._current_region()

        self._syncing_ui = True
        try:
            self.ocr_engine_label.setText(
                "Tesseract · sẵn sàng"
                if self.ocr_engine.is_available()
                else "Tesseract · chưa tìm thấy trong PATH"
            )

            if page is None or region is None:
                self.ocr_machine_text.clear()
                if not self.ocr_editor_dirty:
                    self.ocr_edited_text.clear()
                self.ocr_preview.clear()
                self.ocr_preview.setText("Chưa chọn Region")
                self.ocr_status.setText("Chưa quét.")
                self.ocr_editor_region_id = None
                return

            language_index = self.ocr_language.findData(
                region.ocr_language
            )
            self.ocr_language.setCurrentIndex(max(0, language_index))
            layout_index = self.ocr_layout.findData(
                region.ocr_layout
            )
            self.ocr_layout.setCurrentIndex(max(0, layout_index))

            self.ocr_machine_text.setPlainText(
                region.ocr_machine_text
            )
            if not (
                self.ocr_editor_dirty
                and self.ocr_editor_region_id == region.id
            ):
                self.ocr_edited_text.setPlainText(
                    region.ocr_edited_text
                )
                self.ocr_editor_region_id = region.id
                self.ocr_editor_dirty = False

            status_parts = [
                f"Trạng thái: {STATE_LABELS[region.ocr_state]}"
            ]
            if region.ocr_engine:
                status_parts.append(f"Engine: {region.ocr_engine}")
            if region.ocr_confidence is not None:
                status_parts.append(
                    f"Độ tin cậy tham khảo: {region.ocr_confidence:.0%}"
                )
            if region.ocr_is_stale:
                status_parts.append(
                    "Kết quả cũ: vùng/ngôn ngữ/bố cục đã thay đổi, nên quét lại."
                )
            if region.ocr_warning:
                status_parts.append(region.ocr_warning)
            self.ocr_status.setText("\n".join(status_parts))

            if region.ocr_area is None:
                self.ocr_preview.clear()
                self.ocr_preview.setText("Chưa có vùng OCR")
            else:
                try:
                    crop = crop_raw_to_png(
                        self.session.assets[page.raw_asset],
                        region.ocr_area,
                    )
                    pixmap = QPixmap.fromImage(crop.image).scaled(
                        380,
                        220,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.ocr_preview.setPixmap(pixmap)
                except Exception as exc:
                    self.ocr_preview.clear()
                    self.ocr_preview.setText(
                        f"Không hiển thị được ảnh cắt: {exc}"
                    )
        finally:
            self._syncing_ui = False

    def apply_white_patch(self) -> None:
        self._apply_patch("#ffffff")

    def apply_color_patch(self) -> None:
        color = QColorDialog.getColor(
            QColor("#ffffff"), self, "Chọn màu nền"
        )
        if color.isValid():
            self._apply_patch(color.name())

    def _apply_patch(self, color: str) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            self._error("Chưa chọn vùng", "Chọn Region trước khi tạo patch.")
            return
        try:
            self.session.set_background_patch(
                self.current_page_id,
                self.current_region_id,
                color,
            )
        except Exception as exc:
            self._error("Không tạo được patch", str(exc))
            return
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def remove_patch(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        self.session.remove_region_layer(
            self.current_page_id,
            self.current_region_id,
            LayerKind.BACKGROUND_PATCH,
        )
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def choose_text_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self.text_color), self, "Chọn màu chữ"
        )
        if color.isValid():
            self.text_color = color.name()
            self._mark_editor_dirty()
            self.statusBar().showMessage(
                f"Màu chữ hiện tại: {self.text_color}"
            )

    def apply_vietnamese_text(self) -> None:
        if self.current_region_id is None:
            self._error(
                "Chưa chọn vùng",
                "Chọn Region trước khi tạo chữ Việt.",
            )
            return
        if self._save_editor_to_region(self.current_region_id):
            self._refresh_all(
                select_page_id=self.current_page_id,
                select_region_id=self.current_region_id,
            )

    def _save_editor_to_region(self, region_id: str) -> bool:
        if self.current_page_id is None:
            return False
        try:
            self.session.set_vietnamese_text(
                page_id=self.current_page_id,
                region_id=region_id,
                content=self.vn_text.toPlainText(),
                family=self.font_family.currentFont().family(),
                size=self.font_size.value(),
                align=self.text_align.currentData(),
                color=self.text_color,
            )
        except Exception as exc:
            self._error("Không lưu được chữ Việt", str(exc))
            return False
        self.editor_region_id = region_id
        self.editor_dirty = False
        return True

    def remove_text_layer(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        self.session.remove_region_layer(
            self.current_page_id,
            self.current_region_id,
            LayerKind.VIETNAMESE_TEXT,
        )
        self.editor_dirty = False
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def _state_changed(self, aspect: str, combo: QComboBox) -> None:
        if (
            self._syncing_ui
            or self.current_page_id is None
            or self.current_region_id is None
        ):
            return
        self.session.set_region_state(
            self.current_page_id,
            self.current_region_id,
            aspect,
            combo.currentData(),
        )
        self._refresh_region_lists_only()

    def _layer_visibility_changed(self, item: QListWidgetItem) -> None:
        if self._syncing_ui or self.current_page_id is None:
            return
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        if not layer_id:
            return
        page = self._current_page()
        if page is None:
            return
        try:
            layer = page.layer(layer_id)
        except KeyError:
            return
        if layer.kind == LayerKind.SOURCE:
            return
        visible = item.checkState() == Qt.CheckState.Checked
        self.session.set_layer_visibility(
            self.current_page_id, layer_id, visible
        )
        self._refresh_canvas()

    def undo(self) -> None:
        if not self._confirm_editor_changes():
            return
        if self.session.undo():
            self._repair_selection_after_history()
            self._refresh_all(
                select_page_id=self.current_page_id,
                select_region_id=self.current_region_id,
            )

    def redo(self) -> None:
        if not self._confirm_editor_changes():
            return
        if self.session.redo():
            self._repair_selection_after_history()
            self._refresh_all(
                select_page_id=self.current_page_id,
                select_region_id=self.current_region_id,
            )

    def _page_changed(self, row: int) -> None:
        if self._syncing_ui:
            return
        if row < 0 or row >= len(self.session.project.pages):
            return
        new_page_id = self.session.project.pages[row].id
        if new_page_id == self.current_page_id:
            return
        if not self._confirm_editor_changes():
            self._sync_page_selection()
            return
        self.current_page_id = new_page_id
        self.current_region_id = None
        self.editor_region_id = None
        self.editor_dirty = False
        self.ocr_editor_region_id = None
        self.ocr_editor_dirty = False
        self._refresh_regions()
        self._refresh_contents()
        self._load_region_layers_into_editor()
        self._load_ocr_editor()
        self._refresh_canvas()
        self._refresh_layers()

    def _region_changed(self, row: int) -> None:
        if self._syncing_ui:
            return
        page = self._current_page()
        if page is None or row < 0:
            return
        ordered = sorted(page.regions, key=lambda x: x.order)
        if row >= len(ordered):
            return
        self._switch_region(ordered[row].id)

    def _content_region_changed(self, row: int) -> None:
        if self._syncing_ui or row < 0:
            return
        item = self.contents.item(row)
        if item is None:
            return
        region_id = item.data(Qt.ItemDataRole.UserRole)
        if region_id:
            self._switch_region(str(region_id))

    def _select_region_by_id(self, region_id: str) -> None:
        self._switch_region(region_id)

    def _choose_overlapping_region(self, region_ids: list[str]) -> None:
        page = self._current_page()
        if page is None:
            return
        choices = []
        mapping = {}
        for region_id in region_ids:
            try:
                region = page.region(region_id)
            except KeyError:
                continue
            label = f"{region.order + 1:02d}. {region.name}"
            choices.append(label)
            mapping[label] = region.id
        if not choices:
            return
        choice, ok = QInputDialog.getItem(
            self,
            "Nhiều Region chồng nhau",
            "Chọn Region tại vị trí vừa bấm:",
            choices,
            0,
            False,
        )
        if ok:
            self._switch_region(mapping[choice])

    def _switch_region(
        self, region_id: str, ask_editor: bool = True
    ) -> None:
        page = self._current_page()
        if page is None:
            return
        try:
            page.region(region_id)
        except KeyError:
            return

        if region_id == self.current_region_id:
            self._sync_region_selection_widgets()
            return

        if ask_editor and not self._confirm_editor_changes():
            self._sync_region_selection_widgets()
            return

        self.current_region_id = region_id
        self.editor_region_id = region_id
        self.editor_dirty = False
        self.ocr_editor_region_id = region_id
        self.ocr_editor_dirty = False
        self._sync_region_selection_widgets()
        self._refresh_region_form()
        self._load_region_layers_into_editor()
        self._load_ocr_editor()
        self._refresh_canvas()
        self.statusBar().showMessage(
            f"Đang làm việc với {self._current_region().name}."
        )

    def _confirm_editor_changes(self) -> bool:
        if not self._confirm_ocr_editor_changes():
            return False

        if (
            not self.editor_dirty
            or self.editor_region_id is None
            or self.current_page_id is None
        ):
            return True

        result = QMessageBox.warning(
            self,
            "Chữ Việt chưa áp dụng",
            "Bạn đã thay đổi nội dung/định dạng chữ nhưng chưa bấm Áp dụng. "
            "Muốn lưu thay đổi vào Region hiện tại trước khi chuyển?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Discard:
            self.editor_dirty = False
            return True
        return self._save_editor_to_region(self.editor_region_id)

    def _confirm_ocr_editor_changes(self) -> bool:
        if (
            not self.ocr_editor_dirty
            or self.ocr_editor_region_id is None
            or self.current_page_id is None
        ):
            return True

        result = QMessageBox.warning(
            self,
            "Chữ OCR đã sửa chưa lưu",
            "Bạn đã sửa văn bản OCR nhưng chưa lưu vào Region. "
            "Muốn lưu trước khi chuyển?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Discard:
            self.ocr_editor_dirty = False
            return True
        return self._save_ocr_editor_to_region(
            self.ocr_editor_region_id, reviewed=False
        )

    def _mark_editor_dirty(self) -> None:
        if self._syncing_ui or self.current_region_id is None:
            return
        self.editor_dirty = True

    def _refresh_all(
        self,
        select_page_id: str | None = None,
        select_region_id: str | None = None,
    ) -> None:
        if select_page_id is not None:
            self.current_page_id = select_page_id
        if select_region_id is not None:
            self.current_region_id = select_region_id

        self.project_name.setText(
            f"{self.session.project.name} · format "
            f"v{self.session.project.format_version}"
        )

        self._sync_page_selection(rebuild=True)
        self._refresh_regions()
        self._refresh_contents()
        self._load_region_layers_into_editor()
        self._load_ocr_editor()
        self._refresh_canvas()
        self._refresh_layers()

    def _sync_page_selection(self, rebuild: bool = False) -> None:
        self._syncing_ui = True
        try:
            if rebuild:
                self.pages.clear()
                for i, page in enumerate(self.session.project.pages):
                    self.pages.addItem(f"{i + 1:02d}. {page.name}")
            row = -1
            for i, page in enumerate(self.session.project.pages):
                if page.id == self.current_page_id:
                    row = i
                    break
            self.pages.setCurrentRow(row)
        finally:
            self._syncing_ui = False

    def _refresh_regions(self) -> None:
        page = self._current_page()
        self._syncing_ui = True
        try:
            self.regions.clear()
            if page is not None:
                for region in sorted(page.regions, key=lambda x: x.order):
                    item = QListWidgetItem(
                        f"{region.order + 1:02d}. {region.name}  "
                        f"[Nền: {STATE_LABELS[region.cleanup_state]} | "
                        f"Chữ: {STATE_LABELS[region.text_state]}]"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, region.id)
                    self.regions.addItem(item)
            self._sync_region_selection_widgets()
        finally:
            self._syncing_ui = False
        self._refresh_region_form()

    def _refresh_contents(self) -> None:
        page = self._current_page()
        self._syncing_ui = True
        try:
            self.contents.clear()
            if page is not None:
                for region in sorted(page.regions, key=lambda x: x.order):
                    layer = page.layer_for_region(
                        region.id, LayerKind.VIETNAMESE_TEXT
                    )
                    source_preview = (
                        region.source_text.replace("\n", " / ").strip()[:34]
                        or "(chưa OCR)"
                    )
                    vi_preview = (
                        str(layer.payload.get("content", ""))
                        .replace("\n", " / ")
                        .strip()[:34]
                        if layer is not None
                        else "(chưa có VI)"
                    )
                    item = QListWidgetItem(
                        f"{region.order + 1:02d}. Gốc: {source_preview} | VI: {vi_preview}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, region.id)
                    self.contents.addItem(item)
            self._sync_region_selection_widgets()
        finally:
            self._syncing_ui = False

    def _refresh_region_lists_only(self) -> None:
        current = self.current_region_id
        self._refresh_regions()
        self._refresh_contents()
        self.current_region_id = current
        self._sync_region_selection_widgets()

    def _sync_region_selection_widgets(self) -> None:
        page = self._current_page()
        if page is None:
            self.regions.setCurrentRow(-1)
            self.contents.setCurrentRow(-1)
            return

        ordered = sorted(page.regions, key=lambda x: x.order)
        row = next(
            (
                i
                for i, region in enumerate(ordered)
                if region.id == self.current_region_id
            ),
            -1,
        )
        old = self._syncing_ui
        self._syncing_ui = True
        try:
            self.regions.setCurrentRow(row)
            self.contents.setCurrentRow(row)
        finally:
            self._syncing_ui = old

    def _refresh_region_form(self) -> None:
        region = self._current_region()
        enabled = region is not None

        self._syncing_ui = True
        try:
            self.region_name.setEnabled(enabled)
            self.area_combo.setEnabled(enabled)
            self.vn_text.setEnabled(enabled)
            self.font_family.setEnabled(enabled)
            self.font_size.setEnabled(enabled)
            self.text_align.setEnabled(enabled)
            self.cleanup_state.setEnabled(enabled)
            self.text_state.setEnabled(enabled)
            self.ocr_state.setEnabled(enabled)
            self.ocr_language.setEnabled(enabled)
            self.ocr_layout.setEnabled(enabled)
            self.ocr_edited_text.setEnabled(enabled)

            if region is None:
                self.region_id.setText("—")
                self.region_name.setText("")
                self.ocr_rect.setText("—")
                self.cleanup_rect.setText("—")
                self.text_rect.setText("—")
                self.ocr_state.setCurrentIndex(0)
                self.cleanup_parts.clear()
                return

            self.region_id.setText(region.id)
            self.region_name.setText(region.name)
            self.ocr_rect.setText(self._rect_text(region.ocr_area))
            self.cleanup_rect.setText(
                self._rect_text(region.cleanup_area)
            )
            self.text_rect.setText(
                self._rect_text(region.text_frame)
            )
            ocr_index = self.ocr_state.findData(
                region.ocr_state.value
            )
            self.ocr_state.setCurrentIndex(max(0, ocr_index))

            cleanup_index = self.cleanup_state.findData(
                region.cleanup_state.value
            )
            self.cleanup_state.setCurrentIndex(
                max(0, cleanup_index)
            )
            text_index = self.text_state.findData(
                region.text_state.value
            )
            self.text_state.setCurrentIndex(max(0, text_index))

            self.cleanup_parts.clear()
            for i, rect in enumerate(region.cleanup_parts):
                self.cleanup_parts.addItem(
                    f"Mảng {i + 1}: {self._rect_text(rect)}"
                )
        finally:
            self._syncing_ui = False

    def _load_region_layers_into_editor(self) -> None:
        page = self._current_page()
        region = self._current_region()

        self._syncing_ui = True
        try:
            if page is None or region is None:
                self.vn_text.clear()
                self.editor_region_id = None
                self.editor_dirty = False
                return

            if (
                self.editor_dirty
                and self.editor_region_id == region.id
            ):
                return

            text_layer = page.layer_for_region(
                region.id, LayerKind.VIETNAMESE_TEXT
            )
            if text_layer is None:
                self.vn_text.setPlainText("")
                self.font_size.setValue(32)
                self.text_align.setCurrentIndex(
                    self.text_align.findData("center")
                )
                self.text_color = "#000000"
            else:
                payload = text_layer.payload
                self.vn_text.setPlainText(
                    str(payload.get("content", ""))
                )
                self.font_family.setCurrentFont(
                    QFont(str(payload.get("family", "Arial")))
                )
                self.font_size.setValue(
                    max(6, int(payload.get("size", 32)))
                )
                align_index = self.text_align.findData(
                    payload.get("align", "center")
                )
                self.text_align.setCurrentIndex(
                    max(0, align_index)
                )
                self.text_color = str(
                    payload.get("color", "#000000")
                )
            self.editor_region_id = region.id
            self.editor_dirty = False
        finally:
            self._syncing_ui = False

    def _refresh_canvas(self) -> None:
        page = self._current_page()
        if page is None:
            self.canvas.set_page(None, None)
            return
        raw = self.session.assets.get(page.raw_asset)
        if raw is None:
            self.canvas.set_page(
                page, None, self.current_region_id
            )
            return
        try:
            image = render_page(page, raw)
        except Exception as exc:
            self._error("Không dựng được trang", str(exc))
            return
        self.canvas.set_page(
            page, image, self.current_region_id
        )

    def _refresh_layers(self) -> None:
        self._syncing_ui = True
        try:
            self.layers.clear()
            page = self._current_page()
            if page is None:
                return
            for layer in page.layers:
                label = {
                    LayerKind.SOURCE: "Ảnh gốc",
                    LayerKind.BACKGROUND_PATCH: "Bản vá nền",
                    LayerKind.VIETNAMESE_TEXT: "Chữ Việt",
                    LayerKind.GUIDE: "Hướng dẫn",
                }.get(layer.kind, layer.name)

                region_name = ""
                if layer.region_id:
                    try:
                        region_name = (
                            f" · {page.region(layer.region_id).name}"
                        )
                    except KeyError:
                        region_name = " · vùng không tồn tại"

                item = QListWidgetItem(
                    f"{label}{region_name}"
                )
                item.setData(
                    Qt.ItemDataRole.UserRole, layer.id
                )
                if layer.kind == LayerKind.SOURCE:
                    item.setFlags(
                        item.flags()
                        & ~Qt.ItemFlag.ItemIsUserCheckable
                    )
                    item.setText(item.text() + " (khóa)")
                else:
                    item.setFlags(
                        item.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if layer.visible
                        else Qt.CheckState.Unchecked
                    )
                self.layers.addItem(item)
        finally:
            self._syncing_ui = False

    def _repair_selection_after_history(self) -> None:
        page_ids = {
            page.id for page in self.session.project.pages
        }
        if self.current_page_id not in page_ids:
            self.current_page_id = (
                self.session.project.pages[0].id
                if self.session.project.pages
                else None
            )
            self.current_region_id = None
            return

        if (
            self.current_page_id is not None
            and self.current_region_id is not None
        ):
            region_ids = {
                region.id
                for region in self.session.project.page(
                    self.current_page_id
                ).regions
            }
            if self.current_region_id not in region_ids:
                self.current_region_id = None

    def _current_page(self):
        if self.current_page_id is None:
            return None
        try:
            return self.session.project.page(
                self.current_page_id
            )
        except KeyError:
            return None

    def _current_region(self):
        page = self._current_page()
        if page is None or self.current_region_id is None:
            return None
        try:
            return page.region(self.current_region_id)
        except KeyError:
            return None

    @staticmethod
    def _rect_text(rect: Rect | None) -> str:
        if rect is None:
            return "—"
        return (
            f"x={rect.x:.0f}, y={rect.y:.0f}, "
            f"w={rect.width:.0f}, h={rect.height:.0f}"
        )

    def _confirm_discard(self) -> bool:
        if not self.session.dirty:
            return True
        result = QMessageBox.question(
            self,
            "Dự án chưa lưu",
            "Có thay đổi chưa lưu. Tiếp tục và bỏ các thay đổi đó?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event) -> None:
        if self.ocr_task is not None and self.ocr_task.isRunning():
            QMessageBox.information(
                self,
                "OCR đang chạy",
                "Chờ tác vụ OCR hiện tại hoàn thành trước khi đóng ứng dụng.",
            )
            event.ignore()
            return
        if (
            self._confirm_editor_changes()
            and self._confirm_discard()
        ):
            event.accept()
        else:
            event.ignore()
