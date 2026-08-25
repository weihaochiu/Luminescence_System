from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from gui.main_window_devices import MainWindowDeviceMixin
from gui.main_window_errors import PendingSMUSafetyReconnect
from gui.smu_base import SMUDevice, SMUDriver, SMUFaultIdentity
from gui.smu_control import (
    SMUControlManager,
    SMUInterlockError,
    SMUOperationState,
    SMUOwnership,
)
from gui.smu_manager import SMUManager


def device(resource: str, serial: str, model: str = "B2901B") -> SMUDevice:
    return SMUDevice(
        resource,
        manufacturer="Keysight Technologies",
        model=model,
        serial_number=serial,
        idn=f"Keysight Technologies,{model},{serial},1.0",
        supported=True,
    )


class IdentityDriver(SMUDriver):
    def __init__(self, smu: SMUDevice, output: bool | None = False) -> None:
        super().__init__(object(), smu)
        self.output = output

    def query_output_enabled(self) -> bool | None:
        return self.output

    def safe_stop(self) -> list[str]:
        if self.output is None:
            return ["OUTPUT state unavailable"]
        self.output = False
        return []


class SMUFaultIdentityTests(unittest.TestCase):
    def control(self) -> SMUControlManager:
        control = SMUControlManager()
        self.addCleanup(
            lambda: control.shutdown(safety_confirmed=True, force=True)
        )
        return control

    def latch_and_disconnect(
        self,
        control: SMUControlManager,
        smu: SMUDevice,
    ) -> SMUFaultIdentity:
        control.bind_driver(IdentityDriver(smu), output_confirmed_off=True)
        control._latch_output_unknown("simulated communication loss")
        identity = control.fault_identity
        self.assertIsNotNone(identity)
        control.bind_driver(None, force=True)
        self.assertEqual(identity, control.fault_identity)
        return identity  # type: ignore[return-value]

    def test_case_a_same_physical_smu_completes_full_recovery(self) -> None:
        control = self.control()
        original = device("USB0::OLD::INSTR", "SERIAL-A")
        identity = self.latch_and_disconnect(control, original)
        reconnected = IdentityDriver(original, output=False)
        control.bind_driver(reconnected, output_confirmed_off=False)
        control.configure_safety_recovery(lambda: True, lambda: True)

        self.assertEqual(identity, control.fault_identity)
        self.assertTrue(control.recover_safety_fault())
        self.assertIsNone(control.fault_identity)
        self.assertFalse(control.output_unknown_latched)
        self.assertFalse(control.fault_latched)
        self.assertIs(control.ownership, SMUOwnership.IDLE)
        self.assertIs(control.operation_state, SMUOperationState.READY)

    def test_case_b_smu_b_cannot_clear_smu_a_fault(self) -> None:
        control = self.control()
        smu_a = device("USB0::A::INSTR", "SERIAL-A")
        identity = self.latch_and_disconnect(control, smu_a)
        smu_b = IdentityDriver(device("USB0::B::INSTR", "SERIAL-B"), output=False)

        with self.assertRaises(SMUInterlockError):
            control.bind_driver(smu_b, output_confirmed_off=True)

        self.assertEqual(identity, control.fault_identity)
        self.assertTrue(control.output_unknown_latched)
        self.assertTrue(control.fault_latched)
        self.assertIs(control.ownership, SMUOwnership.FAULT)

    def test_case_c_same_resource_with_different_serial_is_rejected(self) -> None:
        control = self.control()
        smu_a = device("USB0::REUSED::INSTR", "SERIAL-A")
        identity = self.latch_and_disconnect(control, smu_a)
        replacement = IdentityDriver(
            device("USB0::REUSED::INSTR", "SERIAL-B"),
            output=False,
        )

        with self.assertRaises(SMUInterlockError):
            control.bind_driver(replacement, output_confirmed_off=True)
        self.assertEqual(identity, control.fault_identity)

    def test_case_d_same_serial_and_model_with_changed_resource_is_allowed(self) -> None:
        control = self.control()
        smu_a = device("USB0::OLD::INSTR", "SERIAL-A")
        self.latch_and_disconnect(control, smu_a)
        moved = device("USB0::NEW::INSTR", "SERIAL-A")
        control.bind_driver(IdentityDriver(moved, output=False))
        control.configure_safety_recovery(lambda: True, lambda: True)

        self.assertTrue(control.recover_safety_fault())
        self.assertIsNone(control.fault_identity)

    def test_case_e_failed_reconnect_then_connect_b_retains_a_fault(self) -> None:
        manager = SMUManager()
        self.addCleanup(
            lambda: manager.shutdown(safety_confirmed=True, force=True)
        )
        smu_a = device("USB0::A::INSTR", "SERIAL-A")
        manager.control.bind_driver(IdentityDriver(smu_a), output_confirmed_off=True)
        manager.control._latch_output_unknown("A fault")
        manager.control.bind_driver(None, force=True)
        identity = manager.control.fault_identity
        pending = PendingSMUSafetyReconnect.create(identity, "SMU-203")  # type: ignore[arg-type]
        host = SimpleNamespace(
            _pending_smu_safety_reconnect=pending,
            device_panel=SimpleNamespace(set_smu_disconnected=Mock()),
            instrument_state_manager=SimpleNamespace(set_connection_error=Mock()),
        )

        MainWindowDeviceMixin.on_smu_connection_failed(host, "connection failed")
        self.assertIsNone(host._pending_smu_safety_reconnect)
        self.assertFalse(
            manager.connect_device(device("USB0::B::INSTR", "SERIAL-B"))
        )
        self.assertEqual(identity, manager.control.fault_identity)
        self.assertTrue(manager.control.output_unknown_latched)

    def test_case_f_pending_target_mismatch_never_requests_recovery(self) -> None:
        control = self.control()
        smu_a = device("USB0::A::INSTR", "SERIAL-A")
        identity = self.latch_and_disconnect(control, smu_a)
        recovery = Mock(return_value=True)
        control.request_safe_output_off = recovery  # type: ignore[method-assign]
        host = SimpleNamespace(
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

        MainWindowDeviceMixin.on_smu_connected(
            host,
            device("USB0::B::INSTR", "SERIAL-B"),
        )

        recovery.assert_not_called()
        host.report_error.assert_called_once()
        self.assertEqual(identity, control.fault_identity)
        self.assertTrue(control.output_unknown_latched)

    def test_case_g_secondary_fault_cannot_overwrite_first_identity(self) -> None:
        control = self.control()
        smu_a = device("USB0::A::INSTR", "SERIAL-A")
        identity = self.latch_and_disconnect(control, smu_a)

        control._latch_output_unknown("secondary failure while another device is selected")

        self.assertEqual(identity, control.fault_identity)

    def test_case_h_normal_connection_without_fault_is_unchanged(self) -> None:
        control = self.control()
        smu_b = device("USB0::B::INSTR", "SERIAL-B")

        control.bind_driver(IdentityDriver(smu_b), output_confirmed_off=True)

        self.assertIsNone(control.fault_identity)
        self.assertFalse(control.output_unknown_latched)
        self.assertFalse(control.fault_latched)
        self.assertIs(control.ownership, SMUOwnership.IDLE)
        self.assertIs(control.operation_state, SMUOperationState.READY)

    def test_recovery_defense_in_depth_rejects_mismatched_bound_driver(self) -> None:
        control = self.control()
        smu_a = device("USB0::A::INSTR", "SERIAL-A")
        identity = self.latch_and_disconnect(control, smu_a)
        with control._lock:
            control._driver = IdentityDriver(
                device("USB0::B::INSTR", "SERIAL-B"),
                output=False,
            )
        control.configure_safety_recovery(lambda: True, lambda: True)

        self.assertFalse(control.recover_safety_fault())
        self.assertEqual(identity, control.fault_identity)
        self.assertTrue(control.output_unknown_latched)

    def test_identity_match_requires_serial_model_and_manufacturer(self) -> None:
        original = SMUFaultIdentity.from_device(
            device("USB0::OLD::INSTR", "SERIAL-A")
        )
        self.assertTrue(
            original.matches_device(device("USB0::NEW::INSTR", "SERIAL-A"))
        )
        self.assertFalse(
            original.matches_device(device("USB0::OLD::INSTR", "SERIAL-B"))
        )
        self.assertFalse(
            original.matches_device(
                device("USB0::OLD::INSTR", "SERIAL-A", model="B2912A")
            )
        )


if __name__ == "__main__":
    unittest.main()
