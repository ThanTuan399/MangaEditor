from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import ContentRegion, ImageLayer, LayerKind, MangaProject, Page, new_id
from .history import History


class ProjectSession:
    """Điểm duy nhất để giao diện thay đổi dữ liệu dự án."""

    def __init__(self, project: MangaProject | None = None, assets: dict[str, bytes] | None = None):
        self.project = project or MangaProject.create("Dự án mới")
        self.assets = dict(assets or {})
        self.history = History()
        self.dirty = False

    def transact(self, label: str, mutator: Callable[[], None]) -> None:
        self.history.push_before(self.project, self.assets, label)
        mutator()
        self.dirty = True

    def add_page(self, source_name: str, raw_bytes: bytes, width: int, height: int) -> str:
        page_id = new_id("page")
        suffix = Path(source_name).suffix.lower() or ".img"
        asset_key = f"assets/pages/{page_id}/original{suffix}"
        digest = hashlib.sha256(raw_bytes).hexdigest()

        def mutate() -> None:
            self.assets[asset_key] = bytes(raw_bytes)
            self.project.pages.append(
                Page(
                    id=page_id,
                    name=Path(source_name).name,
                    raw_asset=asset_key,
                    raw_sha256=digest,
                    width=int(width),
                    height=int(height),
                )
            )

        self.transact("Nhập trang raw", mutate)
        return page_id

    def add_region(self, page_id: str) -> str:
        page = self.project.page(page_id)
        region = ContentRegion.create(len(page.regions))
        self.transact("Tạo vùng", lambda: page.regions.append(region))
        return region.id

    def delete_region(self, page_id: str, region_id: str) -> None:
        page = self.project.page(page_id)

        def mutate() -> None:
            page.regions[:] = [item for item in page.regions if item.id != region_id]
            for order, item in enumerate(sorted(page.regions, key=lambda x: x.order)):
                item.order = order

        self.transact("Xóa vùng", mutate)

    def rename_region(self, page_id: str, region_id: str, name: str) -> None:
        page = self.project.page(page_id)
        region = page.region(region_id)
        value = name.strip() or region.name

        def mutate() -> None:
            region.name = value
            region.revision += 1

        self.transact("Đổi tên vùng", mutate)

    def set_region_area(self, page_id: str, region_id: str, area_kind: str, rect: Rect) -> None:
        page = self.project.page(page_id)
        region = page.region(region_id)
        safe_rect = rect.clamp(page.width, page.height)
        if safe_rect.is_empty():
            raise ValueError("Phạm vi phải có chiều rộng và chiều cao lớn hơn 0.")
        self.transact("Cập nhật phạm vi vùng", lambda: region.set_area(area_kind, safe_rect))


    def set_background_patch(self, page_id: str, region_id: str, color: str = "#ffffff") -> str:
        page = self.project.page(page_id)
        region = page.region(region_id)
        if region.cleanup_area is None:
            raise ValueError("Vùng này chưa có phạm vi xóa chữ.")
        existing = page.layer_for_region(region_id, LayerKind.BACKGROUND_PATCH)

        def mutate() -> None:
            nonlocal existing
            if existing is None:
                existing = ImageLayer.background_patch(region_id, region.cleanup_area, color)
                page.layers.append(existing)
            else:
                existing.payload["rect"] = region.cleanup_area.to_dict()
                existing.payload["color"] = color
                existing.visible = True

        self.transact("Cập nhật bản vá nền", mutate)
        return existing.id

    def set_vietnamese_text(
        self,
        page_id: str,
        region_id: str,
        content: str,
        family: str,
        size: int,
        align: str = "center",
        color: str = "#000000",
    ) -> str:
        page = self.project.page(page_id)
        region = page.region(region_id)
        if region.text_frame is None:
            raise ValueError("Vùng này chưa có khung đặt chữ Việt.")
        if align not in {"left", "center", "right"}:
            raise ValueError("Kiểu căn chữ không hợp lệ.")
        existing = page.layer_for_region(region_id, LayerKind.VIETNAMESE_TEXT)

        def mutate() -> None:
            nonlocal existing
            if existing is None:
                existing = ImageLayer.vietnamese_text(
                    region_id=region_id,
                    rect=region.text_frame,
                    content=content,
                    family=family,
                    size=size,
                    align=align,
                    color=color,
                )
                page.layers.append(existing)
            else:
                existing.payload.update(
                    {
                        "rect": region.text_frame.to_dict(),
                        "content": content,
                        "family": family,
                        "size": int(size),
                        "align": align,
                        "color": color,
                    }
                )
                existing.visible = True

        self.transact("Cập nhật chữ Việt", mutate)
        return existing.id

    def set_layer_visibility(self, page_id: str, layer_id: str, visible: bool) -> None:
        page = self.project.page(page_id)
        layer = page.layer(layer_id)
        if layer.kind == LayerKind.SOURCE:
            return
        if layer.visible == bool(visible):
            return
        self.transact("Ẩn/hiện layer", lambda: setattr(layer, "visible", bool(visible)))

    def remove_region_layer(self, page_id: str, region_id: str, kind: LayerKind) -> None:
        page = self.project.page(page_id)

        def mutate() -> None:
            page.layers[:] = [
                layer for layer in page.layers
                if not (layer.region_id == region_id and layer.kind == kind)
            ]

        self.transact("Xóa layer vùng", mutate)

    def undo(self) -> bool:
        state = self.history.undo(self.project, self.assets)
        if state is None:
            return False
        self.project, self.assets = state.project, state.assets
        self.dirty = True
        return True

    def redo(self) -> bool:
        state = self.history.redo(self.project, self.assets)
        if state is None:
            return False
        self.project, self.assets = state.project, state.assets
        self.dirty = True
        return True
