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
    PendingSMUSafetyReconnect,
    _error_action_handlers,
    _error_dialog_reconnect,
    _error_reconnect_available,
    _smu_reconnect_target,
)
from gui.main_window_devices import MainWindowDeviceMixin
from gui.smu_base import SMUDevice
from gui.smu_base import SMUDriver, SMUFaultIdentity
from gui.smu_manager import SMUManager
from tests.qt_test_utils import ensure_qapplication


class ErrorActionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    @staticmethod
    def smu(resource: str = "USB0::SMU::INSTR", serial: str = "MY123") -> SMUDevice:
        return SMUDevice(
            resource,
            manufacturer="Keysight Technologies",
            model="B2901B",
            serial_number=serial,
            idn=f"Keysight Technologies,B2901B,{serial},1.0",
            supported=True,
        )

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
        device = self.smu()
        identity = SMUFaultIdentity.from_device(device)
        dummy = SimpleNamespace(
            refresh_devices=camera_refresh,
            refresh_relay_connection=relay_refresh,
            _error_reconnect_available=lambda _event: True,
            _pending_smu_safety_reconnect=None,
            _auto_connect_after_scan=False,
            _measurement_worker=None,
            device_panel=SimpleNamespace(selected_smu=lambda: device),
            smu_manager=SimpleNamespace(
                devices=[device],
                connected_device=None,
                control=SimpleNamespace(
                    output_unknown_latched=True,
                    fault_identity=identity,
                ),
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
        self.assertEqual(identity, dummy._pending_smu_safety_reconnect.target)
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
            smu_manager=SimpleNamespace(
                devices=[other],
                connected_device=None,
                control=SimpleNamespace(fault_identity=None),
            ),
        )
        self.assertIsNone(_smu_reconnect_target(dummy, event))

    def test_fault_target_scan_matches_same_serial_after_resource_change(self) -> None:
        original = self.smu("USB0::OLD::INSTR", "SERIAL-A")
        moved = self.smu("USB0::NEW::INSTR", "SERIAL-A")
        other = self.smu("USB0::OTHER::INSTR", "SERIAL-B")
        identity = SMUFaultIdentity.from_device(original)
        event = ErrorReporter().report("SMU-203", present=False)
        dummy = SimpleNamespace(
            device_panel=SimpleNamespace(selected_smu=lambda: other),
            smu_manager=SimpleNamespace(
                devices=[other, moved],
                connected_device=None,
                control=SimpleNamespace(fault_identity=identity),
            ),
        )

        self.assertEqual(moved, _smu_reconnect_target(dummy, event))

    def test_fault_target_scan_refuses_ambiguous_identity_matches(self) -> None:
        original = self.smu("USB0::OLD::INSTR", "SERIAL-A")
        matches = [
            self.smu("USB0::ONE::INSTR", "SERIAL-A"),
            self.smu("USB0::TWO::INSTR", "SERIAL-A"),
        ]
        event = ErrorReporter().report("SMU-203", present=False)
        dummy = SimpleNamespace(
            device_panel=SimpleNamespace(selected_smu=lambda: None),
            smu_manager=SimpleNamespace(
                devices=matches,
                connected_device=None,
                control=SimpleNamespace(
                    fault_identity=SMUFaultIdentity.from_device(original)
                ),
            ),
        )

        self.assertIsNone(_smu_reconnect_target(dummy, event))

    def test_pending_safety_scan_connects_only_the_unique_identity_match(self) -> None:
        original = self.smu("USB0::OLD::INSTR", "SERIAL-A")
        moved = self.smu("USB0::NEW::INSTR", "SERIAL-A")
        other = self.smu("USB0::OTHER::INSTR", "SERIAL-B")
        identity = SMUFaultIdentity.from_device(original)
        reconnect = Mock(return_value=True)
        panel = SimpleNamespace(
            set_smu_devices=Mock(),
            set_smu_disconnected=Mock(),
            select_smu=Mock(),
        )
        dummy = SimpleNamespace(
            settings=SimpleNamespace(value=Mock(return_value="")),
            device_panel=panel,
            instrument_state_manager=SimpleNamespace(set_disconnected=Mock()),
            _auto_connect_after_scan=False,
            _pending_smu_safety_reconnect=PendingSMUSafetyReconnect.create(
                identity, "SMU-203"
            ),
            smu_manager=SimpleNamespace(
                control=SimpleNamespace(fault_identity=identity),
                reconnect_device_for_safety=reconnect,
            ),
            report_error=Mock(),
        )

        MainWindowDeviceMixin.on_smu_scan_finished(dummy, [other, moved])

        panel.select_smu.assert_called_once_with(moved.visa_address)
        reconnect.assert_called_once_with(moved)
        dummy.report_error.assert_not_called()

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
        device = self.smu()
        driver = SMUDriver(object(), device)
        manager.control.bind_driver(driver, output_confirmed_off=True)
        manager.control._latch_output_unknown("test fault")
        manager._driver = driver
        manager.connected_device = device
        manager._close_session = Mock(return_value=True)
        manager.connect_device = Mock(return_value=True)

        self.assertTrue(manager.reconnect_device_for_safety(device))
        manager._close_session.assert_called_once_with(
            safe_output=False,
            force_unbind=True,
        )
        manager.connect_device.assert_called_once_with(device)

    def test_smu_transport_reconnect_rejects_a_different_device(self) -> None:
        manager = SMUManager()
        self.addCleanup(manager._executor.shutdown, wait=False, cancel_futures=True)
        connected = self.smu("USB0::CONNECTED::INSTR", "SERIAL-A")
        other = self.smu("USB0::OTHER::INSTR", "SERIAL-B")
        driver = SMUDriver(object(), connected)
        manager.control.bind_driver(driver, output_confirmed_off=True)
        manager.control._latch_output_unknown("test fault")
        manager._driver = driver
        manager.connected_device = connected
        manager._close_session = Mock(return_value=True)
        manager.connect_device = Mock()

        self.assertFalse(manager.reconnect_device_for_safety(other))
        manager._close_session.assert_not_called()
        manager.connect_device.assert_not_called()

    def test_smu_203_reconnect_keeps_lock_until_existing_recovery_runs(self) -> None:
        device = self.smu()
        identity = SMUFaultIdentity.from_device(device)
        recovery = Mock(return_value=True)
        control = SimpleNamespace(
            output_unknown_latched=True,
            request_safe_output_off=recovery,
        )
        dummy = SimpleNamespace(
            _pending_smu_safety_reconnect=PendingSMUSafetyReconnect.create(
                identity, "SMU-203"
            ),
            device_panel=SimpleNamespace(set_smu_connected=Mock()),
            settings=SimpleNamespace(setValue=Mock()),
            _remember_smu_selection=Mock(),
            instrument_state_manager=SimpleNamespace(set_connected=Mock()),
            smu_manager=SimpleNamespace(control=control),
            smu_monitor=SimpleNamespace(start=Mock()),
            report_error=Mock(),
        )

        MainWindowDeviceMixin.on_smu_connected(dummy, device)
        self.assertIsNone(dummy._pending_smu_safety_reconnect)
        self.assertTrue(control.output_unknown_latched)
        recovery.assert_called_once_with("post-reconnect safety verification")


if __name__ == "__main__":
    unittest.main()
