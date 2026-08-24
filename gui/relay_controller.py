from __future__ import annotations

"""DCTTech USBRelay8 discovery, runtime state, and verified operations.

The HID path and relay states are runtime-only and are never persisted.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
from threading import RLock
import time
from typing import Any, Callable, Protocol, TYPE_CHECKING

from core.i18n import tr

from .relay_settings import RelayGroup, RelaySettingsStore

if TYPE_CHECKING:
    from .relay_settings import RelaySettings

LOG = logging.getLogger(__name__)


class RelayError(RuntimeError):
    pass


class RelayRoutingFault(RelayError):
    """Mutual-exclusion violation that must latch the SMU interlock."""


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
            raise RelayError(tr("relay.hid_support_missing")) from exc
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
    """Owns the connection and authoritative USBRelay8 controller state.

    CH1 and CH2 command/readback mapping is hardware verified. CH3-CH8 keep
    the protocol's general bit mapping but are not claimed as hardware verified.
    """

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
        settle_seconds: float = 0.15,
        sleep: Any = time.sleep,
    ) -> None:
        self.transport = transport
        self.vid, self.pid, self.product = vid, pid, product
        self.handle: Any | None = None
        self.connected_device: RelayDevice | None = None
        self.settle_seconds = settle_seconds
        self._sleep = sleep
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
            return tr("relay.usbrelay_not_detected")
        if len(devices) > 1:
            return tr("relay.multiple_usbrelay_detected")
        assert self.transport is not None
        try:
            self.handle = self.transport.open(devices[0].path)
            self.connected_device = devices[0]
        except Exception as exc:
            self.handle = None
            self.connected_device = None
            LOG.exception("Relay HID open failed")
            return tr("relay.connection_failed", detail=exc)
        try:
            self.refresh_hardware_state()
        except RelayError as exc:
            return tr("relay.connected_readback_failed", detail=exc)
        return tr("relay.status_connected")

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
        """Read R00 and publish its final byte as controller state."""
        if self.handle is None or self.transport is None:
            self.channel_states = self._unknown_states()
            raise RelayError(tr("relay.not_connected"))
        try:
            raw = self.transport.get_feature_report(
                self.handle, self.STATUS_REPORT_ID, self.REPORT_LENGTH
            )
            LOG.debug(
                "R00 raw feature report (len=%s): %s | %s",
                len(raw), _hex_report(raw), self._runtime_identity(),
            )
            bitmask = self._parse_state_bitmask(raw)
            LOG.debug("R00 state_mask=0x%02X (0b%s)", bitmask, f"{bitmask:08b}")
        except Exception as exc:
            self.last_raw_status = None
            self.last_bitmask = None
            self.channel_states = self._unknown_states()
            LOG.exception("Relay hardware state read failed | %s", self._runtime_identity())
            if isinstance(exc, RelayError):
                raise
            raise RelayError(tr("relay.readback_failed", detail=exc)) from exc

        self.last_raw_status = raw
        self.last_bitmask = bitmask
        self.channel_states = {
            channel: RelayState.ON if bitmask & (1 << (channel - 1)) else RelayState.OFF
            for channel in range(1, 9)
        }
        return bitmask

    @classmethod
    def _parse_state_bitmask(cls, raw: list[int]) -> int:
        """Parse hardware-verified R00: the final returned byte is the mask."""
        if len(raw) not in (8, 9):
            raise RelayError(tr("relay.invalid_report_length", length=len(raw)))
        return raw[-1]

    def set_channel(self, channel: int, state: bool) -> None:
        if channel not in range(1, 9):
            raise RelayError(tr("relay.invalid_channel", channel=channel))
        if self.handle is None or self.transport is None:
            raise RelayError(tr("relay.not_connected"))

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
            self._sleep(self.settle_seconds)
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
        LOG.debug("Relay command verified | CH%s state=%s", channel, requested.value)

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
        self._operation_lock = RLock()
        self._routing_fault_handler: Callable[[str], None] | None = None

    def set_routing_fault_handler(self, handler: Callable[[str], None] | None) -> None:
        """Register the system-level SMU interlock without duplicating controllers."""

        self._routing_fault_handler = handler

    def smu_output_mapping(self) -> dict[str, int]:
        return dict(self.settings_store.settings.smu_output_channels)

    def physical_relay_for_smu_channel(self, channel_id: str) -> int:
        try:
            return self.settings_store.settings.smu_output_channels[channel_id]
        except KeyError as exc:
            raise RelayError(tr("relay.unknown_smu_channel", channel=channel_id)) from exc

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
        if channel in self.settings_store.settings.smu_output_channels.values():
            raise RelayError(tr("relay.routing_channel_protected", relay=channel))
        previous = self.controller.channel_states[channel].value
        requested = "ON" if state else "OFF"
        try:
            self.controller.set_channel(channel, state)
        except Exception as exc:
            self._record("CHANNEL", f"CH{channel}", previous, requested, "FAILURE", source)
            raise RelayError(f"CH{channel} {requested} failed：{exc}") from exc
        self._record("CHANNEL", f"CH{channel}", previous, requested, "SUCCESS", source)

    def group_on(self, group_id: str, source: str = "main_window", group: RelayGroup | None = None) -> None:
        with self._operation_lock:
            self._group_on_unlocked(group_id, source, group)

    def _group_on_unlocked(self, group_id: str, source: str, group: RelayGroup | None) -> None:
        selected = group or self._enabled_group(group_id)
        routing_relays = set(self.settings_store.settings.smu_output_channels.values())
        if routing_relays & set(selected.members):
            raise RelayError(tr("relay.routing_group_on_protected", group=selected.display_name))
        previous = self._group_state(selected).value
        try:
            for channel in selected.members:
                self.controller.set_channel(channel, True)
            state_mask = self.controller.refresh_hardware_state()
            group_mask = self._group_mask(selected)
            if state_mask & group_mask != group_mask:
                raise RelayError(
                    f"Relay controller state mismatch：mask=0x{state_mask:02X}, expected ON mask=0x{group_mask:02X}"
                )
        except Exception as exc:
            for channel in selected.members:
                try:
                    self.controller.set_channel(channel, False)
                except Exception:
                    LOG.exception("Relay rollback failed for CH%s", channel)
            self._record("GROUP", selected.display_name, previous, "ON", "ROLLBACK", source)
            raise RelayError(f"{selected.display_name} ON failed; rollback attempted：{exc}") from exc
        LOG.info("%s relay controller state verified=ON | mask=0x%02X", selected.display_name, state_mask)
        self._record("GROUP", selected.display_name, previous, "ON", "SUCCESS", source)

    def group_off(self, group_id: str, source: str = "main_window", group: RelayGroup | None = None) -> None:
        with self._operation_lock:
            self._group_off_unlocked(group_id, source, group)

    def _group_off_unlocked(self, group_id: str, source: str, group: RelayGroup | None) -> None:
        selected = group or self._enabled_group(group_id)
        routing_relays = set(self.settings_store.settings.smu_output_channels.values())
        if routing_relays & set(selected.members):
            raise RelayError(tr("relay.routing_group_control_protected", group=selected.display_name))
        previous = self._group_state(selected).value
        failures: list[str] = []
        for channel in selected.members:
            try:
                self.controller.set_channel(channel, False)
            except Exception as exc:
                failures.append(f"CH{channel}: {exc}")
        try:
            state_mask = self.controller.refresh_hardware_state()
            group_mask = self._group_mask(selected)
            if state_mask & group_mask:
                failures.append(
                    f"Relay controller state mismatch：mask=0x{state_mask:02X}, expected OFF mask=0x{group_mask:02X}"
                )
        except Exception as exc:
            failures.append(f"Readback failed: {exc}")
        if failures:
            self._record("GROUP", selected.display_name, previous, "OFF", "FAILURE", source)
            raise RelayError(f"{selected.display_name} OFF failed：" + "；".join(failures))
        LOG.info("%s relay controller state verified=OFF | mask=0x%02X", selected.display_name, state_mask)
        self._record("GROUP", selected.display_name, previous, "OFF", "SUCCESS", source)

    @staticmethod
    def _group_mask(group: RelayGroup) -> int:
        return sum(1 << (channel - 1) for channel in group.members)

    def safe_white_light_off(self, source: str = "safety_cleanup") -> bool:
        """Best-effort logical OFF; this cannot verify coil power or contacts."""

        with self._operation_lock:
            return self._safe_white_light_off_unlocked(source)

    def _safe_white_light_off_unlocked(self, source: str) -> bool:
        if not self.controller.connected:
            LOG.warning("White Light OFF skipped: USBRelay8 not connected | source=%s", source)
            return False
        try:
            # CH1/CH2 are the hardware-verified White Light relay channels.
            self.controller.set_channel(1, False)
            self.controller.set_channel(2, False)
            state_mask = self.controller.refresh_hardware_state()
            if state_mask & 0x03:
                raise RelayError(f"Relay controller state mismatch：mask=0x{state_mask:02X}, expected 0x00")
        except Exception:
            LOG.exception("White Light relay controller OFF verification failed | source=%s", source)
            return False
        LOG.info("White Light relay controller OFF verified | mask=0x%02X source=%s", state_mask, source)
        return True

    def select_smu_output_channel(
        self,
        channel_id: str,
        confirm_smu_output_off: Callable[[], bool],
        check_cancel: Callable[[], None] = lambda: None,
        source: str = "smu_manual_output",
    ) -> int:
        """Select one configured route using verified break-before-make."""

        # Never hold the Relay lock while authoritative SMU/VISA I/O runs.
        # The caller's generation/ownership check is repeated after the query
        # and again after acquiring the Relay lock, closing the race window.
        check_cancel()
        if not confirm_smu_output_off():
            raise RelayError(
                "SMU OUTPUT OFF was not authoritatively confirmed; routing is blocked"
            )
        check_cancel()
        with self._operation_lock:
            check_cancel()
            target_relay = self.physical_relay_for_smu_channel(channel_id)
            mapping = self.smu_output_mapping()
            before_mask = self.controller.refresh_hardware_state()
            before = self._routing_state_text(before_mask, mapping)
            self._assert_routing_mutual_exclusion_unlocked(before_mask, mapping, source)
            LOG.info(
                "SMU_ROUTING REQUEST channel=%s mapped_relay=%d state_before=%s",
                channel_id,
                target_relay,
                before,
            )
            try:
                check_cancel()
                failures = self._turn_off_smu_relays_unlocked(mapping)
                if failures:
                    raise RelayError("SMU routing all-OFF failed: " + "; ".join(failures))
                all_off_mask = self.controller.refresh_hardware_state()
                routing_mask = self._routing_mask(mapping)
                if all_off_mask & routing_mask:
                    raise RelayError(
                        f"SMU routing all-OFF verification failed: mask=0x{all_off_mask:02X}"
                    )
                LOG.info("SMU_ROUTING BREAK verified_all_off mask=0x%02X", all_off_mask)
                check_cancel()
                self.controller.set_channel(target_relay, True)
                check_cancel()
                after_mask = self.controller.refresh_hardware_state()
                active = self._assert_routing_mutual_exclusion_unlocked(
                    after_mask, mapping, source
                )
                if active != [channel_id]:
                    raise RelayError(
                        "SMU routing target verification failed: "
                        f"expected={channel_id}/Relay {target_relay}, "
                        f"actual={active or 'none'}, mask=0x{after_mask:02X}"
                    )
                check_cancel()
            except Exception:
                self._safe_white_light_off_unlocked(source + "_rollback")
                self._safe_smu_output_channels_off_unlocked(source + "_rollback")
                self._record("SMU_ROUTING", channel_id, before, "ON", "FAILURE", source)
                raise
            after = self._routing_state_text(after_mask, mapping)
            LOG.info(
                "SMU_ROUTING MAKE verified channel=%s relay=%d state_after=%s",
                channel_id,
                target_relay,
                after,
            )
            self._record("SMU_ROUTING", channel_id, before, "ON", "SUCCESS", source)
            return target_relay

    def clear_smu_output_channels(self, source: str = "smu_manual_stop") -> None:
        """Turn every configured routing relay OFF and require readback confirmation."""

        with self._operation_lock:
            mapping = self.smu_output_mapping()
            before = self._routing_state_text_from_cached(mapping)
            failures = self._turn_off_smu_relays_unlocked(mapping)
            try:
                state_mask = self.controller.refresh_hardware_state()
                if state_mask & self._routing_mask(mapping):
                    failures.append(f"readback mask=0x{state_mask:02X} is not all OFF")
            except Exception as exc:
                failures.append(f"readback failed: {exc}")
            if failures:
                self._record("SMU_ROUTING", "Ch1-Ch4", before, "OFF", "FAILURE", source)
                raise RelayError("SMU routing OFF failed: " + "; ".join(failures))
            LOG.info("SMU_ROUTING all OFF verified mask=0x%02X source=%s", state_mask, source)
            self._record("SMU_ROUTING", "Ch1-Ch4", before, "OFF", "SUCCESS", source)

    def safe_smu_output_channels_off(self, source: str = "safety_cleanup") -> bool:
        with self._operation_lock:
            return self._safe_smu_output_channels_off_unlocked(source)

    def _safe_smu_output_channels_off_unlocked(self, source: str) -> bool:
        if not self.controller.connected:
            LOG.warning("SMU routing OFF skipped: USBRelay8 not connected | source=%s", source)
            return False
        mapping = self.smu_output_mapping()
        failures = self._turn_off_smu_relays_unlocked(mapping)
        try:
            state_mask = self.controller.refresh_hardware_state()
            if state_mask & self._routing_mask(mapping):
                failures.append(f"readback mask=0x{state_mask:02X} is not all OFF")
        except Exception as exc:
            failures.append(f"readback failed: {exc}")
        if failures:
            LOG.error("SMU routing OFF verification failed source=%s failures=%s", source, failures)
            return False
        LOG.info("SMU routing OFF verified mask=0x%02X source=%s", state_mask, source)
        return True

    def active_smu_output_channel(self, refresh: bool = True) -> str | None:
        with self._operation_lock:
            mapping = self.smu_output_mapping()
            mask = (
                self.controller.refresh_hardware_state()
                if refresh
                else self.controller.last_bitmask
            )
            if mask is None:
                raise RelayError("SMU routing state is unavailable")
            active = self._assert_routing_mutual_exclusion_unlocked(
                mask, mapping, "active_smu_output_channel"
            )
            return active[0] if active else None

    def verify_smu_output_channel_state(
        self,
        expected_channel: str | None,
        source: str = "smu_manual_verify",
    ) -> int | None:
        with self._operation_lock:
            mapping = self.smu_output_mapping()
            state_mask = self.controller.refresh_hardware_state()
            active = self._assert_routing_mutual_exclusion_unlocked(
                state_mask, mapping, source
            )
            expected = [] if expected_channel is None else [expected_channel]
            if active != expected:
                reason = (
                    f"SMU routing mismatch: expected={expected or 'none'}, "
                    f"actual={active or 'none'}, mask=0x{state_mask:02X}"
                )
                self._latch_routing_fault_unlocked(reason, source)
            return (
                None
                if expected_channel is None
                else mapping[expected_channel]
            )

    @staticmethod
    def _routing_mask(mapping: dict[str, int]) -> int:
        return sum(1 << (relay - 1) for relay in set(mapping.values()))

    @staticmethod
    def _routing_state_text(mask: int, mapping: dict[str, int]) -> str:
        return ",".join(
            f"{channel_id}/R{relay}={'ON' if mask & (1 << (relay - 1)) else 'OFF'}"
            for channel_id, relay in sorted(mapping.items())
        )

    def _routing_state_text_from_cached(self, mapping: dict[str, int]) -> str:
        return ",".join(
            f"{channel_id}/R{relay}={self.controller.channel_states[relay].value}"
            for channel_id, relay in sorted(mapping.items())
        )

    def _turn_off_smu_relays_unlocked(self, mapping: dict[str, int]) -> list[str]:
        failures: list[str] = []
        for relay in sorted(set(mapping.values())):
            try:
                self.controller.set_channel(relay, False)
            except Exception as exc:
                failures.append(f"Relay {relay}: {exc}")
        return failures

    def _assert_routing_mutual_exclusion_unlocked(
        self,
        state_mask: int,
        mapping: dict[str, int],
        source: str,
    ) -> list[str]:
        active = [
            channel_id
            for channel_id, relay in sorted(mapping.items())
            if state_mask & (1 << (relay - 1))
        ]
        if len(active) <= 1:
            return active
        reason = (
            f"SMU routing mutual-exclusion fault: active={active}, "
            f"state={self._routing_state_text(state_mask, mapping)}"
        )
        self._latch_routing_fault_unlocked(reason, source)
        raise AssertionError("routing fault handler must raise")

    def _latch_routing_fault_unlocked(self, reason: str, source: str) -> None:
        """Fail closed through the single system-level external interlock path."""

        LOG.critical("%s source=%s", reason, source)
        self._safe_white_light_off_unlocked(source + "_fault")
        self._safe_smu_output_channels_off_unlocked(source + "_fault")
        self._record("SMU_ROUTING_FAULT", "routing", reason, "ALL OFF", "FAULT", source)
        if self._routing_fault_handler is not None:
            try:
                self._routing_fault_handler(reason)
            except Exception:
                LOG.exception("SMU routing fault handler failed")
        raise RelayRoutingFault(reason)

    def shutdown(self) -> bool:
        try:
            routing_verified = self.safe_smu_output_channels_off(
                "relay_controller_shutdown"
            )
        except Exception:
            routing_verified = False
            LOG.exception("SMU routing OFF failed during RelayService shutdown")
        try:
            white_verified = self.safe_white_light_off("relay_controller_shutdown")
        except Exception:
            white_verified = False
            LOG.exception("White Light OFF failed during RelayService shutdown")
        self.controller.disconnect()
        return white_verified and routing_verified

    def _enabled_group(self, group_id: str) -> RelayGroup:
        group = self.settings_store.settings.group(group_id)
        if group is None or not group.enabled:
            raise RelayError(tr("relay.enabled_group_not_found", group_id=group_id))
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
