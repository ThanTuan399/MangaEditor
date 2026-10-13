from __future__ import annotations

from copy import deepcopy

from manga_editor import PROJECT_FORMAT_VERSION


def migrate_manifest(data: dict) -> dict:
    manifest = deepcopy(data)
    version = int(manifest.get("format_version", 0))
    if version == PROJECT_FORMAT_VERSION:
        return manifest
    if version < 1:
        raise ValueError(
            f"Định dạng dự án {version} quá cũ hoặc không hợp lệ."
        )

    while version < PROJECT_FORMAT_VERSION:
        if version == 1:
            manifest = _v1_to_v2(manifest)
            version = 2
            continue
        if version == 2:
            manifest = _v2_to_v3(manifest)
            version = 3
            continue
        raise ValueError(f"Không có bước chuyển từ format {version}.")

    if version != PROJECT_FORMAT_VERSION:
        raise ValueError(
            f"Định dạng dự án {version} chưa được hỗ trợ; "
            f"bản hiện tại là {PROJECT_FORMAT_VERSION}."
        )
    return manifest


def _v1_to_v2(manifest: dict) -> dict:
    for page in manifest.get("pages", []):
        layers = page.get("layers", [])
        patch_by_region = {
            layer.get("region_id"): layer
            for layer in layers
            if layer.get("kind") == "background_patch"
            and layer.get("region_id")
        }
        text_by_region = {
            layer.get("region_id"): layer
            for layer in layers
            if layer.get("kind") == "vietnamese_text"
            and layer.get("region_id")
        }

        for region in page.get("regions", []):
            cleanup = region.get("cleanup_area")
            region["cleanup_parts"] = [cleanup] if cleanup else []
            region["ocr_state"] = "not_started"
            region["cleanup_state"] = (
                "in_progress"
                if region.get("id") in patch_by_region or cleanup
                else "not_started"
            )
            text_layer = text_by_region.get(region.get("id"))
            text_content = ""
            if text_layer:
                text_content = str(
                    text_layer.get("payload", {}).get("content", "")
                )
            region["text_state"] = (
                "in_progress"
                if text_content.strip() or region.get("text_frame")
                else "not_started"
            )

        for layer in layers:
            if layer.get("kind") != "background_patch":
                continue
            payload = dict(layer.get("payload", {}))
            if "parts" in payload:
                continue
            rect = payload.get("rect")
            color = payload.get("color", "#ffffff")
            payload["parts"] = (
                [{"rect": rect, "color": color}] if rect else []
            )
            payload.pop("rect", None)
            payload.pop("color", None)
            layer["payload"] = payload

    manifest["format_version"] = 2
    return manifest


def _v2_to_v3(manifest: dict) -> dict:
    for page in manifest.get("pages", []):
        for region in page.get("regions", []):
            region.setdefault("ocr_language", "ja")
            region.setdefault("ocr_layout", "auto")
            region.setdefault("ocr_machine_text", "")
            region.setdefault("ocr_edited_text", "")
            region.setdefault("ocr_engine", "")
            region.setdefault("ocr_warning", "")
            region.setdefault("ocr_confidence", None)
            region.setdefault("ocr_input_revision", 0)
            region.setdefault("ocr_result_revision", -1)

    manifest["format_version"] = 3
    return manifest
