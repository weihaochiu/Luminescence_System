from __future__ import annotations

"""Modeless two-stage progress window for EL Matrix measurement and CSV work."""

from datetime import datetime

from PySide6.QtCore import Signal
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


class MeasurementProgressDialog(QDialog):
    stop_requested = Signal()
    retry_pixel_csv_requested = Signal()

    def __init__(self, recipe_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("progress.title"))
        self.setModal(False)
        self.setMinimumWidth(520)
        self._running = True
        self._postprocessing = False
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
        self.stop_button.clicked.connect(self.stop_requested)
        self.retry_button = QPushButton(tr("progress.retry_pixel_csv"))
        self.retry_button.clicked.connect(self.retry_pixel_csv_requested)
        self.retry_button.hide()
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.retry_button)

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

    def update_postprocess_progress(self, progress: PixelCSVProgress) -> None:
        self._postprocessing = True
        self.stage_value.setText(tr("progress.pixel_csv_postprocess"))
        self.phase_value.setText(tr("progress.pixel_csv_postprocess"))
        self.condition_value.setText(progress.message or tr("progress.generating_pixel_csv"))
        self.channel_value.setText("—")
        self.sample_value.setText("—")
        self.channel_progress_value.setText("—")
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
        self._running = True
        self._postprocessing = True
        self.stage_value.setText(tr("progress.pixel_csv_postprocess"))
        self.phase_value.setText(tr("progress.hardware_complete"))
        self.condition_value.setText(tr("progress.hardware_complete_generating_csv"))
        self.stop_button.setEnabled(False)
        self.retry_button.hide()

    def set_complete(self, total: int, message: str | None = None) -> None:
        self._running = False
        self.phase_value.setText(message or tr("measurement.completed_with_pixel_csv"))
        self.overall_value.setText(f"{total} / {total}")
        self.percent_value.setText("100.0%")
        self.finish_value.setText(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))
        self.stop_button.setEnabled(False)
        self.retry_button.hide()

    def set_stopped(self) -> None:
        self._running = False
        self.phase_value.setText(tr("progress.stopped_safely"))
        self.stop_button.setEnabled(False)

    def set_failed(self, reason: str) -> None:
        self._running = False
        self.phase_value.setText(tr("progress.hardware_failed"))
        self.condition_value.setText(tr("progress.reason", reason=reason))
        self.stop_button.setEnabled(False)

    def set_postprocess_failed(self, reason: str) -> None:
        self._running = False
        self._postprocessing = True
        self.stage_value.setText(tr("progress.pixel_csv_postprocess"))
        self.phase_value.setText(tr("progress.postprocess_failed"))
        self.condition_value.setText(tr("progress.reason", reason=reason))
        self.stop_button.setEnabled(False)
        self.retry_button.setEnabled(True)
        self.retry_button.show()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._running:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)
