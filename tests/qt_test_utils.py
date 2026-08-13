from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


_application: QApplication | None = None


def ensure_qapplication() -> QApplication:
    """Return the process QApplication, creating and retaining it if needed."""

    global _application

    existing = QCoreApplication.instance()
    if existing is None:
        existing = QApplication([])
    if not isinstance(existing, QApplication):
        raise RuntimeError(
            "Qt tests require QApplication, but a non-GUI application already exists"
        )

    _application = existing
    return existing
