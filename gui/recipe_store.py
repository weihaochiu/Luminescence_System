from __future__ import annotations

import json
import logging
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from .numeric import decimal_from_number, normalize_json_numbers, quantize_number
from uuid import uuid4


LOG = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


T = TypeVar("T")


def _dataclass_from_dict(cls: type[T], data: dict[str, Any] | None) -> T:
    """Load known keys from a validated mapping."""
    if data is not None and not isinstance(data, dict):
        raise ValueError(f"{cls.__name__} must be a JSON object")
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
    area_cm2: float = 0.100


def _default_channels() -> list[ChannelRecipe]:
    return [
        ChannelRecipe(f"CH{index}", index == 1, 0.100)
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
    dark_frame_enabled: bool = True
    capture_timeout_s: float = 20.0
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
class LegacyCameraRecipe:
    """Migration DTO for Recipe schema versions that had a camera page."""
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
class LegacyELPoint:
    enabled: bool = True
    setpoint: float = 1.0
    dwell_s: float = 0.50
    exposure_ms: float = 500.0
    gain_percent: int = 10
    frame_count: int = 3
    frame_interval_s: float = 0.10


@dataclass
class LegacyELSweepRecipe:
    """Migration DTO for the removed per-row EL point model."""
    drive_mode: str = "current"
    setpoint_basis: str = "current_density"
    scan_direction: str = "ascending"
    repeat_count: int = 1
    inter_scan_delay_s: float = 1.0
    voltage_compliance_v: float = 3.0
    current_compliance_ma: float = 20.0
    return_to_zero: bool = True
    output_off_after: bool = True
    points: list[LegacyELPoint] = field(
        default_factory=lambda: [
            LegacyELPoint(setpoint=0.1),
            LegacyELPoint(setpoint=0.3),
            LegacyELPoint(setpoint=1.0),
            LegacyELPoint(setpoint=3.0),
            LegacyELPoint(setpoint=10.0),
            LegacyELPoint(setpoint=20.0),
        ]
    )


@dataclass
class OutputRecipe:
    resolution_id: str = "full"
    format_tiff: bool = True
    format_png: bool = False
    format_jpg: bool = False
    format_jpg_with_footer: bool = True
    save_raw_frames: bool = True
    save_summary_csv: bool = True
    save_json: bool = True
    save_recipe_snapshot: bool = True
    export_pixel_csv: bool = False
    pixel_csv_raw: bool = True
    pixel_csv_dark_corrected: bool = True
    pixel_csv_exposure_normalized: bool = False

    def selected_formats(self) -> tuple[str, ...]:
        return tuple(
            label
            for label, enabled in (
                ("TIFF", self.format_tiff),
                ("PNG", self.format_png),
                ("JPG", self.format_jpg),
                ("JPG with Footer", self.format_jpg_with_footer),
            )
            if enabled
        )


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
    output: OutputRecipe = field(default_factory=OutputRecipe)
    import_review_items: list[str] = field(default_factory=list)

    def clone(self) -> "Recipe":
        copied = deepcopy(self)
        copied.recipe_id = str(uuid4())
        copied.name = f"{self.name} - 複本"
        copied.version = 1
        copied.state = "draft"
        copied.created_at = _now()
        copied.modified_at = copied.created_at
        return copied

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

    def dark_profiles(self) -> list[dict[str, Any]]:
        """Return the Shared Dark profiles required by the Matrix capture axes."""

        profiles: dict[tuple[Any, ...], dict[str, Any]] = {}
        for gain in self.el_matrix.gains_percent:
            for exposure in self.el_matrix.exposures_ms:
                exposure = float(exposure)
                gain = int(gain)
                key = (round(exposure, 6), gain, self.output.resolution_id, "RGB48")
                profiles.setdefault(
                    key,
                    {
                        "profile_id": f"DARK_EXP{exposure:g}_GAIN{gain}",
                        "exposure_ms": exposure,
                        "gain_percent": gain,
                        "resolution": self.output.resolution_id,
                        "pixel_format": "RGB48",
                        "trigger_mode": "software",
                    },
                )
        return list(profiles.values())

    def dark_iv_point_count(self) -> int:
        if self.dark_iv.step_v <= 0:
            return 0
        count = int(math.floor(abs(self.dark_iv.stop_v - self.dark_iv.start_v) / self.dark_iv.step_v + 1e-9)) + 1
        if self.dark_iv.direction == "bidirectional":
            count = count * 2 - 1
        return count * max(1, self.dark_iv.repeat_count)

    def dark_iv_estimated_time_s(self) -> float:
        return (
            self.dark_iv.dark_stabilization_s
            + self.dark_iv_point_count()
            * (self.dark_iv.dwell_s + self.dark_iv.nplc / 50.0)
            + max(0, self.dark_iv.repeat_count - 1)
            * self.dark_iv.inter_scan_delay_s
        )

    def matrix_output_on_time_s(self) -> float:
        """Worst continuous OUTPUT ON interval from the formal runtime plan."""

        from .el_matrix_plan import ELMatrixPlan

        return ELMatrixPlan(self).estimate().output_on_per_j_s

    def matrix_estimated_time_s(self) -> float:
        from .el_matrix_plan import ELMatrixPlan

        return ELMatrixPlan(self).estimate().total_time_s

    def matrix_worst_power_mw(self) -> float:
        currents = [
            self.matrix_source_current_ma(channel, float(density))
            for channel in self.enabled_channels()
            for density in self.el_matrix.current_density_ma_cm2
        ]
        return max(currents, default=0.0) * self.el_matrix.voltage_compliance_v

    def validation_warnings(self) -> list[str]:
        warnings: list[str] = []
        if len(self.el_matrix.gains_percent) > 1 or len(self.el_matrix.exposures_ms) > 1:
            if len(self.el_matrix.gains_percent) > 1:
                warnings.append("不同 EL 點使用不同 Gain；未完成 Gain 校正前不可直接建立定量 EL–I 或 k mapping")
            else:
                warnings.append("不同 EL 點使用不同曝光；跨曝光比較需扣除匹配 Dark 並做曝光正規化")
        return warnings

    def validate(
        self,
        global_safety: Any | None = None,
    ) -> list[str]:
        """Validate formal Recipe data against application-wide safety limits."""

        errors: list[str] = []
        if not self.name.strip():
            errors.append("Recipe 名稱不可空白")
        if self.measurement_type != "el_sequence":
            errors.append("Recipe 類型必須是 EL Matrix 量測")
        if self.geometry.active_area_cm2 <= 0:
            errors.append("Active area 必須大於 0")
        expected_channels = [f"CH{index}" for index in range(1, 5)]
        if [channel.channel for channel in self.channels] != expected_channels:
            errors.append("Channel 必須固定且依序為 CH1～CH4")
        enabled_channels = self.enabled_channels()
        if not enabled_channels:
            errors.append("至少需要啟用一個 Channel")
        for channel in enabled_channels:
            if not math.isfinite(channel.area_cm2) or channel.area_cm2 <= 0:
                errors.append(f"{channel.channel} 的 Device Area 必須大於 0")

        matrix = self.el_matrix
        if not matrix.current_density_ma_cm2 or any(
            not math.isfinite(float(value)) or float(value) <= 0
            for value in matrix.current_density_ma_cm2
        ):
            errors.append("Current Density 必須包含大於 0 的有限數值")
        if not matrix.exposures_ms or any(
            not math.isfinite(float(value)) or float(value) <= 0
            for value in matrix.exposures_ms
        ):
            errors.append("Exposure 必須包含大於 0 的有限數值")
        if not matrix.gains_percent or any(int(value) < 0 for value in matrix.gains_percent):
            errors.append("Gain 必須包含大於或等於 0 的數值")
        if matrix.repeat < 1:
            errors.append("每條件拍攝張數必須大於或等於 1")
        if matrix.stabilization_ms < 0:
            errors.append("J Stabilization Time 不可小於 0")
        if matrix.capture_timeout_s <= 0:
            errors.append("相機 timeout 必須大於 0")
        longest_exposure_s = max(
            (float(value) / 1000.0 for value in matrix.exposures_ms), default=0.0
        )
        if matrix.capture_timeout_s < longest_exposure_s:
            errors.append("相機 timeout 不可短於最大曝光時間")

        maximum_current_ma = float(
            getattr(global_safety, "maximum_current_a", 0.050)
        ) * 1000.0
        maximum_voltage_v = float(getattr(global_safety, "maximum_voltage_v", 5.0))
        maximum_power_mw = float(
            getattr(global_safety, "maximum_power_w", 0.150)
        ) * 1000.0
        maximum_voltage_compliance_v = float(
            getattr(global_safety, "maximum_voltage_compliance_v", maximum_voltage_v)
        )
        maximum_current_compliance_ma = float(
            getattr(global_safety, "maximum_current_compliance_a", 0.050)
        ) * 1000.0
        if not math.isfinite(matrix.voltage_compliance_v) or not (
            0 < matrix.voltage_compliance_v <= maximum_voltage_compliance_v
        ):
            errors.append("EL Matrix Voltage Compliance 超過全域安全設定")
        if any(
            self.matrix_source_current_ma(channel, float(density)) > maximum_current_ma
            for channel in enabled_channels
            for density in matrix.current_density_ma_cm2
        ):
            errors.append("EL Matrix 計算出的 Source Current 超過全域安全設定")
        if self.matrix_worst_power_mw() > maximum_power_mw:
            errors.append("EL Matrix 最壞 Compliance 功率超過全域安全設定")

        if self.dark_iv.enabled:
            if self.dark_iv.step_v <= 0 or self.dark_iv.start_v == self.dark_iv.stop_v:
                errors.append("Dark I–V 必須設定非零範圍及大於 0 的 Step")
            if max(abs(self.dark_iv.start_v), abs(self.dark_iv.stop_v)) > maximum_voltage_v:
                errors.append("Dark I–V 掃描電壓超過全域安全設定")
            if not 0 < self.dark_iv.current_compliance_ma <= maximum_current_compliance_ma:
                errors.append("Dark I–V current compliance 超過全域安全設定")

        if not self.output.selected_formats():
            errors.append("至少必須選擇一種影像輸出格式")
        if not self.output.save_summary_csv:
            errors.append("Dark I–V 與 EL scan summary CSV 是必要輸出")
        if not self.output.save_json:
            errors.append("EL 量測必須保存 JSON metadata")
        if not self.output.save_recipe_snapshot:
            errors.append("EL 量測必須保存 Recipe 快照")
        if self.output.export_pixel_csv and not any((
            self.output.pixel_csv_raw,
            self.output.pixel_csv_dark_corrected,
            self.output.pixel_csv_exposure_normalized,
        )):
            errors.append("啟用全解析度像素 CSV 時，至少要選擇一種輸出內容")
        if self.output.export_pixel_csv and not self.output.format_tiff:
            errors.append("Pixel CSV 後處理需要 TIFF 科學影像來源")
        return errors

    def estimated_time_s(self) -> float:
        return self.matrix_estimated_time_s()

    def matrix_capture_counts(self) -> dict[str, int]:
        from .measurement_execution_plan import effective_matrix_capture_axes

        matrix = self.el_matrix
        axes = effective_matrix_capture_axes(self)
        channels = len(self.enabled_channels())
        combination = (
            len(axes.gains_percent) * len(axes.exposures_ms) * axes.repeat
        )
        dark = combination if matrix.dark_frame_enabled else 0
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
        if not isinstance(data, dict):
            raise ValueError("Recipe must be a JSON object")
        if "safety" in data or "smu" in data:
            LOG.warning(
                "Legacy Recipe safety/SMU values were detected and ignored; they did "
                "not override application-wide safety settings"
            )
        if "hdr" in data:
            LOG.warning("Legacy HDR configuration was removed and ignored.")
        # V1 single-current Recipes are migrated into a one-point four-stage draft.
        old_camera = _dataclass_from_dict(LegacyCameraRecipe, data.get("camera"))
        el_data = data.get("el_sweep", {})
        if el_data:
            points = []
            for item in el_data.get("points", []):
                point = _dataclass_from_dict(LegacyELPoint, item)
                # Pre-V1.3.1 rows explicitly disabling the override inherited
                # the camera-page defaults. Missing flags belong to the new
                # explicit-per-row schema and must preserve the row values.
                if "use_camera_override" in item and not bool(item["use_camera_override"]):
                    point.exposure_ms = old_camera.exposure_ms
                    point.gain_percent = old_camera.gain_percent
                    point.frame_count = old_camera.frame_count
                    point.frame_interval_s = old_camera.frame_interval_s
                points.append(point)
            sweep = _dataclass_from_dict(LegacyELSweepRecipe, el_data)
            sweep.points = points
        else:
            old_smu = data.get("smu", {})
            point = LegacyELPoint(
                setpoint=float(old_smu.get("source_value", 10.0)),
                dwell_s=float(old_smu.get("settle_time_s", 1.0)),
                exposure_ms=old_camera.exposure_ms,
                gain_percent=old_camera.gain_percent,
                frame_count=old_camera.frame_count,
                frame_interval_s=old_camera.frame_interval_s,
            )
            sweep = LegacyELSweepRecipe(setpoint_basis="current", points=[point])
        original_measurement_type = str(data.get("measurement_type", "el_sequence"))
        measurement_type = original_measurement_type
        if original_measurement_type == "el_single_current":
            measurement_type = "el_sequence"
        output_data = dict(data.get("output") or {})
        # V1.2.1 used one ambiguous save_csv flag. It represented the required
        # Dark I-V / EL summary tables, not full-resolution pixel matrices.
        if "save_summary_csv" not in output_data and "save_csv" in output_data:
            output_data["save_summary_csv"] = bool(output_data["save_csv"])
        legacy_format = str(output_data.get("image_format", "")).upper()
        if legacy_format and not any(
            key in output_data
            for key in (
                "format_tiff", "format_png", "format_jpg", "format_jpg_with_footer"
            )
        ):
            output_data.update({
                "format_tiff": legacy_format in {"TIF", "TIFF"},
                "format_png": legacy_format == "PNG",
                "format_jpg": legacy_format in {"JPG", "JPEG"},
                "format_jpg_with_footer": legacy_format in {
                    "TIF", "TIFF", "JPG", "JPEG"
                },
            })
        matrix_data = dict(data.get("el_matrix") or {})
        if "dark_frame_enabled" not in matrix_data and "shared_dark_enabled" in matrix_data:
            matrix_data["dark_frame_enabled"] = bool(matrix_data["shared_dark_enabled"])
        migration_ambiguous = False
        if (
            not any(
                key in matrix_data
                for key in (
                    "current_density_ma_cm2", "gains_percent", "exposures_ms"
                )
            )
            and (el_data or original_measurement_type == "el_single_current")
        ):
            legacy_points = [point for point in sweep.points if point.enabled]
            area = float((data.get("geometry") or {}).get("active_area_cm2", 0.100))
            basis = str(sweep.setpoint_basis)
            if basis in {"current", "current_density"} and legacy_points:
                densities = [
                    float(point.setpoint)
                    if basis == "current_density"
                    else float(point.setpoint) / max(area, 1e-12)
                    for point in legacy_points
                ]
                matrix_data["current_density_ma_cm2"] = list(dict.fromkeys(densities))
            else:
                migration_ambiguous = True
                LOG.warning(
                    "Legacy voltage-driven EL points cannot be represented exactly by "
                    "the current-density Matrix; default Matrix points were retained"
                )
            if legacy_points:
                matrix_data["gains_percent"] = list(dict.fromkeys(
                    int(point.gain_percent) for point in legacy_points
                ))
                matrix_data["exposures_ms"] = list(dict.fromkeys(
                    float(point.exposure_ms) for point in legacy_points
                ))
                matrix_data["repeat"] = max(
                    1, max(int(point.frame_count) for point in legacy_points)
                )
                matrix_data["stabilization_ms"] = max(
                    0, round(max(float(point.dwell_s) for point in legacy_points) * 1000)
                )
                matrix_data["voltage_compliance_v"] = float(
                    sweep.voltage_compliance_v
                )
                combinations = (
                    len(matrix_data.get("current_density_ma_cm2", []))
                    * len(matrix_data["gains_percent"])
                    * len(matrix_data["exposures_ms"])
                )
                if combinations != len(legacy_points):
                    migration_ambiguous = True
                    LOG.warning(
                        "Legacy per-row EL points expanded into Matrix axes; Recipe was "
                        "migrated as draft for operator review"
                    )
        legacy_dark = data.get("dark_frames")
        if (
            isinstance(legacy_dark, dict)
            and "dark_frame_enabled" not in matrix_data
        ):
            matrix_data["dark_frame_enabled"] = bool(
                legacy_dark.get("save_master_dark", True)
            )
        raw_channels = data.get("channels")
        if isinstance(raw_channels, list):
            channels = [_dataclass_from_dict(ChannelRecipe, item) for item in raw_channels]
            if any(str(item.get("sample_id", "")).strip() for item in raw_channels):
                LOG.warning(
                    "Legacy Recipe Sample IDs were ignored; enter them in the Main Window"
                )
        else:
            # Legacy files cannot reliably supply four Sample IDs. Preserve the
            # old area only for CH1 and force review by leaving its ID empty.
            legacy_area = float((data.get("geometry") or {}).get("active_area_cm2", 0.100))
            channels = _default_channels()
            channels[0].area_cm2 = legacy_area
        return cls(
            recipe_id=str(data.get("recipe_id") or uuid4()),
            name=str(data.get("name", "未命名 Recipe")),
            description=str(data.get("description", "")),
            measurement_type=measurement_type,
            version=max(1, int(data.get("version", 1))),
            state=(
                "draft"
                if original_measurement_type == "el_single_current" or migration_ambiguous
                else str(data.get("state", "draft"))
            ),
            created_at=str(data.get("created_at", _now())),
            modified_at=str(data.get("modified_at", _now())),
            geometry=_dataclass_from_dict(GeometryRecipe, data.get("geometry")),
            channels=channels,
            el_matrix=_dataclass_from_dict(ELMatrixRecipe, matrix_data),
            polarity=_dataclass_from_dict(PolarityRecipe, data.get("polarity")),
            dark_iv=_dataclass_from_dict(DarkIVRecipe, data.get("dark_iv")),
            output=_dataclass_from_dict(OutputRecipe, output_data),
            import_review_items=[str(item) for item in data.get("import_review_items", [])]
            if isinstance(data.get("import_review_items", []), list) else [],
        )


class RecipeStore:
    """JSON-backed Recipe repository stored in the user's application-data folder."""

    schema_version = 10

    def __init__(self, path: Path) -> None:
        self.path = path
        self.recipes: list[Recipe] = []
        self.load()

    def load(self) -> None:
        self.recipes = []
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Recipe repository root must be a JSON object")
            schema = payload.get("schema_version", 1)
            if not isinstance(schema, int) or isinstance(schema, bool):
                raise ValueError("schema_version must be an integer")
            if schema > self.schema_version:
                raise ValueError(
                    f"Recipe schema {schema} is newer than supported schema {self.schema_version}"
                )
            raw_recipes = payload.get("recipes", [])
            if not isinstance(raw_recipes, list):
                raise ValueError("recipes must be a JSON array")
            for item in raw_recipes:
                if not isinstance(item, dict):
                    raise ValueError("Every Recipe entry must be a JSON object")
            self.recipes = [Recipe.from_dict(item) for item in raw_recipes]
        except Exception as exc:
            raise RuntimeError(f"無法讀取 Recipe 檔案：{exc}") from exc

    def import_payload(self, payload: Any) -> Recipe:
        """Validate, migrate, and import one untrusted Recipe JSON payload."""

        if not isinstance(payload, dict):
            raise ValueError("匯入檔案頂層必須是 JSON object")
        schema = payload.get("schema_version")
        if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
            raise ValueError("匯入檔案必須包含有效的整數 schema_version")
        if schema > self.schema_version:
            raise ValueError(
                f"Recipe schema_version={schema} 高於目前支援版本 {self.schema_version}，拒絕匯入"
            )
        data = payload.get("recipe")
        if not isinstance(data, dict):
            raise ValueError("匯入檔案必須包含 recipe JSON object")
        allowed = {item.name for item in fields(Recipe)} | {
            "camera", "el_sweep", "dark_frames", "smu", "safety", "hdr"
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError("Recipe 含有不支援欄位：" + ", ".join(unknown))
        if schema == self.schema_version:
            deprecated_sections = sorted(
                {"camera", "el_sweep", "dark_frames", "smu", "safety"} & set(data)
            )
            if deprecated_sections:
                raise ValueError(
                    "Recipe schema v10 不可包含已移除欄位："
                    + ", ".join(deprecated_sections)
                )
            sections: tuple[tuple[str, type[Any]], ...] = (
                ("geometry", GeometryRecipe), ("el_matrix", ELMatrixRecipe),
                ("polarity", PolarityRecipe), ("dark_iv", DarkIVRecipe),
                ("output", OutputRecipe),
            )
            for section, model in sections:
                raw = data.get(section)
                if raw is None:
                    continue
                if not isinstance(raw, dict):
                    raise ValueError(f"Recipe.{section} 必須是 JSON object")
                extra = sorted(set(raw) - {item.name for item in fields(model)})
                if extra:
                    raise ValueError(
                        f"Recipe.{section} 含有不支援欄位：" + ", ".join(extra)
                    )
            raw_channels = data.get("channels")
            if raw_channels is not None:
                if not isinstance(raw_channels, list):
                    raise ValueError("Recipe.channels 必須是 JSON array")
                channel_fields = {item.name for item in fields(ChannelRecipe)}
                for index, raw in enumerate(raw_channels):
                    if not isinstance(raw, dict):
                        raise ValueError(f"Recipe.channels[{index}] 必須是 JSON object")
                    extra = sorted(set(raw) - channel_fields)
                    if extra:
                        raise ValueError(
                            f"Recipe.channels[{index}] 含有不支援欄位：" + ", ".join(extra)
                        )
        important = {
            "name", "channels", "el_matrix", "polarity", "dark_iv", "output",
        }
        review = [f"缺少重要欄位：{key}" for key in sorted(important - set(data))]
        recipe = Recipe.from_dict(data)
        recipe.recipe_id = str(uuid4())
        recipe.version = 1
        recipe.state = "draft"
        recipe.created_at = _now()
        recipe.modified_at = recipe.created_at
        recipe.import_review_items = review
        self.upsert(recipe)
        return recipe

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
