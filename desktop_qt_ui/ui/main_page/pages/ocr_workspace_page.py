from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from PyQt6.QtCore import Qt, QRectF, QUrl
from PyQt6.QtGui import QBrush, QPainter, QPen, QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
    FluentIcon as FIF,
)

from manga_translator.image_formats import SUPPORTED_IMAGE_EXTENSIONS
from manga_translator.utils.path_manager import find_json_path
from .ocr_project_registry import OCRProjectRegistry, norm_path, within, render_signature, render_config_digest


def _allowed_image_extensions() -> set[str]:
    values = set()
    for value in SUPPORTED_IMAGE_EXTENSIONS:
        text = str(value).lower().strip()
        if not text:
            continue
        values.add(text if text.startswith(".") else f".{text}")
    return values


_IMAGE_EXTENSIONS = _allowed_image_extensions()


def _region_rect(region: dict[str, Any]) -> QRectF | None:
    points: list[tuple[float, float]] = []

    def collect(value):
        if isinstance(value, (list, tuple)):
            if (
                len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))
            ):
                points.append((float(value[0]), float(value[1])))
                return
            for child in value:
                collect(child)

    collect(region.get("lines"))
    if points:
        xs = [item[0] for item in points]
        ys = [item[1] for item in points]
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        return QRectF(left, top, max(1.0, right - left), max(1.0, bottom - top))

    raw = region.get("_bounding_rect") or region.get("bounding_rect")
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            x, y, w, h = [float(v) for v in raw[:4]]
            return QRectF(x, y, max(1.0, w), max(1.0, h))
        except (TypeError, ValueError):
            return None
    return None


class OCRImagePreview(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._highlight_item: QGraphicsRectItem | None = None
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(self.palette().base()))

    def set_image(self, path: str | None):
        self._scene.clear()
        self._pixmap_item = None
        self._highlight_item = None
        if not path or not os.path.isfile(path):
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._fit_image()

    def highlight_region(self, region: dict[str, Any] | None):
        if self._highlight_item is not None:
            try:
                self._scene.removeItem(self._highlight_item)
            except RuntimeError:
                pass
            self._highlight_item = None
        if not region:
            return
        rect = _region_rect(region)
        if rect is None:
            return
        pen = QPen(self.palette().highlight().color())
        pen.setWidth(4)
        self._highlight_item = self._scene.addRect(rect, pen)
        self.ensureVisible(rect.adjusted(-20, -20, 20, 20), 30, 30)

    def _fit_image(self):
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()



class OCRWorkspacePanel(QWidget):
    """Manage isolated OCR project folders, edit translations, and render changed pages.

    Render Batch always uses current project's images and never merges the
    normal Translation page's global file sources.
    """

    def __init__(self, controller, t_func=lambda value: value, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._t = t_func
        self.image_paths: list[str] = []
        self.current_image_path: str | None = None
        self.current_json_path: str | None = None
        self.current_data: dict[str, Any] | None = None
        self.current_regions: list[dict[str, Any]] = []
        self._dirty = False
        self._loading_table = False
        app_root = getattr(getattr(controller, "config_service", None), "root_dir", None) or os.getcwd()
        self.projects = OCRProjectRegistry(app_root)
        # Preserve existing folders from the old global list on first launch,
        # but register each as a distinct project rather than merging their pages.
        if not self.projects.folders:
            for source in list(getattr(controller, "source_files", []) or []):
                folder = source if os.path.isdir(source) else os.path.dirname(source)
                if folder and os.path.isdir(folder):
                    try:
                        self.projects.add(folder)
                    except (OSError, ValueError):
                        pass
        self._pending_render_signatures: dict[str, str] = {}
        self._pending_render_project: str | None = None

        self._build_ui()
        self._connect_signals()
        self.refresh_sources()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = CardWidget()
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(6)
        project_row = QHBoxLayout()
        project_row.setSpacing(6)
        self.project_title = BodyLabel("Dự án:")
        self.project_combo = ComboBox()
        self.project_combo.setMinimumWidth(270)
        self.remove_project_button = PushButton("Bỏ khỏi danh sách")
        self.open_output_button = PushButton("Mở ảnh đã render")
        project_row.addWidget(self.project_title)
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(self.remove_project_button)
        project_row.addWidget(self.open_output_button)

        source_row = QHBoxLayout()
        source_row.setSpacing(6)
        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)

        self.add_files_button = PushButton(self._t("Add Files"))
        self.add_files_button.setIcon(FIF.ADD)
        self.add_folder_button = PushButton("Thêm thư mục dự án")
        self.add_folder_button.setIcon(FIF.FOLDER_ADD)
        self.scan_button = PrimaryPushButton(self._t("Scan OCR Only"))
        self.scan_button.setIcon(FIF.DOCUMENT)
        self.refresh_button = PushButton(self._t("Refresh"))
        self.refresh_button.setIcon(FIF.SYNC)

        source_row.addWidget(self.add_files_button)
        source_row.addWidget(self.add_folder_button)
        source_row.addWidget(self.scan_button)
        source_row.addWidget(self.refresh_button)

        self.page_combo = ComboBox()
        self.page_combo.setMinimumWidth(220)
        source_row.addWidget(self.page_combo, 1)

        self.copy_all_button = PushButton(self._t("Copy All OCR"))
        self.copy_selected_button = PushButton(self._t("Copy Selected"))
        self.paste_batch_button = PushButton(self._t("Paste Batch"))
        self.save_button = PrimaryPushButton(self._t("Save JSON"))
        self.export_button = PushButton(self._t("Export Batch TXT"))
        self.render_batch_button = PushButton("Render trang đã đổi")
        self.render_current_button = PushButton("Render trang đang chọn")

        edit_row.addWidget(self.copy_all_button)
        edit_row.addWidget(self.copy_selected_button)
        edit_row.addWidget(self.paste_batch_button)
        edit_row.addStretch(1)
        edit_row.addWidget(self.save_button)
        edit_row.addWidget(self.export_button)
        edit_row.addWidget(self.render_current_button)
        edit_row.addWidget(self.render_batch_button)
        toolbar_layout.addLayout(project_row)
        toolbar_layout.addLayout(source_row)
        toolbar_layout.addLayout(edit_row)
        root.addWidget(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        text_card = CardWidget()
        text_layout = QVBoxLayout(text_card)
        text_layout.setContentsMargins(10, 8, 10, 10)
        text_layout.setSpacing(6)

        text_header = QHBoxLayout()
        self.text_title = BodyLabel(self._t("OCR / Translation Text"))
        self.text_title.setStyleSheet("font-weight: 600;")
        self.region_count_label = CaptionLabel("0 regions")
        text_header.addWidget(self.text_title)
        text_header.addStretch(1)
        text_header.addWidget(self.region_count_label)
        text_layout.addLayout(text_header)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", self._t("Original OCR"), self._t("Translation")])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 46)
        text_layout.addWidget(self.table, 1)

        self.copy_hint = CaptionLabel(
            self._t(
                "Copy All uses [001] markers. Translate outside the app, keep the markers, "
                "then copy the result and press Paste Batch."
            )
        )
        self.copy_hint.setWordWrap(True)
        text_layout.addWidget(self.copy_hint)

        image_card = CardWidget()
        image_layout = QVBoxLayout(image_card)
        image_layout.setContentsMargins(10, 8, 10, 10)
        image_layout.setSpacing(6)

        image_header = QHBoxLayout()
        self.image_title = BodyLabel(self._t("Original Image"))
        self.image_title.setStyleSheet("font-weight: 600;")
        self.image_path_label = CaptionLabel("")
        self.image_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        image_header.addWidget(self.image_title)
        image_header.addWidget(self.image_path_label, 1)
        image_layout.addLayout(image_header)

        self.preview = OCRImagePreview()
        image_layout.addWidget(self.preview, 1)

        self.splitter.addWidget(text_card)
        self.splitter.addWidget(image_card)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([620, 620])
        root.addWidget(self.splitter, 1)

        self.status_label = CaptionLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _connect_signals(self):
        self.add_files_button.clicked.connect(self._add_files)
        self.add_folder_button.clicked.connect(self._add_project_folder)
        self.remove_project_button.clicked.connect(self._remove_project)
        self.open_output_button.clicked.connect(self._open_output_folder)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        self.scan_button.clicked.connect(self._scan_project)
        self.refresh_button.clicked.connect(self.refresh_sources)
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.copy_all_button.clicked.connect(self.copy_all_ocr)
        self.copy_selected_button.clicked.connect(self.copy_selected)
        self.paste_batch_button.clicked.connect(self.paste_batch_from_clipboard)
        self.save_button.clicked.connect(self.save_current)
        self.export_button.clicked.connect(self.export_batch_txt)
        self.render_batch_button.clicked.connect(self._render_batch)
        self.render_current_button.clicked.connect(self._render_current)

        self.controller.file_sources_changed.connect(self.refresh_sources)
        self.controller.task_completed.connect(self._on_task_completed)
        self.controller.state_manager.is_translating_changed.connect(self._on_busy_changed)

    def _on_busy_changed(self, busy: bool):
        for widget in (
            self.scan_button, self.render_batch_button, self.render_current_button,
            self.project_combo, self.add_folder_button, self.remove_project_button,
            self.add_files_button, self.table, self.save_button,
        ):
            widget.setEnabled(not busy)
        self.scan_button.setText(
            self._t("Scanning OCR...") if busy else self._t("Scan OCR Only")
        )

    def _populate_project_combo(self):
        self.project_combo.blockSignals(True)
        try:
            self.project_combo.clear()
            for folder in self.projects.folders:
                label = os.path.basename(folder.rstrip(os.sep)) or folder
                self.project_combo.addItem(f"{label} — {folder}", userData=folder)
            if self.projects.active in self.projects.folders:
                self.project_combo.setCurrentIndex(
                    self.projects.folders.index(self.projects.active)
                )
        finally:
            self.project_combo.blockSignals(False)

    def _add_project_folder(self):
        if self.controller.state_manager.is_translating():
            return
        start = self.projects.active or self.controller.get_last_open_dir()
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục truyện / dự án", start)
        if not folder:
            return
        if self._dirty and not self.save_current():
            return
        try:
            self.projects.add(folder)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Dự án", str(exc))
            return
        self.controller.set_last_open_dir(folder)
        self.current_image_path = None
        self.refresh_sources()

    def _remove_project(self):
        if self.controller.state_manager.is_translating():
            return
        folder = self.projects.active
        if not folder:
            return
        if self._dirty and not self.save_current():
            return
        response = QMessageBox.question(
            self, "Bỏ dự án",
            f"Bỏ '{os.path.basename(folder)}' khỏi danh sách?\n"
            "Thao tác này KHÔNG xóa ảnh, JSON hoặc bản dịch trên ổ đĩa.",
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self.projects.remove(folder)
        self.current_image_path = None
        self.refresh_sources()

    def _open_output_folder(self):
        folder = self.projects.active
        if not folder:
            return
        output = self.projects.output_dir(folder)
        output.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output)))

    def _on_project_changed(self, index: int):
        folder = self.project_combo.itemData(index) if index >= 0 else None
        if not folder or self.controller.state_manager.is_translating():
            self._populate_project_combo()
            return
        if self._dirty and not self.save_current():
            self._populate_project_combo()
            return
        self.projects.select(folder)
        self.current_image_path = None
        self.refresh_sources()

    def _add_files(self):
        """Pick an existing image within the active folder; never mix projects."""
        folder = self.projects.active
        if not folder:
            QMessageBox.information(self, "Dự án", "Hãy chọn Thêm thư mục dự án trước.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._t("Add Files"), folder,
            self._t("Images") + " (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.avif *.heic *.heif)",
        )
        if not paths:
            return
        if any(not within(path, folder) for path in paths):
            QMessageBox.warning(
                self, "Dự án", "Ảnh phải nằm trong thư mục dự án hiện tại. "
                "Muốn làm việc với thư mục khác, hãy thêm một dự án riêng."
            )
            return
        if self._dirty and not self.save_current():
            return
        self.refresh_sources()
        selected = norm_path(paths[0])
        for idx, path in enumerate(self.image_paths):
            if norm_path(path) == selected:
                self.page_combo.setCurrentIndex(idx)
                break

    def _collect_source_images(self) -> list[str]:
        return self.projects.images(_IMAGE_EXTENSIONS)

    def _scan_project(self):
        if self._dirty and not self.save_current():
            return
        if not self.projects.active or not self.image_paths:
            QMessageBox.information(self, "OCR Workspace", "Hãy thêm thư mục chứa ảnh trước.")
            return
        self.controller.start_ocr_workspace_scan(
            project_images=list(self.image_paths), project_root=self.projects.active
        )

    def refresh_sources(self):
        # UI refreshes and folder changes must not discard unsaved edits.
        if self._dirty and not self.save_current():
            return
        previous = self.current_image_path
        self._populate_project_combo()
        self.image_paths = self._collect_source_images()

        self.page_combo.blockSignals(True)
        try:
            self.page_combo.clear()
            for index, path in enumerate(self.image_paths, start=1):
                self.page_combo.addItem(f"{index:03d}  {os.path.basename(path)}", userData=path)
            target_index = 0
            if previous:
                for index, path in enumerate(self.image_paths):
                    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(previous)):
                        target_index = index
                        break
            if self.image_paths:
                self.page_combo.setCurrentIndex(target_index)
        finally:
            self.page_combo.blockSignals(False)

        if self.image_paths:
            index = max(0, self.page_combo.currentIndex())
            self.load_page(self.image_paths[index])
        else:
            self._clear_page()
            self.status_label.setText(
                "Chọn Thêm thư mục dự án, sau đó bấm Scan OCR Only."
            )

    def _on_task_completed(self, _paths):
        if self._pending_render_project and getattr(self.controller, "last_completed_workflow", None) == "ocr_workspace_render":
            project = self._pending_render_project
            cache = self.projects.read_cache(project)
            for output in (_paths or []):
                source = self.controller.resolve_completed_source(output) if hasattr(self.controller, "resolve_completed_source") else None
                key = norm_path(source) if source else None
                if key in self._pending_render_signatures and os.path.isfile(output):
                    cache[key] = {"signature": self._pending_render_signatures[key], "output": os.path.abspath(output)}
            try:
                self.projects.store_cache(project, cache)
            except OSError as exc:
                self.status_label.setText(f"Không lưu được cache render: {exc}")
            self._pending_render_project = None
            self._pending_render_signatures.clear()
        if self._dirty and not self.save_current():
            return
        self.refresh_sources()
        if self.current_image_path:
            self.load_page(self.current_image_path, force=True)

    def _on_page_changed(self, index: int):
        if index < 0 or index >= len(self.image_paths):
            return
        if self._dirty and not self.save_current():
            # Keep the selected page and unsaved text intact when disk write fails.
            previous_index = self.image_paths.index(self.current_image_path) if self.current_image_path in self.image_paths else -1
            if previous_index >= 0:
                self.page_combo.blockSignals(True)
                self.page_combo.setCurrentIndex(previous_index)
                self.page_combo.blockSignals(False)
            return
        self.load_page(self.image_paths[index])

    def _clear_page(self):
        self.current_image_path = None
        self.current_json_path = None
        self.current_data = None
        self.current_regions = []
        self._loading_table = True
        try:
            self.table.setRowCount(0)
        finally:
            self._loading_table = False
        self.preview.set_image(None)
        self.image_path_label.setText("")
        self.region_count_label.setText("0 regions")
        self._dirty = False

    def load_page(self, image_path: str, force: bool = False):
        if not image_path:
            return
        if (
            not force
            and self.current_image_path
            and os.path.normcase(os.path.abspath(self.current_image_path))
            == os.path.normcase(os.path.abspath(image_path))
            and self.current_data is not None
        ):
            return

        self.current_image_path = image_path
        self.preview.set_image(image_path)
        self.image_path_label.setText(os.path.basename(image_path))

        json_path = find_json_path(image_path)
        self.current_json_path = json_path if json_path and os.path.isfile(json_path) else None
        self.current_data = None
        self.current_regions = []

        if self.current_json_path:
            try:
                with open(self.current_json_path, "r", encoding="utf-8") as handle:
                    self.current_data = json.load(handle)
                image_data = self._image_data(self.current_data)
                if image_data is not None:
                    regions = image_data.get("regions", [])
                    if isinstance(regions, list):
                        self.current_regions = regions
            except Exception as exc:
                self.status_label.setText(
                    self._t("Failed to load project JSON: {error}", error=str(exc))
                )

        self._populate_table()
        self._dirty = False

        if self.current_json_path:
            self.status_label.setText(
                self._t(
                    "Loaded {count} OCR regions. Edit Original/Translation directly or use Copy All → external translator → Paste Batch.",
                    count=len(self.current_regions),
                )
            )
        else:
            self.status_label.setText(
                self._t("No OCR project data for this page yet. Press Scan OCR Only.")
            )

    @staticmethod
    def _image_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        for value in data.values():
            if isinstance(value, dict) and isinstance(value.get("regions"), list):
                return value
        return None

    def _populate_table(self):
        self._loading_table = True
        try:
            self.table.setRowCount(len(self.current_regions))
            for row, region in enumerate(self.current_regions):
                number = QTableWidgetItem(str(row + 1))
                number.setFlags(number.flags() & ~Qt.ItemFlag.ItemIsEditable)
                number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                original = QTableWidgetItem(str(region.get("text") or ""))
                translation = QTableWidgetItem(str(region.get("translation") or ""))
                self.table.setItem(row, 0, number)
                self.table.setItem(row, 1, original)
                self.table.setItem(row, 2, translation)
                self.table.setRowHeight(row, 48)
        finally:
            self._loading_table = False
        self.region_count_label.setText(f"{len(self.current_regions)} regions")
        if self.current_regions:
            self.table.selectRow(0)
            self.preview.highlight_region(self.current_regions[0])
        else:
            self.preview.highlight_region(None)

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading_table or item.column() == 0:
            return
        row = item.row()
        if row < 0 or row >= len(self.current_regions):
            return
        region = self.current_regions[row]
        if item.column() == 1:
            region["text"] = item.text()
            texts = region.get("texts")
            if isinstance(texts, list):
                if texts:
                    texts[0] = item.text()
                else:
                    region["texts"] = [item.text()]
            else:
                region["texts"] = [item.text()]
        elif item.column() == 2:
            old = str(region.get("translation") or "")
            new = item.text()
            region["translation"] = new
            region["translation_raw"] = new
            if old != new:
                region.pop("translation_rich", None)
        self._dirty = True
        self.save_button.setText(self._t("Save JSON") + " *")

    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.preview.highlight_region(None)
            return
        row = rows[0].row()
        region = self.current_regions[row] if 0 <= row < len(self.current_regions) else None
        self.preview.highlight_region(region)

    def copy_all_ocr(self):
        if not self.current_regions:
            return
        text = "\n".join(
            f"[{index:03d}] {str(region.get('text') or '').replace(chr(10), ' ').strip()}"
            for index, region in enumerate(self.current_regions, start=1)
        )
        QApplication.clipboard().setText(text)
        self.status_label.setText(
            self._t("Copied {count} OCR regions to clipboard.", count=len(self.current_regions))
        )

    def copy_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if row < 0 or row >= len(self.current_regions):
            return
        text = str(self.current_regions[row].get("text") or "")
        QApplication.clipboard().setText(text)
        self.status_label.setText(self._t("Selected OCR text copied."))

    @staticmethod
    def _parse_batch_translation(text: str) -> dict[int, str] | list[str]:
        marker = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
        blocks: dict[int, list[str]] = {}
        current: int | None = None
        saw_marker = False
        for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            match = marker.match(raw_line)
            if match:
                saw_marker = True
                current = int(match.group(1)) - 1
                blocks.setdefault(current, [])
                first = match.group(2).strip()
                if first:
                    blocks[current].append(first)
                continue
            if saw_marker and current is not None:
                line = raw_line.strip()
                if line:
                    blocks[current].append(line)

        if saw_marker:
            return {
                index: " ".join(lines).strip()
                for index, lines in blocks.items()
                if " ".join(lines).strip()
            }

        return [
            line.strip()
            for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        ]

    def paste_batch_from_clipboard(self):
        if not self.current_regions:
            return
        raw = QApplication.clipboard().text()
        if not raw.strip():
            QMessageBox.information(self, self._t("Paste Batch"), self._t("Clipboard is empty."))
            return

        parsed = self._parse_batch_translation(raw)
        # Without explicit [001] markers, only an exact one-line-per-region
        # match is safe. Partial imports would silently shift character dialog.
        if isinstance(parsed, list) and len(parsed) != len(self.current_regions):
            QMessageBox.warning(
                self,
                self._t("Paste Batch"),
                self._t(
                    "Pasted {count} unnumbered lines, but this page has {regions} regions. "
                    "Nothing was changed. Keep [001] markers or paste exactly one line per region.",
                    count=len(parsed), regions=len(self.current_regions),
                ),
            )
            return
        if isinstance(parsed, dict):
            invalid_indices = [idx for idx in parsed if not 0 <= idx < len(self.current_regions)]
            if invalid_indices:
                QMessageBox.warning(
                    self,
                    self._t("Paste Batch"),
                    self._t(
                        "Some [ID] markers do not match this page. Nothing was changed. "
                        "Keep the original [001], [002] markers for the current page."
                    ),
                )
                return
        applied = 0

        self._loading_table = True
        try:
            if isinstance(parsed, dict):
                for row, translation in parsed.items():
                    if 0 <= row < len(self.current_regions):
                        self.current_regions[row]["translation"] = translation
                        self.current_regions[row]["translation_raw"] = translation
                        self.current_regions[row].pop("translation_rich", None)
                        item = self.table.item(row, 2)
                        if item is not None:
                            item.setText(translation)
                        applied += 1
            else:
                for row, translation in enumerate(parsed[: len(self.current_regions)]):
                    self.current_regions[row]["translation"] = translation
                    self.current_regions[row]["translation_raw"] = translation
                    self.current_regions[row].pop("translation_rich", None)
                    item = self.table.item(row, 2)
                    if item is not None:
                        item.setText(translation)
                    applied += 1
        finally:
            self._loading_table = False

        if applied:
            self._dirty = True
            self.save_button.setText(self._t("Save JSON") + " *")
        self.status_label.setText(
            self._t("Pasted {count} translations from clipboard.", count=applied)
        )

    def save_current(self, silent: bool = False):
        if not self.current_json_path or not self.current_data:
            if not silent:
                QMessageBox.information(
                    self,
                    self._t("Save JSON"),
                    self._t("This page has no OCR project JSON yet. Run Scan OCR Only first."),
                )
            return False

        if not self._dirty:
            self.status_label.setText(self._t("Project JSON saved."))
            return True
        image_data = self._image_data(self.current_data)
        if image_data is None:
            return False
        image_data["regions"] = self.current_regions
        image_data["skip_font_scaling"] = False

        tmp_path = self.current_json_path + ".ocr_workspace.tmp"
        backup_path = self.current_json_path + ".ocr_workspace.bak"
        try:
            if os.path.isfile(self.current_json_path):
                shutil.copy2(self.current_json_path, backup_path)
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(self.current_data, handle, ensure_ascii=False, indent=4)
            os.replace(tmp_path, self.current_json_path)
            self._dirty = False
            self.save_button.setText(self._t("Save JSON"))
            self.status_label.setText(self._t("Project JSON saved."))
            return True
        except Exception as exc:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            if not silent:
                QMessageBox.critical(
                    self,
                    self._t("Save JSON"),
                    self._t("Failed to save project JSON: {error}", error=str(exc)),
                )
            return False



    def _render_batch(self):
        self._render_pages(only_current=False)

    def _render_current(self):
        self._render_pages(only_current=True)

    def _render_pages(self, *, only_current: bool):
        """Reuse successful exports and only render changed JSON / render settings."""
        if self.controller.state_manager.is_translating():
            return
        if self._dirty and not self.save_current():
            return
        folder = self.projects.active
        if not folder:
            QMessageBox.information(self, "OCR Workspace", "Hãy chọn dự án trước.")
            return
        settings = self.controller.config_service.get_config().model_dump()
        config_digest = render_config_digest(settings)
        cache = self.projects.read_cache(folder)
        images = [self.current_image_path] if only_current else self.image_paths
        candidates = []
        signatures = {}
        skipped = 0
        for image in images:
            if not image or not within(image, folder):
                continue
            json_path = find_json_path(image)
            if not json_path or not os.path.isfile(json_path):
                continue
            try:
                signature = render_signature(image, json_path, config_digest)
            except OSError:
                continue
            # Force the selected page on explicit user request; batch uses cache.
            if not only_current and self.projects.cached(cache, image, signature):
                skipped += 1
                continue
            candidates.append(image)
            signatures[norm_path(image)] = signature
        if not candidates:
            self.status_label.setText(
                f"Không có trang cần render. {skipped} trang đã có kết quả cập nhật."
            )
            return
        self._pending_render_project = folder
        self._pending_render_signatures = signatures
        self.status_label.setText(
            f"Đang render {len(candidates)} trang của '{os.path.basename(folder)}'; "
            f"bỏ qua {skipped} trang không đổi."
        )
        self.controller.start_ocr_workspace_render(
            project_images=candidates, project_root=folder
        )

    def export_batch_txt(self):
        if self._dirty and not self.save_current():
            return

        initial_dir = str(self.projects.output_dir(self.projects.active)) if self.projects.active else self.controller.config_service.root_dir
        os.makedirs(initial_dir, exist_ok=True)
        default_path = os.path.join(initial_dir, "ocr_workspace_batch.txt")
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("Export Batch TXT"),
            default_path,
            "Text Files (*.txt)",
        )
        if not output_path:
            return

        pages_written = 0
        regions_written = 0
        chunks: list[str] = []

        for page_number, image_path in enumerate(self.image_paths, start=1):
            json_path = find_json_path(image_path)
            if not json_path or not os.path.isfile(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                image_data = self._image_data(data)
                if image_data is None:
                    continue
                regions = image_data.get("regions", [])
                chunks.append(f"=== PAGE {page_number:03d}: {os.path.basename(image_path)} ===")
                for index, region in enumerate(regions, start=1):
                    original = str(region.get("text") or "").replace("\n", " ").strip()
                    translation = str(region.get("translation") or "").replace("\n", " ").strip()
                    chunks.append(f"[{index:03d}] {original}")
                    chunks.append(f"=> {translation}")
                    regions_written += 1
                chunks.append("")
                pages_written += 1
            except Exception:
                continue

        try:
            with open(output_path, "w", encoding="utf-8-sig") as handle:
                handle.write("\n".join(chunks))
            self.status_label.setText(
                self._t(
                    "Exported {pages} pages / {regions} regions to {path}",
                    pages=pages_written,
                    regions=regions_written,
                    path=output_path,
                )
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                self._t("Export Batch TXT"),
                self._t("Export failed: {error}", error=str(exc)),
            )

    def apply_theme(self):
        self.preview.setBackgroundBrush(QBrush(self.palette().base()))
        self.update()


def create_ocr_workspace_page(self) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(18, 16, 18, 14)
    layout.setSpacing(10)

    header = CardWidget()
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(16, 12, 16, 12)
    header_layout.setSpacing(4)
    self.ocr_workspace_page_title_label = TitleLabel(self._t("OCR Workspace"))
    self.ocr_workspace_page_subtitle_label = BodyLabel(
        self._t(
            "Quản lý nhiều dự án theo thư mục riêng. Quét OCR, copy sang Google Dịch, "
            "dán/sửa bản dịch, rồi render những trang đã thay đổi."
        )
    )
    self.ocr_workspace_page_subtitle_label.setWordWrap(True)
    header_layout.addWidget(self.ocr_workspace_page_title_label)
    header_layout.addWidget(self.ocr_workspace_page_subtitle_label)
    layout.addWidget(header)

    self.ocr_workspace_panel = OCRWorkspacePanel(
        controller=self.controller,
        t_func=self._t,
    )
    layout.addWidget(self.ocr_workspace_panel, 1)
    return page
