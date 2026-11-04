from __future__ import annotations

import csv
import tempfile
import threading
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.camera_capture_bridge import CameraCaptureBridge
from gui.camera_controller import CameraController, SDKAutoExposureMode
from gui.camera_recipe_ae import begin_recipe_ae, restore_recipe_ae
from gui.el_matrix_plan import ELMatrixPlan
from gui.el_matrix_runner import ELMatrixRunner
from gui.el_matrix_preflight import collect_preflight_errors
from gui.main_window_measurement import _validate_camera_matrix, _measurement_summary
from gui.measurement_execution_plan import build_measurement_execution_plan
from gui.measurement_worker import MeasurementCancelled
from gui.pixel_csv_postprocessor import PixelCSVPostprocessor
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import Recipe, RecipeStore
from gui.relay_settings import RelaySettings
from gui.smu_control import SMUSafetyLimits
from core.i18n import tr
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_camera_exposure import FakeModeCamera
from tests.test_camera_scientific import _FakeMonoCamera, _install_frame, _open
from tests.test_el_matrix import _FakeHardware


def auto_recipe() -> Recipe:
    recipe = Recipe()
    recipe.polarity.enabled = False
    recipe.dark_iv.enabled = False
    recipe.el_matrix.current_density_ma_cm2 = [2, 4]
    recipe.el_matrix.exposure_mode = "auto"
    recipe.el_matrix.repeat = 2
    return recipe


class AutoCamera(FakeModeCamera):
    def __init__(self):
        super().__init__()
        self.auto_range = (350000, 30, 500, 100)

    def get_AutoExpoRange(self):
        return self.auto_range

    def put_AutoExpoRange(self, *values):
        self.calls.append(("ae_range", *values))
        self.auto_range = tuple(values)

    def get_ExpTimeRange(self):
        return 30, 15000000, 10000

    def get_ExpoAGainRange(self):
        return 100, 800, 100


class AutoHardware(_FakeHardware):
    def __init__(self, results=((500000, 200), (250000, 300)), failure=None):
        super().__init__()
        self.results = iter(results)
        self.failure = failure

    def auto_exposure(self, settings, check_cancel):
        check_cancel()
        self.events.append(("ae", settings.auto_gain_mode))
        if self.failure:
            raise self.failure
        exposure, gain = next(self.results)
        return {"exposure_us": exposure, "gain_percent": gain,
                "metadata": {"RecipeAESDKTarget": 128}}


class RecipeAutoExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def make_controller(self):
        controller = CameraController()
        controller._camera = AutoCamera()
        controller._width, controller._height = 4, 3
        controller._camera_is_mono = True
        controller._scientific_pull_bits = 16
        controller._auto_exposure_roi_readback = (0, 0, 4, 3)
        controller._auto_exposure_roi_verified = True
        self.addCleanup(controller.close_camera)
        return controller

    def test_legacy_recipe_defaults_to_manual(self):
        recipe = Recipe.from_dict({"name": "Legacy", "el_matrix": {"gains_percent": [200], "exposures_ms": [100]}})
        self.assertEqual("manual", recipe.el_matrix.exposure_mode)
        self.assertEqual([200], recipe.el_matrix.gains_percent)
        self.assertEqual([100], recipe.el_matrix.exposures_ms)

    def test_auto_settings_round_trip_import_export(self):
        recipe = auto_recipe()
        recipe.el_matrix.auto_gain_mode = "fixed"
        recipe.el_matrix.auto_gain_percent = 350
        recipe.el_matrix.auto_target_percent = 70
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            store.upsert(recipe)
            loaded = RecipeStore(store.path).recipes[0]
            self.assertEqual(asdict(recipe.el_matrix), asdict(loaded.el_matrix))
            exported = {"schema_version": store.schema_version, "recipe": recipe.to_dict()}
            imported = store.import_payload(exported)
            self.assertEqual(asdict(recipe.el_matrix), asdict(imported.el_matrix))

    def test_ui_dropdown_shows_only_selected_form_and_preserves_values(self):
        with tempfile.TemporaryDirectory() as directory:
            dialog = RecipeManagerDialog(RecipeStore(Path(directory) / "recipes.json"))
            try:
                dialog._new_recipe()
                self.assertEqual(
                    ["manual", "auto"],
                    [dialog.exposure_mode_combo.itemData(index)
                     for index in range(dialog.exposure_mode_combo.count())],
                )
                self.assertEqual("manual", dialog.exposure_mode_combo.currentData())
                self.assertFalse(dialog.manual_exposure_group.isHidden())
                self.assertTrue(dialog.auto_exposure_group.isHidden())
                self.assertFalse(dialog.auto_exposure_group.isEnabled())
                dialog.matrix_gain_edit.setText("150, 250")
                dialog.matrix_exposure_edit.setText("100, 200")
                dialog.exposure_mode_combo.setCurrentIndex(1)
                self.assertEqual("auto", dialog.exposure_mode_combo.currentData())
                self.assertTrue(dialog.manual_exposure_group.isHidden())
                self.assertFalse(dialog.auto_exposure_group.isHidden())
                self.assertFalse(dialog.matrix_gain_edit.isEnabled())
                self.assertFalse(dialog.matrix_exposure_edit.isEnabled())
                self.assertTrue(dialog.auto_exposure_group.isEnabled())
                self.assertFalse(dialog.auto_gain_spin.isEnabled())
                self.assertTrue(dialog.matrix_repeat_spin.isEnabled())
                dialog.auto_gain_mode_combo.setCurrentIndex(1)
                self.assertTrue(dialog.auto_gain_spin.isEnabled())
                dialog.auto_gain_spin.setValue(220)
                loaded = dialog._read_form_to_recipe()
                self.assertEqual("auto", loaded.el_matrix.exposure_mode)
                self.assertEqual([150, 250], loaded.el_matrix.gains_percent)
                self.assertEqual([100, 200], loaded.el_matrix.exposures_ms)
                self.assertEqual(220, loaded.el_matrix.auto_gain_percent)
                dialog._write_recipe_to_form(loaded)
                self.assertEqual("auto", dialog.exposure_mode_combo.currentData())
                self.assertFalse(dialog.auto_exposure_group.isHidden())
                dialog.tabs.setCurrentIndex(2)
                dialog.show()
                for _ in range(4):
                    self.app.processEvents()
                auto_form_height = dialog.exposure_settings_widget.height()
                self.assertTrue(dialog.auto_exposure_group.isVisible())
                self.assertFalse(dialog.manual_exposure_group.isVisible())
                dialog.exposure_mode_combo.setCurrentIndex(0)
                for _ in range(4):
                    self.app.processEvents()
                self.assertFalse(dialog.manual_exposure_group.isHidden())
                self.assertTrue(dialog.auto_exposure_group.isHidden())
                self.assertLess(dialog.exposure_settings_widget.height(), auto_form_height)
                self.assertTrue(dialog.manual_exposure_group.isVisible())
                self.assertFalse(dialog.auto_exposure_group.isVisible())
                self.assertFalse(dialog.auto_exposure_group.isEnabled())
                self.assertTrue(dialog.matrix_gain_edit.isEnabled())
                self.assertEqual("100, 200", dialog.matrix_exposure_edit.text())
                self.assertEqual("manual", dialog._read_form_to_recipe().el_matrix.exposure_mode)
                dialog.exposure_mode_combo.setCurrentIndex(1)
                self.assertEqual(220, dialog.auto_gain_spin.value())
            finally:
                dialog.close()

    def test_inactive_manual_matrix_does_not_control_auto_validation_or_count(self):
        recipe = auto_recipe()
        recipe.el_matrix.exposures_ms = []
        recipe.el_matrix.gains_percent = []
        self.assertEqual([], recipe.validate())
        self.assertEqual({"shared_dark": 4, "el_per_channel": 4, "total_el": 4, "overall": 8}, recipe.matrix_capture_counts())
        estimate = ELMatrixPlan(recipe).estimate()
        self.assertGreaterEqual(estimate.output_on_per_setpoint_s, 60 + 2 * 15)
        self.assertGreaterEqual(estimate.total_time_s, 2 * 60 + 8 * 15)

    def test_only_active_gain_and_exposure_settings_are_validated(self):
        recipe = auto_recipe()
        recipe.el_matrix.auto_gain_percent = -1
        self.assertEqual([], recipe.validate())
        recipe.el_matrix.auto_gain_mode = "fixed"
        self.assertTrue(recipe.validate())
        recipe.el_matrix.exposure_mode = "manual"
        self.assertEqual([], recipe.validate())

    def test_invalid_auto_bounds_modes_and_targets_rejected(self):
        for field, value in (("exposure_mode", "bad"), ("auto_gain_mode", "bad"),
                             ("auto_max_exposure_ms", 15001), ("auto_max_exposure_ms", float("nan")),
                             ("auto_timeout_s", 15), ("auto_timeout_s", float("inf")),
                             ("auto_target_percent", 55), ("auto_target_percent", 50.0),
                             ("auto_max_exposure_ms", "bad"), ("auto_timeout_s", None)):
            with self.subTest(field=field, value=value):
                recipe = auto_recipe()
                setattr(recipe.el_matrix, field, value)
                self.assertTrue(recipe.validate())

    def test_execution_plan_places_matched_dark_after_el(self):
        recipe = auto_recipe()
        plan = build_measurement_execution_plan(recipe)
        self.assertEqual(("initialize", "channels", "auto_dark_frame", "output", "safe_shutdown"), plan.keys)
        steps = plan.to_dict()["steps"][1]["children"][0]["children"][0]["children"]
        self.assertEqual("auto_exposure", steps[0]["children"][0]["key"])

    def test_main_window_accepts_auto_gain_and_rejects_fixed_gain_outside_hardware(self):
        recipe = auto_recipe()
        owner = SimpleNamespace(
            selected_recipe=recipe,
            camera_info={"exposure_range_us": (30, 15000000, 10000), "gain_range": (100, 800, 100)},
            smu_manager=SimpleNamespace(control=SimpleNamespace(safety=SimpleNamespace(limits=SMUSafetyLimits()))),
        )
        self.assertEqual([], _validate_camera_matrix(owner))
        summary = _measurement_summary(owner, ELMatrixPlan(recipe))
        self.assertIn(tr("recipe.auto_gain"), summary)
        self.assertIn(tr("recipe.ae_warning"), summary)
        recipe.el_matrix.auto_gain_mode = "fixed"
        recipe.el_matrix.auto_gain_percent = 900
        self.assertTrue(_validate_camera_matrix(owner))

    def test_preflight_requires_verified_ae_capabilities(self):
        recipe = auto_recipe()
        current = {
            "ScientificMeasurementReady": True, "exposure_range_us": (30, 15000000, 10000),
            "gain_range": (100, 800, 100), "AutoExposureROIVerified": True,
            "SDKAutoExposurePolicy": 1, "AutoExposureMinGain": 100, "AutoExposureMaxGain": 500,
        }
        with tempfile.TemporaryDirectory() as directory:
            def preflight():
                return collect_preflight_errors(recipe,
                    smu_metadata={"connected": True, "supported": True,
                                  "manufacturer": "Keysight Technologies", "model": "B2901BL"},
                    smu_output_confirmed_off=True, relay_connected=True,
                    relay_settings=RelaySettings.defaults(), camera_connected=True,
                    camera_snapshot={}, current_camera=current, output_root=directory)
            self.assertEqual([], preflight())
            current["AutoExposureROIVerified"] = False
            self.assertIn(tr("recipe.validation.ae_capability"), preflight())

    def test_auto_preflight_uses_controller_metadata_after_ae_is_disabled(self):
        camera = _FakeMonoCamera()
        with patch.object(camera, "get_ExpTimeRange", return_value=(30, 15000000, 10000)):
            controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            _install_frame(controller)
            controller._pull_live_frame()
            self.assertTrue(controller.disable_auto_exposure_for_formal_measurement())
            with tempfile.TemporaryDirectory() as directory:
                for roi in ((0, 0, 3, 2), (1, 0, 2, 2)):
                    with self.subTest(roi=roi):
                        self.assertTrue(controller.set_auto_exposure_roi(*roi))
                        metadata = controller.capture_metadata()
                        current = {**metadata, "exposure_range_us": controller._exposure_range,
                                   "gain_range": controller._gain_range}
                        blockers = collect_preflight_errors(
                            auto_recipe(), smu_metadata={"connected": True, "supported": True,
                                "manufacturer": "Keysight Technologies", "model": "B2901BL"},
                            smu_output_confirmed_off=True, relay_connected=True,
                            relay_settings=RelaySettings.defaults(), camera_connected=True,
                            camera_snapshot=metadata, current_camera=current, output_root=directory)
                        self.assertEqual([], blockers)
                        self.assertIs(metadata["AutoExposureROIVerified"], True)
                        self.assertEqual(roi, metadata["AutoExposureROIRequested"])
                        self.assertEqual(roi, metadata["AutoExposureROIReadback"])
                        self.assertEqual("Verified", metadata["AutoExposureROIVerificationStatus"])
        finally:
            controller.close_camera()

    def test_metadata_retains_failed_roi_readback_and_preflight_still_blocks(self):
        camera = _FakeMonoCamera()
        with patch.object(camera, "get_ExpTimeRange", return_value=(30, 15000000, 10000)):
            controller, errors = _open(camera)
        try:
            self.assertTrue(controller.is_open, errors)
            _install_frame(controller)
            controller._pull_live_frame()
            self.assertTrue(controller.disable_auto_exposure_for_formal_measurement())
            with patch.object(camera, "get_AEAuxRect", return_value=(0, 0, 3, 2)):
                self.assertFalse(controller.set_auto_exposure_roi(1, 0, 2, 2))
            metadata = controller.capture_metadata()
            self.assertIs(metadata["AutoExposureROIVerified"], False)
            self.assertEqual("ReadbackMismatch", metadata["AutoExposureROIVerificationStatus"])
            self.assertEqual((1, 0, 2, 2), metadata["AutoExposureROIRequested"])
            self.assertEqual((0, 0, 3, 2), metadata["AutoExposureROIReadback"])
            self.assertTrue(metadata["AutoExposureROIError"])
            current = {**metadata, "exposure_range_us": controller._exposure_range,
                       "gain_range": controller._gain_range}
            with tempfile.TemporaryDirectory() as directory:
                blockers = collect_preflight_errors(
                    auto_recipe(), smu_metadata={"connected": True, "supported": True,
                        "manufacturer": "Keysight Technologies", "model": "B2901BL"},
                    smu_output_confirmed_off=True, relay_connected=True,
                    relay_settings=RelaySettings.defaults(), camera_connected=True,
                    camera_snapshot=metadata, current_camera=current, output_root=directory)
                self.assertEqual([tr("recipe.validation.ae_capability")], blockers)
        finally:
            controller.close_camera()

    def test_fixed_gain_sets_exposure_only_and_restores_sdk_limits(self):
        controller = self.make_controller()
        camera = controller._camera
        settings = asdict(auto_recipe().el_matrix)
        settings.update(auto_gain_mode="fixed", auto_gain_percent=700)
        state = {}
        try:
            begin_recipe_ae(controller, settings, state)
            self.assertEqual((15000000, 30, 700, 700), camera.auto_range)
            self.assertEqual(700, camera.gain)
            self.assertEqual(0, camera.options[nncam.NNCAM_OPTION_AUTOEXP_POLICY])
            self.assertEqual(2, camera.auto_exposure_enable)
            restore_recipe_ae(controller, state)
            self.assertEqual((350000, 30, 500, 100), camera.auto_range)
            self.assertEqual(1, camera.options[nncam.NNCAM_OPTION_AUTOEXP_POLICY])
            self.assertEqual(120, camera.auto_exposure_target)
            self.assertEqual(0, camera.auto_exposure_enable)
        finally:
            controller._camera = None

    def test_auto_gain_retains_native_gain_bounds(self):
        controller = self.make_controller()
        state = {}
        try:
            begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
            self.assertEqual((15000000, 30, 500, 100), controller._camera.auto_range)
            self.assertEqual(1, controller._camera.options[nncam.NNCAM_OPTION_AUTOEXP_POLICY])
            restore_recipe_ae(controller, state)
        finally:
            controller._camera = None

    def test_runtime_target_refresh_uses_recipe_target_then_restores_global_target(self):
        controller = self.make_controller()
        settings = asdict(auto_recipe().el_matrix)
        settings["auto_target_percent"] = 70
        state = {}
        try:
            begin_recipe_ae(controller, settings, state)
            controller._write_sdk_auto_exposure_target(controller._camera)
            self.assertEqual(179, controller._camera.get_AutoExpoTarget())
            self.assertEqual(70, controller.auto_exposure_target_percent)
            restore_recipe_ae(controller, state)
            self.assertEqual(50, controller.auto_exposure_target_percent)
            self.assertEqual(120, controller._camera.get_AutoExpoTarget())
        finally:
            controller._camera = None

    def run_bridge(self, controller, settings, action=None, cancel=lambda: None):
        bridge = CameraCaptureBridge(controller)
        results, failures = [], []
        def worker():
            try:
                results.append(bridge.auto_exposure(settings, cancel))
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        dispatched = False
        deadline = time.monotonic() + 8
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            if (not dispatched and controller.sdk_auto_exposure_mode is SDKAutoExposureMode.ONCE):
                dispatched = True
                if action:
                    action(controller)
            time.sleep(0.002)
        thread.join(0.1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(0, controller._camera.auto_exposure_enable)
        self.assertEqual((350000, 30, 500, 100), controller._camera.auto_range)
        self.assertIsNone(bridge._pending_ae)
        return results, failures

    def test_bridge_convergence_locks_result_and_restores_options(self):
        controller = self.make_controller()
        try:
            def converge(c):
                c._camera.exposure_us, c._camera.gain = 500000, 200
                c._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONV)
            results, failures = self.run_bridge(controller, asdict(auto_recipe().el_matrix), converge)
            self.assertEqual([], failures)
            self.assertEqual((500000, 200), (results[0]["exposure_us"], results[0]["gain_percent"]))
            self.assertEqual(1, results[0]["metadata"]["RecipeAEPolicy"])
        finally:
            controller._camera = None

    def test_bridge_fixed_gain_drift_rejected(self):
        controller = self.make_controller()
        settings = asdict(auto_recipe().el_matrix)
        settings.update(auto_gain_mode="fixed", auto_gain_percent=200)
        try:
            def converge(c):
                c._camera.gain = 201
                c._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONV)
            results, failures = self.run_bridge(controller, settings, converge)
            self.assertEqual([], results)
            self.assertIn("outside verified limits", str(failures[0]))
        finally:
            controller._camera = None

    def test_bridge_convergence_failure_aborts(self):
        controller = self.make_controller()
        try:
            results, failures = self.run_bridge(controller, asdict(auto_recipe().el_matrix),
                lambda c: c._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL))
            self.assertEqual([], results)
            self.assertEqual(1, len(failures))
        finally:
            controller._camera = None

    def test_bridge_timeout_restores_temporary_limits(self):
        controller = self.make_controller()
        settings = asdict(auto_recipe().el_matrix)
        settings["auto_timeout_s"] = 0.08
        try:
            results, failures = self.run_bridge(controller, settings)
            self.assertEqual([], results)
            self.assertIsInstance(failures[0], TimeoutError)
        finally:
            controller._camera = None

    def test_bridge_cancellation_restores_temporary_limits(self):
        controller = self.make_controller()
        cancelled = threading.Event()
        def check():
            if cancelled.is_set():
                raise MeasurementCancelled()
        try:
            results, failures = self.run_bridge(controller, asdict(auto_recipe().el_matrix),
                                                lambda _c: cancelled.set(), check)
            self.assertEqual([], results)
            self.assertIsInstance(failures[0], MeasurementCancelled)
        finally:
            controller._camera = None

    def test_camera_error_aborts_without_waiting_for_timeout(self):
        controller = self.make_controller()
        try:
            results, failures = self.run_bridge(controller, asdict(auto_recipe().el_matrix),
                lambda c: c.error_occurred.emit("camera link failed"))
            self.assertEqual([], results)
            self.assertIn("camera link failed", str(failures[0]))
        finally:
            controller._camera = None

    def test_partial_setup_failure_restores_range_and_policy(self):
        controller = self.make_controller()
        try:
            with patch.object(controller, "_enable_sdk_auto_exposure", side_effect=RuntimeError("setup failed")):
                results, failures = self.run_bridge(controller, asdict(auto_recipe().el_matrix))
            self.assertEqual([], results)
            self.assertIn("setup failed", str(failures[0]))
        finally:
            controller._camera = None

    def test_runner_freezes_repeats_and_captures_matched_dark_after_el(self):
        recipe, hardware = auto_recipe(), AutoHardware()
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=progress.append, is_cancel_requested=lambda: False)
            result = runner.run()
            self.assertTrue(result["safe_shutdown"]["ok"])
            self.assertEqual(8, result["captures"])
            captures = [event for event in hardware.events if isinstance(event, tuple) and event[0] == "capture"]
            self.assertEqual([("capture", 500, 200)] * 2 + [("capture", 250, 300)] * 2
                             + [("capture", 500, 200)] * 2 + [("capture", 250, 300)] * 2, captures)
            self.assertGreater(hardware.events.index("prepare_dark"), hardware.events.index(("ae", "auto")))
            with (runner.run_directory / "measurement_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(["EL"] * 4 + ["DARK"] * 4, [row["MeasurementType"] for row in rows])
            self.assertTrue(all(row["RecipeExposureMode"] == "auto" for row in rows))
            self.assertTrue(all(None not in row for row in rows))
            self.assertEqual(8, progress[-1].total)

    def test_duplicate_results_share_one_dark_profile(self):
        recipe = auto_recipe()
        hardware = AutoHardware(((500000, 200), (500000, 200)))
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=lambda _p: None, is_cancel_requested=lambda: False)
            result = runner.run()
            self.assertEqual(6, result["captures"])
            self.assertEqual(2, runner.plan.capture_counts()["shared_dark"])

    def test_postprocessor_matches_auto_dark_and_repeat_after_shutdown(self):
        recipe = auto_recipe()
        recipe.output.export_pixel_csv = True
        recipe.output.pixel_csv_exposure_normalized = True
        hardware = AutoHardware(((500000, 200), (500000, 200)))
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=lambda _p: None, is_cancel_requested=lambda: False)
            result = runner.run()
            status = PixelCSVPostprocessor(runner.run_directory, result["safe_shutdown"]).run()
            self.assertEqual("completed", status["status"])
            self.assertGreater(status["completed_files"], 0)

    def test_fixed_gain_mismatch_never_captures_and_shuts_down(self):
        recipe = auto_recipe()
        recipe.el_matrix.auto_gain_mode = "fixed"
        recipe.el_matrix.auto_gain_percent = 200
        hardware = AutoHardware(((500000, 201),))
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=lambda _p: None, is_cancel_requested=lambda: False)
            with self.assertRaisesRegex(RuntimeError, "invalid Exposure/Gain"):
                runner.run()
            self.assertTrue(hardware.safe)

    def test_pending_cancelled_before_qt_start_does_not_enable_ae(self):
        controller = self.make_controller()
        settings = asdict(auto_recipe().el_matrix)
        settings["auto_timeout_s"] = -1
        bridge = CameraCaptureBridge(controller)
        failures = []
        def worker():
            try:
                bridge.auto_exposure(settings, lambda: None)
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.1)
        try:
            deadline = time.monotonic() + 3
            while thread.is_alive() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.002)
            thread.join(0.1)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(failures[0], TimeoutError)
            self.assertNotIn(("sdk_auto", 2), controller._camera.calls)
        finally:
            controller._camera = None

    def test_voltage_auto_mode_without_dark(self):
        recipe = auto_recipe()
        recipe.el_matrix.output_mode = "voltage"
        recipe.el_matrix.voltage_v = [0.8]
        recipe.el_matrix.dark_frame_enabled = False
        recipe.el_matrix.auto_gain_mode = "fixed"
        recipe.el_matrix.auto_gain_percent = 200
        hardware = AutoHardware(((500000, 200),))
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(recipe, hardware, directory,
                report_progress=lambda _p: None, is_cancel_requested=lambda: False)
            self.assertEqual(2, runner.run()["captures"])
            self.assertIn(("set_voltage", 0.8, 20), hardware.events)
            self.assertNotIn("prepare_dark", hardware.events)

    def test_runner_ae_failure_always_runs_safe_shutdown(self):
        hardware = AutoHardware(failure=TimeoutError("convergence timeout"))
        with tempfile.TemporaryDirectory() as directory:
            runner = ELMatrixRunner(auto_recipe(), hardware, directory,
                report_progress=lambda _p: None, is_cancel_requested=lambda: False)
            with self.assertRaises(TimeoutError):
                runner.run()
            self.assertTrue(hardware.safe)
            self.assertFalse(any(isinstance(e, tuple) and e[0] == "capture" for e in hardware.events))


if __name__ == "__main__":
    unittest.main()
