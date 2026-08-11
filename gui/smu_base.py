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
    """Small SCPI hardware abstraction shared by manual and Recipe control."""

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

    def configure_voltage_source(self, volts: float, current_compliance_a: float) -> None:
        raise NotImplementedError("This SMU driver does not support voltage-source control")

    def configure_current_source(self, amps: float, voltage_compliance_v: float) -> None:
        raise NotImplementedError("This SMU driver does not support current-source control")

    def set_voltage(self, volts: float) -> None:
        raise NotImplementedError("This SMU driver does not support voltage-source control")

    def set_current(self, amps: float) -> None:
        raise NotImplementedError("This SMU driver does not support current-source control")

    def set_output_enabled(self, enabled: bool) -> None:
        raise NotImplementedError("This SMU driver does not support output control")

    def measure_voltage(self) -> float:
        return float(str(self.resource.query(":MEAS:VOLT?")).strip())

    def measure_current(self) -> float:
        return float(str(self.resource.query(":MEAS:CURR?")).strip())

    def query_compliance_tripped(self, mode: str) -> bool | None:
        command = ":SENS:CURR:PROT:TRIP?" if mode == "CV" else ":SENS:VOLT:PROT:TRIP?"
        try:
            response = str(self.resource.query(command)).strip().upper()
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

