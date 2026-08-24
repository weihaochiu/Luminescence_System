from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.error_reporter import ErrorReporter
from core.error_registry import default_error_registry
from gui.dialogs.error_dialog import ErrorDialog
from gui.main_window_errors import (
    _error_action_handlers,
    _error_dialog_reconnect,
    _error_reconnect_available,
    _smu_reconnect_target,
)
from gui.main_window_devices import MainWindowDeviceMixin
from gui.smu_base import SMUDevice
from gui.smu_manager import SMUManager
from tests.qt_test_utils import ensure_qapplication


class ErrorActionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_every_visible_registry_action_has_a_handler(self) -> None:
        reporter = ErrorReporter()
        for definition in default_error_registry.all():
            event = reporter.report(definition.code, present=False)
            handlers = {action: (lambda _event: True) for action in definition.actions}
            dialog = ErrorDialog(event, action_handlers=handlers)
            self.addCleanup(dialog.close)
            self.assertEqual(set(definition.actions), set(dialog.action_buttons))

    def test_subsystem_reconnect_dispatch_does_not_cross_devices(self) -> None:
        reporter = ErrorReporter()
        camera_refresh = Mock()
        relay_refresh = Mock()
        smu_reconnect = Mock(return_value=True)
        device = SMUDevice("USB0::SMU::INSTR", model="B2901B", supported=True)
        dummy = SimpleNamespace(
            refresh_devices=camera_refresh,
            refresh_relay_connection=relay_refresh,
            _error_reconnect_available=lambda _event: True,
            _smu_reconnect_safety_pending=False,
            _measurement_worker=None,
            device_panel=SimpleNamespace(selected_smu=lambda: device),
            smu_manager=SimpleNamespace(
                devices=[device],
                connected_device=None,
                control=SimpleNamespace(output_unknown_latched=True),
                reconnect_device_for_safety=smu_reconnect,
            ),
        )

        self.assertTrue(_error_dialog_reconnect(dummy, reporter.report("CAM-201", present=False)))
        camera_refresh.assert_called_once_with()
        relay_refresh.assert_not_called()
        smu_reconnect.assert_not_called()

        camera_refresh.reset_mock()
        self.assertTrue(_error_dialog_reconnect(dummy, reporter.report("REL-203", present=False)))
        relay_refresh.assert_called_once_with()
        camera_refresh.assert_not_called()
        smu_reconnect.assert_not_called()

        relay_refresh.reset_mock()
        self.assertTrue(_error_dialog_reconnect(dummy, reporter.report("SMU-203", present=False)))
        smu_reconnect.assert_called_once_with(device)
        camera_refresh.assert_not_called()
        relay_refresh.assert_not_called()
        self.assertTrue(dummy._smu_reconnect_safety_pending)
        self.assertTrue(dummy.smu_manager.control.output_unknown_latched)

    def test_smu_reconnect_never_falls_back_from_requested_resource(self) -> None:
        expected = SMUDevice("USB0::EXPECTED::INSTR", model="B2901B", supported=True)
        other = SMUDevice("USB0::OTHER::INSTR", model="B2901B", supported=True)
        event = ErrorReporter().report(
            "SMU-203",
            context={"resource": expected.visa_address},
            present=False,
        )
        dummy = SimpleNamespace(
            device_panel=SimpleNamespace(selected_smu=lambda: other),
            smu_manager=SimpleNamespace(devices=[other], connected_device=None),
        )
        self.assertIsNone(_smu_reconnect_target(dummy, event))

    def test_reconnect_is_hidden_while_measurement_runs(self) -> None:
        event = ErrorReporter().report("CAM-201", present=False)
        dummy = SimpleNamespace(_measurement_worker=object())
        self.assertFalse(_error_reconnect_available(dummy, event))

    def test_measurement_failure_only_offers_safe_shutdown(self) -> None:
        event = ErrorReporter().report("MEAS-201", present=False)
        dummy = SimpleNamespace(
            _error_dialog_safe_shutdown=Mock(return_value=True),
            _error_dialog_reconnect=Mock(return_value=True),
            _error_reconnect_available=lambda _event: True,
        )
        self.assertEqual(
            {"safe_shutdown"},
            set(_error_action_handlers(dummy, event)),
        )

    def test_smu_transport_reconnect_forces_no_false_safety_confirmation(self) -> None:
        manager = SMUManager()
        self.addCleanup(manager._executor.shutdown, wait=False, cancel_futures=True)
        device = SMUDevice("USB0::SMU::INSTR", model="B2901B", supported=True)
        manager._driver = object()
        manager.connected_device = device
        manager._close_session = Mock(return_value=True)
        manager.connect_device = Mock()

        self.assertTrue(manager.reconnect_device_for_safety(device))
        manager._close_session.assert_called_once_with(
            safe_output=False,
            force_unbind=True,
        )
        manager.connect_device.assert_called_once_with(device)

    def test_smu_transport_reconnect_rejects_a_different_device(self) -> None:
        manager = SMUManager()
        self.addCleanup(manager._executor.shutdown, wait=False, cancel_futures=True)
        connected = SMUDevice("USB0::CONNECTED::INSTR", model="B2901B", supported=True)
        other = SMUDevice("USB0::OTHER::INSTR", model="B2901B", supported=True)
        manager._driver = object()
        manager.connected_device = connected
        manager._close_session = Mock(return_value=True)
        manager.connect_device = Mock()

        self.assertFalse(manager.reconnect_device_for_safety(other))
        manager._close_session.assert_not_called()
        manager.connect_device.assert_not_called()

    def test_smu_203_reconnect_keeps_lock_until_existing_recovery_runs(self) -> None:
        device = SMUDevice(
            "USB0::SMU::INSTR", model="B2901B", serial_number="MY123", supported=True
        )
        recovery = Mock(return_value=True)
        control = SimpleNamespace(
            output_unknown_latched=True,
            request_safe_output_off=recovery,
        )
        dummy = SimpleNamespace(
            _smu_reconnect_safety_pending=True,
            device_panel=SimpleNamespace(set_smu_connected=Mock()),
            settings=SimpleNamespace(setValue=Mock()),
            _remember_smu_selection=Mock(),
            instrument_state_manager=SimpleNamespace(set_connected=Mock()),
            smu_manager=SimpleNamespace(control=control),
            smu_monitor=SimpleNamespace(start=Mock()),
        )

        MainWindowDeviceMixin.on_smu_connected(dummy, device)
        self.assertFalse(dummy._smu_reconnect_safety_pending)
        self.assertTrue(control.output_unknown_latched)
        recovery.assert_called_once_with("post-reconnect safety verification")


if __name__ == "__main__":
    unittest.main()
