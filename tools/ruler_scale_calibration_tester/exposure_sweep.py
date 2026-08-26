from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
from pathlib import Path
from threading import Event
from typing import Callable

from core.calibration.acquisition_quality import RulerAcquisitionQualityEvaluator

from .capture_history import CaptureHistoryStore
from .ruler_auto_exposure import RulerCameraAdapter, RulerAECancelled
from .source import AnalysisSource


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SWEEP_ROOT = PROJECT_ROOT / "local" / "generated" / "ruler_exposure_sweeps"


@dataclass(frozen=True)
class ControlledExposureSweepConfig:
    relative_exposures: tuple[float, ...] = (
        0.25, 0.35, 0.50, 0.70, 1.00, 1.40, 2.00, 2.80, 4.00
    )
    repetitions: int = 3
    settling_frames: int = 1


class ControlledExposureSweepRunner:
    """Diagnostic-only controlled dataset collector; never used as production AE."""

    def __init__(
        self,
        service: object,
        config: ControlledExposureSweepConfig | None = None,
        evaluator: RulerAcquisitionQualityEvaluator | None = None,
        output_root: str | Path = DEFAULT_SWEEP_ROOT,
    ) -> None:
        self.service = service
        self.config = config or ControlledExposureSweepConfig()
        self.evaluator = evaluator or RulerAcquisitionQualityEvaluator()
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        self.output = Path(output_root) / stamp
        self.history = CaptureHistoryStore(self.output / "captures")

    def run(
        self,
        camera: RulerCameraAdapter,
        device_name: str,
        cancel_event: Event | None = None,
    ) -> Path:
        cancel = cancel_event or Event()
        state = camera.snapshot_state()
        limits = camera.limits()
        baseline = int(state.get("ExposureReadbackUs") or limits.exposure_min_us)
        base_gain = limits.gain_min
        exposures = sorted({
            min(
                limits.exposure_max_us,
                max(limits.exposure_min_us, int(round(baseline * multiplier))),
            )
            for multiplier in self.config.relative_exposures
        })
        self.output.mkdir(parents=True, exist_ok=False)
        rows: list[dict[str, object]] = []

        def check_cancel() -> None:
            if cancel.is_set():
                raise RulerAECancelled("controlled_exposure_sweep_cancelled")

        try:
            for exposure in exposures:
                for repetition in range(1, self.config.repetitions + 1):
                    check_cancel()
                    acquired = camera.capture(
                        exposure,
                        base_gain,
                        self.config.settling_frames,
                        check_cancel,
                    )
                    metadata = dict(acquired.metadata)
                    timestamp = acquired.captured_at or datetime.now().astimezone().isoformat(timespec="milliseconds")
                    source_identity = (
                        f"sweep|{device_name}|frame={acquired.frame_sequence}|captured={timestamp}"
                    )
                    source = AnalysisSource(
                        source_type="camera",
                        source_identity=source_identity,
                        frame_sequence=acquired.frame_sequence,
                        display_name=source_identity,
                        capture_timestamp=timestamp,
                        acquisition_metadata=metadata,
                    )
                    pending = self.history.begin_capture(acquired.raw, source)
                    result = self.service.analyze(
                        acquired.raw,
                        input_source=source.display_name,
                        source_type="camera",
                        source_identity=source.source_identity,
                        source_display_name=source.display_name,
                        captured_frame_sequence=source.frame_sequence,
                    )
                    maximum = metadata.get("EffectiveDNMax")
                    metrics = (
                        self.evaluator.evaluate(
                            acquired.raw,
                            result,
                            int(maximum),
                            str(metadata.get("RawValueAlignment") or "unknown"),
                        )
                        if maximum is not None else None
                    )
                    result.diagnostics["controlled_exposure_sweep"] = {
                        "baseline_exposure_us": baseline,
                        "requested_exposure_us": exposure,
                        "repetition": repetition,
                    }
                    self.history.finalize(pending, result)
                    rows.append({
                        "capture_id": pending.capture_id,
                        "exposure_us": metadata.get("ExposureReadbackUs"),
                        "gain": metadata.get("GainReadback"),
                        "global_sat": None if metrics is None else metrics.global_saturation_fraction,
                        "ruler_sat": None if metrics is None else metrics.ruler_roi_saturation_fraction,
                        "tick_sat": None if metrics is None else metrics.tick_band_saturation_fraction,
                        "michelson": None if metrics is None else metrics.michelson_tick_contrast,
                        "normalized_contrast": None if metrics is None else metrics.normalized_tick_contrast,
                        "accepted_ticks": None if metrics is None else metrics.accepted_tick_count,
                        "periodicity_support": None if metrics is None else metrics.periodicity_support,
                        "hierarchy_verified": None if metrics is None else metrics.hierarchy_verified,
                        "calibration_pass": result.success,
                        "failure_reason": ";".join(result.failure_reasons),
                    })
        finally:
            try:
                camera.restore_state(state)
            finally:
                self._write_outputs(rows, baseline, base_gain, exposures)
        return self.output

    def _write_outputs(
        self,
        rows: list[dict[str, object]],
        baseline: int,
        gain: int,
        exposures: list[int],
    ) -> None:
        fields = list(rows[0]) if rows else [
            "capture_id", "exposure_us", "gain", "global_sat", "ruler_sat",
            "tick_sat", "michelson", "normalized_contrast", "accepted_ticks",
            "periodicity_support", "hierarchy_verified", "calibration_pass", "failure_reason",
        ]
        with (self.output / "sweep_results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        passes = sum(bool(row.get("calibration_pass")) for row in rows)
        (self.output / "summary.txt").write_text(
            "\n".join((
                "Controlled Ruler Exposure Sweep",
                f"baseline_exposure_us={baseline}",
                f"base_gain={gain}",
                f"unique_clamped_exposures={','.join(map(str, exposures))}",
                f"captures={len(rows)}",
                f"passes={passes}",
                "All data is diagnostic-only under local/generated.",
            )) + "\n",
            encoding="utf-8",
        )
