from __future__ import annotations

import unittest

from gui.smu_base import SMUDevice, SMUDriver


class FakeResource:
    def __init__(self, failing_command: str = "", output_response: str = "0") -> None:
        self.failing_command = failing_command
        self.output_response = output_response
        self.commands: list[str] = []
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)
        if command == self.failing_command:
            raise RuntimeError("VISA failure")

    def close(self) -> None:
        self.closed = True

    def query(self, command: str) -> str:
        self.asserted_query = command
        return self.output_response


class SMUSafetyTests(unittest.TestCase):
    def test_safe_stop_attempts_every_command_after_a_failure(self) -> None:
        resource = FakeResource(":SOUR:VOLT 0")
        driver = SMUDriver(resource, SMUDevice("USB0::test"))
        failures = driver.safe_stop()
        self.assertEqual([":OUTP OFF", ":SOUR:VOLT 0", ":SOUR:CURR 0"], resource.commands)
        self.assertEqual(1, len(failures))

    def test_close_safely_disables_output_before_closing_resource(self) -> None:
        resource = FakeResource()
        driver = SMUDriver(resource, SMUDevice("USB0::test"))
        driver.close()
        self.assertEqual([":OUTP OFF", ":SOUR:VOLT 0", ":SOUR:CURR 0"], resource.commands)
        self.assertTrue(resource.closed)

    def test_safe_stop_rejects_output_on_confirmation(self) -> None:
        resource = FakeResource(output_response="1")
        driver = SMUDriver(resource, SMUDevice("USB0::test"))
        failures = driver.safe_stop()
        self.assertTrue(any("did not confirm OFF" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
