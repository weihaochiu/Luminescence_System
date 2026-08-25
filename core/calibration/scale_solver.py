from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .config import CalibrationConfig
from .image_utils import angle_axis
from .models import (
    CalibrationResult,
    DetectedNumber,
    PhysicalPitchHypothesis,
    RulerDetection,
    ScaleBarSelection,
    TickMark,
    VerificationMode,
)


@dataclass(frozen=True)
class GridFit:
    success: bool
    periodic_pitch_px: float = 0.0
    intercept_px: float = 0.0
    rmse_px: float = 0.0
    fit_error_percent: float = 0.0
    span_intervals: int = 0
    usable_intervals: int = 0
    occupancy: float = 0.0
    tick_indexes: tuple[int | None, ...] = ()
    residuals_px: tuple[float | None, ...] = ()


@dataclass(frozen=True)
class OCREvaluation:
    usable: bool = False
    support: float = 0.0
    direction: int = 1
    offset: float = 0.0
    associations: tuple[tuple[int, int], ...] = ()
    inlier_number_indexes: tuple[int, ...] = ()


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
    selected = min(in_range or candidates, key=lambda value: abs(math.log(value / target)))
    rendered = scale_bar_pixels(selected, um_per_pixel)
    if selected >= 10_000 and selected % 10_000 == 0:
        label = f"{selected / 10_000:g} cm"
    elif selected >= 1000:
        label = f"{selected / 1000:g} mm"
    else:
        label = f"{selected:g} µm"
    return ScaleBarSelection(selected, rendered, label)


class ScaleSolver:
    """Separate periodic image geometry from the ruler's physical tick pitch."""

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
                tick.periodic_grid_index = int(index)
                tick.residual_px = float(residual)
                accepted.append(tick)

        result.detected_major_ticks = [tick for tick in accepted if tick.kind == "major"]
        result.detected_minor_ticks = [tick for tick in accepted if tick.kind != "major"]
        result.rejected_ticks = rejected
        result.periodic_pitch_px = fit.periodic_pitch_px
        result.fit_rmse_px = fit.rmse_px
        result.fit_error_percent = fit.fit_error_percent
        result.usable_intervals = fit.usable_intervals

        hypotheses, ocr_evaluations = self._physical_hypotheses(fit, accepted, numbers)
        result.pitch_hypotheses = hypotheses
        selected, verification_mode = self._select_hypothesis(hypotheses, ocr_evaluations)
        result.verification_mode = verification_mode.value

        if selected is None:
            result.failure_reasons.append("ambiguous_physical_pitch")
        else:
            result.physical_pitch_mm = selected.physical_pitch_mm
            result.pixels_per_mm = selected.pixels_per_mm
            result.um_per_pixel = pixels_per_mm_to_um_per_pixel(selected.pixels_per_mm)
            result.calibration_span_mm = fit.span_intervals * selected.physical_pitch_mm
            for tick in accepted:
                if tick.periodic_grid_index is not None:
                    tick.fitted_mm = tick.periodic_grid_index * selected.physical_pitch_mm
            evaluation = ocr_evaluations[selected.physical_pitch_mm]
            if verification_mode is VerificationMode.OCR_VERIFIED:
                result.ocr_usable = self._apply_ocr_evaluation(
                    numbers, accepted, selected.physical_pitch_mm, evaluation
                )

        if not ocr_available:
            result.warnings.append("ocr_unavailable")
        elif not result.ocr_usable:
            result.warnings.append("ocr_unusable")
        required_intervals = (
            max(2, self.config.ocr_min_associations - 1)
            if result.verification_mode == VerificationMode.OCR_VERIFIED.value
            else self.config.min_usable_intervals
        )
        if fit.usable_intervals < required_intervals:
            result.failure_reasons.append("insufficient_intervals")
        if selected is not None and result.calibration_span_mm < self.config.min_calibration_span_mm:
            result.failure_reasons.append("insufficient_span")
        if fit.fit_error_percent > self.config.max_fit_error_percent:
            result.failure_reasons.append("geometric_inconsistency")
        if not math.isfinite(fit.periodic_pitch_px) or fit.periodic_pitch_px <= 0:
            result.failure_reasons.append("invalid_scale")

        result.quality_score = self._quality_score(
            detection, fit, result.calibration_span_mm, result.ocr_usable, ocr_available
        )
        result.success = (
            not result.failure_reasons
            and result.verification_mode
            in {
                VerificationMode.TICK_HIERARCHY_VERIFIED.value,
                VerificationMode.OCR_VERIFIED.value,
            }
        )
        result.quality_label = "PASS" if result.success else "FAIL"
        if result.success and result.um_per_pixel is not None:
            result.scale_bar = select_scale_bar(input_resolution[0], result.um_per_pixel, self.config)
        result.diagnostics.update({
            "grid_occupancy": fit.occupancy,
            "accepted_tick_count": len(accepted),
            "rejected_tick_count": len(rejected),
            "periodic_span_intervals": fit.span_intervals,
            "quality_score_definition": {
                "ruler_detection": 25,
                "usable_ticks": 20,
                "physical_span": 15,
                "fit_residual": 20,
                "grid_occupancy": 10,
                "ocr_agreement": 10,
            },
        })
        return result

    def _physical_hypotheses(
        self,
        fit: GridFit,
        ticks: list[TickMark],
        numbers: list[DetectedNumber],
    ) -> tuple[list[PhysicalPitchHypothesis], dict[float, OCREvaluation]]:
        minor_count = sum(tick.kind == "minor" for tick in ticks)
        medium = [tick for tick in ticks if tick.kind == "medium"]
        major = [tick for tick in ticks if tick.kind == "major"]
        evaluations: dict[float, OCREvaluation] = {}
        hypotheses: list[PhysicalPitchHypothesis] = []
        residual_score = float(np.clip(
            1.0 - fit.fit_error_percent / max(self.config.max_fit_error_percent, 1e-9),
            0.0,
            1.0,
        ))
        for physical_pitch in self.config.physical_pitch_hypotheses_mm:
            kind_major_support, major_phase = self._kind_phase_support(major, 10.0 / physical_pitch)
            kind_medium_support = self._medium_phase_support(
                medium, 10.0 / physical_pitch, 5.0 / physical_pitch, major_phase
            )
            length_major_support, length_medium_support, length_major_phase = (
                self._length_hierarchy_support(ticks, physical_pitch)
            )
            if length_major_phase is not None:
                major_phase = length_major_phase
                kind_medium_support = self._medium_phase_support(
                    medium, 10.0 / physical_pitch, 5.0 / physical_pitch, major_phase
                )
            major_support = 0.15 * kind_major_support + 0.85 * length_major_support
            medium_support = 0.15 * kind_medium_support + 0.85 * length_medium_support
            minor_support = min(1.0, minor_count / max(self.config.hierarchy_min_minor_ticks, 1))
            if physical_pitch != 1.0:
                minor_support = 0.0
            hierarchy_score = 0.30 * minor_support + 0.30 * medium_support + 0.40 * major_support
            evaluation = self._evaluate_ocr(numbers, ticks, physical_pitch, fit.periodic_pitch_px)
            evaluations[physical_pitch] = evaluation
            accepted_by_hierarchy = (
                physical_pitch == 1.0
                and minor_count >= self.config.hierarchy_min_minor_ticks
                and len(medium) >= self.config.hierarchy_min_medium_ticks
                and len(major) >= self.config.hierarchy_min_major_ticks
                and medium_support >= self.config.hierarchy_min_support
                and major_support >= self.config.hierarchy_min_support
                and hierarchy_score >= self.config.hierarchy_score_acceptance
            )
            accepted = accepted_by_hierarchy or evaluation.usable
            rejection_reasons: list[str] = []
            if not accepted_by_hierarchy:
                rejection_reasons.append("tick_hierarchy_insufficient")
            if not evaluation.usable:
                rejection_reasons.append("ocr_physical_pitch_unverified")
            hypotheses.append(PhysicalPitchHypothesis(
                periodic_pitch_px=fit.periodic_pitch_px,
                physical_pitch_mm=physical_pitch,
                pixels_per_mm=fit.periodic_pitch_px / physical_pitch,
                minor_support=round(minor_support, 6),
                medium_support=round(medium_support, 6),
                major_support=round(major_support, 6),
                ocr_support=round(evaluation.support, 6),
                hierarchy_score=round(hierarchy_score, 6),
                residual_score=round(residual_score, 6),
                total_score=round(
                    0.55 * hierarchy_score + 0.30 * evaluation.support + 0.15 * residual_score,
                    6,
                ),
                accepted=accepted,
                acceptance_reason=(
                    "ocr_adjacent_centimeter_sequence"
                    if evaluation.usable
                    else "complete_1mm_tick_hierarchy"
                    if accepted_by_hierarchy
                    else ""
                ),
                rejection_reasons=[] if accepted else rejection_reasons,
            ))
        return hypotheses, evaluations

    def _length_hierarchy_support(
        self,
        ticks: list[TickMark],
        physical_pitch_mm: float,
    ) -> tuple[float, float, float | None]:
        major_steps = 10.0 / physical_pitch_mm
        half_steps = 5.0 / physical_pitch_mm
        if (
            not ticks
            or major_steps < 1.0
            or abs(major_steps - round(major_steps)) > 1e-6
            or abs(half_steps - round(half_steps)) > 1e-6
        ):
            return 0.0, 0.0, None
        period = int(round(major_steps))
        half = int(round(half_steps))
        samples = [
            (int(tick.periodic_grid_index), float(tick.length_px))
            for tick in ticks if tick.periodic_grid_index is not None
        ]
        if len(samples) < 3:
            return 0.0, 0.0, None
        best: tuple[float, int, list[float], list[float], list[float]] | None = None
        for phase in range(period):
            major_lengths = [length for index, length in samples if index % period == phase]
            medium_phase = (phase + half) % period
            medium_lengths = [length for index, length in samples if index % period == medium_phase]
            baseline = [
                length for index, length in samples
                if index % period not in {phase, medium_phase}
            ]
            if not major_lengths or not medium_lengths or not baseline:
                continue
            base = float(np.median(baseline))
            separation = float(np.mean(major_lengths)) - base
            candidate = (separation, phase, major_lengths, medium_lengths, baseline)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return 0.0, 0.0, None
        _, phase, major_lengths, medium_lengths, baseline = best
        base = float(np.median(baseline))
        major_mean = float(np.mean(major_lengths))
        medium_mean = float(np.mean(medium_lengths))
        spread = max(float(np.percentile([length for _, length in samples], 95)) - base, 1.0)
        major_support = float(np.clip((major_mean - base) / spread, 0.0, 1.0))
        hierarchy_range = max(major_mean - base, 1.0)
        medium_level = float(np.clip(
            2.0 * (medium_mean - base) / hierarchy_range, 0.0, 1.0
        ))
        # A medium tier must be observably shorter than the major tier. This
        # prevents a every-2-mm subset of identical 10-mm marks from masquerading
        # as alternating 5/10-mm evidence for a 1-mm periodic grid.
        tier_ordering = float(np.clip(
            (major_mean - medium_mean) / max(0.20 * hierarchy_range, 1.0),
            0.0,
            1.0,
        ))
        medium_support = medium_level * tier_ordering
        return major_support, medium_support, float(phase)

    def _select_hypothesis(
        self,
        hypotheses: list[PhysicalPitchHypothesis],
        evaluations: dict[float, OCREvaluation],
    ) -> tuple[PhysicalPitchHypothesis | None, VerificationMode]:
        ocr_verified = [item for item in hypotheses if evaluations[item.physical_pitch_mm].usable]
        if len(ocr_verified) == 1:
            return ocr_verified[0], VerificationMode.OCR_VERIFIED
        if len(ocr_verified) > 1:
            return None, VerificationMode.GEOMETRY_PERIODIC_ONLY
        hierarchy_verified = [
            item for item in hypotheses
            if item.accepted and item.acceptance_reason == "complete_1mm_tick_hierarchy"
        ]
        if len(hierarchy_verified) == 1:
            return hierarchy_verified[0], VerificationMode.TICK_HIERARCHY_VERIFIED
        return None, VerificationMode.GEOMETRY_PERIODIC_ONLY

    def _kind_phase_support(
        self,
        ticks: list[TickMark],
        period_steps: float,
    ) -> tuple[float, float | None]:
        if not ticks or period_steps < 1.0 or abs(period_steps - round(period_steps)) > 1e-6:
            return 0.0, None
        period = int(round(period_steps))
        indexes = [tick.periodic_grid_index for tick in ticks if tick.periodic_grid_index is not None]
        if not indexes:
            return 0.0, None
        best_count = -1
        best_phase = 0
        for phase in range(period):
            count = sum(
                self._phase_distance(index % period, phase, period)
                <= self.config.hierarchy_phase_tolerance_steps
                for index in indexes
            )
            if count > best_count:
                best_count = count
                best_phase = phase
        return best_count / len(indexes), float(best_phase)

    def _medium_phase_support(
        self,
        ticks: list[TickMark],
        major_period_steps: float,
        half_period_steps: float,
        major_phase: float | None,
    ) -> float:
        if (
            not ticks
            or major_phase is None
            or major_period_steps < 1.0
            or abs(major_period_steps - round(major_period_steps)) > 1e-6
            or abs(half_period_steps - round(half_period_steps)) > 1e-6
        ):
            return 0.0
        period = int(round(major_period_steps))
        expected = (int(round(major_phase)) + int(round(half_period_steps))) % period
        indexes = [tick.periodic_grid_index for tick in ticks if tick.periodic_grid_index is not None]
        if not indexes:
            return 0.0
        count = sum(
            self._phase_distance(index % period, expected, period)
            <= self.config.hierarchy_phase_tolerance_steps
            for index in indexes
        )
        return count / len(indexes)

    @staticmethod
    def _phase_distance(value: float, expected: float, period: int) -> float:
        delta = abs(value - expected)
        return min(delta, period - delta)

    def _evaluate_ocr(
        self,
        numbers: list[DetectedNumber],
        ticks: list[TickMark],
        physical_pitch_mm: float,
        periodic_pitch_px: float,
    ) -> OCREvaluation:
        if not numbers or not ticks:
            return OCREvaluation()
        major = [tick for tick in ticks if tick.kind == "major"] or sorted(
            ticks, key=lambda tick: tick.length_px, reverse=True
        )[: max(2, len(ticks) // 5)]
        rectified_positions = np.asarray([tick.rectified_position_px for tick in ticks])
        grid_indexes = np.asarray([float(tick.periodic_grid_index or 0) for tick in ticks])
        rectified_periodic_pitch = (
            abs(float(np.polyfit(grid_indexes, rectified_positions, 1)[0]))
            if len(ticks) >= 2
            else periodic_pitch_px
        )
        max_steps = max(0.75, self.config.ocr_major_tick_max_distance_mm / physical_pitch_mm)
        max_distance = rectified_periodic_pitch * max_steps
        associations: list[tuple[int, int]] = []
        for number_index, number in enumerate(numbers):
            if number.value is None:
                continue
            tick = min(major, key=lambda item: abs(item.rectified_position_px - number.center[0]))
            if abs(tick.rectified_position_px - number.center[0]) <= max_distance:
                associations.append((number_index, ticks.index(tick)))
        if len(associations) < self.config.ocr_min_associations:
            return OCREvaluation(associations=tuple(associations))

        best: tuple[int, float, int, float, np.ndarray] | None = None
        for direction in (-1, 1):
            offsets = np.asarray([
                float(numbers[number_index].value)
                - direction * float(ticks[tick_index].periodic_grid_index) * physical_pitch_mm / 10.0
                for number_index, tick_index in associations
            ])
            offset = float(np.median(offsets))
            residuals = np.asarray([
                abs(
                    float(numbers[number_index].value)
                    - (offset + direction * float(ticks[tick_index].periodic_grid_index) * physical_pitch_mm / 10.0)
                )
                for number_index, tick_index in associations
            ])
            inliers = int(np.count_nonzero(residuals <= self.config.ocr_value_residual_tolerance))
            candidate = (inliers, -float(np.median(residuals)), direction, offset, residuals)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        if best is None:
            return OCREvaluation(associations=tuple(associations))
        inlier_count, _, direction, offset, residuals = best
        inlier_indexes = tuple(
            associations[index][0]
            for index in range(len(associations))
            if residuals[index] <= self.config.ocr_value_residual_tolerance
        )
        support = inlier_count / len(associations)
        inlier_pairs = [
            associations[index]
            for index in range(len(associations))
            if residuals[index] <= self.config.ocr_value_residual_tolerance
        ]
        physical_values = [
            float(ticks[tick_index].periodic_grid_index) * physical_pitch_mm
            for _, tick_index in inlier_pairs
        ]
        label_values = [float(numbers[number_index].value) for number_index, _ in inlier_pairs]
        physical_span = max(physical_values) - min(physical_values) if physical_values else 0.0
        label_span = max(label_values) - min(label_values) if label_values else 0.0
        has_centimeter_span = physical_span >= 9.0 and label_span >= 0.9
        usable = (
            inlier_count >= self.config.ocr_min_associations
            and support >= self.config.ocr_hypothesis_min_support
            and has_centimeter_span
        )
        return OCREvaluation(
            usable=usable,
            support=support if has_centimeter_span else 0.0,
            direction=direction,
            offset=offset,
            associations=tuple(associations),
            inlier_number_indexes=inlier_indexes,
        )

    def _apply_ocr_evaluation(
        self,
        numbers: list[DetectedNumber],
        ticks: list[TickMark],
        physical_pitch_mm: float,
        evaluation: OCREvaluation,
    ) -> bool:
        associated_numbers = {number_index for number_index, _ in evaluation.associations}
        inliers = set(evaluation.inlier_number_indexes)
        for number_index, number in enumerate(numbers):
            number.corrected_value = None
            if number_index not in associated_numbers:
                number.accepted = False
                number.rejection_reason = "no_nearby_major_tick"
        for number_index, tick_index in evaluation.associations:
            number = numbers[number_index]
            tick = ticks[tick_index]
            number.associated_tick_mm = (
                float(tick.periodic_grid_index) * physical_pitch_mm
                if tick.periodic_grid_index is not None else None
            )
            predicted = evaluation.offset + evaluation.direction * float(number.associated_tick_mm) / 10.0
            if number_index in inliers:
                number.accepted = True
                number.rejection_reason = ""
            else:
                corrected = int(round(predicted))
                number.accepted = False
                number.corrected_value = corrected if corrected >= 0 else None
                number.rejection_reason = "ocr_geometry_inconsistency"
        return evaluation.usable

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
                score = unique_indexes.size + 8.0 * occupancy + 8.0 * adjacent - 5.0 * rmse_fraction
                if best is None or score > best[0]:
                    best = (score, pitch, indexes, mask)
        if best is None:
            return GridFit(False)

        _, pitch, indexes, mask = best
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
            signed_slope, intercept = np.polyfit(indexes[active], values[active], 1)
            residual = values - (intercept + signed_slope * indexes)
            median = float(np.median(residual[active]))
            mad = float(np.median(np.abs(residual[active] - median)))
            limit = max(abs(signed_slope) * self.config.grid_residual_tolerance_fraction, 3.5 * 1.4826 * mad)
            new_mask = np.abs(residual - median) <= limit
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
            pitch = abs(float(signed_slope))

        active = np.flatnonzero(mask)
        if active.size < 3:
            return GridFit(False)
        signed_slope, intercept = np.polyfit(indexes[active], values[active], 1)
        pitch = abs(float(signed_slope))
        active_residuals = values[active] - (intercept + signed_slope * indexes[active])
        rmse = float(np.sqrt(np.mean(active_residuals**2)))
        normalized_indexes = indexes - int(np.min(indexes[active]))
        index_span = int(np.max(normalized_indexes[active]) - np.min(normalized_indexes[active]))
        occupancy = active.size / (index_span + 1)
        residual_all = values - (intercept + signed_slope * indexes)
        out_indexes: list[int | None] = []
        out_residuals: list[float | None] = []
        for item_index in range(values.size):
            if mask[item_index]:
                out_indexes.append(int(normalized_indexes[item_index]))
                out_residuals.append(float(residual_all[item_index]))
            else:
                out_indexes.append(None)
                out_residuals.append(None)
        return GridFit(
            True,
            periodic_pitch_px=pitch,
            intercept_px=float(intercept),
            rmse_px=rmse,
            fit_error_percent=rmse / pitch * 100.0,
            span_intervals=index_span,
            usable_intervals=max(0, active.size - 1),
            occupancy=float(occupancy),
            tick_indexes=tuple(out_indexes),
            residuals_px=tuple(out_residuals),
        )

    def _quality_score(
        self,
        detection: RulerDetection,
        fit: GridFit,
        physical_span_mm: float,
        ocr_usable: bool,
        ocr_available: bool,
    ) -> float:
        ruler = 25.0 * np.clip(detection.confidence, 0.0, 1.0)
        ticks = 20.0 * np.clip(fit.usable_intervals / max(self.config.min_usable_intervals, 1), 0.0, 1.0)
        span = 15.0 * np.clip(physical_span_mm / self.config.preferred_calibration_span_mm, 0.0, 1.0)
        residual = 20.0 * np.clip(1.0 - fit.fit_error_percent / self.config.max_fit_error_percent, 0.0, 1.0)
        occupancy = 10.0 * np.clip(fit.occupancy, 0.0, 1.0)
        ocr = 10.0 if ocr_usable else (2.0 if ocr_available else 0.0)
        return round(float(ruler + ticks + span + residual + occupancy + ocr), 1)
