from __future__ import annotations

import unittest

import numpy as np

from core.calibration.models import DetectedNumber, TickMark
from core.calibration.scale_solver import ScaleSolver

from .helpers import synthetic_ticks


class RobustScaleSolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.solver = ScaleSolver()

    def solve(self, ticks: list[TickMark], numbers: list[DetectedNumber] | None = None):
        detection, _ = synthetic_ticks()
        return self.solver.solve(
            detection,
            ticks,
            numbers or [],
            input_resolution=(8000, 1000),
            ocr_available=bool(numbers),
            ocr_diagnostic="test",
        )

    def test_perfect_ticks(self) -> None:
        _, ticks = synthetic_ticks()
        result = self.solve(ticks)
        self.assertTrue(result.success, result.failure_reasons)
        self.assertAlmostEqual(200.0, result.pixels_per_mm, places=6)
        self.assertAlmostEqual(30.0, result.calibration_span_mm)

    def test_missing_ticks_use_long_span(self) -> None:
        _, ticks = synthetic_ticks(missing={4, 17, 24})
        result = self.solve(ticks)
        self.assertTrue(result.success, result.failure_reasons)
        self.assertAlmostEqual(200.0, result.pixels_per_mm, places=5)
        self.assertGreaterEqual(result.calibration_span_mm, 29.0)

    def test_false_tick_is_rejected(self) -> None:
        _, ticks = synthetic_ticks()
        ticks.append(TickMark(877.0, (877.0, 100.0), 22.0))
        result = self.solve(ticks)
        self.assertTrue(result.success, result.failure_reasons)
        self.assertAlmostEqual(200.0, result.pixels_per_mm, places=4)
        self.assertGreaterEqual(len(result.rejected_ticks), 1)

    def test_noisy_ticks_remain_stable(self) -> None:
        noise = np.random.default_rng(42).normal(0.0, 1.2, 31)
        _, ticks = synthetic_ticks(noise=noise)
        result = self.solve(ticks)
        self.assertTrue(result.success, result.failure_reasons)
        self.assertAlmostEqual(200.0, result.pixels_per_mm, delta=0.2)
        self.assertLess(result.fit_error_percent, 2.0)

    def test_ocr_sequence_passes_geometry_validation(self) -> None:
        _, ticks = synthetic_ticks()
        numbers = [
            DetectedNumber(value, str(value), (round(100 + index * 2000), 80, 30, 30), (100 + index * 2000, 95), 90)
            for index, value in enumerate((4, 5, 6, 7))
        ]
        result = self.solve(ticks, numbers)
        self.assertTrue(result.ocr_usable)
        self.assertTrue(all(item.accepted for item in result.detected_numbers))

    def test_one_ocr_outlier_is_rejected_and_correction_recorded(self) -> None:
        _, ticks = synthetic_ticks()
        numbers = [
            DetectedNumber(value, str(value), (round(100 + index * 2000), 80, 30, 30), (100 + index * 2000, 95), 90)
            for index, value in enumerate((4, 5, 9, 7))
        ]
        result = self.solve(ticks, numbers)
        outlier = result.detected_numbers[2]
        self.assertFalse(outlier.accepted)
        self.assertEqual(6, outlier.corrected_value)
        self.assertEqual("ocr_geometry_inconsistency", outlier.rejection_reason)

    def test_two_digit_sequence_is_not_limited_to_fifteen(self) -> None:
        _, ticks = synthetic_ticks()
        numbers = [
            DetectedNumber(value, str(value), (round(100 + index * 2000), 80, 40, 30), (100 + index * 2000, 95), 90)
            for index, value in enumerate((14, 15, 16, 17))
        ]
        result = self.solve(ticks, numbers)
        self.assertTrue(result.ocr_usable)
        self.assertEqual([14, 15, 16, 17], [item.value for item in result.detected_numbers])

    def test_only_one_major_tick_remains_a_safe_geometry_result(self) -> None:
        _, ticks = synthetic_ticks()
        for tick in ticks[1:]:
            tick.kind = "minor"
        result = self.solve(ticks)
        self.assertTrue(result.success, result.failure_reasons)
        self.assertEqual(1, len(result.detected_major_ticks))
        self.assertFalse(result.ocr_usable)

    def test_failure_inputs_do_not_crash(self) -> None:
        detection, ticks = synthetic_ticks(count=1)
        cases = ([], ticks)
        for case in cases:
            with self.subTest(count=len(case)):
                result = self.solver.solve(
                    detection,
                    case,
                    [],
                    input_resolution=(1000, 700),
                    ocr_available=False,
                    ocr_diagnostic="unavailable",
                )
                self.assertFalse(result.success)
                self.assertTrue(result.failure_reasons)


if __name__ == "__main__":
    unittest.main()
