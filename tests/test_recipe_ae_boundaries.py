from __future__ import annotations

from dataclasses import asdict
import json
import threading
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from gui.camera_capture_bridge import CameraCaptureBridge
from gui.camera_controller import CameraController, SDKAutoExposureMode
from gui.camera_recipe_ae import begin_recipe_ae, restore_recipe_ae
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_camera_scientific import _FakeMonoCamera, _open
from tests.test_measurement_sdk_recovery import IndividualLimitCamera
from tests.test_recipe_auto_exposure import auto_recipe


class LiveROICamera(_FakeMonoCamera):
    """Metering storage is created on Start and destroyed on Stop."""

    def __init__(self):
        super().__init__()
        self.running = False

    def StartPullModeWithCallback(self, *args):
        super().StartPullModeWithCallback(*args)
        self.running = True
        self.ae_aux_rect = (1, 1, 1, 1)

    def Stop(self):
        self.running = False
        super().Stop()

    def put_AEAuxRect(self, *roi):
        if not self.running:
            raise RuntimeError("No active metering pipeline")
        super().put_AEAuxRect(*roi)

    def put_eSize(self, index):
        self.assert_stopped = not self.running


class RecipeAEBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def controller(self, camera=None):
        controller = CameraController()
        controller._camera = camera or IndividualLimitCamera()
        controller._width, controller._height = 4, 3
        controller._camera_is_mono = True
        controller._scientific_pull_bits = 16
        self.assertTrue(controller.set_auto_exposure_roi(1, 0, 2, 2))
        self.addCleanup(controller.close_camera)
        return controller

    def run_bridge(self, controller, action=None, timeout=1):
        settings = asdict(auto_recipe().el_matrix)
        settings["auto_timeout_s"] = timeout
        bridge = CameraCaptureBridge(controller)
        results, errors = [], []

        def worker():
            try:
                results.append(bridge.auto_exposure(settings, lambda: None))
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        dispatched = False
        deadline = monotonic() + 5
        while thread.is_alive() and monotonic() < deadline:
            self.app.processEvents()
            if not dispatched and controller.sdk_auto_exposure_mode is SDKAutoExposureMode.ONCE:
                dispatched = True
                if action:
                    action(bridge)
            sleep(0.002)
        thread.join(0.1)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(bridge._pending_ae)
        return results, errors

    def test_open_and_resolution_apply_roi_on_running_pipeline_before_ae(self):
        camera = LiveROICamera()
        controller, errors = _open(camera)
        self.addCleanup(controller.close_camera)
        self.assertTrue(controller.is_open, errors)
        self.assertTrue(controller.auto_exposure_roi_verified)
        self.assertEqual((0, 0, 3, 2), camera.ae_aux_rect)
        self.assertEqual(1, camera.auto_exposure_enable)
        controller.set_resolution(0)
        self.assertEqual([], errors)
        self.assertTrue(camera.assert_stopped)
        self.assertTrue(controller.auto_exposure_roi_verified)
        self.assertEqual((0, 0, 3, 2), camera.ae_aux_rect)
        self.assertEqual(1, camera.auto_exposure_enable)

    def test_trigger_restart_invalidates_then_cleanup_reapplies_custom_roi(self):
        camera = LiveROICamera()
        controller, errors = _open(camera)
        self.addCleanup(controller.close_camera)
        self.assertTrue(controller.is_open, errors)
        self.assertTrue(controller.set_auto_exposure_roi(1, 0, 2, 1))
        controller.prepare_software_triggered_capture(1000, 100)
        self.assertFalse(controller.auto_exposure_roi_verified)
        controller.finish_software_triggered_capture()
        self.assertTrue(controller.auto_exposure_roi_verified)
        self.assertEqual((1, 0, 2, 1), camera.ae_aux_rect)

    def test_snapshot_limits_are_read_before_stop_can_reset_them(self):
        camera = IndividualLimitCamera()
        camera.auto_range = (400000, 60, 400, 120)
        original_stop = camera.Stop

        def stop():
            original_stop()
            camera.auto_range = (350000, 30, 500, 100)

        controller = self.controller(camera)
        state = {}
        with patch.object(camera, "Stop", new=stop):
            begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
            self.assertEqual((5000000, 30, 400, 120), camera.auto_range)
            restore_recipe_ae(controller, state)
        self.assertEqual((400000, 60, 400, 120), camera.auto_range)

    def test_initial_settings_fit_bounds_including_positive_and_negative_stops(self):
        for exposure, gain, stops, expected in (
            (15000000, 800, [0], (5000000, 500)),
            (30, 100, [-2, 2], (120, 100)),
            (5000000, 200, [2], (3750000, 200)),
        ):
            with self.subTest(exposure=exposure, stops=stops):
                controller = self.controller()
                camera = controller._camera
                camera.exposure_us, camera.gain = exposure, gain
                settings = asdict(auto_recipe().el_matrix)
                settings["auto_exposure_stops"] = stops
                state = {}
                original_start = camera.StartPullModeWithCallback
                first_frame_settings = []
                def start(*args):
                    first_frame_settings.append((camera.exposure_us, camera.gain))
                    original_start(*args)
                with patch.object(camera, "StartPullModeWithCallback", new=start):
                    begin_recipe_ae(controller, settings, state)
                self.assertEqual([expected], first_frame_settings)
                self.assertEqual(expected, (camera.exposure_us, camera.gain))
                metadata = state["result_metadata"]
                self.assertEqual(expected, (metadata["RecipeAEInitialExposureUs"], metadata["RecipeAEInitialGainPercent"]))
                restore_recipe_ae(controller, state)

    def test_ignored_initial_setting_write_blocks_ae(self):
        controller = self.controller()
        controller._camera.exposure_us = 15000000
        with patch.object(controller._camera, "put_ExpoTime", return_value=None):
            with self.assertLogs(level="ERROR"):
                results, errors = self.run_bridge(controller)
        self.assertEqual([], results)
        self.assertIn("initial Exposure/Gain readback mismatch", str(errors[0]))
        self.assertNotIn(("sdk_auto", 2), controller._camera.calls)

    def test_start_resetting_target_or_policy_is_detected_before_enabling_ae(self):
        for reset in ("target", "policy", "metering", "rows"):
            with self.subTest(reset=reset):
                controller = self.controller()
                camera = controller._camera
                original = camera.StartPullModeWithCallback
                def start(*args):
                    original(*args)
                    if len([call for call in camera.calls if call == ("start",)]) != 1:
                        return
                    if reset == "target":
                        camera.auto_exposure_target = 16
                    else:
                        option = {"policy": nncam.NNCAM_OPTION_AUTOEXP_POLICY,
                                  "metering": nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT,
                                  "rows": nncam.NNCAM_OPTION_UPSIDE_DOWN}[reset]
                        camera.options[option] = 1 if reset != "policy" else 0
                with patch.object(camera, "StartPullModeWithCallback", new=start):
                    with self.assertLogs(level="ERROR"):
                        results, errors = self.run_bridge(controller)
                self.assertEqual([], results)
                self.assertIn("Top-down rows" if reset == "rows" else "changed", str(errors[0]))
                self.assertNotIn(("sdk_auto", 2), camera.calls)

    def test_success_event_cannot_accept_drifted_policy_target_limits_or_rows(self):
        for drift in ("target", "policy", "limits", "rows", "metering"):
            with self.subTest(drift=drift):
                controller = self.controller()
                camera = controller._camera
                def converge(_bridge):
                    if drift == "target":
                        camera.auto_exposure_target = 16
                    elif drift == "limits":
                        camera.auto_range = (350000, 30, 500, 100)
                    else:
                        option = {"policy": nncam.NNCAM_OPTION_AUTOEXP_POLICY,
                                  "rows": nncam.NNCAM_OPTION_UPSIDE_DOWN,
                                  "metering": nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT}[drift]
                        camera.options[option] = 1 if drift != "policy" else 0
                    controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONV)
                with self.assertLogs(level="ERROR"):
                    results, errors = self.run_bridge(controller, converge)
                self.assertEqual([], results)
                self.assertIn("changed", str(errors[0]))

    def test_cleanup_restores_non_default_metering_and_detects_reset_on_start(self):
        for reset in (False, True):
            with self.subTest(reset=reset):
                controller = self.controller()
                camera = controller._camera
                camera.options[nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT] = 20
                state = {}
                begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
                original_start = camera.StartPullModeWithCallback
                def start(*args):
                    original_start(*args)
                    camera.options[nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT] = 100
                if reset:
                    with patch.object(camera, "StartPullModeWithCallback", new=start):
                        with self.assertRaisesRegex(RuntimeError, "changed"):
                            restore_recipe_ae(controller, state)
                else:
                    restore_recipe_ae(controller, state)
                    self.assertEqual(20, camera.get_Option(nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT))

    def test_timeout_contains_pre_cleanup_native_diagnostics_and_remains_timeout(self):
        controller = self.controller()
        with self.assertLogs("gui.camera_recipe_ae", level="ERROR"):
            results, errors = self.run_bridge(controller, timeout=0.08)
        self.assertEqual([], results)
        self.assertIsInstance(errors[0], TimeoutError)
        details = json.loads(str(errors[0]).split("Recipe AE diagnostics=", 1)[1])
        self.assertEqual([5000000, 500], details["AEMaxTimeGain"])
        self.assertEqual(1, details["PolicyReadback"])
        self.assertEqual(100, details["MeteringPercentReadback"])
        self.assertGreater(details["ElapsedSeconds"], 0)
        self.assertEqual((350000, 30, 500, 100), controller._camera.auto_range)


if __name__ == "__main__":
    unittest.main()
