from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any, TypeVar

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from core.i18n import tr

from .camera_auto_exposure_settings import (
    DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT,
    default_sdk_target_guess,
    target_effective_dn,
    validate_auto_exposure_target_percent,
)
from .camera_ae_calibration import (
    AECalibrationIdentity,
    AECalibrationPoint,
    AECalibrationProfile,
    AECalibrationProfileStore,
    AECalibrationRun,
    CALIBRATION_POINT_TIMEOUT_SECONDS,
    calibration_candidates,
)
from .camera_temperature_monitor import CameraTemperatureUnsupportedError
from .scientific_dn import (
    effective_dn_fraction,
    effective_dn_max,
    effective_dn_to_uint8,
    mean_effective_dn,
    mean_effective_dn_roi,
)
from .scientific_dn_alignment import (
    AlignmentVerificationState,
    AlignmentVerifier,
)
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


class SDKAutoExposureMode(str, Enum):
    MANUAL = "Manual"
    CONTINUOUS = "Continuous"
    ONCE = "Once"


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
    effective_dn_status_changed = Signal(object)
    auto_exposure_result = Signal(bool, str)
    ae_calibration_progress = Signal(object)
    ae_calibration_finished = Signal(bool, str)
    ae_calibration_profile_changed = Signal(object)
    fps_changed = Signal(float, int)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    _sdk_event = Signal(int)

    def __init__(
        self,
        parent: QObject | None = None,
        auto_exposure_target_percent: int = DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT,
        ae_calibration_store_path: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._camera: Any | None = None
        self._device: Any | None = None
        self._buffer: bytes | None = None
        self._width = 0
        self._height = 0
        self._pitch = 0
        self._auto_exposure_target_percent = validate_auto_exposure_target_percent(
            auto_exposure_target_percent
        )
        self._sdk_auto_exposure_mode = SDKAutoExposureMode.MANUAL
        self._sdk_auto_exposure_enable_readback: int | None = None
        self._sdk_auto_exposure_target = default_sdk_target_guess(
            self._auto_exposure_target_percent
        )
        self._sdk_auto_exposure_target_readback: int | None = None
        self._sdk_auto_exposure_policy_readback: int | None = None
        self._sdk_auto_exposure_percent_readback: int | None = None
        self._sdk_auto_exposure_exposure_damping_readback: int | None = None
        self._sdk_auto_exposure_gain_damping_readback: int | None = None
        self._sdk_overexposure_policy_readback: int | None = None
        self._auto_exposure_range: tuple[int, int, int, int] | None = None
        self._last_sdk_ae_calibration_log_monotonic = 0.0
        self._ae_calibration_store = AECalibrationProfileStore(
            ae_calibration_store_path
        )
        self._ae_calibration_profile: AECalibrationProfile | None = None
        self._ae_calibration_run: AECalibrationRun | None = None
        self._ae_calibration_previous_mode = SDKAutoExposureMode.MANUAL
        self._exposure_range: tuple[int, int, int] | None = None
        self._gain_range: tuple[int, int, int] | None = None
        self._latest_mean_effective_dn: float | None = None
        self._latest_effective_dn_fraction: float | None = None
        self._latest_metering_mean_effective_dn: float | None = None
        self._latest_metering_effective_dn_fraction: float | None = None
        self._effective_dn_max: int | None = None
        self._auto_exposure_roi_requested: tuple[int, int, int, int] | None = None
        self._auto_exposure_roi_readback: tuple[int, int, int, int] | None = None
        self._auto_exposure_roi_mode = "Unavailable"
        self._auto_exposure_roi_verified = False
        self._auto_exposure_roi_verification_status = "Disconnected"
        self._auto_exposure_roi_error = ""
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
        self._raw_value_alignment_source = "Unknown"
        self._alignment_verifier: AlignmentVerifier | None = None
        self._alignment_warning_emitted = False
        self._continuous_auto_exposure_requested = True
        self._pixel_format_readback: int | None = None
        self._pixel_format_name = "Unknown"
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
        self._ae_calibration_timer = QTimer(self)
        self._ae_calibration_timer.setSingleShot(True)
        self._ae_calibration_timer.setInterval(
            round(CALIBRATION_POINT_TIMEOUT_SECONDS * 1000)
        )
        self._ae_calibration_timer.timeout.connect(self._on_ae_calibration_timeout)

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
    def auto_exposure_roi(self) -> tuple[int, int, int, int] | None:
        """Return the requested image-pixel AE metering rectangle."""

        return self._auto_exposure_roi_requested

    @property
    def auto_exposure_roi_readback(self) -> tuple[int, int, int, int] | None:
        """Return the SDK readback rectangle, if readback succeeded."""

        return self._auto_exposure_roi_readback

    @property
    def auto_exposure_roi_verified(self) -> bool:
        return self._auto_exposure_roi_verified

    def auto_exposure_roi_status(self) -> dict[str, Any]:
        return {
            "requested": self._auto_exposure_roi_requested,
            "readback": self._auto_exposure_roi_readback,
            "mode": self._auto_exposure_roi_mode,
            "verified": self._auto_exposure_roi_verified,
            "verification_status": self._auto_exposure_roi_verification_status,
            "error": self._auto_exposure_roi_error,
        }

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
            self.error_occurred.emit(self._format_error(tr("camera.error_sdk_enumeration"), exc))
            return []

    def open_device(self, device: Any) -> None:
        self.close_camera()
        try:
            camera = self._apply_camera_startup_setting(
                "Nncam.Open", lambda: nncam.Nncam.Open(device.id)
            )
            if not camera:
                raise CameraStartupError(
                    "Nncam.Open", RuntimeError(tr("camera.error_invalid_handle"))
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
            self._pixel_format_readback = self._read_nonblocking_setting(
                "NNCAM_OPTION_PIXEL_FORMAT diagnostic",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_PIXEL_FORMAT),
            )
            self._pixel_format_name = self._pixel_format_label(
                self._pixel_format_readback
            )
            (
                self._raw_value_alignment,
                self._raw_value_alignment_source,
            ) = self._determine_raw_value_alignment(
                self._sensor_bit_depth,
                16,
                self._pixel_format_readback,
            )
            self._alignment_verifier = None
            if (
                self._sensor_bit_depth is not None
                and self._sensor_bit_depth < 16
            ):
                self._alignment_verifier = AlignmentVerifier(
                    self._sensor_bit_depth,
                    16,
                )
            raw_mode = self._read_nonblocking_setting(
                "NNCAM_OPTION_RAW diagnostic",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_RAW),
            )
            isp_mode = self._read_nonblocking_setting(
                "NNCAM_OPTION_ISP diagnostic",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_ISP),
            )
            self._scientific_isp_bypassed = raw_mode == 1 or isp_mode == -1
            capabilities = self._query_camera_capabilities(camera)
            self._exposure_range = capabilities.get("exposure_range_us")
            self._gain_range = capabilities.get("gain_range")
            self._auto_exposure_range = capabilities.get("auto_exposure_range")
            # The SDK can retain an old/native-default metering rectangle.
            # Force an explicit full-current-image rectangle and verify it
            # before any Continuous AE is enabled.
            self._disable_sdk_auto_exposure(require_readback=True)
            ae_roi_ready = self._apply_auto_exposure_roi(
                (0, 0, self._width, self._height),
                reason="AE_ROI_RESET_FULL_IMAGE",
                refresh_profile=False,
                emit_status=False,
            )
            self._refresh_ae_calibration_profile()
            self._configure_sdk_auto_exposure_parameters(camera)
            if self._continuous_auto_exposure_requested and ae_roi_ready:
                self._enable_sdk_auto_exposure(SDKAutoExposureMode.CONTINUOUS)
            else:
                self._disable_sdk_auto_exposure(require_readback=True)
            self._start_stream()

            current = self._read_current_exposure(camera)
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
                "auto_exposure_mode": self._sdk_auto_exposure_mode.value,
                "continuous_auto_exposure_requested": (
                    self._continuous_auto_exposure_requested
                ),
                "auto_exposure_target_percent": self._auto_exposure_target_percent,
                "sdk_auto_exposure_available": True,
                "auto_exposure_roi_requested": self._auto_exposure_roi_requested,
                "auto_exposure_roi_readback": self._auto_exposure_roi_readback,
                "auto_exposure_roi_mode": self._auto_exposure_roi_mode,
                "auto_exposure_roi_verified": self._auto_exposure_roi_verified,
                "auto_exposure_roi_verification_status": (
                    self._auto_exposure_roi_verification_status
                ),
                "auto_exposure_roi_error": self._auto_exposure_roi_error,
                "sdk_auto_exposure_target": self._sdk_auto_exposure_target,
                "sdk_auto_exposure_target_readback": (
                    self._sdk_auto_exposure_target_readback
                ),
                "auto_exposure_calibration_applied": (
                    self._ae_calibration_profile is not None
                ),
                "auto_exposure_calibration_profile_id": (
                    self._ae_calibration_profile.profile_id
                    if self._ae_calibration_profile is not None
                    else None
                ),
                "sdk_auto_exposure_policy": (
                    self._sdk_auto_exposure_policy_readback
                ),
                "sdk_auto_exposure_percent": (
                    self._sdk_auto_exposure_percent_readback
                ),
                "sdk_auto_exposure_exposure_damping": (
                    self._sdk_auto_exposure_exposure_damping_readback
                ),
                "sdk_auto_exposure_gain_damping": (
                    self._sdk_auto_exposure_gain_damping_readback
                ),
                "sdk_overexposure_policy": (
                    self._sdk_overexposure_policy_readback
                ),
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
                "effective_dn_max": (
                    effective_dn_max(self._sensor_bit_depth)
                    if self._sensor_bit_depth is not None
                    else None
                ),
                "scientific_container": "uint16",
                "scientific_pixel_format": self._scientific_pixel_format,
                "scientific_channels": self._scientific_channels,
                "bit_depth_source": self._bit_depth_source,
                "raw_value_alignment": self._raw_value_alignment,
                "raw_value_alignment_source": self._raw_value_alignment_source,
                "pixel_format_readback": self._pixel_format_readback,
                "pixel_format_name": self._pixel_format_name,
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
            if not self._auto_exposure_roi_verified:
                self.status_changed.emit(
                    tr("camera.status_connected_ae_roi_failed")
                )
            elif self._alignment_verifier is not None:
                self.status_changed.emit(tr("camera.status_confirming_alignment"))
            else:
                self.status_changed.emit(tr("camera.status_connected", device=device.displayname))
        except Exception as exc:
            self.close_camera()
            self.error_occurred.emit(self._format_error(tr("camera.error_open"), exc))

    def close_camera(self) -> None:
        was_open = self._camera is not None
        calibration_was_running = self._ae_calibration_run is not None
        self._ae_calibration_timer.stop()
        if calibration_was_running and self._camera is not None:
            try:
                self._disable_sdk_auto_exposure(require_readback=False)
            except Exception:
                LOG.exception("Failed to disable SDK AE while closing calibration")
        self._ae_calibration_run = None
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
        self._sdk_auto_exposure_mode = SDKAutoExposureMode.MANUAL
        self._sdk_auto_exposure_enable_readback = None
        self._sdk_auto_exposure_target_readback = None
        self._sdk_auto_exposure_policy_readback = None
        self._sdk_auto_exposure_percent_readback = None
        self._sdk_auto_exposure_exposure_damping_readback = None
        self._sdk_auto_exposure_gain_damping_readback = None
        self._sdk_overexposure_policy_readback = None
        self._auto_exposure_range = None
        self._last_sdk_ae_calibration_log_monotonic = 0.0
        self._ae_calibration_profile = None
        self._exposure_range = None
        self._gain_range = None
        self._latest_mean_effective_dn = None
        self._latest_effective_dn_fraction = None
        self._latest_metering_mean_effective_dn = None
        self._latest_metering_effective_dn_fraction = None
        self._effective_dn_max = None
        self._auto_exposure_roi_requested = None
        self._auto_exposure_roi_readback = None
        self._auto_exposure_roi_mode = "Unavailable"
        self._auto_exposure_roi_verified = False
        self._auto_exposure_roi_verification_status = "Disconnected"
        self._auto_exposure_roi_error = ""
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
        self._raw_value_alignment_source = "Unknown"
        self._alignment_verifier = None
        self._alignment_warning_emitted = False
        self._pixel_format_readback = None
        self._pixel_format_name = "Unknown"
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
            self.status_changed.emit(tr("camera.status_disconnected"))
        if calibration_was_running:
            self.ae_calibration_finished.emit(False, tr("camera.calibration_cancelled_disconnect"))

    def set_resolution(self, index: int) -> None:
        if self._camera is None or self._device is None:
            return
        if index < 0 or index >= self._device.model.preview:
            return

        try:
            previous_mode = self._sdk_auto_exposure_mode
            self._disable_sdk_auto_exposure(require_readback=True)
            self._camera.Stop()
            self._camera.put_eSize(index)
            resolution = self._device.model.res[index]
            self._width, self._height = resolution.width, resolution.height
            self._latest_mean_effective_dn = None
            self._latest_effective_dn_fraction = None
            self._latest_metering_mean_effective_dn = None
            self._latest_metering_effective_dn_fraction = None
            ae_roi_ready = self._apply_auto_exposure_roi(
                (0, 0, self._width, self._height),
                reason="AE_ROI_RESET_RESOLUTION_CHANGE",
                refresh_profile=False,
                emit_status=False,
            )
            self._refresh_ae_calibration_profile()
            if previous_mode is not SDKAutoExposureMode.MANUAL and ae_roi_ready:
                self._configure_sdk_auto_exposure_parameters(self._camera)
                self._enable_sdk_auto_exposure(previous_mode)
            self._start_stream()
            self._emit_effective_dn_status()
            if not ae_roi_ready:
                self.error_occurred.emit(
                    tr("camera.error_resolution_ae_roi")
                )
            self.status_changed.emit(tr("camera.status_resolution", width=self._width, height=self._height))
        except Exception as exc:
            self.error_occurred.emit(self._format_error(tr("camera.error_resolution"), exc))

    def set_auto_exposure_roi(
        self, x: int, y: int, width: int, height: int
    ) -> bool:
        """Set and verify the SDK AE metering ROI in image-pixel coordinates."""

        if self._ae_calibration_run is not None:
            self._abort_ae_calibration(tr("camera.calibration_cancelled_roi_changed"))
        verified = self._apply_auto_exposure_roi(
            (x, y, width, height),
            reason="AE_ROI_SET",
        )
        if not verified:
            self.error_occurred.emit(
                tr("camera.error_ae_roi", detail=self._auto_exposure_roi_error)
            )
        return verified

    def reset_auto_exposure_roi(
        self, *, reason: str = "AE_ROI_RESET_FULL_IMAGE"
    ) -> bool:
        """Set and verify an explicit full-current-image SDK AE rectangle."""

        if self._width <= 0 or self._height <= 0:
            self._set_auto_exposure_roi_failure(
                None,
                "InvalidImageSize",
                reason,
                "current image dimensions are unavailable",
            )
            return False
        if self._ae_calibration_run is not None:
            self._abort_ae_calibration(tr("camera.calibration_cancelled_roi_reset"))
        verified = self._apply_auto_exposure_roi(
            (0, 0, self._width, self._height),
            reason=reason,
        )
        if not verified:
            self.error_occurred.emit(
                tr("camera.error_ae_full_roi", detail=self._auto_exposure_roi_error)
            )
        return verified

    def _validate_auto_exposure_roi(
        self, roi: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        if any(isinstance(value, bool) or not isinstance(value, int) for value in roi):
            raise ValueError("AE ROI coordinates and dimensions must be integers")
        x, y, width, height = roi
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("AE ROI requires x/y >= 0 and width/height > 0")
        if x + width > self._width or y + height > self._height:
            raise ValueError(
                f"AE ROI {roi} exceeds current image {self._width}x{self._height}"
            )
        return roi

    def _apply_auto_exposure_roi(
        self,
        roi: tuple[int, int, int, int],
        *,
        reason: str,
        refresh_profile: bool = True,
        emit_status: bool = True,
    ) -> bool:
        requested: tuple[int, int, int, int] | None = None
        try:
            requested = self._validate_auto_exposure_roi(roi)
        except (TypeError, ValueError) as exc:
            self._set_auto_exposure_roi_failure(
                requested or roi, "InvalidROI", "AE_ROI_VERIFY_FAILED", str(exc)
            )
            if emit_status:
                self._emit_effective_dn_status()
            return False
        self._auto_exposure_roi_requested = requested
        self._auto_exposure_roi_readback = None
        self._auto_exposure_roi_mode = (
            "FullImage"
            if requested == (0, 0, self._width, self._height)
            else "CustomROI"
        )
        self._auto_exposure_roi_verified = False
        self._auto_exposure_roi_verification_status = "Pending"
        self._auto_exposure_roi_error = ""
        if self._camera is None:
            self._set_auto_exposure_roi_failure(
                requested, "CameraDisconnected", "AE_ROI_WRITE_FAILED", "camera is not connected"
            )
            if emit_status:
                self._emit_effective_dn_status()
            return False

        previous_mode = self._sdk_auto_exposure_mode
        if previous_mode is not SDKAutoExposureMode.MANUAL:
            try:
                self._disable_sdk_auto_exposure(require_readback=True)
            except Exception as exc:
                self._set_auto_exposure_roi_failure(
                    requested, "DisableAEFailed", "AE_ROI_WRITE_FAILED", str(exc)
                )
                if emit_status:
                    self._emit_effective_dn_status()
                return False
        try:
            self._camera.put_AEAuxRect(*requested)
        except Exception as exc:
            self._set_auto_exposure_roi_failure(
                requested, "WriteFailed", "AE_ROI_WRITE_FAILED", str(exc)
            )
            if emit_status:
                self._emit_effective_dn_status()
            return False
        try:
            readback = tuple(int(value) for value in self._camera.get_AEAuxRect())
        except Exception as exc:
            self._set_auto_exposure_roi_failure(
                requested, "ReadbackFailed", "AE_ROI_READBACK_FAILED", str(exc)
            )
            if emit_status:
                self._emit_effective_dn_status()
            return False
        self._auto_exposure_roi_readback = readback
        if readback != requested:
            self._set_auto_exposure_roi_failure(
                requested,
                "ReadbackMismatch",
                "AE_ROI_VERIFY_FAILED",
                f"requested={requested} readback={readback}",
            )
            if emit_status:
                self._emit_effective_dn_status()
            return False

        self._auto_exposure_roi_verified = True
        self._auto_exposure_roi_verification_status = "Verified"
        self._auto_exposure_roi_error = ""
        LOG.info(
            "%s requested=%s readback=%s verified=True",
            reason,
            requested,
            readback,
        )
        if refresh_profile:
            self._refresh_ae_calibration_profile()
        if previous_mode is not SDKAutoExposureMode.MANUAL:
            try:
                self._configure_sdk_auto_exposure_parameters(self._camera)
                self._enable_sdk_auto_exposure(previous_mode)
            except Exception as exc:
                self._set_auto_exposure_roi_failure(
                    requested, "RestoreAEFailed", "AE_ROI_VERIFY_FAILED", str(exc)
                )
                if emit_status:
                    self._emit_effective_dn_status()
                return False
        if emit_status:
            self._emit_effective_dn_status()
        return True

    def _set_auto_exposure_roi_failure(
        self,
        requested: tuple[int, int, int, int] | None,
        status: str,
        log_event: str,
        error: str,
    ) -> None:
        if requested is not None:
            self._auto_exposure_roi_requested = requested
            self._auto_exposure_roi_mode = (
                "FullImage"
                if requested == (0, 0, self._width, self._height)
                else "CustomROI"
            )
        self._auto_exposure_roi_verified = False
        self._auto_exposure_roi_verification_status = status
        self._auto_exposure_roi_error = str(error)
        self._latest_metering_mean_effective_dn = None
        self._latest_metering_effective_dn_fraction = None
        self._ae_calibration_profile = None
        LOG.error(
            "%s requested=%s readback=%s verified=False error=%s",
            log_event,
            requested,
            self._auto_exposure_roi_readback,
            error,
        )

    def set_manual_exposure(self, exposure_us: int, gain: int) -> None:
        if self._camera is None:
            return
        try:
            self._continuous_auto_exposure_requested = False
            self._disable_sdk_auto_exposure(require_readback=True)
            self._camera.put_ExpoTime(int(exposure_us))
            self._camera.put_ExpoAGain(int(gain))
            self._emit_exposure()
            self.status_changed.emit(tr("camera.status_manual_applied"))
        except Exception as exc:
            self.error_occurred.emit(self._format_error(tr("camera.error_manual_apply"), exc))

    def switch_to_manual_exposure(self) -> bool:
        """Disable AE and preserve the camera's last actual exposure and gain."""

        if self._camera is None:
            return False
        previous_mode = self._sdk_auto_exposure_mode
        try:
            self._continuous_auto_exposure_requested = False
            self._disable_sdk_auto_exposure(require_readback=True)
            current = self._read_current_exposure(self._camera)
            if current is None:
                raise RuntimeError(tr("camera.error_exposure_readback"))
            self.exposure_changed.emit(*current)
            self.status_changed.emit(tr("camera.status_manual_mode"))
            return True
        except Exception as exc:
            if previous_mode is not SDKAutoExposureMode.MANUAL:
                try:
                    self._configure_sdk_auto_exposure_parameters(self._camera)
                    self._enable_sdk_auto_exposure(previous_mode)
                except Exception:
                    LOG.exception("Failed to restore SDK AE after manual switch failure")
            self.error_occurred.emit(self._format_error(tr("camera.error_manual_switch"), exc))
            return False

    def enable_continuous_auto_exposure(self) -> bool:
        """Enable native RisingCam continuous AE, independent of DN alignment."""

        if self._camera is None:
            return False
        self._continuous_auto_exposure_requested = True
        try:
            self._configure_sdk_auto_exposure_parameters(self._camera)
            self._enable_sdk_auto_exposure(SDKAutoExposureMode.CONTINUOUS)
            self.status_changed.emit(tr("camera.status_continuous_ae"))
            self._emit_effective_dn_status()
            return True
        except Exception as exc:
            self.error_occurred.emit(self._format_error(tr("camera.error_continuous_ae"), exc))
            return False

    def start_auto_exposure_once(self) -> None:
        if self._camera is None:
            return
        try:
            self._continuous_auto_exposure_requested = False
            self._configure_sdk_auto_exposure_parameters(self._camera)
            self._enable_sdk_auto_exposure(SDKAutoExposureMode.ONCE)
            self.status_changed.emit(tr("camera.status_waiting_ae"))
        except Exception as exc:
            self.auto_exposure_result.emit(False, self._format_error(tr("camera.error_start_once_ae"), exc))

    def lock_current_exposure(self) -> None:
        if self._camera is None:
            return
        try:
            self._continuous_auto_exposure_requested = False
            self._disable_sdk_auto_exposure(require_readback=True)
            self._emit_exposure()
        except Exception as exc:
            self.error_occurred.emit(self._format_error(tr("camera.error_lock_exposure"), exc))

    def disable_auto_exposure_for_formal_measurement(self) -> bool:
        """Disable SDK AE and verify OFF before Recipe owns Exposure/Gain."""

        self._continuous_auto_exposure_requested = False
        if self._camera is None:
            return True
        try:
            self._disable_sdk_auto_exposure(require_readback=True)
            return True
        except Exception as exc:
            self.error_occurred.emit(
                self._format_error(tr("camera.error_stop_ae"), exc)
            )
            return False

    @property
    def auto_exposure_target_percent(self) -> int:
        return self._auto_exposure_target_percent

    @property
    def sdk_auto_exposure_mode(self) -> SDKAutoExposureMode:
        return self._sdk_auto_exposure_mode

    @property
    def ae_calibration_running(self) -> bool:
        return self._ae_calibration_run is not None

    def _current_ae_calibration_identity(self) -> AECalibrationIdentity | None:
        if (
            self._device is None
            or self._width <= 0
            or self._height <= 0
            or self._sensor_bit_depth is None
            or self._raw_value_alignment not in {"right", "left"}
            or not self._auto_exposure_roi_verified
            or self._auto_exposure_roi_readback is None
        ):
            return None
        model = str(getattr(getattr(self._device, "model", None), "name", ""))
        return AECalibrationIdentity(
            camera_model=model or str(getattr(self._device, "displayname", "")),
            camera_serial=self._device_identifier(self._device),
            width=self._width,
            height=self._height,
            sensor_bit_depth=self._sensor_bit_depth,
            raw_value_alignment=self._raw_value_alignment,
            ae_roi=self._auto_exposure_roi_readback,
            sdk_ae_policy=1,
            sdk_autoexposure_percent=100,
        )

    def _refresh_ae_calibration_profile(self) -> None:
        identity = self._current_ae_calibration_identity()
        self._ae_calibration_profile = self._ae_calibration_store.matching(identity)
        self._sdk_auto_exposure_target = self._runtime_sdk_target(
            self._auto_exposure_target_percent
        )
        self.ae_calibration_profile_changed.emit(self.ae_calibration_status())

    def _runtime_sdk_target(self, target_percent: int) -> int:
        if self._ae_calibration_profile is not None:
            calibrated = self._ae_calibration_profile.calibrated_sdk_target(
                target_percent
            )
            if calibrated is not None:
                return int(calibrated)
        return default_sdk_target_guess(target_percent)

    def calibrated_sdk_target(self, target_percent: int) -> tuple[int, bool]:
        percent = validate_auto_exposure_target_percent(target_percent)
        target = self._runtime_sdk_target(percent)
        return target, self._ae_calibration_profile is not None

    def ae_calibration_status(self) -> dict[str, Any]:
        identity = self._current_ae_calibration_identity()
        profile = self._ae_calibration_profile
        ready = bool(identity is not None and self._camera is not None)
        if self._sensor_bit_depth is None:
            unavailable_reason = tr("camera.calibration_sensor_bits_unconfirmed")
        elif self._raw_value_alignment not in {"right", "left"}:
            unavailable_reason = tr("camera.calibration_alignment_unconfirmed")
        elif not self._auto_exposure_roi_verified:
            unavailable_reason = tr("camera.calibration_roi_unverified")
        elif self._camera is None:
            unavailable_reason = tr("camera.connect_first")
        else:
            unavailable_reason = ""
        return {
            "ready": ready,
            "running": self._ae_calibration_run is not None,
            "unavailable_reason": unavailable_reason,
            "calibrated": profile is not None,
            "camera_model": (
                identity.camera_model
                if identity is not None
                else str(getattr(getattr(self._device, "model", None), "name", ""))
            ),
            "camera_serial": (
                identity.camera_serial
                if identity is not None
                else (
                    self._device_identifier(self._device)
                    if self._device is not None
                    else ""
                )
            ),
            "resolution": identity.resolution if identity is not None else (
                f"{self._width}x{self._height}" if self._width and self._height else ""
            ),
            "sensor_bit_depth": self._sensor_bit_depth,
            "raw_value_alignment": self._raw_value_alignment,
            "ae_roi": (
                identity.ae_roi if identity is not None else self._auto_exposure_roi_readback
            ),
            "profile_id": profile.profile_id if profile is not None else None,
            "created_at": profile.created_at if profile is not None else None,
            "target_mapping": dict(profile.target_mapping) if profile is not None else {},
            "store_path": (
                str(self._ae_calibration_store.path)
                if self._ae_calibration_store.path is not None
                else None
            ),
        }

    def clear_current_ae_calibration(self) -> bool:
        if self._ae_calibration_run is not None:
            return False
        identity = self._current_ae_calibration_identity()
        if identity is None:
            return False
        changed = self._ae_calibration_store.clear(identity)
        self._refresh_ae_calibration_profile()
        if changed and self._camera is not None:
            self._write_sdk_auto_exposure_target(self._camera)
            self._emit_effective_dn_status()
        return changed

    def start_ae_calibration(self) -> bool:
        if self._ae_calibration_run is not None:
            return False
        identity = self._current_ae_calibration_identity()
        if self._camera is None or identity is None:
            self.ae_calibration_finished.emit(
                False, self.ae_calibration_status()["unavailable_reason"]
            )
            return False
        self._ae_calibration_previous_mode = self._sdk_auto_exposure_mode
        self._ae_calibration_run = AECalibrationRun(
            identity=identity,
            candidates=calibration_candidates(
                nncam.NNCAM_AETARGET_MIN, nncam.NNCAM_AETARGET_MAX
            ),
            sdk_minimum=nncam.NNCAM_AETARGET_MIN,
            sdk_maximum=nncam.NNCAM_AETARGET_MAX,
        )
        try:
            self._disable_sdk_auto_exposure(require_readback=True)
            self._configure_sdk_auto_exposure_parameters(self._camera)
            if self._sdk_auto_exposure_policy_readback != 1:
                raise RuntimeError(
                    "NNCAM_OPTION_AUTOEXP_POLICY must read back Exposure Preferred (1)"
                )
            if self._sdk_auto_exposure_percent_readback != 100:
                raise RuntimeError(
                    "NNCAM_OPTION_AUTOEXPOSURE_PERCENT must read back "
                    "full active AE ROI average (100)"
                )
            self._start_next_ae_calibration_point()
            return True
        except Exception as exc:
            self._abort_ae_calibration(
                self._format_error(tr("camera.error_calibration_start"), exc)
            )
            return False

    def cancel_ae_calibration(self) -> None:
        if self._ae_calibration_run is None:
            return
        self._abort_ae_calibration(tr("camera.calibration_cancelled_user"))

    def _start_next_ae_calibration_point(self) -> None:
        run = self._ae_calibration_run
        if run is None or self._camera is None:
            return
        candidate = run.next_candidate()
        if candidate is None:
            self._finish_ae_calibration()
            return
        self._disable_sdk_auto_exposure(require_readback=True)
        readback = self._write_sdk_auto_exposure_target_value(
            self._camera, candidate
        )
        run.start_point(readback)
        self._enable_sdk_auto_exposure(SDKAutoExposureMode.ONCE)
        self._ae_calibration_timer.start()
        self._emit_ae_calibration_progress(tr("camera.calibration_waiting_convergence"))

    def _emit_ae_calibration_progress(self, state: str) -> None:
        run = self._ae_calibration_run
        if run is None:
            return
        current = (
            self._read_current_exposure(self._camera)
            if self._camera is not None
            else None
        )
        self.ae_calibration_progress.emit({
            "point": run.index + 1,
            "total": len(run.candidates),
            "sdk_target": run.current_target,
            "sdk_target_readback": run.current_readback,
            "state": state,
            "exposure_us": current[0] if current is not None else None,
            "gain_percent": current[1] if current is not None else None,
            "mean_effective_dn": self._latest_metering_mean_effective_dn,
            "effective_dn_max": self._effective_dn_max,
            "mean_effective_dn_percent": (
                self._latest_metering_effective_dn_fraction * 100.0
                if self._latest_metering_effective_dn_fraction is not None
                else None
            ),
            "estimated_remaining_seconds": run.estimated_remaining_seconds(),
        })

    def _mark_ae_calibration_converged(self, source: str) -> None:
        run = self._ae_calibration_run
        if run is None or run.state != "waiting_convergence":
            return
        self._ae_calibration_timer.stop()
        try:
            self._disable_sdk_auto_exposure(require_readback=True)
            run.mark_converged(self._frame_sequence, source)
            self._ae_calibration_timer.start()
            self._emit_ae_calibration_progress(tr("camera.calibration_wait_fresh_frame"))
        except Exception as exc:
            self._abort_ae_calibration(
                self._format_error(tr("camera.error_calibration_stop_after_convergence"), exc)
            )

    @Slot()
    def _on_ae_calibration_timeout(self) -> None:
        run = self._ae_calibration_run
        if run is None or self._camera is None:
            return
        try:
            self._disable_sdk_auto_exposure(require_readback=True)
        except Exception as exc:
            self._abort_ae_calibration(
                self._format_error(tr("camera.error_calibration_stop_after_timeout"), exc)
            )
            return
        current = self._read_current_exposure(self._camera)
        point = run.record_point(
            mean_effective_dn=self._latest_metering_mean_effective_dn,
            mean_effective_dn_percent=(
                self._latest_metering_effective_dn_fraction * 100.0
                if self._latest_metering_effective_dn_fraction is not None
                else None
            ),
            exposure_us=current[0] if current is not None else None,
            gain_percent=current[1] if current is not None else None,
            converged=False,
            convergence_source="Timeout",
        )
        self._log_ae_calibration_point(point)
        self._emit_ae_calibration_progress(tr("camera.calibration_point_timeout"))
        QTimer.singleShot(0, self._start_next_ae_calibration_point)

    def _record_ae_calibration_fresh_frame(self) -> None:
        run = self._ae_calibration_run
        if run is None or self._camera is None:
            return
        self._ae_calibration_timer.stop()
        current = self._read_current_exposure(self._camera)
        point = run.record_point(
            mean_effective_dn=self._latest_metering_mean_effective_dn,
            mean_effective_dn_percent=(
                self._latest_metering_effective_dn_fraction * 100.0
                if self._latest_metering_effective_dn_fraction is not None
                else None
            ),
            exposure_us=current[0] if current is not None else None,
            gain_percent=current[1] if current is not None else None,
            converged=True,
        )
        self._log_ae_calibration_point(point)
        self._emit_ae_calibration_progress(tr("camera.calibration_point_recorded"))
        QTimer.singleShot(0, self._start_next_ae_calibration_point)

    def _log_ae_calibration_point(self, point: AECalibrationPoint) -> None:
        identity = (
            self._ae_calibration_run.identity
            if self._ae_calibration_run is not None
            else self._current_ae_calibration_identity()
        )
        LOG.info(
            "SDK_AE_CAL_POINT timestamp=%s camera_serial=%s resolution=%s "
            "sdk_target=%s target_readback=%s converged=%s exposure_us=%s "
            "gain_percent=%s mean_dn=%s dn_max=%s dn_percent=%s saturated=%s "
            "low_signal=%s convergence_source=%s",
            datetime.now().astimezone().isoformat(timespec="milliseconds"),
            identity.camera_serial if identity is not None else "",
            identity.resolution if identity is not None else "",
            point.sdk_target,
            point.sdk_target_readback,
            point.converged,
            point.exposure_us,
            point.gain_percent,
            point.mean_effective_dn,
            self._effective_dn_max,
            point.mean_effective_dn_percent,
            point.saturated,
            point.low_signal,
            point.convergence_source,
        )

    def _finish_ae_calibration(self) -> None:
        run = self._ae_calibration_run
        if run is None:
            return
        profile = run.build_profile()
        if not profile.valid:
            self._abort_ae_calibration(profile.invalid_reason)
            return
        previous_profile = self._ae_calibration_profile
        self._ae_calibration_timer.stop()
        self._ae_calibration_run = None
        self._ae_calibration_profile = profile
        try:
            self._restore_ae_after_calibration()
            self._ae_calibration_store.replace(profile)
            mappings = " ".join(
                f"{percent}% -> target {target}"
                for percent, target in sorted(profile.target_mapping.items())
            )
            LOG.info(
                "SDK_AE_CAL_RESULT timestamp=%s camera_serial=%s resolution=%s "
                "profile_id=%s %s",
                datetime.now().astimezone().isoformat(timespec="milliseconds"),
                profile.camera_serial,
                profile.resolution,
                profile.profile_id,
                mappings,
            )
        except Exception as exc:
            self._ae_calibration_profile = previous_profile
            try:
                self._restore_ae_after_calibration()
            except Exception:
                LOG.exception("Failed to restore prior AE profile after calibration failure")
            self._emit_effective_dn_status()
            self.ae_calibration_finished.emit(
                False,
                self._format_error(tr("camera.error_calibration_finish"), exc),
            )
            return
        self.ae_calibration_profile_changed.emit(self.ae_calibration_status())
        self._emit_effective_dn_status()
        self.ae_calibration_finished.emit(True, tr("camera.calibration_completed"))

    def _abort_ae_calibration(self, message: str) -> None:
        self._ae_calibration_timer.stop()
        self._ae_calibration_run = None
        try:
            self._refresh_ae_calibration_profile()
            self._continuous_auto_exposure_requested = False
            self._disable_sdk_auto_exposure(require_readback=True)
            if self._camera is not None:
                self._write_sdk_auto_exposure_target(self._camera)
        except Exception:
            LOG.exception("Failed to leave SDK AE off after calibration abort")
        self._emit_effective_dn_status()
        self.ae_calibration_finished.emit(False, message)

    def _restore_ae_after_calibration(self) -> None:
        if self._camera is None:
            return
        self._write_sdk_auto_exposure_target(self._camera)
        if self._ae_calibration_previous_mode is SDKAutoExposureMode.CONTINUOUS:
            self._continuous_auto_exposure_requested = True
            self._configure_sdk_auto_exposure_parameters(self._camera)
            self._enable_sdk_auto_exposure(SDKAutoExposureMode.CONTINUOUS)
        else:
            self._continuous_auto_exposure_requested = False
            self._disable_sdk_auto_exposure(require_readback=True)

    def set_auto_exposure_target_percent(self, target_percent: int) -> None:
        self._auto_exposure_target_percent = validate_auto_exposure_target_percent(
            target_percent
        )
        self._sdk_auto_exposure_target = self._runtime_sdk_target(
            self._auto_exposure_target_percent
        )
        if (
            self._camera is not None
            and self._sdk_auto_exposure_mode is not SDKAutoExposureMode.MANUAL
        ):
            self._write_sdk_auto_exposure_target(self._camera)
            self._log_sdk_ae_calibration("TargetChanged")
        self._emit_effective_dn_status()

    def _configure_sdk_auto_exposure_parameters(self, camera: Any) -> None:
        self._sdk_auto_exposure_policy_readback = self._write_nonblocking_sdk_option(
            camera,
            "NNCAM_OPTION_AUTOEXP_POLICY",
            nncam.NNCAM_OPTION_AUTOEXP_POLICY,
            1,
        )
        self._sdk_auto_exposure_percent_readback = self._write_nonblocking_sdk_option(
            camera,
            "NNCAM_OPTION_AUTOEXPOSURE_PERCENT",
            nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT,
            100,
        )
        self._sdk_auto_exposure_exposure_damping_readback = (
            self._read_nonblocking_setting(
                "NNCAM_OPTION_AUTOEXP_EXPOTIME_DAMP readback",
                lambda: camera.get_Option(nncam.NNCAM_OPTION_AUTOEXP_EXPOTIME_DAMP),
            )
        )
        self._sdk_auto_exposure_gain_damping_readback = self._read_nonblocking_setting(
            "NNCAM_OPTION_AUTOEXP_GAIN_DAMP readback",
            lambda: camera.get_Option(nncam.NNCAM_OPTION_AUTOEXP_GAIN_DAMP),
        )
        self._sdk_overexposure_policy_readback = self._read_nonblocking_setting(
            "NNCAM_OPTION_OVEREXP_POLICY readback",
            lambda: camera.get_Option(nncam.NNCAM_OPTION_OVEREXP_POLICY),
        )
        self._write_sdk_auto_exposure_target(camera)

    @staticmethod
    def _write_nonblocking_sdk_option(
        camera: Any,
        label: str,
        option: int,
        requested: int,
    ) -> int | None:
        try:
            camera.put_Option(option, int(requested))
            readback = int(camera.get_Option(option))
            if readback != int(requested):
                LOG.warning(
                    "%s readback mismatch: requested=%s actual=%s",
                    label,
                    requested,
                    readback,
                )
            else:
                LOG.info("%s requested/readback=%s/%s", label, requested, readback)
            return readback
        except Exception as exc:
            LOG.warning("%s unsupported or unavailable: %s", label, exc)
            return CameraController._read_nonblocking_setting(
                f"{label} diagnostic after configuration failure",
                lambda: camera.get_Option(option),
            )

    def _write_sdk_auto_exposure_target(self, camera: Any) -> None:
        requested = self._runtime_sdk_target(self._auto_exposure_target_percent)
        self._write_sdk_auto_exposure_target_value(camera, requested)

    def _write_sdk_auto_exposure_target_value(
        self, camera: Any, requested: int
    ) -> int:
        requested = min(
            max(int(requested), nncam.NNCAM_AETARGET_MIN),
            nncam.NNCAM_AETARGET_MAX,
        )
        camera.put_AutoExpoTarget(requested)
        readback = int(camera.get_AutoExpoTarget())
        self._sdk_auto_exposure_target = requested
        self._sdk_auto_exposure_target_readback = readback
        if readback != requested:
            LOG.warning(
                "SDK AutoExpoTarget readback mismatch: requested=%s actual=%s",
                requested,
                readback,
            )
        else:
            LOG.info("SDK AutoExpoTarget requested/readback=%s/%s", requested, readback)
        return readback

    def _enable_sdk_auto_exposure(self, mode: SDKAutoExposureMode) -> None:
        if self._camera is None:
            raise RuntimeError("Camera is not connected")
        if not self._auto_exposure_roi_verified:
            raise RuntimeError(
                "SDK AE cannot be enabled until AEAuxRect readback is verified"
            )
        if mode not in {SDKAutoExposureMode.CONTINUOUS, SDKAutoExposureMode.ONCE}:
            raise ValueError("SDK AE enable mode must be Continuous or Once")
        enable_value = 1 if mode is SDKAutoExposureMode.CONTINUOUS else 2
        self._camera.put_AutoExpoEnable(enable_value)
        readback = int(self._camera.get_AutoExpoEnable())
        self._sdk_auto_exposure_enable_readback = readback
        if readback != enable_value:
            raise RuntimeError(
                f"SDK AutoExpoEnable requested {enable_value}, read back {readback}"
            )
        self._sdk_auto_exposure_mode = mode
        self._log_sdk_ae_calibration("AEStateChanged")

    def _disable_sdk_auto_exposure(self, *, require_readback: bool) -> None:
        if self._camera is None:
            self._sdk_auto_exposure_mode = SDKAutoExposureMode.MANUAL
            self._sdk_auto_exposure_enable_readback = 0
            return
        self._camera.put_AutoExpoEnable(0)
        try:
            readback = int(self._camera.get_AutoExpoEnable())
        except Exception:
            if require_readback:
                raise
            readback = None
        self._sdk_auto_exposure_enable_readback = readback
        if require_readback and readback != 0:
            raise RuntimeError(
                f"SDK AutoExpoEnable requested 0, read back {readback}"
            )
        self._sdk_auto_exposure_mode = SDKAutoExposureMode.MANUAL
        self._log_sdk_ae_calibration("AEStateChanged")

    def _log_sdk_ae_calibration(self, reason: str) -> None:
        now = monotonic()
        if (
            reason == "ScientificFrame"
            and now - self._last_sdk_ae_calibration_log_monotonic < 1.0
        ):
            return
        self._last_sdk_ae_calibration_log_monotonic = now
        maximum = self._effective_dn_max
        effective_target = (
            target_effective_dn(maximum, self._auto_exposure_target_percent)
            if maximum is not None
            else None
        )
        current = (
            self._read_current_exposure(self._camera)
            if self._camera is not None
            else None
        )
        LOG.info(
            "SDK_AE_CALIBRATION timestamp=%s reason=%s UserTargetPercent=%s%% "
            "EffectiveDNTarget=%s/%s SDKAutoExposureTarget=%s "
            "SDKAutoExposureTargetReadback=%s SDKAutoExposureMode=%s "
            "AutoExposureCalibrationApplied=%s CalibrationProfileId=%s "
            "ExposureReadbackUs=%s GainReadback=%s MeanEffectiveDN=%s "
            "MeanEffectiveDNPercent=%s MeteringMeanEffectiveDN=%s "
            "MeteringMeanEffectiveDNPercent=%s AEROI=%s AEROIVerified=%s "
            "Alignment=%s",
            datetime.now().astimezone().isoformat(timespec="milliseconds"),
            reason,
            self._auto_exposure_target_percent,
            effective_target,
            maximum,
            self._sdk_auto_exposure_target,
            self._sdk_auto_exposure_target_readback,
            self._sdk_auto_exposure_mode.value,
            self._ae_calibration_profile is not None,
            (
                self._ae_calibration_profile.profile_id
                if self._ae_calibration_profile is not None
                else None
            ),
            current[0] if current is not None else None,
            current[1] if current is not None else None,
            self._latest_mean_effective_dn,
            (
                self._latest_effective_dn_fraction * 100.0
                if self._latest_effective_dn_fraction is not None
                else None
            ),
            self._latest_metering_mean_effective_dn,
            (
                self._latest_metering_effective_dn_fraction * 100.0
                if self._latest_metering_effective_dn_fraction is not None
                else None
            ),
            self._auto_exposure_roi_readback,
            self._auto_exposure_roi_verified,
            self._raw_value_alignment,
        )

    def current_exposure(self) -> tuple[int, int]:
        if self._camera is None:
            return 0, 0
        current = self._read_current_exposure(self._camera)
        return current if current is not None else (0, 0)

    def capture_metadata(self) -> dict[str, Any]:
        """Stable identity/format fields for a frame already pulled by this controller."""

        model = getattr(getattr(self._device, "model", None), "name", "")
        auto_mode = self._sdk_auto_exposure_mode.value
        auto_active = self._sdk_auto_exposure_mode is not SDKAutoExposureMode.MANUAL
        current = (
            self._read_current_exposure(self._camera)
            if self._camera is not None
            else None
        )
        tone_controls_neutral = bool(
            self._scientific_isp_bypassed
            or (
                self._linear_readback == 0
                and self._curve_readback == 0
                and self._gamma_readback == 100
            )
        )
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
            "RawValueAlignmentSource": self._raw_value_alignment_source,
            "AlignmentVerificationState": (
                self._alignment_verifier.state.value
                if self._alignment_verifier is not None
                else (
                    AlignmentVerificationState.VERIFIED_RIGHT.value
                    if self._raw_value_alignment == "right"
                    else (
                        AlignmentVerificationState.VERIFIED_LEFT.value
                        if self._raw_value_alignment == "left"
                        else AlignmentVerificationState.UNKNOWN.value
                    )
                )
            ),
            "PixelFormatReadback": self._pixel_format_readback,
            "PixelFormatName": self._pixel_format_name,
            "EffectiveDNMax": self._effective_dn_max,
            "MeanEffectiveDN": self._latest_mean_effective_dn,
            "MeanEffectiveDNPercent": (
                self._latest_effective_dn_fraction * 100.0
                if self._latest_effective_dn_fraction is not None
                else None
            ),
            "ScientificGammaApplied": False if tone_controls_neutral else None,
            "ScientificToneMappingApplied": False if tone_controls_neutral else None,
            "ScientificGammaNeutralVerified": tone_controls_neutral,
            "ScientificToneMappingNeutralVerified": tone_controls_neutral,
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
            "AutoExposureMode": auto_mode,
            "AutoExposureController": "RisingCamSDK" if auto_active else None,
            "AutoExposureTargetPercent": (
                self._auto_exposure_target_percent if auto_active else None
            ),
            "EffectiveDNTarget": (
                target_effective_dn(
                    self._effective_dn_max,
                    self._auto_exposure_target_percent,
                )
                if auto_active and self._effective_dn_max is not None
                else None
            ),
            "SDKAutoExposureEnabled": auto_active,
            "SDKAutoExposureEnableReadback": (
                self._sdk_auto_exposure_enable_readback
            ),
            "SDKAutoExposureTarget": (
                self._sdk_auto_exposure_target
            ),
            "SDKAutoExposureTargetReadback": (
                self._sdk_auto_exposure_target_readback
            ),
            "AutoExposureCalibrationApplied": self._ae_calibration_profile is not None,
            "AutoExposureCalibrationProfileId": (
                self._ae_calibration_profile.profile_id
                if self._ae_calibration_profile is not None
                else None
            ),
            "AutoExposureCalibrationDate": (
                self._ae_calibration_profile.created_at
                if self._ae_calibration_profile is not None
                else None
            ),
            "AutoExposureCalibrationResolution": (
                self._ae_calibration_profile.resolution
                if self._ae_calibration_profile is not None
                else None
            ),
            "SDKAutoExposurePolicy": self._sdk_auto_exposure_policy_readback,
            "SDKAutoExposurePercent": self._sdk_auto_exposure_percent_readback,
            "SDKAutoExposureExposureDamping": (
                self._sdk_auto_exposure_exposure_damping_readback
            ),
            "SDKAutoExposureGainDamping": (
                self._sdk_auto_exposure_gain_damping_readback
            ),
            "SDKOverexposurePolicy": self._sdk_overexposure_policy_readback,
            "AutoExposureMinExposure": (
                self._auto_exposure_range[0] if self._auto_exposure_range else None
            ),
            "AutoExposureMaxExposure": (
                self._auto_exposure_range[1] if self._auto_exposure_range else None
            ),
            "AutoExposureMinGain": (
                self._auto_exposure_range[2] if self._auto_exposure_range else None
            ),
            "AutoExposureMaxGain": (
                self._auto_exposure_range[3] if self._auto_exposure_range else None
            ),
            "ExposureReadbackUs": current[0] if current is not None else None,
            "GainReadback": current[1] if current is not None else None,
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

    @staticmethod
    def _pixel_format_label(value: int | None) -> str:
        names = {
            getattr(nncam, "NNCAM_PIXELFORMAT_RAW8", -1): "RAW8",
            getattr(nncam, "NNCAM_PIXELFORMAT_RAW10", -1): "RAW10",
            getattr(nncam, "NNCAM_PIXELFORMAT_RAW11", -1): "RAW11",
            getattr(nncam, "NNCAM_PIXELFORMAT_RAW12", -1): "RAW12",
            getattr(nncam, "NNCAM_PIXELFORMAT_RAW14", -1): "RAW14",
            getattr(nncam, "NNCAM_PIXELFORMAT_RAW16", -1): "RAW16",
        }
        return names.get(value, f"Unknown({value})" if value is not None else "Unknown")

    @staticmethod
    def _determine_raw_value_alignment(
        sensor_bit_depth: int | None,
        container_bit_depth: int,
        pixel_format_readback: int | None,
    ) -> tuple[str, str]:
        """Return documented alignment or mark runtime verification pending."""

        if sensor_bit_depth == container_bit_depth:
            return "right", "SensorBitDepthEqualsContainerBitDepth"
        # PixelFormat alone does not document whether Grey16 effective bits are
        # MSB- or LSB-aligned. Multi-frame runtime evidence decides later.
        _ = pixel_format_readback
        if (
            sensor_bit_depth is not None
            and int(sensor_bit_depth) < int(container_bit_depth)
        ):
            return "unknown", "RuntimeVerificationPending"
        return "unknown", "SensorBitDepthUnknown"

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
            "PixelFormat diagnostic: %s (%s)\n"
            "RawValueAlignment/source: %s/%s\n"
            "EffectiveDNMax: %s\n"
            "Camera Exposure Hardware Range: min = %s us, max = %s us, default = %s us\n"
            "Camera Gain Hardware Range: min = %s %%, max = %s %%, default = %s %%\n"
            "Auto Exposure Range: min exposure = %s us, max exposure = %s us, "
            "min gain = %s %%, max gain = %s %%\n"
            "Auto Exposure Controller/mode/user target: RisingCamSDK/%s/%s %%\n"
            "SDK Auto Exposure target requested/readback: %s/%s\n"
            "SDK Auto Exposure policy/full-active-AE-ROI percent: %s/%s\n"
            "SDK Auto Exposure exposure/gain damping: %s/%s\n"
            "SDK Overexposure policy: %s",
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
            info.get("pixel_format_readback", "unsupported"),
            info.get("pixel_format_name", "Unknown"),
            info.get("raw_value_alignment", "--"),
            info.get("raw_value_alignment_source", "--"),
            info.get("effective_dn_max", "--"),
            *(exposure or ("--", "--", "--")),
            *(gain or ("--", "--", "--")),
            *(auto_range or ("--", "--", "--", "--")),
            info.get("auto_exposure_mode", "--"),
            info.get("auto_exposure_target_percent", "--"),
            info.get("sdk_auto_exposure_target", "--"),
            info.get("sdk_auto_exposure_target_readback", "--"),
            info.get("sdk_auto_exposure_policy", "unsupported"),
            info.get("sdk_auto_exposure_percent", "unsupported"),
            info.get("sdk_auto_exposure_exposure_damping", "unsupported"),
            info.get("sdk_auto_exposure_gain_damping", "unsupported"),
            info.get("sdk_overexposure_policy", "unsupported"),
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
            if self._ae_calibration_run is not None:
                self._mark_ae_calibration_converged("NNCAM_EVENT_AUTOEXPO_CONV")
            elif self._sdk_auto_exposure_mode is SDKAutoExposureMode.ONCE:
                try:
                    self._disable_sdk_auto_exposure(require_readback=True)
                    current = self._read_current_exposure(self._camera)
                    if current is None:
                        raise RuntimeError("SDK AE convergence Exposure/Gain readback failed")
                    self.exposure_changed.emit(*current)
                    self._log_sdk_ae_calibration("AutoOnceConverged")
                    self.auto_exposure_result.emit(
                        True, tr("camera.auto_exposure_converged")
                    )
                except Exception as exc:
                    self.auto_exposure_result.emit(
                        False,
                        self._format_error(tr("camera.error_lock_after_convergence"), exc),
                    )
            else:
                self._log_sdk_ae_calibration("ContinuousConverged")
        elif event_code == nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL:
            if self._ae_calibration_run is not None:
                self._ae_calibration_timer.stop()
                try:
                    self._disable_sdk_auto_exposure(require_readback=True)
                    run = self._ae_calibration_run
                    current = self._read_current_exposure(self._camera)
                    point = run.record_point(
                        mean_effective_dn=self._latest_metering_mean_effective_dn,
                        mean_effective_dn_percent=(
                            self._latest_metering_effective_dn_fraction * 100.0
                            if self._latest_metering_effective_dn_fraction is not None
                            else None
                        ),
                        exposure_us=current[0] if current is not None else None,
                        gain_percent=current[1] if current is not None else None,
                        converged=False,
                        convergence_source="NNCAM_EVENT_AUTOEXPO_CONVFAIL",
                    )
                    self._log_ae_calibration_point(point)
                    QTimer.singleShot(0, self._start_next_ae_calibration_point)
                except Exception as exc:
                    self._abort_ae_calibration(
                        self._format_error(tr("camera.error_calibration_convergence"), exc)
                    )
            elif self._sdk_auto_exposure_mode is SDKAutoExposureMode.ONCE:
                try:
                    self._disable_sdk_auto_exposure(require_readback=True)
                except Exception:
                    LOG.exception("Failed to disable SDK AE after convergence failure")
                self.auto_exposure_result.emit(
                    False, tr("camera.auto_exposure_not_converged")
                )
            else:
                LOG.warning("RisingCam SDK reported auto exposure convergence failure")
        elif event_code == nncam.NNCAM_EVENT_DISCONNECTED:
            self.close_camera()
            self.error_occurred.emit(tr("camera.error_connection_lost"))
        elif event_code in (nncam.NNCAM_EVENT_ERROR, nncam.NNCAM_EVENT_NOFRAMETIMEOUT):
            self.error_occurred.emit(tr("camera.error_sdk_event", code=f"0x{event_code:04X}"))

    def _update_alignment_verification(self, scientific: np.ndarray) -> None:
        verifier = self._alignment_verifier
        if verifier is None or verifier.is_final:
            return
        previous_state = verifier.state
        state = verifier.add_frame(scientific)
        evidence = verifier.evidence
        if verifier.alignment == "unknown":
            self._raw_value_alignment_source = verifier.source
        LOG.info(
            "DN alignment runtime evidence: state=%s frames=%s sampled=%s "
            "nonzero=%s above_right_max=%s (%.6f) low_bits_zero_ratio=%.6f "
            "nonzero_low_bits=%s patterns=%s",
            state.value,
            evidence.frames,
            evidence.sampled_pixels,
            evidence.nonzero_pixels,
            evidence.above_right_max_pixels,
            evidence.above_right_max_ratio,
            evidence.low_bits_zero_ratio,
            evidence.nonzero_low_bits_pixels,
            evidence.nonzero_low_bit_patterns,
        )
        if state in {
            AlignmentVerificationState.VERIFIED_RIGHT,
            AlignmentVerificationState.VERIFIED_LEFT,
        }:
            self._raw_value_alignment = verifier.alignment
            self._raw_value_alignment_source = verifier.source
            self._effective_dn_max = effective_dn_max(self._sensor_bit_depth)
            self._refresh_ae_calibration_profile()
            if (
                self._camera is not None
                and self._sdk_auto_exposure_mode is not SDKAutoExposureMode.MANUAL
                and self._ae_calibration_run is None
            ):
                self._write_sdk_auto_exposure_target(self._camera)
            LOG.info(
                "DN alignment runtime verified: alignment=%s source=%s",
                self._raw_value_alignment,
                self._raw_value_alignment_source,
            )
            if self._sdk_auto_exposure_mode is SDKAutoExposureMode.CONTINUOUS:
                self.status_changed.emit(
                    tr("camera.status_alignment_ae", alignment=self._raw_value_alignment.capitalize())
                )
            else:
                self.status_changed.emit(
                    tr("camera.status_alignment", alignment=self._raw_value_alignment.capitalize())
                )
        elif state is AlignmentVerificationState.AMBIGUOUS:
            self._raw_value_alignment = "unknown"
            self._raw_value_alignment_source = verifier.source
            if verifier.source == "InsufficientSignal":
                self.status_changed.emit(tr("camera.status_alignment_low_signal_ae"))
            else:
                self.status_changed.emit(tr("camera.status_alignment_unknown_ae"))
                if not self._alignment_warning_emitted:
                    self._alignment_warning_emitted = True
                    self.error_occurred.emit(
                        tr("camera.error_alignment_conflict")
                    )
        elif verifier.source == "InsufficientSignal":
            self._raw_value_alignment_source = verifier.source
            self.status_changed.emit(
                tr("camera.status_alignment_wait_signal")
            )
        elif previous_state is AlignmentVerificationState.UNKNOWN:
            self.status_changed.emit(tr("camera.status_confirming_alignment"))

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
            self._update_alignment_verification(scientific)
            if (
                self._raw_value_alignment in {"right", "left"}
                and self._sensor_bit_depth is not None
            ):
                self._effective_dn_max = effective_dn_max(self._sensor_bit_depth)
                self._latest_mean_effective_dn = mean_effective_dn(
                    scientific,
                    self._sensor_bit_depth,
                    16,
                    self._raw_value_alignment,
                )
                self._latest_effective_dn_fraction = effective_dn_fraction(
                    self._latest_mean_effective_dn,
                    self._effective_dn_max,
                )
                if (
                    self._auto_exposure_roi_verified
                    and self._auto_exposure_roi_readback is not None
                ):
                    if self._auto_exposure_roi_mode == "FullImage":
                        self._latest_metering_mean_effective_dn = (
                            self._latest_mean_effective_dn
                        )
                    else:
                        self._latest_metering_mean_effective_dn = mean_effective_dn_roi(
                            scientific,
                            self._sensor_bit_depth,
                            16,
                            self._raw_value_alignment,
                            *self._auto_exposure_roi_readback,
                        )
                    self._latest_metering_effective_dn_fraction = effective_dn_fraction(
                        self._latest_metering_mean_effective_dn,
                        self._effective_dn_max,
                    )
                else:
                    self._latest_metering_mean_effective_dn = None
                    self._latest_metering_effective_dn_fraction = None
                display = effective_dn_to_uint8(
                    scientific,
                    self._sensor_bit_depth,
                    16,
                    self._raw_value_alignment,
                )
            else:
                self._effective_dn_max = (
                    effective_dn_max(self._sensor_bit_depth)
                    if self._sensor_bit_depth is not None
                    else None
                )
                self._latest_mean_effective_dn = None
                self._latest_effective_dn_fraction = None
                self._latest_metering_mean_effective_dn = None
                self._latest_metering_effective_dn_fraction = None
                # Fail-closed visualization fallback: preserve the prior fixed
                # uint16-container mapping and never infer alignment from pixels.
                display = np.clip(
                    np.rint(scientific.astype(np.float32) * (255.0 / 65535.0)),
                    0,
                    255,
                ).astype(np.uint8)
            calibration_run = self._ae_calibration_run
            calibration_state = (
                calibration_run.state if calibration_run is not None else ""
            )
            if (
                calibration_run is not None
                and calibration_state == "waiting_convergence"
                and self._latest_metering_effective_dn_fraction is not None
            ):
                current = self._read_current_exposure(self._camera)
                if current is not None and calibration_run.observe_stability(
                    current[0],
                    current[1],
                    self._latest_metering_effective_dn_fraction * 100.0,
                ):
                    self._mark_ae_calibration_converged("StableFrameFallback")
                else:
                    self._emit_ae_calibration_progress(tr("camera.calibration_waiting_convergence"))
            elif (
                calibration_run is not None
                and calibration_state == "waiting_fresh_frame"
                and self._frame_sequence + 1 > calibration_run.fresh_after_sequence
            ):
                self._record_ae_calibration_fresh_frame()
            self._log_sdk_ae_calibration("ScientificFrame")
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
            self._emit_effective_dn_status()
        except Exception as exc:
            self._scientific_frame_validated = False
            if not self._scientific_pull_error_reported:
                self._scientific_pull_error_reported = True
                LOG.exception("Camera scientific frame validation failed: %s", exc)
                self.error_occurred.emit(self._format_error(tr("camera.error_read_frame"), exc))

    def _effective_dn_status(self) -> dict[str, Any]:
        target_dn = (
            target_effective_dn(
                self._effective_dn_max,
                self._auto_exposure_target_percent,
            )
            if self._effective_dn_max is not None
            else None
        )
        return {
            "SensorBitDepth": self._sensor_bit_depth,
            "ContainerBitDepth": 16,
            "RawValueAlignment": self._raw_value_alignment,
            "RawValueAlignmentSource": self._raw_value_alignment_source,
            "AlignmentVerificationState": (
                self._alignment_verifier.state.value
                if self._alignment_verifier is not None
                else (
                    AlignmentVerificationState.VERIFIED_RIGHT.value
                    if self._raw_value_alignment == "right"
                    else (
                        AlignmentVerificationState.VERIFIED_LEFT.value
                        if self._raw_value_alignment == "left"
                        else AlignmentVerificationState.UNKNOWN.value
                    )
                )
            ),
            "EffectiveDNMax": self._effective_dn_max,
            "MeanEffectiveDN": self._latest_mean_effective_dn,
            "MeanEffectiveDNPercent": (
                self._latest_effective_dn_fraction * 100.0
                if self._latest_effective_dn_fraction is not None
                else None
            ),
            "MeteringMeanEffectiveDN": self._latest_metering_mean_effective_dn,
            "MeteringMeanEffectiveDNPercent": (
                self._latest_metering_effective_dn_fraction * 100.0
                if self._latest_metering_effective_dn_fraction is not None
                else None
            ),
            "AutoExposureROIRequested": self._auto_exposure_roi_requested,
            "AutoExposureROIReadback": self._auto_exposure_roi_readback,
            "AutoExposureROIMode": self._auto_exposure_roi_mode,
            "AutoExposureROIVerified": self._auto_exposure_roi_verified,
            "AutoExposureROIVerificationStatus": (
                self._auto_exposure_roi_verification_status
            ),
            "AutoExposureROIError": self._auto_exposure_roi_error,
            "AutoExposureTargetPercent": self._auto_exposure_target_percent,
            "AutoExposureTargetDN": target_dn,
            "SDKAutoExposureTarget": self._sdk_auto_exposure_target,
            "SDKAutoExposureTargetReadback": (
                self._sdk_auto_exposure_target_readback
            ),
            "AutoExposureCalibrationApplied": self._ae_calibration_profile is not None,
            "AutoExposureCalibrationProfileId": (
                self._ae_calibration_profile.profile_id
                if self._ae_calibration_profile is not None
                else None
            ),
            "AutoExposureCalibrationDate": (
                self._ae_calibration_profile.created_at
                if self._ae_calibration_profile is not None
                else None
            ),
            "AutoExposureCalibrationResolution": (
                self._ae_calibration_profile.resolution
                if self._ae_calibration_profile is not None
                else None
            ),
            "AutoExposureController": "RisingCamSDK",
            "AutoExposureMode": self._sdk_auto_exposure_mode.value,
            "ContinuousAutoExposureRequested": (
                self._continuous_auto_exposure_requested
            ),
        }

    def _emit_effective_dn_status(self) -> None:
        self.effective_dn_status_changed.emit(self._effective_dn_status())

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
        if current is None:
            if not self._status_query_failed:
                LOG.warning("RisingCam SDK failed to refresh current Exposure/Gain")
            self._status_query_failed = True
            self.exposure_status_changed.emit(None, None, None)
            return
        self._status_query_failed = False
        self.exposure_status_changed.emit(current[0], current[1], None)

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
