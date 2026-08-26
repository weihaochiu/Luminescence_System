from __future__ import annotations

import unittest

import cv2
import numpy as np

from core.calibration.ruler_rectifier import RectificationResult
from core.calibration.tick_detector import TickDetector


class TickDetectorTests(unittest.TestCase):
    def test_residual_slanted_top_ticks_are_detected(self) -> None:
        image = np.full((240, 900), 225, dtype=np.uint8)
        cv2.line(image, (0, 238), (899, 238), 25, 3)
        for index, x in enumerate(range(25, 880, 35)):
            length = 100 if index % 10 == 0 else (78 if index % 5 == 0 else 58)
            cv2.line(image, (x, 0), (x + 13, length), 20, 4)
        identity = np.eye(3, dtype=np.float64)
        rectification = RectificationResult(
            True,
            image,
            identity,
            identity,
            (image.shape[1], image.shape[0]),
        )
        result = TickDetector().detect(rectification)
        self.assertGreaterEqual(len(result.ticks), 20)
        positions = [tick.rectified_position_px for tick in result.ticks]
        self.assertLess(max(np.diff(sorted(positions))), 55.0)


if __name__ == "__main__":
    unittest.main()
