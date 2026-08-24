from __future__ import annotations

"""Immutable, unified high-level SMU state and GUI enablement policy."""

from dataclasses import dataclass
from enum import Enum
import logging

from PySide6.QtCore import QObject, Signal

from core.i18n import i18n, tr

from .smu_control import (
    SMUControlManager,
    SMUOperationState,
    SMUOutputState,
    SMUOwnership,
)


LOG = logging.getLogger(__name__)


class SMUInstrumentState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY_MANUAL = "READY_MANUAL"
    MANUAL_OUTPUT_ON = "MANUAL_OUTPUT_ON"
    TRANSITIONING = "TRANSITIONING"
    AUTO_RUNNING = "AUTO_RUNNING"
    UNEXPECTED_OUTPUT_ON = "UNEXPECTED_OUTPUT_ON"
    OUTPUT_UNKNOWN = "OUTPUT_UNKNOWN"
    ERROR = "ERROR"
    EMERGENCY_STOP = "EMERGENCY_STOP"


@dataclass(frozen=True)
class SMUUIState:
    """Complete presentation policy consumed by every SMU GUI surface."""

    state: SMUInstrumentState
    connected: bool
    supported: bool
    device_label: str
    ownership: SMUOwnership
    operation: SMUOperationState
    output_enabled: bool
    output_confirmed_off: bool
    manual_editable: bool
    manual_off_enabled: bool
    emergency_enabled: bool
    handover_enabled: bool
    status_text: str
    manual_lock_reason: str
    output_state: SMUOutputState = SMUOutputState.OFF
    fault_reason: str = ""

    @classmethod
    def disconnected(cls) -> "SMUUIState":
        return cls(
            state=SMUInstrumentState.DISCONNECTED,
            connected=False,
            supported=False,
            device_label="",
            ownership=SMUOwnership.IDLE,
            operation=SMUOperationState.READY,
            output_enabled=False,
            output_confirmed_off=False,
            manual_editable=False,
            manual_off_enabled=False,
            emergency_enabled=False,
            handover_enabled=False,
            status_text=tr("smu.state.disconnected_status"),
            manual_lock_reason=tr("smu.state.disconnected_reason"),
            output_state=SMUOutputState.UNKNOWN,
        )


class InstrumentStateManager(QObject):
    """Combine connection and hardware-control state into one immutable snapshot."""

    state_changed = Signal(object)

    def __init__(
        self,
        control: SMUControlManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._control = control
        self._connection_state = SMUInstrumentState.DISCONNECTED
        self._connected = False
        self._supported = False
        self._device_label = ""
        self._ownership = control.ownership
        self._operation = control.operation_state
        self._output_enabled = control.output_enabled
        self._output_state = control.output_state
        self._output_confirmed_off = control.output_confirmed_off
        self._last_state = SMUUIState.disconnected()

        control.ownership_changed.connect(self.update_ownership)
        control.operation_state_changed.connect(self.update_operation_state)
        control.output_changed.connect(self.update_output)
        control.output_state_changed.connect(self.update_output_state)
        control.output_confirmation_changed.connect(self.update_output_confirmation)
        i18n.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, _language: str = "") -> None:
        self._publish(force=True)

    @property
    def current(self) -> SMUUIState:
        return self._last_state

    def refresh(self) -> None:
        self._publish(force=True)

    def set_connecting(self, device_label: str = "") -> None:
        self._connection_state = SMUInstrumentState.CONNECTING
        self._connected = False
        self._supported = False
        self._device_label = device_label
        self._publish()

    def set_connected(self, device_label: str, supported: bool) -> None:
        self._connection_state = SMUInstrumentState.READY_MANUAL
        self._connected = True
        self._supported = bool(supported)
        self._device_label = device_label
        self._ownership = self._control.ownership
        self._operation = self._control.operation_state
        self._output_enabled = self._control.output_enabled
        self._output_state = self._control.output_state
        self._output_confirmed_off = self._control.output_confirmed_off
        self._publish()

    def set_disconnected(self) -> None:
        preserve_unknown = (
            self._control.output_unknown_latched
            and self._control.output_state is SMUOutputState.UNKNOWN
        )
        self._connection_state = (
            SMUInstrumentState.ERROR
            if preserve_unknown
            else SMUInstrumentState.DISCONNECTED
        )
        self._connected = False
        self._supported = False
        self._device_label = ""
        self._ownership = (
            self._control.ownership if preserve_unknown else SMUOwnership.IDLE
        )
        self._operation = (
            self._control.operation_state
            if preserve_unknown
            else SMUOperationState.READY
        )
        self._output_enabled = self._control.output_enabled if preserve_unknown else False
        self._output_state = (
            self._control.output_state if preserve_unknown else SMUOutputState.UNKNOWN
        )
        self._output_confirmed_off = False
        self._publish()

    def set_connection_error(self, message: str = "") -> None:
        self._connection_state = SMUInstrumentState.ERROR
        self._connected = False
        self._supported = False
        self._device_label = ""
        self._publish()

    def update_ownership(self, ownership: str) -> None:
        try:
            self._ownership = SMUOwnership(ownership)
        except ValueError:
            self._ownership = SMUOwnership.FAULT
        self._publish()

    def update_operation_state(self, operation: str) -> None:
        try:
            self._operation = SMUOperationState(operation)
        except ValueError:
            self._operation = SMUOperationState.FAULT
        self._publish()

    def update_output(self, enabled: bool) -> None:
        self._output_enabled = bool(enabled)
        self._output_state = (
            SMUOutputState.ON if enabled else self._control.output_state
        )
        self._output_confirmed_off = self._control.output_confirmed_off
        self._publish()

    def update_output_state(self, output_state: str) -> None:
        try:
            self._output_state = SMUOutputState(output_state)
        except ValueError:
            self._output_state = SMUOutputState.UNKNOWN
        self._output_confirmed_off = self._control.output_confirmed_off
        self._publish()

    def update_output_confirmation(self, confirmed: bool) -> None:
        self._output_confirmed_off = bool(confirmed)
        if confirmed and not self._control.output_unknown_latched:
            self._output_enabled = False
            self._output_state = SMUOutputState.OFF
        self._publish()

    def _derive_state(self) -> SMUInstrumentState:
        if self._connection_state is SMUInstrumentState.CONNECTING:
            return SMUInstrumentState.CONNECTING
        if self._output_state is SMUOutputState.UNKNOWN and (
            (self._connected and self._supported)
            or self._control.output_unknown_latched
        ):
            return SMUInstrumentState.OUTPUT_UNKNOWN
        if self._connection_state is SMUInstrumentState.ERROR and not self._connected:
            return SMUInstrumentState.ERROR
        if not self._connected:
            return SMUInstrumentState.DISCONNECTED
        if not self._supported:
            return SMUInstrumentState.ERROR
        if (
            self._ownership is SMUOwnership.FAULT
            or self._operation is SMUOperationState.FAULT
        ):
            return SMUInstrumentState.ERROR
        if (
            self._ownership is SMUOwnership.EMERGENCY
            or self._operation is SMUOperationState.EMERGENCY
        ):
            return SMUInstrumentState.EMERGENCY_STOP
        if self._ownership is SMUOwnership.RECIPE:
            return SMUInstrumentState.AUTO_RUNNING
        if self._output_enabled:
            if (
                self._ownership is SMUOwnership.MANUAL
                and self._operation is SMUOperationState.OUTPUT_ON
            ):
                return SMUInstrumentState.MANUAL_OUTPUT_ON
            if (
                self._ownership is SMUOwnership.MANUAL
                and self._operation
                in (SMUOperationState.BUSY, SMUOperationState.SHUTTING_DOWN)
            ):
                return SMUInstrumentState.TRANSITIONING
            return SMUInstrumentState.UNEXPECTED_OUTPUT_ON
        if self._operation in (
            SMUOperationState.BUSY,
            SMUOperationState.SHUTTING_DOWN,
        ):
            return SMUInstrumentState.TRANSITIONING
        if (
            self._ownership is SMUOwnership.IDLE
            and self._operation is SMUOperationState.READY
            and self._output_confirmed_off
        ):
            return SMUInstrumentState.READY_MANUAL
        return SMUInstrumentState.ERROR

    def _publish(self, force: bool = False) -> None:
        state = self._derive_state()
        manual_editable = state is SMUInstrumentState.READY_MANUAL
        manual_off_enabled = (
            state
            in (
                SMUInstrumentState.MANUAL_OUTPUT_ON,
                SMUInstrumentState.UNEXPECTED_OUTPUT_ON,
                SMUInstrumentState.OUTPUT_UNKNOWN,
            )
            or (
                state is SMUInstrumentState.ERROR
                and self._connected
                and self._supported
                and self._ownership
                not in (SMUOwnership.RECIPE, SMUOwnership.EMERGENCY)
            )
        )
        emergency_enabled = self._connected and self._supported
        handover_enabled = (
            state is SMUInstrumentState.AUTO_RUNNING
            and self._operation is not SMUOperationState.SHUTTING_DOWN
        )
        status_text, lock_reason = self._presentation_text(state)
        snapshot = SMUUIState(
            state=state,
            connected=self._connected,
            supported=self._supported,
            device_label=self._device_label,
            ownership=self._ownership,
            operation=self._operation,
            output_enabled=self._output_enabled,
            output_confirmed_off=self._output_confirmed_off,
            manual_editable=manual_editable,
            manual_off_enabled=manual_off_enabled,
            emergency_enabled=emergency_enabled,
            handover_enabled=handover_enabled,
            status_text=status_text,
            manual_lock_reason=lock_reason,
            output_state=self._output_state,
            fault_reason=self._control.fault_reason,
        )
        previous = self._last_state
        if previous.state is not snapshot.state:
            LOG.info(
                "SMU_UI_STATE %s -> %s owner=%s operation=%s output=%s confirmed_off=%s",
                previous.state.value,
                snapshot.state.value,
                snapshot.ownership.value,
                snapshot.operation.value,
                snapshot.output_enabled,
                snapshot.output_confirmed_off,
            )
            if snapshot.state is SMUInstrumentState.UNEXPECTED_OUTPUT_ON:
                LOG.warning(
                    "SMU_UNEXPECTED_OUTPUT_ON owner=%s operation=%s",
                    snapshot.ownership.value,
                    snapshot.operation.value,
                )
        if force or snapshot != previous:
            self._last_state = snapshot
            self.state_changed.emit(snapshot)

    def _presentation_text(
        self,
        state: SMUInstrumentState,
    ) -> tuple[str, str]:
        output = self._output_state.value
        device = self._device_label or "SMU"
        if state is SMUInstrumentState.DISCONNECTED:
            return tr("smu.state.disconnected_status"), tr("smu.state.disconnected_reason")
        if state is SMUInstrumentState.CONNECTING:
            return tr("smu.state.connecting_status"), tr("smu.state.connecting_reason")
        if state is SMUInstrumentState.EMERGENCY_STOP:
            return (
                tr("smu.state.emergency_status", device=device, output=output),
                tr("smu.state.emergency_reason"),
            )
        if state is SMUInstrumentState.AUTO_RUNNING:
            return (
                tr("smu.state.recipe_status", device=device, output=output),
                tr("smu.state.recipe_reason"),
            )
        if state is SMUInstrumentState.UNEXPECTED_OUTPUT_ON:
            return (
                tr("smu.state.unexpected_status", device=device),
                tr("smu.state.unexpected_reason"),
            )
        if state is SMUInstrumentState.OUTPUT_UNKNOWN:
            reason = self._control.fault_reason
            if "routing" in reason.casefold():
                warning = tr("smu.state.unknown_routing_reason")
            else:
                warning = tr("smu.state.unknown_output_reason")
            return (
                tr("smu.state.unknown_status", device=device),
                warning,
            )
        if state is SMUInstrumentState.MANUAL_OUTPUT_ON:
            return (
                tr("smu.state.manual_on_status", device=device),
                tr("smu.state.manual_on_reason"),
            )
        if state is SMUInstrumentState.TRANSITIONING:
            return (
                tr("smu.state.transitioning_status", device=device, output=output),
                tr("smu.state.transitioning_reason"),
            )
        if state is SMUInstrumentState.ERROR:
            if not self._supported:
                reason = tr("smu.state.unsupported_reason")
            elif not self._output_confirmed_off:
                reason = tr("smu.state.off_unconfirmed_reason")
            else:
                reason = tr("smu.state.inconsistent_reason")
            return tr("smu.state.error_status", device=device, output=output), reason
        return (
            tr("smu.state.ready_status", device=device),
            "",
        )
