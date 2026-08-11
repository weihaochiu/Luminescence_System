from __future__ import annotations

"""Central SMU ownership, polarity translation, safety, and serialized I/O."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import logging
from threading import RLock
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from .smu_base import SMUDriver


LOG = logging.getLogger(__name__)


class SMUOwnership(str, Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    RECIPE = "RECIPE"
    EMERGENCY = "EMERGENCY"


class SMUInterlockError(RuntimeError):
    pass


@dataclass(frozen=True)
class SMUSafetyLimits:
    minimum_voltage_v: float = -5.0
    maximum_voltage_v: float = 5.0
    minimum_current_a: float = -0.050
    maximum_current_a: float = 0.050
    maximum_power_w: float = 0.150
    maximum_voltage_compliance_v: float = 5.0
    maximum_current_compliance_a: float = 0.050


class PolarityService:
    """Authoritative confirmed mapping from device to physical coordinates."""

    def __init__(self, factor: int = 1) -> None:
        self._factor = 1
        self.set_confirmed_factor(factor)

    @property
    def factor(self) -> int:
        return self._factor

    def set_confirmed_factor(self, factor: int) -> None:
        if factor not in (-1, 1):
            raise ValueError("Polarity factor must be +1 or -1")
        # Assignment is deliberately idempotent. Determination must never toggle it.
        self._factor = int(factor)

    def to_physical(self, requested_value: float) -> float:
        return float(requested_value) * self._factor


class SMUSafetyService:
    def __init__(self, limits: SMUSafetyLimits | None = None) -> None:
        self.limits = limits or SMUSafetyLimits()

    def validate(self, mode: str, requested: float, compliance: float) -> None:
        limits = self.limits
        if mode == "CV":
            if not limits.minimum_voltage_v <= requested <= limits.maximum_voltage_v:
                raise ValueError(
                    f"Voltage setpoint {requested:g} V exceeds safety range "
                    f"{limits.minimum_voltage_v:g} to {limits.maximum_voltage_v:g} V"
                )
            if not 0 < compliance <= limits.maximum_current_compliance_a:
                raise ValueError(
                    f"Current compliance must be > 0 and <= "
                    f"{limits.maximum_current_compliance_a * 1000:g} mA"
                )
            estimated_power = abs(requested * compliance)
        elif mode == "CC":
            if not limits.minimum_current_a <= requested <= limits.maximum_current_a:
                raise ValueError(
                    f"Current setpoint {requested * 1000:g} mA exceeds safety range "
                    f"{limits.minimum_current_a * 1000:g} to "
                    f"{limits.maximum_current_a * 1000:g} mA"
                )
            if not 0 < compliance <= limits.maximum_voltage_compliance_v:
                raise ValueError(
                    f"Voltage compliance must be > 0 and <= "
                    f"{limits.maximum_voltage_compliance_v:g} V"
                )
            estimated_power = abs(requested * compliance)
        else:
            raise ValueError("SMU mode must be CV or CC")
        if estimated_power > limits.maximum_power_w:
            raise ValueError(
                f"Setpoint × compliance ({estimated_power * 1000:g} mW) exceeds "
                f"the {limits.maximum_power_w * 1000:g} mW safety limit"
            )


@dataclass(frozen=True)
class SMUReadback:
    voltage_v: float
    current_a: float
    power_w: float
    output_enabled: bool | None
    compliance_tripped: bool | None


class SMUControlManager(QObject):
    """Single source of truth for ownership/output and the only output command route."""

    ownership_changed = Signal(str)
    output_changed = Signal(bool)
    command_applied = Signal(str, float, float, float, int)
    readback_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(
        self,
        polarity: PolarityService | None = None,
        safety: SMUSafetyService | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.polarity = polarity or PolarityService()
        self.safety = safety or SMUSafetyService()
        self._driver: SMUDriver | None = None
        self._ownership = SMUOwnership.IDLE
        self._output_enabled = False
        self._mode = "CC"
        self._lock = RLock()
        self._io_lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smu-io")
        self._pending: Future[Any] | None = None

    @property
    def ownership(self) -> SMUOwnership:
        with self._lock:
            return self._ownership

    @property
    def output_enabled(self) -> bool:
        with self._lock:
            return self._output_enabled

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._pending is not None and not self._pending.done()

    def bind_driver(self, driver: SMUDriver | None) -> None:
        with self._lock:
            if self._ownership is not SMUOwnership.IDLE or self._output_enabled:
                raise SMUInterlockError("Cannot replace SMU driver while output is owned")
            self._driver = driver

    def set_confirmed_polarity_factor(self, factor: int) -> None:
        with self._lock:
            if self._ownership is not SMUOwnership.IDLE:
                raise SMUInterlockError("Polarity cannot change while SMU is owned")
            self.polarity.set_confirmed_factor(factor)
        LOG.info("SMU polarity factor confirmed: %d", factor)

    def acquire(self, owner: SMUOwnership) -> None:
        if owner not in (SMUOwnership.MANUAL, SMUOwnership.RECIPE):
            raise ValueError("Only MANUAL or RECIPE can acquire normal ownership")
        with self._lock:
            if self._driver is None:
                raise SMUInterlockError("No supported SMU is connected")
            if self._ownership is owner:
                return
            if self._ownership is not SMUOwnership.IDLE:
                raise SMUInterlockError(
                    f"SMU is owned by {self._ownership.value}; {owner.value} is blocked"
                )
            self._ownership = owner
        LOG.info("%s SMU ownership acquired", owner.value)
        self.ownership_changed.emit(owner.value)

    def release(self, owner: SMUOwnership) -> None:
        with self._lock:
            if self._ownership is not owner:
                return
            if self._output_enabled:
                raise SMUInterlockError("Cannot release SMU ownership while output is ON")
            self._ownership = SMUOwnership.IDLE
        LOG.info("%s SMU ownership released", owner.value)
        self.ownership_changed.emit(SMUOwnership.IDLE.value)

    def request_manual_output(self, mode: str, requested: float, compliance: float) -> bool:
        self.safety.validate(mode, requested, compliance)
        self.acquire(SMUOwnership.MANUAL)
        physical = self.polarity.to_physical(requested)
        LOG.info("MANUAL_SMU MODE=%s", mode)
        LOG.info("MANUAL_SMU REQUEST=%+.9g POLARITY_FACTOR=%+d ACTUAL=%+.9g COMPLIANCE=%g",
                 requested, self.polarity.factor, physical, compliance)

        def operation() -> None:
            with self._io_lock:
                driver = self._required_driver()
                if mode == "CV":
                    driver.configure_voltage_source(physical, compliance)
                else:
                    driver.configure_current_source(physical, compliance)
                driver.set_output_enabled(True)
            with self._lock:
                self._mode = mode
                self._output_enabled = True
            LOG.info("MANUAL_SMU OUTPUT=ON")
            self.command_applied.emit(mode, requested, physical, compliance, self.polarity.factor)
            self.output_changed.emit(True)

        return self._submit(operation, cleanup_owner=SMUOwnership.MANUAL)

    def request_manual_off(self) -> bool:
        if self.ownership is not SMUOwnership.MANUAL:
            return False
        return self._submit(lambda: self.safe_shutdown(SMUOwnership.MANUAL))

    def acquire_recipe(self) -> None:
        self.acquire(SMUOwnership.RECIPE)

    def prepare_recipe_start(self, close_manual: bool = False) -> None:
        """Perform the only permitted MANUAL -> OFF/IDLE -> RECIPE transition."""
        if self.ownership is SMUOwnership.MANUAL:
            if not close_manual:
                raise SMUInterlockError("Manual SMU ownership must be safely closed first")
            if not self.safe_shutdown(SMUOwnership.MANUAL):
                raise SMUInterlockError("Manual SMU output could not be safely disabled")
        self.acquire_recipe()

    def recipe_output(self, mode: str, requested: float, compliance: float) -> float:
        """Synchronous atomic command for a Recipe worker thread."""
        if self.ownership is not SMUOwnership.RECIPE:
            raise SMUInterlockError("Recipe does not own the SMU")
        self.safety.validate(mode, requested, compliance)
        physical = self.polarity.to_physical(requested)
        with self._io_lock:
            driver = self._required_driver()
            if mode == "CV":
                driver.configure_voltage_source(physical, compliance)
            else:
                driver.configure_current_source(physical, compliance)
            driver.set_output_enabled(True)
        with self._lock:
            self._mode = mode
            self._output_enabled = True
        self.output_changed.emit(True)
        return physical

    def safe_shutdown(self, owner: SMUOwnership | None = None) -> bool:
        """Zero both source functions, OUTPUT OFF, then release ownership."""
        with self._lock:
            if owner is not None and self._ownership not in (owner, SMUOwnership.EMERGENCY):
                return False
            driver = self._driver
        with self._io_lock:
            failures = driver.safe_stop() if driver is not None else []
        with self._lock:
            self._output_enabled = False
            previous = self._ownership
            self._ownership = SMUOwnership.IDLE
        LOG.info("%s SMU source=0 OUTPUT=OFF ownership released", previous.value)
        self.output_changed.emit(False)
        self.ownership_changed.emit(SMUOwnership.IDLE.value)
        if failures:
            self.error_occurred.emit("SMU safety stop incomplete: " + "; ".join(failures))
            return False
        return True

    def request_emergency_off(self) -> bool:
        with self._lock:
            self._ownership = SMUOwnership.EMERGENCY
        LOG.critical("SMU EMERGENCY OFF requested")
        self.ownership_changed.emit(SMUOwnership.EMERGENCY.value)
        return self._submit(lambda: self.safe_shutdown(SMUOwnership.EMERGENCY), allow_busy=True)

    def request_readback(self) -> bool:
        if self.ownership is SMUOwnership.RECIPE or self.is_busy:
            return False

        def operation() -> None:
            with self._io_lock:
                driver = self._required_driver()
                voltage = driver.measure_voltage()
                current = driver.measure_current()
                reading = SMUReadback(
                    voltage_v=voltage,
                    current_a=current,
                    power_w=voltage * current,
                    output_enabled=driver.query_output_enabled(),
                    compliance_tripped=driver.query_compliance_tripped(self._mode),
                )
            self.readback_ready.emit(reading)

        return self._submit(operation, report_errors=False)

    def confirm_output_enabled(self) -> bool | None:
        """Serialized front-panel confirmation used before disconnecting."""
        with self._io_lock:
            enabled = self._required_driver().query_output_enabled()
        if enabled is not None:
            with self._lock:
                self._output_enabled = enabled
            self.output_changed.emit(enabled)
        return enabled

    def shutdown(self) -> None:
        self.safe_shutdown()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _required_driver(self) -> SMUDriver:
        if self._driver is None:
            raise SMUInterlockError("No supported SMU is connected")
        return self._driver

    def _submit(
        self,
        operation: Callable[[], None],
        cleanup_owner: SMUOwnership | None = None,
        report_errors: bool = True,
        allow_busy: bool = False,
    ) -> bool:
        with self._lock:
            if not allow_busy and self._pending is not None and not self._pending.done():
                if cleanup_owner is not None and self._ownership is cleanup_owner:
                    self._ownership = SMUOwnership.IDLE
                    self.ownership_changed.emit(SMUOwnership.IDLE.value)
                return False
            future = self._executor.submit(operation)
            self._pending = future

        def done(completed: Future[Any]) -> None:
            try:
                completed.result()
            except Exception as exc:
                LOG.exception("SMU operation failed")
                if cleanup_owner is not None:
                    self.safe_shutdown(cleanup_owner)
                if report_errors:
                    self.error_occurred.emit(str(exc))
            finally:
                with self._lock:
                    if self._pending is completed:
                        self._pending = None

        future.add_done_callback(done)
        return True
