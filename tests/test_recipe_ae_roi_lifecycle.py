from __future__ import annotations

from contextlib import nullcontext
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
from tests.test_measurement_sdk_recovery import IndividualLimitCamera, NativeFailure
from tests.test_recipe_auto_exposure import auto_recipe


ROI = (1, 0, 2, 2)
DEFAULT_ROI = (0, 0, 4, 3)


class PipelineROICamera(IndividualLimitCamera):
    """A pipeline that loses its custom AE rectangle on every stream start."""

    def __init__(self):
        super().__init__()
        self.starts = 0
        self.ignore_roi_writes_at = set()
        self.fail_roi_writes_at = set()

    def StartPullModeWithCallback(self, callback, context):
        super().StartPullModeWithCallback(callback, context)
        self.starts += 1
        self.ae_aux_rect = DEFAULT_ROI

    def put_AEAuxRect(self, *roi):
        if not self.running:
            raise NativeFailure()
        if self.starts in self.fail_roi_writes_at:
            self.fail_roi_writes_at.remove(self.starts)
            raise NativeFailure()
        if self.starts in self.ignore_roi_writes_at:
            self.calls.append(("ignored_roi", *roi))
            return
        super().put_AEAuxRect(*roi)


class RecipeAEROILifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def setUp(self):
        self.camera = PipelineROICamera()
        self.controller = CameraController()
        self.controller._camera = self.camera
        self.controller._width, self.controller._height = 4, 3
        self.controller._camera_is_mono = True
        self.controller._scientific_pull_bits = 16
        self.assertTrue(self.controller.set_auto_exposure_roi(*ROI))
        self.addCleanup(self.controller.close_camera)
        self.settings = asdict(auto_recipe().el_matrix)

    def bridge_run(self, event=None):
        bridge = CameraCaptureBridge(self.controller)
        result, errors = [], []

        def run():
            try:
                result.append(bridge.auto_exposure(self.settings, lambda: None))
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        deadline, dispatched = monotonic() + 4, False
        while worker.is_alive() and monotonic() < deadline:
            self.app.processEvents()
            if not dispatched and self.controller.sdk_auto_exposure_mode is SDKAutoExposureMode.ONCE:
                dispatched = True
                if event is not None:
                    event(bridge)
            sleep(0.002)
        worker.join(0.1)
        self.assertFalse(worker.is_alive(), "AE request did not release the worker")
        self.assertIsNone(bridge._pending_ae)
        self.assertEqual(0, self.camera.auto_exposure_enable)
        return result, errors

    def test_restart_reapplies_channel_roi_after_limits_before_enabling_ae(self):
        state = {}
        self.controller._latest_metering_mean_effective_dn = 123
        begin_recipe_ae(self.controller, self.settings, state)
        self.assertEqual(ROI, self.camera.ae_aux_rect)
        self.assertTrue(self.controller.auto_exposure_roi_verified)
        self.assertIsNone(self.controller._latest_metering_mean_effective_dn)
        calls = self.camera.calls
        started = calls.index(("start",))
        limits = next(i for i, call in enumerate(calls) if call[0] == "ae_limit")
        reapplied = calls.index(("ae_roi", *ROI), started)
        readback = calls.index(("read_ae_roi",), reapplied)
        self.assertLess(started, limits)
        self.assertLess(limits, reapplied)
        self.assertLess(readback, calls.index(("sdk_auto", 2)))
        self.assertEqual(ROI, state["result_metadata"]["RecipeAEROI"])
        self.assertTrue(state["result_metadata"]["RecipeAEROIVerified"])
        self.assertEqual(self.controller._stream_generation, state["result_metadata"]["RecipeAEROIStreamGeneration"])
        restore_recipe_ae(self.controller, state)
        self.assertEqual(2, self.camera.starts)
        self.assertEqual(ROI, self.camera.ae_aux_rect)
        self.assertTrue(self.controller.auto_exposure_roi_verified)

    def test_setup_roi_mismatch_aborts_before_ae_and_cleanup_reapplies_roi(self):
        self.camera.ignore_roi_writes_at.add(1)
        self.settings["auto_timeout_s"] = 0.1
        with self.assertLogs("gui.camera_controller", level="ERROR"):
            result, errors = self.bridge_run()
        self.assertEqual([], result)
        self.assertIn("RECIPE_AE_SETUP_ROI: AE ROI verification failed", str(errors[0]))
        self.assertNotIn(("sdk_auto", 2), self.camera.calls)
        self.assertEqual(ROI, self.camera.ae_aux_rect)
        self.assertTrue(self.controller.auto_exposure_roi_verified)
        self.assertEqual((350000, 30, 500, 100), self.camera.auto_range)

    def test_roi_write_failure_retains_native_hresult_and_operation(self):
        self.camera.fail_roi_writes_at.add(1)
        self.settings["auto_timeout_s"] = 0.1
        with self.assertLogs(level="ERROR"):
            result, errors = self.bridge_run()
        self.assertEqual([], result)
        self.assertIn("put_AEAuxRect(1, 0, 2, 2)", str(errors[0]))
        self.assertIn("HRESULT=0x8000FFFF", str(errors[0]))
        self.assertNotIn(("sdk_auto", 2), self.camera.calls)
        self.assertEqual(ROI, self.camera.ae_aux_rect)

    def test_snapshot_failure_restart_also_reverifies_channel_roi(self):
        self.camera.fail_snapshot = True
        with self.assertLogs("gui.camera_sdk_diagnostics", level="ERROR"):
            result, errors = self.bridge_run()
        self.assertEqual([], result)
        self.assertIn("get_MinAutoExpoTimeAGain", str(errors[0]))
        self.assertEqual(ROI, self.camera.ae_aux_rect)
        self.assertTrue(self.controller.auto_exposure_roi_verified)
        self.assertEqual([], self.camera.limit_writes)

    def test_convergence_succeeds_when_pipeline_uses_reapplied_roi(self):
        def native_result(_bridge):
            event = (nncam.NNCAM_EVENT_AUTOEXPO_CONV if self.camera.ae_aux_rect == ROI
                     else nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL)
            self.camera.exposure_us, self.camera.gain = 500000, 200
            self.controller._handle_sdk_event(event)

        result, errors = self.bridge_run(native_result)
        self.assertEqual([], errors)
        self.assertEqual(500000, result[0]["exposure_us"])
        self.assertEqual(ROI, result[0]["metadata"]["RecipeAEROI"])
        self.assertEqual(ROI, self.camera.ae_aux_rect)

    def test_success_event_is_rejected_if_native_roi_has_drifted(self):
        def drift(_bridge):
            self.camera.ae_aux_rect = DEFAULT_ROI
            self.controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONV)

        with self.assertLogs(level="ERROR"):
            result, errors = self.bridge_run(drift)
        self.assertEqual([], result)
        self.assertIn("Recipe AE ROI changed", str(errors[0]))
        self.assertIn('"NativeROIReadback": [0, 0, 4, 3]', str(errors[0]))
        self.assertEqual(ROI, self.camera.ae_aux_rect)

    def test_success_event_is_rejected_after_an_unexpected_stream_restart(self):
        def restarted(_bridge):
            self.controller._stream_generation += 1
            self.controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONV)

        with self.assertLogs(level="ERROR"):
            result, errors = self.bridge_run(restarted)
        self.assertEqual([], result)
        self.assertIn("expected_stream=", str(errors[0]))
        self.assertIn("current_stream=", str(errors[0]))

    def test_convergence_failure_captures_settings_before_cleanup_and_marks_frame_lag(self):
        def failed(_bridge):
            self.camera.exposure_us, self.camera.gain = 5000000, 500
            self.controller._scientific_frame_validated = True
            self.controller._latest_metering_mean_effective_dn = 1267.6
            self.controller._latest_metering_effective_dn_fraction = 0.30955
            self.controller._frame_capture_metadata[self.controller._frame_sequence] = {
                "FrameExposureUs": 1750000, "FrameGainPercent": 100,
            }
            self.controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL)

        with self.assertLogs("gui.camera_recipe_ae", level="ERROR"):
            result, errors = self.bridge_run(failed)
        self.assertEqual([], result)
        details = json.loads(str(errors[0]).split("Recipe AE diagnostics=", 1)[1])
        self.assertEqual(ROI, tuple(details["NativeROIReadback"]))
        self.assertEqual(5000000, details["ExposureReadbackUs"])
        self.assertEqual(500, details["GainReadbackPercent"])
        self.assertEqual([5000000, 500], details["AEMaxTimeGain"])
        self.assertEqual(1267.6, details["LastFrameROIMeanDN"])
        self.assertEqual(1750000, details["LastFrameMetadata"]["FrameExposureUs"])
        self.assertEqual((350000, 30, 500, 100), self.camera.auto_range)

    def test_failed_diagnostic_getter_or_collector_does_not_mask_original_failure(self):
        for collector_fails in (False, True):
            with self.subTest(collector_fails=collector_fails):
                def failed(_bridge):
                    self.controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL)

                patcher = (patch("gui.camera_recipe_ae.recipe_ae_failure_context", side_effect=ValueError("collector failed"))
                           if collector_fails else patch.object(self.camera, "get_ExpoTime", side_effect=NativeFailure()))
                with patcher, (self.assertLogs(level="ERROR") if not collector_fails else nullcontext()):
                    result, errors = self.bridge_run(failed)
                self.assertEqual([], result)
                self.assertIn("Recipe AE diagnostics=", str(errors[0]))
                self.assertIn("unavailable", str(errors[0]))
                self.assertEqual(ROI, self.camera.ae_aux_rect)

    def test_success_event_native_roi_read_failure_retains_hresult_and_cleans_up(self):
        def get_AEAuxRect():
            raise NativeFailure()

        def failed_read(_bridge):
            with patch.object(self.camera, "get_AEAuxRect", new=get_AEAuxRect):
                self.controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONV)
                self.assertFalse(self.controller.auto_exposure_roi_verified)

        with self.assertLogs(level="ERROR"):
            result, errors = self.bridge_run(failed_read)
        self.assertEqual([], result)
        self.assertIn("Recipe AE result ROI: get_AEAuxRect()", str(errors[0]))
        self.assertIn("HRESULT=0x8000FFFF", str(errors[0]))
        self.assertEqual(ROI, self.camera.ae_aux_rect)
        self.assertTrue(self.controller.auto_exposure_roi_verified)

    def test_cleanup_roi_mismatch_keeps_primary_failure_and_blocks_verified_state(self):
        self.camera.ignore_roi_writes_at.add(2)
        with self.assertLogs(level="ERROR"):
            result, errors = self.bridge_run(
                lambda _bridge: self.controller._handle_sdk_event(nncam.NNCAM_EVENT_AUTOEXPO_CONVFAIL))
        self.assertEqual([], result)
        self.assertIn("Recipe AE diagnostics=", str(errors[0]))
        self.assertIn("Recipe AE cleanup failed", str(errors[0]))
        self.assertIn("RECIPE_AE_RESTORE_ROI", str(errors[0]))
        self.assertFalse(self.controller.auto_exposure_roi_verified)

    def test_unverified_roi_cannot_start_recipe_ae(self):
        self.controller._auto_exposure_roi_verified = False
        result, errors = self.bridge_run()
        self.assertEqual([], result)
        self.assertIn("requires a verified channel metering ROI", str(errors[0]))
        self.assertNotIn(("sdk_auto", 2), self.camera.calls)


if __name__ == "__main__":
    unittest.main()
