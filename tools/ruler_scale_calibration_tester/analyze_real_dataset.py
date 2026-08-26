from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import logging
from pathlib import Path
import statistics
import sys
from typing import Any

import cv2
import numpy as np

from core.calibration import CalibrationService
from core.calibration.image_utils import normalize_to_uint8, to_bgr

from .image_loader import iter_images, load_image


LOG = logging.getLogger(__name__)


def analyze_dataset(
    input_path: str | Path,
    output_root: str | Path,
    *,
    ground_truth_path: str | Path | None = None,
    service: CalibrationService | None = None,
) -> dict[str, Any]:
    """Analyze an offline image set and write local-only diagnostic artifacts."""
    source = Path(input_path)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    paths = iter_images(source)
    calibration = service or CalibrationService()
    ground_truth = _load_ground_truth(
        Path(ground_truth_path) if ground_truth_path else source / "ground_truth.csv"
    )
    records: list[dict[str, Any]] = []
    contact_rows: list[np.ndarray] = []

    for index, path in enumerate(paths, start=1):
        LOG.info("Real dataset image=%s index=%s total=%s", path, index, len(paths))
        annotation = ground_truth.get(path.name, {})
        try:
            image = load_image(path)
        except Exception as exc:
            record = _load_failure_record(path, str(exc), annotation)
            records.append(record)
            contact_rows.append(_contact_row(None, None, record))
            continue

        metrics = _image_metrics(image)
        result = calibration.analyze(image, input_source=str(path))
        record = _result_record(path, result, metrics, annotation)
        records.append(record)
        _save_debug_images(output / "artifacts" / path.stem, result.debug_images)
        failure_dir = output / "failures" / path.stem
        if not result.success:
            _save_debug_images(failure_dir, result.debug_images)
        contact_rows.append(_contact_row(image, result.debug_images, record))

    _annotate_scale_outliers(records)
    summary = _summarize(records)
    payload = {"summary": summary, "records": records}
    _write_json(output / "results.json", payload)
    _write_csv(output / "results.csv", records)
    (output / "summary.txt").write_text(_summary_text(summary), encoding="utf-8")
    _write_contact_sheet(output / "contact_sheet.png", contact_rows)
    return payload


def _load_ground_truth(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return {
            row["filename"]: row
            for row in csv.DictReader(stream)
            if row.get("filename")
        }


def _load_failure_record(
    path: Path,
    error: str,
    annotation: dict[str, str],
) -> dict[str, Any]:
    return {
        "filename": path.name,
        "resolution": "",
        "dtype": "",
        "ruler_detected": False,
        "roi_correct": _optional_bool(annotation.get("roi_correct")),
        "roi_status": annotation.get("roi_status", "unreviewed"),
        "angle_deg": None,
        "rectification_success": False,
        "tick_candidates": 0,
        "accepted_ticks": 0,
        "periodic_pitch_px": None,
        "physical_pitch_mm": None,
        "pixels_per_mm": None,
        "verification_mode": "unverified",
        "ocr_available": False,
        "ocr_usable": False,
        "ocr_result": "",
        "ocr_diagnostic": "",
        "final_pass": False,
        "quality_label": "FAIL",
        "failure_category": "image_load_failed",
        "failure_reasons": ["image_load_failed"],
        "error": error,
        "review_notes": annotation.get("notes", ""),
        "false_pass": False,
        "wrong_scale": _optional_bool(annotation.get("wrong_scale")) or False,
        "possible_alias_factor": None,
        "scale_outlier": False,
    }


def _result_record(
    path: Path,
    result: Any,
    metrics: dict[str, float],
    annotation: dict[str, str],
) -> dict[str, Any]:
    detection = result.ruler_detection
    roi_correct = _optional_bool(annotation.get("roi_correct"))
    roi_status = annotation.get("roi_status", "").strip().lower()
    if not roi_status:
        roi_status = (
            "correct" if roi_correct is True else "incorrect" if roi_correct is False else "unreviewed"
        )
    accepted_ticks = len(result.detected_major_ticks) + len(result.detected_minor_ticks)
    ocr_text = ",".join(
        item.raw_text for item in result.detected_numbers if item.raw_text
    )
    record: dict[str, Any] = {
        "filename": path.name,
        "resolution": f"{result.input_resolution[0]}x{result.input_resolution[1]}",
        "dtype": result.input_dtype,
        "ruler_detected": bool(detection and detection.success),
        "roi_correct": roi_correct,
        "roi_status": roi_status,
        "candidate_count": result.diagnostics.get("ruler_candidate_count"),
        "selected_score": detection.confidence if detection else None,
        "selected_method": result.diagnostics.get("ruler_selected_method"),
        "candidate_top_n": result.diagnostics.get("ruler_candidates", []),
        "threshold_audit": result.diagnostics.get("threshold_audit", {}),
        "tick_comb_axis_angle_deg": result.diagnostics.get("tick_comb_axis_angle_deg"),
        "orientation_disagreement_deg": result.diagnostics.get("orientation_disagreement_deg"),
        "angle_deg": result.ruler_angle_deg,
        "rectification_success": "rectified" in result.debug_images,
        "rectified_resolution": result.diagnostics.get("rectified_resolution"),
        "tick_candidates": int(result.diagnostics.get("tick_candidate_count", 0)),
        "accepted_ticks": accepted_ticks,
        "rectified_blur_laplacian_variance": result.diagnostics.get(
            "rectified_blur_laplacian_variance"
        ),
        "rectified_saturated_fraction": result.diagnostics.get(
            "rectified_saturated_fraction"
        ),
        "periodic_pitch_px": result.periodic_pitch_px,
        "physical_pitch_mm": result.physical_pitch_mm,
        "pixels_per_mm": result.pixels_per_mm,
        "verification_mode": result.verification_mode,
        "ocr_available": result.ocr_available,
        "ocr_usable": result.ocr_usable,
        "ocr_result": ocr_text,
        "ocr_diagnostic": result.ocr_diagnostic,
        "final_pass": result.success,
        "quality_label": result.quality_label,
        "failure_reasons": list(result.failure_reasons),
        "error": "",
        "review_notes": annotation.get("notes", ""),
        "manual_failure_category": annotation.get("failure_category", ""),
        "wrong_scale": _optional_bool(annotation.get("wrong_scale")) or False,
        "possible_alias_factor": None,
        "scale_outlier": False,
        **metrics,
    }
    record["failure_category"] = _failure_category(record)
    annotated_false_pass = _optional_bool(annotation.get("false_pass"))
    record["false_pass"] = bool(
        annotated_false_pass
        if annotated_false_pass is not None
        else result.success and (roi_status == "incorrect" or record["wrong_scale"])
    )
    return record


def _failure_category(record: dict[str, Any]) -> str:
    manual = str(record.get("manual_failure_category") or "").strip()
    if manual:
        return manual
    if record.get("roi_correct") is False:
        return "wrong_ruler_candidate"
    if not record.get("ruler_detected"):
        return "ruler_not_found"
    if not record.get("rectification_success"):
        return "rectification_error"
    reasons = set(record.get("failure_reasons") or [])
    if "analysis_exception" in reasons:
        return "analysis_exception"
    if "image_too_blurry_for_scale_calibration" in reasons:
        return "blur"
    if "ruler_glare_or_saturation" in reasons:
        return "glare"
    if record.get("periodic_pitch_px") is None:
        return "ticks_not_detected"
    if record.get("physical_pitch_mm") is None:
        return "physical_pitch_ambiguous"
    if not record.get("final_pass"):
        return "quality_gate"
    return "pass"


def _annotate_scale_outliers(records: list[dict[str, Any]]) -> None:
    values = [
        float(record["pixels_per_mm"])
        for record in records
        if record.get("final_pass") and record.get("pixels_per_mm") is not None
    ]
    if len(values) < 3:
        return
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    relative_limit = max(0.05, (3.0 * mad / median) if median else 0.05)
    alias_factors = (0.5, 2.0, 5.0, 10.0)
    for record in records:
        value = record.get("pixels_per_mm")
        if value is None or median <= 0:
            continue
        ratio = float(value) / median
        record["scale_outlier"] = abs(ratio - 1.0) > relative_limit
        nearest = min(alias_factors, key=lambda factor: abs(ratio - factor) / factor)
        if abs(ratio - nearest) / nearest <= 0.12:
            record["possible_alias_factor"] = nearest
            if record.get("final_pass"):
                record["wrong_scale"] = True
                record["false_pass"] = True


def _image_metrics(image: np.ndarray) -> dict[str, float]:
    gray = normalize_to_uint8(image)
    values = gray.astype(np.float32)
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    return {
        "mean_dn8": round(float(values.mean()), 4),
        "std_dn8": round(float(values.std()), 4),
        "p01_dn8": round(float(np.percentile(values, 1)), 4),
        "p99_dn8": round(float(np.percentile(values, 99)), 4),
        "blur_laplacian_variance": round(laplacian_variance, 4),
        "dark_fraction_percent": round(float(np.mean(values <= 2) * 100.0), 4),
        "saturated_fraction_percent": round(float(np.mean(values >= 253) * 100.0), 4),
    }


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        float(record["pixels_per_mm"])
        for record in records
        if record.get("final_pass") and record.get("pixels_per_mm") is not None
    ]
    categories = Counter(str(record["failure_category"]) for record in records)
    stats = _scale_statistics(values)
    return {
        "images": len(records),
        "ruler_detected": sum(bool(item.get("ruler_detected")) for item in records),
        "correct_roi": sum(item.get("roi_correct") is True for item in records),
        "roi_reviewed": sum(item.get("roi_correct") is not None for item in records),
        "roi_uncertain": sum(item.get("roi_status") == "uncertain" for item in records),
        "rectified": sum(bool(item.get("rectification_success")) for item in records),
        "periodic_ticks_usable": sum(item.get("periodic_pitch_px") is not None for item in records),
        "physical_pitch_verified": sum(item.get("physical_pitch_mm") is not None for item in records),
        "ocr_usable": sum(bool(item.get("ocr_usable")) for item in records),
        "final_pass": sum(bool(item.get("final_pass")) for item in records),
        "false_pass": sum(bool(item.get("false_pass")) for item in records),
        "wrong_scale": sum(bool(item.get("wrong_scale")) for item in records),
        "scale_outliers": sum(bool(item.get("scale_outlier")) for item in records),
        "possible_aliases": sum(item.get("possible_alias_factor") is not None for item in records),
        "failure_categories": dict(sorted(categories.items())),
        "scale_statistics": stats,
    }


def _scale_statistics(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "sd": None,
            "cv_percent": None,
            "median": None,
            "mad": None,
            "min": None,
            "max": None,
            "max_deviation_percent": None,
        }
    mean = statistics.fmean(values)
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": mean,
        "sd": sd,
        "cv_percent": sd / mean * 100.0 if mean else None,
        "median": median,
        "mad": statistics.median(deviations),
        "min": min(values),
        "max": max(values),
        "max_deviation_percent": max(deviations) / median * 100.0 if median else None,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    keys = list(dict.fromkeys(key for record in records for key in record))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for record in records:
            writer.writerow({key: _csv_value(record.get(key)) for key in keys})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _summary_text(summary: dict[str, Any]) -> str:
    lines = [
        f"Images: {summary['images']}",
        f"Ruler detected: {summary['ruler_detected']}",
        f"Correct ROI: {summary['correct_roi']} / reviewed {summary['roi_reviewed']}",
        f"Rectified: {summary['rectified']}",
        f"Periodic ticks usable: {summary['periodic_ticks_usable']}",
        f"Physical pitch verified: {summary['physical_pitch_verified']}",
        f"OCR usable: {summary['ocr_usable']}",
        f"Final PASS: {summary['final_pass']}",
        f"False PASS: {summary['false_pass']}",
        f"Wrong scale: {summary['wrong_scale']}",
        f"Scale outliers: {summary['scale_outliers']}",
        f"Possible aliases: {summary['possible_aliases']}",
        "Failure categories:",
    ]
    for reason, count in summary["failure_categories"].items():
        lines.append(f"- {reason}: {count}")
    lines.append("Scale statistics:")
    for name, value in summary["scale_statistics"].items():
        lines.append(f"- {name}: {value}")
    return "\n".join(lines) + "\n"


def _save_debug_images(root: Path, images: dict[str, np.ndarray]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, image in images.items():
        target = root / f"{name}.png"
        if not cv2.imwrite(str(target), _png_ready(image)):
            raise OSError(f"Failed to write debug image: {target}")


def _png_ready(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image)
    if array.dtype != np.uint8:
        array = normalize_to_uint8(array)
    return np.ascontiguousarray(array)


def _contact_row(
    original: np.ndarray | None,
    debug_images: dict[str, np.ndarray] | None,
    record: dict[str, Any],
) -> np.ndarray:
    panels: list[np.ndarray] = []
    sources = [
        original,
        None if debug_images is None else debug_images.get("ruler_candidates"),
        None if debug_images is None else debug_images.get("final_overlay"),
    ]
    labels = ("original", "candidate", "final")
    for label, source in zip(labels, sources):
        panel = np.full((210, 320, 3), 36, dtype=np.uint8)
        if source is not None and np.asarray(source).size:
            fitted = _fit_panel(to_bgr(source), 320, 185)
            y = 25 + (185 - fitted.shape[0]) // 2
            x = (320 - fitted.shape[1]) // 2
            panel[y : y + fitted.shape[0], x : x + fitted.shape[1]] = fitted
        cv2.putText(panel, label, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230, 230, 230), 1)
        panels.append(panel)
    body = np.hstack(panels)
    header = np.full((76, body.shape[1], 3), 24, dtype=np.uint8)
    status = "PASS" if record.get("final_pass") else "FAIL"
    ppm = record.get("pixels_per_mm")
    line1 = f"{record['filename']} | {status} | {record.get('failure_category', '')}"
    line2 = (
        f"roi={record.get('roi_correct')} angle={record.get('angle_deg')} "
        f"ticks={record.get('accepted_ticks', 0)} ppm={ppm} "
        f"mode={record.get('verification_mode', '')}"
    )
    color = (80, 220, 80) if status == "PASS" else (80, 80, 240)
    cv2.putText(header, _ascii(line1), (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 1)
    cv2.putText(header, _ascii(line2), (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (220, 220, 220), 1)
    return np.vstack((header, body))


def _fit_panel(image: np.ndarray, width: int, height: int) -> np.ndarray:
    scale = min(width / image.shape[1], height / image.shape[0])
    size = (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale)))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def _write_contact_sheet(path: Path, rows: list[np.ndarray]) -> None:
    if not rows:
        empty = np.full((120, 640, 3), 32, dtype=np.uint8)
        cv2.putText(empty, "No supported images", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2)
        rows = [empty]
    sheet = np.vstack(rows)
    if not cv2.imwrite(str(path), sheet):
        raise OSError(f"Failed to write contact sheet: {path}")


def _optional_bool(value: str | None) -> bool | None:
    if value is None or not value.strip():
        return None
    return value.strip().casefold() in {"1", "true", "yes", "y"}


def _ascii(value: str) -> str:
    return value.encode("ascii", errors="replace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a real ruler image dataset")
    parser.add_argument("input", help="Image file or directory")
    parser.add_argument(
        "--output",
        default=str(Path("local") / "generated" / "ruler_real_dataset"),
        help="Local diagnostic output directory",
    )
    parser.add_argument("--ground-truth", help="Optional local CSV with filename and roi_correct")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    payload = analyze_dataset(
        args.input,
        args.output,
        ground_truth_path=args.ground_truth,
    )
    print(_summary_text(payload["summary"]), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
