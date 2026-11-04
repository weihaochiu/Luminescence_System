from __future__ import annotations

"""Per-run channel ROIs, expressed exclusively in source image pixels."""

from typing import Iterable, Mapping

import numpy as np


ROI = tuple[int, int, int, int]


def validate_roi(roi: Iterable[int], width: int, height: int) -> ROI:
    values = tuple(roi)
    if len(values) != 4 or any(type(value) is not int for value in values):
        raise ValueError("ROI requires four integer image-pixel coordinates")
    x, y, w, h = values
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError(f"ROI {values} is outside source image {width}x{height}")
    return x, y, w, h


def validate_channel_rois(
    rois: Mapping[str, Iterable[int]], channels: Iterable[str], width: int, height: int,
) -> dict[str, ROI]:
    channels = tuple(channels)
    if not channels or any(channel not in {"CH1", "CH2", "CH3", "CH4"} for channel in channels):
        raise ValueError("Recipe ROI channels must be CH1 through CH4")
    if set(rois) != set(channels):
        raise ValueError("Every enabled channel must have its own ROI")
    return {channel: validate_roi(rois[channel], width, height) for channel in channels}


def crop_channel_frame(source: np.ndarray, roi: ROI) -> np.ndarray:
    if source.dtype != np.uint16 or source.ndim != 2:
        raise ValueError("Recipe ROI requires a uint16 H×W scientific frame")
    x, y, width, height = validate_roi(roi, source.shape[1], source.shape[0])
    return source[y:y + height, x:x + width]
