from __future__ import annotations

import math
import statistics


def repeatability_summary(values: list[float]) -> dict[str, float | int | None]:
    finite = [float(value) for value in values if math.isfinite(float(value)) and float(value) > 0]
    if not finite:
        return {
            "n": 0,
            "mean_pixels_per_mm": None,
            "sd_pixels_per_mm": None,
            "cv_percent": None,
            "min_pixels_per_mm": None,
            "max_pixels_per_mm": None,
            "max_deviation_percent": None,
        }
    mean = statistics.fmean(finite)
    sd = statistics.stdev(finite) if len(finite) > 1 else 0.0
    max_deviation = max(abs(value - mean) for value in finite) / mean * 100.0
    return {
        "n": len(finite),
        "mean_pixels_per_mm": mean,
        "sd_pixels_per_mm": sd,
        "cv_percent": sd / mean * 100.0,
        "min_pixels_per_mm": min(finite),
        "max_pixels_per_mm": max(finite),
        "max_deviation_percent": max_deviation,
    }
