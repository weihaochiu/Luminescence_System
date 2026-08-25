from __future__ import annotations

import logging
import math
from typing import Any

from .numeric import format_scpi_number
from .smu_base import SMUDevice, SMUDriver


LOG = logging.getLogger(__name__)


def is_keysight_b2900(manufacturer: str, model: str) -> bool:
    maker = manufacturer.strip().upper()
    normalized_model = model.strip().upper()
    return ("KEYSIGHT" in maker or "AGILENT" in maker) and normalized_model.startswith("B29")


class KeysightB2900Driver(SMUDriver):
    """Identity and safety-state support for Keysight B2900-series SMUs."""

    driver_name = "Keysight B2900"

    def __init__(self, resource: Any, device: SMUDevice) -> None:
        super().__init__(resource, device)
        self._source_mode: str | None = None

    def configure_voltage_source(self, volts: float, current_compliance_a: float) -> None:
        self._configure_source_mode("VOLT")
        self.resource.write(f":SENS:CURR:PROT {format_scpi_number(current_compliance_a)}")
        self._set_and_verify_source_level("VOLT", volts)

    def configure_current_source(self, amps: float, voltage_compliance_v: float) -> None:
        self._configure_source_mode("CURR")
        self.resource.write(f":SENS:VOLT:PROT {format_scpi_number(voltage_compliance_v)}")
        self._set_and_verify_source_level("CURR", amps)

    def configure_zero_level_measurement(
        self,
        source_mode: str,
        measurement_mode: str,
        compliance: float,
        nplc: float | None,
    ) -> None:
        """Configure a verified zero-level Jsc/Voc measurement transition."""

        source = self._source_function(source_mode)
        measurement = self._nplc_function(measurement_mode)
        if source == measurement:
            raise ValueError("Source and measurement functions must be different")
        self._configure_source_mode(source)
        self.resource.write(f':SENS:FUNC "{measurement}"')
        self.resource.write(f":SENS:{measurement}:RANG:AUTO ON")
        if nplc is not None:
            self.set_measurement_nplc_auto(measurement, False)
            self.set_measurement_nplc(measurement, nplc)
        if source == "VOLT":
            self.resource.write(f":SENS:CURR:PROT {format_scpi_number(compliance)}")
        else:
            self.resource.write(f":SENS:VOLT:PROT {format_scpi_number(compliance)}")
        self._set_and_verify_source_level(source, 0.0)
        LOG.info(
            "B2900_MEASUREMENT_CONFIG source_mode=%s measurement_mode=%s "
            "range=AUTO nplc_auto=%s nplc=%s compliance=%g source_level=0",
            source,
            measurement,
            "OFF" if nplc is not None else "UNCHANGED",
            f"{nplc:g}" if nplc is not None else "UNCHANGED",
            compliance,
        )

    @staticmethod
    def _source_function(mode: str) -> str:
        normalized = str(mode).strip().upper()
        if normalized not in {"CURR", "VOLT"}:
            raise ValueError("Source mode must be CURR or VOLT")
        return normalized

    def _configure_source_mode(self, mode: str) -> None:
        requested = self._source_function(mode)
        try:
            self.set_output_enabled(False)
            if self.query_output_enabled() is not False:
                raise RuntimeError("OUTPUT OFF was not confirmed before source-mode change")
            self.resource.write(f":SOUR:FUNC:MODE {requested}")
            readback = self.query_source_mode()
            LOG.info(
                "B2900_SOURCE_MODE requested=%s readback=%s",
                requested,
                readback or "UNKNOWN",
            )
            if readback != requested:
                error = self._query_system_error_for_diagnostic()
                raise RuntimeError(
                    "B2900 source-mode verification failed: "
                    f"requested {requested}, read back {readback or 'UNKNOWN'}, "
                    f"system error {error}"
                )
            self._source_mode = requested
        except Exception:
            LOG.exception("B2900_SOURCE_MODE_CONFIGURATION_FAILED requested=%s", requested)
            raise

    def query_source_mode(self) -> str | None:
        response = str(self.resource.query(":SOUR:FUNC:MODE?")).strip().upper().strip('"')
        return response if response in {"VOLT", "CURR"} else None

    def _query_system_error_for_diagnostic(self) -> str:
        try:
            return str(self.resource.query(":SYST:ERR?")).strip()
        except Exception as exc:  # noqa: BLE001 - preserve the primary failure
            return f"unavailable ({exc})"

    def _set_and_verify_source_level(self, mode: str, value: float) -> None:
        source = self._source_function(mode)
        numeric = float(value)
        if source == "VOLT":
            self.set_voltage(numeric)
        else:
            self.set_current(numeric)
        readback = float(str(self.resource.query(f":SOUR:{source}?")).strip())
        tolerance = max(1e-12, abs(numeric) * 1e-9)
        if not math.isclose(readback, numeric, rel_tol=1e-9, abs_tol=tolerance):
            raise RuntimeError(
                f"B2900 {source} source-level verification failed: "
                f"requested {numeric:g}, read back {readback:g}"
            )

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

    def safe_stop(self) -> list[str]:
        """Turn OUTPUT OFF first, then zero only the verified active source mode."""

        failures = super().safe_stop()
        command = {
            "VOLT": ":SOUR:VOLT 0",
            "CURR": ":SOUR:CURR 0",
        }.get(self._source_mode)
        if not failures and command is not None:
            try:
                self.resource.write(command)
            except Exception as exc:  # noqa: BLE001 - OUTPUT OFF remains first priority
                LOG.warning(
                    "B2900_SAFE_STOP source-level zero failed after OUTPUT OFF "
                    "command=%s error=%s",
                    command,
                    exc,
                )
        return failures

