from __future__ import annotations

import ast
import unittest
from pathlib import Path


class ManualExposureControlStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_path = Path(__file__).parents[1] / "gui" / "main_window_devices.py"
        cls.tree = ast.parse(cls.source_path.read_text(encoding="utf-8"))
        mixin = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindowDeviceMixin"
        )
        cls.methods = {
            node.name: node for node in mixin.body if isinstance(node, ast.FunctionDef)
        }

    @staticmethod
    def _source(node: ast.AST) -> str:
        return ast.unparse(node)

    def test_manual_widgets_share_one_mode_state_function(self) -> None:
        source = self._source(self.methods["_update_exposure_control_state"])
        self.assertIn("manual = self.controller.is_open", source)
        self.assertIn("not self.auto_exposure_check.isChecked()", source)
        for widget in ("exposure_spin", "gain_spin", "apply_manual_button"):
            self.assertIn(f"self.{widget}.setEnabled(manual)", source)

    def test_connection_state_does_not_overwrite_manual_mode(self) -> None:
        source = self._source(self.methods["_set_camera_controls_enabled"])
        self.assertIn("self._update_exposure_control_state()", source)
        for widget in (
            "auto_target_spin",
            "exposure_spin",
            "gain_spin",
            "apply_manual_button",
        ):
            self.assertNotIn(f"self.{widget}.setEnabled(", source)

    def test_manual_values_are_converted_to_sdk_units(self) -> None:
        source = self._source(self.methods["apply_manual_exposure"])
        self.assertIn("round(self.exposure_spin.value() * 1000.0)", source)
        self.assertIn(
            "self.controller.set_manual_exposure(exposure_us, self.gain_spin.value())",
            source,
        )

    def test_exposure_formatter_is_a_static_method(self) -> None:
        method = self.methods["_format_exposure"]
        decorators = [ast.unparse(node) for node in method.decorator_list]
        self.assertIn("staticmethod", decorators)
        self.assertEqual([arg.arg for arg in method.args.args], ["exposure_us"])

    def test_mixin_methods_have_valid_instance_binding(self) -> None:
        for name, method in self.methods.items():
            positional = [arg.arg for arg in method.args.args]
            decorators = {ast.unparse(node) for node in method.decorator_list}
            valid_instance_method = bool(positional) and positional[0] in {"self", "cls"}
            valid_static_method = "staticmethod" in decorators
            self.assertTrue(
                valid_instance_method or valid_static_method,
                f"{name} 會被 instance 綁定，但未宣告 self/cls 或 @staticmethod",
            )


if __name__ == "__main__":
    unittest.main()
