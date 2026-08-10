from __future__ import annotations

"""USBRelay8 discovery and safe channel/group operations.

The HID path is deliberately runtime-only: it is never persisted in settings.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Protocol

from .relay_settings import RelayGroup, RelaySettingsStore

LOG = logging.getLogger(__name__)


class RelayError(RuntimeError):
    pass


class RelayTransport(Protocol):
    def enumerate(self, vid: int, pid: int) -> list[dict[str, Any]]: ...
    def open(self, path: bytes | str) -> Any: ...
    def send(self, handle: Any, report: list[int]) -> None: ...
    def close(self, handle: Any) -> None: ...


class HidApiTransport:
    """Small adapter around optional ``hidapi`` / ``hid`` package."""

    def __init__(self) -> None:
        try:
            import hid  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RelayError("未安裝 HID 支援套件；無法使用 USBRelay8") from exc
        self.hid = hid

    def enumerate(self, vid: int, pid: int) -> list[dict[str, Any]]:
        return list(self.hid.enumerate(vid, pid))

    def open(self, path: bytes | str) -> Any:
        device = self.hid.device()
        device.open_path(path)
        return device

    def send(self, handle: Any, report: list[int]) -> None:
        handle.write(report)

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


class RelayController:
    """Generic 8-channel hardware controller; no application group knowledge."""

    def __init__(self, transport: RelayTransport | None = None, vid: int = 0x16C0, pid: int = 0x05DF,
                 product: str = "USBRelay8") -> None:
        self.transport = transport
        self.vid, self.pid, self.product = vid, pid, product
        self.handle: Any | None = None
        self.connected_device: RelayDevice | None = None
        self.channel_states: dict[int, bool | None] = {index: None for index in range(1, 9)}

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
            return "偵測到多個相同 Relay 控制器，無法安全判定設備"
        if len(devices) != 1:
            return "偵測到多個 Relay 控制器，請只連接目標設備後重新偵測"
        assert self.transport is not None
        try:
            self.handle = self.transport.open(devices[0].path)
        except Exception as exc:
            self.handle = None
            return f"Relay 連線失敗：{exc}"
        self.connected_device = devices[0]
        return "Relay 已連線"

    def disconnect(self) -> None:
        if self.handle is not None and self.transport is not None:
            try:
                self.transport.close(self.handle)
            except Exception:
                LOG.exception("Failed to close relay HID device")
        self.handle = None
        self.connected_device = None
        self.channel_states = {index: None for index in range(1, 9)}

    def set_channel(self, channel: int, state: bool) -> None:
        if channel not in range(1, 9):
            raise RelayError(f"無效 Channel：CH{channel}")
        if self.handle is None or self.transport is None:
            raise RelayError("Relay 未連線")
        # USBRelay8 HID output report: report-id 0, channel 1..8, 1=ON / 0=OFF.
        self.transport.send(self.handle, [0, channel, 1 if state else 0])
        self.channel_states[channel] = state

    def relay_on(self, channel: int) -> None:
        self.set_channel(channel, True)

    def relay_off(self, channel: int) -> None:
        self.set_channel(channel, False)


class RelayService:
    """Configuration-aware operations, group rollback, and audit log."""

    def __init__(self, controller: RelayController, settings_store: RelaySettingsStore) -> None:
        self.controller = controller
        self.settings_store = settings_store
        self.log_entries: list[RelayLogEntry] = []

    def refresh_connection(self) -> str:
        settings = self.settings_store.settings
        self.controller.vid, self.controller.pid, self.controller.product = settings.vid, settings.pid, settings.product
        return self.controller.refresh_connection()

    def _record(self, operation: str, target: str, previous: str, requested: str, result: str, source: str) -> None:
        entry = RelayLogEntry(datetime.now(timezone.utc).isoformat(), operation, target, previous, requested, result, source)
        self.log_entries.append(entry)
        LOG.info("Relay | %s | %s | %s | %s", target, operation, result, source)

    def channel_on(self, channel: int, source: str = "manual_channel") -> None:
        self._channel(channel, True, source)

    def channel_off(self, channel: int, source: str = "manual_channel") -> None:
        self._channel(channel, False, source)

    def _channel(self, channel: int, state: bool, source: str) -> None:
        previous = self.controller.channel_states[channel]
        try:
            self.controller.set_channel(channel, state)
        except Exception as exc:
            self._record("CHANNEL", f"CH{channel}", str(previous), "ON" if state else "OFF", "FAILURE", source)
            raise RelayError(f"CH{channel} {'開啟' if state else '關閉'}失敗：{exc}") from exc
        self._record("CHANNEL", f"CH{channel}", str(previous), "ON" if state else "OFF", "SUCCESS", source)

    def group_on(self, group_id: str, source: str = "main_window") -> None:
        group = self._enabled_group(group_id)
        previous = self._group_state(group)
        try:
            for channel in group.members:
                self.controller.set_channel(channel, True)
        except Exception as exc:
            for channel in group.members:
                try:
                    self.controller.set_channel(channel, False)
                except Exception:
                    LOG.exception("Relay rollback failed for CH%s", channel)
            self._record("GROUP", group.display_name, previous, "ON", "ROLLBACK", source)
            raise RelayError(f"{group.display_name} 開啟失敗，已嘗試關閉所有 member：{exc}") from exc
        self._record("GROUP", group.display_name, previous, "ON", "SUCCESS", source)

    def group_off(self, group_id: str, source: str = "main_window") -> None:
        group = self._enabled_group(group_id)
        previous = self._group_state(group)
        failures: list[str] = []
        for channel in group.members:
            try:
                self.controller.set_channel(channel, False)
            except Exception as exc:
                failures.append(f"CH{channel}: {exc}")
        if failures:
            self._record("GROUP", group.display_name, previous, "OFF", "FAILURE", source)
            raise RelayError(f"{group.display_name} 關閉不完整：" + "；".join(failures))
        self._record("GROUP", group.display_name, previous, "OFF", "SUCCESS", source)

    def _enabled_group(self, group_id: str) -> RelayGroup:
        group = self.settings_store.settings.group(group_id)
        if group is None or not group.enabled:
            raise RelayError(f"找不到或未啟用的 Relay Group：{group_id}")
        return group

    def _group_state(self, group: RelayGroup) -> str:
        states = {self.controller.channel_states[channel] for channel in group.members}
        return "ON" if states == {True} else "OFF" if states == {False} else "UNKNOWN"
