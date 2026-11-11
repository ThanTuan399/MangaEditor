"""OCR project isolation and incremental render cache tests."""
import json
from pathlib import Path

from desktop_qt_ui.ui.main_page.pages.ocr_project_registry import (
    OCRProjectRegistry,
    render_config_digest,
    render_signature,
    norm_path,
    within,
)


def _image(root: Path, name: str) -> Path:
    output = root / name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake image")
    return output


def test_multiple_projects_have_independent_page_lists(tmp_path):
    first = tmp_path / "Tập Một"
    second = tmp_path / "Tập Hai"
    first.mkdir()
    second.mkdir()
    p1 = _image(first, "001.jpg")
    p2 = _image(second, "001.jpg")
    registry = OCRProjectRegistry(tmp_path / "app")
    registry.add(first)
    registry.add(second)
    assert registry.images({".jpg"}) == [str(p2)]
    registry.select(first)
    assert registry.images({".jpg"}) == [str(p1)]
    assert registry.folders == [norm_path(first), norm_path(second)]
    assert OCRProjectRegistry(tmp_path / "app").active == norm_path(first)


def test_nested_project_is_not_scanned_as_part_of_parent(tmp_path):
    parent = tmp_path / "parent"
    child = parent / "chapter2"
    parent.mkdir()
    child.mkdir()
    p = _image(parent, "1.jpg")
    nested = _image(child, "2.jpg")
    work = _image(parent, "manga_translator_work/ocr_workspace_output/render.jpg")
    registry = OCRProjectRegistry(tmp_path / "app")
    registry.add(parent)
    registry.add(child)
    registry.select(parent)
    assert registry.images({".jpg"}) == [str(p)]
    registry.select(child)
    assert registry.images({".jpg"}) == [str(nested)]
    assert work.is_file()


def test_remove_project_never_deletes_user_files(tmp_path):
    root = tmp_path / "my-manga"
    root.mkdir()
    image = _image(root, "1.png")
    registry = OCRProjectRegistry(tmp_path / "app")
    registry.add(root)
    registry.remove(root)
    assert registry.active is None
    assert image.exists()


def test_render_cache_only_skips_known_successful_outputs(tmp_path):
    app = tmp_path / "app"
    root = tmp_path / "manga"
    root.mkdir()
    image = _image(root, "page.jpg")
    sidecar = root / "page_translations.json"
    sidecar.write_text('{"regions":[{"translation":"Xin chào"}]}', encoding="utf-8")
    settings = {"render": {"font_size": 24}, "translator": {"target_lang": "VIN"}}
    digest = render_config_digest(settings)
    signature = render_signature(str(image), str(sidecar), digest)
    registry = OCRProjectRegistry(app)
    registry.add(root)
    image_key = norm_path(image)
    output = registry.output_dir(root) / "manga" / "page.jpg"
    cache = {image_key: {"signature": signature, "output": str(output)}}
    assert not registry.cached(cache, str(image), signature)
    output.parent.mkdir(parents=True)
    output.write_bytes(b"rendered bytes")
    assert registry.cached(cache, str(image), signature)
    registry.store_cache(root, cache)
    assert registry.cached(registry.read_cache(root), str(image), signature)

    # Changing a translated word invalidates output even if original file is unchanged.
    sidecar.write_text('{"regions":[{"translation":"Chào bạn"}]}', encoding="utf-8")
    changed = render_signature(str(image), str(sidecar), digest)
    assert changed != signature
    assert not registry.cached(cache, str(image), changed)

    # A font/render setting invalidates output; changing unrelated UI settings does not.
    assert digest != render_config_digest({"render": {"font_size": 32}})
    settings["app"] = {"theme": "dark"}
    assert digest == render_config_digest(settings)


def test_paths_are_limited_to_project_folder(tmp_path):
    a = tmp_path / "ProjectA"
    b = tmp_path / "ProjectAB"
    a.mkdir()
    b.mkdir()
    assert within(a / "image.jpg", a)
    assert not within(b / "image.jpg", a)
