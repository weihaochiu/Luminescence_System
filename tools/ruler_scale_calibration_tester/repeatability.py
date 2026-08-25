from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
import statistics

from core.calibration.models import CalibrationResult, VerificationMode


class DuplicateSourceError(ValueError):
    pass


@dataclass(frozen=True)
class RepeatabilityRun:
    run_id: int
    timestamp: str
    source_type: str
    source_identity: str
    frame_sequence: int | None
    filename: str
    ruler_angle_deg: float | None
    pixels_per_mm: float
    um_per_pixel: float
    fit_error_percent: float | None
    quality_score: float
    verification_mode: str
    ocr_usable: bool

    @classmethod
    def from_result(cls, result: CalibrationResult, run_id: int) -> RepeatabilityRun:
        verified = {
            VerificationMode.TICK_HIERARCHY_VERIFIED.value,
            VerificationMode.OCR_VERIFIED.value,
        }
        if (
            not result.success
            or result.verification_mode not in verified
            or result.pixels_per_mm is None
            or result.um_per_pixel is None
        ):
            raise ValueError("Only a successful physically verified calibration can be added")
        if not result.source_identity:
            raise ValueError("Calibration result has no source identity")
        return cls(
            run_id=run_id,
            timestamp=result.timestamp,
            source_type=result.source_type,
            source_identity=result.source_identity,
            frame_sequence=result.captured_frame_sequence,
            filename=result.source_filename,
            ruler_angle_deg=result.ruler_angle_deg,
            pixels_per_mm=float(result.pixels_per_mm),
            um_per_pixel=float(result.um_per_pixel),
            fit_error_percent=result.fit_error_percent,
            quality_score=float(result.quality_score),
            verification_mode=result.verification_mode,
            ocr_usable=bool(result.ocr_usable),
        )


class RepeatabilitySession:
    COLUMNS = (
        "run",
        "timestamp",
        "source_type",
        "source_identity",
        "frame_sequence",
        "filename",
        "angle_deg",
        "pixels_per_mm",
        "um_per_pixel",
        "fit_error_percent",
        "quality_score",
        "verification_mode",
        "ocr_usable",
    )

    def __init__(self) -> None:
        self.runs: list[RepeatabilityRun] = []
        self._source_identities: set[str] = set()

    def add_result(self, result: CalibrationResult) -> RepeatabilityRun:
        run = RepeatabilityRun.from_result(result, len(self.runs) + 1)
        if run.source_identity in self._source_identities:
            raise DuplicateSourceError(
                "This captured frame has already been added to this repeatability session."
            )
        self.runs.append(run)
        self._source_identities.add(run.source_identity)
        return run

    def clear(self) -> None:
        self.runs.clear()
        self._source_identities.clear()

    def summary(self) -> dict[str, float | int | None]:
        return repeatability_summary([run.pixels_per_mm for run in self.runs])

    def export_csv(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(self.COLUMNS)
            for run in self.runs:
                writer.writerow((
                    run.run_id,
                    run.timestamp,
                    run.source_type,
                    run.source_identity,
                    run.frame_sequence,
                    run.filename,
                    run.ruler_angle_deg,
                    run.pixels_per_mm,
                    run.um_per_pixel,
                    run.fit_error_percent,
                    run.quality_score,
                    run.verification_mode,
                    run.ocr_usable,
                ))
            writer.writerow([])
            writer.writerow(("summary_metric", "value"))
            summary = self.summary()
            for metric in (
                "n",
                "mean_pixels_per_mm",
                "sd_pixels_per_mm",
                "cv_percent",
                "min_pixels_per_mm",
                "max_pixels_per_mm",
                "max_deviation_percent",
            ):
                writer.writerow((metric, summary[metric]))
        temporary.replace(destination)
        return destination


def repeatability_summary(values: list[float]) -> dict[str, float | int | None]:
    finite = [float(value) for value in values if math.isfinite(float(value)) and float(value) > 0]
    if not finite:
        return {
            "n": 0,
            "mean_pixels_per_mm": None,
            "sd_pixels_per_mm": None,
            "cv_percent": None,
            "min_pixels_per_mm": None,
            "max_pixels_per_mm": None,
            "max_deviation_percent": None,
        }
    mean = statistics.fmean(finite)
    sd = statistics.stdev(finite) if len(finite) > 1 else 0.0
    max_deviation = max(abs(value - mean) for value in finite) / mean * 100.0
    return {
        "n": len(finite),
        "mean_pixels_per_mm": mean,
        "sd_pixels_per_mm": sd,
        "cv_percent": sd / mean * 100.0,
        "min_pixels_per_mm": min(finite),
        "max_pixels_per_mm": max(finite),
        "max_deviation_percent": max_deviation,
    }
