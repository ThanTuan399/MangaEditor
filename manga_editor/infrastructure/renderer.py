from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import LayerKind, Page


def _rect_from_payload(payload: dict) -> Rect:
    rect = Rect.from_dict(payload.get("rect"))
    if rect is None:
        raise ValueError("Layer thiếu phạm vi rect.")
    return rect


def render_page(page: Page, raw_bytes: bytes) -> QImage:
    """Dựng preview/ảnh xuất từ raw + các layer, không ghi đè raw."""
    image = QImage.fromData(raw_bytes)
    if image.isNull():
        raise ValueError("Không đọc được ảnh raw để dựng trang.")
    image = image.convertToFormat(QImage.Format.Format_ARGB32)

    painter = QPainter(image)
    try:
        # V0.1 cố định thứ tự: nền trước, chữ sau. GUIDE không đi vào ảnh thành phẩm.
        for layer in page.layers:
            if not layer.visible or layer.kind != LayerKind.BACKGROUND_PATCH:
                continue
            rect = _rect_from_payload(layer.payload)
            painter.fillRect(
                QRectF(rect.x, rect.y, rect.width, rect.height),
                QColor(layer.payload.get("color", "#ffffff")),
            )

        for layer in page.layers:
            if not layer.visible or layer.kind != LayerKind.VIETNAMESE_TEXT:
                continue
            rect = _rect_from_payload(layer.payload)
            font = QFont(layer.payload.get("family", "Arial"))
            font.setPixelSize(max(6, int(layer.payload.get("size", 32))))
            painter.setFont(font)
            painter.setPen(QColor(layer.payload.get("color", "#000000")))

            align_name = layer.payload.get("align", "center")
            horizontal = {
                "left": Qt.AlignmentFlag.AlignLeft,
                "center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight,
            }.get(align_name, Qt.AlignmentFlag.AlignHCenter)
            flags = horizontal | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap
            painter.drawText(
                QRectF(rect.x, rect.y, rect.width, rect.height),
                int(flags),
                str(layer.payload.get("content", "")),
            )
    finally:
        painter.end()
    return image


def save_rendered_page(page: Page, raw_bytes: bytes, filename: str, quality: int = -1) -> bool:
    image = render_page(page, raw_bytes)
    return image.save(filename, quality=quality)
