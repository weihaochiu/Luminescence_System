from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gui.hdr_settings import HDRSystemSettings
from gui.recipe_store import Recipe, RecipeStore


class RecipeStoreTests(unittest.TestCase):
    def test_default_formal_recipe_validates(self) -> None:
        recipe = Recipe()
        self.assertEqual([], recipe.validate())
        self.assertEqual(("TIFF", "JPG with Footer"), recipe.output.selected_formats())

    def test_v9_round_trip_contains_only_formal_recipe_sections(self) -> None:
        recipe = Recipe()
        recipe.name = "Round trip"
        recipe.state = "active"
        self.assertFalse(hasattr(recipe.channels[0], "sample_id"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recipes.json"
            store = RecipeStore(path)
            store.upsert(recipe)
            loaded = RecipeStore(path).recipes[0]
        payload = loaded.to_dict()
        self.assertEqual(9, RecipeStore.schema_version)
        for removed in ("camera", "el_sweep", "dark_frames", "smu", "safety"):
            self.assertNotIn(removed, payload)
        self.assertNotIn("sample_id", payload["channels"][0])
        self.assertNotIn("root_directory", payload["output"])
        self.assertEqual([], loaded.validate())

    def test_output_format_checkboxes_round_trip_independently(self) -> None:
        recipe = Recipe()
        recipe.output.format_tiff = True
        recipe.output.format_png = True
        recipe.output.format_jpg = True
        recipe.output.format_jpg_with_footer = True
        loaded = Recipe.from_dict(recipe.to_dict())
        self.assertEqual(
            ("TIFF", "PNG", "JPG", "JPG with Footer"),
            loaded.output.selected_formats(),
        )

    def test_at_least_one_image_format_is_required(self) -> None:
        recipe = Recipe()
        recipe.output.format_tiff = False
        recipe.output.format_png = False
        recipe.output.format_jpg = False
        recipe.output.format_jpg_with_footer = False
        self.assertTrue(any("至少必須選擇" in error for error in recipe.validate()))

    def test_hdr_uses_global_settings_and_requires_dark_and_tiff(self) -> None:
        recipe = Recipe()
        recipe.hdr.enabled = True
        settings = HDRSystemSettings(max_exposure_segments=4)
        self.assertEqual([], recipe.validate(settings))
        recipe.el_matrix.dark_frame_enabled = False
        self.assertTrue(any("Dark Frame" in error for error in recipe.validate(settings)))
        recipe.el_matrix.dark_frame_enabled = True
        recipe.output.format_tiff = False
        self.assertTrue(any("TIFF" in error for error in recipe.validate(settings)))

    def test_legacy_sources_migrate_but_are_not_written_back(self) -> None:
        migrated = Recipe.from_dict({
            "camera": {"exposure_ms": 700},
            "el_sweep": {"points": [{"setpoint": 1, "exposure_ms": 250}]},
            "dark_frames": {"frames_per_profile": 9},
            "smu": {"device_match": "specific", "visa_address": "USB::OLD"},
            "safety": {"max_voltage_v": 1.0},
            "channels": [
                {"channel": f"CH{i}", "enabled": i == 1, "sample_id": "OLD", "area_cm2": 0.1}
                for i in range(1, 5)
            ],
        })
        payload = migrated.to_dict()
        self.assertFalse(hasattr(migrated.channels[0], "sample_id"))
        self.assertNotIn("camera", payload)
        self.assertNotIn("el_sweep", payload)
        self.assertNotIn("dark_frames", payload)
        self.assertNotIn("smu", payload)
        self.assertNotIn("safety", payload)
        self.assertEqual([1.0], migrated.el_matrix.current_density_ma_cm2)
        self.assertEqual([10], migrated.el_matrix.gains_percent)
        self.assertEqual([250.0], migrated.el_matrix.exposures_ms)

    def test_legacy_dark_and_single_format_migrate(self) -> None:
        migrated = Recipe.from_dict({
            "el_matrix": {"shared_dark_enabled": False},
            "output": {"image_format": "PNG"},
        })
        self.assertFalse(migrated.el_matrix.dark_frame_enabled)
        self.assertEqual(("PNG",), migrated.output.selected_formats())

    def test_current_schema_rejects_deprecated_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            with self.assertRaisesRegex(ValueError, "已移除欄位"):
                store.import_payload({
                    "schema_version": RecipeStore.schema_version,
                    "recipe": {"name": "Bad", "safety": {"max_voltage_v": 1}},
                })

            with self.assertRaisesRegex(ValueError, "sample_id"):
                store.import_payload({
                    "schema_version": RecipeStore.schema_version,
                    "recipe": {
                        "name": "Bad sample ownership",
                        "channels": [{
                            "channel": "CH1", "enabled": True,
                            "sample_id": "belongs-to-main-window", "area_cm2": 0.1,
                        }],
                    },
                })

    def test_import_rejects_future_and_unknown_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RecipeStore(Path(directory) / "recipes.json")
            with self.assertRaisesRegex(ValueError, "高於"):
                store.import_payload({"schema_version": 999, "recipe": {}})
            with self.assertRaisesRegex(ValueError, "不支援欄位"):
                store.import_payload({
                    "schema_version": RecipeStore.schema_version,
                    "recipe": {"name": "Bad", "unexpected": {}},
                })

    def test_pixel_csv_requires_tiff_and_a_selected_product(self) -> None:
        recipe = Recipe()
        recipe.output.export_pixel_csv = True
        recipe.output.pixel_csv_raw = False
        recipe.output.pixel_csv_dark_corrected = False
        recipe.output.pixel_csv_exposure_normalized = False
        recipe.output.format_tiff = False
        errors = recipe.validate()
        self.assertTrue(any("至少要選擇一種" in error for error in errors))
        self.assertTrue(any("TIFF" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
