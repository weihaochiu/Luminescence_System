from __future__ import annotations

import unittest
from unittest.mock import patch

from gui.smu_base import SMUDevice, SMUDriver
from gui.smu_manager import SMUManager, select_auto_connect_device


def supported(address: str, serial: str) -> SMUDevice:
    return SMUDevice(
        visa_address=address,
        manufacturer="Keysight Technologies",
        model="B2901BL",
        serial_number=serial,
        supported=True,
    )


class FakeResource:
    def __init__(
        self,
        output_response: str = "0",
        auto_output_response: str = "0",
    ) -> None:
        self.output_response = output_response
        self.auto_output_response = auto_output_response
        self.commands: list[str] = []
        self.transactions: list[str] = []
        self.closed = False
        self.timeout = 0
        self.write_termination = ""
        self.read_termination = ""

    def query(self, command: str) -> str:
        self.transactions.append(command)
        if command == "*IDN?":
            return "Keysight Technologies,B2901BL,SERIAL-1,1.0"
        if command == ":OUTP?":
            return self.output_response
        if command == ":OUTP:ON:AUTO?":
            return self.auto_output_response
        raise AssertionError(f"unexpected query: {command}")

    def write(self, command: str) -> None:
        self.commands.append(command)
        self.transactions.append(command)

    def close(self) -> None:
        self.closed = True


class FakeResourceManager:
    def __init__(self, resource: FakeResource) -> None:
        self.resource = resource
        self.closed = False

    def open_resource(self, _address: str, open_timeout: int = 0) -> FakeResource:
        self.resource.open_timeout = open_timeout
        return self.resource

    def close(self) -> None:
        self.closed = True


class SMUAutoConnectTests(unittest.TestCase):
    def test_selection_priority_and_multi_device_ambiguity(self) -> None:
        first = supported("USB0::1::INSTR", "SERIAL-1")
        second = supported("USB0::2::INSTR", "SERIAL-2")
        self.assertIs(
            second,
            select_auto_connect_device(
                [first, second],
                preferred_serial="SERIAL-2",
                preferred_address=first.visa_address,
            ),
        )
        self.assertIs(
            first,
            select_auto_connect_device([first, second], preferred_address=first.visa_address),
        )
        self.assertIsNone(select_auto_connect_device([first, second]))
        self.assertIs(first, select_auto_connect_device([first]))

    def test_safe_initialization_never_turns_output_on(self) -> None:
        resource = FakeResource(output_response="0")
        manager = FakeResourceManager(resource)
        device = supported("USB0::1::INSTR", "SERIAL-1")
        with patch.object(SMUManager, "_open_resource_manager", return_value=(manager, "test")):
            returned_manager, returned_resource, verified, driver = SMUManager._connect_worker(
                device
            )
        self.assertIs(manager, returned_manager)
        self.assertIs(resource, returned_resource)
        self.assertTrue(verified.supported)
        self.assertEqual(
            [
                ":OUTP OFF",
                ":OUTP:ON:AUTO OFF",
            ],
            resource.commands,
        )
        self.assertEqual(
            [
                "*IDN?",
                ":OUTP OFF",
                ":OUTP?",
                ":OUTP:ON:AUTO OFF",
                ":OUTP:ON:AUTO?",
                ":OUTP?",
            ],
            resource.transactions,
        )
        self.assertNotIn(":OUTP ON", resource.commands)
        driver.close(safe_stop=False)
        manager.close()

    def test_connection_fails_if_output_off_cannot_be_confirmed(self) -> None:
        resource = FakeResource(output_response="1")
        manager = FakeResourceManager(resource)
        device = supported("USB0::1::INSTR", "SERIAL-1")
        with patch.object(SMUManager, "_open_resource_manager", return_value=(manager, "test")):
            with self.assertRaisesRegex(RuntimeError, "OUTP"):
                SMUManager._connect_worker(device)
        self.assertTrue(resource.closed)
        self.assertTrue(manager.closed)
        self.assertNotIn(":OUTP ON", resource.commands)

    def test_connection_fails_if_auto_output_off_cannot_be_confirmed(self) -> None:
        resource = FakeResource(output_response="0", auto_output_response="1")
        manager = FakeResourceManager(resource)
        device = supported("USB0::1::INSTR", "SERIAL-1")
        with patch.object(SMUManager, "_open_resource_manager", return_value=(manager, "test")):
            with self.assertRaisesRegex(RuntimeError, "auto-output"):
                SMUManager._connect_worker(device)
        self.assertTrue(resource.closed)
        self.assertTrue(manager.closed)
        self.assertNotIn(":OUTP ON", resource.commands)

    def test_bind_failure_closes_and_clears_partial_connection(self) -> None:
        resource = FakeResource()
        resource_manager = FakeResourceManager(resource)
        device = supported("USB0::1::INSTR", "SERIAL-1")
        driver = SMUDriver(resource, device)
        manager = SMUManager()
        try:
            with patch.object(
                manager.control,
                "bind_driver",
                side_effect=RuntimeError("bind failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "bind failed"):
                    manager._adopt_connection(
                        resource_manager,
                        resource,
                        device,
                        driver,
                    )
            self.assertTrue(resource.closed)
            self.assertTrue(resource_manager.closed)
            self.assertIsNone(manager._driver)
            self.assertIsNone(manager._resource_manager)
            self.assertIsNone(manager.connected_device)
            self.assertFalse(manager.is_connected)
        finally:
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
