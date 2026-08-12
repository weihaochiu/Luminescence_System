from __future__ import annotations

"""Central SMU ownership, coordinate mapping, safety, and serialized I/O."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import logging
from threading import Event, RLock
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from .smu_base import SMUDriver
from .polarity_measurement import (
    PolarityMeasurementError,
    PolarityMeasurementService,
)
from .polarity_settings import PolarityMeasurementSettings


LOG = logging.getLogger(__name__)


class SMUOwnership(str, Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    RECIPE = "RECIPE"
    EMERGENCY = "EMERGENCY"
    FAULT = "FAULT"


class SMUOperationState(str, Enum):
    READY = "READY"
    BUSY = "BUSY"
    OUTPUT_ON = "OUTPUT_ON"
    RECIPE_LOCKED = "RECIPE_LOCKED"
    EMERGENCY = "EMERGENCY"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    FAULT = "FAULT"


class PolarityState(str, Enum):
    UNKNOWN = "UNKNOWN"
    NORMAL = "NORMAL"
    REVERSED = "REVERSED"
    FAILED = "FAILED"


POLARITY_FACTORS: dict[PolarityState, int] = {
    PolarityState.NORMAL: 1,
    PolarityState.REVERSED: -1,
}


class SMUInterlockError(RuntimeError):
    pass


class _SMUEmergencyAbort(RuntimeError):
    """Internal marker for an operation cancelled by a safety latch."""


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
    """Confirmed mapping used only from Recipe device coordinates to the SMU."""

    def __init__(self, factor: int | None = None) -> None:
        self._factor: int | None = None
        if factor is not None:
            self.set_confirmed_factor(factor)

    @property
    def factor(self) -> int | None:
        return self._factor

    @property
    def is_confirmed(self) -> bool:
        return self._factor in (-1, 1)

    def set_confirmed_factor(self, factor: int) -> None:
        if factor not in (-1, 1):
            raise ValueError("Polarity factor must be +1 or -1")
        self._factor = int(factor)

    def to_physical(self, requested_value: float) -> float:
        if self._factor is None:
            raise SMUInterlockError(
                "尚未確認 Device-to-SMU Polarity，禁止 Recipe 輸出"
            )
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
                    "Current compliance must be > 0 and <= "
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
                    "Voltage compliance must be > 0 and <= "
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
    voltage_v: float | None
    current_a: float | None
    power_w: float | None
    output_enabled: bool | None
    compliance_tripped: bool | None


@dataclass(frozen=True)
class ManualPolarityResult:
    state: PolarityState
    factor: int | None
    jsc_current_a: float | None = None
    voc_v: float | None = None


class SMUControlManager(QObject):
    """Single hardware authority for ownership, output state, and safe shutdown."""

    ownership_changed = Signal(str)
    output_changed = Signal(bool)
    output_confirmation_changed = Signal(bool)
    busy_changed = Signal(bool)
    operation_state_changed = Signal(str)
    polarity_changed = Signal(object)
    manual_polarity_changed = Signal(object)
    manual_sequence_status = Signal(str)
    manual_sequence_finished = Signal(bool)
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
        self.polarity_measurement = PolarityMeasurementService()
        self.safety = safety or SMUSafetyService()
        self._driver: SMUDriver | None = None
        self._ownership = SMUOwnership.IDLE
        self._output_enabled = False
        self._output_confirmed_off = False
        self._last_shutdown_ok: bool | None = None
        self._fault_latched = False
        self._emergency_latch = Event()
        self._recipe_cancel_latch = Event()
        self._manual_cancel_latch = Event()
        self._manual_generation = 0
        self._manual_polarity = ManualPolarityResult(PolarityState.UNKNOWN, None)
        self._last_manual_polarity_snapshot: dict[str, Any] | None = None
        self._operation_state = SMUOperationState.READY
        self._mode = "CC"
        self._lock = RLock()
        self._io_lock = RLock()
        self._output_enable_lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smu-io")
        self._pending: set[Future[Any]] = set()

    @property
    def ownership(self) -> SMUOwnership:
        with self._lock:
            return self._ownership

    @property
    def output_enabled(self) -> bool:
        with self._lock:
            return self._output_enabled

    @property
    def output_confirmed_off(self) -> bool:
        with self._lock:
            return self._output_confirmed_off

    @property
    def last_shutdown_ok(self) -> bool | None:
        with self._lock:
            return self._last_shutdown_ok

    @property
    def emergency_latched(self) -> bool:
        return self._emergency_latch.is_set()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._driver is not None

    @property
    def manual_polarity(self) -> ManualPolarityResult:
        with self._lock:
            return self._manual_polarity

    @property
    def last_manual_polarity_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return (
                None
                if self._last_manual_polarity_snapshot is None
                else dict(self._last_manual_polarity_snapshot)
            )

    @property
    def operation_state(self) -> SMUOperationState:
        with self._lock:
            return self._operation_state

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def bind_driver(
        self,
        driver: SMUDriver | None,
        force: bool = False,
        output_confirmed_off: bool = False,
    ) -> None:
        with self._lock:
            if not force and (
                self._ownership is not SMUOwnership.IDLE
                or self._output_enabled
                or self._pending
                or (
                    driver is None
                    and self._driver is not None
                    and not self._output_confirmed_off
                )
            ):
                raise SMUInterlockError("Cannot replace SMU driver while output is owned")
            self._driver = driver
            self._output_enabled = False
            self._output_confirmed_off = bool(driver is not None and output_confirmed_off)
            self._last_shutdown_ok = True if self._output_confirmed_off else None
            self._fault_latched = False
            self._emergency_latch.clear()
            self._recipe_cancel_latch.clear()
            self._manual_cancel_latch.clear()
            self._manual_generation += 1
            self._manual_polarity = ManualPolarityResult(PolarityState.UNKNOWN, None)
            self._last_manual_polarity_snapshot = None
            self._ownership = SMUOwnership.IDLE
            self._operation_state = SMUOperationState.READY
        self.output_changed.emit(False)
        self.output_confirmation_changed.emit(self._output_confirmed_off)
        self.ownership_changed.emit(SMUOwnership.IDLE.value)
        self.operation_state_changed.emit(SMUOperationState.READY.value)
        self.manual_polarity_changed.emit(self._manual_polarity)

    def set_confirmed_polarity_factor(self, factor: int) -> None:
        with self._lock:
            if self._ownership is not SMUOwnership.IDLE:
                raise SMUInterlockError("Polarity cannot change while SMU is owned")
            self.polarity.set_confirmed_factor(factor)
        LOG.info("SMU_POLARITY confirmed factor=%+d", factor)
        self.polarity_changed.emit(factor)

    def acquire(self, owner: SMUOwnership) -> None:
        if owner not in (SMUOwnership.MANUAL, SMUOwnership.RECIPE):
            raise ValueError("Only MANUAL or RECIPE can acquire normal ownership")
        with self._lock:
            if self._driver is None:
                raise SMUInterlockError("No supported SMU is connected")
            self._ensure_normal_output_allowed_locked()
            if self._ownership is owner:
                return
            if self._ownership is not SMUOwnership.IDLE:
                raise SMUInterlockError(
                    f"SMU is owned by {self._ownership.value}; {owner.value} is blocked"
                )
            if self._output_enabled or not self._output_confirmed_off:
                raise SMUInterlockError("SMU OUTPUT OFF has not been confirmed")
            self._ownership = owner
            if owner is SMUOwnership.RECIPE:
                self._recipe_cancel_latch.clear()
                state = SMUOperationState.RECIPE_LOCKED
            else:
                state = SMUOperationState.READY
            state_changed = self._operation_state is not state
            self._operation_state = state
        LOG.info("SMU_OWNERSHIP %s acquired", owner.value)
        self.ownership_changed.emit(owner.value)
        if state_changed:
            self.operation_state_changed.emit(state.value)

    def release(self, owner: SMUOwnership) -> None:
        with self._lock:
            if self._ownership is not owner:
                return
            if self._output_enabled or not self._output_confirmed_off:
                raise SMUInterlockError(
                    "Cannot release SMU ownership before OUTPUT OFF is confirmed"
                )
            self._ownership = SMUOwnership.IDLE
            state_changed = self._operation_state is not SMUOperationState.READY
            self._operation_state = SMUOperationState.READY
        LOG.info("SMU_OWNERSHIP %s released", owner.value)
        self.ownership_changed.emit(SMUOwnership.IDLE.value)
        if state_changed:
            self.operation_state_changed.emit(SMUOperationState.READY.value)

    def request_manual_output(self, mode: str, requested: float, compliance: float) -> bool:
        """Apply Manual values directly in physical SMU coordinates."""

        self.safety.validate(mode, requested, compliance)
        with self._lock:
            if self._pending:
                return False
            if self._driver is None:
                raise SMUInterlockError("No supported SMU is connected")
            self._ensure_normal_output_allowed_locked()
            if self._ownership is not SMUOwnership.IDLE:
                raise SMUInterlockError(
                    f"SMU is owned by {self._ownership.value}; MANUAL is blocked"
                )
            if self._output_enabled or not self._output_confirmed_off:
                raise SMUInterlockError("SMU OUTPUT OFF has not been confirmed")
            self._ownership = SMUOwnership.MANUAL
            self._operation_state = SMUOperationState.BUSY
            accepted = self._submit(
                lambda: self._apply_output(
                    SMUOwnership.MANUAL,
                    mode,
                    requested,
                    requested,
                    compliance,
                    1,
                ),
                cleanup_owner=SMUOwnership.MANUAL,
                operation_state=SMUOperationState.BUSY,
            )
            if not accepted:
                self._ownership = SMUOwnership.IDLE
                self._operation_state = SMUOperationState.READY
                self.ownership_changed.emit(SMUOwnership.IDLE.value)
                self.operation_state_changed.emit(SMUOperationState.READY.value)
                return False
            self.operation_state_changed.emit(SMUOperationState.BUSY.value)
            self.ownership_changed.emit(SMUOwnership.MANUAL.value)

        LOG.info(
            "MANUAL_SMU PHYSICAL_REQUEST=%+.9g MODE=%s COMPLIANCE=%g",
            requested,
            mode,
            compliance,
        )
        return True

    def request_manual_output_sequence(
        self,
        mode: str,
        requested: float,
        compliance: float,
        area_cm2: float,
        light_on: Callable[[], None],
        light_off: Callable[[], None],
        settings: PolarityMeasurementSettings,
    ) -> bool:
        """Run a new illuminated polarity check before every Manual OUTPUT ON."""

        if area_cm2 <= 0.0:
            raise ValueError("Device area must be greater than 0 cm²")
        settings_errors = settings.validate()
        if settings_errors:
            raise ValueError("Polarity settings are invalid: " + "; ".join(settings_errors))
        polarity_current_compliance_a = (
            settings.jsc_compliance_ma_cm2 * area_cm2 / 1000.0
        )
        limits = self.safety.limits
        if polarity_current_compliance_a > limits.maximum_current_compliance_a:
            raise ValueError(
                "Polarity Jsc current compliance exceeds the SMU safety limit: "
                f"{polarity_current_compliance_a * 1000:g} mA > "
                f"{limits.maximum_current_compliance_a * 1000:g} mA"
            )
        if settings.voc_compliance_v > limits.maximum_voltage_compliance_v:
            raise ValueError(
                "Polarity Voc voltage compliance exceeds the SMU safety limit: "
                f"{settings.voc_compliance_v:g} V > "
                f"{limits.maximum_voltage_compliance_v:g} V"
            )
        self.safety.validate(mode, requested, compliance)
        with self._lock:
            if self._pending:
                return False
            if self._driver is None:
                raise SMUInterlockError("No supported SMU is connected")
            self._ensure_normal_output_allowed_locked()
            if self._ownership is not SMUOwnership.IDLE:
                raise SMUInterlockError(
                    f"SMU is owned by {self._ownership.value}; MANUAL is blocked"
                )
            if self._output_enabled or not self._output_confirmed_off:
                raise SMUInterlockError("SMU OUTPUT OFF has not been confirmed")
            self._manual_generation += 1
            generation = self._manual_generation
            self._manual_cancel_latch.clear()
            self._manual_polarity = ManualPolarityResult(PolarityState.UNKNOWN, None)
            self._last_manual_polarity_snapshot = None
            self._ownership = SMUOwnership.MANUAL
            self._operation_state = SMUOperationState.BUSY

        self.manual_polarity_changed.emit(self._manual_polarity)
        LOG.info(
            "MANUAL_SMU OUTPUT_ON_REQUEST area_cm2=%g mode=%s requested=%+.9g compliance=%g generation=%d",
            area_cm2,
            mode,
            requested,
            compliance,
            generation,
        )

        def operation() -> None:
            success = False
            try:
                with self._io_lock:
                    driver = self._required_driver()
                    measured = self.polarity_measurement.measure(
                        driver,
                        settings,
                        area_cm2,
                        light_on=light_on,
                        light_off=light_off,
                        check_cancel=lambda: self._check_manual_generation(generation),
                        wait_ms=lambda milliseconds: self._wait_for_manual_stabilization(
                            generation,
                            milliseconds / 1000.0,
                        ),
                        status=self.manual_sequence_status.emit,
                    )
                result = ManualPolarityResult(
                    state=PolarityState(measured.state),
                    factor=measured.factor,
                    jsc_current_a=measured.jsc_ma_cm2.representative * area_cm2 / 1000.0,
                    voc_v=measured.voc_v.representative,
                )
                with self._lock:
                    self._manual_polarity = result
                    self._last_manual_polarity_snapshot = measured.to_dict()
                self.manual_polarity_changed.emit(result)
                LOG.info(
                    "MANUAL_SMU POLARITY JSC_A=%+.9g JSC_MA_CM2=%+.9g VOC_V=%+.9g result=%s factor=%s snapshot=%s",
                    result.jsc_current_a,
                    measured.jsc_ma_cm2.representative,
                    result.voc_v,
                    result.state.value,
                    result.factor,
                    measured.to_dict(),
                )
                if result.factor is None:
                    raise SMUInterlockError(
                        "Jsc/Voc signs do not identify a safe output polarity"
                    )

                self._check_manual_generation(generation)
                physical = float(requested) * result.factor
                self.safety.validate(mode, physical, compliance)
                self.manual_sequence_status.emit("設定 SMU…")
                with self._io_lock:
                    driver = self._required_driver()
                    self._check_manual_generation(generation)
                    if mode == "CV":
                        driver.configure_voltage_source(physical, compliance)
                    else:
                        driver.configure_current_source(physical, compliance)
                    with self._output_enable_lock:
                        self._check_manual_generation(generation)
                        driver.set_output_enabled(True)
                        if driver.query_output_enabled() is not True:
                            raise SMUInterlockError("SMU OUTPUT ON could not be confirmed")
                        self._check_manual_generation(generation)

                with self._lock:
                    self._mode = mode
                    self._output_enabled = True
                    self._output_confirmed_off = False
                    self._last_shutdown_ok = None
                    self._operation_state = SMUOperationState.OUTPUT_ON
                self.output_changed.emit(True)
                self.output_confirmation_changed.emit(False)
                self.command_applied.emit(
                    mode,
                    requested,
                    physical,
                    compliance,
                    result.factor,
                )
                self.operation_state_changed.emit(SMUOperationState.OUTPUT_ON.value)
                self.manual_sequence_status.emit("SMU OUTPUT ON")
                LOG.info(
                    "MANUAL_SMU OUTPUT_ON mode=%s requested=%+.9g physical=%+.9g compliance=%g factor=%+d",
                    mode,
                    requested,
                    physical,
                    compliance,
                    result.factor,
                )
                success = True
            except _SMUEmergencyAbort:
                LOG.warning(
                    "MANUAL_SMU OUTPUT_ON_CANCELLED generation=%d",
                    generation,
                )
                raise
            except Exception as exc:
                with self._lock:
                    self._manual_polarity = ManualPolarityResult(
                        PolarityState.FAILED,
                        None,
                    )
                    failed_result = self._manual_polarity
                    if self._last_manual_polarity_snapshot is None:
                        self._last_manual_polarity_snapshot = {
                            "settings_snapshot": settings.snapshot(),
                            "polarity_result": PolarityState.FAILED.value,
                            "polarity_factor": None,
                            "failure_reason": str(exc),
                            "partial_results": (
                                exc.details
                                if isinstance(exc, PolarityMeasurementError)
                                else {}
                            ),
                        }
                self.manual_polarity_changed.emit(failed_result)
                LOG.exception("MANUAL_SMU OUTPUT_ON_ABORT generation=%d", generation)
                raise
            finally:
                self.manual_sequence_finished.emit(success)

        accepted = self._submit(
            operation,
            cleanup_owner=SMUOwnership.MANUAL,
            operation_state=SMUOperationState.BUSY,
        )
        if not accepted:
            with self._lock:
                self._ownership = SMUOwnership.IDLE
                self._operation_state = SMUOperationState.READY
            return False
        self.operation_state_changed.emit(SMUOperationState.BUSY.value)
        self.ownership_changed.emit(SMUOwnership.MANUAL.value)
        return True

    def request_manual_off(self) -> bool:
        with self._lock:
            if self._ownership is not SMUOwnership.MANUAL or self._pending:
                return False
            self._manual_generation += 1
            self._manual_cancel_latch.set()
        return self._submit(
            lambda: self.safe_shutdown(
                SMUOwnership.MANUAL,
                reason="manual off",
            ),
            operation_state=SMUOperationState.SHUTTING_DOWN,
        )

    def request_safe_output_off(self, reason: str = "safe recovery") -> bool:
        """Recover OFF from IDLE/inconsistent states without stealing Recipe ownership."""

        with self._lock:
            if self._driver is None:
                self.error_occurred.emit("SMU is not connected")
                return False
            if self._ownership is SMUOwnership.RECIPE:
                self.error_occurred.emit(
                    "Recipe owns the SMU; use the Recipe-to-Manual handover"
                )
                return False
            owner = self._ownership
            shutdown_owner = (
                SMUOwnership.EMERGENCY
                if self._emergency_latch.is_set()
                else owner
            )
        LOG.warning("SMU_RECOVERY_OFF requested owner=%s reason=%s", owner.value, reason)
        return self._submit(
            lambda: self.safe_shutdown(shutdown_owner, reason=reason),
            allow_busy=True,
            operation_state=SMUOperationState.SHUTTING_DOWN,
        )

    def acquire_recipe(self) -> None:
        self.acquire(SMUOwnership.RECIPE)

    def prepare_recipe_start(self, close_manual: bool = False) -> None:
        """Perform MANUAL -> confirmed OFF/IDLE -> RECIPE."""

        if self.ownership is SMUOwnership.MANUAL:
            if not close_manual:
                raise SMUInterlockError("Manual SMU ownership must be safely closed first")
            LOG.info("SMU_HANDOVER MANUAL -> RECIPE: confirming OUTPUT OFF")
            if not self.safe_shutdown(
                SMUOwnership.MANUAL,
                reason="manual to recipe handover",
            ):
                raise SMUInterlockError("Manual SMU output could not be safely disabled")
        self.acquire_recipe()
        LOG.info("SMU_HANDOVER -> RECIPE complete")

    def request_recipe_handover_to_manual(self) -> bool:
        """Block Recipe output and queue confirmed shutdown at the next I/O safe point."""

        with self._lock:
            if self._ownership is not SMUOwnership.RECIPE:
                self.error_occurred.emit("Recipe does not own the SMU")
                return False
            if self._pending:
                return False
            self._recipe_cancel_latch.set()
        LOG.info("SMU_HANDOVER RECIPE -> MANUAL requested; Recipe output blocked")
        accepted = self._submit(
            lambda: self.safe_shutdown(
                SMUOwnership.RECIPE,
                reason="recipe to manual handover",
            ),
            allow_busy=True,
            operation_state=SMUOperationState.SHUTTING_DOWN,
        )
        if not accepted:
            self._recipe_cancel_latch.clear()
        return accepted

    def recipe_output(self, mode: str, requested: float, compliance: float) -> float:
        """Apply Recipe values after device-coordinate polarity conversion."""

        self.safety.validate(mode, requested, compliance)
        with self._lock:
            if self._ownership is not SMUOwnership.RECIPE:
                raise SMUInterlockError("Recipe does not own the SMU")
            self._ensure_normal_output_allowed_locked()
            if self._recipe_cancel_latch.is_set():
                raise SMUInterlockError("Recipe output is blocked by a handover request")
            physical = self.polarity.to_physical(requested)
        with self._io_lock:
            driver = self._required_driver()
            self._raise_if_output_blocked()
            if mode == "CV":
                driver.configure_voltage_source(physical, compliance)
            else:
                driver.configure_current_source(physical, compliance)
            with self._output_enable_lock:
                self._raise_if_output_blocked()
                driver.set_output_enabled(True)
        with self._lock:
            self._mode = mode
            self._output_enabled = True
            self._output_confirmed_off = False
            self._last_shutdown_ok = None
            aborted = (
                self._ownership is not SMUOwnership.RECIPE
                or self._emergency_latch.is_set()
                or self._recipe_cancel_latch.is_set()
            )
            if not aborted:
                self._operation_state = SMUOperationState.OUTPUT_ON
        self.output_changed.emit(True)
        self.output_confirmation_changed.emit(False)
        if aborted:
            raise _SMUEmergencyAbort(
                "Recipe output ownership changed immediately after OUTPUT ON"
            )
        self.operation_state_changed.emit(SMUOperationState.OUTPUT_ON.value)
        LOG.info(
            "RECIPE_SMU DEVICE_REQUEST=%+.9g POLARITY_FACTOR=%+d PHYSICAL=%+.9g",
            requested,
            self.polarity.factor,
            physical,
        )
        return physical

    def safe_shutdown(
        self,
        owner: SMUOwnership | None = None,
        *,
        reason: str = "safe shutdown",
    ) -> bool:
        """Turn OUTPUT OFF, explicitly confirm it, then release ownership."""

        with self._lock:
            if owner is not None and self._ownership not in (
                owner,
                SMUOwnership.EMERGENCY,
                SMUOwnership.FAULT,
            ):
                return False
            driver = self._driver
            previous = self._ownership

        failures: list[str] = []
        with self._io_lock:
            if driver is None:
                failures.append("SMU driver is not available")
            else:
                try:
                    failures.extend(driver.safe_stop())
                except Exception as exc:  # noqa: BLE001 - fail closed
                    failures.append(str(exc))
                try:
                    observed_output = driver.query_output_enabled()
                except Exception as exc:  # noqa: BLE001 - fail closed
                    observed_output = None
                    failures.append(f"OUTPUT OFF confirmation failed: {exc}")
                if observed_output is not False:
                    observed = "UNKNOWN" if observed_output is None else "ON"
                    failures.append(f"OUTPUT OFF not confirmed (observed {observed})")

        with self._lock:
            if failures:
                self._output_confirmed_off = False
                self._last_shutdown_ok = False
                self._fault_latched = True
                self._ownership = SMUOwnership.FAULT
                self._operation_state = SMUOperationState.FAULT
            else:
                self._output_enabled = False
                self._output_confirmed_off = True
                self._last_shutdown_ok = True
                self._fault_latched = False
                if self._emergency_latch.is_set() and owner is not SMUOwnership.EMERGENCY:
                    self._ownership = SMUOwnership.EMERGENCY
                    self._operation_state = SMUOperationState.EMERGENCY
                else:
                    self._ownership = SMUOwnership.IDLE
                    self._operation_state = SMUOperationState.READY
                    if owner is SMUOwnership.EMERGENCY:
                        self._emergency_latch.clear()
                        self._recipe_cancel_latch.clear()
                    elif owner is SMUOwnership.RECIPE:
                        self._recipe_cancel_latch.clear()
                if (
                    previous is SMUOwnership.EMERGENCY
                    or (
                        previous is SMUOwnership.MANUAL
                        and self._manual_polarity.state is not PolarityState.FAILED
                    )
                ):
                    self._manual_polarity = ManualPolarityResult(
                        PolarityState.UNKNOWN,
                        None,
                    )
            ownership = self._ownership
            state = self._operation_state

        if failures:
            message = "; ".join(failures)
            LOG.error("SMU_FAULT shutdown failed reason=%s: %s", reason, message)
            self.output_confirmation_changed.emit(False)
            self.ownership_changed.emit(SMUOwnership.FAULT.value)
            self.operation_state_changed.emit(SMUOperationState.FAULT.value)
            self.error_occurred.emit("SMU safety stop incomplete: " + message)
            return False

        LOG.info(
            "SMU_SAFE_SHUTDOWN OUTPUT OFF confirmed reason=%s previous_owner=%s",
            reason,
            previous.value,
        )
        self.output_changed.emit(False)
        self.output_confirmation_changed.emit(True)
        self.ownership_changed.emit(ownership.value)
        self.operation_state_changed.emit(state.value)
        if previous in (SMUOwnership.MANUAL, SMUOwnership.EMERGENCY):
            self.manual_polarity_changed.emit(self._manual_polarity)
        return True

    def request_emergency_off(self) -> bool:
        """Latch immediately; shutdown is serialized behind active VISA I/O."""

        with self._lock:
            if (
                self._emergency_latch.is_set()
                and self._ownership is SMUOwnership.EMERGENCY
            ):
                return True
        self._emergency_latch.set()
        self._recipe_cancel_latch.set()
        self._manual_cancel_latch.set()
        with self._lock:
            self._manual_generation += 1
            if self._driver is None:
                LOG.info("SMU_EMERGENCY safe: no SMU is connected")
                self._emergency_latch.clear()
                self._recipe_cancel_latch.clear()
                return True
            self._ownership = SMUOwnership.EMERGENCY
            self._operation_state = SMUOperationState.EMERGENCY
        LOG.critical(
            "SMU_EMERGENCY latched; output blocked; OFF queued behind active VISA I/O"
        )
        self.ownership_changed.emit(SMUOwnership.EMERGENCY.value)
        self.operation_state_changed.emit(SMUOperationState.EMERGENCY.value)
        return self._submit(
            lambda: self.safe_shutdown(
                SMUOwnership.EMERGENCY,
                reason="emergency off",
            ),
            allow_busy=True,
            operation_state=SMUOperationState.EMERGENCY,
        )

    def request_readback(self) -> bool:
        with self._lock:
            if (
                self._driver is None
                or self._ownership not in (SMUOwnership.IDLE, SMUOwnership.MANUAL)
                or self._emergency_latch.is_set()
                or self._pending
            ):
                return False

        def operation() -> None:
            with self._io_lock:
                driver = self._required_driver()
                output_enabled = driver.query_output_enabled()
                with self._lock:
                    ownership = self._ownership
                    operation_state = self._operation_state
                    mode = self._mode
                measure_enabled_output = (
                    output_enabled is True
                    and ownership is SMUOwnership.MANUAL
                    and operation_state is SMUOperationState.OUTPUT_ON
                )
                if measure_enabled_output:
                    voltage = driver.measure_voltage()
                    current = driver.measure_current()
                    power = voltage * current
                    compliance_tripped = driver.query_compliance_tripped(mode)
                    if compliance_tripped:
                        LOG.warning("MANUAL_SMU COMPLIANCE_ACTIVE mode=%s", mode)
                    LOG.debug(
                        "SMU_READBACK output=ON owner=MANUAL mode=MEASURE"
                    )
                else:
                    voltage = None
                    current = None
                    power = None
                    compliance_tripped = None
                    if output_enabled is False:
                        LOG.debug("SMU_READBACK output=OFF mode=OUTPUT_ONLY")
                    elif output_enabled is True:
                        LOG.warning(
                            "SMU_UNEXPECTED_OUTPUT_ON detected during readback "
                            "owner=%s operation=%s",
                            ownership.value,
                            operation_state.value,
                        )
                    else:
                        LOG.debug("SMU_READBACK output=UNKNOWN mode=OUTPUT_ONLY")
                reading = SMUReadback(
                    voltage_v=voltage,
                    current_a=current,
                    power_w=power,
                    output_enabled=output_enabled,
                    compliance_tripped=compliance_tripped,
                )
            with self._lock:
                if reading.output_enabled is not None:
                    self._output_enabled = reading.output_enabled
                    if reading.output_enabled:
                        self._last_shutdown_ok = None
                self._output_confirmed_off = reading.output_enabled is False
            if reading.output_enabled is not None:
                self.output_changed.emit(reading.output_enabled)
            self.output_confirmation_changed.emit(reading.output_enabled is False)
            self.readback_ready.emit(reading)

        return self._submit(operation, report_errors=False)

    def confirm_output_enabled(self) -> bool | None:
        """Serialized front-panel confirmation used before disconnecting."""

        with self._io_lock:
            enabled = self._required_driver().query_output_enabled()
        with self._lock:
            if enabled is not None:
                self._output_enabled = enabled
                if enabled:
                    self._last_shutdown_ok = None
            self._output_confirmed_off = enabled is False
        if enabled is not None:
            self.output_changed.emit(enabled)
        self.output_confirmation_changed.emit(enabled is False)
        return enabled

    def shutdown(self) -> None:
        if self._driver is not None:
            self.safe_shutdown(reason="control shutdown")
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _required_driver(self) -> SMUDriver:
        if self._driver is None:
            raise SMUInterlockError("No supported SMU is connected")
        return self._driver

    def _ensure_normal_output_allowed_locked(self) -> None:
        if self._emergency_latch.is_set():
            raise SMUInterlockError("SMU Emergency OFF is latched; output is blocked")
        if self._fault_latched or self._ownership is SMUOwnership.FAULT:
            raise SMUInterlockError(
                "Previous SMU safety stop failed; run Emergency OFF or safe recovery"
            )

    def _raise_if_output_blocked(self) -> None:
        if self._emergency_latch.is_set():
            raise _SMUEmergencyAbort("SMU output cancelled by Emergency OFF")
        if self._recipe_cancel_latch.is_set():
            raise _SMUEmergencyAbort("SMU output cancelled by Recipe handover")

    def _check_manual_generation(self, generation: int) -> None:
        with self._lock:
            current_generation = self._manual_generation
            owner = self._ownership
        if (
            generation != current_generation
            or owner is not SMUOwnership.MANUAL
            or self._manual_cancel_latch.is_set()
            or self._emergency_latch.is_set()
        ):
            raise _SMUEmergencyAbort("Manual SMU sequence was cancelled")

    def _wait_for_manual_stabilization(self, generation: int, seconds: float) -> None:
        deadline = monotonic() + seconds
        while True:
            self._check_manual_generation(generation)
            remaining = deadline - monotonic()
            if remaining <= 0.0:
                return
            self._manual_cancel_latch.wait(min(0.05, remaining))

    def _measure_with_temporary_output(
        self,
        driver: SMUDriver,
        generation: int,
        measure: Callable[[], float],
    ) -> float:
        output_enabled = False
        try:
            with self._output_enable_lock:
                self._check_manual_generation(generation)
                driver.set_output_enabled(True)
                if driver.query_output_enabled() is not True:
                    raise SMUInterlockError("SMU measurement OUTPUT ON could not be confirmed")
                output_enabled = True
            self._check_manual_generation(generation)
            value = float(measure())
            self._check_manual_generation(generation)
            return value
        finally:
            if output_enabled:
                driver.set_output_enabled(False)
                if driver.query_output_enabled() is not False:
                    raise SMUInterlockError("SMU measurement OUTPUT OFF could not be confirmed")

    def _apply_output(
        self,
        owner: SMUOwnership,
        mode: str,
        requested: float,
        physical: float,
        compliance: float,
        factor: int,
    ) -> None:
        with self._io_lock:
            driver = self._required_driver()
            self._raise_if_output_blocked()
            if mode == "CV":
                driver.configure_voltage_source(physical, compliance)
            else:
                driver.configure_current_source(physical, compliance)
            with self._output_enable_lock:
                self._raise_if_output_blocked()
                driver.set_output_enabled(True)
                if driver.query_output_enabled() is not True:
                    raise SMUInterlockError("SMU OUTPUT ON could not be confirmed")
        with self._lock:
            self._mode = mode
            self._output_enabled = True
            self._output_confirmed_off = False
            self._last_shutdown_ok = None
            aborted = (
                self._ownership is not owner
                or self._emergency_latch.is_set()
                or self._recipe_cancel_latch.is_set()
            )
            if not aborted:
                self._operation_state = SMUOperationState.OUTPUT_ON
        self.output_changed.emit(True)
        self.output_confirmation_changed.emit(False)
        if aborted:
            raise _SMUEmergencyAbort("SMU ownership changed immediately after OUTPUT ON")
        LOG.info("%s_SMU OUTPUT=ON", owner.value)
        self.command_applied.emit(mode, requested, physical, compliance, factor)
        self.operation_state_changed.emit(SMUOperationState.OUTPUT_ON.value)

    def _submit(
        self,
        operation: Callable[[], None],
        cleanup_owner: SMUOwnership | None = None,
        report_errors: bool = True,
        allow_busy: bool = False,
        operation_state: SMUOperationState | None = None,
    ) -> bool:
        start_gate = Event()

        def gated_operation() -> None:
            start_gate.wait()
            operation()

        with self._lock:
            if not allow_busy and self._pending:
                return False
            was_busy = bool(self._pending)
            future = self._executor.submit(gated_operation)
            self._pending.add(future)
            state_changed = (
                operation_state is not None and self._operation_state is not operation_state
            )
            if operation_state is not None:
                self._operation_state = operation_state

        def done(completed: Future[Any]) -> None:
            try:
                completed.result()
            except Exception as exc:  # noqa: BLE001 - report async hardware failure
                if isinstance(exc, _SMUEmergencyAbort):
                    LOG.warning("%s", exc)
                else:
                    LOG.exception("SMU operation failed")
                if cleanup_owner is not None:
                    self.safe_shutdown(cleanup_owner, reason="failed output operation")
                if report_errors and not isinstance(exc, _SMUEmergencyAbort):
                    self.error_occurred.emit(str(exc))
            finally:
                with self._lock:
                    self._pending.discard(completed)
                    now_busy = bool(self._pending)
                if not now_busy:
                    self.busy_changed.emit(False)

        future.add_done_callback(done)
        if not was_busy:
            self.busy_changed.emit(True)
        if state_changed and operation_state is not None:
            self.operation_state_changed.emit(operation_state.value)
        start_gate.set()
        return True
