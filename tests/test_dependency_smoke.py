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
            "tifffile": "tifffile",
            "cv2": "opencv-python-headless",
        }
        self.assertTrue(
            set(expected.values()).issubset(declared),
            f"Missing runtime requirements for imports: {expected}; declared={sorted(declared)}",
        )
        self.assertNotIn("opencv-python", declared)
        self.assertNotIn("pytesseract", declared)

    def test_ocr_backend_is_an_explicit_optional_dependency(self) -> None:
        optional = (
            ROOT / "tools" / "ruler_scale_calibration_tester" / "requirements-ocr.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("pytesseract>=0.3.13,<1", optional)

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

    def test_calibration_and_root_app_import_without_pytesseract(self) -> None:
        statement = (
            "import builtins; real=builtins.__import__; "
            "builtins.__import__=lambda name,*a,**k: "
            "(_ for _ in ()).throw(ImportError('blocked')) if name=='pytesseract' "
            "else real(name,*a,**k); "
            "from gui.app import main; from core.calibration import CalibrationService"
        )
        completed = subprocess.run(
            [sys.executable, "-c", statement],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_root_ruler_launcher_is_single_source_of_truth(self) -> None:
        root_launcher = (ROOT / "run_ruler_scale_calibration_tester.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn('cd /d "%~dp0"', root_launcher)
        self.assertIn('.venv\\Scripts\\python.exe', root_launcher)
        self.assertIn('-m tools.ruler_scale_calibration_tester.main', root_launcher)
        self.assertIn('找不到 Luminescence_System 虛擬環境。', root_launcher)
        self.assertIn('請先執行 setup_and_run.bat 完成環境建立。', root_launcher)
        self.assertNotIn('pip install', root_launcher.casefold())
        forwarding = (
            ROOT / "tools" / "ruler_scale_calibration_tester" / "run_ruler_scale_tester.bat"
        ).read_text(encoding="utf-8")
        self.assertIn('run_ruler_scale_calibration_tester.bat', forwarding)
        self.assertNotIn('-m tools.ruler_scale_calibration_tester.main', forwarding)

    def test_setup_script_installs_only_from_requirements(self) -> None:
        script = (ROOT / "setup_and_run.bat").read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements.txt", script)
        self.assertNotRegex(script.casefold(), r"pip install[^\r\n]*opencv")


if __name__ == "__main__":
    unittest.main()
