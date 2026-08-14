from __future__ import annotations

import ast
import unittest
from pathlib import Path


class ModularArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).parents[1]
        cls.package = cls.root / "gui"

    def test_public_entry_modules_remain_small_coordinators(self) -> None:
        limits = {
            "main_window.py": 340,
            "recipe_dialog.py": 220,
            "auto_hdr.py": 600,
        }
        for name, maximum in limits.items():
            with self.subTest(module=name):
                line_count = len((self.package / name).read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(line_count, maximum)

    def test_main_window_retains_stable_public_class(self) -> None:
        tree = ast.parse((self.package / "main_window.py").read_text(encoding="utf-8"))
        main_window = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )
        bases = {
            base.id for base in main_window.bases if isinstance(base, ast.Name)
        }
        self.assertEqual(
            {"MainWindowUIMixin", "MainWindowDeviceMixin", "QMainWindow"},
            bases,
        )

    def test_recipe_dialog_uses_four_page_binding_and_shared_plan_modules(self) -> None:
        expected = {
            "recipe_dialog_pages.py",
            "recipe_dialog_logic.py",
            "measurement_execution_plan.py",
        }
        self.assertTrue(all((self.package / name).is_file() for name in expected))
        self.assertFalse((self.package / "recipe_dialog_points.py").exists())

    def test_hdr_output_keeps_legacy_import_path(self) -> None:
        source = (self.package / "auto_hdr.py").read_text(encoding="utf-8")
        self.assertIn(
            "from .hdr_output import save_hdr_capture_set, save_hdr_products",
            source,
        )

    def test_architecture_and_requirement_documents_exist(self) -> None:
        docs = self.root / "docs"
        self.assertTrue((docs / "PROGRAM_ARCHITECTURE.md").is_file())
        requirements = (docs / "REQUIREMENTS_LOG.md").read_text(encoding="utf-8")
        self.assertIn("後續需求必須詳細記錄", requirements)
        self.assertIn("禁止為拆分而拆分", requirements)


if __name__ == "__main__":
    unittest.main()
