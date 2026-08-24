from __future__ import annotations

"""Validated QSettings persistence for Manual SMU input parameters only."""

from dataclasses import dataclass
import math
from typing import Any

from PySide6.QtCore import QSettings


MANUAL_SMU_CHANNELS = ("Ch1", "Ch2", "Ch3", "Ch4")
MANUAL_SMU_MODES = ("CC", "CV")

CHANNEL_KEY = "manual_smu/channel"
MODE_KEY = "manual_smu/mode"
AREA_CM2_KEY = "manual_smu/area_cm2"
CC_CURRENT_DENSITY_KEY = "manual_smu/cc/current_density_ma_cm2"
CC_VOLTAGE_COMPLIANCE_KEY = "manual_smu/cc/voltage_compliance_v"
CV_VOLTAGE_KEY = "manual_smu/cv/voltage_v"
CV_CURRENT_COMPLIANCE_KEY = "manual_smu/cv/current_compliance_ma_cm2"


class ManualSMUSettingsWriteError(RuntimeError):
    """Raised when Qt reports that Manual SMU settings were not persisted."""


@dataclass(frozen=True)
class ManualSMUSettings:
    """Operator-entered values; deliberately excludes all hardware state."""

    channel: str = "Ch1"
    mode: str = "CC"
    area_cm2: float = 1.0
    cc_current_density_ma_cm2: float = 0.0
    cc_voltage_compliance_v: float = 1.0
    cv_voltage_v: float = 0.0
    cv_current_compliance_ma_cm2: float = 1.0


class ManualSMUSettingsStore:
    """Read and write the Manual SMU parameter namespace in QSettings."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def load(self) -> ManualSMUSettings:
        defaults = ManualSMUSettings()
        channel = str(self._settings.value(CHANNEL_KEY, defaults.channel))
        if channel not in MANUAL_SMU_CHANNELS:
            channel = defaults.channel
        mode = str(self._settings.value(MODE_KEY, defaults.mode))
        if mode not in MANUAL_SMU_MODES:
            mode = defaults.mode
        area_cm2 = self._finite_value(AREA_CM2_KEY, defaults.area_cm2)
        if area_cm2 <= 0.0:
            area_cm2 = defaults.area_cm2
        cc_voltage_compliance_v = self._finite_value(
            CC_VOLTAGE_COMPLIANCE_KEY,
            defaults.cc_voltage_compliance_v,
        )
        if cc_voltage_compliance_v <= 0.0:
            cc_voltage_compliance_v = defaults.cc_voltage_compliance_v
        cv_current_compliance_ma_cm2 = self._finite_value(
            CV_CURRENT_COMPLIANCE_KEY,
            defaults.cv_current_compliance_ma_cm2,
        )
        if cv_current_compliance_ma_cm2 <= 0.0:
            cv_current_compliance_ma_cm2 = defaults.cv_current_compliance_ma_cm2
        return ManualSMUSettings(
            channel=channel,
            mode=mode,
            area_cm2=area_cm2,
            cc_current_density_ma_cm2=self._finite_value(
                CC_CURRENT_DENSITY_KEY,
                defaults.cc_current_density_ma_cm2,
            ),
            cc_voltage_compliance_v=cc_voltage_compliance_v,
            cv_voltage_v=self._finite_value(CV_VOLTAGE_KEY, defaults.cv_voltage_v),
            cv_current_compliance_ma_cm2=cv_current_compliance_ma_cm2,
        )

    def save(self, values: ManualSMUSettings) -> None:
        safe = self._validated_for_save(values)
        entries = {
            CHANNEL_KEY: safe.channel,
            MODE_KEY: safe.mode,
            AREA_CM2_KEY: safe.area_cm2,
            CC_CURRENT_DENSITY_KEY: safe.cc_current_density_ma_cm2,
            CC_VOLTAGE_COMPLIANCE_KEY: safe.cc_voltage_compliance_v,
            CV_VOLTAGE_KEY: safe.cv_voltage_v,
            CV_CURRENT_COMPLIANCE_KEY: safe.cv_current_compliance_ma_cm2,
        }
        for key, value in entries.items():
            self._settings.setValue(key, value)
        self._settings.sync()
        status = self._settings.status()
        if status != QSettings.Status.NoError:
            status_name = getattr(status, "name", type(status).__name__)
            raise ManualSMUSettingsWriteError(
                f"Manual SMU settings sync failed: {status_name}"
            )

    def reset(self) -> ManualSMUSettings:
        defaults = ManualSMUSettings()
        self.save(defaults)
        return defaults

    def _finite_value(self, key: str, default: float) -> float:
        try:
            value = float(self._settings.value(key, default))
        except (TypeError, ValueError, OverflowError):
            return default
        return value if math.isfinite(value) else default

    @staticmethod
    def _validated_for_save(values: ManualSMUSettings) -> ManualSMUSettings:
        channel = values.channel if values.channel in MANUAL_SMU_CHANNELS else "Ch1"
        mode = values.mode if values.mode in MANUAL_SMU_MODES else "CC"

        def finite(value: float, default: float) -> float:
            try:
                converted = float(value)
            except (TypeError, ValueError, OverflowError):
                return default
            return converted if math.isfinite(converted) else default

        area_cm2 = finite(values.area_cm2, 1.0)
        voltage_compliance = finite(values.cc_voltage_compliance_v, 1.0)
        current_compliance = finite(values.cv_current_compliance_ma_cm2, 1.0)
        return ManualSMUSettings(
            channel=channel,
            mode=mode,
            area_cm2=area_cm2 if area_cm2 > 0.0 else 1.0,
            cc_current_density_ma_cm2=finite(
                values.cc_current_density_ma_cm2,
                0.0,
            ),
            cc_voltage_compliance_v=(
                voltage_compliance if voltage_compliance > 0.0 else 1.0
            ),
            cv_voltage_v=finite(values.cv_voltage_v, 0.0),
            cv_current_compliance_ma_cm2=(
                current_compliance if current_compliance > 0.0 else 1.0
            ),
        )
