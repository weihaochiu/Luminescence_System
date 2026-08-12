from __future__ import annotations

import ast
import unittest
from pathlib import Path


class MainToolbarStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_path = Path(__file__).parents[1] / "gui" / "main_window_ui.py"
        cls.tree = ast.parse(cls.source_path.read_text(encoding="utf-8"))
        main_window = next(
            node for node in cls.tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindowUIMixin"
        )
        cls.toolbar_method = next(
            node
            for node in main_window.body
            if isinstance(node, ast.FunctionDef) and node.name == "_build_menu_and_toolbar"
        )

    def test_toolbar_order_matches_workflow(self) -> None:
        action_names = []
        for node in ast.walk(self.toolbar_method):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "addAction" or not node.args:
                continue
            receiver = node.func.value
            argument = node.args[0]
            if not isinstance(receiver, ast.Name) or receiver.id != "toolbar":
                continue
            if isinstance(argument, ast.Attribute) and isinstance(argument.value, ast.Name):
                if argument.value.id == "self":
                    action_names.append(argument.attr)
        self.assertEqual(
            [
                "refresh_action",
                "connect_action",
                "recipe_manager_action",
                "capture_action",
                "auto_capture_action",
                "fit_action",
            ],
            action_names,
        )

    def test_actual_size_and_global_emergency_are_in_live_view_header(self) -> None:
        source = self.source_path.read_text(encoding="utf-8")
        actual = source.index("header_layout.addWidget(self.live_actual_size_button)")
        emergency = source.index("header_layout.addWidget(self.emergency_stop_button)")
        self.assertLess(actual, emergency)
        self.assertIn('QPushButton("⚠ 緊急停止")', source)
        self.assertIn('setObjectName("globalEmergencyStop")', source)

    def test_toolbar_buttons_use_font_metrics_minimum_size(self) -> None:
        calls = []
        for node in ast.walk(self.toolbar_method):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            calls.append(node.func.attr)
        self.assertIn("setMinimumWidth", calls)
        self.assertIn("setMinimumHeight", calls)
        self.assertNotIn("setFixedSize", calls)

    def test_toolbar_uses_uniform_icon_size(self) -> None:
        source = self.source_path.read_text(encoding="utf-8")
        self.assertIn("toolbar.setIconSize(QSize(20, 20))", source)


if __name__ == "__main__":
    unittest.main()
