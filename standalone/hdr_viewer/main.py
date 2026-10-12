from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from core.i18n import configure_i18n
from .window import HDRViewerWindow


def main() -> int:
    app = QApplication(sys.argv)
    QCoreApplication.setOrganizationName("EL Measurement Lab")
    QCoreApplication.setApplicationName("Offline HDR Viewer")
    configure_i18n(QSettings("EL Measurement Lab", "EL Measurement Equipment Control"))
    app.setStyle("Fusion")
    window = HDRViewerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
