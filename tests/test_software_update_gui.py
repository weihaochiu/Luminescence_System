from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox
from core.i18n import Language, configure_i18n, set_language
from core.release_info import load_history
from core.software_update import UpdateOffer, atomic_json, PENDING_RECORD, INSTALL_RECORD
from gui import __version__
from gui.main_window import MainWindow
from gui.software_update import SoftwareUpdateDialog, operation_active, launch_installer, notify_update_startup
from tests.qt_test_utils import ensure_qapplication
from tests.test_close_safety import FakeCloseEvent, close_fixture


class UpdateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_qapplication()

    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)
        settings = QSettings(str(Path(self.runtime.name) / "settings.ini"), QSettings.IniFormat)
        with patch("gui.main_window.QSettings", return_value=settings), patch(
            "gui.main_window.QStandardPaths.writableLocation", return_value=self.runtime.name
        ), patch("gui.main_window.QTimer.singleShot"):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.addCleanup(setattr, self.window, "_pending_software_update", None)
        self.addCleanup(configure_i18n, None)

    def offer(self):
        return UpdateOffer("a" * 40, [
            {"version": "1.12.0", "date": "2026-11-14", "changes": {
                "zh-TW": ["修正新版行為"], "en-US": ["Fix new behavior"]}},
            {"version": "1.11.0", "date": "2026-11-13", "changes": {
                "zh-TW": ["增加前版功能"], "en-US": ["Add earlier feature"]}},
        ])

    def test_menu_and_about_display_real_version_and_operator_changes(self):
        self.assertIn(self.window.update_action, self.window.help_menu.actions())
        self.assertIn(__version__, self.window.windowTitle())
        with patch("gui.main_window.QMessageBox.about") as about:
            self.window.show_about()
        self.assertIn(__version__, about.call_args.args[2])
        current_release = load_history()[0]
        for change in current_release["changes"]["zh-TW"]:
            self.assertIn(change, about.call_args.args[2])
        set_language(Language.EN_US, persist=False)
        self.assertIn("Check for Updates", self.window.update_action.text())
        with patch("gui.main_window.QMessageBox.about") as about:
            self.window.show_about()
        for change in current_release["changes"]["en-US"]:
            self.assertIn(change, about.call_args.args[2])

    def test_new_version_displays_all_intervening_notes_and_retranslates(self):
        dialog = SoftwareUpdateDialog(self.window)
        dialog.checked(self.offer())
        self.assertTrue(dialog.install_button.isEnabled())
        self.assertIn("1.12.0", dialog.status.text())
        self.assertIn("修正新版行為", dialog.notes.toPlainText())
        self.assertIn("增加前版功能", dialog.notes.toPlainText())
        set_language(Language.EN_US, persist=False)
        self.assertIn("Fix new behavior", dialog.notes.toPlainText())
        self.assertIn("Add earlier feature", dialog.notes.toPlainText())
        dialog.close()

    def test_current_or_older_version_never_enables_install(self):
        dialog = SoftwareUpdateDialog(self.window)
        offer = self.offer()
        offer.releases[0]["version"] = __version__
        dialog.checked(offer)
        self.assertFalse(dialog.install_button.isEnabled())
        dialog.close()

    def test_busy_operation_blocks_download_and_install(self):
        dialog = SoftwareUpdateDialog(self.window)
        dialog.checked(self.offer())
        self.window._measurement_thread = object()
        with patch("gui.software_update.QMessageBox.warning") as warning, patch.object(dialog, "_start") as start:
            dialog.install()
        warning.assert_called_once()
        start.assert_not_called()
        self.window._measurement_thread = None
        self.window._pending_auto_path = "capture.tiff"
        self.assertTrue(operation_active(self.window))
        self.window._pending_auto_path = None
        self.assertFalse(operation_active(self.window))
        dialog.close()

    def test_prepared_update_requires_explicit_restart_confirmation(self):
        dialog = SoftwareUpdateDialog(self.window)
        dialog.checked(self.offer())
        job = Path(self.runtime.name) / "job.json"
        dialog.prepared(job)
        with patch("gui.software_update.QMessageBox.question", return_value=QMessageBox.Cancel):
            dialog.install()
        self.assertIsNone(self.window._pending_software_update)
        with patch("gui.software_update.QMessageBox.question", return_value=QMessageBox.Yes), patch(
            "gui.software_update.QTimer.singleShot"
        ) as schedule:
            dialog.install()
        self.assertEqual(job, self.window._pending_software_update)
        schedule.assert_called_once()
        self.window._pending_software_update = None

    def test_network_failure_is_retryable_and_does_not_offer_install_without_metadata(self):
        dialog = SoftwareUpdateDialog(self.window)
        dialog.failed("network", "HTTP 429")
        self.assertTrue(dialog.check_button.isEnabled())
        self.assertFalse(dialog.install_button.isEnabled())
        self.assertIn("HTTP 429", dialog.notes.toPlainText())
        self.assertEqual("SYS-201", self.window.error_reporter.history()[-1].code)
        dialog.close()

    def test_handoff_backs_up_settings_and_authorizes_only_started_installer(self):
        root = Path(self.runtime.name) / "equipment"
        root.mkdir()
        work = Path(self.runtime.name) / "job"
        work.mkdir()
        job_path = work / "job.json"
        atomic_json(job_path, {"root": str(root), "parent_pid": os.getpid(), "token": "test-token"})
        self.window._pending_software_update = job_path
        with patch("gui.software_update.ROOT", root), patch(
            "gui.software_update.subprocess.Popen", return_value=SimpleNamespace(pid=123)
        ):
            launch_installer(self.window)
        import json
        record = json.loads((root / PENDING_RECORD).read_text())
        self.assertTrue(record["authorized"])
        self.assertEqual(123, record["installer_pid"])
        self.assertTrue((work / "settings.ini").exists())
        with patch("gui.software_update.ROOT", root), patch(
            "gui.software_update.subprocess.Popen", side_effect=OSError("Cannot start")
        ):
            with self.assertRaises(OSError):
                launch_installer(self.window)
        self.assertFalse((root / PENDING_RECORD).exists())
        self.window._pending_software_update = None

    def test_startup_acknowledgement_waits_for_result_before_unlocking_gui(self):
        root = Path(self.runtime.name) / "equipment"
        root.mkdir()
        work = Path(self.runtime.name) / "job"
        work.mkdir()
        atomic_json(root / INSTALL_RECORD, {"sha": "a" * 40})
        atomic_json(work / "job.json", {"root": str(root), "token": "test-token",
                                        "version": __version__, "sha": "a" * 40})
        with patch("gui.software_update.ROOT", root), patch.dict(os.environ, {
            "LUMINESCENCE_UPDATE_JOB": str(work / "job.json"),
            "LUMINESCENCE_UPDATE_TOKEN": "test-token",
            "LUMINESCENCE_UPDATE_RESULT": str(work / "result.json"),
        }):
            notify_update_startup(self.window)
            self.assertFalse(self.window.isEnabled())
            self.app.processEvents()
            self.assertTrue((work / "health.json").exists())
            atomic_json(work / "result.json", {"status": "success"})
            with patch("gui.software_update.QMessageBox.information") as message:
                self.window._update_result_timer.timeout.emit()
            self.assertTrue(self.window.isEnabled())
            self.assertIn(__version__, message.call_args.args[2])

    def test_busy_dialog_cannot_be_closed_or_rejected(self):
        dialog = SoftwareUpdateDialog(self.window)
        dialog.show()
        dialog.busy = True
        self.assertFalse(dialog.close())
        dialog.reject()
        self.assertTrue(dialog.isVisible())
        dialog.busy = False
        dialog.close()

    def test_updated_startup_schedules_no_hardware_autoconnections(self):
        with patch.dict(os.environ, {"LUMINESCENCE_SKIP_AUTOCONNECT": "1"}), patch(
            "gui.main_window.QTimer.singleShot"
        ) as schedule, patch("gui.main_window.QSettings", return_value=self.window.settings), patch(
            "gui.main_window.QStandardPaths.writableLocation", return_value=self.runtime.name
        ):
            window = MainWindow()
        try:
            callbacks = [getattr(call.args[1], "__name__", "") for call in schedule.call_args_list]
            self.assertFalse(set(callbacks) & {"refresh_devices", "auto_connect_smu_on_startup",
                                              "refresh_relay_connection", "auto_connect"})
        finally:
            window.close()


class UpdateCloseSafetyTests(unittest.TestCase):
    def fixture(self, confirmations):
        window, events = close_fixture(confirmations)
        window._pending_software_update = Path("job.json")
        window.relay_controller = SimpleNamespace(connected=True, last_raw_status=[0])
        window.relay_service.shutdown = lambda: events.append("RELAY_SHUTDOWN") or True
        window._unsafe_smu_close_decision = Mock(return_value="force")
        window._confirm_forced_close = Mock(return_value=True)
        return window, events

    def test_unknown_smu_output_cannot_force_update(self):
        window, _events = self.fixture([False])
        event = FakeCloseEvent()
        with patch("gui.software_update.operation_active", return_value=False), patch(
            "gui.main_window_close.QMessageBox.warning"
        ), patch("gui.software_update.launch_installer") as launch:
            MainWindow.closeEvent(window, event)
        self.assertFalse(event.accepted)
        self.assertIsNone(window._pending_software_update)
        window._unsafe_smu_close_decision.assert_not_called()
        launch.assert_not_called()

    def test_failed_relay_shutdown_cancels_update(self):
        window, _events = self.fixture([True])
        window.relay_service.shutdown = Mock(return_value=False)
        event = FakeCloseEvent()
        with patch("gui.software_update.operation_active", return_value=False), patch(
            "gui.main_window_close.QMessageBox.warning"
        ), patch("gui.software_update.launch_installer") as launch:
            MainWindow.closeEvent(window, event)
        self.assertFalse(event.accepted)
        launch.assert_not_called()

    def test_verified_shutdown_starts_installer_only_after_camera_close(self):
        window, events = self.fixture([True])
        event = FakeCloseEvent()
        with patch("gui.software_update.operation_active", return_value=False), patch(
            "gui.software_update.launch_installer", side_effect=lambda _window: events.append("INSTALLER")
        ):
            MainWindow.closeEvent(window, event)
        self.assertTrue(event.accepted)
        self.assertLess(events.index("CAMERA_CLOSE"), events.index("INSTALLER"))

    def test_busy_recheck_at_close_prevents_installation(self):
        window, events = self.fixture([True])
        event = FakeCloseEvent()
        with patch("gui.software_update.operation_active", return_value=True), patch(
            "gui.main_window_close.QMessageBox.warning"
        ), patch("gui.software_update.launch_installer") as launch:
            MainWindow.closeEvent(window, event)
        self.assertFalse(event.accepted)
        self.assertNotIn("SMU_CONFIRM_OFF", events)
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
