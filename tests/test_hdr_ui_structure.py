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
                "recipe_dialog_points.py",
                "recipe_dialog_logic.py",
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
        self.assertIn("self.save_raw_check.setEnabled(not enabled)", self.recipe_source)

    def test_hdr_enable_is_part_of_el_points_page(self) -> None:
        self.assertNotIn("_build_hdr_tab", self.recipe_source)
        self.assertNotIn('"5 定量 HDR"', self.recipe_source)
        self.assertIn('self.tabs.addTab(self._build_el_tab(), "5 EL 點位")', self.recipe_source)
        el_page = self.recipe_source.index("def _build_el_tab")
        hdr_check = self.recipe_source.index('QCheckBox("啟用 HDR")')
        points_table = self.recipe_source.index("self.points_table = QTableWidget")
        self.assertLess(el_page, hdr_check)
        self.assertLess(hdr_check, points_table)

    def test_hdr_greys_camera_cells_and_shows_hdr_state(self) -> None:
        self.assertIn('HDR_CELL_TEXT = "啟用 HDR"', self.recipe_source)
        self.assertIn('item.setBackground(QColor("#e5e7eb"))', self.recipe_source)
        self.assertIn("item.flags() & ~Qt.ItemFlag.ItemIsEditable", self.recipe_source)
        self.assertIn("self.CAMERA_VALUE_ROLE", self.recipe_source)

    def test_hdr_settings_are_reached_from_settings_menu(self) -> None:
        self.assertIn('QAction("HDR…", self)', self.main_source)
        self.assertIn("settings_menu.addAction(self.hdr_settings_action)", self.main_source)
        self.assertIn("嚴重過曝時立即停止", (Path(__file__).parents[1] / "gui" / "hdr_settings_dialog.py").read_text(encoding="utf-8"))

    def test_recipe_camera_strategy_is_removed(self) -> None:
        self.assertNotIn("camera_strategy_combo", self.recipe_source)
        self.assertNotIn('form.addRow("相機策略"', self.recipe_source)
        self.assertIn('"4 相機／非 HDR 預設"', self.recipe_source)
        self.assertIn('"非 HDR 預設 Exposure"', self.recipe_source)

    def test_hdr_disables_non_hdr_table_defaults(self) -> None:
        for widget in (
            "self.exposure_spin",
            "self.gain_spin",
            "self.frames_spin",
            "self.frame_interval_spin",
        ):
            self.assertIn(widget, self.recipe_source)
        self.assertIn("widget.setEnabled(not enabled)", self.recipe_source)


if __name__ == "__main__":
    unittest.main()
