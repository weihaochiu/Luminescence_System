from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from .sdk import nncam


class CameraController(QObject):
    """Thin Qt-friendly layer around the RisingCam pull-mode SDK."""

    frame_ready = Signal(QImage)
    camera_opened = Signal(object)
    camera_closed = Signal()
    exposure_changed = Signal(int, int)
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

        self._sdk_event.connect(self._handle_sdk_event)
        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._poll_frame_rate)

    @property
    def is_open(self) -> bool:
        return self._camera is not None

    @property
    def device_name(self) -> str:
        return self._device.displayname if self._device is not None else ""

    @property
    def image_size(self) -> tuple[int, int]:
        return self._width, self._height

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

            exp_min, exp_max, exp_default = camera.get_ExpTimeRange()
            gain_min, gain_max, gain_default = camera.get_ExpoAGainRange()
            info = {
                "name": device.displayname,
                "model": device.model.name,
                "resolution_index": resolution_index,
                "resolutions": [(r.width, r.height) for r in device.model.res],
                "preview_count": device.model.preview,
                "exposure_range_us": (exp_min, exp_max, exp_default),
                "gain_range": (gain_min, gain_max, gain_default),
                "exposure_us": camera.get_ExpoTime(),
                "gain": camera.get_ExpoAGain(),
                "auto_target": camera.get_AutoExpoTarget(),
                "mono": bool(device.model.flag & nncam.NNCAM_FLAG_MONO),
                "sdk_version": self.sdk_version(),
            }
            self.camera_opened.emit(info)
            self._emit_exposure()
            self.status_changed.emit(f"已連線：{device.displayname}")
        except Exception as exc:
            self.close_camera()
            self.error_occurred.emit(self._format_error("開啟相機失敗", exc))

    def close_camera(self) -> None:
        self._fps_timer.stop()
        if self._camera is not None:
            try:
                self._camera.Close()
            except Exception:
                pass
        was_open = self._camera is not None
        self._camera = None
        self._device = None
        self._buffer = None
        self._width = 0
        self._height = 0
        self._pitch = 0
        self._auto_mode = 0
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

    def set_continuous_auto_exposure(self, enabled: bool) -> None:
        if self._camera is None:
            return
        try:
            mode = 1 if enabled else 0
            self._camera.put_AutoExpoEnable(mode)
            self._auto_mode = mode
            self.status_changed.emit("持續自動曝光已開啟" if enabled else "自動曝光已關閉")
        except Exception as exc:
            self.error_occurred.emit(self._format_error("切換自動曝光失敗", exc))

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

    def set_auto_exposure_target(self, target: int) -> None:
        if self._camera is None:
            return
        try:
            self._camera.put_AutoExpoTarget(int(target))
        except Exception as exc:
            self.error_occurred.emit(self._format_error("設定自動曝光目標失敗", exc))

    def current_exposure(self) -> tuple[int, int]:
        if self._camera is None:
            return 0, 0
        try:
            return self._camera.get_ExpoTime(), self._camera.get_ExpoAGain()
        except Exception:
            return 0, 0

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
            self.frame_ready.emit(image)
        except Exception as exc:
            self.error_occurred.emit(self._format_error("讀取影像失敗", exc))

    def _emit_exposure(self) -> None:
        exposure_us, gain = self.current_exposure()
        self.exposure_changed.emit(exposure_us, gain)

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
