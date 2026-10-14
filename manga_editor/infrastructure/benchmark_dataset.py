from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4


def add_benchmark_sample(
    dataset_dir: str | Path,
    *,
    image_png: bytes,
    truth: str,
    language: str,
    layout: str,
    tags: list[str] | None = None,
    notes: str = "",
    source: dict | None = None,
) -> str:
    root = Path(dataset_dir)
    images = root / "images"
    images.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"

    if manifest_path.exists():
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json phải là object.")
    else:
        manifest = {
            "format_version": 1,
            "description": "MangaEditor OCR benchmark dataset",
            "samples": [],
        }

    samples = manifest.setdefault("samples", [])
    sample_id = f"sample_{uuid4().hex}"
    relative = f"images/{sample_id}.png"
    (root / relative).write_bytes(image_png)

    samples.append(
        {
            "id": sample_id,
            "image": relative,
            "truth": truth,
            "language": language,
            "layout": layout,
            "tags": list(tags or []),
            "notes": notes,
            "source": dict(source or {}),
        }
    )

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return sample_id
