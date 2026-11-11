"""Select only explicitly translated OCR regions for manual image replacement.

Normal load_text keeps its legacy fallback behaviour. OCR Workspace must not
erase a source bubble or redraw original OCR when its Translation cell is empty.
"""
from __future__ import annotations


def regions_to_replace(regions: list) -> list:
    """Return regions with a nonempty replacement, preserving their geometry."""
    return [
        region for region in regions
        if isinstance(getattr(region, "translation", None), str)
        and getattr(region, "translation").strip()
    ]
