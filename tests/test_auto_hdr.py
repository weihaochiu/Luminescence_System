from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from risingcam_gui.auto_hdr import (
    ExposurePlan,
    capture_exposure_sequence,
    merge_quantitative_hdr,
    save_hdr_capture_set,
)
from risingcam_gui.hdr_settings import HDRSystemSettings


class AutoHDRTests(unittest.TestCase):
    def test_merge_preserves_linear_dn_per_second(self) -> None:
        frames = [
            np.array([[[20, 100], [200, 250]], [[20, 100], [200, 250]]], dtype=np.uint8),
            np.array([[[200, 255], [255, 255]], [[200, 255], [255, 255]]], dtype=np.uint8),
        ]
        dark = [
            np.zeros((3, 2, 2), dtype=np.uint8),
            np.zeros((3, 2, 2), dtype=np.uint8),
        ]
        result = merge_quantitative_hdr(frames, dark, [100, 1000], low_signal_sigma=1)
        self.assertAlmostEqual(200.0, float(result.linear_dn_per_s[0, 0]))
        self.assertAlmostEqual(1000.0, float(result.linear_dn_per_s[0, 1]))

    def test_capture_set_saves_every_source_exposure_and_dark(self) -> None:
        frames = [
            np.full((2, 3, 5), 10, dtype=np.uint8),
            np.full((2, 3, 5), 20, dtype=np.uint8),
        ]
        dark = [
            np.full((3, 3, 5), 1, dtype=np.uint8),
            np.full((3, 3, 5), 2, dtype=np.uint8),
        ]
        result = merge_quantitative_hdr(frames, dark, [100, 1000], low_signal_sigma=1)
        with tempfile.TemporaryDirectory() as directory:
            products = save_hdr_capture_set(
                Path(directory) / "EL_100mA",
                frames,
                dark,
                result,
                gain_percent=100,
                hdr_settings_snapshot=HDRSystemSettings().snapshot(),
                execution_summary={
                    "planned_exposures_ms": [100, 1000],
                    "captured_exposures_ms": [100, 1000],
                    "valid_exposures_ms": [100, 1000],
                    "excluded_exposures_ms": [],
                    "skipped_exposures_ms": [],
                    "early_termination": None,
                },
            )
            manifest = json.loads(Path(products["manifest_json"]).read_text(encoding="utf-8"))
            files = list(Path(directory).glob("*"))
        kinds = [record["kind"] for record in manifest["records"]]
        self.assertEqual(4, kinds.count("el_raw"))
        self.assertEqual(6, kinds.count("dark_raw"))
        self.assertEqual(2, kinds.count("master_dark"))
        self.assertIn("hdr_linear_float32", kinds)
        self.assertIn("hdr_preview_8bit", kinds)
        self.assertEqual(len(manifest["records"]) + 2, len(files))

    def test_severe_overexposure_stops_remaining_frames_and_longer_segments(self) -> None:
        calls: list[tuple[float, int]] = []

        def capture(exposure_ms: float, _gain: int, frame_number: int) -> np.ndarray:
            calls.append((exposure_ms, frame_number))
            value = 250 if exposure_ms >= 10 else 100
            return np.full((10, 10), value, dtype=np.uint8)

        plan = ExposurePlan((1.0, 10.0, 100.0, 1000.0), 10, 3, 0.0, "auto", 1.0)
        result = capture_exposure_sequence(plan, capture)
        self.assertEqual((1.0, 10.0), result.captured_exposures_ms)
        self.assertEqual((1.0,), result.valid_exposures_ms)
        self.assertEqual((10.0,), result.excluded_exposures_ms)
        self.assertEqual((100.0, 1000.0), result.skipped_exposures_ms)
        self.assertEqual([(1.0, 1), (1.0, 2), (1.0, 3), (10.0, 1)], calls)
        self.assertEqual(2, result.early_termination["remaining_frames_skipped"])

    def test_hot_pixels_and_outside_roi_do_not_trigger_early_stop(self) -> None:
        frame = np.full((10, 10), 100, dtype=np.uint8)
        frame[0, 0] = 255
        hot = np.zeros((10, 10), dtype=bool)
        hot[0, 0] = True
        plan = ExposurePlan((1.0,), 10, 1, 0.0, "auto", 0.1)
        result = capture_exposure_sequence(
            plan, lambda *_args: frame, hot_pixel_mask=hot
        )
        self.assertEqual((1.0,), result.valid_exposures_ms)
        self.assertIsNone(result.early_termination)

    def test_manifest_saves_excluded_judgment_and_marks_skipped_segments(self) -> None:
        frames = [np.full((3, 4, 5), 100, dtype=np.uint8)]
        dark = [np.zeros((3, 4, 5), dtype=np.uint8)]
        merged = merge_quantitative_hdr(frames, dark, [1], low_signal_sigma=1)
        summary = {
            "planned_exposures_ms": [1, 10, 100],
            "captured_exposures_ms": [1, 10],
            "valid_exposures_ms": [1],
            "excluded_exposures_ms": [10],
            "skipped_exposures_ms": [100],
            "early_termination": {"reason": "severe overexposure"},
        }
        with tempfile.TemporaryDirectory() as directory:
            products = save_hdr_capture_set(
                Path(directory) / "EL",
                frames,
                dark,
                merged,
                10,
                HDRSystemSettings().snapshot(),
                summary,
                excluded_judgment_frames=[(10, np.full((4, 5), 250, dtype=np.uint8))],
            )
            manifest = json.loads(Path(products["manifest_json"]).read_text(encoding="utf-8"))
        kinds = [record["kind"] for record in manifest["records"]]
        self.assertIn("overexposure_judgment", kinds)
        self.assertIn("exposure_skipped", kinds)
        self.assertEqual(summary, manifest["execution_summary"])
        self.assertIn("settings", manifest["hdr_settings_snapshot"])


if __name__ == "__main__":
    unittest.main()
