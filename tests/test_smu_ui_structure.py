from __future__ import annotations

import unittest
from pathlib import Path


class SMUUIStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = Path(__file__).parents[1] / "gui"

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


if __name__ == "__main__":
    unittest.main()
