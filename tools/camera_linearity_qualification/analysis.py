from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable

import numpy as np

from .image_loader import effective_array, load_folder
from .models import (
    AnalysisOutcome, FrameType, LoadedFrame, PreflightResult,
    QualificationResult, ROI, RunMode,
)
from .profile import build_profile
from .regression import RegressionResult, is_monotonic, linear_regression
from .report import write_outputs
from .settings import QualificationCriteria
from .capture_manifest import sha256_file


class CameraLinearityAnalyzer:
    def __init__(self, criteria: QualificationCriteria | None = None) -> None:
        self.criteria = criteria or QualificationCriteria()

    def analyze_folder(
        self,
        folder: str | Path,
        *,
        output_dir: str | Path | None = None,
        roi: ROI | None = None,
        mode: RunMode | str = RunMode.FULL,
        synthetic: bool = False,
        full_frame_confirmed: bool = False,
    ) -> AnalysisOutcome:
        root = Path(folder)
        frames, errors = load_folder(root)
        outcome = self.analyze_frames(
            frames, roi=roi, mode=mode, synthetic=synthetic,
            full_frame_confirmed=full_frame_confirmed, load_errors=errors,
            manifest_path=root / "capture_manifest.json",
            operator_evidence=_operator_evidence(root / "capture_manifest.json"),
        )
        destination = Path(output_dir) if output_dir is not None else root / "ANALYSIS"
        representative = next((effective_array(frame) for frame in frames if frame.frame_type is FrameType.LIGHT), None)
        write_outputs(outcome, destination, representative)
        return outcome

    def analyze_frames(
        self,
        frames: list[LoadedFrame],
        *,
        roi: ROI | None = None,
        mode: RunMode | str = RunMode.FULL,
        synthetic: bool = False,
        full_frame_confirmed: bool = False,
        load_errors: Iterable[str] = (),
        manifest_path: Path | None = None,
        operator_evidence: bool = False,
    ) -> AnalysisOutcome:
        selected_mode = RunMode(mode)
        synthetic = bool(synthetic or any(
            str(frame.metadata.get("CameraSerial", "")).upper().startswith("SYNTHETIC")
            or bool(frame.metadata.get("synthetic_dataset"))
            for frame in frames
        ))
        operator_evidence = bool(operator_evidence or synthetic)
        preflight = self._preflight(frames, list(load_errors), roi)
        tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if not frames:
            preflight.critical_errors.append("No TIFF frames found")
            summary = self._empty_summary(preflight, selected_mode, synthetic)
            profile = build_profile(summary, criteria=self.criteria, mode=selected_mode, synthetic=synthetic, source_paths=[], manifest_path=manifest_path)
            return AnalysisOutcome(QualificationResult.FAIL, summary, dict(tables), profile, preflight)

        shape = _frame_shape(frames[0])
        selected_roi = roi or self._common_roi(frames)
        if selected_roi is None:
            selected_roi = ROI(0, 0, shape[1], shape[0])
            if not full_frame_confirmed:
                preflight.limitations.append("Full-frame ROI used without explicit operator confirmation")
        try:
            selected_roi.validate(shape[1], shape[0])
        except ValueError as exc:
            preflight.critical_errors.append(str(exc))
        self._inventory_tables(frames, tables)

        valid_frames: list[LoadedFrame] = []
        for frame in frames:
            try:
                effective = effective_array(frame)
                if effective.shape != shape:
                    raise ValueError("Resolution inconsistency")
                selected_roi.validate(effective.shape[1], effective.shape[0])
                region = effective[selected_roi.slices()]
                valid_frames.append(frame)
                tables["image_statistics"].append(self._frame_statistics(frame, region))
            except Exception as exc:
                preflight.critical_errors.append(f"{frame.tiff_path.name}: {exc}")

        grouped: dict[tuple[FrameType, int, float], list[LoadedFrame]] = defaultdict(list)
        for frame in valid_frames:
            if frame.frame_type is None or frame.gain_percent is None or frame.actual_exposure_ms is None:
                preflight.limitations.append(f"Unclassified frame excluded: {frame.tiff_path.name}")
                continue
            grouped[(frame.frame_type, frame.gain_percent, frame.actual_exposure_ms)].append(frame)

        point_rows: list[dict[str, Any]] = []
        corrected_means: dict[tuple[int, float], np.ndarray] = {}
        conditions = sorted({(gain, exposure) for frame_type, gain, exposure in grouped if frame_type is FrameType.LIGHT})
        for gain, exposure in conditions:
            light_frames = grouped.get((FrameType.LIGHT, gain, exposure), [])
            dark_frames = grouped.get((FrameType.DARK, gain, exposure), [])
            if not light_frames:
                continue
            lights = np.stack([effective_array(frame)[selected_roi.slices()] for frame in light_frames]).astype(np.float32)
            light_stats = self._condition_statistics(lights)
            dark_stack = (
                np.stack([effective_array(frame)[selected_roi.slices()] for frame in dark_frames]).astype(np.float32)
                if dark_frames else None
            )
            master_dark = np.median(dark_stack, axis=0).astype(np.float32) if dark_stack is not None else None
            if dark_stack is not None:
                dark_stats = self._condition_statistics(dark_stack)
                tables["dark_statistics"].append({
                    "gain_percent": gain, "actual_exposure_ms": exposure,
                    "camera_temperature_c": _mean_temperature(dark_frames),
                    **{key: value for key, value in dark_stats.items() if key != "per_frame_medians"},
                })
            corrected = lights if master_dark is None else lights.astype(np.float32) - master_dark.astype(np.float32)
            corrected_mean = np.mean(corrected, axis=0, dtype=np.float64).astype(np.float32)
            # HDR overlap uses a deterministic spatial sample so full-resolution
            # qualification does not retain every ROI in memory.
            stride = max(1, int(math.ceil(max(corrected_mean.shape) / 256)))
            corrected_means[(gain, exposure)] = corrected_mean[::stride, ::stride].copy()
            medians = np.median(corrected, axis=(1, 2))
            means = np.mean(corrected, axis=(1, 2))
            maximum = self._effective_max(light_frames)
            row = {
                "gain_percent": gain,
                "requested_exposure_ms": _mean_requested(light_frames),
                "actual_exposure_ms": exposure,
                "light_repeats": int(lights.shape[0]),
                "dark_repeats": len(dark_frames),
                "dark_corrected_mean": float(np.mean(corrected)),
                "dark_corrected_median": float(np.median(corrected)),
                "dark_corrected_min": float(np.min(corrected)),
                "negative_pixel_fraction": float(np.mean(corrected < 0)),
                "raw_median": light_stats["median"],
                "p99": light_stats["p99"],
                "p99_9": light_stats["p99_9"],
                "saturation_fraction": float(np.mean(lights >= maximum)) if maximum else math.nan,
                "fraction_ge_95_percent_full_scale": float(np.mean(lights >= maximum * self.criteria.saturation_warning_fraction)) if maximum else math.nan,
                "fraction_ge_98_percent_full_scale": float(np.mean(lights >= maximum * self.criteria.saturation_reject_fraction)) if maximum else math.nan,
                "dn_per_ms": float(np.median(corrected)) / exposure,
            }
            point_rows.append(row)
            mean_cv = _cv(means); median_cv = _cv(medians)
            tables["repeatability"].append({
                "gain_percent": gain, "actual_exposure_ms": exposure,
                "repeat_count": len(medians), "mean_cv_percent": mean_cv,
                "median_cv_percent": median_cv,
                "within_condition_std": float(np.std(medians, ddof=1)) if len(medians) > 1 else 0.0,
                "confidence_interval_95_half_width": float(1.96 * np.std(medians, ddof=1) / math.sqrt(len(medians))) if len(medians) > 1 else 0.0,
                "outlier_frame_count": _outlier_count(medians),
                "sequence_drift_percent": _sequence_drift(medians),
            })
            self._transition_checks(light_frames, medians, row, tables)

        tables["exposure_linearity_points"] = point_rows
        gain_summaries = self._exposure_linearity(point_rows, tables)
        self._gain_response(point_rows, tables)
        hdr_readiness = self._hdr_readiness(corrected_means, tables)
        self._cross_condition_transition_checks(point_rows, tables)
        summary = self._qualification_summary(
            frames, preflight, selected_roi, selected_mode, synthetic,
            gain_summaries, tables, hdr_readiness,
            operator_evidence,
        )
        profile = build_profile(
            summary, criteria=self.criteria, mode=selected_mode, synthetic=synthetic,
            source_paths=[frame.tiff_path for frame in frames], manifest_path=manifest_path,
        )
        summary["profile_usable_for_production"] = profile["profile_usable_for_production"]
        return AnalysisOutcome(QualificationResult(summary["overall_qualification"]), summary, dict(tables), profile, preflight)

    def pilot_readiness(self, medians: list[float]) -> str:
        values = np.asarray(medians, dtype=np.float64)
        if values.size == 0 or np.all(values >= self.criteria.pilot_low_dn):
            return "LIGHT TOO BRIGHT"
        if np.all(values < self.criteria.pilot_high_dn):
            return "LIGHT TOO DIM"
        middle = np.sum((values >= self.criteria.pilot_middle_low_dn) & (values <= self.criteria.pilot_middle_high_dn))
        if middle >= self.criteria.pilot_required_middle_points and np.any(values < self.criteria.pilot_low_dn) and np.any(values > self.criteria.pilot_high_dn):
            return "SUITABLE FOR FULL QUALIFICATION"
        return "LIGHT TOO BRIGHT" if np.median(values) > self.criteria.pilot_high_dn else "LIGHT TOO DIM"

    def validate_dark_preview(self, dark_median: float, light_median: float) -> tuple[bool, str]:
        if dark_median > self.criteria.dark_preview_absolute_max_dn:
            return False, "Dark preview DN is too high"
        if light_median > 0 and dark_median / light_median > self.criteria.dark_preview_light_ratio_max:
            return False, "Dark preview is too similar to the Light phase"
        return True, "Dark preview accepted"

    def _preflight(self, frames: list[LoadedFrame], errors: list[str], roi: ROI | None) -> PreflightResult:
        result = PreflightResult(tiff_count=len(frames), json_count=sum(frame.sidecar_path is not None for frame in frames), unparseable_files=errors)
        seen: set[tuple[Any, ...]] = set()
        sequences: list[int] = []
        common_roi: ROI | None = None
        for frame in frames:
            if frame.sidecar_path is None:
                result.missing_sidecars.append(str(frame.tiff_path))
            else:
                expected_hash = frame.metadata.get("tiff_sha256") or frame.metadata.get("ScientificTiffSha256")
                if expected_hash and str(expected_hash).lower() != sha256_file(frame.tiff_path).lower():
                    result.critical_errors.append(f"TIFF SHA-256 mismatch: {frame.tiff_path.name}")
            result.dtypes.add(frame.image_dtype or str(np.asarray(frame.image).dtype)); result.shapes.add(_frame_shape(frame))
            if frame.sensor_bit_depth is not None: result.bit_depths.add(frame.sensor_bit_depth)
            if frame.effective_dn_max is not None: result.effective_dn_maxima.add(frame.effective_dn_max)
            result.alignments.add(frame.raw_alignment)
            if frame.gain_percent is not None: result.gains.add(frame.gain_percent)
            if frame.actual_exposure_ms is not None: result.exposures_ms.add(frame.actual_exposure_ms)
            if frame.temperature_c is not None: result.temperatures_c.append(frame.temperature_c)
            key = (frame.frame_type, frame.gain_percent, frame.actual_exposure_ms)
            if frame.frame_type and frame.gain_percent is not None and frame.actual_exposure_ms is not None:
                target = result.light_conditions if frame.frame_type is FrameType.LIGHT else result.dark_conditions
                condition_key = f"G{frame.gain_percent}_E{frame.actual_exposure_ms:g}ms"
                target[condition_key] = target.get(condition_key, 0) + 1
            unique = (*key, frame.repeat_index, frame.frame_sequence)
            if unique in seen: result.duplicate_frames.append(frame.tiff_path.name)
            seen.add(unique)
            if frame.requested_exposure_ms and frame.actual_exposure_ms:
                mismatch = abs(frame.actual_exposure_ms - frame.requested_exposure_ms) / frame.requested_exposure_ms
                if mismatch > 0.01: result.readback_mismatches.append(frame.tiff_path.name)
            requested_gain = frame.metadata.get("requested_gain_percent")
            if requested_gain is not None and frame.gain_percent is not None and int(requested_gain) != frame.gain_percent:
                result.readback_mismatches.append(frame.tiff_path.name)
            if frame.frame_sequence is not None: sequences.append(frame.frame_sequence)
            if frame.roi:
                if common_roi is None: common_roi = frame.roi
                elif common_roi != frame.roi: result.roi_compatible = False
        if len(result.dtypes) != 1 or (result.dtypes and result.dtypes != {"uint16"}): result.critical_errors.append("RAW TIFF dtype must be consistently uint16")
        if len(result.shapes) != 1: result.critical_errors.append("Resolution is inconsistent")
        if len(result.bit_depths) != 1 or len(result.effective_dn_maxima) != 1: result.critical_errors.append("Critical bit-depth metadata is missing or inconsistent")
        if result.alignments - {"right", "left"} or len(result.alignments) != 1: result.critical_errors.append("RawValueAlignment is missing, unknown, or inconsistent")
        if len(sequences) != len(set(sequences)):
            result.sequence_anomalies.append("Duplicate FrameSequence values detected")
        if not result.matching_dark_complete: result.limitations.append("Matching Dark frames are incomplete")
        if result.missing_sidecars: result.limitations.append("One or more TIFF sidecars are missing")
        if result.readback_mismatches: result.limitations.append("Requested/actual Exposure or Gain mismatch exceeds tolerance")
        if result.sequence_anomalies: result.limitations.append("FrameSequence evidence is not unique/monotonic")
        if not result.roi_compatible: result.critical_errors.append("ROI metadata is inconsistent")
        return result

    def _inventory_tables(self, frames: list[LoadedFrame], tables: dict[str, list[dict[str, Any]]]) -> None:
        for frame in frames:
            tables["dataset_inventory"].append({
                "tiff_path": str(frame.tiff_path), "sidecar_path": str(frame.sidecar_path or ""),
                "frame_type": frame.frame_type.value if frame.frame_type else "UNKNOWN",
                "gain_percent": frame.gain_percent, "requested_exposure_ms": frame.requested_exposure_ms,
                "actual_exposure_ms": frame.actual_exposure_ms, "repeat_index": frame.repeat_index,
                "frame_sequence": frame.frame_sequence, "dtype": frame.image_dtype or str(np.asarray(frame.image).dtype),
                "shape": list(_frame_shape(frame)), "sensor_bit_depth": frame.sensor_bit_depth,
                "effective_dn_max": frame.effective_dn_max, "raw_alignment": frame.raw_alignment,
                "camera_temperature_c": frame.temperature_c,
            })

    def _frame_statistics(self, frame: LoadedFrame, region: np.ndarray) -> dict[str, Any]:
        stats = _statistics(region)
        maximum = frame.effective_dn_max
        stats.update({
            "tiff_path": str(frame.tiff_path), "frame_type": frame.frame_type.value if frame.frame_type else "UNKNOWN",
            "gain_percent": frame.gain_percent, "actual_exposure_ms": frame.actual_exposure_ms,
            "repeat_index": frame.repeat_index, "frame_sequence": frame.frame_sequence,
            "camera_temperature_c": frame.temperature_c,
            "fraction_at_effective_dn_max": float(np.mean(region == maximum)) if maximum else math.nan,
            "fraction_ge_95_percent_full_scale": float(np.mean(region >= maximum * .95)) if maximum else math.nan,
            "fraction_ge_98_percent_full_scale": float(np.mean(region >= maximum * .98)) if maximum else math.nan,
            "hot_pixel_fraction": float(np.mean(region >= maximum * self.criteria.hot_pixel_fraction_of_full_scale)) if maximum else math.nan,
        })
        return stats

    @staticmethod
    def _condition_statistics(stack: np.ndarray) -> dict[str, Any]:
        result = _statistics(stack)
        result["variance"] = float(np.var(stack))
        result["per_frame_medians"] = [float(item) for item in np.median(stack, axis=(1, 2))]
        return result

    def _exposure_linearity(self, points: list[dict[str, Any]], tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for gain in sorted({int(row["gain_percent"]) for row in points}):
            rows = sorted((row for row in points if int(row["gain_percent"]) == gain), key=lambda row: float(row["actual_exposure_ms"]))
            values = np.asarray([row["dark_corrected_median"] for row in rows], dtype=np.float64)
            exposures = np.asarray([row["actual_exposure_ms"] for row in rows], dtype=np.float64)
            valid = np.isfinite(values) & (values >= self.criteria.low_snr_dn)
            compression_index = _compression_index(exposures, values, self.criteria.compression_ratio)
            for index, row in enumerate(rows):
                row["low_snr_excluded"] = not bool(valid[index])
                row["compression_excluded"] = compression_index is not None and index >= compression_index
                row["saturation_excluded"] = bool(row["fraction_ge_98_percent_full_scale"] > 0)
                valid[index] &= not row["compression_excluded"] and not row["saturation_excluded"]
            indices = np.flatnonzero(valid)
            regression: RegressionResult | None = linear_regression(exposures[indices], values[indices]) if len(indices) >= 2 else None
            residual_lookup: dict[int, float] = {}
            if regression:
                predicted = regression.slope * exposures[indices] + regression.intercept
                for idx, observed, expected in zip(indices, values[indices], predicted):
                    residual_lookup[int(idx)] = float(abs(observed - expected) / max(abs(expected), 1.0) * 100.0)
            for index, row in enumerate(rows): row["residual_percent"] = residual_lookup.get(index)
            classification = _classification(regression, self.criteria)
            monotonic = is_monotonic(values, self.criteria.transition_nonmonotonic_tolerance_percent)
            repeat_ok = all(float(item.get("median_cv_percent", math.inf)) <= self.criteria.repeat_cv_max_percent for item in tables["repeatability"] if int(item["gain_percent"]) == gain)
            passed = bool(regression and len(indices) >= self.criteria.pass_min_linear_points and regression.r2 >= self.criteria.pass_r2 and regression.max_absolute_residual_percent <= self.criteria.pass_max_residual_percent and monotonic and repeat_ok)
            summary = {
                "gain_percent": gain, "classification": classification,
                "linear_point_count": int(len(indices)), "linear_exposure_min_ms": float(exposures[indices[0]]) if len(indices) else None,
                "linear_exposure_max_ms": float(exposures[indices[-1]]) if len(indices) else None,
                "reliable_dn_low": float(values[indices[0]]) if len(indices) else None,
                "reliable_dn_high": float(values[indices[-1]]) if len(indices) else None,
                "compression_onset_dn": float(values[compression_index]) if compression_index is not None else None,
                "monotonic": monotonic, "repeatability_pass": repeat_ok, "pass": passed,
            }
            if regression: summary.update({key: value for key, value in regression.to_dict().items() if key != "residuals"})
            else: summary.update({"slope": None, "intercept": None, "r2": None, "adjusted_r2": None, "rmse": None, "normalized_rmse": None, "max_absolute_residual_percent": None, "median_absolute_residual_percent": None, "p95_residual_percent": None})
            summaries.append(summary); tables["exposure_linearity_summary"].append(summary)
            tables["usable_dynamic_range"].append({
                "gain_percent": gain, "reliable_dn_low": summary["reliable_dn_low"], "reliable_dn_high": summary["reliable_dn_high"],
                "compression_onset_dn": summary["compression_onset_dn"], "validated": passed,
            })
        return summaries

    def _gain_response(self, points: list[dict[str, Any]], tables: dict[str, list[dict[str, Any]]]) -> None:
        exposures = sorted({float(row["actual_exposure_ms"]) for row in points})
        for exposure in exposures:
            rows = {int(row["gain_percent"]): row for row in points if float(row["actual_exposure_ms"]) == exposure}
            baseline = rows.get(100)
            if not baseline or float(baseline["dark_corrected_median"]) <= 0: continue
            for gain, row in sorted(rows.items()):
                tables["gain_response"].append({
                    "actual_exposure_ms": exposure, "gain_percent": gain,
                    "dark_corrected_median": row["dark_corrected_median"],
                    "response_ratio": float(row["dark_corrected_median"]) / float(baseline["dark_corrected_median"]),
                    "nominal_gain_ratio": gain / 100.0,
                    "physical_gain_linearity_claimed": False,
                })

    def _transition_checks(self, frames: list[LoadedFrame], medians: np.ndarray, row: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> None:
        if len(medians) >= 3:
            reference = float(np.median(medians[1:])); deviation = abs(float(medians[0]) - reference) / max(abs(reference), 1.0) * 100.0
            if deviation > self.criteria.transition_first_frame_deviation_percent:
                tables["acquisition_transition_anomalies"].append({
                    "type": "STALE_FIRST_FRAME", "gain_percent": row["gain_percent"], "actual_exposure_ms": row["actual_exposure_ms"],
                    "first_frame_sequence": frames[0].frame_sequence if frames else None, "deviation_percent": deviation, "status": "UNRESOLVED",
                })
        sequences = [frame.frame_sequence for frame in frames if frame.frame_sequence is not None]
        if sequences and any(b <= a for a, b in zip(sequences, sequences[1:])):
            tables["acquisition_transition_anomalies"].append({"type": "NON_MONOTONIC_SEQUENCE", "gain_percent": row["gain_percent"], "actual_exposure_ms": row["actual_exposure_ms"], "status": "UNRESOLVED"})

    def _cross_condition_transition_checks(self, points: list[dict[str, Any]], tables: dict[str, list[dict[str, Any]]]) -> None:
        for gain in sorted({int(row["gain_percent"]) for row in points}):
            rows = sorted((row for row in points if int(row["gain_percent"]) == gain), key=lambda row: float(row["actual_exposure_ms"]))
            for previous, current in zip(rows, rows[1:]):
                tolerance = abs(float(previous["dark_corrected_median"])) * self.criteria.transition_nonmonotonic_tolerance_percent / 100.0
                if float(current["dark_corrected_median"]) < float(previous["dark_corrected_median"]) - tolerance:
                    tables["acquisition_transition_anomalies"].append({"type": "NON_MONOTONIC_RESPONSE", "gain_percent": gain, "previous_exposure_ms": previous["actual_exposure_ms"], "actual_exposure_ms": current["actual_exposure_ms"], "status": "UNRESOLVED"})

    def _hdr_readiness(self, means: dict[tuple[int, float], np.ndarray], tables: dict[str, list[dict[str, Any]]]) -> str:
        results: list[str] = []
        for gain in sorted({key[0] for key in means}):
            exposures = sorted(key[1] for key in means if key[0] == gain)
            for lower, upper in zip(exposures, exposures[1:]):
                low_image, high_image = means[(gain, lower)], means[(gain, upper)]
                low_norm, high_norm = low_image / lower, high_image / upper
                finite = np.isfinite(low_norm) & np.isfinite(high_norm) & (low_image >= self.criteria.low_snr_dn) & (high_image >= self.criteria.low_snr_dn)
                overlap = float(np.mean(finite))
                if np.any(finite):
                    denominator = np.maximum(np.abs(low_norm[finite]), 1e-6)
                    errors = np.abs(high_norm[finite] - low_norm[finite]) / denominator * 100.0
                    median_error, p95_error = float(np.median(errors)), float(np.percentile(errors, 95))
                else: median_error = p95_error = math.inf
                passed = overlap >= self.criteria.hdr_min_overlap_fraction and median_error <= self.criteria.hdr_median_error_max_percent and p95_error <= self.criteria.hdr_p95_error_max_percent
                status = "PASS" if passed else ("CONDITIONAL PASS" if overlap > 0 else "FAIL")
                results.append(status)
                tables["exposure_gap_analysis"].append({"gain_percent": gain, "lower_exposure_ms": lower, "upper_exposure_ms": upper, "exposure_ratio": upper/lower, "median_error_percent": median_error, "p95_pixel_error_percent": p95_error, "overlap_pixel_fraction": overlap, "result": status})
        if results and all(item == "PASS" for item in results): return "PASS"
        if results and any(item in {"PASS", "CONDITIONAL PASS"} for item in results): return "CONDITIONAL PASS"
        return "FAIL"

    def _qualification_summary(self, frames: list[LoadedFrame], preflight: PreflightResult, roi: ROI, mode: RunMode, synthetic: bool, gains: list[dict[str, Any]], tables: dict[str, list[dict[str, Any]]], hdr: str, operator_evidence: bool) -> dict[str, Any]:
        formal_repeats = bool(preflight.light_conditions) and all(count >= 5 for count in preflight.light_conditions.values()) and all(preflight.dark_conditions.get(key, 0) >= 5 for key in preflight.light_conditions)
        unresolved = bool(tables["acquisition_transition_anomalies"])
        temperatures = preflight.temperatures_c
        temperature_span = max(temperatures) - min(temperatures) if temperatures else math.inf
        temperature_ok = bool(temperatures) and temperature_span <= self.criteria.temperature_span_max_c
        validated = [int(item["gain_percent"]) for item in gains if item["pass"]]
        all_gains_pass = bool(gains) and len(validated) == len(gains)
        evidence_complete = (
            preflight.matching_dark_complete and formal_repeats and not unresolved
            and not preflight.critical_errors and not preflight.readback_mismatches
            and not preflight.sequence_anomalies and temperature_ok and operator_evidence
        )
        if mode is RunMode.PILOT:
            readiness = self.pilot_readiness([float(row["dark_corrected_median"]) for row in tables["exposure_linearity_points"]])
            overall = QualificationResult.CONDITIONAL_PASS if readiness == "SUITABLE FOR FULL QUALIFICATION" else QualificationResult.FAIL
        elif all_gains_pass and evidence_complete:
            readiness = None; overall = QualificationResult.PASS
        elif validated and not preflight.critical_errors:
            readiness = None; overall = QualificationResult.CONDITIONAL_PASS
        else:
            readiness = None; overall = QualificationResult.FAIL
        lows = [float(item["reliable_dn_low"]) for item in gains if item.get("pass") and item.get("reliable_dn_low") is not None]
        highs = [float(item["reliable_dn_high"]) for item in gains if item.get("pass") and item.get("reliable_dn_high") is not None]
        reliable_low = max(lows) if lows else None; reliable_high = min(highs) if highs else None
        maximum = next(iter(preflight.effective_dn_maxima), None)
        limitations = list(dict.fromkeys(
            preflight.limitations
            + (["Uniform stable-source operator evidence is missing"] if not operator_evidence else [])
            + (["Synthetic/fake-camera dataset; hardware qualification not established"] if synthetic else [])
            + (["Pilot and Quick Verification cannot create a formal production profile"] if mode is not RunMode.FULL else [])
        ))
        source_metadata = frames[0].metadata if frames else {}
        software_commit = _git_head()
        quick_result = None
        if mode is RunMode.QUICK:
            if all_gains_pass and not unresolved and not preflight.critical_errors and preflight.matching_dark_complete:
                quick_result = "PROFILE STILL VALID"
            elif validated:
                quick_result = "PROFILE DRIFT WARNING"
            else:
                quick_result = "PROFILE INVALID — FULL QUALIFICATION REQUIRED"
        summary = {
            "overall_qualification": overall.value, "run_mode": mode.value, "pilot_readiness": readiness,
            "quick_verification_result": quick_result,
            "raw_format": f"{frames[0].metadata.get('PixelFormat', 'MONO16')} / uint16" if frames else "UNKNOWN",
            "camera_identity": {"model": source_metadata.get("CameraModel"), "serial": source_metadata.get("CameraSerial")},
            "resolution": list(_frame_shape(frames[0])[::-1]) if frames else None,
            "sensor_bit_depth": next(iter(preflight.bit_depths), None), "effective_dn_max": maximum,
            "raw_value_alignment": next(iter(preflight.alignments), "unknown"), "roi": roi.to_dict(),
            "validated_gains": validated, "per_gain_linearity": gains, "empirical_gain_response": tables["gain_response"],
            "reliable_dn_low": reliable_low, "reliable_dn_high": reliable_high,
            "preferred_dn_low": reliable_low, "preferred_dn_high": (reliable_high * .85 if reliable_high is not None else None),
            "target_dn": ((reliable_low + reliable_high * .85) / 2 if reliable_low is not None and reliable_high is not None else None),
            "compression_onset": min((float(item["compression_onset_dn"]) for item in gains if item.get("compression_onset_dn") is not None), default=None),
            "saturation_warning": maximum * self.criteria.saturation_warning_fraction if maximum else None,
            "saturation_reject": maximum * self.criteria.saturation_reject_fraction if maximum else None,
            "transition_frame_status": "FAIL — unresolved anomalies" if unresolved else "PASS",
            "hdr_readiness": hdr, "formal_evidence_complete": evidence_complete,
            "temperature_range_c": [min(temperatures), max(temperatures)] if temperatures else None,
            "recommended_exposure_limits": _recommended_exposure_limits(gains),
            "limitations": limitations, "software_commit": software_commit,
            "profile_usable_for_production": False,
            "recommended_next_step": "Run Full Qualification on stable uniform hardware light source" if mode is not RunMode.FULL or synthetic else ("Review failed criteria and reacquire dataset" if overall is not QualificationResult.PASS else "Archive profile and perform periodic Quick Verification"),
            "preflight": preflight.to_dict(),
        }
        tables["recommended_camera_settings"].append({"reliable_dn_low": reliable_low, "reliable_dn_high": reliable_high, "preferred_dn_low": summary["preferred_dn_low"], "preferred_dn_high": summary["preferred_dn_high"], "target_dn": summary["target_dn"], "saturation_warning": summary["saturation_warning"], "saturation_reject": summary["saturation_reject"]})
        for item in gains: tables["qualification_results"].append({"scope": f"Gain {item['gain_percent']}", "result": "PASS" if item["pass"] else "FAIL", "classification": item["classification"]})
        tables["qualification_results"].append({"scope": "Overall", "result": overall.value, "classification": "formal" if evidence_complete else "insufficient evidence"})
        return summary

    @staticmethod
    def _common_roi(frames: list[LoadedFrame]) -> ROI | None:
        values = {frame.roi for frame in frames if frame.roi is not None}
        return next(iter(values)) if len(values) == 1 else None

    @staticmethod
    def _effective_max(frames: list[LoadedFrame]) -> int | None:
        values = {frame.effective_dn_max for frame in frames if frame.effective_dn_max is not None}
        return next(iter(values)) if len(values) == 1 else None

    @staticmethod
    def _empty_summary(preflight: PreflightResult, mode: RunMode, synthetic: bool) -> dict[str, Any]:
        return {"overall_qualification": QualificationResult.FAIL.value, "run_mode": mode.value, "validated_gains": [], "limitations": preflight.limitations + preflight.critical_errors, "formal_evidence_complete": False, "software_commit": _git_head(), "profile_usable_for_production": False, "synthetic_dataset": synthetic, "preflight": preflight.to_dict()}


def dark_correct(light: np.ndarray, master_dark: np.ndarray) -> np.ndarray:
    """Subtract without clipping; negative evidence is intentionally preserved."""
    return np.asarray(light, dtype=np.float32) - np.asarray(master_dark, dtype=np.float32)


def _statistics(values: np.ndarray) -> dict[str, float]:
    data = np.asarray(values, dtype=np.float64)
    median = float(np.median(data)); mad = float(np.median(np.abs(data - median)))
    percentiles = np.percentile(data, (1, 5, 50, 95, 99, 99.9))
    return {"mean": float(np.mean(data)), "median": median, "standard_deviation": float(np.std(data)), "robust_sigma": 1.4826 * mad, "p01": float(percentiles[0]), "p05": float(percentiles[1]), "p50": float(percentiles[2]), "p95": float(percentiles[3]), "p99": float(percentiles[4]), "p99_9": float(percentiles[5])}


def _compression_index(exposures: np.ndarray, values: np.ndarray, ratio_threshold: float) -> int | None:
    if len(values) < 3: return None
    local_slopes = np.diff(values) / np.diff(exposures)
    positive = local_slopes[:max(1, min(3, len(local_slopes)))]
    reference = float(np.median(positive[positive > 0])) if np.any(positive > 0) else 0.0
    if reference <= 0: return 1
    for index in range(1, len(local_slopes)):
        if local_slopes[index] < reference * ratio_threshold:
            return index + 1
    return None


def _classification(regression: RegressionResult | None, criteria: QualificationCriteria) -> str:
    if regression is None: return "Poor"
    if regression.r2 >= criteria.excellent_r2 and regression.max_absolute_residual_percent <= criteria.excellent_max_residual_percent: return "Excellent"
    if regression.r2 >= criteria.good_r2 and regression.max_absolute_residual_percent <= criteria.good_max_residual_percent: return "Good"
    if regression.r2 >= criteria.acceptable_r2 and regression.max_absolute_residual_percent <= criteria.acceptable_max_residual_percent: return "Acceptable"
    return "Poor"


def _cv(values: np.ndarray) -> float:
    mean = float(np.mean(values)); return float(np.std(values, ddof=1) / abs(mean) * 100.0) if len(values) > 1 and mean != 0 else 0.0


def _outlier_count(values: np.ndarray) -> int:
    median = np.median(values); mad = np.median(np.abs(values - median)); return int(np.sum(np.abs(values - median) > 4.5 * max(float(mad), 1e-9)))


def _sequence_drift(values: np.ndarray) -> float:
    if len(values) < 2: return 0.0
    return float((values[-1] - values[0]) / max(abs(float(np.mean(values))), 1.0) * 100.0)


def _mean_temperature(frames: list[LoadedFrame]) -> float | None:
    values = [frame.temperature_c for frame in frames if frame.temperature_c is not None]
    return float(np.mean(values)) if values else None


def _mean_requested(frames: list[LoadedFrame]) -> float | None:
    values = [frame.requested_exposure_ms for frame in frames if frame.requested_exposure_ms is not None]
    return float(np.mean(values)) if values else None


def _recommended_exposure_limits(gains: list[dict[str, Any]]) -> dict[str, float | None]:
    lows = [item["linear_exposure_min_ms"] for item in gains if item.get("pass") and item.get("linear_exposure_min_ms") is not None]
    highs = [item["linear_exposure_max_ms"] for item in gains if item.get("pass") and item.get("linear_exposure_max_ms") is not None]
    return {"minimum_ms": max(lows) if lows else None, "maximum_ms": min(highs) if highs else None}


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except Exception:
        return "unknown"


def _operator_evidence(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        kinds = {
            str(item.get("kind")) for item in payload.get("events", [])
            if isinstance(item, dict)
        }
        return {"LIGHT_OPERATOR_CONFIRMED", "DARK_OPERATOR_CONFIRMED"}.issubset(kinds)
    except Exception:
        return False


def _frame_shape(frame: LoadedFrame) -> tuple[int, ...]:
    if frame.image_shape is not None:
        return tuple(frame.image_shape)
    return tuple(int(item) for item in np.asarray(frame.image).shape)
