from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from .config import CalibrationConfig
from .models import CalibrationResult, VerificationMode
from .ruler_rectifier import RulerRectifier


@dataclass(frozen=True)
class RulerCandidateQualityConfig:
    """Provisional acquisition-layer candidate gates, separate from physical scale gates."""

    min_candidate_confidence: float = 0.55
    min_periodicity: float = 0.55
    min_accepted_ticks: int = 10
    min_spacing_fraction: float = 0.005
    max_spacing_fraction: float = 0.08
    max_orientation_disagreement_deg: float = 18.0
    min_polygon_inside_fraction: float = 0.50
    min_roi_area_fraction: float = 0.003
    max_roi_area_fraction: float = 0.85


@dataclass(frozen=True)
class RulerCandidateQuality:
    reliable: bool
    reasons: tuple[str, ...]
    confidence: float
    periodicity_support: float
    accepted_tick_count: int
    spacing_fraction: float | None
    parallel_edge_support: float
    tick_comb_support: float
    polygon_inside_fraction: float
    angle_deg: float | None
    polygon: tuple[tuple[float, float], ...]
    roi_area_fraction: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RulerAcquisitionMetrics:
    global_saturation_fraction: float
    ruler_roi_saturation_fraction: float | None
    tick_band_saturation_fraction: float | None
    normalized_tick_contrast: float | None
    michelson_tick_contrast: float | None
    accepted_tick_count: int
    periodicity_support: float
    hierarchy_verified: bool
    candidate: RulerCandidateQuality

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class RulerAcquisitionQualityEvaluator:
    def __init__(
        self,
        candidate_config: RulerCandidateQualityConfig | None = None,
        calibration_config: CalibrationConfig | None = None,
    ) -> None:
        self.candidate_config = candidate_config or RulerCandidateQualityConfig()
        self.calibration_config = calibration_config or CalibrationConfig()
        self.rectifier = RulerRectifier(self.calibration_config)

    def evaluate(
        self,
        raw: np.ndarray,
        result: CalibrationResult,
        effective_dn_max: int,
        raw_value_alignment: str = "right",
    ) -> RulerAcquisitionMetrics:
        source = np.asarray(raw)
        maximum = int(effective_dn_max)
        if source.dtype != np.uint16 or source.ndim != 2:
            raise ValueError("Ruler acquisition quality requires a uint16 HxW frame")
        image = self._effective_dn_frame(source, maximum, raw_value_alignment)
        candidate = self.evaluate_candidate(result, image.shape)
        global_saturation = float(np.mean(image >= maximum))
        roi_saturation: float | None = None
        tick_saturation: float | None = None
        normalized: float | None = None
        michelson: float | None = None
        detection = result.ruler_detection
        if detection is not None and detection.success:
            rectification = self.rectifier.rectify(image, detection)
            if rectification.success:
                rectified_raw = cv2.warpPerspective(
                    image,
                    rectification.original_to_rectified,
                    rectification.output_size,
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE,
                )
                roi_saturation = float(np.mean(rectified_raw >= maximum))
                band_height = max(
                    4,
                    int(round(rectified_raw.shape[0] * self.calibration_config.tick_edge_band_fraction)),
                )
                tick_band = np.concatenate(
                    (rectified_raw[:band_height].ravel(), rectified_raw[-band_height:].ravel())
                )
                tick_saturation = float(np.mean(tick_band >= maximum))
                normalized, michelson = self._tick_contrast(
                    rectified_raw,
                    result,
                    maximum,
                )
        hierarchy_verified = result.verification_mode in {
            VerificationMode.TICK_HIERARCHY_VERIFIED.value,
            VerificationMode.OCR_VERIFIED.value,
        }
        return RulerAcquisitionMetrics(
            global_saturation_fraction=global_saturation,
            ruler_roi_saturation_fraction=roi_saturation,
            tick_band_saturation_fraction=tick_saturation,
            normalized_tick_contrast=normalized,
            michelson_tick_contrast=michelson,
            accepted_tick_count=candidate.accepted_tick_count,
            periodicity_support=candidate.periodicity_support,
            hierarchy_verified=hierarchy_verified,
            candidate=candidate,
        )

    @staticmethod
    def _effective_dn_frame(
        source: np.ndarray,
        maximum: int,
        alignment: str,
    ) -> np.ndarray:
        if maximum <= 0 or maximum > 65535:
            raise ValueError("EffectiveDNMax is invalid")
        normalized_alignment = str(alignment).strip().lower()
        if normalized_alignment == "right":
            if source.size and int(source.max()) > maximum:
                raise ValueError("Right-aligned frame exceeds EffectiveDNMax")
            return source
        if normalized_alignment == "left":
            sensor_bits = maximum.bit_length()
            if maximum != (1 << sensor_bits) - 1:
                raise ValueError("Left alignment requires a 2^N-1 EffectiveDNMax")
            shift = 16 - sensor_bits
            if shift <= 0:
                return source
            return np.right_shift(source, shift).astype(np.uint16, copy=False)
        raise ValueError("RawValueAlignment must be verified as right or left")

    def evaluate_candidate(
        self,
        result: CalibrationResult,
        image_shape: tuple[int, int],
    ) -> RulerCandidateQuality:
        diagnostics = result.diagnostics
        selected = next(
            (item for item in diagnostics.get("ruler_candidates", []) if item.get("selected")),
            {},
        )
        polygon = tuple(
            (float(point[0]), float(point[1])) for point in selected.get("polygon", [])
        )
        height, width = image_shape
        inside_fraction = self._polygon_inside_fraction(polygon, width, height)
        roi_area_fraction = float(selected.get("area_fraction") or 0.0)
        confidence = float(selected.get("score") or 0.0)
        periodicity = float(selected.get("periodicity") or 0.0)
        edge_support = float(selected.get("edge_support") or 0.0)
        tick_comb_support = float(selected.get("tick_comb_support") or 0.0)
        accepted = len(result.detected_major_ticks) + len(result.detected_minor_ticks)
        rectified_width = float((diagnostics.get("rectified_resolution") or [0])[0] or 0)
        spacing_fraction = (
            float(result.periodic_pitch_px) / rectified_width
            if result.periodic_pitch_px is not None and rectified_width > 0
            else None
        )
        disagreement = diagnostics.get("orientation_disagreement_deg")
        reasons: list[str] = []
        config = self.candidate_config
        if confidence < config.min_candidate_confidence:
            reasons.append("candidate_confidence_low")
        if periodicity < config.min_periodicity:
            reasons.append("periodicity_support_low")
        if accepted < config.min_accepted_ticks:
            reasons.append("accepted_ticks_insufficient")
        if spacing_fraction is None or not (
            config.min_spacing_fraction <= spacing_fraction <= config.max_spacing_fraction
        ):
            reasons.append("spacing_inconsistent_with_ruler")
        if disagreement is not None and float(disagreement) > config.max_orientation_disagreement_deg:
            reasons.append("angle_inconsistent")
        if inside_fraction < config.min_polygon_inside_fraction:
            reasons.append("polygon_incomplete")
        if not config.min_roi_area_fraction <= roi_area_fraction <= config.max_roi_area_fraction:
            reasons.append("roi_coverage_implausible")
        return RulerCandidateQuality(
            reliable=not reasons,
            reasons=tuple(reasons),
            confidence=confidence,
            periodicity_support=periodicity,
            accepted_tick_count=accepted,
            spacing_fraction=spacing_fraction,
            parallel_edge_support=edge_support,
            tick_comb_support=tick_comb_support,
            polygon_inside_fraction=inside_fraction,
            angle_deg=result.ruler_angle_deg,
            polygon=polygon,
            roi_area_fraction=roi_area_fraction,
        )

    @staticmethod
    def _polygon_inside_fraction(
        polygon: tuple[tuple[float, float], ...],
        width: int,
        height: int,
    ) -> float:
        """Return clipped polygon area, so valid border-crossing rulers are not rejected."""

        if len(polygon) != 4 or width <= 1 or height <= 1:
            return 0.0
        candidate = np.asarray(polygon, dtype=np.float32)
        area = abs(float(cv2.contourArea(candidate)))
        if area <= 0:
            return 0.0
        frame = np.asarray(
            ((0.0, 0.0), (width - 1.0, 0.0), (width - 1.0, height - 1.0), (0.0, height - 1.0)),
            dtype=np.float32,
        )
        clipped_area, _intersection = cv2.intersectConvexConvex(candidate, frame)
        return min(1.0, max(0.0, float(clipped_area) / area))

    @staticmethod
    def _tick_contrast(
        rectified_raw: np.ndarray,
        result: CalibrationResult,
        maximum: int,
    ) -> tuple[float | None, float | None]:
        ticks = result.detected_major_ticks + result.detected_minor_ticks
        if not ticks:
            return None, None
        height, width = rectified_raw.shape
        pitch = float(result.periodic_pitch_px or max(width / 50.0, 4.0))
        half_width = max(2, min(7, int(round(pitch * 0.08))))
        offset = max(3, int(round(pitch * 0.28)))
        normalized: list[float] = []
        michelson: list[float] = []
        for tick in ticks:
            x = int(round(tick.rectified_position_px))
            length = max(4, int(round(tick.length_px)))
            # Accepted marks are edge-connected. Sample both edges and keep the
            # stronger dark-line observation without using OCR or physical pitch.
            samples: list[tuple[float, float]] = []
            for y0, y1 in ((0, min(height, length)), (max(0, height - length), height)):
                x0, x1 = max(0, x - half_width), min(width, x + half_width + 1)
                if x1 <= x0 or y1 <= y0:
                    continue
                tick_dn = float(np.percentile(rectified_raw[y0:y1, x0:x1], 20))
                backgrounds: list[np.ndarray] = []
                for bx in (x - offset, x + offset):
                    bx0, bx1 = max(0, bx - half_width), min(width, bx + half_width + 1)
                    if bx1 > bx0:
                        backgrounds.append(rectified_raw[y0:y1, bx0:bx1].ravel())
                if backgrounds:
                    background_dn = float(np.median(np.concatenate(backgrounds)))
                    samples.append((tick_dn, background_dn))
            if not samples:
                continue
            tick_dn, background_dn = max(samples, key=lambda pair: pair[1] - pair[0])
            difference = max(0.0, background_dn - tick_dn)
            normalized.append(difference / maximum)
            denominator = background_dn + tick_dn
            michelson.append(difference / denominator if denominator > 0 else 0.0)
        if not normalized:
            return None, None
        return float(np.median(normalized)), float(np.median(michelson))
