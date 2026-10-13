from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
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
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from manga_editor import APP_VERSION
from manga_editor.application.session import ProjectSession
from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import LayerKind
from manga_editor.infrastructure.image_io import load_raw_image
from manga_editor.infrastructure.project_store import ProjectStore
from manga_editor.infrastructure.renderer import render_page, save_rendered_page
from .canvas import CanvasView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MangaEditor v0.1 — {APP_VERSION}")
        self.resize(1500, 920)
        self.session = ProjectSession()
        self.project_path: Path | None = None
        self.current_page_id: str | None = None
        self.current_region_id: str | None = None
        self.text_color = "#000000"

        self.canvas = CanvasView()
        self.canvas.areaDrawn.connect(self._area_drawn)
        self.canvas.regionSelected.connect(self._select_region_by_id)

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
        left.setMinimumWidth(220)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        project_box = QGroupBox("v0.1 — Một trang đơn giản")
        project_layout = QVBoxLayout(project_box)
        self.project_name = QLabel()
        project_layout.addWidget(self.project_name)
        note = QLabel(
            "Quy trình: nhập raw → tạo vùng → đặt phạm vi xóa/chữ → "
            "tạo bản vá nền → nhập chữ Việt → lưu hoặc xuất ảnh. "
            "OCR chưa có ở v0.1."
        )
        note.setWordWrap(True)
        project_layout.addWidget(note)
        right_layout.addWidget(project_box)

        region_box = QGroupBox("1. Vùng nội dung")
        region_layout = QVBoxLayout(region_box)
        region_buttons = QHBoxLayout()
        add_region = QPushButton("Tạo vùng mới")
        add_region.clicked.connect(self.add_region)
        delete_region = QPushButton("Xóa vùng")
        delete_region.clicked.connect(self.delete_region)
        region_buttons.addWidget(add_region)
        region_buttons.addWidget(delete_region)
        region_layout.addLayout(region_buttons)

        self.regions = QListWidget()
        self.regions.setMaximumHeight(125)
        self.regions.currentRowChanged.connect(self._region_changed)
        region_layout.addWidget(self.regions)

        form = QFormLayout()
        self.region_id = QLabel("—")
        self.region_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("ID cố định", self.region_id)

        self.region_name = QLineEdit()
        self.region_name.editingFinished.connect(self.rename_region)
        form.addRow("Tên hiển thị", self.region_name)

        self.area_combo = QComboBox()
        self.area_combo.addItem("Phạm vi xóa chữ", "cleanup_area")
        self.area_combo.addItem("Khung đặt chữ Việt", "text_frame")
        self.area_combo.addItem("Vùng đọc OCR (để dành)", "ocr_area")
        form.addRow("Phạm vi", self.area_combo)
        region_layout.addLayout(form)

        draw_button = QPushButton("Vẽ / cập nhật phạm vi trên ảnh")
        draw_button.clicked.connect(self.begin_draw_area)
        region_layout.addWidget(draw_button)

        self.ocr_rect = QLabel("—")
        self.cleanup_rect = QLabel("—")
        self.text_rect = QLabel("—")
        rect_form = QFormLayout()
        rect_form.addRow("OCR", self.ocr_rect)
        rect_form.addRow("Xóa chữ", self.cleanup_rect)
        rect_form.addRow("Chữ Việt", self.text_rect)
        region_layout.addLayout(rect_form)
        right_layout.addWidget(region_box)

        patch_box = QGroupBox("2. Làm sạch nền cơ bản")
        patch_layout = QVBoxLayout(patch_box)
        patch_note = QLabel(
            "v0.1 chỉ tạo bản vá màu phẳng trên layer riêng. "
            "Không sửa trực tiếp ảnh raw."
        )
        patch_note.setWordWrap(True)
        patch_layout.addWidget(patch_note)

        patch_buttons = QHBoxLayout()
        white_button = QPushButton("Tô trắng vùng xóa")
        white_button.clicked.connect(self.apply_white_patch)
        color_button = QPushButton("Chọn màu nền")
        color_button.clicked.connect(self.apply_color_patch)
        remove_patch = QPushButton("Bỏ bản vá")
        remove_patch.clicked.connect(self.remove_patch)
        patch_buttons.addWidget(white_button)
        patch_buttons.addWidget(color_button)
        patch_buttons.addWidget(remove_patch)
        patch_layout.addLayout(patch_buttons)
        right_layout.addWidget(patch_box)

        text_box = QGroupBox("3. Chữ Việt")
        text_layout = QVBoxLayout(text_box)
        self.vn_text = QTextEdit()
        self.vn_text.setPlaceholderText("Nhập nội dung tiếng Việt cho vùng đang chọn…")
        self.vn_text.setFixedHeight(105)
        text_layout.addWidget(self.vn_text)

        text_form = QFormLayout()
        self.font_family = QFontComboBox()
        text_form.addRow("Phông", self.font_family)

        self.font_size = QSpinBox()
        self.font_size.setRange(6, 300)
        self.font_size.setValue(32)
        self.font_size.setSuffix(" px")
        text_form.addRow("Cỡ chữ", self.font_size)

        self.text_align = QComboBox()
        self.text_align.addItem("Căn trái", "left")
        self.text_align.addItem("Căn giữa", "center")
        self.text_align.addItem("Căn phải", "right")
        self.text_align.setCurrentIndex(1)
        text_form.addRow("Căn chữ", self.text_align)
        text_layout.addLayout(text_form)

        text_buttons = QHBoxLayout()
        apply_text = QPushButton("Áp dụng / cập nhật chữ")
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

        layer_box = QGroupBox("4. Layer của trang")
        layer_layout = QVBoxLayout(layer_box)
        layer_note = QLabel("Bỏ dấu ✓ để ẩn bản vá hoặc chữ; ảnh gốc luôn được khóa.")
        layer_note.setWordWrap(True)
        layer_layout.addWidget(layer_note)
        self.layers = QListWidget()
        self.layers.setMaximumHeight(135)
        self.layers.itemChanged.connect(self._layer_visibility_changed)
        layer_layout.addWidget(self.layers)
        right_layout.addWidget(layer_box)

        export_button = QPushButton("Xuất ảnh hoàn chỉnh")
        export_button.clicked.connect(self.export_image)
        right_layout.addWidget(export_button)
        right_layout.addStretch(1)
        right.setMinimumWidth(390)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.canvas)
        splitter.addWidget(right)
        splitter.setSizes([220, 860, 400])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage(
            "v0.1: làm trọn một trang đơn giản, không phá ảnh raw."
        )

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        name, ok = QInputDialog.getText(self, "Dự án mới", "Tên dự án:")
        if not ok:
            return
        from manga_editor.domain.models import MangaProject

        self.session = ProjectSession(MangaProject.create(name))
        self.project_path = None
        self.current_page_id = None
        self.current_region_id = None
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
            page_id = self.session.add_page(raw.name, raw.data, raw.width, raw.height)
        except Exception as exc:
            self._error("Không nhập được ảnh", str(exc))
            return
        self.current_page_id = page_id
        self.current_region_id = None
        self._refresh_all(select_page_id=page_id)
        self.canvas.fit_page()

    def save_project(self) -> None:
        if self.project_path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Lưu dự án", "manga-project.mep", "MangaEditor Project (*.mep)"
            )
            if not path:
                return
            self.project_path = Path(path if path.lower().endswith(".mep") else path + ".mep")
        try:
            ProjectStore.save(self.project_path, self.session.project, self.session.assets)
            self.session.dirty = False
            self.statusBar().showMessage(f"Đã lưu: {self.project_path}")
        except Exception as exc:
            self._error("Không lưu được dự án", str(exc))

    def open_project(self) -> None:
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
        self.current_page_id = project.pages[0].id if project.pages else None
        self.current_region_id = None
        self._refresh_all(select_page_id=self.current_page_id)
        self.canvas.fit_page()

    def export_image(self) -> None:
        page = self._current_page()
        if page is None:
            self._error("Chưa có trang", "Chọn hoặc nhập một trang trước khi xuất.")
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
            f"Đã xuất {path} đúng kích thước {page.width}×{page.height}."
        )

    def add_region(self) -> None:
        if self.current_page_id is None:
            self._error("Chưa có trang", "Nhập một ảnh raw trước.")
            return
        region_id = self.session.add_region(self.current_page_id)
        self.current_region_id = region_id
        self._refresh_all(
            select_page_id=self.current_page_id, select_region_id=region_id
        )

    def delete_region(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        self.session.delete_region(self.current_page_id, self.current_region_id)
        self.current_region_id = None
        self._refresh_all(select_page_id=self.current_page_id)

    def rename_region(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        self.session.rename_region(
            self.current_page_id, self.current_region_id, self.region_name.text()
        )
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def begin_draw_area(self) -> None:
        if self.current_region_id is None:
            self._error("Chưa chọn vùng", "Tạo hoặc chọn một vùng trước khi vẽ phạm vi.")
            return
        self.canvas.set_draw_mode(self.area_combo.currentData())
        self.statusBar().showMessage(
            "Kéo chuột trên ảnh để đặt phạm vi. Zoom không làm đổi tọa độ lưu."
        )

    def _area_drawn(self, area_kind: str, rect: Rect) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        try:
            self.session.set_region_area(
                self.current_page_id, self.current_region_id, area_kind, rect
            )
        except Exception as exc:
            self._error("Không cập nhật được phạm vi", str(exc))
            return
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def apply_white_patch(self) -> None:
        self._apply_patch("#ffffff")

    def apply_color_patch(self) -> None:
        color = QColorDialog.getColor(QColor("#ffffff"), self, "Chọn màu nền")
        if color.isValid():
            self._apply_patch(color.name())

    def _apply_patch(self, color: str) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            self._error("Chưa chọn vùng", "Chọn vùng trước khi tạo bản vá.")
            return
        try:
            self.session.set_background_patch(
                self.current_page_id, self.current_region_id, color
            )
        except Exception as exc:
            self._error("Không tạo được bản vá", str(exc))
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
        color = QColorDialog.getColor(QColor(self.text_color), self, "Chọn màu chữ")
        if color.isValid():
            self.text_color = color.name()
            self.statusBar().showMessage(f"Màu chữ hiện tại: {self.text_color}")

    def apply_vietnamese_text(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            self._error("Chưa chọn vùng", "Chọn vùng trước khi tạo chữ Việt.")
            return
        try:
            self.session.set_vietnamese_text(
                page_id=self.current_page_id,
                region_id=self.current_region_id,
                content=self.vn_text.toPlainText(),
                family=self.font_family.currentFont().family(),
                size=self.font_size.value(),
                align=self.text_align.currentData(),
                color=self.text_color,
            )
        except Exception as exc:
            self._error("Không tạo được chữ Việt", str(exc))
            return
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def remove_text_layer(self) -> None:
        if self.current_page_id is None or self.current_region_id is None:
            return
        self.session.remove_region_layer(
            self.current_page_id,
            self.current_region_id,
            LayerKind.VIETNAMESE_TEXT,
        )
        self._refresh_all(
            select_page_id=self.current_page_id,
            select_region_id=self.current_region_id,
        )

    def _layer_visibility_changed(self, item: QListWidgetItem) -> None:
        if self.current_page_id is None:
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
        self.session.set_layer_visibility(self.current_page_id, layer_id, visible)
        self._refresh_canvas()

    def undo(self) -> None:
        if self.session.undo():
            self._repair_selection_after_history()
            self._refresh_all(
                select_page_id=self.current_page_id,
                select_region_id=self.current_region_id,
            )

    def redo(self) -> None:
        if self.session.redo():
            self._repair_selection_after_history()
            self._refresh_all(
                select_page_id=self.current_page_id,
                select_region_id=self.current_region_id,
            )

    def _repair_selection_after_history(self) -> None:
        page_ids = {p.id for p in self.session.project.pages}
        if self.current_page_id not in page_ids:
            self.current_page_id = (
                self.session.project.pages[0].id if self.session.project.pages else None
            )
            self.current_region_id = None
            return
        if self.current_page_id is not None and self.current_region_id is not None:
            region_ids = {
                r.id for r in self.session.project.page(self.current_page_id).regions
            }
            if self.current_region_id not in region_ids:
                self.current_region_id = None

    def _page_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.session.project.pages):
            return
        self.current_page_id = self.session.project.pages[row].id
        self.current_region_id = None
        self._refresh_regions()
        self._refresh_canvas()
        self._refresh_layers()

    def _region_changed(self, row: int) -> None:
        page = self._current_page()
        if page is None or row < 0 or row >= len(page.regions):
            self.current_region_id = None
        else:
            ordered = sorted(page.regions, key=lambda x: x.order)
            self.current_region_id = ordered[row].id
        self._refresh_region_form()
        self._load_region_layers_into_editor()
        self._refresh_canvas()

    def _select_region_by_id(self, region_id: str) -> None:
        page = self._current_page()
        if page is None:
            return
        ordered = sorted(page.regions, key=lambda x: x.order)
        for index, region in enumerate(ordered):
            if region.id == region_id:
                self.current_region_id = region_id
                self.regions.setCurrentRow(index)
                return

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
            f"{self.session.project.name} · format v{self.session.project.format_version}"
        )

        self.pages.blockSignals(True)
        self.pages.clear()
        page_row = -1
        for i, page in enumerate(self.session.project.pages):
            self.pages.addItem(f"{i + 1:02d}. {page.name}")
            if page.id == self.current_page_id:
                page_row = i
        self.pages.setCurrentRow(page_row)
        self.pages.blockSignals(False)

        self._refresh_regions()
        self._load_region_layers_into_editor()
        self._refresh_canvas()
        self._refresh_layers()

    def _refresh_regions(self) -> None:
        page = self._current_page()
        self.regions.blockSignals(True)
        self.regions.clear()
        region_row = -1
        if page is not None:
            ordered = sorted(page.regions, key=lambda x: x.order)
            for i, region in enumerate(ordered):
                self.regions.addItem(f"{i + 1:02d}. {region.name}")
                if region.id == self.current_region_id:
                    region_row = i
        self.regions.setCurrentRow(region_row)
        self.regions.blockSignals(False)
        self._refresh_region_form()

    def _refresh_region_form(self) -> None:
        region = self._current_region()
        enabled = region is not None
        self.region_name.setEnabled(enabled)
        self.area_combo.setEnabled(enabled)
        self.vn_text.setEnabled(enabled)
        self.font_family.setEnabled(enabled)
        self.font_size.setEnabled(enabled)
        self.text_align.setEnabled(enabled)

        if region is None:
            self.region_id.setText("—")
            self.region_name.setText("")
            self.ocr_rect.setText("—")
            self.cleanup_rect.setText("—")
            self.text_rect.setText("—")
            return

        self.region_id.setText(region.id)
        self.region_name.setText(region.name)
        self.ocr_rect.setText(self._rect_text(region.ocr_area))
        self.cleanup_rect.setText(self._rect_text(region.cleanup_area))
        self.text_rect.setText(self._rect_text(region.text_frame))

    def _load_region_layers_into_editor(self) -> None:
        page = self._current_page()
        region = self._current_region()
        if page is None or region is None:
            self.vn_text.blockSignals(True)
            self.vn_text.clear()
            self.vn_text.blockSignals(False)
            return

        text_layer = page.layer_for_region(region.id, LayerKind.VIETNAMESE_TEXT)
        if text_layer is None:
            self.vn_text.setPlainText("")
            self.font_size.setValue(32)
            self.text_align.setCurrentIndex(self.text_align.findData("center"))
            self.text_color = "#000000"
            return

        payload = text_layer.payload
        self.vn_text.setPlainText(str(payload.get("content", "")))
        family = str(payload.get("family", "Arial"))
        self.font_family.setCurrentFont(self.font_family.currentFont().__class__(family))
        self.font_size.setValue(max(6, int(payload.get("size", 32))))
        align_index = self.text_align.findData(payload.get("align", "center"))
        self.text_align.setCurrentIndex(max(0, align_index))
        self.text_color = str(payload.get("color", "#000000"))

    def _refresh_canvas(self) -> None:
        page = self._current_page()
        if page is None:
            self.canvas.set_page(None, None)
            return
        raw = self.session.assets.get(page.raw_asset)
        if raw is None:
            self.canvas.set_page(page, None, self.current_region_id)
            return
        try:
            image = render_page(page, raw)
        except Exception as exc:
            self._error("Không dựng được trang", str(exc))
            return
        self.canvas.set_page(page, image, self.current_region_id)

    def _refresh_layers(self) -> None:
        self.layers.blockSignals(True)
        self.layers.clear()
        page = self._current_page()
        if page is not None:
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
                        region_name = f" · {page.region(layer.region_id).name}"
                    except KeyError:
                        region_name = " · vùng không tồn tại"
                item = QListWidgetItem(f"{label}{region_name}")
                item.setData(Qt.ItemDataRole.UserRole, layer.id)
                if layer.kind == LayerKind.SOURCE:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setText(item.text() + " (khóa)")
                else:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
                    )
                self.layers.addItem(item)
        self.layers.blockSignals(False)

    def _current_page(self):
        if self.current_page_id is None:
            return None
        try:
            return self.session.project.page(self.current_page_id)
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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
