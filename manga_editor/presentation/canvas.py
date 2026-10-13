from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView

from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import Page


AREA_STYLE = {
    "ocr_area": ("#27c281", "OCR"),
    "cleanup_area": ("#ff5c5c", "Xóa"),
    "text_frame": ("#3b82f6", "Chữ"),
}


class CanvasView(QGraphicsView):
    areaDrawn = Signal(str, object)
    regionSelected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#202631"))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.page: Page | None = None
        self.active_region_id: str | None = None
        self.area_kind = "ocr_area"
        self.draw_once = False
        self._start: QPointF | None = None
        self._rubber: QGraphicsRectItem | None = None

    def set_page(self, page: Page | None, image_bytes: bytes | None, active_region_id: str | None = None) -> None:
        self.page = page
        self.active_region_id = active_region_id
        self.scene().clear()
        self._rubber = None
        if page is None or image_bytes is None:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_bytes):
            raise ValueError("Không hiển thị được ảnh raw trong dự án.")
        self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(QRectF(0, 0, page.width, page.height))
        self._draw_regions()

    def _draw_regions(self) -> None:
        if self.page is None:
            return
        for region in sorted(self.page.regions, key=lambda x: x.order):
            active = region.id == self.active_region_id
            for area_kind, (color_text, label) in AREA_STYLE.items():
                rect: Rect | None = getattr(region, area_kind)
                if rect is None:
                    continue
                pen = QPen(QColor(color_text), 3 if active else 1, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                item = self.scene().addRect(rect.x, rect.y, rect.width, rect.height, pen)
                item.setData(0, region.id)
                item.setData(1, area_kind)
                text = self.scene().addText(f"{region.name} · {label}")
                text.setDefaultTextColor(QColor(color_text))
                text.setPos(rect.x, max(0, rect.y - 22))

    def set_draw_mode(self, area_kind: str) -> None:
        if area_kind not in AREA_STYLE:
            raise ValueError(area_kind)
        self.area_kind = area_kind
        self.draw_once = True
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def cancel_draw(self) -> None:
        self.draw_once = False
        self._start = None
        if self._rubber is not None:
            self.scene().removeItem(self._rubber)
            self._rubber = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_scale = self.transform().m11() * factor
        if 0.05 <= new_scale <= 20:
            self.scale(factor, factor)
        event.accept()

    def fit_page(self) -> None:
        if self.page is not None:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event):
        if self.draw_once and event.button() == Qt.MouseButton.LeftButton and self.page is not None:
            point = self._clamped_scene_point(event.position())
            self._start = point
            color = QColor(AREA_STYLE[self.area_kind][0])
            pen = QPen(color, 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._rubber = self.scene().addRect(QRectF(point, point), pen)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.draw_once:
            item = self.itemAt(event.position().toPoint())
            while item is not None:
                region_id = item.data(0)
                if region_id:
                    self.regionSelected.emit(str(region_id))
                    event.accept()
                    return
                item = item.parentItem()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.draw_once and self._start is not None and self._rubber is not None:
            point = self._clamped_scene_point(event.position())
            self._rubber.setRect(QRectF(self._start, point).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.draw_once and self._start is not None and event.button() == Qt.MouseButton.LeftButton:
            end = self._clamped_scene_point(event.position())
            rect = Rect.from_points(self._start.x(), self._start.y(), end.x(), end.y())
            area_kind = self.area_kind
            self.cancel_draw()
            if not rect.is_empty():
                self.areaDrawn.emit(area_kind, rect)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _clamped_scene_point(self, viewport_position) -> QPointF:
        point = self.mapToScene(viewport_position.toPoint())
        if self.page is None:
            return point
        return QPointF(
            min(max(0.0, point.x()), float(self.page.width)),
            min(max(0.0, point.y()), float(self.page.height)),
        )
