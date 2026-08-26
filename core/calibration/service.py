from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
import tifffile

from .config import CalibrationConfig
from .digit_recognizer import DigitRecognizer, TesseractDigitRecognizer
from .image_utils import normalize_to_uint8, to_bgr
from .models import CalibrationResult
from .overlay import draw_final_overlay, draw_ocr_overlay
from .ruler_detector import RulerDetector
from .ruler_rectifier import RectificationResult, RulerRectifier
from .scale_solver import ScaleSolver
from .tick_detector import TickDetector


LOG = logging.getLogger(__name__)


class CalibrationService:
    """Production-reusable entry point; no dependency on the standalone tester GUI."""

    def __init__(
        self,
        config: CalibrationConfig | None = None,
        digit_recognizer: DigitRecognizer | None = None,
    ) -> None:
        self.config = config or CalibrationConfig()
        self.ruler_detector = RulerDetector(self.config)
        self.rectifier = RulerRectifier(self.config)
        self.tick_detector = TickDetector(self.config)
        self.digit_recognizer = digit_recognizer or TesseractDigitRecognizer(self.config)
        self.scale_solver = ScaleSolver(self.config)

    def analyze(
        self,
        frame: np.ndarray,
        *,
        input_source: str = "unknown",
        source_type: str | None = None,
        source_identity: str = "",
        source_display_name: str = "",
        captured_frame_sequence: int | None = None,
        source_filename: str = "",
    ) -> CalibrationResult:
        started = monotonic()
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        raw_input = np.asarray(frame).copy()
        gray = normalize_to_uint8(raw_input)
        height, width = gray.shape
        resolved_source_type = source_type or self._infer_source_type(input_source)
        resolved_filename = source_filename
        resolved_identity = source_identity
        resolved_display_name = source_display_name
        if resolved_source_type == "file" and not resolved_filename:
            candidate = Path(input_source).resolve()
            if candidate.is_file():
                resolved_filename = str(candidate)
                resolved_display_name = resolved_display_name or candidate.name
                stat = candidate.stat()
                resolved_identity = resolved_identity or (
                    f"file|{candidate}|mtime_ns={stat.st_mtime_ns}|size={stat.st_size}"
                )
        LOG.info(
            "Ruler calibration analysis start source=%s resolution=%sx%s",
            input_source,
            width,
            height,
        )
        result = CalibrationResult(
            timestamp=timestamp,
            input_resolution=(width, height),
            input_dtype=str(raw_input.dtype),
            input_min=self._scalar_min(raw_input),
            input_max=self._scalar_max(raw_input),
            source_type=resolved_source_type,
            source_identity=resolved_identity,
            source_display_name=resolved_display_name,
            captured_frame_sequence=captured_frame_sequence,
            source_filename=resolved_filename,
            raw_input=raw_input,
        )
        rectification: RectificationResult | None = None
        try:
            detection, detection_artifacts = self.ruler_detector.detect(raw_input)
            result.ruler_detection = detection
            result.ruler_angle_deg = detection.angle_deg if detection.success else None
            result.debug_images.update({
                "original_preview": to_bgr(raw_input),
                "normalized": detection_artifacts.normalized,
                "edges": detection_artifacts.edges,
                "bright_component_mask": detection_artifacts.bright_component_mask,
                "ruler_candidates": detection_artifacts.candidates_overlay,
            })
            detection_diagnostics = {
                "ruler_candidate_count": detection_artifacts.candidate_count,
                "ruler_selected_method": detection_artifacts.selected_method,
                "ruler_selected_score": detection_artifacts.selected_score,
                "tick_comb_axis_angle_deg": detection_artifacts.tick_comb_axis_angle_deg,
                "tick_comb_support": detection_artifacts.tick_comb_support,
                "orientation_disagreement_deg": detection_artifacts.orientation_disagreement_deg,
            }
            result.diagnostics.update(detection_diagnostics)
            if not detection.success:
                result.failure_reasons.append("ruler_not_found")
                result.debug_images["final_overlay"] = draw_final_overlay(raw_input, result, None)
                self._finish_log(result, started, input_source)
                return result

            rectification = self.rectifier.rectify(raw_input, detection)
            if not rectification.success:
                result.failure_reasons.append(rectification.reason or "rectification_failed")
                result.debug_images["final_overlay"] = draw_final_overlay(raw_input, result, rectification)
                self._finish_log(result, started, input_source)
                return result
            result.debug_images["rectified"] = rectification.image
            result.debug_images["ruler_roi"] = self._ruler_roi(gray, detection.polygon)
            rectified_quality = self._image_quality(rectification.image)
            result.diagnostics.update({
                **rectified_quality,
                "input_source": input_source,
                "rectified_resolution": list(rectification.output_size),
            })
            if (
                rectified_quality["rectified_saturated_fraction"]
                > self.config.max_rectified_saturated_fraction
            ):
                result.failure_reasons.append("ruler_glare_or_saturation")
                result.debug_images["final_overlay"] = draw_final_overlay(
                    raw_input, result, rectification
                )
                self._finish_log(result, started, input_source)
                return result
            if (
                rectified_quality["rectified_blur_laplacian_variance"]
                < self.config.min_rectified_blur_laplacian_variance
            ):
                result.failure_reasons.append("image_too_blurry_for_scale_calibration")
                result.debug_images["final_overlay"] = draw_final_overlay(
                    raw_input, result, rectification
                )
                self._finish_log(result, started, input_source)
                return result

            tick_result = self.tick_detector.detect(rectification)
            result.debug_images["threshold"] = tick_result.threshold
            result.debug_images["ticks_overlay"] = tick_result.overlay
            availability = self.digit_recognizer.availability()
            numbers = self.digit_recognizer.recognize(rectification.image) if availability.available else []
            result.debug_images["ocr_overlay"] = draw_ocr_overlay(rectification.image, numbers)
            solved = self.scale_solver.solve(
                detection,
                tick_result.ticks,
                numbers,
                input_resolution=(width, height),
                ocr_available=availability.available,
                ocr_diagnostic=availability.diagnostic,
            )
            solved.timestamp = timestamp
            solved.input_dtype = str(raw_input.dtype)
            solved.input_min = self._scalar_min(raw_input)
            solved.input_max = self._scalar_max(raw_input)
            solved.source_type = resolved_source_type
            solved.source_identity = resolved_identity
            solved.source_display_name = resolved_display_name
            solved.captured_frame_sequence = captured_frame_sequence
            solved.source_filename = resolved_filename
            solved.raw_input = raw_input
            solved.debug_images = result.debug_images
            solved.diagnostics.update({
                **detection_diagnostics,
                **rectified_quality,
                "input_source": input_source,
                "tick_candidate_count": tick_result.candidate_count,
                "rectified_resolution": list(rectification.output_size),
                "coordinate_convention": (
                    "Detection/OCR use rectified (u,v); accepted tick centers are inverse-"
                    "transformed and scale is fitted in original image axis pixels."
                ),
            })
            solved.debug_images["final_overlay"] = draw_final_overlay(raw_input, solved, rectification)
            result = solved
        except Exception as exc:
            LOG.exception("Ruler calibration analysis failed source=%s", input_source)
            result.failure_reasons.append("analysis_exception")
            result.warnings.append(str(exc))
            result.debug_images.setdefault("original_preview", to_bgr(raw_input))
            result.debug_images["final_overlay"] = draw_final_overlay(raw_input, result, rectification)
        self._finish_log(result, started, input_source)
        return result

    def save_debug_package(
        self,
        result: CalibrationResult,
        root: str | Path = Path("local") / "generated" / "debug",
    ) -> Path:
        stamp = result.timestamp.replace(":", "").replace("-", "").replace("+", "_")
        stamp = stamp.replace("T", "_") or datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path(root) / stamp
        counter = 1
        while output.exists():
            output = Path(f"{output}_{counter:02d}")
            counter += 1
        output.mkdir(parents=True, exist_ok=False)
        if result.raw_input is None:
            raise ValueError("Calibration result does not contain an exact raw input frame")
        tifffile.imwrite(output / "raw_input.tiff", result.raw_input)
        for name, image in result.debug_images.items():
            path = output / f"{name}.png"
            array = np.asarray(image)
            if not cv2.imwrite(str(path), array):
                raise OSError(f"Failed to write debug image: {path}")
        result_path = output / "result.json"
        temporary = result_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(result_path)
        LOG.info("Ruler calibration debug package saved path=%s", output)
        return output

    @staticmethod
    def _infer_source_type(input_source: str) -> str:
        lowered = input_source.casefold()
        if lowered.startswith("camera:"):
            return "camera"
        if lowered not in {"", "unknown"}:
            return "file" if Path(input_source).suffix else "synthetic"
        return "unknown"

    @staticmethod
    def _scalar_min(array: np.ndarray) -> float | int | None:
        if array.size == 0:
            return None
        value = np.nanmin(array) if np.issubdtype(array.dtype, np.floating) else np.min(array)
        return value.item() if isinstance(value, np.generic) else value

    @staticmethod
    def _scalar_max(array: np.ndarray) -> float | int | None:
        if array.size == 0:
            return None
        value = np.nanmax(array) if np.issubdtype(array.dtype, np.floating) else np.max(array)
        return value.item() if isinstance(value, np.generic) else value

    @staticmethod
    def _ruler_roi(gray: np.ndarray, polygon: list[tuple[float, float]]) -> np.ndarray:
        points = np.rint(np.asarray(polygon)).astype(np.int32)
        x, y, width, height = cv2.boundingRect(points)
        x = max(0, x)
        y = max(0, y)
        return gray[y : min(gray.shape[0], y + height), x : min(gray.shape[1], x + width)].copy()

    @staticmethod
    def _image_quality(gray: np.ndarray) -> dict[str, float]:
        array = np.asarray(gray)
        normalized = (
            np.ascontiguousarray(array)
            if array.dtype == np.uint8
            else normalize_to_uint8(array)
        )
        return {
            "rectified_blur_laplacian_variance": float(
                cv2.Laplacian(normalized, cv2.CV_32F).var()
            ),
            "rectified_saturated_fraction": float(np.mean(normalized >= 253)),
        }

    @staticmethod
    def _finish_log(result: CalibrationResult, started: float, input_source: str) -> None:
        LOG.info(
            "Ruler calibration analysis end source=%s elapsed_ms=%.1f angle=%s "
            "candidate_count=%s selected_method=%s selected_score=%s "
            "tick_comb_angle=%s orientation_disagreement=%s rectified_resolution=%s "
            "tick_candidates=%s accepted_ticks=%s "
            "ocr_raw=%s ocr_accepted=%s major_ticks=%s minor_ticks=%s rejected_ticks=%s "
            "pixels_per_mm=%s um_per_pixel=%s fit_rmse_px=%s fit_error_percent=%s "
            "quality=%s failure_reasons=%s",
            input_source,
            (monotonic() - started) * 1000.0,
            result.ruler_angle_deg,
            result.diagnostics.get("ruler_candidate_count"),
            result.diagnostics.get("ruler_selected_method"),
            result.diagnostics.get("ruler_selected_score"),
            result.diagnostics.get("tick_comb_axis_angle_deg"),
            result.diagnostics.get("orientation_disagreement_deg"),
            result.diagnostics.get("rectified_resolution"),
            result.diagnostics.get("tick_candidate_count"),
            len(result.detected_major_ticks) + len(result.detected_minor_ticks),
            [item.raw_text for item in result.detected_numbers],
            [item.corrected_value if item.corrected_value is not None else item.value for item in result.detected_numbers if item.accepted],
            len(result.detected_major_ticks),
            len(result.detected_minor_ticks),
            len(result.rejected_ticks),
            result.pixels_per_mm,
            result.um_per_pixel,
            result.fit_rmse_px,
            result.fit_error_percent,
            result.quality_label,
            result.failure_reasons,
        )
