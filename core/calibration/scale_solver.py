from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .config import CalibrationConfig
from .image_utils import angle_axis
from .models import (
    CalibrationResult,
    DetectedNumber,
    RulerDetection,
    ScaleBarSelection,
    TickMark,
)


@dataclass(frozen=True)
class GridFit:
    success: bool
    pixels_per_mm: float = 0.0
    intercept_px: float = 0.0
    rmse_px: float = 0.0
    fit_error_percent: float = 0.0
    span_mm: float = 0.0
    usable_intervals: int = 0
    occupancy: float = 0.0
    tick_indexes: tuple[int | None, ...] = ()
    residuals_px: tuple[float | None, ...] = ()


def pixels_per_mm_to_um_per_pixel(pixels_per_mm: float) -> float:
    value = float(pixels_per_mm)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("pixels_per_mm must be positive and finite")
    return 1000.0 / value


def scale_bar_pixels(length_um: float, um_per_pixel: float) -> float:
    length = float(length_um)
    scale = float(um_per_pixel)
    if not math.isfinite(length) or length <= 0 or not math.isfinite(scale) or scale <= 0:
        raise ValueError("Scale bar length and um_per_pixel must be positive and finite")
    return length / scale


def select_scale_bar(
    image_width_px: int,
    um_per_pixel: float,
    config: CalibrationConfig | None = None,
) -> ScaleBarSelection:
    cfg = config or CalibrationConfig()
    physical_width_um = float(image_width_px) * float(um_per_pixel)
    target = physical_width_um * cfg.scale_bar_target_width_fraction
    if target <= 0 or not math.isfinite(target):
        raise ValueError("Image width and scale must define a positive physical width")
    exponent = math.floor(math.log10(target))
    candidates: list[float] = []
    for power in range(exponent - 2, exponent + 3):
        candidates.extend(multiplier * 10.0**power for multiplier in (1.0, 2.0, 5.0))
    minimum = physical_width_um * cfg.scale_bar_min_width_fraction
    maximum = physical_width_um * cfg.scale_bar_max_width_fraction
    in_range = [value for value in candidates if minimum <= value <= maximum]
    pool = in_range or candidates
    selected = min(pool, key=lambda value: abs(math.log(value / target)))
    rendered = scale_bar_pixels(selected, um_per_pixel)
    if selected >= 10_000 and selected % 10_000 == 0:
        label = f"{selected / 10_000:g} cm"
    elif selected >= 1000:
        label = f"{selected / 1000:g} mm"
    else:
        label = f"{selected:g} µm"
    return ScaleBarSelection(selected, rendered, label)


class ScaleSolver:
    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()

    def solve(
        self,
        detection: RulerDetection,
        ticks: list[TickMark],
        numbers: list[DetectedNumber],
        *,
        input_resolution: tuple[int, int],
        ocr_available: bool,
        ocr_diagnostic: str,
    ) -> CalibrationResult:
        result = CalibrationResult(
            ruler_angle_deg=detection.angle_deg if detection.success else None,
            ruler_detection=detection,
            detected_numbers=numbers,
            input_resolution=input_resolution,
            ocr_available=ocr_available,
            ocr_diagnostic=ocr_diagnostic,
        )
        if not detection.success:
            result.failure_reasons.append("ruler_not_found")
            return result
        if len(ticks) < 2:
            result.failure_reasons.append("no_ticks" if not ticks else "insufficient_ticks")
            return result

        center = np.asarray(detection.center, dtype=np.float64)
        axis = angle_axis(detection.angle_deg)
        projected = np.asarray(
            [float((np.asarray(tick.original_position) - center) @ axis) for tick in ticks],
            dtype=np.float64,
        )
        order = np.argsort(projected)
        ordered_ticks = [ticks[int(index)] for index in order]
        fit = self._robust_grid_fit(projected[order])
        if not fit.success:
            for tick in ticks:
                tick.accepted = False
                tick.rejection_reason = "not_on_periodic_grid"
            result.rejected_ticks = list(ticks)
            result.failure_reasons.append("insufficient_ticks")
            return result

        accepted: list[TickMark] = []
        rejected: list[TickMark] = []
        for tick, index, residual in zip(ordered_ticks, fit.tick_indexes, fit.residuals_px):
            if index is None or residual is None:
                tick.accepted = False
                tick.rejection_reason = "grid_outlier_or_duplicate"
                rejected.append(tick)
            else:
                tick.accepted = True
                tick.fitted_mm = float(index)
                tick.residual_px = float(residual)
                accepted.append(tick)

        result.detected_major_ticks = [tick for tick in accepted if tick.kind == "major"]
        result.detected_minor_ticks = [tick for tick in accepted if tick.kind != "major"]
        result.rejected_ticks = rejected
        result.pixels_per_mm = fit.pixels_per_mm
        result.um_per_pixel = pixels_per_mm_to_um_per_pixel(fit.pixels_per_mm)
        result.calibration_span_mm = fit.span_mm
        result.fit_rmse_px = fit.rmse_px
        result.fit_error_percent = fit.fit_error_percent
        result.usable_intervals = fit.usable_intervals
        result.ocr_usable = self._cross_validate_ocr(numbers, accepted, fit.pixels_per_mm)

        if not ocr_available:
            result.warnings.append("ocr_unavailable")
        elif not result.ocr_usable:
            result.warnings.append("ocr_unusable")
        if fit.usable_intervals < self.config.min_usable_intervals:
            result.failure_reasons.append("insufficient_intervals")
        if fit.span_mm < self.config.min_calibration_span_mm:
            result.failure_reasons.append("insufficient_span")
        if fit.fit_error_percent > self.config.max_fit_error_percent:
            result.failure_reasons.append("geometric_inconsistency")
        if len(result.detected_minor_ticks) < self.config.min_usable_intervals:
            result.failure_reasons.append("insufficient_minor_ticks")
        if not math.isfinite(fit.pixels_per_mm) or fit.pixels_per_mm <= 0:
            result.failure_reasons.append("invalid_scale")

        result.quality_score = self._quality_score(detection, fit, result.ocr_usable, ocr_available)
        result.success = not result.failure_reasons
        result.quality_label = "PASS" if result.success else "FAIL"
        if result.success:
            result.scale_bar = select_scale_bar(input_resolution[0], result.um_per_pixel, self.config)
        result.diagnostics.update({
            "grid_occupancy": fit.occupancy,
            "accepted_tick_count": len(accepted),
            "rejected_tick_count": len(rejected),
            "quality_score_definition": {
                "ruler_detection": 25,
                "usable_ticks": 20,
                "span": 15,
                "fit_residual": 20,
                "grid_occupancy": 10,
                "ocr_agreement": 10,
            },
        })
        return result

    def _robust_grid_fit(self, positions: np.ndarray) -> GridFit:
        values = np.unique(np.asarray(positions, dtype=np.float64))
        if values.size < 3:
            return GridFit(False)
        span = float(values[-1] - values[0])
        if span <= 0:
            return GridFit(False)
        candidates: set[float] = set()
        max_neighbor = min(12, values.size - 1)
        for start in range(values.size - 1):
            for offset in range(1, min(max_neighbor, values.size - start - 1) + 1):
                distance = float(values[start + offset] - values[start])
                for divisor in range(1, min(12, offset + 4) + 1):
                    pitch = distance / divisor
                    if 2.0 <= pitch <= span:
                        candidates.add(round(pitch, 5))
        if not candidates:
            return GridFit(False)

        best: tuple[float, float, np.ndarray, np.ndarray] | None = None
        sample_refs = values[: min(values.size, 24)]
        for pitch in candidates:
            for reference in sample_refs:
                indexes = np.rint((values - reference) / pitch).astype(int)
                fitted = reference + indexes * pitch
                residuals = np.abs(values - fitted)
                mask = residuals <= pitch * self.config.grid_residual_tolerance_fraction
                unique_indexes = np.unique(indexes[mask])
                if unique_indexes.size < 3:
                    continue
                index_span = int(unique_indexes[-1] - unique_indexes[0])
                if index_span <= 0:
                    continue
                occupancy = unique_indexes.size / (index_span + 1)
                gaps = np.diff(unique_indexes)
                adjacent = float(np.mean(gaps == 1)) if gaps.size else 0.0
                rmse_fraction = float(np.sqrt(np.mean((residuals[mask] / pitch) ** 2)))
                score = (
                    unique_indexes.size
                    + 8.0 * occupancy
                    + 8.0 * adjacent
                    - 5.0 * rmse_fraction
                )
                if best is None or score > best[0]:
                    best = (score, pitch, indexes, mask)
        if best is None:
            return GridFit(False)

        _, pitch, indexes, mask = best
        # Resolve duplicate grid assignments using the closest observation.
        for _ in range(4):
            active = np.flatnonzero(mask)
            if active.size < 3:
                return GridFit(False)
            unique_active: list[int] = []
            for grid_index in np.unique(indexes[active]):
                group = active[indexes[active] == grid_index]
                if group.size == 1:
                    unique_active.append(int(group[0]))
                else:
                    expected = values[active[0]] + (grid_index - indexes[active[0]]) * pitch
                    unique_active.append(int(group[np.argmin(np.abs(values[group] - expected))]))
            active = np.asarray(unique_active, dtype=int)
            slope, intercept = np.polyfit(indexes[active], values[active], 1)
            residual = values - (intercept + slope * indexes)
            median = float(np.median(residual[active]))
            mad = float(np.median(np.abs(residual[active] - median)))
            limit = max(abs(slope) * self.config.grid_residual_tolerance_fraction, 3.5 * 1.4826 * mad)
            new_mask = np.abs(residual - median) <= limit
            # Keep only one observation per integer tick.
            for grid_index in np.unique(indexes[new_mask]):
                group = np.flatnonzero(new_mask & (indexes == grid_index))
                if group.size > 1:
                    keep = group[np.argmin(np.abs(residual[group]))]
                    new_mask[group] = False
                    new_mask[keep] = True
            if np.array_equal(new_mask, mask):
                mask = new_mask
                break
            mask = new_mask
            pitch = abs(float(slope))

        active = np.flatnonzero(mask)
        if active.size < 3:
            return GridFit(False)
        slope, intercept = np.polyfit(indexes[active], values[active], 1)
        slope = abs(float(slope))
        fitted_values = intercept + float(np.polyfit(indexes[active], values[active], 1)[0]) * indexes[active]
        active_residuals = values[active] - fitted_values
        rmse = float(np.sqrt(np.mean(active_residuals**2)))
        normalized_indexes = indexes - int(np.min(indexes[active]))
        index_span = int(np.max(normalized_indexes[active]) - np.min(normalized_indexes[active]))
        occupancy = active.size / (index_span + 1)
        out_indexes: list[int | None] = []
        out_residuals: list[float | None] = []
        residual_all = values - (intercept + float(np.polyfit(indexes[active], values[active], 1)[0]) * indexes)
        for item_index in range(values.size):
            if mask[item_index]:
                out_indexes.append(int(normalized_indexes[item_index]))
                out_residuals.append(float(residual_all[item_index]))
            else:
                out_indexes.append(None)
                out_residuals.append(None)
        return GridFit(
            True,
            pixels_per_mm=slope,
            intercept_px=float(intercept),
            rmse_px=rmse,
            fit_error_percent=rmse / slope * 100.0,
            span_mm=float(index_span),
            usable_intervals=max(0, active.size - 1),
            occupancy=float(occupancy),
            tick_indexes=tuple(out_indexes),
            residuals_px=tuple(out_residuals),
        )

    def _cross_validate_ocr(
        self,
        numbers: list[DetectedNumber],
        ticks: list[TickMark],
        pixels_per_mm: float,
    ) -> bool:
        if not numbers or not ticks:
            return False
        major = [tick for tick in ticks if tick.kind == "major"] or ticks
        associations: list[tuple[DetectedNumber, TickMark]] = []
        mm_values = np.asarray([float(tick.fitted_mm) for tick in ticks if tick.fitted_mm is not None])
        rectified_values = np.asarray([
            tick.rectified_position_px for tick in ticks if tick.fitted_mm is not None
        ])
        if mm_values.size >= 2:
            rectified_pixels_per_mm = abs(float(np.polyfit(mm_values, rectified_values, 1)[0]))
        else:
            rectified_pixels_per_mm = pixels_per_mm
        max_distance = rectified_pixels_per_mm * self.config.ocr_major_tick_max_distance_mm
        for number in numbers:
            nearest = min(major, key=lambda tick: abs(tick.rectified_position_px - number.center[0]))
            if abs(nearest.rectified_position_px - number.center[0]) > max_distance:
                number.accepted = False
                number.rejection_reason = "no_nearby_major_tick"
                continue
            number.associated_tick_mm = nearest.fitted_mm
            associations.append((number, nearest))
        if len(associations) < 2:
            return False
        best: tuple[int, float, int, float] | None = None
        for direction in (-1, 1):
            offsets = np.asarray([
                float(number.value) - direction * float(tick.fitted_mm) / 10.0
                for number, tick in associations if number.value is not None and tick.fitted_mm is not None
            ])
            if offsets.size < 2:
                continue
            offset = float(np.median(offsets))
            residuals = np.asarray([
                abs(float(number.value) - (offset + direction * float(tick.fitted_mm) / 10.0))
                for number, tick in associations
            ])
            inliers = int(np.count_nonzero(residuals <= 0.36))
            median_residual = float(np.median(residuals))
            candidate = (inliers, -median_residual, direction, offset)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        if best is None:
            return False
        _, _, direction, offset = best
        accepted_count = 0
        for number, tick in associations:
            predicted = offset + direction * float(tick.fitted_mm) / 10.0
            if abs(float(number.value) - predicted) <= 0.36:
                number.accepted = True
                accepted_count += 1
            else:
                corrected = int(round(predicted))
                number.accepted = False
                number.corrected_value = corrected if corrected >= 0 else None
                number.rejection_reason = "ocr_geometry_inconsistency"
        return accepted_count >= 2

    def _quality_score(
        self,
        detection: RulerDetection,
        fit: GridFit,
        ocr_usable: bool,
        ocr_available: bool,
    ) -> float:
        ruler = 25.0 * np.clip(detection.confidence, 0.0, 1.0)
        ticks = 20.0 * np.clip(fit.usable_intervals / max(self.config.min_usable_intervals, 1), 0.0, 1.0)
        span = 15.0 * np.clip(fit.span_mm / self.config.preferred_calibration_span_mm, 0.0, 1.0)
        residual = 20.0 * np.clip(1.0 - fit.fit_error_percent / self.config.max_fit_error_percent, 0.0, 1.0)
        occupancy = 10.0 * np.clip(fit.occupancy, 0.0, 1.0)
        ocr = 10.0 if ocr_usable else (2.0 if ocr_available else 0.0)
        return round(float(ruler + ticks + span + residual + occupancy + ocr), 1)
