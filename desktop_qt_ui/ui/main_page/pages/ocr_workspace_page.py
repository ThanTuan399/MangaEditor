from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
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
    """Fast OCR -> manual/external translation workspace.

    The panel intentionally does not run translation, inpainting, or rendering.
    It edits MangaEditor's project JSON directly so users can copy OCR text to
    any external translator and paste the result back by region number.
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

        self._build_ui()
        self._connect_signals()
        self.refresh_sources()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = CardWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(6)

        self.add_files_button = PushButton(self._t("Add Files"))
        self.add_files_button.setIcon(FIF.ADD)
        self.add_folder_button = PushButton(self._t("Add Folder"))
        self.add_folder_button.setIcon(FIF.FOLDER_ADD)
        self.scan_button = PrimaryPushButton(self._t("Scan OCR Only"))
        self.scan_button.setIcon(FIF.SEARCH)
        self.refresh_button = PushButton(self._t("Refresh"))
        self.refresh_button.setIcon(FIF.SYNC)

        toolbar_layout.addWidget(self.add_files_button)
        toolbar_layout.addWidget(self.add_folder_button)
        toolbar_layout.addWidget(self.scan_button)
        toolbar_layout.addWidget(self.refresh_button)

        self.page_combo = ComboBox()
        self.page_combo.setMinimumWidth(220)
        toolbar_layout.addWidget(self.page_combo, 1)

        self.copy_all_button = PushButton(self._t("Copy All OCR"))
        self.copy_selected_button = PushButton(self._t("Copy Selected"))
        self.paste_batch_button = PushButton(self._t("Paste Batch"))
        self.save_button = PrimaryPushButton(self._t("Save JSON"))
        self.export_button = PushButton(self._t("Export Batch TXT"))

        toolbar_layout.addWidget(self.copy_all_button)
        toolbar_layout.addWidget(self.copy_selected_button)
        toolbar_layout.addWidget(self.paste_batch_button)
        toolbar_layout.addWidget(self.save_button)
        toolbar_layout.addWidget(self.export_button)
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
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
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
        self.add_folder_button.clicked.connect(self.controller.add_folder)
        self.scan_button.clicked.connect(self.controller.start_ocr_workspace_scan)
        self.refresh_button.clicked.connect(self.refresh_sources)
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.copy_all_button.clicked.connect(self.copy_all_ocr)
        self.copy_selected_button.clicked.connect(self.copy_selected)
        self.paste_batch_button.clicked.connect(self.paste_batch_from_clipboard)
        self.save_button.clicked.connect(self.save_current)
        self.export_button.clicked.connect(self.export_batch_txt)

        self.controller.file_sources_changed.connect(self.refresh_sources)
        self.controller.task_completed.connect(self._on_task_completed)
        self.controller.state_manager.is_translating_changed.connect(self._on_busy_changed)

    def _on_busy_changed(self, busy: bool):
        self.scan_button.setEnabled(not busy)
        self.scan_button.setText(
            self._t("Scanning OCR...") if busy else self._t("Scan OCR Only")
        )

    def _add_files(self):
        start_dir = self.controller.get_last_open_dir()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._t("Add Files"),
            start_dir,
            self._t("Images") + " (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.avif *.heic *.heif)",
        )
        if paths:
            self.controller.set_last_open_dir(os.path.dirname(paths[0]))
            self.controller.add_files(paths)

    def _collect_source_images(self) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for source in list(getattr(self.controller, "source_files", []) or []):
            path = os.path.normpath(source)
            if os.path.isfile(path):
                if os.path.splitext(path)[1].lower() in _IMAGE_EXTENSIONS:
                    key = os.path.normcase(os.path.abspath(path))
                    if key not in seen:
                        seen.add(key)
                        result.append(path)
                continue
            if not os.path.isdir(path):
                continue
            for root, dirs, files in os.walk(path):
                dirs[:] = [
                    name for name in dirs
                    if name not in {"manga_translator_work", ".git", "__pycache__"}
                ]
                for name in files:
                    candidate = os.path.join(root, name)
                    if os.path.splitext(name)[1].lower() not in _IMAGE_EXTENSIONS:
                        continue
                    key = os.path.normcase(os.path.abspath(candidate))
                    if key not in seen:
                        seen.add(key)
                        result.append(candidate)
        result.sort(key=lambda p: p.lower())
        return result

    def refresh_sources(self):
        previous = self.current_image_path
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
                self._t("Add images/folders to the main file list, then press Scan OCR Only.")
            )

    def _on_task_completed(self, _paths):
        self.refresh_sources()
        if self.current_image_path:
            self.load_page(self.current_image_path, force=True)

    def _on_page_changed(self, index: int):
        if index < 0 or index >= len(self.image_paths):
            return
        if self._dirty:
            self.save_current(silent=True)
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

    def export_batch_txt(self):
        if self._dirty:
            self.save_current(silent=True)

        config = self.controller.config_service.get_config()
        initial_dir = config.app.last_output_path or self.controller.config_service.root_dir
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
            "Fast manual-translation workspace: scan OCR only, copy text to any external translator, "
            "paste/edit translations, compare against the raw page, and export text in batches."
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
