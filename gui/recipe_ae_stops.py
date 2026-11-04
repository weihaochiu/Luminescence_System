from __future__ import annotations

"""Exposure-only AE bracketing, expressed in stops relative to convergence."""

import math
from collections.abc import Sequence

from .camera_exposure import OFFICIAL_EXPOSURE_MIN_US, OFFICIAL_EXPOSURE_MAX_US


def stop_factors(stops: object) -> tuple[float, ...]:
    if (not isinstance(stops, (list, tuple)) or not 1 <= len(stops) <= 33
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) or abs(value) > 12 for value in stops)
            or len(set(stops)) != len(stops)):
        raise ValueError("Stop list requires 1–33 unique finite numbers between -12 and +12")
    return tuple(2.0 ** value for value in stops)


def baseline_range_us(stops: object, maximum_ms: float,
                      hardware_range: Sequence[float] | None = None) -> tuple[int, int]:
    factors = stop_factors(stops)
    low, high = OFFICIAL_EXPOSURE_MIN_US, OFFICIAL_EXPOSURE_MAX_US
    if hardware_range is not None:
        low, high = max(low, hardware_range[0]), min(high, hardware_range[1])
    ceiling = maximum_ms * 1000
    if not low <= ceiling <= high:
        raise ValueError("AE exposure ceiling is outside camera capabilities")
    minimum = math.ceil(low / min(1.0, *factors))
    maximum = math.floor(ceiling / max(1.0, *factors))
    if minimum > maximum:
        raise ValueError("Stop list leaves no valid AE baseline exposure range")
    return minimum, maximum


def bracket_exposures_us(baseline_us: int, stops: object) -> tuple[int, ...]:
    exposures = tuple(round(baseline_us * factor) for factor in stop_factors(stops))
    if len(set(exposures)) != len(exposures):
        raise ValueError("Stop entries resolve to duplicate exposures at camera microsecond precision")
    return exposures


def upper_exposures_ms(stops: object, maximum_ms: float) -> tuple[float, ...]:
    _minimum, maximum = baseline_range_us(stops, maximum_ms)
    return tuple(value / 1000.0 for value in bracket_exposures_us(maximum, stops))
