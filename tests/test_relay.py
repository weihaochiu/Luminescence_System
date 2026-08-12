from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.relay_controller import (
    HidApiTransport, RelayController, RelayDevice, RelayError, RelayRoutingFault,
    RelayService, RelayState, run_hardware_diagnostic,
)
from gui.relay_settings import RelayGroup, RelaySettings, RelaySettingsStore
from gui.relay_settings_dialog import RelaySettingsDialog


class FakeTransport:
    def __init__(self, devices=None) -> None:
        self.devices = devices if devices is not None else [
            {"path": b"relay", "product_string": "USBRelay8", "serial_number": "A1"}
        ]
        self.writes: list[list[int]] = []
        self.bitmask = 0
        self.read_calls = 0
        self.report_ids: list[int] = []
        self.fail_send = False
        self.fail_read = False
        self.ignore_commands = False
        self.raw_length = 8

    def enumerate(self, _vid, _pid):
        return self.devices

    def open(self, path):
        return path

    def close(self, _handle):
        pass

    def send(self, _handle, report):
        self.writes.append(list(report))
        if self.fail_send:
            raise OSError("simulated HID feature-report failure")
        if not self.ignore_commands:
            channel = report[2]
            if report[1] == RelayController.COMMAND_ON:
                self.bitmask |= 1 << (channel - 1)
            elif report[1] == RelayController.COMMAND_OFF:
                self.bitmask &= ~(1 << (channel - 1))
        return len(report)

    def error(self, _handle):
        return "simulated hidapi error"

    def get_feature_report(self, _handle, report_id, length):
        self.read_calls += 1
        self.report_ids.append(report_id)
        if self.fail_read:
            raise OSError("simulated feature-report failure")
        payload = [ord("R"), ord("L"), ord("Y"), ord("0"), ord("1"), 0, 0]
        report = payload + ([0] if self.raw_length == 9 else []) + [self.bitmask]
        return report[:length]


class ProductionHidHandle:
    def __init__(self) -> None:
        self.bitmask = 0
        self.feature_reports: list[list[int]] = []
        self.write_called = False

    def send_feature_report(self, report):
        self.feature_reports.append(list(report))
        channel = report[2]
        if report[1] == RelayController.COMMAND_ON:
            self.bitmask |= 1 << (channel - 1)
        else:
            self.bitmask &= ~(1 << (channel - 1))
        return len(report)

    def get_feature_report(self, _report_id, _length):
        return [ord("R"), ord("L"), ord("Y"), ord("0"), ord("1"), 0, 0, self.bitmask]

    def write(self, _report):
        self.write_called = True
        raise AssertionError("Output Report write() must not be called")

    def error(self):
        return "mock hidapi error"


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
        self.controller = RelayController(self.transport, settle_seconds=0)
        self.service = RelayService(self.controller, self.store)
        self.assertEqual("Relay 已連線", self.service.refresh_connection())

    def tearDown(self) -> None:
        self.controller.disconnect()
        self.tmp.cleanup()

    def test_hardware_verified_ch1_ch2_command_bytes(self) -> None:
        self.service.channel_on(1)
        self.service.channel_off(1)
        self.service.channel_on(2)
        self.assertEqual([
            [0x00, 0xFF, 1, 0, 0, 0, 0, 0, 0],
            [0x00, 0xFD, 1, 0, 0, 0, 0, 0, 0],
            [0x00, 0xFF, 2, 0, 0, 0, 0, 0, 0],
        ], self.transport.writes)

    def test_production_hid_transport_uses_feature_report_not_write(self) -> None:
        handle = ProductionHidHandle()
        transport = HidApiTransport.__new__(HidApiTransport)
        controller = RelayController(transport, settle_seconds=0)
        controller.handle = handle
        controller.connected_device = RelayDevice(b"production", "USBRelay8", "A1")

        controller.set_channel(1, True)

        self.assertEqual(
            [[0x00, 0xFF, 1, 0, 0, 0, 0, 0, 0]], handle.feature_reports
        )
        self.assertFalse(handle.write_called)
        self.assertIs(controller.channel_states[1], RelayState.ON)

    def test_r00_uses_final_byte_for_8_and_9_byte_results(self) -> None:
        self.transport.bitmask = 0b10100101
        for raw_length in (8, 9):
            with self.subTest(raw_length=raw_length):
                self.transport.raw_length = raw_length
                self.assertEqual(0b10100101, self.controller.refresh_hardware_state())
                self.assertEqual(0x00, self.transport.report_ids[-1])

    def test_r00_masks_map_ch1_and_ch2_and_white_light_state(self) -> None:
        expected = {
            0x00: (RelayState.OFF, RelayState.OFF, RelayState.OFF),
            0x01: (RelayState.ON, RelayState.OFF, RelayState.PARTIAL),
            0x02: (RelayState.OFF, RelayState.ON, RelayState.PARTIAL),
            0x03: (RelayState.ON, RelayState.ON, RelayState.ON),
        }
        for mask, states in expected.items():
            with self.subTest(mask=mask):
                self.transport.bitmask = mask
                self.controller.refresh_hardware_state()
                self.assertIs(self.controller.channel_states[1], states[0])
                self.assertIs(self.controller.channel_states[2], states[1])
                self.assertIs(self.service.group_state("white_light"), states[2])

    def test_feature_report_positive_short_return_is_transmission_success(self) -> None:
        original_send = self.transport.send
        self.transport.send = lambda handle, report: (original_send(handle, report) and 1)
        self.service.channel_on(1)
        self.assertIs(self.controller.channel_states[1], RelayState.ON)

    def test_channel_command_waits_for_settle_before_r00_verification(self) -> None:
        sleeps: list[float] = []
        controller = RelayController(self.transport, settle_seconds=0.15, sleep=sleeps.append)
        service = RelayService(controller, self.store)
        self.assertEqual("Relay 已連線", service.refresh_connection())
        service.channel_on(1)
        self.assertEqual([0.15], sleeps)
        self.assertEqual(0x00, self.transport.report_ids[-1])

    def test_feature_report_minus_one_includes_hidapi_error(self) -> None:
        self.transport.send = lambda _handle, _report: -1
        with self.assertRaisesRegex(RelayError, "simulated hidapi error"):
            self.service.channel_on(1)
        self.assertIsNot(self.controller.channel_states[1], RelayState.ON)

    def test_hardware_diagnostic_sequence_and_timing(self) -> None:
        sleeps: list[int] = []
        output: list[str] = []
        run_hardware_diagnostic(self.controller, sleep=sleeps.append, output=output.append)
        self.assertEqual([2, 1, 2], sleeps)
        self.assertEqual(
            [(0xFF, 1), (0xFD, 1), (0xFF, 2), (0xFD, 2)],
            [(report[1], report[2]) for report in self.transport.writes],
        )
        self.assertEqual(4, sum("transport type = FEATURE_REPORT" in line for line in output))
        self.assertEqual(4, sum("verification result: SUCCESS" in line for line in output))

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
        self.assertEqual(0x03, self.controller.last_bitmask & 0x03)
        self.service.group_off("white_light")
        self.assertIs(self.service.group_state("white_light"), RelayState.OFF)
        self.assertEqual(0x00, self.controller.last_bitmask & 0x03)

    def test_default_smu_output_mapping_and_schema_round_trip(self) -> None:
        expected = {"Ch1": 5, "Ch2": 6, "Ch3": 7, "Ch4": 8}
        self.assertEqual(expected, self.store.settings.smu_output_channels)
        self.store.save()
        payload = self.store.path.read_text(encoding="utf-8")
        self.assertIn('"schema_version": 2', payload)
        self.assertEqual(
            expected,
            RelaySettingsStore(self.store.path).settings.smu_output_channels,
        )

    def test_legacy_settings_migrate_to_default_smu_mapping(self) -> None:
        legacy = RelaySettings.defaults().to_dict()
        legacy.pop("smu_output_channels")
        legacy["channels"][4]["enabled"] = False
        migrated = RelaySettings.from_dict(legacy)
        self.assertEqual(
            {"Ch1": 5, "Ch2": 6, "Ch3": 7, "Ch4": 8},
            migrated.smu_output_channels,
        )
        self.assertTrue(migrated.channels[4].enabled)

    def test_select_ch3_is_verified_break_before_make(self) -> None:
        self.service.channel_on(1)
        start = len(self.transport.writes)
        relay = self.service.select_smu_output_channel("Ch3", lambda: True)
        commands = [(report[1], report[2]) for report in self.transport.writes[start:]]
        self.assertEqual(
            [(0xFD, 5), (0xFD, 6), (0xFD, 7), (0xFD, 8), (0xFF, 7)],
            commands,
        )
        self.assertEqual(7, relay)
        self.assertEqual("Ch3", self.service.active_smu_output_channel())
        self.assertEqual(0x01, self.transport.bitmask & 0x03)

    def test_unconfirmed_smu_off_blocks_routing_without_relay_commands(self) -> None:
        before = list(self.transport.writes)
        with self.assertRaisesRegex(RelayError, "not authoritatively confirmed"):
            self.service.select_smu_output_channel("Ch2", lambda: False)
        self.assertEqual(before, self.transport.writes)

    def test_direct_or_group_on_cannot_bypass_smu_routing_api(self) -> None:
        with self.assertRaisesRegex(RelayError, "routing"):
            self.service.channel_on(5)
        group = RelayGroup("unsafe", "Unsafe", [5])
        with self.assertRaisesRegex(RelayError, "routing"):
            self.service.group_on("unsafe", group=group)
        self.assertEqual(0, self.transport.bitmask & 0xF0)

    def test_multiple_active_routes_trigger_fault_handler_and_all_off(self) -> None:
        faults: list[str] = []
        self.service.set_routing_fault_handler(faults.append)
        self.transport.bitmask = (1 << 4) | (1 << 6) | 0x03
        with self.assertRaises(RelayRoutingFault):
            self.service.active_smu_output_channel()
        self.assertEqual(0, self.transport.bitmask & 0xF3)
        self.assertEqual(1, len(faults))
        self.assertIn("Ch1", faults[0])
        self.assertIn("Ch3", faults[0])

    def test_target_on_verification_failure_never_leaves_route_or_light_on(self) -> None:
        self.transport.ignore_commands = True
        with self.assertRaisesRegex(RelayError, "verification failed"):
            self.service.select_smu_output_channel("Ch4", lambda: True)
        self.assertEqual(0, self.transport.bitmask & 0xF3)

    def test_mapping_validation_rejects_duplicate_invalid_and_white_light_relays(self) -> None:
        settings = RelaySettings.defaults()
        settings.smu_output_channels["Ch4"] = 5
        self.assertTrue(any("不可重複" in error for error in settings.validate()))
        settings = RelaySettings.defaults()
        settings.smu_output_channels["Ch1"] = 1
        self.assertTrue(any("white_light" in error for error in settings.validate()))
        settings = RelaySettings.defaults()
        settings.smu_output_channels.pop("Ch4")
        self.assertTrue(any("Ch1～Ch4" in error for error in settings.validate()))

    def test_safe_shutdown_verifies_white_light_off_and_disconnects(self) -> None:
        self.service.group_on("white_light")
        self.service.select_smu_output_channel("Ch4", lambda: True)
        self.assertTrue(self.service.shutdown())
        self.assertEqual(0, self.transport.bitmask & 0xF3)
        self.assertFalse(self.controller.connected)

    def test_safe_shutdown_forces_ch1_ch2_off_even_if_group_is_disabled(self) -> None:
        self.transport.bitmask = 0x03
        self.controller.refresh_hardware_state()
        self.store.settings.group("white_light").enabled = False
        self.assertTrue(self.service.shutdown())
        self.assertEqual(0, self.transport.bitmask & 0x03)

    def test_settings_round_trip_and_channel_conflict(self) -> None:
        self.store.settings.channels[2].display_name = "Fixture"
        self.store.settings.groups.append(RelayGroup("fixture", "Fixture", [3, 4, 5]))
        self.store.save()
        restored = RelaySettingsStore(self.store.path)
        self.assertEqual("Fixture", restored.settings.channels[2].display_name)
        restored.settings.groups.append(RelayGroup("other", "Other", [1]))
        self.assertTrue(any("CH1" in error for error in restored.settings.validate()))

    def test_white_light_group_is_fixed_to_hardware_verified_ch1_ch2(self) -> None:
        self.store.settings.group("white_light").members = [1]
        self.assertTrue(any("CH1" in error and "CH2" in error for error in self.store.settings.validate()))

    def test_ambiguous_identical_devices_are_not_connected(self) -> None:
        transport = FakeTransport([
            {"path": b"a", "product_string": "USBRelay8", "serial_number": None},
            {"path": b"b", "product_string": "USBRelay8", "serial_number": None},
        ])
        controller = RelayController(transport)
        self.assertIn("多個", controller.refresh_connection())
        self.assertFalse(controller.connected)

    def test_missing_usbrelay8_is_not_connected(self) -> None:
        controller = RelayController(FakeTransport([]))
        self.assertIn("未偵測到", controller.refresh_connection())
        self.assertFalse(controller.connected)


if __name__ == "__main__":
    unittest.main()
