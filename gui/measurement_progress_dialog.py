from __future__ import annotations

"""Modeless two-stage progress window for EL Matrix measurement and CSV work."""

from datetime import datetime
from enum import Enum

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr

from .el_matrix_plan import format_duration, format_finish_time
from .el_matrix_runner import MatrixRuntimeProgress
from .numeric import format_voltage_number
from .pixel_csv_postprocessor import PixelCSVProgress


class MeasurementProgressState(str, Enum):
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ERROR = "error"


class MeasurementProgressDialog(QDialog):
    stop_requested = Signal()
    retry_pixel_csv_requested = Signal()
    AUTO_CLOSE_MS = 3000

    def __init__(self, recipe_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("progress.title"))
        self.setModal(False)
        self.setMinimumWidth(520)
        self._state = MeasurementProgressState.RUNNING
        self._running = True
        self._postprocessing = False
        self._last_measurement_fields: dict[QLabel, str] = {}
        self._terminal_closed = False
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.setInterval(self.AUTO_CLOSE_MS)
        self._auto_close_timer.timeout.connect(self._auto_close_completed)
        self.recipe_value = QLabel(recipe_name)
        self.stage_value = QLabel(tr("progress.hardware_measurement"))
        self.phase_value = QLabel(tr("progress.preparing"))
        self.channel_value = QLabel("—")
        self.sample_value = QLabel("—")
        self.condition_value = QLabel("—")
        self.channel_progress_value = QLabel("—")
        self.overall_value = QLabel("0 / 0")
        self.percent_value = QLabel("0.0%")
        self.remaining_value = QLabel("—")
        self.remaining_time_value = QLabel("—")
        self.finish_value = QLabel("—")
        form = QFormLayout()
        form.addRow(tr("recipe.title"), self.recipe_value)
        form.addRow(tr("progress.stage"), self.stage_value)
        form.addRow(tr("progress.current_step"), self.phase_value)
        form.addRow(tr("common.channel"), self.channel_value)
        form.addRow(tr("measurement.sample"), self.sample_value)
        form.addRow(tr("progress.condition_status"), self.condition_value)
        form.addRow(tr("progress.channel_progress"), self.channel_progress_value)
        form.addRow(tr("progress.file_capture_progress"), self.overall_value)
        form.addRow(tr("progress.percentage"), self.percent_value)
        form.addRow(tr("progress.remaining_count"), self.remaining_value)
        form.addRow(tr("progress.remaining_time"), self.remaining_time_value)
        form.addRow(tr("progress.estimated_finish"), self.finish_value)
        self.progress_bar = QProgressBar()
        self.stop_button = QPushButton(tr("progress.stop_safe_shutdown"))
        self.stop_button.clicked.connect(self._on_action_clicked)
        self.retry_button = QPushButton(tr("progress.retry_pixel_csv"))
        self.retry_button.clicked.connect(self.retry_pixel_csv_requested)
        self.retry_button.hide()
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.retry_button)

    @property
    def ui_state(self) -> MeasurementProgressState:
        return self._state

    @property
    def auto_close_active(self) -> bool:
        return self._auto_close_timer.isActive()

    def _set_state(self, state: MeasurementProgressState) -> None:
        self._state = state
        self._running = state in (
            MeasurementProgressState.RUNNING,
            MeasurementProgressState.STOPPING,
        )
        if state is not MeasurementProgressState.COMPLETED:
            self._auto_close_timer.stop()

    def _set_close_action(self) -> None:
        self.stop_button.setText(tr("common.close"))
        self.stop_button.setEnabled(True)

    def _on_action_clicked(self) -> None:
        if self._state is MeasurementProgressState.RUNNING:
            self._set_state(MeasurementProgressState.STOPPING)
            self.stop_button.setEnabled(False)
            self.stop_requested.emit()
            return
        if self._state in (
            MeasurementProgressState.COMPLETED,
            MeasurementProgressState.ABORTED,
            MeasurementProgressState.ERROR,
        ):
            self.close()

    def _auto_close_completed(self) -> None:
        if (
            self._state is MeasurementProgressState.COMPLETED
            and not self._terminal_closed
            and self.isVisible()
        ):
            self.close()

    def _remember_measurement_fields(self) -> None:
        self._last_measurement_fields = {
            label: label.text()
            for label in (
                self.channel_value,
                self.sample_value,
                self.condition_value,
                self.channel_progress_value,
            )
        }

    def _restore_measurement_fields(self) -> None:
        for label, value in self._last_measurement_fields.items():
            label.setText(value)

    def update_progress(self, progress: MatrixRuntimeProgress) -> None:
        self.stage_value.setText(tr("progress.hardware_measurement"))
        self.phase_value.setText(progress.phase)
        self.channel_value.setText(
            f"{progress.channel_index} / {progress.channel_total} — {progress.channel}"
            if progress.channel_index else progress.channel or "—"
        )
        self.sample_value.setText(progress.sample_id or "—")
        if (
            progress.current_density_ma_cm2 is None
            and progress.commanded_voltage_v is None
        ):
            self.condition_value.setText(progress.message or "—")
        else:
            electrical = (
                f"V={format_voltage_number(progress.commanded_voltage_v)} V"
                if progress.output_mode == "voltage"
                else f"J={progress.current_density_ma_cm2:g} mA/cm²"
            )
            self.condition_value.setText(tr(
                "progress.condition_value",
                electrical=electrical,
                gain=progress.gain_percent,
                exposure=f"{progress.exposure_ms:g}",
                repeat=progress.repeat_index,
                repeat_total=progress.repeat_total,
            ))
        self.channel_progress_value.setText(
            f"{progress.channel_completed} / {progress.channel_capture_total}"
            if progress.channel_capture_total else "—"
        )
        self.overall_value.setText(f"{progress.current} / {progress.total}")
        percent = 100.0 if progress.total == 0 else progress.current / progress.total * 100.0
        self.percent_value.setText(f"{percent:.1f}%")
        self.remaining_value.setText(tr("progress.captures_remaining", count=progress.remaining_captures))
        self.remaining_time_value.setText(format_duration(progress.remaining_time_s))
        self.finish_value.setText(
            format_finish_time(progress.estimated_finish)
            if progress.estimated_finish is not None else "—"
        )
        self.progress_bar.setRange(0, max(1, progress.total))
        self.progress_bar.setValue(progress.current)
        self._remember_measurement_fields()

    def update_postprocess_progress(self, progress: PixelCSVProgress) -> None:
        self._postprocessing = True
        self.stage_value.setText(tr("progress.pixel_csv_postprocess"))
        self.phase_value.setText(tr("progress.pixel_csv_postprocess"))
        self.overall_value.setText(f"{progress.current} / {progress.total}")
        self.percent_value.setText(f"{progress.percent:.1f}%")
        self.remaining_value.setText(tr("progress.files_remaining", count=max(0, progress.total - progress.current)))
        self.remaining_time_value.setText(format_duration(progress.remaining_time_s))
        self.finish_value.setText(
            format_finish_time(progress.estimated_finish)
            if progress.estimated_finish is not None else "—"
        )
        self.progress_bar.setRange(0, max(1, progress.total))
        self.progress_bar.setValue(progress.current)
        # Hardware is already safely OFF; closing or stopping must not cancel
        # durable post-processing or delete completed measurement products.
        self.stop_button.setEnabled(False)

    def set_hardware_complete_starting_postprocess(self) -> None:
        self._set_state(MeasurementProgressState.RUNNING)
        self._terminal_closed = False
        self._running = True
        self._postprocessing = True
        self._restore_measurement_fields()
        self.stage_value.setText(tr("progress.pixel_csv_postprocess"))
        self.phase_value.setText(tr("progress.hardware_complete"))
        self.stop_button.setText(tr("progress.stop_safe_shutdown"))
        self.stop_button.setEnabled(False)
        self.retry_button.hide()

    def set_complete(self, total: int) -> None:
        self._set_state(MeasurementProgressState.COMPLETED)
        self._terminal_closed = False
        self._restore_measurement_fields()
        self.phase_value.setText(tr(
            "progress.completed_status",
            message=tr("measurement.completed"),
        ))
        self.overall_value.setText(f"{total} / {total}")
        self.percent_value.setText("100.0%")
        self.remaining_value.setText(tr("progress.captures_remaining", count=0))
        self.remaining_time_value.setText(format_duration(0))
        self.finish_value.setText(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(max(1, total))
        self._set_close_action()
        self.retry_button.hide()
        self.show()
        self._auto_close_timer.start()

    def set_stopped(self) -> None:
        self.set_aborted(tr("progress.stopped_safely"))

    def set_aborted(self, message: str | None = None) -> None:
        self._set_state(MeasurementProgressState.ABORTED)
        self._terminal_closed = False
        self.phase_value.setText(message or tr("measurement.stopped_safely"))
        self._set_close_action()
        self.retry_button.hide()
        self.show()

    def set_failed(self, reason: str) -> None:
        self._set_state(MeasurementProgressState.ERROR)
        self._terminal_closed = False
        self.phase_value.setText(tr("progress.hardware_failed"))
        self.condition_value.setText(tr("progress.reason", reason=reason))
        self._set_close_action()
        self.retry_button.hide()
        self.show()

    def set_postprocess_failed(self, reason: str) -> None:
        self._set_state(MeasurementProgressState.ERROR)
        self._terminal_closed = False
        self._postprocessing = True
        self.stage_value.setText(tr("progress.pixel_csv_postprocess"))
        self.phase_value.setText(tr("progress.postprocess_failed"))
        self.condition_value.setText(tr("progress.reason", reason=reason))
        self._set_close_action()
        self.retry_button.setEnabled(True)
        self.retry_button.show()
        self.show()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._running:
            self.hide()
            event.ignore()
            return
        self._auto_close_timer.stop()
        self._terminal_closed = True
        super().closeEvent(event)
