from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RunMode(str, Enum):
    PILOT = "pilot"
    FULL = "full_qualification"
    QUICK = "quick_verification"


class FrameType(str, Enum):
    LIGHT = "LIGHT"
    DARK = "DARK"


class QualificationResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class ROI:
    x: int
    y: int
    width: int
    height: int

    def validate(self, image_width: int, image_height: int) -> None:
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError("ROI must have non-negative origin and positive dimensions")
        if self.x + self.width > image_width or self.y + self.height > image_height:
            raise ValueError("ROI extends beyond image bounds")

    def slices(self) -> tuple[slice, slice]:
        return slice(self.y, self.y + self.height), slice(self.x, self.x + self.width)

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class CaptureCondition:
    gain_percent: int
    exposure_ms: float

    @property
    def key(self) -> str:
        return f"G{self.gain_percent}_E{self.exposure_ms:g}ms"


@dataclass(frozen=True)
class CapturePlan:
    mode: RunMode
    conditions: tuple[CaptureCondition, ...]
    light_repeats: int
    dark_repeats: int
    settling_frames: int
    adaptive_early_stop: bool = True

    @property
    def planned_frame_count(self) -> int:
        return len(self.conditions) * (self.light_repeats + self.dark_repeats)


@dataclass
class LoadedFrame:
    tiff_path: Path
    sidecar_path: Path | None
    image: Any
    frame_type: FrameType | None
    gain_percent: int | None
    requested_exposure_ms: float | None
    actual_exposure_ms: float | None
    repeat_index: int | None
    frame_sequence: int | None
    temperature_c: float | None
    effective_dn_max: int | None
    sensor_bit_depth: int | None
    raw_alignment: str
    roi: ROI | None
    metadata: dict[str, Any] = field(default_factory=dict)
    image_shape: tuple[int, ...] | None = None
    image_dtype: str | None = None


@dataclass
class PreflightResult:
    tiff_count: int = 0
    json_count: int = 0
    missing_sidecars: list[str] = field(default_factory=list)
    unparseable_files: list[str] = field(default_factory=list)
    dtypes: set[str] = field(default_factory=set)
    shapes: set[tuple[int, ...]] = field(default_factory=set)
    bit_depths: set[int] = field(default_factory=set)
    effective_dn_maxima: set[int] = field(default_factory=set)
    alignments: set[str] = field(default_factory=set)
    gains: set[int] = field(default_factory=set)
    exposures_ms: set[float] = field(default_factory=set)
    light_conditions: dict[str, int] = field(default_factory=dict)
    dark_conditions: dict[str, int] = field(default_factory=dict)
    temperatures_c: list[float] = field(default_factory=list)
    duplicate_frames: list[str] = field(default_factory=list)
    readback_mismatches: list[str] = field(default_factory=list)
    sequence_anomalies: list[str] = field(default_factory=list)
    roi_compatible: bool = True
    critical_errors: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @property
    def matching_dark_complete(self) -> bool:
        return bool(self.light_conditions) and all(
            self.dark_conditions.get(key, 0) > 0 for key in self.light_conditions
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("dtypes", "shapes", "bit_depths", "effective_dn_maxima", "alignments", "gains", "exposures_ms"):
            value[key] = sorted(value[key])
        return value


@dataclass
class AnalysisOutcome:
    overall: QualificationResult
    summary: dict[str, Any]
    tables: dict[str, list[dict[str, Any]]]
    profile: dict[str, Any]
    preflight: PreflightResult
    output_dir: Path | None = None
