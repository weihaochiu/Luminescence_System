from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _declared_requirements() -> set[str]:
    names: set[str] = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", line)
        if match:
            names.add(match.group(1).casefold())
    return names


class DependencySmokeTests(unittest.TestCase):
    def test_direct_runtime_imports_have_declared_distributions(self) -> None:
        declared = _declared_requirements()
        expected = {
            "PySide6": "pyside6",
            "numpy": "numpy",
            "PIL": "pillow",
            "pyvisa": "pyvisa",
            "hid": "hidapi",
            "cv2": "opencv-python-headless",
        }
        self.assertTrue(
            set(expected.values()).issubset(declared),
            f"Missing runtime requirements for imports: {expected}; declared={sorted(declared)}",
        )
        self.assertNotIn("opencv-python", declared)

    def test_application_import_smoke_commands(self) -> None:
        for statement in ("from gui.app import main", "import gui.measurement_output"):
            with self.subTest(statement=statement):
                completed = subprocess.run(
                    [sys.executable, "-c", statement],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)

    def test_setup_script_installs_only_from_requirements(self) -> None:
        script = (ROOT / "setup_and_run.bat").read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements.txt", script)
        self.assertNotRegex(script.casefold(), r"pip install[^\r\n]*opencv")


if __name__ == "__main__":
    unittest.main()
