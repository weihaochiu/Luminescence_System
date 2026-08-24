from __future__ import annotations

"""Application-wide Jsc/Voc polarity measurement settings and snapshots."""

from dataclasses import asdict, dataclass, fields
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from core.i18n import tr


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class PolarityMeasurementSettings:
    white_light_stabilization_ms: int = 500
    anti_flicker_enabled: bool = True
    mains_frequency_hz: float = 60.0
    integration_nplc: float = 5.0
    jsc_settle_ms: int = 100
    jsc_sample_count: int = 5
    jsc_aggregation: str = "median"
    jsc_minimum_valid_ma_cm2: float = 1.0
    jsc_max_variation_percent: float = 10.0
    jsc_compliance_ma_cm2: float = 50.0
    voc_settle_ms: int = 100
    voc_sample_count: int = 5
    voc_aggregation: str = "median"
    voc_minimum_valid_v: float = 0.20
    voc_max_variation_percent: float = 10.0
    voc_compliance_v: float = 5.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.white_light_stabilization_ms < 0:
            errors.append(tr("polarity.validation.white_light_wait"))
        if not 40.0 <= self.mains_frequency_hz <= 70.0:
            errors.append(tr("polarity.validation.mains_frequency"))
        if not 0.001 <= self.integration_nplc <= 100.0:
            errors.append(tr("polarity.validation.integration"))
        for name, settle in (("Jsc", self.jsc_settle_ms), ("Voc", self.voc_settle_ms)):
            if settle < 0:
                errors.append(tr("polarity.validation.settle_time", name=name))
        for name, count in (("Jsc", self.jsc_sample_count), ("Voc", self.voc_sample_count)):
            if not 1 <= count <= 1000:
                errors.append(tr("polarity.validation.sample_count", name=name))
        for name, method in (("Jsc", self.jsc_aggregation), ("Voc", self.voc_aggregation)):
            if method not in {"median", "mean"}:
                errors.append(tr("polarity.validation.aggregation", name=name))
        if self.jsc_minimum_valid_ma_cm2 <= 0 or self.voc_minimum_valid_v <= 0:
            errors.append(tr("polarity.validation.minimum_values"))
        if self.jsc_max_variation_percent < 0 or self.voc_max_variation_percent < 0:
            errors.append(tr("polarity.validation.variation"))
        if self.jsc_compliance_ma_cm2 <= 0 or self.voc_compliance_v <= 0:
            errors.append(tr("polarity.validation.compliance"))
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PolarityMeasurementSettings":
        source = data or {}
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in source.items() if key in allowed})

    def snapshot(self) -> dict[str, Any]:
        settings = self.to_dict()
        canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return {
            "snapshot_type": "polarity_measurement_settings",
            "captured_at": _now(),
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "settings": settings,
        }


class PolaritySettingsStore:
    schema_version = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.settings = PolarityMeasurementSettings()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.settings = PolarityMeasurementSettings.from_dict(
            payload.get("polarity_measurement_settings", payload)
        )

    def reset_defaults(self) -> None:
        self.settings = PolarityMeasurementSettings()

    def save(self) -> None:
        errors = self.settings.validate()
        if errors:
            raise ValueError("極性確認設定無效：" + "；".join(errors))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "saved_at": _now(),
            "polarity_measurement_settings": self.settings.to_dict(),
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
