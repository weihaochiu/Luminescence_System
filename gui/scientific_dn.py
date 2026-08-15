from __future__ import annotations

"""Interpret scientific camera containers without changing their raw values."""

import numpy as np


VALID_RAW_VALUE_ALIGNMENTS = frozenset({"right", "left", "unknown"})


def effective_dn_max(sensor_bit_depth: int) -> int:
    """Return the largest Effective DN represented by ``sensor_bit_depth``."""

    bit_depth = int(sensor_bit_depth)
    if not 1 <= bit_depth <= 16:
        raise ValueError("SensorBitDepth must be between 1 and 16")
    return (1 << bit_depth) - 1


def _validated_source(
    scientific: np.ndarray,
    sensor_bit_depth: int,
    container_bit_depth: int,
    raw_value_alignment: str,
) -> tuple[np.ndarray, int, int, str]:
    source = np.asarray(scientific)
    sensor_bits = int(sensor_bit_depth)
    container_bits = int(container_bit_depth)
    alignment = str(raw_value_alignment).strip().lower()
    if source.dtype != np.uint16:
        raise TypeError("Scientific DN source must be a uint16 ndarray")
    if source.ndim != 2:
        raise ValueError("Scientific DN source must be an H×W array")
    if not 1 <= sensor_bits <= container_bits <= 16:
        raise ValueError(
            "Bit depths must satisfy 1 <= SensorBitDepth <= ContainerBitDepth <= 16"
        )
    if alignment not in VALID_RAW_VALUE_ALIGNMENTS:
        raise ValueError("RawValueAlignment must be 'right', 'left', or 'unknown'")
    if alignment == "unknown":
        raise ValueError("RawValueAlignment is unknown")
    return source, sensor_bits, container_bits, alignment


def scientific_to_effective_dn(
    scientific: np.ndarray,
    sensor_bit_depth: int,
    container_bit_depth: int,
    raw_value_alignment: str,
) -> np.ndarray:
    """Return a derived Effective-DN array; never mutate or alias the source."""

    source, sensor_bits, container_bits, alignment = _validated_source(
        scientific,
        sensor_bit_depth,
        container_bit_depth,
        raw_value_alignment,
    )
    if alignment == "right":
        effective = source.copy()
    else:
        effective = np.right_shift(source, container_bits - sensor_bits)
    maximum = effective_dn_max(sensor_bits)
    if effective.size and int(effective.max()) > maximum:
        raise ValueError("Scientific container contains values outside Effective DN range")
    return effective


def mean_effective_dn(
    scientific: np.ndarray,
    sensor_bit_depth: int,
    container_bit_depth: int,
    raw_value_alignment: str,
) -> float:
    """Compute whole-frame mean Effective DN without a float64 image copy."""

    source, sensor_bits, container_bits, alignment = _validated_source(
        scientific,
        sensor_bit_depth,
        container_bit_depth,
        raw_value_alignment,
    )
    if source.size == 0:
        raise ValueError("Scientific DN source cannot be empty")
    if alignment == "right":
        maximum = effective_dn_max(sensor_bits)
        if int(source.max()) > maximum:
            raise ValueError("Scientific container contains values outside Effective DN range")
        return float(np.mean(source, dtype=np.float64))
    effective = np.right_shift(source, container_bits - sensor_bits)
    return float(np.mean(effective, dtype=np.float64))


def effective_dn_fraction(mean_dn: float, maximum_dn: int) -> float:
    """Return a 0–1 signal fraction for an Effective-DN mean."""

    maximum = int(maximum_dn)
    if maximum <= 0:
        raise ValueError("EffectiveDNMax must be positive")
    return min(max(float(mean_dn) / maximum, 0.0), 1.0)


def effective_dn_to_uint8(
    scientific: np.ndarray,
    sensor_bit_depth: int,
    container_bit_depth: int,
    raw_value_alignment: str,
) -> np.ndarray:
    """Map Effective DN linearly to an 8-bit visualization copy."""

    source, sensor_bits, container_bits, alignment = _validated_source(
        scientific,
        sensor_bit_depth,
        container_bit_depth,
        raw_value_alignment,
    )
    maximum = effective_dn_max(sensor_bits)
    if alignment == "right":
        if source.size and int(source.max()) > maximum:
            raise ValueError("Scientific container contains values outside Effective DN range")
        effective = source
    else:
        effective = np.right_shift(source, container_bits - sensor_bits)
    # Integer arithmetic avoids a full-frame float64 allocation while retaining
    # round-to-nearest behavior. The source is read-only and the returned uint8
    # array owns its visualization data.
    scaled = effective.astype(np.uint32) * 255
    return ((scaled + maximum // 2) // maximum).astype(np.uint8)
