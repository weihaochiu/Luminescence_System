from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SMUDevice:
    """Identity returned by a VISA instrument during discovery."""

    visa_address: str
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    firmware_version: str = ""
    idn: str = ""
    visa_backend: str = ""
    driver_name: str = "Generic SCPI"
    supported: bool = False

    @property
    def display_name(self) -> str:
        if self.model:
            maker = self.manufacturer.strip()
            return f"{maker} {self.model}".strip()
        return "VISA 儀器"

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


class SMUDriver:
    """Read-only base interface for the current device-management stage."""

    driver_name = "Generic SCPI"

    def __init__(self, resource: Any, device: SMUDevice) -> None:
        self.resource = resource
        self.device = device

    def query_output_enabled(self) -> bool | None:
        """Read output state without changing the instrument configuration."""
        try:
            response = str(self.resource.query(":OUTP?")).strip().upper()
        except Exception:
            return None
        if response in {"1", "ON"}:
            return True
        if response in {"0", "OFF"}:
            return False
        return None

    def safe_stop(self) -> list[str]:
        """Best-effort neutralization of an instrument output."""
        failures: list[str] = []
        for command in (":SOUR:VOLT 0", ":SOUR:CURR 0", ":OUTP OFF"):
            try:
                self.resource.write(command)
            except Exception as exc:
                failures.append(f"{command}: {exc}")
        return failures

    def close(self, safe_stop: bool = True) -> None:
        if safe_stop:
            self.safe_stop()
        self.resource.close()

