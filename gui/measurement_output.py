from __future__ import annotations

"""RAW TIFF and bottom-footer JPEG output for EL Matrix captures."""

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import tifffile
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QImage


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def sanitize_filename(value: str, fallback: str = "sample") -> str:
    safe = INVALID_FILENAME.sub("_", value.strip()).rstrip(". ")
    return safe or fallback


def _number(value: float | int | None, decimals: int = 3) -> str:
    if value is None or not math.isfinite(float(value)):
        return "N/A"
    rendered = f"{float(value):,.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", ""} else rendered


def format_el_footer(metadata: dict[str, Any]) -> tuple[str, str, str]:
    return (
        f"Sample ID: {metadata['SampleID']}",
        f"{metadata['Channel']} | J={_number(metadata['CommandedCurrentDensity'])} mA/cm² | "
        f"Gain={int(metadata['Gain'])}% | Exposure={_number(metadata['Exposure'], 3)} ms | "
        f"Repeat={metadata['RepeatIndex']}/{metadata['RepeatTotal']}",
        f"Measured: I={_number(metadata.get('MeasuredCurrentMa'))} mA | "
        f"V={_number(metadata.get('MeasuredVoltage'), 3)} V | "
        f"Camera={_number(metadata.get('CameraTemperature'), 1)} °C | {metadata['Timestamp']}",
    )


def format_dark_footer(metadata: dict[str, Any]) -> tuple[str, str, str]:
    channels = ", ".join(metadata["ApplicableChannels"])
    return (
        f"Shared Dark | Applicable Channels: {channels}",
        f"Gain={int(metadata['Gain'])}% | Exposure={_number(metadata['Exposure'], 3)} ms | "
        f"Repeat={metadata['RepeatIndex']}/{metadata['RepeatTotal']}",
        f"Camera={_number(metadata.get('CameraTemperature'), 1)} °C | {metadata['Timestamp']}",
    )


def qimage_to_pillow(image: QImage) -> Image.Image:
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    raw = bytes(rgb.bits())
    return Image.frombuffer(
        "RGB", (rgb.width(), rgb.height()), raw, "raw", "RGB", rgb.bytesPerLine(), 1
    ).copy()


def annotated_jpeg_image(raw: Image.Image, lines: Iterable[str]) -> Image.Image:
    source = raw.copy()
    target_font_px = max(16, round(source.width / 95))
    try:
        font = ImageFont.truetype("arial.ttf", target_font_px)
    except OSError:
        font = ImageFont.load_default()
    lines = tuple(lines)
    padding = max(10, target_font_px // 2)
    line_gap = max(4, target_font_px // 4)
    probe = ImageDraw.Draw(source)
    boxes = [probe.textbbox((0, 0), line, font=font) for line in lines]
    line_height = max((box[3] - box[1] for box in boxes), default=target_font_px)
    footer_height = padding * 2 + len(lines) * line_height + max(0, len(lines) - 1) * line_gap
    annotated = Image.new("RGB", (source.width, source.height + footer_height), (88, 88, 88))
    annotated.paste(source, (0, 0))
    draw = ImageDraw.Draw(annotated)
    y = source.height + padding
    for line in lines:
        # Preserve metadata text; only the visual copy is shortened when needed.
        visible = line
        available = max(0, source.width - 2 * padding)
        if draw.textbbox((0, 0), visible, font=font)[2] > available:
            body = visible
            while body and draw.textbbox((0, 0), body.rstrip() + "…", font=font)[2] > available:
                body = body[:-1]
            visible = body.rstrip() + "…" if body else ""
        draw.text((padding, y), visible, fill=(255, 255, 255), font=font)
        y += line_height + line_gap
    return annotated


@dataclass(frozen=True)
class SavedCapture:
    tiff_path: Path | None
    png_path: Path | None
    jpeg_path: Path | None
    footer_jpeg_path: Path | None
    metadata_path: Path
    file_hashes: dict[str, str]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_mono_array_csv_atomic(
    path: Path, array: np.ndarray, *, value_header: str = "DN"
) -> None:
    """Atomically write an H×W scientific array without image conversion."""

    values = np.asarray(array)
    if values.ndim != 2:
        raise ValueError("Scientific Pixel CSV requires an H×W mono array")
    if not value_header or value_header in {"x", "y"}:
        raise ValueError("Pixel CSV value header must identify the scientific value")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(("y", "x", value_header))
            for y in range(values.shape[0]):
                for x in range(values.shape[1]):
                    writer.writerow((y, x, values[y, x].item()))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_pixel_csv_products(
    raw_array: np.ndarray,
    output_stem: Path,
    output_options: Any,
    *,
    dark_array: np.ndarray | None = None,
    exposure_ms: float,
) -> dict[str, str]:
    """Array-only helper retained for focused tests and offline tooling."""

    if not output_options.export_pixel_csv:
        return {}
    raw = np.asarray(raw_array)
    if raw.dtype != np.uint16 or raw.ndim != 2:
        raise TypeError("Raw Pixel CSV requires a uint16 H×W scientific array")
    dark = None if dark_array is None else np.asarray(dark_array)
    if dark is not None and (dark.dtype != np.uint16 or dark.shape != raw.shape):
        raise TypeError("Shared Dark must be a shape-matched uint16 H×W array")
    corrected = None if dark is None else raw.astype(np.int32) - dark.astype(np.int32)
    paths: dict[str, str] = {}
    if output_options.pixel_csv_raw:
        target = output_stem.with_name(output_stem.name + "_pixels_raw.csv")
        write_mono_array_csv_atomic(target, raw, value_header="DN")
        paths["RAW"] = str(target)
    if output_options.pixel_csv_dark_corrected:
        if corrected is None:
            raise RuntimeError("Dark-corrected Pixel CSV requires a matching Shared Dark frame")
        target = output_stem.with_name(output_stem.name + "_pixels_dark_corrected.csv")
        write_mono_array_csv_atomic(target, corrected, value_header="DarkCorrectedDN")
        paths["DarkCorrected"] = str(target)
    if output_options.pixel_csv_exposure_normalized:
        if corrected is None:
            raise RuntimeError("Exposure-normalized Pixel CSV requires a matching Shared Dark frame")
        if float(exposure_ms) <= 0:
            raise ValueError("Exposure normalization requires exposure_ms > 0")
        target = output_stem.with_name(output_stem.name + "_pixels_exposure_normalized.csv")
        write_mono_array_csv_atomic(
            target,
            corrected.astype(np.float64) / float(exposure_ms),
            value_header="DN_per_ms",
        )
        paths["ExposureNormalized"] = str(target)
    return paths


def scientific_to_visualization(
    scientific_image: np.ndarray,
    sensor_bit_depth: int,
    raw_value_alignment: str,
) -> Image.Image:
    """Create an 8-bit display copy without mutating the scientific source."""

    source = np.asarray(scientific_image)
    if source.dtype != np.uint16:
        raise TypeError("Scientific camera source must use a uint16 container")
    bit_depth = int(sensor_bit_depth)
    if not 1 <= bit_depth <= 16:
        raise ValueError("SensorBitDepth must be between 1 and 16")
    alignment = str(raw_value_alignment).strip().lower()
    if alignment == "right":
        working = source.astype(np.float64, copy=True)
        scale_max = float((1 << bit_depth) - 1)
    elif alignment == "left":
        working = np.right_shift(source, 16 - bit_depth).astype(np.float64)
        scale_max = float((1 << bit_depth) - 1)
    elif alignment == "unknown":
        # Do not infer alignment or bit depth from the brightness of one frame.
        working = source.astype(np.float64, copy=True)
        scale_max = 65535.0
    else:
        raise ValueError("RawValueAlignment must be 'right', 'left', or 'unknown'")
    mapped = np.clip(np.rint(working * (255.0 / scale_max)), 0, 255).astype(np.uint8)
    if mapped.ndim == 2:
        return Image.fromarray(mapped, mode="L")
    if mapped.ndim == 3 and mapped.shape[2] == 3:
        return Image.fromarray(mapped, mode="RGB")
    raise ValueError("Scientific image must be H×W or H×W×3")


def save_scientific_tiff(path: Path, scientific_image: np.ndarray) -> None:
    source = np.asarray(scientific_image)
    if source.dtype != np.uint16:
        raise TypeError("TIFF scientific master requires uint16 source data")
    path.parent.mkdir(parents=True, exist_ok=True)
    if source.ndim not in (2, 3) or (source.ndim == 3 and source.shape[2] != 3):
        raise ValueError("Scientific image must be H×W or H×W×3")
    tifffile.imwrite(path, source, photometric="rgb" if source.ndim == 3 else "minisblack")


def save_matrix_capture(
    scientific_image: np.ndarray | None,
    preview_image: QImage | Image.Image,
    output_stem: Path,
    metadata: dict[str, Any],
    output_options: Any,
) -> SavedCapture:
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    if scientific_image is None:
        raise RuntimeError(
            "Scientific frame is unavailable; refusing to create TIFF from Live View"
        )
    scientific = np.asarray(scientific_image)
    if scientific.dtype != np.uint16:
        raise TypeError("Camera acquisition must provide a uint16 scientific frame")
    scientific_before = scientific.copy()
    # Derived formats branch from the same acquisition array; the QImage is
    # accepted only for live-view reporting and is never used as save input.
    del preview_image
    preview = scientific_to_visualization(
        scientific,
        int(metadata.get("SensorBitDepth", metadata.get("BitDepth", 16))),
        str(metadata.get("RawValueAlignment", "unknown")),
    )

    tiff_path = output_stem.with_suffix(".tiff") if output_options.format_tiff else None
    png_path = output_stem.with_suffix(".png") if output_options.format_png else None
    jpeg_path = output_stem.with_suffix(".jpg") if output_options.format_jpg else None
    footer_path = (
        output_stem.with_name(output_stem.name + "_footer.jpg")
        if output_options.format_jpg_with_footer else None
    )
    metadata_path = output_stem.with_suffix(".json")
    if tiff_path is not None:
        save_scientific_tiff(tiff_path, scientific)
    if png_path is not None:
        preview.save(png_path, format="PNG")
    if jpeg_path is not None:
        preview.convert("RGB").save(jpeg_path, quality=95, subsampling=0)
    annotated: Image.Image | None = None
    if footer_path is not None:
        lines = (
            format_dark_footer(metadata)
            if metadata["MeasurementType"] == "DARK"
            else format_el_footer(metadata)
        )
        annotated = annotated_jpeg_image(preview.convert("RGB"), lines)
        annotated.save(footer_path, quality=95, subsampling=0)
    if not np.array_equal(scientific, scientific_before):
        raise RuntimeError("Derived output generation modified the scientific source buffer")
    metadata.update({
        "ScientificTiffPath": str(tiff_path) if tiff_path else None,
        "RawTiffPath": str(tiff_path) if tiff_path else None,
        "PngPath": str(png_path) if png_path else None,
        "JpegPath": str(jpeg_path) if jpeg_path else None,
        "FooterJpegPath": str(footer_path) if footer_path else None,
        "AnnotatedJpegPath": str(footer_path) if footer_path else None,
        "MetadataJsonPath": str(metadata_path),
        "ScientificDtype": str(scientific.dtype),
        "ScientificShape": list(scientific.shape),
    })
    payload = dict(metadata)
    payload.update({
        "RawImageWidth": int(scientific.shape[1]),
        "RawImageHeight": int(scientific.shape[0]),
        "AnnotatedJpegWidth": annotated.width if annotated else None,
        "AnnotatedJpegHeight": annotated.height if annotated else None,
    })
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    hashes = {"MetadataJsonSha256": sha256_file(metadata_path)}
    for key, path in (
        ("ScientificTiffSha256", tiff_path),
        ("PngSha256", png_path),
        ("JpegSha256", jpeg_path),
        ("FooterJpegSha256", footer_path),
    ):
        if path is not None:
            hashes[key] = sha256_file(path)
    for name, path in dict(metadata.get("PixelCsvPaths", {})).items():
        hashes[f"PixelCsv{name}Sha256"] = sha256_file(path)
    return SavedCapture(
        tiff_path, png_path, jpeg_path, footer_path, metadata_path, hashes
    )


def append_manifest(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
        for key, value in metadata.items()
    }
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def capture_timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M:%S")
