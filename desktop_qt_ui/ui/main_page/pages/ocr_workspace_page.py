from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from typing import Any

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QBrush, QPainter, QPen, QPixmap
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



def _hymt_workspace_indices(
    regions: list[dict[str, Any]], *, overwrite: bool = False
) -> list[int]:
    """Only translate regions with source text; preserve completed work by default."""
    return [
        index
        for index, region in enumerate(regions)
        if str(region.get("text") or "").strip()
        and (overwrite or not str(region.get("translation") or "").strip())
    ]


def _apply_hymt_workspace_results(
    regions: list[dict[str, Any]],
    indices: list[int],
    translations: list[str],
) -> int:
    """Map each output to its original OCR region, preserving geometry and masks."""
    if len(indices) != len(translations):
        raise ValueError("Hy-MT2 result count does not match OCR regions")
    if len(set(indices)) != len(indices):
        raise ValueError("Duplicate region indices from Hy-MT2")
    if any(not 0 <= index < len(regions) for index in indices):
        raise ValueError("Invalid OCR region index in Hy-MT2 results")
    if any(not isinstance(text, str) or not text.strip() for text in translations):
        raise ValueError("Hy-MT2 returned an empty translation; nothing was changed")

    count = 0
    for index, value in zip(indices, translations):
        region = regions[index]
        changed = str(region.get("translation") or "") != value.strip()
        region["translation"] = value.strip()
        region["translation_raw"] = value.strip()
        if changed:
            region.pop("translation_rich", None)
        count += 1
    return count


class OCRWorkspacePanel(QWidget):
    """Fast OCR workspace with manual editing and optional local Hy-MT2.

    Image rendering remains a separate explicit action: translated text is
    saved to project JSON and only Render Batch modifies exported images.
    """

    _hymt_result_ready = pyqtSignal(object)
    _hymt_failed = pyqtSignal(str)

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
        self._hymt_busy = False
        self._hymt_thread = None

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
        source_row = QHBoxLayout()
        source_row.setSpacing(6)
        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)

        self.add_files_button = PushButton(self._t("Add Files"))
        self.add_files_button.setIcon(FIF.ADD)
        self.add_folder_button = PushButton(self._t("Add Folder"))
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
        self.hy_translate_button = PushButton("Dịch bằng Hy-MT2")
        self.hy_translate_button.setToolTip(
            "Dịch OCR của trang hiện tại bằng model GGUF trên máy. "
            "Sau khi sửa bản dịch, chọn Render Batch để thay chữ trên ảnh."
        )
        self.save_button = PrimaryPushButton(self._t("Save JSON"))
        self.export_button = PushButton(self._t("Export Batch TXT"))
        self.render_batch_button = PushButton(self._t("Render Batch"))

        edit_row.addWidget(self.copy_all_button)
        edit_row.addWidget(self.copy_selected_button)
        edit_row.addWidget(self.paste_batch_button)
        edit_row.addWidget(self.hy_translate_button)
        edit_row.addStretch(1)
        edit_row.addWidget(self.save_button)
        edit_row.addWidget(self.export_button)
        edit_row.addWidget(self.render_batch_button)
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
        self.add_folder_button.clicked.connect(self.controller.add_folder)
        self.scan_button.clicked.connect(self.controller.start_ocr_workspace_scan)
        self.refresh_button.clicked.connect(self.refresh_sources)
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.copy_all_button.clicked.connect(self.copy_all_ocr)
        self.copy_selected_button.clicked.connect(self.copy_selected)
        self.paste_batch_button.clicked.connect(self.paste_batch_from_clipboard)
        self.hy_translate_button.clicked.connect(self.translate_current_page_hymt2)
        self._hymt_result_ready.connect(self._on_hymt_result)
        self._hymt_failed.connect(self._on_hymt_failure)
        self.save_button.clicked.connect(self.save_current)
        self.export_button.clicked.connect(self.export_batch_txt)
        self.render_batch_button.clicked.connect(self._render_batch)

        self.controller.file_sources_changed.connect(self.refresh_sources)
        self.controller.task_completed.connect(self._on_task_completed)
        self.controller.state_manager.is_translating_changed.connect(self._on_busy_changed)

    def _on_busy_changed(self, busy: bool):
        self.scan_button.setEnabled(not (busy or self._hymt_busy))
        self.render_batch_button.setEnabled(not (busy or self._hymt_busy))
        self.hy_translate_button.setEnabled(not (busy or self._hymt_busy))
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
        # UI refreshes and folder changes must not discard unsaved edits.
        if self._dirty and not self.save_current():
            return
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



    def _set_hymt_busy(self, busy: bool):
        self._hymt_busy = busy
        for widget in (
            self.table, self.page_combo, self.add_files_button,
            self.add_folder_button, self.refresh_button,
            self.copy_all_button, self.copy_selected_button,
            self.paste_batch_button, self.save_button, self.export_button,
        ):
            widget.setEnabled(not busy)
        state = getattr(self.controller, "state_manager", None)
        translating = bool(state.is_translating()) if callable(getattr(state, "is_translating", None)) else False
        self._on_busy_changed(translating)
        self.hy_translate_button.setText(
            "Hy-MT2 đang dịch..." if busy else "Dịch bằng Hy-MT2"
        )

    def translate_current_page_hymt2(self):
        """Translate OCR text asynchronously without damaging previous region edits."""
        if self._hymt_busy:
            return
        if not self.current_json_path or not self.current_regions:
            QMessageBox.information(
                self, "OCR Workspace",
                "Chưa có vùng OCR. Hãy bấm Scan OCR Only trước."
            )
            return
        state = getattr(self.controller, "state_manager", None)
        if callable(getattr(state, "is_translating", None)) and state.is_translating():
            QMessageBox.information(
                self, "OCR Workspace", "Đang có tác vụ khác. Hãy hoàn thành tác vụ đó trước."
            )
            return

        overwrite = False
        filled = any(str(region.get("translation") or "").strip() for region in self.current_regions)
        if filled:
            answer = QMessageBox.question(
                self, "Dịch bằng Hy-MT2",
                "Trang đã có bản dịch.\n\n"
                "Yes: dịch lại và thay thế TẤT CẢ bản dịch hiện có.\n"
                "No: chỉ dịch các ô Translation còn trống.\n"
                "Cancel: không thay đổi gì.",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            overwrite = answer == QMessageBox.StandardButton.Yes

        indices = _hymt_workspace_indices(self.current_regions, overwrite=overwrite)
        if not indices:
            QMessageBox.information(
                self, "Dịch bằng Hy-MT2",
                "Không có ô Translation còn trống. Chọn Yes để dịch lại toàn bộ."
            )
            return

        if self._dirty and not self.save_current():
            return

        try:
            settings = self.controller.config_service.get_config()
        except (AttributeError, RuntimeError) as exc:
            QMessageBox.warning(self, "Hy-MT2", f"Không đọc được cấu hình ứng dụng: {exc}")
            return
        if settings.translator.target_lang != "VIN":
            QMessageBox.warning(
                self, "Hy-MT2",
                "Chức năng này dịch sang tiếng Việt. "
                "Hãy chọn Target Language = VIN trong Settings → Translation."
            )
            return

        manager = getattr(QApplication.instance(), "_hymt2_manager", None)
        if manager is not None:
            # An explicit translation click starts the local server even when
            # another translator is selected in normal Translation settings.
            manager.ensure_async(settings, force=True)

        texts = [str(self.current_regions[i].get("text") or "") for i in indices]
        self._hymt_busy_indices = indices
        self._hymt_busy_page = self.current_image_path
        self._set_hymt_busy(True)
        self.status_label.setText(
            f"Hy-MT2 đang dịch {len(indices)} vùng OCR. Không cần mở server riêng."
        )

        def translate():
            try:
                from manga_translator.translators.local_hymt2 import LocalHyMT2Translator

                engine = LocalHyMT2Translator()
                engine.parse_args(settings)
                # The server may need time to download/load GGUF the first time.
                # Wait in a daemon thread, never freeze the Qt event loop.
                max_wait = max(20, int(engine.timeout))
                deadline = time.monotonic() + max_wait
                while True:
                    try:
                        engine._resolve_model_name()
                        break
                    except Exception:
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Hy-MT2 chưa sẵn sàng. Kiểm tra result/hymt2-server.log "
                                "hoặc chạy Win-Start-HyMT2.bat để xem lỗi tải/nạp model."
                            )
                        time.sleep(2)
                translations = engine._translate_sync("auto", "Vietnamese", texts)
                self._hymt_result_ready.emit(translations)
            except Exception as exc:
                self._hymt_failed.emit(str(exc))

        self._hymt_thread = threading.Thread(
            target=translate, name="ocr-workspace-hymt2", daemon=True,
        )
        self._hymt_thread.start()

    def _on_hymt_result(self, translations: list[str]):
        indices = list(getattr(self, "_hymt_busy_indices", []))
        page = getattr(self, "_hymt_busy_page", None)
        try:
            if page != self.current_image_path:
                raise RuntimeError("Trang ảnh đã thay đổi khi Hy-MT2 đang chạy.")
            count = _apply_hymt_workspace_results(
                self.current_regions, indices, translations
            )
            self._loading_table = True
            try:
                for index in indices:
                    cell = self.table.item(index, 2)
                    if cell is not None:
                        cell.setText(str(self.current_regions[index]["translation"]))
            finally:
                self._loading_table = False
            self._dirty = True
            self.save_button.setText(self._t("Save JSON") + " *")
            if self.save_current(silent=True):
                self.status_label.setText(
                    f"Đã dịch và lưu {count} vùng. "
                    "Sửa cột Translation nếu cần, rồi bấm Render Batch để thay chữ lên ảnh."
                )
            else:
                self.status_label.setText(
                    "Đã dịch nhưng không lưu được JSON. Hãy bấm Save JSON trước khi render."
                )
        except Exception as exc:
            QMessageBox.warning(self, "Hy-MT2", str(exc))
            self.status_label.setText(f"Lỗi Hy-MT2: {exc}")
        finally:
            self._hymt_busy_indices = []
            self._hymt_busy_page = None
            self._set_hymt_busy(False)

    def _on_hymt_failure(self, error: str):
        self._hymt_busy_indices = []
        self._hymt_busy_page = None
        self._set_hymt_busy(False)
        self.status_label.setText(f"Hy-MT2: {error}")
        QMessageBox.warning(self, "Dịch bằng Hy-MT2", error)

    def _render_batch(self):
        if self._dirty and not self.save_current():
            return
        self.controller.start_ocr_workspace_render()

    def export_batch_txt(self):
        if self._dirty and not self.save_current():
            return

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
