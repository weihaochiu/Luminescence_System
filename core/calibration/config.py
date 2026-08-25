from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationConfig:
    """Centralized, deliberately conservative first-stage quality thresholds."""

    min_ruler_aspect_ratio: float = 3.5
    min_ruler_area_fraction: float = 0.015
    max_ruler_area_fraction: float = 0.92
    min_ruler_confidence: float = 0.35
    rectified_min_height_px: int = 40
    tick_edge_band_fraction: float = 0.42
    tick_min_length_fraction: float = 0.055
    tick_max_width_fraction: float = 0.035
    tick_merge_distance_px: float = 3.0
    grid_residual_tolerance_fraction: float = 0.24
    fit_outlier_sigma: float = 3.5
    min_usable_intervals: int = 10
    min_calibration_span_mm: float = 10.0
    preferred_calibration_span_mm: float = 25.0
    max_fit_error_percent: float = 8.0
    ocr_min_confidence: float = 25.0
    ocr_major_tick_max_distance_mm: float = 4.0
    scale_bar_min_width_fraction: float = 0.15
    scale_bar_target_width_fraction: float = 0.20
    scale_bar_max_width_fraction: float = 0.25
