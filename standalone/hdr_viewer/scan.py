from __future__ import annotations

"""TIFF inventory and strict grouping, independent of Qt and camera hardware."""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
from typing import Callable

import numpy as np
import tifffile


OUTPUT_MARKER = "hdr_viewer_manifest.json"
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
NAME = re.compile(
    rf"^N\d+_(?P<sample>.+)_(?P<channel>CH\d+)_J(?P<density>{NUMBER})_"
    rf"G(?P<gain>\d+)_E(?P<exposure>{NUMBER})(?:ms)?_R(?P<repeat>\d+)$",
    re.IGNORECASE,
)
RUN_NAME = re.compile(r"^\d{8}_\d{6}_[a-fA-F0-9]{8}$")


class Cancelled(Exception):
    pass


@dataclass(frozen=True, order=True)
class GroupKey:
    run: str
    sample: str
    channel: str
    density: float
    gain: int


@dataclass(frozen=True)
class Frame:
    path: Path
    metadata_path: Path | None
    key: GroupKey
    exposure_ms: float
    requested_exposure_ms: float
    shape: tuple[int, int]
    bit_depth: int
    alignment: str
    warnings: tuple[str, ...]
    metadata: dict
    size: int
    mtime_ns: int
    metadata_bytes: bytes | None


@dataclass
class Group:
    key: GroupKey
    frames: list[Frame] = field(default_factory=list)

    @property
    def exposures(self) -> list[float]:
        return sorted({frame.requested_exposure_ms for frame in self.frames})

    @property
    def problem(self) -> str:
        if len(self.exposures) < 2:
            return "NEED_MULTIPLE_EXPOSURES"
        if len({f.exposure_ms for f in self.frames}) < 2:
            return "NEED_MULTIPLE_EXPOSURES"
        if len({(f.shape, f.bit_depth, f.alignment) for f in self.frames}) != 1:
            return "INCONSISTENT_FORMAT"
        identities = {
            (f.metadata.get("CameraSerial"), f.metadata.get("CameraModel"))
            for f in self.frames
            if f.metadata.get("CameraSerial") or f.metadata.get("CameraModel")
        }
        if len(identities) > 1:
            return "INCONSISTENT_CAMERA"
        return ""

    @property
    def work(self) -> int:
        return sum(f.shape[0] * f.shape[1] for f in self.frames) + 3 * self.frames[0].shape[0] * self.frames[0].shape[1]


@dataclass
class Inventory:
    root: Path
    groups: list[Group]
    issues: list[dict]
    scanned: int
    excluded_dark: int


def _number(value: object, field_name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"Invalid {field_name}")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"Invalid {field_name}")
    return number


def _first(data: dict, *keys: str):
    return next((data[k] for k in keys if data.get(k) is not None), None)


def _run_folder(path: Path) -> Path | None:
    for parent in path.parents:
        if (parent / "measurement_snapshot.json").is_file() or RUN_NAME.fullmatch(parent.name):
            return parent
    return None


def read_frame(path: Path) -> Frame | None:
    sidecar = path.with_suffix(".json")
    content = sidecar.read_bytes() if sidecar.is_file() else None
    data = json.loads(content.decode("utf-8-sig")) if content is not None else {}
    if not isinstance(data, dict):
        raise ValueError("JSON metadata must be an object")
    measurement = str(_first(data, "MeasurementType", "frame_type", "FrameType") or "").upper()
    if "DARK" in measurement or "DARK" in path.stem.upper() or any(p.name.upper() == "DARK" for p in path.parents):
        return None
    if data.get("hdr_viewer_output") or "_HDR_" in path.stem.upper():
        return None
    parsed = NAME.fullmatch(path.stem)
    fallback = parsed.groupdict() if parsed else {}
    if measurement and measurement not in {"EL", "LIGHT", "SIGNAL"}:
        raise ValueError("Unsupported measurement type")
    if str(data.get("OutputMode", "current_density")) != "current_density":
        raise ValueError("Voltage-mode capture has no commanded current-density condition")
    warnings: list[str] = []
    if content is None:
        warnings.append("FILENAME_METADATA")
    run = str(data.get("MeasurementRunID") or "").strip()
    if not run:
        folder = _run_folder(path)
        if folder is None:
            raise ValueError("Missing MeasurementRunID and identifiable original run folder")
        # Absolute directory prevents same-named legacy folders being combined.
        run = "folder:" + str(folder.resolve())
        warnings.append("FOLDER_RUN_ID")
    sample = str(data.get("SampleID") or fallback.get("sample") or "").strip()
    channel = str(data.get("Channel") or fallback.get("channel") or "").strip().upper()
    if not sample or not channel:
        raise ValueError("Missing sample or channel")
    density = _first(data, "SetCurrentDensityMaCm2", "CommandedCurrentDensity")
    density = _number(density if density is not None else fallback.get("density"), "current density")
    gain_value = _first(data, "GainReadback", "Gain", "actual_gain_percent")
    gain = _number(gain_value if gain_value is not None else fallback.get("gain"), "Gain", positive=True)
    if gain != int(gain):
        raise ValueError("Gain must be an integer percentage")
    commanded_gain = data.get("Gain")
    if commanded_gain is not None and _number(commanded_gain, "Gain") != gain:
        raise ValueError("Gain readback differs from requested Gain")
    actual_us = _first(data, "ExposureUsedUs", "FrameExposureUs", "RealExposureReadbackUs")
    actual_ms = _first(data, "ActualExposureMs", "ExposureNormalizationMs", "actual_exposure_ms")
    if actual_us is not None:
        exposure = _number(actual_us, "actual exposure", positive=True) / 1000
    elif actual_ms is not None:
        exposure = _number(actual_ms, "actual exposure", positive=True)
    elif data.get("ExposureReadbackUs") is not None:
        exposure = _number(data["ExposureReadbackUs"], "exposure readback", positive=True) / 1000
    else:
        value = _first(data, "Exposure", "RequestedExposureMs", "requested_exposure_ms")
        exposure = _number(value if value is not None else fallback.get("exposure"), "exposure", positive=True)
        warnings.append("REQUESTED_EXPOSURE_ONLY")
    if parsed:
        for field_name, value in (("density", density), ("gain", gain)):
            if float(fallback[field_name]) != value:
                raise ValueError(f"Filename and metadata disagree: {field_name}")
        safe_sample = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", sample.strip()).rstrip(". ")
        if fallback["sample"] != safe_sample or fallback["channel"].upper() != channel:
            raise ValueError("Filename and metadata disagree: sample/channel")
    requested = _first(data, "RequestedExposureMs", "Exposure", "requested_exposure_ms")
    if requested is None:
        requested = fallback.get("exposure", exposure)
    requested = _number(requested, "requested exposure", positive=True)
    if parsed and not math.isclose(float(fallback["exposure"]), requested, rel_tol=1e-8):
        raise ValueError("Filename and metadata disagree: requested exposure")
    with tifffile.TiffFile(path) as handle:
        if len(handle.pages) != 1 or len(handle.series) != 1:
            raise ValueError("Only single-image TIFF captures are supported")
        series = handle.series[0]
        if series.dtype != np.dtype("uint16") or len(series.shape) != 2:
            raise ValueError("Input must be a uint16 monochrome TIFF")
        shape = tuple(int(v) for v in series.shape)
    bits_value = _first(data, "SensorBitDepth", "sensor_bit_depth")
    alignment = str(_first(data, "RawValueAlignment", "raw_value_alignment") or "").lower()
    if bits_value is None and content is None:
        # Explicit viewing-only fallback; never infer sensor bit depth from max pixel.
        bits_value, alignment = 16, "right"
        warnings.append("ASSUMED_UINT16_RANGE")
    bits = _number(bits_value, "SensorBitDepth", positive=True)
    if bits != int(bits) or bits > 16 or alignment not in {"right", "left"}:
        raise ValueError("Invalid or unknown sensor bit depth / RAW alignment")
    maximum = data.get("EffectiveDNMax")
    if maximum is not None and _number(maximum, "EffectiveDNMax") != (1 << int(bits)) - 1:
        raise ValueError("EffectiveDNMax disagrees with sensor bit depth")
    stat = path.stat()
    return Frame(path, sidecar if content is not None else None,
                 GroupKey(run, sample, channel, density, int(gain)), exposure, requested, shape,
                 int(bits), alignment, tuple(warnings), data, stat.st_size, stat.st_mtime_ns, content)


def scan_folder(root: str | Path, *, check_cancel: Callable[[], None] = lambda: None,
                progress: Callable[[dict], None] = lambda _: None) -> Inventory:
    import os

    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError("Input folder does not exist")
    if (base / OUTPUT_MARKER).exists():
        raise ValueError("Generated HDR output is not an original capture folder")
    groups: dict[GroupKey, Group] = {}
    issues: list[dict] = []
    scanned = dark = 0

    def walk_error(error):
        issues.append({"path": str(error.filename), "code": "SCAN_ERROR", "detail": str(error)})

    for directory, children, files in os.walk(base, followlinks=False, onerror=walk_error):
        check_cancel()
        parent = Path(directory)
        children[:] = sorted(name for name in children if not (parent / name).is_symlink()
                             and not (parent / name / OUTPUT_MARKER).exists()
                             and not name.startswith("HDR_VIEW_OUTPUT_"))
        for name in sorted(files):
            check_cancel()
            path = parent / name
            if path.suffix.lower() not in {".tif", ".tiff"} or path.is_symlink():
                continue
            scanned += 1
            try:
                frame = read_frame(path)
                if frame is None:
                    dark += 1
                else:
                    groups.setdefault(frame.key, Group(frame.key)).frames.append(frame)
            except Exception as exc:
                issues.append({"path": str(path), "code": "INVALID_INPUT", "detail": str(exc)})
            progress({"phase": "scan", "scanned": scanned, "path": str(path)})
    return Inventory(base, [groups[key] for key in sorted(groups)], issues, scanned, dark)
