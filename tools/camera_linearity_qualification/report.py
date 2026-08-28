from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .capture_manifest import atomic_write_json
from .models import AnalysisOutcome


CSV_NAMES = (
    "dataset_inventory", "image_statistics", "dark_statistics",
    "exposure_linearity_summary", "exposure_linearity_points", "gain_response",
    "repeatability", "acquisition_transition_anomalies", "usable_dynamic_range",
    "exposure_gap_analysis", "recommended_camera_settings", "qualification_results",
)


def write_outputs(outcome: AnalysisOutcome, output_dir: str | Path, representative: np.ndarray | None = None) -> Path:
    root = Path(output_dir)
    report_dir = root / "report"
    plots_dir = root / "plots"
    csv_dir = root / "csv"
    profile_dir = root / "profile"
    for folder in (report_dir, plots_dir, csv_dir, profile_dir):
        folder.mkdir(parents=True, exist_ok=True)
    atomic_write_json(root / "analysis_summary.json", outcome.summary)
    atomic_write_json(profile_dir / "camera_linearity_profile.json", outcome.profile)
    atomic_write_json(root / "camera_linearity_profile.json", outcome.profile)
    for name in CSV_NAMES:
        _write_csv(csv_dir / f"{name}.csv", outcome.tables.get(name, []))
        _write_csv(root / f"{name}.csv", outcome.tables.get(name, []))
    report = _markdown_report(outcome.summary)
    (report_dir / "CAMERA_LINEARITY_REPORT.md").write_text(report, encoding="utf-8")
    (root / "CAMERA_LINEARITY_REPORT.md").write_text(report, encoding="utf-8")
    _write_plots(plots_dir, outcome.tables, outcome.summary)
    if representative is not None:
        _write_roi_overlay(root / "ROI_overlay.png", representative, outcome.summary.get("roi"))
        _write_roi_overlay(plots_dir / "representative_roi_preview.png", representative, outcome.summary.get("roi"))
    else:
        _placeholder(root / "ROI_overlay.png", "ROI preview unavailable")
        _placeholder(plots_dir / "representative_roi_preview.png", "Representative frame unavailable")
    outcome.output_dir = root
    return root


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if not fields:
            stream.write("status\nNO_DATA\n")
            return
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell(value) for key, value in row.items()})


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _markdown_report(summary: dict[str, Any]) -> str:
    limitations = summary.get("limitations") or ["None recorded"]
    gains = summary.get("validated_gains") or []
    return "\n".join((
        "# Camera Linearity Qualification Report",
        "",
        f"- Overall Qualification: **{summary.get('overall_qualification', 'FAIL')}**",
        f"- RAW format: {summary.get('raw_format', 'UNKNOWN')}",
        f"- Validated Gains: {', '.join(map(str, gains)) or 'None'}",
        f"- Reliable DN range: {summary.get('reliable_dn_low')} to {summary.get('reliable_dn_high')}",
        f"- Preferred Auto Exposure range: {summary.get('preferred_dn_low')} to {summary.get('preferred_dn_high')}",
        f"- Target DN: {summary.get('target_dn')}",
        f"- Compression onset: {summary.get('compression_onset')}",
        f"- Saturation warning: {summary.get('saturation_warning')}",
        f"- Saturation rejection: {summary.get('saturation_reject')}",
        f"- Transition-frame status: {summary.get('transition_frame_status')}",
        f"- HDR / Multi-exposure readiness: {summary.get('hdr_readiness')}",
        f"- Formal profile allowed: {'YES' if summary.get('profile_usable_for_production') else 'NO'}",
        "- Main limitations: " + "; ".join(str(item) for item in limitations),
        "- Recommended next step: " + str(summary.get("recommended_next_step", "Review failed criteria.")),
        "",
        "## Per-Gain Results",
        "",
        "```json",
        json.dumps(summary.get("per_gain_linearity", []), ensure_ascii=False, indent=2),
        "```",
        "",
        "> Synthetic/fake-camera evidence is never equivalent to RisingCam hardware qualification.",
        "",
    ))


def _write_plots(root: Path, tables: dict[str, list[dict[str, Any]]], summary: dict[str, Any]) -> None:
    definitions = {
        "dark_corrected_dn_vs_exposure.png": ("actual_exposure_ms", "dark_corrected_median", "Exposure linearity", "exposure_linearity_points"),
        "regression_residual.png": ("actual_exposure_ms", "residual_percent", "Regression residual", "exposure_linearity_points"),
        "dn_per_exposure_stability.png": ("actual_exposure_ms", "dn_per_ms", "DN/exposure stability", "exposure_linearity_points"),
        "gain_response.png": ("gain_percent", "response_ratio", "Empirical Gain response", "gain_response"),
        "temporal_repeatability.png": ("actual_exposure_ms", "median_cv_percent", "Temporal repeatability", "repeatability"),
        "dark_dn_vs_exposure.png": ("actual_exposure_ms", "median", "Dark DN vs exposure", "dark_statistics"),
        "dark_dn_vs_temperature.png": ("camera_temperature_c", "median", "Dark DN vs temperature", "dark_statistics"),
        "saturation_compression.png": ("actual_exposure_ms", "saturation_fraction", "Saturation / compression", "exposure_linearity_points"),
        "exposure_gap_consistency.png": ("lower_exposure_ms", "median_error_percent", "Exposure-gap consistency", "exposure_gap_analysis"),
    }
    for filename, (x_key, y_key, title, table) in definitions.items():
        rows = tables.get(table, [])
        points = []
        for row in rows:
            try:
                x, y = float(row[x_key]), float(row[y_key])
                if np.isfinite(x) and np.isfinite(y):
                    points.append((x, y))
            except (KeyError, TypeError, ValueError):
                pass
        _line_plot(root / filename, points, title, x_key, y_key)
    heat_rows = tables.get("exposure_linearity_points", [])
    _heatmap(root / "condition_heatmaps.png", heat_rows)


def _font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 18)
    except OSError:
        return ImageFont.load_default()


def _line_plot(path: Path, points: list[tuple[float, float]], title: str, x_label: str, y_label: str) -> None:
    image = Image.new("RGB", (1000, 650), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    draw.text((30, 20), title, fill="black", font=font)
    left, top, right, bottom = 90, 70, 950, 570
    draw.rectangle((left, top, right, bottom), outline="#444", width=2)
    draw.text((left, 600), x_label, fill="black", font=font)
    draw.text((10, top), y_label, fill="black", font=font)
    if points:
        xs, ys = zip(*points)
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        if xmax == xmin: xmax += 1
        if ymax == ymin: ymax += 1
        mapped = [(
            left + (x - xmin) / (xmax - xmin) * (right - left),
            bottom - (y - ymin) / (ymax - ymin) * (bottom - top),
        ) for x, y in sorted(points)]
        if len(mapped) > 1:
            draw.line(mapped, fill="#1665d8", width=3)
        for x, y in mapped:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#d33")
        draw.text((left, bottom + 8), f"x {xmin:.4g} .. {xmax:.4g}", fill="#444", font=font)
        draw.text((right - 250, top + 8), f"y {ymin:.4g} .. {ymax:.4g}", fill="#444", font=font)
    else:
        draw.text((left + 280, top + 220), "INSUFFICIENT DATA", fill="#b33", font=font)
    image.save(path)


def _heatmap(path: Path, rows: list[dict[str, Any]]) -> None:
    image = Image.new("RGB", (1000, 650), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    draw.text((30, 20), "Gain x Exposure condition heatmap", fill="black", font=font)
    gains = sorted({int(row["gain_percent"]) for row in rows if row.get("gain_percent") is not None})
    exposures = sorted({float(row["actual_exposure_ms"]) for row in rows if row.get("actual_exposure_ms") is not None})
    lookup = {(int(row["gain_percent"]), float(row["actual_exposure_ms"])): float(row.get("dark_corrected_median", 0)) for row in rows if row.get("gain_percent") is not None and row.get("actual_exposure_ms") is not None}
    maximum = max(1.0, max((abs(value) for value in lookup.values()), default=0.0))
    if not gains or not exposures:
        draw.text((350, 300), "INSUFFICIENT DATA", fill="#b33", font=font)
    else:
        cell_w = max(30, 850 // len(exposures)); cell_h = max(30, 500 // len(gains))
        for row_index, gain in enumerate(gains):
            draw.text((10, 100 + row_index * cell_h), f"G{gain}", fill="black", font=font)
            for col, exposure in enumerate(exposures):
                value = lookup.get((gain, exposure), 0.0)
                intensity = int(255 * max(0.0, min(1.0, value / maximum)))
                x, y = 90 + col * cell_w, 90 + row_index * cell_h
                draw.rectangle((x, y, x + cell_w - 2, y + cell_h - 2), fill=(255 - intensity, 255 - intensity // 2, 255))
        for col, exposure in enumerate(exposures):
            draw.text((90 + col * cell_w, 60), f"{exposure:g}", fill="black", font=font)
    image.save(path)


def _write_roi_overlay(path: Path, array: np.ndarray, roi: Any) -> None:
    source = np.asarray(array, dtype=np.float64)
    low, high = np.percentile(source, (1, 99)) if source.size else (0, 1)
    scaled = np.clip((source - low) * 255.0 / max(1.0, high - low), 0, 255).astype(np.uint8)
    image = Image.fromarray(scaled, mode="L").convert("RGB")
    draw = ImageDraw.Draw(image)
    if isinstance(roi, dict):
        x, y, width, height = (int(roi[key]) for key in ("x", "y", "width", "height"))
        draw.rectangle((x, y, x + width - 1, y + height - 1), outline="red", width=max(2, image.width // 500))
    image.save(path)


def _placeholder(path: Path, text: str) -> None:
    image = Image.new("RGB", (800, 500), "white")
    ImageDraw.Draw(image).text((100, 230), text, fill="#b33", font=_font())
    image.save(path)
