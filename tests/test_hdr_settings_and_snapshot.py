from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gui.auto_hdr import ExposurePlan
from gui.hdr_settings import HDRSettingsStore, HDRSystemSettings
from gui.measurement_snapshot import build_measurement_snapshot, save_measurement_snapshot
from gui.recipe_store import Recipe


class HDRSettingsAndSnapshotTests(unittest.TestCase):
    def test_settings_round_trip_and_legacy_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hdr_settings.json"
            store = HDRSettingsStore(path, {"quality": "high", "saturation_dn": 240})
            self.assertTrue(store.migrated_from_legacy)
            self.assertEqual(7, store.settings.max_exposure_segments)
            self.assertEqual(5, store.settings.frames_per_exposure)
            self.assertEqual(240, store.settings.saturation_dn)
            loaded = HDRSettingsStore(path)
        self.assertEqual(store.settings.to_dict(), loaded.settings.to_dict())

    def test_recipe_only_persists_hdr_enable_switch(self) -> None:
        recipe = Recipe()
        recipe.hdr.enabled = True
        self.assertEqual({"enabled": True}, recipe.to_dict()["hdr"])

    def test_measurement_snapshot_contains_full_effective_hdr_settings(self) -> None:
        recipe = Recipe()
        recipe.hdr.enabled = True
        settings = HDRSystemSettings(max_exposure_segments=4, severe_saturation_fraction=0.05)
        plan = ExposurePlan((1, 10, 100, 1000), 20, 3, 0.1, "auto", 4.0)
        execution = {
            "valid_exposures_ms": [1],
            "excluded_exposures_ms": [10],
            "skipped_exposures_ms": [100, 1000],
            "early_termination": {"segment_index": 2, "reason": "severe overexposure"},
        }
        snapshot = build_measurement_snapshot(
            recipe, settings, "T0", exposure_plan=plan, execution_summary=execution
        )
        recorded = snapshot["hdr"]["system_settings_snapshot"]["settings"]
        self.assertEqual(4, recorded["max_exposure_segments"])
        self.assertEqual(0.05, recorded["severe_saturation_fraction"])
        self.assertEqual([100, 1000], snapshot["hdr"]["execution"]["skipped_exposures_ms"])
        with tempfile.TemporaryDirectory() as directory:
            path = save_measurement_snapshot(Path(directory) / "measurement_snapshot.json", snapshot)
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(recipe.recipe_id, loaded["recipe"]["recipe_id"])


if __name__ == "__main__":
    unittest.main()
