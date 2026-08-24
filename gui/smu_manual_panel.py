from __future__ import annotations

"""Presentation-only widget for polarity-checked Manual SMU output."""

import logging
from typing import Any, Callable

from PySide6.QtCore import QSignalBlocker, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import i18n, tr

from .instrument_state_manager import SMUInstrumentState, SMUUIState
from .manual_smu_settings import (
    MANUAL_SMU_CHANNELS,
    ManualSMUSettings,
    ManualSMUSettingsStore,
)
from .smu_control import (
    ManualPolarityResult,
    PolarityState,
    SMUOperationState,
    SMUOutputState,
    SMUReadback,
    SMUSafetyLimits,
)


LOG = logging.getLogger(__name__)

PERSISTENCE_DEBOUNCE_INTERVAL_MS = 300
PERSISTENCE_RETRY_INTERVAL_MS = 2000


class ManualSMUPanel(QWidget):
    output_requested = Signal(str, str, float, float, float)
    output_off_requested = Signal()
    handover_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        limits: SMUSafetyLimits | None = None,
        settings: Any | None = None,
        settings_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._limits = limits or SMUSafetyLimits()
        self._ui_state = SMUUIState.disconnected()
        self._settings_store = (
            ManualSMUSettingsStore(
                settings,
                settings_factory=settings_factory,
            )
            if settings is not None
            else None
        )
        self._settings_dirty = False

        self.state_message = QLabel(self._ui_state.manual_lock_reason)
        self.state_message.setWordWrap(True)

        self.channel_combo = QComboBox()
        for channel_id in MANUAL_SMU_CHANNELS:
            self.channel_combo.addItem(channel_id, channel_id)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("smu.constant_current_density"), "CC")
        self.mode_combo.addItem(tr("smu.constant_voltage"), "CV")

        self.area_spin = QDoubleSpinBox()
        self.area_spin.setDecimals(4)
        self.area_spin.setRange(0.0001, 10000.0)
        self.area_spin.setValue(1.0)
        self.area_spin.setSuffix(" cm²")
        self.area_spin.setKeyboardTracking(False)

        self.setpoint_label = QLabel(tr("smu.set_current_density"))
        self.setpoint_spin = QDoubleSpinBox()
        self.setpoint_spin.setDecimals(4)
        self.setpoint_spin.setKeyboardTracking(False)

        self.compliance_label = QLabel(tr("smu.voltage_compliance"))
        self.compliance_spin = QDoubleSpinBox()
        self.compliance_spin.setDecimals(4)
        self.compliance_spin.setKeyboardTracking(False)

        self.output_button = QPushButton(tr("smu.output"))
        self.output_button.setObjectName("manualOutputToggle")
        self.handover_button = QPushButton(tr("smu.safe_handover_manual"))
        self.handover_button.setVisible(False)

        self.form = QFormLayout()
        self.form.addRow(tr("smu.output_channel"), self.channel_combo)
        self.form.addRow(tr("smu.output_mode"), self.mode_combo)
        self.form.addRow(tr("smu.device_area"), self.area_spin)
        self.form.addRow(self.setpoint_label, self.setpoint_spin)
        self.form.addRow(self.compliance_label, self.compliance_spin)

        self.output_value = QLabel("OFF")
        self.active_channel_value = QLabel("—")
        self.factor_value = QLabel(tr("smu.awaiting_output_confirmation"))
        self.voltage_value = QLabel("— V")
        self.current_density_value = QLabel("— mA/cm²")
        self.compliance_value = QLabel("—")
        self.compliance_value.setStyleSheet("color: #b3261e; font-weight: 600;")
        self.readback_form = QFormLayout()
        self.readback_form.addRow(tr("smu.output_status"), self.output_value)
        self.readback_form.addRow(tr("smu.channel_current"), self.active_channel_value)
        self.readback_form.addRow(tr("smu.polarity"), self.factor_value)
        self.readback_form.addRow(tr("smu.voltage_measured"), self.voltage_value)
        self.readback_form.addRow(tr("smu.current_density_measured"), self.current_density_value)
        self.readback_form.addRow(tr("smu.compliance_status"), self.compliance_value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.addWidget(self.state_message)
        layout.addLayout(self.form)
        layout.addWidget(self.output_button)
        layout.addWidget(self.handover_button)
        layout.addLayout(self.readback_form)

        self.output_button.clicked.connect(self._emit_toggle)
        self.handover_button.clicked.connect(self.handover_requested)
        self._active_mode = "CC"
        self._mode_values = {
            "CC": [0.0, 1.0],
            "CV": [0.0, 1.0],
        }
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(PERSISTENCE_DEBOUNCE_INTERVAL_MS)
        self._save_timer.timeout.connect(self._flush_persistent_settings_from_timer)

        self._configure_mode_widgets(self._active_mode)
        self._apply_mode_values(self._active_mode)
        self.restore_persistent_settings()

        self.mode_combo.currentIndexChanged.connect(self._update_mode)
        self.area_spin.valueChanged.connect(self._update_area_limits)
        self.channel_combo.currentIndexChanged.connect(self._schedule_settings_save)
        self.setpoint_spin.valueChanged.connect(self._on_mode_value_changed)
        self.compliance_spin.valueChanged.connect(self._on_mode_value_changed)
        self._update_enabled()
        i18n.language_changed.connect(self.retranslate)

    def retranslate(self, _language: str = "") -> None:
        blocker = QSignalBlocker(self.mode_combo)
        self.mode_combo.setItemText(self.mode_combo.findData("CC"), tr("smu.constant_current_density"))
        self.mode_combo.setItemText(self.mode_combo.findData("CV"), tr("smu.constant_voltage"))
        del blocker
        form_keys = (
            (self.channel_combo, "smu.output_channel"),
            (self.mode_combo, "smu.output_mode"),
            (self.area_spin, "smu.device_area"),
        )
        for field, key in form_keys:
            label = self.form.labelForField(field)
            if isinstance(label, QLabel):
                label.setText(tr(key))
        readback_keys = (
            (self.output_value, "smu.output_status"),
            (self.active_channel_value, "smu.channel_current"),
            (self.factor_value, "smu.polarity"),
            (self.voltage_value, "smu.voltage_measured"),
            (self.current_density_value, "smu.current_density_measured"),
            (self.compliance_value, "smu.compliance_status"),
        )
        for field, key in readback_keys:
            label = self.readback_form.labelForField(field)
            if isinstance(label, QLabel):
                label.setText(tr(key))
        self.handover_button.setText(tr("smu.safe_handover_manual"))
        self._configure_mode_widgets(self.mode)
        self.apply_ui_state(self._ui_state)

    @property
    def mode(self) -> str:
        return str(self.mode_combo.currentData())

    @property
    def area_cm2(self) -> float:
        return float(self.area_spin.value())

    @property
    def persistent_settings_dirty(self) -> bool:
        return self._settings_dirty

    def apply_ui_state(self, state: SMUUIState) -> None:
        self._ui_state = state
        display_output_state = (
            state.output_state
            if state.output_state is SMUOutputState.UNKNOWN
            else SMUOutputState.ON if state.output_enabled else state.output_state
        )
        self.output_value.setText(display_output_state.value)
        if display_output_state is SMUOutputState.ON:
            self.output_button.setText(tr("common.stop"))
        elif display_output_state is SMUOutputState.UNKNOWN:
            self.output_button.setText(tr("smu.safe_recovery"))
        elif state.operation is SMUOperationState.BUSY:
            self.output_button.setText(tr("smu.confirming_polarity"))
        elif state.operation is SMUOperationState.SHUTTING_DOWN:
            self.output_button.setText(tr("common.stopping"))
        else:
            self.output_button.setText(tr("smu.output"))
        self.state_message.setText(state.manual_lock_reason)
        if state.operation is SMUOperationState.FAULT:
            self.active_channel_value.setText(tr("common.fault"))
            self.factor_value.setText(tr("common.pending_confirmation"))
        self.setToolTip(state.manual_lock_reason)
        self._update_enabled()

    def update_sequence_status(self, message: str) -> None:
        self.state_message.setText(message)

    def update_active_channel(self, channel_state: str) -> None:
        labels = {"": "—", "SWITCHING": tr("common.switching"), "FAULT": tr("common.fault")}
        self.active_channel_value.setText(labels.get(channel_state, channel_state))

    def update_polarity(self, result: object) -> None:
        if not isinstance(result, ManualPolarityResult):
            self.factor_value.setText(tr("smu.awaiting_output_confirmation"))
            return
        labels = {
            PolarityState.UNKNOWN: tr("smu.polarity_unknown"),
            PolarityState.INVALID: tr("smu.polarity_invalid"),
            PolarityState.NORMAL: tr("smu.polarity_normal"),
            PolarityState.REVERSED: tr("smu.polarity_reversed"),
            PolarityState.FAILED: tr("smu.polarity_failed"),
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
            kind = tr("smu.current") if self.mode == "CV" else tr("smu.voltage")
            self.compliance_value.setText(tr("smu.compliance_active", kind=kind))
        else:
            self.compliance_value.setText("—")

    def reset_for_output_off(self) -> None:
        self.factor_value.setText(tr("smu.awaiting_output_confirmation"))
        self.voltage_value.setText("— V")
        self.current_density_value.setText("— mA/cm²")
        self.compliance_value.setText("—")
        self.active_channel_value.setText("—")
        if not self._ui_state.output_enabled:
            self.output_button.setText(tr("smu.output"))

    def _update_mode(self) -> None:
        new_mode = self.mode
        if new_mode == self._active_mode:
            return
        self._capture_mode_values(self._active_mode)
        self._active_mode = new_mode
        self._configure_mode_widgets(new_mode)
        self._apply_mode_values(new_mode)
        self._schedule_settings_save()

    def _configure_mode_widgets(self, mode: str) -> None:
        limits = self._limits
        blockers = (
            QSignalBlocker(self.setpoint_spin),
            QSignalBlocker(self.compliance_spin),
        )
        if mode == "CV":
            self.setpoint_label.setText(tr("smu.set_voltage"))
            self.setpoint_spin.setRange(limits.minimum_voltage_v, limits.maximum_voltage_v)
            self.setpoint_spin.setSuffix(" V")
            self.setpoint_spin.setSingleStep(0.05)
            self.compliance_label.setText(tr("smu.current_compliance"))
            maximum_density = (
                limits.maximum_current_compliance_a * 1000.0 / self.area_cm2
            )
            self.compliance_spin.setRange(min(0.001, maximum_density), maximum_density)
            self.compliance_spin.setSuffix(" mA/cm²")
        else:
            self.setpoint_label.setText(tr("smu.set_current_density"))
            maximum_density = limits.maximum_current_a * 1000.0 / self.area_cm2
            minimum_density = limits.minimum_current_a * 1000.0 / self.area_cm2
            self.setpoint_spin.setRange(minimum_density, maximum_density)
            self.setpoint_spin.setSuffix(" mA/cm²")
            self.setpoint_spin.setSingleStep(0.1)
            self.compliance_label.setText(tr("smu.voltage_compliance"))
            maximum_voltage_v = limits.maximum_voltage_compliance_v
            self.compliance_spin.setRange(min(0.001, maximum_voltage_v), maximum_voltage_v)
            self.compliance_spin.setSuffix(" V")
        del blockers

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
        self._capture_mode_values(self._active_mode)
        for mode in self._mode_values:
            self._mode_values[mode] = list(
                self._clamp_mode_values(mode, *self._mode_values[mode])
            )
        self._configure_mode_widgets(self._active_mode)
        self._apply_mode_values(self._active_mode)
        self._schedule_settings_save()

    def _on_mode_value_changed(self, _value: float) -> None:
        self._capture_mode_values(self._active_mode)
        self._schedule_settings_save()

    def _capture_mode_values(self, mode: str) -> None:
        if mode not in self._mode_values:
            return
        self._mode_values[mode] = [
            float(self.setpoint_spin.value()),
            float(self.compliance_spin.value()),
        ]

    def _apply_mode_values(self, mode: str) -> None:
        setpoint, compliance = self._clamp_mode_values(
            mode,
            *self._mode_values[mode],
        )
        self._mode_values[mode] = [setpoint, compliance]
        blockers = (
            QSignalBlocker(self.setpoint_spin),
            QSignalBlocker(self.compliance_spin),
        )
        self.setpoint_spin.setValue(setpoint)
        self.compliance_spin.setValue(compliance)
        del blockers

    def _clamp_mode_values(
        self,
        mode: str,
        setpoint: float,
        compliance: float,
    ) -> tuple[float, float]:
        limits = self._limits
        if mode == "CV":
            setpoint_minimum = limits.minimum_voltage_v
            setpoint_maximum = limits.maximum_voltage_v
            compliance_maximum = (
                limits.maximum_current_compliance_a * 1000.0 / self.area_cm2
            )
        else:
            setpoint_minimum = limits.minimum_current_a * 1000.0 / self.area_cm2
            setpoint_maximum = limits.maximum_current_a * 1000.0 / self.area_cm2
            compliance_maximum = limits.maximum_voltage_compliance_v
        compliance_minimum = min(0.001, compliance_maximum)
        return (
            min(max(float(setpoint), setpoint_minimum), setpoint_maximum),
            min(max(float(compliance), compliance_minimum), compliance_maximum),
        )

    def _apply_persistent_settings(self, saved: ManualSMUSettings) -> None:
        blockers = (
            QSignalBlocker(self.channel_combo),
            QSignalBlocker(self.mode_combo),
            QSignalBlocker(self.area_spin),
        )
        self.area_spin.setValue(saved.area_cm2)
        channel_index = self.channel_combo.findData(saved.channel)
        self.channel_combo.setCurrentIndex(max(0, channel_index))
        self._mode_values = {
            "CC": [
                saved.cc_current_density_ma_cm2,
                saved.cc_voltage_compliance_v,
            ],
            "CV": [
                saved.cv_voltage_v,
                saved.cv_current_compliance_ma_cm2,
            ],
        }
        for mode in self._mode_values:
            self._mode_values[mode] = list(
                self._clamp_mode_values(mode, *self._mode_values[mode])
            )
        mode_index = self.mode_combo.findData(saved.mode)
        self.mode_combo.setCurrentIndex(max(0, mode_index))
        self._active_mode = self.mode
        self._configure_mode_widgets(self._active_mode)
        self._apply_mode_values(self._active_mode)
        del blockers

    def _settings_snapshot(self) -> ManualSMUSettings:
        self._capture_mode_values(self._active_mode)
        return ManualSMUSettings(
            channel=str(self.channel_combo.currentData()),
            mode=self.mode,
            area_cm2=self.area_cm2,
            cc_current_density_ma_cm2=self._mode_values["CC"][0],
            cc_voltage_compliance_v=self._mode_values["CC"][1],
            cv_voltage_v=self._mode_values["CV"][0],
            cv_current_compliance_ma_cm2=self._mode_values["CV"][1],
        )

    def _schedule_settings_save(self, _value: object = None) -> None:
        if self._settings_store is not None:
            self._settings_dirty = True
            self._save_timer.start(PERSISTENCE_DEBOUNCE_INTERVAL_MS)

    def flush_persistent_settings(self) -> None:
        if self._settings_store is None:
            return
        self._save_timer.stop()
        try:
            self._settings_store.save(self._settings_snapshot())
        except Exception:
            self._settings_dirty = True
            self._save_timer.start(PERSISTENCE_RETRY_INTERVAL_MS)
            raise
        self._settings_dirty = False

    def _flush_persistent_settings_from_timer(self) -> None:
        try:
            self.flush_persistent_settings()
        except Exception:
            LOG.exception("Manual SMU settings save failed")

    def restore_persistent_settings(self) -> None:
        """Restore only validated Manual SMU input parameters into the GUI."""

        if self._settings_store is not None:
            self._save_timer.stop()
            self._apply_persistent_settings(self._settings_store.load())
            self._settings_dirty = False

    def reset_persistent_settings(self) -> None:
        """Reset input parameters without changing any SMU or Relay state."""

        self._apply_persistent_settings(ManualSMUSettings())
        self._settings_dirty = self._settings_store is not None
        self.flush_persistent_settings()

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
