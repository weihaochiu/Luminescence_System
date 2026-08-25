from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import CalibrationConfig
from .image_utils import normalize_to_uint8, transform_points
from .models import RulerDetection


@dataclass
class RectificationResult:
    success: bool
    image: np.ndarray
    original_to_rectified: np.ndarray
    rectified_to_original: np.ndarray
    output_size: tuple[int, int]
    reason: str = ""

    def to_original(self, points: np.ndarray) -> np.ndarray:
        return transform_points(points, self.rectified_to_original)

    def to_rectified(self, points: np.ndarray) -> np.ndarray:
        return transform_points(points, self.original_to_rectified)


class RulerRectifier:
    """Rectify the detected quadrilateral without arbitrary post-warp resizing."""

    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()

    def rectify(self, image: np.ndarray, detection: RulerDetection) -> RectificationResult:
        gray = normalize_to_uint8(image)
        identity = np.eye(3, dtype=np.float64)
        if not detection.success or len(detection.polygon) != 4:
            return RectificationResult(False, gray, identity, identity, gray.shape[::-1], "ruler_not_found")
        polygon = np.asarray(detection.polygon, dtype=np.float32)
        axis = np.asarray(
            (np.cos(np.deg2rad(detection.angle_deg)), np.sin(np.deg2rad(detection.angle_deg))),
            dtype=np.float32,
        )
        normal = np.asarray((-axis[1], axis[0]), dtype=np.float32)
        center = np.asarray(detection.center, dtype=np.float32)
        longitudinal = (polygon - center) @ axis
        transverse = (polygon - center) @ normal
        left = polygon[np.argsort(longitudinal)[:2]]
        right = polygon[np.argsort(longitudinal)[-2:]]
        left_t = (left - center) @ normal
        right_t = (right - center) @ normal
        top_left, bottom_left = left[np.argmin(left_t)], left[np.argmax(left_t)]
        top_right, bottom_right = right[np.argmin(right_t)], right[np.argmax(right_t)]
        source = np.asarray((top_left, top_right, bottom_right, bottom_left), dtype=np.float32)
        width = int(round(max(
            np.linalg.norm(top_right - top_left),
            np.linalg.norm(bottom_right - bottom_left),
        )))
        height = int(round(max(
            np.linalg.norm(bottom_left - top_left),
            np.linalg.norm(bottom_right - top_right),
        )))
        if width < height:
            width, height = height, width
            source = np.asarray((bottom_left, top_left, top_right, bottom_right), dtype=np.float32)
        if width < 40 or height < self.config.rectified_min_height_px:
            return RectificationResult(False, gray, identity, identity, gray.shape[::-1], "ruler_roi_too_small")
        destination = np.asarray(
            ((0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)),
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(source, destination)
        inverse = np.linalg.inv(matrix)
        rectified = cv2.warpPerspective(
            gray,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return RectificationResult(True, rectified, matrix, inverse, (width, height))
