from __future__ import annotations

"""Camera, SMU, live-view, and ordinary still-capture operations."""

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QSignalBlocker, QStandardPaths, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from core.i18n import tr

from . import __version__
from .camera_auto_exposure_settings import target_effective_dn
from .camera_exposure import ExposureMode
from .camera_temperature_monitor import TemperatureSample, format_temperature_c
from .image_io import save_image_and_metadata
from .instrument_state_manager import SMUUIState
from .relay_controller import RelayError
from .scientific_dn import mean_effective_dn_roi
from .smu_base import SMUDevice
from .smu_control import (
    SMUErrorEvent,
    SMUErrorKind,
    SMUInterlockError,
    SMUOwnership,
)
from .smu_manager import select_auto_connect_device


class MainWindowDeviceMixin:
    """Coordinate device connections without constructing the main UI."""

    def refresh_smu_devices(self) -> None:
        self.smu_manager.scan()

    def auto_connect_smu_on_startup(self) -> None:
        self._auto_connect_after_scan = self.settings.value(
            "devices/auto_connect_smu", True, type=bool
        )
        self.refresh_smu_devices()

    def on_smu_scan_finished(self, devices: list[SMUDevice]) -> None:
        preferred = str(
            self.settings.value("devices/last_smu_address", "")
            or self.settings.value("devices/selected_smu_address", "")
        )
        self.device_panel.set_smu_devices(devices, preferred)
        self.device_panel.set_smu_disconnected()
        self.instrument_state_manager.set_disconnected()
        auto_connect = self._auto_connect_after_scan
        self._auto_connect_after_scan = False
        pending = self._pending_smu_safety_reconnect
        if pending is not None:
            matches = [
                device for device in devices if pending.target.matches_device(device)
            ]
            if len(matches) != 1:
                self._pending_smu_safety_reconnect = None
                self.report_error(
                    pending.error_code,
                    context={
                        **pending.target.to_context(),
                        "operation": "scan_for_smu_safety_reconnect",
                        "expected": "exactly one matching physical SMU",
                        "actual": f"matching devices: {len(matches)}",
                    },
                )
                return
            target = matches[0]
            self.device_panel.select_smu(target.visa_address)
            if not self.smu_manager.reconnect_device_for_safety(target):
                self._pending_smu_safety_reconnect = None
            return
        fault_identity = self.smu_manager.control.fault_identity
        if fault_identity is not None:
            self.status_message.setText(
                tr(
                    "smu.unresolved_fault_target",
                    target=fault_identity.display_name,
                )
            )
            return
        if not auto_connect:
            return
        selected = select_auto_connect_device(
            devices,
            preferred_serial=str(self.settings.value("devices/last_smu_serial", "")),
            preferred_address=str(self.settings.value("devices/last_smu_address", "")),
        )
        if selected is not None:
            self.device_panel.select_smu(selected.visa_address)
            self.smu_manager.connect_device(selected)
            return
        supported_count = sum(device.supported for device in devices)
        if supported_count > 1:
            self.status_message.setText(tr("smu.multiple_devices_manual_selection"))

    def connect_selected_smu(self) -> None:
        device = self.device_panel.selected_smu()
        if device is None:
            self.report_error("SMU-101", context={"operation": "connect_smu"})
            return
        self._remember_smu_selection(device.visa_address)
        self.smu_manager.connect_device(device)

    def on_smu_connection_started(self, address: str) -> None:
        self.device_panel.set_smu_connecting()
        selected = self.device_panel.selected_smu()
        label = selected.display_name if selected is not None else address
        self.instrument_state_manager.set_connecting(label)

    def on_smu_connection_failed(self, message: str) -> None:
        self._pending_smu_safety_reconnect = None
        self.device_panel.set_smu_disconnected(error=True)
        self.instrument_state_manager.set_connection_error(message)

    def disconnect_smu(self) -> None:
        self.smu_manager.disconnect(force=False)

    def request_manual_smu_output(
        self,
        channel_id: str,
        mode: str,
        requested: float,
        compliance: float,
        area_cm2: float,
    ) -> None:
        try:
            self.emergency_manager.begin_operator_operation()
            accepted = self.smu_manager.control.request_manual_output_sequence(
                channel_id,
                mode,
                requested,
                compliance,
                area_cm2,
                lambda requested_channel, check_cancel: (
                    self.relay_service.select_smu_output_channel(
                        requested_channel,
                        self.smu_manager.control.confirm_output_off_for_routing,
                        check_cancel,
                        "manual_smu_output",
                    )
                ),
                lambda expected_channel: self.relay_service.verify_smu_output_channel_state(
                    expected_channel,
                    "manual_smu_output",
                ),
                lambda: self.relay_service.clear_smu_output_channels(
                    "manual_smu_stop"
                ),
                lambda: self.relay_service.group_on(
                    "white_light", "manual_smu_polarity"
                ),
                lambda: self.relay_service.group_off(
                    "white_light", "manual_smu_polarity"
                ),
                self.polarity_settings_store.settings,
            )
            if not accepted:
                raise SMUInterlockError(tr("smu.error_busy"))
            self.status_message.setText(tr("smu.routing_channel", channel=channel_id))
        except (ValueError, SMUInterlockError, RelayError) as exc:
            self.show_smu_error(str(exc))

    def on_manual_smu_sequence_finished(self, success: bool) -> None:
        self._update_white_light_control()
        if success:
            self.status_message.setText(tr("smu.manual_output_on_monitoring"))

    def on_smu_connected(self, device: SMUDevice) -> None:
        self.device_panel.set_smu_connected(device)
        if device.supported:
            self.settings.setValue("devices/last_smu_address", device.visa_address)
            self.settings.setValue("devices/last_smu_serial", device.serial_number)
        self._remember_smu_selection(device.visa_address)
        self.instrument_state_manager.set_connected(device.display_name, device.supported)
        if device.supported:
            self.smu_monitor.start()
        pending = self._pending_smu_safety_reconnect
        if pending is not None:
            self._pending_smu_safety_reconnect = None
            if not pending.target.matches_device(device):
                self.report_error(
                    pending.error_code,
                    context={
                        **pending.target.to_context(),
                        "operation": "post_reconnect_identity_verification",
                        "expected": pending.target.display_name,
                        "actual": device.idn or device.visa_address,
                    },
                )
                return
            if self.smu_manager.control.output_unknown_latched:
                self.smu_manager.control.request_safe_output_off(
                    "post-reconnect safety verification"
                )

    def on_smu_disconnected(self) -> None:
        self.smu_monitor.stop()
        self.device_panel.set_smu_disconnected()
        self.instrument_state_manager.set_disconnected()

    def update_smu_ui_state(self, state: SMUUIState) -> None:
        self.manual_smu_panel.apply_ui_state(state)
        self.device_panel.apply_smu_ui_state(state)
        unified_status = state.status_text.replace("\n", "｜")
        self.smu_status.setText(unified_status)
        self.status_message.setText(unified_status)

    def request_manual_smu_off(self) -> None:
        control = self.smu_manager.control
        if control.ownership is SMUOwnership.MANUAL:
            accepted = control.request_manual_off()
        else:
            accepted = control.request_safe_output_off("manual panel recovery")
        if not accepted:
            self.show_smu_error(
                tr("smu.error_output_off_unconfirmed"),
                SMUErrorKind.OUTPUT_OFF_UNCONFIRMED,
            )
            return
        self.status_message.setText(tr("smu.confirming_output_off_and_routing"))

    def request_smu_emergency_off(self) -> None:
        self.emergency_stop_measurement()

    def request_recipe_to_manual_handover(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("smu.safe_handover_manual"),
            tr("smu.safe_handover_confirmation"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        if self._measurement_worker is not None:
            self._measurement_worker.request_cancel()
        self.relay_service.safe_white_light_off("recipe_to_manual_handover")
        if not self.smu_manager.control.request_recipe_handover_to_manual():
            self.show_smu_error(tr("smu.error_handover_start"))
            return
        self.status_message.setText(tr("smu.recipe_handover_waiting_safe_point"))

    def _remember_smu_selection(self, address: str) -> None:
        if address:
            self.settings.setValue("devices/selected_smu_address", address)

    def refresh_devices(self) -> None:
        if self.controller.is_open:
            self.controller.close_camera()
        self.devices = self.controller.enumerate_devices()
        self.camera_list.clear()
        for device in self.devices:
            self.camera_list.addItem(device.displayname)
        if self.devices:
            self.camera_list.setCurrentRow(0)
            self.connect_action.setEnabled(True)
            self.status_message.setText(tr("camera.devices_found", count=len(self.devices)))
            if len(self.devices) == 1:
                QTimer.singleShot(100, self.toggle_connection)
        else:
            self.connect_action.setEnabled(False)
            self.status_message.setText(tr("camera.none_found"))

    def toggle_connection(self) -> None:
        if self.controller.is_open:
            self.controller.close_camera()
            return
        index = self.camera_list.currentRow()
        if index < 0 or index >= len(self.devices):
            self.report_error("CAM-101", context={"operation": "connect_camera"})
            return
        self.status_message.setText(tr("camera.connecting"))
        self.controller.open_device(self.devices[index])

    def on_camera_opened(self, info: dict[str, Any]) -> None:
        self.camera_info = info
        self._mean_effective_dn = None
        self._latest_scientific_frame = None
        self._latest_effective_dn_status = {}
        self._live_view_dn_roi = None
        MainWindowDeviceMixin.on_live_view_dn_roi_cleared(self)
        self.connect_action.setText(tr("common.disconnect"))
        self.view_title.setText(tr("camera.live_view_named", name=info["name"]))
        self.model_value.setText(str(info["model"]))
        self.sdk_value.setText(str(info["sdk_version"]))
        self.color_value.setText(tr("camera.monochrome") if info["mono"] else tr("camera.color"))
        self.camera_status.setText(tr("camera.status_model", model=info["model"]))

        with QSignalBlocker(self.resolution_combo):
            self.resolution_combo.clear()
            for width, height in info["resolutions"][: info["preview_count"]]:
                self.resolution_combo.addItem(f"{width} × {height}")
            self.resolution_combo.setCurrentIndex(info["resolution_index"])

        exposure_range = info.get("exposure_range_us")
        gain_range = info.get("gain_range")
        if exposure_range is not None:
            exp_min, exp_max, _ = exposure_range
            self.exposure_spin.setRange(exp_min / 1000.0, exp_max / 1000.0)
            self.exposure_spin.setToolTip(
                tr(
                    "camera.exposure_range",
                    minimum=f"{exp_min / 1000.0:.3f}",
                    maximum=f"{exp_max / 1000.0:.3f}",
                )
            )
        else:
            self.exposure_spin.setToolTip(tr("camera.exposure_range_unavailable"))
        if gain_range is not None:
            gain_min, gain_max, _ = gain_range
            self.gain_spin.setRange(gain_min, gain_max)
            self.gain_spin.setToolTip(tr("camera.gain_range", minimum=gain_min, maximum=gain_max))
        else:
            self.gain_spin.setToolTip(tr("camera.gain_range_unavailable"))

        if info.get("exposure_us") is not None and info.get("gain") is not None:
            self.on_exposure_changed(info["exposure_us"], info["gain"])

        initial_mode = (
            ExposureMode.CONTINUOUS_AUTO
            if info.get("auto_exposure_mode") == "Continuous"
            else ExposureMode.MANUAL
        )
        self._active_exposure_mode = initial_mode
        self._set_exposure_mode_ui(initial_mode)
        self.on_effective_dn_status_changed({
            "SensorBitDepth": info.get("scientific_bit_depth"),
            "ContainerBitDepth": 16,
            "RawValueAlignment": info.get("raw_value_alignment", "unknown"),
            "RawValueAlignmentSource": info.get(
                "raw_value_alignment_source", "Unknown"
            ),
            "AlignmentVerificationState": (
                "Collecting"
                if info.get("raw_value_alignment_source")
                == "RuntimeVerificationPending"
                else "Unknown"
            ),
            "EffectiveDNMax": None,
            "MeanEffectiveDN": None,
            "MeanEffectiveDNPercent": None,
            "AutoExposureTargetPercent": info.get(
                "auto_exposure_target_percent",
                self.controller.auto_exposure_target_percent,
            ),
            "AutoExposureTargetDN": None,
            "AutoExposureROIRequested": info.get("auto_exposure_roi_requested"),
            "AutoExposureROIReadback": info.get("auto_exposure_roi_readback"),
            "AutoExposureROIMode": info.get(
                "auto_exposure_roi_mode", "Unavailable"
            ),
            "AutoExposureROIVerified": info.get(
                "auto_exposure_roi_verified", False
            ),
            "AutoExposureROIVerificationStatus": info.get(
                "auto_exposure_roi_verification_status", "Unavailable"
            ),
            "AutoExposureROIError": info.get("auto_exposure_roi_error", ""),
        })
        self._set_camera_controls_enabled(True)
        self.temperature_monitor.start(
            supported=bool(info.get("temperature_supported", False)),
            camera_model=str(info.get("model", "")),
            camera_identifier=str(info.get("identifier", "")),
        )

    def on_camera_closed(self) -> None:
        self.connect_action.setText(tr("toolbar.camera_connect"))
        self.view_title.setText(tr("camera.live_view"))
        self.camera_info = {}
        self.last_image = None
        self._latest_scientific_frame = None
        self._latest_effective_dn_status = {}
        self.image_view.clear_image()
        MainWindowDeviceMixin.on_live_view_dn_roi_cleared(self)
        self._cancel_auto_capture()
        self._set_camera_controls_enabled(False)
        self.resolution_status.setText(tr("camera.image_status_empty"))
        self.exposure_status.setText(tr("camera.exposure_status_empty"))
        self.gain_status.setText(tr("camera.gain_status_empty"))
        self.fps_status.setText("FPS —")
        self.camera_temperature_value.setText("N/A")
        self.temperature_status.setText(tr("camera.temperature_unavailable"))
        self.camera_status.setText(tr("camera.status_empty"))
        self.current_exposure_value.setText("--")
        self.current_gain_value.setText("--")
        self._mean_effective_dn = None
        self.mean_effective_dn_value.setText(tr("common.undetermined"))
        self.effective_dn_percent_value.setText("--")
        self.sensor_bit_depth_value.setText("--")
        self.raw_value_alignment_value.setText("Unknown")
        self.auto_exposure_target_dn_value.setText(tr("common.undetermined"))
        self.live_view_ae_metering_value.setText(tr("camera.ae_metering_empty"))
        self.live_view_ae_metering_value.setToolTip("")

    def change_resolution(self, index: int) -> None:
        if index >= 0 and self.controller.is_open:
            self.controller.set_resolution(index)
            # Controller has already replaced the SDK rectangle with the new
            # full image. Clear the old-resolution overlay immediately rather
            # than waiting for the first new frame to arrive.
            self.image_view.clear_roi()

    def change_exposure_mode(self, index: int) -> None:
        if index < 0:
            return
        mode = ExposureMode(self.exposure_mode_combo.itemData(index))
        previous = getattr(self, "_active_exposure_mode", ExposureMode.CONTINUOUS_AUTO)
        if not self.controller.is_open or mode is previous:
            self._update_exposure_control_state()
            return

        if mode is ExposureMode.MANUAL:
            changed = self.controller.switch_to_manual_exposure()
        else:
            changed = self.controller.enable_continuous_auto_exposure()
        if not changed:
            self._set_exposure_mode_ui(previous)
            return
        self._active_exposure_mode = mode
        self._update_exposure_control_state()

    def _set_exposure_mode_ui(self, mode: ExposureMode) -> None:
        with QSignalBlocker(self.exposure_mode_combo):
            index = self.exposure_mode_combo.findData(mode.value)
            if index >= 0:
                self.exposure_mode_combo.setCurrentIndex(index)

    def _selected_exposure_mode(self) -> ExposureMode:
        value = self.exposure_mode_combo.currentData()
        return ExposureMode(value or ExposureMode.CONTINUOUS_AUTO.value)

    def _update_exposure_control_state(self) -> None:
        connected = self.controller.is_open
        measurement_locked = getattr(self, "_measurement_worker", None) is not None
        if measurement_locked:
            connected = False
        mode = self._selected_exposure_mode()
        manual = connected and mode is ExposureMode.MANUAL
        limits_available = bool(
            self.camera_info.get("exposure_range_us") and self.camera_info.get("gain_range")
        )
        self.exposure_mode_combo.setEnabled(connected)
        self.exposure_stack.setCurrentIndex(0 if mode is ExposureMode.CONTINUOUS_AUTO else 1)
        self.exposure_spin.setEnabled(manual and limits_available)
        self.gain_spin.setEnabled(manual and limits_available)
        self.apply_manual_button.setEnabled(manual and limits_available)
        self.camera_connection_hint.setVisible(not connected)

    def apply_manual_exposure(self) -> None:
        exposure_us = round(self.exposure_spin.value() * 1000.0)
        self.controller.set_manual_exposure(exposure_us, self.gain_spin.value())

    def on_exposure_changed(self, exposure_us: int, gain: int) -> None:
        with QSignalBlocker(self.exposure_spin):
            self.exposure_spin.setValue(exposure_us / 1000.0)
        with QSignalBlocker(self.gain_spin):
            self.gain_spin.setValue(gain)
        self.exposure_status.setText(tr("camera.exposure_status", value=self._format_exposure(exposure_us)))
        self.gain_status.setText(tr("camera.gain_status", value=gain))
        self.current_exposure_value.setText(f"{exposure_us / 1000.0:.3f} ms")
        self.current_gain_value.setText(f"{gain} %")

    def on_exposure_status_changed(
        self,
        exposure_us: int | None,
        gain: int | None,
        _legacy_brightness: int | None,
    ) -> None:
        if exposure_us is None or gain is None:
            self.current_exposure_value.setText("--")
            self.current_gain_value.setText("--")
            self.exposure_status.setText(tr("camera.exposure_status_empty"))
            self.gain_status.setText(tr("camera.gain_status_empty"))
        else:
            self.current_exposure_value.setText(f"{exposure_us / 1000.0:.3f} ms")
            self.current_gain_value.setText(f"{gain} %")
            self.exposure_status.setText(tr("camera.exposure_status", value=self._format_exposure(exposure_us)))
            self.gain_status.setText(tr("camera.gain_status", value=gain))

    def on_effective_dn_status_changed(self, status: dict[str, Any]) -> None:
        self._latest_effective_dn_status = dict(status)
        if (
            hasattr(self, "exposure_mode_combo")
            and not bool(status.get("AutoExposureROIVerified", True))
            and status.get("AutoExposureMode") == "Manual"
            and getattr(self, "_active_exposure_mode", ExposureMode.MANUAL)
            is ExposureMode.CONTINUOUS_AUTO
        ):
            # A failed AEAuxRect verification forces SDK AE off. Keep the
            # exposure-mode UI from claiming Continuous while the controller
            # is deliberately fail-closed in Manual.
            self._active_exposure_mode = ExposureMode.MANUAL
            self._set_exposure_mode_ui(ExposureMode.MANUAL)
            self._update_exposure_control_state()
        sensor_bits = status.get("SensorBitDepth")
        alignment = str(status.get("RawValueAlignment", "unknown"))
        alignment_source = str(status.get("RawValueAlignmentSource", "Unknown"))
        verification_state = str(status.get("AlignmentVerificationState", "Unknown"))
        maximum = status.get("EffectiveDNMax")
        mean_dn = status.get("MeanEffectiveDN")
        percent = status.get("MeanEffectiveDNPercent")
        target_percent = int(
            status.get(
                "AutoExposureTargetPercent",
                self.controller.auto_exposure_target_percent,
            )
        )
        target_dn = status.get("AutoExposureTargetDN")
        if target_dn is None and maximum is not None:
            target_dn = target_effective_dn(int(maximum), target_percent)

        self._mean_effective_dn = float(mean_dn) if mean_dn is not None else None
        self.sensor_bit_depth_value.setText(
            f"{sensor_bits}-bit" if sensor_bits is not None else "Unknown"
        )
        if alignment in {"right", "left"}:
            alignment_text = alignment.capitalize()
        elif alignment_source == "InsufficientSignal":
            alignment_text = tr("camera.insufficient_signal")
        elif alignment_source == "AmbiguousRuntimeEvidence":
            alignment_text = tr("common.undetermined")
        elif (
            verification_state in {"Unknown", "Collecting"}
            and alignment_source == "RuntimeVerificationPending"
        ):
            alignment_text = tr("common.confirming")
        else:
            alignment_text = "Unknown"
        self.raw_value_alignment_value.setText(alignment_text)
        self.mean_effective_dn_value.setText(
            f"{round(float(mean_dn))} /{int(maximum)}"
            if mean_dn is not None and maximum is not None
            else tr("common.undetermined")
        )
        self.effective_dn_percent_value.setText(
            f"{float(percent):.1f} %" if percent is not None else "--"
        )
        self.auto_exposure_target_percent_value.setText(f"{target_percent} %")
        if target_dn is not None and maximum is not None:
            target_text = f"{int(target_dn)} /{int(maximum)}"
            if not bool(status.get("AutoExposureCalibrationApplied")):
                target_text += tr("common.reference_suffix")
        elif alignment_source == "RuntimeVerificationPending":
            target_text = tr("camera.waiting_dn_alignment")
        elif alignment_source == "InsufficientSignal":
            target_text = tr("camera.alignment_insufficient_signal")
        else:
            target_text = tr("common.undetermined")
        self.auto_exposure_target_dn_value.setText(target_text)
        sdk_target = status.get("SDKAutoExposureTargetReadback")
        calibration_applied = bool(status.get("AutoExposureCalibrationApplied"))
        if calibration_applied:
            calibration_text = tr("camera.calibrated_sdk_target", target=sdk_target)
        else:
            calibration_text = tr("camera.uncalibrated_sdk_target_detail", target=sdk_target)
        self.auto_exposure_target_dn_value.setToolTip(
            tr("camera.ae_controller_details", details=calibration_text)
        )
        MainWindowDeviceMixin._refresh_live_view_ae_metering_status(self, status)
        MainWindowDeviceMixin._refresh_live_view_roi_dn(self)

    def on_frame_ready(self, image: QImage) -> None:
        self.last_image = image.copy()
        self.image_view.set_image(image)
        self.resolution_status.setText(f"{image.width()} × {image.height()}")
        controls_available = getattr(self, "_measurement_worker", None) is None
        self.capture_button.setEnabled(controls_available)
        self.auto_capture_button.setEnabled(controls_available)
        self.capture_action.setEnabled(controls_available)
        self.auto_capture_action.setEnabled(controls_available)
        MainWindowDeviceMixin._update_live_view_roi_controls(self)

        if self._capture_next_frame and self._pending_auto_path:
            self._capture_next_frame = False
            path = self._pending_auto_path
            self._pending_auto_path = None
            self._save_image(path, capture_mode="auto_once", auto_converged=True)
            self._finish_auto_capture_ui()

    def on_scientific_frame_ready(
        self, scientific: Any, _preview: QImage, _sequence: int
    ) -> None:
        # CameraController already owns an independent ndarray for this frame;
        # retain that reference and slice only the selected ROI.
        self._latest_scientific_frame = scientific
        MainWindowDeviceMixin._refresh_live_view_roi_dn(self)

    def begin_live_view_dn_roi_selection(self) -> None:
        if self.image_view.begin_roi_selection():
            self.status_message.setText(tr("camera.roi_selection_instruction"))

    def on_live_view_dn_roi_selected(
        self, x: int, y: int, width: int, height: int
    ) -> None:
        self._live_view_dn_roi = (x, y, width, height)
        coordinate_text = tr("camera.roi_coordinates", x=x, y=y, width=width, height=height)
        self.live_view_roi_value.setText(coordinate_text)
        self.live_view_roi_value.setToolTip(coordinate_text)
        MainWindowDeviceMixin._update_live_view_roi_controls(self)
        MainWindowDeviceMixin._refresh_live_view_roi_dn(self)
        if not self.controller.set_auto_exposure_roi(x, y, width, height):
            self.status_message.setText(tr("camera.roi_sdk_verification_failed"))

    def clear_live_view_dn_roi(self) -> None:
        if self.controller.is_open:
            self.controller.reset_auto_exposure_roi()
        self.image_view.clear_roi()

    def on_live_view_dn_roi_cleared(self) -> None:
        self._live_view_dn_roi = None
        self.live_view_roi_value.setText(tr("camera.roi_not_set"))
        self.live_view_roi_value.setToolTip("")
        self.live_view_roi_dn_value.setText(tr("camera.roi_mean_dn_empty"))
        MainWindowDeviceMixin._update_live_view_roi_controls(self)

    def _refresh_live_view_ae_metering_status(
        self, status: dict[str, Any]
    ) -> None:
        if not hasattr(self, "live_view_ae_metering_value"):
            return
        requested = status.get("AutoExposureROIRequested")
        readback = status.get("AutoExposureROIReadback")
        mode = str(status.get("AutoExposureROIMode", "Unavailable"))
        verified = bool(status.get("AutoExposureROIVerified", False))
        verification = str(
            status.get("AutoExposureROIVerificationStatus", "Unavailable")
        )
        error = str(status.get("AutoExposureROIError", ""))
        if verified and mode == "CustomROI":
            text = tr("camera.ae_metering_roi_verified")
        elif verified and mode == "FullImage":
            text = tr("camera.ae_metering_full_verified")
        elif mode == "CustomROI":
            text = tr("camera.ae_metering_roi_failed")
        elif mode == "FullImage":
            text = tr("camera.ae_metering_full_failed")
        else:
            text = tr("camera.ae_metering_empty")
        tooltip_lines = [
            tr("camera.ae_metering_requested", requested=requested),
            tr("camera.ae_metering_readback", readback=readback),
            tr("camera.ae_metering_status", status=verification),
        ]
        if error:
            tooltip_lines.append(tr("camera.ae_metering_error", error=error))
        self.live_view_ae_metering_value.setText(text)
        self.live_view_ae_metering_value.setToolTip("\n".join(tooltip_lines))

    def _update_live_view_roi_controls(self) -> None:
        if not hasattr(self, "select_dn_roi_button"):
            return
        self.select_dn_roi_button.setEnabled(self.image_view.has_image)
        self.clear_dn_roi_button.setEnabled(self._live_view_dn_roi is not None)

    def _refresh_live_view_roi_dn(self) -> None:
        if not hasattr(self, "live_view_roi_dn_value"):
            return
        roi = self._live_view_dn_roi
        scientific = self._latest_scientific_frame
        status = self._latest_effective_dn_status
        if roi is None or scientific is None:
            self.live_view_roi_dn_value.setText(tr("camera.roi_mean_dn_empty"))
            return
        sensor_bits = status.get("SensorBitDepth")
        container_bits = status.get("ContainerBitDepth")
        alignment = str(status.get("RawValueAlignment", "unknown")).lower()
        maximum = status.get("EffectiveDNMax")
        if alignment == "unknown":
            self.live_view_roi_dn_value.setText(tr("camera.roi_mean_dn_undetermined"))
            return
        if sensor_bits is None or container_bits is None or maximum is None:
            self.live_view_roi_dn_value.setText(tr("camera.roi_mean_dn_empty"))
            return
        try:
            mean_dn = mean_effective_dn_roi(
                scientific,
                int(sensor_bits),
                int(container_bits),
                alignment,
                *roi,
            )
            maximum_dn = int(maximum)
            if maximum_dn <= 0:
                raise ValueError("EffectiveDNMax must be positive")
        except (TypeError, ValueError):
            self.live_view_roi_dn_value.setText(tr("camera.roi_mean_dn_undetermined"))
            return
        percent = mean_dn / maximum_dn * 100.0
        rounded_mean_dn = int(mean_dn + 0.5)
        self.live_view_roi_dn_value.setText(tr(
            "camera.roi_mean_dn_value",
            value=rounded_mean_dn,
            maximum=maximum_dn,
            percent=f"{percent:.1f}",
        ))

    def capture_current_frame(self) -> None:
        if not self.controller.is_open:
            self.report_error("CAM-101", context={"operation": "capture_current_frame"})
            return
        if self.last_image is None:
            self.report_error("CAM-102", context={"operation": "capture_current_frame"})
            return
        path = self._choose_capture_path("manual")
        if path:
            mode = (
                "auto_continuous"
                if self._selected_exposure_mode() is ExposureMode.CONTINUOUS_AUTO
                else "manual"
            )
            self._save_image(path, capture_mode=mode, auto_converged=None)

    def auto_expose_and_capture(self) -> None:
        if not self.controller.is_open:
            self.report_error("CAM-101", context={"operation": "auto_expose_and_capture"})
            return
        if self.last_image is None:
            self.report_error("CAM-102", context={"operation": "auto_expose_and_capture"})
            return
        path = self._choose_capture_path("auto")
        if not path:
            return

        self._pending_auto_path = path
        self._capture_next_frame = False
        self._auto_capture_converged = False
        self.capture_button.setEnabled(False)
        self.auto_capture_button.setEnabled(False)
        self.capture_action.setEnabled(False)
        self.auto_capture_action.setEnabled(False)
        self.exposure_mode_combo.setEnabled(False)
        self.auto_capture_timer.start()
        self.controller.start_auto_exposure_once()

    def on_auto_exposure_result(self, success: bool, message: str) -> None:
        if self._pending_auto_path is None:
            return
        self.auto_capture_timer.stop()
        if success:
            self._auto_capture_converged = True
            self._active_exposure_mode = ExposureMode.MANUAL
            self._set_exposure_mode_ui(ExposureMode.MANUAL)
            self._update_exposure_control_state()
            self.status_message.setText(tr("camera.exposure_converged_capturing"))
            self._capture_next_frame = True
        else:
            self._active_exposure_mode = ExposureMode.MANUAL
            self._set_exposure_mode_ui(ExposureMode.MANUAL)
            self._cancel_auto_capture()
            self.report_error(
                "CAM-202",
                context={"operation": "auto_exposure", "actual": message},
            )

    def on_ae_calibration_finished(self, _success: bool, _message: str) -> None:
        mode = (
            ExposureMode.CONTINUOUS_AUTO
            if self.controller.sdk_auto_exposure_mode.value == "Continuous"
            else ExposureMode.MANUAL
        )
        self._active_exposure_mode = mode
        self._set_exposure_mode_ui(mode)
        self._update_exposure_control_state()

    def _on_auto_capture_timeout(self) -> None:
        if self._pending_auto_path is None:
            return
        self.controller.lock_current_exposure()
        self._active_exposure_mode = ExposureMode.MANUAL
        self._set_exposure_mode_ui(ExposureMode.MANUAL)
        if self.last_image is not None:
            path = self._pending_auto_path
            self._pending_auto_path = None
            self._save_image(path, capture_mode="auto_once_timeout", auto_converged=False)
            self.report_error(
                "CAM-203",
                context={
                    "operation": "auto_exposure_capture",
                    "expected": "convergence event within 15 seconds",
                    "actual": "latest frame saved with auto_converged=false",
                },
            )
        self._finish_auto_capture_ui()

    def _cancel_auto_capture(self) -> None:
        if hasattr(self, "auto_capture_timer"):
            self.auto_capture_timer.stop()
        self._pending_auto_path = None
        self._capture_next_frame = False
        self._finish_auto_capture_ui()

    def _finish_auto_capture_ui(self) -> None:
        connected = (
            self.controller.is_open
            and getattr(self, "_measurement_worker", None) is None
        )
        self.exposure_mode_combo.setEnabled(connected)
        self.capture_button.setEnabled(connected and self.last_image is not None)
        self.auto_capture_button.setEnabled(connected and self.last_image is not None)
        self.capture_action.setEnabled(connected and self.last_image is not None)
        self.auto_capture_action.setEnabled(connected)
        self._update_exposure_control_state()

    def _save_image(self, path: str, capture_mode: str, auto_converged: bool | None) -> None:
        if self.last_image is None:
            return
        exposure_us, gain = self.controller.current_exposure()
        if capture_mode.startswith("auto_once"):
            auto_exposure_mode = "Once"
        elif capture_mode == "auto_continuous":
            auto_exposure_mode = "Continuous"
        else:
            auto_exposure_mode = "Manual"
        metadata = dict(self.controller.capture_metadata())
        maximum_dn = metadata.get("EffectiveDNMax")
        target_percent = self.controller.auto_exposure_target_percent
        metadata.update({
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "application": "EL Measurement Equipment Control",
            "application_version": __version__,
            "camera_name": self.camera_info.get("name", ""),
            "camera_model": self.camera_info.get("model", ""),
            "sdk_version": self.camera_info.get("sdk_version", ""),
            "width_px": self.last_image.width(),
            "height_px": self.last_image.height(),
            "pixel_format": "RGB24",
            "exposure_time_us": exposure_us,
            "exposure_time_ms": exposure_us / 1000.0,
            "gain_percent": gain,
            "capture_mode": capture_mode,
            "AutoExposureMode": auto_exposure_mode,
            "AutoExposureController": (
                "RisingCamSDK" if auto_exposure_mode != "Manual" else None
            ),
            "AutoExposureTargetPercent": (
                target_percent if auto_exposure_mode != "Manual" else None
            ),
            "EffectiveDNTarget": (
                target_effective_dn(int(maximum_dn), target_percent)
                if auto_exposure_mode != "Manual" and maximum_dn is not None
                else None
            ),
            "MeanEffectiveDN": getattr(self, "_mean_effective_dn", None),
            "auto_converged": auto_converged,
            "selected_recipe": self.selected_recipe.to_dict() if self.selected_recipe else None,
            "smu": self.smu_manager.connection_metadata(
                self.device_panel.selected_smu().visa_address
                if self.device_panel.selected_smu() is not None
                else ""
            ),
            "polarity_measurement_settings_snapshot": self.polarity_settings_store.settings.snapshot(),
            "last_manual_polarity_measurement": self.smu_manager.control.last_manual_polarity_snapshot,
            "manual_smu_routing": self.smu_manager.control.manual_routing_snapshot,
        })
        metadata.update(self.temperature_monitor.metadata_fields())
        try:
            image_path, sidecar_path = save_image_and_metadata(self.last_image, path, metadata)
            self.status_message.setText(tr("file.saved_name", name=image_path.name))
            QMessageBox.information(
                self,
                tr("camera.capture_complete"),
                tr("camera.capture_paths", image=image_path, sidecar=sidecar_path),
            )
        except Exception as exc:
            self.report_error(
                "FILE-201",
                context={"operation": "save_image", "resource": path},
                exception=exc,
            )

    def _choose_capture_path(self, mode: str) -> str:
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        base_dir = Path(pictures) if pictures else Path.cwd()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "auto" if mode == "auto" else "capture"
        suggested = str(base_dir / f"EL_{suffix}_{timestamp}.tif")
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("file.save_capture_image"),
            suggested,
            tr("file.image_filter"),
        )
        if not path:
            return ""
        if not Path(path).suffix:
            extension = ".png" if selected_filter.startswith("PNG") else ".tif"
            path += extension
        return path

    def _set_camera_controls_enabled(self, enabled: bool) -> None:
        measurement_locked = getattr(self, "_measurement_worker", None) is not None
        enabled = bool(enabled and not measurement_locked)
        self.connect_action.setEnabled((bool(self.devices) or enabled) and not measurement_locked)
        self.capture_button.setEnabled(False)
        self.auto_capture_button.setEnabled(False)
        self.capture_action.setEnabled(False)
        self.auto_capture_action.setEnabled(False)
        self.resolution_combo.setEnabled(enabled)
        self.exposure_mode_combo.setEnabled(enabled)
        # Exposure widgets have two states, not only connected/disconnected.
        # Delegate them to one state function so a newly opened camera does not
        # overwrite the manual-mode state calculated from the mode selector.
        self._update_exposure_control_state()
        MainWindowDeviceMixin._update_live_view_roi_controls(self)

    def on_temperature_sample(self, sample: TemperatureSample) -> None:
        text = format_temperature_c(sample.value_c)
        self.camera_temperature_value.setText(text)
        self.temperature_status.setText(tr("camera.temperature_current", temperature=text))

    def on_temperature_availability_changed(self, available: bool) -> None:
        if available:
            return
        self.camera_temperature_value.setText("N/A")
        self.temperature_status.setText(tr("camera.temperature_unavailable"))

    def open_temperature_chart(self) -> None:
        self.temperature_chart.show()
        self.temperature_chart.raise_()
        self.temperature_chart.activateWindow()

    def show_error(self, message: str) -> None:
        self.status_message.setText(message)
        self.report_error(
            "CAM-202",
            context={"operation": "camera_control", "actual": message},
        )

    def show_smu_error_event(self, event: SMUErrorEvent) -> None:
        self.show_smu_error(
            event.message,
            event.kind,
            context=event.context,
            user_message_key=event.user_message_key,
            user_message_args=event.user_message_args,
        )

    def show_smu_error(
        self,
        message: str,
        kind: SMUErrorKind = SMUErrorKind.OPERATION_FAILED,
        *,
        context: Mapping[str, object] | None = None,
        user_message_key: str | None = None,
        user_message_args: Mapping[str, object] | None = None,
    ) -> None:
        self.status_message.setText(message)
        if not self.smu_manager.is_connected:
            self.device_panel.set_smu_disconnected(error=True)
        code = {
            SMUErrorKind.OUTPUT_OFF_UNCONFIRMED: "SMU-203",
            SMUErrorKind.UNEXPECTED_OUTPUT: "SMU-205",
            SMUErrorKind.COMPLIANCE_ACTIVE: "SMU-204",
            SMUErrorKind.OPERATION_FAILED: "SMU-201",
            SMUErrorKind.POLARITY_MEASUREMENT_FAILED: "MEAS-202",
        }[kind]
        control = self.smu_manager.control
        fault_identity = control.fault_identity
        connected = self.smu_manager.connected_device
        selected = self.device_panel.selected_smu()
        context_payload: dict[str, object] = {
            "operation": "smu_control",
            "actual": message,
            "expected": "OUTPUT OFF" if code in {"SMU-203", "SMU-205"} else None,
            "smu_error_kind": kind.value,
        }
        if fault_identity is not None:
            context_payload.update(fault_identity.to_context())
        elif connected is not None:
            context_payload.update(
                {
                    "instrument": connected.display_name,
                    "resource": connected.visa_address,
                    "smu_serial_number": connected.serial_number,
                    "smu_idn": connected.idn,
                }
            )
        elif selected is not None:
            context_payload.update(
                {
                    "instrument": selected.display_name,
                    "resource": selected.visa_address,
                    "smu_serial_number": selected.serial_number,
                    "smu_idn": selected.idn,
                }
            )
        if context:
            context_payload.update(context)
        report_kwargs: dict[str, object] = {"context": context_payload}
        if user_message_key:
            report_kwargs["message_key"] = user_message_key
            report_kwargs["message_args"] = dict(user_message_args or {})
        self.report_error(code, **report_kwargs)

    @staticmethod
    def _format_exposure(exposure_us: int) -> str:
        if exposure_us >= 1_000_000:
            return f"{exposure_us / 1_000_000:.3f} s"
        if exposure_us >= 1000:
            return f"{exposure_us / 1000:.3f} ms"
        return f"{exposure_us} μs"
