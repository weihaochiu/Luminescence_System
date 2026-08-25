from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


Point = tuple[float, float]
BBox = tuple[int, int, int, int]


@dataclass
class RulerDetection:
    success: bool
    polygon: list[Point] = field(default_factory=list)
    center: Point = (0.0, 0.0)
    angle_deg: float = 0.0
    confidence: float = 0.0
    reason: str = ""


@dataclass
class TickMark:
    rectified_position_px: float
    original_position: Point
    length_px: float
    kind: str = "minor"
    accepted: bool = True
    fitted_mm: float | None = None
    residual_px: float | None = None
    rejection_reason: str = ""


@dataclass
class DetectedNumber:
    value: int | None
    raw_text: str
    bbox: BBox
    center: Point
    confidence: float
    orientation_deg: int = 0
    accepted: bool = True
    corrected_value: int | None = None
    associated_tick_mm: float | None = None
    rejection_reason: str = ""


@dataclass(frozen=True)
class ScaleBarSelection:
    length_um: float
    rendered_length_px: float
    label: str


@dataclass
class CalibrationResult:
    success: bool = False
    pixels_per_mm: float | None = None
    um_per_pixel: float | None = None
    ruler_angle_deg: float | None = None
    ruler_detection: RulerDetection | None = None
    detected_numbers: list[DetectedNumber] = field(default_factory=list)
    detected_major_ticks: list[TickMark] = field(default_factory=list)
    detected_minor_ticks: list[TickMark] = field(default_factory=list)
    rejected_ticks: list[TickMark] = field(default_factory=list)
    calibration_span_mm: float = 0.0
    fit_rmse_px: float | None = None
    fit_error_percent: float | None = None
    quality_score: float = 0.0
    quality_label: str = "FAIL"
    usable_intervals: int = 0
    ocr_available: bool = False
    ocr_usable: bool = False
    ocr_diagnostic: str = ""
    warnings: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    input_resolution: tuple[int, int] = (0, 0)
    coordinate_system: str = "original_image_pixels"
    algorithm_version: str = "ruler-calibration-v1"
    scale_bar: ScaleBarSelection | None = None
    timestamp: str = ""
    debug_images: dict[str, np.ndarray] = field(
        default_factory=dict, repr=False, compare=False
    )
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("debug_images", None)
        return _json_safe(payload)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value
