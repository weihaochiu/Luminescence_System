from __future__ import annotations

"""Validated QSettings persistence for Manual SMU input parameters only."""

from dataclasses import dataclass
import math
from typing import Any, Callable

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

    def __init__(
        self,
        settings: Any,
        *,
        settings_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._settings_factory = (
            settings_factory
            if settings_factory is not None
            else self._qsettings_factory(settings)
        )

    def load(self) -> ManualSMUSettings:
        return self._load_from(self._settings)

    @classmethod
    def _load_from(cls, settings: Any) -> ManualSMUSettings:
        defaults = ManualSMUSettings()
        channel = str(settings.value(CHANNEL_KEY, defaults.channel))
        if channel not in MANUAL_SMU_CHANNELS:
            channel = defaults.channel
        mode = str(settings.value(MODE_KEY, defaults.mode))
        if mode not in MANUAL_SMU_MODES:
            mode = defaults.mode
        area_cm2 = cls._finite_value(settings, AREA_CM2_KEY, defaults.area_cm2)
        if area_cm2 <= 0.0:
            area_cm2 = defaults.area_cm2
        cc_voltage_compliance_v = cls._finite_value(
            settings,
            CC_VOLTAGE_COMPLIANCE_KEY,
            defaults.cc_voltage_compliance_v,
        )
        if cc_voltage_compliance_v <= 0.0:
            cc_voltage_compliance_v = defaults.cc_voltage_compliance_v
        cv_current_compliance_ma_cm2 = cls._finite_value(
            settings,
            CV_CURRENT_COMPLIANCE_KEY,
            defaults.cv_current_compliance_ma_cm2,
        )
        if cv_current_compliance_ma_cm2 <= 0.0:
            cv_current_compliance_ma_cm2 = defaults.cv_current_compliance_ma_cm2
        return ManualSMUSettings(
            channel=channel,
            mode=mode,
            area_cm2=area_cm2,
            cc_current_density_ma_cm2=cls._finite_value(
                settings,
                CC_CURRENT_DENSITY_KEY,
                defaults.cc_current_density_ma_cm2,
            ),
            cc_voltage_compliance_v=cc_voltage_compliance_v,
            cv_voltage_v=cls._finite_value(
                settings,
                CV_VOLTAGE_KEY,
                defaults.cv_voltage_v,
            ),
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
        writer = self._settings_factory()
        for key, value in entries.items():
            writer.setValue(key, value)
        writer.sync()
        self._raise_for_status(writer, "sync")

        reader = self._settings_factory()
        if isinstance(reader, QSettings):
            reader.setFallbacksEnabled(False)
        reader.sync()
        self._raise_for_status(reader, "readback sync")
        if not all(reader.contains(key) for key in entries):
            raise ManualSMUSettingsWriteError(
                "Manual SMU settings readback verification failed"
            )
        if not self._settings_equal(safe, self._load_from(reader)):
            raise ManualSMUSettingsWriteError(
                "Manual SMU settings readback verification failed"
            )

    @staticmethod
    def _raise_for_status(settings: Any, operation: str) -> None:
        status = settings.status()
        if status != QSettings.Status.NoError:
            status_name = getattr(status, "name", type(status).__name__)
            raise ManualSMUSettingsWriteError(
                f"Manual SMU settings {operation} failed: {status_name}"
            )

    def reset(self) -> ManualSMUSettings:
        defaults = ManualSMUSettings()
        self.save(defaults)
        return defaults

    @staticmethod
    def _finite_value(settings: Any, key: str, default: float) -> float:
        try:
            value = float(settings.value(key, default))
        except (TypeError, ValueError, OverflowError):
            return default
        return value if math.isfinite(value) else default

    @staticmethod
    def _settings_equal(
        expected: ManualSMUSettings,
        actual: ManualSMUSettings,
    ) -> bool:
        if expected.channel != actual.channel or expected.mode != actual.mode:
            return False
        numeric_fields = (
            "area_cm2",
            "cc_current_density_ma_cm2",
            "cc_voltage_compliance_v",
            "cv_voltage_v",
            "cv_current_compliance_ma_cm2",
        )
        return all(
            math.isclose(
                getattr(expected, field),
                getattr(actual, field),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for field in numeric_fields
        )

    @staticmethod
    def _qsettings_factory(settings: Any) -> Callable[[], QSettings]:
        if not isinstance(settings, QSettings):
            raise TypeError(
                "settings_factory is required for non-QSettings persistence backends"
            )

        settings_format = settings.format()
        settings_scope = settings.scope()
        organization = settings.organizationName()
        application = settings.applicationName()
        file_name = settings.fileName()
        fallbacks_enabled = settings.fallbacksEnabled()
        atomic_sync_required = settings.isAtomicSyncRequired()

        if not organization and not application and not file_name:
            raise ValueError("QSettings persistence backend has no storage identity")

        def create() -> QSettings:
            if organization or application:
                fresh = QSettings(
                    settings_format,
                    settings_scope,
                    organization,
                    application,
                )
            else:
                fresh = QSettings(file_name, settings_format)
            fresh.setFallbacksEnabled(fallbacks_enabled)
            fresh.setAtomicSyncRequired(atomic_sync_required)
            return fresh

        return create

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
