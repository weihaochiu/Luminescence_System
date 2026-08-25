from __future__ import annotations

import unittest

from core.calibration.scale_solver import (
    pixels_per_mm_to_um_per_pixel,
    scale_bar_pixels,
    select_scale_bar,
)
from tools.ruler_scale_calibration_tester.repeatability import repeatability_summary


class ScaleMathTests(unittest.TestCase):
    def test_pixels_per_mm_conversion(self) -> None:
        self.assertEqual(5.0, pixels_per_mm_to_um_per_pixel(200.0))

    def test_scale_bar_math(self) -> None:
        self.assertEqual(400.0, scale_bar_pixels(2000.0, 5.0))

    def test_scale_bar_uses_one_two_five_series_and_target_range(self) -> None:
        selection = select_scale_bar(2000, 5.0)
        self.assertEqual(2000.0, selection.length_um)
        self.assertEqual(400.0, selection.rendered_length_px)
        self.assertEqual("2 mm", selection.label)

    def test_invalid_scale_is_rejected(self) -> None:
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pixels_per_mm_to_um_per_pixel(value)

    def test_repeatability_statistics(self) -> None:
        summary = repeatability_summary([199.0, 200.0, 201.0])
        self.assertEqual(3, summary["n"])
        self.assertEqual(200.0, summary["mean_pixels_per_mm"])
        self.assertEqual(1.0, summary["sd_pixels_per_mm"])
        self.assertAlmostEqual(0.5, float(summary["cv_percent"]))


if __name__ == "__main__":
    unittest.main()
