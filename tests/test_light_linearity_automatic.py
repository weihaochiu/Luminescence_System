from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from test_light_linearity_qualification import FakeLight, FakeCamera
from tools.camera_linearity_qualification.capture_runner import AcquiredFrame, CaptureCancelled
from tools.camera_linearity_qualification.models import ROI
from standalone.light_linearity_tester.automatic import (AutomaticCaptureRunner, AutomaticSettings,
                                                        REQUESTED_GAINS, exposure_points, next_pwm, selected_pwm)
from standalone.light_linearity_tester.analysis import write_report, fit_rows, DEFAULT_THRESHOLDS
from standalone.light_linearity_tester.calibration import LightCalibration
from standalone.light_linearity_tester.capture import LightCaptureRunner
from standalone.light_linearity_tester.lux_reference import attach_lux, load_capture, required_levels
from standalone.light_linearity_tester.plan import LightPlan, Retention


class SceneCamera(FakeCamera):
    def __init__(self, light, *, compress=False, maximum_gain=5000, cancel_after=None):
        super().__init__(light, cancel_after=cancel_after)
        self.compress = compress
        self.maximum_gain = maximum_gain

    def snapshot_state(self):
        return {"GainMin": 100, "GainMax": self.maximum_gain, "initial_exposure": 700}

    def capture(self, exposure_ms, gain, settling, timeout, check_cancel):
        self.calls += 1
        check_cancel()
        if self.cancel_after and self.calls > self.cancel_after:
            raise CaptureCancelled("cancelled during scout")
        self.sequence += 1
        level = max(self.light.state.brightness)
        signal = level / 255 * exposure_ms * gain / 100 * 2 if self.light.state.mode == "H" else 0
        if self.compress and gain >= 1000 and signal > 500:
            signal = 500 + (signal - 500) * .4
        noise = max(1., gain / 400)
        pattern = (np.indices((6, 8)).sum(axis=0) % 2 * 2 - 1) * (-1 if self.calls % 2 else 1)
        image = np.clip(np.rint(100 + signal + noise * pattern), 0, 4095).astype(np.uint16)
        metadata = {"ScientificMeasurementReady": True, "SensorBitDepth": 12, "EffectiveDNMax": 4095,
                    "RawValueAlignment": "right", "ExposureUsedUs": exposure_ms * 1000,
                    "GainReadback": gain, "CameraSerial": "SYNTHETIC"}
        return AcquiredFrame(image, metadata, self.sequence, "2026-10-07T12:00:00+08:00", 30.)


class PulseCamera(SceneCamera):
    def capture(self, exposure_ms, gain, settling, timeout, check_cancel):
        frame = super().capture(exposure_ms, gain, settling, timeout, check_cancel)
        if self.light.state.mode == "H" and exposure_ms < 50:
            scale = 1.5 if self.calls % 2 else .5
            frame.scientific[:] = np.clip(np.rint(frame.scientific.astype(float) * scale), 0, 4095).astype(np.uint16)
        return frame


class ZeroNoiseCamera(SceneCamera):
    def capture(self, exposure_ms, gain, settling, timeout, check_cancel):
        frame = super().capture(exposure_ms, gain, settling, timeout, check_cancel)
        frame.scientific[:] = 101 if self.light.state.mode == "H" else 100
        return frame


class PlannerTests(unittest.TestCase):
    def test_gain_set_includes_requested_high_gains_without_extra_levels(self):
        self.assertEqual((100, 200, 300, 400, 500, 1000, 2000, 3000, 5000), REQUESTED_GAINS)

    def test_ev_points_cover_two_stops_and_reject_narrow_range(self):
        times = exposure_points(50, 200, AutomaticSettings())
        self.assertEqual(5, len(times))
        np.testing.assert_allclose(times, (50, 70.711, 100, 141.421, 200), atol=.001)
        self.assertEqual((), exposure_points(180, 220, AutomaticSettings()))
        self.assertEqual((), exposure_points(200, 200, AutomaticSettings()))

    def test_pwm_refinement_only_uses_usable_signal_coverage(self):
        observations = {32: {"status": "VALID", "signal_dn": 100}, 64: {"status": "VALID", "signal_dn": 200},
                        128: {"status": "VALID", "signal_dn": 400}, 255: {"status": "HIGH", "signal_dn": 4095}}
        candidate = next_pwm(observations)
        self.assertNotIn(candidate, observations)
        self.assertTrue(1 <= candidate <= 255)
        self.assertEqual((), selected_pwm(observations))
        observations[16] = {"status": "VALID", "signal_dn": 50}
        observations[96] = {"status": "VALID", "signal_dn": 300}
        self.assertEqual(5, len(selected_pwm(observations)))
        narrow = {i: {"status": "VALID", "signal_dn": 100 + i} for i in range(1, 7)}
        self.assertEqual((), selected_pwm(narrow))

    def test_five_close_points_cannot_pass_coverage_gate(self):
        rows = [{"pwm_level": 128, "exposure_ms": t, "actual_exposure_ms": t, "signal_dn": t * 2,
                 "snr": 100, "near_saturation_fraction": 0, "repeat_cv_percent": 0,
                 "temporal_band_percent": 0, "light_count": 5, "dark_count": 5} for t in (180, 190, 200, 210, 220)]
        result = fit_rows(rows, "actual_exposure_ms", {**DEFAULT_THRESHOLDS, "minimum_exposure_span_ev": 2, "minimum_signal_span_ev": 2})
        self.assertAlmostEqual(1, result["r2"])
        self.assertEqual("INSUFFICIENT_RANGE_COVERAGE", result["status"])


class AutomaticRunTests(unittest.TestCase):
    def test_all_nine_requested_gains_are_actually_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AutomaticSettings(minimum_exposure_ms=50., maximum_exposure_ms=200.)
            session, _camera, light, _runner, _events = self.run_auto(tmp, settings=settings)
            _base, manifest, _snapshot, rows = load_capture(session)
            self.assertEqual("COMPLETE", manifest["phase"], manifest["error"])
            self.assertEqual(set(REQUESTED_GAINS), {row["gain"] for row in rows})
            for group in _runner.planning["gains"]:
                common = group["common_exposure_ms"]
                self.assertGreaterEqual(len([row for row in rows if row["gain"] == group["gain"] and row["exposure_ms"] == common]), 5)
            self.assertTrue(light.state.off_confirmed)

    def test_short_pwm_instability_is_recorded_and_common_points_remain_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            light = FakeLight()
            camera = PulseCamera(light)
            settings = AutomaticSettings(gains=(5000,), formal_step_ev=1.)
            plan = LightPlan(1, (128,), settings.gains, (200.,), retention=Retention.SUMMARY,
                             settling_frames=0, settle_s=0, jitter_s=0, require_measured=False)
            runner = AutomaticCaptureRunner(camera, light, plan, LightCalibration(unit="lux"), tmp,
                                            ROI(0, 0, 8, 6), settings=settings, synthetic=True)
            session = runner.run()
            _base, manifest, _snapshot, rows = load_capture(session)
            self.assertEqual("COMPLETE", manifest["phase"], manifest["error"])
            self.assertTrue(any(probe["status"] == "UNSTABLE" for probe in runner.planning["probes"]))
            common = runner.planning["gains"][0]["common_exposure_ms"]
            self.assertGreaterEqual(len([row for row in rows if row["exposure_ms"] == common]), 5)
            self.assertTrue(light.state.off_confirmed)

    def test_zero_dark_variance_does_not_turn_one_dn_into_high_snr(self):
        with tempfile.TemporaryDirectory() as tmp:
            light = FakeLight()
            camera = ZeroNoiseCamera(light)
            settings = AutomaticSettings(gains=(100,), probe_condition_limit=1)
            plan = LightPlan(1, (128,), (100,), (200.,), retention=Retention.SUMMARY,
                             settling_frames=0, settle_s=0, jitter_s=0, require_measured=False)
            runner = AutomaticCaptureRunner(camera, light, plan, LightCalibration(unit="lux"), tmp,
                                            ROI(0, 0, 8, 6), settings=settings, synthetic=True)
            runner.run()
            first = runner.planning["probes"][0]
            self.assertEqual("LOW", first["status"])
            self.assertAlmostEqual(2, first["snr"])

    def test_high_gain_compression_is_retained_and_not_selected_away(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AutomaticSettings(gains=(5000,), formal_step_ev=1.)
            session, _camera, _light, _runner, _events = self.run_auto(tmp, settings=settings, compress=True)
            summary = write_report(session)
            groups = [row for row in summary["exposure_linearity"] if row["included_count"] >= 5]
            self.assertTrue(groups)
            self.assertTrue(any(row["r2"] < .999 or row["max_residual_percent"] > 2 for row in groups))
            self.assertFalse(any(row["status"] == "PASS" for row in groups))

    def run_auto(self, root, settings=None, **camera_options):
        light = FakeLight()
        camera = SceneCamera(light, **camera_options)
        settings = settings or AutomaticSettings(gains=(100, 5000), formal_step_ev=1.)
        plan = LightPlan(1, (128,), settings.gains, (200.,), settle_s=0, jitter_s=0,
                         settling_frames=0, retention=Retention.SUMMARY, require_measured=False)
        events = []
        runner = AutomaticCaptureRunner(camera, light, plan, LightCalibration(unit="lux"), root,
                                        ROI(0, 0, 8, 6), settings=settings, synthetic=True, progress=events.append)
        return runner.run(), camera, light, runner, events

    def test_high_gain_auto_run_plans_common_exposures_and_defers_lux(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, camera, light, runner, events = self.run_auto(tmp)
            base, manifest, snapshot, rows = load_capture(session)
            self.assertEqual("COMPLETE", manifest["phase"], manifest["error"])
            self.assertEqual({100, 5000}, {row["gain"] for row in rows})
            for group in runner.planning["gains"]:
                common = group["common_exposure_ms"]
                matching = [row for row in rows if row["gain"] == group["gain"] and row["exposure_ms"] == common]
                self.assertGreaterEqual(len(matching), 5)
                self.assertGreaterEqual(len({row["pwm_level"] for row in matching}), 5)
            summary = write_report(session)
            self.assertEqual("AWAITING_LUX", summary["analysis_state"])
            self.assertEqual([], summary["gains_without_usable_exposure_curve"])
            self.assertTrue(light.state.off_confirmed)
            self.assertEqual(1, len(camera.restored))
            self.assertTrue(any(isinstance(e, dict) and e.get("indeterminate") for e in events))
            self.assertFalse((session / "IMAGES").exists())
            journal = (base / "frame_journal.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest["summary_frames"]), len(journal))

    def test_unsupported_gain_is_explicit_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, camera, light, runner, _ = self.run_auto(tmp, settings=AutomaticSettings(gains=(5000,)), maximum_gain=500)
            self.assertEqual("UNSUPPORTED_HARDWARE_GAIN", runner.planning["gains"][0]["status"])
            self.assertEqual([5000], write_report(session)["gains_without_usable_exposure_curve"])
            self.assertEqual(0, camera.calls)
            self.assertTrue(light.state.off_confirmed)

    def test_cancellation_search_budget_and_disk_limit_retain_evidence(self):
        for kind in ("cancel", "budget", "disk"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                kwargs = {"cancel_after": 3} if kind == "cancel" else {}
                settings = AutomaticSettings(gains=(100,), probe_condition_limit=1) if kind == "budget" else AutomaticSettings(gains=(100,))
                if kind == "disk":
                    with patch("standalone.light_linearity_tester.automatic.shutil.disk_usage", return_value=SimpleNamespace(free=0)):
                        session, camera, light, _runner, _events = self.run_auto(tmp, settings, **kwargs)
                else:
                    session, camera, light, _runner, _events = self.run_auto(tmp, settings, **kwargs)
                _base, manifest, _snapshot, _rows = load_capture(session)
                self.assertIn(manifest["phase"], ("CANCELLED", "FAILED"))
                self.assertEqual(1, len(camera.restored))
                self.assertTrue(light.state.off_confirmed)
                write_report(session)


def capture_without_lux(directory):
    light = FakeLight()
    camera = SceneCamera(light)
    plan = LightPlan(1, (1, 32, 64, 128, 255), (100,), (50., 100., 200., 400., 800.),
                     retention=Retention.SUMMARY, settle_s=0, jitter_s=0, settling_frames=0, require_measured=False)
    return LightCaptureRunner(camera, light, plan, LightCalibration(unit="lux"), directory, ROI(0, 0, 8, 6), synthetic=True).run()


class DeferredLuxTests(unittest.TestCase):
    def profile(self, levels):
        return LightCalibration(unit="lux", readings={0: 2., **{level: 2 + level for level in levels}},
                                background=2., reference_level=max(levels))

    def test_post_capture_lux_is_versioned_and_capture_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = capture_without_lux(tmp)
            base, manifest, snapshot, rows = load_capture(session)
            original = (base / "condition_statistics.json").read_bytes()
            levels = required_levels(rows)
            profile = self.profile(levels)
            first = attach_lux(session, profile, reproducibility_confirmed=True)
            self.assertEqual("ANALYZED", write_report(session)["analysis_state"])
            self.assertEqual(original, (base / "condition_statistics.json").read_bytes())
            profile.readings[levels[0]] += .1
            second = attach_lux(session, profile, reproducibility_confirmed=True)
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertEqual(original, (base / "condition_statistics.json").read_bytes())

    def test_lux_requires_correct_channel_all_values_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = capture_without_lux(tmp)
            _base, _manifest, _snapshot, rows = load_capture(session)
            profile = self.profile(required_levels(rows))
            with self.assertRaises(ValueError):
                attach_lux(session, profile, reproducibility_confirmed=False)
            with self.assertRaises(ValueError):
                attach_lux(session, replace(profile, channel=2), reproducibility_confirmed=True)
            with self.assertRaises(ValueError):
                attach_lux(session, replace(profile, unit="W"), reproducibility_confirmed=True)
            with self.assertRaises(ValueError):
                attach_lux(session, replace(profile, readings={255: 2.}), reproducibility_confirmed=True)

    def test_lux_from_another_run_and_tampered_reference_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = capture_without_lux(tmp)
            base, _manifest, _snapshot, rows = load_capture(session)
            record = attach_lux(session, self.profile(required_levels(rows)), reproducibility_confirmed=True)
            original = record.read_bytes()
            record.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_report(session)
            record.write_bytes(original)
            other = capture_without_lux(tmp)
            other_base = other / "SUMMARY"
            (other_base / "LUX").mkdir()
            copied = other_base / "LUX" / record.name
            copied.write_bytes(original)
            (other_base / "analysis_reference.json").write_bytes((base / "analysis_reference.json").read_bytes())
            with self.assertRaises(ValueError):
                write_report(other)


class AutomaticGuiTests(unittest.TestCase):
    def test_cancelling_lux_measurement_turns_off_light_through_worker(self):
        from qt_test_utils import ensure_qapplication
        from PySide6.QtTest import QTest
        from test_gsp4h_controller import FakeRegistry
        from standalone.light_linearity_tester.window import LightLinearityWindow
        ensure_qapplication()
        with tempfile.TemporaryDirectory() as tmp, patch("gui.camera_controller.CameraController.enumerate_devices", return_value=[]):
            window = LightLinearityWindow()
            window.profile_dir = Path(tmp) / "profiles"
            registry = FakeRegistry()
            window.device_worker.make_transport = registry.make_transport
            def wait_idle():
                for _ in range(150):
                    QTest.qWait(10)
                    if not window.job_busy:
                        return
                self.fail("Worker did not complete")
            try:
                window._dispatch({"operation": "connect", "port": "COM6", "parity": "none"})
                wait_idle()
                session = capture_without_lux(tmp)
                window._open_lux(session)
                dialog = window.lux_dialog
                wait_idle()
                self.assertTrue(dialog.ready)
                self.assertEqual("L", registry.devices["COM6"].mode)
                dialog.value.setText("2")
                dialog._next()
                wait_idle()
                self.assertEqual("H", registry.devices["COM6"].mode)
                dialog.reject()
                wait_idle()
                self.assertEqual("L", registry.devices["COM6"].mode)
                self.assertEqual([0, 0, 0, 0], registry.devices["COM6"].values)
                window.close()
                for _ in range(150):
                    QTest.qWait(10)
                    if not window.device_thread.isRunning():
                        break
                self.assertFalse(window.device_thread.isRunning())
            finally:
                if window.device_thread.isRunning():
                    window.device_thread.quit()
                    window.device_thread.wait(2000)
                window.close()

    def test_one_click_mode_uses_editable_gain_defaults_without_resetting_custom_input(self):
        from qt_test_utils import ensure_qapplication
        from PySide6.QtTest import QTest
        from standalone.light_linearity_tester.window import LightLinearityWindow
        ensure_qapplication()
        with tempfile.TemporaryDirectory() as tmp, patch("gui.camera_controller.CameraController.enumerate_devices", return_value=[]):
            window = LightLinearityWindow()
            window.profile_dir = Path(tmp)
            plan = window._plan()
            self.assertEqual(REQUESTED_GAINS, plan.gains)
            self.assertTrue(window.gains.isEnabled())
            window.gains.setText("125, 750, 5000")
            plan = window._plan()
            self.assertEqual((125, 750, 5000), plan.gains)
            runner = AutomaticCaptureRunner(SceneCamera(FakeLight()), FakeLight(), plan, LightCalibration(unit="lux"), tmp, ROI(0, 0, 8, 6))
            self.assertEqual(plan.gains, runner.settings.gains)
            window.latest_scientific = np.zeros((6, 8), dtype=np.uint16)
            estimate = window.estimate()
            self.assertEqual(750, estimate["light_frames"] + estimate["dark_frames"])
            window._set_busy(True)
            self.assertFalse(window.gains.isEnabled())
            window._set_busy(False)
            self.assertTrue(window.gains.isEnabled())
            self.assertEqual("125, 750, 5000", window.gains.text())
            self.assertFalse(plan.require_measured)
            self.assertFalse(window.exposures.isEnabled())
            self.assertFalse(window.levels.isEnabled())
            self.assertTrue(window.table.isHidden())
            self.assertTrue(window.exposures.isHidden())
            window.automatic_mode.setChecked(False)
            self.assertFalse(window.table.isHidden())
            self.assertFalse(window.exposures.isHidden())
            self.assertEqual((125, 750, 5000), window._plan().gains)
            window.mode.setCurrentIndex(0)
            self.assertEqual((125, 750, 5000), window._plan().gains)
            window.automatic_mode.setChecked(True)
            self.assertEqual((125, 750, 5000), window._plan().gains)
            for text in ("", "125,125", "0,125"):
                window.gains.setText(text)
                with self.assertRaises(ValueError):
                    window._plan()
            window.close()
            for _ in range(100):
                QTest.qWait(10)
                if not window.device_thread.isRunning():
                    break
            self.assertFalse(window.device_thread.isRunning())

    def test_lux_dialog_contains_only_used_levels_and_requires_all_lux_entries(self):
        from qt_test_utils import ensure_qapplication
        from standalone.light_linearity_tester.lux_dialog import LuxDialog
        from tools.gsp4h_controller.controller import LightState
        ensure_qapplication()
        with tempfile.TemporaryDirectory() as tmp:
            session = capture_without_lux(tmp)
            dialog = LuxDialog(session)
            saved = []
            applied = []
            dialog.reference_ready.connect(saved.append)
            def applied_level(ch, level):
                applied.append((ch, level))
                levels = [0] * 4
                levels[ch - 1] = level
                dialog.show_readback(LightState(True, True, "FAKE", "H" if level else "L", tuple(levels)))
            dialog.apply_requested.connect(applied_level)
            self.assertEqual(0, dialog.levels[0])
            dialog.start()
            self.assertEqual([(1, 0)], applied)
            for level in dialog.levels:
                self.assertTrue(dialog.ready)
                dialog.value.setText(str(2 + level))
                dialog.next.click()
            self.assertEqual(1, len(saved))
            self.assertEqual(2, saved[0].background)
            self.assertEqual([(1, level) for level in dialog.levels], applied)
            dialog.saving = False
            dialog.hide()
            dialog.deleteLater()

    def test_lux_step_requires_matching_readback_and_valid_value_before_advancing(self):
        from qt_test_utils import ensure_qapplication
        from standalone.light_linearity_tester.lux_dialog import LuxDialog
        from tools.gsp4h_controller.controller import LightState
        ensure_qapplication()
        with tempfile.TemporaryDirectory() as tmp, patch("standalone.light_linearity_tester.lux_dialog.QMessageBox.warning"):
            dialog = LuxDialog(capture_without_lux(tmp))
            applied = []
            dialog.apply_requested.connect(lambda ch, level: applied.append((ch, level)))
            dialog.start()
            dialog.start()
            self.assertEqual([(1, 0)], applied)
            dialog.value.setText("2")
            dialog._next()
            self.assertEqual({}, dialog.readings)
            dialog.show_readback(LightState(True, True, "FAKE", "H", (1, 0, 0, 0)))
            self.assertEqual("ERROR", dialog.phase)
            self.assertFalse(dialog.next.isEnabled())
            dialog._request_current()
            dialog.show_readback(LightState(True, True, "FAKE", "L", (0, 0, 0, 0)))
            for value in ("", "nan", "inf", "-1"):
                dialog.value.setText(value)
                dialog._next()
                self.assertEqual(0, dialog.index)
            dialog.value.setText("10")
            dialog._next()
            self.assertEqual(1, dialog.index)
            self.assertFalse(dialog.ready)
            dialog._next()  # Double click cannot skip an unconfirmed level.
            self.assertEqual(1, dialog.index)
            levels = (dialog.levels[1], 0, 0, 0)
            dialog.show_readback(LightState(True, True, "FAKE", "H", levels))
            dialog.value.setText("5")
            dialog._next()
            self.assertEqual(1, dialog.index)
            dialog.timer.stop()
            dialog.hide()
            dialog.deleteLater()

    def test_previous_step_reapplies_pwm_and_cancel_blocks_late_start(self):
        from qt_test_utils import ensure_qapplication
        from standalone.light_linearity_tester.lux_dialog import LuxDialog
        from tools.gsp4h_controller.controller import LightState
        ensure_qapplication()
        with tempfile.TemporaryDirectory() as tmp:
            session = capture_without_lux(tmp)
            dialog = LuxDialog(session)
            applied = []
            dialog.apply_requested.connect(lambda ch, level: applied.append(level))
            dialog.start()
            dialog.show_readback(LightState(True, True, "FAKE", "L", (0, 0, 0, 0)))
            dialog.value.setText("2")
            dialog._next()
            dialog.show_readback(LightState(True, True, "FAKE", "H", (dialog.levels[1], 0, 0, 0)))
            dialog.value.setText("3")
            dialog._next()
            dialog.show_readback(LightState(True, True, "FAKE", "H", (dialog.levels[2], 0, 0, 0)))
            dialog._previous()
            self.assertEqual(1, dialog.index)
            self.assertEqual(dialog.levels[1], applied[-1])
            self.assertEqual("3.0", dialog.value.text())
            self.assertFalse(dialog.ready)
            dialog.reject()
            dialog.start()
            dialog._request_current()
            self.assertEqual("CLOSED", dialog.phase)
            dialog.deleteLater()
            other = LuxDialog(session)
            pending = []
            other.apply_requested.connect(lambda *args: pending.append(args))
            other.reject()
            other.start()
            self.assertEqual([], pending)
            other.deleteLater()

    def test_guided_settling_can_be_cancelled_with_verified_light_off(self):
        from threading import Event, Timer
        from qt_test_utils import ensure_qapplication
        from test_gsp4h_controller import FakeRegistry
        from standalone.light_linearity_tester.window import DeviceWorker
        ensure_qapplication()
        registry = FakeRegistry()
        cancel = Event()
        worker = DeviceWorker(cancel, registry.make_transport)
        results = []
        worker.completed.connect(results.append)
        worker.execute({"operation": "connect", "port": "COM6", "parity": "none"})
        timer = Timer(.05, cancel.set)
        timer.start()
        try:
            worker.execute({"operation": "apply", "channel": 1, "level": 64, "guided": True, "settle_s": 10})
        finally:
            timer.cancel()
        self.assertTrue(results[-1]['error'])
        self.assertTrue(worker.light.state.off_confirmed)
        cancel.clear()
        worker.execute({"operation": "disconnect"})


if __name__ == "__main__":
    unittest.main()
