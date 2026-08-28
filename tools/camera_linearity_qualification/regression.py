from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import numpy as np


@dataclass(frozen=True)
class RegressionResult:
    slope: float
    intercept: float
    r2: float
    adjusted_r2: float
    rmse: float
    normalized_rmse: float
    max_absolute_residual_percent: float
    median_absolute_residual_percent: float
    p95_residual_percent: float
    residuals: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def linear_regression(x: np.ndarray, y: np.ndarray) -> RegressionResult:
    independent = np.asarray(x, dtype=np.float64)
    dependent = np.asarray(y, dtype=np.float64)
    if independent.ndim != 1 or dependent.ndim != 1 or independent.size != dependent.size:
        raise ValueError("Regression inputs must be equal-length one-dimensional arrays")
    if independent.size < 2 or np.ptp(independent) <= 0:
        raise ValueError("Regression requires at least two distinct x values")
    design = np.column_stack((independent, np.ones_like(independent)))
    slope, intercept = np.linalg.lstsq(design, dependent, rcond=None)[0]
    predicted = slope * independent + intercept
    residuals = dependent - predicted
    ss_res = float(np.sum(residuals ** 2))
    ss_total = float(np.sum((dependent - np.mean(dependent)) ** 2))
    r2 = 1.0 - ss_res / ss_total if ss_total > 0 else (1.0 if ss_res == 0 else 0.0)
    n = independent.size
    adjusted = 1.0 - (1.0 - r2) * (n - 1) / (n - 2) if n > 2 else r2
    rmse = math.sqrt(ss_res / n)
    span = float(np.ptp(dependent))
    normalized = rmse / span if span > 0 else math.inf
    denominator = np.maximum(np.abs(predicted), max(1e-12, span * 0.01))
    residual_percent = np.abs(residuals) / denominator * 100.0
    return RegressionResult(
        float(slope), float(intercept), float(r2), float(adjusted), float(rmse),
        float(normalized), float(np.max(residual_percent)),
        float(np.median(residual_percent)), float(np.percentile(residual_percent, 95)),
        tuple(float(item) for item in residuals),
    )


def is_monotonic(values: np.ndarray, tolerance_percent: float = 0.0) -> bool:
    data = np.asarray(values, dtype=np.float64)
    if data.size < 2:
        return True
    tolerance = np.maximum(np.abs(data[:-1]) * float(tolerance_percent) / 100.0, 1e-9)
    return bool(np.all(np.diff(data) >= -tolerance))
