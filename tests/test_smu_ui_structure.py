from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.smu_control import SMUOperationState, SMUSafetyLimits
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
            "固定電流 CC",
            "固定電壓 CV",
            "Compliance",
            "Output ON",
            "Output OFF",
            "緊急關閉輸出",
            "實測 Voltage",
            "實測 Current",
            "Power",
        ):
            self.assertIn(required, source)
        lowered = source.lower()
        for forbidden in ("pyvisa", "keysight", "resource.write", "resource.query"):
            self.assertNotIn(forbidden, lowered)

    def test_monitor_uses_500_ms_timer_and_control_queue(self) -> None:
        source = (self.gui / "smu_monitor.py").read_text(encoding="utf-8")
        self.assertIn("interval_ms: int = 500", source)
        self.assertIn("self.control.request_readback", source)
        self.assertNotIn("resource.query", source)

    def test_recipe_start_confirms_manual_shutdown_and_disables_panel(self) -> None:
        source = (self.gui / "main_window_measurement.py").read_text(encoding="utf-8")
        self.assertIn("QMessageBox.question", source)
        self.assertIn("prepare_recipe_start(close_manual=True)", source)
        self.assertIn("set_recipe_active(True)", source)
        self.assertIn("safe_shutdown(SMUOwnership.RECIPE)", source)

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
        panel.set_connected(True)
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
        panel.set_connected(True)
        panel.update_polarity(1)
        self.assertTrue(panel.output_button.isEnabled())

        panel.update_operation_state(SMUOperationState.BUSY.value)
        self.assertFalse(panel.mode_combo.isEnabled())
        self.assertFalse(panel.setpoint_spin.isEnabled())
        self.assertFalse(panel.compliance_spin.isEnabled())
        self.assertFalse(panel.output_button.isEnabled())

        panel.update_operation_state(SMUOperationState.READY.value)
        self.assertTrue(panel.output_button.isEnabled())

        panel.update_operation_state(SMUOperationState.FAULT.value)
        panel.set_recipe_active(False)
        self.assertFalse(panel.output_button.isEnabled())

    def test_polarity_label_updates_without_command_applied(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        panel = ManualSMUPanel()
        self.assertEqual("UNKNOWN", panel.factor_value.text())
        panel.update_polarity(-1)
        self.assertEqual("-1", panel.factor_value.text())


if __name__ == "__main__":
    unittest.main()
