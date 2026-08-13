from __future__ import annotations

"""Modeless, presentation-only progress window for EL Matrix runs."""

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

from .el_matrix_plan import format_duration, format_finish_time
from .el_matrix_runner import MatrixRuntimeProgress


class MeasurementProgressDialog(QDialog):
    stop_requested = Signal()

    def __init__(self, recipe_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EL Matrix 自動量測")
        self.setModal(False)
        self.setMinimumWidth(460)
        self._running = True
        self.recipe_value = QLabel(recipe_name)
        self.phase_value = QLabel("準備中")
        self.channel_value = QLabel("—")
        self.sample_value = QLabel("—")
        self.condition_value = QLabel("—")
        self.channel_progress_value = QLabel("—")
        self.overall_value = QLabel("0 / 0")
        self.remaining_value = QLabel("—")
        self.remaining_time_value = QLabel("—")
        self.finish_value = QLabel("—")
        form = QFormLayout()
        form.addRow("Recipe", self.recipe_value)
        form.addRow("目前階段", self.phase_value)
        form.addRow("Channel", self.channel_value)
        form.addRow("Sample", self.sample_value)
        form.addRow("目前條件", self.condition_value)
        form.addRow("Channel 進度", self.channel_progress_value)
        form.addRow("總進度", self.overall_value)
        form.addRow("剩餘照片", self.remaining_value)
        form.addRow("預估剩餘時間", self.remaining_time_value)
        form.addRow("預計完成", self.finish_value)
        self.progress_bar = QProgressBar()
        self.stop_button = QPushButton("停止 / 安全關閉")
        self.stop_button.clicked.connect(self.stop_requested)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stop_button)

    def update_progress(self, progress: MatrixRuntimeProgress) -> None:
        self.phase_value.setText(progress.phase)
        self.channel_value.setText(
            (
                f"{progress.channel_index} / {progress.channel_total} — {progress.channel}"
                if progress.channel_index else progress.channel or "—"
            )
        )
        self.sample_value.setText(progress.sample_id or "—")
        if progress.current_density_ma_cm2 is None:
            self.condition_value.setText(progress.message or "—")
        else:
            self.condition_value.setText(
                f"J={progress.current_density_ma_cm2:g} mA/cm² | Gain={progress.gain_percent}% | "
                f"Exposure={progress.exposure_ms:g} ms | "
                f"Repeat={progress.repeat_index}/{progress.repeat_total}"
            )
        self.channel_progress_value.setText(
            f"{progress.channel_completed} / {progress.channel_capture_total}"
            if progress.channel_capture_total else "—"
        )
        self.overall_value.setText(f"{progress.current} / {progress.total}")
        self.remaining_value.setText(f"{progress.remaining_captures} 張")
        self.remaining_time_value.setText(format_duration(progress.remaining_time_s))
        self.finish_value.setText(
            format_finish_time(progress.estimated_finish)
            if progress.estimated_finish is not None else "—"
        )
        self.progress_bar.setRange(0, max(1, progress.total))
        self.progress_bar.setValue(progress.current)

    def set_complete(self, total: int) -> None:
        self._running = False
        self.phase_value.setText("量測完成")
        self.overall_value.setText(f"{total} / {total}")
        self.finish_value.setText(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))
        self.stop_button.setEnabled(False)

    def set_stopped(self) -> None:
        self._running = False
        self.phase_value.setText("量測已安全停止")
        self.stop_button.setEnabled(False)

    def set_failed(self, reason: str) -> None:
        self._running = False
        self.phase_value.setText("量測中止")
        self.condition_value.setText(f"原因：{reason}")
        self.stop_button.setEnabled(False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._running:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)
