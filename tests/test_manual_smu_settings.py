from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtTest import QSignalSpy, QTest

from gui.manual_smu_settings import (
    AREA_CM2_KEY,
    CC_CURRENT_DENSITY_KEY,
    CC_VOLTAGE_COMPLIANCE_KEY,
    CHANNEL_KEY,
    CV_CURRENT_COMPLIANCE_KEY,
    CV_VOLTAGE_KEY,
    MODE_KEY,
)
from gui.main_window import MainWindow
from gui.main_window_devices import MainWindowDeviceMixin
from gui.relay_controller import RelayService
from gui.smu_base import SMUDriver
from gui.smu_control import PolarityState, SMUControlManager
from gui.smu_manual_panel import ManualSMUPanel
from tests.qt_test_utils import ensure_qapplication


class FakeCloseEvent:
    def __init__(self) -> None:
        self.accepted = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


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

    def test_restore_path_is_signal_neutral(self) -> None:
        settings = self.settings()
        panel = ManualSMUPanel(settings=settings)
        output_requested = QSignalSpy(panel.output_requested)
        output_off_requested = QSignalSpy(panel.output_off_requested)
        handover_requested = QSignalSpy(panel.handover_requested)
        channel_changed = QSignalSpy(panel.channel_combo.currentIndexChanged)
        mode_changed = QSignalSpy(panel.mode_combo.currentIndexChanged)
        area_changed = QSignalSpy(panel.area_spin.valueChanged)
        setpoint_changed = QSignalSpy(panel.setpoint_spin.valueChanged)
        compliance_changed = QSignalSpy(panel.compliance_spin.valueChanged)

        settings.setValue(CHANNEL_KEY, "Ch4")
        settings.setValue(MODE_KEY, "CV")
        settings.setValue(AREA_CM2_KEY, 0.92)
        settings.setValue(CC_CURRENT_DENSITY_KEY, 15.0)
        settings.setValue(CC_VOLTAGE_COMPLIANCE_KEY, 3.0)
        settings.setValue(CV_VOLTAGE_KEY, 1.2)
        settings.setValue(CV_CURRENT_COMPLIANCE_KEY, 20.0)
        settings.sync()

        panel.restore_persistent_settings()

        self.assertEqual("Ch4", panel.channel_combo.currentData())
        self.assertEqual("CV", panel.mode)
        self.assertEqual(0.92, panel.area_cm2)
        self.assertEqual(1.2, panel.setpoint_spin.value())
        self.assertEqual(20.0, panel.compliance_spin.value())
        for signal_spy in (
            output_requested,
            output_off_requested,
            handover_requested,
            channel_changed,
            mode_changed,
            area_changed,
            setpoint_changed,
            compliance_changed,
        ):
            self.assertEqual(0, signal_spy.count())

        panel.mode_combo.setCurrentIndex(0)
        self.assertEqual(15.0, panel.setpoint_spin.value())
        self.assertEqual(3.0, panel.compliance_spin.value())
        self.assertEqual(0, output_requested.count())
        self.assertEqual(0, output_off_requested.count())
        self.assertEqual(0, handover_requested.count())

    def test_main_window_restore_does_not_cross_production_boundaries(self) -> None:
        settings = self.settings()
        panel = ManualSMUPanel(settings=settings)
        control = SMUControlManager()
        driver = Mock(spec=SMUDriver)
        control.bind_driver(driver, output_confirmed_off=True)
        manual_sequence = Mock(name="SMUControlManager.request_manual_output_sequence")
        control.request_manual_output_sequence = manual_sequence
        relay_service = Mock(spec=RelayService)

        class MainWindowHarness(MainWindowDeviceMixin):
            pass

        window = MainWindowHarness()
        window.emergency_manager = SimpleNamespace(begin_operator_operation=Mock())
        window.smu_manager = SimpleNamespace(control=control)
        window.relay_service = relay_service
        window.polarity_settings_store = SimpleNamespace(settings=Mock())
        window.status_message = SimpleNamespace(setText=Mock())
        window.show_smu_error = Mock()
        manual_handler = Mock(wraps=window.request_manual_smu_output)
        panel.output_requested.connect(manual_handler)

        settings.setValue(CHANNEL_KEY, "Ch4")
        settings.setValue(MODE_KEY, "CV")
        settings.setValue("manual_smu/output_enabled", True)
        settings.setValue("manual_smu/active_routing_channel", "Ch4")
        settings.setValue("manual_smu/polarity", "REVERSED")
        settings.sync()

        try:
            panel.restore_persistent_settings()

            self.assertEqual("Ch4", panel.channel_combo.currentData())
            self.assertEqual("CV", panel.mode)
            self.assertEqual("—", panel.active_channel_value.text())
            self.assertEqual("OFF", panel.output_value.text())
            self.assertEqual("待輸出確認", panel.factor_value.text())
            self.assertIs(PolarityState.UNKNOWN, control.manual_polarity.state)
            manual_handler.assert_not_called()
            manual_sequence.assert_not_called()
            driver.set_output_enabled.assert_not_called()
            relay_service.select_smu_output_channel.assert_not_called()
            relay_service.clear_smu_output_channels.assert_not_called()
        finally:
            control.shutdown(safety_confirmed=True)

    def test_immediate_close_flushes_all_values_before_smu_confirmation(self) -> None:
        settings = self.settings()
        panel = ManualSMUPanel(settings=settings)
        control = Mock(spec=SMUControlManager)
        relay_service = Mock(spec=RelayService)

        class MainWindowHarness(MainWindowDeviceMixin):
            pass

        handler_host = MainWindowHarness()
        handler_host.emergency_manager = SimpleNamespace(begin_operator_operation=Mock())
        handler_host.smu_manager = SimpleNamespace(control=control)
        handler_host.relay_service = relay_service
        handler_host.polarity_settings_store = SimpleNamespace(settings=Mock())
        handler_host.status_message = SimpleNamespace(setText=Mock())
        handler_host.show_smu_error = Mock()
        manual_handler = Mock(wraps=handler_host.request_manual_smu_output)
        panel.output_requested.connect(manual_handler)

        panel.channel_combo.setCurrentIndex(3)
        panel.area_spin.setValue(0.92)
        panel.setpoint_spin.setValue(15.0)
        panel.compliance_spin.setValue(3.0)
        panel.mode_combo.setCurrentIndex(1)
        panel.setpoint_spin.setValue(1.2)
        panel.compliance_spin.setValue(20.0)
        self.assertTrue(panel._save_timer.isActive())
        self.assertFalse(settings.contains(CV_VOLTAGE_KEY))

        output_requested = QSignalSpy(panel.output_requested)
        output_off_requested = QSignalSpy(panel.output_off_requested)
        handover_requested = QSignalSpy(panel.handover_requested)
        events: list[str] = []
        original_flush = panel.flush_persistent_settings

        def flush_settings() -> None:
            events.append("SETTINGS_FLUSH")
            original_flush()

        panel.flush_persistent_settings = flush_settings
        relay_service.shutdown.side_effect = lambda: events.append("RELAY_SHUTDOWN")
        smu_manager = SimpleNamespace(
            is_connected=True,
            control=control,
            confirm_safe_for_close=lambda: (
                events.append("SMU_CONFIRM_OFF") or True
            ),
            shutdown=lambda **kwargs: events.append(f"SMU_SHUTDOWN:{kwargs}"),
        )
        window = SimpleNamespace(
            _close_in_progress=False,
            manual_smu_panel=panel,
            setEnabled=lambda enabled: events.append(f"GUI_ENABLED:{enabled}"),
            _cancel_measurement_for_emergency=lambda: events.append("STOP_WORKERS"),
            smu_monitor=SimpleNamespace(stop=lambda: events.append("MONITOR_STOP")),
            smu_manager=smu_manager,
            relay_service=relay_service,
            controller=SimpleNamespace(
                close_camera=lambda: events.append("CAMERA_CLOSE")
            ),
            emergency_manager=SimpleNamespace(trigger=Mock()),
        )
        event = FakeCloseEvent()

        MainWindow.closeEvent(window, event)

        try:
            self.assertTrue(event.accepted)
            self.assertLess(events.index("SETTINGS_FLUSH"), events.index("GUI_ENABLED:False"))
            self.assertLess(events.index("SETTINGS_FLUSH"), events.index("SMU_CONFIRM_OFF"))
            self.assertLess(events.index("MONITOR_STOP"), events.index("SMU_CONFIRM_OFF"))
            self.assertLess(events.index("SMU_CONFIRM_OFF"), events.index("RELAY_SHUTDOWN"))
            self.assertLess(
                events.index("RELAY_SHUTDOWN"),
                events.index("SMU_SHUTDOWN:{'safety_confirmed': True}"),
            )
            self.assertLess(
                events.index("SMU_SHUTDOWN:{'safety_confirmed': True}"),
                events.index("CAMERA_CLOSE"),
            )
            self.assertEqual(0, output_requested.count())
            self.assertEqual(0, output_off_requested.count())
            self.assertEqual(0, handover_requested.count())
            manual_handler.assert_not_called()
            control.request_manual_output_sequence.assert_not_called()
            relay_service.select_smu_output_channel.assert_not_called()
            relay_service.clear_smu_output_channels.assert_not_called()

            restored = ManualSMUPanel(settings=self.settings())
            self.assertEqual("Ch4", restored.channel_combo.currentData())
            self.assertEqual("CV", restored.mode)
            self.assertEqual(0.92, restored.area_cm2)
            self.assertEqual(1.2, restored.setpoint_spin.value())
            self.assertEqual(20.0, restored.compliance_spin.value())
            restored.mode_combo.setCurrentIndex(0)
            self.assertEqual(15.0, restored.setpoint_spin.value())
            self.assertEqual(3.0, restored.compliance_spin.value())
            restored.deleteLater()
        finally:
            panel.deleteLater()

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
