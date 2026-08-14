from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from .camera_exposure import validate_auto_target
from .camera_temperature_monitor import CameraTemperatureUnsupportedError
from .image_brightness import equivalent_brightness_8bit
from .sdk import nncam


LOG = logging.getLogger(__name__)
_T = TypeVar("_T")


class CameraStartupError(RuntimeError):
    """Preserve the exact SDK startup stage while retaining its HRESULT."""

    def __init__(self, stage: str, original: Exception) -> None:
        super().__init__(str(original))
        self.stage = stage
        self.original = original
        self.hr = getattr(original, "hr", None)


class CameraController(QObject):
    """Thin Qt-friendly layer around the RisingCam pull-mode SDK."""

    frame_ready = Signal(QImage)
    frame_ready_sequenced = Signal(QImage, int)
    scientific_frame_ready = Signal(object, QImage, int)
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
        self._sensor_bit_depth: int | None = None
        self._bit_depth_source = "Unknown"
        self._camera_is_mono = False
        self._scientific_pixel_format = "UNKNOWN"
        self._scientific_channels = 0
        self._scientific_pull_bits = 0
        self._raw_value_alignment = "unknown"
        self._scientific_format_negotiation = "Unconfigured"
        self._rgb_option_4_supported: bool | None = None
        self._linear_option_supported: bool | None = None
        self._curve_option_supported: bool | None = None
        self._gamma_supported: bool | None = None
        self._scientific_isp_bypassed = False
        self._scientific_frame_validated = False
        self._scientific_pull_error_reported = False
        self._bitdepth_readback: int | None = None
        self._rgb_option_readback: int | None = None
        self._byteorder_readback: int | None = None
        self._linear_readback: int | None = None
        self._curve_readback: int | None = None
        self._gamma_readback: int | None = None

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
            camera = self._apply_camera_startup_setting(
                "Nncam.Open", lambda: nncam.Nncam.Open(device.id)
            )
            if not camera:
                raise CameraStartupError(
                    "Nncam.Open", RuntimeError("SDK 未回傳有效的相機控制代碼")
                )

            self._camera = camera
            self._device = device
            resolution_index = self._apply_camera_startup_setting(
                "get_eSize", camera.get_eSize
            )
            resolution = device.model.res[resolution_index]
            self._width, self._height = resolution.width, resolution.height
            self._camera_is_mono = bool(device.model.flag & nncam.NNCAM_FLAG_MONO)
            if not self._camera_is_mono:
                raise CameraStartupError(
                    "MONO capability check",
                    RuntimeError(
                        "Formal scientific capture currently supports monochrome cameras only"
                    ),
                )

            # MONO16 startup is deliberately classified by data-integrity impact.
            # BYTEORDER is RGB/BGR channel ordering and is diagnostic-only for a
            # single-channel frame; do not write it or gate connection/readiness.
            self._byteorder_readback = self._read_nonblocking_setting(
                "NNCAM_OPTION_BYTEORDER diagnostic (IgnoredForMono=True)",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_BYTEORDER),
            )

            # BITDEPTH is the one required SDK option for this scientific path.
            self._bitdepth_readback = self._configure_mono16_bitdepth(camera)

            # Tone controls are requested neutral but remain non-blocking. The
            # final authority for this compatibility baseline is the actual
            # uint16 HxW frame pulled below, not universal option echo behavior.
            self._linear_option_supported, self._linear_readback = (
                self._configure_nonblocking_option(
                    camera,
                    "NNCAM_OPTION_LINEAR",
                    nncam.NNCAM_OPTION_LINEAR,
                    0,
                )
            )
            self._curve_option_supported, self._curve_readback = (
                self._configure_nonblocking_option(
                    camera,
                    "NNCAM_OPTION_CURVE",
                    nncam.NNCAM_OPTION_CURVE,
                    0,
                )
            )
            self._gamma_supported, self._gamma_readback = (
                self._configure_nonblocking_gamma(camera, 100)
            )

            # RGB=4 is preferred Grey16, but any put/readback failure or a
            # non-4 echo negotiates to explicit PullImageV4(bits=16).
            (
                self._rgb_option_4_supported,
                self._rgb_option_readback,
                self._scientific_format_negotiation,
            ) = self._negotiate_mono16_rgb_option(camera)

            self._scientific_pixel_format = "MONO16"
            self._scientific_channels = 1
            self._scientific_pull_bits = 16
            self._sensor_bit_depth, self._bit_depth_source = self._read_sensor_bit_depth(
                camera, device.model.flag
            )
            # The bundled wrapper documents the uint16 container but does not
            # guarantee whether effective DN bits are right- or left-aligned.
            self._raw_value_alignment = "unknown"
            raw_mode = self._read_nonblocking_setting(
                "NNCAM_OPTION_RAW diagnostic",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_RAW),
            )
            isp_mode = self._read_nonblocking_setting(
                "NNCAM_OPTION_ISP diagnostic",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_ISP),
            )
            self._scientific_isp_bypassed = raw_mode == 1 or isp_mode == -1
            self._apply_camera_startup_setting(
                "put_AutoExpoEnable(1)", lambda: camera.put_AutoExpoEnable(1)
            )
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
                "mono": self._camera_is_mono,
                "temperature_supported": bool(
                    device.model.flag & nncam.NNCAM_FLAG_GETTEMPERATURE
                ),
                "sdk_version": self.sdk_version(),
                "max_bit_depth": (
                    self._sensor_bit_depth
                    if self._bit_depth_source == "MaxBitDepth" else None
                ),
                "scientific_bit_depth": self._sensor_bit_depth,
                "scientific_container": "uint16",
                "scientific_pixel_format": self._scientific_pixel_format,
                "scientific_channels": self._scientific_channels,
                "bit_depth_source": self._bit_depth_source,
                "raw_value_alignment": self._raw_value_alignment,
                "scientific_format_negotiation": self._scientific_format_negotiation,
                "rgb_option_4_supported": self._rgb_option_4_supported,
                "linear_option_supported": self._linear_option_supported,
                "curve_option_supported": self._curve_option_supported,
                "gamma_supported": self._gamma_supported,
                "scientific_isp_bypassed": self._scientific_isp_bypassed,
                "camera_flags": int(device.model.flag),
                "raw10": bool(device.model.flag & nncam.NNCAM_FLAG_RAW10),
                "raw11": bool(
                    device.model.flag & getattr(nncam, "NNCAM_FLAG_RAW11", 0)
                ),
                "raw12": bool(device.model.flag & nncam.NNCAM_FLAG_RAW12),
                "raw14": bool(device.model.flag & nncam.NNCAM_FLAG_RAW14),
                "raw16": bool(device.model.flag & nncam.NNCAM_FLAG_RAW16),
                "raw_mode": raw_mode,
                "isp_mode": isp_mode,
                "pull_bits": self._scientific_pull_bits,
                "start_pull_mode_status": "OK",
                "bitdepth_readback": self._bitdepth_readback,
                "rgb_option_readback": self._rgb_option_readback,
                "byteorder_readback": self._byteorder_readback,
                "byteorder_ignored_for_mono": True,
                "linear_readback": self._linear_readback,
                "curve_readback": self._curve_readback,
                "gamma_readback": self._gamma_readback,
                "scientific_frame_validated": self._scientific_frame_validated,
                "scientific_measurement_ready": self._scientific_measurement_ready(),
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
        self._sensor_bit_depth = None
        self._bit_depth_source = "Unknown"
        self._camera_is_mono = False
        self._scientific_pixel_format = "UNKNOWN"
        self._scientific_channels = 0
        self._scientific_pull_bits = 0
        self._raw_value_alignment = "unknown"
        self._scientific_format_negotiation = "Unconfigured"
        self._rgb_option_4_supported = None
        self._linear_option_supported = None
        self._curve_option_supported = None
        self._gamma_supported = None
        self._scientific_isp_bypassed = False
        self._scientific_frame_validated = False
        self._scientific_pull_error_reported = False
        self._bitdepth_readback = None
        self._rgb_option_readback = None
        self._byteorder_readback = None
        self._linear_readback = None
        self._curve_readback = None
        self._gamma_readback = None
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
            "ResolutionId": f"sdk:{self._camera.get_eSize()}" if self._camera else "",
            "ImageWidth": self._width,
            "ImageHeight": self._height,
            "PixelFormat": self._scientific_pixel_format,
            "BitDepth": 16,
            "SensorBitDepth": self._sensor_bit_depth,
            "BitDepthSource": self._bit_depth_source,
            "MaxBitDepthReadback": (
                self._sensor_bit_depth
                if self._bit_depth_source == "MaxBitDepth" else None
            ),
            "ContainerBitDepth": 16,
            "ContainerDtype": "uint16",
            "Channels": self._scientific_channels,
            "RawValueAlignment": self._raw_value_alignment,
            "ScientificGammaApplied": False,
            "ScientificToneMappingApplied": False,
            "ScientificPixelFormat": self._scientific_pixel_format,
            "ScientificFormatNegotiation": self._scientific_format_negotiation,
            "RGBOption4Supported": self._rgb_option_4_supported,
            "LINEAROptionSupported": self._linear_option_supported,
            "CURVEOptionSupported": self._curve_option_supported,
            "GammaOptionSupported": self._gamma_supported,
            "ScientificISPBypassed": self._scientific_isp_bypassed,
            "ScientificFrameValidated": self._scientific_frame_validated,
            "ScientificMeasurementReady": self._scientific_measurement_ready(),
            "CameraConnected": self.is_open,
            "BITDEPTHRequested": 1,
            "BITDEPTHReadback": self._bitdepth_readback,
            "RGBOptionRequested": 4,
            "RGBOptionReadback": self._rgb_option_readback,
            "ByteOrderReadback": self._byteorder_readback,
            "ByteOrderIgnoredForMono": True,
            "LINEARReadback": self._linear_readback,
            "CURVEReadback": self._curve_readback,
            "GammaReadback": self._gamma_readback,
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
            "Camera Model: %s\n"
            "Camera Serial: %s\n"
            "Camera flags: 0x%X\n"
            "Mono: %s\n"
            "RAW10/11/12/14/16 flags: %s/%s/%s/%s/%s\n"
            "Resolution: %sx%s\n"
            "SDK version: %s\n"
            "MaxBitDepth: %s\n"
            "Sensor bit depth: %s\n"
            "BitDepthSource: %s\n"
            "ScientificPixelFormat: %s\n"
            "ScientificFormatNegotiation: %s\n"
            "BITDEPTH requested/readback: 1/%s\n"
            "RGB requested/readback/fallback: 4/%s/%s\n"
            "RGB option 4 supported: %s\n"
            "BYTEORDER diagnostic: readback=%s, IgnoredForMono=True\n"
            "LINEAR/CURVE/Gamma requested: 0/0/100\n"
            "LINEAR/CURVE/Gamma readback: %s/%s/%s\n"
            "ScientificISPBypassed: %s\n"
            "RAW mode: %s\n"
            "ISP mode: %s\n"
            "Pull bits: %s\n"
            "StartPullMode status: %s\n"
            "ScientificContainer: %s\n"
            "ScientificChannels: %s\n"
            "ContainerBitDepth: 16\n"
            "ScientificFrameValidated: %s\n"
            "ScientificMeasurementReady: %s\n"
            "RawValueAlignment: %s\n"
            "Camera Exposure Hardware Range: min = %s us, max = %s us, default = %s us\n"
            "Camera Gain Hardware Range: min = %s %%, max = %s %%, default = %s %%\n"
            "Auto Exposure Range: min exposure = %s us, max exposure = %s us, "
            "min gain = %s %%, max gain = %s %%\n"
            "Auto Exposure Target: %s /255",
            info.get("model") or info.get("name") or "--",
            info.get("identifier", "--"),
            info.get("camera_flags", 0),
            info.get("mono", "--"),
            info.get("raw10", False),
            info.get("raw11", False),
            info.get("raw12", False),
            info.get("raw14", False),
            info.get("raw16", False),
            *(
                info.get("resolutions", [("--", "--")])[info.get("resolution_index", 0)]
                if info.get("resolutions")
                else ("--", "--")
            ),
            info.get("sdk_version", "--"),
            info.get("max_bit_depth") if info.get("max_bit_depth") is not None else "--",
            info.get("scientific_bit_depth", "--"),
            info.get("bit_depth_source", "--"),
            info.get("scientific_pixel_format", "--"),
            info.get("scientific_format_negotiation", "--"),
            info.get("bitdepth_readback", "unsupported"),
            (
                info.get("rgb_option_readback")
                if info.get("rgb_option_readback") is not None else "unsupported"
            ),
            (
                "None"
                if info.get("scientific_format_negotiation") == "RGBOption4"
                else "PullImageV4(bits=16)"
            ),
            info.get("rgb_option_4_supported", "--"),
            (
                info.get("byteorder_readback")
                if info.get("byteorder_readback") is not None else "unsupported"
            ),
            info.get("linear_readback") if info.get("linear_readback") is not None else "unsupported",
            info.get("curve_readback") if info.get("curve_readback") is not None else "unsupported",
            info.get("gamma_readback") if info.get("gamma_readback") is not None else "unsupported",
            info.get("scientific_isp_bypassed", "--"),
            info.get("raw_mode") if info.get("raw_mode") is not None else "unsupported",
            info.get("isp_mode") if info.get("isp_mode") is not None else "unsupported",
            info.get("pull_bits", "--"),
            info.get("start_pull_mode_status", "--"),
            info.get("scientific_container", "--"),
            info.get("scientific_channels", "--"),
            info.get("scientific_frame_validated", False),
            info.get("scientific_measurement_ready", False),
            info.get("raw_value_alignment", "--"),
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

    @staticmethod
    def _native_sensor_bit_depth(flags: int) -> int | None:
        for flag, bits in (
            (nncam.NNCAM_FLAG_RAW16, 16),
            (nncam.NNCAM_FLAG_RAW14, 14),
            (nncam.NNCAM_FLAG_RAW12, 12),
            (getattr(nncam, "NNCAM_FLAG_RAW11", 0), 11),
            (nncam.NNCAM_FLAG_RAW10, 10),
        ):
            if flag and flags & flag:
                return bits
        return None

    @classmethod
    def _read_sensor_bit_depth(
        cls, camera: Any, flags: int
    ) -> tuple[int | None, str]:
        try:
            bit_depth = int(camera.MaxBitDepth())
            if not 1 <= bit_depth <= 16:
                raise ValueError(f"unexpected MaxBitDepth value: {bit_depth}")
            LOG.info("Camera startup OK: MaxBitDepth() -> %s", bit_depth)
            return bit_depth, "MaxBitDepth"
        except Exception as exc:
            fallback = cls._native_sensor_bit_depth(flags)
            if fallback is not None:
                LOG.warning(
                    "RisingCam MaxBitDepth() failed (%s); using capability-flag "
                    "fallback: %s bits",
                    exc,
                    fallback,
                )
                return fallback, "CapabilityFlagFallback"
            LOG.warning(
                "RisingCam MaxBitDepth() failed (%s) and no RAW10/11/12/14/16 "
                "capability flag is available; SensorBitDepth=Unknown",
                exc,
            )
            return None, "Unknown"

    @staticmethod
    def _apply_camera_startup_setting(
        name: str, operation: Callable[[], _T]
    ) -> _T:
        try:
            result = operation()
            if result is None:
                LOG.info("Camera startup OK: %s", name)
            else:
                LOG.info("Camera startup OK: %s -> %r", name, result)
            return result
        except Exception as exc:
            LOG.exception("Camera startup FAILED at %s: %s", name, exc)
            raise CameraStartupError(name, exc) from exc

    @classmethod
    def _configure_mono16_bitdepth(cls, camera: Any) -> int:
        """Apply the one required option and verify its scientific mode echo."""

        cls._apply_camera_startup_setting(
            "NNCAM_OPTION_BITDEPTH=1",
            lambda: camera.put_Option(nncam.NNCAM_OPTION_BITDEPTH, 1),
        )
        readback = int(
            cls._apply_camera_startup_setting(
                "NNCAM_OPTION_BITDEPTH readback",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_BITDEPTH),
            )
        )
        if readback != 1:
            mismatch = RuntimeError(f"requested 1, read back {readback}")
            LOG.error(
                "Camera startup FAILED at NNCAM_OPTION_BITDEPTH readback: %s",
                mismatch,
            )
            raise CameraStartupError("NNCAM_OPTION_BITDEPTH readback", mismatch)
        return readback

    @classmethod
    def _negotiate_mono16_rgb_option(
        cls, camera: Any
    ) -> tuple[bool, int | None, str]:
        """Prefer RGB option 4, but always permit explicit 16-bit pull fallback."""

        try:
            cls._apply_camera_startup_setting(
                "NNCAM_OPTION_RGB=4",
                lambda: camera.put_Option(nncam.NNCAM_OPTION_RGB, 4),
            )
        except CameraStartupError as exc:
            LOG.warning(
                "RGB=4 negotiation failed at %s; using PullImageV4(bits=16): %s",
                exc.stage,
                exc.original,
            )
            readback = cls._read_nonblocking_setting(
                "NNCAM_OPTION_RGB diagnostic after put failure",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_RGB),
            )
            return False, readback, "PullBits16Fallback"

        readback = cls._read_nonblocking_setting(
            "NNCAM_OPTION_RGB readback",
            lambda: camera.get_Option(nncam.NNCAM_OPTION_RGB),
        )
        if readback != 4:
            LOG.warning(
                "RGB=4 negotiation readback mismatch (requested=4, readback=%r); "
                "using PullImageV4(bits=16)",
                readback,
            )
            return False, readback, "PullBits16Fallback"
        return True, readback, "RGBOption4"

    @classmethod
    def _configure_nonblocking_option(
        cls,
        camera: Any,
        label: str,
        option: int,
        value: int,
    ) -> tuple[bool, int | None]:
        """Request a neutral ISP setting without gating MONO camera startup."""

        try:
            cls._apply_camera_startup_setting(
                f"{label}={value}", lambda: camera.put_Option(option, value)
            )
        except CameraStartupError as exc:
            LOG.warning(
                "Camera startup NON-BLOCKING setting failed at %s: %s",
                exc.stage,
                exc.original,
            )
            return False, cls._read_nonblocking_setting(
                f"{label} diagnostic after put failure",
                lambda: camera.get_Option(option),
            )
        readback = cls._read_nonblocking_setting(
            f"{label} readback", lambda: camera.get_Option(option)
        )
        if readback != value:
            LOG.warning(
                "Camera startup NON-BLOCKING readback mismatch at %s: "
                "requested=%s, readback=%r",
                label,
                value,
                readback,
            )
            return False, readback
        return True, readback

    @classmethod
    def _configure_nonblocking_gamma(
        cls, camera: Any, value: int
    ) -> tuple[bool, int | None]:
        try:
            cls._apply_camera_startup_setting(
                f"Gamma={value}", lambda: camera.put_Gamma(value)
            )
        except CameraStartupError as exc:
            LOG.warning(
                "Camera startup NON-BLOCKING setting failed at %s: %s",
                exc.stage,
                exc.original,
            )
            return False, cls._read_nonblocking_setting(
                "Gamma diagnostic after put failure", camera.get_Gamma
            )
        readback = cls._read_nonblocking_setting("Gamma readback", camera.get_Gamma)
        if readback != value:
            LOG.warning(
                "Camera startup NON-BLOCKING readback mismatch at Gamma: "
                "requested=%s, readback=%r",
                value,
                readback,
            )
            return False, readback
        return True, readback

    @staticmethod
    def _read_nonblocking_setting(
        name: str, operation: Callable[[], Any]
    ) -> int | None:
        try:
            value = int(operation())
            LOG.info("Camera startup diagnostic: %s -> %s", name, value)
            return value
        except Exception as exc:
            LOG.warning("Camera startup diagnostic unavailable at %s: %s", name, exc)
            return None

    def _scientific_measurement_ready(self) -> bool:
        return bool(
            self._camera is not None
            and self._camera_is_mono
            and self._scientific_pull_bits == 16
            and self._scientific_frame_validated
        )

    def _start_stream(self) -> None:
        if self._camera is None:
            return
        if self._scientific_pull_bits != 16 or not self._camera_is_mono:
            raise CameraStartupError(
                "Scientific format validation",
                RuntimeError("Scientific camera format was not configured"),
            )
        self._scientific_frame_validated = False
        self._scientific_pull_error_reported = False
        self._pitch = nncam.TDIBWIDTHBYTES(self._width * self._scientific_pull_bits)
        self._buffer = bytes(self._pitch * self._height)
        self._apply_camera_startup_setting(
            "StartPullModeWithCallback",
            lambda: self._camera.StartPullModeWithCallback(
                self._camera_callback, self
            ),
        )
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
            expected_pitch = nncam.TDIBWIDTHBYTES(
                self._width * self._scientific_pull_bits
            )
            expected_buffer_size = expected_pitch * self._height
            if self._pitch != expected_pitch or len(self._buffer) != expected_buffer_size:
                raise CameraStartupError(
                    "MONO16 buffer validation",
                    RuntimeError(
                        f"expected pitch={expected_pitch}, buffer={expected_buffer_size}; "
                        f"got pitch={self._pitch}, buffer={len(self._buffer)}"
                    ),
                )
            try:
                self._camera.PullImageV4(
                    self._buffer, 0, self._scientific_pull_bits, 0, None
                )
            except Exception as exc:
                raise CameraStartupError("PullImageV4(bits=16)", exc) from exc
            row_words = self._pitch // 2
            rows = np.frombuffer(self._buffer, dtype="<u2").reshape(
                self._height, row_words
            )
            scientific = rows[:, : self._width].copy()
            if (
                scientific.dtype != np.uint16
                or scientific.ndim != 2
                or scientific.shape != (self._height, self._width)
            ):
                raise CameraStartupError(
                    "PullImageV4(bits=16) output validation",
                    RuntimeError(
                        "scientific frame must be a uint16 HxW single-channel array; "
                        f"got dtype={scientific.dtype}, shape={scientific.shape}"
                    ),
                )
            first_valid_frame = not self._scientific_frame_validated
            self._scientific_frame_validated = True
            self._scientific_pull_error_reported = False
            if first_valid_frame:
                LOG.info(
                    "Camera scientific frame validation:\n"
                    "PullBits=16\n"
                    "PixelFormat=%s\n"
                    "ContainerBitDepth=16\n"
                    "Scientific frame dtype=%s\n"
                    "Scientific frame ndim=%s\n"
                    "Scientific frame shape=%s\n"
                    "Pitch=%s\n"
                    "BufferSize=%s\n"
                    "ScientificFormatNegotiation=%s\n"
                    "ScientificFrameValidated=True\n"
                    "ScientificMeasurementReady=%s",
                    self._scientific_pixel_format,
                    scientific.dtype,
                    scientific.ndim,
                    scientific.shape,
                    self._pitch,
                    len(self._buffer),
                    self._scientific_format_negotiation,
                    self._scientific_measurement_ready(),
                )
            if (
                self._raw_value_alignment == "right"
                and self._sensor_bit_depth is not None
            ):
                display_source = scientific.astype(np.float64)
                maximum_dn = float((1 << self._sensor_bit_depth) - 1)
            elif (
                self._raw_value_alignment == "left"
                and self._sensor_bit_depth is not None
            ):
                shift = 16 - self._sensor_bit_depth
                display_source = np.right_shift(scientific, shift).astype(np.float64)
                maximum_dn = float((1 << self._sensor_bit_depth) - 1)
            else:
                # Unknown means unknown: use the full container range rather than
                # inferring alignment/bit depth from this frame's brightness.
                display_source = scientific.astype(np.float64)
                maximum_dn = 65535.0
            display = np.clip(
                np.rint(display_source * (255.0 / maximum_dn)),
                0,
                255,
            ).astype(np.uint8)
            image = QImage(
                display.data,
                self._width,
                self._height,
                self._width,
                QImage.Format.Format_Grayscale8,
            ).copy()
            self._latest_image = image
            self._frame_sequence += 1
            self.frame_ready.emit(image)
            self.frame_ready_sequenced.emit(image, self._frame_sequence)
            self.scientific_frame_ready.emit(scientific, image, self._frame_sequence)
        except Exception as exc:
            self._scientific_frame_validated = False
            if not self._scientific_pull_error_reported:
                self._scientific_pull_error_reported = True
                LOG.exception("Camera scientific frame validation failed: %s", exc)
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
        stage = getattr(exc, "stage", None)
        if stage is not None:
            if hr is not None:
                return (
                    f"{prefix}\nStage: {stage}\n"
                    f"SDK HRESULT: 0x{hr & 0xFFFFFFFF:08X}"
                )
            return f"{prefix}\nStage: {stage}\nError: {exc}"
        if hr is not None:
            return f"{prefix}（SDK HRESULT 0x{hr & 0xFFFFFFFF:08X}）"
        return f"{prefix}：{exc}"
