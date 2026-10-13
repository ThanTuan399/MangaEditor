from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

from manga_editor.domain.geometry import Rect


@dataclass(frozen=True, slots=True)
class OcrCrop:
    png_bytes: bytes
    image: QImage
    rect: Rect


def crop_raw_to_png(raw_bytes: bytes, rect: Rect) -> OcrCrop:
    image = QImage.fromData(raw_bytes)
    if image.isNull():
        raise ValueError("Không đọc được ảnh raw để cắt vùng OCR.")

    safe = rect.clamp(image.width(), image.height())
    if safe.is_empty():
        raise ValueError("Vùng OCR rỗng.")

    x = max(0, int(round(safe.x)))
    y = max(0, int(round(safe.y)))
    right = min(image.width(), int(round(safe.x + safe.width)))
    bottom = min(image.height(), int(round(safe.y + safe.height)))
    cropped = image.copy(x, y, max(1, right - x), max(1, bottom - y))

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("Không tạo được bộ đệm ảnh OCR.")
    if not cropped.save(buffer, "PNG"):
        raise ValueError("Không mã hóa được ảnh cắt OCR.")
    return OcrCrop(bytes(buffer.data()), cropped, safe)
