from __future__ import annotations

from enum import Enum

from core.i18n import tr


# IUA8300KMB / IMX585 official exposure specification.
OFFICIAL_EXPOSURE_MIN_US = 30
OFFICIAL_EXPOSURE_MAX_US = 15_000_000


def validate_official_exposure_us(exposure_us: int) -> int:
    value = int(exposure_us)
    if not OFFICIAL_EXPOSURE_MIN_US <= value <= OFFICIAL_EXPOSURE_MAX_US:
        raise ValueError(
            "Exposure must be within the official IUA8300KMB range "
            f"{OFFICIAL_EXPOSURE_MIN_US}–{OFFICIAL_EXPOSURE_MAX_US} us; "
            f"got {value} us"
        )
    return value


def constrained_exposure_range_us(
    camera_range: tuple[int, int, int] | tuple[int, int] | None,
) -> tuple[int, int] | None:
    """Intersect an SDK range with the camera model's official limits."""

    if camera_range is None:
        return None
    low = max(OFFICIAL_EXPOSURE_MIN_US, int(camera_range[0]))
    high = min(OFFICIAL_EXPOSURE_MAX_US, int(camera_range[1]))
    return (low, high) if low <= high else None


class ExposureMode(str, Enum):
    """User-selectable exposure modes with canonical persisted values."""

    CONTINUOUS_AUTO = "continuous_auto"
    MANUAL = "manual"

    @property
    def label(self) -> str:
        return {
            ExposureMode.CONTINUOUS_AUTO: tr("camera.exposure_mode_continuous_auto"),
            ExposureMode.MANUAL: tr("camera.exposure_mode_manual"),
        }[self]
