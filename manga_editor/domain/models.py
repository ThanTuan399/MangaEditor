from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from manga_editor import PROJECT_FORMAT_VERSION
from .geometry import Rect


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class LayerKind(StrEnum):
    SOURCE = "source"
    BACKGROUND_PATCH = "background_patch"
    VIETNAMESE_TEXT = "vietnamese_text"
    GUIDE = "guide"


class WorkState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    REVIEWED = "reviewed"


@dataclass(slots=True)
class ImageLayer:
    id: str
    kind: LayerKind
    name: str
    visible: bool = True
    locked: bool = False
    region_id: str | None = None
    payload: dict = field(default_factory=dict)

    @classmethod
    def source(cls) -> "ImageLayer":
        return cls(new_id("layer"), LayerKind.SOURCE, "Ảnh gốc", True, True)

    @classmethod
    def background_patch(
        cls, region_id: str, rects: list[Rect], color: str = "#ffffff"
    ) -> "ImageLayer":
        return cls(
            id=new_id("layer"),
            kind=LayerKind.BACKGROUND_PATCH,
            name="Bản vá nền",
            visible=True,
            locked=False,
            region_id=region_id,
            payload={
                "parts": [
                    {"rect": rect.to_dict(), "color": color}
                    for rect in rects
                ]
            },
        )

    @classmethod
    def vietnamese_text(
        cls,
        region_id: str,
        rect: Rect,
        content: str = "",
        family: str = "Arial",
        size: int = 32,
        align: str = "center",
        color: str = "#000000",
    ) -> "ImageLayer":
        return cls(
            id=new_id("layer"),
            kind=LayerKind.VIETNAMESE_TEXT,
            name="Chữ Việt",
            visible=True,
            locked=False,
            region_id=region_id,
            payload={
                "rect": rect.to_dict(),
                "content": content,
                "family": family,
                "size": int(size),
                "align": align,
                "color": color,
            },
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "visible": self.visible,
            "locked": self.locked,
            "region_id": self.region_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ImageLayer":
        return cls(
            id=data["id"],
            kind=LayerKind(data["kind"]),
            name=data["name"],
            visible=bool(data.get("visible", True)),
            locked=bool(data.get("locked", False)),
            region_id=data.get("region_id"),
            payload=dict(data.get("payload", {})),
        )


@dataclass(slots=True)
class ContentRegion:
    id: str
    name: str
    order: int
    content_type: str = "dialogue"
    ocr_area: Rect | None = None
    cleanup_parts: list[Rect] = field(default_factory=list)
    text_frame: Rect | None = None
    ocr_state: WorkState = WorkState.NOT_STARTED
    cleanup_state: WorkState = WorkState.NOT_STARTED
    text_state: WorkState = WorkState.NOT_STARTED
    revision: int = 0

    @classmethod
    def create(cls, order: int, name: str | None = None) -> "ContentRegion":
        return cls(new_id("region"), name or f"Vùng {order + 1:02d}", order)

    @property
    def cleanup_area(self) -> Rect | None:
        """Khung bao để hiển thị/tương thích; dữ liệu thật là cleanup_parts."""
        return Rect.union_all(self.cleanup_parts)

    def set_area(self, area_kind: str, rect: Rect | None) -> None:
        if area_kind == "ocr_area":
            self.ocr_area = rect
        elif area_kind == "cleanup_area":
            self.cleanup_parts = [] if rect is None else [rect]
            self.cleanup_state = (
                WorkState.NOT_STARTED if rect is None else WorkState.IN_PROGRESS
            )
        elif area_kind == "text_frame":
            self.text_frame = rect
            self.text_state = (
                WorkState.NOT_STARTED if rect is None else WorkState.IN_PROGRESS
            )
        else:
            raise ValueError(f"Phạm vi không hợp lệ: {area_kind}")
        self.revision += 1

    def add_cleanup_part(self, rect: Rect) -> int:
        self.cleanup_parts.append(rect)
        self.cleanup_state = WorkState.IN_PROGRESS
        self.revision += 1
        return len(self.cleanup_parts) - 1

    def remove_cleanup_part(self, index: int) -> Rect:
        if not 0 <= index < len(self.cleanup_parts):
            raise IndexError(index)
        rect = self.cleanup_parts.pop(index)
        if not self.cleanup_parts:
            self.cleanup_state = WorkState.NOT_STARTED
        self.revision += 1
        return rect

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "order": self.order,
            "content_type": self.content_type,
            "ocr_area": None if self.ocr_area is None else self.ocr_area.to_dict(),
            "cleanup_parts": [rect.to_dict() for rect in self.cleanup_parts],
            "text_frame": None if self.text_frame is None else self.text_frame.to_dict(),
            "ocr_state": self.ocr_state.value,
            "cleanup_state": self.cleanup_state.value,
            "text_state": self.text_state.value,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContentRegion":
        cleanup_parts = [
            rect for raw in data.get("cleanup_parts", [])
            if (rect := Rect.from_dict(raw)) is not None
        ]
        if not cleanup_parts:
            legacy = Rect.from_dict(data.get("cleanup_area"))
            if legacy is not None:
                cleanup_parts = [legacy]
        return cls(
            id=data["id"],
            name=data["name"],
            order=int(data["order"]),
            content_type=data.get("content_type", "dialogue"),
            ocr_area=Rect.from_dict(data.get("ocr_area")),
            cleanup_parts=cleanup_parts,
            text_frame=Rect.from_dict(data.get("text_frame")),
            ocr_state=WorkState(data.get("ocr_state", WorkState.NOT_STARTED.value)),
            cleanup_state=WorkState(
                data.get(
                    "cleanup_state",
                    WorkState.IN_PROGRESS.value if cleanup_parts else WorkState.NOT_STARTED.value,
                )
            ),
            text_state=WorkState(
                data.get(
                    "text_state",
                    WorkState.IN_PROGRESS.value
                    if data.get("text_frame") is not None
                    else WorkState.NOT_STARTED.value,
                )
            ),
            revision=int(data.get("revision", 0)),
        )


@dataclass(slots=True)
class Page:
    id: str
    name: str
    raw_asset: str
    raw_sha256: str
    width: int
    height: int
    regions: list[ContentRegion] = field(default_factory=list)
    layers: list[ImageLayer] = field(default_factory=lambda: [ImageLayer.source()])

    def region(self, region_id: str) -> ContentRegion:
        for item in self.regions:
            if item.id == region_id:
                return item
        raise KeyError(region_id)

    def layer(self, layer_id: str) -> ImageLayer:
        for item in self.layers:
            if item.id == layer_id:
                return item
        raise KeyError(layer_id)

    def layer_for_region(self, region_id: str, kind: LayerKind) -> ImageLayer | None:
        for item in self.layers:
            if item.region_id == region_id and item.kind == kind:
                return item
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "raw_asset": self.raw_asset,
            "raw_sha256": self.raw_sha256,
            "width": self.width,
            "height": self.height,
            "regions": [item.to_dict() for item in self.regions],
            "layers": [item.to_dict() for item in self.layers],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Page":
        return cls(
            id=data["id"],
            name=data["name"],
            raw_asset=data["raw_asset"],
            raw_sha256=data["raw_sha256"],
            width=int(data["width"]),
            height=int(data["height"]),
            regions=[ContentRegion.from_dict(x) for x in data.get("regions", [])],
            layers=[ImageLayer.from_dict(x) for x in data.get("layers", [])]
            or [ImageLayer.source()],
        )


@dataclass(slots=True)
class ProjectSettings:
    default_language: str = "ja"

    def to_dict(self) -> dict:
        return {"default_language": self.default_language}

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProjectSettings":
        data = data or {}
        return cls(default_language=data.get("default_language", "ja"))


@dataclass(slots=True)
class MangaProject:
    id: str
    name: str
    pages: list[Page] = field(default_factory=list)
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    format_version: int = PROJECT_FORMAT_VERSION

    @classmethod
    def create(cls, name: str) -> "MangaProject":
        return cls(new_id("project"), name.strip() or "Dự án chưa đặt tên")

    def page(self, page_id: str) -> Page:
        for item in self.pages:
            if item.id == page_id:
                return item
        raise KeyError(page_id)

    def to_dict(self) -> dict:
        return {
            "format_version": self.format_version,
            "id": self.id,
            "name": self.name,
            "settings": self.settings.to_dict(),
            "pages": [item.to_dict() for item in self.pages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MangaProject":
        version = int(data.get("format_version", 0))
        if version != PROJECT_FORMAT_VERSION:
            raise ValueError(
                f"Định dạng dự án {version} chưa được hỗ trợ; bản hiện tại là {PROJECT_FORMAT_VERSION}."
            )
        return cls(
            id=data["id"],
            name=data["name"],
            pages=[Page.from_dict(x) for x in data.get("pages", [])],
            settings=ProjectSettings.from_dict(data.get("settings")),
            format_version=version,
        )
