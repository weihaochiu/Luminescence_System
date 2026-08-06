from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from risingcam_gui.recipe_store import ELPoint, Recipe, RecipeStore
from risingcam_gui.hdr_settings import HDRSystemSettings


class RecipeStoreTests(unittest.TestCase):
    def test_default_four_stage_recipe_validates(self) -> None:
        recipe = Recipe()
        self.assertEqual([], recipe.validate())
        self.assertTrue(recipe.polarity.enabled)
        self.assertTrue(recipe.dark_iv.enabled)
        self.assertEqual(6, len(recipe.enabled_points()))
        self.assertEqual(1, len(recipe.dark_profiles()))
        self.assertTrue(recipe.output.save_summary_csv)
        self.assertFalse(recipe.output.export_pixel_csv)

    def test_current_density_converts_to_actual_current(self) -> None:
        recipe = Recipe()
        recipe.geometry.active_area_cm2 = 0.1
        point = ELPoint(setpoint=20)
        self.assertAlmostEqual(2.0, recipe.actual_current_ma(point))

    def test_unique_dark_profiles_and_quantitative_warning(self) -> None:
        recipe = Recipe()
        recipe.el_sweep.points = [
            ELPoint(setpoint=1, exposure_ms=100),
            ELPoint(setpoint=2, exposure_ms=100),
            ELPoint(setpoint=3, exposure_ms=500),
        ]
        self.assertEqual(2, len(recipe.dark_profiles()))
        self.assertTrue(recipe.validation_warnings())

    def test_round_trip_preserves_points(self) -> None:
        recipe = Recipe()
        recipe.name = "Round trip"
        recipe.state = "active"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recipes.json"
            store = RecipeStore(path)
            store.upsert(recipe)
            loaded = RecipeStore(path).recipes[0]
        self.assertEqual(recipe.name, loaded.name)
        self.assertEqual(len(recipe.el_sweep.points), len(loaded.el_sweep.points))
        self.assertFalse(loaded.output.export_pixel_csv)
        self.assertFalse(loaded.validate())

    def test_hdr_round_trip_and_required_source_outputs(self) -> None:
        recipe = Recipe()
        recipe.hdr.enabled = True
        loaded = Recipe.from_dict(recipe.to_dict())
        self.assertTrue(loaded.hdr.enabled)
        self.assertEqual({"enabled": True}, loaded.to_dict()["hdr"])
        settings = HDRSystemSettings(max_exposure_segments=4)
        self.assertEqual(4, len(loaded.hdr_upper_bound_exposures_ms(settings)))
        self.assertEqual([], loaded.validate(settings))

        loaded.output.save_raw_frames = False
        self.assertTrue(any("原始 EL" in item for item in loaded.validate()))

    def test_hdr_ignores_per_row_camera_values_but_non_hdr_requires_them(self) -> None:
        recipe = Recipe()
        recipe.hdr.enabled = True
        recipe.el_sweep.points[0].exposure_ms = 0
        self.assertEqual([], recipe.validate(HDRSystemSettings()))
        recipe.hdr.enabled = False
        self.assertTrue(any("每列相機設定皆為必填" in item for item in recipe.validate()))

    def test_legacy_global_camera_values_are_materialized_into_every_row(self) -> None:
        migrated = Recipe.from_dict({
            "camera": {"exposure_ms": 1200, "gain_percent": 30, "frame_count": 4, "frame_interval_s": 0.2},
            "el_sweep": {"points": [{"setpoint": 1, "use_camera_override": False}]},
        })
        point = migrated.el_sweep.points[0]
        self.assertEqual((1200, 30, 4, 0.2), migrated.effective_camera(point))

    def test_obsolete_camera_strategy_and_override_are_not_written_back(self) -> None:
        migrated = Recipe.from_dict({
            "camera": {"strategy": "inspection", "exposure_ms": 700},
            "el_sweep": {
                "points": [
                    {
                        "setpoint": 1,
                        "use_camera_override": True,
                        "exposure_ms": 250,
                    }
                ]
            },
        })
        payload = migrated.to_dict()
        self.assertNotIn("strategy", payload["camera"])
        self.assertNotIn("use_camera_override", payload["el_sweep"]["points"][0])
        self.assertEqual(250, migrated.el_sweep.points[0].exposure_ms)

    def test_new_explicit_row_without_legacy_flag_preserves_camera_values(self) -> None:
        loaded = Recipe.from_dict({
            "camera": {"exposure_ms": 700},
            "el_sweep": {"points": [{"setpoint": 1, "exposure_ms": 250}]},
        })
        self.assertEqual(250, loaded.el_sweep.points[0].exposure_ms)

    def test_recipe_store_uses_schema_v6(self) -> None:
        self.assertEqual(6, RecipeStore.schema_version)

    def test_pixel_csv_is_optional_and_preserves_selected_products(self) -> None:
        recipe = Recipe()
        recipe.output.export_pixel_csv = True
        recipe.output.pixel_csv_raw = False
        recipe.output.pixel_csv_dark_corrected = True
        recipe.output.pixel_csv_exposure_normalized = True
        self.assertEqual([], recipe.validate())
        loaded = Recipe.from_dict(recipe.to_dict())
        self.assertTrue(loaded.output.export_pixel_csv)
        self.assertFalse(loaded.output.pixel_csv_raw)
        self.assertTrue(loaded.output.pixel_csv_dark_corrected)
        self.assertTrue(loaded.output.pixel_csv_exposure_normalized)

    def test_pixel_csv_requires_at_least_one_product_when_enabled(self) -> None:
        recipe = Recipe()
        recipe.output.export_pixel_csv = True
        recipe.output.pixel_csv_raw = False
        recipe.output.pixel_csv_dark_corrected = False
        recipe.output.pixel_csv_exposure_normalized = False
        self.assertTrue(any("至少要選擇一種" in item for item in recipe.validate()))

    def test_v121_save_csv_migrates_to_required_summary_csv(self) -> None:
        migrated = Recipe.from_dict({"output": {"save_csv": False}})
        self.assertFalse(migrated.output.save_summary_csv)
        self.assertFalse(migrated.output.export_pixel_csv)

    def test_old_single_current_recipe_migrates_to_review_draft(self) -> None:
        old = {
            "name": "Legacy",
            "state": "active",
            "measurement_type": "el_single_current",
            "camera": {"exposure_ms": 1000, "gain_percent": 20, "frame_count": 2},
            "smu": {"source_value": 5, "settle_time_s": 1},
        }
        migrated = Recipe.from_dict(old)
        self.assertEqual("el_sequence", migrated.measurement_type)
        self.assertEqual("draft", migrated.state)
        self.assertEqual(5, migrated.el_sweep.points[0].setpoint)
        self.assertEqual("current", migrated.el_sweep.setpoint_basis)


if __name__ == "__main__":
    unittest.main()
