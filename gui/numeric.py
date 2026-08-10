from __future__ import annotations

"""Deterministic numeric boundaries for recipes and SCPI commands."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from typing import Any


RECIPE_QUANTUM = Decimal("0.000000001")
SCPI_QUANTUM = Decimal("0.000000001")


def decimal_from_number(value: float | int | str | Decimal) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"Numeric value must be finite: {value!r}")
    return result


def quantize_number(value: float | int | str | Decimal, quantum: Decimal = RECIPE_QUANTUM) -> float:
    return float(decimal_from_number(value).quantize(quantum, rounding=ROUND_HALF_UP))


def format_scpi_number(value: float | int | str | Decimal) -> str:
    """Render a finite SCPI number without binary-float display artefacts."""
    rounded = decimal_from_number(value).quantize(SCPI_QUANTUM, rounding=ROUND_HALF_UP)
    text = format(rounded, "f").rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def normalize_json_numbers(value: Any) -> Any:
    """Recursively quantize finite floats before recipe JSON serialization."""
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Recipe values must be finite")
        return quantize_number(value)
    if isinstance(value, dict):
        return {key: normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json_numbers(item) for item in value]
    return value
