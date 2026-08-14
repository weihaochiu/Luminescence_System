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

    def test_removed_hdr_modules_and_runtime_imports_do_not_return(self) -> None:
        removed = {
            "auto_hdr.py", "hdr_output.py", "hdr_profile.py", "hdr_settings.py",
            "hdr_settings_dialog.py", "hdr_workflow.py",
        }
        self.assertTrue(all(not (self.package / name).exists() for name in removed))
        for path in self.package.glob("*.py"):
            if path.name == "recipe_store.py":
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = {
                alias.name.casefold()
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names
            }
            self.assertFalse(
                any("hdr" in name for name in imported),
                f"Removed HDR dependency imported by {path.name}: {sorted(imported)}",
            )

    def test_removed_hdr_ui_controls_do_not_return(self) -> None:
        recipe_source = (self.package / "recipe_dialog_pages.py").read_text(encoding="utf-8")
        main_source = (self.package / "main_window.py").read_text(encoding="utf-8")
        self.assertNotIn("hdr_enabled_check", recipe_source)
        self.assertNotIn("hdr_session_button", main_source)

    def test_architecture_and_requirement_documents_exist(self) -> None:
        docs = self.root / "docs"
        self.assertTrue((docs / "PROGRAM_ARCHITECTURE.md").is_file())
        requirements = (docs / "REQUIREMENTS_LOG.md").read_text(encoding="utf-8")
        self.assertIn("後續需求必須詳細記錄", requirements)
        self.assertIn("禁止為拆分而拆分", requirements)


if __name__ == "__main__":
    unittest.main()
