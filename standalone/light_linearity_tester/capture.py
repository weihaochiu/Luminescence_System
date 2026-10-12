from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import random
from threading import Event
from time import monotonic
from uuid import uuid4

import numpy as np
import tifffile

from tools.camera_linearity_qualification.capture_manifest import atomic_write_json, sha256_file
from tools.camera_linearity_qualification.capture_plan import capture_timeout_s
from tools.camera_linearity_qualification.capture_runner import AcquiredFrame, CameraCaptureBridgeAdapter, CaptureCancelled, CaptureProgress
from tools.camera_linearity_qualification.models import ROI
from .analysis import ConditionStatistics, DEFAULT_THRESHOLDS
from .calibration import LightCalibration
from .plan import LightPlan, Retention


class VerifiedCameraAdapter(CameraCaptureBridgeAdapter):
    """Reuse the camera handle, explicitly trigger and verify every accepted frame."""

    def capture(self, exposure_ms, gain_percent, settling_frames, timeout_s, check_cancel):
        deadline = monotonic() + timeout_s
        captured = None
        # The bridge's single software trigger cannot discard frames and await a
        # second frame without another trigger. Make each settling frame an
        # explicit complete capture, including its normal trigger cleanup.
        for _ in range(max(0, int(settling_frames)) + 1):
            check_cancel()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Verified camera capture timeout")
            captured = self.bridge.capture(exposure_ms, gain_percent, remaining, check_cancel,
                                           accept_actual_readback=True, settling_frames=0,
                                           require_frame_exposure_match=True, software_triggered=True)
            if captured is None or captured.scientific_image is None:
                raise RuntimeError("Scientific MONO16 frame is unavailable")
        metadata = dict(captured.camera_metadata)
        metadata["SettlingFramesDiscarded"] = max(0, int(settling_frames))
        sequence = int(metadata.get("FrameSequence", -1))
        if sequence < 0:
            raise RuntimeError("FrameSequence metadata is unavailable")
        return AcquiredFrame(np.asarray(captured.scientific_image).copy(), metadata, sequence,
                             captured.timestamp.astimezone().isoformat(timespec="milliseconds"), captured.camera_temperature_c)


class LightCaptureRunner:
    def __init__(self, camera, light, plan: LightPlan, calibration: LightCalibration,
                 output: str | Path, roi: ROI, *, cancel: Event | None = None,
                 progress=None, synthetic: bool = False) -> None:
        plan.validate()
        calibration.validate()
        if calibration.channel != plan.channel:
            raise ValueError("量測表與拍攝通道不同")
        if plan.require_measured:
            calibration.require_levels(plan.levels)
        self.camera, self.light, self.plan = camera, light, plan
        self.calibration = LightCalibration.from_dict(calibration.to_dict())
        self.output, self.roi = Path(output), roi
        self.cancel = cancel or Event()
        self.progress = progress or (lambda value: None)
        self.synthetic = synthetic
        self.last_sequence = None
        self._frame_count = 0

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise CaptureCancelled("已要求安全停止")

    def wait(self, seconds: float) -> None:
        if self.cancel.wait(seconds):
            self.check_cancel()

    def acquire(self, gain: int, exposure: float):
        self.check_cancel()
        acquired = self.camera.capture(exposure, gain, self.plan.settling_frames,
                                       capture_timeout_s(exposure, self.plan.settling_frames), self.check_cancel)
        metadata = acquired.metadata
        if not metadata.get("ScientificMeasurementReady"):
            raise ValueError("相機未確認為 Scientific MONO16")
        data = np.asarray(acquired.scientific)
        bits, maximum = metadata.get("SensorBitDepth"), metadata.get("EffectiveDNMax")
        alignment = metadata.get("RawValueAlignment")
        if data.dtype != np.uint16 or data.ndim != 2 or bits is None or not 1 <= int(bits) <= 16 or maximum != (1 << int(bits)) - 1 or alignment not in ("right", "left"):
            raise ValueError("影像、有效位元深度或 RAW alignment 未驗證")
        actual_us = float(metadata.get("ExposureUsedUs", metadata.get("ExposureReadbackUs", 0)))
        if not np.isfinite(actual_us) or actual_us <= 0 or int(metadata.get("GainReadback", -1)) != gain:
            raise ValueError("相機曝光／Gain 讀回無效")
        if abs(actual_us / 1000 - exposure) > max(.03, exposure * .01):
            raise ValueError(f"曝光讀回超過容差：requested={exposure}, actual={actual_us / 1000}")
        if self.last_sequence is not None and acquired.sequence <= self.last_sequence:
            raise ValueError("重複／舊的 frame sequence")
        self.last_sequence = acquired.sequence
        self.roi.validate(data.shape[1], data.shape[0])
        effective = data if alignment == "right" else np.right_shift(data, 16 - int(bits))
        if np.any(effective > maximum):
            raise ValueError("RAW 有效 DN 超出範圍")
        return acquired, effective[self.roi.slices()], actual_us / 1000

    def verify_light(self, level: int | None) -> dict:
        state = self.light.refresh(self.check_cancel)
        expected = [0] * 4
        if level is not None:
            expected[self.plan.channel - 1] = level
        if state.mode != ("L" if level is None else "H") or (level is not None and tuple(expected) != state.brightness):
            raise RuntimeError("GSP-4H 模式／四通道亮度讀回與目前條件不一致")
        return {"mode": state.mode, "brightness": list(state.brightness)}

    def run(self) -> Path:
        original = self.camera.snapshot_state()
        self.output.mkdir(parents=True, exist_ok=True)
        session = self.output / f"Light_Linearity_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
        summary_dir = session / "SUMMARY"
        summary_dir.mkdir(parents=True)
        self.session, self.started = session, monotonic()
        calibration = self.calibration.snapshot()
        self.calibration_hash = calibration["sha256"]
        try:
            import subprocess
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=3).strip()
            dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True, timeout=3).strip())
        except Exception:
            commit, dirty = "unknown", None
        snapshot = {"schema_version": "1.0", "plan": asdict(self.plan), "ROI": self.roi.to_dict(),
                    "light_calibration": calibration, "analysis_thresholds": DEFAULT_THRESHOLDS,
                    "camera_state_before": original, "synthetic_dataset": self.synthetic,
                    "software_commit": commit, "software_dirty": dirty,
                    "pwm_frequency_source": "user_entered_unverified" if self.plan.pwm_frequency_hz else "unknown",
                    "pwm_duty_cycle": None, "hardware_synchronized": False}
        snapshot.update(self.snapshot_extra())
        atomic_write_json(summary_dir / "measurement_snapshot.json", snapshot)
        self.manifest = {"schema_version": "1.0", "phase": "STARTING", "frames": [], "skipped": [],
                         "summary_frames": [], "error": None, "cleanup_errors": [], "statistics_sha256": None,
                         "snapshot_sha256": sha256_file(summary_dir / "measurement_snapshot.json")}
        self.manifest_path = summary_dir / "capture_manifest.json"
        rows = []
        error = None
        try:
            self.light.turn_off()
            self.wait(self.plan.warmup_s)
            self.capture_schedule(rows)
            self.manifest["phase"] = "COMPLETE"
        except CaptureCancelled as exc:
            error = str(exc)
            self.manifest["phase"] = "CANCELLED"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.manifest["phase"] = "FAILED"
        finally:
            self.progress({"message": "正在驗證關燈並還原相機設定；保留已完成資料"})
            for label, action in (("light_safe_off", self.light.safe_off), ("camera_restore", lambda: self.camera.restore_state(original))):
                try:
                    action()
                except Exception as exc:
                    self.manifest["cleanup_errors"].append(f"{label}: {exc}")
            self.manifest["error"] = error
            if self.manifest["cleanup_errors"]:
                self.manifest["phase"] = "CLEANUP_FAILED"
            atomic_write_json(summary_dir / "condition_statistics.json", rows)
            self.manifest["statistics_sha256"] = sha256_file(summary_dir / "condition_statistics.json")
            atomic_write_json(self.manifest_path, self.manifest)
        return session

    def snapshot_extra(self) -> dict:
        return {}

    def capture_schedule(self, rows: list[dict]) -> None:
        for level in self.plan.levels:
            for gain in self.plan.gains:
                stopped = False
                for exposure in sorted(self.plan.exposures_ms):
                    self.check_cancel()
                    if stopped:
                        self.manifest["skipped"].append({"pwm_level": level, "gain": gain, "exposure_ms": exposure, "reason": "NEAR_SATURATION"})
                        continue
                    row = self.capture_condition(level, gain, exposure)
                    rows.append(row)
                    atomic_write_json(self.session / "SUMMARY" / "condition_statistics.json", rows)
                    if self.plan.adaptive_stop and row["near_saturation_fraction"] > .001:
                        stopped = True
            self.light.turn_off()

    def capture_condition(self, level: int, gain: int, exposure: float) -> dict:
        self.light.turn_off()
        self.wait(self.plan.settle_s)
        stats = ConditionStatistics()
        dark_actual = None
        for repeat in range(1, self.plan.dark_repeats + 1):
            self.progress({"phase": "DARK", "condition": f"CH{self.plan.channel} PWM{level} G{gain} E{exposure:g}ms", "repeat": repeat, "repeats": self.plan.dark_repeats, "exposure_ms": exposure})
            state = self.verify_light(None)
            frame, region, actual = self.acquire(gain, exposure)
            self.verify_light(None)
            stats.add_dark(region)
            if dark_actual is not None and abs(actual - dark_actual) > max(.001, actual * .001):
                raise ValueError("Dark repeats 實際曝光不一致")
            dark_actual = actual
            self.save_frame(frame, "DARK", level, gain, exposure, actual, repeat, state)
            self.emit_progress("DARK", level, gain, exposure, region, frame.metadata["EffectiveDNMax"])
        values = [0] * 4
        values[self.plan.channel - 1] = level
        self.light.enable(values, self.check_cancel)
        self.wait(self.plan.settle_s)
        actual = None
        for repeat in range(1, self.plan.repeats + 1):
            self.progress({"phase": "LIGHT", "condition": f"CH{self.plan.channel} PWM{level} G{gain} E{exposure:g}ms", "repeat": repeat, "repeats": self.plan.repeats, "exposure_ms": exposure})
            self.wait(random.uniform(0, self.plan.jitter_s))
            state = self.verify_light(level)
            frame, region, actual = self.acquire(gain, exposure)
            self.verify_light(level)
            if abs(actual - dark_actual) > max(.001, actual * .001):
                raise ValueError("Light 與 Dark 實際曝光不一致")
            stats.add_light(region, frame.metadata["EffectiveDNMax"], frame.sequence)
            self.save_frame(frame, "LIGHT", level, gain, exposure, actual, repeat, state)
            self.emit_progress("LIGHT", level, gain, exposure, region, frame.metadata["EffectiveDNMax"])
        return {"channel": self.plan.channel, "pwm_level": level, "gain": gain,
                "exposure_ms": exposure, "actual_exposure_ms": actual,
                "relative_intensity": self.calibration.relative(level),
                "measured_intensity": self.calibration.readings.get(level),
                "calibration_sha256": self.calibration_hash, **stats.result()}

    def save_frame(self, frame, kind: str, level: int, gain: int, exposure: float, actual: float, repeat: int, light_state: dict) -> None:
        self._frame_count += 1
        metadata = {"frame_type": kind, "channel": self.plan.channel, "pwm_level": level,
                    "requested_gain": gain, "requested_exposure_ms": exposure, "actual_exposure_ms": actual,
                    "sequence": frame.sequence, "repeat": repeat, "timestamp": frame.captured_at,
                    "temperature_c": frame.temperature_c, "camera": frame.metadata, "light": light_state,
                    "calibration_sha256": self.calibration_hash, "pwm_frequency_hz": self.plan.pwm_frequency_hz,
                    "pwm_frequency_source": "user_entered_unverified" if self.plan.pwm_frequency_hz else "unknown",
                    "pwm_duty_cycle": None, "hardware_synchronized": False}
        self.manifest["summary_frames"].append(metadata)
        if self.plan.retention != Retention.SUMMARY:
            data = np.asarray(frame.scientific)
            cropped = self.plan.retention == Retention.ROI and repeat > 1
            if cropped:
                data = data[self.roi.slices()].copy()
            folder = self.session / "IMAGES" / f"CH{self.plan.channel}_PWM{level:03d}" / kind / f"G{gain}"
            folder.mkdir(parents=True, exist_ok=True)
            token = f"{exposure:.9g}".replace(".", "p")
            path = folder / f"E{token}ms_R{repeat:03d}_SEQ{frame.sequence}.tiff"
            temporary = path.with_suffix(".tiff.tmp")
            try:
                tifffile.imwrite(temporary, data, photometric="minisblack")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            metadata["stored_region"] = "roi" if cropped else "full"
            metadata["analysis_roi"] = self.roi.to_dict()
            metadata["tiff_sha256"] = sha256_file(path)
            atomic_write_json(path.with_suffix(".json"), metadata)
            self.manifest["frames"].append({"tiff": str(path.relative_to(self.session)), "sha256": metadata["tiff_sha256"]})
        self.checkpoint_frame(metadata)

    def checkpoint_frame(self, metadata: dict) -> None:
        atomic_write_json(self.manifest_path, self.manifest)

    def emit_progress(self, phase: str, level: int, gain: int, exposure: float, region: np.ndarray, maximum: int) -> None:
        total = self.plan.condition_count * (self.plan.repeats + self.plan.dark_repeats)
        skipped_frames = len(self.manifest["skipped"]) * (self.plan.repeats + self.plan.dark_repeats)
        total -= skipped_frames
        elapsed = monotonic() - self.started
        remaining = max(0, total - self._frame_count) * elapsed / max(1, self._frame_count)
        self.progress(CaptureProgress(phase, f"CH{self.plan.channel} PWM{level} G{gain} E{exposure:g}ms",
                                      self._frame_count, total, elapsed, remaining, float(np.mean(region)),
                                      float(np.percentile(region, 99)), float(np.mean(region >= maximum * .98))))
