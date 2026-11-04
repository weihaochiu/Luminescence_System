from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, get_ident
from time import monotonic, sleep
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QThreadPool, QTimer
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox

from core.i18n import Language, configure_i18n, set_language
from gui.log_export import LogExportController, NoLogsError, create_log_zip
from gui.main_window import MainWindow
from tests.qt_test_utils import ensure_qapplication


class LogArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.destination = self.root / "日誌.zip"

    def test_archive_contains_current_rotated_and_nested_temperature_logs(self) -> None:
        expected = {
            "luminescence_system.log": "目前日誌\n",
            "luminescence_system.log.1": "previous log\n",
            "camera_temperature_20261104.csv": "timestamp,temperature\nnow,20\n",
            "diagnostics/測試.json": '{"error": "AE"}',
        }
        for relative, content in expected.items():
            path = self.logs / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text(content, encoding="utf-8")
        original_bytes = {name: (self.logs / name).read_bytes() for name in expected}
        self.assertEqual(4, create_log_zip(self.logs, self.destination))
        with zipfile.ZipFile(self.destination) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual({"logs/" + name for name in expected}, set(archive.namelist()))
            for name, content in original_bytes.items():
                self.assertEqual(content, archive.read("logs/" + name))
        for name, content in expected.items():
            self.assertEqual(content, (self.logs / name).read_text(encoding="utf-8"))

    def test_missing_or_empty_logs_do_not_replace_existing_destination(self) -> None:
        self.destination.write_bytes(b"existing archive")
        for source in (self.logs, self.root / "missing"):
            with self.subTest(source=source), self.assertRaises(NoLogsError):
                create_log_zip(source, self.destination)
            self.assertEqual(b"existing archive", self.destination.read_bytes())

    def test_destination_inside_logs_excludes_all_previous_zip_exports(self) -> None:
        (self.logs / "current.log").write_text("current")
        (self.logs / "previous.ZIP").write_bytes(b"old")
        destination = self.logs / "selected.zip"
        destination.write_bytes(b"replace me")
        self.assertEqual(1, create_log_zip(self.logs, destination))
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(["logs/current.log"], archive.namelist())

    def test_compression_failure_preserves_destination_and_removes_partial_zip(self) -> None:
        (self.logs / "current.log").write_text("current")
        self.destination.write_bytes(b"existing archive")
        with patch("gui.log_export.zipfile.ZipFile.write", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                create_log_zip(self.logs, self.destination)
        self.assertEqual(b"existing archive", self.destination.read_bytes())
        self.assertEqual([], list(self.root.glob(".luminescence-logs-*")))
        self.assertEqual("current", (self.logs / "current.log").read_text())

    def test_active_logging_is_flushed_and_rotation_during_compression_is_safe(self) -> None:
        current = self.logs / "application.log"
        rotated = self.logs / "application.log.1"
        rotated.write_text("previous", encoding="utf-8")
        handler = RotatingFileHandler(current, backupCount=2, encoding="utf-8")
        logging.getLogger().addHandler(handler)
        self.addCleanup(handler.close)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        handler.stream.write("buffered current")
        original_write = zipfile.ZipFile.write
        rolled = False

        def write(archive, *args, **kwargs):
            nonlocal rolled
            if not rolled:
                rolled = True
                handler.doRollover()
            return original_write(archive, *args, **kwargs)

        with patch("gui.log_export.zipfile.ZipFile.write", new=write):
            create_log_zip(self.logs, self.destination)
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(b"buffered current", archive.read("logs/application.log"))
            self.assertEqual(b"previous", archive.read("logs/application.log.1"))
        self.assertEqual("buffered current", rotated.read_text())

    def test_symlink_to_non_log_file_is_excluded(self) -> None:
        private = self.root / "outside.txt"
        private.write_text("not a log")
        try:
            (self.logs / "link.log").symlink_to(private)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this Windows installation")
        (self.logs / "current.log").write_text("current")
        self.assertEqual(1, create_log_zip(self.logs, self.destination))
        with zipfile.ZipFile(self.destination) as archive:
            self.assertNotIn("logs/link.log", archive.namelist())


class LogExportGUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_qapplication()

    def setUp(self) -> None:
        configure_i18n(None)
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.window = QMainWindow()
        self.window.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.window.settings_menu = self.window.menuBar().addMenu("Settings")
        self.window.status_message = QLabel(self.window)
        self.controller = LogExportController(self.window, self.logs)
        self.addCleanup(self.window.close)
        self.addCleanup(configure_i18n, None)

    def _wait_finished(self) -> None:
        deadline = monotonic() + 5
        while self.controller._task is not None and monotonic() < deadline:
            self.app.processEvents()
            sleep(0.005)
        self.assertIsNone(self.controller._task)
        self.assertTrue(self.controller.action.isEnabled())

    def test_cancel_save_dialog_creates_no_archive_or_worker(self) -> None:
        with patch("gui.log_export.QFileDialog.getSaveFileName", return_value=("", "")):
            self.controller.action.trigger()
        self.assertIsNone(self.controller._task)
        self.assertTrue(self.controller.action.isEnabled())
        self.assertEqual([], list(self.root.glob("*.zip")))
        self.assertIsNone(self.window.settings.value("logs/export_directory"))

    def test_export_runs_off_gui_thread_and_remembers_selected_destination(self) -> None:
        (self.logs / "current.log").write_text("AE diagnostics")
        destination = self.root / "自訂檔名"
        entered, release = Event(), Event()
        thread_ids = []

        def delayed_export(source, path):
            thread_ids.append(get_ident())
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test worker was not released")
            return create_log_zip(source, path)

        with patch("gui.log_export.QFileDialog.getSaveFileName", return_value=(str(destination), "")), patch(
            "gui.log_export.create_log_zip", side_effect=delayed_export,
        ), patch("gui.log_export.QMessageBox.information") as complete:
            try:
                self.controller.action.trigger()
                self.assertFalse(self.controller.action.isEnabled())
                self.assertTrue(entered.wait(2))
                self.assertNotEqual(get_ident(), thread_ids[0])
                timer_fired = []
                QTimer.singleShot(0, lambda: timer_fired.append(True))
                self.app.processEvents()
                self.assertEqual([True], timer_fired)
            finally:
                release.set()
                QThreadPool.globalInstance().waitForDone(5000)
            self._wait_finished()
            complete.assert_called_once()
            self.assertIn(str(destination) + ".zip", complete.call_args.args[2])
        with zipfile.ZipFile(str(destination) + ".zip") as archive:
            self.assertEqual(b"AE diagnostics", archive.read("logs/current.log"))
        self.assertEqual(str(self.root), self.window.settings.value("logs/export_directory"))

    def test_added_zip_suffix_does_not_silently_overwrite_existing_archive(self) -> None:
        destination = self.root / "existing.zip"
        destination.write_bytes(b"keep me")
        with patch("gui.log_export.QFileDialog.getSaveFileName", return_value=(str(destination.with_suffix("")), "")), patch(
            "gui.log_export.QMessageBox.question", return_value=QMessageBox.StandardButton.No,
        ) as question:
            self.controller.action.trigger()
        question.assert_called_once()
        self.assertIsNone(self.controller._task)
        self.assertEqual(b"keep me", destination.read_bytes())

    def test_empty_logs_show_a_clear_message_and_no_empty_zip(self) -> None:
        destination = self.root / "empty.zip"
        with patch("gui.log_export.QFileDialog.getSaveFileName", return_value=(str(destination), "")), patch(
            "gui.log_export.QMessageBox.warning",
        ) as warning:
            self.controller.action.trigger()
            self._wait_finished()
            warning.assert_called_once()
            self.assertIn("沒有可匯出", warning.call_args.args[2])
        self.assertFalse(destination.exists())

    def test_write_failure_is_reported_and_action_becomes_available_again(self) -> None:
        (self.logs / "current.log").write_text("current")
        destination = self.root / "unavailable" / "result.zip"
        with patch("gui.log_export.QFileDialog.getSaveFileName", return_value=(str(destination), "")), patch(
            "gui.log_export.QMessageBox.warning",
        ) as warning:
            self.controller.action.trigger()
            self._wait_finished()
            warning.assert_called_once()
            self.assertIn("無法匯出", warning.call_args.args[2])
        self.assertEqual("current", (self.logs / "current.log").read_text())

    def test_finishing_during_application_close_does_not_reopen_a_dialog(self) -> None:
        (self.logs / "current.log").write_text("current")
        destination = self.root / "result.zip"
        with patch("gui.log_export.QFileDialog.getSaveFileName", return_value=(str(destination), "")), patch(
            "gui.log_export.QMessageBox.information",
        ) as message:
            self.controller.action.trigger()
            self.window._close_in_progress = True
            self._wait_finished()
            message.assert_not_called()
        self.assertTrue(destination.is_file())

    def test_menu_action_retranslates_and_main_window_uses_application_log_directory(self) -> None:
        self.assertIn(self.controller.action, self.window.settings_menu.actions())
        self.assertEqual("匯出日誌 ZIP…", self.controller.action.text())
        set_language(Language.EN_US, persist=False)
        self.assertEqual("Export Logs as ZIP…", self.controller.action.text())
        set_language(Language.ZH_TW, persist=False)
        with patch("gui.main_window.QSettings", return_value=self.window.settings), patch(
            "gui.main_window.QStandardPaths.writableLocation", return_value=str(self.root),
        ), patch("gui.main_window.QTimer.singleShot"):
            main_window = MainWindow()
        try:
            self.assertIn(main_window.log_export.action, main_window.settings_menu.actions())
            self.assertEqual(self.logs, main_window.log_export.log_directory)
        finally:
            main_window.close()


if __name__ == "__main__":
    unittest.main()
