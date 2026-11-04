from __future__ import annotations

"""Thread-safe bridge from a measurement worker to the existing live stream."""

from dataclasses import dataclass
from datetime import datetime
from threading import Event, Lock
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from .camera_controller import CameraController
from .el_matrix_runner import CapturedFrame


@dataclass
class _PendingCapture:
    token: int
    event: Event
    frame: CapturedFrame | None = None
    error: str = ""
    armed: bool = False
    minimum_sequence: int = 0
    requested_exposure_us: int = 0
    setting_exposure_us: int = 0
    actual_exposure_us: int = 0
    actual_gain_percent: int = 0
    accept_actual_readback: bool = False
    require_frame_exposure_match: bool = False
    discard_remaining: int = 0
    discarded_frames: int = 0
    exposure_mismatch_frames: int = 0
    software_triggered: bool = False
    capture_diagnostics: dict[str, object] | None = None
    exception: Exception | None = None


@dataclass
class _PendingAutoExposure:
    settings: dict[str, Any]
    event: Event
    state: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str = ""
    active: bool = True
    exception: Exception | None = None


@dataclass
class _PendingROI:
    roi: tuple[int, int, int, int]
    event: Event
    active: bool = True
    error: str = ""
    exception: Exception | None = None


class CameraCaptureBridge(QObject):
    """Use the next formal pull-mode frame; never starts a second camera stream."""

    configure_requested = Signal(int, int, int)
    restore_requested = Signal(object, object, object)
    cleanup_requested = Signal(object, object)
    auto_exposure_requested = Signal(object)
    auto_exposure_cleanup_requested = Signal(object, object, object)
    roi_requested = Signal(object)

    def __init__(self, controller: CameraController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._lock = Lock()
        self._pending: _PendingCapture | None = None
        self._pending_ae: _PendingAutoExposure | None = None
        self._pending_roi: _PendingROI | None = None
        self._token = 0
        self._fallback_sequence = 0
        self.configure_requested.connect(self._configure)
        self.restore_requested.connect(self._restore_state)
        self.cleanup_requested.connect(self._cleanup_trigger_mode)
        self.auto_exposure_requested.connect(self._begin_auto_exposure)
        self.auto_exposure_cleanup_requested.connect(self._cleanup_auto_exposure)
        self.roi_requested.connect(self._set_metering_roi)
        result_signal = getattr(controller, "auto_exposure_result", None)
        if result_signal is not None:
            result_signal.connect(self._on_auto_exposure_result)
        for signal_name in ("camera_closed", "error_occurred"):
            signal = getattr(controller, signal_name, None)
            if signal is not None:
                signal.connect(self._fail_auto_exposure)
        scientific = getattr(controller, "scientific_frame_ready", None)
        if scientific is not None:
            scientific.connect(self._on_scientific_frame)
            self._uses_explicit_sequence = True
        else:
            sequenced = getattr(controller, "frame_ready_sequenced", None)
            if sequenced is not None:
                sequenced.connect(self._on_sequenced_frame)
                self._uses_explicit_sequence = True
            else:
                controller.frame_ready.connect(self._on_frame)
                self._uses_explicit_sequence = False

    def capture(
        self,
        exposure_ms: float,
        gain_percent: int,
        timeout_s: float,
        check_cancel: Callable[[], None],
        *,
        accept_actual_readback: bool = False,
        settling_frames: int = 0,
        require_frame_exposure_match: bool = False,
        software_triggered: bool = False,
    ) -> CapturedFrame:
        settling_frame_count = max(0, int(settling_frames))
        with self._lock:
            if self._pending is not None or self._pending_ae is not None or self._pending_roi is not None:
                raise RuntimeError("A camera capture request is already pending")
            self._token += 1
            baseline = int(getattr(self.controller, "frame_sequence", self._fallback_sequence))
            pending = _PendingCapture(
                self._token,
                Event(),
                minimum_sequence=baseline + 1,
                accept_actual_readback=bool(accept_actual_readback),
                require_frame_exposure_match=bool(require_frame_exposure_match),
                software_triggered=bool(software_triggered),
                discard_remaining=settling_frame_count,
            )
            self._pending = pending
        self.configure_requested.emit(
            round(float(exposure_ms) * 1000.0), int(gain_percent), pending.token
        )
        exposure_s = float(exposure_ms) / 1000.0
        deadline = monotonic() + max(
            float(timeout_s),
            exposure_s * (settling_frame_count + 1) + 2.0,
        )
        failure = None
        try:
            while not pending.event.wait(0.05):
                check_cancel()
                if monotonic() >= deadline:
                    raise TimeoutError(
                        f"Camera capture timeout at {exposure_ms:g} ms / Gain {gain_percent}%"
                    )
            if pending.error:
                raise RuntimeError(pending.error) from pending.exception
            if pending.frame is None:
                raise RuntimeError("Camera capture completed without a frame")
            return pending.frame
        except Exception as exc:
            failure = exc
            raise
        finally:
            # Keep the request reserved until cleanup ends, but invalidate
            # late configuration callbacks after cancellation or timeout.
            pending.event.set()
            pending.armed = False
            try:
                if pending.software_triggered:
                    self._request_trigger_cleanup()
            except Exception as cleanup:
                if failure is not None:
                    raise RuntimeError(f"{failure}; Camera cleanup failed: {cleanup}") from failure
                raise
            finally:
                with self._lock:
                    if self._pending is pending:
                        self._pending = None

    def set_metering_roi(self, roi, check_cancel: Callable[[], None], timeout_s: float = 10.0) -> None:
        """Apply channel metering on the controller's owner thread, before AE."""
        check_cancel()
        pending = _PendingROI(tuple(roi), Event())
        with self._lock:
            if self._pending is not None or self._pending_ae is not None or self._pending_roi is not None:
                raise RuntimeError("A camera request is already pending")
            self._pending_roi = pending
        deadline = monotonic() + timeout_s
        self.roi_requested.emit(pending)
        try:
            while not pending.event.wait(0.05):
                check_cancel()
                if monotonic() >= deadline:
                    raise TimeoutError("Channel ROI setting timed out")
            check_cancel()
            if pending.error:
                raise RuntimeError(pending.error) from pending.exception
        finally:
            pending.active = False
            with self._lock:
                if self._pending_roi is pending:
                    self._pending_roi = None

    @Slot(object)
    def _set_metering_roi(self, pending: _PendingROI) -> None:
        if not pending.active or self._pending_roi is not pending:
            return
        try:
            if not self.controller.set_auto_exposure_roi(*pending.roi):
                raise RuntimeError("Channel AE ROI readback verification failed")
        except Exception as exc:
            pending.exception = exc
            pending.error = str(exc)
        finally:
            pending.event.set()

    def auto_exposure(
        self, settings: dict[str, Any], check_cancel: Callable[[], None],
    ) -> dict[str, Any]:
        """Run native one-shot AE on the Qt thread; freeze before returning."""
        check_cancel()
        pending = _PendingAutoExposure(dict(settings), Event(), {})
        with self._lock:
            if self._pending is not None or self._pending_ae is not None or self._pending_roi is not None:
                raise RuntimeError("A camera request is already pending")
            self._pending_ae = pending
        deadline = monotonic() + float(settings["auto_timeout_s"])
        self.auto_exposure_requested.emit(pending)
        failure = None
        try:
            while not pending.event.wait(0.05):
                check_cancel()
                if monotonic() >= deadline:
                    raise TimeoutError("Recipe auto exposure did not converge before timeout")
            check_cancel()
            if pending.error:
                raise RuntimeError(pending.error) from pending.exception
            if pending.result is None:
                raise RuntimeError("Recipe AE completed without Exposure/Gain readback")
            return pending.result
        except Exception as exc:
            failure = exc
            raise
        finally:
            pending.active = False
            completed, response = Event(), {}
            self.auto_exposure_cleanup_requested.emit(pending, completed, response)
            try:
                if not completed.wait(5.0):
                    raise TimeoutError("Recipe AE cleanup timed out")
                if response.get("error"):
                    raise RuntimeError(response["error"]) from response.get("exception")
            except Exception as cleanup:
                if failure is not None:
                    raise RuntimeError(f"{failure}; Recipe AE cleanup failed: {cleanup}") from failure
                raise
            finally:
                with self._lock:
                    if self._pending_ae is pending:
                        self._pending_ae = None

    @Slot(object)
    def _begin_auto_exposure(self, pending: _PendingAutoExposure) -> None:
        if not pending.active or self._pending_ae is not pending:
            return
        try:
            from .camera_recipe_ae import begin_recipe_ae
            begin_recipe_ae(self.controller, pending.settings, pending.state)
        except Exception as exc:
            pending.exception = exc
            pending.error = str(exc)
            pending.event.set()

    @Slot(bool, str)
    def _on_auto_exposure_result(self, success: bool, message: str) -> None:
        pending = self._pending_ae
        if pending is None or not pending.active or pending.event.is_set():
            return
        try:
            from .camera_recipe_ae import verify_recipe_ae_roi
            if not success:
                raise RuntimeError(message)
            metadata = dict(pending.state["result_metadata"])
            verify_recipe_ae_roi(
                self.controller, metadata["RecipeAEROI"], metadata["RecipeAEROIStreamGeneration"],
            )
            exposure, gain = self.controller.current_exposure()
            if (not metadata["RecipeAEMinExposureMs"] * 1000 <= exposure
                    <= metadata["RecipeAEMaxExposureMs"] * 1000
                    or not metadata["RecipeAEMinGain"] <= gain <= metadata["RecipeAEMaxGain"]):
                raise RuntimeError("Recipe AE result is outside verified limits")
            pending.result = {"exposure_us": exposure, "gain_percent": gain,
                              "metadata": metadata}
        except Exception as exc:
            pending.exception = exc
            from .camera_recipe_ae import recipe_ae_failure_context
            try:
                details = recipe_ae_failure_context(self.controller, pending.state)
            except Exception as diagnostic_error:
                details = f"unavailable: {diagnostic_error}"
            pending.error = f"{exc}; Recipe AE diagnostics={details}"
        pending.event.set()

    def _fail_auto_exposure(self, message: str = "Camera disconnected during Recipe AE") -> None:
        pending = self._pending_ae
        if pending is not None and pending.active and not pending.event.is_set():
            pending.error = message
            pending.event.set()

    @Slot(object, object, object)
    def _cleanup_auto_exposure(self, pending: _PendingAutoExposure,
                               completed: Event, response: dict) -> None:
        try:
            if pending.state:
                from .camera_recipe_ae import restore_recipe_ae
                restore_recipe_ae(self.controller, pending.state)
        except Exception as exc:
            response["exception"] = exc
            response["error"] = str(exc)
        finally:
            completed.set()

    def restore_state(self, state: dict[str, object], timeout_s: float = 5.0) -> None:
        """Synchronously request state restoration on the CameraController owner thread."""

        completed = Event()
        response: dict[str, Any] = {}
        self.restore_requested.emit(dict(state), completed, response)
        if not completed.wait(max(0.1, float(timeout_s))):
            raise TimeoutError("Camera state restoration timed out")
        if response.get("error"):
            raise RuntimeError(response["error"]) from response.get("exception")

    def _request_trigger_cleanup(self, timeout_s: float = 5.0) -> None:
        completed = Event()
        response: dict[str, Any] = {}
        self.cleanup_requested.emit(completed, response)
        if not completed.wait(max(0.1, float(timeout_s))):
            raise TimeoutError("Camera trigger-mode cleanup timed out")
        if response.get("error"):
            raise RuntimeError(response["error"]) from response.get("exception")

    @Slot(object, object)
    def _cleanup_trigger_mode(self, completed: object, response: object) -> None:
        try:
            finish = getattr(
                self.controller, "finish_software_triggered_capture", None
            )
            if callable(finish):
                finish()
        except Exception as exc:
            if isinstance(response, dict):
                response["exception"] = exc
                response["error"] = str(exc)
        finally:
            if isinstance(completed, Event):
                completed.set()

    @Slot(object, object, object)
    def _restore_state(
        self,
        state: object,
        completed: object,
        response: object,
    ) -> None:
        try:
            if isinstance(state, dict):
                self.controller.restore_exposure_state(state)
        except Exception as exc:
            if isinstance(response, dict):
                response["exception"] = exc
                response["error"] = str(exc)
        finally:
            if isinstance(completed, Event):
                completed.set()

    @Slot(int, int, int)
    def _configure(self, exposure_us: int, gain_percent: int, token: int) -> None:
        with self._lock:
            pending = self._pending
        if pending is None or pending.token != token or pending.event.is_set():
            return
        if not self.controller.is_open:
            pending.error = "Camera is not connected"
            pending.event.set()
            return
        try:
            pending.requested_exposure_us = int(exposure_us)
            if pending.software_triggered:
                prepare = getattr(
                    self.controller, "prepare_software_triggered_capture", None
                )
                trigger = getattr(self.controller, "trigger_single_frame", None)
                if not callable(prepare) or not callable(trigger):
                    raise RuntimeError(
                        "Camera controller does not support formal software-trigger capture"
                    )
                diagnostics = dict(prepare(exposure_us, gain_percent))
                setting_exposure = int(
                    diagnostics["ExposureSettingReadbackUs"]
                )
                actual_exposure = int(diagnostics["RealExposureReadbackUs"])
                actual_gain = int(diagnostics["GainReadback"])
                pending.capture_diagnostics = diagnostics
            else:
                self.controller.set_manual_exposure(exposure_us, gain_percent)
                setting_exposure, actual_gain = self.controller.current_exposure()
                actual_exposure = setting_exposure
            if (
                not pending.accept_actual_readback
                and (setting_exposure != exposure_us or actual_gain != gain_percent)
            ):
                raise RuntimeError(
                    "Camera Exposure/Gain readback mismatch: "
                    f"requested={exposure_us} us/{gain_percent}%, "
                    f"actual={setting_exposure} us/{actual_gain}%"
                )
            pending.setting_exposure_us = int(setting_exposure)
            pending.actual_exposure_us = int(actual_exposure)
            pending.actual_gain_percent = int(actual_gain)
            # Frames generated before the setting readback completed may still
            # be queued in Qt/SDK. Only a later generation is a formal frame.
            current_sequence = int(
                getattr(self.controller, "frame_sequence", self._fallback_sequence)
            )
            pending.minimum_sequence = current_sequence + 1
            if pending.event.is_set():
                return
            pending.armed = True
            if pending.software_triggered:
                trigger()
        except Exception as exc:
            cleanup_error = None
            finish = getattr(
                self.controller, "finish_software_triggered_capture", None
            )
            if pending.software_triggered and callable(finish):
                try:
                    finish()
                except Exception as cleanup:
                    cleanup_error = cleanup
            pending.exception = exc
            pending.error = str(exc)
            if cleanup_error is not None:
                pending.error += f"; Camera cleanup failed: {cleanup_error}"
            pending.event.set()

    @Slot(QImage)
    def _on_frame(self, image: QImage) -> None:
        self._fallback_sequence += 1
        self._accept_frame(image, self._fallback_sequence)

    @Slot(QImage, int)
    def _on_sequenced_frame(self, image: QImage, sequence: int) -> None:
        self._accept_frame(image, int(sequence))

    @Slot(object, QImage, int)
    def _on_scientific_frame(
        self, scientific_image: object, image: QImage, sequence: int
    ) -> None:
        self._accept_frame(image, int(sequence), scientific_image)

    def _accept_frame(
        self, image: QImage, sequence: int, scientific_image: object | None = None
    ) -> None:
        with self._lock:
            pending = self._pending
        if (
            pending is None or not pending.armed or pending.event.is_set()
            or sequence < pending.minimum_sequence
        ):
            return
        frame_metadata_reader = getattr(
            self.controller, "frame_capture_metadata", None
        )
        frame_metadata = (
            dict(frame_metadata_reader(sequence))
            if callable(frame_metadata_reader)
            else {}
        )
        verification = {}
        if pending.require_frame_exposure_match:
            frame_exposure = frame_metadata.get("FrameExposureUs")
            frame_gain = frame_metadata.get("FrameGainPercent")
            combined_valid = bool(frame_metadata.get("FrameExposureGainMetadataValid"))
            exposure_valid = bool(frame_metadata.get(
                "FrameExposureMetadataValid", combined_valid
            )) and frame_exposure is not None
            gain_valid = bool(frame_metadata.get(
                "FrameGainMetadataValid", combined_valid
            )) and frame_gain is not None
            # A missing Gain flag must not disable a valid Exposure check (or
            # vice versa). Never interpret raw fields without their flags.
            if (
                (exposure_valid and int(frame_exposure) != pending.actual_exposure_us)
                or (gain_valid and int(frame_gain) != pending.actual_gain_percent)
            ):
                pending.exposure_mismatch_frames += 1
                pending.minimum_sequence = sequence + 1
                return
            if not (exposure_valid and gain_valid) and not pending.software_triggered:
                pending.error = (
                    "Camera frame Exposure/Gain metadata is unavailable; "
                    "refusing to save an unverified frame"
                )
                pending.event.set()
                return
            if pending.software_triggered:
                try:
                    diagnostics = pending.capture_diagnostics or {}
                    if not diagnostics.get("CaptureStreamRestarted"):
                        raise RuntimeError("Triggered capture stream restart was not confirmed")
                    after = self.controller.triggered_capture_readback()
                    expected = {
                        "ExposureSettingAfterCaptureUs": pending.setting_exposure_us,
                        "RealExposureAfterCaptureUs": pending.actual_exposure_us,
                        "GainAfterCapture": pending.actual_gain_percent,
                        "TriggerModeAfterCapture": 1,
                        "AutoExposureAfterCapture": 0,
                    }
                    if after != expected or pending.actual_exposure_us <= 0:
                        raise RuntimeError(
                            f"Camera state changed during triggered capture: expected={expected}, actual={after}"
                        )
                    verification.update(after)
                except Exception as exc:
                    pending.exception = exc
                    pending.error = str(exc)
                    pending.event.set()
                    return
            frame_metadata["FrameExposureUs"] = frame_exposure if exposure_valid else None
            frame_metadata["FrameGainPercent"] = frame_gain if gain_valid else None
            verification.update({
                "FrameMetadataStatus": (
                    "AVAILABLE" if exposure_valid and gain_valid else
                    "PARTIAL" if exposure_valid or gain_valid else "UNAVAILABLE"
                ),
                "ExposureVerificationSource": (
                    "FrameMetadata" if exposure_valid else
                    "RealExposureReadback+SoftwareTrigger"
                ),
                "GainVerificationSource": (
                    "FrameMetadata" if gain_valid else "GainReadback+SoftwareTrigger"
                ),
                "ExposureUsedUs": int(frame_exposure) if exposure_valid else pending.actual_exposure_us,
            })
        if pending.discard_remaining > 0:
            pending.discard_remaining -= 1
            pending.discarded_frames += 1
            pending.minimum_sequence = sequence + 1
            return
        temperature = None
        try:
            temperature = self.controller.read_temperature_c()
        except Exception:
            pass
        capture_metadata = getattr(self.controller, "capture_metadata", None)
        controller_metadata = (
            dict(capture_metadata()) if callable(capture_metadata) else {}
        )
        metadata = dict(controller_metadata)
        metadata.update({
            "ImageWidth": image.width(),
            "ImageHeight": image.height(),
            "PixelFormat": (
                str(controller_metadata.get("PixelFormat", "UNKNOWN"))
                if scientific_image is not None else "RGB24"
            ),
            "BitDepth": (
                int(controller_metadata.get("BitDepth", 8))
                if scientific_image is not None else 8
            ),
            "CameraModel": self.controller.device_name,
            "FrameSequence": sequence,
            "RequestedExposureUs": pending.requested_exposure_us,
            "ExposureSettingReadbackUs": pending.setting_exposure_us,
            "ExposureReadbackUs": pending.setting_exposure_us,
            "RealExposureReadbackUs": pending.actual_exposure_us,
            "GainReadback": pending.actual_gain_percent,
            "SettlingFramesDiscarded": pending.discarded_frames,
            "ExposureMismatchFramesDiscarded": pending.exposure_mismatch_frames,
        })
        if pending.capture_diagnostics:
            metadata.update(pending.capture_diagnostics)
        metadata.update(frame_metadata)
        metadata.update(verification)
        frame_exposure = metadata.get("ExposureUsedUs", metadata.get("FrameExposureUs"))
        if frame_exposure is not None and pending.requested_exposure_us > 0:
            difference_us = int(frame_exposure) - pending.requested_exposure_us
            metadata["ExposureDifferenceUs"] = difference_us
            metadata["ExposureDifferencePercent"] = (
                difference_us / pending.requested_exposure_us * 100.0
            )
            metadata["ExposureStatus"] = (
                "EXACT" if difference_us == 0 else "ACTUAL_DIFFERENT"
            )
        pending.frame = CapturedFrame(
            image.copy(),
            datetime.now().astimezone(),
            temperature,
            metadata,
            scientific_image,
        )
        pending.event.set()
