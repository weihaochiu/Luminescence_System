from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import cv2
import tifffile

from core.calibration.digit_recognizer import UnavailableDigitRecognizer
from core.calibration.image_utils import axis_angle_error
from core.calibration.ruler_detector import RulerDetector
from core.calibration.service import CalibrationService
from tools.ruler_scale_calibration_tester.batch import run_batch

from .helpers import synthetic_ruler


class CalibrationPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = CalibrationService(digit_recognizer=UnavailableDigitRecognizer("test unavailable"))

    def test_synthetic_orientations(self) -> None:
        detector = RulerDetector()
        for angle in (0, 30, 90, 135, 180, 270):
            with self.subTest(angle=angle):
                image = synthetic_ruler(angle)
                detection, _ = detector.detect(image)
                self.assertTrue(detection.success, detection)
                self.assertLessEqual(axis_angle_error(detection.angle_deg, angle), 1.0)
                result = self.service.analyze(image, input_source=f"synthetic:{angle}")
                self.assertTrue(result.success, result.failure_reasons)
                expected = 20.0 if angle in (0, 180) else 15.0
                self.assertAlmostEqual(expected, result.pixels_per_mm, delta=0.4)

    def test_no_ruler_does_not_crash(self) -> None:
        image = np.full((500, 700), 128, dtype=np.uint8)
        result = self.service.analyze(image)
        self.assertFalse(result.success)
        self.assertIn("ruler_not_found", result.failure_reasons)
        self.assertIn("final_overlay", result.debug_images)

    def test_mild_perspective_is_rectified_and_fitted_in_original_plane(self) -> None:
        source = np.float32(((0, 0), (999, 0), (999, 699), (0, 699)))
        destination = np.float32(((8, 4), (991, 0), (999, 699), (0, 692)))
        warped = cv2.warpPerspective(
            synthetic_ruler(),
            cv2.getPerspectiveTransform(source, destination),
            (1000, 700),
            borderValue=35,
        )
        result = self.service.analyze(warped, input_source="synthetic:perspective")
        self.assertTrue(result.success, result.failure_reasons)
        self.assertEqual("original_image_pixels", result.coordinate_system)
        self.assertAlmostEqual(20.0, result.pixels_per_mm, delta=0.5)

    def test_ruler_without_ticks_does_not_crash(self) -> None:
        image = np.full((500, 800), 30, dtype=np.uint8)
        image[190:310, 80:720] = 210
        result = self.service.analyze(image)
        self.assertFalse(result.success)
        self.assertTrue(result.failure_reasons)

    def test_ocr_unavailable_is_explicit_but_geometry_can_pass(self) -> None:
        result = self.service.analyze(synthetic_ruler())
        self.assertTrue(result.success, result.failure_reasons)
        self.assertFalse(result.ocr_available)
        self.assertIn("ocr_unavailable", result.warnings)
        self.assertIn("test unavailable", result.ocr_diagnostic)

    def test_debug_package_contains_evidence_and_json(self) -> None:
        raw = synthetic_ruler().astype(np.uint16) * 200
        raw[0, 0] = 52341
        expected_raw = raw.copy()
        result = self.service.analyze(
            raw,
            input_source="camera:test",
            source_type="camera",
            source_identity="camera|test|frame=100|captured=now",
            captured_frame_sequence=100,
        )
        raw.fill(0)
        with tempfile.TemporaryDirectory() as directory:
            output = self.service.save_debug_package(result, directory)
            exact = tifffile.imread(output / "raw_input.tiff")
            self.assertEqual(np.uint16, exact.dtype)
            self.assertTrue(np.array_equal(expected_raw, exact))
            self.assertEqual(52341, int(exact.max()))
            self.assertTrue((output / "original_preview.png").is_file())
            self.assertTrue((output / "normalized.png").is_file())
            self.assertTrue((output / "ruler_candidates.png").is_file())
            self.assertTrue((output / "ruler_roi.png").is_file())
            self.assertTrue((output / "rectified.png").is_file())
            self.assertTrue((output / "threshold.png").is_file())
            self.assertTrue((output / "ticks_overlay.png").is_file())
            self.assertTrue((output / "ocr_overlay.png").is_file())
            self.assertTrue((output / "final_overlay.png").is_file())
            payload = (output / "result.json").read_text(encoding="utf-8")
            self.assertIn('"pixels_per_mm"', payload)
            self.assertIn('"input_dtype": "uint16"', payload)
            self.assertIn('"input_max": 52341', payload)
            self.assertIn('"periodic_pitch_px"', payload)
            self.assertIn('"physical_pitch_mm"', payload)
            self.assertIn('"verification_mode"', payload)
            self.assertIn('"pitch_hypotheses"', payload)
            self.assertIn('"source_identity": "camera|test|frame=100|captured=now"', payload)
            self.assertNotIn('"raw_input"', payload)
            self.assertIn('"coordinate_system": "original_image_pixels"', payload)

    def test_batch_offline_regression_entry(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.png"
            Image.fromarray(synthetic_ruler()).save(path)
            summary = run_batch(path)
            self.assertEqual(1, summary["images"])
            self.assertEqual(1, summary["ruler_detected"])
            self.assertEqual(1, summary["calibration_successful"])


if __name__ == "__main__":
    unittest.main()
