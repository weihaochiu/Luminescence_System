from __future__ import annotations

import cv2
import numpy as np


def normalize_to_uint8(image: np.ndarray) -> np.ndarray:
    """Return a contrast-normalized grayscale image without changing geometry."""

    source = np.asarray(image)
    if source.ndim == 3:
        if source.shape[2] == 4:
            source = cv2.cvtColor(source, cv2.COLOR_BGRA2GRAY)
        elif source.shape[2] == 3:
            source = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError(f"Unsupported channel count: {source.shape}")
    if source.ndim != 2 or source.size == 0:
        raise ValueError(f"Expected a non-empty HxW or HxWxC image, got {source.shape}")
    finite = source[np.isfinite(source)] if np.issubdtype(source.dtype, np.floating) else source
    if finite.size == 0:
        raise ValueError("Input image has no finite pixels")
    low, high = np.percentile(finite, (0.5, 99.5))
    if high <= low:
        return np.zeros(source.shape, dtype=np.uint8)
    scaled = np.clip((source.astype(np.float32) - float(low)) * (255.0 / (high - low)), 0, 255)
    return np.rint(scaled).astype(np.uint8)


def to_bgr(image: np.ndarray) -> np.ndarray:
    source = normalize_to_uint8(image)
    return cv2.cvtColor(source, cv2.COLOR_GRAY2BGR)


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    shaped = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(shaped, np.asarray(matrix, dtype=np.float64)).reshape(-1, 2)


def angle_axis(angle_deg: float) -> np.ndarray:
    radians = np.deg2rad(angle_deg)
    return np.asarray((np.cos(radians), np.sin(radians)), dtype=np.float64)


def normalize_axis_angle(angle_deg: float) -> float:
    return float(angle_deg % 180.0)


def axis_angle_error(a_deg: float, b_deg: float) -> float:
    delta = abs(normalize_axis_angle(a_deg) - normalize_axis_angle(b_deg))
    return min(delta, 180.0 - delta)
