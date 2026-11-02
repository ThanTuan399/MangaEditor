"""Validate OCR polygon coordinates before passing them to cv2.fillPoly.

TextBlock loads polygon points from project JSON as float64, while OpenCV
requires a contiguous array of 2D int32 points. The mask generator must not
fail an entire render job because one OCR region has invalid or empty geometry.
"""
from __future__ import annotations

import logging
from typing import Iterable

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def mask_from_text_regions(regions: Iterable, shape: tuple[int, int]) -> np.ndarray:
    """Build a uint8 region mask, skipping invalid/degenerate polygons safely."""
    height, width = int(shape[0]), int(shape[1])
    result = np.zeros((max(height, 0), max(width, 0)), dtype=np.uint8)
    if height <= 0 or width <= 0:
        return result

    polygons = []
    invalid = 0
    for region in regions:
        raw_lines = getattr(region, "lines", [])
        try:
            lines = np.asarray(raw_lines, dtype=np.float64)
        except (TypeError, ValueError, OverflowError):
            invalid += 1
            continue

        # Typical JSON has shape (line_count, 4, 2).
        # A single polygon may also have shape (4, 2).
        if lines.ndim == 2 and lines.shape[-1] == 2:
            lines = lines[np.newaxis, :, :]
        if lines.ndim != 3 or lines.shape[-1] != 2:
            invalid += 1
            continue

        for points in lines:
            if len(points) < 3 or not np.isfinite(points).all():
                invalid += 1
                continue
            coords = np.rint(points)
            # Clamp before converting: floats can be outside int32 range.
            coords[:, 0] = np.clip(coords[:, 0], 0, width - 1)
            coords[:, 1] = np.clip(coords[:, 1], 0, height - 1)
            polygon = np.ascontiguousarray(coords, dtype=np.int32)
            if len(np.unique(polygon, axis=0)) < 3:
                invalid += 1
                continue
            polygons.append(polygon.reshape(-1, 1, 2))

    if invalid:
        logger.warning(
            "Skipped %d malformed/degenerate OCR polygons while creating render mask",
            invalid,
        )
    if polygons:
        cv2.fillPoly(result, polygons, 255)
    return result
