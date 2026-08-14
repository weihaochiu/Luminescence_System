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

import cv2
import numpy as np
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


def write_pixel_csv_atomic(
    path: Path, image: Image.Image, *, divisor: float | None = None
) -> None:
    rgb = image.convert("RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(("y", "x", "R", "G", "B"))
            pixels = rgb.load()
            for y in range(rgb.height):
                for x in range(rgb.width):
                    values = pixels[x, y]
                    if divisor is not None:
                        values = tuple(float(value) / divisor for value in values)
                    writer.writerow((y, x, *values))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
        write_pixel_csv_atomic(target, raw)
        paths["RAW"] = str(target)
    if output_options.pixel_csv_dark_corrected:
        if dark is None:
            raise RuntimeError("Dark-corrected Pixel CSV requires a matching Shared Dark frame")
        target = output_stem.with_name(output_stem.name + "_pixels_dark_corrected.csv")
        write_pixel_csv_atomic(target, corrected)
        paths["DarkCorrected"] = str(target)
    if output_options.pixel_csv_exposure_normalized:
        target = output_stem.with_name(output_stem.name + "_pixels_exposure_normalized.csv")
        write_pixel_csv_atomic(
            target, corrected, divisor=max(float(exposure_ms), 1e-12)
        )
        paths["ExposureNormalized"] = str(target)
    return paths


def scientific_to_visualization(scientific_image: np.ndarray) -> Image.Image:
    """Create an 8-bit display copy without mutating the scientific source."""

    source = np.asarray(scientific_image)
    if source.dtype != np.uint16:
        raise TypeError("Scientific camera source must use a uint16 container")
    working = source.astype(np.float64, copy=True)
    maximum = float(np.max(working, initial=0.0))
    scale_max = 4095.0 if maximum <= 4095.0 else 65535.0
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
    encoded = source if source.ndim == 2 else cv2.cvtColor(source, cv2.COLOR_RGB2BGR)
    if not cv2.imwrite(str(path), encoded):
        raise OSError(f"Unable to write scientific TIFF: {path}")


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
    preview = scientific_to_visualization(scientific)

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
