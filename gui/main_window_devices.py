from __future__ import annotations

"""Camera, SMU, live-view, and ordinary still-capture operations."""

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, QStandardPaths, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import __version__
from .camera_exposure import ExposureMode, validate_auto_target
from .image_io import save_image_and_metadata
from .instrument_state_manager import SMUUIState
from .relay_controller import RelayError
from .smu_base import SMUDevice
from .smu_control import SMUInterlockError, SMUOwnership
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
            self.status_message.setText(
                "找到多台支援的 SMU，且無法確認上次成功設備；請手動選擇後連線。"
            )

    def connect_selected_smu(self) -> None:
        device = self.device_panel.selected_smu()
        if device is None:
            QMessageBox.information(self, "尚未選擇 SMU", "請先在左側 SMU 列表選擇一台儀器。")
            return
        self._remember_smu_selection(device.visa_address)
        self.smu_manager.connect_device(device)

    def on_smu_connection_started(self, address: str) -> None:
        self.device_panel.set_smu_connecting()
        selected = self.device_panel.selected_smu()
        label = selected.display_name if selected is not None else address
        self.instrument_state_manager.set_connecting(label)

    def on_smu_connection_failed(self, message: str) -> None:
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
                raise SMUInterlockError("SMU 正忙碌，請稍後再試。")
            self.status_message.setText(
                f"手動輸出：正在以 Break-Before-Make 切換 {channel_id}…"
            )
        except (ValueError, SMUInterlockError, RelayError) as exc:
            self.show_smu_error(str(exc))

    def on_manual_smu_sequence_finished(self, success: bool) -> None:
        self._update_white_light_control()
        if success:
            self.status_message.setText("手動 SMU OUTPUT ON；已啟動實際 V / J 監控。")

    def on_smu_connected(self, device: SMUDevice) -> None:
        self.device_panel.set_smu_connected(device)
        if device.supported:
            self.settings.setValue("devices/last_smu_address", device.visa_address)
            self.settings.setValue("devices/last_smu_serial", device.serial_number)
        self._remember_smu_selection(device.visa_address)
        self.instrument_state_manager.set_connected(device.display_name, device.supported)
        if device.supported:
            self.smu_monitor.start()

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
            self.show_smu_error("目前無法執行 SMU OUTPUT OFF 安全復歸。")
            return
        self.status_message.setText(
            "正在確認 SMU OUTPUT OFF；確認後將關閉並驗證所有 SMU routing Relay。"
        )

    def request_smu_emergency_off(self) -> None:
        self.emergency_stop_measurement()

    def request_recipe_to_manual_handover(self) -> None:
        answer = QMessageBox.question(
            self,
            "安全交接至手動控制",
            "將取消目前 Recipe、關閉白光，並在 SMU I/O 安全點確認 OUTPUT OFF。\n\n"
            "確認完成前手動輸出會維持鎖定。是否繼續？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        if self._measurement_worker is not None:
            self._measurement_worker.request_cancel()
        self.relay_service.safe_white_light_off("recipe_to_manual_handover")
        if not self.smu_manager.control.request_recipe_handover_to_manual():
            self.show_smu_error("無法啟動 Recipe 至手動控制的安全交接。")
            return
        self.status_message.setText(
            "Recipe 已停止接受新輸出；正在等待安全點並確認 SMU OUTPUT OFF。"
        )

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
            self.status_message.setText(f"找到 {len(self.devices)} 台相機")
            if len(self.devices) == 1:
                QTimer.singleShot(100, self.toggle_connection)
        else:
            self.connect_action.setEnabled(False)
            self.status_message.setText("找不到相機；請檢查 USB、供電與驅動程式")

    def toggle_connection(self) -> None:
        if self.controller.is_open:
            self.controller.close_camera()
            return
        index = self.camera_list.currentRow()
        if index < 0 or index >= len(self.devices):
            QMessageBox.information(self, "尚未選擇相機", "請先在左側相機列表選擇一台相機。")
            return
        self.status_message.setText("正在連線相機…")
        self.controller.open_device(self.devices[index])

    def on_camera_opened(self, info: dict[str, Any]) -> None:
        self.camera_info = info
        self.connect_action.setText("中斷連線")
        self.view_title.setText(f"即時影像 [{info['name']}]")
        self.model_value.setText(str(info["model"]))
        self.sdk_value.setText(str(info["sdk_version"]))
        self.color_value.setText("黑白" if info["mono"] else "彩色")
        self.camera_status.setText(f"相機 {info['model']}")

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
                "相機允許曝光範圍：\n"
                f"{exp_min / 1000.0:.3f}–{exp_max / 1000.0:.3f} ms"
            )
        else:
            self.exposure_spin.setToolTip("無法從相機 SDK 取得曝光時間硬體範圍")
        if gain_range is not None:
            gain_min, gain_max, _ = gain_range
            self.gain_spin.setRange(gain_min, gain_max)
            self.gain_spin.setToolTip(
                f"相機允許 Gain 範圍：\n{gain_min}–{gain_max} %"
            )
        else:
            self.gain_spin.setToolTip("無法從相機 SDK 取得 Gain 硬體範圍")

        target = info.get("auto_target")
        try:
            self._last_valid_auto_target = validate_auto_target(
                int(target) if target is not None else 120
            )
        except (TypeError, ValueError):
            self._last_valid_auto_target = 120
        self.auto_target_edit.setText(str(self._last_valid_auto_target))
        if info.get("exposure_us") is not None and info.get("gain") is not None:
            self.on_exposure_changed(info["exposure_us"], info["gain"])

        self._active_exposure_mode = ExposureMode.CONTINUOUS_AUTO
        self._set_exposure_mode_ui(ExposureMode.CONTINUOUS_AUTO)
        self._set_camera_controls_enabled(True)
        self._revalidate_locked_hdr_profile()

    def on_camera_closed(self) -> None:
        self.connect_action.setText("相機連線")
        self.view_title.setText("即時影像")
        self.camera_info = {}
        self.last_image = None
        self.image_view.clear_image()
        self._cancel_auto_capture()
        self._set_camera_controls_enabled(False)
        self.resolution_status.setText("影像 —")
        self.exposure_status.setText("曝光 —")
        self.gain_status.setText("Gain —")
        self.fps_status.setText("FPS —")
        self.camera_status.setText("相機 —")
        self.current_exposure_value.setText("--")
        self.current_gain_value.setText("--")
        self.current_brightness_value.setText("-- /255")

    def change_resolution(self, index: int) -> None:
        if index >= 0 and self.controller.is_open:
            self.controller.set_resolution(index)

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
            changed = self.controller.enable_continuous_auto_exposure(
                getattr(self, "_last_valid_auto_target", 120)
            )
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

    def apply_auto_exposure_target(self) -> None:
        previous = getattr(self, "_last_valid_auto_target", 120)
        try:
            target = validate_auto_target(int(self.auto_target_edit.text().strip()))
        except (TypeError, ValueError) as exc:
            self.auto_target_edit.setText(str(previous))
            message = str(exc) if str(exc) else "影像亮度目標必須是整數。"
            if "允許範圍" not in message:
                message = "影像亮度目標必須是 16–220 範圍內的整數 /255。"
            QMessageBox.warning(self, "影像亮度目標輸入錯誤", message)
            return

        if self.controller.is_open and not self.controller.set_auto_exposure_target(target):
            self.auto_target_edit.setText(str(previous))
            return
        self._last_valid_auto_target = target
        self.auto_target_edit.setText(str(target))

    def _update_exposure_control_state(self) -> None:
        connected = self.controller.is_open
        mode = self._selected_exposure_mode()
        manual = connected and mode is ExposureMode.MANUAL
        limits_available = bool(
            self.camera_info.get("exposure_range_us") and self.camera_info.get("gain_range")
        )
        self.exposure_mode_combo.setEnabled(connected)
        self.exposure_stack.setCurrentIndex(0 if mode is ExposureMode.CONTINUOUS_AUTO else 1)
        self.auto_target_edit.setEnabled(connected and mode is ExposureMode.CONTINUOUS_AUTO)
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
        self.exposure_status.setText(f"曝光 {self._format_exposure(exposure_us)}")
        self.gain_status.setText(f"Gain {gain}%")
        self.current_exposure_value.setText(f"{exposure_us / 1000.0:.3f} ms")
        self.current_gain_value.setText(f"{gain} %")

    def on_exposure_status_changed(
        self, exposure_us: int | None, gain: int | None, brightness: int | None
    ) -> None:
        if exposure_us is None or gain is None:
            self.current_exposure_value.setText("--")
            self.current_gain_value.setText("--")
            self.exposure_status.setText("曝光 —")
            self.gain_status.setText("Gain —")
        else:
            self.current_exposure_value.setText(f"{exposure_us / 1000.0:.3f} ms")
            self.current_gain_value.setText(f"{gain} %")
            self.exposure_status.setText(f"曝光 {self._format_exposure(exposure_us)}")
            self.gain_status.setText(f"Gain {gain}%")
        self.current_brightness_value.setText(
            f"{brightness} /255" if brightness is not None else "-- /255"
        )

    def on_frame_ready(self, image: QImage) -> None:
        self.last_image = image.copy()
        self.image_view.set_image(image)
        self.resolution_status.setText(f"{image.width()} × {image.height()}")
        self.capture_button.setEnabled(True)
        self.auto_capture_button.setEnabled(True)
        self.capture_action.setEnabled(True)
        self.auto_capture_action.setEnabled(True)

        if self._capture_next_frame and self._pending_auto_path:
            self._capture_next_frame = False
            path = self._pending_auto_path
            self._pending_auto_path = None
            self._save_image(path, capture_mode="auto_once", auto_converged=True)
            self._finish_auto_capture_ui()

    def capture_current_frame(self) -> None:
        if self.last_image is None:
            QMessageBox.information(self, "尚無影像", "請先連線相機並等待即時影像出現。")
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
        if not self.controller.is_open or self.last_image is None:
            QMessageBox.information(self, "尚無影像", "請先連線相機並等待即時影像出現。")
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
            self.status_message.setText("曝光已收斂，正在取得拍攝影像…")
            self._capture_next_frame = True
        else:
            self._active_exposure_mode = ExposureMode.MANUAL
            self._set_exposure_mode_ui(ExposureMode.MANUAL)
            self._cancel_auto_capture()
            QMessageBox.warning(self, "自動曝光失敗", message)

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
            QMessageBox.information(
                self,
                "自動曝光逾時",
                "15 秒內未收到收斂事件，已鎖定並保存最新畫面；JSON 紀錄中的 auto_converged 為 false。",
            )
        self._finish_auto_capture_ui()

    def _cancel_auto_capture(self) -> None:
        if hasattr(self, "auto_capture_timer"):
            self.auto_capture_timer.stop()
        self._pending_auto_path = None
        self._capture_next_frame = False
        self._finish_auto_capture_ui()

    def _finish_auto_capture_ui(self) -> None:
        connected = self.controller.is_open
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
        metadata = {
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
            "auto_exposure_target": getattr(self, "_last_valid_auto_target", 120),
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
        }
        try:
            image_path, sidecar_path = save_image_and_metadata(self.last_image, path, metadata)
            self.status_message.setText(f"已保存：{image_path.name}")
            QMessageBox.information(
                self,
                "拍攝完成",
                f"影像：{image_path}\n設定紀錄：{sidecar_path}",
            )
        except Exception as exc:
            self.show_error(f"儲存影像失敗：{exc}")

    def _choose_capture_path(self, mode: str) -> str:
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        base_dir = Path(pictures) if pictures else Path.cwd()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "auto" if mode == "auto" else "capture"
        suggested = str(base_dir / f"EL_{suffix}_{timestamp}.tif")
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "保存拍攝影像",
            suggested,
            "TIFF（建議） (*.tif *.tiff);;PNG (*.png);;JPEG (*.jpg *.jpeg);;Bitmap (*.bmp)",
        )
        if not path:
            return ""
        if not Path(path).suffix:
            extension = ".png" if selected_filter.startswith("PNG") else ".tif"
            path += extension
        return path

    def _set_camera_controls_enabled(self, enabled: bool) -> None:
        self.connect_action.setEnabled(bool(self.devices) or enabled)
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

    def show_error(self, message: str) -> None:
        self.status_message.setText(message)
        QMessageBox.warning(self, "相機控制錯誤", message)

    def show_smu_error(self, message: str) -> None:
        self.status_message.setText(message)
        if not self.smu_manager.is_connected:
            self.device_panel.set_smu_disconnected(error=True)
        QMessageBox.warning(self, "SMU 設備錯誤", message)

    @staticmethod
    def _format_exposure(exposure_us: int) -> str:
        if exposure_us >= 1_000_000:
            return f"{exposure_us / 1_000_000:.3f} s"
        if exposure_us >= 1000:
            return f"{exposure_us / 1000:.3f} ms"
        return f"{exposure_us} μs"
