from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

from manga_editor.domain.models import MangaProject


class ProjectStore:
    MANIFEST = "project.json"

    @classmethod
    def save(cls, filename: str | Path, project: MangaProject, assets: dict[str, bytes]) -> None:
        target = Path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        cls._validate_assets(project, assets)

        fd, tmp_name = tempfile.mkstemp(prefix=target.stem + "-", suffix=".tmp", dir=target.parent)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    cls.MANIFEST,
                    json.dumps(project.to_dict(), ensure_ascii=False, indent=2).encode("utf-8"),
                )
                for key, value in assets.items():
                    if not key.startswith("assets/"):
                        raise ValueError(f"Đường dẫn asset không hợp lệ: {key}")
                    archive.writestr(key, value)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()

    @classmethod
    def load(cls, filename: str | Path) -> tuple[MangaProject, dict[str, bytes]]:
        with zipfile.ZipFile(filename, "r") as archive:
            try:
                manifest = json.loads(archive.read(cls.MANIFEST).decode("utf-8"))
            except KeyError as exc:
                raise ValueError("Dự án thiếu project.json.") from exc
            project = MangaProject.from_dict(manifest)
            assets: dict[str, bytes] = {}
            for page in project.pages:
                if not page.raw_asset.startswith("assets/"):
                    raise ValueError(f"Đường dẫn raw không hợp lệ: {page.raw_asset}")
                try:
                    assets[page.raw_asset] = archive.read(page.raw_asset)
                except KeyError as exc:
                    raise ValueError(f"Dự án thiếu ảnh raw của trang: {page.name}") from exc
        cls._validate_assets(project, assets)
        return project, assets

    @staticmethod
    def _validate_assets(project: MangaProject, assets: dict[str, bytes]) -> None:
        for page in project.pages:
            raw = assets.get(page.raw_asset)
            if raw is None:
                raise ValueError(f"Thiếu asset raw: {page.raw_asset}")
            digest = hashlib.sha256(raw).hexdigest()
            if digest != page.raw_sha256:
                raise ValueError(f"Ảnh raw của trang '{page.name}' không khớp checksum.")
