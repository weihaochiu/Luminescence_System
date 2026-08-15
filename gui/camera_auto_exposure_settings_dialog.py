from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .camera_auto_exposure_settings import (
    AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS,
    load_auto_exposure_target_percent,
    save_auto_exposure_target_percent,
)


class AECalibrationProgressDialog(QDialog):
    """Modal progress view for the controller-owned asynchronous scan."""

    def __init__(self, controller: Any, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.success = False
        self.result_message = ""
        self.setWindowTitle("AE Calibration")
        self.setModal(True)
        self.setMinimumWidth(430)

        self.point_value = QLabel("--")
        self.sdk_target_value = QLabel("--")
        self.state_value = QLabel("準備中…")
        self.exposure_value = QLabel("--")
        self.gain_value = QLabel("--")
        self.dn_value = QLabel("--")
        self.signal_value = QLabel("--")
        self.remaining_value = QLabel("--")
        self.progress = QProgressBar()
        self.progress.setRange(0, 15)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._cancel)

        form = QFormLayout()
        form.addRow("Point", self.point_value)
        form.addRow("SDK Target", self.sdk_target_value)
        form.addRow("狀態", self.state_value)
        form.addRow("Exposure", self.exposure_value)
        form.addRow("Gain", self.gain_value)
        form.addRow("Effective DN", self.dn_value)
        form.addRow("Signal", self.signal_value)
        form.addRow("Estimated remaining time", self.remaining_value)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)

        controller.ae_calibration_progress.connect(self._on_progress)
        controller.ae_calibration_finished.connect(self._on_finished)

    def start(self) -> None:
        if not self.controller.start_ae_calibration():
            self.result_message = "無法啟動 AE Calibration"

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.state_value.setText("正在取消並關閉 Camera AE…")
        self.controller.cancel_ae_calibration()

    def reject(self) -> None:
        if self.controller.ae_calibration_running:
            self._cancel()
            return
        super().reject()

    def _on_progress(self, status: dict[str, Any]) -> None:
        point, total = int(status["point"]), int(status["total"])
        self.progress.setRange(0, total)
        self.progress.setValue(max(0, point - 1))
        self.point_value.setText(f"{point} /{total}")
        self.sdk_target_value.setText(str(status.get("sdk_target", "--")))
        self.state_value.setText(str(status.get("state", "--")))
        exposure = status.get("exposure_us")
        gain = status.get("gain_percent")
        mean_dn = status.get("mean_effective_dn")
        maximum = status.get("effective_dn_max")
        percent = status.get("mean_effective_dn_percent")
        self.exposure_value.setText(
            f"{float(exposure) / 1000.0:.3f} ms" if exposure is not None else "--"
        )
        self.gain_value.setText(f"{gain} %" if gain is not None else "--")
        self.dn_value.setText(
            f"{float(mean_dn):.0f} /{maximum}"
            if mean_dn is not None and maximum is not None
            else "--"
        )
        self.signal_value.setText(
            f"{float(percent):.1f} %" if percent is not None else "--"
        )
        self.remaining_value.setText(
            f"{status.get('estimated_remaining_seconds', 0)} s"
        )

    def _on_finished(self, success: bool, message: str) -> None:
        self.success = bool(success)
        self.result_message = str(message)
        if success:
            self.progress.setValue(self.progress.maximum())
            self.accept()
        else:
            super().reject()


class CameraAutoExposureSettingsDialog(QDialog):
    """Edit scientific AE target and manage per-camera SDK calibration."""

    def __init__(
        self,
        settings,
        parent=None,
        *,
        controller: Any | None = None,
        measurement_running: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._controller = controller
        self._measurement_running = measurement_running or (lambda: False)
        self.setWindowTitle("相機自動曝光設定")
        self.setModal(True)
        self.setMinimumWidth(500)

        self.target_percent_combo = QComboBox()
        for percent in AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS:
            self.target_percent_combo.addItem(f"{percent} %", percent)
        current = load_auto_exposure_target_percent(settings)
        self.target_percent_combo.setCurrentIndex(
            self.target_percent_combo.findData(current)
        )
        self.target_percent_combo.currentIndexChanged.connect(
            self._update_target_tooltip
        )

        target_form = QFormLayout()
        target_form.addRow("自動曝光目標", self.target_percent_combo)

        calibration_group = QGroupBox("Calibration")
        calibration_form = QFormLayout(calibration_group)
        self.calibration_status_value = QLabel("尚未校正")
        self.calibration_camera_value = QLabel("--")
        self.calibration_resolution_value = QLabel("--")
        self.calibration_date_value = QLabel("--")
        self.calibrate_button = QPushButton("執行 AE 校正")
        self.clear_calibration_button = QPushButton("清除目前校正")
        self.calibrate_button.clicked.connect(self._run_calibration)
        self.clear_calibration_button.clicked.connect(self._clear_calibration)
        calibration_form.addRow("狀態", self.calibration_status_value)
        calibration_form.addRow("Camera", self.calibration_camera_value)
        calibration_form.addRow("Resolution", self.calibration_resolution_value)
        calibration_form.addRow("Calibration date", self.calibration_date_value)
        calibration_form.addRow(self.calibrate_button)
        calibration_form.addRow(self.clear_calibration_button)

        explanation = QLabel(
            "RisingCam SDK 的 AutoExpoTarget 與 Scientific DN 百分比不是相同尺度。\n"
            "校正會建立兩者的實機對應關係。"
        )
        explanation.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(target_form)
        layout.addWidget(calibration_group)
        layout.addWidget(explanation)
        layout.addWidget(buttons)

        if controller is not None:
            controller.ae_calibration_profile_changed.connect(
                lambda _status: self.refresh_calibration_status()
            )
            controller.effective_dn_status_changed.connect(
                lambda _status: self.refresh_calibration_status()
            )
        self.refresh_calibration_status()

    @property
    def target_percent(self) -> int:
        return int(self.target_percent_combo.currentData())

    def refresh_calibration_status(self) -> None:
        if self._controller is None:
            self.calibrate_button.setEnabled(False)
            self.clear_calibration_button.setEnabled(False)
            self.calibrate_button.setToolTip("請先連線相機")
            self._update_target_tooltip()
            return
        status = self._controller.ae_calibration_status()
        calibrated = bool(status.get("calibrated"))
        self.calibration_status_value.setText(
            "已校正" if calibrated else "目前解析度尚未校正"
        )
        camera = status.get("camera_model") or "--"
        serial = status.get("camera_serial") or ""
        self.calibration_camera_value.setText(
            f"{camera} ({serial})" if serial else str(camera)
        )
        self.calibration_resolution_value.setText(status.get("resolution") or "--")
        self.calibration_date_value.setText(status.get("created_at") or "--")
        measurement_locked = bool(self._measurement_running())
        ready = bool(status.get("ready")) and not measurement_locked
        self.calibrate_button.setEnabled(ready and not status.get("running"))
        tooltip = (
            "Measurement 正在執行，禁止 AE calibration。"
            if measurement_locked
            else str(status.get("unavailable_reason", ""))
        )
        self.calibrate_button.setToolTip(tooltip)
        self.clear_calibration_button.setEnabled(
            calibrated and not measurement_locked and not status.get("running")
        )
        self._update_target_tooltip()

    def _update_target_tooltip(self) -> None:
        if self._controller is None:
            self.target_percent_combo.setToolTip("目前使用未校正 SDK Target guess。")
            return
        target, applied = self._controller.calibrated_sdk_target(self.target_percent)
        self.target_percent_combo.setToolTip(
            f"Calibrated SDK Target = {target}"
            if applied
            else f"目前使用未校正 SDK Target guess = {target}。"
        )

    def _run_calibration(self) -> None:
        if self._measurement_running():
            QMessageBox.warning(
                self, "無法執行 AE 校正", "Measurement 正在執行，禁止 Calibration。"
            )
            return
        answer = QMessageBox.question(
            self,
            "執行 AE 校正",
            "校正期間請保持目前場景與照明穩定。\n"
            "程式會多次調整 RisingCam SDK Auto Exposure Target，\n"
            "過程中畫面亮度會改變。",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        progress = AECalibrationProgressDialog(self._controller, self)
        QTimer.singleShot(0, progress.start)
        progress.exec()
        self.refresh_calibration_status()
        if progress.success:
            QMessageBox.information(self, "AE Calibration", progress.result_message)
        elif progress.result_message:
            QMessageBox.warning(self, "AE Calibration", progress.result_message)

    def _clear_calibration(self) -> None:
        answer = QMessageBox.question(
            self,
            "清除目前校正",
            "確定要清除目前相機與解析度的 AE Calibration profile？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.clear_current_ae_calibration()
            self.refresh_calibration_status()

    def accept(self) -> None:
        save_auto_exposure_target_percent(self._settings, self.target_percent)
        super().accept()
