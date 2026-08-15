from __future__ import annotations

from enum import Enum


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
