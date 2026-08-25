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
        self.assertAlmostEqual(200.0, result.periodic_pitch_px, places=6)
        self.assertEqual(1.0, result.physical_pitch_mm)
        self.assertEqual("tick_hierarchy_verified", result.verification_mode)
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
        self.assertEqual("ocr_verified", result.verification_mode)
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

    def test_only_one_major_tick_is_not_physically_verified(self) -> None:
        _, ticks = synthetic_ticks()
        for tick in ticks[1:]:
            tick.kind = "minor"
        result = self.solve(ticks)
        self.assertFalse(result.success)
        self.assertEqual(1, len(result.detected_major_ticks))
        self.assertFalse(result.ocr_usable)
        self.assertIn("ambiguous_physical_pitch", result.failure_reasons)

    def test_every_second_tick_does_not_create_400_px_per_mm_alias(self) -> None:
        _, ticks = synthetic_ticks(missing={index for index in range(31) if index % 2})
        result = self.solve(ticks)
        self.assertFalse(result.success)
        self.assertAlmostEqual(400.0, result.periodic_pitch_px, places=5)
        self.assertIsNone(result.pixels_per_mm)
        self.assertEqual("geometry_periodic_only", result.verification_mode)
        self.assertIn("ambiguous_physical_pitch", result.failure_reasons)

    def test_equal_length_false_medium_labels_cannot_verify_every_second_subset(self) -> None:
        _, ticks = synthetic_ticks(missing={index for index in range(31) if index % 2})
        long_ticks = [tick for tick in ticks if tick.length_px == 60.0]
        for index, tick in enumerate(long_ticks):
            tick.kind = "major" if index % 2 == 0 else "medium"
        result = self.solve(ticks)
        self.assertFalse(result.success)
        self.assertAlmostEqual(400.0, result.periodic_pitch_px, places=5)
        self.assertIn("ambiguous_physical_pitch", result.failure_reasons)

    def test_every_fifth_tick_does_not_create_1000_px_per_mm_alias(self) -> None:
        _, ticks = synthetic_ticks(missing={index for index in range(31) if index % 5})
        result = self.solve(ticks)
        self.assertFalse(result.success)
        self.assertAlmostEqual(1000.0, result.periodic_pitch_px, places=5)
        self.assertIsNone(result.pixels_per_mm)
        self.assertEqual({1.0, 2.0, 5.0, 10.0}, {
            item.physical_pitch_mm for item in result.pitch_hypotheses
        })

    def test_only_ten_mm_major_ticks_need_ocr_to_resolve_pitch(self) -> None:
        _, all_ticks = synthetic_ticks()
        ticks = [tick for index, tick in enumerate(all_ticks) if index % 10 == 0]
        no_ocr = self.solve([TickMark(**vars(tick)) for tick in ticks])
        self.assertFalse(no_ocr.success)
        self.assertIn("ambiguous_physical_pitch", no_ocr.failure_reasons)
        numbers = [
            DetectedNumber(
                value,
                str(value),
                (round(tick.rectified_position_px), 80, 30, 30),
                (tick.rectified_position_px, 95),
                90,
            )
            for value, tick in zip((3, 4, 5), ticks)
        ]
        result = self.solve(ticks, numbers)
        self.assertTrue(result.success, result.failure_reasons)
        self.assertAlmostEqual(200.0, result.pixels_per_mm, places=5)
        self.assertEqual(10.0, result.physical_pitch_mm)
        self.assertEqual("ocr_verified", result.verification_mode)

    def test_random_missing_ticks_keep_true_scale(self) -> None:
        rng = np.random.default_rng(20260825)
        removable = [index for index in range(31) if index % 5]
        missing = set(rng.choice(removable, size=7, replace=False).tolist())
        _, ticks = synthetic_ticks(missing=missing)
        result = self.solve(ticks)
        self.assertTrue(result.success, result.failure_reasons)
        self.assertAlmostEqual(200.0, result.pixels_per_mm, delta=0.2)

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
                self.assertEqual("unverified", result.verification_mode)


if __name__ == "__main__":
    unittest.main()
