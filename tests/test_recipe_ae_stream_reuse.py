from __future__ import annotations

from dataclasses import asdict
import unittest
from unittest.mock import patch

from gui.camera_controller import CameraController, SDKAutoExposureMode
from gui.camera_recipe_ae import begin_recipe_ae, restore_recipe_ae
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_measurement_sdk_recovery import IndividualLimitCamera
from tests.test_recipe_auto_exposure import AutoCamera, auto_recipe


ROI = (1, 0, 2, 2)


class RecipeAEStreamReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def controller(self, camera=None):
        controller = CameraController()
        controller._camera = camera or IndividualLimitCamera()
        controller._width, controller._height = 4, 3
        controller._camera_is_mono = True
        controller._scientific_pull_bits = 16
        self.assertTrue(controller.set_auto_exposure_roi(*ROI))
        self.addCleanup(controller.close_camera)
        return controller

    def test_matching_policy_reuses_stream_and_restores_limits_target_and_roi(self):
        controller = self.controller()
        camera = controller._camera
        original_generation = controller._stream_generation
        original_target = camera.auto_exposure_target
        settings = asdict(auto_recipe().el_matrix)
        settings["auto_target_percent"] = 30
        state = {}
        with patch.object(controller, "_start_native_auto_exposure", wraps=controller._start_native_auto_exposure) as start:
            begin_recipe_ae(controller, settings, state)
        start.assert_called_once_with(SDKAutoExposureMode.ONCE, configure_parameters=False)
        self.assertEqual(30, controller.auto_exposure_target_percent)
        self.assertEqual((5000000, 30, 500, 100), camera.auto_range)
        self.assertEqual(ROI, camera.ae_aux_rect)
        self.assertFalse(state["result_metadata"]["RecipeAEStreamRestarted"])
        self.assertEqual(2, camera.auto_exposure_enable)
        restore_recipe_ae(controller, state)
        self.assertEqual(0, camera.stops)
        self.assertNotIn(("start",), camera.calls)
        self.assertEqual(original_generation, controller._stream_generation)
        self.assertEqual((350000, 30, 500, 100), camera.auto_range)
        self.assertEqual(original_target, camera.auto_exposure_target)
        self.assertEqual(ROI, camera.ae_aux_rect)
        self.assertEqual(0, camera.auto_exposure_enable)

    def test_same_policy_is_never_rewritten_on_running_camera(self):
        controller = self.controller()
        state = {}
        begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
        restore_recipe_ae(controller, state)
        options = {nncam.NNCAM_OPTION_AUTOEXP_POLICY, nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT}
        self.assertFalse(any(call[0] == "option" and call[1] in options for call in controller._camera.calls))

    def test_fixed_gain_switch_restarts_and_restores_original_policy(self):
        controller = self.controller()
        camera = controller._camera
        settings = asdict(auto_recipe().el_matrix)
        settings.update(auto_gain_mode="fixed", auto_gain_percent=700)
        state = {}
        begin_recipe_ae(controller, settings, state)
        self.assertTrue(state["result_metadata"]["RecipeAEStreamRestarted"])
        self.assertEqual((5000000, 30, 700, 700), camera.auto_range)
        self.assertEqual(0, camera.get_Option(nncam.NNCAM_OPTION_AUTOEXP_POLICY))
        restore_recipe_ae(controller, state)
        self.assertEqual(2, camera.stops)
        self.assertEqual(1, camera.get_Option(nncam.NNCAM_OPTION_AUTOEXP_POLICY))
        self.assertEqual(ROI, camera.ae_aux_rect)

    def test_toolbar_once_uses_same_native_entry_and_no_restart(self):
        controller = self.controller(AutoCamera())
        with patch.object(controller, "_start_native_auto_exposure", wraps=controller._start_native_auto_exposure) as start:
            controller.start_auto_exposure_once()
        start.assert_called_once_with(SDKAutoExposureMode.ONCE)
        self.assertEqual(2, controller._camera.auto_exposure_enable)
        self.assertNotIn(("start",), controller._camera.calls)

    def test_queued_previous_success_and_failure_cannot_finish_new_recipe(self):
        for event in (nncam.NNCAM_EVENT_AUTOEXPO_CONV, nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL):
            with self.subTest(event=event):
                controller = self.controller()
                camera = controller._camera
                results = []
                controller.auto_exposure_result.connect(lambda ok, message: results.append(ok))
                controller._enable_sdk_auto_exposure(SDKAutoExposureMode.ONCE)
                generation = controller._stream_generation
                # Queue a native result, then start a new run before Qt handles it.
                controller._camera_callback(event, (controller, generation))
                state = {}
                begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
                self.assertEqual(generation, controller._stream_generation)
                self.app.processEvents()
                self.assertEqual([], results)
                self.assertEqual(2, camera.auto_exposure_enable)
                controller._camera_callback(nncam.NNCAM_EVENT_AUTOEXPO_CONV, (controller, generation))
                self.app.processEvents()
                self.assertEqual([True], results)
                self.assertEqual(0, camera.auto_exposure_enable)
                restore_recipe_ae(controller, state)

    def test_current_failure_is_reported_and_old_stream_success_is_ignored(self):
        controller = self.controller()
        results = []
        controller.auto_exposure_result.connect(lambda ok, message: results.append(ok))
        state = {}
        begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
        generation = controller._stream_generation
        controller._camera_callback(nncam.NNCAM_EVENT_AUTOEXPO_CONV, (controller, generation - 1))
        self.app.processEvents()
        self.assertEqual([], results)
        self.assertEqual(2, controller._camera.auto_exposure_enable)
        controller._camera_callback(nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL, (controller, generation))
        self.app.processEvents()
        self.assertEqual([False], results)
        self.assertEqual(0, controller._camera.auto_exposure_enable)
        restore_recipe_ae(controller, state)

    def test_partial_limit_write_failure_restores_without_restart(self):
        controller = self.controller()
        camera = controller._camera
        camera.fail_after_max_write = True
        state = {}
        with self.assertLogs("gui.camera_sdk_diagnostics", level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "put_MaxAutoExpoTimeAGain"):
                begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
        restore_recipe_ae(controller, state)
        self.assertEqual(0, camera.stops)
        self.assertEqual((350000, 30, 500, 100), camera.auto_range)
        self.assertTrue(camera.running)
        self.assertTrue(controller.auto_exposure_roi_verified)


if __name__ == "__main__":
    unittest.main()
