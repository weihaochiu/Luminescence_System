from __future__ import annotations

import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QSizePolicy

from gui.measurement_control_bar import MeasurementControlBar
from gui.responsive_layout import (
    LayoutMode,
    ResponsiveThresholds,
    effective_logical_width,
    layout_mode_for_width,
)


class ResponsiveLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        existing = QApplication.instance()
        cls.app = (
            existing
            if isinstance(existing, QApplication)
            else QApplication([]) if existing is None else None
        )

    def test_required_logical_widths_choose_expected_modes(self) -> None:
        thresholds = ResponsiveThresholds()
        self.assertEqual(LayoutMode.COMPACT, layout_mode_for_width(1024, thresholds))
        self.assertEqual(LayoutMode.STANDARD, layout_mode_for_width(1366, thresholds))
        self.assertEqual(LayoutMode.WIDE, layout_mode_for_width(1920, thresholds))
        self.assertEqual(1600, effective_logical_width(1920, 1600, 1750))

    def test_same_widgets_are_rearranged_and_emergency_never_hidden(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        bar = MeasurementControlBar()
        widget_id = id(bar.emergency_stop_button)
        positions = {}
        for mode in (LayoutMode.WIDE, LayoutMode.STANDARD, LayoutMode.COMPACT):
            bar.set_layout_mode(mode)
            index = bar.grid.indexOf(bar.emergency_stop_button)
            positions[mode] = bar.grid.getItemPosition(index)
            self.assertEqual(widget_id, id(bar.emergency_stop_button))
            self.assertFalse(bar.emergency_stop_button.isHidden())
            self.assertFalse(bar.selected_recipe_label.text().startswith("Recipe"))
            self.assertFalse(bar.recipe_label.isHidden())
        self.assertEqual(0, positions[LayoutMode.WIDE][0])
        self.assertEqual(4, positions[LayoutMode.COMPACT][0])
        self.assertNotEqual(positions[LayoutMode.WIDE], positions[LayoutMode.COMPACT])

    def test_path_data_and_dpi_aware_size_policy_are_preserved(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        bar = MeasurementControlBar()
        path = r"D:\Research\Perovskite\EL Measurement\2026\August\very-long-path"
        bar.measurement_path_edit.setText(path)
        self.assertEqual(path, bar.measurement_path_edit.text())
        self.assertEqual(path, bar.measurement_path_edit.toolTip())
        self.assertEqual(
            QSizePolicy.Policy.MinimumExpanding,
            bar.measurement_path_edit.sizePolicy().horizontalPolicy(),
        )
        standard, wide = bar.recommended_breakpoints()
        self.assertGreaterEqual(standard, 1080)
        self.assertGreater(wide, standard)

    def test_main_window_required_geometries_keep_emergency_and_live_view_visible(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        from gui.main_window import MainWindow

        with TemporaryDirectory() as runtime_dir:
            with patch(
                "gui.main_window.QStandardPaths.writableLocation",
                return_value=runtime_dir,
            ), patch("gui.main_window.QTimer.singleShot"):
                window = MainWindow()
            manager = window.responsive_layout_manager
            window.show()
            self.app.processEvents()
            try:
                with patch.object(
                    manager,
                    "_available_screen_width",
                    side_effect=lambda: window.width(),
                ):
                    for width, height, mode in (
                        (1024, 768, LayoutMode.COMPACT),
                        (1366, 768, LayoutMode.STANDARD),
                        (1920, 1080, LayoutMode.WIDE),
                    ):
                        window.resize(width, height)
                        self.app.processEvents()
                        manager.update_now()
                        self.app.processEvents()
                        bar = window.measurement_control_bar
                        emergency = bar.emergency_stop_button
                        self.assertEqual(mode, manager.mode)
                        self.assertEqual(mode, bar.layout_mode)
                        self.assertFalse(emergency.isHidden())
                        self.assertLessEqual(
                            emergency.geometry().right(), bar.contentsRect().right()
                        )
                        self.assertLessEqual(
                            emergency.geometry().bottom(), bar.contentsRect().bottom()
                        )
                        workspace = window.main_splitter.widget(1)
                        self.assertGreaterEqual(workspace.width(), workspace.minimumWidth())
            finally:
                window.close()
                self.app.processEvents()

    def test_runtime_font_change_refreshes_control_metrics(self) -> None:
        if self.app is None:
            self.skipTest("A non-GUI Qt application already exists")
        from PySide6.QtWidgets import QWidget
        from gui.responsive_layout import ResponsiveLayoutManager

        window = QWidget()
        bar = MeasurementControlBar(window)
        manager = ResponsiveLayoutManager(window, bar)
        with patch.object(bar, "refresh_metrics", wraps=bar.refresh_metrics) as refresh:
            self.app.sendEvent(bar, QEvent(QEvent.Type.FontChange))
            self.app.processEvents()
            self.assertGreaterEqual(refresh.call_count, 1)
        manager.deleteLater()
        window.close()


if __name__ == "__main__":
    unittest.main()
