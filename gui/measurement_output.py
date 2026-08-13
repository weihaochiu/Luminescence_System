from __future__ import annotations

"""RAW TIFF and bottom-footer JPEG output for EL Matrix captures."""

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

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
    tiff_path: Path
    jpeg_path: Path
    metadata_path: Path


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
    payload = dict(metadata)
    payload.update({
        "RawImageWidth": raw.width,
        "RawImageHeight": raw.height,
        "AnnotatedJpegWidth": annotated.width,
        "AnnotatedJpegHeight": annotated.height,
    })
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return SavedCapture(tiff_path, jpeg_path, metadata_path)


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
