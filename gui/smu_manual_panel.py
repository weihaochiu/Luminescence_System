from __future__ import annotations

"""Presentation-only widget for fixed CV/CC manual SMU output."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .instrument_state_manager import SMUInstrumentState, SMUUIState
from .smu_control import SMUOperationState, SMUReadback, SMUSafetyLimits


class ManualSMUPanel(QWidget):
    output_requested = Signal(str, float, float)
    output_off_requested = Signal()
    emergency_off_requested = Signal()
    handover_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        limits: SMUSafetyLimits | None = None,
    ) -> None:
        super().__init__(parent)
        self._limits = limits or SMUSafetyLimits()
        self._ui_state = SMUUIState.disconnected()

        self.coordinate_note = QLabel(
            "手動輸入使用 SMU 實體座標；不套用 Device Polarity。"
        )
        self.coordinate_note.setWordWrap(True)
        self.state_message = QLabel(self._ui_state.manual_lock_reason)
        self.state_message.setWordWrap(True)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("定電流 CC", "CC")
        self.mode_combo.addItem("定電壓 CV", "CV")
        self.setpoint_spin = QDoubleSpinBox()
        self.setpoint_spin.setDecimals(4)
        self.setpoint_spin.setKeyboardTracking(False)
        self.compliance_spin = QDoubleSpinBox()
        self.compliance_spin.setDecimals(4)
        self.compliance_spin.setKeyboardTracking(False)
        self.output_button = QPushButton("Output ON")
        self.off_button = QPushButton("Output OFF")
        self.handover_button = QPushButton("安全交接至手動控制")
        self.handover_button.setVisible(False)
        self.emergency_button = QPushButton("Emergency OFF")
        self.emergency_button.setStyleSheet(
            "background: #9b111e; color: white; font-weight: 700;"
        )

        form = QFormLayout()
        form.addRow("輸出模式", self.mode_combo)
        form.addRow("設定值", self.setpoint_spin)
        form.addRow("Compliance", self.compliance_spin)

        buttons = QGridLayout()
        buttons.addWidget(self.output_button, 0, 0)
        buttons.addWidget(self.off_button, 0, 1)
        buttons.addWidget(self.handover_button, 1, 0, 1, 2)
        buttons.addWidget(self.emergency_button, 2, 0, 1, 2)

        self.requested_value = QLabel("—")
        self.factor_value = QLabel("UNKNOWN")
        self.actual_value = QLabel("—")
        self.voltage_value = QLabel("— V")
        self.current_value = QLabel("— mA")
        self.power_value = QLabel("— mW")
        self.output_value = QLabel("OFF")
        self.compliance_value = QLabel("—")
        self.ownership_value = QLabel("IDLE")
        self.operation_value = QLabel(SMUOperationState.READY.value)
        readback = QFormLayout()
        readback.addRow("Manual request", self.requested_value)
        readback.addRow("Recipe Polarity", self.factor_value)
        readback.addRow("Physical SMU command", self.actual_value)
        readback.addRow("Measured Voltage", self.voltage_value)
        readback.addRow("Measured Current", self.current_value)
        readback.addRow("Power", self.power_value)
        readback.addRow("Output", self.output_value)
        readback.addRow("Compliance", self.compliance_value)
        readback.addRow("Ownership", self.ownership_value)
        readback.addRow("Operation state", self.operation_value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.addWidget(self.coordinate_note)
        layout.addWidget(self.state_message)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(readback)

        self.mode_combo.currentIndexChanged.connect(self._update_mode)
        self.output_button.clicked.connect(self._emit_output)
        self.off_button.clicked.connect(self.output_off_requested)
        self.handover_button.clicked.connect(self.handover_requested)
        self.emergency_button.clicked.connect(self.emergency_off_requested)
        self._update_mode()
        self._update_enabled()

    @property
    def mode(self) -> str:
        return str(self.mode_combo.currentData())

    def apply_ui_state(self, state: SMUUIState) -> None:
        self._ui_state = state
        self.ownership_value.setText(state.ownership.value)
        self.operation_value.setText(state.operation.value)
        self.output_value.setText("ON" if state.output_enabled else "OFF")
        self.state_message.setText(state.manual_lock_reason)
        self.setToolTip(state.manual_lock_reason)
        self._update_enabled()

    def update_polarity(self, factor: object) -> None:
        self.factor_value.setText("UNKNOWN" if factor is None else f"{int(factor):+d}")

    def update_command(
        self,
        mode: str,
        requested: float,
        physical: float,
        compliance: float,
        factor: int,
    ) -> None:
        del compliance, factor
        unit = "V" if mode == "CV" else "mA"
        scale = 1.0 if mode == "CV" else 1000.0
        self.requested_value.setText(f"{requested * scale:+.4f} {unit}")
        self.actual_value.setText(f"{physical * scale:+.4f} {unit}")

    def update_readback(self, reading: SMUReadback) -> None:
        self.voltage_value.setText(f"{reading.voltage_v:+.6f} V")
        self.current_value.setText(f"{reading.current_a * 1000:+.6f} mA")
        self.power_value.setText(f"{reading.power_w * 1000:+.6f} mW")
        # Output presentation is intentionally updated only by SMUUIState.
        self.compliance_value.setText(
            "TRIPPED"
            if reading.compliance_tripped
            else ("正常" if reading.compliance_tripped is False else "未知")
        )

    def _update_mode(self) -> None:
        limits = self._limits
        if self.mode == "CV":
            self.setpoint_spin.setRange(limits.minimum_voltage_v, limits.maximum_voltage_v)
            self.setpoint_spin.setValue(0.0)
            self.setpoint_spin.setSuffix(" V")
            self.setpoint_spin.setSingleStep(0.05)
            maximum_current_ma = limits.maximum_current_compliance_a * 1000.0
            self.compliance_spin.setRange(min(0.001, maximum_current_ma), maximum_current_ma)
            self.compliance_spin.setValue(min(1.0, maximum_current_ma))
            self.compliance_spin.setSuffix(" mA")
        else:
            self.setpoint_spin.setRange(
                limits.minimum_current_a * 1000.0,
                limits.maximum_current_a * 1000.0,
            )
            self.setpoint_spin.setValue(0.0)
            self.setpoint_spin.setSuffix(" mA")
            self.setpoint_spin.setSingleStep(0.1)
            maximum_voltage_v = limits.maximum_voltage_compliance_v
            self.compliance_spin.setRange(min(0.001, maximum_voltage_v), maximum_voltage_v)
            self.compliance_spin.setValue(min(1.0, maximum_voltage_v))
            self.compliance_spin.setSuffix(" V")

    def _emit_output(self) -> None:
        requested = self.setpoint_spin.value()
        compliance = self.compliance_spin.value()
        if self.mode == "CC":
            requested /= 1000.0
        else:
            compliance /= 1000.0
        self.output_requested.emit(self.mode, requested, compliance)

    def _update_enabled(self) -> None:
        editable = self._ui_state.manual_editable
        self.mode_combo.setEnabled(editable)
        self.setpoint_spin.setEnabled(editable)
        self.compliance_spin.setEnabled(editable)
        self.output_button.setEnabled(editable)
        self.off_button.setEnabled(self._ui_state.manual_off_enabled)
        self.emergency_button.setEnabled(self._ui_state.emergency_enabled)
        show_handover = self._ui_state.state is SMUInstrumentState.AUTO_RUNNING
        self.handover_button.setVisible(show_handover)
        self.handover_button.setEnabled(self._ui_state.handover_enabled)
