from __future__ import annotations

import json
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
from gui.camera_sdk_diagnostics import CameraSDKOperationError, exception_hresult
from gui.dark_iv_chart import DarkIVChartDialog
from gui.el_matrix_runner import DarkIVPointProgress, ELMatrixRunner
from gui.measurement_worker import MeasurementWorker
from gui.sdk import nncam
from tests.qt_test_utils import ensure_qapplication
from tests.test_camera_scientific import _FakeMonoCamera, _open
from tests.test_dark_iv_chart import _row
from tests.test_recipe_auto_exposure import AutoCamera, AutoHardware, auto_recipe


class NativeFailure(Exception):
    hr = -2147418113  # The SDK's signed E_UNEXPECTED / 0x8000FFFF.

    def __init__(self):
        super().__init__("Catastrophic failure")


class StoppedConfigurationCamera(AutoCamera):
    """Model an SDK which rejects AE configuration during acquisition."""

    def __init__(self, *, fail_policy=False, fail_restore_stop=False):
        super().__init__()
        self.running = True
        self.fail_policy = fail_policy
        self.fail_restore_stop = fail_restore_stop
        self.stops = 0

    def Stop(self):
        self.stops += 1
        if self.fail_restore_stop and self.stops == 2:
            raise RuntimeError("restore Stop failed")
        self.running = False
        super().Stop()

    def StartPullModeWithCallback(self, callback, context):
        self.running = True
        super().StartPullModeWithCallback(callback, context)

    def put_AutoExpoRange(self, *values):
        if self.running:
            raise NativeFailure()
        super().put_AutoExpoRange(*values)

    def put_Option(self, option, value):
        if option in {nncam.NNCAM_OPTION_AUTOEXP_POLICY,
                      nncam.NNCAM_OPTION_AUTOEXPOSURE_PERCENT}:
            if self.running:
                raise NativeFailure()
            if self.fail_policy and option == nncam.NNCAM_OPTION_AUTOEXP_POLICY:
                self.fail_policy = False
                raise NativeFailure()
        super().put_Option(option, value)


class MeasurementSDKRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def controller(self, camera):
        controller = CameraController()
        controller._camera = camera
        controller._width, controller._height = 4, 3
        controller._camera_is_mono = True
        controller._scientific_pull_bits = 16
        controller._auto_exposure_roi_readback = (0, 0, 4, 3)
        controller._auto_exposure_roi_verified = True
        self.addCleanup(controller.close_camera)
        return controller

    def in_worker(self, operation):
        values, errors = [], []

        def run():
            try:
                values.append(operation())
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 8
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        thread.join(0.1)
        self.assertFalse(thread.is_alive(), "Camera bridge did not release the worker")
        return values, errors

    def test_recipe_ae_setup_and_restore_stop_acquisition_before_writes(self):
        camera = StoppedConfigurationCamera()
        controller = self.controller(camera)
        state = {}
        original_generation = controller._stream_generation
        begin_recipe_ae(controller, asdict(auto_recipe().el_matrix), state)
        self.assertTrue(camera.running)
        self.assertEqual(2, camera.auto_exposure_enable)
        self.assertGreater(controller._stream_generation, original_generation)
        restore_recipe_ae(controller, state)
        self.assertTrue(camera.running)
        self.assertEqual(2, camera.stops)
        self.assertEqual((350000, 30, 500, 100), camera.auto_range)
        self.assertEqual(120, camera.auto_exposure_target)
        self.assertEqual(0, camera.auto_exposure_enable)
        self.assertIs(controller.sdk_auto_exposure_mode, SDKAutoExposureMode.MANUAL)
        self.assertEqual((0, 0, 4, 3), controller._auto_exposure_roi_readback)

    def test_partial_ae_failure_preserves_sdk_operation_and_hresult_and_restores(self):
        camera = StoppedConfigurationCamera(fail_policy=True)
        controller = self.controller(camera)
        bridge = CameraCaptureBridge(controller)
        with self.assertLogs("gui.camera_sdk_diagnostics", level="ERROR") as logs:
            values, errors = self.in_worker(
                lambda: bridge.auto_exposure(asdict(auto_recipe().el_matrix), lambda: None))
        self.assertEqual([], values)
        self.assertEqual(1, len(errors))
        self.assertIn("Recipe AE setup: put_Option(NNCAM_OPTION_AUTOEXP_POLICY", str(errors[0]))
        self.assertIn("HRESULT=0x8000FFFF", str(errors[0]))
        self.assertEqual(nncam.E_UNEXPECTED, exception_hresult(errors[0]))
        self.assertIn("NativeFailure", "\n".join(logs.output))
        self.assertEqual((350000, 30, 500, 100), camera.auto_range)
        self.assertTrue(camera.running)
        self.assertIsNone(bridge._pending_ae)

    def test_ae_cleanup_failure_keeps_primary_error_and_releases_pending_request(self):
        camera = StoppedConfigurationCamera(fail_policy=True, fail_restore_stop=True)
        bridge = CameraCaptureBridge(self.controller(camera))
        with self.assertLogs("gui.camera_sdk_diagnostics", level="ERROR"):
            _, errors = self.in_worker(
                lambda: bridge.auto_exposure(asdict(auto_recipe().el_matrix), lambda: None))
        self.assertIn("NNCAM_OPTION_AUTOEXP_POLICY", str(errors[0]))
        self.assertIn("restore Stop failed", str(errors[0]))
        self.assertEqual(nncam.E_UNEXPECTED, exception_hresult(errors[0]))
        self.assertIsNone(bridge._pending_ae)

    def test_formal_capture_failure_identifies_flush_and_restores_video_mode(self):
        class FlushFailureCamera(_FakeMonoCamera):
            def put_Option(self, option, value):
                if option == nncam.NNCAM_OPTION_FLUSH:
                    raise NativeFailure()
                super().put_Option(option, value)

        camera = FlushFailureCamera()
        controller, _ = _open(camera)
        self.addCleanup(controller.close_camera)
        bridge = CameraCaptureBridge(controller)
        with self.assertLogs("gui.camera_sdk_diagnostics", level="ERROR"):
            _, errors = self.in_worker(lambda: bridge.capture(
                1, 100, 1, lambda: None, software_triggered=True))
        self.assertIn("Trigger capture setup: put_Option(NNCAM_OPTION_FLUSH", str(errors[0]))
        self.assertEqual(nncam.E_UNEXPECTED, exception_hresult(errors[0]))
        self.assertEqual(0, camera.get_Option(nncam.NNCAM_OPTION_TRIGGER))
        self.assertIsNone(bridge._pending)

    def runner(self, directory, hardware):
        recipe = auto_recipe()
        recipe.dark_iv.enabled = True
        recipe.dark_iv.dark_stabilization_s = 0
        recipe.el_matrix.stabilization_s = 0
        return ELMatrixRunner(recipe, hardware, directory,
                              report_progress=lambda _: None,
                              is_cancel_requested=lambda: False,
                              sample_ids={"CH1": "TEST"})

    def test_failure_after_dark_iv_keeps_files_and_records_actual_ae_stage(self):
        error = CameraSDKOperationError("Recipe AE setup: put_Option", NativeFailure())
        hardware = AutoHardware(failure=error)
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, hardware)
            with self.assertLogs("gui.el_matrix_runner", level="ERROR"):
                with self.assertRaises(CameraSDKOperationError):
                    runner.run()
            for name in ("dark_iv.csv", "dark_iv.json", "dark_iv.png"):
                paths = list(runner.run_directory.rglob(name))
                self.assertEqual(1, len(paths), name)
                self.assertGreater(paths[0].stat().st_size, 0)
            report = json.loads((runner.run_directory / "measurement_failure.json").read_text("utf-8"))
            self.assertEqual("Auto Exposure", report["phase"])
            self.assertEqual(("CH1", "TEST"), (report["channel"], report["sample_id"]))
            self.assertEqual(0, report["completed_captures"])
            self.assertEqual("0x8000FFFF", report["hresult"])
            self.assertIn("auto_exposure", report["traceback"])
            self.assertTrue(hardware.safe)

    def test_shutdown_failure_keeps_both_causes_in_report(self):
        class ShutdownFailureHardware(AutoHardware):
            def safe_shutdown(self):
                super().safe_shutdown()
                raise RuntimeError("shutdown connection lost")

        hardware = ShutdownFailureHardware(failure=NativeFailure())
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, hardware)
            with self.assertLogs("gui.el_matrix_runner", level="ERROR"):
                with self.assertRaises(RuntimeError) as failure:
                    runner.run()
            self.assertIn("Catastrophic failure", str(failure.exception))
            self.assertIn("shutdown connection lost", str(failure.exception))
            report = json.loads((runner.run_directory / "measurement_failure.json").read_text("utf-8"))
            self.assertEqual("0x8000FFFF", report["hresult"])
            self.assertEqual("shutdown connection lost", report["safe_shutdown_error"])

    def test_diagnostic_write_failure_does_not_replace_measurement_error(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, AutoHardware(failure=NativeFailure()))
            write_text = Path.write_text

            def write(path, *args, **kwargs):
                if path.name == "measurement_failure.json":
                    raise PermissionError("diagnostic write denied")
                return write_text(path, *args, **kwargs)

            with patch.object(Path, "write_text", write):
                with self.assertLogs("gui.el_matrix_runner", level="ERROR"):
                    with self.assertRaises(NativeFailure):
                        runner.run()

    def test_channel_cleanup_failure_does_not_hide_original_camera_failure(self):
        class ChannelCleanupFailureHardware(AutoHardware):
            def clear_routing(self):
                if any(isinstance(event, tuple) and event[0] == "ae" for event in self.events):
                    raise RuntimeError("channel relay cleanup failed")
                super().clear_routing()

        with tempfile.TemporaryDirectory() as directory:
            hardware = ChannelCleanupFailureHardware(failure=NativeFailure())
            runner = self.runner(directory, hardware)
            with self.assertLogs("gui.el_matrix_runner", level="ERROR"):
                with self.assertRaises(RuntimeError) as failure:
                    runner.run()
            self.assertIn("Catastrophic failure", str(failure.exception))
            self.assertIn("channel relay cleanup failed", str(failure.exception))
            self.assertEqual(nncam.E_UNEXPECTED, exception_hresult(failure.exception))
            self.assertTrue(hardware.safe)

    def test_worker_failure_includes_last_phase_channel_and_traceback(self):
        def run(progress, _cancelled):
            progress(SimpleNamespace(phase="Auto Exposure", channel="CH1", sample_id="TEST"))
            raise CameraSDKOperationError("Recipe AE setup", NativeFailure())

        worker = MeasurementWorker(run)
        errors = []
        worker.failed.connect(errors.append)
        with self.assertLogs("gui.measurement_worker", level="ERROR") as logs:
            worker.execute()
        self.assertIn("Stage=Auto Exposure; channel=CH1; sample_id=TEST", errors[0])
        self.assertIn("0x8000FFFF", errors[0])
        self.assertIn("Traceback", "\n".join(logs.output))

    def test_completed_dark_iv_remains_complete_after_later_failure_or_cancel(self):
        chart = DarkIVChartDialog()
        self.addCleanup(chart.close)
        point = DarkIVPointProgress("CH1", "TEST", 1, 1,
                                   _row(0.5, 1e-6, point=1, direction="forward"))
        chart.add_point(point)
        chart.mark_complete("dark_iv.png")
        completed = chart.status_value.text()
        chart.mark_failed("Recipe AE failed")
        self.assertEqual(completed, chart.status_value.text())
        chart.mark_aborted()
        self.assertEqual(completed, chart.status_value.text())
        chart.add_point(DarkIVPointProgress("CH2", "TEST2", 1, 2, point.row))
        chart.mark_failed("scan interrupted")
        self.assertIn("scan interrupted", chart.status_value.text())


if __name__ == "__main__":
    unittest.main()
