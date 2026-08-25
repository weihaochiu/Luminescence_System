from __future__ import annotations

import builtins
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.calibration.digit_recognizer import TesseractDigitRecognizer
from core.calibration.models import CalibrationResult
from core.i18n import i18n, set_language
from tools.ruler_scale_calibration_tester.repeatability import (
    DuplicateSourceError,
    RepeatabilitySession,
)
from tools.ruler_scale_calibration_tester.source import FrameCaptureState


class FrameCaptureStateTests(unittest.TestCase):
    def test_later_live_frames_do_not_replace_frozen_frame_100(self) -> None:
        state = FrameCaptureState()
        state.update_live(np.full((4, 5), 100, dtype=np.uint16), 100)
        captured, source = state.capture_camera(
            "RisingCam", captured_at="2026-08-25T12:00:00.000+08:00"
        )
        state.update_live(np.full((4, 5), 101, dtype=np.uint16), 101)
        state.update_live(np.full((4, 5), 102, dtype=np.uint16), 102)
        self.assertTrue(np.all(captured == 100))
        self.assertTrue(np.all(state.captured_frame == 100))
        self.assertTrue(np.all(state.latest_frame == 102))
        self.assertEqual(100, source.frame_sequence)
        self.assertIn("frame=100", source.source_identity)


class RepeatabilitySessionTests(unittest.TestCase):
    @staticmethod
    def result(identity: str, pixels_per_mm: float = 200.0) -> CalibrationResult:
        return CalibrationResult(
            success=True,
            pixels_per_mm=pixels_per_mm,
            um_per_pixel=1000.0 / pixels_per_mm,
            ruler_angle_deg=1.25,
            fit_error_percent=0.4,
            quality_score=94.0,
            verification_mode="tick_hierarchy_verified",
            ocr_usable=False,
            source_type="camera",
            source_identity=identity,
            captured_frame_sequence=100,
            timestamp="2026-08-25T12:00:00+08:00",
        )

    def test_run_is_not_added_until_explicit_add_and_duplicate_is_rejected(self) -> None:
        session = RepeatabilitySession()
        result = self.result("camera|test|frame=100|captured=now")
        self.assertEqual([], session.runs)
        session.add_result(result)
        self.assertEqual(1, len(session.runs))
        with self.assertRaisesRegex(
            DuplicateSourceError,
            "This captured frame has already been added to this repeatability session",
        ):
            session.add_result(result)

    def test_csv_contains_runs_and_summary(self) -> None:
        session = RepeatabilitySession()
        session.add_result(self.result("camera|one", 199.0))
        session.add_result(self.result("camera|two", 201.0))
        with tempfile.TemporaryDirectory() as directory:
            path = session.export_csv(Path(directory) / "repeatability.csv")
            text = path.read_text(encoding="utf-8")
        self.assertIn("source_identity", text)
        self.assertIn("run,timestamp", text)
        self.assertIn("angle_deg", text)
        self.assertIn("verification_mode", text)
        self.assertIn("mean_pixels_per_mm,200.0", text)
        self.assertIn("sd_pixels_per_mm", text)
        self.assertIn("cv_percent", text)
        self.assertIn("max_deviation_percent", text)


class OCRDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_language = i18n.language
        set_language("en-US", persist=False)

    def tearDown(self) -> None:
        set_language(self.original_language, persist=False)

    def test_python_package_missing_diagnostic(self) -> None:
        real_import = builtins.__import__

        def blocked(name: str, *args: object, **kwargs: object):
            if name == "pytesseract":
                raise ImportError("intentionally absent")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocked):
            availability = TesseractDigitRecognizer().availability()
        self.assertFalse(availability.available)
        self.assertEqual(
            "OCR unavailable:\npytesseract Python package is not installed.",
            availability.diagnostic,
        )

    def test_executable_missing_diagnostic(self) -> None:
        fake = SimpleNamespace(
            pytesseract=SimpleNamespace(tesseract_cmd="tesseract"),
            get_tesseract_version=lambda: "never",
        )
        with patch.dict("sys.modules", {"pytesseract": fake}), patch(
            "core.calibration.digit_recognizer.shutil.which", return_value=None
        ):
            availability = TesseractDigitRecognizer().availability()
        self.assertFalse(availability.available)
        self.assertEqual(
            "OCR unavailable:\nTesseract executable was not found.",
            availability.diagnostic,
        )

    def test_available_diagnostic_reports_version(self) -> None:
        fake = SimpleNamespace(
            pytesseract=SimpleNamespace(tesseract_cmd="tesseract"),
            get_tesseract_version=lambda: "5.4.1",
        )
        with patch.dict("sys.modules", {"pytesseract": fake}), patch(
            "core.calibration.digit_recognizer.shutil.which", return_value="C:/Tesseract/tesseract.exe"
        ):
            availability = TesseractDigitRecognizer().availability()
        self.assertTrue(availability.available)
        self.assertEqual("OCR available:\nTesseract 5.4.1", availability.diagnostic)


if __name__ == "__main__":
    unittest.main()
