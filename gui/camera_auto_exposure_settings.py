from __future__ import annotations

"""Persistent operator settings for Effective-DN software auto exposure."""

from typing import Any


AUTO_EXPOSURE_TARGET_PERCENT_KEY = "camera/auto_exposure_target_percent"
AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS = (20, 30, 40, 50, 60, 70, 80)
DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT = 50


def validate_auto_exposure_target_percent(value: int) -> int:
    percent = int(value)
    if percent not in AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS:
        raise ValueError(
            "Auto exposure target percent must be one of "
            + ", ".join(str(item) for item in AUTO_EXPOSURE_TARGET_PERCENT_OPTIONS)
        )
    return percent


def load_auto_exposure_target_percent(settings: Any) -> int:
    try:
        return validate_auto_exposure_target_percent(
            int(settings.value(
                AUTO_EXPOSURE_TARGET_PERCENT_KEY,
                DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT,
            ))
        )
    except (TypeError, ValueError):
        return DEFAULT_AUTO_EXPOSURE_TARGET_PERCENT


def save_auto_exposure_target_percent(settings: Any, value: int) -> None:
    settings.setValue(
        AUTO_EXPOSURE_TARGET_PERCENT_KEY,
        validate_auto_exposure_target_percent(value),
    )


def target_effective_dn(maximum_dn: int, target_percent: int) -> int:
    maximum = int(maximum_dn)
    if maximum <= 0:
        raise ValueError("EffectiveDNMax must be positive")
    percent = validate_auto_exposure_target_percent(target_percent)
    return round(maximum * (percent / 100.0))
