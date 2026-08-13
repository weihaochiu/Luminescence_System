from __future__ import annotations

"""Presentation-only widget for polarity-checked Manual SMU output."""

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .instrument_state_manager import SMUInstrumentState, SMUUIState
from .smu_control import (
    ManualPolarityResult,
    PolarityState,
    SMUOperationState,
    SMUOutputState,
    SMUReadback,
    SMUSafetyLimits,
)


LOG = logging.getLogger(__name__)


class ManualSMUPanel(QWidget):
    output_requested = Signal(str, str, float, float, float)
    output_off_requested = Signal()
    handover_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        limits: SMUSafetyLimits | None = None,
    ) -> None:
        super().__init__(parent)
        self._limits = limits or SMUSafetyLimits()
        self._ui_state = SMUUIState.disconnected()

        self.state_message = QLabel(self._ui_state.manual_lock_reason)
        self.state_message.setWordWrap(True)

        self.channel_combo = QComboBox()
        for channel_id in ("Ch1", "Ch2", "Ch3", "Ch4"):
            self.channel_combo.addItem(channel_id, channel_id)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("定電流密度", "CC")
        self.mode_combo.addItem("定電壓", "CV")

        self.area_spin = QDoubleSpinBox()
        self.area_spin.setDecimals(4)
        self.area_spin.setRange(0.0001, 10000.0)
        self.area_spin.setValue(1.0)
        self.area_spin.setSuffix(" cm²")
        self.area_spin.setKeyboardTracking(False)

        self.setpoint_label = QLabel("設定電流密度")
        self.setpoint_spin = QDoubleSpinBox()
        self.setpoint_spin.setDecimals(4)
        self.setpoint_spin.setKeyboardTracking(False)

        self.compliance_label = QLabel("Voltage Compliance")
        self.compliance_spin = QDoubleSpinBox()
        self.compliance_spin.setDecimals(4)
        self.compliance_spin.setKeyboardTracking(False)

        self.output_button = QPushButton("輸出")
        self.output_button.setObjectName("manualOutputToggle")
        self.handover_button = QPushButton("安全交接至手動控制")
        self.handover_button.setVisible(False)

        form = QFormLayout()
        form.addRow("輸出通道", self.channel_combo)
        form.addRow("輸出模式", self.mode_combo)
        form.addRow("元件面積", self.area_spin)
        form.addRow(self.setpoint_label, self.setpoint_spin)
        form.addRow(self.compliance_label, self.compliance_spin)

        self.output_value = QLabel("OFF")
        self.active_channel_value = QLabel("—")
        self.factor_value = QLabel("待輸出確認")
        self.voltage_value = QLabel("— V")
        self.current_density_value = QLabel("— mA/cm²")
        self.compliance_value = QLabel("—")
        self.compliance_value.setStyleSheet("color: #b3261e; font-weight: 600;")
        readback = QFormLayout()
        readback.addRow("輸出狀態", self.output_value)
        readback.addRow("目前通道", self.active_channel_value)
        readback.addRow("極性", self.factor_value)
        readback.addRow("量測電壓", self.voltage_value)
        readback.addRow("量測電流密度", self.current_density_value)
        readback.addRow("Compliance 狀態", self.compliance_value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.addWidget(self.state_message)
        layout.addLayout(form)
        layout.addWidget(self.output_button)
        layout.addWidget(self.handover_button)
        layout.addLayout(readback)

        self.mode_combo.currentIndexChanged.connect(self._update_mode)
        self.area_spin.valueChanged.connect(self._update_area_limits)
        self.output_button.clicked.connect(self._emit_toggle)
        self.handover_button.clicked.connect(self.handover_requested)
        self._update_mode()
        self._update_enabled()

    @property
    def mode(self) -> str:
        return str(self.mode_combo.currentData())

    @property
    def area_cm2(self) -> float:
        return float(self.area_spin.value())

    def apply_ui_state(self, state: SMUUIState) -> None:
        self._ui_state = state
        display_output_state = (
            state.output_state
            if state.output_state is SMUOutputState.UNKNOWN
            else SMUOutputState.ON if state.output_enabled else state.output_state
        )
        self.output_value.setText(display_output_state.value)
        if display_output_state is SMUOutputState.ON:
            self.output_button.setText("停止")
        elif display_output_state is SMUOutputState.UNKNOWN:
            self.output_button.setText("安全復歸")
        elif state.operation is SMUOperationState.BUSY:
            self.output_button.setText("正在確認極性…")
        elif state.operation is SMUOperationState.SHUTTING_DOWN:
            self.output_button.setText("停止中…")
        else:
            self.output_button.setText("輸出")
        self.state_message.setText(state.manual_lock_reason)
        if state.operation is SMUOperationState.FAULT:
            self.active_channel_value.setText("故障")
            self.factor_value.setText("待確認")
        self.setToolTip(state.manual_lock_reason)
        self._update_enabled()

    def update_sequence_status(self, message: str) -> None:
        self.state_message.setText(message)

    def update_active_channel(self, channel_state: str) -> None:
        labels = {"": "—", "SWITCHING": "切換中…", "FAULT": "故障"}
        self.active_channel_value.setText(labels.get(channel_state, channel_state))

    def update_polarity(self, result: object) -> None:
        if not isinstance(result, ManualPolarityResult):
            self.factor_value.setText("待輸出確認")
            return
        labels = {
            PolarityState.UNKNOWN: "待輸出確認",
            PolarityState.INVALID: "無效／未判定",
            PolarityState.NORMAL: "正常",
            PolarityState.REVERSED: "反向",
            PolarityState.FAILED: "確認失敗",
        }
        self.factor_value.setText(labels[result.state])
        self.voltage_value.setText(
            "— V" if result.voc_v is None else f"{result.voc_v:.4f} V"
        )
        if result.jsc_current_a is None or self.area_cm2 <= 0.0:
            self.current_density_value.setText("— mA/cm²")
        else:
            density = result.jsc_current_a * 1000.0 / self.area_cm2
            self.current_density_value.setText(f"{density:.2f} mA/cm²")

    def update_command(
        self,
        mode: str,
        requested: float,
        physical: float,
        compliance: float,
        factor: int,
    ) -> None:
        LOG.info(
            "MANUAL_SMU GUI_APPLIED mode=%s requested=%+.9g physical=%+.9g compliance=%g factor=%+d",
            mode,
            requested,
            physical,
            compliance,
            factor,
        )

    def update_readback(self, reading: SMUReadback) -> None:
        self.voltage_value.setText(
            "— V" if reading.voltage_v is None else f"{reading.voltage_v:.4f} V"
        )
        if reading.current_a is None or self.area_cm2 <= 0.0:
            self.current_density_value.setText("— mA/cm²")
        else:
            density = reading.current_a * 1000.0 / self.area_cm2
            self.current_density_value.setText(f"{density:.2f} mA/cm²")
        if reading.compliance_tripped:
            kind = "Current" if self.mode == "CV" else "Voltage"
            self.compliance_value.setText(f"⚠ {kind} Compliance Active")
        else:
            self.compliance_value.setText("—")

    def reset_for_output_off(self) -> None:
        self.factor_value.setText("待輸出確認")
        self.voltage_value.setText("— V")
        self.current_density_value.setText("— mA/cm²")
        self.compliance_value.setText("—")
        self.active_channel_value.setText("—")
        if not self._ui_state.output_enabled:
            self.output_button.setText("輸出")

    def _update_mode(self) -> None:
        limits = self._limits
        if self.mode == "CV":
            self.setpoint_label.setText("設定電壓")
            self.setpoint_spin.setRange(limits.minimum_voltage_v, limits.maximum_voltage_v)
            self.setpoint_spin.setValue(0.0)
            self.setpoint_spin.setSuffix(" V")
            self.setpoint_spin.setSingleStep(0.05)
            self.compliance_label.setText("Current Compliance")
            maximum_density = (
                limits.maximum_current_compliance_a * 1000.0 / self.area_cm2
            )
            self.compliance_spin.setRange(min(0.001, maximum_density), maximum_density)
            self.compliance_spin.setValue(min(1.0, maximum_density))
            self.compliance_spin.setSuffix(" mA/cm²")
        else:
            self.setpoint_label.setText("設定電流密度")
            maximum_density = limits.maximum_current_a * 1000.0 / self.area_cm2
            minimum_density = limits.minimum_current_a * 1000.0 / self.area_cm2
            self.setpoint_spin.setRange(minimum_density, maximum_density)
            self.setpoint_spin.setValue(0.0)
            self.setpoint_spin.setSuffix(" mA/cm²")
            self.setpoint_spin.setSingleStep(0.1)
            self.compliance_label.setText("Voltage Compliance")
            maximum_voltage_v = limits.maximum_voltage_compliance_v
            self.compliance_spin.setRange(min(0.001, maximum_voltage_v), maximum_voltage_v)
            self.compliance_spin.setValue(min(1.0, maximum_voltage_v))
            self.compliance_spin.setSuffix(" V")

    def _emit_toggle(self) -> None:
        if self._ui_state.output_enabled or self._ui_state.manual_off_enabled:
            self.output_off_requested.emit()
            return
        area = self.area_cm2
        requested = self.setpoint_spin.value()
        compliance = self.compliance_spin.value()
        if self.mode == "CC":
            requested = requested * area / 1000.0
        else:
            compliance = compliance * area / 1000.0
        self.output_requested.emit(
            str(self.channel_combo.currentData()),
            self.mode,
            requested,
            compliance,
            area,
        )

    def _update_area_limits(self, _area: float) -> None:
        limits = self._limits
        if self.mode == "CC":
            self.setpoint_spin.setRange(
                limits.minimum_current_a * 1000.0 / self.area_cm2,
                limits.maximum_current_a * 1000.0 / self.area_cm2,
            )
        else:
            maximum_density = (
                limits.maximum_current_compliance_a * 1000.0 / self.area_cm2
            )
            self.compliance_spin.setRange(min(0.001, maximum_density), maximum_density)

    def _update_enabled(self) -> None:
        editable = self._ui_state.manual_editable
        self.channel_combo.setEnabled(editable)
        self.mode_combo.setEnabled(editable)
        self.area_spin.setEnabled(editable)
        self.setpoint_spin.setEnabled(editable)
        self.compliance_spin.setEnabled(editable)
        self.output_button.setEnabled(editable or self._ui_state.manual_off_enabled)
        show_handover = self._ui_state.state is SMUInstrumentState.AUTO_RUNNING
        self.handover_button.setVisible(show_handover)
        self.handover_button.setEnabled(self._ui_state.handover_enabled)
