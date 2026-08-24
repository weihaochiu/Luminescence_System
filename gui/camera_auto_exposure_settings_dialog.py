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

from core.i18n import tr

from .error_reporting import report_error

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
        self.setWindowTitle(tr("camera.ae_calibration"))
        self.setModal(True)
        self.setMinimumWidth(430)

        self.point_value = QLabel("--")
        self.sdk_target_value = QLabel("--")
        self.state_value = QLabel(tr("common.preparing"))
        self.exposure_value = QLabel("--")
        self.gain_value = QLabel("--")
        self.dn_value = QLabel("--")
        self.signal_value = QLabel("--")
        self.remaining_value = QLabel("--")
        self.progress = QProgressBar()
        self.progress.setRange(0, 15)
        self.cancel_button = QPushButton(tr("common.cancel"))
        self.cancel_button.clicked.connect(self._cancel)

        form = QFormLayout()
        form.addRow(tr("common.point"), self.point_value)
        form.addRow(tr("camera.sdk_target"), self.sdk_target_value)
        form.addRow(tr("common.status"), self.state_value)
        form.addRow(tr("camera.exposure_time"), self.exposure_value)
        form.addRow(tr("camera.gain"), self.gain_value)
        form.addRow(tr("camera.effective_dn"), self.dn_value)
        form.addRow(tr("camera.signal"), self.signal_value)
        form.addRow(tr("progress.estimated_remaining"), self.remaining_value)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)

        controller.ae_calibration_progress.connect(self._on_progress)
        controller.ae_calibration_finished.connect(self._on_finished)

    def start(self) -> None:
        if not self.controller.start_ae_calibration():
            self.result_message = tr("camera.ae_calibration_start_failed")

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.state_value.setText(tr("camera.ae_calibration_cancelling"))
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
        self.setWindowTitle(tr("camera.auto_exposure_settings"))
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
        target_form.addRow(tr("camera.auto_exposure_target"), self.target_percent_combo)

        calibration_group = QGroupBox(tr("camera.calibration"))
        calibration_form = QFormLayout(calibration_group)
        self.calibration_status_value = QLabel(tr("camera.not_calibrated"))
        self.calibration_camera_value = QLabel("--")
        self.calibration_resolution_value = QLabel("--")
        self.calibration_date_value = QLabel("--")
        self.calibrate_button = QPushButton(tr("camera.run_ae_calibration"))
        self.clear_calibration_button = QPushButton(tr("camera.clear_calibration"))
        self.calibrate_button.clicked.connect(self._run_calibration)
        self.clear_calibration_button.clicked.connect(self._clear_calibration)
        calibration_form.addRow(tr("common.status"), self.calibration_status_value)
        calibration_form.addRow(tr("camera.model"), self.calibration_camera_value)
        calibration_form.addRow(tr("camera.resolution"), self.calibration_resolution_value)
        calibration_form.addRow(tr("camera.calibration_date"), self.calibration_date_value)
        calibration_form.addRow(self.calibrate_button)
        calibration_form.addRow(self.clear_calibration_button)

        explanation = QLabel(tr("camera.calibration_explanation"))
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
            self.calibrate_button.setToolTip(tr("camera.connect_first"))
            self._update_target_tooltip()
            return
        status = self._controller.ae_calibration_status()
        calibrated = bool(status.get("calibrated"))
        self.calibration_status_value.setText(
            tr("camera.calibrated") if calibrated else tr("camera.resolution_not_calibrated")
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
            tr("camera.calibration_blocked_measurement")
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
            self.target_percent_combo.setToolTip(tr("camera.uncalibrated_sdk_target"))
            return
        target, applied = self._controller.calibrated_sdk_target(self.target_percent)
        self.target_percent_combo.setToolTip(
            tr("camera.calibrated_sdk_target", target=target)
            if applied
            else tr("camera.uncalibrated_sdk_target_value", target=target)
        )

    def _run_calibration(self) -> None:
        if self._measurement_running():
            report_error(
                self,
                "UI-101",
                context={"operation": "ae_calibration", "actual": "measurement is running"},
            )
            return
        answer = QMessageBox.question(
            self,
            tr("camera.run_ae_calibration"),
            tr("camera.calibration_confirmation"),
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
            QMessageBox.information(self, tr("camera.ae_calibration"), progress.result_message)
        elif progress.result_message:
            report_error(
                self,
                "CAM-202",
                context={"operation": "ae_calibration", "actual": progress.result_message},
            )

    def _clear_calibration(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("camera.clear_calibration"),
            tr("camera.clear_calibration_confirmation"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.clear_current_ae_calibration()
            self.refresh_calibration_status()

    def accept(self) -> None:
        save_auto_exposure_target_percent(self._settings, self.target_percent)
        super().accept()
