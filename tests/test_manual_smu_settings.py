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
    ManualSMUSettings,
    ManualSMUSettingsStore,
    ManualSMUSettingsWriteError,
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


class FakeSettingsBackend:
    def __init__(self) -> None:
        self.persisted: dict[str, object] = {}


class FakeStatusSettings:
    """QSettings fake with the same first-error status lifecycle as Qt."""

    def __init__(
        self,
        *statuses: QSettings.Status,
        backend: FakeSettingsBackend | None = None,
        omitted_keys: set[str] | None = None,
        write_overrides: dict[str, object] | None = None,
    ) -> None:
        self._statuses = list(statuses)
        self._status = QSettings.Status.NoError
        self._backend = backend or FakeSettingsBackend()
        self._pending: dict[str, object] = {}
        self._omitted_keys = omitted_keys or set()
        self._write_overrides = write_overrides or {}
        self.sync_calls = 0

    def value(self, key: str, default: object = None) -> object:
        return self._backend.persisted.get(key, default)

    def setValue(self, key: str, value: object) -> None:  # noqa: N802 - Qt API
        self._pending[key] = value

    def sync(self) -> None:
        self.sync_calls += 1
        outcome = (
            self._statuses.pop(0)
            if self._statuses
            else QSettings.Status.NoError
        )
        if self._status == QSettings.Status.NoError:
            self._status = outcome
        if outcome == QSettings.Status.NoError:
            persisted = {
                key: value
                for key, value in self._pending.items()
                if key not in self._omitted_keys
            }
            persisted.update(self._write_overrides)
            self._backend.persisted.update(persisted)
            self._pending.clear()

    def status(self) -> QSettings.Status:
        return self._status

    def contains(self, key: str) -> bool:
        return key in self._backend.persisted

    def allKeys(self) -> list[str]:  # noqa: N802 - Qt API
        return list(self._backend.persisted)


class FakeSettingsFactory:
    def __init__(self, *instance_statuses: QSettings.Status) -> None:
        self.backend = FakeSettingsBackend()
        self._instance_statuses = list(instance_statuses)
        self.instances: list[FakeStatusSettings] = []
        self.omitted_keys_by_instance: dict[int, set[str]] = {}
        self.write_overrides_by_instance: dict[int, dict[str, object]] = {}

    def source(self) -> FakeStatusSettings:
        return FakeStatusSettings(backend=self.backend)

    def __call__(self) -> FakeStatusSettings:
        index = len(self.instances)
        status = (
            self._instance_statuses.pop(0)
            if self._instance_statuses
            else QSettings.Status.NoError
        )
        settings = FakeStatusSettings(
            status,
            backend=self.backend,
            omitted_keys=self.omitted_keys_by_instance.get(index),
            write_overrides=self.write_overrides_by_instance.get(index),
        )
        self.instances.append(settings)
        return settings


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

    def production_boundaries(
        self,
        panel: ManualSMUPanel,
    ) -> tuple[SMUControlManager, Mock, Mock, Mock, Mock]:
        control = SMUControlManager()
        driver = Mock(spec=SMUDriver)
        control.bind_driver(driver, output_confirmed_off=True)
        manual_sequence = Mock(
            name="SMUControlManager.request_manual_output_sequence"
        )
        control.request_manual_output_sequence = manual_sequence
        relay_service = Mock(spec=RelayService)

        class MainWindowHarness(MainWindowDeviceMixin):
            pass

        handler_host = MainWindowHarness()
        handler_host.emergency_manager = SimpleNamespace(
            begin_operator_operation=Mock()
        )
        handler_host.smu_manager = SimpleNamespace(control=control)
        handler_host.relay_service = relay_service
        handler_host.polarity_settings_store = SimpleNamespace(settings=Mock())
        handler_host.status_message = SimpleNamespace(setText=Mock())
        handler_host.show_smu_error = Mock()
        manual_handler = Mock(wraps=handler_host.request_manual_smu_output)
        panel.output_requested.connect(manual_handler)
        return control, driver, manual_sequence, relay_service, manual_handler

    def close_window(
        self,
        panel: ManualSMUPanel,
        control: SMUControlManager,
        relay_service: Mock,
        confirmations: list[bool],
    ) -> tuple[SimpleNamespace, FakeCloseEvent, list[str]]:
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
                events.append("SMU_CONFIRM_OFF") or confirmations.pop(0)
            ),
            shutdown=lambda **kwargs: events.append(f"SMU_SHUTDOWN:{kwargs}"),
        )
        window = SimpleNamespace(
            _close_in_progress=False,
            manual_smu_panel=panel,
            setEnabled=lambda enabled: events.append(f"GUI_ENABLED:{enabled}"),
            _cancel_measurement_for_emergency=lambda: events.append("STOP_WORKERS"),
            smu_monitor=SimpleNamespace(
                stop=lambda: events.append("MONITOR_STOP"),
                start=lambda: events.append("MONITOR_START"),
            ),
            smu_manager=smu_manager,
            relay_service=relay_service,
            controller=SimpleNamespace(
                close_camera=lambda: events.append("CAMERA_CLOSE")
            ),
            emergency_manager=SimpleNamespace(trigger=Mock()),
        )
        window._cancel_close_after_safety_failure = (
            lambda event: MainWindow._cancel_close_after_safety_failure(window, event)
        )
        window._unsafe_smu_close_decision = Mock(return_value="cancel")
        window._confirm_forced_close = Mock(return_value=False)
        return window, FakeCloseEvent(), events

    def test_store_accepts_no_error_status_after_sync(self) -> None:
        factory = FakeSettingsFactory(
            QSettings.Status.NoError,
            QSettings.Status.NoError,
        )

        ManualSMUSettingsStore(
            factory.source(),
            settings_factory=factory,
        ).save(ManualSMUSettings(channel="Ch4"))

        self.assertEqual(1, factory.instances[0].sync_calls)
        self.assertEqual(1, factory.instances[1].sync_calls)
        self.assertEqual("Ch4", factory.backend.persisted[CHANNEL_KEY])

    def test_store_raises_for_access_error_status_without_sync_exception(self) -> None:
        factory = FakeSettingsFactory(QSettings.Status.AccessError)

        with self.assertRaisesRegex(
            ManualSMUSettingsWriteError,
            r"sync failed: AccessError",
        ):
            ManualSMUSettingsStore(
                factory.source(),
                settings_factory=factory,
            ).save(ManualSMUSettings())

        self.assertEqual(1, factory.instances[0].sync_calls)

    def test_store_raises_for_format_error_status(self) -> None:
        factory = FakeSettingsFactory(QSettings.Status.FormatError)

        with self.assertRaisesRegex(
            ManualSMUSettingsWriteError,
            r"sync failed: FormatError",
        ):
            ManualSMUSettingsStore(
                factory.source(),
                settings_factory=factory,
            ).save(ManualSMUSettings())

    def test_qsettings_error_status_is_sticky_but_fresh_instance_recovers(
        self,
    ) -> None:
        blocker = Path(self.temporary_directory.name) / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        settings_path = blocker / "sticky.ini"
        poisoned = QSettings(str(settings_path), QSettings.Format.IniFormat)
        poisoned.setValue("probe/value", 1)
        poisoned.sync()
        self.assertEqual(QSettings.Status.AccessError, poisoned.status())

        blocker.unlink()
        blocker.mkdir()
        poisoned.setValue("probe/value", 2)
        poisoned.sync()

        self.assertTrue(settings_path.exists())
        self.assertEqual(QSettings.Status.AccessError, poisoned.status())
        fresh = QSettings(str(settings_path), QSettings.Format.IniFormat)
        fresh.setValue("probe/value", 3)
        fresh.sync()
        self.assertEqual(QSettings.Status.NoError, fresh.status())
        self.assertEqual(3, fresh.value("probe/value"))

    def test_fake_status_settings_preserves_first_error_like_qt(self) -> None:
        settings = FakeStatusSettings(
            QSettings.Status.AccessError,
            QSettings.Status.NoError,
        )
        settings.setValue("probe/value", 1)
        settings.sync()
        self.assertEqual(QSettings.Status.AccessError, settings.status())

        settings.setValue("probe/value", 2)
        settings.sync()

        self.assertEqual(2, settings.value("probe/value"))
        self.assertEqual(QSettings.Status.AccessError, settings.status())

    def test_native_factory_preserves_production_backend_identity_without_write(
        self,
    ) -> None:
        organization = "EL Measurement Lab"
        application = "EL Measurement Equipment Control"
        source = QSettings(
            QSettings.Format.NativeFormat,
            QSettings.Scope.UserScope,
            organization,
            application,
        )
        source.setFallbacksEnabled(False)
        store = ManualSMUSettingsStore(source)
        first = store._settings_factory()
        second = store._settings_factory()
        self.assertIsNot(first, second)
        for fresh in (first, second):
            self.assertEqual(source.format(), fresh.format())
            self.assertEqual(source.scope(), fresh.scope())
            self.assertEqual(organization, fresh.organizationName())
            self.assertEqual(application, fresh.applicationName())
            self.assertEqual(source.fileName(), fresh.fileName())
            self.assertEqual(source.fallbacksEnabled(), fresh.fallbacksEnabled())
            self.assertEqual(
                source.isAtomicSyncRequired(),
                fresh.isAtomicSyncRequired(),
            )

    def test_readback_verifies_all_seven_values_with_fresh_reader(self) -> None:
        factory = FakeSettingsFactory(
            QSettings.Status.NoError,
            QSettings.Status.NoError,
        )
        expected = ManualSMUSettings(
            channel="Ch4",
            mode="CV",
            area_cm2=0.92,
            cc_current_density_ma_cm2=15.0,
            cc_voltage_compliance_v=3.0,
            cv_voltage_v=1.2,
            cv_current_compliance_ma_cm2=20.0,
        )

        ManualSMUSettingsStore(
            factory.source(),
            settings_factory=factory,
        ).save(expected)

        self.assertIsNot(factory.instances[0], factory.instances[1])
        self.assertEqual(
            expected,
            ManualSMUSettingsStore._load_from(factory.instances[1]),
        )

    def test_incomplete_readback_is_treated_as_persistence_failure(self) -> None:
        factory = FakeSettingsFactory(
            QSettings.Status.NoError,
            QSettings.Status.NoError,
        )
        factory.omitted_keys_by_instance[0] = {CV_VOLTAGE_KEY}
        panel = ManualSMUPanel(
            settings=factory.source(),
            settings_factory=factory,
        )
        try:
            panel.mode_combo.setCurrentIndex(1)
            panel.setpoint_spin.setValue(1.2)
            with self.assertRaisesRegex(
                ManualSMUSettingsWriteError,
                "readback verification failed",
            ):
                panel.flush_persistent_settings()

            self.assertTrue(panel.persistent_settings_dirty)
            self.assertTrue(panel._save_timer.isActive())
            self.assertEqual(2000, panel._save_timer.interval())
        finally:
            panel._save_timer.stop()
            panel.deleteLater()

    def test_dirty_state_clears_only_after_successful_sync(self) -> None:
        factory = FakeSettingsFactory(
            QSettings.Status.NoError,
            QSettings.Status.NoError,
            QSettings.Status.AccessError,
        )
        panel = ManualSMUPanel(
            settings=factory.source(),
            settings_factory=factory,
        )
        try:
            self.assertFalse(panel.persistent_settings_dirty)
            panel.channel_combo.setCurrentIndex(3)
            self.assertTrue(panel.persistent_settings_dirty)

            panel.flush_persistent_settings()
            self.assertFalse(panel.persistent_settings_dirty)

            panel.area_spin.setValue(0.92)
            self.assertTrue(panel.persistent_settings_dirty)
            with self.assertRaises(ManualSMUSettingsWriteError):
                panel.flush_persistent_settings()

            self.assertTrue(panel.persistent_settings_dirty)
            self.assertTrue(panel._save_timer.isActive())
            self.assertGreaterEqual(panel._save_timer.interval(), 1000)
        finally:
            panel._save_timer.stop()
            panel.deleteLater()

    def test_debounce_failure_is_logged_and_schedules_slow_retry(self) -> None:
        factory = FakeSettingsFactory(QSettings.Status.FormatError)
        panel = ManualSMUPanel(
            settings=factory.source(),
            settings_factory=factory,
        )
        try:
            panel.area_spin.setValue(0.92)

            with self.assertLogs("gui.smu_manual_panel", level="ERROR") as captured:
                panel._flush_persistent_settings_from_timer()

            self.assertTrue(panel.persistent_settings_dirty)
            self.assertTrue(panel._save_timer.isActive())
            self.assertGreaterEqual(panel._save_timer.interval(), 1000)
            self.assertTrue(
                any(
                    "Manual SMU settings save failed" in message
                    and "FormatError" in message
                    for message in captured.output
                )
            )
        finally:
            panel._save_timer.stop()
            panel.deleteLater()

    def test_persistent_access_errors_use_distinct_low_frequency_attempts(
        self,
    ) -> None:
        factory = FakeSettingsFactory(
            QSettings.Status.AccessError,
            QSettings.Status.AccessError,
            QSettings.Status.AccessError,
        )
        panel = ManualSMUPanel(
            settings=factory.source(),
            settings_factory=factory,
        )
        (
            control,
            driver,
            manual_sequence,
            relay_service,
            manual_handler,
        ) = self.production_boundaries(panel)
        output_requested = QSignalSpy(panel.output_requested)
        output_off_requested = QSignalSpy(panel.output_off_requested)
        handover_requested = QSignalSpy(panel.handover_requested)
        try:
            panel.area_spin.setValue(0.92)
            with self.assertLogs("gui.smu_manual_panel", level="ERROR") as captured:
                for _ in range(3):
                    panel._flush_persistent_settings_from_timer()
                    self.assertTrue(panel.persistent_settings_dirty)
                    self.assertTrue(panel._save_timer.isActive())
                    self.assertEqual(2000, panel._save_timer.interval())

            self.assertEqual(3, len(factory.instances))
            self.assertEqual(3, len({id(item) for item in factory.instances}))
            self.assertTrue(
                all("AccessError" in message for message in captured.output)
            )
            self.assertTrue(
                all("area_cm2" not in message for message in captured.output)
            )
            self.assertEqual(0, output_requested.count())
            self.assertEqual(0, output_off_requested.count())
            self.assertEqual(0, handover_requested.count())
            manual_handler.assert_not_called()
            manual_sequence.assert_not_called()
            driver.set_output_enabled.assert_not_called()
            relay_service.select_smu_output_channel.assert_not_called()
            relay_service.clear_smu_output_channels.assert_not_called()
        finally:
            panel._save_timer.stop()
            control.shutdown(safety_confirmed=True)
            panel.deleteLater()

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

    def test_access_error_on_close_does_not_block_safe_shutdown(self) -> None:
        factory = FakeSettingsFactory(QSettings.Status.AccessError)
        panel = ManualSMUPanel(
            settings=factory.source(),
            settings_factory=factory,
        )
        (
            control,
            driver,
            manual_sequence,
            relay_service,
            manual_handler,
        ) = self.production_boundaries(panel)
        output_requested = QSignalSpy(panel.output_requested)
        output_off_requested = QSignalSpy(panel.output_off_requested)
        handover_requested = QSignalSpy(panel.handover_requested)
        panel.channel_combo.setCurrentIndex(3)
        window, event, events = self.close_window(
            panel,
            control,
            relay_service,
            [True],
        )

        try:
            with self.assertLogs("gui.main_window_close", level="ERROR") as captured:
                MainWindow.closeEvent(window, event)

            self.assertTrue(event.accepted)
            self.assertTrue(panel.persistent_settings_dirty)
            self.assertTrue(panel._save_timer.isActive())
            self.assertLess(
                events.index("SETTINGS_FLUSH"),
                events.index("GUI_ENABLED:False"),
            )
            self.assertLess(
                events.index("GUI_ENABLED:False"),
                events.index("MONITOR_STOP"),
            )
            self.assertLess(
                events.index("MONITOR_STOP"),
                events.index("SMU_CONFIRM_OFF"),
            )
            self.assertLess(
                events.index("SMU_CONFIRM_OFF"),
                events.index("RELAY_SHUTDOWN"),
            )
            self.assertLess(
                events.index("RELAY_SHUTDOWN"),
                events.index("SMU_SHUTDOWN:{'safety_confirmed': True}"),
            )
            self.assertLess(
                events.index("SMU_SHUTDOWN:{'safety_confirmed': True}"),
                events.index("CAMERA_CLOSE"),
            )
            self.assertTrue(
                any(
                    "Manual SMU settings flush failed during application close"
                    in message
                    and "AccessError" in message
                    for message in captured.output
                )
            )
            self.assertEqual(0, output_requested.count())
            self.assertEqual(0, output_off_requested.count())
            self.assertEqual(0, handover_requested.count())
            manual_handler.assert_not_called()
            manual_sequence.assert_not_called()
            driver.set_output_enabled.assert_not_called()
            relay_service.select_smu_output_channel.assert_not_called()
            relay_service.clear_smu_output_channels.assert_not_called()
        finally:
            panel._save_timer.stop()
            control.shutdown(safety_confirmed=True)
            panel.deleteLater()

    def test_cancel_after_access_error_keeps_dirty_retry_and_saves_all_values(
        self,
    ) -> None:
        factory = FakeSettingsFactory(
            QSettings.Status.AccessError,
            QSettings.Status.NoError,
            QSettings.Status.NoError,
        )
        settings = factory.source()
        panel = ManualSMUPanel(
            settings=settings,
            settings_factory=factory,
        )
        (
            control,
            driver,
            manual_sequence,
            relay_service,
            manual_handler,
        ) = self.production_boundaries(panel)
        output_requested = QSignalSpy(panel.output_requested)
        output_off_requested = QSignalSpy(panel.output_off_requested)
        handover_requested = QSignalSpy(panel.handover_requested)

        panel.channel_combo.setCurrentIndex(3)
        panel.area_spin.setValue(0.92)
        panel.setpoint_spin.setValue(15.0)
        panel.compliance_spin.setValue(3.0)
        panel.mode_combo.setCurrentIndex(1)
        panel.setpoint_spin.setValue(1.2)
        panel.compliance_spin.setValue(20.0)
        window, event, events = self.close_window(
            panel,
            control,
            relay_service,
            [False],
        )

        try:
            with self.assertLogs("gui.main_window_close", level="ERROR"):
                MainWindow.closeEvent(window, event)

            self.assertFalse(event.accepted)
            self.assertFalse(window._close_in_progress)
            self.assertIn("GUI_ENABLED:True", events)
            self.assertIn("MONITOR_START", events)
            self.assertNotIn("RELAY_SHUTDOWN", events)
            self.assertTrue(panel.persistent_settings_dirty)
            self.assertTrue(panel._save_timer.isActive())
            self.assertGreaterEqual(panel._save_timer.interval(), 1000)
            self.assertIsNone(settings.value(CHANNEL_KEY))

            panel._flush_persistent_settings_from_timer()

            self.assertFalse(panel.persistent_settings_dirty)
            self.assertFalse(panel._save_timer.isActive())
            self.assertIsNot(factory.instances[0], factory.instances[1])
            restored = ManualSMUPanel(
                settings=factory.source(),
                settings_factory=factory,
            )
            self.assertEqual("Ch4", restored.channel_combo.currentData())
            self.assertEqual("CV", restored.mode)
            self.assertEqual(0.92, restored.area_cm2)
            self.assertEqual(1.2, restored.setpoint_spin.value())
            self.assertEqual(20.0, restored.compliance_spin.value())
            restored.mode_combo.setCurrentIndex(0)
            self.assertEqual(15.0, restored.setpoint_spin.value())
            self.assertEqual(3.0, restored.compliance_spin.value())

            self.assertEqual(0, output_requested.count())
            self.assertEqual(0, output_off_requested.count())
            self.assertEqual(0, handover_requested.count())
            manual_handler.assert_not_called()
            manual_sequence.assert_not_called()
            driver.set_output_enabled.assert_not_called()
            relay_service.select_smu_output_channel.assert_not_called()
            relay_service.clear_smu_output_channels.assert_not_called()
            self.assertIs(PolarityState.UNKNOWN, control.manual_polarity.state)
            self.assertEqual("—", panel.active_channel_value.text())
            self.assertEqual("OFF", panel.output_value.text())
            restored.deleteLater()
        finally:
            panel._save_timer.stop()
            control.shutdown(safety_confirmed=True)
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
