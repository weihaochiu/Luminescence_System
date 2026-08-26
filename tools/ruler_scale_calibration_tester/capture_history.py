from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any

import cv2
import numpy as np
import tifffile

from core.calibration.image_utils import normalize_to_uint8
from core.calibration.models import CalibrationResult

from .source import AnalysisSource


LOG = logging.getLogger(__name__)

CAPTURE_SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY_ROOT = PROJECT_ROOT / "local" / "ruler_capture_history"
DEBUG_IMAGE_NAMES = (
    "final_overlay",
    "ticks_overlay",
    "ruler_candidates",
    "rectified",
    "threshold",
    "edges",
    "ocr_overlay",
)
MANIFEST_FIELDS = (
    "capture_id",
    "timestamp",
    "frame_sequence",
    "camera",
    "result",
    "failure_reason",
    "verification_mode",
    "pixels_per_mm",
    "um_per_pixel",
    "angle_deg",
    "quality_score",
    "directory",
)


@dataclass(frozen=True)
class PendingCapture:
    capture_id: str
    directory: Path
    source: AnalysisSource
    captured_at: str
    raw_dtype: str
    raw_shape: tuple[int, int]
    raw_min: float | int
    raw_max: float | int


@dataclass(frozen=True)
class CaptureHistoryStats:
    count: int
    disk_bytes: int
    root: Path


@dataclass(frozen=True)
class AnalysisOutcome:
    result: CalibrationResult
    capture_id: str = ""
    capture_directory: Path | None = None
    history_stats: CaptureHistoryStats | None = None
    persistence_error: str = ""


class CaptureHistoryStore:
    """Persist every camera capture before analysis and append an audit manifest."""

    _lock = threading.Lock()

    def __init__(self, root: str | Path = DEFAULT_HISTORY_ROOT) -> None:
        self.root = Path(root)

    def begin_capture(self, frame: np.ndarray, source: AnalysisSource) -> PendingCapture:
        raw = np.asarray(frame).copy()
        if raw.ndim != 2:
            raise ValueError(f"Camera capture must be an HxW scientific frame, got {raw.shape}")
        captured_at = source.capture_timestamp or datetime.now().astimezone().isoformat(
            timespec="milliseconds"
        )
        captured_dt = _parse_timestamp(captured_at)
        capture_id, directory = self._create_session_directory(
            captured_dt, source.frame_sequence
        )
        pending = PendingCapture(
            capture_id=capture_id,
            directory=directory,
            source=source,
            captured_at=captured_at,
            raw_dtype=str(raw.dtype),
            raw_shape=(int(raw.shape[0]), int(raw.shape[1])),
            raw_min=_scalar(raw.min()),
            raw_max=_scalar(raw.max()),
        )

        # These three files are written before any calibration code is called.
        tifffile.imwrite(directory / "raw_input.tiff", raw)
        preview = np.ascontiguousarray(normalize_to_uint8(raw))
        if not cv2.imwrite(str(directory / "preview.png"), preview):
            raise OSError(f"Failed to write capture preview: {directory / 'preview.png'}")
        self._write_result_json(
            pending,
            {
                "schema_version": CAPTURE_SCHEMA_VERSION,
                "capture_id": capture_id,
                "capture_timestamp": captured_at,
                "analysis_timestamp": None,
                "algorithm_version": None,
                "camera_identity": source.source_identity,
                "camera_display_name": source.display_name,
                "camera_acquisition": _camera_acquisition_payload(source),
                "frame_sequence": source.frame_sequence,
                "input_dtype": pending.raw_dtype,
                "input_resolution": [pending.raw_shape[1], pending.raw_shape[0]],
                "input_min": pending.raw_min,
                "input_max": pending.raw_max,
                "preview_is_visualization_only": True,
                "success": False,
                "failure_reasons": ["analysis_pending"],
                "warnings": [],
                "analysis_exception": None,
            },
        )
        return pending

    def finalize(self, pending: PendingCapture, result: CalibrationResult) -> AnalysisOutcome:
        persistence_errors: list[str] = []
        for name in DEBUG_IMAGE_NAMES:
            image = result.debug_images.get(name)
            if image is None:
                continue
            try:
                target = pending.directory / f"{name}.png"
                array = np.asarray(image)
                if array.dtype != np.uint8:
                    array = normalize_to_uint8(array)
                if not cv2.imwrite(str(target), np.ascontiguousarray(array)):
                    raise OSError(f"Failed to write debug image: {target}")
            except Exception as exc:
                LOG.exception("Capture debug image persistence failed name=%s", name)
                persistence_errors.append(f"{name}: {exc}")

        try:
            self._write_result_json(pending, self._result_payload(pending, result))
        except Exception as exc:
            LOG.exception("Capture result JSON persistence failed capture_id=%s", pending.capture_id)
            persistence_errors.append(f"result.json: {exc}")
        try:
            self._append_manifest(pending, result)
        except Exception as exc:
            LOG.exception("Capture manifest append failed capture_id=%s", pending.capture_id)
            persistence_errors.append(f"manifest.csv: {exc}")

        error = "; ".join(persistence_errors)
        return AnalysisOutcome(
            result=result,
            capture_id=pending.capture_id,
            capture_directory=pending.directory,
            history_stats=self.statistics(),
            persistence_error=error,
        )

    def statistics(self) -> CaptureHistoryStats:
        count = 0
        disk_bytes = 0
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    disk_bytes += path.stat().st_size
                except OSError:
                    continue
                if path.name == "raw_input.tiff":
                    count += 1
        return CaptureHistoryStats(count=count, disk_bytes=disk_bytes, root=self.root.resolve())

    def _create_session_directory(
        self, captured_at: datetime, frame_sequence: int | None
    ) -> tuple[str, Path]:
        date_text = captured_at.strftime("%Y%m%d")
        sequence = "unknown" if frame_sequence is None else f"{int(frame_sequence):06d}"
        base = f"{captured_at.strftime('%Y%m%d_%H%M%S_%f')[:19]}_frame_{sequence}"
        with self._lock:
            day_root = self.root / date_text
            day_root.mkdir(parents=True, exist_ok=True)
            for counter in range(10000):
                capture_id = base if counter == 0 else f"{base}_{counter:02d}"
                directory = day_root / capture_id
                try:
                    directory.mkdir(exist_ok=False)
                    return capture_id, directory
                except FileExistsError:
                    continue
        raise OSError(f"Could not allocate a unique capture directory below {day_root}")

    def _result_payload(
        self, pending: PendingCapture, result: CalibrationResult
    ) -> dict[str, Any]:
        detection = result.ruler_detection
        candidates = result.diagnostics.get("ruler_candidates", [])
        accepted_ocr = [item.raw_text for item in result.detected_numbers if item.accepted]
        raw_ocr = [item.raw_text for item in result.detected_numbers if item.raw_text]
        analysis_exception = None
        if "analysis_exception" in result.failure_reasons:
            analysis_exception = "; ".join(result.warnings) or "analysis_exception"
        return {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "capture_id": pending.capture_id,
            "capture_timestamp": pending.captured_at,
            "analysis_timestamp": result.timestamp,
            "algorithm_version": result.algorithm_version,
            "camera_identity": pending.source.source_identity,
            "camera_display_name": pending.source.display_name,
            "camera_acquisition": _camera_acquisition_payload(pending.source),
            "frame_sequence": pending.source.frame_sequence,
            "input_dtype": pending.raw_dtype,
            "input_resolution": [pending.raw_shape[1], pending.raw_shape[0]],
            "input_min": pending.raw_min,
            "input_max": pending.raw_max,
            "preview_is_visualization_only": True,
            "ruler_detected": bool(detection and detection.success),
            "ruler_detection": None if detection is None else result.to_dict()["ruler_detection"],
            "ruler_candidates": candidates,
            "selected_candidate_method": result.diagnostics.get("ruler_selected_method"),
            "selected_candidate_score": result.diagnostics.get("ruler_selected_score"),
            "angle_deg": result.ruler_angle_deg,
            "rectified_blur_laplacian_variance": result.diagnostics.get(
                "rectified_blur_laplacian_variance"
            ),
            "rectified_saturated_fraction": result.diagnostics.get(
                "rectified_saturated_fraction"
            ),
            "tick_candidate_count": result.diagnostics.get("tick_candidate_count", 0),
            "accepted_tick_count": len(result.detected_major_ticks)
            + len(result.detected_minor_ticks),
            "rejected_tick_count": len(result.rejected_ticks),
            "periodic_pitch_px": result.periodic_pitch_px,
            "physical_pitch_mm": result.physical_pitch_mm,
            "verification_mode": result.verification_mode,
            "pixels_per_mm": result.pixels_per_mm,
            "um_per_pixel": result.um_per_pixel,
            "fit_rmse_px": result.fit_rmse_px,
            "fit_error_percent": result.fit_error_percent,
            "quality_score": result.quality_score,
            "quality_label": result.quality_label,
            "ocr_available": result.ocr_available,
            "ocr_usable": result.ocr_usable,
            "ocr_diagnostic": result.ocr_diagnostic,
            "ocr_raw": raw_ocr,
            "ocr_accepted": accepted_ocr,
            "success": result.success,
            "warnings": list(result.warnings),
            "failure_reasons": list(result.failure_reasons),
            "analysis_exception": analysis_exception,
            "ruler_auto_exposure_attempt": result.diagnostics.get(
                "ruler_auto_exposure_attempt"
            ),
            "ruler_auto_exposure_attempts": result.diagnostics.get(
                "ruler_auto_exposure_attempts", []
            ),
            "calibration_result": result.to_dict(),
        }

    @staticmethod
    def _write_result_json(pending: PendingCapture, payload: dict[str, Any]) -> None:
        target = pending.directory / "result.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)

    def _append_manifest(self, pending: PendingCapture, result: CalibrationResult) -> None:
        target = self.root / "manifest.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "capture_id": pending.capture_id,
            "timestamp": pending.captured_at,
            "frame_sequence": pending.source.frame_sequence,
            "camera": pending.source.display_name or pending.source.source_identity,
            "result": "PASS" if result.success else "FAIL",
            "failure_reason": ";".join(result.failure_reasons),
            "verification_mode": result.verification_mode,
            "pixels_per_mm": result.pixels_per_mm,
            "um_per_pixel": result.um_per_pixel,
            "angle_deg": result.ruler_angle_deg,
            "quality_score": result.quality_score,
            "directory": str(pending.directory.resolve()),
        }
        with self._lock:
            write_header = not target.exists() or target.stat().st_size == 0
            with target.open("a", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
                stream.flush()
                os.fsync(stream.fileno())


def analyze_camera_capture(
    service: Any,
    history: CaptureHistoryStore,
    frame: np.ndarray,
    source: AnalysisSource,
) -> AnalysisOutcome:
    """Raw-first camera workflow. A service exception becomes persisted evidence."""
    pending = history.begin_capture(frame, source)
    try:
        result = service.analyze(
            np.asarray(frame).copy(),
            input_source=source.display_name or source.source_type,
            source_type=source.source_type,
            source_identity=source.source_identity,
            source_display_name=source.display_name,
            captured_frame_sequence=source.frame_sequence,
            source_filename=source.filename,
        )
        if not isinstance(result, CalibrationResult):
            raise TypeError("Calibration service returned an invalid result")
    except Exception as exc:
        LOG.exception("Camera capture analysis raised capture_id=%s", pending.capture_id)
        result = CalibrationResult(
            success=False,
            source_type="camera",
            source_identity=source.source_identity,
            source_display_name=source.display_name,
            captured_frame_sequence=source.frame_sequence,
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            input_dtype=pending.raw_dtype,
            input_resolution=(pending.raw_shape[1], pending.raw_shape[0]),
            input_min=pending.raw_min,
            input_max=pending.raw_max,
            failure_reasons=["analysis_exception"],
            warnings=[f"{type(exc).__name__}: {exc}"],
            raw_input=np.asarray(frame).copy(),
        )
        preview = normalize_to_uint8(frame)
        result.debug_images["final_overlay"] = cv2.cvtColor(
            np.ascontiguousarray(preview), cv2.COLOR_GRAY2BGR
        )
    return history.finalize(pending, result)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.now().astimezone()
    return parsed.astimezone() if parsed.tzinfo is not None else parsed.astimezone()


def _scalar(value: np.generic[Any] | float | int) -> float | int:
    return value.item() if isinstance(value, np.generic) else value


def _camera_acquisition_payload(source: AnalysisSource) -> dict[str, Any]:
    metadata = dict(source.acquisition_metadata or {})
    exposure = metadata.get("ExposureReadbackUs")
    gain = metadata.get("GainReadback")
    auto_mode = metadata.get("AutoExposureMode")
    auto_enabled = metadata.get("SDKAutoExposureEnabled")
    auto_target = metadata.get(
        "SDKAutoExposureTargetReadback", metadata.get("SDKAutoExposureTarget")
    )
    values = {
        "camera_exposure_us": exposure,
        "camera_gain": gain,
        "auto_exposure_enabled": auto_enabled,
        "auto_exposure_mode": auto_mode,
        "auto_exposure_target": auto_target,
        "sensor_bit_depth": metadata.get("SensorBitDepth"),
        "raw_value_alignment": metadata.get("RawValueAlignment"),
        "effective_dn_max": metadata.get("EffectiveDNMax"),
        "camera_temperature_c": metadata.get("CameraTemperatureC"),
        "timestamp": source.capture_timestamp or None,
    }
    values["availability"] = {
        key: value is not None and value not in ("", "unknown")
        for key, value in values.items()
        if key != "timestamp"
    }
    values["source"] = "CameraController.capture_metadata"
    values["controller_metadata"] = metadata
    return values
