from __future__ import annotations

"""Shared SCPI primitives and driver contract for supported SMUs."""

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from typing import Any

from core.i18n import tr


def _identity_value(value: str) -> str:
    return str(value or "").strip().casefold()


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
        return tr("smu.visa_instrument")

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SMUFaultIdentity:
    """Immutable physical identity bound to an unresolved SMU safety fault.

    A serial number is the strong identity.  VISA resources are retained for
    diagnostics and consistency checks, but a reused resource can never
    override a serial mismatch.  Devices without a serial are recoverable only
    when the resource and the full, non-empty IDN identity agree.
    """

    visa_address: str
    serial_number: str
    manufacturer: str
    model: str
    idn: str

    @classmethod
    def from_device(cls, device: SMUDevice) -> "SMUFaultIdentity":
        return cls(
            visa_address=str(device.visa_address or "").strip(),
            serial_number=str(device.serial_number or "").strip(),
            manufacturer=str(device.manufacturer or "").strip(),
            model=str(device.model or "").strip(),
            idn=str(device.idn or "").strip(),
        )

    @property
    def display_name(self) -> str:
        instrument = " ".join(
            value for value in (self.manufacturer, self.model) if value
        ).strip()
        if self.serial_number:
            return f"{instrument} ({self.serial_number})" if instrument else self.serial_number
        return instrument or self.idn or self.visa_address

    def matches_device(self, device: SMUDevice) -> bool:
        return self.matches(SMUFaultIdentity.from_device(device))

    def matches(self, other: "SMUFaultIdentity") -> bool:
        serial = _identity_value(self.serial_number)
        other_serial = _identity_value(other.serial_number)
        if serial or other_serial:
            if not serial or not other_serial or serial != other_serial:
                return False
            manufacturer = _identity_value(self.manufacturer)
            other_manufacturer = _identity_value(other.manufacturer)
            model = _identity_value(self.model)
            other_model = _identity_value(other.model)
            return bool(
                manufacturer
                and other_manufacturer
                and manufacturer == other_manufacturer
                and model
                and other_model
                and model == other_model
            )

        resource = _identity_value(self.visa_address)
        other_resource = _identity_value(other.visa_address)
        idn = _identity_value(self.idn)
        other_idn = _identity_value(other.idn)
        return bool(
            resource
            and resource == other_resource
            and idn
            and idn == other_idn
            and _identity_value(self.manufacturer)
            == _identity_value(other.manufacturer)
            and _identity_value(self.model) == _identity_value(other.model)
        )

    def to_context(self) -> dict[str, str]:
        return {
            "instrument": self.display_name,
            "resource": self.visa_address,
            "smu_serial_number": self.serial_number,
            "smu_manufacturer": self.manufacturer,
            "smu_model": self.model,
            "smu_idn": self.idn,
        }


class SMUDriver:
    """Small synchronous driver API. Serialization is owned by SMUControlManager."""

    driver_name = "Generic SCPI"

    def __init__(self, resource: Any, device: SMUDevice) -> None:
        self.resource = resource
        self.device = device

    def configure_voltage_source(self, volts: float, current_compliance_a: float) -> None:
        raise NotImplementedError

    def configure_current_source(self, amps: float, voltage_compliance_v: float) -> None:
        raise NotImplementedError

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

    def query_output_enabled(self) -> bool | None:
        try:
            response = str(self.resource.query(":OUTP?")).strip().upper()
        except Exception:
            return None
        if response in {"1", "ON"}:
            return True
        if response in {"0", "OFF"}:
            return False
        return None

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

    def supports_measurement_nplc(self, mode: str) -> bool:
        del mode
        return False

    def get_measurement_nplc(self, mode: str) -> float | None:
        del mode
        return None

    def set_measurement_nplc(self, mode: str, nplc: float) -> None:
        del mode, nplc
        raise NotImplementedError("This SMU driver does not support measurement NPLC")

    def get_measurement_nplc_auto(self, mode: str) -> bool | None:
        del mode
        return None

    def supports_measurement_nplc_auto(self, mode: str) -> bool:
        del mode
        return False

    def set_measurement_nplc_auto(self, mode: str, enabled: bool) -> None:
        del mode, enabled
        raise NotImplementedError("This SMU driver does not support automatic measurement NPLC")

    @contextmanager
    def temporary_measurement_nplc(self, mode: str, nplc: float):
        """Apply integration only when supported, restoring the prior value."""

        if not self.supports_measurement_nplc(mode):
            yield False
            return
        previous = self.get_measurement_nplc(mode)
        if previous is None:
            raise RuntimeError("Cannot safely change NPLC because its current value is unavailable")
        previous_auto: bool | None = None
        if self.supports_measurement_nplc_auto(mode):
            previous_auto = self.get_measurement_nplc_auto(mode)
            if previous_auto is None:
                raise RuntimeError(
                    "Cannot safely change NPLC because its automatic-mode state is unavailable"
                )
        try:
            if previous_auto is not None:
                self.set_measurement_nplc_auto(mode, False)
            self.set_measurement_nplc(mode, nplc)
            yield True
        finally:
            try:
                self.set_measurement_nplc(mode, previous)
            finally:
                if previous_auto is not None:
                    self.set_measurement_nplc_auto(mode, previous_auto)

    def safe_stop(self) -> list[str]:
        """Best effort OUTPUT OFF with explicit confirmation.

        Source level is intentionally left untouched here because the generic
        driver cannot know which source parameter is active. Hardware-specific
        drivers may zero only their verified active source mode afterwards.
        """

        failures: list[str] = []
        try:
            self.resource.write(":OUTP OFF")
        except Exception as exc:  # noqa: BLE001 - collect every cleanup failure
            failures.append(f":OUTP OFF: {exc}")

        observed = self.query_output_enabled()
        if observed is not False:
            state = "UNKNOWN" if observed is None else "ON"
            failures.append(f":OUTP? did not confirm OFF (observed {state})")

        return failures

    def close(self, safe_stop: bool = True) -> None:
        if safe_stop:
            self.safe_stop()
        self.resource.close()
