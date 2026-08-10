from __future__ import annotations

"""Sample-specific quantitative HDR profiles for repeat/stability imaging."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


PROFILE_VERSION = "1.0"
SUPPORTED_ALGORITHM = "linear_exposure_normalized_v1"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class HDRProfile:
    profile_version: str = PROFILE_VERSION
    profile_id: str = field(default_factory=lambda: str(uuid4()))
    sample_id: str = ""
    measurement_role: str = "T0"
    camera_name: str = ""
    camera_model: str = ""
    camera_serial: str = ""
    resolution: str = "current"
    pixel_format: str = "RGB24"
    gain_percent: int = 10
    exposure_times_ms: tuple[float, ...] = ()
    planned_exposure_times_ms: tuple[float, ...] = ()
    captured_exposure_times_ms: tuple[float, ...] = ()
    excluded_exposure_times_ms: tuple[float, ...] = ()
    skipped_exposure_times_ms: tuple[float, ...] = ()
    early_termination: dict[str, Any] | None = None
    frames_per_exposure: int = 3
    frame_interval_s: float = 0.1
    saturation_threshold_dn: float = 245.0
    minimum_snr: float = 5.0
    dark_frames_per_exposure: int = 5
    dark_combine_method: str = "median"
    dark_frame_method: str = "recapture_each_measurement"
    hdr_algorithm: str = SUPPORTED_ALGORITHM
    output_unit: str = "DN/s"
    analysis_format: str = "float32_tiff"
    gamma: float = 1.0
    recipe_id: str = ""
    recipe_version: int = 1
    scan_signature: str = ""
    scan_conditions: dict[str, Any] = field(default_factory=dict)
    source_el_frames_required: bool = True
    source_dark_frames_required: bool = True
    master_dark_required: bool = True
    hdr_settings_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "exposure_times_ms",
            "planned_exposure_times_ms",
            "captured_exposure_times_ms",
            "excluded_exposure_times_ms",
            "skipped_exposure_times_ms",
        ):
            payload[key] = list(getattr(self, key))
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HDRProfile":
        allowed = {item.name for item in fields(cls)}
        values = {key: value for key, value in data.items() if key in allowed}
        for key in (
            "exposure_times_ms",
            "planned_exposure_times_ms",
            "captured_exposure_times_ms",
            "excluded_exposure_times_ms",
            "skipped_exposure_times_ms",
        ):
            values[key] = tuple(float(value) for value in data.get(key, ()))
        profile = cls(**values)
        errors = profile.validate_internal()
        if errors:
            raise ValueError("HDR Profile 無效：" + "；".join(errors))
        return profile

    @classmethod
    def load(cls, path: str | Path) -> "HDRProfile":
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        data = payload.get("hdr_profile", payload)
        if not isinstance(data, dict):
            raise ValueError("HDR Profile JSON 結構無效")
        return cls.from_dict(data)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "el_quantitative_hdr_profile",
            "hdr_profile": self.to_dict(),
        }
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        return target

    def validate_internal(self) -> list[str]:
        errors: list[str] = []
        if self.profile_version != PROFILE_VERSION:
            errors.append(f"不支援 Profile 版本 {self.profile_version}")
        if not self.sample_id.strip():
            errors.append("缺少 Sample ID")
        if not self.exposure_times_ms or any(value <= 0 for value in self.exposure_times_ms):
            errors.append("曝光時間列表必須包含大於 0 的數值")
        if tuple(sorted(set(self.exposure_times_ms))) != self.exposure_times_ms:
            errors.append("曝光時間必須由短至長且不可重複")
        if self.frames_per_exposure < 1 or self.dark_frames_per_exposure < 1:
            errors.append("EL 與 Dark frame 數量必須大於 0")
        if self.gain_percent < 0 or self.frame_interval_s < 0:
            errors.append("Gain 與 frame interval 無效")
        if not (0 < self.saturation_threshold_dn <= 255) or self.minimum_snr <= 0:
            errors.append("飽和門檻或最低 SNR 無效")
        if self.dark_frame_method != "recapture_each_measurement":
            errors.append("Dark frame 必須在每次量測重新拍攝")
        if self.hdr_algorithm != SUPPORTED_ALGORITHM:
            errors.append("HDR 演算法版本不相容")
        if self.output_unit != "DN/s" or self.analysis_format != "float32_tiff" or self.gamma != 1.0:
            errors.append("定量輸出必須為 gamma 1.0 的 float32 TIFF（DN/s）")
        if not all(
            (self.source_el_frames_required, self.source_dark_frames_required, self.master_dark_required)
        ):
            errors.append("Profile 必須要求保存各曝光原始 EL、Dark 與 Master Dark")
        return errors

    def compatibility_issues(
        self,
        sample_id: str,
        recipe: Any,
        camera_info: dict[str, Any] | None = None,
        hdr_settings: Any | None = None,
    ) -> tuple[list[str], list[str]]:
        errors = self.validate_internal()
        warnings: list[str] = []
        if sample_id.strip() != self.sample_id:
            errors.append(f"Sample ID 不一致：Profile={self.sample_id}，目前={sample_id.strip()}")
        if self.recipe_id and getattr(recipe, "recipe_id", "") != self.recipe_id:
            errors.append("Recipe ID 與首次量測不同")
        algorithm = str(getattr(hdr_settings, "algorithm", SUPPORTED_ALGORITHM))
        current_signature, _conditions = recipe_scan_signature(recipe, algorithm)
        if self.scan_signature and current_signature != self.scan_signature:
            errors.append("EL 掃描點、驅動模式或關鍵量測條件與 T0 不一致")
        if getattr(recipe.camera, "pixel_format", "") != self.pixel_format:
            errors.append("Pixel format 與首次量測不同")
        if hdr_settings is not None and algorithm != self.hdr_algorithm:
            errors.append("目前「設定 → HDR」的演算法版本與 Profile 不相容")
        if int(getattr(recipe, "version", 1)) != self.recipe_version:
            warnings.append(
                f"Recipe 版本不同（T0 v{self.recipe_version}／目前 v{getattr(recipe, 'version', 1)}），"
                "但關鍵掃描條件簽章相同"
            )
        info = camera_info or {}
        current_model = str(info.get("model", ""))
        current_serial = str(info.get("serial", ""))
        if self.camera_model and current_model and self.camera_model != current_model:
            errors.append(f"相機型號不一致：Profile={self.camera_model}，目前={current_model}")
        if self.camera_serial and current_serial and self.camera_serial != current_serial:
            errors.append("相機序號與首次量測不同")
        if self.camera_model and not current_model:
            warnings.append("目前尚未連接相機，無法立即核對相機型號／序號")
        return errors, warnings

    def suggested_filename(self) -> str:
        safe_id = re.sub(r"[^0-9A-Za-z._-]+", "_", self.sample_id.strip()).strip("._") or "sample"
        return f"{safe_id}_T0_HDR_Profile.json"


def create_t0_profile(
    sample_id: str,
    recipe: Any,
    exposure_times_ms: list[float] | tuple[float, ...],
    gain_percent: int,
    camera_info: dict[str, Any] | None = None,
    hdr_settings: Any | None = None,
    capture_summary: dict[str, Any] | None = None,
) -> HDRProfile:
    """Create the immutable Profile after the T0 auto-exposure prescan."""
    if hdr_settings is None:
        raise ValueError("建立 T0 Profile 時必須提供「設定 → HDR」的完整設定")
    signature, conditions = recipe_scan_signature(recipe, str(hdr_settings.algorithm))
    info = camera_info or {}
    summary = capture_summary or {}
    valid_exposures = tuple(
        sorted({float(value) for value in summary.get("valid_exposures_ms", exposure_times_ms)})
    )
    profile = HDRProfile(
        sample_id=sample_id.strip(),
        camera_name=str(info.get("name", "")),
        camera_model=str(info.get("model", "")),
        camera_serial=str(info.get("serial", "")),
        resolution=str(getattr(recipe.camera, "resolution", "current")),
        pixel_format=str(getattr(recipe.camera, "pixel_format", "RGB24")),
        gain_percent=int(gain_percent),
        exposure_times_ms=valid_exposures,
        planned_exposure_times_ms=tuple(float(value) for value in summary.get("planned_exposures_ms", exposure_times_ms)),
        captured_exposure_times_ms=tuple(float(value) for value in summary.get("captured_exposures_ms", valid_exposures)),
        excluded_exposure_times_ms=tuple(float(value) for value in summary.get("excluded_exposures_ms", ())),
        skipped_exposure_times_ms=tuple(float(value) for value in summary.get("skipped_exposures_ms", ())),
        early_termination=summary.get("early_termination"),
        frames_per_exposure=int(hdr_settings.frames_per_exposure),
        frame_interval_s=float(hdr_settings.frame_interval_s),
        saturation_threshold_dn=float(hdr_settings.saturation_dn),
        minimum_snr=float(hdr_settings.minimum_snr),
        dark_frames_per_exposure=int(hdr_settings.dark_frames_per_exposure),
        dark_combine_method=str(hdr_settings.dark_combine_method),
        hdr_algorithm=str(hdr_settings.algorithm),
        recipe_id=str(recipe.recipe_id),
        recipe_version=int(recipe.version),
        scan_signature=signature,
        scan_conditions=conditions,
        hdr_settings_snapshot=hdr_settings.snapshot(),
    )
    errors = profile.validate_internal()
    if errors:
        raise ValueError("無法建立 HDR Profile：" + "；".join(errors))
    return profile


def recipe_scan_signature(
    recipe: Any, hdr_algorithm: str = SUPPORTED_ALGORITHM
) -> tuple[str, dict[str, Any]]:
    conditions = {
        "active_area_cm2": float(recipe.geometry.active_area_cm2),
        "drive_mode": str(recipe.el_sweep.drive_mode),
        "setpoint_basis": str(recipe.el_sweep.setpoint_basis),
        "scan_direction": str(recipe.el_sweep.scan_direction),
        "repeat_count": int(recipe.el_sweep.repeat_count),
        "points": [
            {
                "setpoint": float(point.setpoint),
                "dwell_s": float(point.dwell_s),
            }
            for point in recipe.enabled_points()
        ],
        "resolution": str(recipe.camera.resolution),
        "pixel_format": str(recipe.camera.pixel_format),
        "trigger_mode": str(recipe.camera.trigger_mode),
        "dark_combine_method": str(recipe.dark_frames.combine_method),
        "hdr_algorithm": str(hdr_algorithm),
    }
    canonical = json.dumps(conditions, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), conditions
