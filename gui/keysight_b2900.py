from __future__ import annotations

from typing import Any

from .numeric import format_scpi_number
from .smu_base import SMUDevice, SMUDriver


def is_keysight_b2900(manufacturer: str, model: str) -> bool:
    maker = manufacturer.strip().upper()
    normalized_model = model.strip().upper()
    return ("KEYSIGHT" in maker or "AGILENT" in maker) and normalized_model.startswith("B29")


class KeysightB2900Driver(SMUDriver):
    """Identity and safety-state support for Keysight B2900-series SMUs."""

    driver_name = "Keysight B2900"

    def __init__(self, resource: Any, device: SMUDevice) -> None:
        super().__init__(resource, device)

    def configure_voltage_source(self, volts: float, current_compliance_a: float) -> None:
        self.resource.write(":SOUR:FUNC VOLT")
        self.resource.write(f":SENS:CURR:PROT {format_scpi_number(current_compliance_a)}")
        self.set_voltage(volts)

    def configure_current_source(self, amps: float, voltage_compliance_v: float) -> None:
        self.resource.write(":SOUR:FUNC CURR")
        self.resource.write(f":SENS:VOLT:PROT {format_scpi_number(voltage_compliance_v)}")
        self.set_current(amps)

    def set_voltage(self, volts: float) -> None:
        self.resource.write(f":SOUR:VOLT {format_scpi_number(volts)}")

    def set_current(self, amps: float) -> None:
        self.resource.write(f":SOUR:CURR {format_scpi_number(amps)}")

    def set_output_enabled(self, enabled: bool) -> None:
        self.resource.write(":OUTP ON" if enabled else ":OUTP OFF")

