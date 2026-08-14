from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from gui.hdr_settings import HDRSystemSettings
from gui.camera_controller import CameraController
from gui.sdk import nncam
from gui.el_matrix_plan import ELMatrixPlan
from gui.measurement_control_bar import MeasurementControlBar
from gui.main_window_measurement import begin_el_matrix_measurement, _measurement_summary
from gui.measurement_execution_plan import build_measurement_execution_plan
from gui.measurement_output import save_matrix_capture
from gui.recipe_dialog import RecipeManagerDialog
from gui.recipe_store import Recipe, RecipeStore
from gui.smu_control import SMUSafetyLimits
from tests.qt_test_utils import ensure_qapplication


class RecipeWorkflowRefactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def test_recipe_dialog_has_exactly_four_pages(self) -> None:
        for removed_model_field in (
            "camera", "el_sweep", "dark_frames", "smu", "safety"
        ):
            self.assertFalse(hasattr(Recipe(), removed_model_field))
        self.assertFalse(hasattr(Recipe().channels[0], "sample_id"))
        with tempfile.TemporaryDirectory() as directory:
            dialog = RecipeManagerDialog(RecipeStore(Path(directory) / "recipes.json"))
            try:
                self.assertEqual(4, dialog.tabs.count())
                self.assertEqual(
                    [
                        "1 基本資料",
                        "2 極性確認 / Dark IV",
                        "3 EL Matrix",
                        "4 輸出",
                    ],
                    [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())],
                )
                self.assertTrue(hasattr(dialog, "polarity_enabled_check"))
                self.assertTrue(hasattr(dialog, "dark_iv_enabled_check"))
                self.assertTrue(hasattr(dialog, "dark_frame_enabled_check"))
                for removed in (
                    "image_format_combo", "output_root_edit", "device_match_combo",
                    "points_table", "dark_frames_per_profile_spin",
                ):
                    self.assertFalse(hasattr(dialog, removed), removed)
                dialog._new_recipe()
                dialog.polarity_enabled_check.setChecked(False)
                dialog.dark_iv_enabled_check.setChecked(False)
                dialog.dark_frame_enabled_check.setChecked(True)
                self.app.processEvents()
                self.assertEqual(
                    [
                        "1. 初始化 / 前置檢查",
                        "2. Dark Frame",
                        "3. EL Matrix",
                        "4. 輸出（full）",
                    ],
                    [
                        dialog.execution_tree.topLevelItem(i).text(0)
                        for i in range(dialog.execution_tree.topLevelItemCount())
                    ],
                )
                dialog.hdr_enabled_check.setChecked(True)
                self.assertFalse(dialog.matrix_gain_edit.isEnabled())
                self.assertFalse(dialog.matrix_exposure_edit.isEnabled())
                dialog.hdr_enabled_check.setChecked(False)
                self.assertTrue(dialog.matrix_gain_edit.isEnabled())
            finally:
                dialog.close()

    def test_resolution_modes_are_only_sdk_enumerated_modes_with_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dialog = RecipeManagerDialog(
                RecipeStore(Path(directory) / "recipes.json"),
                camera_resolutions=[(3840, 2160), (1920, 1080)],
            )
            try:
                self.assertEqual(2, dialog.resolution_combo.count())
                self.assertEqual(
                    ["sdk:0", "sdk:1"],
                    [dialog.resolution_combo.itemData(i) for i in range(2)],
                )
                self.assertEqual(
                    ["3840 × 2160", "1920 × 1080"],
                    [dialog.resolution_combo.itemText(i) for i in range(2)],
                )
            finally:
                dialog.close()

    def test_execution_plan_a_b_c_and_disabled_steps_are_absent(self) -> None:
        recipe = Recipe()

        plan_a = build_measurement_execution_plan(recipe)
        self.assertEqual(
            ("initialize", "polarity", "dark_iv", "dark_frame", "el_matrix", "output"),
            plan_a.keys,
        )

        recipe.polarity.enabled = False
        recipe.dark_iv.enabled = True
        recipe.el_matrix.dark_frame_enabled = False
        plan_b = build_measurement_execution_plan(recipe)
        self.assertEqual(
            ("initialize", "dark_iv", "el_matrix", "output"), plan_b.keys
        )

        recipe.dark_iv.enabled = False
        recipe.el_matrix.dark_frame_enabled = True
        plan_c = build_measurement_execution_plan(recipe)
        self.assertEqual(
            ("initialize", "dark_frame", "el_matrix", "output"), plan_c.keys
        )
        serialized = json.dumps(plan_c.to_dict(), ensure_ascii=False)
        self.assertNotIn("skipped", serialized.casefold())
        self.assertNotIn("極性確認", serialized)
        self.assertNotIn("Dark IV", serialized)

    def test_plan_tracks_noncontiguous_channels_hdr_and_formats(self) -> None:
        recipe = Recipe()
        for channel in recipe.channels:
            channel.enabled = channel.channel in {"CH1", "CH3", "CH5"}
        # The current hardware model is CH1..CH4; explicitly use CH1/CH3.
        recipe.channels[0].enabled = True
        recipe.channels[1].enabled = False
        recipe.channels[2].enabled = True
        recipe.channels[3].enabled = False
        recipe.hdr.enabled = True
        recipe.output.format_png = True
        settings = HDRSystemSettings(max_exposure_segments=3)
        plan = build_measurement_execution_plan(recipe, hdr_settings=settings)
        matrix = next(step for step in plan.steps if step.key == "el_matrix")
        self.assertEqual(["CH1", "CH3"], [child.title for child in matrix.children])
        payload = json.dumps(plan.to_dict(), ensure_ascii=False)
        self.assertIn("Base / T0", payload)
        self.assertIn("Stop 1", payload)
        self.assertIn("線性合併 / 輸出", payload)
        output = next(step for step in plan.steps if step.key == "output")
        self.assertEqual(
            ["TIFF", "PNG", "JPG with Footer"],
            [child.title for child in output.children],
        )
        runtime = ELMatrixPlan(recipe, hdr_settings=settings)
        self.assertEqual(tuple(settings.planned_exposures_ms()), runtime.exposures_ms)
        self.assertEqual((settings.locked_gain_percent,), runtime.gains_percent)
        self.assertEqual(settings.frames_per_exposure, runtime.repeat)
        expected_per_channel = (
            len(recipe.el_matrix.current_density_ma_cm2)
            * len(settings.planned_exposures_ms())
            * settings.frames_per_exposure
        )
        self.assertEqual(expected_per_channel, runtime.capture_counts()["el_per_channel"])

    def test_sample_id_inputs_follow_exact_active_channels_and_preserve_per_channel_values(self) -> None:
        bar = MeasurementControlBar()
        try:
            bar.set_active_channels(["CH1", "CH3", "CH5"])
            self.assertEqual(["CH1", "CH3", "CH5"], list(bar.sample_id_edits))
            bar.sample_id_edits["CH1"].setText("A")
            bar.sample_id_edits["CH3"].setText("B")
            bar.sample_id_edits["CH5"].setText("C")
            self.assertEqual({"CH1": "A", "CH3": "B", "CH5": "C"}, bar.sample_ids())
            bar.set_active_channels(["CH3", "CH5"])
            self.assertEqual({"CH3": "B", "CH5": "C"}, bar.sample_ids())
            bar.set_active_channels(["CH2"])
            self.assertEqual(["CH2"], list(bar.sample_id_edits))
            bar.set_active_channels(["CH2", "CH4"])
            self.assertEqual(["CH2", "CH4"], list(bar.sample_id_edits))
            bar.sample_id_edits["CH4"].clear()
            self.assertEqual(["CH2", "CH4"], bar.missing_sample_channels())
        finally:
            bar.close()

    def test_start_is_blocked_with_exact_missing_active_channel_message(self) -> None:
        bar = MeasurementControlBar()
        try:
            bar.set_active_channels(["CH1", "CH3"])
            bar.sample_id_edits["CH1"].setText("A")
            owner = SimpleNamespace(
                selected_recipe=Recipe(), measurement_control_bar=bar,
                hdr_session_state=None,
            )
            with patch(
                "gui.main_window_measurement.QMessageBox.warning"
            ) as warning:
                begin_el_matrix_measurement(owner)
            warning.assert_called_once()
            self.assertEqual(
                "無法開始量測：CH3 尚未設定樣品 ID。",
                warning.call_args.args[2],
            )
        finally:
            bar.close()

    def test_measurement_summary_keeps_channel_sample_mapping(self) -> None:
        recipe = Recipe()
        recipe.channels[1].enabled = True
        plan = ELMatrixPlan(
            recipe, sample_ids={"CH1": "A/1", "CH2": "B 2"}
        )
        owner = SimpleNamespace(
            smu_manager=SimpleNamespace(
                control=SimpleNamespace(
                    safety=SimpleNamespace(limits=SMUSafetyLimits())
                )
            ),
            hdr_settings_store=SimpleNamespace(settings=HDRSystemSettings()),
            hdr_session_state=None,
        )
        summary = _measurement_summary(owner, plan)
        self.assertIn("樣品：CH1=A/1 / CH2=B 2", summary)

    def test_uint16_tiff_exact_match_and_derived_outputs_do_not_mutate_source(self) -> None:
        source = np.array([[0, 1, 255, 256, 1024, 2048, 4095]], dtype=np.uint16)
        before = source.copy()
        recipe = Recipe()
        recipe.output.format_tiff = True
        recipe.output.format_png = True
        recipe.output.format_jpg = True
        recipe.output.format_jpg_with_footer = True
        metadata = {
            "MeasurementType": "EL", "SampleID": "A/B", "Channel": "CH1",
            "CommandedCurrentDensity": 2.0, "Gain": 100, "Exposure": 10.0,
            "RepeatIndex": 1, "RepeatTotal": 1, "MeasuredCurrentMa": 1.198,
            "MeasuredVoltage": 1.24, "CameraTemperature": 39.8,
            "Timestamp": "2026-08-14 06:44:12", "ApplicableChannels": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            saved = save_matrix_capture(
                source,
                Image.new("L", (source.shape[1], source.shape[0])),
                Path(directory) / "capture",
                metadata,
                recipe.output,
            )
            reloaded = cv2.imread(str(saved.tiff_path), cv2.IMREAD_UNCHANGED)
            self.assertEqual(np.uint16, reloaded.dtype)
            np.testing.assert_array_equal(source, reloaded)
            np.testing.assert_array_equal(before, source)
            self.assertTrue(saved.png_path.is_file())
            self.assertTrue(saved.jpeg_path.is_file())
            self.assertTrue(saved.footer_jpeg_path.is_file())
            self.assertNotEqual(saved.jpeg_path, saved.footer_jpeg_path)
            with Image.open(saved.footer_jpeg_path) as footer:
                self.assertGreater(footer.height, source.shape[0])

    def test_output_format_combinations_have_deterministic_noncolliding_paths(self) -> None:
        source = np.array([[0, 255, 256, 4095]], dtype=np.uint16)
        metadata = {
            "MeasurementType": "EL", "SampleID": "A", "Channel": "CH1",
            "CommandedCurrentDensity": 2.0, "Gain": 100, "Exposure": 10.0,
            "RepeatIndex": 1, "RepeatTotal": 1, "MeasuredCurrentMa": 1.0,
            "MeasuredVoltage": 1.2, "CameraTemperature": 30.0,
            "Timestamp": "2026-08-14 06:44:12", "ApplicableChannels": [],
        }
        cases = (
            ("tiff", (True, False, False, False), {".tiff"}),
            ("jpg", (False, False, True, False), {".jpg"}),
            ("jpg_both", (False, False, True, True), {".jpg", "_footer.jpg"}),
            ("all", (True, True, True, True), {".tiff", ".png", ".jpg", "_footer.jpg"}),
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, flags, expected_suffixes in cases:
                with self.subTest(name=name):
                    output = Recipe().output
                    (
                        output.format_tiff,
                        output.format_png,
                        output.format_jpg,
                        output.format_jpg_with_footer,
                    ) = flags
                    saved = save_matrix_capture(
                        source,
                        Image.new("L", (4, 1)),
                        Path(directory) / name / "capture",
                        dict(metadata),
                        output,
                    )
                    paths = [
                        path for path in (
                            saved.tiff_path, saved.png_path, saved.jpeg_path,
                            saved.footer_jpeg_path,
                        ) if path is not None
                    ]
                    suffixes = {
                        "_footer.jpg" if path.name.endswith("_footer.jpg") else path.suffix
                        for path in paths
                    }
                    self.assertEqual(expected_suffixes, suffixes)
                    self.assertEqual(len(paths), len(set(paths)))
                    self.assertTrue(all(path.is_file() for path in paths))

    def test_rgb_uint16_tiff_round_trip_preserves_channel_values(self) -> None:
        source = np.array(
            [[[0, 1, 2], [255, 256, 4095], [1024, 2048, 3072]]],
            dtype=np.uint16,
        )
        output = Recipe().output
        output.format_jpg_with_footer = False
        metadata = {
            "MeasurementType": "EL", "SampleID": "A", "Channel": "CH1",
            "CommandedCurrentDensity": 2.0, "Gain": 100, "Exposure": 10.0,
            "RepeatIndex": 1, "RepeatTotal": 1, "MeasuredCurrentMa": 1.0,
            "MeasuredVoltage": 1.2, "CameraTemperature": 30.0,
            "Timestamp": "2026-08-14 06:44:12", "ApplicableChannels": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            saved = save_matrix_capture(
                source, Image.new("RGB", (3, 1)), Path(directory) / "rgb",
                metadata, output,
            )
            loaded_bgr = cv2.imread(str(saved.tiff_path), cv2.IMREAD_UNCHANGED)
            loaded_rgb = cv2.cvtColor(loaded_bgr, cv2.COLOR_BGR2RGB)
            self.assertEqual(np.uint16, loaded_rgb.dtype)
            np.testing.assert_array_equal(source, loaded_rgb)

    def test_camera_scientific_branch_enables_high_bit_mode_and_pulls_rgb48(self) -> None:
        open_source = inspect.getsource(CameraController.open_device)
        pull_source = inspect.getsource(CameraController._pull_live_frame)
        self.assertIn("NNCAM_OPTION_BITDEPTH, 1", open_source)
        self.assertIn("PullImageV4(self._buffer, 0, 48", pull_source)
        self.assertIn('dtype="<u2"', pull_source)
        self.assertIn("scientific_frame_ready.emit(scientific", pull_source)
        self.assertEqual(
            12,
            CameraController._native_sensor_bit_depth(nncam.NNCAM_FLAG_RAW12),
        )


if __name__ == "__main__":
    unittest.main()
