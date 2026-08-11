from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.relay_controller import RelayController, RelayError, RelayService, RelayState
from gui.relay_settings import RelayGroup, RelaySettingsStore
from gui.relay_settings_dialog import RelaySettingsDialog


class FakeTransport:
    def __init__(self, devices=None) -> None:
        self.devices = devices if devices is not None else [
            {"path": b"relay", "product_string": "USBRelay8", "serial_number": "A1"}
        ]
        self.writes: list[list[int]] = []
        self.bitmask = 0
        self.read_calls = 0
        self.fail_send = False
        self.fail_read = False
        self.ignore_commands = False

    def enumerate(self, _vid, _pid):
        return self.devices

    def open(self, path):
        return path

    def close(self, _handle):
        pass

    def send(self, _handle, report):
        self.writes.append(list(report))
        if self.fail_send:
            raise OSError("simulated HID write failure")
        if not self.ignore_commands:
            channel = report[2]
            if report[1] == RelayController.COMMAND_ON:
                self.bitmask |= 1 << (channel - 1)
            elif report[1] == RelayController.COMMAND_OFF:
                self.bitmask &= ~(1 << (channel - 1))
        return len(report)

    def get_feature_report(self, _handle, report_id, length):
        self.read_calls += 1
        if self.fail_read:
            raise OSError("simulated feature-report failure")
        # The selector is supplied to GET_FEATURE, but response bytes 0..4
        # contain the DCTTech module serial; state is byte 7.
        report = [ord("R"), ord("L"), ord("Y"), ord("0"), ord("1"), 0, 0, self.bitmask, 0]
        return report[:length]


class RelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        existing = QApplication.instance()
        # Some earlier unittest modules create a QCoreApplication. Qt cannot
        # replace it with QApplication in the same process.
        cls.app = existing if isinstance(existing, QApplication) else QApplication([]) if existing is None else None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelaySettingsStore(Path(self.tmp.name) / "relay_settings.json")
        self.transport = FakeTransport()
        self.controller = RelayController(self.transport)
        self.service = RelayService(self.controller, self.store)
        self.assertEqual("Relay 已連線", self.service.refresh_connection())

    def tearDown(self) -> None:
        self.controller.disconnect()
        self.tmp.cleanup()

    def test_dcttech_command_and_hardware_readback(self) -> None:
        self.service.channel_on(3)
        self.assertEqual(
            [0x00, 0xFF, 3, 0, 0, 0, 0, 0, 0], self.transport.writes[-1]
        )
        self.assertIs(self.controller.channel_states[3], RelayState.ON)
        self.service.channel_off(3)
        self.assertEqual(
            [0x00, 0xFD, 3, 0, 0, 0, 0, 0, 0], self.transport.writes[-1]
        )
        self.assertIs(self.controller.channel_states[3], RelayState.OFF)

    def test_on_command_failure_never_displays_on(self) -> None:
        self.transport.fail_send = True
        with self.assertRaises(RelayError):
            self.service.channel_on(1)
        self.assertIs(self.controller.channel_states[1], RelayState.OFF)

    def test_on_command_success_but_readback_off_is_error(self) -> None:
        self.transport.ignore_commands = True
        with self.assertRaises(RelayError):
            self.service.channel_on(1)
        self.assertIs(self.controller.channel_states[1], RelayState.ERROR)
        self.assertEqual("FAILURE", self.service.log_entries[-1].result)

    def test_readback_failure_is_error_and_other_channels_unknown(self) -> None:
        self.transport.fail_read = True
        with self.assertRaises(RelayError):
            self.service.channel_on(1)
        self.assertIs(self.controller.channel_states[1], RelayState.ERROR)
        self.assertIs(self.controller.channel_states[2], RelayState.UNKNOWN)

    def test_group_live_state_on_and_partial(self) -> None:
        self.service.channel_on(1)
        self.service.channel_on(2)
        self.assertIs(self.service.group_state("white_light"), RelayState.ON)
        self.service.channel_off(2)
        self.assertIs(self.service.group_state("white_light"), RelayState.PARTIAL)

    def test_disconnected_state_is_unknown(self) -> None:
        self.controller.disconnect()
        self.assertTrue(all(value is RelayState.UNKNOWN for value in self.controller.channel_states.values()))
        self.assertIs(self.service.group_state("white_light"), RelayState.UNKNOWN)

    def test_dialog_reopen_refreshes_same_controller_state(self) -> None:
        if self.app is None:
            self.skipTest("A QCoreApplication already owns the full-suite process")
        self.transport.bitmask = 0b00000011
        before = self.transport.read_calls
        first = RelaySettingsDialog(self.store, self.service)
        self.assertGreater(self.transport.read_calls, before)
        self.assertEqual("開啟", first.channel_table.item(0, 5).text())
        first.close()

        controller_identity = id(self.service.controller)
        second = RelaySettingsDialog(self.store, self.service)
        self.assertEqual(controller_identity, id(second.service.controller))
        self.assertEqual("開啟", second.channel_table.item(1, 5).text())
        second.close()

    def test_save_does_not_reset_runtime_or_change_hardware(self) -> None:
        if self.app is None:
            self.skipTest("A QCoreApplication already owns the full-suite process")
        self.service.channel_on(1)
        writes_before = list(self.transport.writes)
        handle_before = self.controller.handle
        dialog = RelaySettingsDialog(self.store, self.service)
        dialog.channel_table.cellWidget(0, 2).setText("Saved name")
        dialog._save()

        self.assertEqual(writes_before, self.transport.writes)
        self.assertIs(handle_before, self.controller.handle)
        self.assertIs(self.controller.channel_states[1], RelayState.ON)
        self.assertEqual("Saved name", self.store.settings.channels[0].display_name)

    def test_runtime_state_is_not_persisted(self) -> None:
        self.service.channel_on(1)
        self.store.save()
        payload = self.store.path.read_text(encoding="utf-8")
        self.assertNotIn("channel_states", payload)
        self.assertNotIn("bitmask", payload)
        self.assertNotIn("path", payload)
        self.assertNotIn("synchronized", payload)

    def test_group_commands_are_verified(self) -> None:
        self.service.group_on("white_light")
        self.assertIs(self.service.group_state("white_light"), RelayState.ON)
        self.service.group_off("white_light")
        self.assertIs(self.service.group_state("white_light"), RelayState.OFF)

    def test_settings_round_trip_and_channel_conflict(self) -> None:
        self.store.settings.channels[2].display_name = "Fixture"
        self.store.settings.groups.append(RelayGroup("fixture", "Fixture", [3, 4, 5]))
        self.store.save()
        restored = RelaySettingsStore(self.store.path)
        self.assertEqual("Fixture", restored.settings.channels[2].display_name)
        restored.settings.groups.append(RelayGroup("other", "Other", [1]))
        self.assertTrue(any("CH1" in error for error in restored.settings.validate()))

    def test_ambiguous_identical_devices_are_not_connected(self) -> None:
        transport = FakeTransport([
            {"path": b"a", "product_string": "USBRelay8", "serial_number": None},
            {"path": b"b", "product_string": "USBRelay8", "serial_number": None},
        ])
        controller = RelayController(transport)
        self.assertIn("多個", controller.refresh_connection())
        self.assertFalse(controller.connected)


if __name__ == "__main__":
    unittest.main()
