from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QLabel

from gui.camera_controller import CameraController
from gui.camera_temperature_chart import CameraTemperatureChart
from gui.camera_temperature_monitor import (
    CameraTemperatureMonitor,
    CameraTemperatureUnsupportedError,
    STALE_AFTER_SECONDS,
    TemperatureSample,
    format_temperature_c,
)
from gui.image_io import save_image_and_metadata
from gui.main_window_devices import MainWindowDeviceMixin
from gui.sdk import nncam

from tests.qt_test_utils import ensure_qapplication


class CameraTemperatureControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_qapplication()

    def test_bundled_sdk_tenths_are_converted_to_celsius(self) -> None:
        controller = CameraController()
        controller._camera = SimpleNamespace(get_Temperature=Mock(return_value=403))
        controller._device = SimpleNamespace(
            model=SimpleNamespace(flag=nncam.NNCAM_FLAG_GETTEMPERATURE)
        )
        self.assertAlmostEqual(40.3, controller.read_temperature_c())
        controller._camera.get_Temperature.assert_called_once_with()

    def test_disconnected_camera_is_not_queried(self) -> None:
        controller = CameraController()
        self.assertIsNone(controller.read_temperature_c())

    def test_unsupported_camera_raises_specific_nonfatal_error(self) -> None:
        controller = CameraController()
        controller._camera = SimpleNamespace(get_Temperature=Mock())
        controller._device = SimpleNamespace(model=SimpleNamespace(flag=0))
        with self.assertRaises(CameraTemperatureUnsupportedError):
            controller.read_temperature_c()
        controller._camera.get_Temperature.assert_not_called()

    def test_camera_closing_is_emitted_before_sdk_handle_close(self) -> None:
        controller = CameraController()
        events: list[str] = []
        controller._camera = SimpleNamespace(Close=lambda: events.append("SDK_CLOSE"))
        controller._device = SimpleNamespace(model=SimpleNamespace(flag=0))
        controller.camera_closing.connect(lambda: events.append("MONITOR_STOP"))
        controller.close_camera()
        self.assertEqual(["MONITOR_STOP", "SDK_CLOSE"], events)


class CameraTemperatureMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_qapplication()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.connected = True
        self.values: list[object] = [39.8]
        self.queries = 0

        def read() -> float:
            self.queries += 1
            value = self.values.pop(0)
            if isinstance(value, BaseException):
                raise value
            return float(value)

        self.monitor = CameraTemperatureMonitor(
            read,
            lambda: self.connected,
            self.directory.name,
            interval_ms=60_000,
            history_limit=3,
        )

    def tearDown(self) -> None:
        self.monitor.stop()
        self.directory.cleanup()

    def test_disconnected_start_does_not_query_sdk(self) -> None:
        self.connected = False
        self.monitor.start()
        self.assertEqual(0, self.queries)
        self.assertTrue(self.monitor.is_running)

    def test_start_reads_emits_updates_latest_timestamp_and_creates_csv(self) -> None:
        received: list[TemperatureSample] = []
        self.monitor.sample_received.connect(received.append)
        self.monitor.start(camera_model="TestCam", camera_identifier="ABC")
        self.assertTrue(self.monitor.is_running)
        self.assertEqual(1, len(received))
        self.assertEqual(39.8, received[0].value_c)
        self.assertIsNotNone(received[0].timestamp.tzinfo)
        self.assertEqual(received[0], self.monitor.latest_snapshot())
        self.assertTrue(self.monitor.csv_path and self.monitor.csv_path.is_file())

    def test_multiple_samples_append_csv_and_rolling_history(self) -> None:
        self.values = [39.8, 40.1, 40.2, 40.3]
        self.monitor.start()
        self.monitor.poll_now()
        self.monitor.poll_now()
        self.monitor.poll_now()
        self.assertEqual([40.1, 40.2, 40.3], [item.value_c for item in self.monitor.history])
        self.monitor.stop()
        with self.monitor.csv_path.open("r", newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(4, len(rows))
        self.assertEqual(["timestamp", "temperature_c"], list(rows[0]))

    def test_csv_timestamp_is_timezone_aware_and_has_milliseconds(self) -> None:
        self.monitor.start()
        self.monitor.stop()
        with self.monitor.csv_path.open("r", newline="", encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        parsed = datetime.fromisoformat(row["timestamp"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertRegex(row["timestamp"], r"\.\d{3}[+-]\d{2}:\d{2}$")

    def test_temporary_error_is_nonfatal_and_next_poll_recovers(self) -> None:
        self.values = [RuntimeError("temporary"), 40.1]
        availability: list[bool] = []
        self.monitor.availability_changed.connect(availability.append)
        with self.assertLogs("gui.camera_temperature_monitor", level="WARNING"):
            self.monitor.start()
        self.assertTrue(self.monitor.is_running)
        self.assertIsNone(self.monitor.latest_snapshot())
        self.monitor.poll_now()
        self.assertEqual(40.1, self.monitor.latest_snapshot().value_c)
        self.assertIn(False, availability)
        self.assertTrue(availability[-1])

    def test_invalid_temperature_is_skipped_without_stopping_polling(self) -> None:
        self.values = [float("nan"), 40.2]
        with self.assertLogs("gui.camera_temperature_monitor", level="WARNING"):
            self.monitor.start()
        self.assertEqual(0, len(self.monitor.history))
        self.assertTrue(self.monitor.is_running)
        self.monitor.poll_now()
        self.assertEqual(40.2, self.monitor.latest_snapshot().value_c)

    def test_unsupported_stops_repeated_queries_without_ending_camera_session(self) -> None:
        self.values = [CameraTemperatureUnsupportedError("not supported")]
        with self.assertLogs("gui.camera_temperature_monitor", level="WARNING"):
            self.monitor.start()
        self.assertTrue(self.monitor.session_active)
        self.assertTrue(self.monitor.unsupported)
        self.assertFalse(self.monitor.is_running)
        self.monitor.poll_now()
        self.assertEqual(1, self.queries)

    def test_capability_flag_can_disable_polling_without_any_query(self) -> None:
        with self.assertLogs("gui.camera_temperature_monitor", level="WARNING"):
            self.monitor.start(supported=False)
        self.assertTrue(self.monitor.unsupported)
        self.assertEqual(0, self.queries)

    def test_disconnect_and_shutdown_stop_polling_and_clear_latest(self) -> None:
        self.values = [39.8, 40.1]
        self.monitor.start()
        self.monitor.stop()
        self.monitor.poll_now()
        self.assertEqual(1, self.queries)
        self.assertIsNone(self.monitor.latest_snapshot())
        self.assertFalse(self.monitor.is_running)
        self.monitor.shutdown()
        self.assertEqual(1, self.queries)

    def test_duplicate_start_does_not_duplicate_poll_or_timer_connection(self) -> None:
        self.values = [39.8, 40.1]
        received: list[TemperatureSample] = []
        self.monitor.sample_received.connect(received.append)
        self.monitor.start()
        self.monitor.start()
        self.assertEqual(1, self.queries)
        self.monitor.poll_now()
        self.assertEqual(2, self.queries)
        self.assertEqual(2, len(received))

    def test_latest_metadata_omits_unavailable_and_stale_values(self) -> None:
        self.assertEqual({}, self.monitor.metadata_fields())
        self.monitor.start()
        sample = self.monitor.latest_snapshot()
        fields = self.monitor.metadata_fields(reference_time=sample.timestamp)
        self.assertEqual(39.8, fields["CameraTemperature_C"])
        self.assertEqual(sample.timestamp_text(), fields["CameraTemperatureTimestamp"])
        stale_at = sample.timestamp + timedelta(seconds=STALE_AFTER_SECONDS + 0.1)
        self.assertEqual({}, self.monitor.metadata_fields(reference_time=stale_at))


class CameraTemperatureGUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_qapplication()

    def test_temperature_formatting_and_unavailable_gui(self) -> None:
        self.assertEqual("40.3 °C", format_temperature_c(40.3))
        self.assertEqual("N/A", format_temperature_c(None))
        fixture = SimpleNamespace(
            camera_temperature_value=QLabel("old"),
            temperature_status=QLabel("old"),
        )
        sample = TemperatureSample(40.34, datetime.now().astimezone())
        MainWindowDeviceMixin.on_temperature_sample(fixture, sample)
        self.assertEqual("40.3 °C", fixture.camera_temperature_value.text())
        MainWindowDeviceMixin.on_temperature_availability_changed(fixture, False)
        self.assertEqual("N/A", fixture.camera_temperature_value.text())
        self.assertEqual("相機溫度 N/A", fixture.temperature_status.text())

    def test_chart_updates_rolling_points_current_min_and_max(self) -> None:
        chart = CameraTemperatureChart(max_samples=2)
        now = datetime.now().astimezone()
        chart.add_sample(TemperatureSample(40.0, now))
        chart.add_sample(TemperatureSample(39.5, now + timedelta(seconds=1)))
        chart.add_sample(TemperatureSample(40.5, now + timedelta(seconds=2)))
        self.assertEqual(2, chart.sample_count)
        self.assertEqual(39.5, chart.session_min_c)
        self.assertEqual(40.5, chart.session_max_c)
        self.assertEqual(2, chart._series.count())

    def test_closing_chart_does_not_stop_monitor_or_logging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values = iter((39.8, 39.9))
            monitor = CameraTemperatureMonitor(
                lambda: next(values), lambda: True, directory, interval_ms=60_000
            )
            chart = CameraTemperatureChart()
            monitor.sample_received.connect(chart.add_sample)
            monitor.start()
            chart.show()
            chart.close()
            monitor.poll_now()
            self.assertTrue(monitor.is_running)
            self.assertEqual(2, chart.sample_count)
            self.assertTrue(monitor.csv_path.is_file())
            monitor.stop()


class CameraTemperatureMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_qapplication()

    @staticmethod
    def _image() -> QImage:
        image = QImage(3, 2, QImage.Format.Format_RGB888)
        image.fill(QColor(12, 34, 56))
        return image

    def test_regular_image_metadata_and_pixels_are_preserved(self) -> None:
        metadata = {
            "CameraTemperature_C": 40.37,
            "CameraTemperatureTimestamp": "2026-08-13T10:30:01.123+08:00",
        }
        with tempfile.TemporaryDirectory() as directory:
            output, sidecar = save_image_and_metadata(
                self._image(), str(Path(directory) / "capture.png"), metadata
            )
            saved = json.loads(sidecar.read_text(encoding="utf-8"))
            pixels = np.asarray(Image.open(output).convert("RGB"))
        self.assertEqual(metadata, saved)
        self.assertTrue(np.all(pixels == np.array([12, 34, 56], dtype=np.uint8)))

    def test_regular_tiff_png_jpeg_and_bmp_paths_all_get_sidecars(self) -> None:
        metadata = {"CameraTemperature_C": 39.8}
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".tif", ".png", ".jpg", ".bmp"):
                with self.subTest(suffix=suffix):
                    output, sidecar = save_image_and_metadata(
                        self._image(), str(Path(directory) / f"capture{suffix}"), metadata
                    )
                    self.assertTrue(output.is_file())
                    self.assertEqual(metadata, json.loads(sidecar.read_text(encoding="utf-8")))

    def test_unavailable_temperature_is_not_fabricated_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, sidecar = save_image_and_metadata(
                self._image(), str(Path(directory) / "capture.png"), {}
            )
            saved = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertNotIn("CameraTemperature_C", saved)
        self.assertNotIn(0, saved.values())

    def test_manual_capture_wiring_consumes_snapshot_instead_of_querying_sdk(self) -> None:
        source = (
            Path(__file__).parents[1] / "gui" / "main_window_devices.py"
        ).read_text(encoding="utf-8")
        save_method = source[source.index("    def _save_image(") : source.index("    def _choose_capture_path(")]
        self.assertIn("self.temperature_monitor.metadata_fields()", save_method)
        self.assertNotIn("read_temperature_c", save_method)

    def test_main_window_wires_start_and_pre_close_stop_once(self) -> None:
        devices_source = (
            Path(__file__).parents[1] / "gui" / "main_window_devices.py"
        ).read_text(encoding="utf-8")
        ui_source = (
            Path(__file__).parents[1] / "gui" / "main_window_ui.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(1, devices_source.count("self.temperature_monitor.start("))
        self.assertEqual(
            1,
            ui_source.count("self.controller.camera_closing.connect(self.temperature_monitor.stop)"),
        )

if __name__ == "__main__":
    unittest.main()
