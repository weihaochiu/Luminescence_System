from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
from PySide6.QtWidgets import QWidget

from gui.dark_iv_chart import (
    DarkIVChartDialog,
    current_magnitude_a,
    device_voltage_v,
    save_dark_iv_plot_png,
)
from gui.el_matrix_runner import DarkIVPointProgress, DarkIVScanCompleted
from gui.main_window_measurement import _on_measurement_progress
from tests.qt_test_utils import ensure_qapplication


def _row(
    voltage: float,
    current: float,
    *,
    point: int,
    direction: str,
    factor: int = 1,
) -> dict[str, object]:
    return {
        "Repeat": 1,
        "PointIndex": point,
        "SweepDirection": direction,
        "SetVoltageV": voltage,
        "PolarityFactor": factor,
        "MeasuredVoltageV": voltage * factor,
        "MeasuredCurrentA": current,
        "ComplianceTripped": False,
    }


class DarkIVChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_live_chart_uses_device_voltage_absolute_current_and_split_sweeps(self) -> None:
        dialog = DarkIVChartDialog()
        rows = (
            _row(-1.0, -1e-9, point=1, direction="forward", factor=-1),
            _row(0.0, 1e-10, point=2, direction="forward", factor=-1),
            _row(-1.0, -2e-9, point=3, direction="reverse", factor=-1),
        )
        for current, row in enumerate(rows, start=1):
            dialog.add_point(DarkIVPointProgress(
                channel="CH1",
                sample_id="Si",
                current=current,
                total=len(rows),
                row=row,
            ))
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())
        self.assertEqual("CH1", dialog.current_channel)
        self.assertEqual(3, dialog.point_count)
        self.assertEqual(2, dialog.series_count)
        self.assertEqual(-1.0, device_voltage_v(rows[0]))
        self.assertEqual(1e-9, current_magnitude_a(rows[0]))
        self.assertEqual("-2.000000e-09 A", dialog.current_value.text())
        self.assertEqual("|Current| (A)", dialog._current_axis.titleText())
        dialog.close()
        self.app.processEvents()
        self.assertFalse(dialog.isVisible())

    def test_png_contains_plot_and_footer_area(self) -> None:
        rows = [
            _row(-1.0, 1e-12, point=1, direction="forward"),
            _row(0.0, 1e-9, point=2, direction="forward"),
            _row(1.0, 1e-6, point=3, direction="forward"),
        ]
        footer = (
            "Timestamp: 2026-09-03T12:00:00+08:00 | Channel: CH1 | Sample ID: Si",
            "Sweep: -1 to 1 V | Step: 1 V | Direction: forward | Repeat: 1",
            "Dwell: 0 s | NPLC: 1 | Current compliance: 20 mA | Polarity factor: +1",
            "Axes: X=device-coordinate measured Voltage (V) | Y=|Current| (A), log10",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = save_dark_iv_plot_png(
                rows,
                Path(directory) / "dark_iv.png",
                channel="CH1",
                sample_id="Si",
                footer_lines=footer,
            )
            self.assertGreater(output.stat().st_size, 0)
            with Image.open(output) as image:
                self.assertEqual((1400, 1040), image.size)
                self.assertEqual((88, 88, 88, 255), image.getpixel((5, 900)))

    def test_main_window_progress_handler_creates_and_completes_live_chart(self) -> None:
        window = QWidget()
        window._measurement_progress_dialog = None
        window._dark_iv_progress_dialog = None
        window.status_message = SimpleNamespace(setText=Mock())
        point = DarkIVPointProgress(
            channel="CH2",
            sample_id="Device-B",
            current=1,
            total=1,
            row=_row(0.5, -3e-8, point=1, direction="forward"),
        )
        _on_measurement_progress(window, point)
        chart = window._dark_iv_progress_dialog
        self.assertIsInstance(chart, DarkIVChartDialog)
        self.assertTrue(chart.isVisible())
        self.assertEqual(1, chart.point_count)
        _on_measurement_progress(window, DarkIVScanCompleted(
            channel="CH2",
            sample_id="Device-B",
            total=1,
            png_path=r"D:\data\CH2_Device-B\DARK_IV\dark_iv.png",
        ))
        self.assertIn("dark_iv.png", chart.status_value.text())
        self.assertEqual(2, window.status_message.setText.call_count)
        chart.hide()
        chart.deleteLater()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
