"""Folder-isolated OCR Workspace projects and incremental render cache.

No project files are copied or combined. A project is an existing directory,
with its own image list, OCR JSON sidecars, exported images, and render cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable


_EXCLUDE_DIRS = {
    ".git", ".venv", "__pycache__", "manga_translator_work",
    "result", ".manga_ocr_workspace",
}


def norm_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def within(path: str | Path, folder: str | Path) -> bool:
    path, folder = norm_path(path), norm_path(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:
        return False


def _natural_key(value: str):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", value)]


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def render_config_digest(settings: dict) -> str:
    """Only settings that can affect image output invalidate cached renders."""
    cli = settings.get("cli", {})
    relevant = {
        key: settings.get(key, {}) for key in
        ("render", "inpainter", "mask_refinement", "detector", "ocr", "upscale")
    }
    relevant["cli"] = {
        key: cli.get(key) for key in
        ("format", "save_quality", "export_editable_psd", "psd_script_only")
    }
    relevant["target_lang"] = settings.get("translator", {}).get("target_lang", "VIN")
    relevant["cache_version"] = 2
    return hashlib.sha256(
        json.dumps(relevant, sort_keys=True, default=str, ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()


def render_signature(image: str, json_path: str, digest: str) -> str:
    """Invalidate when source pixels, sidecar content or render settings change."""
    source = Path(image)
    sidecar = Path(json_path)
    info = source.stat()
    digestor = hashlib.sha256()
    digestor.update(norm_path(source).encode("utf-8"))
    digestor.update(str(info.st_size).encode("ascii"))
    digestor.update(str(info.st_mtime_ns).encode("ascii"))
    digestor.update(digest.encode("ascii"))
    # JSON is small in normal OCR workflows; hashing content catches edits
    # made by external translators/editors even if the mtime is preserved.
    with sidecar.open("rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            digestor.update(piece)
    return digestor.hexdigest()


class OCRProjectRegistry:
    """Persistent project directory list; removal never deletes user files."""

    def __init__(self, app_root: str | Path):
        self.index_path = Path(app_root) / "config" / "ocr_workspace_projects.json"
        self.folders: list[str] = []
        self.active: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.index_path.is_file():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            seen: set[str] = set()
            for item in raw.get("folders", []):
                path = norm_path(item)
                if path not in seen:
                    seen.add(path)
                    self.folders.append(path)
            active = norm_path(raw["active"]) if raw.get("active") else None
            self.active = active if active in self.folders else (
                self.folders[0] if self.folders else None
            )
        except (OSError, ValueError, TypeError, KeyError):
            self.folders = []
            self.active = None

    def _save(self) -> None:
        atomic_json(self.index_path, {
            "version": 1, "folders": self.folders, "active": self.active,
        })

    def add(self, folder: str | Path) -> str:
        path = norm_path(folder)
        if not os.path.isdir(path):
            raise ValueError(f"Project folder does not exist: {path}")
        if path not in self.folders:
            self.folders.append(path)
        self.active = path
        self._save()
        return path

    def select(self, folder: str | Path) -> None:
        path = norm_path(folder)
        if path not in self.folders:
            raise ValueError("Unknown OCR project folder")
        self.active = path
        self._save()

    def remove(self, folder: str | Path) -> None:
        path = norm_path(folder)
        if path in self.folders:
            self.folders.remove(path)
            if self.active == path:
                self.active = self.folders[0] if self.folders else None
            self._save()

    def images(self, extensions: set[str]) -> list[str]:
        """Enumerate only active project's images, never any nested other project."""
        root = self.active
        if not root or not os.path.isdir(root):
            return []
        nested_projects = {
            path for path in self.folders if path != root and within(path, root)
        }
        result: list[str] = []
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = sorted(
                (folder for folder in dirs
                 if folder.lower() not in _EXCLUDE_DIRS
                 and norm_path(os.path.join(current, folder)) not in nested_projects
                 and not os.path.islink(os.path.join(current, folder))),
                key=_natural_key,
            )
            for name in files:
                if os.path.splitext(name)[1].lower() in extensions:
                    result.append(os.path.normpath(os.path.join(current, name)))
        return sorted(result, key=lambda p: _natural_key(os.path.relpath(p, root)))

    @staticmethod
    def output_dir(folder: str | Path) -> Path:
        return Path(folder) / "manga_translator_work" / "ocr_workspace_output"

    @staticmethod
    def cache_path(folder: str | Path) -> Path:
        return Path(folder) / "manga_translator_work" / "ocr_workspace_render_cache.json"

    def read_cache(self, folder: str | Path) -> dict:
        try:
            cache = json.loads(self.cache_path(folder).read_text(encoding="utf-8"))
            return cache if isinstance(cache, dict) else {}
        except (OSError, ValueError):
            return {}

    def store_cache(self, folder: str | Path, cache: dict) -> None:
        atomic_json(self.cache_path(folder), cache)

    @staticmethod
    def cached(cache: dict, image: str, signature: str) -> bool:
        entry = cache.get(norm_path(image))
        return (
            isinstance(entry, dict)
            and entry.get("signature") == signature
            and bool(entry.get("output"))
            and os.path.isfile(entry["output"])
        )
