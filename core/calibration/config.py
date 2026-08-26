from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationConfig:
    """Centralized, deliberately conservative first-stage quality thresholds."""

    min_ruler_aspect_ratio: float = 3.5
    min_ruler_area_fraction: float = 0.015
    max_ruler_area_fraction: float = 0.92
    min_ruler_confidence: float = 0.35
    partial_ruler_min_aspect_ratio: float = 1.6
    partial_ruler_min_area_fraction: float = 0.08
    partial_ruler_min_rectangularity: float = 0.55
    partial_ruler_min_periodicity: float = 0.55
    min_rectified_blur_laplacian_variance: float = 20.0
    max_rectified_saturated_fraction: float = 0.92
    rectified_min_height_px: int = 40
    tick_edge_band_fraction: float = 0.42
    tick_min_length_fraction: float = 0.055
    tick_max_width_fraction: float = 0.035
    tick_merge_distance_px: float = 3.0
    tick_merge_distance_height_fraction: float = 0.004
    grid_residual_tolerance_fraction: float = 0.24
    fit_outlier_sigma: float = 3.5
    min_usable_intervals: int = 10
    min_calibration_span_mm: float = 10.0
    preferred_calibration_span_mm: float = 25.0
    max_fit_error_percent: float = 8.0
    ocr_min_confidence: float = 25.0
    ocr_major_tick_max_distance_mm: float = 4.0
    physical_pitch_hypotheses_mm: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0)
    hierarchy_phase_tolerance_steps: float = 0.30
    hierarchy_min_minor_ticks: int = 6
    hierarchy_min_medium_ticks: int = 2
    hierarchy_min_major_ticks: int = 2
    hierarchy_min_support: float = 0.70
    hierarchy_score_acceptance: float = 0.62
    ocr_value_residual_tolerance: float = 0.20
    ocr_min_associations: int = 2
    ocr_hypothesis_min_support: float = 0.66
    physical_pitch_relative_tolerance: float = 0.12
    scale_bar_min_width_fraction: float = 0.15
    scale_bar_target_width_fraction: float = 0.20
    scale_bar_max_width_fraction: float = 0.25
