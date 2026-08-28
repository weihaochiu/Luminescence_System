from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import tifffile

from .models import FrameType, LoadedFrame, ROI


NAME_PATTERN = re.compile(
    r"(?P<type>LIGHT|DARK).*?G(?P<gain>\d+).*?E(?P<exposure>\d+(?:\.\d+)?)ms.*?R(?P<repeat>\d+).*?SEQ(?P<sequence>\d+)",
    re.IGNORECASE,
)


def load_folder(root: str | Path) -> tuple[list[LoadedFrame], list[str]]:
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(base)
    frames: list[LoadedFrame] = []
    errors: list[str] = []
    for path in sorted((*base.rglob("*.tif"), *base.rglob("*.tiff"))):
        try:
            frames.append(load_frame(path, load_pixels=False))
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return frames, errors


def load_frame(path: str | Path, *, load_pixels: bool = True) -> LoadedFrame:
    tiff_path = Path(path)
    with tifffile.TiffFile(tiff_path) as handle:
        series = handle.series[0]
        image_shape = tuple(int(item) for item in series.shape)
        image_dtype = str(series.dtype)
    image = np.asarray(tifffile.imread(tiff_path)) if load_pixels else None
    sidecar = tiff_path.with_suffix(".json")
    metadata: dict[str, Any] = {}
    if sidecar.exists():
        metadata = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    parsed = NAME_PATTERN.search(tiff_path.stem)
    frame_text = _first(metadata, "frame_type", "FrameType", "MeasurementType")
    if frame_text is None and parsed:
        frame_text = parsed.group("type")
    frame_type = _frame_type(frame_text)
    gain = _integer(_first(metadata, "actual_gain_percent", "actual_gain_readback", "GainReadback", "Gain", "MatchingGain"))
    if gain is None and parsed:
        gain = int(parsed.group("gain"))
    requested = _number(_first(metadata, "requested_exposure_ms", "RequestedExposureMs", "Exposure", "MatchingExposure"))
    actual = _number(_first(metadata, "actual_exposure_ms", "ActualExposureMs"))
    if actual is None:
        readback_us = _number(_first(metadata, "actual_exposure_readback_us", "ExposureReadbackUs"))
        actual = readback_us / 1000.0 if readback_us is not None else requested
    if requested is None and parsed:
        requested = float(parsed.group("exposure"))
    repeat = _integer(_first(metadata, "repeat_index", "RepeatIndex"))
    sequence = _integer(_first(metadata, "frame_sequence", "FrameSequence"))
    if parsed:
        repeat = repeat if repeat is not None else int(parsed.group("repeat"))
        sequence = sequence if sequence is not None else int(parsed.group("sequence"))
    temperature = _number(_first(metadata, "camera_temperature_c", "CameraTemperatureC", "CameraTemperature_C", "CameraTemperature"))
    maximum = _integer(_first(metadata, "effective_dn_max", "EffectiveDNMax"))
    bit_depth = _integer(_first(metadata, "sensor_bit_depth", "SensorBitDepth", "BitDepth"))
    alignment = str(_first(metadata, "raw_value_alignment", "RawValueAlignment") or "unknown").lower()
    roi = _roi(_first(metadata, "roi", "ROI"))
    return LoadedFrame(
        tiff_path, sidecar if sidecar.exists() else None, image, frame_type, gain,
        requested, actual, repeat, sequence, temperature, maximum, bit_depth,
        alignment, roi, metadata, image_shape, image_dtype,
    )


def effective_array(frame: LoadedFrame) -> np.ndarray:
    source = np.asarray(tifffile.imread(frame.tiff_path) if frame.image is None else frame.image)
    if source.dtype != np.uint16 or source.ndim != 2:
        raise TypeError("Scientific input must be a uint16 HxW TIFF")
    if frame.sensor_bit_depth is None or frame.effective_dn_max is None:
        raise ValueError("SensorBitDepth and EffectiveDNMax are required")
    expected = (1 << int(frame.sensor_bit_depth)) - 1
    if int(frame.effective_dn_max) != expected:
        raise ValueError("EffectiveDNMax is inconsistent with SensorBitDepth")
    if frame.raw_alignment == "right":
        result = source.copy()
    elif frame.raw_alignment == "left":
        result = np.right_shift(source, 16 - int(frame.sensor_bit_depth))
    else:
        raise ValueError("RawValueAlignment must be verified as right or left")
    if np.any(result > int(frame.effective_dn_max)):
        raise ValueError("Invalid DN above EffectiveDNMax")
    return result


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _frame_type(value: Any) -> FrameType | None:
    text = str(value or "").upper()
    if "DARK" in text:
        return FrameType.DARK
    if "LIGHT" in text or text in {"EL", "SIGNAL"}:
        return FrameType.LIGHT
    return None


def _roi(value: Any) -> ROI | None:
    if isinstance(value, dict):
        try:
            return ROI(int(value["x"]), int(value["y"]), int(value["width"]), int(value["height"]))
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return ROI(*(int(item) for item in value))
        except (TypeError, ValueError):
            return None
    return None
