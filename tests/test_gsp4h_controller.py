"""GSP-4H protocol/lifecycle tests. Never open an actual hardware serial port."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QThread
from PySide6.QtSerialPort import QSerialPort

from qt_test_utils import ensure_qapplication
from tools.gsp4h_controller.controller import EnableCancelled, LightController, LightState
from tools.gsp4h_controller.discovery import PortInfo, ScanCancelled, scan_ports
from tools.gsp4h_controller.protocol import (
    ControllerError, brightness_command, mode_command, parse_brightness, parse_mode,
)
from tools.gsp4h_controller.serial_transport import QtSerialTransport
from tools.gsp4h_controller.settings import BrightnessStore
from tools.gsp4h_controller.window import LightControlWindow
from tools.gsp4h_controller.worker import ControllerWorker


READ_COMMANDS = {b"T#", b"SA#", b"SB#", b"SC#", b"SD#"}
OFF_COMMANDS = [b"TL#", b"SA0000#", b"SB0000#", b"SC0000#", b"SD0000#"]


@dataclass
class FakeDevice:
    mode: str = "H"
    values: list[int] = field(default_factory=lambda: [31, 32, 33, 34])
    replies: dict[bytes, bytes | Exception] = field(default_factory=dict)
    ignore: set[bytes] = field(default_factory=set)

    def reply(self, command: bytes) -> bytes:
        if command == b"T#":
            raw = self.mode.encode()
        elif command in (b"TH#", b"TL#"):
            if command not in self.ignore:
                self.mode = chr(command[1])
            raw = command[1:2].lower()
        elif command.startswith(b"S"):
            channel = "ABCD".index(chr(command[1]))
            if len(command) == 3:
                raw = f"{'abcd'[channel]}{self.values[channel]:04d}".encode()
            else:
                if command not in self.ignore:
                    self.values[channel] = int(command[2:6])
                raw = command[1:2].lower()
        else:
            raise AssertionError(command)
        raw = self.replies.get(command, raw)
        if isinstance(raw, Exception):
            raise raw
        return raw


class FakeRegistry:
    def __init__(self, devices: dict[str, FakeDevice] | None = None) -> None:
        self.devices = devices if devices is not None else {"COM6": FakeDevice()}
        self.commands: list[tuple[str, bytes]] = []
        self.command_states: list[tuple[bytes, str, tuple[int, ...]]] = []
        self.transports: list[FakeTransport] = []
        self.block_command: bytes | None = None
        self.started = Event()
        self.release = Event()

    def make_transport(self):
        transport = FakeTransport(self)
        self.transports.append(transport)
        return transport

    def ports(self):
        return [PortInfo(name, "USB Serial Adapter", "Example", "VID=0403 PID=6001", name + "-SN") for name in self.devices]


class FakeTransport:
    def __init__(self, registry: FakeRegistry) -> None:
        self.registry = registry
        self.is_open = False
        self.port = ""
        self.parity = ""
        self.close_count = 0
        self.open_threads: list[QThread] = []
        self.fail_close = False

    def open(self, port: str, parity: str) -> None:
        if port not in self.registry.devices:
            raise ControllerError("Unavailable fake port")
        self.port, self.parity = port, parity
        self.is_open = True
        self.open_threads.append(QThread.currentThread())

    def exchange(self, command: bytes, response_length: int) -> bytes:
        if not self.is_open:
            raise ControllerError("Disconnected fake device")
        self.registry.commands.append((self.port, command))
        device = self.registry.devices[self.port]
        self.registry.command_states.append((command, device.mode, tuple(device.values)))
        if command == self.registry.block_command:
            self.registry.started.set()
            if not self.registry.release.wait(3):
                raise ControllerError("Fake test gate timed out")
        return self.registry.devices[self.port].reply(command)

    def close(self) -> None:
        self.close_count += 1
        if self.fail_close:
            raise ControllerError("Fake close failure")
        self.is_open = False


class ProtocolTests(unittest.TestCase):
    def test_exact_ascii_commands(self):
        self.assertEqual(b"SA0100#", brightness_command(1, 100))
        self.assertEqual(b"SD0255#", brightness_command(4, 255))
        self.assertEqual(b"SB#", brightness_command(2))
        self.assertEqual(b"TH#", mode_command("H"))
        self.assertEqual(b"TL#", mode_command("L"))
        self.assertEqual(b"T#", mode_command())

    def test_reject_invalid_channels_and_values(self):
        for channel in (0, 5, True, 1.0, "1"):
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                brightness_command(channel, 0)
        for value in (-1, 256, True, 1.0, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                brightness_command(1, value)

    def test_brightness_case_and_optional_framing(self):
        self.assertEqual(136, parse_brightness(b"b0136", 2))
        self.assertEqual(255, parse_brightness(b"\r\nD0255#\r\n", 4))

    def test_reject_wrong_channel_range_and_garbage(self):
        for raw in (b"b0100", b"a0256", b"a100", b"a0100a", b"a0 00", b"\xff", b"SA0100#"):
            with self.subTest(raw=raw), self.assertRaises(ControllerError):
                parse_brightness(raw, 1)

    def test_mode_case_is_accepted_but_letter_i_is_not_off(self):
        for raw, expected in ((b"H", "H"), (b"h", "H"), (b"L", "L"), (b"l#\r\n", "L")):
            self.assertEqual(expected, parse_mode(raw))
        for raw in (b"I", b"i", b"0", b"LH", b""):
            with self.assertRaises(ControllerError):
                parse_mode(raw)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.device = self.registry.devices["COM6"]
        self.transport = self.registry.make_transport()
        self.logs = []
        self.control = LightController(self.transport, lambda kind, data: self.logs.append((kind, data)))

    def commands(self):
        return [command for _, command in self.registry.commands]

    def test_connect_only_reads_and_preserves_existing_light(self):
        state = self.control.connect()
        self.assertTrue(state.ready)
        self.assertEqual((31, 32, 33, 34), state.brightness)
        self.assertEqual("H", state.mode)
        self.assertEqual([b"T#", b"SA#", b"SB#", b"SC#", b"SD#"], self.commands())
        self.assertEqual([31, 32, 33, 34], self.device.values)

    def test_brightness_write_requires_matching_readback(self):
        self.control.connect()
        self.registry.commands.clear()
        state = self.control.set_brightness(2, 100)
        self.assertEqual([b"SB0100#", b"SB#", b"T#"], self.commands())
        self.assertEqual((31, 100, 33, 34), state.brightness)

    def test_nonzero_brightness_does_not_enable_dark_mode(self):
        self.device.mode = "L"
        self.device.values = [0] * 4
        self.control.connect()
        self.registry.commands.clear()
        state = self.control.set_brightness(1, 100)
        self.assertEqual("L", state.mode)
        self.assertEqual((100, 0, 0, 0), state.brightness)
        self.assertEqual([b"SA0100#", b"SA#", b"T#"], self.commands())

    def test_last_nonzero_channel_set_to_zero_preserves_output_mode(self):
        self.device.values = [10, 0, 0, 0]
        self.control.connect()
        state = self.control.set_brightness(1, 0)
        self.assertEqual("H", state.mode)
        self.assertEqual((0,) * 4, state.brightness)
        self.assertNotIn(b"TL#", self.commands())

    def test_zeroing_one_channel_does_not_disable_another_nonzero_channel(self):
        self.device.values = [10, 20, 0, 0]
        self.control.connect()
        state = self.control.set_brightness(1, 0)
        self.assertEqual("H", state.mode)
        self.assertEqual((0, 20, 0, 0), state.brightness)
        self.assertNotIn(b"TL#", self.commands())

    def test_front_panel_mode_change_is_detected_when_editing_brightness(self):
        self.control.connect()
        self.device.mode = "L"
        self.assertEqual("L", self.control.set_brightness(1, 100).mode)
        self.assertNotIn(b"TH#", self.commands())

    def test_brightness_mode_readback_failure_invalidates_state(self):
        self.device.mode = "L"
        self.device.values = [0] * 4
        self.control.connect()
        self.device.replies[b"T#"] = ControllerError("timeout")
        with self.assertRaises(ControllerError):
            self.control.set_brightness(1, 100)
        self.assertFalse(self.control.state.ready)
        self.assertIsNone(self.control.state.mode)

    def test_normal_off_preserves_all_brightness_values(self):
        self.control.connect()
        self.registry.commands.clear()
        state = self.control.turn_off()
        self.assertEqual("L", state.mode)
        self.assertEqual((31, 32, 33, 34), state.brightness)
        self.assertTrue(state.connected)
        self.assertFalse(any(len(cmd) == 7 for cmd in self.commands()))

    def test_normal_off_can_verify_after_lost_acknowledgement(self):
        self.control.connect()
        self.device.replies[b"TL#"] = ControllerError("lost acknowledgement")
        self.assertEqual("L", self.control.turn_off().mode)
        self.assertEqual([31, 32, 33, 34], self.device.values)

    def test_normal_off_failure_does_not_claim_success_or_clear_brightness(self):
        self.control.connect()
        self.device.ignore.add(b"TL#")
        with self.assertRaises(ControllerError):
            self.control.turn_off()
        self.assertFalse(self.control.state.ready)
        self.assertEqual([31, 32, 33, 34], self.device.values)

    def test_enable_sets_every_channel_while_dark_before_switching_on(self):
        self.control.connect()
        desired = (80, 120, 0, 200)
        self.registry.command_states.clear()
        state = self.control.enable(desired)
        self.assertEqual(desired, state.brightness)
        self.assertEqual("H", state.mode)
        writes = [(cmd, mode) for cmd, mode, _ in self.registry.command_states if len(cmd) == 7]
        self.assertEqual(4, len(writes))
        self.assertTrue(all(mode == "L" for _, mode in writes))
        switch = [(mode, values) for cmd, mode, values in self.registry.command_states if cmd == b"TH#"]
        self.assertEqual([("L", desired)], switch)

    def test_invalid_enable_settings_do_not_touch_device(self):
        self.control.connect()
        self.registry.commands.clear()
        with self.assertRaises(ValueError):
            self.control.enable((80, 120, 0, 256))
        self.assertEqual([], self.registry.commands)

    def test_partial_enable_failure_never_switches_on(self):
        self.control.connect()
        self.device.ignore.add(b"SC0200#")
        self.registry.commands.clear()
        with self.assertRaises(ControllerError):
            self.control.enable((80, 120, 200, 0))
        self.assertNotIn(b"TH#", self.commands())
        self.assertEqual("L", self.device.mode)

    def test_enable_cancellation_keeps_controller_dark(self):
        self.control.connect()
        self.registry.commands.clear()
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise EnableCancelled("cancelled")
        with self.assertRaises(EnableCancelled):
            self.control.enable((80, 120, 0, 0), cancel)
        self.assertNotIn(b"TH#", self.commands())
        self.assertEqual("L", self.control.state.mode)

    def test_failed_enable_mode_readback_returns_to_dark(self):
        self.control.connect()
        self.device.ignore.add(b"TH#")
        with self.assertRaises(ControllerError):
            self.control.enable((80, 120, 0, 0))
        self.assertEqual("L", self.device.mode)
        self.assertEqual("L", self.control.state.mode)

    def test_global_mode_write_is_verified(self):
        self.control.connect()
        self.registry.commands.clear()
        self.assertEqual("L", self.control.set_mode("L").mode)
        self.assertEqual([b"TL#", b"T#"], self.commands())

    def test_invalid_inputs_do_not_write(self):
        self.control.connect()
        before = list(self.commands())
        with self.assertRaises(ValueError):
            self.control.set_brightness(1, 256)
        with self.assertRaises(ValueError):
            self.control.set_mode("X")
        self.assertEqual(before, self.commands())
        self.assertTrue(self.control.state.ready)

    def test_mismatching_brightness_invalidates_all_known_state(self):
        self.control.connect()
        self.device.ignore.add(b"SA0100#")
        with self.assertRaisesRegex(ControllerError, "mismatch"):
            self.control.set_brightness(1, 100)
        self.assertFalse(self.control.state.ready)
        self.assertEqual((None,) * 4, self.control.state.brightness)
        with self.assertRaises(ControllerError):
            self.control.set_mode("H")

    def test_mode_ack_is_not_sufficient_without_readback(self):
        self.device.mode = "L"
        self.control.connect()
        self.device.ignore.add(b"TH#")
        with self.assertRaisesRegex(ControllerError, "mismatch"):
            self.control.set_mode("H")
        self.assertFalse(self.control.state.ready)

    def test_partial_initial_read_keeps_shutdown_responsibility(self):
        self.device.replies[b"SC#"] = b"d0033"
        with self.assertRaises(ControllerError):
            self.control.connect()
        self.assertTrue(self.control.state.connected)
        self.assertTrue(self.control.state.shutdown_required)
        self.assertFalse(self.control.state.ready)

    def test_timeout_invalidates_state_and_refresh_recovers_without_writes(self):
        self.control.connect()
        self.device.replies[b"SA#"] = ControllerError("timeout")
        with self.assertRaises(ControllerError):
            self.control.refresh()
        self.assertFalse(self.control.state.ready)
        self.device.replies.clear()
        self.registry.commands.clear()
        self.assertTrue(self.control.refresh().ready)
        self.assertTrue(set(self.commands()) <= READ_COMMANDS)

    def test_disconnect_writes_every_channel_then_verifies_and_closes(self):
        self.control.connect()
        self.registry.commands.clear()
        state = self.control.disconnect()
        self.assertEqual(OFF_COMMANDS + [b"T#", b"SA#", b"SB#", b"SC#", b"SD#"], self.commands())
        self.assertTrue(state.off_confirmed)
        self.assertFalse(state.connected)
        self.assertFalse(state.shutdown_required)

    def test_missing_off_ack_still_attempts_all_channels_and_uses_readback(self):
        self.control.connect()
        self.device.replies[b"SA0000#"] = ControllerError("ack timeout")
        self.assertTrue(self.control.safe_off().off_confirmed)
        self.assertEqual([0] * 4, self.device.values)
        self.assertTrue(any(kind == "WARN" for kind, _ in self.logs))

    def test_off_failure_keeps_connection_and_attempts_all_reads(self):
        self.control.connect()
        self.device.ignore.add(b"SC0000#")
        self.device.replies[b"T#"] = ControllerError("timeout")
        self.registry.commands.clear()
        with self.assertRaises(ControllerError):
            self.control.disconnect()
        self.assertEqual(OFF_COMMANDS + [b"T#", b"SA#", b"SB#", b"SC#", b"SD#"], self.commands())
        self.assertTrue(self.transport.is_open)
        self.assertTrue(self.control.state.shutdown_required)
        self.assertFalse(self.control.state.off_confirmed)
        self.assertEqual(0, self.transport.close_count)

    def test_shutdown_can_recover_after_failed_readback(self):
        self.control.connect()
        self.device.ignore.add(b"SC0000#")
        with self.assertRaises(ControllerError):
            self.control.disconnect()
        self.device.ignore.clear()
        self.assertTrue(self.control.disconnect().off_confirmed)

    def test_usb_loss_requires_shutdown_and_retries_original_port_only(self):
        self.control.connect()
        self.transport.close()
        self.control.connection_fault()
        self.assertFalse(self.control.state.ready)
        self.assertTrue(self.control.state.shutdown_required)
        self.assertTrue(self.control.disconnect().off_confirmed)
        self.assertEqual("COM6", self.transport.port)

    def test_new_connect_cannot_replace_unresolved_session(self):
        self.control.connect()
        self.transport.close()
        with self.assertRaises(ControllerError):
            self.control.connect("COM7")

    def test_close_failure_retains_session(self):
        self.control.connect()
        self.transport.fail_close = True
        with self.assertRaises(ControllerError):
            self.control.disconnect()
        self.assertTrue(self.control.state.shutdown_required)


class DiscoveryTests(unittest.TestCase):
    def scan(self, registry, cancel=None):
        return scan_ports(registry.ports(), registry.make_transport, cancel or Event(), lambda *_: None)

    def test_prefers_com6_and_never_changes_any_device(self):
        registry = FakeRegistry({"COM7": FakeDevice(), "COM6": FakeDevice()})
        result = self.scan(registry)
        self.assertEqual("COM6", result.selected)
        self.assertEqual(("COM6", "COM7"), result.compatible)
        self.assertEqual("COM6", registry.commands[0][0])
        self.assertTrue(all(command in READ_COMMANDS for _, command in registry.commands))
        self.assertTrue(all(not transport.is_open for transport in registry.transports))
        self.assertTrue(all(device.mode == "H" and device.values == [31, 32, 33, 34] for device in registry.devices.values()))

    def test_single_usb_adapter_on_different_port_is_selected(self):
        registry = FakeRegistry({"COM19": FakeDevice()})
        self.assertEqual("COM19", self.scan(registry).selected)

    def test_multiple_nonpreferred_candidates_require_manual_selection(self):
        registry = FakeRegistry({"COM19": FakeDevice(), "COM7": FakeDevice()})
        result = self.scan(registry)
        self.assertIsNone(result.selected)
        self.assertEqual(("COM7", "COM19"), result.compatible)

    def test_rejects_incompatible_and_partial_four_channel_protocol(self):
        invalid = FakeDevice(replies={b"T#": b"OK"})
        partial = FakeDevice(replies={b"SD#": b"a0034"})
        registry = FakeRegistry({"COM6": invalid, "COM7": partial, "COM8": FakeDevice()})
        result = self.scan(registry)
        self.assertEqual(("COM8",), result.compatible)
        self.assertEqual("COM8", result.selected)
        self.assertEqual([b"T#"], [cmd for port, cmd in registry.commands if port == "COM6"])

    def test_empty_inventory_is_not_assumed_to_contain_com6(self):
        registry = FakeRegistry({})
        self.assertEqual((), self.scan(registry).compatible)
        self.assertEqual([], registry.commands)

    def test_cancellation_before_scan_opens_nothing(self):
        registry = FakeRegistry()
        cancel = Event()
        cancel.set()
        with self.assertRaises(ScanCancelled):
            self.scan(registry, cancel)
        self.assertEqual([], registry.transports)

    def test_cancel_during_probe_closes_handle_and_sends_no_off(self):
        registry = FakeRegistry()
        cancel = Event()
        def log(kind, _):
            if kind == "RX":
                cancel.set()
        with self.assertRaises(ScanCancelled):
            scan_ports(registry.ports(), registry.make_transport, cancel, log)
        self.assertEqual([("COM6", b"T#")], registry.commands)
        self.assertFalse(registry.transports[0].is_open)

    def test_port_display_contains_usb_metadata(self):
        port = PortInfo("COM19", "USB RS232", "FTDI", "VID=0403 PID=6001", "1234")
        self.assertIn("COM19", port.display)
        self.assertIn("SN=1234", port.display)
        self.assertIn("VID=0403", port.display)


class FakeQtSerial:
    def __init__(self, chunks=None):
        self.chunks = list(chunks or [])
        self.pending = b""
        self.opened = True
        self.written = []
        self.settings = {}
        self.current_error = QSerialPort.SerialPortError.NoError

    def isOpen(self): return self.opened
    def open(self, _): self.opened = True; return True
    def close(self): self.opened = False
    def setPortName(self, value): self.settings["port"] = value
    def setBaudRate(self, value): self.settings["baud"] = value; return True
    def setDataBits(self, value): self.settings["data"] = value; return True
    def setStopBits(self, value): self.settings["stop"] = value; return True
    def setParity(self, value): self.settings["parity"] = value; return True
    def setFlowControl(self, value): self.settings["flow"] = value; return True
    def clear(self, _): self.pending = b""; return True
    def clearError(self): self.current_error = QSerialPort.SerialPortError.NoError
    def error(self): return self.current_error
    def errorString(self): return "fake serial error"
    def write(self, data): self.written.append(data); return len(data)
    def bytesToWrite(self): return 0
    def readAll(self): data = self.pending; self.pending = b""; return data
    def waitForReadyRead(self, _):
        if self.chunks:
            self.pending = self.chunks.pop(0)
            return True
        return False


class SerialTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def transport(self, chunks=None):
        transport = QtSerialTransport()
        transport.serial = FakeQtSerial(chunks)
        return transport

    def test_fragmented_reply_without_line_terminator(self):
        transport = self.transport([b"b0", b"1", b"36"])
        raw = transport.exchange(b"SB#", 5)
        self.assertEqual(136, parse_brightness(raw, 2))
        self.assertEqual([b"SB#"], transport.serial.written)

    def test_optional_framing_in_separate_chunk(self):
        transport = self.transport([b"a0100", b"#\r\n"])
        self.assertEqual(100, parse_brightness(transport.exchange(b"SA#", 5), 1))

    def test_partial_timeout_reports_raw_bytes_and_requires_resync(self):
        transport = self.transport([b"a01"])
        with self.assertRaisesRegex(ControllerError, "partial RX=b'a01'"):
            transport.exchange(b"SA#", 5)
        self.assertTrue(transport._resync_needed)

    def test_coalesced_garbage_is_not_accepted_as_valid_readback(self):
        transport = self.transport([b"a0100bad"])
        with self.assertRaises(ControllerError):
            parse_brightness(transport.exchange(b"SA#", 5), 1)

    def test_oversized_reply_is_bounded(self):
        transport = self.transport([b"a" * 100])
        with self.assertRaisesRegex(ControllerError, "Oversized"):
            transport.exchange(b"SA#", 5)

    def test_serial_settings_and_usb_identity_check(self):
        transport = self.transport()
        transport.serial.opened = False
        info = Mock()
        info.portName.return_value = "COM19"
        info.serialNumber.return_value = "adapter-A"
        with patch("tools.gsp4h_controller.serial_transport.QSerialPortInfo.availablePorts", return_value=[info]):
            transport.open("COM19")
            self.assertEqual(19200, transport.serial.settings["baud"])
            self.assertEqual(QSerialPort.FlowControl.NoFlowControl, transport.serial.settings["flow"])
            self.assertEqual(QSerialPort.Parity.NoParity, transport.serial.settings["parity"])
            transport.close()
            info.serialNumber.return_value = "adapter-B"
            with self.assertRaisesRegex(ControllerError, "serial number changed"):
                transport.open("COM19")
            self.assertEqual([], transport.serial.written)
            transport.reset_identity()
            transport.open("COM19", "even")
            self.assertEqual(QSerialPort.Parity.EvenParity, transport.serial.settings["parity"])


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()
        cls.quit_on_last_window = cls.app.quitOnLastWindowClosed()
        # These windows are test fixtures in a shared QApplication, rather than
        # the application's actual last window. Do not post process-wide Quit
        # events that can interfere with later suites' timer/event-loop tests.
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.quit_on_last_window)

    def setUp(self):
        self.registry = FakeRegistry()
        self.window = None
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = BrightnessStore(Path(self.temporary_directory.name) / "brightness.json")

    def create_window(self, auto_start=True):
        worker = ControllerWorker(Event(), self.registry.make_transport, self.registry.ports)
        self.window = LightControlWindow(auto_start=auto_start, worker=worker, settings_store=self.store)
        self.window.show()
        return self.window

    def wait(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.app.processEvents()
        self.assertTrue(predicate(), "Qt operation did not complete in time")

    def tearDown(self):
        self.registry.block_command = None
        self.registry.release.set()
        for device in self.registry.devices.values():
            device.replies.clear()
            device.ignore.clear()
        if self.window is not None and not self.window._thread_stopped:
            self.wait(lambda: not self.window._busy)
            self.window.close()
            self.wait(lambda: self.window._thread_stopped)
            self.assertFalse(self.window.worker_thread.isRunning())

    def test_startup_autoscans_connects_and_only_reads_in_worker_thread(self):
        self.registry.devices["COM6"].mode = "L"
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.assertEqual("COM6", window.state.port)
        self.assertTrue(all(command in READ_COMMANDS for _, command in self.registry.commands))
        self.assertEqual("31", window.readbacks[0].text())
        self.assertEqual(31, window.values[0].value())
        self.assertEqual("L", window.state.mode)
        self.assertEqual("connected", window.connection_lamp.property("connectionState"))
        self.assertTrue(all(thread is window.worker_thread for transport in self.registry.transports for thread in transport.open_threads))

    def test_no_match_stays_disconnected_and_can_exit(self):
        self.registry.devices["COM6"].replies[b"T#"] = b"OK"
        window = self.create_window()
        self.wait(lambda: not window._busy and bool(self.registry.commands))
        self.assertFalse(window.state.shutdown_required)
        self.assertFalse(window.power_button.isEnabled())
        self.assertEqual("disconnected", window.connection_lamp.property("connectionState"))
        window.close()
        self.wait(lambda: window._thread_stopped)
        self.assertTrue(all(command in READ_COMMANDS for _, command in self.registry.commands))

    def test_slider_change_sends_without_apply_but_keeps_dark_mode(self):
        self.registry.devices["COM6"].mode = "L"
        self.registry.devices["COM6"].values = [0] * 4
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        window.sliders[1].setValue(100)
        self.wait(lambda: window.state.brightness[1] == 100 and not window._busy)
        self.assertEqual(("COM6", b"SB0100#"), self.registry.commands[0])
        self.assertEqual("100", window.readbacks[1].text())
        self.assertEqual("L", window.state.mode)
        self.assertFalse(hasattr(window, "apply_buttons"))

    def test_numeric_change_also_sends_directly(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        window.values[2].setValue(120)
        self.wait(lambda: window.state.brightness[2] == 120 and not window._busy)
        self.assertEqual(120, window.sliders[2].value())

    def test_drag_coalesces_latest_value_while_serial_is_busy(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        self.registry.block_command = b"SA0100#"
        window.sliders[0].setValue(100)
        self.wait(lambda: self.registry.started.is_set())
        self.assertTrue(window.sliders[0].isEnabled())
        for value in (101, 150, 200):
            window.sliders[0].setValue(value)
        self.registry.release.set()
        self.wait(lambda: window.state.brightness[0] == 200 and not window._busy)
        writes = [cmd for _, cmd in self.registry.commands if len(cmd) == 7]
        self.assertEqual([b"SA0100#", b"SA0200#"], writes)

    def test_pending_changes_to_multiple_channels_are_not_lost(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        window.sliders[0].setValue(100)
        window.sliders[3].setValue(200)
        self.wait(lambda: window.state.brightness == (100, 32, 33, 200) and not window._busy)

    def test_close_before_live_timer_sends_discards_pending_brightness(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        window.sliders[0].setValue(100)
        window.close()
        self.wait(lambda: window._thread_stopped)
        self.assertNotIn(("COM6", b"SA0100#"), self.registry.commands)
        self.assertTrue(window.state.off_confirmed)

    def test_normal_off_keeps_desired_settings_and_discards_unsent_device_writes(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        window.sliders[0].setValue(100)
        window.power_button.click()
        self.wait(lambda: window.state.mode == "L" and not window._busy)
        self.assertNotIn(("COM6", b"SA0100#"), self.registry.commands)
        self.assertEqual([100, 32, 33, 34], [spin.value() for spin in window.values])
        self.assertEqual((100, 32, 33, 34), self.store.load())
        self.assertEqual((31, 32, 33, 34), window.state.brightness)
        self.assertEqual({}, window._pending_brightness)

    def test_connection_lamp_is_checking_until_all_readback_is_verified(self):
        self.registry.block_command = b"T#"
        window = self.create_window()
        self.wait(lambda: self.registry.started.is_set())
        self.assertEqual("checking", window.connection_lamp.property("connectionState"))
        self.registry.release.set()
        self.wait(lambda: window.state.ready and not window._busy)
        self.assertEqual("connected", window.connection_lamp.property("connectionState"))

    def test_failed_readback_turns_lamp_red_and_clears_pending_updates(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.block_command = b"SA0100#"
        self.registry.devices["COM6"].ignore.add(b"SA0100#")
        self.registry.commands.clear()
        window.sliders[0].setValue(100)
        self.wait(lambda: self.registry.started.is_set())
        window.sliders[0].setValue(150)
        self.registry.release.set()
        self.wait(lambda: not window._busy)
        self.assertEqual("error", window.connection_lamp.property("connectionState"))
        self.assertEqual({}, window._pending_brightness)
        self.assertNotIn(("COM6", b"SA0150#"), self.registry.commands)

    def test_readback_refresh_does_not_automatically_enable_nonzero_light(self):
        self.registry.devices["COM6"].mode = "L"
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        window.refresh_button.click()
        self.wait(lambda: not window._busy)
        self.assertTrue(all(cmd in READ_COMMANDS for _, cmd in self.registry.commands))
        self.assertEqual("L", window.state.mode)
        self.assertEqual({}, window._pending_brightness)

    def test_close_shuts_down_all_channels_before_thread_exit(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        window.close()
        self.wait(lambda: window._thread_stopped)
        self.assertEqual(OFF_COMMANDS + [b"T#", b"SA#", b"SB#", b"SC#", b"SD#"], [cmd for _, cmd in self.registry.commands])
        self.assertEqual("L", self.registry.devices["COM6"].mode)
        self.assertEqual([0] * 4, self.registry.devices["COM6"].values)

    def test_close_failure_retains_window_and_retry_control(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.devices["COM6"].ignore.add(b"SA0000#")
        window.close()
        self.wait(lambda: not window._busy and not window._closing)
        self.assertTrue(window.isVisible())
        self.assertFalse(window._thread_stopped)
        self.assertTrue(window.power_button.isEnabled())
        self.assertEqual("重試關燈", window.power_button.text())
        self.assertIn("取消關閉", window.status.text())

    def test_close_during_scan_cancels_probe_without_writing_or_autoconnecting(self):
        self.registry.block_command = b"T#"
        window = self.create_window()
        self.wait(lambda: self.registry.started.is_set())
        window.close()
        self.registry.release.set()
        self.wait(lambda: window._thread_stopped)
        self.assertEqual([("COM6", b"T#")], self.registry.commands)
        self.assertEqual([31, 32, 33, 34], self.registry.devices["COM6"].values)

    def test_normal_off_takes_priority_after_current_bounded_command(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.block_command = b"SA0100#"
        window.values[0].setValue(100)
        self.wait(lambda: self.registry.started.is_set())
        window.values[0].setValue(150)
        window.power_button.click()
        self.assertTrue(window._off_pending)
        self.assertFalse(window.power_button.isEnabled())
        self.registry.release.set()
        self.wait(lambda: window.state.mode == "L" and not window._busy)
        self.assertEqual([100, 32, 33, 34], self.registry.devices["COM6"].values)
        self.assertEqual((150, 32, 33, 34), self.store.load())
        self.assertNotIn(("COM6", b"SA0150#"), self.registry.commands)

    def test_usb_fault_disables_general_controls_and_retains_off_retry(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        control = window.worker.controller
        control.transport.close()
        window.worker.connection_fault.emit(control.connection_fault())
        self.app.processEvents()
        self.assertFalse(window.sliders[0].isEnabled())
        self.assertFalse(window.scan_button.isEnabled())
        self.assertTrue(window.power_button.isEnabled())
        self.assertEqual("未知", window.readbacks[0].text())
        self.assertEqual("error", window.connection_lamp.property("connectionState"))
        window.power_button.click()
        self.wait(lambda: not window._busy)
        self.assertEqual("L", window.state.mode)
        self.assertEqual("connected", window.connection_lamp.property("connectionState"))

    def test_power_toggle_restores_settings_after_normal_off(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        window.power_button.click()
        self.wait(lambda: window.state.mode == "L" and not window._busy)
        self.assertEqual((31, 32, 33, 34), window.desired_brightness)
        window.power_button.click()
        self.wait(lambda: window.state.mode == "H" and not window._busy)
        self.assertEqual((31, 32, 33, 34), window.state.brightness)
        self.assertEqual("關閉光源", window.power_button.text())
        self.assertFalse(hasattr(window, "on_button"))
        self.assertFalse(hasattr(window, "off_mode_button"))
        self.assertFalse(hasattr(window, "all_off_button"))

    def test_saved_settings_are_not_overwritten_by_zero_device_readback_on_restart(self):
        self.store.save((80, 120, 0, 0))
        self.registry.devices["COM6"].mode = "L"
        self.registry.devices["COM6"].values = [0] * 4
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.assertEqual([80, 120, 0, 0], [spin.value() for spin in window.values])
        self.assertEqual(["0"] * 4, [label.text() for label in window.readbacks])
        self.assertTrue(all(cmd in READ_COMMANDS for _, cmd in self.registry.commands))
        window.power_button.click()
        self.wait(lambda: window.state.mode == "H" and not window._busy)
        self.assertEqual((80, 120, 0, 0), window.state.brightness)

    def test_shutdown_zeroes_hardware_but_preserves_saved_settings(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        window.sliders[0].setValue(80)
        self.wait(lambda: window.state.brightness[0] == 80 and not window._busy)
        window.close()
        self.wait(lambda: window._thread_stopped)
        self.assertEqual([0] * 4, self.registry.devices["COM6"].values)
        self.assertEqual((80, 32, 33, 34), self.store.load())
        next_window = self.create_window()
        self.wait(lambda: next_window.state.ready and not next_window._busy)
        self.assertEqual((80, 32, 33, 34), next_window.desired_brightness)
        self.assertEqual((0,) * 4, next_window.state.brightness)
        self.assertEqual("L", next_window.state.mode)

    def test_refresh_does_not_replace_saved_settings_with_device_changes(self):
        self.store.save((80, 120, 0, 0))
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.devices["COM6"].values = [0] * 4
        window.refresh_button.click()
        self.wait(lambda: not window._busy)
        self.assertEqual((80, 120, 0, 0), window.desired_brightness)
        self.assertEqual([80, 120, 0, 0], [spin.value() for spin in window.values])
        self.assertEqual((80, 120, 0, 0), self.store.load())

    def test_power_on_captures_latest_slider_value_before_live_timer(self):
        self.registry.devices["COM6"].mode = "L"
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        window.sliders[0].setValue(80)
        window.power_button.click()
        self.wait(lambda: window.state.mode == "H" and not window._busy)
        self.assertEqual(80, window.state.brightness[0])
        self.assertEqual({}, window._pending_brightness)

    def test_cancel_power_on_prevents_th_and_keeps_settings(self):
        self.store.save((80, 120, 0, 0))
        self.registry.devices["COM6"].mode = "L"
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        self.registry.block_command = b"SA0080#"
        window.power_button.click()
        self.wait(lambda: self.registry.started.is_set())
        self.assertEqual("取消開啟並關燈", window.power_button.text())
        window.power_button.click()
        self.registry.release.set()
        self.wait(lambda: window.state.mode == "L" and not window._busy)
        self.assertNotIn(("COM6", b"TH#"), self.registry.commands)
        self.assertEqual((80, 120, 0, 0), self.store.load())

    def test_close_during_power_on_never_enables_then_zeroes_hardware(self):
        self.store.save((80, 120, 0, 0))
        self.registry.devices["COM6"].mode = "L"
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        self.registry.commands.clear()
        self.registry.block_command = b"SA0080#"
        window.power_button.click()
        self.wait(lambda: self.registry.started.is_set())
        window.close()
        self.registry.release.set()
        self.wait(lambda: window._thread_stopped)
        self.assertNotIn(("COM6", b"TH#"), self.registry.commands)
        self.assertEqual([0] * 4, self.registry.devices["COM6"].values)
        self.assertEqual((80, 120, 0, 0), self.store.load())

    def test_settings_failure_does_not_prevent_safe_shutdown(self):
        window = self.create_window()
        self.wait(lambda: window.state.ready and not window._busy)
        window.sliders[0].setValue(80)
        with patch.object(self.store, "save", side_effect=OSError("disk full")):
            window.close()
            self.wait(lambda: not window._busy and not window._closing)
            self.assertFalse(window._thread_stopped)
            self.assertTrue(window.isVisible())
            self.assertEqual([0] * 4, self.registry.devices["COM6"].values)
            self.assertEqual("L", self.registry.devices["COM6"].mode)
            self.assertIn("尚未儲存", window.status.text())
        window.close()
        self.wait(lambda: window._thread_stopped)
        self.assertEqual((80, 32, 33, 34), self.store.load())


class BrightnessStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = BrightnessStore(Path(self.temporary_directory.name) / "brightness.json")

    def test_missing_file_returns_no_initial_settings(self):
        self.assertIsNone(self.store.load())

    def test_brightness_survives_recreating_store(self):
        self.store.save((80, 120, 0, 255))
        self.assertEqual((80, 120, 0, 255), BrightnessStore(self.store.path).load())

    def test_invalid_preferences_are_not_used_or_rewritten_by_load(self):
        for values in ([1, 2, 3], [1, 2, 3, 256], [True, 2, 3, 4], ["1", 2, 3, 4]):
            raw = json.dumps({"schema_version": 1, "brightness": values})
            self.store.path.write_text(raw, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.store.load()
            self.assertEqual(raw, self.store.path.read_text(encoding="utf-8"))

    def test_malformed_or_unknown_schema_is_not_accepted(self):
        for raw in ('{', '{"schema_version": 2, "brightness": [1,2,3,4]}'):
            self.store.path.write_text(raw, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.store.load()

    def test_failed_atomic_replace_preserves_previous_settings(self):
        self.store.save((80, 120, 0, 0))
        with patch("tools.gsp4h_controller.settings.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.store.save((10, 20, 30, 40))
        self.assertEqual((80, 120, 0, 0), self.store.load())
        self.assertEqual(["brightness.json"], [path.name for path in self.store.path.parent.iterdir()])


if __name__ == "__main__":
    unittest.main()
