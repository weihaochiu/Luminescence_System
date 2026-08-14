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

from PIL import Image, ImageChops, ImageDraw, ImageFont
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
    tiff_path: Path
    jpeg_path: Path
    metadata_path: Path
    file_hashes: dict[str, str]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_pixel_csv(path: Path, image: Image.Image, *, divisor: float | None = None) -> None:
    rgb = image.convert("RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(("y", "x", "R", "G", "B"))
        pixels = rgb.load()
        for y in range(rgb.height):
            for x in range(rgb.width):
                values = pixels[x, y]
                if divisor is not None:
                    values = tuple(float(value) / divisor for value in values)
                writer.writerow((y, x, *values))


def save_pixel_csv_products(
    raw_image: QImage | Image.Image,
    output_stem: Path,
    output_options: Any,
    *,
    dark_image: QImage | Image.Image | None = None,
    exposure_ms: float,
) -> dict[str, str]:
    if not output_options.export_pixel_csv:
        return {}
    raw = qimage_to_pillow(raw_image) if isinstance(raw_image, QImage) else raw_image.copy()
    dark = (
        qimage_to_pillow(dark_image) if isinstance(dark_image, QImage)
        else dark_image.copy() if isinstance(dark_image, Image.Image) else None
    )
    corrected = ImageChops.subtract(raw.convert("RGB"), dark.convert("RGB")) if dark is not None else raw.convert("RGB")
    paths: dict[str, str] = {}
    if output_options.pixel_csv_raw:
        target = output_stem.with_name(output_stem.name + "_pixels_raw.csv")
        _write_pixel_csv(target, raw)
        paths["RAW"] = str(target)
    if output_options.pixel_csv_dark_corrected:
        if dark is None:
            raise RuntimeError("Dark-corrected Pixel CSV requires a matching Shared Dark frame")
        target = output_stem.with_name(output_stem.name + "_pixels_dark_corrected.csv")
        _write_pixel_csv(target, corrected)
        paths["DarkCorrected"] = str(target)
    if output_options.pixel_csv_exposure_normalized:
        target = output_stem.with_name(output_stem.name + "_pixels_exposure_normalized.csv")
        _write_pixel_csv(target, corrected, divisor=max(float(exposure_ms), 1e-12))
        paths["ExposureNormalized"] = str(target)
    return paths


def save_matrix_capture(
    raw_image: QImage | Image.Image,
    output_stem: Path,
    metadata: dict[str, Any],
) -> SavedCapture:
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    raw = qimage_to_pillow(raw_image) if isinstance(raw_image, QImage) else raw_image.copy()
    raw_pixels = raw.tobytes()
    raw_size = raw.size
    tiff_path = output_stem.with_suffix(".tiff")
    jpeg_path = output_stem.with_suffix(".jpg")
    metadata_path = output_stem.with_suffix(".json")
    raw.save(tiff_path, compression="tiff_lzw")
    lines = format_dark_footer(metadata) if metadata["MeasurementType"] == "DARK" else format_el_footer(metadata)
    annotated = annotated_jpeg_image(raw, lines)
    annotated.save(jpeg_path, quality=95, subsampling=0)
    if raw.size != raw_size or raw.tobytes() != raw_pixels:
        raise RuntimeError("Footer generation modified the RAW image buffer")
    metadata.update({
        "RawTiffPath": str(tiff_path),
        "AnnotatedJpegPath": str(jpeg_path),
        "MetadataJsonPath": str(metadata_path),
    })
    payload = dict(metadata)
    payload.update({
        "RawImageWidth": raw.width,
        "RawImageHeight": raw.height,
        "AnnotatedJpegWidth": annotated.width,
        "AnnotatedJpegHeight": annotated.height,
    })
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    hashes = {
        "RawTiffSha256": sha256_file(tiff_path),
        "AnnotatedJpegSha256": sha256_file(jpeg_path),
        "MetadataJsonSha256": sha256_file(metadata_path),
    }
    for name, path in dict(metadata.get("PixelCsvPaths", {})).items():
        hashes[f"PixelCsv{name}Sha256"] = sha256_file(path)
    return SavedCapture(tiff_path, jpeg_path, metadata_path, hashes)


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
