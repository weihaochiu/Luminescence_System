from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np
import tifffile

from tools.camera_linearity_qualification.capture_runner import AcquiredFrame
from tools.camera_linearity_qualification.models import ROI
from tools.gsp4h_controller.controller import LightState
from tools.light_linearity_qualification.calibration import LightCalibration
from tools.light_linearity_qualification.plan import LightPlan, Retention
from tools.light_linearity_qualification.capture import LightCaptureRunner, VerifiedCameraAdapter
from tools.light_linearity_qualification.analysis import write_report, ConditionStatistics, fit_rows, DEFAULT_THRESHOLDS


READINGS = {16: 20., 64: 40., 128: 80., 192: 120., 255: 160.}


class FakeLight:
    def __init__(self):
        self.state = LightState(True, True, "FAKE", "L", (0, 0, 0, 0))
        self.off_calls = 0
        self.enable_calls = []
        self.fail_cleanup = False

    def turn_off(self):
        self.state = replace(self.state, mode="L")
        return self.state

    def safe_off(self):
        self.off_calls += 1
        if self.fail_cleanup:
            raise RuntimeError("OFF readback failed")
        self.state = replace(self.state, mode="L", brightness=(0, 0, 0, 0))
        return self.state

    def enable(self, values, check_cancel):
        check_cancel()
        self.enable_calls.append(tuple(values))
        self.state = replace(self.state, mode="H", brightness=tuple(values))
        return self.state

    def refresh(self, check_cancel=None):
        if check_cancel:
            check_cancel()
        return self.state


class FakeCamera:
    def __init__(self, light, *, stale=False, mismatch=False, cancel_after=None):
        self.light = light
        self.sequence = 0
        self.restored = []
        self.stale, self.mismatch, self.cancel_after = stale, mismatch, cancel_after
        self.calls = 0

    def snapshot_state(self):
        return {"initial_gain": 150, "initial_exposure": 100}

    def restore_state(self, state):
        self.restored.append(state)

    def capture(self, exposure_ms, gain, settling, timeout, check_cancel):
        from tools.camera_linearity_qualification.capture_runner import CaptureCancelled
        self.calls += 1
        if self.cancel_after and self.calls > self.cancel_after:
            raise CaptureCancelled("cancel test")
        check_cancel()
        if not self.stale or self.calls == 1:
            self.sequence += 1
        level = max(self.light.state.brightness)
        signal = READINGS.get(level, 0) / 160 * exposure_ms * gain / 100 if self.light.state.mode == "H" else 0
        # Balanced temporal noise leaves the ROI mean exactly linear.
        pattern = np.indices((8, 10)).sum(axis=0) % 2 * 2 - 1
        image = np.clip(np.rint(10 + signal + pattern * (-1 if self.calls % 2 else 1)), 0, 4095).astype(np.uint16)
        metadata = {"ScientificMeasurementReady": True, "SensorBitDepth": 12, "EffectiveDNMax": 4095,
                    "RawValueAlignment": "right", "ExposureReadbackUs": exposure_ms * 1000,
                    "ExposureUsedUs": exposure_ms * 1000 + (100000 if self.mismatch else 0),
                    "GainReadback": gain, "CameraSerial": "SYNTHETIC"}
        return AcquiredFrame(image, metadata, self.sequence, "2026-10-07T12:00:00+08:00", 25.)


class CalibrationTests(unittest.TestCase):
    def test_background_reference_and_missing_levels(self):
        profile = LightCalibration(background=10, readings={0: 10, 64: 35, 255: 110})
        self.assertEqual(.25, profile.relative(64))
        self.assertEqual(0., profile.relative(0))
        self.assertIsNone(profile.relative(65))
        with self.assertRaises(ValueError):
            profile.require_levels((64, 65))
        with self.assertRaises(ValueError):
            LightCalibration(readings={255: 0}).require_levels((255,))

    def test_invalid_readings_are_rejected(self):
        for readings in ({256: 1}, {-1: 1}, {1: float("nan")}, {1: float("inf")}, {1: -1}):
            with self.subTest(readings=readings), self.assertRaises(ValueError):
                LightCalibration(readings=readings).validate()

    def test_csv_round_trip_keeps_blanks_and_rejects_wrong_channel_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.csv"
            profile = LightCalibration(channel=2, unit="lux", readings={0: 0, 64: 35, 255: 110})
            profile.export_csv(path)
            target = LightCalibration(channel=2, unit="lux")
            target.import_csv(path)
            self.assertEqual(profile.readings, target.readings)
            self.assertNotIn(65, target.readings)
            wrong = LightCalibration(channel=1, unit="lux", readings={32: 7})
            with self.assertRaises(ValueError):
                wrong.import_csv(path)
            self.assertEqual({32: 7}, wrong.readings)

    def test_csv_duplicate_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.csv"
            for content in ("1,64,1,lux\n1,64,2,lux\n", "1,64,nan,lux\n"):
                path.write_text("channel,pwm_level,measured_intensity,unit\n" + content)
                with self.assertRaises(ValueError):
                    LightCalibration(unit="lux").import_csv(path)

    def test_snapshot_hash_changes_on_reading_and_round_trips_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = LightCalibration(readings={255: 100})
            first = profile.snapshot()["sha256"]
            profile.save(Path(tmp) / "profile.json")
            self.assertEqual(first, LightCalibration.load(Path(tmp) / "profile.json").snapshot()["sha256"])
            profile.readings[128] = 60
            self.assertNotEqual(first, profile.snapshot()["sha256"])


class PlanTests(unittest.TestCase):
    def test_capacity_and_time_account_for_matching_darks_and_settling(self):
        plan = LightPlan(1, (16, 64), (100,), (100., 1000.), settling_frames=2, settle_s=0)
        full = plan.estimate(1000, 1000, 100, 100)
        self.assertEqual(20, full["light_frames"])
        self.assertEqual(20, full["dark_frames"])
        self.assertEqual(80_000_000, full["pixel_bytes"])
        self.assertAlmostEqual(66, full["minimum_seconds"])
        roi = replace(plan, retention=Retention.ROI).estimate(1000, 1000, 100, 100)
        self.assertEqual(16_640_000, roi["pixel_bytes"])
        summary = replace(plan, retention=Retention.SUMMARY).estimate(1000, 1000, 100, 100)
        self.assertEqual(0, summary["pixel_bytes"])

    def test_invalid_matrix_rejected(self):
        plan = LightPlan(1, (16,), (100,), (50.,))
        for changed in (replace(plan, levels=(0,)), replace(plan, levels=(16, 16)), replace(plan, exposures_ms=(float("nan"),)), replace(plan, pwm_frequency_hz=0)):
            with self.assertRaises(ValueError):
                changed.validate()


class CaptureTests(unittest.TestCase):
    def test_camera_adapter_explicitly_triggers_discarded_and_accepted_frames(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        from datetime import datetime
        bridge = Mock()
        bridge.capture.return_value = SimpleNamespace(scientific_image=np.ones((4, 5), dtype=np.uint16),
                                                      camera_metadata={"FrameSequence": 4},
                                                      timestamp=datetime.now().astimezone(), camera_temperature_c=25.)
        adapter = VerifiedCameraAdapter(bridge, Mock(), {"initial": True})
        acquired = adapter.capture(15000, 200, 2, 90, lambda: None)
        self.assertEqual(3, bridge.capture.call_count)
        self.assertEqual(2, acquired.metadata["SettlingFramesDiscarded"])
        for call in bridge.capture.call_args_list:
            self.assertTrue(call.kwargs["software_triggered"])
            self.assertTrue(call.kwargs["require_frame_exposure_match"])
            self.assertEqual(0, call.kwargs["settling_frames"])

    def test_cleanup_failure_is_reported_even_when_all_frames_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            light = FakeLight()
            light.fail_cleanup = True
            camera = FakeCamera(light)
            plan = LightPlan(1, (255,), (100,), (100.,), settle_s=0, jitter_s=0, settling_frames=0)
            runner = LightCaptureRunner(camera, light, plan, LightCalibration(readings={255: 160.}), tmp, ROI(0, 0, 10, 8), synthetic=True)
            session = runner.run()
            manifest = json.loads((session / "SUMMARY" / "capture_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("CLEANUP_FAILED", manifest["phase"])
            self.assertTrue(manifest["cleanup_errors"])
            self.assertEqual(1, len(camera.restored))
            self.assertEqual("CLEANUP_FAILED", write_report(session)["run_phase"])

    def test_saturation_skip_resets_for_each_pwm_and_progress_counts_both_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            light = FakeLight()
            camera = FakeCamera(light)
            events = []
            plan = LightPlan(1, (255, 16), (100,), (100., 5000., 10000.), settle_s=0, jitter_s=0, settling_frames=0)
            runner = LightCaptureRunner(camera, light, plan, LightCalibration(readings=dict(READINGS)), tmp, ROI(0, 0, 10, 8), synthetic=True, progress=events.append)
            session = runner.run()
            manifest = json.loads((session / "SUMMARY" / "capture_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(1, len(manifest["skipped"]))
            self.assertEqual(255, manifest["skipped"][0]["pwm_level"])
            progress = [value for value in events if not isinstance(value, dict)][-1]
            self.assertEqual(50, progress.completed_frames)
            self.assertEqual(50, progress.total_frames)

    def run_capture(self, directory, retention=Retention.FULL, **camera_options):
        light = FakeLight()
        camera = FakeCamera(light, **camera_options)
        profile = LightCalibration(readings=dict(READINGS))
        plan = LightPlan(2, (64, 128), (100,), (50., 100.), repeats=5, dark_repeats=5,
                         settling_frames=0, settle_s=0, jitter_s=0, retention=retention)
        profile.channel = 2
        runner = LightCaptureRunner(camera, light, plan, profile, directory, ROI(2, 2, 4, 4), synthetic=True)
        return runner.run(), camera, light, profile

    def test_full_capture_separates_levels_and_keeps_snapshot_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, camera, light, profile = self.run_capture(tmp)
            rows = json.loads((session / "SUMMARY" / "condition_statistics.json").read_text())
            self.assertEqual(4, len(rows))
            self.assertEqual(40, len(list((session / "IMAGES").rglob("*.tiff"))))
            self.assertTrue(all(values[0] == values[2] == values[3] == 0 for values in light.enable_calls))
            self.assertEqual(1, len(camera.restored))
            self.assertTrue(light.state.off_confirmed)
            saved = rows[0]["calibration_sha256"]
            profile.readings[64] = 999
            summary = write_report(session)
            self.assertEqual(saved, summary["calibration_sha256"])
            self.assertFalse(summary["profile_usable_for_production"])

    def test_roi_retention_first_full_others_crop_original_uint16(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, *_ = self.run_capture(tmp, Retention.ROI)
            files = list((session / "IMAGES").rglob("*.tiff"))
            self.assertEqual(8, sum(tifffile.imread(file).shape == (8, 10) for file in files))
            self.assertEqual(32, sum(tifffile.imread(file).shape == (4, 4) for file in files))
            self.assertTrue(all(tifffile.imread(file).dtype == np.uint16 for file in files))

    def test_summary_only_and_summary_remains_usable_after_images_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, *_ = self.run_capture(tmp, Retention.SUMMARY)
            self.assertFalse((session / "IMAGES").exists())
            self.assertEqual(4, write_report(session)["condition_count"])
            session, *_ = self.run_capture(tmp)
            for file in (session / "IMAGES").rglob("*.tiff"):
                file.unlink()
            summary = write_report(session / "SUMMARY")
            self.assertTrue(any("移走或刪除" in item for item in summary["limitations"]))

    def test_stale_mismatched_or_cancelled_capture_restores_and_turns_off(self):
        for options, phase in (({"stale": True}, "FAILED"), ({"mismatch": True}, "FAILED"), ({"cancel_after": 12}, "CANCELLED")):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as tmp:
                session, camera, light, _ = self.run_capture(tmp, **options)
                manifest = json.loads((session / "SUMMARY" / "capture_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(phase, manifest["phase"])
                self.assertTrue(light.state.off_confirmed)
                self.assertEqual(1, len(camera.restored))
                write_report(session)

    def test_report_detects_tampered_statistics_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, *_ = self.run_capture(tmp)
            image = next((session / "IMAGES").rglob("*.tiff"))
            image.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                write_report(session)
            session, *_ = self.run_capture(tmp, Retention.SUMMARY)
            (session / "SUMMARY" / "condition_statistics.json").write_text("[]")
            with self.assertRaises(ValueError):
                write_report(session)


class AnalysisTests(unittest.TestCase):
    def test_measured_intensity_regression_uses_meter_not_pwm_code(self):
        rows = [{"pwm_level": level, "exposure_ms": 100, "actual_exposure_ms": 100, "relative_intensity": measured / 160,
                 "signal_dn": measured * 3, "snr": 100, "near_saturation_fraction": 0,
                 "repeat_cv_percent": 0, "temporal_band_percent": 0, "light_count": 5, "dark_count": 5}
                for level, measured in READINGS.items()]
        result = fit_rows(rows, "relative_intensity", DEFAULT_THRESHOLDS)
        self.assertEqual("PASS", result["status"])
        self.assertAlmostEqual(480, result["slope"])
        rows[2]["signal_dn"] *= 1.2
        self.assertEqual("FAIL", fit_rows(rows, "relative_intensity", DEFAULT_THRESHOLDS)["status"])

    def test_pwm_brightness_and_moving_bands_are_detected_separately(self):
        stats = ConditionStatistics()
        for i in range(5):
            stats.add_dark(np.full((8, 10), 10 + i % 2))
        for i in range(5):
            image = np.full((8, 10), 100., dtype=float)
            image[i, :] += 80
            stats.add_light(image, 4095, i)
        result = stats.result()
        self.assertAlmostEqual(0, result["repeat_cv_percent"])
        self.assertGreater(result["temporal_band_percent"], 2)


class GuiTests(unittest.TestCase):
    def test_old_imports_resolve_to_new_standalone_implementation(self):
        from tools.light_linearity_qualification import calibration as legacy
        from standalone.light_linearity_tester import calibration as relocated
        self.assertIs(legacy, relocated)
        self.assertIs(LightCalibration, relocated.LightCalibration)
        self.assertEqual("light_linearity_tester", Path(relocated.__file__).parent.name)

    def test_legacy_table_is_read_without_deleting_or_overwriting_source(self):
        from qt_test_utils import ensure_qapplication
        from PySide6.QtTest import QTest
        from standalone.light_linearity_tester.window import LightLinearityWindow
        ensure_qapplication()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_file = root / "legacy" / "calibrations" / "CH1.json"
            LightCalibration(readings={64: 40., 255: 100.}, unit="lux").save(legacy_file)
            original = legacy_file.read_bytes()
            with patch("standalone.light_linearity_tester.window.DATA_ROOT", root / "data"), patch("standalone.light_linearity_tester.window.LEGACY_DATA_ROOT", root / "legacy"), patch("gui.camera_controller.CameraController.enumerate_devices", return_value=[]):
                window = LightLinearityWindow()
                self.assertEqual("0.4", window.table.item(64, 2).text())
                self.assertEqual(root / "data" / "calibrations", window.profile_dir)
                window._save_current()
                self.assertTrue((window.profile_dir / "CH1.json").exists())
                self.assertEqual(original, legacy_file.read_bytes())
                self.assertEqual(root / "data" / "runs", Path(window.output_path.text()))
                window.close()
                for _ in range(100):
                    QTest.qWait(10)
                    if not window.device_thread.isRunning():
                        break
                self.assertFalse(window.device_thread.isRunning())

    def test_local_ui_language_selection_preserves_dynamic_values(self):
        from core.i18n import i18n, set_language, Language
        from tools.light_linearity_qualification.messages import msg
        from tools.light_linearity_qualification.window import CaptureProgressDialog
        from qt_test_utils import ensure_qapplication
        ensure_qapplication()
        original = i18n.language
        try:
            set_language(Language.EN_US, persist=False)
            self.assertEqual("English", msg("中文", "English"))
            dialog = CaptureProgressDialog()
            self.assertEqual("Linearity test progress", dialog.windowTitle())
            self.assertIn("0.5 s", dialog.elapsed.text())
            dialog.timer.stop()
            dialog.hide()
            dialog.deleteLater()
        finally:
            set_language(original, persist=False)

    def test_progress_heartbeat_while_worker_is_waiting(self):
        from qt_test_utils import ensure_qapplication
        from PySide6.QtTest import QTest
        from tools.light_linearity_qualification.window import CaptureProgressDialog
        ensure_qapplication()
        dialog = CaptureProgressDialog()
        dialog.show()
        first = dialog.elapsed.text()
        QTest.qWait(650)
        self.assertNotEqual(first, dialog.elapsed.text())
        requested = []
        dialog.stop_requested.connect(lambda: requested.append(True))
        dialog.reject()
        self.assertTrue(dialog.isVisible())
        self.assertEqual([True], requested)
        dialog.timer.stop()
        dialog.hide()
        dialog.deleteLater()

    def test_channel_tables_and_shutdown_without_hardware(self):
        from qt_test_utils import ensure_qapplication
        from PySide6.QtTest import QTest
        from tools.light_linearity_qualification.window import LightLinearityWindow
        ensure_qapplication()
        with tempfile.TemporaryDirectory() as tmp, patch("gui.camera_controller.CameraController.enumerate_devices", return_value=[]):
            window = LightLinearityWindow()
            window.profile_dir = Path(tmp)
            window.table.item(255, 1).setText("100")
            window.table.item(64, 1).setText("25")
            self.assertEqual("0.25", window.table.item(64, 2).text())
            window.channel.setCurrentIndex(1)
            self.assertEqual("", window.table.item(64, 1).text())
            window.channel.setCurrentIndex(0)
            self.assertEqual("25.0", window.table.item(64, 1).text())
            window.close()
            for _ in range(100):
                QTest.qWait(10)
                if not window.device_thread.isRunning():
                    break
            self.assertFalse(window.device_thread.isRunning())


if __name__ == "__main__":
    unittest.main()
