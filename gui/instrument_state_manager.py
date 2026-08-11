from __future__ import annotations

"""Unified high-level SMU state and UI enablement policy."""

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, Signal

from .smu_control import SMUControlManager, SMUOperationState, SMUOwnership


class SMUInstrumentState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY_MANUAL = "READY_MANUAL"
    AUTO_RUNNING = "AUTO_RUNNING"
    ERROR = "ERROR"
    EMERGENCY_STOP = "EMERGENCY_STOP"


@dataclass(frozen=True)
class SMUUIState:
    """Complete presentation policy derived from connection and control state."""

    state: SMUInstrumentState
    connected: bool
    supported: bool
    device_label: str
    ownership: SMUOwnership
    operation: SMUOperationState
    output_enabled: bool
    manual_editable: bool
    manual_off_enabled: bool
    emergency_enabled: bool
    status_text: str
    manual_lock_reason: str

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
            manual_editable=False,
            manual_off_enabled=False,
            emergency_enabled=False,
            status_text="SMU 未連線",
            manual_lock_reason="請先連線支援的 SMU。",
        )


class InstrumentStateManager(QObject):
    """Single source of truth for SMU state shown by every GUI surface.

    The lower-level :class:`SMUControlManager` remains authoritative for hardware
    ownership and safety.  This class combines that state with the asynchronous
    connection lifecycle and exposes one immutable UI policy.
    """

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
        self._last_state = SMUUIState.disconnected()

        control.ownership_changed.connect(self.update_ownership)
        control.operation_state_changed.connect(self.update_operation_state)
        control.output_changed.connect(self.update_output)

    @property
    def current(self) -> SMUUIState:
        return self._last_state

    def refresh(self) -> None:
        self._publish()

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
        self._publish()

    def set_disconnected(self) -> None:
        self._connection_state = SMUInstrumentState.DISCONNECTED
        self._connected = False
        self._supported = False
        self._device_label = ""
        self._ownership = SMUOwnership.IDLE
        self._operation = SMUOperationState.READY
        self._output_enabled = False
        self._publish()

    def set_connection_error(self, message: str = "") -> None:
        self._connection_state = SMUInstrumentState.ERROR
        self._connected = False
        self._supported = False
        self._device_label = message.strip()
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
        self._publish()

    def _derive_state(self) -> SMUInstrumentState:
        if self._connection_state is SMUInstrumentState.CONNECTING:
            return SMUInstrumentState.CONNECTING
        if self._connection_state is SMUInstrumentState.ERROR and not self._connected:
            return SMUInstrumentState.ERROR
        if not self._connected:
            return SMUInstrumentState.DISCONNECTED
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
        if (
            self._ownership is SMUOwnership.RECIPE
            or self._operation is SMUOperationState.RECIPE_LOCKED
        ):
            return SMUInstrumentState.AUTO_RUNNING
        return SMUInstrumentState.READY_MANUAL

    def _publish(self) -> None:
        state = self._derive_state()
        manual_editable = (
            state is SMUInstrumentState.READY_MANUAL
            and self._supported
            and self._ownership is SMUOwnership.IDLE
            and self._operation is SMUOperationState.READY
            and not self._output_enabled
        )
        manual_off_enabled = (
            state is SMUInstrumentState.READY_MANUAL
            and self._supported
            and self._ownership is SMUOwnership.MANUAL
            and self._operation is SMUOperationState.OUTPUT_ON
            and self._output_enabled
        )
        emergency_enabled = (
            self._connected
            and self._supported
            and state is not SMUInstrumentState.EMERGENCY_STOP
        )
        status_text, lock_reason = self._presentation_text(state, manual_editable)
        self._last_state = SMUUIState(
            state=state,
            connected=self._connected,
            supported=self._supported,
            device_label=self._device_label,
            ownership=self._ownership,
            operation=self._operation,
            output_enabled=self._output_enabled,
            manual_editable=manual_editable,
            manual_off_enabled=manual_off_enabled,
            emergency_enabled=emergency_enabled,
            status_text=status_text,
            manual_lock_reason=lock_reason,
        )
        self.state_changed.emit(self._last_state)

    def _presentation_text(
        self,
        state: SMUInstrumentState,
        manual_editable: bool,
    ) -> tuple[str, str]:
        output = "ON" if self._output_enabled else "OFF"
        device = self._device_label or "SMU"
        if state is SMUInstrumentState.DISCONNECTED:
            return "SMU 未連線", "請先連線支援的 SMU。"
        if state is SMUInstrumentState.CONNECTING:
            return "SMU 連線與安全初始化中…", "正在連線並確認 OUTPUT OFF。"
        if state is SMUInstrumentState.ERROR:
            return f"{device}｜錯誤／不安全狀態｜OUTPUT：{output}", "SMU 處於錯誤或未確認安全狀態。"
        if state is SMUInstrumentState.EMERGENCY_STOP:
            return f"{device}｜Emergency Stop｜OUTPUT：{output}", "Emergency Stop 正在執行或尚未安全完成。"
        if state is SMUInstrumentState.AUTO_RUNNING:
            return f"{device}｜自動量測控制中｜OUTPUT：{output}", "Recipe／自動量測目前擁有 SMU 控制權。"
        if not self._supported:
            return f"{device}｜不支援手動輸出｜OUTPUT：{output}", "目前連線的 VISA 儀器不受支援。"
        if manual_editable:
            return f"{device}｜手動控制可用｜OUTPUT：{output}", ""
        if self._operation is SMUOperationState.BUSY:
            reason = "手動 SMU 命令執行中。"
        elif self._operation is SMUOperationState.SHUTTING_DOWN:
            reason = "正在安全歸零並關閉輸出。"
        elif self._ownership is SMUOwnership.MANUAL and self._output_enabled:
            reason = "手動輸出已開啟；請先執行 Output OFF。"
        elif self._output_enabled:
            reason = "偵測到 OUTPUT ON；請使用安全關閉或 Emergency Stop。"
        else:
            reason = "SMU 控制狀態正在同步。"
        return f"{device}｜{reason.rstrip('。')}｜OUTPUT：{output}", reason
