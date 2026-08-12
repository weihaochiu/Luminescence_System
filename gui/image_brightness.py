from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage


def equivalent_brightness_8bit(image: QImage) -> int | None:
    """Return whole-frame mean luminance on a 0–255 scale.

    This deliberately lives outside the GUI so a future Sample ROI or AE ROI
    implementation can replace the sampling policy without changing widgets.
    """

    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        return None

    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    height, width = rgb.height(), rgb.width()
    rows = np.frombuffer(rgb.bits(), dtype=np.uint8).reshape(height, rgb.bytesPerLine())
    pixels = rows[:, : width * 3].reshape(height, width, 3)
    # Sample a regular whole-frame grid so status refresh does not compete with
    # the preview path on high-resolution sensors.
    step = max(1, max(width, height) // 512)
    sample = pixels[::step, ::step].astype(np.float32)
    # Rec. 709 luma coefficients are used only for the 8-bit preview status.
    luminance = (
        sample[:, :, 0] * 0.2126
        + sample[:, :, 1] * 0.7152
        + sample[:, :, 2] * 0.0722
    )
    return int(np.clip(np.rint(np.mean(luminance)), 0, 255))
