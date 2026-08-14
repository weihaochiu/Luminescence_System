from __future__ import annotations

"""Application-wide SMU and measurement watchdog safety settings."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout

from .smu_control import SMUSafetyLimits, SMUSafetyService


def load_global_safety(settings: QSettings) -> tuple[SMUSafetyLimits, float, float]:
    defaults = SMUSafetyLimits()
    limits = SMUSafetyLimits(
        minimum_voltage_v=float(settings.value("safety/minimum_voltage_v", defaults.minimum_voltage_v)),
        maximum_voltage_v=float(settings.value("safety/maximum_voltage_v", defaults.maximum_voltage_v)),
        minimum_current_a=float(settings.value("safety/minimum_current_a", defaults.minimum_current_a)),
        maximum_current_a=float(settings.value("safety/maximum_current_a", defaults.maximum_current_a)),
        maximum_power_w=float(settings.value("safety/maximum_power_w", defaults.maximum_power_w)),
        maximum_voltage_compliance_v=float(settings.value(
            "safety/maximum_voltage_compliance_v", defaults.maximum_voltage_compliance_v
        )),
        maximum_current_compliance_a=float(settings.value(
            "safety/maximum_current_compliance_a", defaults.maximum_current_compliance_a
        )),
    )
    return (
        limits,
        float(settings.value("safety/max_recipe_time_s", 1800.0)),
        float(settings.value("safety/max_output_time_s", 600.0)),
    )


class SMUSafetyDialog(QDialog):
    def __init__(
        self,
        safety: SMUSafetyService,
        settings: QSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.safety = safety
        self.settings = settings
        self.setWindowTitle("安全 / SMU")
        form = QFormLayout(self)
        limits, max_recipe, max_output = load_global_safety(settings)
        self.max_voltage = self._spin(0.001, 210, limits.maximum_voltage_v, " V")
        self.max_current = self._spin(0.001, 10000, limits.maximum_current_a * 1000, " mA")
        self.max_power = self._spin(0.001, 1_000_000, limits.maximum_power_w * 1000, " mW")
        self.max_voltage_compliance = self._spin(
            0.001, 210, limits.maximum_voltage_compliance_v, " V"
        )
        self.max_current_compliance = self._spin(
            0.001, 10000, limits.maximum_current_compliance_a * 1000, " mA"
        )
        self.max_recipe_time = self._spin(0.1, 86400, max_recipe, " s")
        self.max_output_time = self._spin(0.1, 86400, max_output, " s")
        form.addRow("最大允許電壓", self.max_voltage)
        form.addRow("最大允許電流", self.max_current)
        form.addRow("最大允許功率", self.max_power)
        form.addRow("最大 Voltage compliance", self.max_voltage_compliance)
        form.addRow("最大 Current compliance", self.max_current_compliance)
        form.addRow("單次 Recipe 最長時間", self.max_recipe_time)
        form.addRow("單一 J OUTPUT 最長時間", self.max_output_time)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def _spin(minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(6)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    def _save(self) -> None:
        maximum_voltage = self.max_voltage.value()
        maximum_current_a = self.max_current.value() / 1000.0
        limits = SMUSafetyLimits(
            minimum_voltage_v=-maximum_voltage,
            maximum_voltage_v=maximum_voltage,
            minimum_current_a=-maximum_current_a,
            maximum_current_a=maximum_current_a,
            maximum_power_w=self.max_power.value() / 1000.0,
            maximum_voltage_compliance_v=self.max_voltage_compliance.value(),
            maximum_current_compliance_a=self.max_current_compliance.value() / 1000.0,
        )
        values = {
            "minimum_voltage_v": limits.minimum_voltage_v,
            "maximum_voltage_v": limits.maximum_voltage_v,
            "minimum_current_a": limits.minimum_current_a,
            "maximum_current_a": limits.maximum_current_a,
            "maximum_power_w": limits.maximum_power_w,
            "maximum_voltage_compliance_v": limits.maximum_voltage_compliance_v,
            "maximum_current_compliance_a": limits.maximum_current_compliance_a,
        }
        for key, value in values.items():
            self.settings.setValue(f"safety/{key}", value)
        self.settings.setValue("safety/max_recipe_time_s", self.max_recipe_time.value())
        self.settings.setValue("safety/max_output_time_s", self.max_output_time.value())
        self.settings.sync()
        self.safety.limits = limits
        self.accept()
