from __future__ import annotations

import sys
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication
from core.i18n import configure_i18n
from gui.app import _configure_logging
from .window import LightLinearityWindow


def main() -> int:
    QCoreApplication.setOrganizationName("EL Measurement Lab")
    QCoreApplication.setApplicationName("GSP4H Light Linearity Qualification")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _configure_logging()
    configure_i18n(QSettings("EL Measurement Lab", "EL Measurement Equipment Control"))
    window = LightLinearityWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
