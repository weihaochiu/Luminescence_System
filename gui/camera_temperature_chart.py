from __future__ import annotations

"""Presentation-only rolling chart for camera-temperature samples."""

from collections import deque
from datetime import timedelta
from typing import Iterable

from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, QPointF, Qt, Slot
from PySide6.QtGui import QCloseEvent, QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from .camera_temperature_monitor import MAX_CHART_SAMPLES, TemperatureSample


class CameraTemperatureChart(QDialog):
    """A 30-minute display buffer; closing it never changes monitor state."""

    def __init__(
        self,
        parent=None,
        *,
        max_samples: int = MAX_CHART_SAMPLES,
        display_minutes: int = 30,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Camera Temperature vs Time")
        self.setMinimumSize(720, 440)
        self._samples: deque[TemperatureSample] = deque(maxlen=max(1, max_samples))
        self._session_min_c: float | None = None
        self._session_max_c: float | None = None
        self._display_minutes = max(1, display_minutes)

        self._current_value = QLabel("目前：N/A")
        self._minimum_value = QLabel("本次最低：N/A")
        self._maximum_value = QLabel("本次最高：N/A")
        summary = QHBoxLayout()
        summary.addWidget(self._current_value)
        summary.addStretch(1)
        summary.addWidget(self._minimum_value)
        summary.addWidget(self._maximum_value)

        self._series = QLineSeries(self)
        self._series.setName("相機溫度")
        self._chart = QChart()
        self._chart.setTitle("Camera Temperature vs Time")
        self._chart.addSeries(self._series)

        self._time_axis = QDateTimeAxis()
        self._time_axis.setTitleText("時間")
        self._time_axis.setFormat("HH:mm:ss")
        self._time_axis.setTickCount(7)
        self._temperature_axis = QValueAxis()
        self._temperature_axis.setTitleText("Temperature (°C)")
        self._temperature_axis.setLabelFormat("%.1f")
        self._chart.addAxis(self._time_axis, Qt.AlignmentFlag.AlignBottom)
        self._chart.addAxis(self._temperature_axis, Qt.AlignmentFlag.AlignLeft)
        self._series.attachAxis(self._time_axis)
        self._series.attachAxis(self._temperature_axis)

        view = QChartView(self._chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout = QVBoxLayout(self)
        layout.addLayout(summary)
        layout.addWidget(view, 1)

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def session_min_c(self) -> float | None:
        return self._session_min_c

    @property
    def session_max_c(self) -> float | None:
        return self._session_max_c

    @Slot(str)
    def start_session(self, _csv_path: str = "") -> None:
        self._samples.clear()
        self._session_min_c = None
        self._session_max_c = None
        self._series.clear()
        self._current_value.setText("目前：N/A")
        self._minimum_value.setText("本次最低：N/A")
        self._maximum_value.setText("本次最高：N/A")

    @Slot(object)
    def add_sample(self, sample: TemperatureSample) -> None:
        self._samples.append(sample)
        self._session_min_c = (
            sample.value_c
            if self._session_min_c is None
            else min(self._session_min_c, sample.value_c)
        )
        self._session_max_c = (
            sample.value_c
            if self._session_max_c is None
            else max(self._session_max_c, sample.value_c)
        )
        self._refresh()

    def set_history(self, samples: Iterable[TemperatureSample]) -> None:
        self.start_session()
        for sample in samples:
            self._samples.append(sample)
            self._session_min_c = (
                sample.value_c
                if self._session_min_c is None
                else min(self._session_min_c, sample.value_c)
            )
            self._session_max_c = (
                sample.value_c
                if self._session_max_c is None
                else max(self._session_max_c, sample.value_c)
            )
        self._refresh()

    def _refresh(self) -> None:
        if not self._samples:
            self._series.clear()
            return
        points = [
            QPointF(sample.timestamp.timestamp() * 1000.0, sample.value_c)
            for sample in self._samples
        ]
        self._series.replace(points)
        first = self._samples[0].timestamp
        latest = self._samples[-1]
        window_start = max(first, latest.timestamp - timedelta(minutes=self._display_minutes))
        if window_start == latest.timestamp:
            window_start = latest.timestamp - timedelta(seconds=60)
        self._time_axis.setRange(
            QDateTime.fromMSecsSinceEpoch(round(window_start.timestamp() * 1000.0)),
            QDateTime.fromMSecsSinceEpoch(round(latest.timestamp.timestamp() * 1000.0)),
        )
        values = [sample.value_c for sample in self._samples]
        visible_min = min(values)
        visible_max = max(values)
        padding = max(0.5, (visible_max - visible_min) * 0.1)
        self._temperature_axis.setRange(visible_min - padding, visible_max + padding)
        self._current_value.setText(f"目前：{latest.value_c:.1f} °C")
        self._minimum_value.setText(f"本次最低：{self._session_min_c:.1f} °C")
        self._maximum_value.setText(f"本次最高：{self._session_max_c:.1f} °C")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.hide()
        event.ignore()
