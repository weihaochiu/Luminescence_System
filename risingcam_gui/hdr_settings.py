from __future__ import annotations

"""Application-wide quantitative HDR settings and immutable snapshots."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class HDRSystemSettings:
    """Settings shared by every Recipe that enables HDR.

    A Recipe stores only the enable/disable decision.  Every measurement must
    store :meth:`snapshot` so later edits to these defaults never alter the
    audit trail of an existing result.
    """

    settings_version: str = "1.0"
    strategy: str = "auto"  # auto / fixed_bracket
    prioritize_single_exposure: bool = True
    max_exposure_segments: int = 4
    frames_per_exposure: int = 3
    frame_interval_s: float = 0.10
    gain_mode: str = "auto_lock"  # auto_lock / manual_lock
    locked_gain_percent: int = 10
    min_exposure_ms: float = 0.030
    max_exposure_ms: float = 15000.0
    exposure_ratio: float = 4.0
    saturation_dn: float = 245.0
    target_high_dn: float = 220.0
    minimum_snr: float = 5.0
    max_point_time_s: float = 60.0
    exposure_order: str = "short_to_long"
    early_stop_on_severe_overexposure: bool = True
    severe_saturation_fraction: float = 0.05
    judgment_frames: int = 1
    judgment_region: str = "effective_device_roi"
    exclude_hot_pixels: bool = True
    save_judgment_frame: bool = True
    dark_frames_per_exposure: int = 5
    dark_combine_method: str = "median"
    dark_frame_method: str = "recapture_each_measurement"
    save_source_exposures: bool = True
    save_source_dark_frames: bool = True
    save_master_dark: bool = True
    save_linear_float32_tiff: bool = True
    save_preview_png: bool = True
    auto_save_profile: bool = True
    allow_supplemental_long_exposure: bool = True
    algorithm: str = "linear_exposure_normalized_v1"
    output_unit: str = "DN/s"
    output_format: str = "float32_tiff"
    gamma: float = 1.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.strategy not in {"auto", "fixed_bracket"}:
            errors.append("HDR 策略必須是自動判斷或固定曝光組合")
        if not 1 <= self.max_exposure_segments <= 20:
            errors.append("HDR 最大曝光段數必須介於 1 到 20")
        if self.frames_per_exposure < 1 or self.judgment_frames != 1:
            errors.append("每段 frame 數必須大於 0，且過曝判斷固定使用第一張")
        if self.gain_mode not in {"auto_lock", "manual_lock"} or self.locked_gain_percent < 0:
            errors.append("HDR Gain 鎖定設定無效")
        if not (0 < self.min_exposure_ms <= self.max_exposure_ms <= 15000):
            errors.append("HDR 曝光範圍必須大於 0、前後有序且不超過 15000 ms")
        if self.exposure_ratio <= 1:
            errors.append("HDR 曝光級距倍率必須大於 1")
        if not (0 < self.target_high_dn < self.saturation_dn <= 255):
            errors.append("HDR 高亮目標必須低於飽和門檻，且飽和門檻不可超過 255 DN")
        if not (0 < self.severe_saturation_fraction <= 1):
            errors.append("嚴重過曝比例必須大於 0 且不超過 100%")
        if self.minimum_snr <= 0 or self.max_point_time_s <= 0:
            errors.append("最低 SNR 與每點時間上限必須大於 0")
        if self.exposure_order != "short_to_long":
            errors.append("HDR 曝光順序必須固定為短曝光到長曝光")
        if self.judgment_region != "effective_device_roi":
            errors.append("過曝判定必須使用有效元件 ROI")
        if self.dark_frames_per_exposure < 1 or self.dark_combine_method not in {"median", "average"}:
            errors.append("Dark frame 數量或合成方式無效")
        if self.dark_frame_method != "recapture_each_measurement":
            errors.append("Dark frames 必須在每次量測重新拍攝")
        required = (
            self.save_source_exposures,
            self.save_source_dark_frames,
            self.save_master_dark,
            self.save_linear_float32_tiff,
            self.auto_save_profile,
            self.save_judgment_frame,
        )
        if not all(required):
            errors.append("HDR 必須保存原始 EL、原始 Dark、Master Dark、判斷幀、Float32 TIFF 與 Profile")
        if (
            self.algorithm != "linear_exposure_normalized_v1"
            or self.output_unit != "DN/s"
            or self.output_format != "float32_tiff"
            or self.gamma != 1.0
        ):
            errors.append("定量 HDR 必須使用線性算法並輸出 gamma 1.0 的 Float32 TIFF（DN/s）")
        return errors

    def planned_exposures_ms(self) -> list[float]:
        if self.max_exposure_segments == 1 or self.min_exposure_ms == self.max_exposure_ms:
            return [float(self.min_exposure_ms)]
        required = int(
            math.ceil(
                math.log(self.max_exposure_ms / self.min_exposure_ms)
                / math.log(self.exposure_ratio)
            )
        ) + 1
        count = max(2, min(self.max_exposure_segments, required))
        ratio = (self.max_exposure_ms / self.min_exposure_ms) ** (1.0 / (count - 1))
        return [float(self.min_exposure_ms * ratio**index) for index in range(count)]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "HDRSystemSettings":
        source = data or {}
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in source.items() if key in allowed})

    @classmethod
    def from_legacy_recipe(cls, data: dict[str, Any] | None) -> "HDRSystemSettings":
        legacy = data or {}
        quality = str(legacy.get("quality", "standard"))
        max_segments, frames = {
            "fast": (3, 1),
            "standard": (5, 3),
            "high": (7, 5),
        }.get(quality, (4, 3))
        mapped = {
            "max_exposure_segments": max_segments,
            "frames_per_exposure": frames,
            "gain_mode": legacy.get("gain_mode", "auto_lock"),
            "locked_gain_percent": legacy.get("locked_gain_percent", 10),
            "min_exposure_ms": legacy.get("min_exposure_ms", 0.030),
            "max_exposure_ms": legacy.get("max_exposure_ms", 15000.0),
            "exposure_ratio": legacy.get("exposure_ratio", 4.0),
            "saturation_dn": legacy.get("saturation_dn", 245.0),
            "target_high_dn": legacy.get("target_high_dn", 220.0),
            "minimum_snr": legacy.get("minimum_snr", 5.0),
            "max_point_time_s": legacy.get("max_point_time_s", 60.0),
            "save_source_exposures": legacy.get("save_source_exposures", True),
            "save_source_dark_frames": legacy.get("save_source_dark_frames", True),
            "save_master_dark": legacy.get("save_master_dark", True),
            "save_linear_float32_tiff": legacy.get("save_linear_float32_tiff", True),
            "save_preview_png": legacy.get("save_preview_png", True),
            "auto_save_profile": legacy.get("auto_save_profile", True),
            "algorithm": legacy.get("algorithm", "linear_exposure_normalized_v1"),
        }
        return cls.from_dict(mapped)

    def snapshot(self) -> dict[str, Any]:
        settings = self.to_dict()
        canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return {
            "snapshot_type": "hdr_system_settings",
            "captured_at": _now(),
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "settings": settings,
        }


class HDRSettingsStore:
    schema_version = 1

    def __init__(self, path: Path, legacy_hdr: dict[str, Any] | None = None) -> None:
        self.path = path
        self.migrated_from_legacy = False
        self.settings = HDRSystemSettings()
        self.load(legacy_hdr)

    def load(self, legacy_hdr: dict[str, Any] | None = None) -> None:
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.settings = HDRSystemSettings.from_dict(payload.get("hdr_settings", payload))
            return
        if legacy_hdr:
            self.settings = HDRSystemSettings.from_legacy_recipe(legacy_hdr)
            self.migrated_from_legacy = True
            self.save()

    def save(self) -> None:
        errors = self.settings.validate()
        if errors:
            raise ValueError("HDR 系統設定無效：" + "；".join(errors))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "saved_at": _now(),
            "hdr_settings": self.settings.to_dict(),
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
