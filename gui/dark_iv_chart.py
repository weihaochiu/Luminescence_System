from __future__ import annotations

"""Live and file-rendered Dark I-V plots using device-coordinate voltage."""

from collections import defaultdict
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QLogValueAxis, QValueAxis
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCloseEvent, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QVBoxLayout

from core.i18n import tr


PLOT_COLORS = (
    QColor("#d62728"),
    QColor("#2ca02c"),
    QColor("#1f77b4"),
    QColor("#9467bd"),
    QColor("#ff7f0e"),
    QColor("#17becf"),
)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def device_voltage_v(row: Mapping[str, Any]) -> float | None:
    """Return measured voltage in the Recipe/device polarity coordinate."""
    measured = _finite(row.get("MeasuredVoltageV"))
    factor = _finite(row.get("PolarityFactor"))
    if measured is not None and factor in (-1.0, 1.0):
        return measured * factor
    return _finite(row.get("SetVoltageV"))


def current_magnitude_a(row: Mapping[str, Any]) -> float | None:
    current = _finite(row.get("MeasuredCurrentA"))
    if current is None or current == 0.0:
        return None
    return abs(current)


def _curve_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row.get("Repeat", 1)), str(row.get("SweepDirection", "forward"))


def _curve_name(key: tuple[int, str]) -> str:
    repeat, direction = key
    direction_text = tr(f"dark_iv.direction.{direction}")
    return tr("dark_iv.curve_name", direction=direction_text, repeat=repeat)


def _axis_ranges(rows: Iterable[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    points = [
        (voltage, current)
        for row in rows
        if (voltage := device_voltage_v(row)) is not None
        and (current := current_magnitude_a(row)) is not None
    ]
    if points:
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        x_min, x_max = min(x_values), max(x_values)
        if x_min == x_max:
            padding = max(0.1, abs(x_min) * 0.1)
        else:
            padding = (x_max - x_min) * 0.05
        x_min -= padding
        x_max += padding
        y_min = 10.0 ** math.floor(math.log10(min(y_values)))
        y_max = 10.0 ** math.ceil(math.log10(max(y_values)))
        if y_min == y_max:
            y_min /= 10.0
            y_max *= 10.0
        return x_min, x_max, y_min, y_max
    return -1.0, 1.0, 1e-15, 1e-12


class DarkIVChartDialog(QDialog):
    """Modeless live Dark I-V chart; closing only hides the presentation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dark_iv.window_title"))
        self.setMinimumSize(820, 600)
        self._channel = ""
        self._sample_id = ""
        self._rows: list[dict[str, Any]] = []
        self._series: dict[tuple[int, str], QLineSeries] = {}

        self.channel_value = QLabel("—")
        self.progress_value = QLabel("0 / 0")
        self.voltage_value = QLabel("—")
        self.current_value = QLabel("—")
        self.status_value = QLabel(tr("dark_iv.waiting"))
        form = QFormLayout()
        form.addRow(tr("dark_iv.channel_sample"), self.channel_value)
        form.addRow(tr("dark_iv.point_progress"), self.progress_value)
        form.addRow(tr("dark_iv.measured_voltage"), self.voltage_value)
        form.addRow(tr("dark_iv.signed_current"), self.current_value)
        form.addRow(tr("dark_iv.status"), self.status_value)

        self._chart = QChart()
        self._chart.setTitle(tr("dark_iv.chart_title"))
        self._chart.legend().setVisible(True)
        self._voltage_axis = QValueAxis()
        self._voltage_axis.setTitleText(tr("dark_iv.voltage_axis"))
        self._voltage_axis.setLabelFormat("%.3g")
        self._voltage_axis.setTickCount(7)
        self._current_axis = QLogValueAxis()
        self._current_axis.setTitleText(tr("dark_iv.current_axis"))
        self._current_axis.setBase(10.0)
        self._current_axis.setLabelFormat("%.0e")
        self._current_axis.setMinorTickCount(8)
        self._chart.addAxis(self._voltage_axis, Qt.AlignmentFlag.AlignBottom)
        self._chart.addAxis(self._current_axis, Qt.AlignmentFlag.AlignLeft)
        self._voltage_axis.setRange(-1.0, 1.0)
        self._current_axis.setRange(1e-15, 1e-12)

        self._view = QChartView(self._chart)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._view, 1)

    @property
    def point_count(self) -> int:
        return len(self._rows)

    @property
    def series_count(self) -> int:
        return len(self._series)

    @property
    def current_channel(self) -> str:
        return self._channel

    def reset(self) -> None:
        self._channel = ""
        self._sample_id = ""
        self._rows.clear()
        for series in self._series.values():
            self._chart.removeSeries(series)
            series.deleteLater()
        self._series.clear()
        self.channel_value.setText("—")
        self.progress_value.setText("0 / 0")
        self.voltage_value.setText("—")
        self.current_value.setText("—")
        self.status_value.setText(tr("dark_iv.waiting"))
        self._chart.setTitle(tr("dark_iv.chart_title"))
        self._voltage_axis.setRange(-1.0, 1.0)
        self._current_axis.setRange(1e-15, 1e-12)

    def add_point(self, progress: Any) -> None:
        if self._channel and self._channel != progress.channel:
            self.reset()
        self._channel = str(progress.channel)
        self._sample_id = str(progress.sample_id)
        row = dict(progress.row)
        self._rows.append(row)
        key = _curve_key(row)
        series = self._series.get(key)
        if series is None:
            series = QLineSeries(self)
            series.setName(_curve_name(key))
            series.setPen(QPen(PLOT_COLORS[len(self._series) % len(PLOT_COLORS)], 2.2))
            series.setPointsVisible(True)
            series.setMarkerSize(7.0)
            self._chart.addSeries(series)
            series.attachAxis(self._voltage_axis)
            series.attachAxis(self._current_axis)
            self._series[key] = series
        voltage = device_voltage_v(row)
        current = current_magnitude_a(row)
        if voltage is not None and current is not None:
            series.append(voltage, current)
        x_min, x_max, y_min, y_max = _axis_ranges(self._rows)
        self._voltage_axis.setRange(x_min, x_max)
        self._current_axis.setRange(y_min, y_max)
        self._chart.setTitle(
            tr("dark_iv.chart_title_channel", channel=self._channel, sample=self._sample_id)
        )
        self.channel_value.setText(f"{self._channel} — {self._sample_id}")
        self.progress_value.setText(f"{progress.current} / {progress.total}")
        self.voltage_value.setText(
            tr("dark_iv.voltage_value", value=f"{voltage:.6g}")
            if voltage is not None else "—"
        )
        signed_current = _finite(row.get("MeasuredCurrentA"))
        self.current_value.setText(
            tr("dark_iv.current_value", value=f"{signed_current:.6e}")
            if signed_current is not None else "—"
        )
        self.status_value.setText(
            tr("dark_iv.compliance")
            if bool(row.get("ComplianceTripped"))
            else tr("dark_iv.measuring")
        )
        if not self.isVisible():
            self.show()

    def mark_complete(self, png_path: str) -> None:
        self.status_value.setText(tr("dark_iv.completed_png", path=png_path))

    def mark_aborted(self) -> None:
        if self._rows:
            self.status_value.setText(tr("dark_iv.aborted"))

    def mark_failed(self, reason: str) -> None:
        if self._rows:
            self.status_value.setText(tr("dark_iv.failed", reason=reason))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.hide()
        event.ignore()


def save_dark_iv_plot_png(
    rows: Iterable[Mapping[str, Any]],
    path: str | Path,
    *,
    channel: str,
    sample_id: str,
    footer_lines: Iterable[str] = (),
) -> Path:
    """Render a deterministic publication-style PNG without using widgets."""
    saved_rows = [dict(row) for row in rows]
    output = Path(path)
    width, height = 1400, 1040
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        plot = QRectF(150.0, 100.0, 1120.0, 650.0)
        x_min, x_max, y_min, y_max = _axis_ranges(saved_rows)
        log_min = math.log10(y_min)
        log_max = math.log10(y_max)

        painter.setPen(QPen(QColor("#d9d9d9"), 1.0))
        y_start = math.floor(log_min)
        y_stop = math.ceil(log_max)
        for exponent in range(y_start, y_stop + 1):
            y = plot.bottom() - (exponent - log_min) / (log_max - log_min) * plot.height()
            painter.drawLine(plot.left(), y, plot.right(), y)
            painter.setPen(QColor("#333333"))
            painter.drawText(QRectF(45.0, y - 14.0, 90.0, 28.0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"10^{exponent}")
            painter.setPen(QPen(QColor("#d9d9d9"), 1.0))
        for index in range(7):
            ratio = index / 6.0
            x = plot.left() + ratio * plot.width()
            painter.drawLine(x, plot.top(), x, plot.bottom())
            value = x_min + ratio * (x_max - x_min)
            painter.setPen(QColor("#333333"))
            painter.drawText(QRectF(x - 55.0, plot.bottom() + 10.0, 110.0, 30.0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{value:.3g}")
            painter.setPen(QPen(QColor("#d9d9d9"), 1.0))

        painter.setPen(QPen(QColor("#111111"), 2.0))
        painter.drawRect(plot)
        title_font = QFont(painter.font())
        title_font.setPointSize(18)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(150.0, 25.0, 1120.0, 50.0), Qt.AlignmentFlag.AlignCenter, f"DARK I-V — {channel} / {sample_id}")
        axis_font = QFont(painter.font())
        axis_font.setPointSize(13)
        axis_font.setBold(False)
        painter.setFont(axis_font)
        painter.drawText(QRectF(plot.left(), 790.0, plot.width(), 40.0), Qt.AlignmentFlag.AlignCenter, "Voltage (V)")
        painter.save()
        painter.translate(35.0, plot.center().y())
        painter.rotate(-90.0)
        painter.drawText(QRectF(-plot.height() / 2.0, -20.0, plot.height(), 40.0), Qt.AlignmentFlag.AlignCenter, "|Current| (A)")
        painter.restore()

        grouped: dict[tuple[int, str], list[tuple[float, float]]] = defaultdict(list)
        for row in saved_rows:
            voltage = device_voltage_v(row)
            current = current_magnitude_a(row)
            if voltage is not None and current is not None:
                grouped[_curve_key(row)].append((voltage, current))
        legend_x = plot.right() - 230.0
        legend_y = plot.top() + 20.0
        for curve_index, (key, points) in enumerate(grouped.items()):
            color = PLOT_COLORS[curve_index % len(PLOT_COLORS)]
            pen = QPen(color, 3.0)
            painter.setPen(pen)
            path_item = QPainterPath()
            for point_index, (voltage, current) in enumerate(points):
                x = plot.left() + (voltage - x_min) / (x_max - x_min) * plot.width()
                y = plot.bottom() - (math.log10(current) - log_min) / (log_max - log_min) * plot.height()
                if point_index == 0:
                    path_item.moveTo(x, y)
                else:
                    path_item.lineTo(x, y)
                painter.drawEllipse(QPointF(x, y), 4.0, 4.0)
            painter.drawPath(path_item)
            y_legend = legend_y + curve_index * 30.0
            painter.drawLine(legend_x, y_legend, legend_x + 35.0, y_legend)
            painter.setPen(QColor("#222222"))
            painter.drawText(QRectF(legend_x + 45.0, y_legend - 15.0, 180.0, 30.0), Qt.AlignmentFlag.AlignVCenter, _curve_name(key))

        footer = tuple(str(line) for line in footer_lines)
        if footer:
            footer_top = 850.0
            painter.fillRect(QRectF(0.0, footer_top, width, height - footer_top), QColor("#585858"))
            footer_font = QFont(painter.font())
            footer_font.setPointSize(10)
            footer_font.setBold(False)
            painter.setFont(footer_font)
            painter.setPen(QColor("white"))
            line_height = (height - footer_top - 24.0) / len(footer)
            for index, line in enumerate(footer):
                painter.drawText(
                    QRectF(24.0, footer_top + 12.0 + index * line_height, width - 48.0, line_height),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    line,
                )
    finally:
        painter.end()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output), "PNG"):
        raise OSError(f"Could not save Dark I-V PNG: {output}")
    if not output.is_file() or output.stat().st_size <= 0:
        raise OSError(f"Dark I-V PNG is empty: {output}")
    return output
