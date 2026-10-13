from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RawImage:
    name: str
    data: bytes
    width: int
    height: int


def load_raw_image(filename: str | Path) -> RawImage:
    """Đọc ảnh bằng Qt ở tầng infrastructure; domain không phụ thuộc PySide6."""
    from PySide6.QtGui import QImageReader

    path = Path(filename)
    reader = QImageReader(str(path))
    size = reader.size()
    if not size.isValid():
        raise ValueError(f"Không đọc được kích thước ảnh: {path.name}")
    data = path.read_bytes()
    if not data:
        raise ValueError("Ảnh raw rỗng.")
    return RawImage(path.name, data, size.width(), size.height())
