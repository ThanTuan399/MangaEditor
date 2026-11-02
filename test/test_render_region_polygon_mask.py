"""Regression tests for OpenCV 5 fillPoly and OCR Workspace rendering masks."""
from types import SimpleNamespace

import cv2
import numpy as np

from manga_translator.mask_refinement.region_polygon_mask import mask_from_text_regions


def test_render_mask_accepts_textblock_float64_geometry():
    region = SimpleNamespace(lines=np.array(
        [[[2.2, 3.2], [12.0, 3.2], [12.0, 15.1], [2.2, 15.1]]],
        dtype=np.float64,
    ))
    mask = mask_from_text_regions([region], (24, 30))
    assert mask.shape == (24, 30)
    assert mask.dtype == np.uint8
    assert mask[7, 7] == 255
    assert mask[0, 0] == 0


def test_render_mask_ignores_invalid_empty_and_nonfinite_polygons():
    invalid = [
        SimpleNamespace(lines=[]),
        SimpleNamespace(lines=np.array([[1, 2], [2, 3]], dtype=np.float64)),
        SimpleNamespace(lines=np.array([
            [[np.nan, 2], [6, 2], [6, 6], [2, 6]]
        ])),
        SimpleNamespace(lines=np.array([
            [[3, 4], [3, 4], [3, 4], [3, 4]]
        ])),
    ]
    result = mask_from_text_regions(invalid, (20, 20))
    assert np.count_nonzero(result) == 0


def test_render_mask_clips_out_of_bounds_without_overflow():
    region = SimpleNamespace(lines=np.array(
        [[[-1e40, -1e40], [1e40, -1e40], [1e40, 1e40], [-1e40, 1e40]]],
        dtype=np.float64,
    ))
    mask = mask_from_text_regions([region], (20, 20))
    assert mask.dtype == np.uint8
    assert mask[10, 10] == 255


def test_render_mask_tolerates_single_polygon_and_multiple_regions():
    regions = [
        SimpleNamespace(lines=[[0, 0], [5, 0], [5, 5], [0, 5]]),
        SimpleNamespace(lines=np.array(
            [[[10, 10], [15, 10], [15, 15], [10, 15]]],
            dtype=np.float64,
        )),
    ]
    result = mask_from_text_regions(regions, (20, 20))
    assert result[2, 2] == 255
    assert result[12, 12] == 255
    assert result[8, 8] == 0


def test_render_mask_empty_regions_with_opencv5():
    result = mask_from_text_regions([], (12, 18))
    assert result.shape == (12, 18)
    assert not np.any(result)
