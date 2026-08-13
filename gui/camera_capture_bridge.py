from __future__ import annotations

"""Thread-safe bridge from a measurement worker to the existing live stream."""

from dataclasses import dataclass
from datetime import datetime
from threading import Event, Lock
from time import monotonic
from typing import Callable

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


class CameraCaptureBridge(QObject):
    """Use the next formal pull-mode frame; never starts a second camera stream."""

    configure_requested = Signal(int, int, int)

    def __init__(self, controller: CameraController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._lock = Lock()
        self._pending: _PendingCapture | None = None
        self._token = 0
        self.configure_requested.connect(self._configure)
        controller.frame_ready.connect(self._on_frame)

    def capture(
        self,
        exposure_ms: float,
        gain_percent: int,
        timeout_s: float,
        check_cancel: Callable[[], None],
    ) -> CapturedFrame:
        with self._lock:
            if self._pending is not None:
                raise RuntimeError("A camera capture request is already pending")
            self._token += 1
            pending = _PendingCapture(self._token, Event())
            self._pending = pending
        self.configure_requested.emit(
            round(float(exposure_ms) * 1000.0), int(gain_percent), pending.token
        )
        deadline = monotonic() + max(float(timeout_s), float(exposure_ms) / 1000.0 + 2.0)
        try:
            while not pending.event.wait(0.05):
                check_cancel()
                if monotonic() >= deadline:
                    raise TimeoutError(
                        f"Camera capture timeout at {exposure_ms:g} ms / Gain {gain_percent}%"
                    )
            if pending.error:
                raise RuntimeError(pending.error)
            if pending.frame is None:
                raise RuntimeError("Camera capture completed without a frame")
            return pending.frame
        finally:
            with self._lock:
                if self._pending is pending:
                    self._pending = None

    @Slot(int, int, int)
    def _configure(self, exposure_us: int, gain_percent: int, token: int) -> None:
        with self._lock:
            pending = self._pending
        if pending is None or pending.token != token:
            return
        if not self.controller.is_open:
            pending.error = "Camera is not connected"
            pending.event.set()
            return
        try:
            self.controller.set_manual_exposure(exposure_us, gain_percent)
            actual_exposure, actual_gain = self.controller.current_exposure()
            if actual_exposure != exposure_us or actual_gain != gain_percent:
                raise RuntimeError(
                    "Camera Exposure/Gain readback mismatch: "
                    f"requested={exposure_us} us/{gain_percent}%, "
                    f"actual={actual_exposure} us/{actual_gain}%"
                )
            pending.armed = True
        except Exception as exc:
            pending.error = str(exc)
            pending.event.set()

    @Slot(QImage)
    def _on_frame(self, image: QImage) -> None:
        with self._lock:
            pending = self._pending
        if pending is None or not pending.armed or pending.event.is_set():
            return
        temperature = None
        try:
            temperature = self.controller.read_temperature_c()
        except Exception:
            pass
        metadata = {
            "ImageWidth": image.width(),
            "ImageHeight": image.height(),
            "PixelFormat": "RGB24",
            "BitDepth": 8,
            "CameraModel": self.controller.device_name,
        }
        capture_metadata = getattr(self.controller, "capture_metadata", None)
        if callable(capture_metadata):
            metadata.update(capture_metadata())
        pending.frame = CapturedFrame(
            image.copy(),
            datetime.now().astimezone(),
            temperature,
            metadata,
        )
        pending.event.set()
