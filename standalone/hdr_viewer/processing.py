from __future__ import annotations

"""Streaming exposure fusion and display conversion; versioned correction seam."""

from dataclasses import dataclass
import hashlib
import math
from typing import Callable, Protocol

import numpy as np
import tifffile

from .scan import Frame, Group


class Correction(Protocol):
    """Future dark/gain/flat corrections act before exposure normalization.

    Adding an implementation does not enable a quantitative claim: a separate
    qualification/output contract will be required for that future mode.
    """

    def describe(self) -> dict: ...
    def apply(self, signal: np.ndarray, frame: Frame) -> np.ndarray: ...


class NoCorrection:
    def describe(self) -> dict:
        return {"name": "none", "version": "1", "quantitative": False}

    def apply(self, signal: np.ndarray, frame: Frame) -> np.ndarray:
        return signal


@dataclass(frozen=True)
class DisplaySettings:
    gamma: float = 2.2
    compression: float = 100.0

    def validate(self):
        if not math.isfinite(self.gamma) or not .1 <= self.gamma <= 10:
            raise ValueError("Display gamma must be 0.1–10")
        if not math.isfinite(self.compression) or not 1 <= self.compression <= 10000:
            raise ValueError("Display compression must be 1–10000")


@dataclass
class Fusion:
    image: np.ndarray
    valid: np.ndarray
    provenance: list[dict]
    corrections: dict


def load_signal(frame: Frame) -> tuple[np.ndarray, str]:
    stat = frame.path.stat()
    if stat.st_size != frame.size or stat.st_mtime_ns != frame.mtime_ns:
        raise ValueError("Input changed after scan; scan again")
    if frame.metadata_path is not None and frame.metadata_path.read_bytes() != frame.metadata_bytes:
        raise ValueError("Metadata changed after scan; scan again")
    # Hash the same file bytes that are decoded; don't read an unverified
    # replacement from a second path lookup.
    from io import BytesIO

    payload = frame.path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    expected = frame.metadata.get("ScientificTiffSha256") or frame.metadata.get("RawTiffSha256")
    if expected is not None and str(expected).lower() != digest:
        raise ValueError("TIFF checksum differs from capture metadata")
    raw = tifffile.imread(BytesIO(payload))
    if raw.dtype != np.uint16 or raw.shape != frame.shape:
        raise ValueError("Input format changed after scan")
    effective = raw if frame.alignment == "right" else np.right_shift(raw, 16 - frame.bit_depth)
    if np.any(effective > (1 << frame.bit_depth) - 1):
        raise ValueError("RAW DN exceeds declared effective range")
    return effective.astype(np.float32), digest


def fuse(group: Group, *, correction: Correction | None = None,
         check_cancel: Callable[[], None] = lambda: None,
         step: Callable[[int, str], None] = lambda *_: None) -> Fusion:
    if group.problem:
        raise ValueError(group.problem)
    correction = correction or NoCorrection()
    shape = group.frames[0].shape
    pixels = shape[0] * shape[1]
    numerator = np.zeros(shape, np.float64)
    denominator = np.zeros(shape, np.float64)
    provenance: list[dict] = []
    maximum = (1 << group.frames[0].bit_depth) - 1
    for exposure in group.exposures:
        check_cancel()
        frames = [f for f in group.frames if f.requested_exposure_ms == exposure]
        mean_dn = np.zeros(shape, np.float64)
        mean_rate = np.zeros(shape, np.float64)
        unsaturated_repeats = np.ones(shape, dtype=bool)
        # Every repeat is normalized by its own actual exposure, then averaged.
        for frame in frames:
            check_cancel()
            signal, digest = load_signal(frame)
            mean_dn += signal / len(frames)
            unsaturated_repeats &= signal < maximum * .98
            corrected = np.asarray(correction.apply(signal, frame), dtype=np.float64)
            if corrected.shape != shape or not np.all(np.isfinite(corrected)):
                raise ValueError("Invalid correction output")
            mean_rate += corrected / (frame.exposure_ms / 1000.0) / len(frames)
            provenance.append({"path": str(frame.path), "sha256": digest,
                               "metadata_path": str(frame.metadata_path) if frame.metadata_path else None,
                               "metadata_sha256": hashlib.sha256(frame.metadata_bytes).hexdigest() if frame.metadata_bytes else None,
                               "actual_exposure_ms": frame.exposure_ms,
                               "requested_exposure_ms": frame.requested_exposure_ms,
                               "warnings": list(frame.warnings), "metadata": frame.metadata})
            check_cancel()
            step(pixels, "read")
        # Engineering display weights, not a calibrated noise model.
        fraction = mean_dn / maximum
        weights = np.maximum(0, np.minimum(fraction - .005, .98 - fraction))
        weights[~unsaturated_repeats] = 0
        weights[~np.isfinite(mean_rate)] = 0
        numerator += mean_rate * weights
        denominator += weights
    check_cancel()
    valid = denominator > 0
    if not np.any(valid):
        raise ValueError("No usable pixels: all exposures are dark or near saturation")
    image = np.full(shape, np.nan, dtype=np.float32)
    with np.errstate(over="ignore", invalid="ignore"):
        np.divide(numerator, denominator, out=image, where=valid)
    valid &= np.isfinite(image)
    image[~valid] = np.nan
    if not np.any(valid):
        raise ValueError("No finite float32 HDR pixels")
    step(pixels, "fuse")
    return Fusion(image, valid, provenance, correction.describe())


def tone_map(image: np.ndarray, valid: np.ndarray, settings: DisplaySettings) -> tuple[np.ndarray, dict]:
    settings.validate()
    values = image[valid]
    positive = values[values > 0]
    white = float(np.percentile(positive, 99.8)) if positive.size else 1.0
    white = max(white, np.finfo(np.float32).tiny)
    normalized = np.zeros(image.shape, np.float32)
    normalized[valid] = np.clip(image[valid] / white, 0, 1)
    mapped = np.log1p(normalized * settings.compression) / math.log1p(settings.compression)
    mapped = np.power(mapped, 1 / settings.gamma)
    return np.rint(mapped * 65535).astype(np.uint16), {
        "method": "per_group_log_white_percentile", "white_percentile": 99.8,
        "white_value": white, "gamma": settings.gamma, "compression": settings.compression,
        "invalid_pixels_displayed_as": 0, "cross_group_brightness_comparable": False,
    }
