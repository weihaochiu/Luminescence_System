from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from risingcam_gui.hdr_profile import HDRProfile, create_t0_profile
from risingcam_gui.hdr_settings import HDRSystemSettings
from risingcam_gui.recipe_store import Recipe


class HDRProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recipe = Recipe()
        self.recipe.hdr.enabled = True
        self.recipe.state = "active"
        self.settings = HDRSystemSettings()

    def test_create_save_load_and_match_stability_profile(self) -> None:
        profile = create_t0_profile(
            "PSC-001",
            self.recipe,
            [0.1, 1.0, 10.0],
            100,
            {"name": "RisingCam", "model": "IMX585", "serial": "CAM-1"},
            self.settings,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / profile.suggested_filename()
            profile.save(path)
            loaded = HDRProfile.load(path)
        errors, warnings = loaded.compatibility_issues(
            "PSC-001",
            self.recipe,
            {"name": "RisingCam", "model": "IMX585", "serial": "CAM-1"},
            self.settings,
        )
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual((0.1, 1.0, 10.0), loaded.exposure_times_ms)
        self.assertTrue(loaded.source_el_frames_required)
        self.assertTrue(loaded.source_dark_frames_required)

    def test_sample_or_scan_change_is_rejected(self) -> None:
        profile = create_t0_profile(
            "PSC-001", self.recipe, [0.1, 1.0], 50, hdr_settings=self.settings
        )
        errors, _warnings = profile.compatibility_issues(
            "PSC-002", self.recipe, hdr_settings=self.settings
        )
        self.assertTrue(any("Sample ID" in item for item in errors))

        self.recipe.el_sweep.points[0].setpoint = 999
        errors, _warnings = profile.compatibility_issues(
            "PSC-001", self.recipe, hdr_settings=self.settings
        )
        self.assertTrue(any("掃描點" in item for item in errors))

    def test_profile_records_planned_captured_excluded_and_skipped_segments(self) -> None:
        summary = {
            "planned_exposures_ms": [1, 10, 100, 1000],
            "captured_exposures_ms": [1, 10],
            "valid_exposures_ms": [1],
            "excluded_exposures_ms": [10],
            "skipped_exposures_ms": [100, 1000],
            "early_termination": {"segment_index": 2, "reason": "severe overexposure"},
        }
        profile = create_t0_profile(
            "PSC-001", self.recipe, [1, 10, 100, 1000], 20,
            hdr_settings=self.settings, capture_summary=summary,
        )
        self.assertEqual((1.0,), profile.exposure_times_ms)
        self.assertEqual((10.0,), profile.excluded_exposure_times_ms)
        self.assertEqual((100.0, 1000.0), profile.skipped_exposure_times_ms)
        self.assertIsNotNone(profile.early_termination)
        self.assertIn("settings", profile.hdr_settings_snapshot)


if __name__ == "__main__":
    unittest.main()
