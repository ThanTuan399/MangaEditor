from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage


@dataclass(frozen=True, slots=True)
class ImageSegment:
    png_bytes: bytes
    x: int
    width: int


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def segment_vertical_columns(
    image_bytes: bytes,
    *,
    ink_threshold: int = 190,
    max_columns: int = 10,
) -> list[ImageSegment]:
    """Tách cột chữ từ phải sang trái bằng projection đơn giản.

    Chỉ dùng như bước chuẩn bị cho Tesseract chữ Nhật dọc. Nếu phát hiện
    không chắc chắn, trả lại một segment toàn ảnh thay vì cố chia sai.
    """
    image = QImage.fromData(image_bytes)
    if image.isNull():
        raise ValueError("Không đọc được ảnh để tách cột dọc.")
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)

    min_ink = max(2, int(gray.height() * 0.02))
    active = []
    for x in range(gray.width()):
        count = 0
        for y in range(gray.height()):
            if gray.pixelColor(x, y).red() < ink_threshold:
                count += 1
        active.append(count >= min_ink)

    groups: list[list[int]] = []
    start = None
    for x, is_active in enumerate(active):
        if is_active and start is None:
            start = x
        elif not is_active and start is not None:
            groups.append([start, x - 1])
            start = None
    if start is not None:
        groups.append([start, gray.width() - 1])

    merge_gap = max(3, int(gray.width() * 0.012))
    merged: list[list[int]] = []
    for group in groups:
        if merged and group[0] - merged[-1][1] - 1 <= merge_gap:
            merged[-1][1] = group[1]
        else:
            merged.append(group)

    min_width = max(4, int(gray.width() * 0.018))
    merged = [g for g in merged if g[1] - g[0] + 1 >= min_width]

    if len(merged) < 2 or len(merged) > max_columns:
        return [ImageSegment(_encode_png(image), 0, image.width())]

    padding = max(3, int(gray.width() * 0.01))
    segments: list[ImageSegment] = []
    for left, right in sorted(merged, key=lambda g: g[0], reverse=True):
        x0 = max(0, left - padding)
        x1 = min(image.width(), right + padding + 1)
        crop = image.copy(x0, 0, max(1, x1 - x0), image.height())
        segments.append(
            ImageSegment(_encode_png(crop), x0, crop.width())
        )
    return segments
