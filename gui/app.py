import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import hashlib

from PySide6.QtCore import QCoreApplication, QLockFile, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox
from core.i18n import tr
from core.release_info import ROOT

from .main_window import MainWindow


def _configure_logging() -> None:
    app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    log_directory = (Path(app_data) if app_data else Path.cwd()) / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_directory / "luminescence_system.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(item, RotatingFileHandler) for item in root.handlers):
        root.addHandler(handler)


def main() -> int:
    QCoreApplication.setOrganizationName("EL Measurement Lab")
    QCoreApplication.setApplicationName("EL Measurement Equipment Control")

    app = QApplication(sys.argv)
    data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    data.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(str(ROOT).casefold().encode("utf-8")).hexdigest()[:16]
    instance_lock = QLockFile(str(data / f"instance-{identity}.lock"))
    if not instance_lock.tryLock(0):
        QMessageBox.information(None, tr("update.title"), tr("update.error.instance"))
        return 1
    app.setStyle("Fusion")
    _configure_logging()
    window = MainWindow()
    window.show()
    from .software_update import notify_update_startup
    notify_update_startup(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
