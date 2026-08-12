from __future__ import annotations

from enum import Enum


AUTO_TARGET_MIN = 16
AUTO_TARGET_MAX = 220


class ExposureMode(str, Enum):
    """User-selectable exposure modes and their Traditional Chinese labels."""

    CONTINUOUS_AUTO = "continuous_auto"
    MANUAL = "manual"

    @property
    def label(self) -> str:
        return {
            ExposureMode.CONTINUOUS_AUTO: "持續自動曝光",
            ExposureMode.MANUAL: "手動曝光",
        }[self]


def validate_auto_target(target: int) -> int:
    """Return a valid SDK AE target without silently changing invalid input."""

    value = int(target)
    if not AUTO_TARGET_MIN <= value <= AUTO_TARGET_MAX:
        raise ValueError(
            f"影像亮度目標允許範圍為 {AUTO_TARGET_MIN}–{AUTO_TARGET_MAX} /255。"
        )
    return value
