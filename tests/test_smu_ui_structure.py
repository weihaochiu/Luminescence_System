from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.instrument_state_manager import SMUInstrumentState, SMUUIState
from gui.smu_control import (
    ManualPolarityResult,
    PolarityState,
    SMUOperationState,
    SMUOwnership,
    SMUReadback,
    SMUSafetyLimits,
)
from gui.smu_manual_panel import ManualSMUPanel


class SMUUIStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = Path(__file__).parents[1] / "gui"
        existing = QApplication.instance()
        cls.app = (
            existing
            if isinstance(existing, QApplication)
            else QApplication([]) if existing is None else None
        )

    def test_manual_panel_is_presentational_and_has_required_controls(self) -> None:
        source = (self.gui / "smu_manual_panel.py").read_text(encoding="utf-8")
        for required in (
            "定電流密度",
            "定電壓",
            "元件面積",
            "設定電流密度",
            "Voltage Compliance",
            "Current Compliance",
            "OUTPUT OFF",
            "量測電壓",
            "量測電流密度",
            "待輸出確認",
        ):
            self.assertIn(required, source)
        self.assertNotIn("Emergency OFF", source)
        lowered = source.lower()
        for forbidden in ("pyvisa", "keysight", "resource.write", "resource.query"):
            self.assertNotIn(forbidden, lowered)

    def test_monitor_uses_500_ms_timer_and_control_queue(self) -> None:
        source = (self.gui / "smu_monitor.py").read_text(encoding="utf-8")
        self.assertIn("interval_ms: int = 500", source)
        self.assertIn("self.control.request_readback", source)
        self.assertNotIn("resource.query", source)

    def test_recipe_start_confirms_manual_shutdown_via_authoritative_state(self) -> None:
        source = (self.gui / "main_window_measurement.py").read_text(encoding="utf-8")
        self.assertIn("QMessageBox.question", source)
        self.assertIn("prepare_recipe_start(close_manual=True)", source)
        self.assertIn("safe_shutdown(SMUOwnership.RECIPE)", source)
        self.assertNotIn("set_recipe_active", source)

    def test_window_close_stops_monitor_before_manager_shutdown(self) -> None:
        source = (self.gui / "main_window.py").read_text(encoding="utf-8")
        monitor = source.index("self.smu_monitor.stop()")
        shutdown = source.index("self.smu_manager.shutdown()")
        self.assertLess(monitor, shutdown)

    def test_polarity_factor_is_assignment_not_toggle(self) -> None:
        source = (self.gui / "smu_control.py").read_text(encoding="utf-8")
        self.assertIn("return float(requested_value) * self._factor", source)
        self.assertNotIn("factor *=", source)

    def test_mode_switch_resets_setpoint_and_uses_authoritative_limits(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        limits = SMUSafetyLimits(
            minimum_voltage_v=-3.0,
            maximum_voltage_v=4.0,
            minimum_current_a=-0.012,
            maximum_current_a=0.015,
            maximum_voltage_compliance_v=2.5,
            maximum_current_compliance_a=0.008,
        )
        panel = ManualSMUPanel(limits=limits)
        panel.apply_ui_state(self.ready_state())
        self.assertEqual(-12.0, panel.setpoint_spin.minimum())
        self.assertEqual(15.0, panel.setpoint_spin.maximum())
        self.assertEqual(2.5, panel.compliance_spin.maximum())

        panel.setpoint_spin.setValue(10.0)
        panel.mode_combo.setCurrentIndex(1)
        self.assertEqual(0.0, panel.setpoint_spin.value())
        self.assertEqual(-3.0, panel.setpoint_spin.minimum())
        self.assertEqual(4.0, panel.setpoint_spin.maximum())
        self.assertEqual(8.0, panel.compliance_spin.maximum())

    def test_busy_state_immediately_disables_manual_editing(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        panel = ManualSMUPanel()
        ready = self.ready_state()
        panel.apply_ui_state(ready)
        panel.update_polarity(ManualPolarityResult(PolarityState.NORMAL, 1))
        self.assertTrue(panel.output_button.isEnabled())

        panel.apply_ui_state(
            replace(
                ready,
                operation=SMUOperationState.BUSY,
                manual_editable=False,
                manual_lock_reason="手動命令執行中",
            )
        )
        self.assertFalse(panel.mode_combo.isEnabled())
        self.assertFalse(panel.area_spin.isEnabled())
        self.assertFalse(panel.setpoint_spin.isEnabled())
        self.assertFalse(panel.compliance_spin.isEnabled())
        self.assertFalse(panel.output_button.isEnabled())

        panel.apply_ui_state(ready)
        self.assertTrue(panel.output_button.isEnabled())

        panel.apply_ui_state(
            replace(
                ready,
                state=SMUInstrumentState.ERROR,
                operation=SMUOperationState.FAULT,
                manual_editable=False,
            )
        )
        self.assertFalse(panel.output_button.isEnabled())

        panel.apply_ui_state(
            replace(
                ready,
                state=SMUInstrumentState.UNEXPECTED_OUTPUT_ON,
                output_enabled=True,
                output_confirmed_off=False,
                manual_editable=False,
                manual_off_enabled=True,
            )
        )
        self.assertTrue(panel.output_button.isEnabled())
        self.assertEqual("OUTPUT ON", panel.output_button.text())
        self.assertFalse(hasattr(panel, "off_button"))
        self.assertFalse(hasattr(panel, "emergency_button"))

        panel.update_readback(SMUReadback(1.0, 0.001, 0.001, True, True))
        self.assertEqual("⚠ Voltage Compliance Active", panel.compliance_value.text())

    def test_polarity_label_updates_without_command_applied(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        panel = ManualSMUPanel()
        self.assertEqual("待輸出確認", panel.factor_value.text())
        panel.update_polarity(ManualPolarityResult(PolarityState.REVERSED, -1))
        self.assertEqual("反向 (-1)", panel.factor_value.text())
        panel.update_command("CC", 0.002, 0.002, 2.0, 1)
        self.assertEqual("反向 (-1)", panel.factor_value.text())

    def test_density_and_current_compliance_are_converted_with_area(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        panel = ManualSMUPanel()
        panel.apply_ui_state(self.ready_state())
        emitted: list[tuple[str, float, float, float]] = []
        panel.output_requested.connect(lambda *values: emitted.append(values))
        panel.area_spin.setValue(2.0)
        panel.setpoint_spin.setValue(3.0)
        panel.output_button.click()
        self.assertEqual("CC", emitted[-1][0])
        self.assertAlmostEqual(0.006, emitted[-1][1])
        self.assertAlmostEqual(2.0, emitted[-1][3])

        panel.mode_combo.setCurrentIndex(1)
        panel.compliance_spin.setValue(4.0)
        panel.output_button.click()
        self.assertEqual("CV", emitted[-1][0])
        self.assertAlmostEqual(0.008, emitted[-1][2])

    def test_output_off_readback_displays_unavailable_values(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        panel = ManualSMUPanel()
        panel.update_readback(
            SMUReadback(
                voltage_v=None,
                current_a=None,
                power_w=None,
                output_enabled=False,
                compliance_tripped=None,
            )
        )
        self.assertEqual("— V", panel.voltage_value.text())
        self.assertEqual("— mA/cm²", panel.current_density_value.text())
        self.assertEqual("", panel.compliance_value.text())

    def test_readback_uses_measured_current_not_requested_value(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        panel = ManualSMUPanel()
        panel.area_spin.setValue(2.0)
        panel.update_readback(SMUReadback(1.23456, 0.006, 0.0, True, False))
        self.assertEqual("1.2346 V", panel.voltage_value.text())
        self.assertEqual("3.00 mA/cm²", panel.current_density_value.text())

    @staticmethod
    def ready_state() -> SMUUIState:
        return SMUUIState(
            state=SMUInstrumentState.READY_MANUAL,
            connected=True,
            supported=True,
            device_label="B2901BL",
            ownership=SMUOwnership.IDLE,
            operation=SMUOperationState.READY,
            output_enabled=False,
            output_confirmed_off=True,
            manual_editable=True,
            manual_off_enabled=False,
            emergency_enabled=True,
            handover_enabled=False,
            status_text="B2901BL｜手動控制可用｜OUTPUT：OFF",
            manual_lock_reason="",
        )


if __name__ == "__main__":
    unittest.main()
