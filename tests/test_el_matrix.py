from __future__ import annotations

import tempfile
import json
import threading
import time
import unittest
from types import SimpleNamespace
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tifffile
from PIL import Image
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage

from gui.el_matrix_plan import ELMatrixPlan
from gui.el_matrix_preflight import collect_preflight_errors
from gui.camera_capture_bridge import CameraCaptureBridge
from gui.el_matrix_runner import CapturedFrame, ELMatrixRunner
from gui.measurement_snapshot import (
    build_el_matrix_snapshot,
    snapshot_payload,
    verify_snapshot_hash,
)
from gui.measurement_output import (
    annotated_jpeg_image,
    format_dark_footer,
    format_el_footer,
    sanitize_filename,
    save_matrix_capture,
    save_pixel_csv_products,
)
from gui.measurement_progress_dialog import MeasurementProgressDialog
from gui.main_window_devices import MainWindowDeviceMixin
from gui.recipe_store import Recipe
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import RecipeStore
from gui.polarity_settings import PolarityMeasurementSettings
from gui.relay_settings import RelaySettings
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

    def apply_polarity_factor(self, factor):
        self.events.append(("apply_polarity", factor))

    def prepare_channel_dark(self):
        self.events.append("prepare_channel_dark")

    def run_dark_iv(self, _settings, _check_cancel):
        self.events.append("dark_iv")
        return [{"Repeat": 1, "PointIndex": 1, "CommandedVoltageV": 0.0}]

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
            {"CameraModel": "Fake", "CameraSerial": "SN1", "PixelFormat": "RGB48", "BitDepth": 12},
            np.full((3, 4, 3), 1024, dtype=np.uint16),
        )

    def output_off(self):
        self.events.append("output_off")

    def clear_routing(self):
        self.events.append("clear_routing")

    def safe_shutdown(self):
        self.safe = True
        self.events.append("safe_shutdown")
        return {
            "smu_output_off": True,
            "routing_off": True,
            "white_light_off": True,
            "ownership_released": True,
            "ok": True,
        }


def _small_recipe(channel_count: int = 2) -> Recipe:
    recipe = Recipe()
    for index, channel in enumerate(recipe.channels):
        channel.enabled = index < channel_count
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
    recipe.dark_iv.dark_stabilization_s = 0
    recipe.dark_iv.start_v = 0
    recipe.dark_iv.stop_v = 0.1
    recipe.dark_iv.step_v = 0.1
    recipe.dark_iv.dwell_s = 0
    recipe.dark_iv.nplc = 0
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
            self.assertTrue(dialog.dark_frame_enabled_check.isChecked())
            self.assertEqual(4, dialog.tabs.count())
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
        dark_iv = 2 * recipe.dark_iv_estimated_time_s()
        expected = 0.010 + (2 * 2 * 0.5) + (2 * 3) + (2 * 2 * 2) + 1 + dark_iv
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
                sample_ids={"CH1": "Sample/A", "CH2": "Sample B"},
                now=lambda: datetime(2026, 8, 14, 6, 0, 0).astimezone(),
            ).run()
            run_directory = Path(result["output_directory"])
            self.assertTrue(run_directory.is_dir())
            self.assertTrue((run_directory / "measurement_snapshot.json").is_file())
            self.assertTrue(Path(result["final_manifest"]).is_file())
            self.assertTrue((run_directory / "CH1_Sample_A").is_dir())
            self.assertTrue((run_directory / "CH2_Sample B").is_dir())
            manifest = (run_directory / "measurement_manifest.csv").read_text(
                encoding="utf-8-sig"
            )
            self.assertIn("Sample/A", manifest)
            self.assertIn("Sample B", manifest)
        self.assertEqual(1, hardware.events.count("prepare_dark"))
        self.assertEqual(2, hardware.polarity_calls)
        self.assertEqual(2, hardware.events.count("dark_iv"))
        self.assertEqual(4, len([event for event in hardware.events if isinstance(event, tuple) and event[0] == "set_current"]))
        self.assertTrue(hardware.safe)
        completed = [item.current for item in progress]
        self.assertEqual(sorted(completed), completed)
        remaining = [item.remaining_time_s for item in progress]
        self.assertEqual(sorted(remaining, reverse=True), remaining)
        finishes = [item.estimated_finish for item in progress]
        self.assertEqual(sorted(finishes, reverse=True), finishes)
        self.assertEqual(recipe.matrix_capture_counts()["overall"], completed[-1])
        # Every route is preceded by both authoritative OUTPUT OFF and routing clear.
        for index, event in enumerate(hardware.events):
            if isinstance(event, tuple) and event[0] == "route":
                self.assertIn("output_off", hardware.events[:index])
                self.assertEqual("clear_routing", hardware.events[index - 1])

    def test_polarity_can_be_disabled_and_is_removed_from_execution(self) -> None:
        recipe = _small_recipe(3)
        recipe.polarity.enabled = False
        self.assertEqual([], recipe.validate())
        self.assertEqual(3, len(ELMatrixPlan(recipe).channels))

    def test_all_polarities_precede_shared_dark_and_channel_dark_iv(self) -> None:
        recipe = _small_recipe(2)
        hardware = _FakeHardware()
        with tempfile.TemporaryDirectory() as directory:
            ELMatrixRunner(recipe, hardware, directory,
                           report_progress=lambda _item: None,
                           is_cancel_requested=lambda: False).run()
        polarity_positions = [i for i, event in enumerate(hardware.events)
                              if isinstance(event, tuple) and event[0] == "polarity"]
        shared_position = hardware.events.index("prepare_dark")
        self.assertTrue(all(position < shared_position for position in polarity_positions))
        self.assertEqual(2, hardware.events.count("dark_iv"))
        for position, event in enumerate(hardware.events):
            if event == "dark_iv":
                self.assertIn("output_off", hardware.events[position + 1:])

    def test_matrix_time_estimates_remain_available_for_global_watchdogs(self) -> None:
        four = Recipe()
        for channel in four.channels:
            channel.enabled = True
        self.assertGreater(four.matrix_estimated_time_s(), 4500)

        repeat = Recipe()
        repeat.el_matrix.current_density_ma_cm2 = [2]
        repeat.el_matrix.repeat = 10
        self.assertAlmostEqual(1806.925, repeat.matrix_output_on_time_s(), places=3)

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

    def test_relay_smu_save_and_cancel_failures_all_use_safe_shutdown(self) -> None:
        recipe = _small_recipe(1)
        for stage in ("relay", "smu", "save", "cancel"):
            hardware = _FakeHardware()
            if stage == "relay":
                hardware.route_channel = lambda *_args: (_ for _ in ()).throw(RuntimeError("relay failed"))
            elif stage == "smu":
                hardware.set_current = lambda *_args: (_ for _ in ()).throw(RuntimeError("smu failed"))
            cancel_calls = 0
            def cancelled() -> bool:
                nonlocal cancel_calls
                cancel_calls += 1
                return stage == "cancel" and cancel_calls > 2
            target = "gui.el_matrix_runner.save_matrix_capture" if stage == "save" else "builtins.id"
            replacement = (
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("save failed"))
                if stage == "save" else id
            )
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                with patch(target, replacement):
                    with self.assertRaises(Exception):
                        ELMatrixRunner(
                            recipe, hardware, directory,
                            report_progress=lambda _item: None,
                            is_cancel_requested=cancelled,
                        ).run()
                self.assertTrue(hardware.safe)

    def test_safe_shutdown_failure_cannot_report_completion(self) -> None:
        recipe = _small_recipe(1)
        hardware = _FakeHardware()
        def failed_shutdown():
            hardware.events.append("safe_shutdown_failed")
            raise RuntimeError("safe shutdown verification failed")
        hardware.safe_shutdown = failed_shutdown
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "safe shutdown"):
                ELMatrixRunner(
                    recipe, hardware, directory,
                    report_progress=lambda _item: None,
                    is_cancel_requested=lambda: False,
                ).run()


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
        raw = np.arange(8 * 6, dtype=np.uint16).reshape(6, 8)
        before = raw.copy()
        output = Recipe().output
        with tempfile.TemporaryDirectory() as directory:
            saved = save_matrix_capture(
                raw, Image.new("L", (8, 6)), Path(directory) / "capture",
                self._metadata(), output,
            )
            payload = json.loads(saved.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(str(saved.tiff_path), payload["RawTiffPath"])
            self.assertEqual(str(saved.footer_jpeg_path), payload["AnnotatedJpegPath"])
            self.assertEqual(str(saved.metadata_path), payload["MetadataJsonPath"])
            tiff = tifffile.imread(saved.tiff_path)
            np.testing.assert_array_equal(before, tiff)
            with Image.open(saved.footer_jpeg_path) as jpeg:
                self.assertEqual(8, jpeg.width)
                self.assertGreater(jpeg.height, 6)
        np.testing.assert_array_equal(before, raw)

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

    def test_pixel_csv_products_follow_output_options(self) -> None:
        recipe = Recipe()
        recipe.output.export_pixel_csv = True
        image = Image.new("RGB", (2, 1), (10, 20, 30))
        dark = Image.new("RGB", (2, 1), (1, 2, 3))
        with tempfile.TemporaryDirectory() as directory:
            paths = save_pixel_csv_products(
                image, Path(directory) / "capture", recipe.output,
                dark_image=dark, exposure_ms=10,
            )
            self.assertEqual({"RAW", "DarkCorrected"}, set(paths))
            for path in paths.values():
                self.assertTrue(Path(path).is_file())


class MeasurementSnapshotAndPreflightTests(unittest.TestCase):
    def test_snapshot_is_deep_immutable_and_hash_matches_saved_content(self) -> None:
        recipe = _small_recipe(1)
        snapshot = build_el_matrix_snapshot(
            recipe, execution_order=[{"phase": "polarity"}],
            camera={"CameraModel": "Fake", "ImageWidth": 4, "ImageHeight": 3,
                    "Resolution": "4x3", "PixelFormat": "RGB24", "BitDepth": 8},
            smu={"model": "B2901BL"}, relay_mapping={"Ch1": 5},
            polarity_settings=PolarityMeasurementSettings(),
            sample_ids={"CH1": "ORIGINAL"},
        )
        recipe.channels[0].area_cm2 = 999
        self.assertNotIn("sample_id", snapshot["recipe"]["complete_snapshot"]["channels"][0])
        self.assertEqual("ORIGINAL", snapshot["channels"][0]["sample_id"])
        self.assertTrue(verify_snapshot_hash(snapshot))
        with self.assertRaises(TypeError):
            snapshot["camera"]["CameraModel"] = "changed"

    def test_preflight_aggregates_visa_and_relay_mapping_mismatch(self) -> None:
        recipe = _small_recipe(1)
        relay = RelaySettings.defaults()
        relay.smu_output_channels["Ch2"] = relay.smu_output_channels["Ch1"]
        camera = {"Resolution": "4x3", "PixelFormat": "RGB24", "BitDepth": 8,
                  "ImageWidth": 4, "ImageHeight": 3}
        current = dict(camera)
        current.update({"exposure_range_us": (1, 1000000, 1), "gain_range": (0, 500, 1)})
        with tempfile.TemporaryDirectory() as directory:
            errors = collect_preflight_errors(
                recipe,
                smu_metadata={"connected": True, "supported": True,
                              "manufacturer": "Keysight Technologies", "model": "B2901BL",
                              "visa_address": "USB::ACTUAL"},
                smu_output_confirmed_off=True, relay_connected=True,
                relay_settings=relay, camera_connected=True,
                camera_snapshot=camera, current_camera=current, output_root=directory,
            )
        self.assertFalse(any("VISA" in item for item in errors))
        self.assertTrue(any("不可重複" in item or "不完整或不唯一" in item for item in errors))


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


class _SequencedCameraController(_FakeCameraController):
    frame_ready_sequenced = Signal(QImage, int)

    def __init__(self) -> None:
        super().__init__()
        self.frame_sequence = 10


class CameraCaptureBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_bridge_reuses_one_existing_live_frame_without_second_capture(self) -> None:
        controller = _FakeCameraController()
        bridge = CameraCaptureBridge(controller)
        result: list[CapturedFrame] = []
        live_view: list[QImage] = []
        controller.frame_ready.connect(lambda image: live_view.append(image.copy()))
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
        self.assertEqual(1, len(live_view))
        self.assertEqual((5, 4), (result[0].image.width(), result[0].image.height()))

    def test_bridge_discards_queued_old_generation_after_setting_change(self) -> None:
        controller = _SequencedCameraController()
        bridge = CameraCaptureBridge(controller)
        result: list[CapturedFrame] = []
        thread = threading.Thread(
            target=lambda: result.append(bridge.capture(50, 200, 2, lambda: None))
        )
        thread.start()
        deadline = time.monotonic() + 1
        while controller.configure_calls == 0 and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.005)
        old = QImage(2, 2, QImage.Format.Format_RGB888); old.fill(QColor(255, 0, 0))
        new = QImage(3, 2, QImage.Format.Format_RGB888); new.fill(QColor(0, 255, 0))
        controller.frame_ready_sequenced.emit(old, 10)
        controller.frame_sequence = 11
        controller.frame_ready_sequenced.emit(new, 11)
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.005)
        thread.join(timeout=0.1)
        self.assertEqual((3, 2), (result[0].image.width(), result[0].image.height()))

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

    def test_live_view_updates_without_reenabling_capture_controls(self) -> None:
        class _Widget:
            def __init__(self): self.enabled = True; self.value = None
            def setEnabled(self, value): self.enabled = bool(value)
            def setText(self, value): self.value = value
        class _View:
            def __init__(self): self.image = None
            def set_image(self, image): self.image = image.copy()
        window = SimpleNamespace(
            _measurement_worker=object(), last_image=None, image_view=_View(),
            resolution_status=_Widget(), capture_button=_Widget(),
            auto_capture_button=_Widget(), capture_action=_Widget(),
            auto_capture_action=_Widget(), _capture_next_frame=False,
            _pending_auto_path=None,
        )
        image = QImage(7, 5, QImage.Format.Format_RGB888)
        MainWindowDeviceMixin.on_frame_ready(window, image)
        self.assertEqual((7, 5), (window.image_view.image.width(), window.image_view.image.height()))
        for name in ("capture_button", "auto_capture_button", "capture_action", "auto_capture_action"):
            self.assertFalse(getattr(window, name).enabled)


if __name__ == "__main__":
    unittest.main()
