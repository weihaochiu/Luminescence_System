from __future__ import annotations

"""Local log snapshots and a background ZIP export action for Settings."""

from contextlib import ExitStack
from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory, mkstemp
import zipfile

from PySide6.QtCore import QObject, QRunnable, QStandardPaths, QThreadPool, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from core.i18n import i18n, tr


LOG = logging.getLogger(__name__)


class NoLogsError(RuntimeError):
    """There are no log files to export yet."""


def create_log_zip(log_directory: Path, destination: Path) -> int:
    """Snapshot logs, then atomically publish a ZIP without modifying originals.

    Hold active file-handler locks only while copying, so rotation cannot change
    files mid-snapshot. Compression runs after releasing the logging locks.
    Existing ZIP exports and links outside the log directory are excluded.
    """

    source = log_directory.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise NoLogsError()
    if destination.suffix.lower() != ".zip":
        raise ValueError("The log archive must have a .zip extension")

    archive_path: Path | None = None
    try:
        with TemporaryDirectory(prefix="luminescence-log-snapshot-") as temporary:
            snapshot = Path(temporary)
            with ExitStack() as locks:
                for handler in logging.getLogger().handlers:
                    if (isinstance(handler, logging.FileHandler)
                            and Path(handler.baseFilename).resolve().is_relative_to(source)):
                        handler.acquire()
                        locks.callback(handler.release)
                        handler.flush()
                files = sorted(
                    path for path in source.rglob("*")
                    if path.is_file() and not path.is_symlink()
                    and path.resolve().is_relative_to(source)
                    and path.suffix.lower() != ".zip"
                    and path.resolve() != destination
                )
                if not files:
                    raise NoLogsError()
                for path in files:
                    target = snapshot / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Bound the copy even when a temperature CSV is still growing.
                    with path.open("rb") as original, target.open("wb") as copied:
                        remaining = os.fstat(original.fileno()).st_size
                        while remaining > 0:
                            chunk = original.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                break
                            copied.write(chunk)
                            remaining -= len(chunk)
                    shutil.copystat(path, target)

            descriptor, name = mkstemp(
                prefix=".luminescence-logs-", suffix=".zip", dir=destination.parent,
            )
            os.close(descriptor)
            archive_path = Path(name)
            with zipfile.ZipFile(
                archive_path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False,
            ) as archive:
                for path in files:
                    relative = path.relative_to(source)
                    archive.write(snapshot / relative, (Path("logs") / relative).as_posix())
            os.replace(archive_path, destination)
            return len(files)
    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)


class _ExportSignals(QObject):
    completed = Signal(str, int)
    failed = Signal(str, bool)


class _ExportTask(QRunnable):
    def __init__(self, source: Path, destination: Path) -> None:
        super().__init__()
        self.source = source
        self.destination = destination
        self.signals = _ExportSignals()

    def run(self) -> None:
        try:
            count = create_log_zip(self.source, self.destination)
        except NoLogsError:
            self.signals.failed.emit("", True)
        except Exception as exc:
            LOG.exception("Log ZIP export failed")
            self.signals.failed.emit(str(exc), False)
        else:
            self.signals.completed.emit(str(self.destination), count)


class LogExportController(QObject):
    def __init__(self, window: QMainWindow, log_directory: Path) -> None:
        super().__init__(window)
        self.window = window
        self.log_directory = log_directory
        self._task: _ExportTask | None = None
        self.action = QAction(window)
        self.action.triggered.connect(self.choose_destination)
        window.settings_menu.addSeparator()
        window.settings_menu.addAction(self.action)
        i18n.language_changed.connect(self._retranslate)
        self._retranslate()

    @Slot()
    def _retranslate(self) -> None:
        self.action.setText(tr("logs.export_busy" if self._task else "logs.export"))
        self.action.setToolTip(tr("logs.export_tooltip"))

    @Slot()
    def choose_destination(self) -> None:
        if self._task is not None:
            return
        default_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation,
        ) or str(Path.home())
        directory = str(self.window.settings.value("logs/export_directory", default_directory))
        filename = f"luminescence_logs_{datetime.now():%Y%m%d_%H%M%S}.zip"
        selected, _filter = QFileDialog.getSaveFileName(
            self.window, tr("logs.export"), str(Path(directory) / filename),
            tr("logs.zip_filter"),
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_name(destination.name + ".zip")
            # The native save dialog checked the name without the added suffix.
            if destination.exists() and QMessageBox.question(
                self.window, tr("logs.export"),
                tr("logs.confirm_replace", path=str(destination)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
        self.window.settings.setValue("logs/export_directory", str(destination.parent))
        task = _ExportTask(self.log_directory, destination)
        task.signals.completed.connect(self._completed)
        task.signals.failed.connect(self._failed)
        self._task = task
        self.action.setEnabled(False)
        self._retranslate()
        self.window.status_message.setText(tr("logs.export_busy"))
        QThreadPool.globalInstance().start(task)

    def _finish(self) -> bool:
        self._task = None
        self.action.setEnabled(True)
        self._retranslate()
        # Do not reopen message boxes while the main window is shutting down.
        return not getattr(self.window, "_close_in_progress", False)

    @Slot(str, int)
    def _completed(self, path: str, count: int) -> None:
        if self._finish():
            message = tr("logs.export_complete", path=path, count=count)
            self.window.status_message.setText(message)
            QMessageBox.information(self.window, tr("logs.export"), message)

    @Slot(str, bool)
    def _failed(self, detail: str, empty: bool) -> None:
        if self._finish():
            message = tr("logs.no_logs") if empty else tr("logs.export_failed", detail=detail)
            self.window.status_message.setText(message)
            QMessageBox.warning(self.window, tr("logs.export"), message)
