from __future__ import annotations

from enum import Enum

from core.i18n import tr


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
