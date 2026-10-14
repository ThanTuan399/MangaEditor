from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter


PROFILES = {
    "original": "Ảnh gốc",
    "upscale2x": "Phóng 2×",
    "contrast": "Tương phản tự động",
    "manga_clean": "Manga sạch: xám + tương phản + 2× + viền trắng",
}


@dataclass(frozen=True, slots=True)
class PreparedImage:
    png_bytes: bytes
    image: QImage
    profile: str
    metadata: dict


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("Không tạo được bộ đệm ảnh OCR.")
    if not image.save(buffer, "PNG"):
        raise ValueError("Không mã hóa được ảnh OCR.")
    return bytes(buffer.data())


def _load(image_bytes: bytes) -> QImage:
    image = QImage.fromData(image_bytes)
    if image.isNull():
        raise ValueError("Không đọc được ảnh OCR.")
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def _auto_contrast(image: QImage) -> QImage:
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    histogram = [0] * 256
    for y in range(gray.height()):
        for x in range(gray.width()):
            histogram[gray.pixelColor(x, y).red()] += 1

    total = max(1, gray.width() * gray.height())
    low_target = total * 0.02
    high_target = total * 0.98

    cumulative = 0
    low = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= low_target:
            low = value
            break

    cumulative = 0
    high = 255
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= high_target:
            high = value
            break

    if high <= low + 4:
        return gray

    result = QImage(
        gray.width(),
        gray.height(),
        QImage.Format.Format_Grayscale8,
    )
    scale = 255.0 / (high - low)
    for y in range(gray.height()):
        for x in range(gray.width()):
            value = gray.pixelColor(x, y).red()
            adjusted = int(max(0, min(255, (value - low) * scale)))
            result.setPixelColor(x, y, QColor(adjusted, adjusted, adjusted))
    return result


def _pad_white(image: QImage, padding: int) -> QImage:
    result = QImage(
        image.width() + padding * 2,
        image.height() + padding * 2,
        QImage.Format.Format_ARGB32,
    )
    result.fill(QColor("white"))
    painter = QPainter(result)
    try:
        painter.drawImage(padding, padding, image)
    finally:
        painter.end()
    return result


def prepare_image(image_bytes: bytes, profile: str) -> PreparedImage:
    if profile not in PROFILES:
        raise ValueError(f"Profile OCR không hợp lệ: {profile}")

    original = _load(image_bytes)
    image = original
    metadata = {
        "profile": profile,
        "input_width": original.width(),
        "input_height": original.height(),
    }

    if profile == "upscale2x":
        image = original.scaled(
            original.width() * 2,
            original.height() * 2,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    elif profile == "contrast":
        image = _auto_contrast(original)
    elif profile == "manga_clean":
        image = _auto_contrast(original)
        image = image.scaled(
            image.width() * 2,
            image.height() * 2,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        image = _pad_white(image, 16)

    metadata.update({
        "output_width": image.width(),
        "output_height": image.height(),
    })
    return PreparedImage(
        png_bytes=_encode_png(image),
        image=image,
        profile=profile,
        metadata=metadata,
    )
