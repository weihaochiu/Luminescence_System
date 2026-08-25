from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from time import monotonic

import cv2
import numpy as np

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

    def analyze(self, frame: np.ndarray, *, input_source: str = "unknown") -> CalibrationResult:
        started = monotonic()
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        gray = normalize_to_uint8(frame)
        height, width = gray.shape
        LOG.info(
            "Ruler calibration analysis start source=%s resolution=%sx%s",
            input_source,
            width,
            height,
        )
        result = CalibrationResult(
            timestamp=timestamp,
            input_resolution=(width, height),
        )
        rectification: RectificationResult | None = None
        try:
            detection, detection_artifacts = self.ruler_detector.detect(frame)
            result.ruler_detection = detection
            result.ruler_angle_deg = detection.angle_deg if detection.success else None
            result.debug_images.update({
                "original": to_bgr(frame),
                "normalized": detection_artifacts.normalized,
                "edges": detection_artifacts.edges,
                "ruler_candidates": detection_artifacts.candidates_overlay,
            })
            if not detection.success:
                result.failure_reasons.append("ruler_not_found")
                result.debug_images["final_overlay"] = draw_final_overlay(frame, result, None)
                self._finish_log(result, started, input_source)
                return result

            rectification = self.rectifier.rectify(frame, detection)
            if not rectification.success:
                result.failure_reasons.append(rectification.reason or "rectification_failed")
                result.debug_images["final_overlay"] = draw_final_overlay(frame, result, rectification)
                self._finish_log(result, started, input_source)
                return result
            result.debug_images["rectified"] = rectification.image
            result.debug_images["ruler_roi"] = self._ruler_roi(gray, detection.polygon)

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
            solved.debug_images = result.debug_images
            solved.diagnostics.update({
                "input_source": input_source,
                "tick_candidate_count": tick_result.candidate_count,
                "rectified_resolution": list(rectification.output_size),
                "coordinate_convention": (
                    "Detection/OCR use rectified (u,v); accepted tick centers are inverse-"
                    "transformed and scale is fitted in original image axis pixels."
                ),
            })
            solved.debug_images["final_overlay"] = draw_final_overlay(frame, solved, rectification)
            result = solved
        except Exception as exc:
            LOG.exception("Ruler calibration analysis failed source=%s", input_source)
            result.failure_reasons.append("analysis_exception")
            result.warnings.append(str(exc))
            result.debug_images.setdefault("original", to_bgr(frame))
            result.debug_images["final_overlay"] = draw_final_overlay(frame, result, rectification)
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
    def _ruler_roi(gray: np.ndarray, polygon: list[tuple[float, float]]) -> np.ndarray:
        points = np.rint(np.asarray(polygon)).astype(np.int32)
        x, y, width, height = cv2.boundingRect(points)
        x = max(0, x)
        y = max(0, y)
        return gray[y : min(gray.shape[0], y + height), x : min(gray.shape[1], x + width)].copy()

    @staticmethod
    def _finish_log(result: CalibrationResult, started: float, input_source: str) -> None:
        LOG.info(
            "Ruler calibration analysis end source=%s elapsed_ms=%.1f angle=%s "
            "ocr_raw=%s ocr_accepted=%s major_ticks=%s minor_ticks=%s rejected_ticks=%s "
            "pixels_per_mm=%s um_per_pixel=%s fit_rmse_px=%s fit_error_percent=%s "
            "quality=%s failure_reasons=%s",
            input_source,
            (monotonic() - started) * 1000.0,
            result.ruler_angle_deg,
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
