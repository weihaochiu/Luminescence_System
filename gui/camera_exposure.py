from __future__ import annotations

from enum import Enum


# Fixed RisingCam SDK target for operator-facing Live View auto exposure.
# This is not PreviewBrightness8bit, SensorBitDepth, ContainerBitDepth, or
# ScientificDN, and it must not be used as a Recipe exposure/gain setting.
DEFAULT_AUTO_EXPOSURE_TARGET = 120
PREVIEW_BRIGHTNESS_8BIT_MAX = 255


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
