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

from .smu_control import SMUReadback


class ManualSMUPanel(QWidget):
    output_requested = Signal(str, float, float)
    output_off_requested = Signal()
    emergency_off_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._recipe_active = False
        self._output_on = False

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("固定電流 CC", "CC")
        self.mode_combo.addItem("固定電壓 CV", "CV")
        self.setpoint_spin = QDoubleSpinBox()
        self.setpoint_spin.setDecimals(4)
        self.setpoint_spin.setKeyboardTracking(False)
        self.compliance_spin = QDoubleSpinBox()
        self.compliance_spin.setDecimals(4)
        self.compliance_spin.setKeyboardTracking(False)
        self.output_button = QPushButton("Output ON")
        self.off_button = QPushButton("Output OFF")
        self.emergency_button = QPushButton("緊急關閉輸出")
        self.emergency_button.setStyleSheet("background: #9b111e; color: white; font-weight: 700;")

        form = QFormLayout()
        form.addRow("輸出模式", self.mode_combo)
        form.addRow("設定值", self.setpoint_spin)
        form.addRow("Compliance", self.compliance_spin)

        buttons = QGridLayout()
        buttons.addWidget(self.output_button, 0, 0)
        buttons.addWidget(self.off_button, 0, 1)
        buttons.addWidget(self.emergency_button, 1, 0, 1, 2)

        self.requested_value = QLabel("Requested：—")
        self.factor_value = QLabel("Polarity factor：+1")
        self.actual_value = QLabel("Actual SMU command：—")
        self.voltage_value = QLabel("— V")
        self.current_value = QLabel("— mA")
        self.power_value = QLabel("— mW")
        self.output_value = QLabel("OFF")
        self.compliance_value = QLabel("—")
        self.ownership_value = QLabel("IDLE")
        readback = QFormLayout()
        readback.addRow("Requested", self.requested_value)
        readback.addRow("Polarity", self.factor_value)
        readback.addRow("Physical", self.actual_value)
        readback.addRow("實測 Voltage", self.voltage_value)
        readback.addRow("實測 Current", self.current_value)
        readback.addRow("Power", self.power_value)
        readback.addRow("Output", self.output_value)
        readback.addRow("Compliance", self.compliance_value)
        readback.addRow("Ownership", self.ownership_value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(readback)

        self.mode_combo.currentIndexChanged.connect(self._update_mode)
        self.output_button.clicked.connect(self._emit_output)
        self.off_button.clicked.connect(self.output_off_requested)
        self.emergency_button.clicked.connect(self.emergency_off_requested)
        self._update_mode()
        self._update_enabled()

    @property
    def mode(self) -> str:
        return str(self.mode_combo.currentData())

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self._output_on = False
            self.update_ownership("IDLE")
            self.output_value.setText("OFF")
        self._update_enabled()

    def set_recipe_active(self, active: bool) -> None:
        self._recipe_active = active
        self._update_enabled()

    def update_ownership(self, ownership: str) -> None:
        self.ownership_value.setText(ownership)
        self._recipe_active = ownership == "RECIPE"
        self._update_enabled()

    def update_output(self, enabled: bool) -> None:
        self._output_on = enabled
        self.output_value.setText("ON" if enabled else "OFF")
        self._update_enabled()

    def update_command(
        self, mode: str, requested: float, physical: float, compliance: float, factor: int
    ) -> None:
        unit = "V" if mode == "CV" else "mA"
        scale = 1.0 if mode == "CV" else 1000.0
        self.requested_value.setText(f"{requested * scale:+.4f} {unit}")
        self.factor_value.setText(f"{factor:+d}")
        self.actual_value.setText(f"{physical * scale:+.4f} {unit}")

    def update_readback(self, reading: SMUReadback) -> None:
        self.voltage_value.setText(f"{reading.voltage_v:+.6f} V")
        self.current_value.setText(f"{reading.current_a * 1000:+.6f} mA")
        self.power_value.setText(f"{reading.power_w * 1000:+.6f} mW")
        if reading.output_enabled is not None:
            self.update_output(reading.output_enabled)
        self.compliance_value.setText(
            "TRIPPED" if reading.compliance_tripped else
            ("正常" if reading.compliance_tripped is False else "未知")
        )

    def _update_mode(self) -> None:
        if self.mode == "CV":
            self.setpoint_spin.setRange(-5.0, 5.0)
            self.setpoint_spin.setSuffix(" V")
            self.setpoint_spin.setSingleStep(0.05)
            self.compliance_spin.setRange(0.001, 50.0)
            self.compliance_spin.setValue(min(max(self.compliance_spin.value(), 1.0), 50.0))
            self.compliance_spin.setSuffix(" mA")
        else:
            self.setpoint_spin.setRange(-50.0, 50.0)
            self.setpoint_spin.setSuffix(" mA")
            self.setpoint_spin.setSingleStep(0.1)
            self.compliance_spin.setRange(0.001, 5.0)
            self.compliance_spin.setValue(min(max(self.compliance_spin.value(), 1.0), 5.0))
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
        editable = self._connected and not self._recipe_active and not self._output_on
        self.mode_combo.setEnabled(editable)
        self.setpoint_spin.setEnabled(editable)
        self.compliance_spin.setEnabled(editable)
        self.output_button.setEnabled(editable)
        self.off_button.setEnabled(self._connected and not self._recipe_active and self._output_on)
        self.emergency_button.setEnabled(self._connected and not self._recipe_active)
