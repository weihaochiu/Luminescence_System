from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from core.calibration.digit_recognizer import UnavailableDigitRecognizer
from core.calibration.service import CalibrationService
from tools.ruler_scale_calibration_tester.analyze_real_dataset import analyze_dataset

from .helpers import synthetic_ruler


class RealDatasetAnalyzerTests(unittest.TestCase):
    def test_writes_reports_contact_sheet_and_debug_artifacts(self) -> None:
        service = CalibrationService(
            digit_recognizer=UnavailableDigitRecognizer("test unavailable")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            output = root / "output"
            source.mkdir()
            image_path = source / "sample.png"
            Image.fromarray(synthetic_ruler()).save(image_path)
            (source / "ground_truth.csv").write_text(
                "filename,roi_correct,notes\nsample.png,true,synthetic review\n",
                encoding="utf-8",
            )

            payload = analyze_dataset(source, output, service=service)

            self.assertEqual(1, payload["summary"]["images"])
            self.assertEqual(1, payload["summary"]["correct_roi"])
            self.assertEqual(1, payload["summary"]["final_pass"])
            self.assertTrue((output / "results.csv").is_file())
            self.assertTrue((output / "results.json").is_file())
            self.assertTrue((output / "summary.txt").is_file())
            self.assertTrue((output / "contact_sheet.png").is_file())
            self.assertTrue((output / "artifacts" / "sample" / "rectified.png").is_file())
            saved = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertEqual("sample.png", saved["records"][0]["filename"])


if __name__ == "__main__":
    unittest.main()
