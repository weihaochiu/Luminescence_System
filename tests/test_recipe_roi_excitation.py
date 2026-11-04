from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PySide6.QtGui import QImage
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from gui.el_matrix_runner import ELMatrixRunner
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_roi_dialog import RecipeROIDialog
from gui.recipe_roi_excitation import ELROISession, validate_roi_excitation
from gui.recipe_roi_excitation import run_el_roi_selection
from gui.recipe_store import Recipe, RecipeStore
from gui.smu_control import SMUSafetyLimits
from tests.qt_test_utils import ensure_qapplication
from tests.test_recipe_channel_roi import CameraSignals
from tests.test_recipe_channel_roi import Emergency
from gui.polarity_settings import PolarityMeasurementSettings
from gui.camera_controller import CameraController
from tests.test_measurement_sdk_recovery import IndividualLimitCamera
from unittest.mock import patch
from tests.test_el_matrix import _FakeHardware, _small_recipe


class PositioningHardware:
    def __init__(self):
        self.events = []
        self.output = False
        self.white = False
        self.inhibited = False
        self.factor = None
        self.factor_result = -1
        self.polarity_ok = True
        self.reads = 0
        self.fail_monitor = False
        self.control = SimpleNamespace(safety=SimpleNamespace(limits=SMUSafetyLimits()))
        self.relay = SimpleNamespace(
            set_white_light_inhibited=self.inhibit, safe_white_light_off=self.white_off,
            verify_white_light_off=lambda: not self.white,
            verify_smu_output_channel_state=lambda *args: None)

    def inhibit(self, owner, enabled):
        self.inhibited = enabled
        self.events.append(("inhibit", enabled))

    def white_off(self, source):
        self.white = False
        self.events.append("white_off")
        return True

    def _verify_gsp4h_dark(self):
        self.events.append("gsp_dark")

    def output_off(self):
        self.events.append("output_off")
        self.output = False

    def clear_routing(self):
        if self.output:
            raise AssertionError("Routing while output ON")
        self.events.append("clear_routing")

    def route_channel(self, name, check):
        check()
        if self.output:
            raise AssertionError("Routing while output ON")
        self.events.append(("route", name))

    def run_polarity(self, channel, check):
        check()
        if self.inhibited:
            raise AssertionError("Polarity may use white light only before selection")
        self.events.append(("polarity", channel.channel))
        self.white = True
        return {"polarity_factor": self.factor_result,
                "polarity_check_status": "COMPLETED" if self.polarity_ok else "FAILED"}

    def apply_polarity_factor(self, factor):
        if self.output:
            raise AssertionError("Polarity change while output ON")
        self.factor = factor
        self.events.append(("factor", factor))

    def _on(self, mode, value, compliance):
        if self.white or not self.inhibited:
            raise AssertionError("EL cannot turn ON until white light is inhibited and OFF")
        self.output = True
        self.events.append((mode, value, compliance))
        return value * self.factor

    def set_current(self, value, compliance):
        return self._on("CC", value, compliance)

    def set_voltage(self, value, compliance):
        return self._on("CV", value, compliance)

    def readback(self):
        self.reads += 1
        if self.fail_monitor and self.reads > 1:
            raise RuntimeError("Compliance tripped")
        return SimpleNamespace(current_a=-0.0002, voltage_v=-1.2)

    def safe_shutdown(self):
        self.output_off()
        self.white_off("shutdown")
        self.events.append("shutdown")
        return {key: True for key in ("ok", "smu_output_off", "routing_off", "white_light_off", "ownership_released")}


class ELROIExcitationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def recipe(self, two=False):
        recipe = Recipe()
        recipe.dark_iv.enabled = False
        recipe.el_matrix.stabilization_ms = 0
        if two:
            recipe.channels[1].enabled = True
            recipe.channels[1].area_cm2 = 0.2
        return recipe

    def test_current_density_is_per_channel_area_and_polarity_precedes_el(self):
        recipe, hardware = self.recipe(two=True), PositioningHardware()
        recipe.el_matrix.roi_current_density_ma_cm2 = 6
        session = ELROISession(recipe, hardware)
        session.prepare("CH1")
        session.prepare("CH2")
        cc = [event for event in hardware.events if isinstance(event, tuple) and event[0] == "CC"]
        self.assertEqual([("CC", 0.0006, 3), ("CC", 0.0012, 3)], cc)
        self.assertLess(hardware.events.index(("polarity", "CH1")), hardware.events.index(cc[0]))
        self.assertLess(hardware.events.index("white_off"), hardware.events.index(cc[0]))
        self.assertEqual(-1, session.result["channels"]["CH1"]["polarity_factor"])
        self.assertEqual(-0.0006, session.result["channels"]["CH1"]["commanded_physical"])
        self.assertEqual({"CH1", "CH2"}, set(session.result["polarity"]))

    def test_voltage_uses_current_compliance_and_configured_negative_polarity(self):
        recipe, hardware = self.recipe(), PositioningHardware()
        recipe.polarity.enabled = False
        recipe.geometry.forward_polarity = "negative"
        recipe.el_matrix.output_mode = "voltage"
        recipe.el_matrix.roi_voltage_v = 1.1
        session = ELROISession(recipe, hardware)
        session.prepare("CH1")
        self.assertIn(("CV", 1.1, 20), hardware.events)
        self.assertEqual(-1.1, session.result["channels"]["CH1"]["commanded_physical"])
        self.assertEqual({}, session.result["polarity"])

    def test_invalid_or_failed_polarity_never_enables_el(self):
        for factor, completed in ((None, True), (1, False), (True, True)):
            hardware = PositioningHardware()
            hardware.factor_result, hardware.polarity_ok = factor, completed
            session = ELROISession(self.recipe(), hardware)
            session.request_channel("CH1")
            with self.assertLogs("gui.recipe_roi_excitation", level="ERROR"):
                session.run()
            self.assertTrue(session.result["error"])
            self.assertFalse(any(isinstance(e, tuple) and e[0] in {"CC", "CV"} for e in hardware.events))
            self.assertFalse(hardware.output)
            self.assertIn("shutdown", hardware.events)

    def test_confirmation_cancels_session_and_safe_shutdown_releases_inhibition(self):
        hardware = PositioningHardware()
        session = ELROISession(self.recipe(two=True), hardware)
        def ready(channel, _record):
            self.assertFalse(hardware.white)
            self.assertTrue(hardware.inhibited)
            if channel == "CH1":
                session.request_channel("CH2")
            else:
                session.cancel()
        session.ready.connect(ready)
        session.request_channel("CH1")
        session.run()
        self.assertEqual("", session.result["error"])
        self.assertFalse(hardware.output)
        self.assertFalse(hardware.inhibited)
        self.assertTrue(session.result["safe_shutdown"]["ok"])

    def test_cancel_before_start_never_enables_output(self):
        hardware = PositioningHardware()
        session = ELROISession(self.recipe(), hardware)
        session.request_channel("CH1")
        session.cancel()
        session.run()
        self.assertEqual(["output_off", "white_off", "shutdown", ("inhibit", False)], hardware.events)

    def test_white_light_or_compliance_fault_during_selection_shuts_down(self):
        for fault in ("white", "compliance", "timeout"):
            hardware = PositioningHardware()
            hardware.fail_monitor = fault == "compliance"
            session = ELROISession(self.recipe(), hardware)
            def ready(*_args):
                if fault == "white":
                    hardware.white = True
                if fault == "timeout":
                    session._output_started -= session.max_output_time_s + 1
            session.ready.connect(ready)
            session.request_channel("CH1")
            with self.assertLogs("gui.recipe_roi_excitation", level="ERROR"):
                session.run()
            self.assertTrue(session.result["error"])
            self.assertFalse(hardware.output)
            self.assertFalse(hardware.white)

    def test_shutdown_failure_is_reported_even_after_operator_confirmation(self):
        hardware = PositioningHardware()
        hardware.safe_shutdown = Mock(side_effect=RuntimeError("OFF not confirmed"))
        session = ELROISession(self.recipe(), hardware)
        session.cancel()
        session.run()
        self.assertIn("OFF not confirmed", session.result["error"])

    def test_actual_negative_polarity_cannot_exceed_asymmetric_voltage_limit(self):
        recipe, hardware = self.recipe(), PositioningHardware()
        recipe.el_matrix.output_mode = "voltage"
        hardware.control.safety.limits = replace(SMUSafetyLimits(), minimum_voltage_v=-0.5)
        session = ELROISession(recipe, hardware)
        with self.assertRaises(ValueError):
            session.prepare("CH1")
        self.assertFalse(hardware.output)

    def test_validation_rejects_nonfinite_bool_negative_and_safety_excess(self):
        recipe = self.recipe()
        for value in (0, -1, True, float("nan"), float("inf"), "bad", 10000):
            recipe.el_matrix.roi_current_density_ma_cm2 = value
            self.assertTrue(validate_roi_excitation(recipe), value)
        recipe.el_matrix.roi_current_density_ma_cm2 = 2
        recipe.el_matrix.output_mode = "voltage"
        for value in (0, -1, 6, float("nan")):
            recipe.el_matrix.roi_voltage_v = value
            self.assertTrue(validate_roi_excitation(recipe), value)
        recipe.el_matrix.roi_voltage_v = 1
        self.assertEqual([], validate_roi_excitation(recipe))
        self.assertTrue(validate_roi_excitation(recipe, replace(SMUSafetyLimits(), maximum_power_w=0.001)))

    def test_legacy_defaults_and_schema14_roundtrip(self):
        legacy = Recipe.from_dict({"name": "legacy", "el_matrix": {"output_mode": "voltage"}})
        self.assertEqual(0.8, legacy.el_matrix.roi_voltage_v)
        legacy.el_matrix.roi_voltage_v = 1.23
        legacy.el_matrix.roi_current_density_ma_cm2 = 6.5
        with TemporaryDirectory() as root:
            store = RecipeStore(Path(root) / "recipes.json")
            store.upsert(legacy)
            loaded = RecipeStore(store.path).recipes[0]
            self.assertEqual(1.23, loaded.el_matrix.roi_voltage_v)
            self.assertEqual(6.5, loaded.el_matrix.roi_current_density_ma_cm2)

    def test_editor_switches_roi_units_and_preserves_values(self):
        with TemporaryDirectory() as root:
            store = RecipeStore(Path(root) / "recipes.json")
            store.upsert(self.recipe())
            dialog = RecipeManagerDialog(store)
            dialog.tabs.setCurrentIndex(2)
            dialog.show()
            self.app.processEvents()
            try:
                dialog.roi_current_density_spin.setValue(7)
                dialog.matrix_output_mode_combo.setCurrentIndex(1)
                self.assertFalse(dialog.roi_current_density_spin.isVisible())
                self.assertTrue(dialog.roi_voltage_spin.isVisible())
                dialog.roi_voltage_spin.setValue(1.2)
                recipe = dialog._read_form_to_recipe()
                self.assertEqual((7, 1.2), (recipe.el_matrix.roi_current_density_ma_cm2, recipe.el_matrix.roi_voltage_v))
                dialog.matrix_output_mode_combo.setCurrentIndex(0)
                self.assertEqual(7, dialog.roi_current_density_spin.value())
            finally:
                dialog.close()

    def test_dialog_ignores_old_frames_and_old_roi_until_current_channel_ready(self):
        camera = CameraSignals()
        dialog = RecipeROIDialog(camera, ("CH1", "CH2"), excitation_required=True)
        requests = []
        dialog.channel_requested.connect(requests.append)
        image = QImage(4, 3, QImage.Format.Format_RGB888)
        try:
            camera.frame_ready.emit(image)
            self.assertFalse(dialog.view.has_image)
            dialog.channel_ready("CH1", "6 mA/cm²")
            camera.frame_ready.emit(image)
            dialog.view.set_roi(0, 0, 2, 2)
            dialog.view._finish_roi_selection()
            dialog._selected(0, 0, 2, 2)
            dialog._next()
            self.assertEqual(["CH2"], requests)
            camera.frame_ready.emit(image)
            dialog._selected(0, 0, 2, 2)
            self.assertFalse(dialog.next_button.isEnabled())
            dialog.channel_ready("CH1", "stale")
            self.assertTrue(dialog._waiting_channel)
            dialog.channel_ready("CH2", "6 mA/cm²")
            self.assertFalse(dialog.view.isEnabled())
            camera.frame_ready.emit(image)
            self.assertTrue(dialog.view.isEnabled())
        finally:
            dialog.reject()

    def test_formal_run_reuses_preselection_polarity_instead_of_reilluminating(self):
        recipe = _small_recipe(1)
        recipe.polarity.enabled = True
        recipe.dark_iv.enabled = False
        hardware = _FakeHardware()
        hardware.run_polarity = Mock(side_effect=AssertionError("must reuse prepared polarity"))
        prepared = {"CH1": {"polarity_factor": -1, "polarity_check_status": "COMPLETED"}}
        with TemporaryDirectory() as root:
            runner = ELMatrixRunner(recipe, hardware, root, report_progress=lambda _: None,
                                    is_cancel_requested=lambda: False, prepared_polarity_results=prepared)
            runner.run()
        hardware.run_polarity.assert_not_called()
        self.assertEqual(-1, runner._polarity["CH1"]["polarity_factor"])

    def test_real_dialog_thread_channel_switch_confirm_cancel_and_emergency(self):
        for action in ("confirm", "cancel", "emergency"):
            with self.subTest(action=action):
                owner = QWidget()
                owner.controller = CameraController()
                owner.controller._camera = IndividualLimitCamera()
                owner.controller._width, owner.controller._height = 4, 3
                owner.controller._scientific_pull_bits = 16
                owner.controller._camera_is_mono = True
                owner.controller._exposure_range = (30, 15000000, 10000)
                owner.controller.set_auto_exposure_roi(0, 0, 4, 3)
                owner.emergency_manager = Emergency()
                owner.emergency_manager.is_active = False
                owner.polarity_settings_store = SimpleNamespace(settings=PolarityMeasurementSettings())
                owner.smu_manager = SimpleNamespace(control=Mock())
                owner.relay_service = Mock()
                owner.max_output_time_s, owner.max_recipe_time_s = 2, 5
                hardware = PositioningHardware()
                timer = QTimer()
                timer.setInterval(10)
                seen = []
                def interact():
                    for dialog in owner.findChildren(RecipeROIDialog):
                        if dialog._closed:
                            if action == "confirm":
                                owner.controller._scientific_frame_validated = True
                                owner.controller.frame_ready.emit(QImage(4, 3, QImage.Format.Format_RGB888))
                            continue
                        if dialog._waiting_channel:
                            continue
                        if action != "confirm":
                            if action == "emergency":
                                owner.emergency_manager.is_active = True
                                owner.emergency_manager.triggered.emit(1)
                            else:
                                dialog.reject()
                            continue
                        name = dialog.channels[dialog._index]
                        if name in seen:
                            continue
                        seen.append(name)
                        owner.controller.frame_ready.emit(QImage(4, 3, QImage.Format.Format_RGB888))
                        dialog.view.set_roi(0, 0, 2, 2)
                        dialog.view._finish_roi_selection()
                        dialog._selected(0, 0, 2, 2)
                        dialog._next()
                timer.timeout.connect(interact)
                timer.start()
                try:
                    with patch("gui.el_matrix_hardware.ELMatrixHardwareAdapter", return_value=hardware):
                        rois = run_el_roi_selection(owner, self.recipe(two=True))
                    if action == "confirm":
                        self.assertEqual({"CH1": (0, 0, 2, 2), "CH2": (0, 0, 2, 2)}, rois)
                        self.assertEqual(["CH1", "CH2"], seen)
                        self.assertTrue(owner.controller._scientific_frame_validated)
                    else:
                        self.assertIsNone(rois)
                    self.assertFalse(hardware.output)
                    self.assertFalse(hardware.white)
                    self.assertFalse(hardware.inhibited)
                finally:
                    timer.stop()
                    owner.controller.close_camera()
                    owner.close()


if __name__ == "__main__":
    unittest.main()
