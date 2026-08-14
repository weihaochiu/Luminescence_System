from __future__ import annotations

import unittest
from pathlib import Path


class HDRUIStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).parents[1] / "gui"
        cls.main_source = "\n".join(
            (root / name).read_text(encoding="utf-8")
            for name in (
                "main_window.py",
                "main_window_ui.py",
                "main_window_devices.py",
                "measurement_control_bar.py",
            )
        )
        cls.recipe_source = "\n".join(
            (root / name).read_text(encoding="utf-8")
            for name in (
                "recipe_dialog.py",
                "recipe_dialog_pages.py",
                "recipe_dialog_logic.py",
                "measurement_execution_plan.py",
            )
        )
        cls.workflow_source = (root / "hdr_workflow.py").read_text(encoding="utf-8")

    def test_main_window_has_hdr_session_button(self) -> None:
        self.assertIn('QPushButton("HDR：未設定")', self.main_source)
        self.assertIn("choose_hdr_session(", self.main_source)

    def test_t0_and_aging_choices_are_explicit(self) -> None:
        self.assertIn("首次量測（T0）", self.workflow_source)
        self.assertIn("Aging／重複量測", self.workflow_source)
        self.assertIn("HDR Profile 不相容", self.workflow_source)

    def test_hdr_source_el_and_dark_outputs_are_forced(self) -> None:
        settings_source = (Path(__file__).parents[1] / "gui" / "hdr_settings_dialog.py").read_text(encoding="utf-8")
        self.assertIn("固定保存：所有實際拍攝的原始 EL、原始 Dark", settings_source)
        self.assertIn("定量 HDR 必須選擇 TIFF", (Path(__file__).parents[1] / "gui" / "recipe_store.py").read_text(encoding="utf-8"))

    def test_hdr_enable_is_part_of_el_matrix_page(self) -> None:
        self.assertNotIn("_build_hdr_tab", self.recipe_source)
        self.assertIn('self.tabs.addTab(self._build_el_matrix_tab(), "3 EL Matrix")', self.recipe_source)
        el_page = self.recipe_source.index("def _build_el_matrix_tab")
        hdr_check = self.recipe_source.index('QCheckBox("啟用 HDR（詳細參數：設定 → HDR）")')
        matrix = self.recipe_source.index("self.matrix_current_density_edit")
        self.assertLess(el_page, hdr_check)
        self.assertLess(hdr_check, matrix)

    def test_hdr_plan_uses_global_settings_and_merge(self) -> None:
        self.assertIn("hdr_settings.planned_exposures_ms()", self.recipe_source)
        self.assertIn('"線性合併 / 輸出"', self.recipe_source)

    def test_hdr_settings_are_reached_from_settings_menu(self) -> None:
        self.assertIn('QAction("HDR…", self)', self.main_source)
        self.assertIn("settings_menu.addAction(self.hdr_settings_action)", self.main_source)
        self.assertIn("嚴重過曝時立即停止", (Path(__file__).parents[1] / "gui" / "hdr_settings_dialog.py").read_text(encoding="utf-8"))

    def test_recipe_camera_strategy_is_removed(self) -> None:
        self.assertNotIn("camera_strategy_combo", self.recipe_source)
        self.assertNotIn('form.addRow("相機策略"', self.recipe_source)
        self.assertNotIn('"4 相機／非 HDR 預設"', self.recipe_source)
        self.assertNotIn('"非 HDR 預設 Exposure"', self.recipe_source)

    def test_legacy_el_points_and_camera_defaults_are_removed(self) -> None:
        self.assertNotIn("self.points_table", self.recipe_source)
        self.assertNotIn("self.exposure_spin", self.recipe_source)
        self.assertNotIn("self.gain_spin", self.recipe_source)


if __name__ == "__main__":
    unittest.main()
