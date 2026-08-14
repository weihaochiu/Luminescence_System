from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from .camera_exposure import validate_auto_target
from .camera_temperature_monitor import CameraTemperatureUnsupportedError
from .image_brightness import equivalent_brightness_8bit
from .sdk import nncam


LOG = logging.getLogger(__name__)


class CameraController(QObject):
    """Thin Qt-friendly layer around the RisingCam pull-mode SDK."""

    frame_ready = Signal(QImage)
    frame_ready_sequenced = Signal(QImage, int)
    camera_opened = Signal(object)
    camera_closing = Signal()
    camera_closed = Signal()
    exposure_changed = Signal(int, int)
    exposure_status_changed = Signal(object, object, object)
    auto_exposure_result = Signal(bool, str)
    fps_changed = Signal(float, int)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    _sdk_event = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._camera: Any | None = None
        self._device: Any | None = None
        self._buffer: bytes | None = None
        self._width = 0
        self._height = 0
        self._pitch = 0
        self._auto_mode = 0
        self._latest_image: QImage | None = None
        self._status_query_failed = False
        self._frame_sequence = 0

        self._sdk_event.connect(self._handle_sdk_event)
        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._poll_frame_rate)
        self._camera_status_timer = QTimer(self)
        self._camera_status_timer.setInterval(300)
        self._camera_status_timer.timeout.connect(self._poll_camera_status)

    @property
    def is_open(self) -> bool:
        return self._camera is not None

    @property
    def device_name(self) -> str:
        return self._device.displayname if self._device is not None else ""

    @property
    def image_size(self) -> tuple[int, int]:
        return self._width, self._height

    @property
    def frame_sequence(self) -> int:
        return self._frame_sequence

    @property
    def temperature_supported(self) -> bool:
        return bool(
            self._device is not None
            and self._device.model.flag & nncam.NNCAM_FLAG_GETTEMPERATURE
        )

    def enumerate_devices(self) -> list[Any]:
        try:
            nncam.Nncam.GigeEnable(None, None)
            return list(nncam.Nncam.EnumV2())
        except Exception as exc:
            self.error_occurred.emit(self._format_error("無法載入相機 SDK 或列出相機", exc))
            return []

    def open_device(self, device: Any) -> None:
        self.close_camera()
        try:
            camera = nncam.Nncam.Open(device.id)
            if not camera:
                raise RuntimeError("SDK 未回傳有效的相機控制代碼")

            self._camera = camera
            self._device = device
            resolution_index = camera.get_eSize()
            resolution = device.model.res[resolution_index]
            self._width, self._height = resolution.width, resolution.height

            # Match QImage's RGB byte order. Preview and saved basic captures use RGB24.
            camera.put_Option(nncam.NNCAM_OPTION_BYTEORDER, 0)
            camera.put_AutoExpoEnable(1)
            self._auto_mode = 1
            self._start_stream()

            capabilities = self._query_camera_capabilities(camera)
            current = self._read_current_exposure(camera)
            auto_target = self._query_optional(camera, "get_AutoExpoTarget", "Auto Exposure Target")
            info = {
                "name": device.displayname,
                "model": device.model.name,
                "identifier": self._device_identifier(device),
                "resolution_index": resolution_index,
                "resolutions": [(r.width, r.height) for r in device.model.res],
                "preview_count": device.model.preview,
                **capabilities,
                "exposure_us": current[0] if current is not None else None,
                "gain": current[1] if current is not None else None,
                "auto_target": auto_target,
                "mono": bool(device.model.flag & nncam.NNCAM_FLAG_MONO),
                "temperature_supported": bool(
                    device.model.flag & nncam.NNCAM_FLAG_GETTEMPERATURE
                ),
                "sdk_version": self.sdk_version(),
            }
            self._log_camera_capabilities(info)
            self.camera_opened.emit(info)
            if current is not None:
                self.exposure_changed.emit(*current)
            self._camera_status_timer.start()
            self.status_changed.emit(f"已連線：{device.displayname}")
        except Exception as exc:
            self.close_camera()
            self.error_occurred.emit(self._format_error("開啟相機失敗", exc))

    def close_camera(self) -> None:
        was_open = self._camera is not None
        if was_open:
            # Direct Qt slots stop telemetry and close its CSV before the SDK
            # handle can be destroyed.
            self.camera_closing.emit()
        self._fps_timer.stop()
        self._camera_status_timer.stop()
        if self._camera is not None:
            try:
                self._camera.Close()
            except Exception:
                pass
        self._camera = None
        self._device = None
        self._buffer = None
        self._width = 0
        self._height = 0
        self._pitch = 0
        self._auto_mode = 0
        self._latest_image = None
        self._status_query_failed = False
        self._frame_sequence = 0
        if was_open:
            self.camera_closed.emit()
            self.status_changed.emit("相機已中斷連線")

    def set_resolution(self, index: int) -> None:
        if self._camera is None or self._device is None:
            return
        if index < 0 or index >= self._device.model.preview:
            return

        try:
            previous_auto_mode = self._camera.get_AutoExpoEnable()
            self._camera.Stop()
            self._camera.put_eSize(index)
            resolution = self._device.model.res[index]
            self._width, self._height = resolution.width, resolution.height
            self._start_stream()
            self._camera.put_AutoExpoEnable(previous_auto_mode)
            self._auto_mode = previous_auto_mode
            self.status_changed.emit(f"解析度：{self._width} × {self._height}")
        except Exception as exc:
            self.error_occurred.emit(self._format_error("切換解析度失敗", exc))

    def set_manual_exposure(self, exposure_us: int, gain: int) -> None:
        if self._camera is None:
            return
        try:
            self._camera.put_AutoExpoEnable(0)
            self._camera.put_ExpoTime(int(exposure_us))
            self._camera.put_ExpoAGain(int(gain))
            self._auto_mode = 0
            self._emit_exposure()
            self.status_changed.emit("手動曝光設定已套用")
        except Exception as exc:
            self.error_occurred.emit(self._format_error("套用手動曝光失敗", exc))

    def switch_to_manual_exposure(self) -> bool:
        """Disable AE and preserve the camera's last actual exposure and gain."""

        if self._camera is None:
            return False
        try:
            self._camera.put_AutoExpoEnable(0)
            self._auto_mode = 0
            current = self._read_current_exposure(self._camera)
            if current is None:
                raise RuntimeError("SDK 無法讀回目前 Exposure/Gain")
            self.exposure_changed.emit(*current)
            self.status_changed.emit("已切換為手動曝光並保留目前 Exposure/Gain")
            return True
        except Exception as exc:
            try:
                self._camera.put_AutoExpoEnable(1)
                self._auto_mode = 1
            except Exception as rollback_exc:
                LOG.error("Failed to restore continuous AE after mode-switch error: %s", rollback_exc)
            self.error_occurred.emit(self._format_error("切換手動曝光失敗", exc))
            return False

    def enable_continuous_auto_exposure(self, target: int) -> bool:
        """Apply the retained target first, then enable continuous AE."""

        if self._camera is None:
            return False
        try:
            target = validate_auto_target(target)
            self._camera.put_AutoExpoTarget(target)
            self._camera.put_AutoExpoEnable(1)
            self._auto_mode = 1
            self.status_changed.emit("持續自動曝光已開啟")
            return True
        except Exception as exc:
            self.error_occurred.emit(self._format_error("切換持續自動曝光失敗", exc))
            return False

    def start_auto_exposure_once(self) -> None:
        if self._camera is None:
            return
        try:
            self._camera.put_AutoExpoEnable(2)
            self._auto_mode = 2
            self.status_changed.emit("正在等待自動曝光收斂…")
        except Exception as exc:
            self.auto_exposure_result.emit(False, self._format_error("無法啟動單次自動曝光", exc))

    def lock_current_exposure(self) -> None:
        if self._camera is None:
            return
        try:
            self._camera.put_AutoExpoEnable(0)
            self._auto_mode = 0
            self._emit_exposure()
        except Exception as exc:
            self.error_occurred.emit(self._format_error("鎖定曝光失敗", exc))

    def set_auto_exposure_target(self, target: int) -> bool:
        if self._camera is None:
            return False
        try:
            self._camera.put_AutoExpoTarget(validate_auto_target(target))
            return True
        except Exception as exc:
            self.error_occurred.emit(self._format_error("設定影像亮度目標失敗", exc))
            return False

    def current_exposure(self) -> tuple[int, int]:
        if self._camera is None:
            return 0, 0
        current = self._read_current_exposure(self._camera)
        return current if current is not None else (0, 0)

    def capture_metadata(self) -> dict[str, Any]:
        """Stable identity/format fields for a frame already pulled by this controller."""

        model = getattr(getattr(self._device, "model", None), "name", "")
        return {
            "CameraModel": str(model or self.device_name),
            "CameraSerial": self._device_identifier(self._device) if self._device is not None else "",
            "Resolution": f"{self._width}x{self._height}",
            "ImageWidth": self._width,
            "ImageHeight": self._height,
            "PixelFormat": "RGB24",
            "BitDepth": 8,
        }

    def read_temperature_c(self) -> float | None:
        """Read sensor temperature via bundled SDK, returning degrees Celsius.

        ``Nncam.get_Temperature`` returns signed tenths of a degree Celsius.
        This method must run in the controller's Qt thread so it is serialized
        with pull-mode event handling and all other camera calls.
        """

        if self._camera is None:
            return None
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Camera temperature query must run in the camera owner thread")
        if not self.temperature_supported:
            raise CameraTemperatureUnsupportedError(
                "NNCAM_FLAG_GETTEMPERATURE is not present for this camera"
            )
        raw_tenths_c = int(self._camera.get_Temperature())
        return raw_tenths_c / 10.0

    @staticmethod
    def _read_current_exposure(camera: Any) -> tuple[int, int] | None:
        try:
            return int(camera.get_ExpoTime()), int(camera.get_ExpoAGain())
        except Exception:
            return None

    @staticmethod
    def _device_identifier(device: Any) -> str:
        identifier = getattr(device, "id", "")
        if isinstance(identifier, bytes):
            return identifier.decode("utf-8", errors="replace")
        return str(identifier)

    @staticmethod
    def _query_optional(camera: Any, method_name: str, description: str) -> Any | None:
        try:
            return getattr(camera, method_name)()
        except Exception as exc:
            LOG.warning("RisingCam SDK query failed for %s: %s", description, exc)
            return None

    @classmethod
    def _query_camera_capabilities(cls, camera: Any) -> dict[str, Any]:
        exposure_range = cls._query_optional(
            camera, "get_ExpTimeRange", "Camera Exposure Hardware Range"
        )
        gain_range = cls._query_optional(
            camera, "get_ExpoAGainRange", "Camera Gain Hardware Range"
        )

        auto_range_raw = cls._query_optional(camera, "get_AutoExpoRange", "Auto Exposure Range")
        auto_min = cls._query_optional(
            camera, "get_MinAutoExpoTimeAGain", "Auto Exposure minimum limit"
        )
        auto_max = cls._query_optional(
            camera, "get_MaxAutoExpoTimeAGain", "Auto Exposure maximum limit"
        )
        auto_range = None
        if auto_range_raw is not None:
            max_time, min_time, max_gain, min_gain = auto_range_raw
            auto_range = (int(min_time), int(max_time), int(min_gain), int(max_gain))
        if auto_min is not None and auto_max is not None:
            auto_range = (
                int(auto_min[0]),
                int(auto_max[0]),
                int(auto_min[1]),
                int(auto_max[1]),
            )

        return {
            "exposure_range_us": tuple(map(int, exposure_range)) if exposure_range else None,
            "gain_range": tuple(map(int, gain_range)) if gain_range else None,
            "auto_exposure_range": auto_range,
        }

    @staticmethod
    def _log_camera_capabilities(info: dict[str, Any]) -> None:
        exposure = info.get("exposure_range_us")
        gain = info.get("gain_range")
        auto_range = info.get("auto_exposure_range")
        target = info.get("auto_target")
        LOG.info(
            "Camera Exposure Hardware Range: min = %s us, max = %s us, default = %s us\n"
            "Camera Gain Hardware Range: min = %s %%, max = %s %%, default = %s %%\n"
            "Auto Exposure Range: min exposure = %s us, max exposure = %s us, "
            "min gain = %s %%, max gain = %s %%\n"
            "Auto Exposure Target: %s /255",
            *(exposure or ("--", "--", "--")),
            *(gain or ("--", "--", "--")),
            *(auto_range or ("--", "--", "--", "--")),
            target if target is not None else "--",
        )

    @staticmethod
    def sdk_version() -> str:
        try:
            version = nncam.Nncam.Version()
            return version.decode("ascii", errors="replace") if isinstance(version, bytes) else str(version)
        except Exception:
            return "unknown"

    def _start_stream(self) -> None:
        if self._camera is None:
            return
        self._pitch = nncam.TDIBWIDTHBYTES(self._width * 24)
        self._buffer = bytes(self._pitch * self._height)
        self._camera.StartPullModeWithCallback(self._camera_callback, self)
        self._fps_timer.start()

    @staticmethod
    def _camera_callback(event_code: int, context: "CameraController") -> None:
        # SDK callbacks run on an internal native thread. A Qt signal moves work
        # safely back to the GUI thread before the image buffer is touched.
        context._sdk_event.emit(event_code)

    @Slot(int)
    def _handle_sdk_event(self, event_code: int) -> None:
        if self._camera is None:
            return

        if event_code == nncam.NNCAM_EVENT_IMAGE:
            self._pull_live_frame()
        elif event_code == nncam.NNCAM_EVENT_EXPOSURE:
            self._emit_exposure()
        elif event_code == nncam.NNCAM_EVENT_AUTOEXPO_CONV:
            self.lock_current_exposure()
            self.auto_exposure_result.emit(True, "自動曝光已收斂")
        elif event_code == nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL:
            self.lock_current_exposure()
            self.auto_exposure_result.emit(False, "自動曝光未能收斂")
        elif event_code == nncam.NNCAM_EVENT_DISCONNECTED:
            self.close_camera()
            self.error_occurred.emit("相機連線中斷，請檢查 USB 線與供電。")
        elif event_code in (nncam.NNCAM_EVENT_ERROR, nncam.NNCAM_EVENT_NOFRAMETIMEOUT):
            self.error_occurred.emit(f"相機回報錯誤事件：0x{event_code:04X}")

    def _pull_live_frame(self) -> None:
        if self._camera is None or self._buffer is None:
            return
        try:
            self._camera.PullImageV4(self._buffer, 0, 24, 0, None)
            image = QImage(
                self._buffer,
                self._width,
                self._height,
                self._pitch,
                QImage.Format.Format_RGB888,
            ).copy()
            self._latest_image = image
            self._frame_sequence += 1
            self.frame_ready.emit(image)
            self.frame_ready_sequenced.emit(image, self._frame_sequence)
        except Exception as exc:
            self.error_occurred.emit(self._format_error("讀取影像失敗", exc))

    def _emit_exposure(self) -> None:
        if self._camera is None:
            return
        current = self._read_current_exposure(self._camera)
        if current is not None:
            self.exposure_changed.emit(*current)

    @Slot()
    def _poll_camera_status(self) -> None:
        if self._camera is None:
            return
        current = self._read_current_exposure(self._camera)
        try:
            brightness = (
                equivalent_brightness_8bit(self._latest_image)
                if self._latest_image is not None
                else None
            )
        except Exception as exc:
            LOG.warning("Unable to calculate current image brightness: %s", exc)
            brightness = None
        if current is None:
            if not self._status_query_failed:
                LOG.warning("RisingCam SDK failed to refresh current Exposure/Gain")
            self._status_query_failed = True
            self.exposure_status_changed.emit(None, None, brightness)
            return
        self._status_query_failed = False
        self.exposure_status_changed.emit(current[0], current[1], brightness)

    @Slot()
    def _poll_frame_rate(self) -> None:
        if self._camera is None:
            return
        try:
            frame_count, elapsed_ms, total_frames = self._camera.get_FrameRate()
            fps = (frame_count * 1000.0 / elapsed_ms) if elapsed_ms else 0.0
            self.fps_changed.emit(fps, total_frames)
        except Exception:
            self.fps_changed.emit(0.0, 0)

    @staticmethod
    def _format_error(prefix: str, exc: Exception) -> str:
        hr = getattr(exc, "hr", None)
        if hr is not None:
            return f"{prefix}（SDK HRESULT 0x{hr & 0xFFFFFFFF:08X}）"
        return f"{prefix}：{exc}"
