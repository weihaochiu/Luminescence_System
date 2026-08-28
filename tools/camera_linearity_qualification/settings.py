from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


CRITERIA_VERSION = "1.0.0"


@dataclass(frozen=True)
class QualificationCriteria:
    version: str = CRITERIA_VERSION
    pilot_low_dn: float = 200.0
    pilot_high_dn: float = 2000.0
    pilot_middle_low_dn: float = 200.0
    pilot_middle_high_dn: float = 2000.0
    pilot_required_middle_points: int = 3
    early_stop_consecutive: int = 2
    early_stop_median_dn: float = 2200.0
    early_stop_p99_dn: float = 4000.0
    early_stop_saturated_fraction: float = 0.001
    capture_timeout_multiplier: float = 1.5
    capture_timeout_overhead_s: float = 3.0
    compression_ratio: float = 0.95
    low_snr_dn: float = 20.0
    excellent_r2: float = 0.9995
    excellent_max_residual_percent: float = 1.0
    good_r2: float = 0.999
    good_max_residual_percent: float = 2.0
    acceptable_r2: float = 0.995
    acceptable_max_residual_percent: float = 5.0
    pass_min_linear_points: int = 5
    pass_r2: float = 0.999
    pass_max_residual_percent: float = 2.0
    repeat_cv_max_percent: float = 2.0
    temperature_span_max_c: float = 5.0
    saturation_warning_fraction: float = 0.95
    saturation_reject_fraction: float = 0.98
    hot_pixel_fraction_of_full_scale: float = 0.98
    transition_first_frame_deviation_percent: float = 10.0
    transition_nonmonotonic_tolerance_percent: float = 2.0
    dark_preview_light_ratio_max: float = 0.25
    dark_preview_absolute_max_dn: float = 200.0
    hdr_median_error_max_percent: float = 3.0
    hdr_p95_error_max_percent: float = 10.0
    hdr_min_overlap_fraction: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QualificationCriteria":
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in payload.items() if key in known})

    @classmethod
    def load(cls, path: str | Path) -> "QualificationCriteria":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        from .capture_manifest import atomic_write_json
        atomic_write_json(Path(path), self.to_dict())
