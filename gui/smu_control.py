from __future__ import annotations

"""Central SMU ownership, polarity translation, safety, and serialized I/O."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import logging
from threading import Event, RLock
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from .smu_base import SMUDriver


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


class SMUInterlockError(RuntimeError):
    pass


class _SMUEmergencyAbort(RuntimeError):
    """Internal marker for a normal operation cancelled by the emergency latch."""


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
        # Assignment is deliberately idempotent. Determination must never toggle it.
        self._factor = int(factor)

    def to_physical(self, requested_value: float) -> float:
        if self._factor is None:
            raise SMUInterlockError(
                "尚未確認元件極性，無法使用 Device-coordinate SMU 輸出。"
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
    busy_changed = Signal(bool)
    operation_state_changed = Signal(str)
    polarity_changed = Signal(object)
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
        self._output_confirmed_off = False
        self._last_shutdown_ok: bool | None = None
        self._fault_latched = False
        self._emergency_latch = Event()
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
    def operation_state(self) -> SMUOperationState:
        with self._lock:
            return self._operation_state

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def bind_driver(self, driver: SMUDriver | None, force: bool = False) -> None:
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
            self._output_confirmed_off = False
            self._last_shutdown_ok = None
            self._fault_latched = False
            self._emergency_latch.clear()
            self._ownership = SMUOwnership.IDLE
            self._operation_state = SMUOperationState.READY

    def set_confirmed_polarity_factor(self, factor: int) -> None:
        with self._lock:
            if self._ownership is not SMUOwnership.IDLE:
                raise SMUInterlockError("Polarity cannot change while SMU is owned")
            self.polarity.set_confirmed_factor(factor)
        LOG.info("SMU polarity factor confirmed: %d", factor)
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
            self._ownership = owner
            state = (
                SMUOperationState.RECIPE_LOCKED
                if owner is SMUOwnership.RECIPE
                else SMUOperationState.READY
            )
            state_changed = self._operation_state is not state
            self._operation_state = state
        LOG.info("%s SMU ownership acquired", owner.value)
        self.ownership_changed.emit(owner.value)
        if state_changed:
            self.operation_state_changed.emit(state.value)

    def release(self, owner: SMUOwnership) -> None:
        with self._lock:
            if self._ownership is not owner:
                return
            if self._output_enabled:
                raise SMUInterlockError("Cannot release SMU ownership while output is ON")
            self._ownership = SMUOwnership.IDLE
            state_changed = self._operation_state is not SMUOperationState.READY
            self._operation_state = SMUOperationState.READY
        LOG.info("%s SMU ownership released", owner.value)
        self.ownership_changed.emit(SMUOwnership.IDLE.value)
        if state_changed:
            self.operation_state_changed.emit(SMUOperationState.READY.value)

    def request_manual_output(self, mode: str, requested: float, compliance: float) -> bool:
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
            physical = self.polarity.to_physical(requested)
            factor = self.polarity.factor
            assert factor is not None
            self._ownership = SMUOwnership.MANUAL
            self.ownership_changed.emit(SMUOwnership.MANUAL.value)

            try:
                accepted = self._submit(
                    lambda: self._apply_output(
                        SMUOwnership.MANUAL, mode, requested, physical, compliance, factor
                    ),
                    cleanup_owner=SMUOwnership.MANUAL,
                    operation_state=SMUOperationState.BUSY,
                )
            except Exception:
                self._ownership = SMUOwnership.IDLE
                self._operation_state = SMUOperationState.READY
                self.ownership_changed.emit(SMUOwnership.IDLE.value)
                self.operation_state_changed.emit(SMUOperationState.READY.value)
                raise
            if not accepted:
                # This can only occur if a future was registered while holding the same lock.
                # Roll back this request only; never alter ownership for an older operation.
                self._ownership = SMUOwnership.IDLE
                self._operation_state = SMUOperationState.READY
                self.ownership_changed.emit(SMUOwnership.IDLE.value)
                self.operation_state_changed.emit(SMUOperationState.READY.value)
                return False

        LOG.info("MANUAL_SMU MODE=%s", mode)
        LOG.info("MANUAL_SMU REQUEST=%+.9g POLARITY_FACTOR=%+d ACTUAL=%+.9g COMPLIANCE=%g",
                 requested, factor, physical, compliance)
        return True

    def request_manual_off(self) -> bool:
        with self._lock:
            if self._ownership is not SMUOwnership.MANUAL or self._pending:
                return False
            return self._submit(
                lambda: self.safe_shutdown(SMUOwnership.MANUAL),
                operation_state=SMUOperationState.SHUTTING_DOWN,
            )

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
        self.safety.validate(mode, requested, compliance)
        with self._lock:
            if self._ownership is not SMUOwnership.RECIPE:
                raise SMUInterlockError("Recipe does not own the SMU")
            self._ensure_normal_output_allowed_locked()
            physical = self.polarity.to_physical(requested)
        with self._io_lock:
            driver = self._required_driver()
            self._raise_if_emergency_latched()
            if mode == "CV":
                driver.configure_voltage_source(physical, compliance)
            else:
                driver.configure_current_source(physical, compliance)
            with self._output_enable_lock:
                self._raise_if_emergency_latched()
                driver.set_output_enabled(True)
        with self._lock:
            self._mode = mode
            self._output_enabled = True
            self._output_confirmed_off = False
            self._last_shutdown_ok = None
            aborted = (
                self._ownership is not SMUOwnership.RECIPE
                or self._emergency_latch.is_set()
            )
        self.output_changed.emit(True)
        if aborted:
            raise _SMUEmergencyAbort(
                "Recipe SMU ownership changed immediately after OUTPUT ON"
            )
        return physical

    def safe_shutdown(self, owner: SMUOwnership | None = None) -> bool:
        """Zero both source functions and release only after a confirmed command path."""
        with self._lock:
            if owner is not None and self._ownership not in (
                owner,
                SMUOwnership.EMERGENCY,
                SMUOwnership.FAULT,
            ):
                return False
            driver = self._driver
        with self._io_lock:
            try:
                failures = driver.safe_stop() if driver is not None else []
            except Exception as exc:
                failures = [str(exc)]

        with self._lock:
            previous = self._ownership
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
                    # A normal operation aborted by Emergency may perform an early cleanup,
                    # but only the queued Emergency shutdown may release the latch/ownership.
                    self._ownership = SMUOwnership.EMERGENCY
                    self._operation_state = SMUOperationState.EMERGENCY
                else:
                    self._ownership = SMUOwnership.IDLE
                    self._operation_state = SMUOperationState.READY
                    if owner is SMUOwnership.EMERGENCY:
                        self._emergency_latch.clear()

            ownership = self._ownership
            state = self._operation_state

        if failures:
            LOG.error("%s SMU safety stop incomplete: %s", previous.value, "; ".join(failures))
            self.ownership_changed.emit(SMUOwnership.FAULT.value)
            self.operation_state_changed.emit(SMUOperationState.FAULT.value)
            self.error_occurred.emit("SMU safety stop incomplete: " + "; ".join(failures))
            return False

        LOG.info("%s SMU source=0 OUTPUT=OFF; state=%s", previous.value, state.value)
        self.output_changed.emit(False)
        self.ownership_changed.emit(ownership.value)
        self.operation_state_changed.emit(state.value)
        return True

    def request_emergency_off(self) -> bool:
        # Serialize only against the final OUTPUT ON check/call. A blocking configure or
        # measurement VISA call is intentionally not presented as safely preemptible.
        with self._output_enable_lock:
            self._emergency_latch.set()
        with self._lock:
            self._ownership = SMUOwnership.EMERGENCY
            self._operation_state = SMUOperationState.EMERGENCY
        LOG.critical("SMU EMERGENCY OFF requested")
        self.ownership_changed.emit(SMUOwnership.EMERGENCY.value)
        self.operation_state_changed.emit(SMUOperationState.EMERGENCY.value)
        return self._submit(
            lambda: self.safe_shutdown(SMUOwnership.EMERGENCY),
            allow_busy=True,
            operation_state=SMUOperationState.EMERGENCY,
        )

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
                self._output_confirmed_off = enabled is False
                if enabled:
                    self._last_shutdown_ok = None
            self.output_changed.emit(enabled)
        return enabled

    def shutdown(self) -> None:
        self.safe_shutdown()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _required_driver(self) -> SMUDriver:
        if self._driver is None:
            raise SMUInterlockError("No supported SMU is connected")
        return self._driver

    def _ensure_normal_output_allowed_locked(self) -> None:
        if self._emergency_latch.is_set():
            raise SMUInterlockError("SMU Emergency OFF 尚未安全完成，禁止開啟輸出。")
        if self._fault_latched or self._ownership is SMUOwnership.FAULT:
            raise SMUInterlockError(
                "前次 SMU safety stop 未確認成功；請重新執行 Emergency OFF 或重新連線。"
            )

    def _raise_if_emergency_latched(self) -> None:
        if self._emergency_latch.is_set():
            raise _SMUEmergencyAbort("SMU output operation cancelled by Emergency OFF")

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
            self._raise_if_emergency_latched()
            if mode == "CV":
                driver.configure_voltage_source(physical, compliance)
            else:
                driver.configure_current_source(physical, compliance)
            with self._output_enable_lock:
                self._raise_if_emergency_latched()
                driver.set_output_enabled(True)
        with self._lock:
            self._mode = mode
            self._output_enabled = True
            self._output_confirmed_off = False
            self._last_shutdown_ok = None
            aborted = self._ownership is not owner or self._emergency_latch.is_set()
            if not aborted:
                self._operation_state = SMUOperationState.OUTPUT_ON
        self.output_changed.emit(True)
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
            except Exception as exc:
                if isinstance(exc, _SMUEmergencyAbort):
                    LOG.warning("%s", exc)
                else:
                    LOG.exception("SMU operation failed")
                if cleanup_owner is not None:
                    self.safe_shutdown(cleanup_owner)
                if report_errors and not isinstance(exc, _SMUEmergencyAbort):
                    self.error_occurred.emit(str(exc))
            finally:
                with self._lock:
                    self._pending.discard(completed)
                    now_busy = bool(self._pending)

        future.add_done_callback(done)
        if not was_busy:
            self.busy_changed.emit(True)
        if state_changed and operation_state is not None:
            self.operation_state_changed.emit(operation_state.value)
        start_gate.set()

        def report_idle(completed: Future[Any]) -> None:
            with self._lock:
                now_busy = bool(self._pending)
            if not now_busy:
                self.busy_changed.emit(False)

        future.add_done_callback(report_idle)
        return True
