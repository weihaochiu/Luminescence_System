"""Run with the supplied launcher or python -m tools.gsp4h_controller.main."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

if __package__ in (None, ""):
    # Supports launching this folder directly, without importing the main app.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from gsp4h_controller.window import LightControlWindow
else:
    from .window import LightControlWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("GSP4H Standalone Light Controller")
    app.setStyle("Fusion")
    window = LightControlWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
