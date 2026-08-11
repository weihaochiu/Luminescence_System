from __future__ import annotations

"""DCTTech USBRelay8 discovery, runtime state, and verified operations.

The HID path and relay states are runtime-only and are never persisted.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import time
from typing import Any, Protocol, TYPE_CHECKING

from .relay_settings import RelayGroup, RelaySettingsStore

if TYPE_CHECKING:
    from .relay_settings import RelaySettings

LOG = logging.getLogger(__name__)


class RelayError(RuntimeError):
    pass


class RelayState(str, Enum):
    UNKNOWN = "UNKNOWN"
    OFF = "OFF"
    ON = "ON"
    ERROR = "ERROR"
    PARTIAL = "PARTIAL"


class RelayTransport(Protocol):
    def enumerate(self, vid: int, pid: int) -> list[dict[str, Any]]: ...
    def open(self, path: bytes | str) -> Any: ...
    def send(self, handle: Any, report: list[int]) -> int: ...
    def get_feature_report(self, handle: Any, report_id: int, length: int) -> list[int]: ...
    def error(self, handle: Any) -> str: ...
    def close(self, handle: Any) -> None: ...


class HidApiTransport:
    """Small adapter around the optional Python ``hidapi`` package."""

    def __init__(self) -> None:
        try:
            import hid  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RelayError("未安裝 HID 支援套件，無法使用 USBRelay8") from exc
        self.hid = hid

    def enumerate(self, vid: int, pid: int) -> list[dict[str, Any]]:
        return list(self.hid.enumerate(vid, pid))

    def open(self, path: bytes | str) -> Any:
        device = self.hid.device()
        device.open_path(path)
        return device

    def send(self, handle: Any, report: list[int]) -> int:
        return int(handle.send_feature_report(report))

    def get_feature_report(self, handle: Any, report_id: int, length: int) -> list[int]:
        return list(handle.get_feature_report(report_id, length))

    def error(self, handle: Any) -> str:
        error_method = getattr(handle, "error", None)
        if callable(error_method):
            try:
                return str(error_method() or "unknown hidapi error")
            except Exception as exc:
                return f"unable to read hidapi error: {exc}"
        return "hidapi error information unavailable"

    def close(self, handle: Any) -> None:
        handle.close()


@dataclass(frozen=True)
class RelayDevice:
    path: bytes | str
    product: str
    serial_number: str | None


@dataclass(frozen=True)
class RelayLogEntry:
    timestamp: str
    operation_type: str
    target: str
    previous_state: str
    requested_state: str
    result: str
    source: str


def _hex_report(report: list[int]) -> str:
    return " ".join(f"{value:02X}" for value in report)


class RelayController:
    """Owns the connection and the single authoritative runtime state."""

    REPORT_LENGTH = 9
    STATUS_REPORT_ID = 0x00
    COMMAND_ON = 0xFF
    COMMAND_OFF = 0xFD

    def __init__(
        self,
        transport: RelayTransport | None = None,
        vid: int = 0x16C0,
        pid: int = 0x05DF,
        product: str = "USBRelay8",
    ) -> None:
        self.transport = transport
        self.vid, self.pid, self.product = vid, pid, product
        self.handle: Any | None = None
        self.connected_device: RelayDevice | None = None
        self.channel_states = self._unknown_states()
        self.last_raw_status: list[int] | None = None
        self.last_bitmask: int | None = None
        self.last_command_report: list[int] | None = None
        self.last_send_result: int | None = None
        self.last_verification = "NOT_RUN"

    @staticmethod
    def _unknown_states() -> dict[int, RelayState]:
        return {index: RelayState.UNKNOWN for index in range(1, 9)}

    @property
    def connected(self) -> bool:
        return self.handle is not None

    def discover(self) -> list[RelayDevice]:
        if self.transport is None:
            try:
                self.transport = HidApiTransport()
            except RelayError:
                return []
        matches = []
        for item in self.transport.enumerate(self.vid, self.pid):
            product = str(item.get("product_string") or "")
            if product and product != self.product:
                continue
            matches.append(RelayDevice(item["path"], product or self.product, item.get("serial_number") or None))
        return matches

    def refresh_connection(self) -> str:
        self.disconnect()
        devices = self.discover()
        if not devices:
            return "未偵測到 USBRelay8"
        if len(devices) > 1 and not all(item.serial_number for item in devices):
            return "偵測到多個無法安全辨識的 Relay 裝置"
        if len(devices) != 1:
            return "偵測到多個 Relay 裝置，請只連接一台"
        assert self.transport is not None
        try:
            self.handle = self.transport.open(devices[0].path)
            self.connected_device = devices[0]
        except Exception as exc:
            self.handle = None
            self.connected_device = None
            LOG.exception("Relay HID open failed")
            return f"Relay 連線失敗：{exc}"
        try:
            self.refresh_hardware_state()
        except RelayError as exc:
            return f"Relay 已連線，但狀態讀取失敗：{exc}"
        return "Relay 已連線"

    def disconnect(self) -> None:
        if self.handle is not None and self.transport is not None:
            try:
                self.transport.close(self.handle)
            except Exception:
                LOG.exception("Failed to close relay HID device")
        self.handle = None
        self.connected_device = None
        self.channel_states = self._unknown_states()
        self.last_raw_status = None
        self.last_bitmask = None
        self.last_command_report = None
        self.last_send_result = None
        self.last_verification = "NOT_RUN"

    def _runtime_identity(self) -> str:
        path = self.connected_device.path if self.connected_device else None
        return f"path={path!r} VID={self.vid:04X} PID={self.pid:04X} Product={self.product}"

    def refresh_hardware_state(self) -> int:
        """Read and publish the DCTTech feature-report relay bitmask."""
        if self.handle is None or self.transport is None:
            self.channel_states = self._unknown_states()
            raise RelayError("Relay 未連線")
        try:
            raw = self.transport.get_feature_report(
                self.handle, self.STATUS_REPORT_ID, self.REPORT_LENGTH
            )
            LOG.debug(
                "Raw feature report (len=%s): %s | %s",
                len(raw), _hex_report(raw), self._runtime_identity(),
            )
            bitmask = self._parse_state_bitmask(raw)
            LOG.debug("Relay bitmask = 0b%s", f"{bitmask:08b}")
        except Exception as exc:
            self.last_raw_status = None
            self.last_bitmask = None
            self.channel_states = self._unknown_states()
            LOG.exception("Relay hardware state read failed | %s", self._runtime_identity())
            if isinstance(exc, RelayError):
                raise
            raise RelayError(f"HID 狀態讀取失敗：{exc}") from exc

        self.last_raw_status = raw
        self.last_bitmask = bitmask
        self.channel_states = {
            channel: RelayState.ON if bitmask & (1 << (channel - 1)) else RelayState.OFF
            for channel in range(1, 9)
        }
        return bitmask

    @staticmethod
    def _looks_like_serial(values: list[int]) -> bool:
        return len(values) == 5 and all(0x20 <= value <= 0x7E for value in values)

    @classmethod
    def _parse_state_bitmask(cls, raw: list[int]) -> int:
        """Parse DCTTech payloads with or without a backend-supplied report ID."""
        if len(raw) == 8:
            # Windows hidapi omits Report ID 0 and returns the 8-byte payload.
            return raw[7]
        if len(raw) == 9:
            unprefixed = cls._looks_like_serial(raw[0:5])
            report_id_prefixed = raw[0] == cls.STATUS_REPORT_ID and cls._looks_like_serial(raw[1:6])
            if report_id_prefixed and not unprefixed:
                return raw[8]
            if unprefixed and not report_id_prefixed:
                return raw[7]
            raise RelayError("無法辨識 9-byte HID feature report layout")
        raise RelayError(f"無效的 HID feature report 長度：{len(raw)}（支援 8 或 9 bytes）")

    def set_channel(self, channel: int, state: bool) -> None:
        if channel not in range(1, 9):
            raise RelayError(f"無效的 Channel：CH{channel}")
        if self.handle is None or self.transport is None:
            raise RelayError("Relay 未連線")

        command = self.COMMAND_ON if state else self.COMMAND_OFF
        report = [0x00, command, channel, 0, 0, 0, 0, 0, 0]
        requested = RelayState.ON if state else RelayState.OFF
        self.last_command_report = report
        self.last_send_result = None
        self.last_verification = "NOT_RUN"
        timestamp = datetime.now(timezone.utc).isoformat()
        LOG.debug("%s | CH%s %s requested | %s", timestamp, channel, requested.value, self._runtime_identity())
        LOG.debug("HID feature report: %s | transport type=FEATURE_REPORT", _hex_report(report))
        try:
            sent = self.transport.send(self.handle, report)
            self.last_send_result = sent
            LOG.debug("send_feature_report return value: %s", sent)
            if sent <= 0:
                hid_error = self.transport.error(self.handle)
                LOG.error("send_feature_report failed: return=%s hid_error=%s", sent, hid_error)
                raise RelayError(f"send_feature_report failed：return={sent}, hid_error={hid_error}")
        except Exception as exc:
            self.last_verification = "TRANSMISSION_FAILED"
            LOG.exception("CH%s %s command failed | %s", channel, requested.value, self._runtime_identity())
            if isinstance(exc, RelayError):
                raise
            raise RelayError(f"CH{channel} command send failed：{exc}") from exc

        try:
            self.refresh_hardware_state()
        except RelayError as exc:
            self.channel_states[channel] = RelayState.ERROR
            self.last_verification = "READBACK_FAILED"
            LOG.error("command sent but state verification failed | CH%s expected=%s reason=%s", channel, requested.value, exc)
            raise RelayError(f"CH{channel} command sent but state verification failed：{exc}") from exc

        actual = self.channel_states[channel]
        if actual is not requested:
            self.channel_states[channel] = RelayState.ERROR
            self.last_verification = "FAILED"
            LOG.error(
                "command sent but state verification failed | CH%s expected=%s actual=%s raw=%s",
                channel, requested.value, actual.value, _hex_report(self.last_raw_status or []),
            )
            raise RelayError(
                f"CH{channel} command sent but state verification failed：expected {requested.value}, actual {actual.value}"
            )
        self.last_verification = "SUCCESS"
        LOG.debug("verification: SUCCESS | CH%s=%s", channel, requested.value)

    def relay_on(self, channel: int) -> None:
        self.set_channel(channel, True)

    def relay_off(self, channel: int) -> None:
        self.set_channel(channel, False)


def run_hardware_diagnostic(
    controller: RelayController,
    *,
    sleep: Any = time.sleep,
    output: Any = print,
) -> None:
    """Exercise CH1/CH2 for a human-observed mechanical-click check."""
    sequence = ((1, True, 2), (1, False, 1), (2, True, 2), (2, False, 0))
    for channel, state, delay_after in sequence:
        command = controller.COMMAND_ON if state else controller.COMMAND_OFF
        report = [0x00, command, channel, 0, 0, 0, 0, 0, 0]
        output(f"CH{channel} {'ON' if state else 'OFF'}")
        output(f"command bytes: {_hex_report(report)}")
        output("transport type = FEATURE_REPORT")
        try:
            controller.set_channel(channel, state)
        finally:
            output(f"send_feature_report return value: {controller.last_send_result}")
            raw = controller.last_raw_status
            output(f"raw readback bytes (len={len(raw) if raw is not None else 0}): {_hex_report(raw or [])}")
            bitmask = controller.last_bitmask
            output(f"parsed bitmask: {'UNKNOWN' if bitmask is None else f'0b{bitmask:08b}'}")
            output(f"verification result: {controller.last_verification}")
        if delay_after:
            sleep(delay_after)


class RelayService:
    """Configuration-aware verified operations, group state, and audit log."""

    def __init__(self, controller: RelayController, settings_store: RelaySettingsStore) -> None:
        self.controller = controller
        self.settings_store = settings_store
        self.log_entries: list[RelayLogEntry] = []

    def refresh_connection(self, settings: RelaySettings | None = None) -> str:
        selected = settings or self.settings_store.settings
        self.controller.vid, self.controller.pid, self.controller.product = selected.vid, selected.pid, selected.product
        return self.controller.refresh_connection()

    def refresh_hardware_state(self) -> int:
        return self.controller.refresh_hardware_state()

    def _record(self, operation: str, target: str, previous: str, requested: str, result: str, source: str) -> None:
        entry = RelayLogEntry(datetime.now(timezone.utc).isoformat(), operation, target, previous, requested, result, source)
        self.log_entries.append(entry)
        LOG.info("Relay | %s | %s | %s | %s", target, operation, result, source)

    def channel_on(self, channel: int, source: str = "manual_channel") -> None:
        self._channel(channel, True, source)

    def channel_off(self, channel: int, source: str = "manual_channel") -> None:
        self._channel(channel, False, source)

    def _channel(self, channel: int, state: bool, source: str) -> None:
        previous = self.controller.channel_states[channel].value
        requested = "ON" if state else "OFF"
        try:
            self.controller.set_channel(channel, state)
        except Exception as exc:
            self._record("CHANNEL", f"CH{channel}", previous, requested, "FAILURE", source)
            raise RelayError(f"CH{channel} {requested} failed：{exc}") from exc
        self._record("CHANNEL", f"CH{channel}", previous, requested, "SUCCESS", source)

    def group_on(self, group_id: str, source: str = "main_window", group: RelayGroup | None = None) -> None:
        selected = group or self._enabled_group(group_id)
        previous = self._group_state(selected).value
        try:
            for channel in selected.members:
                self.controller.set_channel(channel, True)
        except Exception as exc:
            for channel in selected.members:
                try:
                    self.controller.set_channel(channel, False)
                except Exception:
                    LOG.exception("Relay rollback failed for CH%s", channel)
            self._record("GROUP", selected.display_name, previous, "ON", "ROLLBACK", source)
            raise RelayError(f"{selected.display_name} ON failed; rollback attempted：{exc}") from exc
        self._record("GROUP", selected.display_name, previous, "ON", "SUCCESS", source)

    def group_off(self, group_id: str, source: str = "main_window", group: RelayGroup | None = None) -> None:
        selected = group or self._enabled_group(group_id)
        previous = self._group_state(selected).value
        failures: list[str] = []
        for channel in selected.members:
            try:
                self.controller.set_channel(channel, False)
            except Exception as exc:
                failures.append(f"CH{channel}: {exc}")
        if failures:
            self._record("GROUP", selected.display_name, previous, "OFF", "FAILURE", source)
            raise RelayError(f"{selected.display_name} OFF failed：" + "；".join(failures))
        self._record("GROUP", selected.display_name, previous, "OFF", "SUCCESS", source)

    def _enabled_group(self, group_id: str) -> RelayGroup:
        group = self.settings_store.settings.group(group_id)
        if group is None or not group.enabled:
            raise RelayError(f"找不到已啟用的 Relay Group：{group_id}")
        return group

    def group_state(self, group_id: str, group: RelayGroup | None = None) -> RelayState:
        selected = group or self.settings_store.settings.group(group_id)
        return RelayState.UNKNOWN if selected is None else self._group_state(selected)

    def _group_state(self, group: RelayGroup) -> RelayState:
        states = [self.controller.channel_states[channel] for channel in group.members]
        if not states or RelayState.UNKNOWN in states:
            return RelayState.UNKNOWN
        if RelayState.ERROR in states:
            return RelayState.ERROR
        if all(state is RelayState.ON for state in states):
            return RelayState.ON
        if all(state is RelayState.OFF for state in states):
            return RelayState.OFF
        return RelayState.PARTIAL
