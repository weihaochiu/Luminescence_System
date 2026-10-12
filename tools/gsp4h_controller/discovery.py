"""Read-only protocol discovery: never write mode or brightness while probing."""
from __future__ import annotations

from dataclasses import dataclass
import re
from threading import Event
from typing import Callable

from .controller import Log, Transport
from .protocol import ControllerError, brightness_command, mode_command, parse_brightness, parse_mode


class ScanCancelled(Exception):
    pass


@dataclass(frozen=True)
class PortInfo:
    name: str
    description: str = ""
    manufacturer: str = ""
    usb_id: str = ""
    serial_number: str = ""

    @property
    def display(self) -> str:
        return " | ".join(part for part in (
            self.name, self.description, self.manufacturer, self.usb_id,
            f"SN={self.serial_number}" if self.serial_number else "",
        ) if part)


@dataclass(frozen=True)
class ScanResult:
    ports: tuple[PortInfo, ...]
    compatible: tuple[str, ...]
    selected: str | None


def scan_ports(
    ports: list[PortInfo], make_transport: Callable[[], Transport],
    cancel: Event, log: Log, preferred: str = "COM6", parity: str = "none",
) -> ScanResult:
    def check_cancel() -> None:
        if cancel.is_set():
            raise ScanCancelled()

    def key(port: PortInfo) -> tuple[bool, int, str]:
        digits = re.search(r"\d+$", port.name)
        return (port.name.upper() != preferred.upper(), int(digits[0]) if digits else 99999, port.name)

    ordered = sorted({port.name: port for port in ports}.values(), key=key)
    compatible: list[str] = []
    for port in ordered:
        check_cancel()
        log("SCAN", port.name)
        transport = make_transport()
        try:
            transport.open(port.name, parity)
            check_cancel()
            command = mode_command()
            log("TX", f"{port.name} {command!r}")
            raw = transport.exchange(command, 1)
            log("RX", f"{port.name} {raw!r}")
            parse_mode(raw)
            for channel in range(1, 5):
                check_cancel()
                command = brightness_command(channel)
                log("TX", f"{port.name} {command!r}")
                raw = transport.exchange(command, 5)
                log("RX", f"{port.name} {raw!r}")
                parse_brightness(raw, channel)
            check_cancel()
            compatible.append(port.name)
            log("MATCH", port.name)
        except ScanCancelled:
            raise
        except Exception as exc:
            log("SCAN_SKIP", f"{port.name}: {exc}")
        finally:
            # Probe sessions never take control or change a setting. Do not send
            # OFF commands to unidentified or unselected devices during scanning.
            transport.close()
    check_cancel()
    preferred_match = next((port for port in compatible if port.upper() == preferred.upper()), None)
    selected = preferred_match or (compatible[0] if len(compatible) == 1 else None)
    return ScanResult(tuple(ordered), tuple(compatible), selected)
