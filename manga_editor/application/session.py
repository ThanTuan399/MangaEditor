from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from manga_editor.domain.geometry import Rect
from manga_editor.domain.models import (
    ContentRegion,
    ImageLayer,
    LayerKind,
    MangaProject,
    Page,
    WorkState,
    new_id,
)
from .history import History


class ProjectSession:
    """Điểm duy nhất để giao diện thay đổi dữ liệu dự án."""

    def __init__(
        self,
        project: MangaProject | None = None,
        assets: dict[str, bytes] | None = None,
    ):
        self.project = project or MangaProject.create("Dự án mới")
        self.assets = dict(assets or {})
        self.history = History()
        self.dirty = False

    def transact(self, label: str, mutator: Callable[[], None]) -> None:
        self.history.push_before(self.project, self.assets, label)
        mutator()
        self.dirty = True

    def add_page(
        self, source_name: str, raw_bytes: bytes, width: int, height: int
    ) -> str:
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

    def create_region_with_cleanup_part(self, page_id: str, rect: Rect) -> str:
        page = self.project.page(page_id)
        safe = self._safe_rect(page, rect)
        region = ContentRegion.create(len(page.regions))

        def mutate() -> None:
            region.add_cleanup_part(safe)
            page.regions.append(region)

        self.transact("Tạo vùng mới từ mảng xóa", mutate)
        return region.id

    def delete_region(self, page_id: str, region_id: str) -> None:
        page = self.project.page(page_id)

        def mutate() -> None:
            page.regions[:] = [
                item for item in page.regions if item.id != region_id
            ]
            page.layers[:] = [
                layer for layer in page.layers if layer.region_id != region_id
            ]
            self._normalize_orders(page)

        self.transact("Xóa vùng", mutate)

    def rename_region(self, page_id: str, region_id: str, name: str) -> None:
        page = self.project.page(page_id)
        region = page.region(region_id)
        value = name.strip() or region.name

        def mutate() -> None:
            region.name = value
            region.revision += 1

        self.transact("Đổi tên vùng", mutate)

    def move_region(self, page_id: str, region_id: str, direction: int) -> bool:
        page = self.project.page(page_id)
        ordered = sorted(page.regions, key=lambda item: item.order)
        index = next((i for i, item in enumerate(ordered) if item.id == region_id), -1)
        target = index + (1 if direction > 0 else -1)
        if index < 0 or target < 0 or target >= len(ordered):
            return False

        def mutate() -> None:
            ordered[index].order, ordered[target].order = (
                ordered[target].order,
                ordered[index].order,
            )

        self.transact("Đổi thứ tự vùng", mutate)
        return True

    def set_region_area(
        self, page_id: str, region_id: str, area_kind: str, rect: Rect
    ) -> None:
        page = self.project.page(page_id)
        region = page.region(region_id)
        safe = self._safe_rect(page, rect)

        def mutate() -> None:
            region.set_area(area_kind, safe)
            if area_kind == "cleanup_area":
                self._sync_patch_to_region(page, region)
            elif area_kind == "text_frame":
                text_layer = page.layer_for_region(
                    region_id, LayerKind.VIETNAMESE_TEXT
                )
                if text_layer is not None:
                    text_layer.payload["rect"] = safe.to_dict()
            elif area_kind == "ocr_area":
                region.ocr_state = WorkState.IN_PROGRESS

        self.transact("Cập nhật phạm vi vùng", mutate)

    def add_cleanup_part(
        self, page_id: str, region_id: str, rect: Rect
    ) -> int:
        page = self.project.page(page_id)
        region = page.region(region_id)
        safe = self._safe_rect(page, rect)
        result_index = len(region.cleanup_parts)

        def mutate() -> None:
            region.add_cleanup_part(safe)
            patch = page.layer_for_region(region_id, LayerKind.BACKGROUND_PATCH)
            if patch is not None:
                parts = patch.payload.setdefault("parts", [])
                default_color = (
                    parts[0].get("color", "#ffffff") if parts else "#ffffff"
                )
                parts.append({"rect": safe.to_dict(), "color": default_color})
            region.cleanup_state = WorkState.IN_PROGRESS

        self.transact("Thêm mảng xóa vào vùng", mutate)
        return result_index

    def remove_cleanup_part(
        self, page_id: str, region_id: str, index: int
    ) -> None:
        page = self.project.page(page_id)
        region = page.region(region_id)

        def mutate() -> None:
            region.remove_cleanup_part(index)
            patch = page.layer_for_region(region_id, LayerKind.BACKGROUND_PATCH)
            if patch is not None:
                parts = patch.payload.setdefault("parts", [])
                if 0 <= index < len(parts):
                    parts.pop(index)
                if not parts:
                    page.layers.remove(patch)
            region.cleanup_state = (
                WorkState.IN_PROGRESS
                if region.cleanup_parts
                else WorkState.NOT_STARTED
            )

        self.transact("Xóa mảng khỏi vùng", mutate)

    def split_cleanup_part(
        self, page_id: str, region_id: str, index: int
    ) -> str:
        """Tách đúng một mảng xóa sang Region mới; không tự sao chép chữ."""
        page = self.project.page(page_id)
        source = page.region(region_id)
        if not 0 <= index < len(source.cleanup_parts):
            raise IndexError(index)

        new_region = ContentRegion.create(len(page.regions))
        source_patch = page.layer_for_region(
            region_id, LayerKind.BACKGROUND_PATCH
        )

        def mutate() -> None:
            part = source.remove_cleanup_part(index)
            new_region.add_cleanup_part(part)
            new_region.name = f"{source.name} — tách"
            page.regions.append(new_region)

            if source_patch is not None:
                patch_parts = source_patch.payload.setdefault("parts", [])
                moved_patch = (
                    patch_parts.pop(index)
                    if 0 <= index < len(patch_parts)
                    else None
                )
                if not patch_parts:
                    page.layers.remove(source_patch)
                if moved_patch is not None:
                    layer = ImageLayer.background_patch(
                        new_region.id, [part], moved_patch.get("color", "#ffffff")
                    )
                    page.layers.append(layer)

            source.cleanup_state = (
                WorkState.IN_PROGRESS
                if source.cleanup_parts
                else WorkState.NOT_STARTED
            )
            new_region.cleanup_state = WorkState.IN_PROGRESS
            self._normalize_orders(page)

        self.transact("Tách mảng thành vùng mới", mutate)
        return new_region.id

    def merge_regions(
        self,
        page_id: str,
        target_region_id: str,
        source_region_id: str,
        text_policy: str = "keep_target",
    ) -> str:
        """
        Gộp source vào target. Target giữ ID.
        text_policy: keep_target | keep_source | append.
        """
        if target_region_id == source_region_id:
            raise ValueError("Không thể gộp một vùng với chính nó.")
        if text_policy not in {"keep_target", "keep_source", "append"}:
            raise ValueError("Quy tắc gộp chữ không hợp lệ.")

        page = self.project.page(page_id)
        target = page.region(target_region_id)
        source = page.region(source_region_id)
        target_patch = page.layer_for_region(
            target_region_id, LayerKind.BACKGROUND_PATCH
        )
        source_patch = page.layer_for_region(
            source_region_id, LayerKind.BACKGROUND_PATCH
        )
        target_text = page.layer_for_region(
            target_region_id, LayerKind.VIETNAMESE_TEXT
        )
        source_text = page.layer_for_region(
            source_region_id, LayerKind.VIETNAMESE_TEXT
        )

        def mutate() -> None:
            target.cleanup_parts.extend(source.cleanup_parts)
            if target.ocr_area is None:
                target.ocr_area = source.ocr_area
            elif source.ocr_area is not None:
                target.ocr_area = target.ocr_area.union(source.ocr_area)
            if target.text_frame is None:
                target.text_frame = source.text_frame

            self._merge_patch_layers(
                page, target, source, target_patch, source_patch
            )
            self._merge_text_layers(
                page,
                target_region_id,
                source_region_id,
                target_text,
                source_text,
                text_policy,
            )

            target.ocr_state = self._merged_state(
                target.ocr_state, source.ocr_state
            )
            target.cleanup_state = self._merged_state(
                target.cleanup_state, source.cleanup_state
            )
            target.text_state = self._merged_state(
                target.text_state, source.text_state
            )
            target.revision += 1

            page.layers[:] = [
                layer
                for layer in page.layers
                if layer.region_id != source_region_id
            ]
            page.regions[:] = [
                region
                for region in page.regions
                if region.id != source_region_id
            ]
            self._normalize_orders(page)

        self.transact("Gộp vùng", mutate)
        return target_region_id

    def set_region_state(
        self,
        page_id: str,
        region_id: str,
        aspect: str,
        state: WorkState | str,
    ) -> None:
        page = self.project.page(page_id)
        region = page.region(region_id)
        value = state if isinstance(state, WorkState) else WorkState(state)
        field = {
            "ocr": "ocr_state",
            "cleanup": "cleanup_state",
            "text": "text_state",
        }.get(aspect)
        if field is None:
            raise ValueError(f"Trạng thái không hợp lệ: {aspect}")
        if getattr(region, field) == value:
            return

        def mutate() -> None:
            setattr(region, field, value)
            region.revision += 1

        self.transact("Cập nhật trạng thái vùng", mutate)

    def set_background_patch(
        self, page_id: str, region_id: str, color: str = "#ffffff"
    ) -> str:
        page = self.project.page(page_id)
        region = page.region(region_id)
        if not region.cleanup_parts:
            raise ValueError("Vùng này chưa có phạm vi xóa chữ.")
        existing = page.layer_for_region(
            region_id, LayerKind.BACKGROUND_PATCH
        )

        def mutate() -> None:
            nonlocal existing
            if existing is None:
                existing = ImageLayer.background_patch(
                    region_id, region.cleanup_parts, color
                )
                page.layers.append(existing)
            else:
                existing.payload["parts"] = [
                    {"rect": rect.to_dict(), "color": color}
                    for rect in region.cleanup_parts
                ]
                existing.visible = True
            region.cleanup_state = WorkState.IN_PROGRESS
            region.revision += 1

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
        existing = page.layer_for_region(
            region_id, LayerKind.VIETNAMESE_TEXT
        )

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
            region.text_state = WorkState.IN_PROGRESS
            region.revision += 1

        self.transact("Cập nhật chữ Việt", mutate)
        return existing.id

    def set_layer_visibility(
        self, page_id: str, layer_id: str, visible: bool
    ) -> None:
        page = self.project.page(page_id)
        layer = page.layer(layer_id)
        if layer.kind == LayerKind.SOURCE:
            return
        if layer.visible == bool(visible):
            return
        self.transact(
            "Ẩn/hiện layer",
            lambda: setattr(layer, "visible", bool(visible)),
        )

    def remove_region_layer(
        self, page_id: str, region_id: str, kind: LayerKind
    ) -> None:
        page = self.project.page(page_id)
        region = page.region(region_id)

        def mutate() -> None:
            page.layers[:] = [
                layer
                for layer in page.layers
                if not (layer.region_id == region_id and layer.kind == kind)
            ]
            if kind == LayerKind.BACKGROUND_PATCH:
                region.cleanup_state = (
                    WorkState.IN_PROGRESS
                    if region.cleanup_parts
                    else WorkState.NOT_STARTED
                )
            elif kind == LayerKind.VIETNAMESE_TEXT:
                region.text_state = (
                    WorkState.IN_PROGRESS
                    if region.text_frame is not None
                    else WorkState.NOT_STARTED
                )
            region.revision += 1

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

    @staticmethod
    def _safe_rect(page: Page, rect: Rect) -> Rect:
        safe = rect.clamp(page.width, page.height)
        if safe.is_empty():
            raise ValueError(
                "Phạm vi phải có chiều rộng và chiều cao lớn hơn 0."
            )
        return safe

    @staticmethod
    def _normalize_orders(page: Page) -> None:
        for order, item in enumerate(
            sorted(page.regions, key=lambda region: region.order)
        ):
            item.order = order

    @staticmethod
    def _merged_state(a: WorkState, b: WorkState) -> WorkState:
        if a == b == WorkState.NOT_STARTED:
            return WorkState.NOT_STARTED
        if a == b == WorkState.REVIEWED:
            return WorkState.REVIEWED
        return WorkState.IN_PROGRESS

    @staticmethod
    def _sync_patch_to_region(page: Page, region: ContentRegion) -> None:
        patch = page.layer_for_region(
            region.id, LayerKind.BACKGROUND_PATCH
        )
        if patch is None:
            return
        old_parts = list(patch.payload.get("parts", []))
        default_color = (
            old_parts[0].get("color", "#ffffff")
            if old_parts
            else "#ffffff"
        )
        patch.payload["parts"] = [
            {
                "rect": rect.to_dict(),
                "color": (
                    old_parts[i].get("color", default_color)
                    if i < len(old_parts)
                    else default_color
                ),
            }
            for i, rect in enumerate(region.cleanup_parts)
        ]

    @staticmethod
    def _merge_patch_layers(
        page: Page,
        target: ContentRegion,
        source: ContentRegion,
        target_patch: ImageLayer | None,
        source_patch: ImageLayer | None,
    ) -> None:
        if target_patch is None and source_patch is None:
            return
        if target_patch is None and source_patch is not None:
            source_patch.region_id = target.id
            return
        if target_patch is not None and source_patch is not None:
            target_patch.payload.setdefault("parts", []).extend(
                source_patch.payload.get("parts", [])
            )
            if source_patch in page.layers:
                page.layers.remove(source_patch)

    @staticmethod
    def _merge_text_layers(
        page: Page,
        target_region_id: str,
        source_region_id: str,
        target_text: ImageLayer | None,
        source_text: ImageLayer | None,
        policy: str,
    ) -> None:
        if policy == "keep_target":
            if target_text is None and source_text is not None:
                source_text.region_id = target_region_id
            elif source_text is not None and source_text in page.layers:
                page.layers.remove(source_text)
            return

        if policy == "keep_source":
            if target_text is not None and target_text in page.layers:
                page.layers.remove(target_text)
            if source_text is not None:
                source_text.region_id = target_region_id
            return

        # append
        if target_text is None and source_text is not None:
            source_text.region_id = target_region_id
            return
        if target_text is not None and source_text is not None:
            left = str(target_text.payload.get("content", "")).rstrip()
            right = str(source_text.payload.get("content", "")).lstrip()
            target_text.payload["content"] = (
                f"{left}\n{right}" if left and right else left or right
            )
            if source_text in page.layers:
                page.layers.remove(source_text)
