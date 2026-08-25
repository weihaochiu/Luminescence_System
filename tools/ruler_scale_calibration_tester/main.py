from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from gui.app import _configure_logging
from core.i18n import configure_i18n

from .window import RulerScaleTesterWindow


def main() -> int:
    QCoreApplication.setOrganizationName("EL Measurement Lab")
    QCoreApplication.setApplicationName("Ruler Scale Calibration Tester")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _configure_logging()
    configure_i18n(QSettings("EL Measurement Lab", "EL Measurement Equipment Control"))
    window = RulerScaleTesterWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
