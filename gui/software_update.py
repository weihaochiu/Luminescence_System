"""Operator update dialog and safe-exit handoff; filesystem/network work stays off Qt."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
import zipfile

from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from core.i18n import i18n, tr
from core.release_info import ROOT, format_changes, load_history, version_tuple
from core.software_update import (
    PENDING_RECORD, UpdateError, UpdateOffer, atomic_json, check_latest,
    installed_sha, prepare_update, read_json,
)
from . import __version__

LOG = logging.getLogger(__name__)


def operation_active(window) -> bool:
    control = window.smu_manager.control
    return bool(
        getattr(window, "_measurement_thread", None) is not None
        or getattr(window, "_measurement_worker", None) is not None
        or getattr(window, "_measurement_starting", False)
        or getattr(window, "_capture_next_frame", False)
        or getattr(window, "_pending_auto_path", None)
        or getattr(window.controller, "_ae_calibration_run", None) is not None
        or getattr(control, "is_busy", False)
        or getattr(control.ownership, "value", control.ownership) != "IDLE"
    )


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(str, str)
    progress = Signal(str, int)


class _Task(QRunnable):
    def __init__(self, function) -> None:
        super().__init__()
        self.signals = _Signals()
        self.function = function

    def run(self) -> None:
        try:
            self.signals.completed.emit(self.function(self.signals.progress.emit))
        except Exception as exc:
            LOG.exception("Software update task failed")
            if isinstance(exc, UpdateError):
                reason = exc.reason
            elif isinstance(exc, URLError):
                reason = "network"
            elif isinstance(exc, subprocess.TimeoutExpired):
                reason = "dependencies"
            elif isinstance(exc, (zipfile.BadZipFile, ValueError, KeyError, SyntaxError)):
                reason = "invalid_package"
            elif isinstance(exc, OSError):
                reason = "filesystem"
            else:
                reason = "invalid_package"
            self.signals.failed.emit(reason, str(exc))


class SoftwareUpdateDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.offer: UpdateOffer | None = None
        self.job: Path | None = None
        self.busy = False
        self.setWindowTitle(tr("update.title"))
        self.resize(700, 560)
        layout = QVBoxLayout(self)
        self.current = QLabel(self)
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.notes = QTextBrowser(self)
        self.notes.setPlainText(format_changes(load_history()[:1], i18n.language.value))
        layout.addWidget(self.notes)
        self.progress = QProgressBar(self)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.buttons = QDialogButtonBox(self)
        self.check_button = QPushButton(tr("update.check"), self)
        self.install_button = QPushButton(tr("update.install"), self)
        self.close_button = QPushButton(tr("common.close"), self)
        self.buttons.addButton(self.check_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.install_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.close_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(self.buttons)
        self.check_button.clicked.connect(self.check)
        self.install_button.clicked.connect(self.install)
        self.buttons.rejected.connect(self.reject)
        self.install_button.setEnabled(False)
        i18n.language_changed.connect(self.retranslate)
        self.retranslate()

    def retranslate(self, _language: str = "") -> None:
        self.setWindowTitle(tr("update.title"))
        self.current.setText(tr("update.current", version=__version__,
                                commit=(installed_sha(ROOT) or tr("update.unknown_commit"))[:40]))
        self.check_button.setText(tr("update.check"))
        self.install_button.setText(tr("update.restart" if self.job else "update.install"))
        self.close_button.setText(tr("common.close"))
        if self.offer:
            self.render_offer()
        else:
            self.notes.setPlainText(format_changes(load_history()[:1], i18n.language.value))

    def _start(self, function, completed) -> None:
        self.busy = True
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress.show()
        self.progress.setRange(0, 0)
        self.task = _Task(function)
        self.task.signals.completed.connect(completed)
        self.task.signals.failed.connect(self.failed)
        self.task.signals.progress.connect(self.on_progress)
        QThreadPool.globalInstance().start(self.task)

    def _idle(self) -> None:
        self.busy = False
        self.check_button.setEnabled(self.job is None)
        self.close_button.setEnabled(True)
        self.progress.hide()

    def check(self) -> None:
        if self.busy:
            return
        self.status.setText(tr("update.checking"))
        self._start(lambda _progress: check_latest(), self.checked)

    def checked(self, offer: UpdateOffer) -> None:
        self._idle()
        self.offer = offer
        self.render_offer()

    def render_offer(self) -> None:
        if self.offer is None:
            return
        newer = version_tuple(self.offer.version) > version_tuple(__version__)
        self.status.setText(tr("update.available" if newer else "update.up_to_date",
                               version=self.offer.version))
        self.notes.setPlainText(format_changes(self.offer.releases, i18n.language.value,
                                              after=__version__ if newer else None))
        self.install_button.setEnabled(newer and not self.busy)

    def install(self) -> None:
        if self.busy or not self.offer:
            return
        if operation_active(self.window):
            QMessageBox.warning(self, tr("update.title"), tr("update.busy"))
            return
        if self.job:
            answer = QMessageBox.question(self, tr("update.title"), tr("update.confirm_restart"),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.window._pending_software_update = self.job
            self.accept()
            QTimer.singleShot(0, self.window.close)
            return
        self.status.setText(tr("update.download"))
        self._start(lambda progress: prepare_update(ROOT, self.window.application_directory,
                                                     self.offer, progress), self.prepared)

    def prepared(self, job: Path) -> None:
        self._idle()
        self.job = job
        self.status.setText(tr("update.ready"))
        self.install_button.setText(tr("update.restart"))
        self.install_button.setEnabled(True)

    def on_progress(self, phase: str, value: int) -> None:
        self.status.setText(tr(f"update.{phase}"))
        self.progress.setRange(0, 100 if value >= 0 else 0)
        if value >= 0:
            self.progress.setValue(value)

    def failed(self, reason: str, detail: str) -> None:
        self._idle()
        key = f"update.error.{reason}"
        explanation = tr(key)
        if explanation == f"[{key}]":
            key = "update.error.network"
            explanation = tr(key)
        self.window.report_error("SYS-201", present=False, message_key=key,
                                 context={"operation": "software_update", "actual": detail})
        self.status.setText(explanation)
        self.notes.setPlainText(explanation + "\n\n" + detail)
        if self.offer:
            self.install_button.setEnabled(version_tuple(self.offer.version) > version_tuple(__version__))

    def reject(self) -> None:
        if not self.busy:
            super().reject()

    def closeEvent(self, event) -> None:
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)


def open_update_dialog(window) -> None:
    if operation_active(window):
        QMessageBox.information(window, tr("update.title"), tr("update.busy"))
        return
    dialog = SoftwareUpdateDialog(window)
    dialog.check()
    dialog.exec()


def launch_installer(window) -> None:
    """Called only after successful, verified normal shutdown, never forced exit."""
    job_path = Path(window._pending_software_update).resolve()
    job = read_json(job_path)
    if Path(job["root"]).resolve() != ROOT or job["parent_pid"] != os.getpid():
        raise UpdateError("invalid_package", "Invalid installer handoff")
    window.settings.sync()
    if window.settings.status() != QSettings.Status.NoError:
        raise UpdateError("settings")
    backup = QSettings(str(job_path.parent / "settings.ini"), QSettings.Format.IniFormat)
    backup.setValue("__update_backup_format__", 1)
    for key in window.settings.allKeys():
        backup.setValue(key, window.settings.value(key))
    backup.sync()
    if backup.status() != QSettings.Status.NoError:
        raise UpdateError("settings")
    pending = ROOT / PENDING_RECORD
    atomic_json(pending, {"job": str(job_path), "token": job["token"]})
    try:
        process = subprocess.Popen([sys.executable, "-m", "core.update_runner", "--job", str(job_path)],
                         cwd=job_path.parent / "helper", close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        atomic_json(pending, {"job": str(job_path), "token": job["token"],
                              "installer_pid": process.pid, "authorized": True})
    except Exception:
        pending.unlink(missing_ok=True)
        raise


def notify_update_startup(window) -> None:
    result_path = os.environ.pop("LUMINESCENCE_UPDATE_RESULT", "")
    job_path = os.environ.pop("LUMINESCENCE_UPDATE_JOB", "")
    token = os.environ.pop("LUMINESCENCE_UPDATE_TOKEN", "")
    if not result_path:
        return
    if job_path:
        job = read_json(Path(job_path))
        if (job["token"] != token or Path(job["root"]).resolve() != ROOT
                or job["version"] != __version__ or installed_sha(ROOT) != job["sha"]):
            raise UpdateError("startup_failed", "Invalid startup acknowledgement")
        window.setEnabled(False)
        QTimer.singleShot(0, lambda: atomic_json(Path(job_path).parent / "health.json", {"token": token}))
    timer = QTimer(window)
    window._update_result_timer = timer
    timer.setInterval(250)
    deadline = time.monotonic() + 90

    def poll() -> None:
        path = Path(result_path)
        if not path.exists():
            if time.monotonic() > deadline:
                timer.stop()
                QMessageBox.warning(window, tr("update.title"), tr("update.error.confirmation"))
                window.close()
            return
        timer.stop()
        result = read_json(path)
        window.setEnabled(True)
        message = tr("update.finished" if result["status"] == "success" else "update.restored",
                     version=__version__)
        message += "\n\n" + format_changes(load_history()[:1], i18n.language.value)
        message += "\n\n" + tr("update.log_path", path=str(path.parent))
        QMessageBox.information(window, tr("update.title"), message)

    timer.timeout.connect(poll)
    timer.start()
