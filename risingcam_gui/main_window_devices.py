from __future__ import annotations

"""Camera, SMU, live-view, and ordinary still-capture operations."""

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, QStandardPaths, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import __version__
from .image_io import save_image_and_metadata
from .smu_base import SMUDevice


class MainWindowDeviceMixin:
    """Coordinate device connections without constructing the main UI."""

    def refresh_smu_devices(self) -> None:
        self.smu_manager.scan()

    def on_smu_scan_finished(self, devices: list[SMUDevice]) -> None:
        preferred = str(self.settings.value("devices/last_smu_address", ""))
        self.device_panel.set_smu_devices(devices, preferred)
        self.device_panel.set_smu_disconnected()

    def connect_selected_smu(self) -> None:
        device = self.device_panel.selected_smu()
        if device is None:
            QMessageBox.information(self, "尚未選擇 SMU", "請先在左側 SMU 列表選擇一台儀器。")
            return
        self._remember_smu_selection(device.visa_address)
        self.smu_manager.connect_device(device)

    def disconnect_smu(self) -> None:
        self.smu_manager.disconnect(force=False)

    def on_smu_connected(self, device: SMUDevice) -> None:
        self.device_panel.set_smu_connected(device)
        self.smu_status.setText(f"SMU {device.model or device.display_name}")
        self._remember_smu_selection(device.visa_address)

    def on_smu_disconnected(self) -> None:
        self.device_panel.set_smu_disconnected()
        self.smu_status.setText("SMU —")

    def _remember_smu_selection(self, address: str) -> None:
        if address:
            self.settings.setValue("devices/last_smu_address", address)

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

        exp_min, exp_max, _ = info["exposure_range_us"]
        gain_min, gain_max, _ = info["gain_range"]
        self.exposure_spin.setRange(exp_min / 1000.0, exp_max / 1000.0)
        self.gain_spin.setRange(gain_min, gain_max)
        self.auto_target_spin.setValue(info["auto_target"])
        self.on_exposure_changed(info["exposure_us"], info["gain"])

        with QSignalBlocker(self.auto_exposure_check):
            self.auto_exposure_check.setChecked(True)
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

    def change_resolution(self, index: int) -> None:
        if index >= 0 and self.controller.is_open:
            self.controller.set_resolution(index)

    def toggle_auto_exposure(self, enabled: bool) -> None:
        self._update_exposure_control_state()
        self.controller.set_continuous_auto_exposure(enabled)

    def _update_exposure_control_state(self) -> None:
        manual = self.controller.is_open and not self.auto_exposure_check.isChecked()
        self.exposure_spin.setEnabled(manual)
        self.gain_spin.setEnabled(manual)
        self.apply_manual_button.setEnabled(manual)
        self.auto_target_spin.setEnabled(self.controller.is_open and self.auto_exposure_check.isChecked())

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
            mode = "auto_continuous" if self.auto_exposure_check.isChecked() else "manual"
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
        self.auto_exposure_check.setEnabled(False)
        self.auto_capture_timer.start()
        self.controller.start_auto_exposure_once()

    def on_auto_exposure_result(self, success: bool, message: str) -> None:
        if self._pending_auto_path is None:
            return
        self.auto_capture_timer.stop()
        if success:
            self._auto_capture_converged = True
            with QSignalBlocker(self.auto_exposure_check):
                self.auto_exposure_check.setChecked(False)
            self._update_exposure_control_state()
            self.status_message.setText("曝光已收斂，正在取得拍攝影像…")
            self._capture_next_frame = True
        else:
            with QSignalBlocker(self.auto_exposure_check):
                self.auto_exposure_check.setChecked(False)
            self._cancel_auto_capture()
            QMessageBox.warning(self, "自動曝光失敗", message)

    def _on_auto_capture_timeout(self) -> None:
        if self._pending_auto_path is None:
            return
        self.controller.lock_current_exposure()
        with QSignalBlocker(self.auto_exposure_check):
            self.auto_exposure_check.setChecked(False)
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
        self.auto_exposure_check.setEnabled(connected)
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
            "auto_exposure_target": self.auto_target_spin.value(),
            "auto_converged": auto_converged,
            "selected_recipe": self.selected_recipe.to_dict() if self.selected_recipe else None,
            "smu": self.smu_manager.connection_metadata(
                self.device_panel.selected_smu().visa_address
                if self.device_panel.selected_smu() is not None
                else ""
            ),
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
        self.auto_exposure_check.setEnabled(enabled)
        # Exposure widgets have two states, not only connected/disconnected.
        # Delegate them to one state function so a newly opened camera does not
        # overwrite the manual-mode state calculated from the checkbox.
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
