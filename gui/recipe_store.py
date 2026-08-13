from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from .numeric import decimal_from_number, normalize_json_numbers, quantize_number
from .polarity_settings import PolarityMeasurementSettings
from uuid import uuid4


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


T = TypeVar("T")


def _dataclass_from_dict(cls: type[T], data: dict[str, Any] | None) -> T:
    """Load known keys only so older/newer Recipe files remain readable."""
    source = data or {}
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in source.items() if key in allowed})


@dataclass
class GeometryRecipe:
    active_area_cm2: float = 0.100
    device_id_required: bool = True
    forward_polarity: str = "positive"


@dataclass
class PolarityRecipe:
    """Recipe opt-in only; all measurement conditions are application-wide."""

    enabled: bool = True


@dataclass
class ChannelRecipe:
    """Logical substrate channel; physical relays remain hardware settings."""

    channel: str = "CH1"
    enabled: bool = False
    sample_id: str = ""
    area_cm2: float = 0.100


def _default_channels() -> list[ChannelRecipe]:
    return [
        ChannelRecipe(f"CH{index}", index == 1, f"Sample_A{index}", 0.100)
        for index in range(1, 5)
    ]


@dataclass
class ELMatrixRecipe:
    """One shared matrix executed for every enabled logical channel."""

    current_density_ma_cm2: list[float] = field(
        default_factory=lambda: [2.0, 4.0, 6.0, 8.0, 10.0, 12.0]
    )
    gains_percent: list[int] = field(default_factory=lambda: [100, 200, 300, 400, 500])
    exposures_ms: list[float] = field(
        default_factory=lambda: [
            0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0,
            200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0, 15000.0,
        ]
    )
    repeat: int = 1
    voltage_compliance_v: float = 3.0
    stabilization_ms: int = 0
    shared_dark_enabled: bool = True
    estimated_capture_overhead_s: float = 0.15
    estimated_polarity_duration_s: float = 8.0
    estimated_routing_transition_s: float = 0.5
    estimated_shared_dark_overhead_s: float = 1.0


@dataclass
class DarkIVRecipe:
    enabled: bool = True
    dark_stabilization_s: float = 10.0
    start_v: float = -0.20
    stop_v: float = 1.20
    step_v: float = 0.02
    direction: str = "forward"
    dwell_s: float = 0.10
    current_compliance_ma: float = 20.0
    nplc: float = 1.0
    repeat_count: int = 1
    inter_scan_delay_s: float = 1.0
    return_to_zero: bool = True
    output_off_after: bool = True
    compliance_action: str = "confirm"


@dataclass
class CameraRecipe:
    # These values are non-HDR table-entry defaults only. Acquisition always
    # uses the explicit ELPoint values when HDR is disabled.
    exposure_ms: float = 500.0
    gain_percent: int = 10
    frame_count: int = 3
    frame_interval_s: float = 0.10
    frame_handling: str = "save_all"
    resolution: str = "current"
    pixel_format: str = "RGB24"
    trigger_mode: str = "software"
    capture_timeout_s: float = 20.0


@dataclass
class HDRRecipe:
    """A Recipe only decides whether the system-wide HDR workflow is used."""
    enabled: bool = False


@dataclass
class ELPoint:
    enabled: bool = True
    setpoint: float = 1.0
    dwell_s: float = 0.50
    exposure_ms: float = 500.0
    gain_percent: int = 10
    frame_count: int = 3
    frame_interval_s: float = 0.10


@dataclass
class ELSweepRecipe:
    drive_mode: str = "current"
    setpoint_basis: str = "current_density"
    scan_direction: str = "ascending"
    repeat_count: int = 1
    inter_scan_delay_s: float = 1.0
    voltage_compliance_v: float = 3.0
    current_compliance_ma: float = 20.0
    return_to_zero: bool = True
    output_off_after: bool = True
    points: list[ELPoint] = field(
        default_factory=lambda: [
            ELPoint(setpoint=0.1),
            ELPoint(setpoint=0.3),
            ELPoint(setpoint=1.0),
            ELPoint(setpoint=3.0),
            ELPoint(setpoint=10.0),
            ELPoint(setpoint=20.0),
        ]
    )


@dataclass
class DarkFrameRecipe:
    frames_per_profile: int = 5
    frame_interval_s: float = 0.10
    camera_switch_delay_s: float = 0.30
    combine_method: str = "median"
    save_raw_frames: bool = True
    save_master_dark: bool = True
    capture_after_el: bool = False


@dataclass
class SMURecipe:
    device_match: str = "any_b2900"
    visa_address: str = ""


@dataclass
class SafetyRecipe:
    max_current_ma: float = 50.0
    max_voltage_v: float = 5.0
    max_power_mw: float = 150.0
    max_output_time_s: float = 600.0
    max_recipe_time_s: float = 1800.0
    stop_on_camera_error: bool = True
    stop_on_smu_error: bool = True


@dataclass
class OutputRecipe:
    root_directory: str = ""
    sample_id_required: bool = True
    image_format: str = "TIFF"
    save_raw_frames: bool = True
    save_summary_csv: bool = True
    save_json: bool = True
    save_recipe_snapshot: bool = True
    export_pixel_csv: bool = False
    pixel_csv_raw: bool = True
    pixel_csv_dark_corrected: bool = True
    pixel_csv_exposure_normalized: bool = False


@dataclass
class Recipe:
    recipe_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "新 EL Recipe"
    description: str = ""
    measurement_type: str = "el_sequence"
    version: int = 1
    state: str = "draft"
    created_at: str = field(default_factory=_now)
    modified_at: str = field(default_factory=_now)
    geometry: GeometryRecipe = field(default_factory=GeometryRecipe)
    channels: list[ChannelRecipe] = field(default_factory=_default_channels)
    el_matrix: ELMatrixRecipe = field(default_factory=ELMatrixRecipe)
    polarity: PolarityRecipe = field(default_factory=PolarityRecipe)
    dark_iv: DarkIVRecipe = field(default_factory=DarkIVRecipe)
    camera: CameraRecipe = field(default_factory=CameraRecipe)
    hdr: HDRRecipe = field(default_factory=HDRRecipe)
    el_sweep: ELSweepRecipe = field(default_factory=ELSweepRecipe)
    dark_frames: DarkFrameRecipe = field(default_factory=DarkFrameRecipe)
    smu: SMURecipe = field(default_factory=SMURecipe)
    safety: SafetyRecipe = field(default_factory=SafetyRecipe)
    output: OutputRecipe = field(default_factory=OutputRecipe)

    def clone(self) -> "Recipe":
        copied = deepcopy(self)
        copied.recipe_id = str(uuid4())
        copied.name = f"{self.name} - 複本"
        copied.version = 1
        copied.state = "draft"
        copied.created_at = _now()
        copied.modified_at = copied.created_at
        return copied

    def enabled_points(self) -> list[ELPoint]:
        return [point for point in self.el_sweep.points if point.enabled]

    def enabled_channels(self) -> list[ChannelRecipe]:
        order = {f"CH{index}": index for index in range(1, 5)}
        return sorted(
            (channel for channel in self.channels if channel.enabled),
            key=lambda channel: order.get(channel.channel, 99),
        )

    def matrix_source_current_ma(self, channel: ChannelRecipe, current_density: float) -> float:
        return quantize_number(
            decimal_from_number(current_density) * decimal_from_number(channel.area_cm2)
        )

    def effective_camera(self, point: ELPoint) -> tuple[float, int, int, float]:
        return (
            point.exposure_ms,
            point.gain_percent,
            point.frame_count,
            point.frame_interval_s,
        )

    def hdr_upper_bound_exposures_ms(self, hdr_settings: Any | None = None) -> list[float]:
        if not self.hdr.enabled or hdr_settings is None:
            return []
        return list(hdr_settings.planned_exposures_ms())

    def dark_profiles(self, hdr_settings: Any | None = None) -> list[dict[str, Any]]:
        if self.hdr.enabled:
            if hdr_settings is None:
                return [{"profile_id": "HDR_RUNTIME_PROFILE", "provisional": True}]
            gain: int | str = (
                hdr_settings.locked_gain_percent
                if hdr_settings.gain_mode == "manual_lock"
                else "T0_AUTO_LOCK"
            )
            return [
                {
                    "profile_id": f"HDR_PROVISIONAL_{index + 1}",
                    "exposure_ms": exposure,
                    "gain_percent": gain,
                    "resolution": self.camera.resolution,
                    "pixel_format": self.camera.pixel_format,
                    "trigger_mode": self.camera.trigger_mode,
                    "provisional": True,
                }
                for index, exposure in enumerate(self.hdr_upper_bound_exposures_ms(hdr_settings))
            ]
        profiles: dict[tuple[Any, ...], dict[str, Any]] = {}
        for point in self.enabled_points():
            exposure, gain, _frames, _interval = self.effective_camera(point)
            key = (
                round(exposure, 6),
                gain,
                self.camera.resolution,
                self.camera.pixel_format,
                self.camera.trigger_mode,
            )
            profiles.setdefault(
                key,
                {
                    "profile_id": f"DARK_EXP{exposure:g}_GAIN{gain}",
                    "exposure_ms": exposure,
                    "gain_percent": gain,
                    "resolution": self.camera.resolution,
                    "pixel_format": self.camera.pixel_format,
                    "trigger_mode": self.camera.trigger_mode,
                },
            )
        return list(profiles.values())

    def setpoint_unit(self) -> str:
        return {
            "current": "mA",
            "current_density": "mA/cm²",
            "voltage": "V",
        }.get(self.el_sweep.setpoint_basis, "")

    def actual_current_ma(self, point: ELPoint) -> float:
        if self.el_sweep.setpoint_basis == "current_density":
            return quantize_number(decimal_from_number(point.setpoint) * decimal_from_number(self.geometry.active_area_cm2))
        if self.el_sweep.setpoint_basis == "current":
            return quantize_number(point.setpoint)
        return 0.0

    def dark_iv_point_count(self) -> int:
        if self.dark_iv.step_v <= 0:
            return 0
        count = int(math.floor(abs(self.dark_iv.stop_v - self.dark_iv.start_v) / self.dark_iv.step_v + 1e-9)) + 1
        if self.dark_iv.direction == "bidirectional":
            count = count * 2 - 1
        return count * max(1, self.dark_iv.repeat_count)

    def validation_warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.hdr.enabled:
            warnings.append(
                "T0 必須建立樣品專屬 HDR Profile；Aging／重複量測必須匯入並鎖定該 Profile"
            )
            return warnings
        cameras = {self.effective_camera(point)[:2] for point in self.enabled_points()}
        if len(cameras) > 1:
            if len({gain for _exposure, gain in cameras}) > 1:
                warnings.append("不同 EL 點使用不同 Gain；未完成 Gain 校正前不可直接建立定量 EL–I 或 k mapping")
            else:
                warnings.append("不同 EL 點使用不同曝光；跨曝光比較需扣除匹配 Dark 並做曝光正規化")
        return warnings

    def validate(self, hdr_settings: Any | None = None) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("Recipe 名稱不可空白")
        if self.measurement_type != "el_sequence":
            errors.append("Recipe 類型必須是四階段 EL 量測")
        if self.geometry.active_area_cm2 <= 0:
            errors.append("Active area 必須大於 0")
        expected_channels = [f"CH{index}" for index in range(1, 5)]
        if [channel.channel for channel in self.channels] != expected_channels:
            errors.append("Channel 必須固定且依序為 CH1～CH4")
        enabled_channels = self.enabled_channels()
        if not enabled_channels:
            errors.append("至少需要啟用一個 Channel")
        for channel in enabled_channels:
            if not channel.sample_id.strip():
                errors.append(f"{channel.channel} 的 Sample / Device ID 不可空白")
            if not math.isfinite(channel.area_cm2) or channel.area_cm2 <= 0:
                errors.append(f"{channel.channel} 的 Device Area 必須大於 0")
        matrix = self.el_matrix
        if not matrix.current_density_ma_cm2:
            errors.append("Current Density 至少需要一個值")
        elif any(not math.isfinite(float(value)) or float(value) <= 0 for value in matrix.current_density_ma_cm2):
            errors.append("所有 EL Current Density 必須是大於 0 的有限數值")
        if not matrix.exposures_ms:
            errors.append("Exposure 至少需要一個值")
        elif any(not math.isfinite(float(value)) or float(value) <= 0 for value in matrix.exposures_ms):
            errors.append("所有 Exposure 必須是大於 0 的有限數值")
        if not matrix.gains_percent:
            errors.append("Gain 至少需要一個值")
        elif any(int(value) < 0 for value in matrix.gains_percent):
            errors.append("所有 Gain 必須大於或等於 0")
        if matrix.repeat < 1:
            errors.append("每條件拍攝張數必須是大於或等於 1 的整數")
        if matrix.stabilization_ms < 0:
            errors.append("J Stabilization Time 不可小於 0")
        if not math.isfinite(matrix.voltage_compliance_v) or not (
            0 < matrix.voltage_compliance_v <= self.safety.max_voltage_v
        ):
            errors.append("EL Matrix Voltage Compliance 必須在安全電壓範圍內")
        if any(
            self.matrix_source_current_ma(channel, float(density)) > self.safety.max_current_ma
            for channel in enabled_channels
            for density in matrix.current_density_ma_cm2
        ):
            errors.append("EL Matrix 計算出的 Source Current 超過最大允許電流")
        if not self.dark_iv.enabled:
            errors.append("Dark I–V 是 EL Recipe 的必做階段")
        if self.dark_iv.step_v <= 0 or self.dark_iv.start_v == self.dark_iv.stop_v:
            errors.append("Dark I–V 必須設定非零範圍及大於 0 的 Step")
        if max(abs(self.dark_iv.start_v), abs(self.dark_iv.stop_v)) > self.safety.max_voltage_v:
            errors.append("Dark I–V 掃描電壓超過安全上限")
        if self.dark_iv.current_compliance_ma <= 0:
            errors.append("Dark I–V current compliance 必須大於 0")
        if self.dark_iv.current_compliance_ma > self.safety.max_current_ma:
            errors.append("Dark I–V current compliance 超過最大允許電流")
        if self.smu.device_match == "specific" and not self.smu.visa_address.strip():
            errors.append("指定 SMU 時必須填寫 VISA 位址")
        if self.el_sweep.drive_mode == "current" and self.el_sweep.setpoint_basis not in {
            "current", "current_density"
        }:
            errors.append("電流模式必須使用電流或電流密度點位")
        if self.el_sweep.drive_mode == "voltage" and self.el_sweep.setpoint_basis != "voltage":
            errors.append("電壓模式必須使用電壓點位")
        points = self.enabled_points()
        if not points:
            errors.append("至少需要一個已啟用的 EL 點位")
        for index, point in enumerate(points, start=1):
            exposure, gain, frames, interval = self.effective_camera(point)
            if point.setpoint <= 0:
                errors.append(f"EL 點位 {index} 的設定值必須大於 0")
            if point.dwell_s < 0:
                errors.append(f"EL 點位 {index} 的等待時間無效")
            if not self.hdr.enabled and (exposure <= 0 or frames < 1 or interval < 0 or gain < 0):
                errors.append(
                    f"EL 點位 {index} 未填妥 Exposure、Gain、Frames 與 Frame interval；"
                    "關閉 HDR 時每列相機設定皆為必填"
                )
            if self.el_sweep.drive_mode == "current" and self.actual_current_ma(point) > self.safety.max_current_ma:
                errors.append(f"EL 點位 {index} 的實際輸出電流超過安全上限")
            if self.el_sweep.drive_mode == "voltage" and point.setpoint > self.safety.max_voltage_v:
                errors.append(f"EL 點位 {index} 的輸出電壓超過安全上限")
            hdr_point_limit = float(getattr(hdr_settings, "max_point_time_s", 0.0))
            point_time = (
                point.dwell_s + hdr_point_limit
                if self.hdr.enabled and hdr_settings is not None
                else point.dwell_s + frames * exposure / 1000.0 + max(0, frames - 1) * interval
            )
            if point_time > self.safety.max_output_time_s:
                errors.append(f"EL 點位 {index} 的預估連續輸出時間超過安全上限")
        if self.el_sweep.drive_mode == "current":
            if self.el_sweep.voltage_compliance_v <= 0:
                errors.append("Voltage compliance 必須大於 0")
            if self.el_sweep.voltage_compliance_v > self.safety.max_voltage_v:
                errors.append("Voltage compliance 超過最大允許電壓")
        else:
            if self.el_sweep.current_compliance_ma <= 0:
                errors.append("Current compliance 必須大於 0")
            if self.el_sweep.current_compliance_ma > self.safety.max_current_ma:
                errors.append("Current compliance 超過最大允許電流")
        if points:
            if self.el_sweep.drive_mode == "current":
                worst_power_mw = max(self.actual_current_ma(point) for point in points) * self.el_sweep.voltage_compliance_v
            else:
                worst_power_mw = max(point.setpoint for point in points) * self.el_sweep.current_compliance_ma
            if worst_power_mw > self.safety.max_power_mw:
                errors.append("EL 設定值與 Compliance 的最壞情況功率超過安全上限")
        if self.dark_frames.frames_per_profile < 1:
            errors.append("每個 Dark Profile 至少需要 1 frame")
        longest_exposure_s = (
            float(hdr_settings.max_exposure_ms) / 1000.0
            if self.hdr.enabled and hdr_settings is not None
            else max([self.effective_camera(point)[0] / 1000.0 for point in points], default=0.0)
        )
        if self.camera.capture_timeout_s < longest_exposure_s:
            errors.append("相機 timeout 不可短於最大曝光時間")
        if self.hdr.enabled:
            if hdr_settings is not None:
                errors.extend(f"HDR 系統設定：{item}" for item in hdr_settings.validate())
                bracket_time = (
                    hdr_settings.frames_per_exposure
                    * sum(hdr_settings.planned_exposures_ms())
                    / 1000.0
                )
                if bracket_time > hdr_settings.max_point_time_s:
                    errors.append("HDR 最壞曝光組合時間超過每個量測點的時間上限")
            required_hdr_outputs = (
                self.output.save_raw_frames,
                self.dark_frames.save_raw_frames,
                self.dark_frames.save_master_dark,
            )
            if not all(required_hdr_outputs):
                errors.append("HDR Recipe 必須允許保存各曝光原始 EL、原始 Dark 與 Master Dark")
            if self.output.image_format.upper() != "TIFF":
                errors.append("定量 HDR 的原始與分析影像格式必須使用 TIFF")
        estimated = self.estimated_time_s(hdr_settings)
        if self.safety.max_recipe_time_s < estimated:
            errors.append("Recipe 最長時間短於預估完整流程時間")
        if not self.output.save_summary_csv:
            errors.append("Dark I–V 與 EL scan summary CSV 是必要輸出")
        if not self.output.save_json:
            errors.append("EL 量測必須保存 JSON metadata")
        if not self.output.save_recipe_snapshot:
            errors.append("EL 量測必須保存 Recipe 快照")
        if self.output.export_pixel_csv and not any(
            (
                self.output.pixel_csv_raw,
                self.output.pixel_csv_dark_corrected,
                self.output.pixel_csv_exposure_normalized,
            )
        ):
            errors.append("啟用全解析度像素 CSV 時，至少要選擇一種輸出內容")
        return errors

    def estimated_time_s(self, hdr_settings: Any | None = None) -> float:
        # Polarity duration is global and captured at execution time; a Recipe
        # no longer owns a second, potentially stale parameter set. The editor
        # uses the system defaults for its non-binding estimate because Recipe
        # execution is not currently enabled.
        polarity = PolarityMeasurementSettings()
        polarity_time = (
            polarity.white_light_stabilization_ms
            + polarity.jsc_settle_ms
            + polarity.voc_settle_ms
        ) / 1000.0
        if polarity.anti_flicker_enabled:
            polarity_time += (
                polarity.jsc_sample_count + polarity.voc_sample_count
            ) * polarity.integration_nplc / polarity.mains_frequency_hz
        dark_iv_time = (
            self.dark_iv.dark_stabilization_s
            + self.dark_iv_point_count() * (self.dark_iv.dwell_s + self.dark_iv.nplc / 50.0)
            + max(0, self.dark_iv.repeat_count - 1) * self.dark_iv.inter_scan_delay_s
        )
        dark_time = 0.0
        for profile in self.dark_profiles(hdr_settings):
            if "exposure_ms" not in profile:
                continue
            dark_time += self.dark_frames.camera_switch_delay_s
            dark_time += self.dark_frames.frames_per_profile * (
                profile["exposure_ms"] / 1000.0 + self.dark_frames.frame_interval_s
            )
        sequence_multiplier = 2 if self.el_sweep.scan_direction == "bidirectional" else 1
        el_time = 0.0
        for point in self.enabled_points():
            if self.hdr.enabled:
                el_time += point.dwell_s + float(getattr(hdr_settings, "max_point_time_s", 0.0))
            else:
                exposure, _gain, frames, interval = self.effective_camera(point)
                el_time += point.dwell_s + frames * exposure / 1000.0 + max(0, frames - 1) * interval
        el_time *= sequence_multiplier * max(1, self.el_sweep.repeat_count)
        el_time += max(0, self.el_sweep.repeat_count - 1) * self.el_sweep.inter_scan_delay_s
        if self.dark_frames.capture_after_el:
            dark_time *= 2
        return polarity_time + dark_iv_time + dark_time + el_time + 2.0

    def matrix_capture_counts(self) -> dict[str, int]:
        matrix = self.el_matrix
        channels = len(self.enabled_channels())
        combination = len(matrix.gains_percent) * len(matrix.exposures_ms) * matrix.repeat
        dark = combination if matrix.shared_dark_enabled else 0
        per_channel = len(matrix.current_density_ma_cm2) * combination
        total_el = channels * per_channel
        return {
            "shared_dark": dark,
            "el_per_channel": per_channel,
            "total_el": total_el,
            "overall": dark + total_el,
        }

    def is_available(self) -> bool:
        return self.state == "active" and not self.validate()

    def to_dict(self) -> dict[str, Any]:
        return normalize_json_numbers(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recipe":
        # V1 single-current Recipes are migrated into a one-point four-stage draft.
        old_camera = _dataclass_from_dict(CameraRecipe, data.get("camera"))
        el_data = data.get("el_sweep", {})
        if el_data:
            points = []
            for item in el_data.get("points", []):
                point = _dataclass_from_dict(ELPoint, item)
                # Pre-V1.3.1 rows explicitly disabling the override inherited
                # the camera-page defaults. Missing flags belong to the new
                # explicit-per-row schema and must preserve the row values.
                if "use_camera_override" in item and not bool(item["use_camera_override"]):
                    point.exposure_ms = old_camera.exposure_ms
                    point.gain_percent = old_camera.gain_percent
                    point.frame_count = old_camera.frame_count
                    point.frame_interval_s = old_camera.frame_interval_s
                points.append(point)
            sweep = _dataclass_from_dict(ELSweepRecipe, el_data)
            sweep.points = points
        else:
            old_smu = data.get("smu", {})
            point = ELPoint(
                setpoint=float(old_smu.get("source_value", 10.0)),
                dwell_s=float(old_smu.get("settle_time_s", 1.0)),
                exposure_ms=old_camera.exposure_ms,
                gain_percent=old_camera.gain_percent,
                frame_count=old_camera.frame_count,
                frame_interval_s=old_camera.frame_interval_s,
            )
            sweep = ELSweepRecipe(setpoint_basis="current", points=[point])
        original_measurement_type = str(data.get("measurement_type", "el_sequence"))
        measurement_type = original_measurement_type
        if original_measurement_type == "el_single_current":
            measurement_type = "el_sequence"
        output_data = dict(data.get("output") or {})
        # V1.2.1 used one ambiguous save_csv flag. It represented the required
        # Dark I-V / EL summary tables, not full-resolution pixel matrices.
        if "save_summary_csv" not in output_data and "save_csv" in output_data:
            output_data["save_summary_csv"] = bool(output_data["save_csv"])
        raw_channels = data.get("channels")
        if isinstance(raw_channels, list):
            channels = [_dataclass_from_dict(ChannelRecipe, item) for item in raw_channels]
        else:
            # Legacy files cannot reliably supply four Sample IDs. Preserve the
            # old area only for CH1 and force review by leaving its ID empty.
            legacy_area = float((data.get("geometry") or {}).get("active_area_cm2", 0.100))
            channels = _default_channels()
            channels[0].sample_id = ""
            channels[0].area_cm2 = legacy_area
        return cls(
            recipe_id=str(data.get("recipe_id") or uuid4()),
            name=str(data.get("name", "未命名 Recipe")),
            description=str(data.get("description", "")),
            measurement_type=measurement_type,
            version=max(1, int(data.get("version", 1))),
            state="draft" if original_measurement_type == "el_single_current" else str(data.get("state", "draft")),
            created_at=str(data.get("created_at", _now())),
            modified_at=str(data.get("modified_at", _now())),
            geometry=_dataclass_from_dict(GeometryRecipe, data.get("geometry")),
            channels=channels,
            el_matrix=_dataclass_from_dict(ELMatrixRecipe, data.get("el_matrix")),
            polarity=_dataclass_from_dict(PolarityRecipe, data.get("polarity")),
            dark_iv=_dataclass_from_dict(DarkIVRecipe, data.get("dark_iv")),
            camera=old_camera,
            hdr=_dataclass_from_dict(HDRRecipe, data.get("hdr")),
            el_sweep=sweep,
            dark_frames=_dataclass_from_dict(DarkFrameRecipe, data.get("dark_frames")),
            smu=_dataclass_from_dict(SMURecipe, data.get("smu")),
            safety=_dataclass_from_dict(SafetyRecipe, data.get("safety")),
            output=_dataclass_from_dict(OutputRecipe, output_data),
        )


class RecipeStore:
    """JSON-backed Recipe repository stored in the user's application-data folder."""

    schema_version = 7

    def __init__(self, path: Path) -> None:
        self.path = path
        self.recipes: list[Recipe] = []
        self.legacy_hdr_settings_candidate: dict[str, Any] | None = None
        self.load()

    def load(self) -> None:
        self.recipes = []
        self.legacy_hdr_settings_candidate = None
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            for item in payload.get("recipes", []):
                legacy_hdr = item.get("hdr") or {}
                if any(key != "enabled" for key in legacy_hdr):
                    self.legacy_hdr_settings_candidate = dict(legacy_hdr)
                    break
            self.recipes = [Recipe.from_dict(item) for item in payload.get("recipes", [])]
        except Exception as exc:
            raise RuntimeError(f"無法讀取 Recipe 檔案：{exc}") from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "saved_at": _now(),
            "recipes": [recipe.to_dict() for recipe in self.recipes],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def available(self) -> list[Recipe]:
        return sorted(
            (recipe for recipe in self.recipes if recipe.is_available()),
            key=lambda recipe: recipe.name.casefold(),
        )

    def get(self, recipe_id: str) -> Recipe | None:
        return next((recipe for recipe in self.recipes if recipe.recipe_id == recipe_id), None)

    def upsert(self, recipe: Recipe) -> None:
        recipe.modified_at = _now()
        existing = self.get(recipe.recipe_id)
        if existing is None:
            self.recipes.append(recipe)
        else:
            index = self.recipes.index(existing)
            comparable_existing = existing.to_dict()
            comparable_new = recipe.to_dict()
            for payload in (comparable_existing, comparable_new):
                payload.pop("modified_at", None)
                payload.pop("version", None)
            if comparable_existing != comparable_new:
                recipe.version = existing.version + 1
            self.recipes[index] = recipe
        self.save()

    def delete(self, recipe_id: str) -> None:
        self.recipes = [recipe for recipe in self.recipes if recipe.recipe_id != recipe_id]
        self.save()
