from __future__ import annotations

import cv2
import numpy as np

from core.calibration.models import RulerDetection, TickMark


def synthetic_ruler(angle_deg: float = 0.0, scale: float | None = None) -> np.ndarray:
    image = np.full((700, 1000), 35, dtype=np.uint8)
    cv2.rectangle(image, (100, 260), (900, 440), 210, -1)
    cv2.rectangle(image, (100, 260), (900, 440), 245, 3)
    for index in range(39):
        x = 120 + index * 20
        endpoint = 330 if index % 10 == 0 else (310 if index % 5 == 0 else 292)
        cv2.line(image, (x, 260), (x, endpoint), 20, 3)
    if angle_deg % 360 == 0 and (scale is None or scale == 1.0):
        return image
    selected_scale = scale if scale is not None else (1.0 if angle_deg % 180 == 0 else 0.75)
    matrix = cv2.getRotationMatrix2D((500, 350), -angle_deg, selected_scale)
    return cv2.warpAffine(image, matrix, (1000, 700), borderValue=35)


def synthetic_ticks(
    *,
    pixels_per_mm: float = 200.0,
    count: int = 31,
    missing: set[int] | None = None,
    noise: np.ndarray | None = None,
) -> tuple[RulerDetection, list[TickMark]]:
    omitted = missing or set()
    detection = RulerDetection(
        True,
        polygon=[(0.0, 0.0), (7000.0, 0.0), (7000.0, 200.0), (0.0, 200.0)],
        center=(0.0, 100.0),
        angle_deg=0.0,
        confidence=0.9,
    )
    jitter = np.zeros(count) if noise is None else noise
    ticks = []
    for index in range(count):
        if index in omitted:
            continue
        x = 100.0 + index * pixels_per_mm + float(jitter[index])
        ticks.append(
            TickMark(
                rectified_position_px=x,
                original_position=(x, 100.0),
                length_px=60.0 if index % 10 == 0 else 30.0,
                kind="major" if index % 10 == 0 else "minor",
            )
        )
    return detection, ticks
