from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest

from gui.manual_smu_settings import (
    AREA_CM2_KEY,
    CC_CURRENT_DENSITY_KEY,
    CC_VOLTAGE_COMPLIANCE_KEY,
    CHANNEL_KEY,
    CV_CURRENT_COMPLIANCE_KEY,
    CV_VOLTAGE_KEY,
    MODE_KEY,
)
from gui.smu_manual_panel import ManualSMUPanel
from tests.qt_test_utils import ensure_qapplication


class ManualSMUSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.settings_path = Path(self.temporary_directory.name) / "manual_smu.ini"

    def settings(self) -> QSettings:
        return QSettings(str(self.settings_path), QSettings.Format.IniFormat)

    def test_first_launch_uses_existing_defaults(self) -> None:
        panel = ManualSMUPanel(settings=self.settings())
        self.assertEqual("Ch1", panel.channel_combo.currentData())
        self.assertEqual("CC", panel.mode)
        self.assertEqual(1.0, panel.area_cm2)
        self.assertEqual(0.0, panel.setpoint_spin.value())
        self.assertEqual(1.0, panel.compliance_spin.value())

    def test_cc_values_area_and_channel_survive_recreation(self) -> None:
        first = ManualSMUPanel(settings=self.settings())
        first.channel_combo.setCurrentIndex(0)
        first.area_spin.setValue(0.9200)
        first.setpoint_spin.setValue(15.0000)
        first.compliance_spin.setValue(3.0000)
        first.flush_persistent_settings()

        restored = ManualSMUPanel(settings=self.settings())
        self.assertEqual("Ch1", restored.channel_combo.currentData())
        self.assertEqual("CC", restored.mode)
        self.assertAlmostEqual(0.9200, restored.area_cm2, places=4)
        self.assertAlmostEqual(15.0000, restored.setpoint_spin.value(), places=4)
        self.assertAlmostEqual(3.0000, restored.compliance_spin.value(), places=4)

    def test_parameter_changes_auto_save_after_short_debounce(self) -> None:
        first = ManualSMUPanel(settings=self.settings())
        first.channel_combo.setCurrentIndex(2)
        first.area_spin.setValue(1.25)
        first.setpoint_spin.setValue(12.5)
        QTest.qWait(350)

        restored = ManualSMUPanel(settings=self.settings())
        self.assertEqual("Ch3", restored.channel_combo.currentData())
        self.assertEqual(1.25, restored.area_cm2)
        self.assertEqual(12.5, restored.setpoint_spin.value())

    def test_cc_and_cv_keep_independent_values_across_switches_and_restart(self) -> None:
        first = ManualSMUPanel(settings=self.settings())
        first.area_spin.setValue(0.92)
        first.setpoint_spin.setValue(15.0)
        first.compliance_spin.setValue(3.0)
        first.mode_combo.setCurrentIndex(1)
        first.setpoint_spin.setValue(1.20)
        first.compliance_spin.setValue(20.0)
        first.flush_persistent_settings()

        restored = ManualSMUPanel(settings=self.settings())
        self.assertEqual("CV", restored.mode)
        self.assertAlmostEqual(1.20, restored.setpoint_spin.value(), places=4)
        self.assertAlmostEqual(20.0, restored.compliance_spin.value(), places=4)
        restored.mode_combo.setCurrentIndex(0)
        self.assertAlmostEqual(15.0, restored.setpoint_spin.value(), places=4)
        self.assertAlmostEqual(3.0, restored.compliance_spin.value(), places=4)
        restored.mode_combo.setCurrentIndex(1)
        self.assertAlmostEqual(1.20, restored.setpoint_spin.value(), places=4)
        self.assertAlmostEqual(20.0, restored.compliance_spin.value(), places=4)

    def test_startup_restore_emits_no_output_or_routing_request(self) -> None:
        settings = self.settings()
        settings.setValue(CHANNEL_KEY, "Ch4")
        settings.setValue(MODE_KEY, "CV")
        settings.setValue("manual_smu/output_enabled", True)
        settings.setValue("manual_smu/active_routing_channel", "Ch4")
        settings.setValue("manual_smu/polarity", "REVERSED")
        settings.sync()
        output_command = Mock()
        routing_command = Mock()

        panel = ManualSMUPanel(settings=self.settings())
        panel.output_requested.connect(output_command)
        panel.output_requested.connect(routing_command)
        self.app.processEvents()

        self.assertEqual("Ch4", panel.channel_combo.currentData())
        self.assertEqual("—", panel.active_channel_value.text())
        self.assertEqual("OFF", panel.output_value.text())
        self.assertEqual("待輸出確認", panel.factor_value.text())
        output_command.assert_not_called()
        routing_command.assert_not_called()

    def test_invalid_values_fall_back_or_clamp_without_exception(self) -> None:
        settings = self.settings()
        settings.setValue(CHANNEL_KEY, "Ch99")
        settings.setValue(MODE_KEY, "invalid")
        settings.setValue(AREA_CM2_KEY, -5)
        settings.setValue(CC_CURRENT_DENSITY_KEY, "not-a-number")
        settings.setValue(CC_VOLTAGE_COMPLIANCE_KEY, float("inf"))
        settings.setValue(CV_VOLTAGE_KEY, float("nan"))
        settings.setValue(CV_CURRENT_COMPLIANCE_KEY, -1)
        settings.sync()

        fallback = ManualSMUPanel(settings=self.settings())
        self.assertEqual("Ch1", fallback.channel_combo.currentData())
        self.assertEqual("CC", fallback.mode)
        self.assertEqual(1.0, fallback.area_cm2)
        self.assertEqual(0.0, fallback.setpoint_spin.value())
        self.assertEqual(1.0, fallback.compliance_spin.value())

        settings = self.settings()
        settings.setValue(MODE_KEY, "CV")
        settings.setValue(AREA_CM2_KEY, 1_000_000)
        settings.setValue(CV_VOLTAGE_KEY, 1_000_000)
        settings.setValue(CV_CURRENT_COMPLIANCE_KEY, 1_000_000)
        settings.sync()
        clamped = ManualSMUPanel(settings=self.settings())
        self.assertEqual(clamped.area_spin.maximum(), clamped.area_cm2)
        self.assertEqual(clamped.setpoint_spin.maximum(), clamped.setpoint_spin.value())
        self.assertEqual(
            clamped.compliance_spin.maximum(),
            clamped.compliance_spin.value(),
        )

    def test_only_parameter_keys_are_written_and_reset_is_hardware_neutral(self) -> None:
        settings = self.settings()
        panel = ManualSMUPanel(settings=settings)
        output_command = Mock()
        panel.output_requested.connect(output_command)
        panel.area_spin.setValue(2.0)
        panel.mode_combo.setCurrentIndex(1)
        panel.setpoint_spin.setValue(1.2)
        panel.compliance_spin.setValue(20.0)
        panel.reset_persistent_settings()

        self.assertEqual("Ch1", panel.channel_combo.currentData())
        self.assertEqual("CC", panel.mode)
        self.assertEqual(1.0, panel.area_cm2)
        output_command.assert_not_called()
        self.assertEqual(
            {
                CHANNEL_KEY,
                MODE_KEY,
                AREA_CM2_KEY,
                CC_CURRENT_DENSITY_KEY,
                CC_VOLTAGE_COMPLIANCE_KEY,
                CV_VOLTAGE_KEY,
                CV_CURRENT_COMPLIANCE_KEY,
            },
            set(settings.allKeys()),
        )


if __name__ == "__main__":
    unittest.main()
