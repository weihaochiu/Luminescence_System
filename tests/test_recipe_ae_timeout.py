from __future__ import annotations

from dataclasses import asdict
import gc
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
import weakref

from gui.camera_capture_bridge import CameraCaptureBridge
from gui.camera_controller import CameraController
from gui.el_matrix_plan import ELMatrixPlan
from gui.el_matrix_runner import ELMatrixRunner
from gui.measurement_worker import MeasurementCancelled
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import Recipe, RecipeStore
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_recipe_auto_exposure import AutoCamera, AutoHardware, auto_recipe


class RecipeAETimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def test_new_default_is_budgeted_and_explicit_saved_timeouts_are_preserved(self):
        recipe = auto_recipe()
        self.assertEqual(120, recipe.el_matrix.auto_timeout_s)
        self.assertEqual(240, ELMatrixPlan(recipe).estimate().auto_exposure_time_s)
        self.assertEqual(120, Recipe.from_dict({}).el_matrix.auto_timeout_s)
        for timeout in (30, 60, 180):
            with self.subTest(timeout=timeout):
                recipe.el_matrix.auto_timeout_s = timeout
                loaded = Recipe.from_dict(recipe.to_dict())
                self.assertEqual(timeout, loaded.el_matrix.auto_timeout_s)
                self.assertEqual(2 * timeout, ELMatrixPlan(loaded).estimate().auto_exposure_time_s)

    def test_existing_recipe_can_apply_save_and_reload_120_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            recipe = auto_recipe()
            recipe.el_matrix.auto_timeout_s = 60
            store.upsert(recipe)
            dialog = RecipeManagerDialog(store)
            try:
                self.assertEqual(60, dialog.auto_timeout_spin.value())
                previous_estimate = ELMatrixPlan(dialog._read_form_to_recipe()).estimate()
                dialog.auto_timeout_recommended_button.click()
                self.assertEqual(120, dialog.auto_timeout_spin.value())
                updated_estimate = ELMatrixPlan(dialog._read_form_to_recipe()).estimate()
                self.assertAlmostEqual(previous_estimate.total_time_s + 120, updated_estimate.total_time_s)
                self.assertEqual(60, RecipeStore(store.path).get(recipe.recipe_id).el_matrix.auto_timeout_s)
                with patch("gui.recipe_dialog_logic.QMessageBox.information"):
                    dialog._save_current()
                saved = RecipeStore(store.path).get(recipe.recipe_id)
                self.assertEqual(120, saved.el_matrix.auto_timeout_s)
                expected = recipe.to_dict()
                actual = saved.to_dict()
                self.assertEqual(expected["el_matrix"] | {"auto_timeout_s": 120}, actual["el_matrix"])
                dialog._reload_list(preferred_id=recipe.recipe_id)
                self.assertEqual(120, dialog.auto_timeout_spin.value())
            finally:
                dialog.close()

    def test_timeout_button_does_not_keep_closed_editor_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            store.upsert(auto_recipe())
            dialog = RecipeManagerDialog(store)
            reference = weakref.ref(dialog)
            dialog.auto_timeout_recommended_button.click()
            dialog.close()
            del dialog
            gc.collect()
            self.assertIsNone(reference())

    def run_virtual_ae(self, *, timeout=120, outcome="converged"):
        controller = CameraController()
        controller._camera = camera = AutoCamera()
        controller._width, controller._height = 4, 3
        controller._camera_is_mono = True
        controller._scientific_pull_bits = 16
        controller._auto_exposure_roi_readback = (0, 0, 4, 3)
        controller._auto_exposure_roi_verified = True
        self.addCleanup(controller.close_camera)
        bridge = CameraCaptureBridge(controller)
        settings = asdict(auto_recipe().el_matrix)
        settings["auto_timeout_s"] = timeout
        tick = [0.0]

        class FrameIntervalEvent(Event):
            """Advance virtual time by one 5 s frame without hardware or sleeps."""

            def wait(self, _timeout=None):
                if not self.is_set():
                    tick[0] += 5
                    if tick[0] == 75 and outcome in {"converged", "sdk_failed"}:
                        camera.exposure_us, camera.gain = 5_000_000, 338
                        controller._handle_sdk_event(
                            nncam.NNCAM_EVENT_AUTOEXPO_CONV if outcome == "converged"
                            else nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL
                        )
                return self.is_set()

        def cancel():
            if tick[0] >= 75 and outcome == "cancelled":
                raise MeasurementCancelled()

        result = error = None
        with patch("gui.camera_capture_bridge.monotonic", side_effect=lambda: tick[0]), \
                patch("gui.camera_capture_bridge.Event", FrameIntervalEvent):
            try:
                result = bridge.auto_exposure(settings, cancel)
            except Exception as exc:
                error = exc
        self.assertEqual(0, camera.auto_exposure_enable)
        self.assertEqual((350000, 30, 500, 100), camera.auto_range)
        self.assertIsNone(bridge._pending_ae)
        return result, error, tick[0]

    def test_long_exposure_convergence_after_60_seconds_is_accepted_with_120(self):
        result, error, elapsed = self.run_virtual_ae()
        self.assertIsNone(error)
        self.assertEqual(75, elapsed)
        self.assertEqual((5_000_000, 338), (result["exposure_us"], result["gain_percent"]))

    def test_explicit_60_seconds_still_times_out_before_late_convergence(self):
        result, error, elapsed = self.run_virtual_ae(timeout=60)
        self.assertIsNone(result)
        self.assertIsInstance(error, TimeoutError)
        self.assertEqual(60, elapsed)

    def test_120_seconds_remains_a_hard_timeout_without_convergence(self):
        result, error, elapsed = self.run_virtual_ae(outcome="no_result")
        self.assertIsNone(result)
        self.assertIsInstance(error, TimeoutError)
        self.assertEqual(120, elapsed)

    def test_late_sdk_failure_is_not_accepted_as_convergence(self):
        result, error, elapsed = self.run_virtual_ae(outcome="sdk_failed")
        self.assertIsNone(result)
        self.assertIsInstance(error, RuntimeError)
        self.assertNotIsInstance(error, TimeoutError)
        self.assertEqual(75, elapsed)

    def test_cancellation_during_extended_wait_restores_camera(self):
        result, error, elapsed = self.run_virtual_ae(outcome="cancelled")
        self.assertIsNone(result)
        self.assertIsInstance(error, MeasurementCancelled)
        self.assertEqual(75, elapsed)

    def test_global_output_watchdog_can_stop_ae_before_recipe_timeout(self):
        tick = [0.0]

        class WatchdogHardware(AutoHardware):
            def auto_exposure(self, settings, check_cancel):
                tick[0] = 31.0
                check_cancel()
                raise AssertionError("Output watchdog did not stop AE")

        hardware = WatchdogHardware()
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(
                auto_recipe(), hardware, directory,
                report_progress=lambda _p: None, is_cancel_requested=lambda: False,
                max_output_time_s=30,
            )
            with patch("gui.el_matrix_runner.monotonic", side_effect=lambda: tick[0]):
                with self.assertRaisesRegex(RuntimeError, "max_output_time_s"):
                    runner.run()
            self.assertTrue(hardware.safe)
            self.assertEqual(0, runner._completed)


if __name__ == "__main__":
    unittest.main()
