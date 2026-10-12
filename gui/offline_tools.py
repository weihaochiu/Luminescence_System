from __future__ import annotations

"""Launch offline tools as independent processes, without acquisition ownership."""

from pathlib import Path
import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMessageBox

from core.i18n import tr


def open_offline_viewer(parent):
    root = Path(__file__).resolve().parents[1]
    started, _pid = QProcess.startDetached(sys.executable, ["-m", "standalone.hdr_viewer.main"], str(root))
    if not started:
        QMessageBox.warning(parent, tr("offline.launch_title"), tr("offline.launch_failed"))
