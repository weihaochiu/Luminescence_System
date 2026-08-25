from __future__ import annotations

"""Central SMU ownership, coordinate mapping, safety, and serialized I/O."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
import logging
from threading import Event, RLock
from time import monotonic
from typing import Any, Callable, Mapping

from PySide6.QtCore import QObject, Signal

from core.i18n import tr

from .smu_base import SMUDevice, SMUDriver, SMUFaultIdentity
from .polarity_measurement import (
    PolarityFailureCategory,
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


class SMUOutputState(str, Enum):
    """Authoritative OUTPUT state; UNKNOWN is never equivalent to OFF."""

    OFF = "OFF"
    ON = "ON"
    UNKNOWN = "UNKNOWN"


class SMUErrorKind(str, Enum):
    """Canonical user-facing SMU failure conditions, independent of prose."""

    OUTPUT_OFF_UNCONFIRMED = "output_off_unconfirmed"
    UNEXPECTED_OUTPUT = "unexpected_output"
    COMPLIANCE_ACTIVE = "compliance_active"
    OPERATION_FAILED = "operation_failed"
    POLARITY_MEASUREMENT_FAILED = "polarity_measurement_failed"


@dataclass(frozen=True)
class SMUErrorEvent:
    kind: SMUErrorKind
    message: str
    context: Mapping[str, object] = field(default_factory=dict)
    user_message_key: str | None = None
    user_message_args: Mapping[str, object] = field(default_factory=dict)


class PolarityState(str, Enum):
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"
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

    def clear(self) -> None:
        self._factor = None

    def to_physical(self, requested_value: float) -> float:
        if self._factor is None:
            raise SMUInterlockError(
                tr("smu.error_polarity_unconfirmed")
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
    output_state_changed = Signal(str)
    output_confirmation_changed = Signal(bool)
    busy_changed = Signal(bool)
    operation_state_changed = Signal(str)
    polarity_changed = Signal(object)
    manual_polarity_changed = Signal(object)
    manual_sequence_status = Signal(str)
    manual_sequence_finished = Signal(bool)
    manual_channel_changed = Signal(str)
    command_applied = Signal(str, float, float, float, int)
    readback_ready = Signal(object)
    error_occurred = Signal(str)
    error_event = Signal(object)

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
        self._output_state = SMUOutputState.UNKNOWN
        self._output_confirmed_off = False
        self._output_unknown_latched = False
        self._fault_identity: SMUFaultIdentity | None = None
        self._ever_output_enabled = False
        self._fault_reason = ""
        self._last_shutdown_ok: bool | None = None
        self._fault_latched = False
        self._emergency_latch = Event()
        self._recipe_cancel_latch = Event()
        self._manual_cancel_latch = Event()
        self._manual_generation = 0
        self._manual_polarity = ManualPolarityResult(PolarityState.UNKNOWN, None)
        self._last_manual_polarity_snapshot: dict[str, Any] | None = None
        self._selected_manual_channel = ""
        self._active_manual_channel = ""
        self._active_manual_relay: int | None = None
        self._manual_routing_clear: Callable[[], None] | None = None
        self._manual_routing_verify: Callable[[str], int | None] | None = None
        self._recovery_routing_off: Callable[[], bool] | None = None
        self._recovery_white_light_off: Callable[[], bool] | None = None
        self._external_interlock_fault = False
        self._operation_state = SMUOperationState.READY
        self._mode = "CC"
        self._lock = RLock()
        self._io_lock = RLock()
        self._output_enable_lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smu-io")
        self._pending: set[Future[Any]] = set()
        self._safe_off_pending = False
        self._compliance_active_reported = False
        self._unexpected_output_reported = False

    @property
    def ownership(self) -> SMUOwnership:
        with self._lock:
            return self._ownership

    @property
    def output_enabled(self) -> bool:
        with self._lock:
            return self._output_enabled

    @property
    def output_state(self) -> SMUOutputState:
        with self._lock:
            return self._output_state

    @property
    def output_unknown_latched(self) -> bool:
        with self._lock:
            return self._output_unknown_latched

    @property
    def fault_latched(self) -> bool:
        with self._lock:
            return self._fault_latched

    @property
    def fault_reason(self) -> str:
        with self._lock:
            return self._fault_reason

    @property
    def fault_identity(self) -> SMUFaultIdentity | None:
        with self._lock:
            return self._fault_identity

    @property
    def requires_close_output_confirmation(self) -> bool:
        """Distinguish a never-owned/disconnected SMU from lost output state."""

        with self._lock:
            return bool(
                self._output_unknown_latched
                or self._output_state is SMUOutputState.ON
                or self._driver is not None
            )

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
    def manual_routing_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "selected_smu_channel": self._selected_manual_channel or None,
                "physical_relay_channel": self._active_manual_relay,
                "active_channel_verified": self._active_manual_channel or None,
            }

    @property
    def operation_state(self) -> SMUOperationState:
        with self._lock:
            return self._operation_state

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def confirm_output_off_for_routing(self) -> bool:
        """Query the physical SMU immediately before any routing transition."""

        with self._io_lock:
            with self._lock:
                driver = self._driver
            if driver is None:
                return False
            try:
                observed = driver.query_output_enabled()
            except Exception:
                observed = None
        with self._lock:
            if observed is not None:
                self._output_enabled = observed
                if observed or not self._output_unknown_latched:
                    self._output_state = (
                        SMUOutputState.ON if observed else SMUOutputState.OFF
                    )
                if observed:
                    self._ever_output_enabled = True
            self._output_confirmed_off = observed is False
        if observed is not None:
            self.output_changed.emit(observed)
            self.output_state_changed.emit(self._output_state.value)
        else:
            self._latch_output_unknown(
                "SMU OUTPUT state became UNKNOWN during routing confirmation"
            )
        self.output_confirmation_changed.emit(observed is False)
        if observed is not False:
            LOG.error(
                "SMU_ROUTING blocked: authoritative OUTPUT state=%s",
                "UNKNOWN" if observed is None else "ON",
            )
        return observed is False

    def configure_safety_recovery(
        self,
        routing_off: Callable[[], bool],
        white_light_off: Callable[[], bool],
    ) -> None:
        """Use the existing relay safety APIs for explicit fault recovery."""

        with self._lock:
            self._recovery_routing_off = routing_off
            self._recovery_white_light_off = white_light_off

    def device_matches_fault(self, device: SMUDevice) -> bool:
        """Return whether ``device`` is the physical target of the fault latch."""

        with self._lock:
            identity = self._fault_identity
        return bool(
            identity is not None and identity.matches_device(device)
        )

    def bind_driver(
        self,
        driver: SMUDriver | None,
        force: bool = False,
        output_confirmed_off: bool = False,
    ) -> None:
        with self._lock:
            previous_driver = self._driver
            existing_unknown_latch = self._output_unknown_latched
            existing_fault_latch = self._fault_latched
            existing_external_fault = self._external_interlock_fault
            existing_fault_reason = self._fault_reason
            existing_fault_identity = self._fault_identity
            previous_identity = (
                SMUFaultIdentity.from_device(previous_driver.device)
                if previous_driver is not None
                else None
            )
            incoming_identity = (
                SMUFaultIdentity.from_device(driver.device)
                if driver is not None
                else None
            )
            unresolved_fault = bool(existing_fault_latch or existing_unknown_latch)
            if driver is not None and unresolved_fault:
                if (
                    existing_fault_identity is None
                    or incoming_identity is None
                    or not existing_fault_identity.matches(incoming_identity)
                ):
                    raise SMUInterlockError(
                        "Cannot bind a different physical SMU while a safety fault is unresolved"
                    )
            reconnecting_fault = bool(
                driver is not None
                and previous_driver is None
                and unresolved_fault
                and existing_fault_identity is not None
                and incoming_identity is not None
                and existing_fault_identity.matches(incoming_identity)
            )
            lost_unconfirmed_output = bool(
                driver is None
                and previous_driver is not None
                and self._output_state is not SMUOutputState.OFF
            )
            if not force and not reconnecting_fault and (
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
            keep_fault_latched = bool(
                lost_unconfirmed_output
                or existing_fault_latch
                or existing_unknown_latch
            )
            keep_unknown_latched = bool(lost_unconfirmed_output or existing_unknown_latch)
            if keep_fault_latched and existing_fault_identity is None:
                existing_fault_identity = previous_identity
            self._output_state = (
                SMUOutputState.UNKNOWN
                if keep_unknown_latched
                else (
                    SMUOutputState.OFF
                    if self._output_confirmed_off
                    else SMUOutputState.UNKNOWN
                )
            )
            self._last_shutdown_ok = True if self._output_confirmed_off else None
            self._fault_latched = keep_fault_latched
            self._emergency_latch.clear()
            self._recipe_cancel_latch.clear()
            self._manual_cancel_latch.clear()
            self._manual_generation += 1
            self._manual_polarity = ManualPolarityResult(PolarityState.UNKNOWN, None)
            self._last_manual_polarity_snapshot = None
            self._selected_manual_channel = ""
            self._active_manual_channel = ""
            self._active_manual_relay = None
            self._manual_routing_clear = None
            self._manual_routing_verify = None
            self._external_interlock_fault = bool(
                keep_fault_latched and existing_external_fault
            )
            self._output_unknown_latched = keep_unknown_latched
            self._fault_identity = (
                existing_fault_identity if keep_fault_latched else None
            )
            self._fault_reason = (
                "SMU communication was lost before OUTPUT OFF could be confirmed"
                if lost_unconfirmed_output
                else existing_fault_reason if keep_fault_latched else ""
            )
            self._ownership = (
                SMUOwnership.FAULT if keep_fault_latched else SMUOwnership.IDLE
            )
            self._operation_state = (
                SMUOperationState.FAULT
                if keep_fault_latched
                else SMUOperationState.READY
            )
            if driver is not None and not keep_fault_latched:
                self._ever_output_enabled = False
                self._compliance_active_reported = False
                self._unexpected_output_reported = False
            ownership = self._ownership
            operation = self._operation_state
        self.output_changed.emit(False)
        self.output_state_changed.emit(self._output_state.value)
        self.output_confirmation_changed.emit(self._output_confirmed_off)
        self.ownership_changed.emit(ownership.value)
        self.operation_state_changed.emit(operation.value)
        self.manual_polarity_changed.emit(self._manual_polarity)
        self.manual_channel_changed.emit("")

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
            self._manual_generation += 1
            generation = self._manual_generation
            self._manual_cancel_latch.clear()
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
                    generation,
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
        channel_id: str,
        mode: str,
        requested: float,
        compliance: float,
        area_cm2: float,
        select_channel: Callable[[str, Callable[[], None]], int],
        verify_channel: Callable[[str], int | None],
        clear_channels: Callable[[], None],
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
        manual_diagnostics: dict[str, object] = {
            "white_light_final_state": "NOT_ATTEMPTED",
            "routing_final_state": "NOT_SELECTED",
        }

        def diagnostic_clear_channels() -> None:
            try:
                clear_channels()
            except Exception as exc:
                manual_diagnostics["routing_final_state"] = f"OFF not confirmed: {exc}"
                raise
            manual_diagnostics["routing_final_state"] = "OFF (confirmed)"

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
            self._selected_manual_channel = str(channel_id)
            self._active_manual_channel = ""
            self._active_manual_relay = None
            self._manual_routing_clear = diagnostic_clear_channels
            self._manual_routing_verify = verify_channel
            self._ownership = SMUOwnership.MANUAL
            self._operation_state = SMUOperationState.BUSY

        self.manual_polarity_changed.emit(self._manual_polarity)
        self.manual_channel_changed.emit("SWITCHING")
        LOG.info(
            "MANUAL_SMU OUTPUT_ON_REQUEST channel=%s area_cm2=%g mode=%s requested=%+.9g compliance=%g generation=%d",
            channel_id,
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
                    try:
                        observed_off = self._query_output_or_latch(
                            driver,
                            "manual routing precheck",
                        )
                    except Exception:
                        raise
                    if observed_off is not False:
                        observed = "UNKNOWN" if observed_off is None else "ON"
                        raise SMUInterlockError(
                            "SMU OUTPUT OFF must be authoritatively confirmed before "
                            f"Relay switching (observed {observed})"
                        )
                self._check_manual_generation(generation)
                self.manual_sequence_status.emit(tr("smu.sequence_white_light_off"))
                light_off()
                self._check_manual_generation(generation)
                self.manual_sequence_status.emit(tr("smu.sequence_switch_channel"))
                physical_relay = select_channel(
                    channel_id,
                    lambda: self._check_manual_generation(generation),
                )
                self._check_manual_generation(generation)
                verified_relay = verify_channel(channel_id)
                if verified_relay != physical_relay:
                    raise SMUInterlockError(
                        "Verified SMU routing relay does not match the selected channel"
                    )
                with self._lock:
                    self._active_manual_channel = channel_id
                    self._active_manual_relay = physical_relay
                self.manual_channel_changed.emit(channel_id)
                LOG.info(
                    "MANUAL_SMU ROUTING channel=%s mapped_relay=%d verified=true",
                    channel_id,
                    physical_relay,
                )
                manual_diagnostics["physical_relay_channel"] = physical_relay
                manual_diagnostics["routing_final_state"] = (
                    f"Relay {physical_relay} ON (confirmed)"
                )

                def verified_light_on() -> None:
                    self._check_manual_generation(generation)
                    if verify_channel(channel_id) != physical_relay:
                        raise SMUInterlockError("SMU routing changed before White Light ON")
                    self._check_manual_generation(generation)
                    light_on()
                    manual_diagnostics["white_light_final_state"] = "ON (confirmed)"
                    self._check_manual_generation(generation)

                def verified_light_off() -> None:
                    try:
                        light_off()
                    except Exception as exc:
                        manual_diagnostics["white_light_final_state"] = (
                            f"OFF not confirmed: {exc}"
                        )
                        raise
                    manual_diagnostics["white_light_final_state"] = "OFF (confirmed)"
                    self._check_manual_generation(generation)

                with self._io_lock:
                    driver = self._required_driver()
                    measured = self.polarity_measurement.measure(
                        driver,
                        settings,
                        area_cm2,
                        light_on=verified_light_on,
                        light_off=verified_light_off,
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
                    self._last_manual_polarity_snapshot = {
                        **measured.to_dict(),
                        "selected_smu_channel": channel_id,
                        "physical_relay_channel": physical_relay,
                        "active_channel_verified": channel_id,
                    }
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
                    raise PolarityMeasurementError(
                        "Invalid polarity measurement: "
                        + (measured.failure_reason or "Jsc/Voc measurements do not identify a safe output polarity"),
                        result=measured,
                        details={
                            "Jsc": asdict(measured.jsc_ma_cm2),
                            "Voc": asdict(measured.voc_v),
                            "failure_reason": measured.failure_reason,
                        },
                        user_message_key="polarity.error.invalid_polarity",
                    )

                self._check_manual_generation(generation)
                if verify_channel(channel_id) != physical_relay:
                    raise SMUInterlockError("SMU routing changed after polarity measurement")
                physical = float(requested) * result.factor
                self.safety.validate(mode, physical, compliance)
                self.manual_sequence_status.emit(tr("smu.sequence_configure"))
                with self._io_lock:
                    driver = self._required_driver()
                    self._check_manual_generation(generation)
                    if mode == "CV":
                        driver.configure_voltage_source(physical, compliance)
                    else:
                        driver.configure_current_source(physical, compliance)
                    with self._output_enable_lock:
                        self._check_manual_generation(generation)
                        if verify_channel(channel_id) != physical_relay:
                            raise SMUInterlockError("SMU routing changed before OUTPUT ON")
                        self._check_manual_generation(generation)
                        driver.set_output_enabled(True)
                        if self._query_output_or_latch(
                            driver,
                            "manual formal OUTPUT ON confirmation",
                        ) is not True:
                            raise SMUInterlockError("SMU OUTPUT ON could not be confirmed")
                        self._check_manual_generation(generation)
                        if verify_channel(channel_id) != physical_relay:
                            raise SMUInterlockError("SMU routing changed after OUTPUT ON")
                        self._check_manual_generation(generation)

                with self._lock:
                    cancelled = bool(
                        generation != self._manual_generation
                        or self._manual_cancel_latch.is_set()
                        or self._emergency_latch.is_set()
                        or self._ownership is not SMUOwnership.MANUAL
                    )
                    self._mode = mode
                    self._output_enabled = True
                    self._output_state = SMUOutputState.ON
                    self._ever_output_enabled = True
                    self._output_confirmed_off = False
                    self._last_shutdown_ok = None
                    if not cancelled:
                        self._operation_state = SMUOperationState.OUTPUT_ON
                self.output_changed.emit(True)
                self.output_state_changed.emit(SMUOutputState.ON.value)
                self.output_confirmation_changed.emit(False)
                if cancelled:
                    raise _SMUEmergencyAbort(
                        "Manual SMU sequence was cancelled immediately after OUTPUT ON"
                    )
                self.command_applied.emit(
                    mode,
                    requested,
                    physical,
                    compliance,
                    result.factor,
                )
                self.operation_state_changed.emit(SMUOperationState.OUTPUT_ON.value)
                self.manual_sequence_status.emit(tr("smu.sequence_output_on"))
                LOG.info(
                    "MANUAL_SMU OUTPUT_ON channel=%s relay=%d mode=%s requested=%+.9g physical=%+.9g compliance=%g factor=%+d",
                    channel_id,
                    physical_relay,
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
                    if self._manual_polarity.state is not PolarityState.INVALID:
                        self._manual_polarity = ManualPolarityResult(
                            PolarityState.FAILED,
                            None,
                        )
                    failed_result = self._manual_polarity
                    if self._last_manual_polarity_snapshot is None:
                        self._last_manual_polarity_snapshot = {
                            "settings_snapshot": settings.snapshot(),
                            "selected_smu_channel": channel_id,
                            "physical_relay_channel": self._active_manual_relay,
                            "active_channel_verified": self._active_manual_channel or None,
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

        def failure_context(exception: BaseException) -> Mapping[str, object]:
            context: dict[str, object] = dict(manual_diagnostics)
            context["selected_smu_channel"] = channel_id
            if isinstance(exception, PolarityMeasurementError):
                context.update(exception.details)
            with self._lock:
                driver = self._driver
                output_state = self._output_state.value
                output_confirmed_off = self._output_confirmed_off
            context["output_state_after_abort"] = (
                f"{output_state} (confirmed)" if output_confirmed_off else output_state
            )
            if driver is not None:
                context.update(SMUFaultIdentity.from_device(driver.device).to_context())
            return context

        accepted = self._submit(
            operation,
            cleanup_owner=SMUOwnership.MANUAL,
            operation_state=SMUOperationState.BUSY,
            error_context_provider=failure_context,
        )
        if not accepted:
            with self._lock:
                self._ownership = SMUOwnership.IDLE
                self._operation_state = SMUOperationState.READY
                self._selected_manual_channel = ""
                self._manual_routing_clear = None
                self._manual_routing_verify = None
            self.manual_channel_changed.emit("")
            return False
        self.operation_state_changed.emit(SMUOperationState.BUSY.value)
        self.ownership_changed.emit(SMUOwnership.MANUAL.value)
        return True

    def request_manual_off(self) -> bool:
        """Accept fail-safe OFF even when ownership/state/readback is stale or busy."""

        return self.request_safe_output_off("manual off")

    def request_safe_output_off(self, reason: str = "safe recovery") -> bool:
        """Queue fail-safe OFF behind active I/O, regardless of ordinary state."""

        # Latch cancellation before inspecting normal admission state. Once STOP
        # is accepted, an older Manual or Recipe operation must not reach a later
        # OUTPUT ON command after this request has been queued.
        self._manual_cancel_latch.set()
        self._recipe_cancel_latch.set()
        with self._lock:
            self._manual_generation += 1
            owner = self._ownership
            if self._driver is None:
                self._log_output_off_diagnostics(
                    logging.ERROR,
                    "rejected",
                    reason,
                    "UNAVAILABLE",
                    "driver is not connected",
                )
                self._emit_error_event(
                    SMUErrorKind.OPERATION_FAILED,
                    tr("smu.error_not_connected"),
                )
                return False
            if self._safe_off_pending:
                self._log_output_off_diagnostics(
                    logging.INFO,
                    "idempotent",
                    reason,
                    "PENDING",
                    "an OUTPUT OFF request is already serialized",
                )
                return True
            self._safe_off_pending = True
            shutdown_owner = (
                SMUOwnership.EMERGENCY
                if self._emergency_latch.is_set()
                else owner
            )
        self._log_output_off_diagnostics(
            logging.WARNING,
            "accepted",
            reason,
            "PENDING",
            "queued behind active SMU I/O",
        )

        def recover() -> None:
            try:
                if not self.safe_shutdown(shutdown_owner, reason=reason):
                    return
                with self._lock:
                    explicit_recovery_required = bool(
                        self._output_unknown_latched or self._external_interlock_fault
                    )
                if explicit_recovery_required and not self.recover_safety_fault():
                    raise SMUInterlockError(
                        "Safety recovery requires confirmed SMU OFF, routing all OFF, "
                        "and White Light OFF"
                    )
            finally:
                with self._lock:
                    self._safe_off_pending = False

        try:
            return self._submit(
                recover,
                allow_busy=True,
                operation_state=SMUOperationState.SHUTTING_DOWN,
            )
        except RuntimeError as exc:
            with self._lock:
                self._safe_off_pending = False
            self._log_output_off_diagnostics(
                logging.ERROR,
                "rejected",
                reason,
                "NOT_QUERIED",
                f"executor rejected shutdown: {exc}",
            )
            return False

    def recover_safety_fault(self) -> bool:
        """Clear UNKNOWN/routing FAULT only after all safety readbacks pass."""

        with self._lock:
            driver = self._driver
            routing_off = self._recovery_routing_off
            white_light_off = self._recovery_white_light_off
            fault_identity = self._fault_identity
        if driver is None or routing_off is None or white_light_off is None:
            LOG.error("SMU_RECOVERY blocked: device or relay safety verifier unavailable")
            return False
        current_identity = SMUFaultIdentity.from_device(driver.device)
        if fault_identity is None or not fault_identity.matches(current_identity):
            LOG.critical(
                "SMU_RECOVERY blocked: connected physical identity does not match fault target "
                "fault=%s connected=%s",
                fault_identity,
                current_identity,
            )
            return False
        try:
            with self._io_lock:
                observed = driver.query_output_enabled()
        except Exception as exc:  # noqa: BLE001 - explicit fail-closed state
            self._latch_output_unknown(f"SMU recovery OUTPUT query failed: {exc}")
            return False
        if observed is not False:
            if observed is None:
                self._latch_output_unknown("SMU recovery OUTPUT state is UNKNOWN")
            else:
                with self._lock:
                    self._output_enabled = True
                    self._output_state = SMUOutputState.ON
                    self._output_confirmed_off = False
                    self._ever_output_enabled = True
                self.output_changed.emit(True)
                self.output_state_changed.emit(SMUOutputState.ON.value)
                self.output_confirmation_changed.emit(False)
            LOG.error(
                "SMU_RECOVERY blocked: OUTPUT is %s",
                "UNKNOWN" if observed is None else "ON",
            )
            return False
        try:
            routing_verified = bool(routing_off())
        except Exception:  # noqa: BLE001 - preserve latch and continue logging
            routing_verified = False
            LOG.exception("SMU_RECOVERY routing OFF verification failed")
        try:
            white_verified = bool(white_light_off())
        except Exception:  # noqa: BLE001 - preserve latch
            white_verified = False
            LOG.exception("SMU_RECOVERY White Light OFF verification failed")
        if not routing_verified or not white_verified:
            LOG.error(
                "SMU_RECOVERY blocked: routing_off=%s white_light_off=%s",
                routing_verified,
                white_verified,
            )
            return False
        with self._lock:
            self._output_enabled = False
            self._output_state = SMUOutputState.OFF
            self._output_confirmed_off = True
            self._output_unknown_latched = False
            self._external_interlock_fault = False
            self._fault_latched = False
            self._fault_reason = ""
            self._fault_identity = None
            self._emergency_latch.clear()
            self._recipe_cancel_latch.clear()
            self._manual_cancel_latch.clear()
            self._ownership = SMUOwnership.IDLE
            self._operation_state = SMUOperationState.READY
            self._active_manual_channel = ""
            self._active_manual_relay = None
            self._selected_manual_channel = ""
            self._manual_routing_clear = None
            self._manual_routing_verify = None
        LOG.warning("SMU_RECOVERY complete: OUTPUT OFF, routing OFF, White Light OFF")
        self.output_changed.emit(False)
        self.output_state_changed.emit(SMUOutputState.OFF.value)
        self.output_confirmation_changed.emit(True)
        self.ownership_changed.emit(SMUOwnership.IDLE.value)
        self.operation_state_changed.emit(SMUOperationState.READY.value)
        self.manual_channel_changed.emit("")
        return True

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
                self._emit_error_event(
                    SMUErrorKind.OPERATION_FAILED,
                    tr("smu.error_recipe_not_owner"),
                )
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
            self._raise_if_output_blocked(SMUOwnership.RECIPE)
            if mode == "CV":
                driver.configure_voltage_source(physical, compliance)
            else:
                driver.configure_current_source(physical, compliance)
            with self._output_enable_lock:
                self._raise_if_output_blocked(SMUOwnership.RECIPE)
                driver.set_output_enabled(True)
        with self._lock:
            self._mode = mode
            self._output_enabled = True
            self._output_state = SMUOutputState.ON
            self._ever_output_enabled = True
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
        self.output_state_changed.emit(SMUOutputState.ON.value)
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

    def set_recipe_polarity_factor(self, factor: int | None) -> None:
        """Replace the per-channel mapping while Recipe owns a confirmed-OFF SMU."""

        with self._lock:
            if self._ownership is not SMUOwnership.RECIPE:
                raise SMUInterlockError("Recipe does not own the SMU")
            if self._output_enabled or not self._output_confirmed_off:
                raise SMUInterlockError("Polarity can change only while Recipe OUTPUT is confirmed OFF")
            if factor is None:
                self.polarity.clear()
            else:
                self.polarity.set_confirmed_factor(factor)
        if factor is not None:
            self.polarity_changed.emit(factor)

    def recipe_output_off(self, reason: str = "recipe transition") -> None:
        """Verified OUTPUT OFF that deliberately retains Recipe ownership."""

        with self._lock:
            if self._ownership is not SMUOwnership.RECIPE:
                raise SMUInterlockError("Recipe does not own the SMU")
            driver = self._required_driver()
        failures: list[str] = []
        observed: bool | None = None
        with self._io_lock:
            try:
                failures.extend(driver.safe_stop())
                observed = driver.query_output_enabled()
            except Exception as exc:
                failures.append(str(exc))
        if observed is not False:
            failures.append(
                "OUTPUT OFF not confirmed (observed "
                + ("UNKNOWN" if observed is None else "ON") + ")"
            )
        if failures:
            self._manual_cancel_latch.set()
            self._recipe_cancel_latch.set()
        with self._lock:
            if failures:
                self._latch_output_unknown_locked("; ".join(failures))
            else:
                self._output_enabled = False
                self._output_confirmed_off = True
                self._output_state = SMUOutputState.OFF
                self._operation_state = SMUOperationState.RECIPE_LOCKED
        if failures:
            self.output_state_changed.emit(SMUOutputState.UNKNOWN.value)
            self.operation_state_changed.emit(SMUOperationState.FAULT.value)
            message = "Recipe OUTPUT OFF failed: " + "; ".join(failures)
            self._emit_error_event(SMUErrorKind.OUTPUT_OFF_UNCONFIRMED, message)
            raise SMUInterlockError(message)
        LOG.info("RECIPE_SMU OUTPUT OFF verified reason=%s", reason)
        self.output_changed.emit(False)
        self.output_state_changed.emit(SMUOutputState.OFF.value)
        self.output_confirmation_changed.emit(True)
        self.operation_state_changed.emit(SMUOperationState.RECIPE_LOCKED.value)

    def recipe_readback(self) -> SMUReadback:
        """Synchronous formal-image readback serialized with Recipe I/O."""

        with self._lock:
            if self._ownership is not SMUOwnership.RECIPE:
                raise SMUInterlockError("Recipe does not own the SMU")
            mode = self._mode
        with self._io_lock:
            driver = self._required_driver()
            enabled = self._query_output_or_latch(driver, "Recipe formal image readback")
            if enabled is not True:
                raise SMUInterlockError("Recipe formal image readback requires confirmed OUTPUT ON")
            voltage = float(driver.measure_voltage())
            current = float(driver.measure_current())
            compliance = driver.query_compliance_tripped(mode)
        if compliance:
            message = tr("smu.error_compliance_detected")
            self._emit_error_event(SMUErrorKind.COMPLIANCE_ACTIVE, message)
            raise SMUInterlockError(message)
        return SMUReadback(voltage, current, voltage * current, True, compliance)

    def recipe_polarity_measurement(
        self,
        settings: PolarityMeasurementSettings,
        area_cm2: float,
        *,
        light_on: Callable[[], None],
        light_off: Callable[[], None],
        check_cancel: Callable[[], None],
        wait_ms: Callable[[int], None],
        status: Callable[[str], None],
    ) -> dict[str, Any]:
        """Run Jsc/Voc for one routed Recipe channel and replace its factor."""

        with self._lock:
            if self._ownership is not SMUOwnership.RECIPE:
                raise SMUInterlockError("Recipe does not own the SMU")
            if self._output_enabled or not self._output_confirmed_off:
                raise SMUInterlockError("Recipe polarity requires confirmed OUTPUT OFF")
            self.polarity.clear()
        with self._io_lock:
            result = self.polarity_measurement.measure(
                self._required_driver(),
                settings,
                area_cm2,
                light_on=light_on,
                light_off=light_off,
                check_cancel=check_cancel,
                wait_ms=wait_ms,
                status=status,
            )
        if result.factor is None:
            raise SMUInterlockError(
                "Invalid polarity measurement: "
                + (result.failure_reason or "Jsc/Voc did not identify a safe polarity")
            )
        with self._lock:
            self.polarity.set_confirmed_factor(result.factor)
            self._output_enabled = False
            self._output_confirmed_off = True
            self._output_state = SMUOutputState.OFF
            self._operation_state = SMUOperationState.RECIPE_LOCKED
        self.polarity_changed.emit(result.factor)
        payload = result.to_dict()
        payload.update({
            "polarity_check_status": "COMPLETED",
            "polarity_timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        return payload

    def safe_shutdown(
        self,
        owner: SMUOwnership | None = None,
        *,
        reason: str = "safe shutdown",
    ) -> bool:
        """Turn OUTPUT OFF, explicitly confirm it, then release ownership."""

        with self._lock:
            driver = self._driver
            previous = self._ownership
            routing_clear = self._manual_routing_clear

        failures: list[str] = []
        observed_output: bool | None = None
        shutdown_attempts = 0
        with self._io_lock:
            if driver is None:
                failures.append("SMU driver is not available")
            else:
                for shutdown_attempts in range(1, 3):
                    attempt_failures: list[str] = []
                    try:
                        attempt_failures.extend(driver.safe_stop())
                    except Exception as exc:  # noqa: BLE001 - fail closed
                        attempt_failures.append(str(exc))
                    try:
                        observed_output = driver.query_output_enabled()
                    except Exception as exc:  # noqa: BLE001 - fail closed
                        observed_output = None
                        attempt_failures.append(
                            f"OUTPUT OFF confirmation failed: {exc}"
                        )
                    if observed_output is False:
                        if attempt_failures:
                            LOG.warning(
                                "SMU_OUTPUT_OFF physical OFF recovered despite attempt "
                                "diagnostics attempt=%d diagnostics=%s",
                                shutdown_attempts,
                                attempt_failures,
                            )
                        failures = []
                        break
                    observed = "UNKNOWN" if observed_output is None else "ON"
                    attempt_failures.append(
                        f"OUTPUT OFF not confirmed (observed {observed})"
                    )
                    failures = attempt_failures
                    if shutdown_attempts == 1:
                        LOG.warning(
                            "SMU_OUTPUT_OFF retrying after unconfirmed physical state "
                            "reason=%s diagnostics=%s",
                            reason,
                            attempt_failures,
                        )
        smu_off_confirmed = driver is not None and observed_output is False
        self._log_output_off_diagnostics(
            logging.INFO if smu_off_confirmed else logging.ERROR,
            "physical_confirmation",
            reason,
            "OFF" if observed_output is False else "UNKNOWN" if observed_output is None else "ON",
            (
                f"physical OUTPUT OFF confirmed after {shutdown_attempts} attempt(s)"
                if smu_off_confirmed
                else f"physical OUTPUT OFF not confirmed after {shutdown_attempts} attempt(s)"
            ),
        )

        # Normal routing changes are permitted only after SMU OFF has been
        # authoritatively confirmed. EmergencyManager also owns an independent,
        # immediate best-effort routing OFF action.
        routing_cleared = False
        if smu_off_confirmed and routing_clear is not None:
            try:
                routing_clear()
                routing_cleared = True
                LOG.info("MANUAL_SMU STOP routing all OFF confirmed")
            except Exception as exc:  # noqa: BLE001 - fail closed
                failures.append(f"SMU routing OFF failed: {exc}")

        with self._lock:
            if failures:
                if not smu_off_confirmed:
                    self._latch_output_unknown_locked("; ".join(failures))
                else:
                    if self._fault_identity is None and driver is not None:
                        self._fault_identity = SMUFaultIdentity.from_device(driver.device)
                    self._output_enabled = False
                    self._output_confirmed_off = True
                    if not self._output_unknown_latched:
                        self._output_state = SMUOutputState.OFF
                self._last_shutdown_ok = False
                self._fault_latched = True
                self._fault_reason = "; ".join(failures)
                self._ownership = SMUOwnership.FAULT
                self._operation_state = SMUOperationState.FAULT
            else:
                self._output_enabled = False
                self._output_confirmed_off = True
                self._last_shutdown_ok = True
                if self._output_unknown_latched:
                    self._output_state = SMUOutputState.UNKNOWN
                else:
                    self._output_state = SMUOutputState.OFF
                if self._external_interlock_fault or self._output_unknown_latched:
                    self._fault_latched = True
                    self._ownership = SMUOwnership.FAULT
                    self._operation_state = SMUOperationState.FAULT
                else:
                    self._fault_latched = False
                    self._fault_reason = ""
                if self._external_interlock_fault or self._output_unknown_latched:
                    pass
                elif self._emergency_latch.is_set() and owner is not SMUOwnership.EMERGENCY:
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
                if routing_cleared:
                    self._active_manual_channel = ""
                    self._active_manual_relay = None
                    self._selected_manual_channel = ""
                    self._manual_routing_clear = None
                    self._manual_routing_verify = None
                if (
                    previous is SMUOwnership.EMERGENCY
                    or (
                        previous is SMUOwnership.MANUAL
                        and self._manual_polarity.state
                        not in {PolarityState.FAILED, PolarityState.INVALID}
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
            self._log_output_off_diagnostics(
                logging.ERROR,
                "fault_latched",
                reason,
                (
                    "OFF"
                    if smu_off_confirmed
                    else "UNKNOWN" if observed_output is None else "ON"
                ),
                message,
            )
            if smu_off_confirmed:
                self.output_changed.emit(False)
            self.output_state_changed.emit(self._output_state.value)
            self.output_confirmation_changed.emit(smu_off_confirmed)
            self.ownership_changed.emit(SMUOwnership.FAULT.value)
            self.operation_state_changed.emit(SMUOperationState.FAULT.value)
            self._emit_error_event(
                SMUErrorKind.OPERATION_FAILED
                if smu_off_confirmed
                else SMUErrorKind.OUTPUT_OFF_UNCONFIRMED,
                tr("smu.error_routing_recovery_incomplete")
                if smu_off_confirmed
                else tr("smu.error_output_off_unconfirmed"),
            )
            if routing_clear is not None:
                self.manual_channel_changed.emit("FAULT")
            return False

        LOG.info(
            "SMU_SAFE_SHUTDOWN OUTPUT OFF confirmed reason=%s previous_owner=%s",
            reason,
            previous.value,
        )
        self.output_changed.emit(False)
        self.output_state_changed.emit(self._output_state.value)
        self.output_confirmation_changed.emit(True)
        self.ownership_changed.emit(ownership.value)
        self.operation_state_changed.emit(state.value)
        if previous in (SMUOwnership.MANUAL, SMUOwnership.EMERGENCY):
            self.manual_polarity_changed.emit(self._manual_polarity)
        if routing_cleared:
            self.manual_channel_changed.emit("")
        return True

    def request_external_interlock(self, reason: str) -> bool:
        """Latch a non-resettable routing fault and invalidate active workers."""

        self._emergency_latch.set()
        self._recipe_cancel_latch.set()
        self._manual_cancel_latch.set()
        with self._lock:
            self._external_interlock_fault = True
            self._latch_output_unknown_locked(reason)
            has_driver = self._driver is not None
            busy = bool(self._pending)
        LOG.critical("SMU_EXTERNAL_INTERLOCK latched reason=%s", reason)
        self.output_state_changed.emit(SMUOutputState.UNKNOWN.value)
        self.output_confirmation_changed.emit(False)
        self.ownership_changed.emit(SMUOwnership.FAULT.value)
        self.operation_state_changed.emit(SMUOperationState.FAULT.value)
        self._emit_error_event(SMUErrorKind.OPERATION_FAILED, reason)
        if not has_driver or busy:
            return True
        return self._submit(
            lambda: self.safe_shutdown(reason="external routing interlock"),
            allow_busy=True,
            operation_state=SMUOperationState.FAULT,
        )

    def mark_external_routing_off_verified(self) -> None:
        """Publish an independently verified Emergency routing disconnect."""

        with self._lock:
            self._active_manual_channel = ""
            self._active_manual_relay = None
        self.manual_channel_changed.emit("")

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
            with self._lock:
                routing_verify = self._manual_routing_verify
                active_channel = self._active_manual_channel
                active_relay = self._active_manual_relay
                routing_should_be_active = (
                    routing_verify is not None
                    and bool(active_channel)
                    and self._ownership is SMUOwnership.MANUAL
                    and self._operation_state is SMUOperationState.OUTPUT_ON
                )
            if routing_should_be_active:
                try:
                    actual_relay = (
                        None
                        if routing_verify is None or not active_channel
                        else routing_verify(active_channel)
                    )
                except Exception as exc:
                    self.request_external_interlock(
                        f"SMU routing verification failed during live readback: {exc}"
                    )
                    raise
                if actual_relay != active_relay:
                    reason = (
                        "SMU routing mismatch during live readback: "
                        f"expected={active_channel}/Relay {active_relay}, "
                        f"actual_relay={actual_relay}"
                    )
                    self.request_external_interlock(reason)
                    raise SMUInterlockError(reason)
            with self._io_lock:
                driver = self._required_driver()
                try:
                    output_enabled = driver.query_output_enabled()
                except Exception as exc:
                    self._latch_output_unknown(f"SMU readback OUTPUT query failed: {exc}")
                    raise
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
                        with self._lock:
                            report_compliance = not self._compliance_active_reported
                            self._compliance_active_reported = True
                        if report_compliance:
                            self._emit_error_event(
                                SMUErrorKind.COMPLIANCE_ACTIVE,
                                tr("smu.error_compliance_detected"),
                            )
                    else:
                        with self._lock:
                            self._compliance_active_reported = False
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
                        with self._lock:
                            report_unexpected = not self._unexpected_output_reported
                            self._unexpected_output_reported = True
                        if report_unexpected:
                            self._emit_error_event(
                                SMUErrorKind.UNEXPECTED_OUTPUT,
                                tr("smu.error_unexpected_output_detected"),
                            )
                    else:
                        LOG.debug("SMU_READBACK output=UNKNOWN mode=OUTPUT_ONLY")
                    if output_enabled is not True:
                        with self._lock:
                            self._unexpected_output_reported = False
                reading = SMUReadback(
                    voltage_v=voltage,
                    current_a=current,
                    power_w=power,
                    output_enabled=output_enabled,
                    compliance_tripped=compliance_tripped,
                )
            if routing_should_be_active:
                try:
                    actual_after = (
                        None
                        if routing_verify is None
                        else routing_verify(active_channel)
                    )
                except Exception as exc:
                    self.request_external_interlock(
                        f"SMU routing verification failed after live readback: {exc}"
                    )
                    raise
                if actual_after != active_relay:
                    reason = "SMU routing changed during live readback"
                    self.request_external_interlock(reason)
                    raise SMUInterlockError(reason)
            with self._lock:
                if reading.output_enabled is not None:
                    self._output_enabled = reading.output_enabled
                    self._output_state = (
                        SMUOutputState.ON
                        if reading.output_enabled
                        else SMUOutputState.OFF
                    )
                    if reading.output_enabled:
                        self._ever_output_enabled = True
                        self._last_shutdown_ok = None
                self._output_confirmed_off = reading.output_enabled is False
            if reading.output_enabled is not None:
                self.output_changed.emit(reading.output_enabled)
                self.output_state_changed.emit(self._output_state.value)
            else:
                self._latch_output_unknown(
                    "SMU readback returned UNKNOWN output state"
                )
                raise SMUInterlockError("SMU readback OUTPUT state is UNKNOWN")
            self.output_confirmation_changed.emit(reading.output_enabled is False)
            self.readback_ready.emit(reading)

        return self._submit(
            operation,
            cleanup_owner=SMUOwnership.MANUAL,
            report_errors=False,
        )

    def confirm_output_enabled(self) -> bool | None:
        """Serialized front-panel confirmation used before disconnecting."""

        try:
            with self._io_lock:
                enabled = self._required_driver().query_output_enabled()
        except Exception as exc:
            self._latch_output_unknown(f"SMU OUTPUT query failed: {exc}")
            raise
        with self._lock:
            if enabled is not None:
                self._output_enabled = enabled
                if enabled or not self._output_unknown_latched:
                    self._output_state = (
                        SMUOutputState.ON if enabled else SMUOutputState.OFF
                    )
                if enabled:
                    self._ever_output_enabled = True
                    self._last_shutdown_ok = None
            self._output_confirmed_off = enabled is False
        if enabled is not None:
            self.output_changed.emit(enabled)
            self.output_state_changed.emit(self._output_state.value)
        else:
            self._latch_output_unknown("SMU OUTPUT query returned UNKNOWN")
        self.output_confirmation_changed.emit(enabled is False)
        return enabled

    def shutdown(
        self,
        *,
        safety_confirmed: bool = False,
        force: bool = False,
    ) -> bool:
        safe = True
        if self._driver is not None and not safety_confirmed:
            safe = self.safe_shutdown(reason="control shutdown")
        self._executor.shutdown(wait=not force, cancel_futures=True)
        return safe

    def _latch_output_unknown(self, reason: str) -> None:
        """Latch UNKNOWN into the existing FAULT/ownership state machine."""

        self._manual_cancel_latch.set()
        self._recipe_cancel_latch.set()
        with self._lock:
            self._latch_output_unknown_locked(reason)
        LOG.critical("SMU_OUTPUT_UNKNOWN latched reason=%s", reason)
        self.output_state_changed.emit(SMUOutputState.UNKNOWN.value)
        self.output_confirmation_changed.emit(False)
        self.ownership_changed.emit(SMUOwnership.FAULT.value)
        self.operation_state_changed.emit(SMUOperationState.FAULT.value)
        self.manual_channel_changed.emit("FAULT")
        self._emit_error_event(SMUErrorKind.OUTPUT_OFF_UNCONFIRMED, str(reason))

    def _latch_output_unknown_locked(
        self,
        reason: str,
        identity: SMUFaultIdentity | None = None,
    ) -> None:
        """Mutate the fail-closed state without ever replacing its first identity."""

        if self._fault_identity is None:
            if identity is None and self._driver is not None:
                identity = SMUFaultIdentity.from_device(self._driver.device)
            self._fault_identity = identity
        self._manual_generation += 1
        self._output_state = SMUOutputState.UNKNOWN
        self._output_confirmed_off = False
        self._output_unknown_latched = True
        self._fault_latched = True
        self._fault_reason = str(reason)
        self._ownership = SMUOwnership.FAULT
        self._operation_state = SMUOperationState.FAULT

    def _emit_error_event(
        self,
        kind: SMUErrorKind,
        message: str,
        *,
        context: Mapping[str, object] | None = None,
        user_message_key: str | None = None,
        user_message_args: Mapping[str, object] | None = None,
    ) -> None:
        event = SMUErrorEvent(
            kind=kind,
            message=str(message),
            context=dict(context or {}),
            user_message_key=user_message_key,
            user_message_args=dict(user_message_args or {}),
        )
        self.error_event.emit(event)
        self.error_occurred.emit(event.message)

    def _required_driver(self) -> SMUDriver:
        if self._driver is None:
            raise SMUInterlockError("No supported SMU is connected")
        return self._driver

    def _query_output_or_latch(
        self,
        driver: SMUDriver,
        context: str,
    ) -> bool | None:
        try:
            observed = driver.query_output_enabled()
        except Exception as exc:
            self._latch_output_unknown(f"{context} failed: {exc}")
            raise
        if observed is None:
            self._latch_output_unknown(f"{context} returned UNKNOWN")
        return observed

    def _ensure_normal_output_allowed_locked(self) -> None:
        if self._emergency_latch.is_set():
            raise SMUInterlockError("SMU Emergency OFF is latched; output is blocked")
        if self._fault_latched or self._ownership is SMUOwnership.FAULT:
            raise SMUInterlockError(
                "Previous SMU safety stop failed; run Emergency OFF or safe recovery"
            )

    def _raise_if_output_blocked(self, owner: SMUOwnership) -> None:
        if self._emergency_latch.is_set():
            raise _SMUEmergencyAbort("SMU output cancelled by Emergency OFF")
        if owner is SMUOwnership.RECIPE and self._recipe_cancel_latch.is_set():
            raise _SMUEmergencyAbort("SMU output cancelled by Recipe handover")
        if owner is SMUOwnership.MANUAL and self._manual_cancel_latch.is_set():
            raise _SMUEmergencyAbort("Manual SMU output was cancelled")

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
                if self._query_output_or_latch(
                    driver,
                    "temporary measurement OUTPUT ON confirmation",
                ) is not True:
                    raise SMUInterlockError("SMU measurement OUTPUT ON could not be confirmed")
                output_enabled = True
            self._check_manual_generation(generation)
            value = float(measure())
            self._check_manual_generation(generation)
            return value
        finally:
            if output_enabled:
                driver.set_output_enabled(False)
                if self._query_output_or_latch(
                    driver,
                    "temporary measurement OUTPUT OFF confirmation",
                ) is not False:
                    raise SMUInterlockError("SMU measurement OUTPUT OFF could not be confirmed")

    def _apply_output(
        self,
        owner: SMUOwnership,
        mode: str,
        requested: float,
        physical: float,
        compliance: float,
        factor: int,
        manual_generation: int | None = None,
    ) -> None:
        with self._io_lock:
            driver = self._required_driver()
            if manual_generation is not None:
                self._check_manual_generation(manual_generation)
            self._raise_if_output_blocked(owner)
            if mode == "CV":
                driver.configure_voltage_source(physical, compliance)
            else:
                driver.configure_current_source(physical, compliance)
            with self._output_enable_lock:
                if manual_generation is not None:
                    self._check_manual_generation(manual_generation)
                self._raise_if_output_blocked(owner)
                driver.set_output_enabled(True)
                if self._query_output_or_latch(
                    driver,
                    f"{owner.value} OUTPUT ON confirmation",
                ) is not True:
                    raise SMUInterlockError("SMU OUTPUT ON could not be confirmed")
                if manual_generation is not None:
                    self._check_manual_generation(manual_generation)
        with self._lock:
            self._mode = mode
            self._output_enabled = True
            self._output_state = SMUOutputState.ON
            self._ever_output_enabled = True
            self._output_confirmed_off = False
            self._last_shutdown_ok = None
            aborted = (
                self._ownership is not owner
                or self._emergency_latch.is_set()
                or (
                    owner is SMUOwnership.RECIPE
                    and self._recipe_cancel_latch.is_set()
                )
                or (
                    owner is SMUOwnership.MANUAL
                    and (
                        self._manual_cancel_latch.is_set()
                        or manual_generation != self._manual_generation
                    )
                )
            )
            if not aborted:
                self._operation_state = SMUOperationState.OUTPUT_ON
        self.output_changed.emit(True)
        self.output_state_changed.emit(SMUOutputState.ON.value)
        self.output_confirmation_changed.emit(False)
        if aborted:
            raise _SMUEmergencyAbort("SMU ownership changed immediately after OUTPUT ON")
        LOG.info("%s_SMU OUTPUT=ON", owner.value)
        self.command_applied.emit(mode, requested, physical, compliance, factor)
        self.operation_state_changed.emit(SMUOperationState.OUTPUT_ON.value)

    def _log_output_off_diagnostics(
        self,
        level: int,
        stage: str,
        reason: str,
        physical_readback: str,
        detail: str,
    ) -> None:
        with self._lock:
            ownership = self._ownership.value
            operation_state = self._operation_state.value
            output_state = self._output_state.value
            output_confirmed_off = self._output_confirmed_off
            pending_count = len(self._pending)
            emergency_latch = self._emergency_latch.is_set()
            fault_latch = self._fault_latched
            driver_connected = self._driver is not None
        LOG.log(
            level,
            "SMU_OUTPUT_OFF stage=%s ownership=%s operation_state=%s "
            "output_state=%s output_confirmed_off=%s pending_count=%d "
            "emergency_latch=%s fault_latch=%s driver_connected=%s "
            "reason=%s physical_readback=%s detail=%s",
            stage,
            ownership,
            operation_state,
            output_state,
            output_confirmed_off,
            pending_count,
            emergency_latch,
            fault_latch,
            driver_connected,
            reason,
            physical_readback,
            detail,
        )

    def _submit(
        self,
        operation: Callable[[], None],
        cleanup_owner: SMUOwnership | None = None,
        report_errors: bool = True,
        allow_busy: bool = False,
        operation_state: SMUOperationState | None = None,
        error_context_provider: Callable[[BaseException], Mapping[str, object]] | None = None,
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
                elif (
                    isinstance(exc, PolarityMeasurementError)
                    and exc.category is PolarityFailureCategory.MEASUREMENT_QUALITY
                ):
                    LOG.warning("Polarity measurement quality failure: %s", exc)
                else:
                    LOG.exception("SMU operation failed")
                if (
                    isinstance(exc, PolarityMeasurementError)
                    and exc.category is PolarityFailureCategory.OUTPUT_OFF_UNCONFIRMED
                ):
                    self._latch_output_unknown(str(exc))
                cleanup_ok = True
                if cleanup_owner is not None:
                    cleanup_ok = self.safe_shutdown(
                        cleanup_owner, reason="failed output operation"
                    )
                if (
                    report_errors
                    and not isinstance(exc, _SMUEmergencyAbort)
                    and cleanup_ok
                    and not (
                        isinstance(exc, PolarityMeasurementError)
                        and exc.category
                        is PolarityFailureCategory.OUTPUT_OFF_UNCONFIRMED
                    )
                ):
                    context = (
                        dict(error_context_provider(exc))
                        if error_context_provider is not None
                        else {}
                    )
                    if (
                        isinstance(exc, PolarityMeasurementError)
                        and exc.category is PolarityFailureCategory.MEASUREMENT_QUALITY
                    ):
                        self._emit_error_event(
                            SMUErrorKind.POLARITY_MEASUREMENT_FAILED,
                            str(exc),
                            context=context,
                            user_message_key=exc.user_message_key,
                            user_message_args=exc.user_message_args,
                        )
                    elif (
                        isinstance(exc, PolarityMeasurementError)
                        and exc.category is PolarityFailureCategory.OUTPUT_OFF_UNCONFIRMED
                    ):
                        self._emit_error_event(
                            SMUErrorKind.OUTPUT_OFF_UNCONFIRMED,
                            str(exc),
                            context=context,
                        )
                    else:
                        self._emit_error_event(
                            SMUErrorKind.OPERATION_FAILED,
                            str(exc),
                            context=context,
                        )
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
