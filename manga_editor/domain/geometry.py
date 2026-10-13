from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    """Hình chữ nhật theo tọa độ pixel của ảnh gốc."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_points(cls, x1: float, y1: float, x2: float, y2: float) -> "Rect":
        left, right = sorted((float(x1), float(x2)))
        top, bottom = sorted((float(y1), float(y2)))
        return cls(left, top, right - left, bottom - top)

    def clamp(self, image_width: int, image_height: int) -> "Rect":
        left = min(max(0.0, self.x), float(image_width))
        top = min(max(0.0, self.y), float(image_height))
        right = min(max(left, self.x + self.width), float(image_width))
        bottom = min(max(top, self.y + self.height), float(image_height))
        return Rect(left, top, right - left, bottom - top)

    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Rect | None":
        if data is None:
            return None
        return cls(float(data["x"]), float(data["y"]), float(data["width"]), float(data["height"]))
