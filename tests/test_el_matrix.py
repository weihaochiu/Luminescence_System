from __future__ import annotations

import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage

from gui.el_matrix_plan import ELMatrixPlan
from gui.camera_capture_bridge import CameraCaptureBridge
from gui.el_matrix_runner import CapturedFrame, ELMatrixRunner
from gui.measurement_output import (
    annotated_jpeg_image,
    format_dark_footer,
    format_el_footer,
    sanitize_filename,
    save_matrix_capture,
)
from gui.measurement_progress_dialog import MeasurementProgressDialog
from gui.recipe_store import Recipe
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import RecipeStore
from tests.qt_test_utils import ensure_qapplication


@dataclass
class _Readback:
    current_a: float = 0.0008
    voltage_v: float = 1.24


class _FakeHardware:
    def __init__(self, fail_capture: bool = False) -> None:
        self.events: list[object] = []
        self.fail_capture = fail_capture
        self.polarity_calls = 0
        self.default_polarity_calls = 0
        self.safe = False

    def prepare_shared_dark(self) -> None:
        self.events.append("prepare_dark")

    def route_channel(self, channel, _check_cancel) -> None:
        self.events.append(("route", channel))

    def run_polarity(self, channel, _check_cancel):
        self.polarity_calls += 1
        self.events.append(("polarity", channel.channel))
        return {
            "polarity_check_status": "COMPLETED",
            "polarity_result": "NORMAL",
            "polarity_factor": 1,
            "polarity_timestamp": "2026-08-14T06:00:00+08:00",
            "Jsc": {"representative": -10},
            "Voc": {"representative": 1.1},
        }

    def use_default_polarity(self, channel):
        self.default_polarity_calls += 1
        self.events.append(("default_polarity", channel.channel))
        return {
            "polarity_check_status": "SKIPPED",
            "polarity_result": "STANDARD_WIRING",
            "polarity_factor": 1,
        }

    def set_current(self, current_a, compliance):
        self.events.append(("set_current", current_a, compliance))
        return current_a

    def readback(self):
        self.events.append("readback")
        return _Readback()

    def capture(self, exposure, gain, _timeout, _check_cancel):
        self.events.append(("capture", exposure, gain))
        if self.fail_capture:
            raise RuntimeError("camera failed")
        image = QImage(4, 3, QImage.Format.Format_RGB888)
        image.fill(QColor(10, 20, 30))
        return CapturedFrame(
            image,
            datetime(2026, 8, 14, 6, 44, 12).astimezone(),
            39.8,
            {"CameraModel": "Fake", "CameraSerial": "SN1", "PixelFormat": "RGB24", "BitDepth": 8},
        )

    def output_off(self):
        self.events.append("output_off")

    def clear_routing(self):
        self.events.append("clear_routing")

    def safe_shutdown(self):
        self.safe = True
        self.events.append("safe_shutdown")


def _small_recipe(channel_count: int = 2) -> Recipe:
    recipe = Recipe()
    for index, channel in enumerate(recipe.channels):
        channel.enabled = index < channel_count
        channel.sample_id = f"Sample/{index + 1}"
        channel.area_cm2 = 0.1 + index * 0.1
    recipe.el_matrix.current_density_ma_cm2 = [2.0, 4.0]
    recipe.el_matrix.gains_percent = [100, 200]
    recipe.el_matrix.exposures_ms = [1.0]
    recipe.el_matrix.repeat = 1
    recipe.el_matrix.stabilization_ms = 0
    recipe.el_matrix.estimated_capture_overhead_s = 0
    recipe.el_matrix.estimated_polarity_duration_s = 0
    recipe.el_matrix.estimated_routing_transition_s = 0
    recipe.el_matrix.estimated_shared_dark_overhead_s = 0
    return recipe


class ELMatrixRecipeAndPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_recipe_dialog_exposes_fixed_channel_table_and_shared_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            store.upsert(Recipe())
            dialog = RecipeManagerDialog(store)
            self.app.processEvents()
            self.assertEqual(4, dialog.channels_table.rowCount())
            self.assertEqual("CH1", dialog.channels_table.item(0, 1).text())
            self.assertTrue(dialog.matrix_current_density_edit.text())
            self.assertTrue(dialog.shared_dark_enabled_check.isChecked())
            dialog.close()
    def test_enabled_channels_are_fixed_order_and_disabled_are_skipped(self) -> None:
        recipe = _small_recipe(3)
        recipe.channels[1].enabled = False
        self.assertEqual(["CH1", "CH3"], [item.channel for item in recipe.enabled_channels()])

    def test_channel_counts_one_through_four_do_not_multiply_shared_dark(self) -> None:
        for count in range(1, 5):
            recipe = _small_recipe(count)
            counts = recipe.matrix_capture_counts()
            self.assertEqual(2, counts["shared_dark"])
            self.assertEqual(count * 4, counts["total_el"])
            self.assertEqual(2 + count * 4, counts["overall"])

    def test_validation_rejects_invalid_channel_area_j_repeat_gain_exposure_and_compliance(self) -> None:
        cases = []
        recipe = _small_recipe(1); recipe.channels[0].area_cm2 = 0; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.current_density_ma_cm2 = [0]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.current_density_ma_cm2 = [-1]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.repeat = 0; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.gains_percent = [-1]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.exposures_ms = [0]; cases.append(recipe)
        recipe = _small_recipe(1); recipe.el_matrix.voltage_compliance_v = 99; cases.append(recipe)
        for recipe in cases:
            with self.subTest(recipe=recipe.to_dict()):
                self.assertTrue(recipe.validate())

    def test_matrix_order_is_channel_j_gain_exposure_repeat(self) -> None:
        recipe = _small_recipe(2)
        recipe.el_matrix.exposures_ms = [1, 2]
        recipe.el_matrix.repeat = 2
        el = [capture for capture in ELMatrixPlan(recipe).captures() if capture.measurement_type == "EL"]
        keys = [
            (item.channel, item.current_density_ma_cm2, item.gain_percent, item.exposure_ms, item.repeat_index)
            for item in el
        ]
        self.assertEqual(("CH1", 2, 100, 1, 1), keys[0])
        self.assertEqual(("CH1", 2, 100, 1, 2), keys[1])
        self.assertEqual(("CH1", 2, 100, 2, 1), keys[2])
        self.assertLess(keys.index(("CH1", 4, 100, 1, 1)), keys.index(("CH2", 2, 100, 1, 1)))

    def test_eta_dark_once_stabilization_per_channel_j_and_mock_finish(self) -> None:
        recipe = _small_recipe(2)
        recipe.el_matrix.stabilization_ms = 500
        recipe.el_matrix.estimated_polarity_duration_s = 3
        recipe.el_matrix.estimated_routing_transition_s = 2
        recipe.el_matrix.estimated_shared_dark_overhead_s = 1
        now = datetime(2026, 8, 14, 6, 0, 0).astimezone()
        estimate = ELMatrixPlan(recipe).estimate(now)
        # Exposure: dark 2 ms + EL (2 ch * 2 J * 2 gain * 1 ms) = 10 ms.
        expected = 0.010 + (2 * 2 * 0.5) + (2 * 3) + (2 * 2) + 1
        self.assertAlmostEqual(expected, estimate.total_time_s, places=6)
        self.assertEqual(now.timestamp() + expected, estimate.estimated_finish.timestamp())


class ELMatrixRunnerTests(unittest.TestCase):
    def test_runner_dark_once_stabilizes_once_per_j_and_keeps_output_during_inner_matrix(self) -> None:
        recipe = _small_recipe(2)
        hardware = _FakeHardware()
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            result = ELMatrixRunner(
                recipe, hardware, directory,
                report_progress=progress.append,
                is_cancel_requested=lambda: False,
                now=lambda: datetime(2026, 8, 14, 6, 0, 0).astimezone(),
            ).run()
            self.assertTrue(Path(result["output_directory"]).is_dir())
        self.assertEqual(1, hardware.events.count("prepare_dark"))
        self.assertEqual(2, hardware.polarity_calls)
        self.assertEqual(4, len([event for event in hardware.events if isinstance(event, tuple) and event[0] == "set_current"]))
        self.assertTrue(hardware.safe)
        completed = [item.current for item in progress]
        self.assertEqual(sorted(completed), completed)
        self.assertEqual(recipe.matrix_capture_counts()["overall"], completed[-1])
        # Every route is preceded by both authoritative OUTPUT OFF and routing clear.
        for index, event in enumerate(hardware.events):
            if isinstance(event, tuple) and event[0] == "route":
                self.assertIn("output_off", hardware.events[:index])
                self.assertEqual("clear_routing", hardware.events[index - 1])

    def test_skip_polarity_never_reuses_previous_channel_result(self) -> None:
        recipe = _small_recipe(3)
        recipe.polarity.enabled = False
        hardware = _FakeHardware()
        with tempfile.TemporaryDirectory() as directory:
            ELMatrixRunner(
                recipe, hardware, directory,
                report_progress=lambda _item: None,
                is_cancel_requested=lambda: False,
            ).run()
        self.assertEqual(0, hardware.polarity_calls)
        self.assertEqual(3, hardware.default_polarity_calls)

    def test_runtime_error_always_reaches_shared_safe_shutdown(self) -> None:
        recipe = _small_recipe(1)
        hardware = _FakeHardware(fail_capture=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "camera failed"):
                ELMatrixRunner(
                    recipe, hardware, directory,
                    report_progress=lambda _item: None,
                    is_cancel_requested=lambda: False,
                ).run()
        self.assertTrue(hardware.safe)


class MatrixImageOutputTests(unittest.TestCase):
    def _metadata(self, measurement_type: str = "EL") -> dict[str, object]:
        return {
            "MeasurementType": measurement_type,
            "SampleID": "perovskite/TOPCon",
            "Channel": "CH1" if measurement_type == "EL" else "SHARED",
            "CommandedCurrentDensity": 12,
            "Gain": 500,
            "Exposure": 6000,
            "RepeatIndex": 1,
            "RepeatTotal": 1,
            "MeasuredCurrentMa": 1.19800000000003,
            "MeasuredVoltage": 1.24,
            "CameraTemperature": 39.8,
            "Timestamp": "2026-08-14 06:44:12",
            "ApplicableChannels": ["CH1", "CH2", "CH3"],
        }

    def test_raw_tiff_keeps_dimensions_and_pixels_while_jpeg_footer_is_below(self) -> None:
        raw = Image.new("RGB", (8, 6))
        raw.putdata([(index, index + 1, index + 2) for index in range(48)])
        before = raw.tobytes()
        with tempfile.TemporaryDirectory() as directory:
            saved = save_matrix_capture(raw, Path(directory) / "capture", self._metadata())
            with Image.open(saved.tiff_path) as tiff:
                self.assertEqual((8, 6), tiff.size)
                self.assertEqual(before, tiff.convert("RGB").tobytes())
            with Image.open(saved.jpeg_path) as jpeg:
                self.assertEqual(8, jpeg.width)
                self.assertGreater(jpeg.height, 6)
        self.assertEqual(before, raw.tobytes())

    def test_uncompressed_annotated_buffer_preserves_the_complete_source_region(self) -> None:
        raw = Image.new("RGB", (200, 60), (12, 34, 56))
        annotated = annotated_jpeg_image(raw, format_el_footer(self._metadata()))
        self.assertEqual(raw.tobytes(), annotated.crop((0, 0, raw.width, raw.height)).tobytes())

    def test_footer_formatters_and_filename_sanitization(self) -> None:
        el_lines = "\n".join(format_el_footer(self._metadata()))
        for expected in ("perovskite/TOPCon", "CH1", "J=12", "Gain=500%", "6,000 ms", "1.198 mA", "1.24 V", "39.8 °C"):
            self.assertIn(expected, el_lines)
        dark_lines = "\n".join(format_dark_footer(self._metadata("DARK")))
        self.assertIn("Shared Dark", dark_lines)
        self.assertIn("CH1, CH2, CH3", dark_lines)
        self.assertNotIn("J=0", dark_lines)
        self.assertEqual("perovskite_TOPCon", sanitize_filename("perovskite/TOPCon"))


class _FakeCameraController(QObject):
    frame_ready = Signal(QImage)

    def __init__(self) -> None:
        super().__init__()
        self.is_open = True
        self.device_name = "Fake Camera"
        self.requested = (0, 0)
        self.configure_calls = 0

    def set_manual_exposure(self, exposure_us: int, gain: int) -> None:
        self.configure_calls += 1
        self.requested = (exposure_us, gain)

    def current_exposure(self):
        return self.requested

    def read_temperature_c(self):
        return 39.8


class CameraCaptureBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_bridge_reuses_one_existing_live_frame_without_second_capture(self) -> None:
        controller = _FakeCameraController()
        bridge = CameraCaptureBridge(controller)
        result: list[CapturedFrame] = []
        failure: list[Exception] = []

        def worker() -> None:
            try:
                result.append(bridge.capture(50, 200, 2, lambda: None))
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 1
        while controller.configure_calls == 0 and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        image = QImage(5, 4, QImage.Format.Format_RGB888)
        image.fill(QColor(1, 2, 3))
        controller.frame_ready.emit(image)
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        thread.join(timeout=0.1)
        self.assertFalse(failure)
        self.assertEqual(1, controller.configure_calls)
        self.assertEqual(1, len(result))
        self.assertEqual((5, 4), (result[0].image.width(), result[0].image.height()))

    def test_progress_window_is_modeless_and_close_does_not_request_stop(self) -> None:
        dialog = MeasurementProgressDialog("EL_Matrix_Standard")
        stops: list[bool] = []
        dialog.stop_requested.connect(lambda: stops.append(True))
        self.assertFalse(dialog.isModal())
        dialog.show()
        self.app.processEvents()
        dialog.close()
        self.app.processEvents()
        self.assertFalse(stops)
        self.assertFalse(dialog.isVisible())
        dialog.set_stopped()


if __name__ == "__main__":
    unittest.main()
