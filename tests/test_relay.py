from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gui.relay_controller import RelayController, RelayError, RelayService
from gui.relay_settings import RelayGroup, RelaySettingsStore


class FakeTransport:
    def __init__(self, devices=None, fail_on=None) -> None:
        self.devices = devices if devices is not None else [{"path": b"relay", "product_string": "USBRelay8", "serial_number": "A1"}]
        self.fail_on = set(fail_on or [])
        self.writes: list[list[int]] = []

    def enumerate(self, _vid, _pid): return self.devices
    def open(self, path): return path
    def close(self, _handle): pass
    def send(self, _handle, report):
        self.writes.append(report)
        if tuple(report[1:]) in self.fail_on:
            raise OSError("simulated HID failure")


class RelayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelaySettingsStore(Path(self.tmp.name) / "relay_settings.json")
        self.transport = FakeTransport()
        self.controller = RelayController(self.transport)
        self.service = RelayService(self.controller, self.store)
        self.assertEqual("Relay 已連線", self.service.refresh_connection())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_channel_individual_on_off(self) -> None:
        self.service.channel_on(3)
        self.service.channel_off(3)
        self.assertEqual([[0, 3, 1], [0, 3, 0]], self.transport.writes)

    def test_group_on_and_off(self) -> None:
        self.service.group_on("white_light")
        self.service.group_off("white_light")
        self.assertEqual([[0, 1, 1], [0, 2, 1], [0, 1, 0], [0, 2, 0]], self.transport.writes)

    def test_multi_channel_group(self) -> None:
        self.store.settings.groups.append(RelayGroup("fixture", "Fixture", [3, 4, 5]))
        self.service.group_on("fixture")
        self.assertEqual([[0, 3, 1], [0, 4, 1], [0, 5, 1]], self.transport.writes)

    def test_group_on_rolls_back_all_members(self) -> None:
        self.transport.fail_on.add((2, 1))
        with self.assertRaises(RelayError):
            self.service.group_on("white_light")
        self.assertEqual([0, 1, 0], self.transport.writes[-2])
        self.assertEqual([0, 2, 0], self.transport.writes[-1])
        self.assertEqual("ROLLBACK", self.service.log_entries[-1].result)

    def test_group_off_continues_after_failure(self) -> None:
        self.transport.fail_on.add((1, 0))
        with self.assertRaises(RelayError):
            self.service.group_off("white_light")
        self.assertIn([0, 2, 0], self.transport.writes)

    def test_settings_round_trip_and_channel_conflict(self) -> None:
        self.store.settings.channels[2].display_name = "Fixture"
        self.store.settings.channels[2].description = "Test device"
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
        self.assertIn("無法安全判定", controller.refresh_connection())
        self.assertFalse(controller.connected)

    def test_hid_path_is_runtime_only_and_can_change(self) -> None:
        self.store.save()
        payload = self.store.path.read_text(encoding="utf-8")
        self.assertNotIn("path", payload)
        first = RelayController(FakeTransport([{ "path": b"old", "product_string": "USBRelay8", "serial_number": "A1"}]))
        second = RelayController(FakeTransport([{ "path": b"new", "product_string": "USBRelay8", "serial_number": "A1"}]))
        self.assertTrue(first.refresh_connection().endswith("已連線"))
        self.assertTrue(second.refresh_connection().endswith("已連線"))


if __name__ == "__main__":
    unittest.main()
