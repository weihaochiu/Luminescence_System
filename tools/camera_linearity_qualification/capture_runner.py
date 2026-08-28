from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from threading import Event
from time import monotonic
from typing import Any, Callable, Protocol
import uuid

import numpy as np
import tifffile

from .analysis import CameraLinearityAnalyzer
from .capture_manifest import CaptureManifest, atomic_write_json, sha256_file
from .capture_plan import capture_timeout_s
from .models import CaptureCondition, CapturePlan, FrameType, ROI
from .settings import QualificationCriteria


class CaptureCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class AcquiredFrame:
    scientific: np.ndarray
    metadata: dict[str, Any]
    sequence: int
    captured_at: str
    temperature_c: float | None


class CameraAdapter(Protocol):
    def snapshot_state(self) -> dict[str, Any]: ...
    def capture(self, exposure_ms: float, gain_percent: int, settling_frames: int, timeout_s: float, check_cancel: Callable[[], None]) -> AcquiredFrame: ...
    def restore_state(self, state: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class CaptureProgress:
    phase: str
    condition: str
    completed_frames: int
    total_frames: int
    elapsed_s: float
    eta_s: float | None
    median_dn: float | None = None
    p99_dn: float | None = None
    saturation_fraction: float | None = None
    status: str = "RUNNING"
    message: str = ""


@dataclass(frozen=True)
class CaptureRunResult:
    session_dir: Path
    completed: bool
    cancelled: bool
    captured_conditions: tuple[CaptureCondition, ...]
    skipped_conditions: tuple[CaptureCondition, ...]
    pilot_readiness: str | None = None


class CameraCaptureBridgeAdapter:
    """Use CameraCaptureBridge and its existing MONO16 pull stream."""

    def __init__(self, bridge: Any, controller: Any, original_state: dict[str, Any] | None = None) -> None:
        self.bridge = bridge
        self.controller = controller
        self.original_state = dict(original_state or {})

    def snapshot_state(self) -> dict[str, Any]:
        if not self.original_state:
            raise RuntimeError("Camera state snapshot must be captured on the CameraController owner thread")
        return dict(self.original_state)

    def capture(self, exposure_ms: float, gain_percent: int, settling_frames: int, timeout_s: float, check_cancel: Callable[[], None]) -> AcquiredFrame:
        captured = self.bridge.capture(
            exposure_ms, gain_percent, timeout_s, check_cancel,
            accept_actual_readback=True,
            settling_frames=max(0, int(settling_frames)),
        )
        if captured is None or captured.scientific_image is None:
            raise RuntimeError("Scientific MONO16 frame is unavailable")
        metadata = dict(captured.camera_metadata)
        sequence = int(metadata.get("FrameSequence", -1))
        if sequence < 0:
            raise RuntimeError("FrameSequence metadata is unavailable")
        return AcquiredFrame(
            np.asarray(captured.scientific_image).copy(), metadata, sequence,
            captured.timestamp.astimezone().isoformat(timespec="milliseconds"),
            captured.camera_temperature_c,
        )

    def restore_state(self, state: dict[str, Any]) -> None:
        if bool(getattr(self.controller, "is_open", False)):
            self.bridge.restore_state(state)

    def close(self) -> None:
        self.controller.close_camera()


class CaptureRunner:
    def __init__(
        self,
        camera: CameraAdapter,
        plan: CapturePlan,
        output_root: str | Path,
        roi: ROI,
        *,
        criteria: QualificationCriteria | None = None,
        cancel_event: Event | None = None,
        confirm_phase: Callable[[str, dict[str, Any]], bool] | None = None,
        progress: Callable[[CaptureProgress], None] | None = None,
        synthetic_source: bool | None = None,
    ) -> None:
        self.camera = camera
        self.plan = plan
        self.output_root = Path(output_root)
        self.roi = roi
        self.criteria = criteria or QualificationCriteria()
        self.cancel_event = cancel_event or Event()
        self.confirm_phase = confirm_phase or (lambda phase, payload: True)
        self.progress = progress or (lambda payload: None)
        self.synthetic_source = (
            not isinstance(camera, CameraCaptureBridgeAdapter)
            if synthetic_source is None else bool(synthetic_source)
        )
        self._last_sequence: int | None = None

    def run(self) -> CaptureRunResult:
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        session_id = uuid.uuid4().hex
        session = self.output_root / f"Camera_Linearity_Qualification_{stamp}"
        session.mkdir(parents=True, exist_ok=False)
        manifest = CaptureManifest(session / "capture_manifest.json", session_id, self.plan.mode.value)
        original = self.camera.snapshot_state()
        snapshot = {
            "schema_version": "1.0.0", "session_id": session_id,
            "mode": self.plan.mode.value, "created_at": datetime.now().astimezone().isoformat(),
            "synthetic_dataset": self.synthetic_source,
            "ROI": self.roi.to_dict(), "capture_plan": {
                "conditions": [{"gain_percent": item.gain_percent, "exposure_ms": item.exposure_ms} for item in self.plan.conditions],
                "light_repeats": self.plan.light_repeats, "dark_repeats": self.plan.dark_repeats,
                "settling_frames": self.plan.settling_frames, "adaptive_early_stop": self.plan.adaptive_early_stop,
            }, "camera_state_before": original,
        }
        atomic_write_json(session / "measurement_snapshot.json", snapshot)
        completed_conditions: list[CaptureCondition] = []
        skipped: list[CaptureCondition] = []
        last_light_medians: dict[str, float] = {}
        started = monotonic(); completed_frames = 0
        estimated_total = self.plan.planned_frame_count
        cancelled = False

        def check_cancel() -> None:
            if self.cancel_event.is_set():
                raise CaptureCancelled("Safe stop requested")

        try:
            if not self.confirm_phase("LIGHT", {"instruction": "Turn on and stabilize the fixed uniform light source."}):
                raise CaptureCancelled("Light phase was not confirmed")
            manifest.add_event("LIGHT_OPERATOR_CONFIRMED", "Operator confirmed stable fixed light source")
            manifest.set_phase("LIGHT")
            consecutive_stop: dict[int, int] = {}
            stopped_gains: set[int] = set()
            previous_response: dict[int, tuple[float, float]] = {}
            for condition in self.plan.conditions:
                check_cancel()
                if condition.gain_percent in stopped_gains:
                    skipped.append(condition)
                    manifest.add_skip(_condition_dict(condition), "ADAPTIVE_EARLY_STOP")
                    estimated_total -= self.plan.light_repeats + self.plan.dark_repeats
                    continue
                metrics: list[tuple[float, float, float]] = []
                for repeat in range(1, self.plan.light_repeats + 1):
                    acquired = self._capture_verified(condition, check_cancel)
                    region = self._effective_roi(acquired)
                    median, p99 = float(np.median(region)), float(np.percentile(region, 99))
                    maximum = int(acquired.metadata["EffectiveDNMax"])
                    saturation = float(np.mean(region == maximum))
                    metrics.append((median, p99, saturation))
                    self._save(session, manifest, session_id, FrameType.LIGHT, condition, repeat, acquired)
                    completed_frames += 1
                    self._emit_progress("LIGHT", condition, completed_frames, estimated_total, started, median, p99, saturation)
                condition_median = float(np.median([item[0] for item in metrics]))
                last_light_medians[condition.key] = condition_median
                completed_conditions.append(condition)
                trigger = self._early_stop_trigger(condition, metrics, previous_response.get(condition.gain_percent))
                previous_response[condition.gain_percent] = (condition.exposure_ms, condition_median)
                consecutive_stop[condition.gain_percent] = consecutive_stop.get(condition.gain_percent, 0) + 1 if trigger else 0
                if self.plan.adaptive_early_stop and consecutive_stop[condition.gain_percent] >= self.criteria.early_stop_consecutive:
                    stopped_gains.add(condition.gain_percent)
                    manifest.add_event("ADAPTIVE_EARLY_STOP", f"{condition.key}: {trigger}")
                    elapsed = monotonic() - started
                    rate = completed_frames / elapsed if elapsed > 0 else 0.0
                    eta = max(0, estimated_total - completed_frames) / rate if rate else None
                    self.progress(CaptureProgress(
                        "LIGHT", condition.key, completed_frames, estimated_total,
                        elapsed, eta, metrics[-1][0], metrics[-1][1], metrics[-1][2],
                        "WARNING", f"Adaptive early stop for Gain {condition.gain_percent}: {trigger}",
                    ))

            pilot_readiness = None
            if self.plan.mode.value == "pilot":
                pilot_readiness = CameraLinearityAnalyzer(self.criteria).pilot_readiness(list(last_light_medians.values()))
                manifest.add_event("PILOT_READINESS", pilot_readiness)
                manifest.set_phase("COMPLETE")
                return CaptureRunResult(session, True, False, tuple(completed_conditions), tuple(skipped), pilot_readiness)

            if self.plan.dark_repeats:
                preview_condition = completed_conditions[0] if completed_conditions else None
                if preview_condition is None:
                    raise RuntimeError("No Light conditions were captured")
                if not self.confirm_phase("DARK", {"instruction": "Turn off the light or fully cover the lens.", "camera_temperature_c": original.get("CameraTemperatureC")}):
                    raise CaptureCancelled("Dark phase was not confirmed")
                manifest.add_event("DARK_OPERATOR_CONFIRMED", "Operator confirmed light off / lens fully covered")
                manifest.set_phase("DARK_PREVIEW")
                preview = self._capture_verified(preview_condition, check_cancel)
                preview_median = float(np.median(self._effective_roi(preview)))
                accepted, reason = CameraLinearityAnalyzer(self.criteria).validate_dark_preview(preview_median, last_light_medians[preview_condition.key])
                if not accepted and not self.confirm_phase("DARK_RECONFIRM", {"warning": reason, "dark_median": preview_median, "light_median": last_light_medians[preview_condition.key]}):
                    raise CaptureCancelled("Dark preview rejected")
                manifest.add_event("DARK_PREVIEW", f"median={preview_median:g}; {reason}")
                manifest.set_phase("DARK")
                for condition in completed_conditions:
                    for repeat in range(1, self.plan.dark_repeats + 1):
                        check_cancel()
                        acquired = self._capture_verified(condition, check_cancel)
                        region = self._effective_roi(acquired)
                        median, p99 = float(np.median(region)), float(np.percentile(region, 99))
                        maximum = int(acquired.metadata["EffectiveDNMax"])
                        saturation = float(np.mean(region == maximum))
                        self._save(session, manifest, session_id, FrameType.DARK, condition, repeat, acquired)
                        completed_frames += 1
                        self._emit_progress("DARK", condition, completed_frames, estimated_total, started, median, p99, saturation)
            manifest.set_phase("COMPLETE")
            return CaptureRunResult(session, True, False, tuple(completed_conditions), tuple(skipped))
        except CaptureCancelled as exc:
            cancelled = True; manifest.add_event("CANCELLED", str(exc)); manifest.set_phase("CANCELLED")
            return CaptureRunResult(session, False, True, tuple(completed_conditions), tuple(skipped))
        except Exception as exc:
            manifest.add_event("FAILED", f"{type(exc).__name__}: {exc}"); manifest.set_phase("FAILED")
            raise
        finally:
            try:
                self.camera.restore_state(original)
                manifest.add_event("CAMERA_STATE_RESTORED", "Exposure/Gain/Auto Exposure restoration completed")
            except Exception as exc:
                manifest.add_event("CAMERA_STATE_RESTORE_FAILED", str(exc))
                if not cancelled:
                    raise

    def _capture_verified(self, condition: CaptureCondition, check_cancel: Callable[[], None]) -> AcquiredFrame:
        acquired = self.camera.capture(
            condition.exposure_ms, condition.gain_percent, self.plan.settling_frames,
            max(
                5.0,
                condition.exposure_ms / 1000.0
                * (self.plan.settling_frames + 1)
                * self.criteria.capture_timeout_multiplier
                + self.criteria.capture_timeout_overhead_s,
            ),
            check_cancel,
        )
        if self._last_sequence is not None and acquired.sequence <= self._last_sequence:
            raise RuntimeError(
                f"Stale/non-monotonic scientific frame rejected: sequence={acquired.sequence}, previous={self._last_sequence}"
            )
        self._last_sequence = acquired.sequence
        metadata = acquired.metadata
        if not bool(metadata.get("ScientificMeasurementReady", True)):
            raise RuntimeError("Camera is not Scientific MONO16 measurement-ready")
        maximum = metadata.get("EffectiveDNMax"); alignment = str(metadata.get("RawValueAlignment", "unknown")).lower()
        bit_depth = metadata.get("SensorBitDepth")
        if maximum is None or bit_depth is None or int(maximum) != (1 << int(bit_depth)) - 1 or alignment not in {"right", "left"}:
            raise RuntimeError("Critical EffectiveDNMax/bit-depth/alignment metadata is not verified")
        actual_us = float(metadata.get("ExposureReadbackUs", 0)); actual_gain = int(metadata.get("GainReadback", -1))
        exposure_error = abs(actual_us / 1000.0 - condition.exposure_ms) / condition.exposure_ms
        if exposure_error > 0.01 or actual_gain != condition.gain_percent:
            raise RuntimeError(f"Camera setting/readback mismatch requested={condition.exposure_ms:g} ms/G{condition.gain_percent}, actual={actual_us/1000:g} ms/G{actual_gain}")
        return acquired

    def _effective_roi(self, acquired: AcquiredFrame) -> np.ndarray:
        image = np.asarray(acquired.scientific)
        if image.dtype != np.uint16 or image.ndim != 2:
            raise TypeError("Capture must be uint16 HxW MONO16")
        self.roi.validate(image.shape[1], image.shape[0])
        bit_depth = int(acquired.metadata["SensorBitDepth"]); alignment = str(acquired.metadata["RawValueAlignment"]).lower()
        effective = image if alignment == "right" else np.right_shift(image, 16 - bit_depth)
        maximum = int(acquired.metadata["EffectiveDNMax"])
        if np.any(effective > maximum): raise RuntimeError("Capture contains invalid effective DN")
        return effective[self.roi.slices()]

    def _save(self, session: Path, manifest: CaptureManifest, session_id: str, frame_type: FrameType, condition: CaptureCondition, repeat: int, acquired: AcquiredFrame) -> None:
        actual_ms = float(acquired.metadata["ExposureReadbackUs"]) / 1000.0
        folder = session / frame_type.value / f"G{condition.gain_percent}" / f"E{condition.exposure_ms:05.0f}ms"
        stem = f"{frame_type.value}_G{condition.gain_percent}_E{condition.exposure_ms:05.0f}ms_R{repeat:02d}_SEQ{acquired.sequence:06d}"
        tiff_path = folder / f"{stem}.tiff"; json_path = folder / f"{stem}.json"
        folder.mkdir(parents=True, exist_ok=True)
        temporary = tiff_path.with_suffix(".tiff.tmp")
        try:
            with temporary.open("wb") as stream:
                tifffile.imwrite(stream, np.asarray(acquired.scientific), photometric="minisblack")
            temporary.replace(tiff_path)
        finally:
            temporary.unlink(missing_ok=True)
        payload = {
            "schema_version": "1.0.0", "session_id": session_id, "frame_type": frame_type.value,
            "synthetic_dataset": self.synthetic_source,
            "CameraModel": acquired.metadata.get("CameraModel"), "CameraSerial": acquired.metadata.get("CameraSerial"),
            "resolution": [int(acquired.scientific.shape[1]), int(acquired.scientific.shape[0])],
            "dtype": str(acquired.scientific.dtype), "PixelFormat": acquired.metadata.get("PixelFormat", "MONO16"),
            "SensorBitDepth": acquired.metadata.get("SensorBitDepth"), "EffectiveDNMax": acquired.metadata.get("EffectiveDNMax"),
            "RawValueAlignment": acquired.metadata.get("RawValueAlignment"), "ROI": self.roi.to_dict(),
            "requested_exposure_ms": condition.exposure_ms, "actual_exposure_ms": actual_ms,
            "actual_exposure_readback_us": acquired.metadata.get("ExposureReadbackUs"),
            "requested_gain_percent": condition.gain_percent, "actual_gain_percent": acquired.metadata.get("GainReadback"),
            "MatchingGain": condition.gain_percent if frame_type is FrameType.DARK else None,
            "MatchingExposure": condition.exposure_ms if frame_type is FrameType.DARK else None,
            "repeat_index": repeat, "frame_sequence": acquired.sequence,
            "settling_frames_discarded": self.plan.settling_frames, "timestamp": acquired.captured_at,
            "CameraTemperatureC": acquired.temperature_c, "SDKIdentity": acquired.metadata.get("SDKVersion"),
            "DriverIdentity": acquired.metadata.get("DriverIdentity"), "software_commit": _git_head(),
            "tiff_sha256": sha256_file(tiff_path),
        }
        atomic_write_json(json_path, payload)
        manifest.add_frame({"frame_type": frame_type.value, "condition": condition.key, "repeat": repeat, "frame_sequence": acquired.sequence, "tiff": str(tiff_path.relative_to(session)), "json": str(json_path.relative_to(session)), "tiff_sha256": payload["tiff_sha256"]})

    def _early_stop_trigger(self, condition: CaptureCondition, metrics: list[tuple[float, float, float]], previous: tuple[float, float] | None) -> str | None:
        median = float(np.median([item[0] for item in metrics])); p99 = float(np.median([item[1] for item in metrics])); saturation = float(np.median([item[2] for item in metrics]))
        reasons = []
        if median >= self.criteria.early_stop_median_dn: reasons.append("ROI_MEDIAN")
        if p99 >= self.criteria.early_stop_p99_dn: reasons.append("ROI_P99")
        if saturation >= self.criteria.early_stop_saturated_fraction: reasons.append("SATURATION_FRACTION")
        if previous and condition.exposure_ms > previous[0] and previous[1] > 0:
            expected = previous[1] * condition.exposure_ms / previous[0]
            if median < expected * self.criteria.compression_ratio: reasons.append("COMPRESSED_RESPONSE")
        return "+".join(reasons) if reasons else None

    def _emit_progress(self, phase: str, condition: CaptureCondition, completed: int, total: int, started: float, median: float, p99: float, saturation: float) -> None:
        elapsed = monotonic() - started; rate = completed / elapsed if elapsed > 0 else 0
        eta = (max(0, total - completed) / rate) if rate else None
        status = "REJECT" if saturation >= self.criteria.early_stop_saturated_fraction else ("WARNING" if median >= self.criteria.early_stop_median_dn else "PASS")
        self.progress(CaptureProgress(phase, condition.key, completed, total, elapsed, eta, median, p99, saturation, status))


def _condition_dict(condition: CaptureCondition) -> dict[str, Any]:
    return {"gain_percent": condition.gain_percent, "exposure_ms": condition.exposure_ms}


def _git_head() -> str:
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except Exception:
        return "unknown"
