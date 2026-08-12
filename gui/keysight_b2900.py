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

    def set_auto_output_enabled(self, enabled: bool) -> None:
        self.resource.write(":OUTP:ON:AUTO ON" if enabled else ":OUTP:ON:AUTO OFF")

    def query_auto_output_enabled(self) -> bool | None:
        try:
            response = str(self.resource.query(":OUTP:ON:AUTO?")).strip().upper()
        except Exception:
            return None
        if response in {"1", "ON"}:
            return True
        if response in {"0", "OFF"}:
            return False
        return None

    @staticmethod
    def _nplc_function(mode: str) -> str:
        normalized = str(mode).strip().upper()
        if normalized not in {"CURR", "VOLT"}:
            raise ValueError("Measurement NPLC mode must be CURR or VOLT")
        return normalized

    def supports_measurement_nplc(self, mode: str) -> bool:
        try:
            self._nplc_function(mode)
        except ValueError:
            return False
        return True

    def get_measurement_nplc(self, mode: str) -> float | None:
        function = self._nplc_function(mode)
        try:
            return float(str(self.resource.query(f":SENS:{function}:NPLC?")).strip())
        except Exception:
            return None

    def set_measurement_nplc(self, mode: str, nplc: float) -> None:
        function = self._nplc_function(mode)
        if not 0.001 <= float(nplc) <= 100.0:
            raise ValueError("B2900 NPLC must be between 0.001 and 100")
        self.resource.write(f":SENS:{function}:NPLC {format_scpi_number(nplc)}")

    def get_measurement_nplc_auto(self, mode: str) -> bool | None:
        function = self._nplc_function(mode)
        try:
            response = str(self.resource.query(f":SENS:{function}:NPLC:AUTO?")).strip().upper()
        except Exception:
            return None
        if response in {"1", "ON"}:
            return True
        if response in {"0", "OFF"}:
            return False
        return None

    def supports_measurement_nplc_auto(self, mode: str) -> bool:
        return self.supports_measurement_nplc(mode)

    def set_measurement_nplc_auto(self, mode: str, enabled: bool) -> None:
        function = self._nplc_function(mode)
        state = "ON" if enabled else "OFF"
        self.resource.write(f":SENS:{function}:NPLC:AUTO {state}")

